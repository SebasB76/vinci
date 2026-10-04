"""Vinci's own tables in espol.db (next to the aula_core tables).

  bot_reminders        which due-date reminders were already sent (hours = 0: a quiz's opening alert)
  avisos               every alert Vinci sent that offers a handoff (plain text + subjects)
  entregas             handoffs queued for a subject bot (from an alert button or routed by
                       Vinci); the subject bot's agenda claims each one exactly once
  briefs               pre-class briefs already claimed, one per subject and class start,
                       so a restart never sends a brief twice
  horario_propuestas   schedules Vinci extracted from a screenshot, waiting for the
                       captain to press «Guardar»
  libros               per subject: the main book the captain named, the files given as its PDF,
                       and when the subject bot asked the captain for that PDF (once)
  todos                the captain's own to-do list (readings, paperwork, what a professor said in
                       class): text, subject and due date when given, and when it was done
  todo_reminders       which to-do reminders were already sent (like bot_reminders)
  shown_pages          each page of the material a tool showed a bot (Vinci or a subject): what a citation
                       in its answers may point at (citations.py)
  grading_schemes      per subject: how it is graded this semester (grades.py), saved only by the
                       captain's «Guardar» under a proposal
  grading_scheme_proposals
                       schemes a bot read from the syllabus or heard from the captain, waiting for that press
  manual_grades        grades the captain told a bot about that Canvas does not have (a lesson on paper)
  submission_proposals PDFs a subject bot built from the captain's photos for an assignment, waiting for
                       «Entregar» (pending → submitting → submitted; or cancelled, replaced by a newer
                       PDF for the same assignment, or failed when the aula refuses it for good)
  class_notes          each Markdown note in the captain's notes folder (notes.py): its subject once decided
                       (and how), whether Vinci asked or the captain said it is not from class, and the text
                       last handed to the subject bot for a summary
  note_questions       the «//vinci …» lines of a note, each handed to the subject bot once
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from aula_core import timefmt

SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_reminders (
    assignment_id INTEGER NOT NULL,
    hours INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (assignment_id, hours, due_at)
);
CREATE TABLE IF NOT EXISTS avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    texto TEXT NOT NULL,
    materias TEXT NOT NULL DEFAULT '[]',
    creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entregas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    materia TEXT NOT NULL,
    origen TEXT NOT NULL,
    aviso_id INTEGER,
    texto TEXT NOT NULL,
    adjuntos TEXT NOT NULL DEFAULT '[]',
    creado TEXT NOT NULL,
    reclamado TEXT,
    UNIQUE (aviso_id, materia)
);
CREATE TABLE IF NOT EXISTS briefs (
    materia TEXT NOT NULL,
    inicio TEXT NOT NULL,
    reclamado TEXT NOT NULL,
    PRIMARY KEY (materia, inicio)
);
CREATE TABLE IF NOT EXISTS libros (
    materia TEXT PRIMARY KEY,
    titulo TEXT,
    archivos TEXT NOT NULL DEFAULT '[]',
    pedido TEXT,
    actualizado TEXT
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    subject TEXT,
    due_at TEXT,
    all_day INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    done_at TEXT
);
CREATE TABLE IF NOT EXISTS todo_reminders (
    todo_id INTEGER NOT NULL,
    hours INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (todo_id, hours, due_at)
);
CREATE TABLE IF NOT EXISTS grading_schemes (
    subject TEXT PRIMARY KEY,
    scheme TEXT NOT NULL,
    saved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grading_scheme_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    scheme TEXT NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS manual_grades (
    subject TEXT NOT NULL,
    period TEXT NOT NULL,
    component TEXT NOT NULL,
    label TEXT NOT NULL,
    score REAL NOT NULL,
    out_of REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (subject, period, component, label)
);
CREATE TABLE IF NOT EXISTS horario_propuestas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clases TEXT NOT NULL,
    creado TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    resuelto TEXT
);
CREATE TABLE IF NOT EXISTS submission_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    course_id INTEGER NOT NULL,
    assignment_id INTEGER NOT NULL,
    assignment_name TEXT NOT NULL,
    pdf TEXT NOT NULL,
    pages INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS class_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    digest TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    subject TEXT,
    decided_by TEXT,
    ignored INTEGER NOT NULL DEFAULT 0,
    asked_at TEXT,
    announced_at TEXT,
    summarized_text TEXT,
    summarized_at TEXT,
    handed_images TEXT NOT NULL DEFAULT '[]',
    checked_digest TEXT,
    gone_at TEXT
);
CREATE TABLE IF NOT EXISTS note_questions (
    note_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    handoff_id INTEGER,
    PRIMARY KEY (note_id, question)
);
CREATE TABLE IF NOT EXISTS shown_pages (
    bot TEXT NOT NULL,
    file_id INTEGER NOT NULL,
    page INTEGER NOT NULL,
    shown_at TEXT NOT NULL,
    PRIMARY KEY (bot, file_id, page)
);
"""


