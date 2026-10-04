"""{{MARKER}}. Se sobrescribe cada vez que corres setup.sh.

Model-free Telegram handlers of Vinci and its subject bots, answering only the captain:

- Inline buttons (callback data `v1:...`): run `espol-bot boton <data>`, which queues a
  handoff, saves or discards a schedule proposal or a grading scheme, creates / archives a subject
  bot, marks an assignment as handed in or closes a to-do (the pressed button then turns into its undo), or
  hands in to the aula the PDF a subject bot built from the captain's photos.
- A bot created for Vinci to manage (`managed_bot_created`): run `espol-bot bot-creado <id>`,
  which fetches its token from Telegram and provisions it.
- Any message carrying a bot token (for example BotFather's reply, forwarded): delete it
  from the chat and hand the token to `espol-bot token` on stdin.
- /start: Hermes ignores it, so the bot greets with `espol-bot saludo` (who it is, and for a
  subject bot when its next brief comes). In Vinci's chat, `/start s_<id>_ok` (or `t_…`, `…_no`) is a tick
  on the dashboard behind the menu button: the page opened Vinci's deep link. It runs as the
  «✅ Ya lo entregué» / «✅ Hecho» button would (`espol-bot boton v1:s:<id>:ok`), and the /start is deleted.
- The captain's vote in a subject bot's quiz poll (`poll_answer`): run `espol-bot quiz-respuesta`,
  which records it and, after the quiz's last question, answers the score to send.
- /estado, in Vinci's chat: the system health from `espol-bot estado` (last poll and sync, token
  chain, feeds), without waking the model.
- /token, in Vinci's chat: `espol-bot canvas-form` answers with a Mini App keyboard button whose page
  encrypts a new Canvas token on the phone; the button's web_app_data (only ciphertext) goes to
  `espol-bot canvas-submit` on stdin, which decrypts it and reseeds the token chain.
- A Canvas token pasted in any bot's chat: deleted and never used; Vinci answers with the /token form.
- The `/` menu in the captain's chat: this bot's own commands (/estado, /token, /quiz) first, then Hermes's.

Every answer that cites the material goes through `espol-bot citas` before it is sent (hook
transform_llm_output): a citation of a page the bot was never shown becomes a warning, and a missing or
wrong aula link is set right. If the check fails, the answer goes as it is.

A subject bot also gets the tools `ver_pagina` and `ver_foto` (toolset vinci-paginas): a page of one of its
own downloaded PDFs (`espol-bot pagina`), or a photo of its notebook (`espol-bot foto`: a board photo, a
capture from the captain's notes), handed to the model as an image. A scanned book has next to no text, and
an MCP tool's image reaches the model only as a file path.

These run in group -100, before every Hermes handler, and stop the update there
(ApplicationHandlerStop): a token or a bot-creation message never becomes a Hermes
event, so it never reaches the model or a session log.
"""

import asyncio
import html
import json
import logging
import os
import re
import subprocess

logger = logging.getLogger("vinci-botones")

BOT = "{{BOT}}"
CAPTAIN = "{{USER_ID}}"
ENV = {"AULA_CONFIG": "{{CONFIG}}", "AULA_SECRETS": "{{SECRETS}}", "HERMES_BIN": "{{HERMES}}"}
SUBJECT = "{{CODIGO}}"  # this bot's subject code; empty for Vinci
PATTERN = r"^v1:"
TOKEN_RE = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{30,}\b")
# ESPOL's aula tokens are 64 letters (both cases) and digits; stock Canvas prefixes "<digits>~". Mixed case keeps
# a pasted lowercase hex hash from counting as one.
CANVAS_TOKEN_RE = re.compile(r"\b(?:\d{1,6}~)?(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*\d)"
                             r"[A-Za-z0-9]{64}\b")
START_RE = re.compile(r"^/start(?:@\w+)?(?:\s|$)")
TICK_RE = re.compile(r"^/start(?:@\w+)?\s+([st])_(-?\d{1,20})_(ok|no)\s*$")  # a tick on the dashboard
STATUS_RE = re.compile(r"^/estado(?:@\w+)?(?:\s|$)")
FORM_RE = re.compile(r"^/token(?:@\w+)?(?:\s|$)")
# Telegram gives up on a press left unanswered for a few seconds (the spinner times out, the toast is
# lost): a press whose work takes longer than this is answered first and done after.
QUICK = 3
CITES = ("📄", "](")  # an answer without either cites nothing: it skips the check
FAILED = {"respuesta": "⚠️ Algo falló de mi lado; inténtalo otra vez en un rato."}
# Hermes's menu covers every private chat and lists only its own commands (and the default profile's skills).
# A menu scoped to the captain's chat wins over it, so this one lists the project's commands before Hermes's.
MENU = ([("quiz", "Quiz corto de un tema con el material: /quiz derivadas")] if SUBJECT else
        [("estado", "Salud del sistema: sondeo, aula, token de Canvas y feeds"),
         ("token", "Token nuevo de Canvas, cifrado en tu celular"),
         ("quiz", "Quiz corto de un tema, del bot de la materia: /quiz derivadas")])
