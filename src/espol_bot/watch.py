"""The captain's watchdog: the health of every Vinci on this install (his and each friend's), for the admin panel and
`espol-bot doctor`, and a WhatsApp message to the captain when one of them breaks and again when it recovers.

It runs in the captain's maintenance, every 10 minutes, so it also notices his own poll stopping. Only failures
(health.FAIL) alert, once per incident: the set failing now is kept in meta and compared on the next run. The
captain's own Canvas token is left out: his Vinci already tells him when Canvas refuses it (poller._token_refused).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from aula_core.config import ConfigError
from aula_core.store import get_meta, set_meta
from espol_bot import amigos, health, messages
from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

FAILING = "watch_failing"
CAPTAIN = "Tú"
OWN_ALERT = {"Token de Canvas"}  # the captain's Vinci already says it in his chat


@dataclass(frozen=True)
class Person:
    name: str
    friend: bool
    checks: list[health.Check]


def _checks(cfg: BotConfig, now: datetime) -> list[health.Check]:
    conn = health.open_readonly(cfg.core.db_path)
    try:
        return health.checks(cfg, conn, now)
    finally:
        if conn is not None:
            conn.close()


def survey(cfg: BotConfig, now: datetime) -> list[Person]:
    """The captain first, then each active friend; a friend whose folder cannot be read is one failing check."""
    people = [Person(CAPTAIN, False, _checks(cfg, now))]
    for friend in amigos.active(cfg):
        try:
            with amigos.scope(cfg, friend) as fcfg:
                found = _checks(fcfg, now)
        except (ConfigError, OSError, sqlite3.Error) as exc:
            found = [health.Check("Configuración", health.FAIL, f"no pude leer su Vinci: {exc}")]
        people.append(Person(friend.nombre, True, found))
    return people


def alerts(conn: sqlite3.Connection, people: list[Person]) -> list[str]:
    """The messages for what broke and what recovered since the last run; remembers what fails now."""
    failing = {f"{p.name} · {c.name}": c for p in people for c in p.checks
               if c.level == health.FAIL and (p.friend or c.name not in OWN_ALERT)}
    try:
        before = set(json.loads(get_meta(conn, FAILING) or "[]"))
    except ValueError:
        before = set()
    texts = [f"⚠️ <b>Vigilancia · {messages.e(key)}</b>: {messages.e(check.detail)}"
             for key, check in failing.items() if key not in before]
    texts += [f"✅ <b>Vigilancia · {messages.e(key)}</b>: volvió a estar bien." for key in sorted(before - set(failing))]
    set_meta(conn, FAILING, json.dumps(sorted(failing), ensure_ascii=False))
    conn.commit()
    return texts


def run(cfg: BotConfig, conn: sqlite3.Connection, send, now: datetime) -> list[str]:
    """The captain's maintenance: survey everyone and send him what changed. Never raises: a broken watchdog must
    not stop the token renewal it runs next to."""
    if cfg.friend:
        return []
    try:
        texts = alerts(conn, survey(cfg, now))
        for text in texts:
            send(text)
        return texts
    except Exception:  # noqa: BLE001 (see the docstring)
        log.exception("vigilancia: falló")
        return []


def terminal_lines(people: list[Person]) -> list[str]:
    """One line per friend for `espol-bot doctor`, and a line per check that is not fine."""
    lines = []
    for person in people:
        if not person.friend:
            continue
        level = (health.FAIL if any(c.level == health.FAIL for c in person.checks) else
                 health.WARN if any(c.level == health.WARN for c in person.checks) else health.OK)
        lines.append(f"{health.ICON[level]} Vinci de {person.name}" + (": todo en orden" if level == health.OK else ""))
        lines += [f"   {health.ICON[c.level]} {c.name}: {c.detail}" for c in person.checks if c.level != health.OK]
    return lines
