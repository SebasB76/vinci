"""{{MARKER}}. Se sobrescribe cada vez que corres setup.sh.

Model-free Telegram handlers of Vinci and its subject bots, answering only the captain:

- Inline buttons (callback data `v1:...`): run `espol-bot boton <data>`, which queues a
  handoff, saves or discards a schedule proposal, or creates / archives a subject bot.
- A bot created for Vinci to manage (`managed_bot_created`): run `espol-bot bot-creado <id>`,
  which fetches its token from Telegram and provisions it.
- Any message carrying a bot token (for example BotFather's reply, forwarded): delete it
  from the chat and hand the token to `espol-bot token` on stdin.

These run in group -100, before every Hermes handler, and stop the update there
(ApplicationHandlerStop): a token or a bot-creation message never becomes a Hermes
event, so it never reaches the model or a session log.
"""

import asyncio
import json
import logging
import os
import re

logger = logging.getLogger("vinci-botones")

BOT = "{{BOT}}"
CAPTAIN = "{{USER_ID}}"
ENV = {"AULA_CONFIG": "{{CONFIG}}", "AULA_SECRETS": "{{SECRETS}}", "HERMES_BIN": "{{HERMES}}"}
PATTERN = r"^v1:"
TOKEN_RE = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{30,}\b")
FAILED = {"respuesta": "⚠️ Algo falló de mi lado; inténtalo otra vez en un rato."}


async def _run(*args, stdin=None):
    proc = await asyncio.create_subprocess_exec(
        BOT, *args, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={**os.environ, **ENV})
    out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="replace").strip()[-500:] or f"exit {proc.returncode}")
    return json.loads(out.decode() or "{}")


def _is_captain(user):
    return str(getattr(user, "id", "")) == CAPTAIN


def register(ctx):
    def _wire(application, adapter):
        from telegram import ReplyKeyboardRemove, Update
        from telegram.ext import ApplicationHandlerStop, CallbackQueryHandler, TypeHandler

        async def _say(context, chat_id, result):
            if result.get("respuesta"):
                markup = ReplyKeyboardRemove() if result.get("quitar_teclado") else None
                await context.bot.send_message(chat_id=chat_id, text=result["respuesta"], parse_mode="HTML",
                                               disable_web_page_preview=True, reply_markup=markup)

        async def _on_created(context, message, created):
            if not _is_captain(message.from_user):
                return
            try:
                result = await _run("bot-creado", str(created.bot.id))
            except Exception as exc:
                logger.error("bot-creado: %s", exc)
                result = FAILED
            await _say(context, message.chat_id, result)

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

        async def _intercept(update, context):
            if getattr(update, "managed_bot", None) is not None:
                raise ApplicationHandlerStop  # handled through its service message below
            message = update.effective_message
            if message is None or update.callback_query is not None:
                return
            created = getattr(message, "managed_bot_created", None)
            match = None if created is not None else TOKEN_RE.search(message.text or message.caption or "")
            if created is None and match is None:
                return
            try:
                if created is not None:
                    await _on_created(context, message, created)
                else:
                    await _on_token(context, message, match.group(0))
            except Exception as exc:  # a failed reply must not let the update through to Hermes
                logger.error("filtro de tokens: %s", exc)
            raise ApplicationHandlerStop

        async def _on_button(update, context):
            query = update.callback_query
            if query is None:
                return
            if not _is_captain(query.from_user):
                await query.answer("Este bot solo atiende a su dueño.")
                return
            try:
                result = await _run("boton", query.data or "")
            except Exception as exc:
                logger.error("botón %r: %s", query.data, exc)
                await query.answer("No pude procesar el botón; intenta de nuevo en un rato.", show_alert=True)
                return
            try:
                await query.answer((result.get("aviso") or "Listo")[:190])
            except Exception as exc:  # a slow press can outlive the callback's lifetime: still reply below
                logger.info("no pude contestar el botón: %s", exc)
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

    ctx.register_platform_handler("telegram", _wire)
