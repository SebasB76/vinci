"""The team of subject bots: Vinci creates, provisions and archives them from chat.

The model never does it itself. Its tools (herramientas.py) only *show* a card with
buttons; the captain's press, handled without the model by the `vinci-botones` plugin
(`espol-bot boton`), is what creates or archives a bot:

  1. `proponer_equipo` reads the courses of the aula virtual, adds one subject per ESPOL code
     to materias.toml ("pendiente"; its theory and práctico courses go to the same subject)
     and shows the team with a «➕ Crear» button each.
  2. «➕ Crear <bot>» marks the subject "esperando_bot" and sends a Telegram keyboard
     button that creates the bot for Vinci to manage (Bot API 9.6 managed bots: the captain
     confirms name and username in Telegram's own screen; the name suggested is its
     subject's, «Estadística»). If Vinci may not manage bots yet, it sends the
     @BotFather steps instead.
  3. The new bot arrives as a `managed_bot_created` service message (its token is fetched
     with getManagedBotToken) or as BotFather's reply forwarded by the captain. The plugin
     catches either before Hermes sees it (so it never reaches the model or a session log),
     deletes any message carrying a token, and runs `espol-bot bot-creado` / `espol-bot
     token`: the token goes to secrets.env (mode 600) and the subject's Hermes profile, cron
     agenda and plugin are created (idempotent), and the bot gets its subject's name and
     its photo from the party. The multiplexing gateway serves the new profile by itself within a minute.
  4. «🗄️ Archivar» / «♻️ Reactivar» park or unpark the subject's gateway and pause or resume
     its agenda; memory and notebook stay.
"""

from __future__ import annotations

import contextlib
import itertools
import re
import sys
import zlib
from dataclasses import replace

from aula_core import queries
from aula_core.config import load_secret_values, secrets_path
from aula_core.queries import fold
from aula_core.store import file_lock
from espol_bot import materias
from espol_bot.config import BotConfig, TelegramSecrets, captain_id, load_telegram_secrets, token_key
from espol_bot.hermes_setup import Setup, upsert_env
from espol_bot.messages import e
from espol_bot.telegram import Telegram, TelegramError

TOKEN_RE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")
WAITING = "esperando_bot"
TO_CREATE = ("pendiente", WAITING)
USERNAME_MAX = 32  # Telegram's cap on a bot's username, «bot» included
STATE_LABEL = {"pendiente": "➕ por crear", WAITING: "⏳ esperando su bot", "activa": "✅ activo",
               "archivada": "🗄️ archivado"}


def suggested_username(subject: materias.Subject) -> str:
    """vinci_<words of the bot's name>_bot within USERNAME_MAX: the words that fit with the most letters,
    the later ones on a tie ('Ciencias de la Sostenibilidad' → vinci_sostenibilidad_bot); vinci_<code>_bot
    when none fits."""
    words = [w for w in re.findall(r"[a-z0-9]+", fold(subject.display).lower()) if w not in materias.SMALL_WORDS][:8]
    room = USERNAME_MAX - len("vinci__bot")
    subsets = [c for n in range(len(words), 0, -1) for c in itertools.combinations(words, n)]
    slug = max((s for s in map("_".join, reversed(subsets)) if len(s) <= room), key=len, default=subject.code.lower())
    return f"vinci_{slug}_bot"


def propose(cfg: BotConfig, conn) -> tuple[list[materias.Subject], list[str], list[materias.Subject]]:
    """(team, notes, gone): the current team merged with the active aula courses. Existing
    entries keep their name, username and state; a course of a known subject (its práctico, say)
    joins that subject; a course of a new subject comes in as 'pendiente'."""
    team, notes = list(materias.load(cfg.core)), []
    courses = queries.courses(conn)
    for course in courses:
        code = materias.base_code(course["codigo"])
        if code is None:
            notes.append(f"«{course['nombre']}» no tiene un código ESPOL reconocible ({course['codigo']}); la salto.")
            continue
        existing = materias.for_course(team, course["id"], course["codigo"])
        if existing:
            if course["id"] not in existing.course_ids:
                team[team.index(existing)] = replace(existing, course_ids=(*existing.course_ids, course["id"]))
            continue
        team.append(materias.Subject(code=code, name=materias.short_name(course["nombre"]), course_ids=(course["id"],)))
    active_ids = {c["id"] for c in courses}
    gone = [s for s in team if s.state == "activa" and s.course_ids and not active_ids & set(s.course_ids)]
    return team, notes, gone


