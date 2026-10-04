"""Reads the aula virtual into the local store and records what changed.

A sync reads, per active course: assignments with the student's submission (and, for a Classic
Quiz, its settings: one more read when its assignment changed), announcements, and the material catalog. It compares each item against the previous
snapshot and appends an `events` row for:

  new_course, new_assignment, due_changed, new_announcement,
  grade_posted, grade_changed, new_file, file_updated, new_link

The catalog is every document the aula shows, downloaded or not: the Files listing (with its
folders), Modules (with the subheaders that split a week, «ANTES de clase…», and their outside
links), and what Pages, the «Programa del curso», announcements (and their attachments) and
assignments link to. Only metadata is read here; aula_core.materials downloads. What the catalog
finds only by following a link (a linked file's metadata, a Page's body) costs extra reads, so
background work gets a `budget` of them per sync and the rest waits for the next one; a course's
first catalog read stays silent until it is complete, like every first read.

The first successful read of each course resource (assignments, announcements,
files) only seeds the store, so the student is not flooded with every historical
item. A resource that fails is left as it was and read again on the next sync,
without holding back the others; `SyncReport.failed` lists it with how many reads
in a row have failed, and `mark_reported` flags it until it reads fine again.
Events are consumed by whoever needs them (the Telegram bot); the CLI can sync
without losing them.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from aula_core import timefmt
from aula_core.canvas import (
    CanvasClient,
    CanvasError,
    InvalidTokenError,
    ThrottledError,
)
from aula_core.catalog import Refs, classify, clean_title, html_to_text, mark_duplicates, refs, term_year
from aula_core.config import CoreConfig
from aula_core.queries import quiz_info
from aula_core.store import delete_meta, get_meta, set_meta

log = logging.getLogger(__name__)

# An assignment that asks for its handwritten pages scanned or photographed (a professor's own words).
ASKS_SCAN = re.compile(r"escane|scann|a mano|manuscrit|fotograf", re.IGNORECASE)

HIDDEN = (401, 403, 404)  # a tab or a file this student cannot see: not a failure
PAGE_REFRESH = timedelta(days=1)  # a Page read through a link, when the course hides its Pages list
UNREACHABLE_RETRY = timedelta(days=7)


@dataclass
class FailedResource:
    course_id: int
    resource: str
    what: str
    reads: int
    reported: bool


@dataclass
class SyncReport:
    first_sync: bool
    courses: int = 0
    events: int = 0
    warnings: list[str] = field(default_factory=list)
    failed: list[FailedResource] = field(default_factory=list)
    requests: int = 0


def _resource_key(kind: str, course_id: int, resource: str) -> str:
    return f"{kind}:{course_id}:{resource}"


def _record(conn, now_iso: str, kind: str, course_id: int, ref_id: int, payload: dict) -> None:
    conn.execute(
        "INSERT INTO events(kind, course_id, ref_id, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (kind, course_id, ref_id, json.dumps(payload, ensure_ascii=False), now_iso),
    )


class _Syncer:
    def __init__(self, conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig, now: datetime,
                 budget: int | None = None):
        self.conn = conn
        self.client = client
        self.cfg = cfg
        self.now = now
        self.now_iso = timefmt.iso(now)
        self.budget = budget
        self.events = 0
        self.warnings: list[str] = []
        self.failed: list[FailedResource] = []
        self.bodies: dict[int, list[tuple[str, str | None, list]]] = {}  # course: (where, html, attachments)
        self.read: dict[int, set[str]] = {}

    def spend(self) -> bool:
        """One more read for what only a link leads to; False once this sync's budget is used up."""
        if self.budget is None:
            return True
        self.budget -= 1
        return self.budget >= 0

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
            {"enrollment_state": "active", "include[]": ["term", "total_scores", "syllabus_body"]},
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
                "term_start": timefmt.normalize((c.get("term") or {}).get("start_at")),
                "term_end": timefmt.normalize((c.get("term") or {}).get("end_at")),
                "syllabus_body": c.get("syllabus_body"),
            })
        return courses

    def upsert_course(self, c: dict) -> bool:
        """Returns True when the course was already known."""
        known = self.conn.execute("SELECT 1 FROM courses WHERE id = ?", (c["id"],)).fetchone() is not None
        self.conn.execute(
            """INSERT INTO courses(id, name, course_code, term, html_url, current_score, current_grade, active, first_seen,
                 term_start, term_end)
               VALUES (:id, :name, :course_code, :term, :html_url, :current_score, :current_grade, 1, :now, :term_start,
                 :term_end)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, course_code=excluded.course_code, term=excluded.term,
                 html_url=excluded.html_url, current_score=excluded.current_score,
                 current_grade=excluded.current_grade, active=1, term_start=excluded.term_start,
                 term_end=excluded.term_end""",
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
        bodies = self.bodies.setdefault(course["id"], [])
        for a in raw:
            if a.get("published") is False:
                continue
            bodies.append((f"Tarea «{a.get('name') or '(sin nombre)'}»", a.get("description"), []))
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
                "allowed_extensions": ",".join(x.lower().lstrip(".") for x in a.get("allowed_extensions") or []),
                "asks_scan": int(bool(ASKS_SCAN.search(f"{a.get('name') or ''} {a.get('description') or ''}"))),
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
            quiz = self._quiz(course, a, row)
            if quiz:
                info["quiz"] = quiz
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
                     allowed_extensions, asks_scan, sub_state, submitted_at, score, grade, graded_at, excused, missing,
                     late, active, first_seen)
                   VALUES (:id, :course_id, :name, :due_at, :lock_at, :html_url, :points_possible, :submission_types,
                     :allowed_extensions, :asks_scan, :sub_state, :submitted_at, :score, :grade, :graded_at, :excused,
                     :missing, :late, 1, :now)
                   ON CONFLICT(id) DO UPDATE SET course_id=excluded.course_id, name=excluded.name, due_at=excluded.due_at,
                     lock_at=excluded.lock_at, html_url=excluded.html_url, points_possible=excluded.points_possible,
                     submission_types=excluded.submission_types, allowed_extensions=excluded.allowed_extensions,
                     asks_scan=excluded.asks_scan, sub_state=excluded.sub_state,
                     submitted_at=excluded.submitted_at, score=excluded.score, grade=excluded.grade,
                     graded_at=excluded.graded_at, excused=excluded.excused, missing=excluded.missing,
                     late=excluded.late, active=1""",
                {**row, "now": self.now_iso},
            )
        self._deactivate("assignments", course["id"], seen)
        self.read.setdefault(course["id"], set()).add("assignments")

    def _quiz(self, course: dict, a: dict, row: dict) -> dict | None:
        """What the Classic Quiz behind an assignment says about itself. Read again only when its assignment
        changed (editing a quiz updates it), and never for the first time once it closed."""
        if "online_quiz" not in (a.get("submission_types") or []) or not a.get("quiz_id"):
            return None
        stored = self.conn.execute("SELECT * FROM quizzes WHERE assignment_id = ?", (a["id"],)).fetchone()
        version = timefmt.normalize(a.get("updated_at")) or ""
        closes = timefmt.parse(row["lock_at"] or row["due_at"])
        if stored is not None and stored["read_for"] == version or stored is None and closes and closes < self.now:
            return quiz_info(stored)
        try:
            # Works even where the course hides its Quizzes tab (the list answers 404 there).
            q = self.client.get(f"courses/{course['id']}/quizzes/{a['quiz_id']}")
        except (InvalidTokenError, ThrottledError):
            raise
        except CanvasError as exc:
            # The alert still goes out, without these details; the next sync tries again.
            log.warning("cuestionario %s de %s: %s", a["quiz_id"], course["name"], exc)
            return quiz_info(stored)
        quiz = {"assignment_id": a["id"], "quiz_id": a["quiz_id"], "question_count": q.get("question_count"),
                "time_limit": q.get("time_limit"), "allowed_attempts": q.get("allowed_attempts"),
                "unlock_at": timefmt.normalize(q.get("unlock_at")), "lock_at": timefmt.normalize(q.get("lock_at")),
                "hide_results": q.get("hide_results"), "read_for": version}
        self.conn.execute(
            """INSERT OR REPLACE INTO quizzes(assignment_id, quiz_id, question_count, time_limit, allowed_attempts,
                 unlock_at, lock_at, hide_results, read_for)
               VALUES (:assignment_id, :quiz_id, :question_count, :time_limit, :allowed_attempts, :unlock_at, :lock_at,
                 :hide_results, :read_for)""", quiz)
        return quiz_info(quiz)

    # -- announcements ----------------------------------------------------------------

    def announcements(self, course: dict, quiet: bool) -> None:
        # Newest first; one page of 50 is plenty between two polls.
        raw = self.client.get(
            f"courses/{course['id']}/discussion_topics",
            {"only_announcements": "true", "per_page": 50},
        )
        bodies = self.bodies.setdefault(course["id"], [])
        for t in raw if isinstance(raw, list) else []:
            bodies.append((f"Anuncio «{t.get('title') or '(sin título)'}»", t.get("message"), t.get("attachments") or []))
            found = refs(t.get("message"), self.cfg.canvas_url)
            attached = [a["id"] for a in t.get("attachments") or [] if a.get("id")]
            material = json.dumps({"files": [fid for _, fid, _ in found.files] + attached,
                                   "links": [url for url, _ in found.links]}, ensure_ascii=False)
            if self.conn.execute("SELECT 1 FROM announcements WHERE id = ?", (t["id"],)).fetchone():
                # One stored before announcements kept their links, or edited since, gets them now.
                self.conn.execute("UPDATE announcements SET material = ? WHERE id = ? AND material IS NOT ?",
                                  (material, t["id"], material))
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
                "material": material,
            }
            self.conn.execute(
                """INSERT INTO announcements(id, course_id, title, message_text, author, posted_at, html_url, first_seen,
                     material)
                   VALUES (:id, :course_id, :title, :message_text, :author, :posted_at, :html_url, :now, :material)""",
                {**row, "now": self.now_iso},
            )
            self.emit(quiet, "new_announcement", course, row["id"], {
                "titulo": row["title"], "autor": author, "texto": row["message_text"][:600], "url": row["html_url"],
            })
        self.read.setdefault(course["id"], set()).add("announcements")

    # -- the material catalog ----------------------------------------------------------------

    def files(self, course: dict, quiet: bool) -> None:
        cid = course["id"]
        catalog_seeded = _resource_key("seeded", cid, "catalog")
        quiet_catalog = quiet or get_meta(self.conn, catalog_seeded) is None
        found: dict[int, dict] = {}
        listing_ok = True
        try:
            for f in self.client.iter_pages(f"courses/{cid}/files", {"sort": "updated_at", "order": "desc"}):
                found[f["id"]] = {"file": f, "source": "Archivos", "quiet": quiet}
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            # Many courses hide the Files tab from students; Modules still link the files.
            if exc.status not in HIDDEN:
                raise
            listing_ok = False
        folders = self._folders(cid) if listing_ok else {}

        links: dict[str, dict] = {}
        module_pages: dict[str, dict] = {}
        modules_ok = True
        try:
            for module in self.client.iter_pages(f"courses/{cid}/modules", {"include[]": ["items"]}):
                items = module.get("items")
                if items is None and module.get("items_url"):
                    items = self.client.get_all(module["items_url"])
                name, section = clean_title(module.get("name")), None
                for item in items or []:
                    kind = item.get("type")
                    if kind == "SubHeader":  # «ANTES de clase en vivo», «Materiales adicionales»…
                        section = clean_title(item.get("title"))
                    elif kind == "File" and item.get("content_id"):
                        fid = item["content_id"]
                        if fid not in found:
                            try:
                                found[fid] = {"file": self.client.get(f"courses/{cid}/files/{fid}"), "quiet": quiet}
                            except InvalidTokenError:
                                raise
                            except CanvasError as exc:
                                if exc.status not in HIDDEN:
                                    raise
                                continue
                        entry = found[fid]
                        if not entry.get("module"):
                            entry.update(module=name, section=section, source=f"Módulo «{name}»")
                    elif kind == "ExternalUrl" and item.get("external_url"):
                        self._link(links, item["external_url"], item.get("title"), f"Módulo «{name}»", name, section,
                                   module_item=True)
                    elif kind == "Page" and item.get("page_url"):
                        module_pages.setdefault(item["page_url"], {"module": name, "section": section})
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            if exc.status not in HIDDEN:
                raise
            modules_ok = False
        if not listing_ok and not modules_ok:
            raise CanvasError("no tengo acceso a Archivos ni a Módulos", 403)

        complete = self._linked(course, found, links, module_pages, quiet_catalog)
        seen = self._store_files(course, found, folders)
        seen_links = self._store_links(course, links, quiet_catalog)
        if listing_ok and modules_ok and complete:
            self._deactivate("files", cid, seen)
            self._deactivate("links", cid, seen_links)
        term = self.conn.execute("SELECT term_start, term, name FROM courses WHERE id = ?", (cid,)).fetchone()
        mark_duplicates(self.conn, cid, term_year(term["term_start"], term["name"], term["term"]) or self.now.year)
        if complete:
            set_meta(self.conn, catalog_seeded, self.now_iso)

    def _folders(self, cid: int) -> dict[int, str]:
        """Folder id -> its path in the Files tab ('Slides/2026'), without the root folder."""
        try:
            return {f["id"]: (f.get("full_name") or "").partition("/")[2] or None
                    for f in self.client.iter_pages(f"courses/{cid}/folders")}
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            if exc.status not in HIDDEN:
                raise
            return {}

    def _link(self, links: dict, url: str, title: str | None, source: str, module: str | None, section: str | None, *,
              module_item: bool = False) -> None:
        url = url.strip()
        if url in links:
            links[url]["module_item"] |= module_item
            return
        kind, access = classify(url)
        links[url] = {"url": url, "title": clean_title(title) or url, "kind": kind, "access": access, "source": source,
                      "module": module, "section": section, "module_item": module_item}

    def _linked(self, course: dict, found: dict, links: dict, module_pages: dict, quiet: bool) -> bool:
        """Adds what the course's Pages, «Programa del curso», announcements and assignments link to.
        False when this sync could not read all of it (a source failed, or the budget ran out)."""
        cid = course["id"]
        complete = {"assignments", "announcements"} <= self.read.get(cid, set())
        sources = [("Programa del curso", course.get("syllabus_body"), [])] + self.bodies.get(cid, [])
        for where, _, attachments in sources:
            for att in attachments:
                if att.get("id") and att["id"] not in found:
                    found[att["id"]] = {"file": att, "source": where, "quiet": quiet, "download_url": att.get("url")}
        pages, pages_complete = self._pages(cid, module_pages, [body for _, body, _ in sources])
        items = [(where, refs(body, self.cfg.canvas_url), None, None) for where, body, _ in sources] + pages
        for where, found_refs, module, section in items:
            for link_cid, fid, _ in found_refs.files:
                if fid in found:
                    continue
                entry, spent = self._linked_file(cid, link_cid or cid, fid)
                complete &= spent
                if entry is not None:
                    found[fid] = {**entry, "source": where, "module": module, "section": section, "quiet": quiet}
            for url, text in found_refs.links:
                self._link(links, url, text, where, module, section)
        return complete and pages_complete

    def _linked_file(self, cid: int, link_cid: int, fid: int) -> tuple[dict | None, bool]:
        """(entry, whether it could be looked at): a file known from an earlier sync costs no read."""
        known = self.conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
        if known is not None:
            return (None if known["active"] and known["course_id"] != cid else {"known": known}), True
        blocked = self.conn.execute("SELECT checked_at FROM unreachable WHERE course_id = ? AND file_id = ?",
                                    (cid, fid)).fetchone()
        if blocked and self.now - timefmt.parse(blocked["checked_at"]) < UNREACHABLE_RETRY:
            return None, True
        if not self.spend():
            return None, False
        try:
            return {"file": self.client.get(f"courses/{link_cid}/files/{fid}")}, True
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            if exc.status not in HIDDEN:
                raise
            self.conn.execute("INSERT OR REPLACE INTO unreachable(course_id, file_id, checked_at) VALUES (?, ?, ?)",
                              (cid, fid, self.now_iso))
            return None, True

    def _pages(self, cid: int, module_pages: dict, bodies: list[str | None]) -> tuple[list, bool]:
        """(where, refs, module, section) of every Page the course shows or links to. A Page's body is
        read again only when it changed (or, when the Pages list is hidden, once a day)."""
        try:
            listed = {p["url"]: p for p in self.client.iter_pages(f"courses/{cid}/pages", {"sort": "updated_at"})
                      if p.get("url") and p.get("published") is not False}
        except InvalidTokenError:
            raise
        except CanvasError as exc:
            if exc.status not in HIDDEN:
                raise
            listed = {}
        wanted = {slug: {"module": None, "section": None} for slug in listed} | module_pages
        for body in bodies:
            for page_cid, slug in refs(body, self.cfg.canvas_url).pages:
                if page_cid == cid:
                    wanted.setdefault(slug, {"module": None, "section": None})
        out, complete, queue, done = [], True, list(wanted), set()
        while queue:
            slug = queue.pop(0)
            if slug in done:
                continue
            done.add(slug)
            stored = self.conn.execute("SELECT * FROM pages WHERE course_id = ? AND slug = ?", (cid, slug)).fetchone()
            listing = listed.get(slug)
            fresh = stored is not None and (
                stored["updated_at"] == timefmt.normalize(listing.get("updated_at")) if listing is not None
                else self.now - (timefmt.parse(stored["fetched_at"]) or self.now) < PAGE_REFRESH)
            if fresh:
                page_refs, title = Refs.from_json(json.loads(stored["refs"])), stored["title"]
            elif self.spend():
                try:
                    page = self.client.get(f"courses/{cid}/pages/{slug}")
                except InvalidTokenError:
                    raise
                except CanvasError as exc:
                    if exc.status not in HIDDEN:
                        raise
                    continue
                page_refs, title = refs(page.get("body"), self.cfg.canvas_url), page.get("title") or slug
                self.conn.execute(
                    "INSERT OR REPLACE INTO pages(course_id, slug, title, updated_at, refs, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (cid, slug, title, timefmt.normalize(page.get("updated_at")),
                     json.dumps(page_refs.as_json(), ensure_ascii=False), self.now_iso))
            else:
                complete = False
                if stored is None:
                    continue
                page_refs, title = Refs.from_json(json.loads(stored["refs"])), stored["title"]
            where = wanted[slug]
            out.append((f"Página «{title}»", page_refs, where["module"], where["section"]))
            for page_cid, sub in page_refs.pages:
                if page_cid == cid and sub not in done:
                    wanted.setdefault(sub, where)
                    queue.append(sub)
        return out, complete

    def _store_files(self, course: dict, found: dict, folders: dict) -> list[int]:
        cid, seen = course["id"], []
        for fid, entry in found.items():
            known = entry.get("known")
            if known is not None:  # linked from somewhere, already in the catalog: nothing new to read
                self.conn.execute(
                    "UPDATE files SET active = 1, course_id = ?, source = ?, module = COALESCE(module, ?),"
                    " section = COALESCE(section, ?) WHERE id = ?",
                    (cid, entry["source"], entry.get("module"), entry.get("section"), fid))
                seen.append(fid)
                continue
            f = entry["file"]
            if f.get("locked_for_user") or f.get("hidden_for_user"):
                continue
            seen.append(fid)
            row = {
                "id": fid,
                "course_id": cid,
                "display_name": f.get("display_name") or f.get("filename") or f"archivo-{fid}",
                "filename": f.get("filename"),
                "content_type": f.get("content-type") or f.get("content_type"),
                "size": f.get("size"),
                "updated_at": timefmt.normalize(f.get("updated_at") or f.get("modified_at")),
                "created_at": timefmt.normalize(f.get("created_at")),
                "html_url": f"{self.cfg.canvas_url}/courses/{cid}/files/{fid}",
                "module": entry.get("module"),
                "section": entry.get("section"),
                "folder": folders.get(f.get("folder_id")),
                "source": entry.get("source") or "Archivos",
                "download_url": entry.get("download_url"),
            }
            prev = self.conn.execute("SELECT * FROM files WHERE id = ?", (fid,)).fetchone()
            info = {"archivo": row["display_name"], "modulo": row["module"], "seccion": row["section"],
                    "origen": row["source"], "url": row["html_url"]}
            if prev is None:
                self.emit(entry["quiet"], "new_file", course, fid, info)
            elif prev["updated_at"] != row["updated_at"]:
                self.emit(entry["quiet"], "file_updated", course, fid, info)
            self.conn.execute(
                """INSERT INTO files(id, course_id, display_name, filename, content_type, size, updated_at, html_url,
                     module, active, first_seen, folder, section, source, created_at, download_url)
                   VALUES (:id, :course_id, :display_name, :filename, :content_type, :size, :updated_at, :html_url,
                     :module, 1, :now, :folder, :section, :source, :created_at, :download_url)
                   ON CONFLICT(id) DO UPDATE SET course_id=excluded.course_id, display_name=excluded.display_name,
                     filename=excluded.filename, content_type=excluded.content_type, size=excluded.size,
                     updated_at=excluded.updated_at, html_url=excluded.html_url,
                     module=COALESCE(excluded.module, files.module), section=COALESCE(excluded.section, files.section),
                     folder=COALESCE(excluded.folder, files.folder), source=excluded.source,
                     created_at=COALESCE(excluded.created_at, files.created_at),
                     download_url=COALESCE(excluded.download_url, files.download_url), active=1""",
                {**row, "now": self.now_iso},
            )
        return seen

    def _store_links(self, course: dict, links: dict, quiet: bool) -> list[int]:
        """Outside links; one a module lists (the professor's own «material» item) is announced as new."""
        cid, seen = course["id"], []
        for link in links.values():
            prev = self.conn.execute("SELECT id FROM links WHERE course_id = ? AND url = ?", (cid, link["url"])).fetchone()
            self.conn.execute(
                """INSERT INTO links(course_id, url, title, kind, access, source, module, section, active, first_seen)
                   VALUES (:course_id, :url, :title, :kind, :access, :source, :module, :section, 1, :now)
                   ON CONFLICT(course_id, url) DO UPDATE SET title=excluded.title, kind=excluded.kind,
                     access=excluded.access, source=excluded.source, module=excluded.module,
                     section=excluded.section, active=1""",
                {**link, "course_id": cid, "now": self.now_iso})
            link_id = self.conn.execute("SELECT id FROM links WHERE course_id = ? AND url = ?",
                                        (cid, link["url"])).fetchone()["id"]
            seen.append(link_id)
            if prev is None and link["module_item"]:
                self.emit(quiet, "new_link", course, link_id, {
                    "enlace": link["title"], "url": link["url"], "tipo": link["kind"], "acceso": link["access"],
                    "modulo": link["module"], "seccion": link["section"]})
        return seen

    def _deactivate(self, table: str, course_id: int, seen: list[int]) -> None:
        # Negative ids are material that never came from Canvas (a fetched link, a PDF the student gave).
        marks = ",".join("?" * len(seen)) or "NULL"
        self.conn.execute(
            f"UPDATE {table} SET active = 0 WHERE course_id = ? AND id > 0 AND id NOT IN ({marks})",
            (course_id, *seen),
        )


def sync(conn: sqlite3.Connection, client: CanvasClient, cfg: CoreConfig, now: datetime, *,
         budget: int | None = None) -> SyncReport:
    """Read everything once and record changes. Caller holds `store.sync_lock`. `budget`: how many
    reads the catalog may spend following links (None: as many as it needs)."""
    first = get_meta(conn, "initialized") is None
    report = SyncReport(first_sync=first)
    s = _Syncer(conn, client, cfg, now, budget)
    courses = s.courses()
    report.courses = len(courses)
    ids = [c["id"] for c in courses]
    conn.execute(
        f"UPDATE courses SET active = 0 WHERE id NOT IN ({','.join('?' * len(ids)) or 'NULL'})", ids
    )
    for course in courses:
        known = s.upsert_course(course)
        if not first and not known:
            s.emit(False, "new_course", course, course["id"], {"codigo": course["course_code"], "url": course["html_url"]})
        for resource, label, step in (("assignments", "tareas", s.assignments),
                                      ("announcements", "anuncios", s.announcements),
                                      ("files", "archivos", s.files)):
            baseline = _resource_key("seeded", course["id"], resource)
            failing = _resource_key("failing", course["id"], resource)
            reported = _resource_key("reported", course["id"], resource)
            seeded = get_meta(conn, baseline) is not None
            try:
                step(course, not seeded)
            except (InvalidTokenError, ThrottledError):  # stop reading altogether, don't move on to the next
                conn.rollback()
                raise
            except CanvasError as exc:
                s.warnings.append(f"{course['name']}: {exc}")
                log.warning("%s: %s", course["name"], exc)
                if exc.status not in HIDDEN:
                    reads = int(get_meta(conn, failing) or 0) + 1
                    set_meta(conn, failing, str(reads))
                    s.failed.append(FailedResource(course["id"], resource, f"los {label} de {course['name']}",
                                                   reads, get_meta(conn, reported) is not None))
                    continue
            else:
                if not seeded:
                    set_meta(conn, baseline, s.now_iso)
            delete_meta(conn, failing, reported)
        conn.commit()
    set_meta(conn, "initialized", "1")
    set_meta(conn, "last_sync", s.now_iso)
    conn.commit()
    report.events = s.events
    report.warnings = s.warnings
    report.failed = s.failed
    report.requests = client.requests_made
    return report


def last_sync(conn: sqlite3.Connection) -> datetime | None:
    return timefmt.parse(get_meta(conn, "last_sync"))


def pending_events(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM events WHERE delivered_at IS NULL ORDER BY id").fetchall()
    return [{"id": r["id"], "kind": r["kind"], "course_id": r["course_id"], "ref_id": r["ref_id"],
             "created_at": r["created_at"], **json.loads(r["payload"])} for r in rows]


def mark_reported(conn: sqlite3.Connection, failure: FailedResource, now: datetime) -> None:
    set_meta(conn, _resource_key("reported", failure.course_id, failure.resource), timefmt.iso(now))
    conn.commit()


def mark_delivered(conn: sqlite3.Connection, event_ids: list[int], now: datetime) -> None:
    conn.executemany("UPDATE events SET delivered_at = ? WHERE id = ?", [(timefmt.iso(now), i) for i in event_ids])
    conn.commit()
