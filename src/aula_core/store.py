"""Local SQLite store: the last known state of the aula virtual plus derived data.

Tables:
  meta           key/value (last sync time, initialized flag, which course
                 resources already have their silent first read, and which
                 ones are failing and whether that was already reported)
  courses, assignments, announcements, files
                 the latest snapshot read from Canvas
  events         changes detected by a sync (new assignment, grade posted, ...);
                 consumers such as the bot mark them delivered
  chunks         full-text index (FTS5) of downloaded course material, one row per page
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
    first_seen TEXT NOT NULL
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
    first_seen TEXT NOT NULL
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
    first_seen TEXT NOT NULL
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

CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    text,
    file_id UNINDEXED,
    course_id UNINDEXED,
    page UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
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


@contextmanager
def file_lock(data_dir: Path, name: str) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / name).open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def sync_lock(data_dir: Path):
    """One sync at a time, whether it comes from the bot or from `aula`."""
    return file_lock(data_dir, "sync.lock")


def material_lock(data_dir: Path):
    """One material download at a time. Apart from sync_lock: a first download can take many minutes,
    and a quick sync (a bot's refresh, setup.sh) must not wait for it."""
    return file_lock(data_dir, "material.lock")
