"""Token-free Canvas iCal and announcement feeds as a continuity floor.

Feed URLs contain unguessable credentials, so this module reads them only from
``secrets.env``, never logs them, and only contacts the configured Canvas host.
The resulting assignments, calendar events and announcements go into the same
SQLite tables used by normal API syncs.
"""

from __future__ import annotations

import hashlib
import html
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from aula_core import timefmt
from aula_core.catalog import html_to_text
from aula_core.config import CoreConfig, load_secret_values, update_secret_values
from aula_core.store import get_meta, set_meta

CALENDAR_KEY = "CANVAS_CALENDAR_FEED_URL"
ANNOUNCEMENTS_KEY = "CANVAS_ANNOUNCEMENT_FEED_URLS"
MAX_FEED_BYTES = 5 * 1024 * 1024
TIMEOUT = (10, 30)


class FeedError(Exception):
    pass


@dataclass
class FeedReport:
    events: int = 0
    errors: list[str] = field(default_factory=list)


def announcements_key(secret_url: str) -> str:
    """meta key holding when this announcement feed was last read; keyed by a hash, never the URL."""
    return "feeds_announcements_seeded_" + hashlib.sha256(secret_url.encode()).hexdigest()[:16]


def configured() -> bool:
    values = load_secret_values()
    return bool(values.get(CALENDAR_KEY) or values.get(ANNOUNCEMENTS_KEY))


def configure(calendar_url: str, announcement_urls: list[str], cfg: CoreConfig) -> None:
    urls = [calendar_url, *announcement_urls]
    for url in urls:
        if url:
            _safe_url(url, cfg)
    values = {CALENDAR_KEY: calendar_url.strip(),
              ANNOUNCEMENTS_KEY: " ".join(url.strip() for url in announcement_urls if url.strip())}
    update_secret_values(values)


def sync(conn: sqlite3.Connection, cfg: CoreConfig, now: datetime) -> FeedReport:
    values = load_secret_values()
    report = FeedReport()
    calendar = values.get(CALENDAR_KEY, "").strip()
    announcements = values.get(ANNOUNCEMENTS_KEY, "").split()
    if calendar:
        try:
            report.events += _calendar(conn, cfg, now, _fetch(calendar, cfg))
        except FeedError as exc:
            report.errors.append(f"calendario: {exc}")
    for url in announcements:
        try:
            report.events += _announcements(conn, cfg, now, _fetch(url, cfg), url)
        except FeedError as exc:
            report.errors.append(f"anuncios: {exc}")
    conn.commit()
    return report