_TASKS = set()  # asyncio keeps only a weak reference to a task


def _env():
    # The gateway's PYTHONPATH points at its own Python's packages: espol-bot runs on another Python and would
    # load their C extensions (Pillow fails with «cannot import name '_imaging'»).
    return {**{k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}, **ENV}


async def _run(*args, stdin=None):
    proc = await asyncio.create_subprocess_exec(
        BOT, *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_env())
    out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="replace").strip()[-500:] or f"exit {proc.returncode}")
    return json.loads(out.decode() or "{}")


def _is_captain(user):
    return str(getattr(user, "id", "")) == CAPTAIN


def register(ctx):
    def _wire(application, adapter):
        from telegram import (BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup,
                              KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, WebAppInfo)
        from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, TypeHandler

        async def _publish_menu():
            for _ in range(300):  # this factory runs before the bot connects; the Bot API waits for it
                if application.running:
                    break
                await asyncio.sleep(1)
            else:
                return
            try:  # the same list Hermes publishes, minus room for ours
                from hermes_cli.commands_platforms import telegram_menu_commands, telegram_menu_max_commands
                hermes, _ = await asyncio.to_thread(
                    telegram_menu_commands, max_commands=max(1, telegram_menu_max_commands() - len(MENU)))
                ours = {name for name, _ in MENU}
                commands = [BotCommand(name, desc) for name, desc in
                            MENU + [(name, desc) for name, desc in hermes if name not in ours]]
                await application.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=int(CAPTAIN)))
            except Exception as exc:  # the captain keeps Hermes's menu; typed commands still work
                logger.warning("no pude publicar el menú de comandos: %s", exc)

        async def _say(context, chat_id, result):
            if result.get("respuesta"):
                markup, button = None, result.get("web_app_button")
                if button:  # only a keyboard button may send web_app_data back to the bot
                    markup = ReplyKeyboardMarkup([[KeyboardButton(button["text"], web_app=WebAppInfo(button["url"]))]],
                                                 resize_keyboard=True, one_time_keyboard=True)
                elif result.get("quitar_teclado"):
                    markup = ReplyKeyboardRemove()
                await context.bot.send_message(chat_id=chat_id, text=result["respuesta"], parse_mode="HTML",
                                               disable_web_page_preview=True, reply_markup=markup)

        async def _reply(context, chat_id, *args, stdin=None):
            try:
                result = await _run(*args, stdin=stdin)
            except Exception as exc:
                logger.error("%s: %s", args[0], exc)
                result = FAILED
            await _say(context, chat_id, result)

        async def _on_created(context, message, created):
            if not _is_captain(message.from_user):
                return
            await _reply(context, message.chat_id, "bot-creado", str(created.bot.id))

        async def _on_token(context, message, token):
            try:
                await message.delete()
                deleted = True
            except Exception as exc:
                logger.warning("no pude borrar el mensaje con el token: %s", exc)
                deleted = False
            if not _is_captain(message.from_user):
                return
            try:
                result = await _run("token", stdin=token)
            except Exception as exc:
                logger.error("token: %s", exc)
                result = dict(FAILED)
            note = ("🔒 Borré del chat el mensaje con el token." if deleted else
                    "🔒 Borra tú el mensaje con el token (yo no pude).")
            await _say(context, message.chat_id, {**result, "respuesta": "\n".join(
                t for t in (note, result.get("respuesta")) if t)})

        async def _on_canvas_token(context, message):
            try:
                await message.delete()
            except Exception as exc:
                logger.warning("no pude borrar el mensaje con el token de Canvas: %s", exc)
            if not _is_captain(message.from_user):
                return
            note = "🔒 Borré tu mensaje: traía un token de Canvas, y lo que se pega en el chat lo lee Telegram."
            if SUBJECT:
                await _say(context, message.chat_id, {"respuesta": note + " Para cambiarlo, mándale /token a Vinci."})
                return
            try:
                result = await _run("canvas-form")
            except Exception as exc:
                logger.error("canvas-form: %s", exc)
                await _say(context, message.chat_id, {"respuesta": f"{note}\n{FAILED['respuesta']}"})
                return
            await _say(context, message.chat_id, {**result, "respuesta": (
                f"{note} Pégalo en este formulario, que lo cifra antes de enviarlo (como ya pasó por Telegram, mejor "
                f"crea uno nuevo).\n\n{result.get('respuesta') or ''}")})

        async def _on_tick(context, message, tick):
            try:  # the deep link's /start is only how the page reached the bot
                await message.delete()
            except Exception as exc:
                logger.info("no pude borrar el /start del dashboard: %s", exc)
            try:
                result = await _run("boton", f"v1:{tick[1]}:{tick[2]}:{tick[3]}")
            except Exception as exc:
                logger.error("dashboard %s: %s", tick[0], exc)
                result = FAILED
            text = result.get("respuesta") or html.escape(result.get("aviso") or "")
            await _say(context, message.chat_id, {"respuesta": f"📋 {text}" if text else ""})

        async def _intercept(update, context):
            if getattr(update, "managed_bot", None) is not None:
                raise ApplicationHandlerStop  # handled through its service message below
            vote = getattr(update, "poll_answer", None)
            if vote is not None and SUBJECT:
                if _is_captain(vote.user):
                    try:
                        result = await _run("quiz-respuesta", "--curso", SUBJECT, str(vote.poll_id),
                                            *(str(o) for o in vote.option_ids))
                        await _say(context, int(CAPTAIN), result)
                    except Exception as exc:
                        logger.error("quiz-respuesta: %s", exc)
                raise ApplicationHandlerStop
            message = update.effective_message
            if message is None or update.callback_query is not None:
                return
            created = getattr(message, "managed_bot_created", None)
            form = getattr(message, "web_app_data", None)
            match = canvas = None
            if created is None and form is None:
                text = message.text or message.caption or ""
                match = TOKEN_RE.search(text)
                canvas = None if match else CANVAS_TOKEN_RE.search(text)
            plain = created is None and form is None and match is None and canvas is None
            start = plain and START_RE.match(message.text or "")
            status = plain and not SUBJECT and STATUS_RE.match(message.text or "")
            ask_form = plain and not SUBJECT and FORM_RE.match(message.text or "")
            if plain and not start and not status and not ask_form:
                return
            try:
                if created is not None:
                    await _on_created(context, message, created)
                elif form is not None:
                    if not SUBJECT and _is_captain(message.from_user):
                        await _reply(context, message.chat_id, "canvas-submit", stdin=form.data or "")
                elif match is not None:
                    await _on_token(context, message, match.group(0))
                elif canvas is not None:
                    await _on_canvas_token(context, message)
                elif _is_captain(message.from_user) and not SUBJECT and TICK_RE.match(message.text or ""):
                    await _on_tick(context, message, TICK_RE.match(message.text or ""))
                elif _is_captain(message.from_user):
                    command = (("estado",) if status else ("canvas-form",) if ask_form else
                               ("saludo", *(("--curso", SUBJECT) if SUBJECT else ())))
                    await _reply(context, message.chat_id, *command)
            except Exception as exc:  # a failed reply must not let the update through to Hermes
                logger.error("filtro: %s", exc)
            raise ApplicationHandlerStop

        async def _answer(query, text, **kwargs):
            try:
                await query.answer(text, **kwargs)
            except Exception as exc:  # too old already: the outcome still reaches the chat
                logger.info("no pude contestar el botón: %s", exc)

        async def _on_button(update, context):
            query = update.callback_query
            if query is None:
                return
            if not _is_captain(query.from_user):
                await query.answer("Este bot solo atiende a su dueño.")
                return
            work = asyncio.ensure_future(_run("boton", query.data or ""))
            late = not (await asyncio.wait({work}, timeout=QUICK))[0]
            if late:  # its toast is dropped: every slow outcome sends its own message
                await _answer(query, "⏳ Un momento…")
            try:
                result = await work
            except Exception as exc:
                logger.error("botón %r: %s", query.data, exc)
                failed = "No pude procesar el botón; intenta de nuevo en un rato."
                if not late:
                    await _answer(query, failed, show_alert=True)
                elif query.message is not None:
                    await context.bot.send_message(chat_id=query.message.chat_id, text=f"⚠️ {failed}")
                return
            if not late:
                await _answer(query, (result.get("aviso") or "Listo")[:190])
            replacement = result.get("replace_button")
            markup = getattr(query.message, "reply_markup", None)
            if replacement and markup is not None:
                rows = [[InlineKeyboardButton(replacement[0], callback_data=replacement[1])
                         if b.callback_data == query.data else b for b in row] for row in markup.inline_keyboard]
                try:
                    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
                except Exception as exc:  # already edited, too old: harmless
                    logger.info("no pude cambiar el botón: %s", exc)
            if result.get("quitar_botones"):
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception as exc:  # already edited, too old: harmless
                    logger.info("no pude quitar los botones: %s", exc)
            if result.get("respuesta") and query.message is not None:
                await context.bot.send_message(chat_id=query.message.chat_id, text=result["respuesta"],
                                               parse_mode="HTML", disable_web_page_preview=True)

        application.add_handler(TypeHandler(Update, _intercept), group=-100)
        application.add_handler(CallbackQueryHandler(_on_button, pattern=PATTERN))
        task = asyncio.ensure_future(_publish_menu())
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)

    ctx.register_platform_handler("telegram", _wire)
    ctx.register_hook("transform_llm_output", _check_citations)
    if SUBJECT:
        ctx.register_tool(name="ver_pagina", toolset="vinci-paginas", schema=PAGE_TOOL, handler=_see_page,
                          is_async=True, description=PAGE_TOOL["description"])
        ctx.register_tool(name="ver_foto", toolset="vinci-paginas", schema=PHOTO_TOOL, handler=_see_photo,
                          is_async=True, description=PHOTO_TOOL["description"])


