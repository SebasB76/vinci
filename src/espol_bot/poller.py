"""Deterministic poller: sync, then notify. No model call anywhere in this file.

`poll()` runs every `intervalo_minutos` from a Hermes no-agent cron job:
  1. sync the aula virtual (plus material download/indexing) through aula_core;
  2. report, once per failure episode, each course resource that keeps failing;
  3. send one Telegram message per undelivered event (grouped when there are many);
  4. send the 24 h / 3 h reminders for unsubmitted deliverables.
`summary()` runs at `resumen_diario` and sends the week at a glance.

Events stay undelivered, and reminders unmarked, until Telegram accepts the
message, so a failed send is retried on the next poll.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aula_core import Aula, queries, timefmt
from aula_core import sync as core_sync
from aula_core.canvas import CanvasError, InvalidTokenError
from aula_core.store import delete_meta, get_meta, set_meta
from espol_bot import messages
from espol_bot.config import BotConfig
from espol_bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

BOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_reminders (
    assignment_id INTEGER NOT NULL,
    hours INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (assignment_id, hours, due_at)
);
"""

ALERT_AFTER = 3                  # consecutive failures before telling the captain
ALERT_EVERY = timedelta(hours=24)


@dataclass
class PollResult:
    sent: list[str] = field(default_factory=list)
    events: int = 0
    reminders: int = 0
    error: str | None = None


class Bot:
    def __init__(self, cfg: BotConfig, telegram: Telegram, aula: Aula | None = None):
        self.cfg = cfg
        self.tz = cfg.core.tz
        self.telegram = telegram
        self.aula = aula or Aula(cfg.core)
        self.conn.executescript(BOT_SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        return self.aula.conn

    # -- failure handling ------------------------------------------------------------

    def _fail(self, key: str, text: str, *, threshold: int) -> str:
        count = int(get_meta(self.conn, f"bot_fail_count_{key}") or 0) + 1
        set_meta(self.conn, f"bot_fail_count_{key}", str(count))
        last = timefmt.parse(get_meta(self.conn, f"bot_alert_{key}"))
        now = self.aula.now()
        if count >= threshold and (last is None or now - last >= ALERT_EVERY):
            try:
                self.telegram.send(messages.alert(text))
                set_meta(self.conn, f"bot_alert_{key}", timefmt.iso(now))
            except TelegramError as exc:
                log.error("No pude avisar por Telegram: %s", exc)
        self.conn.commit()
        return text

    def _ok(self) -> None:
        delete_meta(self.conn, "bot_fail_count_token", "bot_fail_count_red")
        self.conn.commit()

    # -- poll ------------------------------------------------------------------------

    def poll(self) -> PollResult:
        result = PollResult()
        try:
            report = self.aula.sync(materials=True)
        except InvalidTokenError:
            result.error = self._fail(
                "token", "Tu token de Canvas ya no funciona (¿expiró?). Crea uno nuevo en el aula virtual "
                "y ponlo en secrets.env; mientras tanto no puedo revisar tus materias.", threshold=1)
            return result
        except CanvasError as exc:
            result.error = self._fail(
                "red", f"Llevo un rato sin poder leer el aula virtual: {exc}", threshold=ALERT_AFTER)
            return result
        self._ok()
        now = self.aula.now()

        try:
            if get_meta(self.conn, "bot_welcomed") is None:
                week = queries.pending(self.conn, now, days=7, overdue_days=0)
                text = messages.welcome(queries.courses(self.conn), len(week), self.cfg.poll_minutes)
                self.telegram.send(text)
                set_meta(self.conn, "bot_welcomed", timefmt.iso(now))
                self.conn.commit()
                result.sent.append(text)
            self._report_failures(report.failed, now)
            self._deliver_events(result, now)
            self._send_reminders(result, now)
        except TelegramError as exc:
            log.error("%s", exc)
            result.error = str(exc)
        return result

    def _report_failures(self, failed: list[core_sync.FailedResource], now: datetime) -> None:
        for failure in failed:
            if failure.reads >= ALERT_AFTER and not failure.reported:
                self.telegram.send(messages.alert(
                    f"Llevo un rato sin poder leer {failure.what}; lo sigo intentando en cada revisión "
                    "y el resto de tus materias funciona normal."))
                core_sync.mark_reported(self.conn, failure, now)

    def _deliver_events(self, result: PollResult, now: datetime) -> None:
        events = core_sync.pending_events(self.conn)
        result.events = len(events)
        if not events:
            return
        if len(events) > self.cfg.max_messages_per_poll:
            text = messages.digest(events, self.tz)
            self.telegram.send(text)
            result.sent.append(text)
            core_sync.mark_delivered(self.conn, [ev["id"] for ev in events], now)
            return
        for ev in events:
            status = None
            if ev["kind"] in ("new_file", "file_updated"):
                row = self.conn.execute("SELECT index_status FROM files WHERE id = ?", (ev["ref_id"],)).fetchone()
                status = row["index_status"] if row else None
            text = messages.event_message(ev, self.tz, now, status)
            self.telegram.send(text)
            result.sent.append(text)
            core_sync.mark_delivered(self.conn, [ev["id"]], now)

    def _send_reminders(self, result: PollResult, now: datetime) -> None:
        horizon = max(self.cfg.reminder_hours)
        upcoming = queries.pending(self.conn, now, days=horizon // 24 + 1, overdue_days=0)
        for task in upcoming:
            due = timefmt.parse(task["vence"])
            if due is None or due <= now:
                continue
            hours_left = (due - now).total_seconds() / 3600
            applicable = [h for h in self.cfg.reminder_hours if hours_left <= h]
            if not applicable:
                continue
            smallest = min(applicable)
            already = self.conn.execute(
                "SELECT 1 FROM bot_reminders WHERE assignment_id = ? AND hours = ? AND due_at = ?",
                (task["id"], smallest, task["vence"]),
            ).fetchone()
            if already:
                continue
            text = messages.reminder_message(task, smallest, self.tz, now)
            self.telegram.send(text)
            result.sent.append(text)
            result.reminders += 1
            # Mark every larger offset too, so a late-created task gets one reminder, not two.
            self.conn.executemany(
                "INSERT OR IGNORE INTO bot_reminders(assignment_id, hours, due_at, sent_at) VALUES (?, ?, ?, ?)",
                [(task["id"], h, task["vence"], timefmt.iso(now)) for h in applicable],
            )
            self.conn.commit()

    # -- daily summary ---------------------------------------------------------------

    def summary_text(self, now: datetime) -> str:
        local_midnight = now.astimezone(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        week = queries.assignments_between(self.conn, now, now, local_midnight + timedelta(days=7))
        overdue = [t for t in queries.pending(self.conn, now, overdue_days=7) if t["atrasada"]]
        since = timefmt.iso(now - timedelta(hours=24))
        recent = [a for a in queries.announcements(self.conn, limit=50) if (a["publicado"] or "") >= since]
        return messages.weekly_summary(week, overdue, recent, self.tz, now)

    def summary(self, *, sync_first: bool = True) -> PollResult:
        result = PollResult()
        if sync_first:
            result = self.poll()
        now = self.aula.now()
        today = now.astimezone(self.tz).date().isoformat()
        if get_meta(self.conn, "bot_last_summary") == today:
            return result
        text = self.summary_text(now)
        try:
            self.telegram.send(text)
        except TelegramError as exc:
            result.error = str(exc)
            return result
        set_meta(self.conn, "bot_last_summary", today)
        self.conn.commit()
        result.sent.append(text)
        return result