def ensure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(SCHEMA)
    return conn


# -- avisos ------------------------------------------------------------------------------


def new_alert(conn: sqlite3.Connection, text: str, codes: list[str], now: datetime) -> int:
    cur = conn.execute("INSERT INTO avisos(texto, materias, creado) VALUES (?, ?, ?)",
                       (text, json.dumps(codes), timefmt.iso(now)))
    conn.commit()
    return int(cur.lastrowid)


def set_alert_text(conn: sqlite3.Connection, alert_id: int, text: str) -> None:
    conn.execute("UPDATE avisos SET texto = ? WHERE id = ?", (text, alert_id))
    conn.commit()


def alert(conn: sqlite3.Connection, alert_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM avisos WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "texto": row["texto"], "materias": json.loads(row["materias"]), "creado": row["creado"]}


# -- entregas ----------------------------------------------------------------------------


def queue_handoff(conn: sqlite3.Connection, code: str, origin: str, text: str, now: datetime, *,
                  alert_id: int | None = None, attachments: list[dict] | None = None) -> tuple[int, bool]:
    """Queue a handoff; returns (id, created). An alert is handed to a subject only once."""
    if alert_id is not None:
        row = conn.execute("SELECT id FROM entregas WHERE aviso_id = ? AND materia = ?", (alert_id, code)).fetchone()
        if row:
            return int(row["id"]), False
    cur = conn.execute(
        "INSERT INTO entregas(materia, origen, aviso_id, texto, adjuntos, creado) VALUES (?, ?, ?, ?, ?, ?)",
        (code, origin, alert_id, text, json.dumps(attachments or [], ensure_ascii=False), timefmt.iso(now)))
    conn.commit()
    return int(cur.lastrowid), True


def claim_handoffs(conn: sqlite3.Connection, code: str, now: datetime, limit: int = 5, *,
                   origins: tuple[str, ...] = (), exclude: bool = False) -> list[dict]:
    """The oldest unclaimed handoffs for `code` (up to `limit`), each marked claimed atomically
    so it is handed to the subject bot at most once. `origins` keeps only those (or, with `exclude`, the rest)."""
    claimed = []
    only = (f" AND origen {'NOT IN' if exclude else 'IN'} ({','.join('?' * len(origins))})") if origins else ""
    rows = conn.execute(f"SELECT * FROM entregas WHERE materia = ? AND reclamado IS NULL{only} ORDER BY id LIMIT ?",
                        (code, *origins, limit)).fetchall()
    for row in rows:
        cur = conn.execute("UPDATE entregas SET reclamado = ? WHERE id = ? AND reclamado IS NULL",
                           (timefmt.iso(now), row["id"]))
        if cur.rowcount == 1:
            claimed.append({"id": row["id"], "materia": row["materia"], "origen": row["origen"],
                            "aviso_id": row["aviso_id"], "texto": row["texto"],
                            "adjuntos": json.loads(row["adjuntos"]), "creado": row["creado"]})
    conn.commit()
    return claimed


