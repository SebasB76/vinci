"""Citations a bot can back up.

Every page of the material a tool shows a bot (a search hit, a page read, a page seen as an image) is
recorded per bot, and the tool hands the model that page's citation ready to copy: file, page or slide,
and its link in the aula. Before an answer reaches the captain, the vinci-botones plugin runs
`espol-bot citas` on it (`check`): a citation of a page this bot was never shown, or of a file that is
not in its material, becomes a warning, and one that lost its link or carries a wrong one gets the
file's own. Only citations shaped like the ones the tools hand out are checked: «📄 <file>, página N»,
with or without its link.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from urllib.parse import unquote, urldefrag

from aula_core import timefmt
from aula_core.catalog import normalized_name

VINCI = "vinci"  # Vinci's pages; a subject bot's go under its code
PLURAL = {"página": "páginas", "diapositiva": "diapositivas", "sección": "secciones"}
MAX_RANGE = 60  # a longer range cites a whole book, not a page
_LOCATOR = (r"(?:p[áa]ginas?|diapositivas?|secci(?:[óo]n|ones)|hojas?|p[áa]gs?\.|pp?\.|diap\.)\s*"
            r"(?P<first>\d+)(?:\s*(?:-|–|a|al)\s*(?P<last>\d+))?(?!\d)")
LINKED = re.compile(r"(?:📄\s*)?\[(?P<label>(?P<name>[^\[\]\n]+?),\s*" + _LOCATOR + r")\]\((?P<url>[^()\s]+)\)",
                    re.I)
PLAIN = re.compile(r"📄\s*(?P<label>(?P<name>[^\[\]\n📄]+?),\s*" + _LOCATOR + r")", re.I)


def _url(url: str) -> str:
    """A link Telegram's Markdown keeps whole: no spaces or parentheses."""
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _same_url(a: str | None, b: str | None) -> bool:
    return bool(a and b) and unquote(urldefrag(a)[0]).rstrip("/") == unquote(urldefrag(b)[0]).rstrip("/")


def cite(name: str, unit: str, first: int, last: int | None = None, url: str | None = None) -> str:
    """The citation of a page (or a range) of a file, as the model should write it."""
    where = f"{unit} {first}" if last in (None, first) else f"{PLURAL.get(unit, unit + 's')} {first}-{last}"
    label = f"{name.replace('[', '(').replace(']', ')')}, {where}"
    return f"📄 [{label}]({_url(url)})" if url else f"📄 {label}"


def record(conn: sqlite3.Connection, bot: str, file_id: int, pages, now: datetime) -> None:
    rows = [(bot, file_id, int(page), timefmt.iso(now)) for page in dict.fromkeys(pages)]
    if rows:
        conn.executemany("INSERT INTO shown_pages(bot, file_id, page, shown_at) VALUES (?, ?, ?, ?)"
                         " ON CONFLICT(bot, file_id, page) DO UPDATE SET shown_at = excluded.shown_at", rows)
        conn.commit()


def _candidates(conn: sqlite3.Connection, course_ids: list[int] | None, name: str, url: str | None) -> list:
    extra, params = "", []
    if course_ids is not None:
        extra = f" AND course_id IN ({','.join('?' * len(course_ids)) or 'NULL'})"
        params = list(course_ids)
    rows = conn.execute(f"SELECT id, display_name, html_url FROM files WHERE 1 = 1{extra} ORDER BY active DESC, id DESC",
                        params).fetchall()
    by_url = [r for r in rows if url and _same_url(r["html_url"], url)]
    key = normalized_name(name)
    return by_url or [r for r in rows if key and normalized_name(r["display_name"]) == key]


def _shown(conn: sqlite3.Connection, bot: str, file_id: int, first: int, last: int) -> bool:
    if last < first or last - first >= MAX_RANGE:
        return False
    seen = conn.execute("SELECT COUNT(*) FROM shown_pages WHERE bot = ? AND file_id = ? AND page BETWEEN ? AND ?",
                        (bot, file_id, first, last)).fetchone()[0]
    return seen == last - first + 1


def _verdict(conn, bot: str, course_ids, match: re.Match) -> tuple[str, str | None]:
    """(what the citation becomes, why it changed or None)."""
    label, url = match["label"].strip(), match.groupdict().get("url")
    first = int(match["first"])
    last = int(match["last"]) if match["last"] else first
    files = _candidates(conn, course_ids, match["name"].strip(), url)
    if not files:
        return f"⚠️ «{label}» (ese archivo no está en el material: no lo tomes como fuente)", "archivo desconocido"
    shown = next((f for f in files if _shown(conn, bot, f["id"], first, last)), None)
    if shown is None:
        return f"⚠️ «{label}» (esa página no salió del material que leí: no la tomes como fuente)", "página no leída"
    right = shown["html_url"]
    if url and _same_url(url, right) or not url and not right:
        return match[0], None
    return (f"📄 [{label}]({_url(right)})" if right else f"📄 {label}"), "enlace corregido" if url else "enlace agregado"


def check(conn: sqlite3.Connection, bot: str, course_ids: list[int] | None, text: str) -> tuple[str, list[dict]]:
    """The answer with each citation checked against the pages `bot` was shown in `course_ids` (None: every
    course), and what changed."""
    matches = list(LINKED.finditer(text))
    taken = [m.span() for m in matches]
    matches += [m for m in PLAIN.finditer(text) if not any(a < m.end() and m.start() < b for a, b in taken)]
    out, changes, at = [], [], 0
    for match in sorted(matches, key=lambda m: m.start()):
        new, why = _verdict(conn, bot, course_ids, match)
        out += [text[at:match.start()], new]
        at = match.end()
        if why:
            changes.append({"cita": match["label"].strip(), "cambio": why})
    out.append(text[at:])
    return "".join(out), changes
