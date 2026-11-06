"""{{MARKER}}. Se sobrescribe cada vez que corres setup.sh.

Vinci on WhatsApp, before Hermes sees a message (hook pre_gateway_dispatch). No model involved. The gateway runs
the hook with the plugins of the profile the sender is routed to, so this same file is in Vinci's profile, in every
friend's and in the default one; it acts only on WhatsApp.

- The captain's private chat: «/amigo agregar 0991234567 Angel», «/amigo quitar Angel» and «/amigos» run
  `espol-bot amigo` (amigos.py); anything else goes on to his Vinci.
- Vinci's own commands, for the captain and every friend with their Vinci, each over their own aula: /start,
  /estado, /token, /entregas (a link to the dashboard), /marca (what a tick on it types) and /cambio (card trades)
  run `espol-bot whatsapp-comando` (in a group, all but /start and /cambio only say to ask in private); «/quiz derivadas» becomes a request for a quiz, which Vinci sends as polls (send_quiz). Hermes' own
  (/new, /usage, /stop, /help) go on to Hermes.
- A group: only a mention of Vinci gets here (Hermes' require_mention). The captain's «@vinci activa este grupo» /
  «desactiva este grupo» turns it on or off (`espol-bot whatsapp-grupo`); «activa los avisos» / «desactiva los
  avisos» do the same for the class reminders and the aula's news there (avisos.py); «este grupo es de confianza»
  makes it a friends' group, where those notices tag people and say who handed in. In a group that is on, the captain and
  every friend with their own Vinci go on to it (_own_vinci sends each friend to their own profile); a friend still
  without one, or anyone else, reaches Vinci as a guest (GUEST_HEADER): only its guest tools, never the captain's
  data. A group that is off gets nothing.
- A friend's private chat: the ciphertext the token page gave them goes to `espol-bot amigo token` on stdin, so
  the token reaches no model and no session log; a raw token pasted by mistake is not passed on either.
- A vote on one of Vinci's polls (WhatsApp's stand-in for a card's buttons, whatsapp.py) runs that button for
  whoever voted, over their own aula (`espol-bot whatsapp-comando voto`), without the model. In a group Hermes only
  lets through a vote on a quiz (its options start with 🇦 🇧…, a mention pattern in setup): anyone's vote there
  counts (`espol-bot whatsapp-grupo voto`). Once every member answered it all, or 15 minutes after the quiz went out
  (QUIZ_CLOSES, checked by the relay loop), the group gets everyone's results, tagged. A vote skips Hermes' sessions
  altogether (_wire_votes): one cast while Vinci's turn still runs is not queued for the model.
- A voice note or an audio file: Hermes transcribes a voice note on its own, not an audio file (a recording someone
  forwarded, an .m4a), so this one hears that with the same local Whisper. In a group a voice note cannot mention
  Vinci: every one gets here (a mention pattern in setup), and only the captain's or a friend's with their Vinci that
  says «Vinci» or answers one of its messages goes on; anyone else's is not even heard.
- Vinci answers a voice note with a voice note too, then the text (voice.auto_tts, set up by hermes_setup). Hermes
  would also speak the answer to a typed message under that setting: _speak_only_to_voice stops it.
- Anyone else, in private: with [channels] inscripcion_abierta, the link for their token, as «/amigo agregar»
  sends (`espol-bot amigo inscribir`), and the captain hears of it; otherwise nothing.
- A mention reaches Hermes as «@<number>»: what goes on to a Vinci says «@vinci» or the person's WhatsApp name
  instead, from the names of everyone who has written to Vinci (kept in NAMES), also in the message it quotes.
- A sticker never reaches a Vinci: Hermes would hand it over as a document it cannot open.
- A file that goes on to a Vinci is noted with its chat (ATTACHMENTS): WhatsApp's files land in Hermes' shared cache,
  and a tool takes one only for the chat that sent it (herramientas._media_file).
- In a group, what goes on to a Vinci starts with who wrote it, already checked by their number. Every Vinci speaks
  from the same WhatsApp account, so Hermes calls any of their messages «your previous message»: a quote counts as
  this Vinci's own only when its text is in this conversation. After GROUP_IDLE without a message, the conversation
  starts over, as /new would: a group chat that grew for days got too big for Hermes to summarize.
- A private chat starts over after PRIVATE_IDLE too: Hermes keeps a conversation's rules and memory as they were when
  it began, and a chat open for days kept old ones. What it was doing survives in each turn's context (vinci-botones).

- The /token page and the dashboard, opened from a button: what they post to Vinci's relay (src/espol_bot/relay.py)
  is fetched here every few seconds while a link is open (`espol-bot whatsapp-rele`), only by the default profile's
  copy and one process at a time, and answered in the chat of whom the link was for.
- The Académico, once connected from its button (src/espol_bot/portal_login.py), and the brief before a class
  (agenda.run_vinci): the question waits in TURNS, and a loop puts it back in the Hermes session it came from
  (ctx.inject_message, which the gateway allows this plugin only: plugins.entries.vinci-whatsapp.allow_gateway_injection),
  on WhatsApp or Telegram, so Vinci answers it there. A recent Hermes lets a plugin inject only into its own profile's
  sessions, an older one hands its injector to the default profile only: so the copy in each Vinci's profile tries
  its own sessions, the default one tries them all, and whichever the gateway takes first claims the turn.

When adding or removing a friend changed the routes, the gateway restarts itself once the turns in flight end.
Any failure here drops the message: nothing reaches a Vinci that this plugin could not place.
"""