def _check_citations(response_text="", **_):
    if not any(mark in (response_text or "") for mark in CITES):
        return None
    try:
        proc = subprocess.run([BOT, "citas", *(("--curso", SUBJECT) if SUBJECT else ())], input=response_text,
                              capture_output=True, text=True, timeout=20, env=_env())
        return json.loads(proc.stdout or "{}").get("respuesta") or None
    except Exception as exc:  # never hold an answer back over the check
        logger.error("citas: %s", exc)
        return None


PAGE_TOOL = {
    "name": "ver_pagina",
    "description": "Muestra como imagen una página de un PDF del material de tu materia, para leerla tú: un "
                   "escaneo (estado «escaneado»), una fórmula, una figura o una tabla que el texto no trae bien. "
                   "Solo PDF ya bajados; una página por llamada.",
    "parameters": {"type": "object", "properties": {
        "archivo_id": {"type": "integer", "description": "el ID del archivo (de archivos o buscar_material)"},
        "pagina": {"type": "integer", "description": "número de página, desde 1"}},
        "required": ["archivo_id", "pagina"]},
}


async def _see_page(args, **_):
    try:
        file_id, page = int(args["archivo_id"]), int(args["pagina"])
    except (KeyError, TypeError, ValueError):
        return json.dumps({"error": "Dime «archivo_id» y «pagina» como números."}, ensure_ascii=False)
    try:
        result = await _run("pagina", "--curso", SUBJECT, str(file_id), str(page))
    except Exception as exc:
        logger.error("ver_pagina: %s", exc)
        return json.dumps({"error": "No pude mostrar la página; intenta de nuevo."}, ensure_ascii=False)
    if result.get("error"):
        return json.dumps({"error": result["error"]}, ensure_ascii=False)
    text = (f"Página {result['pagina']} de {result.get('paginas') or '?'} de «{result['archivo']}» (archivo "
            f"{result['archivo_id']}), como imagen: léela tú y cita esa página así: {result['cita']}")
    return {"_multimodal": True, "text_summary": text,
            "content": [{"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": f"data:{result['tipo']};base64,{result['imagen']}"}}]}


