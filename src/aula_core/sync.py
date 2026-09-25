"""Reads the aula virtual into the local store and records what changed.

A sync reads, per active course: assignments with the student's submission,
announcements, and files (from the Files listing and from Modules). It compares
each item against the previous snapshot and appends an `events` row for:

  new_course, new_assignment, due_changed, new_announcement,
  grade_posted, grade_changed, new_file, file_updated

The very first sync (and the first time a course shows up) only seeds the store,
so the student is not flooded with every historical item. Events are consumed
by whoever needs them (the Telegram bot); the CLI can sync without losing them.
"""

from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aula_core import timefmt
from aula_core.canvas import CanvasClient, CanvasError, InvalidTokenError
from aula_core.config import CoreConfig
from aula_core.store import get_meta, set_meta

log = logging.getLogger(__name__)


@dataclass
class SyncReport:
    first_sync: bool
    courses: int = 0
    events: int = 0
    warnings: list[str] = field(default_factory=list)
    requests: int = 0


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", value)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _record(conn, now_iso: str, kind: str, course_id: int, ref_id: int, payload: dict) -> None:
    conn.execute(
        "INSERT INTO events(kind, course_id, ref_id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (kind, course_id, ref_id, json.dumps(payload, ensure_ascii=False), now_iso),
    )


