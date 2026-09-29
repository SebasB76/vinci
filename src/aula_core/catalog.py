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

PUBLIC = "publico"      # may open without the student's login: a bot tries it anonymously and what comes back decides
LINK_ONLY = "solo_enlace"  # not a document (a video, a form, a folder) or only opens in a browser: only listed

KIND_LABEL = {
    "dropbox": "archivo de Dropbox", "dropbox_carpeta": "carpeta de Dropbox", "sharepoint": "SharePoint de ESPOL",
    "sharepoint_carpeta": "carpeta de SharePoint", "onedrive": "OneDrive", "stream": "video de Microsoft Stream",
    "video": "video", "zoom": "grabación de Zoom", "google_doc": "Google Docs", "google_slides": "Google Slides",
    "google_sheet": "Google Sheets", "google_drawing": "dibujo de Google", "google_drive": "archivo de Google Drive",
    "google_carpeta": "carpeta de Google Drive", "google_form": "formulario de Google", "google": "Google",
    "microsoft": "Microsoft Teams / Forms", "web": "página web",
}
WHY_LINK_ONLY = {
    "stream": "es un video que pide tu cuenta de ESPOL", "video": "es un video (todavía no los proceso)",
    "zoom": "es una grabación (todavía no las proceso)", "dropbox_carpeta": "es una carpeta, no un archivo",
    "sharepoint_carpeta": "es una carpeta, no un archivo", "google_carpeta": "es una carpeta, no un archivo",
    "google_form": "es un formulario, no un documento", "google": "no es un documento que pueda bajar",
    "onedrive": "OneDrive personal solo se abre en el navegador", "microsoft": "pide tu cuenta de ESPOL",
}

# A Google editor file and how it exports as PDF («/d/e/…» is one published to the web: a plain page).
GOOGLE_FILE = re.compile(r"^/(document|presentation|spreadsheets|drawings)/(?:u/\d+/)?d/(?!e/)([\w-]{10,})")
GOOGLE_EXPORT = {"document": ("google_doc", "export?format=pdf"), "presentation": ("google_slides", "export/pdf"),
                 "spreadsheets": ("google_sheet", "export?format=pdf"), "drawings": ("google_drawing", "export/pdf")}
DRIVE_FILE = re.compile(r"^/file/(?:u/\d+/)?d/([\w-]{10,})")
SHAREPOINT_SITE = {"g": "", "s": "/sites", "t": "/teams"}


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _drive_file(url: str) -> str | None:
    parts = urlsplit(url)
    if match := DRIVE_FILE.match(parts.path):
        return match[1]
    if parts.path in ("/uc", "/download"):
        return dict(parse_qsl(parts.query)).get("id")
    return None


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
        return ("sharepoint_carpeta", LINK_ONLY) if path.startswith("/:f:/") else ("sharepoint", PUBLIC)
    if under("onedrive.live.com", "onedrive.com", "1drv.ms"):
        return "onedrive", LINK_ONLY
    if under("youtube.com", "youtu.be", "vimeo.com"):
        return "video", LINK_ONLY
    if under("zoom.us"):
        return "zoom", LINK_ONLY
    if under("forms.gle") or under("docs.google.com") and path.startswith("/forms/"):
        return "google_form", LINK_ONLY
    if host == "docs.google.com" and (match := GOOGLE_FILE.match(path)):
        return GOOGLE_EXPORT[match[1]][0], PUBLIC
    if host == "docs.google.com" and re.match(r"^/\w+/(?:u/\d+/)?d/e/", path):
        return "web", PUBLIC
    if under("drive.google.com", "docs.google.com", "drive.usercontent.google.com") and (_drive_file(url) or path == "/open"):
        return "google_drive", PUBLIC
    if under("drive.google.com") and "folder" in path:
        return "google_carpeta", LINK_ONLY
    if under("docs.google.com", "drive.google.com"):
        return "google", LINK_ONLY
    if under("teams.microsoft.com", "forms.office.com", "office.com", "microsoft365.com"):
        return "microsoft", LINK_ONLY
    return "web", PUBLIC


def download_url(url: str) -> str:
    """Where a link hands over its document without a login: a Google file's PDF export, a Drive file's
    download, a SharePoint share's download.aspx (which needs no cookie), a Dropbox file with dl=1. Any
    other link (a Drive «open?id=», a web page) is fetched as it is, and its redirects decide."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    key = [(k, v) for k, v in query if k == "resourcekey"]  # a Drive file shared by link before 2021 needs it
    kind = classify(url)[0]
    if kind in ("google_doc", "google_slides", "google_sheet", "google_drawing"):
        match = GOOGLE_FILE.match(parts.path)
        export = GOOGLE_EXPORT[match[1]][1]
        return f"https://docs.google.com/{match[1]}/d/{match[2]}/{export}" + (
            ("&" if "?" in export else "?") + urlencode(key) if key else "")
    if kind == "google_drive" and (file_id := _drive_file(url)):
        return "https://drive.google.com/uc?" + urlencode([("export", "download"), ("id", file_id), *key])
    if kind == "sharepoint":
        # A share link (/:b:/s/<site>/<token>) downloads through its site; a path link (/:b:/r/…) as it is.
        steps = parts.path.strip("/").split("/")
        if len(steps) >= 3 and re.fullmatch(r":\w:", steps[0]) and steps[1] in SHAREPOINT_SITE:
            site = "/".join(steps[2:-1])
            if steps[1] == "g" and site:
                site = "/" + site
            elif site:
                site = f"{SHAREPOINT_SITE[steps[1]]}/{site}"
            return urlunsplit(("https", parts.netloc, f"{site}/_layouts/15/download.aspx",
                               urlencode([("share", steps[-1])]), ""))
        return urlunsplit(parts._replace(query=urlencode([*query, ("download", "1")])))
    if kind == "dropbox":
        return urlunsplit(parts._replace(query=urlencode([(k, v) for k, v in query if k != "dl"] + [("dl", "1")])))
    return url


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
