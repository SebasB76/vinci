"""The order of the captain's pending deliverables, in the 7:00 summary and in Vinci's `semana`, with no model.

Overdue first; then what is due within URGENT, by due date (no time left to weigh it against anything);
then the rest by how many points of the final grade it is worth under its subject's saved scheme
(grades.weights), heaviest first; last, by due date, what has no known weight: a subject with no saved
scheme, an assignment no component takes, a to-do from the captain's list. A weight is never guessed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aula_core import timefmt
from espol_bot import agenda, grades, materias, store

URGENT = timedelta(hours=24)
TIERS = ("overdue", "urgent", "weighted", "unweighted")
LATEST = datetime.max.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Entry:
    item: dict                # a queries.* assignment, or a store to-do when `todo`
    todo: bool
    due: datetime | None
    weight: float | None      # points of the final 100
    unknown: str | None       # why no weight: no_scheme, no_component, not_weighable; None for a to-do
    tier: str


def weights(conn: sqlite3.Connection, subjects: list[materias.Subject], tz: ZoneInfo) -> tuple[dict, set[int]]:
    """{assignment id: weight or None} under every saved scheme, and the course ids those subjects cover."""
    found: dict[int, float | None] = {}
    covered: set[int] = set()
    for subject in subjects:
        saved = store.grading_scheme(conn, subject.code)
        if saved is None:
            continue
        ids = agenda.course_ids_for(conn, subject)
        covered.update(ids)
        found.update(grades.weights(saved["scheme"], grades.assignments(conn, ids),
                                    store.manual_grades(conn, subject.code), tz))
    return found, covered


def _tier(due: datetime | None, weight: float | None, now: datetime) -> str:
    if due is not None and due < now:
        return "overdue"
    if due is not None and due <= now + URGENT:
        return "urgent"
    return "weighted" if weight is not None else "unweighted"


def ordered(conn: sqlite3.Connection, subjects: list[materias.Subject], tz: ZoneInfo, now: datetime,
            tasks: list[dict], todos: list[dict]) -> list[Entry]:
    """`tasks` (unsubmitted assignments from aula_core.queries) and the dated `todos`, in priority order."""
    found, covered = weights(conn, subjects, tz)
    entries = []
    for t in tasks:
        weight = found.get(t["id"])
        unknown = (None if weight is not None else "not_weighable" if t["id"] in found
                   else "no_component" if t["curso_id"] in covered else "no_scheme")
        due = timefmt.parse(t["vence"])
        entries.append(Entry(t, False, due, weight, unknown, _tier(due, weight, now)))
    for todo in todos:
        due = timefmt.parse(todo["due_at"])
        if due is not None:
            entries.append(Entry(todo, True, due, None, None, _tier(due, None, now)))

    def key(entry: Entry):
        # At one decimal, as the summary shows them: two that read the same go by due date.
        heavier = -round(entry.weight, 1) if entry.tier == "weighted" else 0
        return TIERS.index(entry.tier), heavier, entry.due or LATEST
    return sorted(entries, key=key)
