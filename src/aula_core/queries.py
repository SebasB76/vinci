"""Read-side queries over the local store. Every function returns plain dicts,
so the CLI, the bot, or a future web page can render them however they like."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from aula_core import extract, ocr, timefmt
from aula_core.catalog import KIND_LABEL, PUBLIC, WHY_LINK_ONLY, fold, is_old, term_year

DONE_SQL = ("(a.excused = 1 OR a.submitted_at IS NOT NULL"
            " OR COALESCE(a.sub_state, '') IN ('submitted', 'graded', 'pending_review')"
            " OR a.id IN (SELECT assignment_id FROM marked_submitted))")
OFFLINE_TYPES = {"none", "on_paper"}


class NotFound(Exception):
    pass


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
    """Newest first, each with the files and outside links it points to (its text alone loses them)."""
    extra, params = _course_filter(ids, "n.course_id")
    rows = conn.execute(
        f"""SELECT n.*, c.name AS course_name FROM announcements n JOIN courses c ON c.id = n.course_id
            WHERE c.active = 1{extra} ORDER BY n.posted_at DESC LIMIT ?""",
        [*params, limit],
    ).fetchall()
    result = []
    for r in rows:
        material = json.loads(r["material"] or "{}")
        files, urls = material.get("files") or [], material.get("links") or []
        linked = conn.execute(
            f"""SELECT l.*, c.name AS course_name FROM links l JOIN courses c ON c.id = l.course_id
                WHERE l.course_id = ? AND l.url IN ({','.join('?' * len(urls)) or 'NULL'})""",
            [r["course_id"], *urls]).fetchall()
        attached = conn.execute(f"SELECT id, display_name FROM files WHERE active = 1 AND id IN "
                                f"({','.join('?' * len(files)) or 'NULL'})", files).fetchall()
        result.append({"id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "titulo": r["title"],
                       "autor": r["author"], "publicado": r["posted_at"], "texto": r["message_text"],
                       "url": r["html_url"], "archivos": [{"archivo_id": f["id"], "archivo": f["display_name"]}
                                                          for f in attached],
                       "enlaces": sorted((_link(link) for link in linked), key=lambda link: urls.index(link["url"]))})
    return result


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


INDEX_STATE = {"ok": "leído", "escaneado": "escaneado", "sin_texto": "sin texto", "no_soportado": "formato que no leo",
               "error_lectura": "no se pudo leer"}


def file_state(f: dict, max_mb: float) -> str:
    """leído · escaneado (its pages are images) · sin bajar · muy grande para bajar · no se pudo bajar · …"""
    if f["descargado"] and f["indexado"] in INDEX_STATE:
        return INDEX_STATE[f["indexado"]]
    if f["indexado"] == "muy_grande" or (f["tamano"] or 0) > max_mb * 1024 * 1024:
        return "muy grande para bajar"
    return "no se pudo bajar" if f["indexado"] == "error_descarga" else "sin bajar"


def _file(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "archivo": r["display_name"],
            "extension": Path(r["filename"] or r["display_name"] or "").suffix.lower().lstrip("."),
            "modulo": r["module"], "seccion": r["section"], "carpeta": r["folder"], "origen": r["source"],
            "tamano": r["size"], "subido": r["created_at"], "actualizado": r["updated_at"],
            "descargado": r["local_path"] if r["local_path"] and Path(r["local_path"]).exists() else None,
            "indexado": r["index_status"], "paginas": r["pages"], "idioma": r["language"] or None,
            "copia_de": r["duplicate_of"], "url": r["html_url"],
            "anterior": is_old(r["folder"], r["display_name"], term_year(r["term_start"], r["course_name"], r["term"]))}


def files(conn: sqlite3.Connection, ids: list[int] | None = None, name: str | None = None) -> list[dict]:
    """The catalog: every document the aula shows (downloaded or not) plus what was added by hand."""
    extra, params = _course_filter(ids, "f.course_id")
    rows = conn.execute(
        f"""SELECT f.*, c.name AS course_name, c.term_start, c.term FROM files f JOIN courses c ON c.id = f.course_id
            WHERE f.active = 1 AND c.active = 1{extra} ORDER BY c.name, f.module, f.display_name""",
        params,
    ).fetchall()
    needle = fold(name) if name else None
    return [_file(r) for r in rows if not needle or any(
        needle in fold(r[k]) for k in ("display_name", "module", "section", "folder", "source"))]


def _link(r: sqlite3.Row) -> dict:
    why = r["problem"] if r["access"] == PUBLIC else WHY_LINK_ONLY.get(r["kind"], "no lo puedo abrir")
    return {"enlace_id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "titulo": r["title"],
            "tipo": KIND_LABEL.get(r["kind"], r["kind"]), "acceso": r["access"], "modulo": r["module"],
            "seccion": r["section"], "origen": r["source"], "archivo_id": r["file_id"], "motivo": why,
            "probado": r["checked_at"], "url": r["url"]}


def links(conn: sqlite3.Connection, ids: list[int] | None = None, name: str | None = None) -> list[dict]:
    """Outside links of the courses: what they are, whether a bot may open them (acceso «publico»: it tries
    without a login) and what that gave: the file it opened (archivo_id), or why it does not open (motivo)."""
    extra, params = _course_filter(ids, "l.course_id")
    rows = conn.execute(
        f"""SELECT l.*, c.name AS course_name FROM links l JOIN courses c ON c.id = l.course_id
            WHERE l.active = 1 AND c.active = 1{extra} ORDER BY c.name, l.module, l.id""",
        params,
    ).fetchall()
    needle = fold(name) if name else None
    return [_link(r) for r in rows
            if not needle or any(needle in fold(r[k]) for k in ("title", "module", "section", "source", "url"))]


def bibliography(conn: sqlite3.Connection, ids: list[int]) -> dict | None:
    """The books the newest syllabus of these courses names: {'principal': [...], 'complementaria': [...], ...}."""
    extra, params = _course_filter(ids, "b.course_id")
    row = conn.execute(
        f"""SELECT b.*, f.display_name, f.html_url FROM bibliography b JOIN files f ON f.id = b.file_id
            WHERE f.active = 1 AND b.main != '[]'{extra} ORDER BY f.updated_at DESC, b.file_id DESC LIMIT 1""",
        params,
    ).fetchone()
    if row is None:
        return None
    return {"principal": json.loads(row["main"]), "complementaria": json.loads(row["others"]),
            "silabo": row["display_name"], "silabo_id": row["file_id"], "url": row["html_url"]}


def ocr_state(conn: sqlite3.Connection, digest: str | None) -> dict | None:
    """The pages of a file that are only an image: how many OCR read, how many wait, which read poorly."""
    rows = conn.execute("SELECT page, text, confidence FROM ocr_pages WHERE digest = ? ORDER BY page",
                        (digest,)).fetchall() if digest else []
    if not rows:
        return None
    return {"pages": len(rows), "read": sum(1 for r in rows if r["text"]),
            "pending": sum(1 for r in rows if r["text"] is None),
            "doubtful": [r["page"] for r in rows if r["text"] and ocr.doubtful(r["text"], r["confidence"])]}


def ocr_waiting(conn: sqlite3.Connection) -> int:
    """Scanned pages of downloaded files that OCR has not read yet."""
    return conn.execute("SELECT COUNT(*) FROM ocr_pages o WHERE o.text IS NULL AND EXISTS (SELECT 1 FROM files f"
                        " WHERE f.digest = o.digest AND f.local_path IS NOT NULL)").fetchone()[0]


def ocr_pages(conn: sqlite3.Connection, file_id: int) -> set[int]:
    """The pages of a file whose indexed text came from OCR."""
    return {r["page"] for r in conn.execute("SELECT o.page FROM ocr_pages o JOIN files f ON f.digest = o.digest"
                                            " WHERE f.id = ? AND o.text != ''", (file_id,))}


def file_by_id(conn: sqlite3.Connection, file_id: int) -> dict:
    row = conn.execute(
        "SELECT f.*, c.name AS course_name, c.term_start, c.term FROM files f JOIN courses c ON c.id = f.course_id"
        " WHERE f.id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"No conozco el archivo {file_id}. Prueba `aula archivos`.")
    return {**_file(row), "ocr": ocr_state(conn, row["digest"])}


def read_pages(conn: sqlite3.Connection, file_id: int, first: int | None = None, last: int | None = None) -> dict:
    """Text of an indexed file, page by page (optionally a page range); a page read with OCR says so."""
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
    read = ocr_pages(conn, file_id)
    return {**info, "unidad": unit,
            "contenido": [{"pagina": n, "texto": "".join(parts), **({"ocr": True} if n in read else {})}
                          for n, parts in sorted(pages.items())]}
