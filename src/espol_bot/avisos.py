"""Notices for the WhatsApp groups the captain turned them on in («@vinci activa los avisos», amigos.notice_groups).

Model-free, and only what the whole class shares: never a grade, a submission or the captain's notebook.
  - `class_reminders`, from Vinci's agenda tick (every minute): `brief_minutos_antes` before each class in
    horario.toml, the subject, time, room (marked when it is virtual) and what of that subject is due in 7 days,
    submitted or not, since a classmate may not have. Each class start is claimed in `briefs` as «grupo:<code>»,
    so a restart never sends it twice and the captain's own brief is not affected.
  - `send_events`, from the poller: the aula's new announcements, new assignments and changed due dates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aula_core import Aula, timefmt
from espol_bot import amigos, horario, messages, store, whatsapp
from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

EVENT_KINDS = ("new_announcement", "new_assignment", "due_changed")
DUE_DAYS = 7


def _send(cfg: BotConfig, groups: list[str], html_text: str) -> None:
    text = whatsapp.from_html(html_text)
    for group in groups:
        try:
            whatsapp.send_text(cfg.whatsapp_bridge, group, text)
        except Exception as exc:  # one group the number left must not stop the rest
            log.error("avisos %s: %s", group, exc)


def _due(conn, course_ids: list[int], now: datetime) -> list:
    if not course_ids:
        return []
    return conn.execute(
        f"""SELECT name, due_at FROM assignments WHERE active = 1 AND due_at >= ? AND due_at < ?
            AND course_id IN ({','.join('?' * len(course_ids))}) ORDER BY due_at""",
        [timefmt.iso(now), timefmt.iso(now + timedelta(days=DUE_DAYS)), *course_ids]).fetchall()


def reminder_text(cfg: BotConfig, subject, start: datetime, blocks: list[horario.Clase], due: list,
                  now: datetime) -> str:
    tz, clase = cfg.core.tz, blocks[0]
    minutes = max(1, round((start - now).total_seconds() / 60))
    local = start.astimezone(tz)
    day = "Hoy" if local.date() == now.astimezone(tz).date() else "Mañana"
    lines = [f"🔔 <b>Clase en {minutes} min: {messages.e(subject.name)}</b>",
             f"{day} {timefmt.DAYS_LONG[local.weekday()]} {local.day} {timefmt.MONTHS[local.month - 1]}, "
             f"{clase.inicio:%H:%M}–{max(b.fin for b in blocks):%H:%M}"
             + (f" · {messages.e(clase.aula)}" if clase.aula else "")]
    if "virtual" in (clase.aula or "").lower():
        lines.append("🖥️ Es virtual: el enlace está en el aula virtual.")
    if due:
        lines.append("\n<b>Vence esta semana</b>")
        lines += [f"• {messages.e(r['name'])}: {messages.e(timefmt.human(r['due_at'], tz))} "
                  f"({messages.e(timefmt.until(r['due_at'], now))})" for r in due]
    return "\n".join(lines)


def class_reminders(cfg: BotConfig, subjects: list, now: datetime) -> None:
    from espol_bot import agenda
    groups = amigos.notice_groups(cfg)
    if not groups:
        return
    for subject in subjects:
        found = agenda.sessions(cfg, subject)
        lead = timedelta(minutes=cfg.brief_minutes)
        upcoming = [(start, c) for start, c in horario.occurrences(
            list(found), now, now + lead + timedelta(seconds=1), cfg.core.tz, subject.code)
            if now < start <= now + lead]
        if not upcoming:
            continue
        aula = Aula(cfg.core)
        try:
            conn = store.ensure(aula.conn)
            for start, clase in upcoming:
                if store.claim_brief(conn, f"grupo:{subject.code}", start, now):
                    due = _due(conn, agenda.course_ids_for(conn, subject), now)
                    log.info("avisos: clase de %s %s a %d grupos", subject.code, start.isoformat(), len(groups))
                    _send(cfg, groups, reminder_text(cfg, subject, start, found[clase], due, now))
        finally:
            aula.close()


def send_events(cfg: BotConfig, events: list[dict], now: datetime) -> None:
    groups = amigos.notice_groups(cfg)
    shared = [ev for ev in events if ev["kind"] in EVENT_KINDS]
    if not groups or not shared:
        return
    if len(shared) > cfg.max_messages_per_poll:
        _send(cfg, groups, messages.digest(shared, cfg.core.tz))
        return
    for ev in shared:
        _send(cfg, groups, messages.event_message(ev, cfg.core.tz, now))
