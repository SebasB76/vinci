"""System health for `espol-bot doctor` and Vinci's /estado: read-only, no Canvas call, no model.

Everything comes from what the no-agent jobs leave in espol.db (their last run, the last sync, the
token chain, when each feed was last read) and from which feeds secrets.env holds, never their URLs.

Thresholds (P = intervalo_minutos, 30 by default):
  poll            ❌ when its last run is older than 2·P (at least one run missed)
  aula sync       ⚠️ when older than 2·P (the feeds may still carry dates and announcements)
  maintenance     ❌ when older than 25 min (it runs every 10; the token dies at one hour)
  token           ⚠️ from 50 min old (a renewal missed), ❌ from 60 min or when Canvas refused it
  each feed       ❌ when the last maintenance failed to read it, ⚠️ when not read for 25 min
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from aula_core import PAUSED_KEY, REFUSED_KEY, feeds, timefmt, token_fingerprint
from aula_core.config import ConfigError, load_secret_values
from aula_core.store import set_meta
from espol_bot import token_renewal
from espol_bot.config import BotConfig

POLL_RUN = "bot_run_poll"
MAINTENANCE_RUN = "bot_run_maintenance"
MAINTENANCE_LATE = timedelta(minutes=25)  # hermes_setup runs it every 10 minutes
FEED_LATE = MAINTENANCE_LATE              # the maintenance reads every feed
TOKEN_LATE = token_renewal.RENEW_AFTER + timedelta(minutes=10)
TOKEN_DEAD = timedelta(hours=1)           # ESPOL silently invalidates a personal token after an hour

OK, WARN, FAIL = "ok", "warn", "fail"
ICON = {OK: "✅", WARN: "⚠️", FAIL: "❌"}


@dataclass(frozen=True)
class Check:
    name: str
    level: str
    detail: str
    fix: str | None = None  # a command the captain runs in a terminal
    chat_fix: str | None = None  # or what they send Vinci instead; /estado offers only this one


def record_run(conn: sqlite3.Connection, key: str, now: datetime, **details) -> None:
    set_meta(conn, key, json.dumps({"at": timefmt.iso(now), **details}, ensure_ascii=False))
    conn.commit()


def open_readonly(db_path: Path) -> sqlite3.Connection | None:
    """espol.db without creating or migrating anything; None before the first sync made it."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def checks(cfg: BotConfig, conn: sqlite3.Connection | None, now: datetime) -> list[Check]:
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall()) if conn is not None else {}
    try:
        secrets = load_secret_values()
    except ConfigError:
        secrets = {}
    ago = _Ago(now, cfg.core.tz)
    return [_poll(cfg, meta, now, ago), _sync(cfg, meta, now, ago), _maintenance(meta, now, ago),
            _token(meta, secrets, now, ago), *_feeds(meta, secrets, now, ago)]


class _Ago:
    def __init__(self, now: datetime, tz):
        self.now, self.tz = now, tz

    def __call__(self, moment: datetime) -> str:
        local = moment.astimezone(self.tz)
        clock = f"{local:%H:%M}" if local.date() == self.now.astimezone(self.tz).date() else timefmt.human(moment, self.tz)
        when = "hace un momento" if self.now - moment < timedelta(minutes=1) else timefmt.until(moment, self.now)
        return f"{when} ({clock})"


def _run(meta: dict[str, str], key: str) -> tuple[datetime | None, dict]:
    try:
        run = json.loads(meta.get(key) or "{}")
    except ValueError:
        run = {}
    return timefmt.parse(run.get("at")), run


def _bot_command(name: str) -> str:
    return f"{Path(sys.executable).with_name('espol-bot')} {name}"


def _poll(cfg: BotConfig, meta: dict[str, str], now: datetime, ago: _Ago) -> Check:
    name, every = "Sondeo", timedelta(minutes=cfg.poll_minutes)
    at, run = _run(meta, POLL_RUN)
    if at is None and meta.get("initialized"):  # just installed, or updated from before runs were recorded
        return Check(name, WARN, f"todavía no registra ninguna corrida: la primera llega en menos de "
                     f"{cfg.poll_minutes} min; si no, revisa el gateway de Hermes.")
    if at is None:
        return Check(name, FAIL, "todavía no ha corrido nunca: sin él no llegan avisos ni recordatorios.",
                     "hermes gateway status")
    if now - at > 2 * every:
        return Check(name, FAIL, f"no corre desde {ago(at)}; debería cada {cfg.poll_minutes} min. Sin él no te "
                     "llegan avisos ni recordatorios: ¿la PC estuvo apagada o se detuvo el gateway de Hermes?",
                     "hermes gateway status")
    if run.get("error"):
        return Check(name, WARN, f"corrió {ago(at)}, con un problema: {run['error']}")
    return Check(name, OK, f"corrió {ago(at)}; corre cada {cfg.poll_minutes} min.")


