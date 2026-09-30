"""The tools each bot gets, served over MCP by `espol-bot mcp vinci|materia`.

Vinci (the main bot): read-only queries over the aula data of every course (it opens the outside links
the aula shows without a login, like a subject bot) and over every subject notebook, the schedule (it
can read it and propose one extracted from a screenshot; only the captain's «Guardar» button saves it),
the captain's own to-do list (it adds items; the captain closes them with «✅ Hecho»), the grade calculator
of every subject (grades.py; a scheme is saved only by the captain's «Guardar esquema»), the handoff of an
item to a subject bot, and the team (it shows cards whose «Crear» / «Archivar» buttons, pressed by the
captain, create or archive a subject bot). No Vinci tool writes a notebook, reads arbitrary files, runs
commands, or sees a bot token.

A subject bot: the same queries restricted to its own courses (theory and práctico), the classes of its
subject, its grade calculator, and its own notebook (read and write; attachments only from the files the
captain sent it, which Hermes keeps in the profile's media cache).

Material is a catalog, not a pile of text: `archivos` lists every document and outside link of the
courses (where it is, whether it is read yet) and each document is downloaded only when a bot needs
it (bajar_archivo). An outside link (a Google Doc, a SharePoint share, a professor's page) opens
without the student's login when a bot reads it (leer_archivo with its enlace_id), and an
announcement shows the links it carries, which its text alone loses. Search weighs the subject's
main book (libros.py) first and runs the question in two languages when the material is in English.
A scanned page is seen as an image by `ver_pagina`, a tool of the vinci-botones plugin (an MCP
result cannot carry an image to the model in Hermes). Each page a tool shows comes with its citation
and is recorded, so the answer's citations can be checked before they are sent (citations.py).

The Canvas token stays inside this process: no tool ever returns it.
"""

from __future__ import annotations

import base64
import logging
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from aula_core import Aula, extract, queries, search, timefmt
from aula_core.canvas import CanvasError
from aula_core.catalog import PUBLIC, normalized_name
from aula_core.config import ConfigError
from aula_core.materials import safe_filename
from espol_bot import agenda, citations, grades, horario, libros, materias, messages, store
from espol_bot.config import BotConfig, load_telegram_secrets
from espol_bot.cuaderno import FILE_KINDS, KINDS, NOTE_KINDS, Notebook, NotebookError
from espol_bot.cuaderno import root as notebooks_root
from espol_bot.mcp_server import Tool, ToolError
from espol_bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

MEDIA_DIRS = ("cache", "image_cache", "audio_cache", "document_cache")
MEDIA_EXT = {
    "foto": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"},
    "audio": {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".aac"},
    "documento": {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".doc", ".ppt"},
}
MAX_ATTACHMENT = 50 * 1024 * 1024
MAX_READ_CHARS = 24000
RECENT_MEDIA = timedelta(minutes=30)
CATALOG_LIMIT = 60   # documents listed without a name filter; the rest is one `nombre` away
FILTERED_LIMIT = 100
LINK_LIMIT = 25
HIT_CHARS = 1500
READ_WHAT = "Dime «archivo_id» (un documento de archivos) o «enlace_id» (un enlace de archivos o de un anuncio)."
READ_PROPERTIES = {
    "archivo_id": {"type": "integer"},
    "enlace_id": {"type": "integer", "description": "un enlace de «enlaces» (archivos) o de un anuncio"},
    "paginas": {"type": "string", "description": "rango, ej. 3-5"},
    "reintentar": {"type": "boolean", "description": "con enlace_id: pruébalo otra vez aunque hace poco pidió iniciar "
                                                     "sesión (el estudiante dice que ya lo compartieron)"},
}


@dataclass
class Ctx:
    cfg: BotConfig
    hermes_home: Path | None = None
    code: str | None = None
    _aula: Aula | None = field(default=None, repr=False)

    @property
    def aula(self) -> Aula:
        if self._aula is None:
            self._aula = Aula(self.cfg.core)
            store.ensure(self._aula.conn)
        return self._aula

    @property
    def conn(self):
        return self.aula.conn

    def now(self) -> datetime:
        return self.aula.now()

    @property
    def bot(self) -> str:
        """Whose shown pages a citation may point at (citations.py)."""
        return self.code or citations.VINCI

    def subjects(self) -> list[materias.Subject]:
        try:
            return materias.load(self.cfg.core)
        except ConfigError as exc:
            raise ToolError(str(exc)) from None

    def subject(self) -> materias.Subject:
        subject = materias.by_code(self.subjects(), self.code or "")
        if subject is None:
            raise ToolError(f"La materia {self.code} ya no está en materias.toml.")
        return subject

    def refresh(self) -> None:
        """Re-read the aula virtual when the local copy is stale (GET only); fall back to it on errors, and
        while the poll is reading it (a chat answer does not wait for a paced background sync)."""
        try:
            self.aula.ensure_fresh(wait=False)
        except (CanvasError, ConfigError) as exc:
            if not queries.courses(self.conn):
                raise ToolError(f"No pude leer el aula virtual: {exc}") from None
            log.warning("uso los datos guardados: %s", exc)


# -- shared helpers ------------------------------------------------------------------------


def _int(value, name: str, default: int | None = None, lo: int = 1, hi: int = 365) -> int | None:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"«{name}» debe ser un número.") from None
    return max(lo, min(hi, number))


def _pages(value) -> tuple[int | None, int | None]:
    if value in (None, ""):
        return None, None
    first, _, last = str(value).partition("-")
    try:
        return int(first), int(last or first)
    except ValueError:
        raise ToolError("«paginas» debe ser un rango como 3-5.") from None


def _trim_hits(hits: list[dict]) -> list[dict]:
    for hit in hits:
        hit["texto"] = hit["texto"][:HIT_CHARS]
        for key in ("ruta_local", "puntaje", *(k for k, v in hit.items() if v is None)):
            hit.pop(key, None)
        if hit.get("coincide") == "todas":
            del hit["coincide"]
    return hits


def _kinds(ctx: Ctx) -> set[str]:
    return {*ctx.cfg.core.material_extensions, "html"}


def _search(ctx: Ctx, args: dict, course_ids: list[int] | None, prefer: set[int], *, can_fetch: bool) -> dict:
    """The question, and its translation when given (the material is often in English), merged by relevance."""
    n = _int(args.get("n"), "n", 5, 1, 10)
    questions = [str(args["pregunta"]), *([str(args["traduccion"])] if args.get("traduccion") else [])]
    found: dict[tuple, dict] = {}
    for question in questions:
        for hit in search.search(ctx.conn, question, course_ids=course_ids, limit=n, prefer=prefer):
            key = (normalized_name(hit["archivo"]), hit["pagina"])
            if key not in found or hit["puntaje"] > found[key]["puntaje"]:
                found[key] = hit
    hits = sorted(found.values(), key=lambda h: (h["coincide"] != "todas", -h["puntaje"]))[:n]
    for hit in hits:
        hit["cita"] = citations.cite(hit["archivo"], hit["unidad"], hit["pagina"], url=hit["url"])
        citations.record(ctx.conn, ctx.bot, hit["archivo_id"], [hit["pagina"]], ctx.now())
    result: dict = {"resultados": _trim_hits(hits)}
    ids = course_ids if course_ids is not None else [c["id"] for c in queries.courses(ctx.conn)]
    marks = ",".join("?" * len(ids)) or "NULL"
    english = ctx.conn.execute(f"SELECT COUNT(*) FROM files WHERE active = 1 AND language = 'en' AND course_id IN ({marks})",
                               ids).fetchone()[0]
    unread = sum(1 for f in queries.files(ctx.conn, course_ids)
                 if f["extension"] in _kinds(ctx) and not f["descargado"] and not f["copia_de"])
    notes = []
    if not hits:
        result["en_el_material"] = False
        if not (unread and can_fetch):
            notes.append("Nada del material leído trata esto: empieza tu respuesta con «No está en el material», sin "
                         "cita ni página. Después, si le sirve, explícalo con conocimiento general"
                         + ("" if can_fetch else " (o con la web, dando su enlace)")
                         + " diciendo que no sale del material.")
    if english and not args.get("traduccion"):
        notes.append(f"{english} documento(s) del material están en inglés: repite la búsqueda con «traduccion» "
                     "(la pregunta en inglés) para no perdértelos.")
    if unread and len(hits) < n:
        fetch = ("si uno de archivos parece tener el tema, bájalo con bajar_archivo y busca otra vez."
                 + ("" if hits else " Si ninguno lo trae, empieza tu respuesta con «No está en el material», sin cita.")
                 if can_fetch else "el bot de la materia los baja cuando le hacen falta.")
        notes.append(f"Solo busco en lo ya leído; {unread} documento(s) del catálogo siguen sin bajar: {fetch}")
    if notes:
        result["nota"] = " ".join(notes)
    return result


