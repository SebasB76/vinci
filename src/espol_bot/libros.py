"""Each subject's main book (the syllabus' BÁSICA / Lectura obligatoria / Texto guía): which one it
is, where its PDF is, and asking the captain for that PDF once.

- Which one: what the captain told a bot («el libro principal es Zurita»), else the main entry of the
  newest syllabus of the subject's courses. Unknown while neither exists.
- Its PDF: the files given for it (sent to the bot, or put in `libros/<CÓDIGO>/` of the data folder,
  for a book over the 20 MB a Telegram bot can receive), else the catalog documents whose name
  matches it (another edition counts). A document that matches a complementary book better is not
  the main one, and once a match names an author the ones that name none drop out.
- The ask: when the main book is known and no PDF of it can be read (none, or only one too big to
  download), the subject bot asks once, with a fixed message (no model) that says how to hand it
  over; never again for that subject. When the aula only links it, the poll first opens that link
  without a login: a public one is the book, and only one that does not open is asked for.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from aula_core import materials, queries, syllabus, timefmt
from aula_core.catalog import fold
from aula_core.config import CoreConfig
from espol_bot import materias, messages

log = logging.getLogger(__name__)

TELEGRAM_BOT_LIMIT_MB = 20  # the most a bot can download of a file sent to it (Bot API getFile)
FOLDER_SOURCE = "Carpeta libros"
SENT_SOURCE = "Lo mandó el estudiante"
BOOK_TYPES = (".pdf", ".docx", ".pptx")
UNUSABLE = ("muy grande para bajar", "no se pudo bajar")
# What the copies of a sent file carry before its own name: Hermes' media cache, a handoff through Vinci.
COPY_PREFIX = re.compile(r"^(?:doc_[0-9a-f]{8,}_|\d{8}-\d{6}-[0-9a-f]{6}-)")
NOISE = set("""edicion edition primera segunda tercera cuarta quinta sexta septima octava novena decima first second
third fourth fifth sixth seventh eighth ninth tenth volumen tomo isbn pearson mcgraw hill cengage wiley prentice
editorial learning press education hardcover para como with from sobre fundamentals introduccion introduction""".split())


def folder(cfg: CoreConfig, code: str) -> Path:
    return cfg.data_dir / "libros" / code.upper()


# -- matching a reference («Sommerville, I. (2016). Software Engineering (10th ed.)») to a file name --------


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{4,}", fold(text)) if w not in NOISE]


def _parts(reference: str) -> tuple[list[str], list[str]]:
    """(author words, title words) of a bibliography entry."""
    year = re.search(r"\((?:19|20)\d{2}[a-z]?\)\.?\s*", reference)
    cut = year or re.search(r"(?<=[^\W\d_]{3})\.\s+", reference)
    if not cut:
        return [], _words(reference)
    title = re.split(r"\(|\.\s|:", reference[cut.end():])[0]
    return _words(reference[:cut.start()]), _words(title)


def _hits(reference: str, haystack: str) -> tuple[int, int, int, int]:
    """(author hits, title hits, author words, title words) of a reference in a squashed file name."""
    authors, title = _parts(reference)
    return sum(a in haystack for a in authors), sum(t in haystack for t in title), len(authors), len(title)


def _matches(hits: tuple[int, int, int, int]) -> bool:
    author, title, authors, words = hits
    if words >= 2 and title >= max(2, math.ceil(0.6 * words)):
        return True
    if not authors and words and title == words:  # a bare name, as the captain says it: «Zurita»
        return True
    return author >= 1 and (title >= 1 or not words)


def matching(reference: str, others: list[str], rows: list[dict]) -> list[dict]:
    """The catalog rows that are copies (or chapters) of the book `reference`."""
    found = []
    for row in rows:
        haystack = re.sub(r"[^a-z0-9]", "", fold(f"{row['archivo']} {row.get('carpeta') or ''} {row.get('titulo') or ''}"))
        hits = _hits(reference, haystack)
        if not _matches(hits):
            continue
        if any(sum(_hits(o, haystack)[:2]) > sum(hits[:2]) for o in others):
            continue
        found.append((hits, row))
    if any(hits[0] for hits, _ in found):
        found = [(hits, row) for hits, row in found if hits[0]]
    return [row for _, row in found]


# -- what is stored ---------------------------------------------------------------------------------


def _stored(conn: sqlite3.Connection, code: str) -> dict:
    row = conn.execute("SELECT * FROM libros WHERE materia = ?", (code,)).fetchone()
    return {"titulo": row["titulo"], "archivos": json.loads(row["archivos"]), "pedido": row["pedido"]} if row else \
        {"titulo": None, "archivos": [], "pedido": None}


def _save(conn: sqlite3.Connection, code: str, now: datetime, **changes) -> None:
    data = _stored(conn, code) | changes
    conn.execute("INSERT OR REPLACE INTO libros(materia, titulo, archivos, pedido, actualizado) VALUES (?, ?, ?, ?, ?)",
                 (code, data["titulo"], json.dumps(data["archivos"]), data["pedido"], timefmt.iso(now)))
    conn.commit()


def set_main(conn: sqlite3.Connection, code: str, now: datetime, *, title: str | None = None,
             file_id: int | None = None) -> None:
    """What the captain said: the main book's title and/or the catalog file that is its PDF. Another
    title drops the files given for the one before."""
    stored = _stored(conn, code)
    title = (title or "").strip() or None
    files = [] if title and title != stored["titulo"] else stored["archivos"]
    files = files + ([file_id] if file_id is not None and file_id not in files else [])
    _save(conn, code, now, titulo=title or stored["titulo"], archivos=files)


def mark_asked(conn: sqlite3.Connection, code: str, now: datetime) -> None:
    if not _stored(conn, code)["pedido"]:
        _save(conn, code, now, pedido=timefmt.iso(now))


# -- the book of a subject ----------------------------------------------------------------------------


def main_book(conn: sqlite3.Connection, cfg: CoreConfig, subject: materias.Subject, course_ids: list[int]) -> dict:
    stored = _stored(conn, subject.code)
    books = queries.bibliography(conn, course_ids) if course_ids else None
    title = stored["titulo"] or (books["principal"][0] if books else None)
    catalog = queries.files(conn, course_ids) if course_ids else []
    given = [f for f in catalog if f["id"] in stored["archivos"] or f["origen"] == FOLDER_SOURCE]
    found = given
    if not found and title:
        documents = [f for f in catalog if f["extension"] in ("pdf", "docx", "pptx") and not f["copia_de"]
                     and not syllabus.is_syllabus(f["archivo"])]
        found = matching(title, (books or {}).get("complementaria", []) if not stored["titulo"] else [], documents)
    links = []
    if title and not found:
        links = [{k: link[k] for k in ("enlace_id", "titulo", "tipo", "motivo", "url")}
                 for link in matching(title, [], [{**link, "archivo": link["titulo"] or ""}
                                                  for link in queries.links(conn, course_ids)])]
    return {
        "titulo": title,
        "origen": "te lo dijo el estudiante" if stored["titulo"] else f"sílabo «{books['silabo']}»" if books else None,
        "silabo": {"archivo": books["silabo"], "archivo_id": books["silabo_id"], "url": books["url"]} if books else None,
        "complementaria": (books or {}).get("complementaria", []),
        "archivos": [{"archivo_id": f["id"], "archivo": f["archivo"], "estado": queries.file_state(f, cfg.max_file_mb), "idioma": f["idioma"],
                      "url": f["url"]} for f in found],
        "enlaces": links,
        "pedido": stored["pedido"],
    }


def file_ids(book: dict) -> set[int]:
    return {f["archivo_id"] for f in book["archivos"]}


def handover(cfg: CoreConfig, subject: materias.Subject) -> str:
    """How the captain gives the bot a PDF, plain text for a tool result."""
    return (f"Si lo tienes en PDF: hasta {TELEGRAM_BOT_LIMIT_MB} MB, mándalo por el chat de {subject.display}; si pesa "
            f"más (Telegram no deja que un bot reciba archivos más grandes), ponlo en la carpeta "
            f"{folder(cfg, subject.code)} de tu computadora: lo tomo en la próxima revisión del aula (cada 30 min) o "
            "en cuanto me digas que ya está.")


# -- books the captain hands over ---------------------------------------------------------------------


def scan_folder(conn: sqlite3.Connection, cfg: CoreConfig, subject: materias.Subject, course_ids: list[int]) -> list[int]:
    """Indexes the new or changed documents in `libros/<CÓDIGO>/` (kept where they are); returns their ids."""
    base = folder(cfg, subject.code)
    base.mkdir(parents=True, exist_ok=True)
    known = {r["local_path"]: r for r in conn.execute("SELECT * FROM files WHERE source = ? AND local_path LIKE ?",
                                                      (FOLDER_SOURCE, f"{base}/%"))}
    added = []
    present = set()
    for path in sorted(p for p in base.iterdir() if p.is_file() and p.suffix.lower() in BOOK_TYPES):
        present.add(str(path))
        stat = path.stat()
        row = known.get(str(path))
        if row and row["downloaded_version"] == f"{stat.st_size}:{int(stat.st_mtime)}" and row["active"]:
            continue
        if not course_ids:
            continue
        log.info("libro de %s en la carpeta: %s", subject.code, path.name)
        added.append(materials.add_local(conn, cfg, course_ids[0], path, name=path.name, source=FOLDER_SOURCE,
                                         in_place=True, file_id=row["id"] if row else None))
    gone = [r["id"] for path, r in known.items() if path not in present and r["active"]]
    if gone:
        conn.executemany("UPDATE files SET active = 0 WHERE id = ?", [(i,) for i in gone])
        conn.commit()
    return added


def add_sent(conn: sqlite3.Connection, cfg: CoreConfig, subject: materias.Subject, course_ids: list[int], path: Path,
             now: datetime, *, main: bool) -> int:
    """A document the captain sent a bot, as course material (and as the main book's PDF when `main`)."""
    if not course_ids:
        raise ValueError(f"No encuentro los cursos de {subject.name} en el aula virtual.")
    file_id = materials.add_local(conn, cfg, course_ids[0], path, name=COPY_PREFIX.sub("", path.name) or path.name,
                                  source=SENT_SOURCE)
    if main:
        set_main(conn, subject.code, now, file_id=file_id)
    return file_id


# -- the one ask ------------------------------------------------------------------------------------------


def ask_text(cfg: CoreConfig, subject: materias.Subject, book: dict) -> str:
    e = messages.e
    where = "No está en el aula virtual."
    if book["archivos"]:
        where = (f"En el aula está «{e(book['archivos'][0]['archivo'])}», pero pesa más de lo que bajo "
                 f"({cfg.max_file_mb:g} MB, <code>material.tamano_maximo_mb</code> en config.toml).")
    elif book["enlaces"]:
        link = book["enlaces"][0]
        where = (f"En el aula solo está como enlace ({e(link['tipo'])}) y no lo pude abrir"
                 + (f": {e(link['motivo'])}" if link["motivo"] else "")
                 + f". {messages.link(link['url'], link['titulo'] or 'Abrir enlace')}.")
    said = "Según el sílabo es" if (book["origen"] or "").startswith("sílabo") else "Me dijiste que es"
    return (f"📘 <b>El libro principal de {e(subject.name)}</b>\n"
            f"{said}: <i>{e(book['titulo'])}</i>\n{where}\n\n"
            "Si lo tienes en PDF, pásamelo una vez y lo uso primero al explicarte y en los briefs:\n"
            f"• Hasta {TELEGRAM_BOT_LIMIT_MB} MB: mándamelo aquí, en este chat.\n"
            f"• Si pesa más (Telegram no deja que un bot reciba archivos de más de {TELEGRAM_BOT_LIMIT_MB} MB): ponlo en "
            f"la carpeta <code>{e(folder(cfg, subject.code))}</code> de tu computadora y lo tomo solo en la próxima "
            "revisión del aula.\n"
            "No te lo vuelvo a pedir.")


def readable_files(book: dict) -> list[dict]:
    return [f for f in book["archivos"] if f["estado"] not in UNUSABLE]


def needs_ask(book: dict) -> bool:
    return bool(book["titulo"]) and not readable_files(book) and not book["pedido"]