import asyncio
import fcntl
import json
import logging
import os
import re
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("vinci-whatsapp")

BOT = "{{BOT}}"
CAPTAIN = "{{CAPTAIN}}"
REGISTRY = "{{REGISTRY}}"
GROUPS = "{{GROUPS}}"
BRIDGE = "{{BRIDGE}}"
SESSION = "{{SESSION}}"  # the bridge's login: its creds.json says which ids are Vinci's own
NAMES = os.path.join(os.path.dirname(GROUPS), "whatsapp-nombres.json")
QUIZ_CLOSES = os.path.join(os.path.dirname(GROUPS), "quiz-cierres.json")
FRIEND_PROFILE_PREFIX = "amigo-"  # amigos.PROFILE_PREFIX
GROUP_IDLE = int("{{GROUP_IDLE}}")  # seconds; the E2E test shortens it
PRIVATE_IDLE = 4 * 3600
RELAY = "{{RELAY}}"  # relay.py's mailboxes; set only in the default profile's copy, the one that polls
RELAY_EVERY = 3
TURNS = os.path.join(os.path.dirname(REGISTRY), "turns")  # relay.queue_turn
# This copy's profile, from where setup put it (<root>/profiles/<name>/plugins/vinci-whatsapp/); "" in the default's.
_HOME = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROFILE = os.path.basename(_HOME) if os.path.basename(os.path.dirname(_HOME)) == "profiles" else ""
ENV = {"AULA_CONFIG": "{{CONFIG}}", "AULA_SECRETS": "{{SECRETS}}", "HERMES_BIN": "{{HERMES}}"}
SEALED_RE = re.compile(r"v1\.[A-Za-z0-9_-]{200,}")
# ESPOL's aula tokens: 64 letters (both cases) and digits; stock Canvas prefixes "<digits>~".
CANVAS_TOKEN_RE = re.compile(r"\b(?:\d{1,6}~)?(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*\d)"
                             r"[A-Za-z0-9]{64}\b")
MENTION_RE = re.compile(r"@(\d{6,})\b")
FRIEND_RE = re.compile(r"^/amigos?\b\s*(\S*)\s*(.*)$", re.S)
COMMAND_RE = re.compile(r"^/(start|ayuda|estado|token|quiz|entregas|marca|cambio)\b\s*(.*)$", re.S | re.I)
PRIVATE_ONLY = ("estado", "token", "entregas", "marca")  # they show or change the sender's own aula
QUIZ = "Hazme un quiz corto{tema}: de 3 a 5 preguntas de opción múltiple sacadas de mi material."
PRIVATE = "Eso te lo contesto por privado: escríbeme /{0} en nuestro chat."
ON_RE = re.compile(r"\bactiva(?:r|te)? (?:este|el) grupo\b")
OFF_RE = re.compile(r"\bdesactiva(?:r|te)? (?:este|el) grupo\b")
TRUST_OFF_RE = re.compile(r"\b(?:este|el) grupo (?:ya )?no es de confianza\b")
TRUST_ON_RE = re.compile(r"\b(?:este|el) grupo es de confianza\b")
NOTICES_ON_RE = re.compile(r"\b(?:activa(?:r)?|manda(?:r)?) (?:los )?avisos\b")
NOTICES_OFF_RE = re.compile(r"\b(?:desactiva(?:r)?|quita(?:r)?) (?:los )?avisos\b|\bno mandes (?:los )?avisos\b")
PENDING_DM = ("Para empezar, conecta tu aula virtual desde el enlace que te mandé: yo solo la leo, no cambio nada. "
              "Si el enlace ya no abre, escríbeme /token y te mando otro.")
