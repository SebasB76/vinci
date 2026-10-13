"""Read-side queries over the local store. Every function returns plain dicts,
so the CLI, the bot, or a future web page can render them however they like."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from aula_core import extract, ocr, timefmt
from aula_core.catalog import (KIND_LABEL, PUBLIC, WHY_LINK_ONLY, assigned_files, fold, html_to_text, is_old,
                                term_year)

# A grade on something Canvas takes no upload for is the only sign from the aula that it is done.
DONE_SQL = ("(a.excused = 1 OR a.submitted_at IS NOT NULL"
            " OR COALESCE(a.sub_state, '') IN ('submitted', 'graded', 'pending_review')"
            " OR (COALESCE(a.submission_types, '') IN ('none', 'on_paper', 'external_tool') AND a.score IS NOT NULL)"
            " OR a.id IN (SELECT assignment_id FROM marked_submitted))")
OFFLINE_TYPES = {"none", "on_paper"}
QUIZ_FIELDS = ("question_count", "time_limit", "allowed_attempts", "unlock_at", "lock_at", "hide_results")
QUIZ_SQL = (", ".join(f"q.{f} AS quiz_{f}" for f in QUIZ_FIELDS) + ", q.quiz_id"
            ", (SELECT kind FROM assignment_delivery d WHERE d.assignment_id = a.id) AS delivery_said")
QUIZ_JOIN = "LEFT JOIN quizzes q ON q.assignment_id = a.id"

# How an assignment is handed in. For «none» and «on_paper» Canvas only says that nothing is uploaded there, which
# fits an exam in class as well as a lab finished on another platform: the instructions tell them apart, and the
# student's word (assignment_delivery) wins over both. Only a past event leaves the pending list on its own.
CANVAS_SUBMISSION, EXTERNAL_SUBMISSION, SCHEDULED_EVENT, UNKNOWN = (
    "canvas_submission", "external_submission", "scheduled_event", "unknown")
DELIVERIES = (CANVAS_SUBMISSION, EXTERNAL_SUBMISSION, SCHEDULED_EVENT, UNKNOWN)
DELIVERY_LABEL = {CANVAS_SUBMISSION: "se entrega en el aula", EXTERNAL_SUBMISSION: "se entrega fuera del aula",
                  SCHEDULED_EVENT: "es presencial: no hay nada que subir",
                  UNKNOWN: "el aula no dice cómo se entrega"}
# Over the folded instructions. Canvas itself appends «(Enlaces a un sitio externo.)» to a link that leaves the aula.
ELSEWHERE_RE = re.compile(r"\b(plataforma|laboratorio|labs?|submit|suban|subir|sube|subirlo|envien|enviar|repositorio|"
                          r"github|formulario|evidencia|captura|perusall|sitio externo)\b")
IN_PERSON_RE = re.compile(r"\b(examen(es)?|leccion(es)?|presencial|exposicion(es)?|sustentacion|defensa|prueba escrita|"
                          r"evaluacion escrita|asistencias?|participacion)\b")


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


def delivery(r: sqlite3.Row) -> tuple[str, str]:
    """(kind, what it rests on: «student», «canvas», «instructions», «title» or «no_instructions»)."""
    if r["delivery_said"] in DELIVERIES:
        return r["delivery_said"], "student"
    types = set((r["submission_types"] or "").split(",")) - {""}
    if "external_tool" in types:
        return EXTERNAL_SUBMISSION, "canvas"
    if not types or not types <= OFFLINE_TYPES:
        return CANVAS_SUBMISSION, "canvas"
    material = json.loads(r["material"] or "{}")
    if not r["description"] and not material.get("files") and not material.get("links"):
        # a grade column (the exam, participation), unless its name points elsewhere («PERUSALL: …»)
        return (EXTERNAL_SUBMISSION, "title") if ELSEWHERE_RE.search(fold(r["name"])) else (SCHEDULED_EVENT,
                                                                                            "no_instructions")
    text = fold(r["description"])
    elsewhere, in_person = bool(ELSEWHERE_RE.search(text)), bool(IN_PERSON_RE.search(text))
    if elsewhere != in_person:
        return (EXTERNAL_SUBMISSION if elsewhere else SCHEDULED_EVENT), "instructions"
    return UNKNOWN, "instructions"


def _assignment(r: sqlite3.Row, now: datetime) -> dict:
    types = set((r["submission_types"] or "").split(",")) - {""}
    done = bool(r["done"])
    due = timefmt.parse(r["due_at"])
    kind, basis = delivery(r)
    return {
        "id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "tarea": r["name"],
        "vence": r["due_at"], "entregada": done,
        # An event that passed was held, not missed; work done elsewhere is late until marked or graded.
        "atrasada": bool(due and due < now and not done and kind != SCHEDULED_EVENT),
        "sin_entrega_en_linea": bool(types) and types <= OFFLINE_TYPES,
        "delivery": kind, "delivery_basis": basis,
        "puntos": r["points_possible"], "nota": r["score"], "calificacion": r["grade"], "url": r["html_url"],
        "quiz": quiz_info(r, "quiz_"),
    }


def quiz_info(r, prefix: str = "") -> dict | None:
    """A quiz's settings as alerts and tools show them; None when the assignment is not a quiz read so far."""
    if r is None or r["quiz_id"] is None:
        return None
    return {f: r[prefix + f] for f in QUIZ_FIELDS}