def _read(ctx: Ctx, file_id: int, pages, *, can_fetch: bool) -> dict:
    first, last = _pages(pages)
    data = queries.read_pages(ctx.conn, file_id, first, last)
    result = {"archivo_id": data["id"], "archivo": data["archivo"], "curso": data["curso"], "unidad": data["unidad"],
              "paginas": data["paginas"], "idioma": data["idioma"], "url": data["url"]}
    total = 0
    kept = []
    for page in data["contenido"]:
        total += len(page["texto"])
        if total > MAX_READ_CHARS and kept:
            result["aviso"] = f"Texto recortado en la {data['unidad']} {kept[-1]['pagina']}; pide un rango más corto."
            break
        kept.append({**page, "cita": citations.cite(data["archivo"], data["unidad"], page["pagina"], url=data["url"])})
    result["contenido"] = kept
    if kept:  # a blank page inside the range was read too
        citations.record(ctx.conn, ctx.bot, data["id"], range(kept[0]["pagina"], kept[-1]["pagina"] + 1), ctx.now())
    if data["indexado"] == "escaneado":
        result["aviso"] = ("Es un escaneo: sus páginas son imágenes y casi no tienen texto. "
                           + ("Mira la página que necesites con ver_pagina(archivo_id, pagina)." if can_fetch else
                              "El bot de la materia puede mirar sus páginas como imagen."))
    elif not data["descargado"]:
        result["aviso"] = ("Todavía no lo bajé del aula: " + ("usa bajar_archivo y vuelve a leerlo." if can_fetch else
                                                               "el bot de la materia lo baja cuando lo necesita."))
    elif not kept:
        result["aviso"] = "El archivo no tiene texto indexado."
    return result


def _catalog_entry(ctx: Ctx, f: dict, main: set[int], copies: Counter, several_courses: bool) -> dict:
    entry = {"id": f["id"], "archivo": f["archivo"]}
    if several_courses:
        entry["curso"] = f["curso"]
    for key in ("modulo", "seccion", "carpeta"):
        if f[key]:
            entry[key] = f[key]
    if f["origen"] and not f["origen"].startswith(("Archivos", "Módulo")):
        entry["origen"] = f["origen"]
    entry["estado"] = queries.file_state(f, ctx.cfg.core.max_file_mb)
    if f["tamano"]:
        entry["mb"] = round(f["tamano"] / 1024 / 1024, 1)
    for key, value in (("paginas", f["paginas"]), ("idioma", f["idioma"]), ("subido", (f["subido"] or "")[:10]),
                       ("libro_principal", f["id"] in main), ("semestre_anterior", f["anterior"]),
                       ("copias", copies.get(f["id"]))):
        if value:
            entry[key] = value
    return entry


def _link_entry(link: dict) -> dict:
    """«se puede abrir» (leer_archivo with its enlace_id tries it without a login), «abierto» (its document is
    archivo_id), «no se abre» (it asked for a login, or is gone) or «solo enlace» (a video, a form); `motivo` says why."""
    if link["acceso"] != PUBLIC:
        access = "solo enlace"
    elif link["motivo"]:
        access = "no se abre"
    else:
        access = "abierto" if link["archivo_id"] is not None else "se puede abrir"
    entry = {"enlace_id": link["enlace_id"], "titulo": link["titulo"], "tipo": link["tipo"], "acceso": access}
    for key in ("motivo", "modulo", "seccion", "origen", "archivo_id"):
        if link[key] is not None and not (key == "origen" and str(link[key]).startswith("Módulo")):
            entry[key] = link[key]
    entry["url"] = link["url"]
    return entry


def _announcements(conn, course_ids: list[int] | None, n: int) -> list[dict]:
    items = queries.announcements(conn, course_ids, limit=n)
    for item in items:
        item["enlaces"] = [_link_entry(link) for link in item["enlaces"]]
        for key in ("archivos", "enlaces"):
            if not item[key]:
                del item[key]
    return items


def _open_link(ctx: Ctx, link_id: int, retry: bool) -> int:
    try:
        return ctx.aula.fetch_link(link_id, retry=retry)
    except CanvasError as exc:
        raise ToolError(str(exc)) from None


def _material(ctx: Ctx, course_ids: list[int] | None, name: str | None, book: dict | None) -> dict:
    """The catalog: every document of the courses (read or not), then their outside links. Only files a
    bot can read count (a Canvas course page also holds images like anuncios.png or silabos.png, which a
    model reads as «the syllabus is uploaded»); copies of the same file are listed once."""
    kinds = _kinds(ctx)
    found = queries.files(ctx.conn, course_ids, name)
    readable = [f for f in found if f["extension"] in kinds]
    main = libros.file_ids(book) if book else set()
    copies = Counter(f["copia_de"] for f in readable if f["copia_de"])
    kept = sorted((f for f in readable if not f["copia_de"]), key=lambda f: (f["id"] not in main, f["anterior"]))
    limit = FILTERED_LIMIT if name else CATALOG_LIMIT
    several = len({f["curso_id"] for f in kept}) > 1
    result: dict = {}
    if book and book["titulo"]:
        result["libro_principal"] = {"titulo": book["titulo"], "archivo_ids": sorted(main)}
    result["material"] = [_catalog_entry(ctx, f, main, copies, several) for f in kept[:limit]]
    notes = []
    if not readable:
        notes.append(f"No hay material del curso que puedas leer ({', '.join(k.upper() for k in sorted(kinds))})"
                     + (" con ese nombre." if name else " en el aula virtual todavía."))
    if len(kept) > limit:
        notes.append(f"Muestro {limit} de {len(kept)} documentos (primero el libro principal y lo de este semestre): "
                     "pide con «nombre» (parte del nombre, módulo, sección o carpeta) para ver otros.")
    if copies:
        notes.append(f"{sum(copies.values())} copia(s) del mismo archivo en otra carpeta o año no se listan "
                     "(«copias» dice cuántas tiene cada uno).")
    others = len(found) - len(readable)
    if others:
        result["otros_archivos"] = others
        notes.append(f"Hay {others} archivo(s) más que no son material que puedas leer (imágenes u otros formatos, casi "
                     "siempre adornos de la página del aula): no hables de ellos como sílabo, módulos, temas o "
                     "contenido del curso.")
    links = queries.links(ctx.conn, course_ids, name)
    if links:
        result["enlaces"] = [_link_entry(link) for link in links[:LINK_LIMIT]]
        if len(links) > LINK_LIMIT:
            notes.append(f"Muestro {LINK_LIMIT} de {len(links)} enlaces; filtra con «nombre».")
    if notes:
        result["nota"] = " ".join(notes)
    return result


def _book_json(ctx: Ctx, subject: materias.Subject, book: dict, *, own_bot: bool) -> dict:
    result = {k: v for k, v in book.items() if k != "pedido" and v not in (None, [], "")}
    result["complementaria"] = book["complementaria"][:6]
    if not book["titulo"]:
        result["nota"] = ("No sé cuál es: el sílabo no lo dice o no está en el aula. Si el estudiante te lo dice, "
                          "guárdalo con libro_principal(titulo=…).")
    elif not libros.readable_files(book):
        result["nota"] = ("No tengo un PDF suyo que pueda leer. " + libros.handover(ctx.cfg.core, subject)
                          + (" Ya se lo pedí una vez; no insistas: dilo solo si pregunta." if book["pedido"] else ""))
    elif own_bot and any(f["estado"] != "leído" for f in book["archivos"]):
        result["nota"] = "Un archivo sin bajar se baja con bajar_archivo; uno escaneado se mira con ver_pagina."
    return result


def _schedule_json(ctx: Ctx, code: str | None = None) -> dict:
    try:
        classes = horario.load(ctx.cfg.core)
    except ConfigError as exc:
        raise ToolError(str(exc)) from None
    if code:
        classes = horario.for_subject(classes, code)
    subjects = ctx.subjects()
    return {"archivo": str(horario.path(ctx.cfg.core)), "clases": horario.to_json(classes),
            "texto": horario.render(classes, subjects, html=False) if classes else
            "Todavía no hay horario guardado. Pídele una captura de su horario de ESPOL (con la columna de horas)."}