RAW_TOKEN = ("⚠️ Eso parece tu token del aula tal cual: bórralo de este chat (mantenlo presionado → Eliminar) y usa "
             "el enlace que te mandé, que lo cifra en tu celular.")
RAW_TOKEN_ACTIVE = ("⚠️ Eso parece tu token del aula tal cual: bórralo de este chat (mantenlo presionado → Eliminar) y "
                    "escríbeme /token: te mando un enlace que lo cifra en tu celular.")
FAILED = "⚠️ Algo falló de mi lado; inténtalo otra vez en un rato."
GROUP_HEADER = "[{name} te escribe en un grupo de WhatsApp]"
# Someone in a group with no Vinci of their own: Vinci answers with only its guest tools (vinci-botones' pre_tool_call).
GUEST_HEADER = "[{name}, invitado sin su propio Vinci, te escribe en un grupo de WhatsApp]"
PENDING_HEADER = ("[{name}, invitado: ya te escribió y le falta conectar su aula con el enlace que le llegó por "
                  "privado, te escribe en un grupo de WhatsApp]")
NOT_YOURS = ("(un mensaje de Vinci que no está en tu conversación: es del Vinci de otra persona del grupo, o de hace "
             "rato) ")
AUDIO = ("ptt", "audio")  # the bridge's mediaType for a voice note and for an audio file
CALLS_VINCI_RE = re.compile(r"\b[bv]in(?:ch|c|s)h?i\b")  # «Vinci» as Whisper may spell it, over _plain text
# Next to the profile's config (<profile>/plugins/vinci-whatsapp/__init__.py); the profile's tools read it there.
ATTACHMENTS = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "..", "adjuntos.json"))
ATTACHMENTS_KEPT = 7 * 86400
_HEARD = {}  # the last audio heard: a group's audio file is heard to place it, then again for the model
_TASKS = set()  # asyncio keeps only a weak reference to a task
_VOTES = asyncio.Lock()
_GATEWAY = []  # the gateway, as the hook last saw it
_LIVE_ROUTES = {}  # sender → a route to their own Vinci that the boot routes missed (_own_vinci)
LIVE_ROUTE = "vinci-whatsapp-en-vivo-"


def register(ctx):
    _speak_only_to_voice()
    ctx.register_hook("pre_gateway_dispatch", _dispatch)
    ctx.register_platform_handler("whatsapp", _wire_votes)
    if RELAY:
        threading.Thread(target=_relay_loop, args=(ctx,), name="vinci-relay", daemon=True).start()
    elif PROFILE:
        threading.Thread(target=_turns_loop, args=(ctx,), name=f"vinci-turnos-{PROFILE}", daemon=True).start()


def _speak_only_to_voice():
    """With voice.auto_tts the gateway runner speaks every answer, and the adapter speaks the one to a voice note:
    keep only the adapter's. Each profile's copy of this plugin runs this, so it wraps once."""
    try:
        from gateway.run_voice import GatewayVoiceMixin
    except ImportError:
        return
    original = GatewayVoiceMixin._should_send_voice_reply
    if getattr(original, "vinci_voice_only", False):
        return

    def should_send_voice_reply(self, event, *args, **kwargs):
        heard = getattr(getattr(event, "message_type", None), "value", None) == "voice"
        return heard and original(self, event, *args, **kwargs)

    should_send_voice_reply.vinci_voice_only = True
    GatewayVoiceMixin._should_send_voice_reply = should_send_voice_reply


