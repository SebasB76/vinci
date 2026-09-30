"""Downloads course files into per-course folders and indexes their text.

Only each course's syllabus downloads on its own (`sync_materials`): it is small, and it names the
main book. Everything else in the catalog stays metadata until a bot or the student asks for it
(`download`). Material that did not come from Canvas (a public link, a PDF the student handed
over) joins the catalog with a negative id (`add_local`) and is indexed the same way.

A PDF page with no text (a scan) is read with OCR once per file content (`read_scans`): indexing only
registers it and puts in the text already read for the same bytes, so a copy or a download of the same
file again costs nothing. What is not read yet (no OCR engine, or the time a run had ran out) stays
an image for ver_pagina until a later run reads it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aula_core import catalog, extract, ocr, syllabus, timefmt
from aula_core.canvas import (
    CanvasClient,
    CanvasError,
    InvalidTokenError,
    ThrottledError,
)
from aula_core.config import CoreConfig

log = logging.getLogger(__name__)

CHUNK_CHARS = 2000
READABLE = ("pdf", "pptx", "docx", "html")
SCANNED_CHARS = 40  # a PDF page with less text than this is an image: a scan, a photo, a handwritten board


@dataclass
class MaterialResult:
    file_id: int
    name: str
    status: str


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^A-Za-z0-9._ -]+", "", value).strip().replace(" ", "-")
    return re.sub(r"-{2,}", "-", value)[:80] or "curso"


def safe_filename(value: str) -> str:
    value = value.replace("/", "-").replace("\\", "-").replace("\x00", "").strip(". ")
    return value[:150] or "archivo"


def extension(row: sqlite3.Row) -> str:
    name = row["filename"] or row["display_name"] or ""
    return Path(name).suffix.lower().lstrip(".")


def is_syllabus(row: sqlite3.Row) -> bool:
    return extension(row) in ("pdf", "docx") and syllabus.is_syllabus(row["display_name"])


def course_dir(conn: sqlite3.Connection, cfg: CoreConfig, course_id: int) -> Path:
    course = conn.execute("SELECT name, course_code FROM courses WHERE id = ?", (course_id,)).fetchone()
    label = (course["course_code"] or course["name"]) if course else str(course_id)
    return cfg.materials_dir / slug(label)


def _meta(client: CanvasClient, row: sqlite3.Row) -> dict:
    """The file's download link: through its course, else the file itself (an announcement's attachment),
    else the link the announcement carried."""
    for path in (f"courses/{row['course_id']}/files/{row['id']}", f"files/{row['id']}"):
        try:
            return client.get(path)
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            if exc.status not in (401, 403, 404):
                raise
    if row["download_url"]:
        return {"url": row["download_url"]}
    raise CanvasError(f"No tengo acceso a {row['display_name']} en el aula virtual", 403)


def download(conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig, file_id: int, *, force: bool = False) -> Path:
    """Download one file (read-only GET) into its course folder; returns the local path."""
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise KeyError(file_id)
    here = Path(row["local_path"]) if row["local_path"] else None
    if file_id < 0:  # never came from Canvas: it is the copy we have, or nothing
        if here and here.exists():
            return here
        raise CanvasError(f"{row['display_name']} ya no está en esta computadora")
    if not force and here and row["downloaded_version"] == row["updated_at"] and here.exists():
        return here
    cap = int(cfg.max_file_mb * 1024 * 1024)
    if row["size"] and row["size"] > cap:
        raise CanvasError(f"{row['display_name']} pesa {row['size'] / 1024 / 1024:.0f} MB, más que el tope de "
                          f"{cfg.max_file_mb:g} MB (material.tamano_maximo_mb en config.toml)")
    url = _meta(client, row).get("url")
    if not url:
        raise CanvasError(f"Canvas no da enlace de descarga para {row['display_name']}")
    folder = course_dir(conn, cfg, row["course_id"])
    if here:
        dest = here
    else:
        name, ext = safe_filename(row["display_name"]), extension(row)
        if ext and Path(name).suffix.lower().lstrip(".") != ext:
            name = f"{name}.{ext}"
        dest = folder / name
        taken = conn.execute("SELECT 1 FROM files WHERE local_path = ? AND id != ?", (str(dest), file_id)).fetchone()
        if taken:
            dest = dest.with_name(f"{dest.stem} ({file_id}){dest.suffix}")
    client.download(url, dest, max_bytes=cap)
    conn.execute(
        "UPDATE files SET local_path = ?, downloaded_version = ?, index_status = NULL WHERE id = ?",
        (str(dest), row["updated_at"], file_id),
    )
    conn.commit()
    return dest


def _status(pages: list[tuple[int, str]], ext: str) -> str:
    if ext == "pdf" and pages and sum(len(text) < SCANNED_CHARS for _, text in pages) * 2 > len(pages):
        return "escaneado"
    return "ok" if any(text for _, text in pages) else "sin_texto"


def file_digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def _store_page(conn: sqlite3.Connection, file_id: int, course_id: int, number: int, text: str) -> None:
    for start in range(0, len(text), CHUNK_CHARS):
        piece = text[start:start + CHUNK_CHARS]
        if piece.strip():
            conn.execute("INSERT INTO chunks(text, file_id, course_id, page) VALUES (?, ?, ?, ?)",
                         (piece, file_id, course_id, number))


def _register_scanned(conn: sqlite3.Connection, digest: str, numbers) -> dict[int, str]:
    """Queue for OCR the pages of this content not seen before; the text already read for the others."""
    conn.executemany("INSERT OR IGNORE INTO ocr_pages(digest, page) VALUES (?, ?)", [(digest, n) for n in numbers])
    return {r["page"]: r["text"] for r in conn.execute(
        "SELECT page, text FROM ocr_pages WHERE digest = ? AND text != ''", (digest,))}


def index(conn: sqlite3.Connection, file_id: int) -> str:
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    path = Path(row["local_path"] or "")
    try:
        pages = extract.extract(path)
    except ValueError:
        status = "no_soportado"
        pages = []
    except Exception as exc:
        log.warning("No pude leer %s: %s", path.name, exc)
        status = "error_lectura"
        pages = []
    else:
        status = _status(pages, path.suffix.lower().lstrip("."))
    scanned = [n for n, text in pages if len(text) < SCANNED_CHARS] if path.suffix.lower() == ".pdf" else []
    digest = file_digest(path) if pages and path.suffix.lower() == ".pdf" else None
    books = _bibliography(path, pages) if pages and is_syllabus(row) else None
    # Write only after the (slow) extraction, so a sync running meanwhile never waits on this transaction.
    read = _register_scanned(conn, digest, scanned) if digest else {}
    pages = [(n, read.get(n) or text) for n, text in pages]
    language = catalog.language("\n".join(text for _, text in pages[:40])) or "" if pages else ""
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    for number, text in pages:
        _store_page(conn, file_id, row["course_id"], number, text)
    conn.execute("UPDATE files SET index_status = ?, pages = ?, language = ?, digest = ? WHERE id = ?",
                 (status, len(pages), language, digest, file_id))
    if books is not None:
        _store_bibliography(conn, row, books)
    conn.commit()
    return status


def _bibliography(path: Path, pages: list[tuple[int, str]]) -> dict:
    text = ""
    if path.suffix.lower() == ".pdf":
        try:
            text = extract.layout_text(path)
        except Exception as exc:
            log.warning("%s: %s", path.name, exc)
    books = syllabus.parse(text) if text else {"main": []}
    return books if books["main"] else syllabus.parse("\n".join(t for _, t in pages))


def _store_bibliography(conn: sqlite3.Connection, row: sqlite3.Row, books: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO bibliography(file_id, course_id, main, others, parsed_at) VALUES (?, ?, ?, ?, ?)",
                 (row["id"], row["course_id"], json.dumps(books["main"], ensure_ascii=False),
                  json.dumps(books.get("others", []), ensure_ascii=False), timefmt.iso(datetime.now().astimezone())))


def backfill(conn: sqlite3.Connection) -> None:
    """What files indexed by an earlier version lack: their language, whether they are a scan, a
    syllabus' books, and their pages with no text queued for OCR. From the index already there: nothing
    is read again from Canvas."""
    rows = conn.execute("SELECT * FROM files WHERE index_status IN ('ok', 'sin_texto') AND language IS NULL").fetchall()
    for row in rows:
        by_page: dict[int, int] = {}
        text = []
        for chunk in conn.execute("SELECT page, text FROM chunks WHERE file_id = ? ORDER BY rowid", (row["id"],)):
            by_page[int(chunk["page"])] = by_page.get(int(chunk["page"]), 0) + len(chunk["text"])
            if len(text) < 30:
                text.append(chunk["text"])
        total = row["pages"] or len(by_page)
        status = row["index_status"]
        if extension(row) == "pdf" and total and sum(n >= SCANNED_CHARS for n in by_page.values()) * 2 < total:
            status = "escaneado"
        conn.execute("UPDATE files SET language = ?, index_status = ? WHERE id = ?",
                     (catalog.language("\n".join(text)) or "", status, row["id"]))
    for row in conn.execute("SELECT f.* FROM files f LEFT JOIN bibliography b ON b.file_id = f.id WHERE b.file_id IS NULL"
                            " AND f.index_status IN ('ok', 'escaneado') AND f.local_path IS NOT NULL").fetchall():
        if is_syllabus(row) and Path(row["local_path"]).exists():
            pages = [(int(c["page"]), c["text"]) for c in
                     conn.execute("SELECT page, text FROM chunks WHERE file_id = ? ORDER BY rowid", (row["id"],))]
            _store_bibliography(conn, row, _bibliography(Path(row["local_path"]), pages))
    for row in conn.execute("SELECT * FROM files WHERE digest IS NULL AND pages > 0 AND local_path LIKE '%.pdf'"
                            " AND index_status IN ('ok', 'escaneado')").fetchall():
        path = Path(row["local_path"])
        if not path.exists():
            continue
        size: dict[int, int] = {}
        for chunk in conn.execute("SELECT page, length(text) AS n FROM chunks WHERE file_id = ?", (row["id"],)):
            size[int(chunk["page"])] = size.get(int(chunk["page"]), 0) + chunk["n"]
        digest = file_digest(path)
        _register_scanned(conn, digest, [n for n in range(1, row["pages"] + 1) if size.get(n, 0) < SCANNED_CHARS])
        conn.execute("UPDATE files SET digest = ? WHERE id = ?", (digest, row["id"]))
        _apply_read(conn, digest)
    conn.commit()


def _apply_read(conn: sqlite3.Connection, digest: str, pages: list[int] | None = None) -> None:
    """Put the OCR text of `digest` (only `pages`, if given) into the index of every file with that content."""
    marks = f" AND page IN ({','.join('?' * len(pages))})" if pages else ""
    read = conn.execute(f"SELECT page, text FROM ocr_pages WHERE digest = ? AND text != ''{marks}",
                        [digest, *(pages or [])]).fetchall()
    for f in conn.execute("SELECT id, course_id, language FROM files WHERE digest = ?", (digest,)).fetchall():
        for r in read:
            conn.execute("DELETE FROM chunks WHERE file_id = ? AND page = ?", (f["id"], r["page"]))
            _store_page(conn, f["id"], f["course_id"], r["page"], r["text"])
        if read and not f["language"]:
            text = [c["text"] for c in conn.execute("SELECT text FROM chunks WHERE file_id = ? ORDER BY rowid LIMIT 30",
                                                    (f["id"],))]
            conn.execute("UPDATE files SET language = ? WHERE id = ?", (catalog.language("\n".join(text)) or "", f["id"]))


def read_scans(conn: sqlite3.Connection, cfg: CoreConfig, *, seconds: float | None = None,
               file_id: int | None = None, background: bool = False) -> int:
    """OCR the pages still waiting (only those of `file_id`, if given) until `seconds` run out; the smallest
    files first, so a handout never waits behind a scanned book. Returns how many pages it read."""
    eng = ocr.engine(cfg.data_dir)
    if eng is None:
        return 0
    deadline = time.monotonic() + seconds if seconds is not None else None
    extra, params = (" AND f.id = ?", [file_id]) if file_id is not None else ("", [])
    waiting = conn.execute(
        f"""SELECT o.digest, COUNT(DISTINCT o.page) AS n FROM ocr_pages o JOIN files f ON f.digest = o.digest
            WHERE o.text IS NULL{extra} GROUP BY o.digest ORDER BY n, o.digest""", params).fetchall()
    done = 0
    for item in waiting:
        copies = conn.execute("SELECT local_path FROM files WHERE digest = ? AND local_path IS NOT NULL", (item["digest"],))
        path = next((p for p in (Path(r["local_path"]) for r in copies) if p.exists()), None)
        if path is None:
            continue
        numbers = [r["page"] for r in conn.execute(
            "SELECT page FROM ocr_pages WHERE digest = ? AND text IS NULL ORDER BY page", (item["digest"],))]
        for number in numbers:
            if deadline is not None and time.monotonic() >= deadline:
                return done
            try:
                text, confidence = ocr.read_page(eng, path, number, background=background)
            except Exception as exc:  # a page tesseract cannot read stays an image for ver_pagina
                log.warning("OCR de %s p.%d: %s", path.name, number, exc)
                text, confidence = "", None
            if len(text) < SCANNED_CHARS:
                text = ""  # a blank page, or a figure with a stray letter: nothing to search
            cur = conn.execute("UPDATE ocr_pages SET text = ?, confidence = ?, read_at = ? WHERE digest = ? AND page = ?"
                               " AND text IS NULL", (text, confidence, timefmt.iso(datetime.now().astimezone()),
                                                     item["digest"], number))
            if cur.rowcount:  # another run may have read it meanwhile
                _apply_read(conn, item["digest"], [number])
                done += 1
            conn.commit()
    return done


def sync_materials(conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig, *,
                   budget_mb: float | None = None) -> list[MaterialResult]:
    """Download and index each course's syllabus when it is new or updated, up to `budget_mb` a run (the
    first file always goes): the rest waits for the next run. Nothing else downloads on its own."""
    backfill(conn)
    results = []
    max_bytes = cfg.max_file_mb * 1024 * 1024
    budget, used = (budget_mb * 1024 * 1024 if budget_mb is not None else float("inf")), 0
    rows = conn.execute("SELECT * FROM files WHERE active = 1 AND id > 0 AND duplicate_of IS NULL"
                        " ORDER BY course_id, id").fetchall()
    for row in rows:
        if not is_syllabus(row):
            continue
        current = (row["downloaded_version"] == row["updated_at"] and row["index_status"]
                   and row["local_path"] and Path(row["local_path"]).exists())
        if current:
            continue
        if row["size"] and row["size"] > max_bytes:
            if row["index_status"] != "muy_grande":
                conn.execute("UPDATE files SET index_status = 'muy_grande' WHERE id = ?", (row["id"],))
                conn.commit()
            continue
        if used and used + (row["size"] or 0) > budget:
            break
        try:
            used += download(conn, client, cfg, row["id"]).stat().st_size
            status = index(conn, row["id"])
        except (InvalidTokenError, ThrottledError):
            raise
        except CanvasError as exc:
            log.warning("%s: %s", row["display_name"], exc)
            status = "error_descarga"
        results.append(MaterialResult(row["id"], row["display_name"], status))
    return results


def add_local(conn: sqlite3.Connection, cfg: CoreConfig, course_id: int, path: Path, *, name: str, source: str,
              html_url: str | None = None, in_place: bool = False, file_id: int | None = None) -> int:
    """Index material that did not come from Canvas. `in_place` keeps it where it is (the student's own
    folder); otherwise it is copied next to the course's downloads. Returns its (negative) id."""
    if file_id is None:
        file_id = min(-1, (conn.execute("SELECT MIN(id) FROM files").fetchone()[0] or 0) - 1)
    if in_place:
        dest = path
    else:
        folder = course_dir(conn, cfg, course_id) / "recibidos"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / safe_filename(name)
        n = 1
        while dest.exists() and dest.resolve() != path.resolve():
            dest = folder / f"{Path(safe_filename(name)).stem}-{n}{Path(name).suffix}"
            n += 1
        if dest.resolve() != path.resolve():
            shutil.copy2(path, dest)
    stat = dest.stat()
    now = timefmt.iso(datetime.now().astimezone())
    conn.execute(
        """INSERT INTO files(id, course_id, display_name, filename, size, updated_at, html_url, local_path,
             downloaded_version, index_status, active, first_seen, source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET course_id=excluded.course_id, display_name=excluded.display_name,
             filename=excluded.filename, size=excluded.size, updated_at=excluded.updated_at, html_url=excluded.html_url,
             local_path=excluded.local_path, downloaded_version=excluded.downloaded_version, index_status=NULL,
             active=1, source=excluded.source""",
        (file_id, course_id, name, dest.name, stat.st_size, now, html_url, str(dest), f"{stat.st_size}:{int(stat.st_mtime)}",
         now, source, now))
    conn.commit()
    index(conn, file_id)
    return file_id