def sync_team(cfg: BotConfig, conn) -> tuple[list[materias.Subject], list[str], list[materias.Subject]]:
    with file_lock(cfg.core.data_dir, "equipo.lock"):
        team, notes, gone = propose(cfg, conn)
        materias.save(cfg.core, team)
    return team, notes, gone


def team_card(team: list[materias.Subject], notes: list[str], gone: list[materias.Subject]) -> tuple[str, list]:
    lines = ["🤖 <b>Tu equipo de bots</b> (uno por materia)", ""]
    for s in team:
        handle = f" · {e(s.handle())}" if s.username else ""
        lines.append(f"• <b>{e(s.display)}</b> ({s.code}) — {STATE_LABEL[s.state]}{handle}")
    lines += [f"⚠️ {e(n)}" for n in notes]
    lines += [f"⚠️ {e(s.display)} ya no aparece en tu aula virtual: puedes archivarlo." for s in gone]
    todo = [s for s in team if s.state in TO_CREATE]
    if todo:
        lines += ["", "Pulsa «Crear» en cada materia que quieras: te guío para crear su bot en Telegram y yo lo "
                      "configuro. El token nunca llega al modelo."]
    return "\n".join(lines), [(f"➕ Crear {s.display}", f"v1:c:0:{s.code}") for s in todo][:8]


def creation_message(subject: materias.Subject, can_manage: bool) -> tuple[str, dict | None]:
    """What Vinci sends after «Crear»: the managed-bot button, or the @BotFather steps."""
    username = suggested_username(subject)
    if can_manage:
        text = (f"🤖 <b>Creemos {e(subject.display)}</b>\n"
                f"Pulsa el botón de abajo. Telegram te muestra el bot nuevo con el nombre «{e(subject.display)}» y el "
                f"usuario @{username} (puedes cambiarlos); al confirmarlo me lo comparte y yo lo configuro solo. "
                "El token no pasa por el chat.")
        # Telegram's create-bot screen adds its own fixed «bot»: suggest the username without it.
        request = {"request_id": zlib.crc32(subject.code.encode()) & 0x7FFFFFFF,
                   "suggested_name": subject.display, "suggested_username": username.removesuffix("bot")}
        markup = {"keyboard": [[{"text": f"🤖 Crear {subject.display}", "request_managed_bot": request}]],
                  "resize_keyboard": True, "one_time_keyboard": True}
        return text, markup
    text = (f"🤖 <b>Creemos {e(subject.display)}</b>\n"
            "1. Abre @BotFather y envía /newbot.\n"
            f"2. Nombre: <code>{e(subject.display)}</code>\n"
            f"3. Usuario: <code>{username}</code> (o cualquiera libre que termine en «bot»).\n"
            "4. Reenvíame aquí la respuesta de BotFather (la que trae el token). La borro del chat apenas llega y el "
            "token no pasa por el modelo.\n"
            "💡 Para que la próxima vez sea un solo toque: en @BotFather abre la Mini App, elige a Vinci y activa la "
            "opción para que gestione otros bots.")
    return text, None


def _reply(text: str | None, code: str | None = None, *, remove_keyboard: bool = False) -> dict:
    return {"respuesta": text, "materia": code, "quitar_teclado": remove_keyboard}


def _match(team: list[materias.Subject], me: dict) -> materias.Subject | None:
    """The subject a new bot belongs to: by the name/username suggested for it, else the one
    subject waiting for its bot."""
    candidates = [s for s in team if s.state in TO_CREATE]
    named = [s for s in candidates if me.get("first_name") == s.display or me.get("username") == suggested_username(s)]
    if len(named) == 1:
        return named[0]
    waiting = [s for s in candidates if s.state == WAITING]
    return waiting[0] if len(waiting) == 1 else None