async def _dispatch(event=None, gateway=None, session_store=None, **_):
    if gateway is not None:
        _GATEWAY[:] = [gateway]
    source = getattr(event, "source", None)
    platform = getattr(getattr(source, "platform", None), "value", None)
    if source is None or platform != "whatsapp":
        return None
    try:
        if _kind(event) == "poll_update":  # the bridge names a voter by their number: not a name to keep
            return await _sort(event, source, gateway)
        names = _remember(source)  # anyone who mentions Vinci, even without their own Vinci yet
        result = await _sort(event, source, gateway)
        if result is None:
            _note_attachments(event, source)
            original = str(getattr(event, "text", "") or "")
            text = original
            kind, audio = _audio(event)
            if kind == "audio":
                text = _with_transcript(text, await _hear(audio))
            named = _named(text, names)
            if getattr(event, "reply_to_text", None):  # Hermes quotes it after this hook: fixed here, in place
                event.reply_to_text = _named(str(event.reply_to_text), names)
            group = str(getattr(source, "chat_id", "")).endswith("@g.us")
            if not _strip_mention(named).startswith("/"):
                key = _session_key(gateway, source)
                await _fresh_start(gateway, session_store, event, key, GROUP_IDLE if group else PRIVATE_IDLE)
            if group and not _strip_mention(named).startswith("/"):
                _own_quote(event, session_store, key)
                name = names.get(_bare(getattr(source, "user_id", None))) or getattr(source, "user_name", "") or "Alguien"
                header = {"activo": GROUP_HEADER, "pendiente": PENDING_HEADER}.get(_vinci_state(source), GUEST_HEADER)
                named = f"{header.format(name=name)}\n{named}"
            if named != original:
                return {"action": "rewrite", "text": named}
        return result
    except Exception:
        logger.exception("no pude ordenar un mensaje de WhatsApp")
        return {"action": "skip", "reason": "vinci-whatsapp: error"}


def _wire_votes(_native, adapter):
    """A vote never needs the model, but Hermes would get in its way: it joins texts one person sends in a row into a
    single message (two quick votes become text no poll has), and queues whatever reaches a chat whose turn still runs
    (Vinci's polls go out mid-turn) past the pre_gateway_dispatch hook, for the model. Here a vote goes straight to
    _sort, before either."""
    if getattr(adapter, "_vinci_votes", False):  # every profile's copy of this plugin registers it
        return
    enqueue, handle = adapter._enqueue_text_event, adapter.handle_message

    def enqueue_text(event):  # a vote is a text
        if _kind(event) == "poll_update":
            _spawn_vote(event)
        else:
            enqueue(event)

    async def handle_message(event):
        if _kind(event) == "poll_update":
            _spawn_vote(event)
        else:
            await handle(event)

    adapter._enqueue_text_event, adapter.handle_message = enqueue_text, handle_message
    adapter._vinci_votes = True


def _spawn_vote(event):
    task = asyncio.ensure_future(_count_vote(event))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _count_vote(event):
    try:
        async with _VOTES:  # in the order they came: of two votes on one question, the first counts
            await _sort(event, event.source, _GATEWAY[0] if _GATEWAY else None)
    except Exception:
        logger.exception("no pude contar un voto de WhatsApp")


def _skip(reason):
    return {"action": "skip", "reason": f"vinci-whatsapp: {reason}"}


def _vinci_state(source) -> str | None:
    """«activo» for the captain or a friend with their Vinci, «pendiente» for a friend still without a token."""
    senders = _aliases(getattr(source, "user_id", None)) | _aliases(getattr(source, "user_id_alt", None))
    if CAPTAIN in senders:
        return "activo"
    return next((f.get("estado") for f in _read(REGISTRY, "amigos") if f.get("numero") in senders), None)


