"""The course material catalog, as plain functions: text cleanup, what an aula page links to,
what kind of place an external link is, which documents are copies of another, and which
ones belong to an earlier semester. No Canvas calls; the only SQL is `mark_duplicates`."""

from __future__ import annotations

import html
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def fold(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", value)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def clean_title(value: str | None) -> str | None:
    """A module or subheader name as a person reads it: some professors write them in LaTeX
    (`\\( \\Large \\color{grey} \\text{Semana 1} \\)`), which Canvas renders but an alert would not."""
    if not value or "\\" not in value and "$" not in value:
        return value.strip() if value else value
    text = re.sub(r"\\[()\[\]]", " ", value)
    text = re.sub(r"\\(?:color|textcolor)\{[^}]*\}", " ", text)
    text = re.sub(r"\\(?:text\w*|math\w+|emph|bf|it)\s*\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+\*?|\\[,;:! ]", " ", text)
    text = re.sub(r"[{}$~]", " ", text)
    return re.sub(r"\s+", " ", text).strip() or value.strip()


# -- what an aula page (a Page, the «Programa del curso», an announcement, an assignment) links to ----

ANCHOR = re.compile(r"""<a\b([^>]*)>(.*?)</a>""", re.I | re.S)
IFRAME = re.compile(r"""<iframe\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", re.I)
HREF = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.I)
FILE_PATH = re.compile(r"^(?:/api/v1)?(?:/courses/(\d+))?/files/(\d+)(?:/|$)")
PAGE_PATH = re.compile(r"^(?:/api/v1)?/courses/(\d+)/pages/([^/?#]+)")
IMAGE_NAME = re.compile(r"\.(?:png|jpe?g|gif|webp|svg|bmp)$", re.I)


@dataclass(frozen=True)
class Refs:
    files: tuple[tuple[int | None, int, str], ...] = ()   # (course id in the link, file id, anchor text)
    pages: tuple[tuple[int, str], ...] = ()               # (course id, page slug)
    links: tuple[tuple[str, str], ...] = ()               # (url, anchor text)

    def as_json(self) -> dict:
        return {"files": [list(f) for f in self.files], "pages": [list(p) for p in self.pages],
                "links": [list(link) for link in self.links]}

    @classmethod
    def from_json(cls, data: dict) -> "Refs":
        return cls(tuple(tuple(f) for f in data.get("files", [])), tuple(tuple(p) for p in data.get("pages", [])),
                   tuple(tuple(link) for link in data.get("links", [])))


def refs(body: str | None, canvas_url: str) -> Refs:
    """The files, pages and outside links an aula HTML body points to. Only anchors count (and embedded
    videos): an <img> is the page's own decoration, like the ESPOL template banners."""
    if not body:
        return Refs()
    canvas = urlsplit(canvas_url)
    files, pages, links = {}, {}, {}
    for attrs, inner in ANCHOR.findall(body):
        match = HREF.search(attrs)
        if not match:
            continue
        url = html.unescape(match[1]).strip()
        text = re.sub(r"\s+", " ", html_to_text(inner)).strip()
        parts = urlsplit(url)
        if parts.scheme in ("", "http", "https") and parts.netloc in ("", canvas.netloc):
            if file := FILE_PATH.match(parts.path):
                if not IMAGE_NAME.search(text):
                    files.setdefault(int(file[2]), (int(file[1]) if file[1] else None, int(file[2]), text))
            elif page := PAGE_PATH.match(parts.path):
                pages.setdefault((int(page[1]), page[2]), None)
            continue
        if parts.scheme in ("http", "https") and parts.netloc:
            links.setdefault(url, text or url)
    for src in IFRAME.findall(body):
        url = html.unescape(src).strip()
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and parts.netloc and parts.netloc != canvas.netloc:
            links.setdefault(url, url)
    return Refs(tuple(files.values()), tuple(pages), tuple(links.items()))


# -- external links --------------------------------------------------------------------------------

PUBLIC = "publico"      # a file or a page anyone can open: the bot fetches it when it needs it
LINK_ONLY = "solo_enlace"  # needs the student's ESPOL login, or is a video or a folder: only listed

KIND_LABEL = {
    "dropbox": "archivo de Dropbox", "dropbox_carpeta": "carpeta de Dropbox", "sharepoint": "SharePoint de ESPOL",
    "onedrive": "OneDrive", "stream": "video de Microsoft Stream", "video": "video", "zoom": "grabación de Zoom",
    "google": "Google Drive / Docs", "microsoft": "Microsoft Teams / Forms", "web": "página web",
}
WHY_LINK_ONLY = {
    "sharepoint": "pide tu cuenta de ESPOL", "onedrive": "pide tu cuenta de ESPOL", "stream": "es un video que pide tu cuenta de ESPOL",
    "google": "solo abre con tu cuenta o si el profe lo compartió con cualquiera", "microsoft": "pide tu cuenta de ESPOL",
    "video": "es un video (todavía no los proceso)", "zoom": "es una grabación (todavía no las proceso)",
    "dropbox_carpeta": "es una carpeta, no un archivo",
}


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify(url: str) -> tuple[str, str]:
    """(kind, access) of an outside link."""
    host, path = _host(url), urlsplit(url).path

    def under(*domains: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in domains)

    if under("dropbox.com", "dropboxusercontent.com"):
        folder = path.startswith(("/scl/fo/", "/sh/"))
        return ("dropbox_carpeta", LINK_ONLY) if folder else ("dropbox", PUBLIC)
    if under("microsoftstream.com") or host == "stream.microsoft.com" or (under("sharepoint.com") and "/:v:/" in path):
        return "stream", LINK_ONLY
    if under("sharepoint.com"):
        return "sharepoint", LINK_ONLY
    if under("onedrive.live.com", "onedrive.com", "1drv.ms"):
        return "onedrive", LINK_ONLY
    if under("youtube.com", "youtu.be", "vimeo.com"):
        return "video", LINK_ONLY
    if under("zoom.us"):
        return "zoom", LINK_ONLY
    if under("docs.google.com", "drive.google.com", "forms.gle"):
        return "google", LINK_ONLY
    if under("teams.microsoft.com", "forms.office.com", "office.com", "microsoft365.com"):
        return "microsoft", LINK_ONLY
    return "web", PUBLIC


def direct_url(url: str) -> str:
    """The URL that downloads a public link's file (a Dropbox share link needs dl=1)."""
    if classify(url)[0] != "dropbox":
        return url
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "dl"] + [("dl", "1")]
    return urlunsplit(parts._replace(query=urlencode(query)))


# -- copies and old semesters ----------------------------------------------------------------------

YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def years(*texts: str | None) -> list[int]:
    return [int(y) for text in texts if text for y in YEAR.findall(text)]


def term_year(term_start: str | None, course_name: str | None, term: str | None) -> int | None:
    """The year of the course's semester: from its term's start, else from its name («… 2026-1T»)."""
    return (years(term_start) or years(course_name, term) or [None])[0]


def is_old(folder: str | None, name: str | None, term_year: int | None) -> bool:
    """Material of an earlier semester: its folder or name only mentions earlier years (`Slides/2021`)."""
    found = years(folder, name)
    return bool(term_year and found) and max(found) < term_year


def normalized_name(name: str | None) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", fold(name))
    stem = re.sub(r"^(copia de|copy of)\s+|\s*(\(\d+\)|-\s*copia|copy)$", "", stem.strip())
    return re.sub(r"[^a-z0-9]+", "", stem)


def mark_duplicates(conn: sqlite3.Connection, course_id: int, term_year: int | None) -> None:
    """Copies of a document (same name, same size, in another folder or year) point at the one kept: the
    newest. Search skips the copies; nothing is deleted."""
    rows = conn.execute("SELECT id, display_name, size, folder, updated_at FROM files"
                        " WHERE course_id = ? AND active = 1 AND id > 0", (course_id,)).fetchall()
    groups: dict[tuple[str, int], list[sqlite3.Row]] = {}
    for r in rows:
        if r["size"]:
            groups.setdefault((normalized_name(r["display_name"]), r["size"]), []).append(r)
    keep_of: dict[int, int | None] = {r["id"]: None for r in rows}
    for copies in groups.values():
        if len(copies) < 2:
            continue
        kept = max(copies, key=lambda r: (not is_old(r["folder"], r["display_name"], term_year),
                                          max(years(r["folder"], r["display_name"]) or [0]), r["updated_at"] or "", r["id"]))
        for r in copies:
            keep_of[r["id"]] = None if r["id"] == kept["id"] else kept["id"]
    conn.executemany("UPDATE files SET duplicate_of = ? WHERE id = ? AND duplicate_of IS NOT ?",
                     [(kept, fid, kept) for fid, kept in keep_of.items()])


# -- language --------------------------------------------------------------------------------------

SPANISH = set("de la que el en los del las por una para con se es al como mas pero sus este esta entre cuando "
              "tambien son su lo le hay sobre".split())
ENGLISH = set("the of and to in is that for with as are this by be on from which an or can it its these "
              "we not".split())


def language(text: str) -> str | None:
    """'es' or 'en' from the most common words; None with too little text to tell."""
    words = re.findall(r"[a-z]+", fold(text[:60000]))
    es, en = sum(w in SPANISH for w in words), sum(w in ENGLISH for w in words)
    if es + en < 20:
        return None
    return "es" if es >= en else "en"