def _fetch(url: str, cfg: CoreConfig) -> str:
    _safe_url(url, cfg)
    try:
        response = requests.get(url, headers={"User-Agent": "espol-academic-bot/0.1"}, timeout=TIMEOUT,
                                allow_redirects=False)
    except requests.RequestException as exc:
        raise FeedError(f"no responde ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise FeedError(f"respondió {response.status_code}")
    if len(response.content) > MAX_FEED_BYTES:
        raise FeedError("es demasiado grande")
    return response.text


def _safe_url(url: str, cfg: CoreConfig) -> None:
    parsed, canvas = urlsplit(url), urlsplit(cfg.canvas_url)
    if parsed.scheme not in ("http", "https") or parsed.netloc != canvas.netloc:
        raise FeedError("la dirección no pertenece al aula configurada")


def _calendar(conn: sqlite3.Connection, cfg: CoreConfig, now: datetime, text: str) -> int:
    seeded = get_meta(conn, "feeds_calendar_seeded") is not None
    emitted = 0
    for event in _ical_events(text, cfg):
        course_id = _course_id(event.get("URL", ""))
        if course_id is None or not _known_course(conn, course_id):
            continue
        url = event.get("URL") or f"{cfg.canvas_url}/courses/{course_id}"
        assignment_id = _assignment_id(url)
        item_id = assignment_id if assignment_id is not None else _negative_id(event.get("UID") or url)
        name = event.get("SUMMARY") or "Evento del aula"
        due_at = event.get("DTSTART")
        if not due_at:
            continue
        previous = conn.execute("SELECT * FROM assignments WHERE id = ?", (item_id,)).fetchone()
        if previous is None:
            conn.execute(
                """INSERT INTO assignments(id, course_id, name, due_at, lock_at, html_url, points_possible,
                     submission_types, sub_state, submitted_at, score, grade, graded_at, excused, missing, late,
                     active, first_seen)
                   VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, NULL, NULL, NULL, NULL, NULL, 0, 0, 0, 1, ?)""",
                (item_id, course_id, name, due_at, url, "none" if assignment_id is None else "", timefmt.iso(now)),
            )
            if seeded:
                _event(conn, now, "new_assignment", course_id, item_id,
                       {"tarea": name, "url": url, "due_at": due_at})
                emitted += 1
        else:
            if previous["due_at"] != due_at:
                _event(conn, now, "due_changed", course_id, item_id,
                       {"tarea": name, "url": url, "due_at": due_at,
                        "due_at_anterior": previous["due_at"]})
                emitted += 1
            conn.execute("UPDATE assignments SET course_id = ?, name = ?, due_at = ?, html_url = ?, active = 1 "
                         "WHERE id = ?", (course_id, name, due_at, url, item_id))
    set_meta(conn, "feeds_calendar_seeded", timefmt.iso(now))
    return emitted


def _announcements(conn: sqlite3.Connection, cfg: CoreConfig, now: datetime, text: str, secret_url: str) -> int:
    key = announcements_key(secret_url)
    seeded = get_meta(conn, key) is not None
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FeedError("no es Atom/RSS válido") from exc
    emitted = 0
    entries = root.findall("{*}entry") or root.findall(".//item")
    for entry in entries:
        link_node = entry.find("{*}link")
        url = (link_node.get("href") if link_node is not None else None) or _xml_text(entry, "link")
        course_id = _course_id(url)
        if course_id is None or not _known_course(conn, course_id):
            continue
        topic_id = _topic_id(url) or abs(_negative_id(_xml_text(entry, "id") or url))
        if conn.execute("SELECT 1 FROM announcements WHERE id = ?", (topic_id,)).fetchone():
            continue
        title = _xml_text(entry, "title") or "Anuncio del aula"
        author_node = entry.find("{*}author")
        author = _xml_text(author_node, "name") if author_node is not None else None
        posted = _xml_text(entry, "published") or _xml_text(entry, "updated")
        body = _xml_text(entry, "content") or _xml_text(entry, "summary") or _xml_text(entry, "description")
        row = (topic_id, course_id, title, html_to_text(html.unescape(body)), author,
               timefmt.normalize(posted), url, timefmt.iso(now))
        conn.execute("""INSERT INTO announcements(id, course_id, title, message_text, author, posted_at, html_url,
                        first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", row)
        course_had_news = conn.execute(
            "SELECT COUNT(*) FROM announcements WHERE course_id = ? AND id != ?", (course_id, topic_id)
        ).fetchone()[0] > 0
        if seeded or course_had_news:
            _event(conn, now, "new_announcement", course_id, topic_id,
                   {"titulo": title, "autor": author, "texto": row[3][:600], "url": url})
            emitted += 1
    set_meta(conn, key, timefmt.iso(now))
    return emitted


def _ical_events(text: str, cfg: CoreConfig) -> list[dict[str, str]]:
    unfolded: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in unfolded:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT" and current is not None:
            events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        key = raw_key.split(";", 1)[0]
        value = value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
        current[key] = _ical_time(value, cfg) if key in ("DTSTART", "DTEND") else value
    return events


def _ical_time(value: str, cfg: CoreConfig) -> str:
    for pattern, zone in (("%Y%m%dT%H%M%SZ", timezone.utc), ("%Y%m%dT%H%M%S", cfg.tz),
                          ("%Y%m%d", cfg.tz)):
        try:
            return timefmt.iso(datetime.strptime(value, pattern).replace(tzinfo=zone))
        except ValueError:
            pass
    return timefmt.normalize(value) or ""


def _xml_text(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    child = node.find(f"{{*}}{name}")
    return "" if child is None else "".join(child.itertext()).strip()


def _course_id(url: str) -> int | None:
    match = re.search(r"/courses/(\d+)(?:/|$)", url)
    return int(match[1]) if match else None


def _assignment_id(url: str) -> int | None:
    match = re.search(r"/assignments/(\d+)(?:[/?#]|$)", url)
    return int(match[1]) if match else None


def _topic_id(url: str) -> int | None:
    match = re.search(r"/discussion_topics/(\d+)(?:[/?#]|$)", url)
    return int(match[1]) if match else None


def _negative_id(seed: str) -> int:
    return -int(hashlib.sha256(seed.encode()).hexdigest()[:15], 16)


def _known_course(conn: sqlite3.Connection, course_id: int) -> bool:
    return conn.execute("SELECT 1 FROM courses WHERE id = ? AND active = 1", (course_id,)).fetchone() is not None


def _event(conn: sqlite3.Connection, now: datetime, kind: str, course_id: int, ref_id: int, payload: dict) -> None:
    import json
    course = conn.execute("SELECT name FROM courses WHERE id = ?", (course_id,)).fetchone()
    payload = {"curso": course["name"] if course else "Aula virtual", "curso_id": course_id, **payload}
    conn.execute("INSERT INTO events(kind, course_id, ref_id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                 (kind, course_id, ref_id, json.dumps(payload, ensure_ascii=False), timefmt.iso(now)))