async def _sort(event, source, gateway):
    senders = _aliases(getattr(source, "user_id", None)) | _aliases(getattr(source, "user_id_alt", None))
    text = str(getattr(event, "text", "") or "").strip()
    chat = str(getattr(source, "chat_id", "") or "")
    friend = next((f for f in _read(REGISTRY, "amigos") if f.get("numero") in senders), None)
    captain = CAPTAIN in senders
    reply_to = getattr(event, "message_id", None)

    if _kind(event) == "sticker":
        return _skip("sticker")

    if _kind(event) == "poll_update":
        who = CAPTAIN if captain else (friend or {}).get("numero") if (friend or {}).get("estado") == "activo" else None
        poll = getattr(event, "reply_to_message_id", None)
        if chat.endswith("@g.us"):
            voter = _voter(event)
            if poll and voter and chat in _read(GROUPS, "grupos"):
                vote = json.dumps({"encuesta": poll, "opcion": text, "numeros": sorted(_aliases(voter)),
                                   "votante": voter})
                await _answer(chat, await _run("whatsapp-grupo", "voto", chat, stdin=vote), None, gateway)
            return _skip("voto en un quiz de grupo")
        if who and poll:
            vote = json.dumps({"encuesta": poll, "opcion": text})
            await _answer(chat, await _run("whatsapp-comando", "voto", who, stdin=vote), None, gateway)
        return _skip("voto en una encuesta")

    if friend and friend.get("estado") == "activo" and not captain:
        await _own_vinci(source, friend, gateway)

    if chat.endswith("@g.us"):
        plain = _plain(text)
        if captain and (TRUST_OFF_RE.search(plain) or TRUST_ON_RE.search(plain)):
            action = "sin-confianza" if TRUST_OFF_RE.search(plain) else "confianza"
            await _answer(chat, await _run("whatsapp-grupo", action, chat), reply_to, gateway)
            return _skip(f"grupo {action}")
        if captain and (NOTICES_OFF_RE.search(plain) or NOTICES_ON_RE.search(plain)):
            action = "sin-avisos" if NOTICES_OFF_RE.search(plain) else "avisos"
            await _answer(chat, await _run("whatsapp-grupo", action, chat), reply_to, gateway)
            return _skip(f"grupo {action}")
        if captain and (OFF_RE.search(plain) or ON_RE.search(plain)):
            action = "desactivar" if OFF_RE.search(plain) else "activar"
            await _answer(chat, await _run("whatsapp-grupo", action, chat), reply_to, gateway)
            return _skip(f"grupo {action}")
        if chat not in _read(GROUPS, "grupos"):
            return _skip("grupo apagado")
        kind, audio = _audio(event)
        if kind:
            if not (captain or (friend and friend.get("estado") == "activo")):
                return _skip("audio de alguien sin Vinci")
            raw = getattr(event, "raw_message", None) or {}
            to_vinci = _bare(raw.get("quotedParticipant")) in _own_ids()
            heard = await _hear(audio) if kind == "audio" or not to_vinci else None
            if not to_vinci and not CALLS_VINCI_RE.search(_plain(heard or "")):
                return _skip("audio que no llama a Vinci")
            return None
        if captain or (friend and friend.get("estado") == "activo"):
            if CANVAS_TOKEN_RE.search(text):
                await _answer(chat, {"respuesta": RAW_TOKEN_ACTIVE}, reply_to, gateway)
                return _skip("token sin cifrar")
            return await _command(text, senders, chat, reply_to, gateway, group=True)
        if text.startswith("/"):  # a command reaches Hermes without a mention: not necessarily for Vinci
            return _skip("comando de alguien sin Vinci")
        return None  # a guest

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

    if friend is None:  # [channels] inscripcion_abierta: they get the token link (amigos.signup), no model turn
        number = _phone(source)
        if number:
            name = str(getattr(source, "user_name", "") or "")
            await _answer(chat, await _run("amigo", "inscribir", number, *name.split()), reply_to, gateway)
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
    if text.lower().startswith("/token"):  # the invitation's link lasts a day: a new one
        await _answer(chat, await _run("amigo", "inscribir", friend["numero"]), reply_to, gateway)
        return _skip("amigo sin token pide otro enlace")
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
                                   stdin=rest if name in ("marca", "cambio") else None), reply_to, gateway)
    return _skip(f"/{name}")


def _voter(event):
    """Who cast a group vote. The bridge names the poll's author (Vinci) as its sender there; its tally of this one
    update names the voter."""
    native = (getattr(event, "metadata", None) or {}).get("whatsapp_native") or {}
    tally = (native.get("pollUpdate") or {}).get("aggregation") or []
    return next((str(v) for option in tally for v in option.get("voters") or []), None)


def _kind(event):
    return (getattr(event, "raw_message", None) or {}).get("mediaType")