class _Syncer:
    def __init__(self, conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig, now: datetime):
        self.conn = conn
        self.client = client
        self.cfg = cfg
        self.now_iso = timefmt.iso(now)
        self.events = 0
        self.warnings: list[str] = []

    def emit(self, quiet: bool, kind: str, course: dict, ref_id: int, payload: dict) -> None:
        if quiet:
            return
        payload = {"curso": course["name"], "curso_id": course["id"], **payload}
        _record(self.conn, self.now_iso, kind, course["id"], ref_id, payload)
        self.events += 1

    # -- courses ----------------------------------------------------------------------

    def courses(self) -> list[dict]:
        raw = self.client.get_all(
            "courses",
            {"enrollment_state": "active", "include[]": ["term", "total_scores"]},
        )
        courses = []
        for c in raw:
            if not c.get("name") or c.get("access_restricted_by_date"):
                continue
            enrollment = next((e for e in c.get("enrollments") or [] if e.get("type") in ("student", "StudentEnrollment")), {})
            courses.append({
                "id": c["id"],
                "name": c["name"],
                "course_code": c.get("course_code"),
                "term": (c.get("term") or {}).get("name"),
                "html_url": f"{self.cfg.canvas_url}/courses/{c['id']}",
                "current_score": enrollment.get("computed_current_score"),
                "current_grade": enrollment.get("computed_current_grade"),
            })
        return courses

    def upsert_course(self, c: dict) -> bool:
        """Returns True when the course was already known."""
        known = self.conn.execute("SELECT 1 FROM courses WHERE id = ?", (c["id"],)).fetchone() is not None
        self.conn.execute(
            """INSERT INTO courses(id, name, course_code, term, html_url, current_score, current_grade, active, first_seen)
               VALUES (:id, :name, :course_code, :term, :html_url, :current_score, :current_grade, 1, :now)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, course_code=excluded.course_code, term=excluded.term,
                 html_url=excluded.html_url, current_score=excluded.current_score,
                 current_grade=excluded.current_grade, active=1""",
            {**c, "now": self.now_iso},
        )
        return known

    # -- assignments ------------------------------------------------------------------

    def assignments(self, course: dict, quiet: bool) -> None:
        raw = self.client.get_all(
            f"courses/{course['id']}/assignments",
            {"include[]": ["submission"], "order_by": "due_date"},
        )
        seen = []
        for a in raw:
            if a.get("published") is False:
                continue
            sub = a.get("submission") or {}
            row = {
                "id": a["id"],
                "course_id": course["id"],
                "name": a.get("name") or "(sin nombre)",
                "due_at": timefmt.normalize(a.get("due_at")),
                "lock_at": timefmt.normalize(a.get("lock_at")),
                "html_url": a.get("html_url") or f"{self.cfg.canvas_url}/courses/{course['id']}/assignments/{a['id']}",
                "points_possible": a.get("points_possible"),
                "submission_types": ",".join(a.get("submission_types") or []),
                "sub_state": sub.get("workflow_state"),
                "submitted_at": timefmt.normalize(sub.get("submitted_at")),
                "score": sub.get("score"),
                "grade": sub.get("grade"),
                "graded_at": timefmt.normalize(sub.get("graded_at")),
                "excused": int(bool(sub.get("excused"))),
                "missing": int(bool(sub.get("missing"))),
                "late": int(bool(sub.get("late"))),
            }
            seen.append(row["id"])
            prev = self.conn.execute("SELECT * FROM assignments WHERE id = ?", (row["id"],)).fetchone()
            info = {"tarea": row["name"], "url": row["html_url"], "due_at": row["due_at"],
                    "puntos": row["points_possible"]}
            if prev is None or not prev["active"]:
                if prev is None:
                    self.emit(quiet, "new_assignment", course, row["id"], info)
            else:
                if prev["due_at"] != row["due_at"]:
                    self.emit(quiet, "due_changed", course, row["id"], {**info, "due_at_anterior": prev["due_at"]})
                had_grade = prev["score"] is not None or prev["grade"] is not None
                has_grade = row["score"] is not None or row["grade"] is not None
                grade_info = {**info, "nota": row["score"], "calificacion": row["grade"]}
                if has_grade and not had_grade and not row["excused"]:
                    self.emit(quiet, "grade_posted", course, row["id"], grade_info)
                elif has_grade and had_grade and (prev["score"], prev["grade"]) != (row["score"], row["grade"]):
                    self.emit(quiet, "grade_changed", course, row["id"],
                              {**grade_info, "nota_anterior": prev["score"], "calificacion_anterior": prev["grade"]})
            self.conn.execute(
                """INSERT INTO assignments(id, course_id, name, due_at, lock_at, html_url, points_possible, submission_types,
                     sub_state, submitted_at, score, grade, graded_at, excused, missing, late, active, first_seen)
                   VALUES (:id, :course_id, :name, :due_at, :lock_at, :html_url, :points_possible, :submission_types,
                     :sub_state, :submitted_at, :score, :grade, :graded_at, :excused, :missing, :late, 1, :now)
                   ON CONFLICT(id) DO UPDATE SET course_id=excluded.course_id, name=excluded.name, due_at=excluded.due_at,
                     lock_at=excluded.lock_at, html_url=excluded.html_url, points_possible=excluded.points_possible,
                     submission_types=excluded.submission_types, sub_state=excluded.sub_state,
                     submitted_at=excluded.submitted_at, score=excluded.score, grade=excluded.grade,
                     graded_at=excluded.graded_at, excused=excluded.excused, missing=excluded.missing,
                     late=excluded.late, active=1""",
                {**row, "now": self.now_iso},
            )
        self._deactivate("assignments", course["id"], seen)

    # -- announcements ----------------------------------------------------------------

    def announcements(self, course: dict, quiet: bool) -> None:
        # Newest first; one page of 50 is plenty between two polls.
        raw = self.client.get(
            f"courses/{course['id']}/discussion_topics",
            {"only_announcements": "true", "per_page": 50},
        )
        for t in raw if isinstance(raw, list) else []:
            if self.conn.execute("SELECT 1 FROM announcements WHERE id = ?", (t["id"],)).fetchone():
                continue
            author = (t.get("author") or {}).get("display_name") or t.get("user_name")
            row = {
                "id": t["id"],
                "course_id": course["id"],
                "title": t.get("title") or "(sin título)",
                "message_text": html_to_text(t.get("message")),
                "author": author,
                "posted_at": timefmt.normalize(t.get("posted_at")),
                "html_url": t.get("html_url") or f"{self.cfg.canvas_url}/courses/{course['id']}/discussion_topics/{t['id']}",
            }
            self.conn.execute(
                """INSERT INTO announcements(id, course_id, title, message_text, author, posted_at, html_url, first_seen)
                   VALUES (:id, :course_id, :title, :message_text, :author, :posted_at, :html_url, :now)""",
                {**row, "now": self.now_iso},
            )
            self.emit(quiet, "new_announcement", course, row["id"], {
                "titulo": row["title"], "autor": author, "texto": row["message_text"][:600], "url": row["html_url"],
            })

    # -- files --------------------------------------------------------------------------

    def files(self, course: dict, quiet: bool) -> None:
        cid = course["id"]
        found: dict[int, dict] = {}
        listing_ok = True
        try:
            for f in self.client.iter_pages(f"courses/{cid}/files", {"sort": "updated_at", "order": "desc"}):
                found[f["id"]] = {"file": f, "module": None}
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            # Many courses hide the Files tab from students; Modules still link the files.
            if exc.status not in (401, 403, 404):
                raise
            listing_ok = False

        modules_ok = True
        try:
            for module in self.client.iter_pages(f"courses/{cid}/modules", {"include[]": ["items"]}):
                items = module.get("items")
                if items is None and module.get("items_url"):
                    items = self.client.get_all(module["items_url"])
                for item in items or []:
                    if item.get("type") != "File" or not item.get("content_id"):
                        continue
                    fid = item["content_id"]
                    if fid not in found:
                        try:
                            found[fid] = {"file": self.client.get(f"courses/{cid}/files/{fid}"), "module": None}
                        except InvalidTokenError:
                            raise
                        except CanvasError as exc:
                            if exc.status not in (401, 403, 404):
                                raise
                            continue
                    found[fid]["module"] = found[fid]["module"] or module.get("name")
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            if exc.status not in (401, 403, 404):
                raise
            modules_ok = False

        for fid, entry in found.items():
            f = entry["file"]
            if f.get("locked_for_user") or f.get("hidden_for_user"):
                continue
            row = {
                "id": fid,
                "course_id": cid,
                "display_name": f.get("display_name") or f.get("filename") or f"archivo-{fid}",
                "filename": f.get("filename"),
                "content_type": f.get("content-type") or f.get("content_type"),
                "size": f.get("size"),
                "updated_at": timefmt.normalize(f.get("updated_at") or f.get("modified_at")),
                "html_url": f"{self.cfg.canvas_url}/courses/{cid}/files/{fid}",
                "module": entry["module"],
            }
            prev = self.conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
            info = {"archivo": row["display_name"], "modulo": row["module"], "url": row["html_url"]}
            if prev is None:
                self.emit(quiet, "new_file", course, fid, info)
            elif prev["updated_at"] != row["updated_at"]:
                self.emit(quiet, "file_updated", course, fid, info)
            self.conn.execute(
                """INSERT INTO files(id, course_id, display_name, filename, content_type, size, updated_at, html_url,
                     module, active, first_seen)
                   VALUES (:id, :course_id, :display_name, :filename, :content_type, :size, :updated_at, :html_url,
                     :module, 1, :now)
                   ON CONFLICT(id) DO UPDATE SET course_id=excluded.course_id, display_name=excluded.display_name,
                     filename=excluded.filename, content_type=excluded.content_type, size=excluded.size,
                     updated_at=excluded.updated_at, html_url=excluded.html_url,
                     module=COALESCE(excluded.module, files.module), active=1""",
                {**row, "now": self.now_iso},
            )
        if listing_ok and modules_ok:
            self._deactivate("files", cid, list(found))
        if not listing_ok and not modules_ok:
            self.warnings.append(f"{course['name']}: no tengo acceso a Archivos ni a Módulos")

    def _deactivate(self, table: str, course_id: int, seen: list[int]) -> None:
        marks = ",".join("?" * len(seen)) or "NULL"
        self.conn.execute(
            f"UPDATE {table} SET active = 0 WHERE course_id = ? AND id NOT IN ({marks})",
            (course_id, *seen),
        )


