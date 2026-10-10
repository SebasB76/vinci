"""Friends on WhatsApp: each one gets a Vinci of their own, with their own aula.

A friend's Vinci is a Hermes profile (`amigo-<slug>`) whose tools, poll and token chain run against the friend's
own folder, `<data>/amigos/<slug>/` (secrets.env with their Canvas token, espol.db, material): the same code as the
captain's Vinci, pointed there by AULA_SECRETS, AULA_DATA_DIR and ESPOL_AMIGO. Hermes routes a WhatsApp message to
that profile by its sender's number, in the friend's private chat and in any group, so «@vinci ¿qué tengo esta
semana?» answers each person with their own aula, and one friend's tools never open another's data.

    1. The captain, in his WhatsApp chat with Vinci: «/amigo agregar 0991234567 Angel». Vinci writes to Angel's
       private chat with a one-time link (token_form.py, the page in WhatsApp mode).
    2. Angel creates a token in the aula, the page encrypts it on the phone and Angel pastes the ciphertext in the
       chat. The plugin of Hermes' default profile (hermes/whatsapp/plugin) hands it to `espol-bot amigo token`
       before Hermes sees it: the token reaches no model and no log.
    3. The token is verified and starts its own renewal chain, the aula is read once, and the profile, its crons
       and the routes are set up; the gateway restarts to load the routes.
    4. «/amigo quitar Angel» deletes the friend's tokens from the aula, the profile and the folder.

`whatsapp.json` (same folder as the registry) lists the groups where Vinci answers whoever mentions it; the
captain turns one on or off by writing «@vinci activa este grupo» there. Neither file holds a secret, so the
plugin reads them on every message.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from aula_core import Aula, queries, timefmt
from aula_core.canvas import CanvasError
from aula_core.config import ConfigError, config_path, load_config, update_secret_values
from aula_core.store import connect, file_lock, set_meta
from espol_bot import token_form, whatsapp
from espol_bot.store import ensure as store_ensure
from espol_bot.config import BotConfig, load_bot_config, whatsapp_settings
from espol_bot.token_renewal import RenewalError, TokenRenewal

log = logging.getLogger(__name__)

PENDING, ACTIVE = "pendiente", "activo"
PROFILE_PREFIX = "amigo-"


@dataclass
class Friend:
    slug: str
    nombre: str
    numero: str
    estado: str = PENDING
    agregado: str = ""


@dataclass
class Outcome:
    respuesta: str            # for the chat it came from, WhatsApp-formatted
    reiniciar: bool = False   # the routes changed: the gateway must restart to serve them

    def json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


# -- the two files ------------------------------------------------------------------------------

def root(cfg: BotConfig) -> Path:
    return cfg.core.data_dir / "amigos"


def registry_path(cfg: BotConfig) -> Path:
    return root(cfg) / "amigos.json"


def groups_path(cfg: BotConfig) -> Path:
    return root(cfg) / "whatsapp.json"


def _read(path: Path, key: str) -> list:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(key) or []
    except FileNotFoundError:
        return []


def _write(path: Path, data: dict) -> None:
    # Phone numbers: private, and replaced in one step so the plugin never reads half a file.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
                                     delete=False) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
    os.chmod(tmp.name, 0o600)
    os.replace(tmp.name, path)


def load(cfg: BotConfig) -> list[Friend]:
    return [Friend(**item) for item in _read(registry_path(cfg), "amigos")]


def save(cfg: BotConfig, friends: list[Friend]) -> None:
    _write(registry_path(cfg), {"amigos": [asdict(f) for f in friends]})


def active(cfg: BotConfig) -> list[Friend]:
    return [f for f in load(cfg) if f.estado == ACTIVE]


def groups(cfg: BotConfig) -> list[str]:
    return [str(g) for g in _read(groups_path(cfg), "grupos")]


def set_group(cfg: BotConfig, group: str, on: bool) -> bool:
    if not re.fullmatch(r"[\d-]+@g\.us", group):
        raise ConfigError(f"{group} no es el ID de un grupo de WhatsApp (termina en @g.us)")
    current = groups(cfg)
    wanted = sorted(set(current) | {group}) if on else [g for g in current if g != group]
    if wanted == current:
        return False
    _write(groups_path(cfg), {"grupos": wanted})
    return True


# -- one friend's world ------------------------------------------------------------------------

def folder(cfg: BotConfig, friend: Friend) -> Path:
    return root(cfg) / friend.slug


def profile_name(friend: Friend) -> str:
    return PROFILE_PREFIX + friend.slug


def env(cfg: BotConfig, friend: Friend) -> dict[str, str]:
    """What points the code at the friend's aula instead of the captain's (aula_core.config, config.py)."""
    base = folder(cfg, friend)
    return {"AULA_CONFIG": str(config_path()), "AULA_SECRETS": str(base / "secrets.env"),
            "AULA_DATA_DIR": str(base), "ESPOL_AMIGO": friend.slug}


@contextmanager
def scope(cfg: BotConfig, friend: Friend):
    """The friend's BotConfig, with this process' environment pointed at their folder until the block ends."""
    wanted = env(cfg, friend)
    saved = {key: os.environ.get(key) for key in wanted}
    os.environ.update(wanted)
    try:
        yield load_bot_config(load_config())
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _slug(name: str, taken: set[str]) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:24] or "amigo"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def find(friends: list[Friend], who: str) -> Friend | None:
    who = who.strip()
    try:
        number = whatsapp.normalize_number(who)
    except ConfigError:
        number = ""
    key = who.lower()
    return next((f for f in friends if f.numero == number or f.slug == key or f.nombre.lower() == key), None)


def _captain(cfg: BotConfig) -> str:
    wa = whatsapp_settings()
    if wa is None:
        raise ConfigError("Vinci no está en WhatsApp: falta WHATSAPP_CAPTAIN en secrets.env")
    return wa.captain


# -- the steps -----------------------------------------------------------------------------------

def add(cfg: BotConfig, number_text: str, name: str, now: datetime) -> Outcome:
    captain = _captain(cfg)
    number = whatsapp.normalize_number(number_text)
    name = re.sub(r"\s+", " ", name).strip()[:40]
    if not name:
        raise ConfigError("Dime también su nombre: /amigo agregar 0991234567 Angel")
    if number == captain:
        raise ConfigError("Ese es tu número: tu Vinci ya eres tú.")
    friends = load(cfg)
    friend = next((f for f in friends if f.numero == number), None)
    if friend and friend.estado == ACTIVE:
        return Outcome(f"{friend.nombre} ya tiene su Vinci.")
    if friend is None:
        friend = Friend(_slug(name, {f.slug for f in friends}), name, number, PENDING, timefmt.iso(now))
        friends.append(friend)
    base = folder(cfg, friend)
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    update_secret_values({"WHATSAPP_OWNER": number}, path=base / "secrets.env")
    with scope(cfg, friend) as fcfg:
        conn = connect(fcfg.core.db_path)
        try:
            with file_lock(fcfg.core.data_dir, "bot.lock"):
                form = token_form.new_form(fcfg, conn, now, _invitation(friend), ttl=token_form.AUTO_FORM_TTL)
        finally:
            conn.close()
    whatsapp.WhatsApp(number, cfg.whatsapp_bridge).send(form["respuesta"])
    save(cfg, friends)
    log.info("amigo agregar: %s (pendiente)", friend.slug)
    return Outcome(f"Le escribí a {friend.nombre} por privado con el enlace para su token. Cuando lo pegue, armo su "
                   "Vinci y te aviso.")


def _invitation(friend: Friend) -> str:
    return (f"👋 Hola, {friend.nombre}: soy Vinci, un asistente del aula virtual de ESPOL. Te digo qué tienes "
            "pendiente, tus anuncios y tus notas, te aviso lo nuevo por aquí y te ayudo a estudiar con tu material. "
            "Para leer tu aula necesito un token tuyo; yo solo leo.\n\n")


def submit_token(cfg: BotConfig, number: str, data: str, now: datetime) -> Outcome:
    """The ciphertext a friend pasted in the chat: their token, verified; the first time, their whole Vinci."""
    friends = load(cfg)
    friend = next((f for f in friends if f.numero == number), None)
    if friend is None:
        raise ConfigError("ese número no es de ningún amigo")
    with scope(cfg, friend) as fcfg:
        result = token_form.submit(fcfg, data, now)
        if not result.get("ok"):
            return Outcome(whatsapp.from_html(result["respuesta"]))
        if friend.estado == ACTIVE:  # a new token after the chain broke
            return Outcome("✅ Listo, ya vuelvo a leer tu aula.")
        try:
            names = _first_read(fcfg, now)
        except CanvasError as exc:
            return Outcome(f"✅ Tu token funciona, pero no pude leer tu aula ahora ({exc}). Lo intento solo en un rato.")
    friend.estado = ACTIVE
    save(cfg, friends)
    _provision(cfg)
    listed = ", ".join(names[:8]) + ("…" if len(names) > 8 else "")
    try:
        whatsapp.WhatsApp(_captain(cfg), cfg.whatsapp_bridge).send(
            f"✅ {friend.nombre} ya tiene su Vinci: veo sus {len(names)} materias.")
    except whatsapp.WhatsAppError as exc:
        log.warning("no pude avisarle al capitán: %s", exc)
    log.info("amigo token: %s activo (%d materias)", friend.slug, len(names))
    return Outcome(f"✅ Listo, {friend.nombre}: ya veo tus {len(names)} materias ({listed}). Escríbeme aquí, o "
                   "mencióname en el grupo con @vinci, y te contesto con lo tuyo. Lo nuevo del aula y lo que vence "
                   "te lo aviso por aquí.", reiniciar=True)


def _first_read(fcfg: BotConfig, now: datetime) -> list[str]:
    """The aula once, without material (the poll brings it a slice at a time); the poll's welcome is not needed."""
    with file_lock(fcfg.core.data_dir, "bot.lock"):
        aula = Aula(fcfg.core)
        try:
            aula.sync(materials=False)
            set_meta(aula.conn, "bot_welcomed", timefmt.iso(now))
            aula.conn.commit()
            return [c["nombre"] for c in queries.courses(aula.conn)]
        finally:
            aula.close()


