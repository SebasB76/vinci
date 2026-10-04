"""Opens an outside link of the catalog without a login and indexes what it leads to.

Try, then decide. Only links the aula itself shows are opened. One that may open without the student's
account (a Google Doc, Slides, Sheets or Drive file, a SharePoint or Dropbox share, a professor's page)
is asked for anonymously, through the address that hands over its document (a Google file's PDF export,
a share's download), and what comes back decides: a document joins the catalog like an aula PDF; a
login page, a redirect to one, or a 401/403 means it is private. The outcome is kept per link, so a
private link is not asked for again on every question (only after PRIVATE_RETRY, or when the student
says it is shared now), and a Google file, which its owner keeps editing, is read again after REFRESH.
Videos, forms and folders are never fetched.

Anonymous means anonymous: the request carries no Canvas token (it is not the Canvas client), keeps and
sends no cookie (not even one the host sets on the way), reads no .netrc or proxy credential, and follows
redirects by hand so each hop is checked. It refuses addresses inside the student's network or computer
(the aula's own host aside: it is the one server the bot already reads), and a download has a size and
a time cap. What comes back is material to read, never instructions.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import re
import socket
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from html.parser import HTMLParser
from http.cookiejar import DefaultCookiePolicy
from pathlib import Path
from urllib.parse import unquote, urlencode, urljoin, urlsplit

import requests

from aula_core import materials, timefmt
from aula_core.canvas import USER_AGENT, CanvasError
from aula_core.catalog import KIND_LABEL, LINK_ONLY, PUBLIC, WHY_LINK_ONLY, classify, download_url
from aula_core.config import CoreConfig, section

log = logging.getLogger(__name__)

MAX_REDIRECTS = 8
TIMEOUT = (10, 30)
DEADLINE = 120  # seconds for a whole download, however slowly the host sends it
PRIVATE_RETRY = timedelta(hours=6)
REFRESH = timedelta(days=1)
LIVING = ("google_doc", "google_slides", "google_sheet", "google_drawing")
LOGIN_HOSTS = {"accounts.google.com": "google", "login.microsoftonline.com": "sharepoint",
               "login.microsoft.com": "sharepoint", "login.live.com": "sharepoint", "login.windows.net": "sharepoint"}
LOGIN_PATH = re.compile(r"(?i)/(?:servicelogin|signin|login|_forms/default\.aspx|_layouts/15/authenticate\.aspx)")
LOGIN = {"google": "Google pide iniciar sesión (no está compartido con «cualquier persona con el enlace»)",
         "sharepoint": "pide tu cuenta de ESPOL (Microsoft no lo abre sin iniciar sesión)",
         "dropbox": "Dropbox pide iniciar sesión", "web": "la página pide iniciar sesión o no deja entrar a un bot"}


class LinkError(CanvasError):
    pass


class _Refused(Exception):
    """Why a link gave no document; `lasting` when asking again soon would get the same (a login, a 404)."""

    def __init__(self, reason: str, lasting: bool = True):
        super().__init__(reason)
        self.lasting = lasting


def _provider(kind: str) -> str:
    return "google" if kind.startswith("google") else kind if kind in LOGIN else "web"


def route(url: str, cfg: CoreConfig) -> str:
    """Where a request for `url` really goes. `[test] link_hosts` in config.toml ({host: base}) sends a host
    and its subdomains to a local stand-in: the E2E test's Google, SharePoint and DSpace. A real install has none."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    for name, base in section(cfg.raw, "test").get("link_hosts", {}).items():
        if host == name or host.endswith("." + name):
            return base.rstrip("/") + parts.path + (f"?{parts.query}" if parts.query else "")
    return url


def _public_host(url: str, canvas_url: str) -> None:
    host = urlsplit(url).hostname or ""
    if host == urlsplit(canvas_url).hostname:
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError as exc:
        raise _Refused(f"no encuentro {host} ({exc})", lasting=False) from None
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise _Refused(f"{host} no es una dirección pública de internet; no la abro")


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # no .netrc login and no proxy credentials from the environment
    session.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))  # keeps no cookie, so it sends none
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _login(url: str, kind: str) -> str | None:
    """Why a redirect to `url` means the document is private: whose login it is (None: not a login page)."""
    host = (urlsplit(url).hostname or "").lower()
    if host in LOGIN_HOSTS:
        return LOGIN[LOGIN_HOSTS[host]]
    return LOGIN[_provider(kind)] if LOGIN_PATH.search(urlsplit(url).path) else None