def _upcoming(ctx: Ctx, days: int, code: str | None = None) -> list[dict]:
    try:
        classes = horario.load(ctx.cfg.core)
    except ConfigError:
        return []
    names = horario.names(ctx.subjects())
    now = ctx.now()
    return [{"materia": c.materia, "nombre": names.get(c.materia, c.materia),
             "cuando": f"{timefmt.DAYS_LONG[start.weekday()]} {start.day} {timefmt.MONTHS[start.month - 1]}, "
                       f"{c.inicio:%H:%M}–{c.fin:%H:%M}", "aula": c.aula}
            for start, c in horario.occurrences(classes, now, now + timedelta(days=days), ctx.cfg.core.tz, code)]


def _todo_due(ctx: Ctx, value, now: datetime) -> tuple[datetime | None, bool]:
    """(due moment, all day) from «AAAA-MM-DD» or «AAAA-MM-DD HH:MM»; a date alone is due at the end of that day."""
    text = str(value or "").strip()
    if not text:
        return None, False
    try:
        moment = datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        raise ToolError("«due» debe ser AAAA-MM-DD o AAAA-MM-DD HH:MM.") from None
    all_day = len(text) <= 10
    if all_day:
        moment = moment.replace(hour=23, minute=59)
    moment = moment.replace(tzinfo=ctx.cfg.core.tz) if moment.tzinfo is None else moment
    if moment < now:
        raise ToolError(f"Esa fecha ya pasó (hoy es {timefmt.human(now, ctx.cfg.core.tz)}): revisa qué día "
                        "quiso decir.")
    return moment, all_day


def _todo_json(ctx: Ctx, todo: dict, now: datetime) -> dict:
    result = {"id": todo["id"], "text": todo["text"]}
    if todo["subject"]:
        result["subject"] = todo["subject"]
    if todo["due_at"]:
        result["due"] = messages.todo_due(todo, ctx.cfg.core.tz)
        result["overdue"] = timefmt.parse(todo["due_at"]) < now
    return result


def _notebook_json(nb: Notebook, kind: str | None, n: int, open_only: bool = False) -> dict:
    if kind and kind not in KINDS:
        raise ToolError(f"«tipo» debe ser uno de: {', '.join(KINDS)}.")
    return {"materia": nb.code, "resumen": nb.overview(),
            "entradas": nb.entries(kind=kind, limit=n, open_only=open_only)}


NO_SCHEME = ("No sé cómo se evalúa {name} este semestre: no hay un esquema guardado. Búscalo en el sílabo o las "
             "políticas del curso (archivos, leer_archivo) y en los anuncios (este semestre el primer parcial no tiene "
             "examen por El Niño y cada materia lo maneja distinto), y propónselo con propose_grading_scheme. Si no lo "
             "encuentras, díselo así y pregúntale cómo se evalúa: nunca inventes pesos.")
SCHEME_PROPERTIES = {
    "periods": {"type": "array", "description": "las partes de la nota final: «Primer parcial», «Segundo parcial», "
                                                "«Mejoramiento», o una sola («Curso») si el sílabo pesa todo junto",
                "items": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "weight": {"type": "number", "description": "% de la nota final; los períodos suman 100 (el "
                                                                "mejoramiento no lleva)"},
                    "improvement": {"type": "boolean", "description": "true si es el mejoramiento: reemplaza al período "
                                                                      "más bajo si sale mayor"},
                    "replaces": {"type": "array", "items": {"type": "string"},
                                 "description": "mejoramiento: qué períodos puede reemplazar (vacío: cualquiera)"},
                    "start": {"type": "string", "description": "AAAA-MM-DD: desde cuándo cuentan sus tareas del aula"},
                    "end": {"type": "string", "description": "AAAA-MM-DD: hasta cuándo"},
                    "exception": {"type": "string", "description": "en qué cambia este semestre respecto del sílabo y "
                                                                   "por qué (ej. sin examen por El Niño: la lección de la "
                                                                   "semana 7 vale lo del examen)"},
                    "components": {"type": "array", "items": {"type": "object", "properties": {
                        "name": {"type": "string", "description": "«Examen», «Lecciones», «Talleres»…"},
                        "weight": {"type": "number", "description": "% del período; los componentes suman 100"},
                        "match": {"type": "array", "items": {"type": "string"},
                                  "description": "partes del nombre de sus tareas en el aula («lección», «taller»)"},
                        "assignment_ids": {"type": "array", "items": {"type": "integer"},
                                           "description": "IDs de tareas del aula (de notas) que van aquí"},
                        "expected_count": {"type": "integer", "description": "cuántas notas tendrá en total, si el "
                                                                             "documento lo dice («4 lecciones»)"}},
                        "required": ["name", "weight"]}}},
                    "required": ["name", "components"]}},
    "passing_grade": {"type": "number", "description": "nota para aprobar, sobre 100 (por defecto 60)"},
    "sources": {"type": "array", "items": {"type": "string"},
                "description": "de dónde sale cada peso: «Políticas del curso, pág. 2», «anuncio del 29/09», «me lo dijo "
                               "el estudiante»"},
    "open_questions": {"type": "array", "items": {"type": "string"},
                       "description": "lo que no pudiste confirmar, como pregunta (ej. «¿Cómo se reemplaza el examen del "
                                      "primer parcial?»)"},
}
STATUS_PROPERTIES = {
    "what_if": {"type": "array", "description": "supón este % en lo que falta de esas partes («¿y si saco 70 en la "
                                               "lección?»)",
                "items": {"type": "object", "properties": {"period": {"type": "string"}, "component": {"type": "string"},
                                                           "score": {"type": "number", "description": "0 a 100"}},
                          "required": ["period", "component", "score"]}},
    "target": {"type": "number", "description": "la nota final a la que apunta, si no es solo aprobar"},
}
GRADE_PROPERTIES = {
    "period": {"type": "string", "description": "el período del esquema"},
    "component": {"type": "string", "description": "el componente de ese período"},
    "label": {"type": "string", "description": "qué fue: «Lección 2», «Examen»"},
    "score": {"type": "number"},
    "out_of": {"type": "number", "description": "sobre cuánto (10, 20, 100…)"},
    "remove": {"type": "boolean", "description": "true para borrar una nota que anotaste mal"},
}