def remove(cfg: BotConfig, who: str, now: datetime) -> Outcome:
    friends = load(cfg)
    friend = find(friends, who)
    if friend is None:
        return Outcome(f"No tengo a ningún amigo «{who}». Escribe /amigos para ver la lista.")
    revoked = 0
    with scope(cfg, friend) as fcfg:
        if (folder(cfg, friend) / "secrets.env").exists():
            conn = connect(fcfg.core.db_path)
            try:
                with file_lock(fcfg.core.data_dir, "bot.lock"):
                    revoked = TokenRenewal(fcfg.core, conn, now).revoke()
            except (RenewalError, ConfigError) as exc:
                log.warning("amigo quitar %s: tokens: %s", friend.slug, exc)
            finally:
                conn.close()
    save(cfg, [f for f in friends if f.slug != friend.slug])
    from espol_bot import hermes_setup
    hermes_setup.Setup(cfg).drop_friend(friend)
    shutil.rmtree(folder(cfg, friend), ignore_errors=True)
    _provision(cfg)
    log.info("amigo quitar: %s (%d tokens borrados)", friend.slug, revoked)
    tokens = f" y {revoked} token{'s' if revoked != 1 else ''} suyo{'s' if revoked != 1 else ''} del aula" if revoked else ""
    return Outcome(f"Listo: quité a {friend.nombre}. Borré su Vinci, sus datos{tokens}.",
                   reiniciar=friend.estado == ACTIVE)