def _audio(event):
    """(«ptt» or «audio», its file) for a voice note or an audio file; (None, None) for anything else."""
    kind = (getattr(event, "raw_message", None) or {}).get("mediaType")
    urls = getattr(event, "media_urls", None) or []
    return (kind, str(urls[0])) if kind in AUDIO and urls else (None, None)


async def _hear(path):
    """Its transcript with Hermes' own STT (local Whisper, as configured), or None when it could not."""
    if path not in _HEARD:
        from tools.transcription_tools import transcribe_audio
        result = await asyncio.to_thread(transcribe_audio, path, None, "gateway")
        heard = str(result.get("transcript") or "").strip() if result.get("success") else ""
        if not heard:
            logger.info("no pude transcribir un audio de WhatsApp: %s", result.get("error") or "sin voz")
        _HEARD.clear()
        _HEARD[path] = heard or None
    return _HEARD[path]


def _with_transcript(text, heard):
    """An audio file reaches the model as Hermes puts a voice note: the transcript in quotes, then any caption."""
    if not heard:
        return text  # Hermes still tells the model where the file is
    caption = "" if text.strip() == "[audio received]" else text.strip()
    return f'"{heard}"' + (f"\n\n{caption}" if caption else "")


def _session_key(gateway, source):
    try:
        return gateway._session_key_for_source(source)
    except Exception:
        return None


async def _fresh_start(gateway, session_store, event, key, idle):
    """A conversation idle for `idle` seconds starts over, through Hermes' own /new handler, whose notice nobody
    gets: it returns the notice instead of sending it."""
    try:
        entry = session_store.lookup_by_session_key(key) if key else None
    except Exception:
        entry = None
    updated = getattr(entry, "updated_at", None)
    if updated is None or (datetime.now(updated.tzinfo) - updated).total_seconds() < idle:
        return
    try:
        import dataclasses
        await gateway._handle_reset_command(dataclasses.replace(event, text="/new"))
        logger.info("chat inactivo: conversación nueva")
    except Exception:  # the message still goes on, in the old conversation
        logger.exception("no pude empezar de nuevo la conversación")


def _own_quote(event, session_store, key):
    """Whether the quoted Vinci message is this Vinci's: its text is in this conversation (Hermes' state.db for
    the profile this copy of the plugin is in)."""
    if not getattr(event, "reply_to_is_own_message", False) or not getattr(event, "reply_to_text", None):
        return
    quoted = _letters(event.reply_to_text)[:80]
    found = False
    try:
        session_id = session_store.peek_session_id(key)
        db = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "state.db")
        if session_id and quoted and os.path.exists(db):
            import sqlite3
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5) as conn:
                rows = conn.execute("SELECT content FROM messages WHERE session_id = ? AND role = 'assistant' "
                                    "ORDER BY id DESC LIMIT 300", (session_id,)).fetchall()
            found = any(quoted in _letters(row[0] or "") for row in rows)
    except Exception:  # a quote left as Hermes put it
        logger.exception("no pude ver de quién es el mensaje citado")
        return
    if not found:
        event.reply_to_is_own_message = False
        event.reply_to_text = NOT_YOURS + str(event.reply_to_text)


def _letters(text):
    # WhatsApp gives a quote back with its own formatting (_x_ for *x*, links unwrapped): compare letters only
    return re.sub(r"[^a-z0-9]", "", _plain(str(text)))


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


def _note_attachments(event, source):
    paths = [os.path.realpath(str(p)) for p in getattr(event, "media_urls", None) or []]
    if not paths:
        return
    now = time.time()
    owners = {p: o for p, o in _read_dict(ATTACHMENTS).items() if now - float(o.get("en") or 0) < ATTACHMENTS_KEPT}
    owners.update(dict.fromkeys(paths, {"chat": f"whatsapp:{getattr(source, 'chat_id', '')}", "en": now}))
    try:
        tmp = f"{ATTACHMENTS}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(owners, fh)
        os.replace(tmp, ATTACHMENTS)
    except OSError as exc:  # the file reaches the model, but its tools will not take it
        logger.warning("no pude anotar de qué chat es un adjunto: %s", exc)


def _named(text, names):
    own = _own_ids()
    return MENTION_RE.sub(lambda m: "@vinci" if m[1] in own else f"@{names[m[1]]}" if m[1] in names else m[0], text)