def sync(conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig, now: datetime) -> SyncReport:
    """Read everything once and record changes. Caller holds `store.sync_lock`."""
    first = get_meta(conn, "initialized") is None
    report = SyncReport(first_sync=first)
    s = _Syncer(conn, client, cfg, now)
    courses = s.courses()
    report.courses = len(courses)
    ids = [c["id"] for c in courses]
    conn.execute(
        f"UPDATE courses SET active = 0 WHERE id NOT IN ({','.join('?' * len(ids)) or 'NULL'})", ids
    )
    conn.commit()
    seeded = True
    for course in courses:
        known = s.upsert_course(course)
        for step in (s.assignments, s.announcements, s.files):
            try:
                step(course, not known)
            except InvalidTokenError:
                conn.rollback()
                raise
            except CanvasError as exc:
                s.warnings.append(f"{course['name']}: {exc}")
                log.warning("%s: %s", course["name"], exc)
                if not known and exc.status not in (401, 403, 404):
                    conn.rollback()
                    seeded = False
                    break
        else:
            if not first and not known:
                s.emit(False, "new_course", course, course["id"],
                       {"codigo": course["course_code"], "url": course["html_url"]})
        conn.commit()
    if seeded:
        set_meta(conn, "initialized", "1")
    set_meta(conn, "last_sync", s.now_iso)
    conn.commit()
    report.events = s.events
    report.warnings = s.warnings
    report.requests = client.requests_made
    return report


def last_sync(conn: sqlite3.Connection) -> datetime | None:
    return timefmt.parse(get_meta(conn, "last_sync"))


def pending_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM events WHERE delivered_at IS NULL ORDER BY id").fetchall()
    return [{"id": r["id"], "kind": r["kind"], "course_id": r["course_id"], "ref_id": r["ref_id"],
             "created_at": r["created_at"], **json.loads(r["payload"])} for r in rows]


def mark_delivered(conn: sqlite3.Connection, event_ids: list[int], now: datetime) -> None:
    conn.executemany("UPDATE events SET delivered_at = ? WHERE id = ?", [(timefmt.iso(now), i) for i in event_ids])
    conn.commit()