def _sync(cfg: BotConfig, meta: dict[str, str], now: datetime, ago: _Ago) -> Check:
    name = "Aula virtual"
    last = timefmt.parse(meta.get("last_sync"))
    paused = timefmt.parse(meta.get(PAUSED_KEY))
    pause = (f" Canvas pidió bajar el ritmo: no lo leo hasta las {paused.astimezone(cfg.core.tz):%H:%M}."
             if paused and now < paused else "")
    if last is None:
        return Check(name, FAIL, "nunca se leyó con el token de Canvas." + pause)
    if now - last > timedelta(minutes=2 * cfg.poll_minutes):
        return Check(name, WARN, f"leída por última vez {ago(last)}: lo guardado puede estar desactualizado; los "
                     "feeds sin token siguen trayendo fechas y anuncios si están activos." + pause)
    return Check(name, WARN if pause else OK, f"leída {ago(last)}." + pause)


def _maintenance(meta: dict[str, str], now: datetime, ago: _Ago) -> Check:
    name = "Mantenimiento"
    at, run = _run(meta, MAINTENANCE_RUN)
    if at is None and meta.get("initialized"):
        return Check(name, WARN, "todavía no registra ninguna corrida: la primera llega en menos de 10 min; si "
                     "no, revisa el gateway de Hermes.")
    if at is None:
        return Check(name, FAIL, "todavía no ha corrido nunca: es el que renueva el token antes de que venza.",
                     "hermes gateway status")
    if now - at > MAINTENANCE_LATE:
        return Check(name, FAIL, f"no corre desde {ago(at)}; debería cada 10 min. Sin él el token de Canvas "
                     "vence a la hora y la cadena se corta.", "hermes gateway status")
    return Check(name, OK, f"corrió {ago(at)}; corre cada 10 min.")