def listing(cfg: BotConfig) -> Outcome:
    friends = load(cfg)
    if not friends:
        return Outcome("Todavía no agregaste a nadie. Para agregar: /amigo agregar 0991234567 Angel")
    lines = [f"- {f.nombre}: {'tiene su Vinci' if f.estado == ACTIVE else 'esperando su token'}" for f in friends]
    return Outcome("Tus amigos en Vinci:\n" + "\n".join(lines))



def command(cfg: BotConfig, name: str, number: str, data: str, now: datetime) -> Outcome:
    """Vinci's own slash commands on WhatsApp, for the captain or an active friend, each over their own aula:
    /start, /estado and /token, plus the ciphertext the captain pastes after his /token, and a vote on one of
    the polls that stand in for a card's buttons (`data`: {"encuesta", "opcion"})."""
    captain = number == _captain(cfg)
    friend = None if captain else next((f for f in active(cfg) if f.numero == number), None)
    if not captain and friend is None:
        raise ConfigError("ese número no tiene su Vinci")
    if name == "start":
        return Outcome(_greeting(friend))
    if name in ("voto", "marca", "entregas"):
        act = {"voto": _vote, "marca": _mark, "entregas": _deliverables}[name]
        if friend is None:
            return act(cfg, data, now)
        with scope(cfg, friend) as fcfg:
            return act(fcfg, data, now)
    if friend is None:
        return Outcome(whatsapp.from_html(_command_html(cfg, name, data, now)))
    if name == "token-cifrado":
        return submit_token(cfg, number, data, now)
    with scope(cfg, friend) as fcfg:
        return Outcome(whatsapp.from_html(_command_html(fcfg, name, data, now)))


MARK_RE = re.compile(r"\s*([st])(\d{1,12})\s+(ok|no)\b", re.I)