def sniff(body: bytes, content_type: str) -> str | None:
    """What the bytes are, by their content (Drive sends every file as application/octet-stream)."""
    if body.startswith(b"%PDF"):
        return "pdf"
    if body.startswith(b"PK\x03\x04"):
        try:
            members = zipfile.ZipFile(io.BytesIO(body)).namelist()
        except zipfile.BadZipFile:
            return None
        return next((ext for ext, folder in (("docx", "word/"), ("pptx", "ppt/"))
                     if any(m.startswith(folder) for m in members)), None)
    head = body[:512].lstrip().lower()
    if content_type in ("text/html", "application/xhtml+xml") or head.startswith((b"<!doctype html", b"<html")):
        return "html"
    return None


class _DriveWarning(HTMLParser):
    """The page Drive shows before a big file («Google Drive can't scan this file for viruses»): its form
    goes on to the download."""

    def __init__(self):
        super().__init__()
        self.action: str | None = None
        self.fields: list[tuple[str, str]] = []
        self._inside = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "download-form":
            self.action, self._inside = attrs.get("action"), True
        elif tag == "input" and self._inside and attrs.get("type") == "hidden" and attrs.get("name"):
            self.fields.append((attrs["name"], attrs.get("value") or ""))

    def handle_endtag(self, tag):
        if tag == "form":
            self._inside = False


def _drive_confirm(url: str, body: bytes) -> str | None:
    if (urlsplit(url).hostname or "") != "drive.usercontent.google.com":
        return None
    page = _DriveWarning()
    page.feed(body.decode("utf-8", "replace"))
    return f"{urljoin(url, page.action)}?{urlencode(page.fields)}" if page.action and page.fields else None


def _file_name(resp: requests.Response) -> str | None:
    value = resp.headers.get("Content-Disposition", "")
    if match := re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", value, re.I):
        return unquote(match[1]).strip('" ')
    if match := re.search(r'filename\s*=\s*"?([^";]+)"?', value, re.I):
        return match[1].strip()
    return None


def _body(resp: requests.Response, max_bytes: int, started: float) -> bytes:
    size = resp.headers.get("Content-Length", "")
    too_big = f"pesa más de {max_bytes // 1024 // 1024} MB, el tope (material.tamano_maximo_mb en config.toml)"
    if size.isdigit() and int(size) > max_bytes:
        raise _Refused(too_big)
    body = bytearray()
    try:
        for chunk in resp.iter_content(65536):
            body += chunk
            if len(body) > max_bytes:
                raise _Refused(too_big)
            if time.monotonic() - started > DEADLINE:
                raise _Refused(f"tardó más de {DEADLINE} s en bajar", lasting=False)
    except requests.RequestException as exc:
        raise _Refused(f"se cortó la descarga ({type(exc).__name__})", lasting=False) from None
    return bytes(body)


def _download(link_url: str, kind: str, cfg: CoreConfig) -> tuple[bytes, str, str | None]:
    """(body, extension, the file name the host gave) of the document behind a link, asked for anonymously.
    A share or an export must hand over a document: a page there is its login or «ask for access» page."""
    url = download_url(link_url)
    rerouted, confirmed, started = url != link_url, False, time.monotonic()
    max_bytes = int(cfg.max_file_mb * 1024 * 1024)
    session = _session()
    try:
        for _ in range(MAX_REDIRECTS + 1):
            if time.monotonic() - started > DEADLINE:
                raise _Refused(f"tardó más de {DEADLINE} s en responder", lasting=False)
            target = route(url, cfg)
            _public_host(target, cfg.canvas_url)
            try:
                resp = session.get(target, timeout=TIMEOUT, stream=True, allow_redirects=False)
            except requests.RequestException as exc:
                raise _Refused(f"no pude conectar ({type(exc).__name__})", lasting=False) from None
            with resp:
                if resp.is_redirect and resp.headers.get("Location"):
                    url = urljoin(url, resp.headers["Location"])
                    if login := _login(url, kind):
                        raise _Refused(login)
                    landed = classify(url)
                    if not rerouted and landed[1] == PUBLIC and download_url(url) != url:
                        # A short link that lands on a Google file or a share: that one's download instead.
                        url, kind, rerouted = download_url(url), landed[0], True
                    continue
                status = resp.status_code
                if status in (401, 403):
                    raise _Refused(LOGIN[_provider(kind)])
                if status in (404, 410):
                    raise _Refused("el enlace ya no existe (lo borraron o lo movieron)")
                if status == 429 or status >= 500:
                    raise _Refused(f"el sitio respondió {status}", lasting=False)
                if status >= 400:
                    raise _Refused(f"el sitio respondió {status}")
                body = _body(resp, max_bytes, started)
                content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                ext = sniff(body, content_type)
                if ext == "html" and not confirmed and (confirm := _drive_confirm(url, body)):
                    url, confirmed = confirm, True
                    continue
                if ext is None:
                    given = _file_name(resp)
                    what = f"«{given}»" if given else f"un {content_type}" if content_type else "un archivo"
                    raise _Refused(f"lleva a {what}, que no sé leer (leo PDF, DOCX, PPTX y páginas web)")
                if ext == "html" and kind != "web":
                    raise _Refused(LOGIN[_provider(kind)])
                return body, ext, _file_name(resp)
        raise _Refused("redirige demasiadas veces")
    finally:
        session.close()