def _token(meta: dict[str, str], secrets: dict[str, str], now: datetime, ago: _Ago) -> Check:
    name = "Token de Canvas"
    current = secrets.get("CANVAS_TOKEN", "")
    if not current:
        return Check(name, FAIL, "falta CANVAS_TOKEN en secrets.env.", _bot_command("resembrar"), "/token")
    fingerprint = token_fingerprint(current)
    if meta.get(REFUSED_KEY) == fingerprint:
        return Check(name, FAIL, "la cadena de renovación está cortada: Canvas rechazó el token actual. Crea un "
                     "token nuevo en el aula (Configuración → Nuevo token de acceso) y resiémbralo con el "
                     "formulario de /token, que lo cifra antes de enviarlo; no lo pegues en el chat.",
                     _bot_command("resembrar"), "/token")
    if meta.get(token_renewal.DISABLED) == "server-fixed":
        return Check(name, OK, "la renovación automática se apagó sola porque ESPOL ya no vence los tokens a la "
                     "hora; el actual dura meses.")
    _, maintenance = _run(meta, MAINTENANCE_RUN)
    failed = f" La última renovación falló: {maintenance['renewal_error']}" if maintenance.get("renewal_error") else ""
    born = (timefmt.parse(meta.get(token_renewal.CURRENT_CREATED))
            if meta.get(token_renewal.CURRENT_FINGERPRINT) == fingerprint else None)
    if born is None:
        return Check(name, WARN, "todavía no sé su edad: el próximo mantenimiento lo renueva y la empieza a "
                     "contar." + failed)
    renew = int(token_renewal.RENEW_AFTER.total_seconds() // 60)
    age = now - born
    if age >= TOKEN_DEAD:
        return Check(name, FAIL, f"se creó {ago(born)} y no se ha renovado: ESPOL invalida los tokens a la hora, "
                     "así que ya no sirve. Si el próximo mantenimiento no lo logra, la cadena se corta." + failed,
                     _bot_command("mantenimiento"))
    if age >= TOKEN_LATE or failed:
        return Check(name, WARN, f"se creó {ago(born)}; ya debió renovarse (a los {renew} min, antes de la hora en "
                     "que ESPOL lo invalida)." + failed)
    return Check(name, OK, f"renovado {ago(born)}; la cadena está sana (se renueva a los {renew} min, ESPOL lo "
                 "invalida a la hora).")


def _feeds(meta: dict[str, str], secrets: dict[str, str], now: datetime, ago: _Ago) -> list[Check]:
    calendar = secrets.get(feeds.CALENDAR_KEY, "").strip()
    announcements = secrets.get(feeds.ANNOUNCEMENTS_KEY, "").split()
    if not calendar and not announcements:
        return [Check("Feeds sin token", WARN, "no están configurados: si la cadena del token se corta, dejan de "
                      "llegar fechas y anuncios. Copia del aula la Fuente del calendario y el RSS de Anuncios de "
                      "cada materia y guárdalos una vez.", _bot_command("feeds"))]
    ran, maintenance = _run(meta, MAINTENANCE_RUN)
    errors = maintenance.get("feed_errors") or []

    def one(name: str, what: str, read: datetime | None, prefix: str) -> Check:
        error = next((e.split(": ", 1)[-1] for e in errors if e.startswith(prefix)), None)
        if error and (read is None or (ran is not None and read < ran)):
            return Check(name, FAIL, f"{what}el último mantenimiento no pudo leerlo ({error}).",
                         _bot_command("feeds"))
        if read is None:
            return Check(name, WARN, f"{what}configurado, pero todavía no se ha leído.")
        if now - read > FEED_LATE:
            return Check(name, WARN, f"{what}leído por última vez {ago(read)}.")
        return Check(name, OK, f"{what}activo, leído {ago(read)}.")

    found = []
    if calendar:
        found.append(one("Calendario (iCal)", "",
                         timefmt.parse(meta.get("feeds_calendar_seeded")), "calendario:"))
    else:
        found.append(Check("Calendario (iCal)", WARN, "sin configurar: las fechas solo llegan con el token.",
                           _bot_command("feeds")))
    if announcements:
        reads = [timefmt.parse(meta.get(feeds.announcements_key(url))) for url in announcements]
        oldest = None if None in reads else min(reads)
        what = "" if len(announcements) == 1 else f"{len(announcements)} feeds; el más atrasado: "
        found.append(one("Anuncios (RSS/Atom)", what, oldest, "anuncios:"))
    else:
        found.append(Check("Anuncios (RSS/Atom)", WARN, "sin configurar: los anuncios solo llegan con el token.",
                           _bot_command("feeds")))
    return found


def _headline(found: list[Check]) -> tuple[str, str]:
    problems = sum(c.level == FAIL for c in found)
    warnings = sum(c.level == WARN for c in found)
    if problems:
        return FAIL, f"{problems} {'cosa falla' if problems == 1 else 'cosas fallan'}" + (
            f" y {warnings} para revisar" if warnings else "")
    if warnings:
        return WARN, f"{warnings} {'cosa' if warnings == 1 else 'cosas'} para revisar"
    return OK, "todo en orden"


def terminal_report(found: list[Check], now: datetime, tz) -> str:
    level, summary = _headline(found)
    lines = [f"Estado de Vinci · {timefmt.human(now, tz)}: {ICON[level]} {summary}", ""]
    for check in found:
        lines.append(f"{ICON[check.level]} {check.name}: {check.detail}")
        if check.chat_fix and check.fix:
            lines.append(f"   → {check.chat_fix} en el chat de Vinci, o aquí: {check.fix}")
        elif check.fix:
            lines.append(f"   → {check.fix}")
    return "\n".join(lines)


def telegram_report(found: list[Check], now: datetime, tz) -> str:
    level, summary = _headline(found)
    lines = [f"🩺 <b>Estado de Vinci</b> · {escape(timefmt.human(now, tz))}", f"{ICON[level]} {escape(summary.capitalize())}", ""]
    for check in found:
        fix = ("" if check.level == OK else f" Mándame <code>{escape(check.chat_fix)}</code>." if check.chat_fix else
               f" En una terminal: <code>{escape(check.fix)}</code>" if check.fix else "")
        lines.append(f"{ICON[check.level]} <b>{escape(check.name)}</b>: {escape(check.detail)}{fix}")
    return "\n".join(lines)