def _mark(cfg: BotConfig, data: str, now: datetime) -> Outcome:
    """«/marca s123 ok», what a tick on the dashboard types in the chat: the «✅ Ya lo entregué» / «✅ Hecho» button."""
    from espol_bot import botones
    match = MARK_RE.match(data or "")
    if not match:
        return Outcome("Así: /marca s123 ok (una tarea) o /marca t7 ok (de tu lista); «no» lo deshace.")
    answer = botones.handle(cfg, f"v1:{match[1].lower()}:{match[2]}:{match[3].lower()}", now)
    return Outcome(whatsapp.from_html(answer.get("respuesta") or answer.get("aviso") or ""))


def _deliverables(cfg: BotConfig, data: str, now: datetime) -> Outcome:
    """/entregas: a link to the dashboard with this aula's deliverables, ticks pointed back at this chat."""
    from espol_bot import dashboard, materias
    aula = Aula(cfg.core)
    try:
        conn = store_ensure(aula.conn)
        url = dashboard.whatsapp_url(conn, cfg, materias.load(cfg.core), now, whatsapp.own_number())
    finally:
        aula.close()
    if url is None:
        return Outcome("El panel de entregas está apagado en esta instalación.")
    return Outcome(f"📋 Tus entregas, el semestre y lo nuevo del aula: {url}\n\nAl marcar una en el panel, vuelves a "
                   "este chat con el mensaje listo: envíalo y la cuento.")


def _vote(cfg: BotConfig, data: str, now: datetime) -> Outcome:
    """What the button behind a poll option does; nothing for a poll that is not ours or an option that does nothing."""
    from espol_bot import botones
    vote = json.loads(data or "{}")
    options = whatsapp.read_polls(cfg.core.data_dir).get(str(vote.get("encuesta") or ""))
    callback = (options or {}).get(str(vote.get("opcion") or "").strip())
    if not callback:
        return Outcome("")
    quiz_vote = re.fullmatch(r"q:([A-Z0-9]{2,12}):(\d)", callback)
    if quiz_vote:
        from espol_bot import quiz
        return Outcome(whatsapp.from_html(quiz.answer(cfg.core, quiz_vote[1], str(vote["encuesta"]),
                                                      int(quiz_vote[2]), now)))
    answer = botones.handle(cfg, callback, now)
    return Outcome(whatsapp.from_html(answer.get("respuesta") or answer.get("aviso") or ""))


def _command_html(cfg: BotConfig, name: str, data: str, now: datetime) -> str:
    from espol_bot import health
    if name == "estado":
        conn = health.open_readonly(cfg.core.db_path)
        try:
            return health.telegram_report(health.checks(cfg, conn, now), now, cfg.core.tz)
        finally:
            if conn is not None:
                conn.close()
    if name == "token":
        return token_form.open_form(cfg, now, whatsapp=True)["respuesta"]
    return token_form.submit(cfg, data, now, whatsapp=True)["respuesta"]


def _greeting(friend: Friend | None) -> str:
    lines = [f"👋 ¡Hola{', ' + friend.nombre if friend else ''}! Soy Vinci, "
             f"{'tu pana' if friend else 'tu guía'} para el aula virtual de ESPOL.",
             "",
             "*Pregúntame lo que sea*",
             "• «¿Qué tengo esta semana?», «¿qué pide el taller 2?», «¿cómo voy en Cálculo?»",
             "• Te explico el material citando la página, y busco exámenes anteriores",
             "• «Anota: estudiar el cap. 3 para el viernes» y te lo recuerdo",
             "• «Hazme diapositivas de …» y te mando el .pptx",
             "",
             "*Comandos*",
             "/entregas · tu panel de entregas y lo nuevo del aula",
             "/quiz <tema> · un quiz con encuestas",
             "/estado · cómo va la lectura de tu aula",
             "/token · poner un token nuevo del aula",
             "/new · empezar la conversación de cero",
             "",
             "En un grupo, mencióname con @vinci y te contesto con lo tuyo."]
    if friend is None:
        lines += ["", "*Tus amigos*", "/amigo agregar <número> <nombre> · /amigo quitar <nombre> · /amigos",
                  "", "Los avisos del aula y el resumen de las 7:00 te llegan aquí y en Telegram. Crear o archivar bots "
                  "de materia sigue en Telegram."]
    return "\n".join(lines)


def _provision(cfg: BotConfig) -> None:
    """Every friend's profile and the WhatsApp routes, as setup.sh leaves them."""
    from espol_bot import hermes_setup
    setup = hermes_setup.Setup(cfg)
    for friend in active(cfg):
        setup.friend(friend)
    setup.whatsapp_on()