def _bounded(value, name: str, lo: float, hi: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ToolError(f"«{name}» debe ser un número.") from None
    if not lo <= number <= hi:
        raise ToolError(f"«{name}» debe estar entre {lo:g} y {hi:g}.")
    return number


def _saved_scheme(ctx: Ctx, subject: materias.Subject) -> dict:
    saved = store.grading_scheme(ctx.conn, subject.code)
    if saved is None:
        raise ToolError(NO_SCHEME.format(name=subject.name))
    return saved["scheme"]


def _component(scheme: dict, subject: materias.Subject, period, component) -> tuple[str, str]:
    found = grades.find_component(scheme, str(period or ""), str(component or ""))
    if found is None:
        raise ToolError(f"No hay «{period} · {component}» en el esquema de {subject.name}. Sus partes: "
                        + "; ".join(grades.component_names(scheme)) + ".")
    return found


def _grade_status(ctx: Ctx, subject: materias.Subject, args: dict) -> dict:
    saved = store.grading_scheme(ctx.conn, subject.code)
    if saved is None:
        return {"subject": subject.name, "scheme": None, "message": NO_SCHEME.format(name=subject.name)}
    what_if = {}
    for entry in args.get("what_if") or []:
        if not isinstance(entry, dict):
            raise ToolError("«what_if» es una lista de {period, component, score}.")
        what_if[_component(saved["scheme"], subject, entry.get("period"), entry.get("component"))] = \
            _bounded(entry.get("score"), "score", 0, 100)
    target = _bounded(args["target"], "target", 1, 100) if args.get("target") not in (None, "") else None
    data = grades.status(ctx.conn, subject, ctx.cfg.core.tz, what_if=what_if, target=target)
    result = data["result"]
    message = "Muéstrale «summary» tal cual: son cuentas ya hechas, no las rehagas ni las redondees distinto."
    if result["open_questions"]:
        message += " Hay cosas sin confirmar («open_questions»): pregúntaselas y, con su respuesta, propón el esquema corregido."
    if result["unassigned_grades"]:
        message += " Hay notas del aula que no van en ninguna parte del esquema: pregúntale a cuál van."
    return {"subject": subject.name, "summary": data["summary"], "details": result, "saved_at": data["saved_at"],
            "message": message}


def _propose_scheme(ctx: Ctx, subject: materias.Subject, args: dict, sender: str | None) -> dict:
    """Validates the scheme and shows it to the captain from `sender`'s chat (a subject code; None: Vinci's)."""
    try:
        scheme = grades.validate({k: args[k] for k in ("periods", "passing_grade", "sources", "open_questions")
                                  if args.get(k) is not None})
    except grades.SchemeError as exc:
        raise ToolError("No puedo proponer ese esquema:\n- " + "\n- ".join(exc.errors)
                        + "\nCorrígelo (con lo que dice el documento, o pregúntale) y vuelve a proponer.") from None
    slots, loose = grades.assign(scheme, grades.assignments(ctx.conn, agenda.course_ids_for(ctx.conn, subject)),
                                 ctx.cfg.core.tz)
    lines = grades.scheme_text(scheme, slots)
    if loose:
        lines.append("❓ Notas del aula que no van en ninguna parte: " + ", ".join(a["name"] for a in loose))
    proposal_id = store.new_scheme_proposal(ctx.conn, subject.code, scheme, ctx.now())
    card = messages.grading_card(subject.name, lines, scheme["open_questions"], scheme["sources"])
    try:
        Telegram(load_telegram_secrets(sender), api=ctx.cfg.telegram_api).send(
            card, [(messages.SCHEME_SAVE_BUTTON, f"v1:g:{proposal_id}:ok"), (messages.SCHEME_FIX_BUTTON, f"v1:g:{proposal_id}:no")])
    except (TelegramError, ConfigError) as exc:
        raise ToolError(f"No pude mostrarle el esquema por Telegram: {exc}") from None
    message = (f"Le mostré el esquema en una tarjeta con «{messages.SCHEME_SAVE_BUTTON}» y «{messages.SCHEME_FIX_BUTTON}». Se "
               "guarda solo cuando pulse Guardar; tú no puedes guardarlo. Dile en una línea de dónde lo sacaste.")
    if scheme["open_questions"]:
        message += " Pregúntale ahora lo que no pudiste confirmar («open_questions»), una línea por pregunta."
    return {"proposal": proposal_id, "open_questions": scheme["open_questions"],
            "unassigned_grades": [a["name"] for a in loose], "message": message}


def _record_grade(ctx: Ctx, subject: materias.Subject, args: dict) -> dict:
    scheme = _saved_scheme(ctx, subject)
    period, component = _component(scheme, subject, args["period"], args["component"])
    label = " ".join(str(args["label"]).split())[:80]
    if not label:
        raise ToolError("«label» dice qué fue: «Lección 2», «Examen».")
    now = ctx.now()
    if args.get("remove"):
        if not store.set_manual_grade(ctx.conn, subject.code, period, component, label, None, None, now):
            raise ToolError(f"No tenía anotada «{label}» en {period} · {component}.")
        recorded = {"removed": label}
    else:
        if args.get("score") in (None, "") or args.get("out_of") in (None, ""):
            raise ToolError("Dime «score» y «out_of» (8 sobre 10: score 8, out_of 10).")
        out_of = _bounded(args["out_of"], "out_of", 0.01, 1000)
        score = _bounded(args["score"], "score", 0, out_of)
        store.set_manual_grade(ctx.conn, subject.code, period, component, label, score, out_of, now)
        recorded = {"period": period, "component": component, "label": label, "score": score, "out_of": out_of}
    return {"recorded": recorded, **_grade_status(ctx, subject, {})}


# -- Vinci ---------------------------------------------------------------------------------


def _vinci_course_ids(ctx: Ctx, materia: str | None) -> list[int] | None:
    if not materia:
        return None
    subjects = ctx.subjects()
    ambiguous = None
    if subjects:
        try:
            subject = materias.resolve(subjects, materia)
            course_ids = agenda.course_ids_for(ctx.conn, subject)
            if course_ids:
                return course_ids
        except materias.Ambiguous as exc:
            ambiguous = exc
    try:
        return queries.course_ids(ctx.conn, materia)
    except queries.NotFound as exc:
        raise ToolError(str(ambiguous or exc)) from None


def _vinci_subject(ctx: Ctx, materia: str | None) -> materias.Subject | None:
    try:
        return materias.resolve(ctx.subjects(), materia) if materia else None
    except materias.Ambiguous:
        return None


def _books(ctx: Ctx, subjects: list[materias.Subject]) -> dict[str, dict]:
    return {s.code: libros.main_book(ctx.conn, ctx.cfg.core, s, agenda.course_ids_for(ctx.conn, s)) for s in subjects}


def _media_file(ctx: Ctx, path: str) -> Path:
    """A file the captain sent this bot over Telegram (Hermes keeps it in the profile's media cache)."""
    if ctx.hermes_home is None:
        raise ToolError("Este servidor no conoce la carpeta de Hermes del bot; no puedo tomar adjuntos.")
    try:
        real = Path(path).expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError):
        raise ToolError(f"No encuentro el archivo {path}.") from None
    roots = [(ctx.hermes_home / d).resolve() for d in MEDIA_DIRS if (ctx.hermes_home / d).exists()]
    if not real.is_file() or not any(real.is_relative_to(root) for root in roots):
        raise ToolError("Solo puedo tomar archivos que el estudiante te mandó por Telegram "
                        "(los que Hermes guarda en tu caché), no otros archivos del computador.")
    if real.stat().st_size > MAX_ATTACHMENT:
        raise ToolError("El archivo es demasiado grande (máximo 50 MB).")
    return real


def _document(ctx: Ctx, path: str) -> Path:
    """A document the captain sent: straight to this bot (media cache) or through Vinci (by then in the notebook)."""
    attachments = (notebooks_root(ctx.cfg.core) / (ctx.code or "") / "adjuntos").resolve()
    try:
        real = Path(path).expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError):
        real = None
    if ctx.code and real and real.is_file() and real.is_relative_to(attachments):
        return real
    return _media_file(ctx, path)


def _kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    return next((kind for kind, exts in MEDIA_EXT.items() if ext in exts), "documento")


