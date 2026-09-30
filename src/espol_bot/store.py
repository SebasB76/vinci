"""Vinci's own tables in espol.db (next to the aula_core tables).

  bot_reminders        which due-date reminders were already sent
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
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

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
CREATE TABLE IF NOT EXISTS horario_propuestas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clases TEXT NOT NULL,
    creado TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    resuelto TEXT
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


def claim_handoffs(conn: sqlite3.Connection, code: str, now: datetime, limit: int = 5) -> list[dict]:
    """The oldest unclaimed handoffs for `code` (up to `limit`), each marked claimed atomically
    so it is handed to the subject bot at most once."""
    claimed = []
    rows = conn.execute("SELECT * FROM entregas WHERE materia = ? AND reclamado IS NULL ORDER BY id LIMIT ?",
                        (code, limit)).fetchall()
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
