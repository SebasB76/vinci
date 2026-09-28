"""Opens a public outside link from the catalog (a Dropbox file, a professor's page) and indexes it.

Only links the aula itself shows are opened, and only public ones: SharePoint, OneDrive, Stream
and the like need the student's ESPOL login, so they stay listed with their link. The request
carries no Canvas token (it is not the Canvas client), follows redirects by hand so each hop is
checked, and refuses addresses inside the student's network or computer (the aula's own host
aside: it is the one server the bot already reads).
"""

from __future__ import annotations

import ipaddress
import socket
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from aula_core import materials
from aula_core.canvas import USER_AGENT, CanvasError
from aula_core.catalog import KIND_LABEL, LINK_ONLY, WHY_LINK_ONLY, direct_url
from aula_core.config import CoreConfig

MAX_REDIRECTS = 5
TYPES = {"application/pdf": "pdf", "text/html": "html",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx"}


class LinkError(CanvasError):
    pass


def _public_host(url: str, canvas_url: str) -> None:
    host = urlsplit(url).hostname or ""
    if host == urlsplit(canvas_url).hostname:
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError as exc:
        raise LinkError(f"No encuentro {host}: {exc}") from exc
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise LinkError(f"{host} no es una dirección pública de internet; no la abro.")


def _get(url: str, max_bytes: int, canvas_url: str) -> tuple[bytes, str, str]:
    """(body, content type, final URL)."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    for _ in range(MAX_REDIRECTS + 1):
        _public_host(url, canvas_url)
        try:
            resp = session.get(url, timeout=30, stream=True, allow_redirects=False)
        except requests.RequestException as exc:
            raise LinkError(f"No pude abrir el enlace: {exc}") from exc
        if resp.is_redirect and resp.headers.get("Location"):
            url = urljoin(url, resp.headers["Location"])
            resp.close()
            continue
        if resp.status_code in (401, 403):
            raise LinkError("El enlace pide iniciar sesión; ábrelo tú y, si es material, pásamelo.", resp.status_code)
        if resp.status_code >= 400:
            raise LinkError(f"El enlace respondió {resp.status_code}.", resp.status_code)
        body = bytearray()
        for chunk in resp.iter_content(65536):
            body += chunk
            if len(body) > max_bytes:
                raise LinkError("El archivo del enlace es demasiado grande.")
        return bytes(body), resp.headers.get("Content-Type", "").split(";")[0].strip().lower(), url
    raise LinkError("El enlace redirige demasiadas veces.")


def fetch(conn: sqlite3.Connection, cfg: CoreConfig, link_id: int) -> int:
    """Download and index the public link `link_id`; returns its file id in the catalog."""
    link = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if link is None:
        raise LinkError(f"No conozco el enlace {link_id}.")
    if link["file_id"] is not None:
        row = conn.execute("SELECT local_path FROM files WHERE id = ?", (link["file_id"],)).fetchone()
        if row and row["local_path"] and Path(row["local_path"]).exists():
            return link["file_id"]
    if link["access"] == LINK_ONLY:
        raise LinkError(f"Es un enlace de {KIND_LABEL.get(link['kind'], link['kind'])}: "
                        f"{WHY_LINK_ONLY.get(link['kind'], 'no lo puedo abrir')}. Ábrelo tú: {link['url']}")
    body, content_type, final = _get(direct_url(link["url"]), int(cfg.max_file_mb * 1024 * 1024), cfg.canvas_url)
    ext = TYPES.get(content_type) or Path(urlsplit(final).path).suffix.lower().lstrip(".")
    if ext not in materials.READABLE:
        raise LinkError(f"El enlace lleva a un {content_type or 'archivo'} que no sé leer. Ábrelo tú: {link['url']}")
    name = materials.safe_filename(link["title"] or "enlace")
    if Path(name).suffix.lower().lstrip(".") != ext:
        name = f"{name}.{ext}"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(body)
        file_id = materials.add_local(conn, cfg, link["course_id"], path, name=name, source=f"Enlace «{link['title']}»",
                                      html_url=link["url"], file_id=link["file_id"])
    conn.execute("UPDATE links SET file_id = ? WHERE id = ?", (file_id, link_id))
    conn.commit()
    return file_id