PHOTO_TOOL = {
    "name": "ver_foto",
    "description": "Muestra como imagen una foto de tu cuaderno (tipo «foto»: una pizarra, una captura de los "
                   "apuntes del estudiante), para leerla tú. Una foto por llamada.",
    "parameters": {"type": "object", "properties": {
        "entrada": {"type": "integer", "description": "el número de la entrada del cuaderno (foto #N)"}},
        "required": ["entrada"]},
}


async def _see_photo(args, **_):
    try:
        entry = int(args["entrada"])
    except (KeyError, TypeError, ValueError):
        return json.dumps({"error": "Dime «entrada» como número."}, ensure_ascii=False)
    try:
        result = await _run("foto", "--curso", SUBJECT, str(entry))
    except Exception as exc:
        logger.error("ver_foto: %s", exc)
        return json.dumps({"error": "No pude mostrar la foto; intenta de nuevo."}, ensure_ascii=False)
    if result.get("error"):
        return json.dumps({"error": result["error"]}, ensure_ascii=False)
    text = f"Foto #{result['entrada']} de tu cuaderno ({result['texto']}), como imagen: léela tú."
    return {"_multimodal": True, "text_summary": text,
            "content": [{"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": f"data:{result['tipo']};base64,{result['imagen']}"}}]}
