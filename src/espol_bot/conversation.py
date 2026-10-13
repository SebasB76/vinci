"""What Vinci knows about the conversation it answers, kept outside the model's history so it survives a new
conversation, a restart and a long chat's summary:

- the clock and what kind of chat it is;
- notes that hold in that chat only (`chat_note`: how a group wants to be spoken to, something agreed there);
- the subject in focus: the one the student last named here, for what comes in without one (a photo, a voice note,
  «anota…»), while it lasts;
- the activity open here (a quiz, a study session), active or paused, with where it got to: Vinci answers whatever
  else comes up without dragging it along, and takes it up again when asked;
- in a private chat, the PDFs waiting for the student's vote and what became of the recent ones, so «ya lo entregué»
  only comes after the vote did it.

The vinci-botones plugin adds `context()` to every turn's message (hook pre_llm_call, `espol-bot contexto`), after
`note_turn` read the student's message. Hermes stamps a conversation with the day it started, so a chat open for days
kept that day as «today»; and a group's habits saved in Vinci's memory followed the student into his private chat.
A focus and an activity belong to one Hermes session key: a private chat, or one person in a group.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from aula_core import timefmt
from aula_core.config import CoreConfig
from espol_bot import materias

MAX_NOTES = 10
NOTE_CHARS = 300
FOCUS_TTL = timedelta(hours=3)
ACTIVITY_IDLE = timedelta(hours=4)  # an activity left this long is paused: it waits to be asked for again
ACTIVITY_KEEP = timedelta(days=3)  # one paused longer is not brought up any more (it stays in the table)
RECENT = timedelta(hours=24)  # a submission's outcome stays in the context this long
KINDS = {"quiz": "quiz", "study": "sesión de estudio", "jury": "práctica de exposición"}
HEADER = "[Contexto de este chat: lo agrega el sistema en cada mensaje; el estudiante no lo escribió ni lo ve]"
SYSTEM_TASK = "[Tarea del sistema"


class NoteError(ValueError):
    """A note or an activity the model must fix: the message says why."""


def chat_key(platform: str, chat_id: str) -> str:
    return f"{platform}:{chat_id}" if platform and chat_id else ""


# -- notes of one chat --------------------------------------------------------------------


def notes(conn: sqlite3.Connection, chat: str) -> list[dict]:
    rows = conn.execute("SELECT id, text, created_at FROM chat_notes WHERE chat = ? ORDER BY id", (chat,)).fetchall()
    return [{"id": r["id"], "text": r["text"], "created_at": r["created_at"]} for r in rows]


def add_note(conn: sqlite3.Connection, chat: str, text: str, now: datetime) -> dict:
    text = " ".join(str(text or "").split())
    if not text or len(text) > NOTE_CHARS:
        raise NoteError(f"La nota debe tener entre 1 y {NOTE_CHARS} caracteres.")
    present = notes(conn, chat)
    same = next((n for n in present if n["text"].casefold() == text.casefold()), None)
    if same:
        return same
    if len(present) >= MAX_NOTES:
        raise NoteError(f"Este chat ya tiene {MAX_NOTES} notas: borra una que ya no valga (action: remove).")
    note_id = conn.execute("INSERT INTO chat_notes(chat, text, created_at) VALUES (?, ?, ?)",
                           (chat, text, timefmt.iso(now))).lastrowid
    conn.commit()
    return {"id": note_id, "text": text, "created_at": timefmt.iso(now)}


def remove_note(conn: sqlite3.Connection, chat: str, note_id: int) -> bool:
    removed = conn.execute("DELETE FROM chat_notes WHERE chat = ? AND id = ?", (chat, note_id)).rowcount == 1
    conn.commit()
    return removed


# -- the subject in focus -----------------------------------------------------------------


def set_focus(conn: sqlite3.Connection, session: str, code: str, now: datetime, how: str) -> None:
    if not session:
        return
    conn.execute("INSERT INTO chat_focus(session, subject, set_at, how) VALUES (?, ?, ?, ?) ON CONFLICT(session) DO "
                 "UPDATE SET subject = excluded.subject, set_at = excluded.set_at, how = excluded.how",
                 (session, code, timefmt.iso(now), how))
    conn.commit()


def focus(conn: sqlite3.Connection, session: str, now: datetime) -> dict | None:
    """{subject (its code), set_at, how} while it lasts (FOCUS_TTL since it was last named), else None."""
    row = conn.execute("SELECT * FROM chat_focus WHERE session = ?", (session,)).fetchone() if session else None
    if row is None or now - timefmt.parse(row["set_at"]) > FOCUS_TTL:
        return None
    return {"subject": row["subject"], "set_at": row["set_at"], "how": row["how"]}


def note_turn(conn: sqlite3.Connection, subjects: list[materias.Subject], session: str, message: str,
              now: datetime) -> None:
    """The student's own message: a single subject named in it becomes the focus. A system task (a brief) is not his."""
    if not session or not message or message.lstrip().startswith(SYSTEM_TASK):
        return
    named = materias.mentioned(subjects, message)
    if len(named) == 1:
        set_focus(conn, session, named[0].code, now, "named")


