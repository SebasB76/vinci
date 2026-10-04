"""Deterministic poller: sync, then notify. No model call anywhere in this file.

`poll()` runs every `intervalo_minutos` from a Hermes no-agent cron job:
  1. sync the aula virtual (plus material download/indexing) through aula_core, gently: it is
     background work, so its requests are spaced and its material comes a slice per poll;
     a token Canvas refused is not tried again until it changes, and the captain gets the /token
     form without asking for it;
  2. report, once per failure episode, each course resource that keeps failing;
  3. send one Telegram message per undelivered event (grouped when there are many);
  4. send the 24 h / 3 h reminders for unsubmitted deliverables (each with «✅ Ya lo entregué», for
     what went in on paper, by email or in the lab, which Canvas never learns about) and for the
     captain's own to-dos (store.todos, each with «✅ Hecho»); and, for a quiz that opens at a set time for
     a short window (a 30-minute test in class), «abre en 15 min» before it opens, or «ya abrió» right after;
  5. point the menu button of Vinci's chat at a fresh dashboard when what it shows changed (dashboard.py);
  6. per subject bot: index the books the captain put in `libros/<CÓDIGO>/`, and ask once, from
     that bot's chat, for its main book's PDF when there is none it can read (libros.py).
Then (`read_scans`, outside the poll's lock) OCR of the scanned pages still waiting, OCR_MINUTES a run.
`summary()` runs at `resumen_diario` and sends the week at a glance, the open to-dos included.

Events stay undelivered, and reminders unmarked, until Telegram accepts the
message, so a failed send is retried on the next poll.

Everything goes out through Vinci's chat. A message about a course that has an
active subject bot carries a «Consultar con <bot>» button per course;
the alert is recorded in `avisos` so the button can hand it to that bot.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from aula_core import Aula, feeds, queries, timefmt
from aula_core import sync as core_sync
from aula_core.canvas import CanvasError, InvalidTokenError
from aula_core.config import ConfigError
from aula_core.store import delete_meta, get_meta, set_meta
from espol_bot import agenda, dashboard, health, libros, materias, messages, priority, store, token_form
from espol_bot.config import BotConfig, load_telegram_secrets
from espol_bot.telegram import Telegram, TelegramError
from espol_bot.token_renewal import RenewalError, TokenRenewal

log = logging.getLogger(__name__)

MAX_BUTTONS = 6

OCR_MINUTES = 10  # of each poll: a 300-page scanned book is searchable after a few polls
ALERT_AFTER = 3                  # consecutive failures before telling the captain
ALERT_EVERY = timedelta(hours=24)
OPENING_LEAD = timedelta(minutes=15)
SHORT_WINDOW = timedelta(hours=12)  # a quiz open longer than this gets the usual reminders only


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
        self.aula = aula or Aula(cfg.core, background=True)
        store.ensure(self.conn)
        try:
            self.team = materias.load(cfg.core)  # archived subjects too: their grading schemes still count
            self.subjects = [s for s in self.team if s.active]
            self.team_error = None
        except ConfigError as exc:
            log.error("%s", exc)
            self.team, self.subjects, self.team_error = [], [], str(exc)

    @property
    def conn(self) -> sqlite3.Connection:
        return self.aula.conn

    # -- sending ---------------------------------------------------------------------

    def _subjects_for(self, course_ids) -> list[materias.Subject]:
        found: list[materias.Subject] = []
        for course_id in course_ids:
            row = self.conn.execute("SELECT course_code FROM courses WHERE id = ?", (course_id,)).fetchone()
            subject = materias.for_course(self.subjects, course_id, row["course_code"] if row else None)
            if subject and subject not in found:
                found.append(subject)
        return found[:MAX_BUTTONS]

    def _send(self, text: str, course_ids=(), extra: list[tuple[str, str]] = ()) -> None:
        """Send to the captain; offer a handoff button per course that has an active subject bot, then `extra`."""
        subjects = self._subjects_for(dict.fromkeys(c for c in course_ids if c is not None))
        buttons = []
        if subjects:
            alert_id = store.new_alert(self.conn, messages.plain(text), [s.code for s in subjects], self.aula.now())
            buttons = [(messages.handoff_button(s.display), f"v1:a:{alert_id}:{s.code}") for s in subjects]
        self.telegram.send(text, buttons + list(extra))

    def _hand_in_hint(self, assignment_id: int, course_id: int) -> str:
        """The line that points a handwritten, PDF-upload assignment at its subject bot; empty for any other."""
        row = self.conn.execute("SELECT submission_types, allowed_extensions, asks_scan FROM assignments WHERE id = ?",
                                (assignment_id,)).fetchone()
        if row is None or "online_upload" not in (row["submission_types"] or "").split(","):
            return ""
        extensions = set((row["allowed_extensions"] or "").split(",")) - {""}
        subjects = self._subjects_for([course_id])
        if (extensions and "pdf" not in extensions) or not subjects:
            return ""
        if not (row["asks_scan"] or subjects[0].code.upper() in self.cfg.handwritten_subjects):
            return ""
        return "\n" + messages.hand_in_hint(subjects[0].handle())

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

    def _token_refused(self) -> str:
        """Sends the /token form on its own once per refused token, and again each ALERT_EVERY while none is
        pending (the polls leave Canvas alone until the token changes)."""
        command = Path(sys.executable).with_name("espol-bot")
        floor = (" Los feeds públicos siguen actualizando fechas, eventos y anuncios." if feeds.configured() else
                 f" Para mantener fechas y anuncios aun sin token, configura sus feeds una vez con "
                 f"<code>{escape(str(command))} feeds</code>.")
        text = ("⚠️ La cadena automática del token de Canvas se cortó (la PC pudo estar apagada más de una hora). "
                "No hace falta que escribas /token: aquí va el formulario, que lo cifra en tu celular antes de "
                "enviarlo (no lo pegues en el chat)." + floor)
        refused = self.aula.refused_token()
        if not refused:
            return text
        now = self.aula.now()
        last = timefmt.parse(get_meta(self.conn, "bot_alert_token_at"))
        due = (get_meta(self.conn, "bot_alert_token") != refused
               or ((last is None or now - last >= ALERT_EVERY) and not token_form.pending(self.conn, now)))
        if due:
            form = token_form.new_form(self.cfg, self.conn, now, text + "\n\n", ttl=token_form.AUTO_FORM_TTL)
            try:
                self.telegram.send(form["respuesta"], reply_markup=token_form.keyboard(form["web_app_button"]))
                set_meta(self.conn, "bot_alert_token", refused)
                set_meta(self.conn, "bot_alert_token_at", timefmt.iso(now))
                self.conn.commit()
            except TelegramError as exc:
                log.error("No pude avisar por Telegram: %s", exc)
        return text

    def _ok(self) -> None:
        delete_meta(self.conn, "bot_fail_count_token", "bot_fail_count_red", "bot_alert_token",
                    "bot_alert_token_at")
        self.conn.commit()

    # -- poll ------------------------------------------------------------------------

    def maintenance(self) -> PollResult:
        """Fast no-agent background work: renew the token and refresh token-free feeds."""
        result = PollResult()
        now = self.aula.now()
        renewal_error = None
        try:
            renewal = TokenRenewal(self.cfg.core, self.conn, now).maintain()
            if renewal.chain_cut:
                result.error = self._token_refused()
            elif renewal.server_fixed:
                delete_meta(self.conn, "bot_fail_count_renewal", "bot_alert_renewal")
                self.conn.commit()
        except RenewalError as exc:
            renewal_error = str(exc)
            result.error = self._fail("renewal", f"No pude renovar el token de Canvas: {exc}. "
                                      "Si la cadena se corta, te mostraré cómo resembrarla.", threshold=1)
        floor = feeds.sync(self.conn, self.cfg.core, now)
        if floor.errors:
            self._fail("feeds", "No pude actualizar el respaldo sin token (" + "; ".join(floor.errors) + ").",
                       threshold=ALERT_AFTER)
        else:
            delete_meta(self.conn, "bot_fail_count_feeds")
            self.conn.commit()
        result.events = floor.events
        health.record_run(self.conn, health.MAINTENANCE_RUN, now, renewal_error=renewal_error,
                          feed_errors=floor.errors)
        return result

    def poll(self) -> PollResult:
        result = PollResult()
        problems = []  # for /estado; the token chain has its own line there
        if self.team_error:
            self._fail("materias", f"No puedo leer tu equipo de bots: {self.team_error}. Te sigo mandando los "
                       "avisos del aula, pero sin los botones de cada materia; los bots de materia no mandan briefs "
                       "ni reciben lo que les pases hasta que corrijas ese archivo.", threshold=1)
        try:
            report = self.aula.sync(materials=True)
        except InvalidTokenError:
            result.error = self._token_refused()
            report = core_sync.SyncReport(first_sync=False)
            floor = feeds.sync(self.conn, self.cfg.core, self.aula.now())
            result.events += floor.events
        except CanvasError as exc:
            problems.append(f"no pude leer el aula virtual ({exc})")
            result.error = self._fail(
                "red", f"Llevo un rato sin poder leer el aula virtual: {exc}", threshold=ALERT_AFTER)
            report = core_sync.SyncReport(first_sync=False)
            floor = feeds.sync(self.conn, self.cfg.core, self.aula.now())
            result.events += floor.events
        else:
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
            self._send_quiz_openings(result, now)
        except TelegramError as exc:
            log.error("%s", exc)
            problems.append(f"Telegram no aceptó un mensaje ({exc})")
            result.error = str(exc)
        try:
            dashboard.publish(self.conn, self.cfg, self.telegram, self.team, now)
        except TelegramError as exc:  # the menu button keeps the last snapshot until the next poll
            log.warning("dashboard: %s", exc)
        self._main_books(result, now)
        health.record_run(self.conn, health.POLL_RUN, now, error="; ".join(problems) or None)
        return result

    def _main_books(self, result: PollResult, now: datetime) -> None:
        for subject in self.subjects:
            course_ids = agenda.course_ids_for(self.conn, subject)
            if not course_ids:
                continue
            try:
                libros.scan_folder(self.conn, self.cfg.core, subject, course_ids)
            except OSError as exc:
                log.warning("carpeta de libros de %s: %s", subject.code, exc)
            book = libros.main_book(self.conn, self.cfg.core, subject, course_ids)
            if libros.needs_ask(book) and book["enlaces"]:
                try:  # the aula links it: if that opens without a login, it is the book and there is nothing to ask
                    self.aula.fetch_link(book["enlaces"][0]["enlace_id"])
                except CanvasError as exc:
                    log.info("el libro de %s no se abre desde su enlace: %s", subject.code, exc)
                book = libros.main_book(self.conn, self.cfg.core, subject, course_ids)
            if not libros.needs_ask(book):
                continue
            text = libros.ask_text(self.cfg.core, subject, book)
            try:  # from the subject bot's own chat; a failure asks again next poll
                Telegram(load_telegram_secrets(subject.code), api=self.cfg.telegram_api).send(text)
            except (TelegramError, ConfigError) as exc:
                log.warning("no pude pedir el libro de %s: %s", subject.code, exc)
                continue
            libros.mark_asked(self.conn, subject.code, now)
            result.sent.append(text)

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
            self._send(text, [ev["course_id"] for ev in events])
            result.sent.append(text)
            core_sync.mark_delivered(self.conn, [ev["id"] for ev in events], now)
            return
        for ev in events:
            status = None
            if ev["kind"] in ("new_file", "file_updated"):
                row = self.conn.execute("SELECT index_status FROM files WHERE id = ?", (ev["ref_id"],)).fetchone()
                status = row["index_status"] if row else None
            text = messages.event_message(ev, self.tz, now, status)
            if ev["kind"] == "new_assignment" and not ev.get("quiz"):
                text += self._hand_in_hint(ev["ref_id"], ev["course_id"])
            self._send(text, [ev["course_id"]])
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
            text += self._hand_in_hint(task["id"], task["curso_id"])
            self._send(text, [task["curso_id"]], [(messages.SUBMITTED_BUTTON, f"v1:s:{task['id']}:ok")])
            result.sent.append(text)
            result.reminders += 1
            # Mark every larger offset too, so a late-created task gets one reminder, not two.
            self.conn.executemany(
                "INSERT OR IGNORE INTO bot_reminders(assignment_id, hours, due_at, sent_at) VALUES (?, ?, ?, ?)",
                [(task["id"], h, task["vence"], timefmt.iso(now)) for h in applicable],
            )
            self.conn.commit()
        self._send_todo_reminders(result, now, horizon)

    def _send_quiz_openings(self, result: PollResult, now: datetime) -> None:
        # A poll every N minutes must still warn before the opening, so the lead is at least one interval.
        lead = max(OPENING_LEAD, timedelta(minutes=self.cfg.poll_minutes))
        for task in queries.quiz_openings(self.conn, now, lead):
            quiz = task["quiz"]
            opens, closes = timefmt.parse(quiz["unlock_at"]), timefmt.parse(quiz["lock_at"] or task["vence"])
            if closes is None or closes <= now or closes - opens > SHORT_WINDOW:
                continue
            # hours = 0 in bot_reminders is this alert, keyed by the opening time.
            already = self.conn.execute("SELECT 1 FROM bot_reminders WHERE assignment_id = ? AND hours = 0 AND due_at = ?",
                                        (task["id"], quiz["unlock_at"])).fetchone()
            if already:
                continue
            text = messages.quiz_opening(task, self.tz, now)
            self._send(text, [task["curso_id"]])
            result.sent.append(text)
            result.reminders += 1
            self.conn.execute("INSERT OR IGNORE INTO bot_reminders(assignment_id, hours, due_at, sent_at) VALUES (?, ?, ?, ?)",
                              (task["id"], 0, quiz["unlock_at"], timefmt.iso(now)))
            self.conn.commit()

    def _send_todo_reminders(self, result: PollResult, now: datetime, horizon: int) -> None:
        for todo in store.open_todos(self.conn, now + timedelta(hours=horizon)):
            due = timefmt.parse(todo["due_at"])
            if due is None or due <= now:
                continue
            applicable = [h for h in self.cfg.reminder_hours if (due - now).total_seconds() / 3600 <= h]
            already = self.conn.execute("SELECT 1 FROM todo_reminders WHERE todo_id = ? AND hours = ? AND due_at = ?",
                                        (todo["id"], min(applicable), todo["due_at"])).fetchone()
            if already:
                continue
            text = messages.todo_reminder(todo, self.tz, now)
            self.telegram.send(text, [(messages.TODO_DONE_BUTTON, f"v1:t:{todo['id']}:ok")])
            result.sent.append(text)
            result.reminders += 1
            self.conn.executemany(
                "INSERT OR IGNORE INTO todo_reminders(todo_id, hours, due_at, sent_at) VALUES (?, ?, ?, ?)",
                [(todo["id"], h, todo["due_at"], timefmt.iso(now)) for h in applicable])
            self.conn.commit()

    def read_scans(self) -> None:
        try:
            read = self.aula.read_scans(seconds=OCR_MINUTES * 60)
        except Exception:  # never a failed poll (Hermes would forward it to the captain) over OCR
            log.exception("OCR")
            return
        if read:
            log.info("OCR: %d página(s) escaneada(s) leída(s)", read)

    # -- daily summary ---------------------------------------------------------------

    def summary_text(self, now: datetime) -> tuple[str, list[int], list[tuple[str, str]]]:
        local_midnight = now.astimezone(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        week = queries.assignments_between(self.conn, now, now, local_midnight + timedelta(days=7))
        todos = store.open_todos(self.conn, local_midnight + timedelta(days=7))
        overdue = [t for t in queries.pending(self.conn, now, overdue_days=7) if t["atrasada"]]
        since = timefmt.iso(now - timedelta(hours=24))
        recent = [a for a in queries.announcements(self.conn, limit=50) if (a["publicado"] or "") >= since]
        pending = [t for t in week if not t["entregada"]]
        entries = priority.ordered(self.conn, self.team, self.tz, now, overdue + pending, todos)
        undated = [t for t in todos if not t["due_at"]]
        courses = [t["curso_id"] for t in overdue + pending] + [a["curso_id"] for a in recent]
        # The buttons in the order the to-dos show: «Por entregar», then «Atrasadas», then the undated ones.
        shown = [e.item for e in entries if e.todo and e.tier != "overdue"] + \
            [e.item for e in entries if e.todo and e.tier == "overdue"] + undated
        done = [(messages.todo_done_button(t["text"]), f"v1:t:{t['id']}:ok") for t in shown[:MAX_BUTTONS]]
        text = messages.weekly_summary(entries, len(week) - len(pending), recent, self.tz, now, undated)
        return text, courses, done

    def summary(self, *, sync_first: bool = True) -> PollResult:
        result = PollResult()
        if sync_first:
            result = self.poll()
        now = self.aula.now()
        today = now.astimezone(self.tz).date().isoformat()
        if get_meta(self.conn, "bot_last_summary") == today:
            return result
        text, courses, done = self.summary_text(now)
        try:
            self._send(text, courses, done)
        except TelegramError as exc:
            result.error = str(exc)
            return result
        set_meta(self.conn, "bot_last_summary", today)
        self.conn.commit()
        result.sent.append(text)
        return result
