"""{{MARKER}}. Se sobrescribe cada vez que corres setup.sh.

Vinci on WhatsApp, before Hermes sees a message (hook pre_gateway_dispatch). No model involved. The gateway runs
the hook with the plugins of the profile the sender is routed to, so this same file is in Vinci's profile, in every
friend's and in the default one; it acts only on WhatsApp.

- The captain's private chat: «/amigo agregar 0991234567 Angel», «/amigo quitar Angel» and «/amigos» run
  `espol-bot amigo` (amigos.py); anything else goes on to his Vinci.
- Vinci's own commands, for the captain and every friend with their Vinci, each over their own aula: /start,
  /estado, /token, /entregas (a link to the dashboard) and /marca (what a tick on it types) run
  `espol-bot whatsapp-comando` (in a group, all but /start only say to ask in private); «/quiz derivadas» becomes a request for a quiz, which Vinci sends as polls (send_quiz). Hermes' own
  (/new, /usage, /stop, /help) go on to Hermes.
- A group: only a mention of Vinci gets here (Hermes' require_mention). The captain's «@vinci activa este grupo» /
  «desactiva este grupo» turns it on or off (`espol-bot whatsapp-grupo`). In a group that is on, the captain and
  every friend with their own Vinci go on to it (Hermes routes each sender to their profile); a friend still
  without one, or anyone else, gets a fixed answer. A group that is off gets nothing.
- A friend's private chat: the ciphertext the token page gave them goes to `espol-bot amigo token` on stdin, so
  the token reaches no model and no session log; a raw token pasted by mistake is not passed on either.
- A vote on one of Vinci's polls (WhatsApp's stand-in for a card's buttons, whatsapp.py) runs that button for
  whoever voted, over their own aula (`espol-bot whatsapp-comando voto`), without the model. Hermes only lets a
  vote through in private, which is where Vinci sends its polls.
- Anyone else, in private: nothing.
- A mention reaches Hermes as «@<number>»: what goes on to a Vinci says «@vinci» or the person's WhatsApp name
  instead, from the names of everyone who has written to Vinci (kept in NAMES).

When adding or removing a friend changed the routes, the gateway restarts itself once the turns in flight end.
Any failure here drops the message: nothing reaches a Vinci that this plugin could not place.
"""

import asyncio
import json
import logging
import os
import re
import unicodedata
import urllib.request

logger = logging.getLogger("vinci-whatsapp")

BOT = "{{BOT}}"
CAPTAIN = "{{CAPTAIN}}"
REGISTRY = "{{REGISTRY}}"
GROUPS = "{{GROUPS}}"
BRIDGE = "{{BRIDGE}}"
SESSION = "{{SESSION}}"  # the bridge's login: its creds.json says which ids are Vinci's own
NAMES = os.path.join(os.path.dirname(GROUPS), "whatsapp-nombres.json")
RESTART = bool("{{RESTART}}")  # empty in the E2E test, which restarts its own gateway
ENV = {"AULA_CONFIG": "{{CONFIG}}", "AULA_SECRETS": "{{SECRETS}}", "HERMES_BIN": "{{HERMES}}"}
SEALED_RE = re.compile(r"v1\.[A-Za-z0-9_-]{200,}")
# ESPOL's aula tokens: 64 letters (both cases) and digits; stock Canvas prefixes "<digits>~".
CANVAS_TOKEN_RE = re.compile(r"\b(?:\d{1,6}~)?(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*\d)"
                             r"[A-Za-z0-9]{64}\b")
MENTION_RE = re.compile(r"@(\d{6,})\b")
FRIEND_RE = re.compile(r"^/amigos?\b\s*(\S*)\s*(.*)$", re.S)
COMMAND_RE = re.compile(r"^/(start|ayuda|estado|token|quiz|entregas|marca)\b\s*(.*)$", re.S | re.I)
PRIVATE_ONLY = ("estado", "token", "entregas", "marca")  # they show or change the sender's own aula
QUIZ = "Hazme un quiz corto{tema}: de 3 a 5 preguntas de opción múltiple sacadas de mi material."
PRIVATE = "Eso te lo contesto por privado: escríbeme /{0} en nuestro chat."
ON_RE = re.compile(r"\bactiva(?:r|te)? (?:este|el) grupo\b")
OFF_RE = re.compile(r"\bdesactiva(?:r|te)? (?:este|el) grupo\b")
NO_VINCI = ("Todavía no tengo tu aula, así que no puedo contestarte con lo tuyo. Pídele a quien maneja Vinci que te "
            "agregue: te escribo por privado para conectarla.")
PENDING_GROUP = "Te escribí por privado con el enlace para tu token: termina ahí y te contesto con lo tuyo."
PENDING_DM = ("Para empezar, abre el enlace que te mandé, pega tu token del aula y pégame aquí el texto cifrado que "
              "te da (empieza con v1.).")
RAW_TOKEN = ("⚠️ Eso parece tu token del aula tal cual: bórralo de este chat (mantenlo presionado → Eliminar) y usa "
             "el enlace que te mandé, que lo cifra en tu celular.")