def assignments_between(conn: sqlite3.Connection, now: datetime, start: datetime, end: datetime,
                        ids: list[int] | None = None) -> list[dict]:
    extra, params = _course_filter(ids, "a.course_id")
    rows = conn.execute(
        f"""SELECT a.*, c.name AS course_name, {DONE_SQL} AS done, {QUIZ_SQL} FROM assignments a
            JOIN courses c ON c.id = a.course_id {QUIZ_JOIN}
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
        f"""SELECT a.*, c.name AS course_name, {DONE_SQL} AS done, {QUIZ_SQL} FROM assignments a
            JOIN courses c ON c.id = a.course_id {QUIZ_JOIN}
            WHERE a.active = 1 AND c.active = 1 AND NOT {DONE_SQL}
              AND (a.due_at IS NULL OR a.due_at >= ?){' AND a.due_at < ?' if until else ''}{extra}
            ORDER BY a.due_at IS NULL, a.due_at, c.name""",
        [since, *([until] if until else []), *params],
    ).fetchall()
    tasks = [_assignment(r, now) for r in rows]
    # A paper exam from yesterday is not "pending"; a lab handed in on another platform still is.
    return [t for t in tasks if not (t["delivery"] == SCHEDULED_EVENT and t["vence"] and timefmt.parse(t["vence"]) < now)]


FIND_STOPWORDS = set("""de del la las el los en con para por que una uno un y o mi tu su sus al lo esa ese esta este
tarea tareas deber deberes entrega trabajo actividad sobre the of and""".split())


def find_assignments(conn: sqlite3.Connection, now: datetime, words: str, ids: list[int] | None = None,
                     limit: int = 8) -> list[dict]:
    """Every assignment of the semester whose title or instructions carry the student's words («taller 2», «el de
    vectores»), handed in or past included, best match first. A number must match as a whole word."""
    wanted = [w for w in re.findall(r"\w+", fold(words)) if w not in FIND_STOPWORDS and (len(w) > 2 or w.isdigit())]
    if not wanted:
        return []
    extra, params = _course_filter(ids, "a.course_id")
    rows = conn.execute(
        f"""SELECT a.*, c.name AS course_name, {DONE_SQL} AS done, {QUIZ_SQL} FROM assignments a
            JOIN courses c ON c.id = a.course_id {QUIZ_JOIN} WHERE a.active = 1 AND c.active = 1{extra}""",
        params).fetchall()

    def hits(text: str, word: str) -> bool:
        pattern = rf"\b{word}\b" if word.isdigit() else rf"\b{re.escape(word[:max(4, len(word) - 2)])}"
        return re.search(pattern, text) is not None

    scored = []
    for r in rows:
        title, body = fold(r["name"]), fold(html_to_text(r["description"]))
        in_title = [w for w in wanted if hits(title, w)]
        in_body = [w for w in wanted if w not in in_title and hits(body, w)]
        score = 3 * len(in_title) + len(in_body)
        if score:
            due = timefmt.parse(r["due_at"])
            distance = abs((due - now).total_seconds()) if due else float("inf")
            scored.append((-score, distance, r, "título" if in_title else "consigna"))
    found = []
    for _, _, r, where in sorted(scored, key=lambda item: item[:2])[:limit]:
        material = json.loads(r["material"] or "{}")
        found.append({**_assignment(r, now), "coincide_en": where, "anexos": len(material.get("files") or [])
                      + len(material.get("links") or [])})
    return found


def assignment(conn: sqlite3.Connection, now: datetime, assignment_id: int, ids: list[int] | None = None) -> dict:
    """One assignment with what the professor wrote in it, and the files and outside links that text points to."""
    extra, params = _course_filter(ids, "a.course_id")
    row = conn.execute(
        f"""SELECT a.*, c.name AS course_name, {DONE_SQL} AS done, {QUIZ_SQL} FROM assignments a
            JOIN courses c ON c.id = a.course_id {QUIZ_JOIN} WHERE a.id = ?{extra}""",
        [assignment_id, *params],
    ).fetchone()
    if row is None:
        raise NotFound(f"No conozco la tarea {assignment_id}: usa el «id» que da tareas o semana.")
    material = json.loads(row["material"] or "{}")
    fids, urls = material.get("files") or [], material.get("links") or []
    source = f"Tarea «{row['name']}»"  # how sync recorded it before assignments kept their own list
    files = conn.execute(
        f"""SELECT f.*, c.name AS course_name, c.term_start, c.term FROM files f JOIN courses c ON c.id = f.course_id
            WHERE f.active = 1 AND (f.id IN ({','.join('?' * len(fids)) or 'NULL'}) OR f.source = ? AND f.course_id = ?)""",
        [*fids, source, row["course_id"]]).fetchall()
    links = conn.execute(
        f"""SELECT l.*, c.name AS course_name FROM links l JOIN courses c ON c.id = l.course_id
            WHERE l.active = 1 AND l.course_id = ? AND (l.url IN ({','.join('?' * len(urls)) or 'NULL'}) OR l.source = ?)""",
        [row["course_id"], *urls, source]).fetchall()
    order = {fid: n for n, fid in enumerate(fids)}  # as the professor listed them
    return {**_assignment(row, now), "cierra": row["lock_at"], "tipos_de_entrega": row["submission_types"],
            "consigna": row["description"] or None,
            "rubrica": json.loads(row["rubric"]) if row["rubric"] else None,
            "archivos": [_file(f, set(fids)) for f in sorted(files, key=lambda f: order.get(f["id"], len(order)))],
            "enlaces": [_link(li) for li in links]}


def quiz_openings(conn: sqlite3.Connection, now: datetime, lead: timedelta) -> list[dict]:
    """Unanswered quizzes that open, or opened, within `lead` of now."""
    rows = conn.execute(
        f"""SELECT a.*, c.name AS course_name, {DONE_SQL} AS done, {QUIZ_SQL} FROM assignments a
            JOIN courses c ON c.id = a.course_id {QUIZ_JOIN}
            WHERE a.active = 1 AND c.active = 1 AND NOT {DONE_SQL} AND q.unlock_at > ? AND q.unlock_at <= ?
            ORDER BY q.unlock_at""",
        [timefmt.iso(now - lead), timefmt.iso(now + lead)],
    ).fetchall()
    return [_assignment(r, now) for r in rows]


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


def _file(r: sqlite3.Row, assigned: set[int] = frozenset()) -> dict:
    return {"id": r["id"], "curso": r["course_name"], "curso_id": r["course_id"], "archivo": r["display_name"],
            "extension": Path(r["filename"] or r["display_name"] or "").suffix.lower().lstrip("."),
            "modulo": r["module"], "seccion": r["section"], "carpeta": r["folder"], "origen": r["source"],
            "tamano": r["size"], "subido": r["created_at"], "actualizado": r["updated_at"],
            "descargado": r["local_path"] if r["local_path"] and Path(r["local_path"]).exists() else None,
            "indexado": r["index_status"], "paginas": r["pages"], "idioma": r["language"] or None,
            "copia_de": r["duplicate_of"], "url": r["html_url"],
            "anterior": r["id"] not in assigned and is_old(r["folder"], r["display_name"],
                                                            term_year(r["term_start"], r["course_name"], r["term"]))}


def files(conn: sqlite3.Connection, ids: list[int] | None = None, name: str | None = None) -> list[dict]:
    """The catalog: every document the aula shows (downloaded or not) plus what was added by hand."""
    extra, params = _course_filter(ids, "f.course_id")
    rows = conn.execute(
        f"""SELECT f.*, c.name AS course_name, c.term_start, c.term FROM files f JOIN courses c ON c.id = f.course_id
            WHERE f.active = 1 AND c.active = 1{extra} ORDER BY c.name, f.module, f.display_name""",
        params,
    ).fetchall()
    needle, assigned = (fold(name) if name else None), assigned_files(conn)
    return [_file(r, assigned) for r in rows if not needle or any(
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
    return {**_file(row, assigned_files(conn)), "ocr": ocr_state(conn, row["digest"])}


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