def register_token(cfg: BotConfig, token: str, *, quiet_if_known: bool = False, hermes_bin: str | None = None) -> dict:
    """A new subject bot's token (never shown to the model): check it with Telegram, store it
    in secrets.env (600) and create the subject's Hermes profile. Returns what to tell the captain."""
    token = token.strip()
    if not TOKEN_RE.fullmatch(token):
        return _reply("⚠️ Eso no parece el token de un bot (se ve como <code>123456789:AA…</code>).")
    with file_lock(cfg.core.data_dir, "equipo.lock"):
        secrets = load_secret_values()
        owner = next((k for k, v in secrets.items() if k.startswith("TELEGRAM_BOT_TOKEN") and v == token), None)
        if owner == token_key():
            return _reply("⚠️ Ese es el token de Vinci. Cada materia necesita su propio bot nuevo.")
        team = materias.load(cfg.core)
        if owner:
            if quiet_if_known:
                return _reply(None)
            known = materias.by_code(team, owner.removeprefix("TELEGRAM_BOT_TOKEN_"))
            if known is None:
                return _reply(f"ℹ️ Ese token ya está guardado ({e(owner)}), pero no tengo esa materia.")
            with contextlib.redirect_stdout(sys.stderr):  # finish a setup that was interrupted
                Setup(cfg, hermes_bin=hermes_bin).subject(known)
            return _reply(f"ℹ️ Ese bot ya estaba configurado como <b>{e(known.display)}</b>; lo revisé y está al día.",
                          known.code, remove_keyboard=True)
        try:
            me = Telegram(TelegramSecrets(token, captain_id(secrets)), api=cfg.telegram_api).get_me()
        except TelegramError as exc:
            return _reply(f"⚠️ Telegram no aceptó ese token ({e(str(exc))}). Revisa que esté completo.")
        subject = _match(team, me)
        if subject is None:
            waiting = [s.display for s in team if s.state in TO_CREATE]
            hint = (f" Pulsa primero «Crear» en la materia que es ({', '.join(waiting)})." if waiting else
                    " Pídeme primero «arma mi equipo».")
            return _reply("⚠️ No sé de qué materia es ese bot, así que no lo guardé." + e(hint)
                          + " Por seguridad, revoca ese token en @BotFather (/revoke).")
        upsert_env(secrets_path(), {token_key(subject.code): token})
        subject = materias.update(cfg.core, subject.code, username=me.get("username") or subject.username,
                                  state="activa")
        with contextlib.redirect_stdout(sys.stderr):
            Setup(cfg, hermes_bin=hermes_bin).subject(subject)
    return _reply(f"✅ <b>{e(subject.display)}</b> quedó creado y activo: {e(subject.handle())}.\n"
                  f"Ábrelo y mándale /start; en un minuto ya te responde. Con tu horario guardado, te mandará su brief "
                  f"{cfg.brief_minutes} minutos antes de cada clase.", subject.code, remove_keyboard=True)


def managed_bot_created(cfg: BotConfig, bot_id: int, *, hermes_bin: str | None = None) -> dict:
    """The captain created a bot for Vinci to manage: fetch its token from Telegram and register it."""
    try:
        token = Telegram(load_telegram_secrets(), api=cfg.telegram_api).managed_bot_token(bot_id)
    except TelegramError as exc:
        return _reply(f"⚠️ No pude obtener el token del bot nuevo ({e(str(exc))}). Pulsa «Crear» otra vez.")
    return register_token(cfg, token, quiet_if_known=True, hermes_bin=hermes_bin)


def set_archived(cfg: BotConfig, code: str, archive: bool) -> str:
    """Archive (park the gateway, pause the agenda) or reactivate a subject bot. Returns HTML."""
    with file_lock(cfg.core.data_dir, "equipo.lock"):
        subject = materias.by_code(materias.load(cfg.core), code)
        if subject is None:
            return f"⚠️ No tengo una materia {e(code)}."
        if subject.state in TO_CREATE:
            return f"ℹ️ <b>{e(subject.display)}</b> todavía no tiene bot."
        subject = materias.update(cfg.core, subject.code, state="archivada" if archive else "activa")
        with contextlib.redirect_stdout(sys.stderr):
            Setup(cfg).subject(subject)
    if archive:
        return (f"🗄️ <b>{e(subject.display)}</b> quedó archivado: ya no manda briefs ni responde. Su memoria y su "
                "cuaderno siguen guardados; si lo necesitas otra vez, pídeme reactivarlo.")
    return f"♻️ <b>{e(subject.display)}</b> está activo otra vez; en un minuto vuelve a responder."
