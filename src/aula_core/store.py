"""Local SQLite store: the last known state of the aula virtual plus derived data.

Tables:
  meta           key/value (last sync time, initialized flag, which course
                 resources already have their silent first read, and which
                 ones are failing and whether that was already reported)
  courses, assignments, announcements, files
                 the latest snapshot read from Canvas. `files` is the material catalog: every
                 document of a course wherever the aula shows it (Files, Modules, Pages, the
                 «Programa del curso», announcements, assignments), downloaded or not, plus
                 material that never came from Canvas (negative ids: a public link fetched,
                 a PDF the student handed over). An announcement keeps the files and links it
                 points to (`material`)
  links          external links of each course (Google Docs, SharePoint, a professor's page, videos),
                 with what opening one anonymously gave (its file, or why it did not open)
  pages          the course Pages already read, with the files and links they point to
  unreachable    files linked somewhere that this student cannot open (retried weekly)
  bibliography   the main and complementary books parsed from each syllabus
  events         changes detected by a sync (new assignment, grade posted, ...);
                 consumers such as the bot mark them delivered
  marked_submitted
                 assignments the student says were handed in outside Canvas (on paper, by email, in
                 the lab): counted as submitted everywhere, since Canvas never learns about them
  chunks         full-text index (FTS5) of downloaded course material, one row per page
  ocr_pages      the PDF pages that are only an image, by the SHA-256 of their file (`files.digest`), with
                 the text OCR read from them; NULL text: not read yet. Keyed by content, so a copy of
                 a file or the same file downloaded again is never read twice
"""

from __future__ import annotations

import fcntl
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    course_code TEXT,
    term TEXT,
    html_url TEXT,
    current_score REAL,
    current_grade TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    term_start TEXT
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    due_at TEXT,
    lock_at TEXT,
    html_url TEXT,
    points_possible REAL,
    submission_types TEXT,
    sub_state TEXT,
    submitted_at TEXT,
    score REAL,
    grade TEXT,
    graded_at TEXT,
    excused INTEGER NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0,
    late INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assignments_due ON assignments(due_at);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    message_text TEXT,
    author TEXT,
    posted_at TEXT,
    html_url TEXT,
    first_seen TEXT NOT NULL,
    material TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    filename TEXT,
    content_type TEXT,
    size INTEGER,
    updated_at TEXT,
    html_url TEXT,
    module TEXT,
    local_path TEXT,
    downloaded_version TEXT,
    index_status TEXT,
    pages INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    folder TEXT,
    section TEXT,
    source TEXT,
    created_at TEXT,
    language TEXT,
    duplicate_of INTEGER,
    download_url TEXT,
    digest TEXT
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    kind TEXT NOT NULL,
    access TEXT NOT NULL,
    source TEXT,
    module TEXT,
    section TEXT,
    file_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    checked_at TEXT,
    problem TEXT,
    UNIQUE (course_id, url)
);

CREATE TABLE IF NOT EXISTS pages (
    course_id INTEGER NOT NULL,
    slug TEXT NOT NULL,
    title TEXT,
    updated_at TEXT,
    refs TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT,
    PRIMARY KEY (course_id, slug)
);

CREATE TABLE IF NOT EXISTS unreachable (
    course_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (course_id, file_id)
);

CREATE TABLE IF NOT EXISTS bibliography (
    file_id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL,
    main TEXT NOT NULL DEFAULT '[]',
    others TEXT NOT NULL DEFAULT '[]',
    parsed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    course_id INTEGER,
    ref_id INTEGER,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS marked_submitted (
    assignment_id INTEGER PRIMARY KEY,
    marked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ocr_pages (
    digest TEXT NOT NULL,
    page INTEGER NOT NULL,
    text TEXT,
    confidence REAL,
    read_at TEXT,
    PRIMARY KEY (digest, page)
);
CREATE INDEX IF NOT EXISTS ocr_pages_pending ON ocr_pages(digest) WHERE text IS NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    text,
    file_id UNINDEXED,
    course_id UNINDEXED,
    page UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


# Columns added after a table first shipped: CREATE TABLE IF NOT EXISTS leaves an existing table as it was.
ADDED_COLUMNS = {
    "courses": ["term_start TEXT"],
    "announcements": ["material TEXT"],
    "links": ["checked_at TEXT", "problem TEXT"],
    "files": ["folder TEXT", "section TEXT", "source TEXT", "created_at TEXT", "language TEXT",
              "duplicate_of INTEGER", "download_url TEXT", "digest TEXT"],
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for column in columns:
            if column.split()[0] not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
    conn.commit()
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def delete_meta(conn: sqlite3.Connection, *keys: str) -> None:
    conn.execute(f"DELETE FROM meta WHERE key IN ({','.join('?' * len(keys))})", keys)


def set_marked_submitted(conn: sqlite3.Connection, assignment_id: int, marked: bool, now: str) -> bool:
    """Record (or undo) that the student handed an assignment in outside Canvas; False when nothing changed."""
    if marked:
        cur = conn.execute("INSERT OR IGNORE INTO marked_submitted(assignment_id, marked_at) VALUES (?, ?)",
                           (assignment_id, now))
    else:
        cur = conn.execute("DELETE FROM marked_submitted WHERE assignment_id = ?", (assignment_id,))
    conn.commit()
    return cur.rowcount == 1


@contextmanager
def file_lock(data_dir: Path, name: str, *, wait: bool = True) -> Iterator[bool]:
    """Yields whether it holds the lock: with `wait` off it yields False at once while another process has it."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / name).open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def sync_lock(data_dir: Path, *, wait: bool = True):
    """One sync at a time, whether it comes from the bot or from `aula`."""
    return file_lock(data_dir, "sync.lock", wait=wait)


def material_lock(data_dir: Path):
    """One material download at a time. Apart from sync_lock: a first download can take many minutes,
    and a quick sync (a bot's refresh, setup.sh) must not wait for it."""
    return file_lock(data_dir, "material.lock")