RAW_TOKEN_ACTIVE = ("⚠️ Eso parece tu token del aula tal cual: bórralo de este chat (mantenlo presionado → Eliminar) y "
                    "escríbeme /token: te mando un enlace que lo cifra en tu celular.")
FAILED = "⚠️ Algo falló de mi lado; inténtalo otra vez en un rato."
_TASKS = set()  # asyncio keeps only a weak reference to a task


def register(ctx):
    ctx.register_hook("pre_gateway_dispatch", _dispatch)


async def _dispatch(event=None, gateway=None, **_):
    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", None)
    if source is None or platform != "whatsapp":
        return None
    try:
        names = _remember(source)  # anyone who mentions Vinci, even without their own Vinci yet
        result = await _sort(event, source, gateway)
        if result is None:
            text = str(getattr(event, "text", "") or "")
            named = _named(text, names)
            if named != text:
                return {"action": "rewrite", "text": named}
        return result
    except Exception:
        logger.exception("no pude ordenar un mensaje de WhatsApp")
        return {"action": "skip", "reason": "vinci-whatsapp: error"}


def _skip(reason):
    return {"action": "skip", "reason": f"vinci-whatsapp: {reason}"}


async def _sort(event, source, gateway):
    senders = _aliases(getattr(source, "user_id", None)) | _aliases(getattr(source, "user_id_alt", None))
    text = str(getattr(event, "text", "") or "").strip()
    chat = str(getattr(source, "chat_id", "") or "")
    friend = next((f for f in _read(REGISTRY, "amigos") if f.get("numero") in senders), None)
    captain = CAPTAIN in senders
    reply_to = getattr(event, "message_id", None)

    if (getattr(event, "raw_message", None) or {}).get("mediaType") == "poll_update":
        who = CAPTAIN if captain else (friend or {}).get("numero") if (friend or {}).get("estado") == "activo" else None
        poll = getattr(event, "reply_to_message_id", None)
        if who and poll:
            vote = json.dumps({"encuesta": poll, "opcion": text})
            await _answer(chat, await _run("whatsapp-comando", "voto", who, stdin=vote), None, gateway)
        return _skip("voto en una encuesta")

    if chat.endswith("@g.us"):
        plain = _plain(text)
        if captain and (OFF_RE.search(plain) or ON_RE.search(plain)):
            action = "desactivar" if OFF_RE.search(plain) else "activar"
            await _answer(chat, await _run("whatsapp-grupo", action, chat), reply_to, gateway)
            return _skip(f"grupo {action}")
        if chat not in _read(GROUPS, "grupos"):
            return _skip("grupo apagado")
        if captain or (friend and friend.get("estado") == "activo"):
            if CANVAS_TOKEN_RE.search(text):
                await _answer(chat, {"respuesta": RAW_TOKEN_ACTIVE}, reply_to, gateway)
                return _skip("token sin cifrar")
            return await _command(text, senders, chat, reply_to, gateway, group=True)
        if text.startswith("/"):  # a command reaches Hermes without a mention: not necessarily for Vinci
            return _skip("comando de alguien sin Vinci")
        await _answer(chat, {"respuesta": PENDING_GROUP if friend else NO_VINCI}, reply_to, gateway)
        return _skip("sin Vinci")

    if captain:
        sealed = SEALED_RE.search(text)
        if sealed:  # what the page gave him after a /token here
            await _answer(chat, await _run("whatsapp-comando", "token-cifrado", CAPTAIN, stdin=sealed[0]), reply_to,
                          gateway)
            return _skip("token cifrado del capitán")
        if CANVAS_TOKEN_RE.search(text):
            await _answer(chat, {"respuesta": RAW_TOKEN_ACTIVE}, reply_to, gateway)
            return _skip("token sin cifrar")
        match = FRIEND_RE.match(text)
        if not match:
            return await _command(text, senders, chat, reply_to, gateway)
        verb, rest = match[1].lower(), match[2].split()
        if text.lower().startswith("/amigos") or verb in ("", "lista"):
            result = await _run("amigo", "lista")
        elif verb in ("agregar", "quitar"):
            result = await _run("amigo", verb, *rest)
        else:
            result = {"respuesta": "Así: /amigo agregar 0991234567 Angel · /amigo quitar Angel · /amigos"}
        await _answer(chat, result, reply_to, gateway)
        return _skip("comando del capitán")

    if friend is None:
        return _skip("desconocido")
    sealed = SEALED_RE.search(text)
    if sealed:
        number = friend["numero"]
        if friend.get("estado") != "activo":
            await _answer(chat, {"respuesta": "🔒 Recibido. Estoy leyendo tu aula por primera vez, dame un minuto…"},
                          None, gateway)
        await _answer(chat, await _run("amigo", "token", number, stdin=sealed[0]), reply_to, gateway)
        return _skip("token cifrado")
    if CANVAS_TOKEN_RE.search(text):
        await _answer(chat, {"respuesta": RAW_TOKEN_ACTIVE if friend.get("estado") == "activo" else RAW_TOKEN},
                      reply_to, gateway)
        return _skip("token sin cifrar")
    if friend.get("estado") == "activo":
        return await _command(text, senders, chat, reply_to, gateway)
    await _answer(chat, {"respuesta": PENDING_DM}, reply_to, gateway)
    return _skip("amigo sin token")


