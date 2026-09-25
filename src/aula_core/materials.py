"""Downloads course files into per-course folders and indexes their text."""

from __future__ import annotations

import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from aula_core import extract
from aula_core.canvas import CanvasClient, CanvasError, InvalidTokenError
from aula_core.config import CoreConfig

log = logging.getLogger(__name__)

CHUNK_CHARS = 2000


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


def course_dir(conn: sqlite3.Connection, cfg: CoreConfig, course_id: int) -> Path:
    course = conn.execute("SELECT name, course_code FROM courses WHERE id = ?", (course_id,)).fetchone()
    label = (course["course_code"] or course["name"]) if course else str(course_id)
    return cfg.materials_dir / slug(label)


def download(conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig, file_id: int, *, force: bool = False) -> Path:
    """Download one file (read-only GET) into its course folder; returns the local path."""
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise KeyError(file_id)
    if (not force and row["local_path"] and row["downloaded_version"] == row["updated_at"]
            and Path(row["local_path"]).exists()):
        return Path(row["local_path"])
    meta = client.get(f"courses/{row['course_id']}/files/{file_id}")
    url = meta.get("url")
    if not url:
        raise CanvasError(f"Canvas no da enlace de descarga para {row['display_name']}")
    folder = course_dir(conn, cfg, row["course_id"])
    if row["local_path"]:
        dest = Path(row["local_path"])
    else:
        name, ext = safe_filename(row["display_name"]), extension(row)
        if ext and Path(name).suffix.lower().lstrip(".") != ext:
            name = f"{name}.{ext}"
        dest = folder / name
        taken = conn.execute("SELECT 1 FROM files WHERE local_path = ? AND id != ?", (str(dest), file_id)).fetchone()
        if taken:
            dest = dest.with_name(f"{dest.stem} ({file_id}){dest.suffix}")
    client.download(url, dest, max_bytes=int(cfg.max_file_mb * 1024 * 1024))
    conn.execute(
        "UPDATE files SET local_path = ?, downloaded_version = ?, index_status = NULL WHERE id = ?",
        (str(dest), row["updated_at"], file_id),
    )
    conn.commit()
    return dest


def index(conn: sqlite3.Connection, file_id: int) -> str:
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
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
        status = "ok" if any(text for _, text in pages) else "sin_texto"
    for number, text in pages:
        for start in range(0, len(text), CHUNK_CHARS):
            piece = text[start:start + CHUNK_CHARS]
            if piece.strip():
                conn.execute(
                    "INSERT INTO chunks(text, file_id, course_id, page) VALUES (?, ?, ?, ?)",
                    (piece, file_id, row["course_id"], number),
                )
    conn.execute("UPDATE files SET index_status = ?, pages = ? WHERE id = ?", (status, len(pages), file_id))
    conn.commit()
    return status


def sync_materials(conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig) -> list[MaterialResult]:
    """Download and index every new or updated file of the configured types."""
    results = []
    max_bytes = cfg.max_file_mb * 1024 * 1024
    rows = conn.execute("SELECT * FROM files WHERE active = 1 ORDER BY course_id, id").fetchall()
    for row in rows:
        if extension(row) not in cfg.material_extensions:
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
        try:
            download(conn, client, cfg, row["id"])
            status = index(conn, row["id"])
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            log.warning("%s: %s", row["display_name"], exc)
            status = "error_descarga"
        results.append(MaterialResult(row["id"], row["display_name"], status))
    return results