# -- activities ---------------------------------------------------------------------------


def _activity(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "kind": row["kind"], "subject": row["subject"], "topic": row["topic"],
            "state": row["state"], "data": json.loads(row["data"] or "{}"), "started_at": row["started_at"],
            "updated_at": row["updated_at"]}


def start_activity(conn: sqlite3.Connection, session: str, kind: str, subject: str | None, topic: str, data: dict,
                   now: datetime) -> dict:
    """A new activity, active; the one open before it is paused, not lost."""
    if kind not in KINDS:
        raise NoteError(f"«kind» debe ser uno de: {', '.join(KINDS)}.")
    topic = " ".join(str(topic or "").split())[:120]
    if not topic:
        raise NoteError("Falta el tema («topic»).")
    conn.execute("UPDATE activities SET state = 'paused', updated_at = ? WHERE session = ? AND state = 'active'",
                 (timefmt.iso(now), session))
    activity_id = conn.execute(
        "INSERT INTO activities(session, kind, subject, topic, state, data, started_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
        (session, kind, subject, topic, json.dumps(data, ensure_ascii=False), timefmt.iso(now), timefmt.iso(now))
    ).lastrowid
    conn.commit()
    return activity(conn, activity_id)


def activity(conn: sqlite3.Connection, activity_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    return _activity(row) if row else None


def update_activity(conn: sqlite3.Connection, activity_id: int, now: datetime, *, state: str | None = None,
                    data: dict | None = None) -> dict:
    current = activity(conn, activity_id)
    if current is None:
        raise NoteError("Esa actividad ya no existe.")
    if state == "active":  # only one active per conversation
        conn.execute("UPDATE activities SET state = 'paused', updated_at = ? WHERE session = ? AND state = 'active' "
                     "AND id != ?", (timefmt.iso(now), _session_of(conn, activity_id), activity_id))
    conn.execute("UPDATE activities SET state = ?, data = ?, updated_at = ? WHERE id = ?",
                 (state or current["state"], json.dumps(data if data is not None else current["data"],
                                                        ensure_ascii=False), timefmt.iso(now), activity_id))
    conn.commit()
    return activity(conn, activity_id)


def _session_of(conn: sqlite3.Connection, activity_id: int) -> str:
    return conn.execute("SELECT session FROM activities WHERE id = ?", (activity_id,)).fetchone()["session"]


def open_activities(conn: sqlite3.Connection, session: str, now: datetime) -> list[dict]:
    """The activities not done here, newest first; one left alone for ACTIVITY_IDLE is paused on the way, and one
    untouched for ACTIVITY_KEEP is left out."""
    if not session:
        return []
    found = []
    for row in conn.execute("SELECT * FROM activities WHERE session = ? AND state != 'completed' AND updated_at >= ? "
                            "ORDER BY updated_at DESC, id DESC LIMIT 5",
                            (session, timefmt.iso(now - ACTIVITY_KEEP))).fetchall():
        item = _activity(row)
        if item["state"] == "active" and now - timefmt.parse(item["updated_at"]) > ACTIVITY_IDLE:
            conn.execute("UPDATE activities SET state = 'paused' WHERE id = ?", (item["id"],))
            conn.commit()
            item["state"] = "paused"
        found.append(item)
    return found


# -- the turn's context -------------------------------------------------------------------


def clock(now: datetime, core: CoreConfig) -> str:
    local = now.astimezone(core.tz)
    return (f"{timefmt.DAYS_LONG[local.weekday()]} {local.day} {timefmt.MONTHS[local.month - 1]} {local.year}, "
            f"{local:%H:%M}")


def _ago(moment: str, now: datetime) -> str:
    return timefmt.until(moment, now).removeprefix("hace ") or "un momento"


def _describe(core: CoreConfig, conn: sqlite3.Connection, item: dict, names: dict[str, str],
              now: datetime) -> str | None:
    """One line on an open activity; None for a quiz already answered in full (it is closed on the way)."""
    from espol_bot import quiz
    subject = names.get(item["subject"] or "", item["subject"] or "")
    where = f" de {subject}" if subject else ""
    state = "en curso" if item["state"] == "active" else "en pausa"
    if item["kind"] == "quiz":
        done = quiz.progress(core, item["data"].get("code", ""), int(item["data"].get("quiz_id") or 0))
        if done is None or done["finished"]:
            conn.execute("UPDATE activities SET state = 'completed' WHERE id = ?", (item["id"],))
            conn.commit()
            return None
        return (f"#{item['id']} quiz «{item['topic']}»{where} ({state}): respondió {done['answered']} de "
                f"{done['questions']}; las encuestas siguen en su chat privado")
    data, line = item["data"], f"#{item['id']} {KINDS[item['kind']]} «{item['topic']}»{where} ({state})"
    if data.get("minutes"):
        left = int(data["minutes"]) - int((now - timefmt.parse(item["started_at"])).total_seconds() // 60)
        line += f", {data['minutes']} min desde hace {_ago(item['started_at'], now)}" + (
            f" (quedan unos {left} min)" if item["state"] == "active" and left > 0 else "")
    if data.get("goal"):
        line += f"; meta: {data['goal']}"
    steps = data.get("steps") or []
    if item["kind"] == "jury":
        line += f"; lleva {len(steps)} pregunta(s)"
    if steps:
        line += f"; último paso: {steps[-1].get('done')}" + (f"; sigue: {steps[-1]['next']}" if steps[-1].get("next")
                                                            else "")
    return line


def submissions(conn: sqlite3.Connection, core: CoreConfig, now: datetime) -> str | None:
    """The PDFs waiting for the student's vote and what became of the recent ones, from the table the vote writes:
    what Vinci says it did has to match this, not what the conversation remembers."""
    rows = conn.execute("SELECT assignment_name, pages, state, created_at, updated_at FROM submission_proposals "
                        "WHERE state IN ('pending', 'submitting') OR (state IN ('submitted', 'failed', 'cancelled') AND updated_at >= ?) "
                        "ORDER BY id DESC LIMIT 4", (timefmt.iso(now - RECENT),)).fetchall()
    said = []
    for r in rows:
        at = f"{timefmt.parse(r['updated_at'] or r['created_at']).astimezone(core.tz):%H:%M}"
        said.append({"pending": f"el PDF de «{r['assignment_name']}» ({r['pages']} pág.) espera su voto «Entregar»: "
                                "todavía NO está entregado",
                     "submitting": f"«{r['assignment_name']}» se está subiendo al aula ahora, con su voto",
                     "submitted": f"«{r['assignment_name']}» se entregó en el aula a las {at}, con su voto",
                     "failed": f"la entrega de «{r['assignment_name']}» falló a las {at}: NO está entregada",
                     "cancelled": f"canceló la entrega de «{r['assignment_name']}» a las {at}"}[r["state"]])
    return ("Entregas con PDF (lo que de verdad pasó; no digas otra cosa): " + " · ".join(said) + ".") if said else None


def context(conn: sqlite3.Connection, core: CoreConfig, now: datetime, *, chat: str, chat_type: str,
            session: str = "", subjects: list[materias.Subject] | None = None) -> str:
    """The block the model reads at the end of each message of this chat."""
    lines = [HEADER, f"Ahora: {clock(now, core)} (hora de Ecuador). Úsala para «hoy», «mañana» y lo que vence."]
    if chat_type == "group":
        lines.append("Chat: un grupo de WhatsApp; todo el grupo lee lo que contestas.")
    elif chat_type:
        lines.append("Chat: su chat privado contigo.")
    here = notes(conn, chat) if chat else []
    if here:
        lines.append("Notas de este chat (valen solo aquí): " + " · ".join(f"#{n['id']} {n['text']}" for n in here))
    names = {s.code: s.name for s in subjects or []}
    current = focus(conn, session, now)
    if current:
        name = names.get(current["subject"], current["subject"])
        lines.append(f"Materia en foco: {name} (desde hace {_ago(current['set_at'], now)}). Una foto, una nota de voz "
                     f"o un «anota…» que llega sin materia es de {name}, salvo que diga otra.")
    described = [line for line in (_describe(core, conn, a, names, now) for a in open_activities(conn, session, now))
                 if line]
    if described:
        lines.append("Actividades abiertas aquí: " + " · ".join(described) + ". Si su mensaje no es parte de una, "
                     "contesta lo que pide y no la retomes ni la ofrezcas: sigue abierta para cuando él la pida.")
    handed = submissions(conn, core, now) if chat_type and chat_type != "group" else None
    if handed:
        lines.append(handed)
    return "\n".join(lines)