def _copy(conn: sqlite3.Connection, link: sqlite3.Row) -> int | None:
    """The file id of the copy already opened from this link, if it is still on disk."""
    if link["file_id"] is None:
        return None
    row = conn.execute("SELECT local_path FROM files WHERE id = ?", (link["file_id"],)).fetchone()
    return link["file_id"] if row and row["local_path"] and Path(row["local_path"]).exists() else None


def _title(link: sqlite3.Row, given: str | None) -> str:
    """The document's name: the link's text, unless that is the address itself (then the one the host gave)."""
    title = (link["title"] or "").strip()
    if not title or title.startswith(("http://", "https://")):
        title = Path(given).stem if given else "enlace"
    return title


def _refusal(link: sqlite3.Row, reason: str, tried: datetime | None, cfg: CoreConfig) -> str:
    when = (f" (lo intenté el {timefmt.human(tried, cfg.tz)}; si ya lo compartieron con cualquiera que tenga el "
            "enlace, pídeme que lo intente otra vez)") if tried else ""
    return (f"No pude abrir el enlace ({KIND_LABEL.get(link['kind'], link['kind'])}): {reason}{when}. "
            f"Ábrelo tú: {link['url']} y, si es material del curso, descárgalo en PDF y pásamelo.")


def _mark(conn: sqlite3.Connection, link_id: int, now: datetime, problem: str | None) -> None:
    conn.execute("UPDATE links SET checked_at = ?, problem = ? WHERE id = ?", (timefmt.iso(now), problem, link_id))
    conn.commit()


def fetch(conn: sqlite3.Connection, cfg: CoreConfig, link_id: int, now: datetime, *, retry: bool = False) -> int:
    """The catalog file id of the document behind link `link_id`, downloading and indexing it when needed.
    `retry`: ask again now, even if the link was private a moment ago or its copy is recent."""
    link = conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if link is None:
        raise LinkError(f"No conozco el enlace {link_id}.")
    if link["access"] == LINK_ONLY:
        raise LinkError(f"Es un enlace de {KIND_LABEL.get(link['kind'], link['kind'])}: "
                        f"{WHY_LINK_ONLY.get(link['kind'], 'no lo puedo abrir')}. Ábrelo tú: {link['url']}")
    have = _copy(conn, link)
    checked = timefmt.parse(link["checked_at"])
    if have is not None and not retry and (link["kind"] not in LIVING or checked and now - checked < REFRESH):
        return have
    if have is None and link["problem"] and not retry and checked and now - checked < PRIVATE_RETRY:
        raise LinkError(_refusal(link, link["problem"], checked, cfg))
    try:
        body, ext, given = _download(link["url"], link["kind"], cfg)
    except _Refused as exc:
        if have is not None:  # the copy we have still reads; the next question tries again tomorrow
            log.warning("no pude volver a abrir el enlace %s: %s", link_id, exc)
            _mark(conn, link_id, now, None)
            return have
        _mark(conn, link_id, now, str(exc) if exc.lasting else None)
        raise LinkError(_refusal(link, str(exc), None, cfg)) from None
    title = _title(link, given)
    name = materials.safe_filename(title)
    if Path(name).suffix.lower().lstrip(".") != ext:
        name = f"{name}.{ext}"
    if have is not None:  # a newer version of a Google file replaces the copy it had
        old = conn.execute("SELECT local_path FROM files WHERE id = ?", (have,)).fetchone()["local_path"]
        Path(old).unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(body)
        file_id = materials.add_local(conn, cfg, link["course_id"], path, name=name, source=f"Enlace «{title}»",
                                      html_url=link["url"], file_id=link["file_id"])
    conn.execute("UPDATE links SET file_id = ?, checked_at = ?, problem = NULL WHERE id = ?",
                 (file_id, timefmt.iso(now), link_id))
    conn.commit()
    return file_id