def _own_ids():
    me = _read_dict(os.path.join(SESSION, "creds.json")).get("me") or {}
    return {_bare(me.get("id")), _bare(me.get("lid"))} - {""}


def _phone(source):
    """The sender's phone number: their «…@s.whatsapp.net» id, else the shortest alias, as Hermes picks (a LID is
    longer); "" when only a LID is known."""
    raw = [str(getattr(source, k, "") or "") for k in ("user_id", "user_id_alt")]
    jid = next((r for r in raw if r.endswith("@s.whatsapp.net")), "")
    if jid:
        return _bare(jid)
    aliases = set().union(*(_aliases(r) for r in raw if r)) - {""}
    found = min(aliases, key=lambda a: (len(a), a)) if aliases else ""
    return found if re.fullmatch(r"\d{8,15}", found) and not any(r == f"{found}@lid" for r in raw) else ""


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
    await asyncio.to_thread(_deliver, chat, result, reply_to)
    if (result or {}).get("profiles_changed") and gateway is not None:
        await _serve_profiles(gateway)


async def _own_vinci(source, friend, gateway):
    """An active friend's message goes to their own Vinci. Hermes routed it before this hook, by the routes it read at
    boot: those miss a friend who connected since, and a sender the bridge names only by a LID. A route for this exact
    sender goes into the live set, which Hermes checks again when it admits the message."""
    profile = FRIEND_PROFILE_PREFIX + str(friend.get("slug") or "")
    sender = str(getattr(source, "user_id", "") or "")
    if gateway is None or not sender or getattr(source, "profile", None) == profile:
        return
    try:
        if profile not in gateway.served_profile_names():
            await _serve_profiles(gateway)
        if profile not in gateway.served_profile_names():
            logger.error("el Vinci de %s todavía no está servido: su mensaje va al de Vinci", friend.get("slug"))
            return
        from gateway.profile_routing import ProfileRoute
        from gateway.session_identity import clear_identity
        _LIVE_ROUTES[sender] = ProfileRoute(name=f"{LIVE_ROUTE}{friend.get('slug')}", platform="whatsapp",
                                            profile=profile, user_id=sender)
        _set_routes(gateway, gateway.config.profile_routes)
        clear_identity(source)  # drops what the boot routes resolved
        source.profile = profile
        logger.info("%s va a su propio Vinci (ruta en vivo)", friend.get("slug"))
    except Exception:
        logger.exception("no pude mandar a %s a su propio Vinci", friend.get("slug"))


async def _serve_profiles(gateway):
    """A friend's Vinci came or went: Hermes serves the change now (it rescans profiles/ every 30 s anyway) and takes
    the routes setup just wrote, with no restart."""
    try:
        await gateway.reconcile_served_profiles(reason="vinci-whatsapp")
        import yaml
        from gateway.profile_routing import parse_profile_routes
        from hermes_constants import get_process_hermes_home
        with open(get_process_hermes_home() / "config.yaml", encoding="utf-8") as fh:
            written = (yaml.safe_load(fh) or {}).get("gateway", {}).get("profile_routes") or []
        _set_routes(gateway, parse_profile_routes(written))
    except Exception:
        logger.exception("no pude actualizar los Vinci servidos; Hermes lo reintenta solo")


def _set_routes(gateway, base):
    served = set(gateway.served_profile_names())
    for sender in [s for s, route in _LIVE_ROUTES.items() if route.profile not in served]:
        del _LIVE_ROUTES[sender]  # a friend removed since
    routes = [r for r in base if not r.name.startswith(LIVE_ROUTE)] + list(_LIVE_ROUTES.values())
    gateway.config.profile_routes = sorted(routes, key=lambda r: -r.specificity)  # Hermes takes the first match


def _deliver(chat, result, reply_to):
    text, button = (result or {}).get("respuesta"), (result or {}).get("button")
    if not text:
        return
    reply = {"replyTo": reply_to} if reply_to else {}
    if (result or {}).get("image"):  # the token guide, right above the form's message
        _post("send-media", {"chatId": chat, "filePath": result["image"], "mediaType": "image"})
    if button:  # a page: a button that opens it inside WhatsApp (iPhone); the bare link on a bridge without the route
        try:
            _post("send-url-button", {"chatId": chat, "text": text, "buttonText": button["text"], "url": button["url"],
                                      **reply})
            return
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        text = f"{text}\n\n{button['url']}"
    mentions = {"mentions": result["menciones"]} if (result or {}).get("menciones") else {}
    _post("send", {"chatId": chat, "message": text, **reply, **mentions})