def pending_handoffs(conn: sqlite3.Connection, code: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM entregas WHERE materia = ? AND reclamado IS NULL", (code,)).fetchone()[0]


# -- briefs ------------------------------------------------------------------------------


def claim_brief(conn: sqlite3.Connection, code: str, class_start: datetime, now: datetime) -> bool:
    """True the first time a given class of a subject is claimed; False ever after."""
    cur = conn.execute("INSERT OR IGNORE INTO briefs(materia, inicio, reclamado) VALUES (?, ?, ?)",
                       (code, class_start.isoformat(), timefmt.iso(now)))
    conn.commit()
    return cur.rowcount == 1


# -- horario_propuestas ------------------------------------------------------------------


def new_proposal(conn: sqlite3.Connection, classes: list[dict], now: datetime) -> int:
    cur = conn.execute("INSERT INTO horario_propuestas(clases, creado) VALUES (?, ?)",
                       (json.dumps(classes, ensure_ascii=False), timefmt.iso(now)))
    conn.commit()
    return int(cur.lastrowid)


def proposal(conn: sqlite3.Connection, proposal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM horario_propuestas WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "clases": json.loads(row["clases"]), "estado": row["estado"], "creado": row["creado"]}


def resolve_proposal(conn: sqlite3.Connection, proposal_id: int, state: str, now: datetime) -> bool:
    """Move a pending proposal to 'guardada' or 'descartada'; False when it was not pending."""
    cur = conn.execute(
        "UPDATE horario_propuestas SET estado = ?, resuelto = ? WHERE id = ? AND estado = 'pendiente'",
        (state, timefmt.iso(now), proposal_id))
    if state == "guardada" and cur.rowcount == 1:
        # Only one schedule is current: older pending proposals are superseded.
        conn.execute("UPDATE horario_propuestas SET estado = 'descartada', resuelto = ? "
                     "WHERE estado = 'pendiente' AND id < ?", (timefmt.iso(now), proposal_id))
    conn.commit()
    return cur.rowcount == 1


# -- todos -------------------------------------------------------------------------------


def _todo(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "text": row["text"], "subject": row["subject"], "due_at": row["due_at"],
            "all_day": bool(row["all_day"]), "created_at": row["created_at"], "done_at": row["done_at"]}


def add_todo(conn: sqlite3.Connection, text: str, subject: str | None, due: datetime | None, all_day: bool,
             now: datetime) -> dict:
    cur = conn.execute("INSERT INTO todos(text, subject, due_at, all_day, created_at) VALUES (?, ?, ?, ?, ?)",
                       (text, subject, timefmt.iso(due) if due else None, int(all_day), timefmt.iso(now)))
    conn.commit()
    return todo(conn, int(cur.lastrowid))


def todo(conn: sqlite3.Connection, todo_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return _todo(row) if row else None


def delete_todo(conn: sqlite3.Connection, todo_id: int) -> None:
    conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()


def set_todo_done(conn: sqlite3.Connection, todo_id: int, done: bool, now: datetime) -> bool:
    """Mark a to-do done (or open again); False when it already was."""
    cur = conn.execute("UPDATE todos SET done_at = ? WHERE id = ? AND done_at IS " + ("NULL" if done else "NOT NULL"),
                       (timefmt.iso(now) if done else None, todo_id))
    conn.commit()
    return cur.rowcount == 1


def open_todos(conn: sqlite3.Connection, until: datetime | None = None) -> list[dict]:
    """Open to-dos by due date (overdue first), then the ones with no date; `until` drops those due later."""
    rows = conn.execute("SELECT * FROM todos WHERE done_at IS NULL ORDER BY due_at IS NULL, due_at, id").fetchall()
    limit = timefmt.iso(until) if until else None
    return [_todo(r) for r in rows if not (limit and r["due_at"] and r["due_at"] >= limit)]


# -- grading schemes ---------------------------------------------------------------------


def grading_scheme(conn: sqlite3.Connection, subject: str) -> dict | None:
    row = conn.execute("SELECT * FROM grading_schemes WHERE subject = ?", (subject,)).fetchone()
    return {"scheme": json.loads(row["scheme"]), "saved_at": row["saved_at"]} if row else None


def new_scheme_proposal(conn: sqlite3.Connection, subject: str, scheme: dict, now: datetime) -> int:
    cur = conn.execute("INSERT INTO grading_scheme_proposals(subject, scheme, created_at) VALUES (?, ?, ?)",
                       (subject, json.dumps(scheme, ensure_ascii=False), timefmt.iso(now)))
    conn.commit()
    return int(cur.lastrowid)


def scheme_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM grading_scheme_proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "subject": row["subject"], "scheme": json.loads(row["scheme"]), "state": row["state"]}


def resolve_scheme_proposal(conn: sqlite3.Connection, proposal_id: int, save: bool, now: datetime) -> bool:
    """Save a pending proposal as its subject's scheme (older pending ones of that subject are superseded),
    or discard it; False when it was not pending."""
    cur = conn.execute("UPDATE grading_scheme_proposals SET state = ?, resolved_at = ? WHERE id = ? AND state = 'pending'",
                       ("saved" if save else "discarded", timefmt.iso(now), proposal_id))
    if save and cur.rowcount == 1:
        row = conn.execute("SELECT subject, scheme FROM grading_scheme_proposals WHERE id = ?", (proposal_id,)).fetchone()
        conn.execute("INSERT INTO grading_schemes(subject, scheme, saved_at) VALUES (?, ?, ?) ON CONFLICT(subject) "
                     "DO UPDATE SET scheme = excluded.scheme, saved_at = excluded.saved_at",
                     (row["subject"], row["scheme"], timefmt.iso(now)))
        conn.execute("UPDATE grading_scheme_proposals SET state = 'discarded', resolved_at = ? "
                     "WHERE state = 'pending' AND subject = ? AND id < ?", (timefmt.iso(now), row["subject"], proposal_id))
    conn.commit()
    return cur.rowcount == 1


def manual_grades(conn: sqlite3.Connection, subject: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM manual_grades WHERE subject = ? ORDER BY recorded_at, label", (subject,)).fetchall()
    return [{"period": r["period"], "component": r["component"], "label": r["label"], "score": r["score"],
             "out_of": r["out_of"], "recorded_at": r["recorded_at"]} for r in rows]


def set_manual_grade(conn: sqlite3.Connection, subject: str, period: str, component: str, label: str,
                     score: float | None, out_of: float | None, now: datetime) -> bool:
    """Record (or, with `score` None, remove) a grade the captain gave; False when there was nothing to remove."""
    if score is None:
        cur = conn.execute("DELETE FROM manual_grades WHERE subject = ? AND period = ? AND component = ? AND label = ?",
                           (subject, period, component, label))
    else:
        cur = conn.execute(
            "INSERT INTO manual_grades(subject, period, component, label, score, out_of, recorded_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?) ON CONFLICT(subject, period, component, label) DO UPDATE SET score = excluded.score,"
            " out_of = excluded.out_of, recorded_at = excluded.recorded_at",
            (subject, period, component, label, score, out_of, timefmt.iso(now)))
    conn.commit()
    return cur.rowcount == 1


# -- submissions --------------------------------------------------------------------------

# A press whose process died mid-upload leaves its proposal «submitting»; after this long it may be pressed again.
STUCK_SUBMISSION_MINUTES = 10


def new_submission_proposal(conn: sqlite3.Connection, subject: str, course_id: int, assignment_id: int,
                            assignment_name: str, pdf: str, pages: int, now: datetime) -> int:
    """A newer PDF for the same assignment replaces the pending one: its card stops working."""
    conn.execute("UPDATE submission_proposals SET state = 'replaced', updated_at = ? "
                 "WHERE assignment_id = ? AND state = 'pending'", (timefmt.iso(now), assignment_id))
    cur = conn.execute(
        "INSERT INTO submission_proposals(subject, course_id, assignment_id, assignment_name, pdf, pages, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", (subject, course_id, assignment_id, assignment_name, pdf, pages, timefmt.iso(now)))
    conn.commit()
    return int(cur.lastrowid)


def submission_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM submission_proposals WHERE id = ?", (proposal_id,)).fetchone()
    return dict(row) if row else None


def claim_submission(conn: sqlite3.Connection, proposal_id: int, now: datetime) -> bool:
    """pending → submitting, once: a double press uploads nothing twice."""
    stuck = timefmt.iso(now - timedelta(minutes=STUCK_SUBMISSION_MINUTES))
    cur = conn.execute("UPDATE submission_proposals SET state = 'submitting', updated_at = ? WHERE id = ? AND "
                       "(state = 'pending' OR (state = 'submitting' AND updated_at < ?))",
                       (timefmt.iso(now), proposal_id, stuck))
    conn.commit()
    return cur.rowcount == 1


def set_submission_state(conn: sqlite3.Connection, proposal_id: int, state: str, now: datetime,
                         only_from: str | None = None) -> bool:
    sql = "UPDATE submission_proposals SET state = ?, updated_at = ? WHERE id = ?"
    params = [state, timefmt.iso(now), proposal_id]
    if only_from:
        sql += " AND state = ?"
        params.append(only_from)
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.rowcount == 1


# -- class notes -------------------------------------------------------------------------


def _note(row: sqlite3.Row) -> dict:
    return {**dict(row), "ignored": bool(row["ignored"]), "handed_images": json.loads(row["handed_images"])}


def class_note(conn: sqlite3.Connection, note_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM class_notes WHERE id = ?", (note_id,)).fetchone()
    return _note(row) if row else None


def see_note(conn: sqlite3.Connection, path: str, digest: str, now: datetime, *, old: bool = False) -> dict:
    """The note at `path` as of this scan: new ones start now, and a changed text moves `changed_at` to now.
    An `old` note (written long before Vinci first saw it) is recorded as ignored."""
    stamp = timefmt.iso(now)
    conn.execute("INSERT INTO class_notes(path, digest, first_seen, changed_at, ignored) VALUES (?, ?, ?, ?, ?) "
                 "ON CONFLICT(path) DO UPDATE SET changed_at = CASE WHEN digest != excluded.digest "
                 "THEN excluded.changed_at ELSE changed_at END, digest = excluded.digest, gone_at = NULL",
                 (path, digest, stamp, stamp, int(old)))
    conn.commit()
    return _note(conn.execute("SELECT * FROM class_notes WHERE path = ?", (path,)).fetchone())


def notes_gone(conn: sqlite3.Connection, present: set[str], now: datetime) -> None:
    for row in conn.execute("SELECT id, path FROM class_notes WHERE gone_at IS NULL").fetchall():
        if row["path"] not in present:
            conn.execute("UPDATE class_notes SET gone_at = ? WHERE id = ?", (timefmt.iso(now), row["id"]))
    conn.commit()


def set_note_subject(conn: sqlite3.Connection, note_id: int, code: str, how: str) -> None:
    """A note moved to another subject is summarized there from the start."""
    conn.execute("UPDATE class_notes SET summarized_text = CASE WHEN subject IS ? THEN summarized_text END, "
                 "handed_images = CASE WHEN subject IS ? THEN handed_images ELSE '[]' END, "
                 "subject = ?, decided_by = ?, ignored = 0 WHERE id = ?", (code, code, code, how, note_id))
    conn.commit()


def update_note(conn: sqlite3.Connection, note_id: int, **values) -> None:
    allowed = {"ignored", "asked_at", "announced_at", "summarized_text", "summarized_at", "handed_images",
               "checked_digest"}
    assert set(values) <= allowed, values
    if "handed_images" in values:
        values["handed_images"] = json.dumps(values["handed_images"], ensure_ascii=False)
    for key in ("asked_at", "announced_at", "summarized_at"):
        if isinstance(values.get(key), datetime):
            values[key] = timefmt.iso(values[key])
    conn.execute(f"UPDATE class_notes SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                 (*values.values(), note_id))
    conn.commit()


def see_question(conn: sqlite3.Connection, note_id: int, question: str, now: datetime) -> None:
    conn.execute("INSERT OR IGNORE INTO note_questions(note_id, question, seen_at) VALUES (?, ?, ?)",
                 (note_id, question, timefmt.iso(now)))
    conn.commit()


def unsent_questions(conn: sqlite3.Connection, note_id: int) -> list[str]:
    rows = conn.execute("SELECT question FROM note_questions WHERE note_id = ? AND handoff_id IS NULL "
                        "ORDER BY seen_at, rowid", (note_id,)).fetchall()
    return [r["question"] for r in rows]


def question_sent(conn: sqlite3.Connection, note_id: int, question: str, handoff_id: int) -> None:
    conn.execute("UPDATE note_questions SET handoff_id = ? WHERE note_id = ? AND question = ?",
                 (handoff_id, note_id, question))
    conn.commit()