async def _command(text, senders, chat, reply_to, gateway, *, group=False):
    """Vinci's own commands; anything else goes on to the sender's Vinci (None)."""
    match = COMMAND_RE.match(_strip_mention(text))
    if not match:
        return None
    name, rest = match[1].lower(), match[2].strip()
    if name == "quiz":
        return {"action": "rewrite", "text": QUIZ.format(tema=f" de {rest}" if rest else "")}
    if group and name in PRIVATE_ONLY:
        await _answer(chat, {"respuesta": PRIVATE.format(name)}, reply_to, gateway)
        return _skip(f"/{name} en un grupo")
    who = CAPTAIN if CAPTAIN in senders else next(f["numero"] for f in _read(REGISTRY, "amigos")
                                                     if f.get("numero") in senders)
    await _answer(chat, await _run("whatsapp-comando", "start" if name == "ayuda" else name, who,
                                   stdin=rest if name == "marca" else None), reply_to, gateway)
    return _skip(f"/{name}")


def _strip_mention(text):
    # «@vinci /estado» in a group, as people also type it
    return re.sub(r"^@\S+\s+", "", text.strip())


def _remember(source):
    """Records who this sender is called, under each of their ids; returns every name known so far."""
    names = _read_dict(NAMES)
    name = str(getattr(source, "user_name", "") or "").strip()
    ids = {_bare(i) for i in _aliases(getattr(source, "user_id", None)) | _aliases(getattr(source, "user_id_alt", None))}
    if name and any(names.get(i) != name for i in ids):
        names.update(dict.fromkeys(ids, name))
        try:
            os.makedirs(os.path.dirname(NAMES), exist_ok=True)
            tmp = f"{NAMES}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(names, fh, ensure_ascii=False)
            os.replace(tmp, NAMES)
        except OSError as exc:  # a name not kept only leaves a mention as a number
            logger.warning("no pude guardar el nombre de quien escribe: %s", exc)
    return names


def _named(text, names):
    own = _own_ids()
    return MENTION_RE.sub(lambda m: "@vinci" if m[1] in own else f"@{names[m[1]]}" if m[1] in names else m[0], text)


def _own_ids():
    me = _read_dict(os.path.join(SESSION, "creds.json")).get("me") or {}
    return {_bare(me.get("id")), _bare(me.get("lid"))} - {""}


def _bare(user_id):
    return re.sub(r"[:@].*$", "", str(user_id or ""))


def _read_dict(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _aliases(user_id):
    if not user_id:
        return set()
    try:  # a LID («…@lid») and the phone number it stands for, from the bridge's own mapping files
        from gateway.whatsapp_identity import expand_whatsapp_aliases
        return set(expand_whatsapp_aliases(str(user_id)))
    except Exception:
        return {re.sub(r"[:@].*$", "", str(user_id))}


def _plain(text):
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


def _read(path, key):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh).get(key) or []
    except FileNotFoundError:
        return []


def _env():
    # The gateway's PYTHONPATH points at its own Python's packages: espol-bot runs on another Python.
    # A friend's own AULA_DATA_DIR / ESPOL_AMIGO must not leak in: these commands run as the captain's install.
    drop = ("PYTHONPATH", "PYTHONHOME", "AULA_DATA_DIR", "ESPOL_AMIGO")
    return {**{k: v for k, v in os.environ.items() if k not in drop}, **ENV}


async def _run(*args, stdin=None):
    proc = await asyncio.create_subprocess_exec(
        BOT, *args, "--json", stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_env())
    out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout=600)
    if proc.returncode != 0:  # espol-bot's own message for a ConfigError: «Vinci: …»
        message = err.decode(errors="replace").strip().splitlines()
        logger.error("%s: %s", args[0], message[-1] if message else proc.returncode)
        last = message[-1] if message else ""
        return {"respuesta": last.removeprefix("Vinci: ") if last.startswith("Vinci: ") else FAILED}
    return json.loads(out.decode() or "{}")


async def _answer(chat, result, reply_to, gateway):
    text = (result or {}).get("respuesta")
    if text:
        payload = {"chatId": chat, "message": text, **({"replyTo": reply_to} if reply_to else {})}
        await asyncio.to_thread(_post, payload)
    if (result or {}).get("reiniciar") and RESTART and gateway is not None:
        _restart(gateway)


def _post(payload):
    request = urllib.request.Request(f"{BRIDGE}/send", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def _restart(gateway):
    # As Hermes' own /restart: under systemd or a container, exit for the supervisor; else a detached helper.
    try:
        from gateway.restart import is_container_restart_context, is_gateway_supervisor_process
        via_service = is_gateway_supervisor_process() or is_container_restart_context()
        gateway.request_restart(detached=not via_service, via_service=via_service)
        logger.info("rutas de WhatsApp cambiadas: reinicio del gateway pedido")
    except Exception:
        logger.exception("no pude reiniciar el gateway; hazlo a mano: hermes gateway restart")
