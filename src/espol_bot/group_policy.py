"""Where each tool's answer lands when it is called from a WhatsApp group, in one table.

The tools decide the delivery (a page with someone's data always goes to their private chat); this table is what
the model is told about it, added to the tool's result by `herramientas`, so no tool repeats its own group line and
the SKILL.md files point here instead of restating it.
"""

from __future__ import annotations

GROUP = "group"      # the whole group sees it
PRIVATE = "private"  # it went to the sender's private chat

TELL_PRIVATE = "Estás en un grupo y esto le llegó a su chat privado: dile en el grupo, en una línea, que se lo mandaste por privado."
TELL_GROUP = "Estás en un grupo: esto lo ve todo el grupo."

# tool → (where its answer lands, the line the model gets in a group)
TOOLS: dict[str, tuple[str, str]] = {
    "show_page": (PRIVATE, TELL_PRIVATE),
    "academic_record": (PRIVATE, TELL_PRIVATE),
    "add_todo": (PRIVATE, TELL_PRIVATE + " Si era algo para todo el grupo a una hora, era chat_reminder."),
    "propose_grading_scheme": (PRIVATE, TELL_PRIVATE),
    "proponer_horario": (PRIVATE, TELL_PRIVATE),
    "join_group": (GROUP, TELL_GROUP + " Solo cuenta el voto de quien lo pidió: los demás no pueden unirlo."),
    "prepare_submission": (PRIVATE, TELL_PRIVATE + " Cuando vote Entregar, yo aviso aquí que quedó entregado; tú no "
                                                   "lo anuncias."),
    "draft_submission": (PRIVATE, TELL_PRIVATE + " Cuando vote Entregar, yo aviso aquí que quedó entregado; tú no "
                                                 "lo anuncias."),
    "send_quiz": (GROUP, TELL_GROUP + " Vota quien quiera; los resultados los mando yo al grupo, tú no los anuncias."),
    "send_study_page": (GROUP, TELL_GROUP + " El repaso sale solo del material del curso, nunca de su cuaderno."),
    "chat_reminder": (GROUP, TELL_GROUP + " El recordatorio sale en este grupo a su hora."),
    "chat_note": (GROUP, "Estás en un grupo: la nota vale solo en este grupo."),
}


def group_of(channel: dict) -> str | None:
    """The WhatsApp group («…@g.us») a tool call comes from; None in a private chat or outside WhatsApp."""
    chat = str(channel.get("chat") or "").removeprefix("whatsapp:")
    return chat if channel.get("canal") == "whatsapp" and chat.endswith("@g.us") else None


def note(tool: str, channel: dict) -> str | None:
    """The line the model gets with this tool's result when it was called from a group."""
    if group_of(channel) is None or tool not in TOOLS:
        return None
    return TOOLS[tool][1]
