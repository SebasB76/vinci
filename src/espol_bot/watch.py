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


def alerts(conn: sqlite3.Connection, people: list[Person]) -> list[tuple[str, bool, str]]:
    """What broke and what recovered since the last message about it: (key, failing now, text)."""
    failing = {f"{p.name} · {c.name}": c for p in people for c in p.checks
               if c.level == health.FAIL and (p.friend or c.name not in OWN_ALERT)}
    before = _told(conn)
    changes = [(key, True, f"⚠️ <b>Vigilancia · {messages.e(key)}</b>: {messages.e(check.detail)}")
               for key, check in failing.items() if key not in before]
    changes += [(key, False, f"✅ <b>Vigilancia · {messages.e(key)}</b>: volvió a estar bien.")
                for key in sorted(before - set(failing))]
    return changes


def _told(conn: sqlite3.Connection) -> set[str]:
    try:
        return set(json.loads(get_meta(conn, FAILING) or "[]"))
    except ValueError:
        return set()


def run(cfg: BotConfig, conn: sqlite3.Connection, send, now: datetime) -> list[str]:
    """The captain's maintenance: survey everyone and send him what changed. A change counts as told only once its
    message went out: with the WhatsApp bridge down (it belongs to the gateway), the next run tells it. Never raises:
    a broken watchdog must not stop the token renewal it runs next to."""
    if cfg.friend:
        return []
    try:
        told, sent = _told(conn), []
        for key, failing, text in alerts(conn, survey(cfg, now)):
            try:
                send(text)
            except Exception as exc:  # noqa: BLE001 (the bridge is down: the rest waits too)
                log.warning("vigilancia: no pude avisar (%s); lo intento en la próxima corrida", exc)
                break
            told = told | {key} if failing else told - {key}
            sent.append(text)
        set_meta(conn, FAILING, json.dumps(sorted(told), ensure_ascii=False))
        conn.commit()
        return sent
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