def _newest_audio(ctx: Ctx) -> Path | None:
    """The latest audio file in the media cache from the last 30 minutes (for voice notes,
    which Hermes turns into text without telling the agent where the audio is)."""
    if ctx.hermes_home is None:
        return None
    cutoff = datetime.now().timestamp() - RECENT_MEDIA.total_seconds()
    found = []
    for d in MEDIA_DIRS:
        base = ctx.hermes_home / d
        if base.is_dir():
            found += [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_EXT["audio"]
                      and p.stat().st_mtime >= cutoff]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def vinci_tools(ctx: Ctx) -> list[Tool]:
    def materias_(args):
        subjects = ctx.subjects()
        if not subjects:
            return {"materias": [], "nota": "Todavía no hay bots de materia. Usa proponer_equipo para armarlo."}
        return {"materias": [{"codigo": s.code, "nombre": s.name, "bot": s.display, "usuario": s.handle(),
                              "estado": s.state} for s in subjects]}

    def semana(args):
        days = _int(args.get("dias"), "dias", 7, 1, 31)
        ctx.refresh()
        now = ctx.now()
        pending = queries.pending(ctx.conn, now, days=days, overdue_days=7)
        notebooks = {}
        for s in ctx.subjects():
            nb = Notebook(ctx.cfg.core, s.code, read_only=True)
            notebooks[s.code] = {"nombre": s.name, "estado": s.state, **nb.overview()}
            nb.close()
        local_midnight = now.astimezone(ctx.cfg.core.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        todos = [_todo_json(ctx, t, now) for t in store.open_todos(ctx.conn, local_midnight + timedelta(days=days))]
        return {"hoy": timefmt.human(now, ctx.cfg.core.tz), "clases": _upcoming(ctx, days),
                "pendientes": pending, "todos": todos, "cuadernos": notebooks}

    def tareas(args):
        ctx.refresh()
        return queries.pending(ctx.conn, ctx.now(), _vinci_course_ids(ctx, args.get("materia")),
                               days=_int(args.get("dias"), "dias"))

    def anuncios(args):
        ctx.refresh()
        return _announcements(ctx.conn, _vinci_course_ids(ctx, args.get("materia")), _int(args.get("n"), "n", 5, 1, 30))

    def notas(args):
        ctx.refresh()
        return queries.grades(ctx.conn, _vinci_course_ids(ctx, args.get("materia")))

    def archivos(args):
        subject = _vinci_subject(ctx, args.get("materia"))
        book = _books(ctx, [subject])[subject.code] if subject else None
        return _material(ctx, _vinci_course_ids(ctx, args.get("materia")), args.get("nombre"), book)

    def buscar(args):
        subject = _vinci_subject(ctx, args.get("materia"))
        books = _books(ctx, [subject] if subject else ctx.subjects())
        prefer = set().union(*(libros.file_ids(b) for b in books.values()))
        return _search(ctx, args, _vinci_course_ids(ctx, args.get("materia")), prefer, can_fetch=False)

    def leer(args):
        if args.get("enlace_id") not in (None, ""):
            fid = _open_link(ctx, _int(args["enlace_id"], "enlace_id", hi=10**12), bool(args.get("reintentar")))
        elif args.get("archivo_id") not in (None, ""):
            fid = _int(args["archivo_id"], "archivo_id", lo=-10**12, hi=10**12)
        else:
            raise ToolError(READ_WHAT)
        try:
            return _read(ctx, fid, args.get("paginas"), can_fetch=False)
        except queries.NotFound as exc:
            raise ToolError(str(exc)) from None

    def libro(args):
        try:
            subject = materias.resolve(ctx.subjects(), str(args["materia"]))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None
        if str(args.get("titulo") or "").strip():
            libros.set_main(ctx.conn, subject.code, ctx.now(), title=str(args["titulo"]))
        return {"materia": subject.name, **_book_json(ctx, subject, _books(ctx, [subject])[subject.code], own_bot=False)}

    def cuaderno(args):
        try:
            subject = materias.resolve(ctx.subjects(), str(args["materia"]))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None
        nb = Notebook(ctx.cfg.core, subject.code, read_only=True)
        try:
            return _notebook_json(nb, args.get("tipo"), _int(args.get("n"), "n", 20, 1, 100))
        finally:
            nb.close()

    def horario_(args):
        return _schedule_json(ctx)

    def proponer_horario(args):
        classes, errors, warnings = horario.validate(args.get("clases"), ctx.subjects())
        if errors:
            raise ToolError("No puedo proponer ese horario:\n- " + "\n- ".join(errors)
                            + "\nCorrige con lo que ves en la captura (o pregúntale) y vuelve a proponer.")
        now = ctx.now()
        proposal_id = store.new_proposal(ctx.conn, horario.to_json(classes), now)
        card = messages.schedule_card(horario.render(classes, ctx.subjects()), len(classes), warnings)
        try:
            Telegram(load_telegram_secrets(), api=ctx.cfg.telegram_api).send(
                card, [("✅ Guardar horario", f"v1:h:{proposal_id}:ok"), ("✏️ Corregir", f"v1:h:{proposal_id}:no")])
        except (TelegramError, ConfigError) as exc:
            raise ToolError(f"No pude mostrarle la propuesta por Telegram: {exc}") from None
        return {"propuesta": proposal_id, "clases": len(classes), "advertencias": warnings,
                "mensaje": "Le mostré el horario extraído en una tarjeta con los botones «Guardar horario» y "
                           "«Corregir». Se guarda solo cuando pulse Guardar; tú no puedes guardarlo. Dile que "
                           "lo revise (sobre todo días y horas) y, si algo está mal, que te diga qué corregir."}

    def add_todo(args):
        text = " ".join(str(args["text"]).split())
        if not text or len(text) > 300:
            raise ToolError("«text» debe tener entre 1 y 300 caracteres.")
        now = ctx.now()
        due, all_day = _todo_due(ctx, args.get("due"), now)
        subject = str(args.get("subject") or "").strip() or None
        if subject:
            try:
                subject = materias.resolve(ctx.subjects(), subject).name
            except materias.Ambiguous:
                pass  # no bot for it (yet): keep the student's own words
        todo = store.add_todo(ctx.conn, text, subject, due, all_day, now)
        try:
            card(messages.todo_card(todo, ctx.cfg.core.tz, ctx.cfg.reminder_hours),
                 [(messages.TODO_DONE_BUTTON, f"v1:t:{todo['id']}:ok")])
        except ToolError:
            store.delete_todo(ctx.conn, todo["id"])
            raise
        return {"todo": _todo_json(ctx, todo, now),
                "message": "Le mostré el pendiente anotado en una tarjeta con el botón «✅ Hecho». Confírmaselo en "
                           "una línea (qué y para cuándo), sin repetir la tarjeta."}

    def one_subject(text) -> materias.Subject:
        try:
            return materias.resolve(ctx.subjects(), str(text))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None

    def grade_status(args):
        ctx.refresh()
        if str(args.get("subject") or "").strip():
            return _grade_status(ctx, one_subject(args["subject"]), args)
        if args.get("what_if") or args.get("target") not in (None, ""):
            raise ToolError("Para suponer notas o apuntar a una nota, dime la materia («subject»).")
        overview = [_grade_status(ctx, s, {}) for s in ctx.subjects()]
        return {"subjects": [{"subject": o["subject"], **({"summary": o["summary"]} if "summary" in o else {"scheme": None})}
                             for o in overview],
                "message": "Muéstrale el «summary» de cada materia tal cual (son cuentas ya hechas). De las que no "
                           "tienen esquema, dile que todavía no sé cómo se evalúan y ofrécele buscarlo."}

    def propose_scheme(args):
        return _propose_scheme(ctx, one_subject(args["subject"]), args, None)

    def record_grade(args):
        return _record_grade(ctx, one_subject(args["subject"]), args)

    def entregar(args):
        try:
            subject = materias.resolve(ctx.subjects(), str(args["materia"]))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None
        if not subject.active:
            raise ToolError(f"{subject.display} está {subject.state}: no puede recibir cosas. "
                            "Díselo al estudiante (si todavía no tiene bot, puede crearlo con proponer_equipo).")
        text = str(args["mensaje"]).strip()
        paths = args.get("adjuntos") or []
        if not isinstance(paths, list) or len(paths) > 10:
            raise ToolError("«adjuntos» debe ser una lista de hasta 10 rutas.")
        files = [_media_file(ctx, str(p)) for p in paths]
        now = ctx.now()
        folder = ctx.cfg.core.data_dir / "entregas" / subject.code
        folder.mkdir(parents=True, exist_ok=True)
        attachments = []
        for source in files:
            dest = folder / f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}-{safe_filename(source.name)}"
            shutil.copy2(source, dest)
            attachments.append({"tipo": _kind_of(source), "archivo": str(dest), "nombre": source.name})
        handoff_id, _ = store.queue_handoff(ctx.conn, subject.code, "vinci", text, now, attachments=attachments)
        extra = f" con {len(attachments)} adjunto(s)" if attachments else ""
        return {"entrega": handoff_id, "bot": subject.display, "usuario": subject.handle(),
                "confirmacion": f"Listo: se lo pasé a {subject.display} ({subject.handle()}){extra}. "
                                "Te responde en su chat en un minuto más o menos."}

    def card(text: str, buttons: list[tuple[str, str]]) -> None:
        try:
            Telegram(load_telegram_secrets(), api=ctx.cfg.telegram_api).send(text, buttons)
        except (TelegramError, ConfigError) as exc:
            raise ToolError(f"No pude mostrarle la tarjeta por Telegram: {exc}") from None

    def proponer_equipo(args):
        from espol_bot import equipo
        ctx.refresh()
        team, notes, gone = equipo.sync_team(ctx.cfg, ctx.conn)
        text, buttons = equipo.team_card(team, notes, gone)
        card(text, buttons)
        return {"materias": [{"codigo": s.code, "bot": s.display, "estado": s.state} for s in team],
                "mensaje": "Le mostré su equipo con un botón «➕ Crear» por cada bot que falta. Un bot se crea solo "
                           "cuando pulse ese botón y lo confirme en Telegram; tú no puedes crearlo. Si pregunta, "
                           "explícale los pasos y dile que tú nunca ves el token: se guarda solo y, si llega en un mensaje, se borra."}

    def confirm_card(args, state: str, kind: str, question: str, label: str) -> dict:
        try:
            subject = materias.resolve(ctx.subjects(), str(args["materia"]))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None
        if subject.state != state:
            raise ToolError(f"{subject.display} está «{subject.state}», no «{state}».")
        card(question.format(bot=f"<b>{messages.e(subject.display)}</b>"),
             [(f"{label} {subject.display}", f"v1:{kind}:0:{subject.code}"), ("Cancelar", f"v1:n:0:{subject.code}")])
        return {"bot": subject.display,
                "mensaje": f"Le mostré el botón «{label}». Solo pasa si lo pulsa; tú no puedes hacerlo por tu cuenta."}

    def archivar(args):
        return confirm_card(args, "activa", "x", "🗄️ ¿Archivo {bot}? Deja de mandar briefs y de responder; su "
                            "memoria y su cuaderno quedan guardados y puedes reactivarlo cuando quieras.", "🗄️ Archivar")

    def reactivar(args):
        return confirm_card(args, "archivada", "r", "♻️ ¿Reactivo {bot}? Vuelve a responder y a mandar sus briefs.",
                            "♻️ Reactivar")

    materia = {"materia": {"type": "string", "description": "materia (nombre o código); vacío = todas"}}
    return [
        Tool("materias", "Los bots de materia del estudiante: nombre, código, @usuario y estado.", materias_),
        Tool("semana", "Vista general: clases de los próximos días (según el horario), entregas pendientes y "
             "atrasadas de todas las materias, su lista de pendientes personales («todos»), y lo que dice cada "
             "cuaderno (dudas abiertas y temas débiles). "
             "Úsala para «¿qué tengo esta semana?», «¿cómo voy en todo?» y planes de estudio.", semana,
             {"dias": {"type": "integer", "description": "cuántos días hacia adelante (por defecto 7)"}}),
        Tool("tareas", "Entregas pendientes del aula virtual, por fecha.", tareas,
             {**materia, "dias": {"type": "integer", "description": "solo las que vencen en N días"}}),
        Tool("anuncios", "Anuncios recientes de los profesores, con los archivos y enlaces que traen (un Google Doc, "
             "un SharePoint): léelos con leer_archivo.", anuncios,
             {**materia, "n": {"type": "integer", "description": "cuántos (por defecto 5)"}}),
        Tool("notas", "Notas publicadas por materia.", notas, dict(materia)),
        Tool("grade_status", "La calculadora de notas: aplica el esquema de evaluación guardado de una materia (sus "
             "pesos de este semestre) a sus notas del aula y a las que te dijo, y dice cómo va y qué promedio necesita "
             "en lo que falta para aprobar. Sin «subject», todas. Las cuentas vienen hechas en «summary».", grade_status,
             {"subject": {"type": "string", "description": "materia (nombre o código); vacío = todas"},
              **STATUS_PROPERTIES}),
        Tool("propose_grading_scheme", "Le muestra en una tarjeta cómo se evalúa una materia este semestre (del sílabo, "
             "las políticas del curso, un anuncio o lo que te dijo), con «✅ Guardar esquema» y «✏️ Corregir». Solo se "
             "guarda si pulsa Guardar. Úsala también para corregirlo: manda el esquema completo otra vez.",
             propose_scheme, {"subject": {"type": "string"}, **SCHEME_PROPERTIES}, ["subject", "periods", "sources"],
             read_only=False),
        Tool("record_grade", "Anota una nota que te dijo y que no está en el aula (una lección en papel), en su parte "
             "del esquema; devuelve cómo va con ella.", record_grade,
             {"subject": {"type": "string"}, **GRADE_PROPERTIES}, ["subject", "period", "component", "label"],
             read_only=False),
        Tool("archivos", "Catálogo del material de las materias: cada documento (PDF, PPTX, DOCX, páginas) con su "
             "ID, módulo, sección, carpeta, de dónde salió y su estado (leído, sin bajar, escaneado…), y los enlaces "
             "de fuera (Google Docs, Drive, SharePoint, Dropbox, videos) con su «enlace_id». Con «materia», también su "
             "libro principal.", archivos,
             {**materia, "nombre": {"type": "string", "description": "parte del nombre, módulo, sección o carpeta"}}),
        Tool("buscar_material", "Busca en el texto del material ya leído; devuelve archivo, página, fragmento y la "
             "«cita» lista para copiar, con el libro principal primero. Mucho material está en inglés: pasa también "
             "«traduccion».",
             buscar, {"pregunta": {"type": "string"},
                      "traduccion": {"type": "string", "description": "la misma pregunta en inglés"},
                      **materia, "n": {"type": "integer"}}, ["pregunta"]),
        Tool("leer_archivo", "Lee el texto de un archivo del material por páginas, cada una con su «cita»; con "
             "«enlace_id», el de un enlace de fuera (un Google Doc, un Drive, un SharePoint): lo abre sin la cuenta del "
             "estudiante y lo lee como un PDF del aula, o dice por qué no se abre.", leer, READ_PROPERTIES),
        Tool("libro_principal", "El libro principal de una materia (la bibliografía BÁSICA del sílabo): cuál es y "
             "si hay PDF. Si el estudiante te dice cuál es («el libro de Estadística es Zurita»), pásalo en «titulo» "
             "y queda guardado para su bot.", libro,
             {"materia": {"type": "string"}, "titulo": {"type": "string", "description": "lo que dijo el estudiante"}},
             ["materia"], read_only=False),
        Tool("cuaderno", "Lee (solo lectura) el cuaderno de un bot de materia: clases, apuntes, dudas, temas "
             "débiles y adjuntos.", cuaderno,
             {"materia": {"type": "string"}, "tipo": {"type": "string", "enum": list(KINDS)},
              "n": {"type": "integer", "description": "cuántas entradas (por defecto 20)"}}, ["materia"]),
        Tool("horario", "El horario de clases guardado.", horario_),
        Tool("proponer_horario", "Muestra al estudiante, en una tarjeta con botones, el horario que extrajiste de "
             "su captura. Solo se guarda si el estudiante pulsa «Guardar horario». Una entrada por bloque de clase.",
             proponer_horario,
             {"clases": {"type": "array", "items": {
                 "type": "object",
                 "properties": {"materia": {"type": "string", "description": "código, ej. CCPG1055"},
                                "dia": {"type": "string", "description": "lunes … sábado"},
                                "inicio": {"type": "string", "description": "HH:MM (24 h)"},
                                "fin": {"type": "string", "description": "HH:MM (24 h)"},
                                "aula": {"type": "string"}, "paralelo": {"type": "string"}},
                 "required": ["materia", "dia", "inicio", "fin"]}}},
             ["clases"], read_only=False),
        Tool("add_todo", "Anota un pendiente personal en su lista («anota: …», «recuérdame …»): lecturas, trámites, "
             "lo que el profe dijo en clase y no subió. Le muestra una tarjeta con el botón «✅ Hecho»; se lo "
             "recuerdo 24 h y 3 h antes y sale en el resumen de las 7:00 y en semana hasta que lo marque.", add_todo,
             {"text": {"type": "string", "description": "qué hacer, corto y en sus palabras (sin la fecha)"},
              "subject": {"type": "string", "description": "la materia, si la dijo"},
              "due": {"type": "string", "description": "para cuándo, si lo dijo: AAAA-MM-DD, o AAAA-MM-DD HH:MM si "
                                                       "dijo la hora (calcula «el viernes» desde hoy)"}},
             ["text"], read_only=False),
        Tool("entregar_a_materia", "Pasa algo (texto, y fotos/PDF/audios que el estudiante te mandó) al bot de "
             "una materia, que le responde en su propio chat. Úsala solo si sabes con certeza de qué materia es; "
             "si no, pregúntale.", entregar,
             {"materia": {"type": "string", "description": "nombre o código de la materia"},
              "mensaje": {"type": "string", "description": "qué le pasas: sus palabras y qué contienen los adjuntos"},
              "adjuntos": {"type": "array", "items": {"type": "string"},
                           "description": "rutas de los archivos que te mandó por Telegram"}},
             ["materia", "mensaje"], read_only=False),
        Tool("proponer_equipo", "Arma o revisa su equipo de bots de materia: lee las materias del aula virtual y le "
             "muestra una tarjeta con un botón «➕ Crear» por cada bot que falta. El bot se crea cuando lo pulsa y lo "
             "confirma en Telegram; el token nunca llega a ti.", proponer_equipo, read_only=False),
        Tool("archivar_materia", "Fin de semestre: le muestra un botón para archivar el bot de una materia (deja de "
             "responder y de mandar briefs; conserva memoria y cuaderno). Solo se archiva si lo pulsa.", archivar,
             {"materia": {"type": "string"}}, ["materia"], read_only=False),
        Tool("reactivar_materia", "Le muestra un botón para reactivar el bot archivado de una materia.", reactivar,
             {"materia": {"type": "string"}}, ["materia"], read_only=False),
    ]


