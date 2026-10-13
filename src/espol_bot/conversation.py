"""What Vinci knows about the chat it answers, kept outside the model's history: the clock and what kind of chat
it is, and the notes that hold in that chat only (`chat_note`: how a group wants to be spoken to, something agreed
there).

The vinci-botones plugin adds `context()` to every turn's message (hook pre_llm_call, `espol-bot contexto`). Hermes
stamps a conversation with the day it started, so a chat open for days kept that day as «today»; and a group's habits
saved in Vinci's memory (MEMORY.md, USER.md, the same in every chat) followed the student into his private chat.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from aula_core import timefmt
from aula_core.config import CoreConfig

MAX_NOTES = 10
NOTE_CHARS = 300
HEADER = "[Contexto de este chat: lo agrega el sistema en cada mensaje; el estudiante no lo escribió ni lo ve]"


class NoteError(ValueError):
    """A note the model must fix or drop: the message says why."""


def chat_key(platform: str, chat_id: str) -> str:
    return f"{platform}:{chat_id}" if platform and chat_id else ""


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


def clock(now: datetime, core: CoreConfig) -> str:
    local = now.astimezone(core.tz)
    return (f"{timefmt.DAYS_LONG[local.weekday()]} {local.day} {timefmt.MONTHS[local.month - 1]} {local.year}, "
            f"{local:%H:%M}")


def context(conn: sqlite3.Connection, core: CoreConfig, now: datetime, *, chat: str, chat_type: str) -> str:
    """The block the model reads at the end of each message of this chat."""
    lines = [HEADER, f"Ahora: {clock(now, core)} (hora de Ecuador). Úsala para «hoy», «mañana» y lo que vence."]
    if chat_type == "group":
        lines.append("Chat: un grupo de WhatsApp; todo el grupo lee lo que contestas.")
    elif chat_type:
        lines.append("Chat: su chat privado contigo.")
    here = notes(conn, chat) if chat else []
    if here:
        lines.append("Notas de este chat (valen solo aquí): " + " · ".join(f"#{n['id']} {n['text']}" for n in here))
    return "\n".join(lines)