def _post(path, payload):
    request = urllib.request.Request(f"{BRIDGE}/{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def _relay_loop(ctx):
    try:  # one poller for the machine, whichever process loaded this copy first (the gateway, normally)
        lock = open(f"{RELAY}.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    while True:
        time.sleep(RELAY_EVERY)
        try:
            _inject_turns(ctx)
        except Exception:
            logger.exception("no pude retomar una pregunta del Académico")
        try:
            _close_quizzes()
        except Exception:
            logger.exception("no pude cerrar un quiz de grupo")
        try:
            if not _relay_waiting():
                continue
            proc = subprocess.run([BOT, "whatsapp-rele", "--json"], capture_output=True, timeout=600, env=_env())
            if proc.returncode != 0:
                message = proc.stderr.decode(errors="replace").strip().splitlines()
                logger.warning("whatsapp-rele: %s", message[-1] if message else proc.returncode)
                continue
            for answer in json.loads(proc.stdout.decode() or "{}").get("respuestas") or []:
                _deliver(answer["chat"], answer, None)  # a new friend's Vinci: _own_vinci serves it on their first message
        except Exception:
            logger.exception("no pude atender el relé")


def _turns_loop(ctx):
    while True:
        time.sleep(RELAY_EVERY)
        try:
            _inject_turns(ctx)
        except Exception:
            logger.exception("no pude retomar un turno en el perfil %s", PROFILE)


def _inject_turns(ctx):
    """Each turn queued for a session (relay.queue_turn), back in it; kept for a retry while the gateway cannot take
    it yet, dropped when it expires. A profile's copy takes only that profile's sessions («agent:<profile>:…»)."""
    try:
        names = sorted(n for n in os.listdir(TURNS) if n.endswith(".json"))
    except FileNotFoundError:
        return
    for name in names:
        path = os.path.join(TURNS, name)
        turn = _read_dict(path)
        session = str(turn.get("session") or "")
        if PROFILE and not session.startswith(f"agent:{PROFILE}:"):
            continue
        claimed = f"{path}.{os.getpid()}-{threading.get_ident()}"
        try:  # the other copy may be at the same file: only one gets to rename it
            os.rename(path, claimed)
        except FileNotFoundError:
            continue
        if not session or float(turn.get("expires") or 0) < time.time():
            logger.warning("un turno para %s venció sin volver a su chat", session or "?")
            os.remove(claimed)
        elif ctx.inject_message(str(turn.get("text") or ""), session_key=session):
            os.remove(claimed)
            logger.info("turno devuelto a su chat")
        else:
            os.rename(claimed, path)


def _close_quizzes():
    """The results of each group quiz not everyone finished, once its time is up (amigos.QUIZ_CLOSES)."""
    closes = _read_dict(QUIZ_CLOSES).get("quizzes") or {}
    now = _now()
    for group in sorted({c["grupo"] for c in closes.values() if datetime.fromisoformat(c["a"]) <= now}):
        proc = subprocess.run([BOT, "whatsapp-grupo", "cierre", group, "--json"], capture_output=True, timeout=120,
                              env=_env())
        if proc.returncode != 0:
            message = proc.stderr.decode(errors="replace").strip().splitlines()
            logger.warning("whatsapp-grupo cierre: %s", message[-1] if message else proc.returncode)
            continue
        _deliver(group, json.loads(proc.stdout.decode() or "{}"), None)


def _now():
    # AULA_NOW: the clock espol-bot keeps (aula_core.config.now_utc), which wrote the expiries these files hold
    return datetime.fromisoformat(os.environ["AULA_NOW"]) if os.environ.get("AULA_NOW") else datetime.now(timezone.utc)


def _relay_waiting():
    """Whether some link sent on WhatsApp may still post to the relay (relay.py's registry)."""
    data = _read_dict(RELAY)
    now = _now()
    if not data.get("url"):
        return False
    for box in (data.get("mailboxes") or {}).values():
        try:
            if datetime.fromisoformat(str(box.get("expires"))) > now:
                return True
        except ValueError:
            continue
    return False