# -- subject bot -----------------------------------------------------------------------------


def subject_tools(ctx: Ctx) -> list[Tool]:
    def course_ids() -> list[int]:
        ids = agenda.course_ids_for(ctx.conn, ctx.subject())
        if not ids:
            raise ToolError(f"No encuentro {ctx.code} entre las materias del aula virtual.")
        return ids

    def own_file(file_id) -> int:
        fid = _int(file_id, "archivo_id", lo=-10**12, hi=10**12)  # below zero: material added by hand
        try:
            info = queries.file_by_id(ctx.conn, fid)
        except queries.NotFound as exc:
            raise ToolError(str(exc)) from None
        if info["curso_id"] not in course_ids():
            raise ToolError("Ese archivo es de otra materia; solo puedes usar el material de la tuya.")
        return fid

    def own_link(link_id) -> int:
        lid = _int(link_id, "enlace_id", hi=10**12)
        row = ctx.conn.execute("SELECT course_id FROM links WHERE id = ?", (lid,)).fetchone()
        if row is None:
            raise ToolError(f"No conozco el enlace {lid}; mira «enlaces» en archivos.")
        if row["course_id"] not in course_ids():
            raise ToolError("Ese enlace es de otra materia; solo puedes usar el material de la tuya.")
        return lid

    def book() -> dict:
        return libros.main_book(ctx.conn, ctx.cfg.core, ctx.subject(), course_ids())

    def file_result(fid: int) -> dict:
        info = queries.file_by_id(ctx.conn, fid)
        result = {"archivo_id": fid, "archivo": info["archivo"], "estado": queries.file_state(info, ctx.cfg.core.max_file_mb),
                  "paginas": info["paginas"], "idioma": info["idioma"], "url": info["url"]}
        if info["indexado"] == "escaneado":
            result["aviso"] = ("Es un escaneo: sus páginas son imágenes. Mira la que necesites con "
                               "ver_pagina(archivo_id, pagina).")
        return {k: v for k, v in result.items() if v is not None}

    def resumen(args):
        ctx.refresh()
        s, cids, now = ctx.subject(), course_ids(), ctx.now()
        nb = Notebook(ctx.cfg.core, s.code)
        try:
            notebook = {"resumen": nb.overview(), "ultimas": nb.entries(limit=5)}
        finally:
            nb.close()
        main = book()
        return {"materia": s.name, "codigo": s.code, "bot": s.display, "proximas_clases": _upcoming(ctx, 7, s.code),
                "pendientes": queries.pending(ctx.conn, now, cids, days=14),
                "anuncios": _announcements(ctx.conn, cids, 3), "cuaderno": notebook,
                "libro_principal": {"titulo": main["titulo"], "archivos": [
                    {k: f[k] for k in ("archivo_id", "archivo", "estado")} for f in main["archivos"]]}}

    def tareas(args):
        ctx.refresh()
        return queries.pending(ctx.conn, ctx.now(), course_ids(), days=_int(args.get("dias"), "dias"))

    def anuncios(args):
        ctx.refresh()
        return _announcements(ctx.conn, course_ids(), _int(args.get("n"), "n", 5, 1, 30))

    def notas(args):
        ctx.refresh()
        return queries.grades(ctx.conn, course_ids())

    def archivos(args):
        return _material(ctx, course_ids(), args.get("nombre"), book())

    def buscar(args):
        return _search(ctx, args, course_ids(), libros.file_ids(book()), can_fetch=True)

    def leer(args):
        if args.get("enlace_id") not in (None, ""):
            fid = _open_link(ctx, own_link(args["enlace_id"]), bool(args.get("reintentar")))
        elif args.get("archivo_id") not in (None, ""):
            fid = own_file(args["archivo_id"])
        else:
            raise ToolError(READ_WHAT)
        return _read(ctx, fid, args.get("paginas"), can_fetch=True)

    def bajar(args):
        if args.get("enlace_id") not in (None, ""):
            return file_result(_open_link(ctx, own_link(args["enlace_id"]), bool(args.get("reintentar"))))
        if args.get("archivo_id") in (None, ""):
            raise ToolError("Dime «archivo_id» (un documento de archivos) o «enlace_id» (uno de sus enlaces).")
        fid = own_file(args["archivo_id"])
        try:
            ctx.aula.download(fid)
        except CanvasError as exc:
            url = queries.file_by_id(ctx.conn, fid)["url"]
            raise ToolError(f"No pude bajar el archivo: {exc}." + (f" Puede abrirlo en el aula: {url}" if url else "")) \
                from None
        return file_result(fid)

    def libro(args):
        s = ctx.subject()
        title = str(args.get("titulo") or "").strip()
        if title or args.get("archivo_id") not in (None, ""):
            fid = own_file(args["archivo_id"]) if args.get("archivo_id") not in (None, "") else None
            libros.set_main(ctx.conn, s.code, ctx.now(), title=title or None, file_id=fid)
        return _book_json(ctx, s, book(), own_bot=True)

    def agregar(args):
        source = _document(ctx, str(args["ruta"]))
        if source.suffix.lower() not in libros.BOOK_TYPES:
            raise ToolError("Solo agrego al material documentos PDF, DOCX o PPTX; una foto o un audio va al cuaderno "
                            "con guardar_adjunto.")
        fid = libros.add_sent(ctx.conn, ctx.cfg.core, ctx.subject(), course_ids(), source, ctx.now(),
                              main=bool(args.get("libro_principal")))
        return {**file_result(fid), "libro_principal": bool(args.get("libro_principal"))}

    def horario_(args):
        return _schedule_json(ctx, ctx.code)

    def grade_status(args):
        ctx.refresh()
        return _grade_status(ctx, ctx.subject(), args)

    def propose_scheme(args):
        return _propose_scheme(ctx, ctx.subject(), args, ctx.subject().code)

    def record_grade(args):
        return _record_grade(ctx, ctx.subject(), args)

    def notebook() -> Notebook:
        return Notebook(ctx.cfg.core, ctx.subject().code)

    def cuaderno(args):
        nb = notebook()
        try:
            return _notebook_json(nb, args.get("tipo"), _int(args.get("n"), "n", 20, 1, 100), bool(args.get("abiertas")))
        finally:
            nb.close()

    def anotar(args):
        kind = str(args["tipo"])
        if kind not in NOTE_KINDS:
            raise ToolError(f"«tipo» debe ser uno de: {', '.join(NOTE_KINDS)} (para archivos usa guardar_adjunto).")
        nb = notebook()
        try:
            return nb.add(kind, str(args["texto"]), ctx.now(), class_date=args.get("fecha_clase") or None)
        except NotebookError as exc:
            raise ToolError(str(exc)) from None
        finally:
            nb.close()

    def resolver(args):
        nb = notebook()
        try:
            return nb.resolve(_int(args["entrada_id"], "entrada_id", hi=10**9), ctx.now())
        except NotebookError as exc:
            raise ToolError(str(exc)) from None
        finally:
            nb.close()

    def guardar_adjunto(args):
        kind = str(args["tipo"])
        if kind not in FILE_KINDS:
            raise ToolError(f"«tipo» debe ser uno de: {', '.join(FILE_KINDS)}.")
        if args.get("ruta"):
            source = _media_file(ctx, str(args["ruta"]))
        elif kind == "audio":
            source = _newest_audio(ctx)
        else:
            raise ToolError("Dime la ruta del archivo (aparece como «Image attached at: …» o «saved at: …»).")
        nb = notebook()
        try:
            entry = nb.add(kind, str(args["resumen"]), ctx.now(), class_date=args.get("fecha_clase") or None,
                           transcript=args.get("transcripcion"), source_file=source)
        except NotebookError as exc:
            raise ToolError(str(exc)) from None
        finally:
            nb.close()
        if source is None:
            entry["aviso"] = "No encontré el audio en tu caché; guardé solo la transcripción y el resumen."
        return entry

    return [
        Tool("resumen", "Tu materia de un vistazo: próximas clases, pendientes, anuncios y tu cuaderno.", resumen),
        Tool("tareas", "Entregas pendientes de tu materia.", tareas,
             {"dias": {"type": "integer", "description": "solo las que vencen en N días"}}),
        Tool("anuncios", "Anuncios recientes de tu materia, con los archivos y enlaces que traen (un Google Doc, un "
             "SharePoint): léelos con leer_archivo.", anuncios, {"n": {"type": "integer"}}),
        Tool("notas", "Notas publicadas de tu materia.", notas),
        Tool("grade_status", "La calculadora de notas de tu materia: aplica su esquema de evaluación guardado (los "
             "pesos de este semestre) a sus notas del aula y a las que te dijo, y dice cómo va y qué promedio necesita "
             "en lo que falta para aprobar. Las cuentas vienen hechas en «summary».", grade_status, STATUS_PROPERTIES),
        Tool("propose_grading_scheme", "Le muestra en una tarjeta cómo se evalúa tu materia este semestre (del sílabo, "
             "las políticas del curso, un anuncio o lo que te dijo), con «✅ Guardar esquema» y «✏️ Corregir». Solo se "
             "guarda si pulsa Guardar. Úsala también para corregirlo: manda el esquema completo otra vez.",
             propose_scheme, SCHEME_PROPERTIES, ["periods", "sources"], read_only=False),
        Tool("record_grade", "Anota una nota que te dijo y que no está en el aula (una lección en papel), en su parte "
             "del esquema; devuelve cómo va con ella.", record_grade, GRADE_PROPERTIES,
             ["period", "component", "label"], read_only=False),
        Tool("archivos", "Catálogo del material de tu materia: cada documento (PDF, PPTX, DOCX, páginas) con su ID, "
             "módulo, sección, carpeta, de dónde salió y su estado (leído, sin bajar, escaneado, muy grande…), tu "
             "libro principal primero; y los enlaces de fuera (Google Docs, Drive, SharePoint, Dropbox, videos) con su "
             "«enlace_id».",
             archivos, {"nombre": {"type": "string", "description": "parte del nombre, módulo, sección o carpeta"}}),
        Tool("buscar_material", "Busca en el texto del material ya leído de tu materia (archivo, página, fragmento y "
             "la «cita» lista para copiar), con tu libro principal primero. Mucho material está en inglés: pasa "
             "también «traduccion».",
             buscar, {"pregunta": {"type": "string"},
                      "traduccion": {"type": "string", "description": "la misma pregunta en inglés"},
                      "n": {"type": "integer"}}, ["pregunta"]),
        Tool("leer_archivo", "Lee un archivo del material de tu materia, por páginas, cada una con su «cita»; con "
             "«enlace_id», el de un enlace de fuera (un Google Doc, un Drive, un SharePoint): lo abre sin la cuenta "
             "del estudiante y lo lee como un PDF del aula, o dice por qué no se abre.", leer, READ_PROPERTIES),
        Tool("bajar_archivo", "Baja e indexa un documento de tu materia que está «sin bajar» (solo lectura del aula), "
             "o abre un enlace de fuera sin la cuenta del estudiante (un Google Doc, un Dropbox, una página pública). "
             "Baja solo lo que necesitas ahora.", bajar,
             {"archivo_id": {"type": "integer"}, "enlace_id": {"type": "integer"},
              "reintentar": READ_PROPERTIES["reintentar"]}, read_only=False),
        Tool("libro_principal", "Tu libro principal (la bibliografía BÁSICA del sílabo): cuál es, sus archivos y "
             "cómo pasarte el PDF. Si el estudiante te dice cuál es, guárdalo con «titulo»; si un archivo del "
             "catálogo es ese libro, con «archivo_id».", libro,
             {"titulo": {"type": "string"}, "archivo_id": {"type": "integer"}}, read_only=False),
        Tool("agregar_material", "Agrega al material de tu materia un PDF, DOCX o PPTX que el estudiante te mandó por "
             "Telegram o por Vinci (queda leído y se puede buscar); con «libro_principal» es el PDF de tu libro "
             "principal.", agregar,
             {"ruta": {"type": "string", "description": "ruta del documento que te llegó («saved at: …», o la del "
                                                         "adjunto en tu cuaderno)"},
                       "libro_principal": {"type": "boolean"}}, ["ruta"], read_only=False),
        Tool("horario", "Las clases de tu materia según el horario.", horario_),
        Tool("cuaderno", "Lee tu cuaderno: lo visto en cada clase, apuntes, dudas, temas débiles y adjuntos.",
             cuaderno, {"tipo": {"type": "string", "enum": list(KINDS)}, "n": {"type": "integer"},
                        "abiertas": {"type": "boolean", "description": "solo dudas/temas sin resolver"}}),
        Tool("anotar", "Escribe en tu cuaderno: «clase» (lo que se vio en una clase), «apunte», «duda» o "
             "«tema_debil» (algo que le cuesta).", anotar,
             {"tipo": {"type": "string", "enum": list(NOTE_KINDS)}, "texto": {"type": "string"},
              "fecha_clase": {"type": "string", "description": "AAAA-MM-DD de la clase, si aplica"}},
             ["tipo", "texto"], read_only=False),
        Tool("resolver", "Marca como resuelta una duda o un tema débil de tu cuaderno.", resolver,
             {"entrada_id": {"type": "integer"}}, ["entrada_id"], read_only=False),
        Tool("guardar_adjunto", "Guarda en tu cuaderno una foto (ej. de la pizarra), una nota de voz o un documento "
             "que el estudiante te mandó, con tu resumen (y la transcripción, si es audio).", guardar_adjunto,
             {"tipo": {"type": "string", "enum": list(FILE_KINDS)},
              "resumen": {"type": "string", "description": "qué contiene, en 1-5 líneas"},
              "ruta": {"type": "string", "description": "ruta del archivo que te llegó (para audio puede ir vacía)"},
              "transcripcion": {"type": "string", "description": "texto de la nota de voz, si lo tienes"},
              "fecha_clase": {"type": "string", "description": "AAAA-MM-DD de la clase, si aplica"}},
             ["tipo", "resumen"], read_only=False),
    ]


