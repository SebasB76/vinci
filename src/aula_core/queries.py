"""Read-side queries over the local store. Every function returns plain dicts,
so the CLI, the bot, or a future web page can render them however they like."""

from __future__ import annotations

import sqlite3
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from aula_core import extract, timefmt

DONE_SQL = ("(a.excused = 1 OR a.submitted_at IS NOT NULL"
            " OR COALESCE(a.sub_state, '') IN ('submitted', 'graded', 'pending_review'))")
OFFLINE_TYPES = {"none", "on_paper"}


class NotFound(Exception):
    pass


def fold(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()


def courses(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM courses WHERE active = 1 ORDER BY name").fetchall()
    return [
        {"id": r["id"], "nombre": r["name"], "codigo": r["course_code"], "periodo": r["term"],
         "nota_actual": r["current_score"], "calificacion_actual": r["current_grade"], "url": r["html_url"]}
        for r in rows
    ]


def course_ids(conn: sqlite3.Connection, fragment: str | None) -> list[int] | None:
    """Course ids whose name or code contains `fragment` (accent/case-insensitive)."""
    if not fragment:
        return None
    needle = fold(fragment)
    rows = conn.execute("SELECT id, name, course_code FROM courses WHERE active = 1").fetchall()
    ids = [r["id"] for r in rows if needle in fold(r["name"]) or needle in fold(r["course_code"])]
    if not ids:
        raise NotFound(f"Ninguna materia coincide con «{fragment}». Prueba `aula cursos` para ver los nombres.")
    return ids


def _course_filter(ids: list[int] | None, column: str) -> tuple[str, list]:
    if ids is None:
        return "", []
    return f" AND {column} IN ({','.join('?' * len(ids))})", list(ids)


def _assignment(r: sqlite3.Row, now: datetime) -> dict:
    types = set((r["submission_types"] or "").split(",")) - {""}
    done = bool(r["done"])
    due = timefmt.parse(r["due_at"])
    offline = bool(types) and types <= OFFLINE_TYPES
    return {
        "id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "tarea": r["name"],
        "vence": r["due_at"], "entregada": done,
        # Canvas never records a submission for paper/no-submission items, so they are never "late".
        "atrasada": bool(due and due < now and not done and not offline),
        "sin_entrega_en_linea": offline,
        "puntos": r["points_possible"], "nota": r["score"], "calificacion": r["grade"], "url": r["html_url"],
    }


def assignments_between(conn: sqlite3.Connection, now: datetime, start: datetime, end: datetime,
                        ids: list[int] | None = None) -> list[dict]:
    extra, params = _course_filter(ids, "a.course_id")
    rows = conn.execute(
        f"""SELECT a.*, c.name AS course_name, {DONE_SQL} AS done FROM assignments a
            JOIN courses c ON c.id = a.course_id
            WHERE a.active = 1 AND c.active = 1 AND a.due_at >= ? AND a.due_at < ?{extra}
            ORDER BY a.due_at, c.name""",
        [timefmt.iso(start), timefmt.iso(end), *params],
    ).fetchall()
    return [_assignment(r, now) for r in rows]


def pending(conn: sqlite3.Connection, now: datetime, ids: list[int] | None = None, *,
            days: int | None = None, overdue_days: int = 7) -> list[dict]:
    """Not-yet-submitted assignments ordered by due date: recently overdue first, then
    upcoming, then the ones with no due date."""
    extra, params = _course_filter(ids, "a.course_id")
    since = timefmt.iso(now - timedelta(days=overdue_days))
    until = timefmt.iso(now + timedelta(days=days)) if days is not None else None
    rows = conn.execute(
        f"""SELECT a.*, c.name AS course_name, {DONE_SQL} AS done FROM assignments a
            JOIN courses c ON c.id = a.course_id
            WHERE a.active = 1 AND c.active = 1 AND NOT {DONE_SQL}
              AND (a.due_at IS NULL OR a.due_at >= ?){' AND a.due_at < ?' if until else ''}{extra}
            ORDER BY a.due_at IS NULL, a.due_at, c.name""",
        [since, *([until] if until else []), *params],
    ).fetchall()
    tasks = [_assignment(r, now) for r in rows]
    # A paper exam from yesterday is not "pending": it just never gets a Canvas submission.
    return [t for t in tasks if not (t["sin_entrega_en_linea"] and t["vence"] and timefmt.parse(t["vence"]) < now)]


def announcements(conn: sqlite3.Connection, ids: list[int] | None = None, *, limit: int = 10) -> list[dict]:
    extra, params = _course_filter(ids, "n.course_id")
    rows = conn.execute(
        f"""SELECT n.*, c.name AS course_name FROM announcements n JOIN courses c ON c.id = n.course_id
            WHERE c.active = 1{extra} ORDER BY n.posted_at DESC LIMIT ?""",
        [*params, limit],
    ).fetchall()
    return [{"id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "titulo": r["title"],
             "autor": r["author"], "publicado": r["posted_at"], "texto": r["message_text"], "url": r["html_url"]}
            for r in rows]


def grades(conn: sqlite3.Connection, ids: list[int] | None = None) -> list[dict]:
    extra, params = _course_filter(ids, "c.id")
    result = []
    for c in conn.execute(f"SELECT * FROM courses c WHERE c.active = 1{extra} ORDER BY c.name", params).fetchall():
        graded = conn.execute(
            """SELECT * FROM assignments WHERE course_id = ? AND active = 1 AND (score IS NOT NULL OR grade IS NOT NULL)
               ORDER BY COALESCE(graded_at, due_at) DESC""",
            (c["id"],),
        ).fetchall()
        result.append({
            "curso": c["name"], "curso_id": c["id"], "nota_actual": c["current_score"],
            "calificacion_actual": c["current_grade"],
            "tareas": [{"id": a["id"], "tarea": a["name"], "nota": a["score"], "calificacion": a["grade"],
                        "puntos": a["points_possible"], "calificada": a["graded_at"], "url": a["html_url"]}
                       for a in graded],
        })
    return result


def _file(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "archivo": r["display_name"],
            "modulo": r["module"], "tamano": r["size"], "actualizado": r["updated_at"],
            "descargado": r["local_path"] if r["local_path"] and Path(r["local_path"]).exists() else None,
            "indexado": r["index_status"], "paginas": r["pages"], "url": r["html_url"]}


def files(conn: sqlite3.Connection, ids: list[int] | None = None, name: str | None = None) -> list[dict]:
    extra, params = _course_filter(ids, "f.course_id")
    rows = conn.execute(
        f"""SELECT f.*, c.name AS course_name FROM files f JOIN courses c ON c.id = f.course_id
            WHERE f.active = 1 AND c.active = 1{extra} ORDER BY c.name, f.module, f.display_name""",
        params,
    ).fetchall()
    needle = fold(name) if name else None
    return [_file(r) for r in rows
            if not needle or needle in fold(r["display_name"]) or needle in fold(r["module"])]


def file_by_id(conn: sqlite3.Connection, file_id: int) -> dict:
    row = conn.execute(
        "SELECT f.*, c.name AS course_name FROM files f JOIN courses c ON c.id = f.course_id WHERE f.id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"No conozco el archivo {file_id}. Prueba `aula archivos`.")
    return _file(row)


def read_pages(conn: sqlite3.Connection, file_id: int, first: int | None = None, last: int | None = None) -> dict:
    """Text of an indexed file, page by page (optionally a page range)."""
    info = file_by_id(conn, file_id)
    rows = conn.execute(
        "SELECT page, text FROM chunks WHERE file_id = ? ORDER BY CAST(page AS INTEGER), rowid", (file_id,)
    ).fetchall()
    pages: dict[int, list[str]] = {}
    for r in rows:
        number = int(r["page"])
        if (first is None or number >= first) and (last is None or number <= last):
            pages.setdefault(number, []).append(r["text"])
    unit = extract.UNIT.get(Path(info["descargado"] or info["archivo"]).suffix.lower().lstrip("."), "página")
    return {**info, "unidad": unit,
            "contenido": [{"pagina": n, "texto": "".join(parts)} for n, parts in sorted(pages.items())]}