def page_image(cfg: BotConfig, code: str, file_id: int, page: int) -> dict:
    """A page of a downloaded PDF of the subject `code`, as a JPEG: what the plugin's ver_pagina shows the model."""
    ctx = Ctx(cfg, code=code.upper())
    try:
        info = queries.file_by_id(ctx.conn, file_id)
        if info["curso_id"] not in agenda.course_ids_for(ctx.conn, ctx.subject()):
            raise ToolError("Ese archivo es de otra materia; solo puedes usar el material de la tuya.")
        if info["extension"] != "pdf":
            raise ToolError("Solo puedo mostrarte páginas de un PDF; lee este con leer_archivo.")
        if not info["descargado"]:
            raise ToolError("Todavía no lo bajé del aula: usa bajar_archivo primero.")
        try:
            jpeg = extract.render_page(Path(info["descargado"]), page)
        except ValueError as exc:
            raise ToolError(str(exc)) from None
        citations.record(ctx.conn, ctx.bot, file_id, [page], ctx.now())
        return {"archivo_id": file_id, "archivo": info["archivo"], "pagina": page, "paginas": info["paginas"],
                "cita": citations.cite(info["archivo"], "página", page, url=info["url"]),
                "tipo": "image/jpeg", "imagen": base64.b64encode(jpeg).decode()}
    except queries.NotFound as exc:
        raise ToolError(str(exc)) from None
    finally:
        ctx.aula.close()


def check_citations(cfg: BotConfig, code: str | None, text: str) -> dict:
    """An answer of Vinci (no `code`) or of a subject bot with its citations checked (citations.py): what the
    plugin sends instead, when something changed."""
    ctx = Ctx(cfg, code=code.upper() if code else None)
    try:
        course_ids = agenda.course_ids_for(ctx.conn, ctx.subject()) if code else None
        checked, changes = citations.check(ctx.conn, ctx.bot, course_ids, text)
    finally:
        ctx.aula.close()
    for change in changes:
        log.info("citas %s: %s «%s»", ctx.bot, change["cambio"], change["cita"])
    return {"respuesta": checked, "cambios": changes} if changes else {}
