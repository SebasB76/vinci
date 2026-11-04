"""What Canvas holds beyond a course's content: its professors and assistants, its forums, the calendar, the
professors' inbox messages, the student's groups and the peer reviews they owe.

Each read fails alone: the rest of the sync goes on, and the next sync tries again.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from aula_core import timefmt
from aula_core.canvas import CanvasError, InvalidTokenError, ThrottledError
from aula_core.catalog import html_to_text
from aula_core.store import get_meta, set_meta

log = logging.getLogger(__name__)

STAFF_EVERY = timedelta(days=7)
GROUPS_EVERY = timedelta(hours=12)
CALENDAR_AHEAD = timedelta(days=120)
INBOX_PAGE = 30
INBOX_SINCE = timedelta(days=120)  # a first read stores the term's messages, not years of them
SEED_VIEW_SINCE = timedelta(days=21)
STAFF_ENROLLMENTS = {"TeacherEnrollment", "TaEnrollment", "DesignerEnrollment"}
CONTEXTS_PER_READ = 10  # Canvas takes at most 10 context_codes per calendar request


def self_id(s) -> int:
    known = get_meta(s.conn, "canvas_user_id")
    if known:
        return int(known)
    me = s.client.get("users/self")
    set_meta(s.conn, "canvas_user_id", str(me["id"]))
    return me["id"]


def _fresh(s, key: str, every: timedelta) -> bool:
    last = timefmt.parse(get_meta(s.conn, key))
    return last is not None and s.now - last < every


def _absolute(s, url: str | None) -> str | None:
    return f"{s.cfg.canvas_url}{url}" if url and url.startswith("/") else url


# -- per course ---------------------------------------------------------------------------


def staff(s, course: dict, quiet: bool) -> None:
    """The course's professors and assistants, read once a week."""
    key = f"staff_read:{course['id']}"
    if _fresh(s, key, STAFF_EVERY):
        return
    try:
        people = s.client.get_all(f"courses/{course['id']}/users",
                                  {"enrollment_type[]": ["teacher", "ta"], "include[]": ["email", "enrollments"]})
    except (InvalidTokenError, ThrottledError):
        raise
    except CanvasError as exc:
        if exc.status not in (403, 404):
            raise
        people = []  # the course hides its People list: asking every poll would not change that
    s.conn.execute("DELETE FROM course_staff WHERE course_id = ?", (course["id"],))
    for p in people:
        types = {e.get("type") for e in p.get("enrollments") or [] if e.get("course_id") in (None, course["id"])}
        s.conn.execute("INSERT OR REPLACE INTO course_staff(course_id, user_id, name, role, email) VALUES (?, ?, ?, ?, ?)",
                       (course["id"], p["id"], p.get("name") or p.get("short_name"),
                        "ta" if types and "TeacherEnrollment" not in types else "teacher", p.get("email")))
    set_meta(s.conn, key, s.now_iso)


def discussions(s, course: dict, quiet: bool) -> None:
    """The course's forums (not its announcements). A topic that is new or got replies is opened to see whether the
    student posted in it and who answered them."""
    cid = course["id"]
    raw = s.client.get_all(f"courses/{cid}/discussion_topics", {"per_page": 50})
    seen = []
    for t in raw:
        if t.get("published") is False:
            continue
        prev = s.conn.execute("SELECT * FROM discussions WHERE id = ?", (t["id"],)).fetchone()
        assignment = t.get("assignment") or {}
        row = {
            "id": t["id"], "course_id": cid, "title": t.get("title") or "(sin título)",
            "message_text": html_to_text(t.get("message")) or None,
            "author": (t.get("author") or {}).get("display_name") or t.get("user_name"),
            "posted_at": timefmt.normalize(t.get("posted_at")),
            "last_reply_at": timefmt.normalize(t.get("last_reply_at")),
            "due_at": timefmt.normalize(assignment.get("due_at") or t.get("todo_date")),
            "lock_at": timefmt.normalize(t.get("lock_at")),
            "assignment_id": t.get("assignment_id"),
            "require_initial_post": int(bool(t.get("require_initial_post"))),
            "participated": prev["participated"] if prev else None,
            "replies": prev["replies"] if prev else None,
            "html_url": t.get("html_url") or f"{s.cfg.canvas_url}/courses/{cid}/discussion_topics/{t['id']}",
        }
        seen.append(row["id"])
        changed = prev is None or prev["last_reply_at"] != row["last_reply_at"]
        if changed and (not quiet or _recent(s, row)):
            view = _view(s, cid, t["id"])
            if view is not None:
                mine, replies = _my_thread(view, self_id(s))
                before = None if prev is None or prev["replies"] is None else set(json.loads(prev["replies"]))
                row["participated"] = int(bool(mine))
                row["replies"] = json.dumps(sorted(r["id"] for r in replies))
                new = [r for r in replies if before is not None and r["id"] not in before]
                if new:
                    s.emit(quiet, "discussion_reply", course, row["id"],
                           {"titulo": row["title"], "url": row["html_url"],
                            "respuestas": [{"autor": r["author"], "texto": r["text"]} for r in new]})
        s.conn.execute(
            """INSERT INTO discussions(id, course_id, title, message_text, author, posted_at, last_reply_at, due_at,
                 lock_at, assignment_id, require_initial_post, participated, replies, html_url, active, first_seen)
               VALUES (:id, :course_id, :title, :message_text, :author, :posted_at, :last_reply_at, :due_at, :lock_at,
                 :assignment_id, :require_initial_post, :participated, :replies, :html_url, 1, :now)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, message_text=excluded.message_text,
                 author=excluded.author, posted_at=excluded.posted_at, last_reply_at=excluded.last_reply_at,
                 due_at=excluded.due_at, lock_at=excluded.lock_at, assignment_id=excluded.assignment_id,
                 require_initial_post=excluded.require_initial_post, participated=excluded.participated,
                 replies=excluded.replies, html_url=excluded.html_url, active=1""",
            {**row, "now": s.now_iso})
        if prev is None:
            s.emit(quiet, "new_discussion", course, row["id"],
                   {"titulo": row["title"], "autor": row["author"], "texto": (row["message_text"] or "")[:600],
                    "due_at": row["due_at"], "calificado": row["assignment_id"] is not None, "url": row["html_url"]})
    s._deactivate("discussions", cid, seen)


def _recent(s, row: dict) -> bool:
    """On a first read, only topics still alive are opened: one read each."""
    if row["lock_at"] and row["lock_at"] < s.now_iso:
        return False
    since = timefmt.iso(s.now - SEED_VIEW_SINCE)
    return (row["last_reply_at"] or row["posted_at"] or "") >= since or (row["due_at"] or "") >= s.now_iso


def _view(s, cid: int, tid: int) -> dict | None:
    try:
        return s.client.get(f"courses/{cid}/discussion_topics/{tid}/view")
    except (InvalidTokenError, ThrottledError):
        raise
    except CanvasError as exc:
        if exc.status == 403:  # «post before you see the replies»: the student has not posted
            return {"view": [], "participants": []}
        log.warning("foro %s: %s", tid, exc)
        return None


def _my_thread(view: dict, me: int) -> tuple[list[int], list[dict]]:
    """The student's own entries, and the replies others left under them."""
    names = {p.get("id"): p.get("display_name") for p in view.get("participants") or []}
    mine, replies = [], []

    def walk(entries, parent_mine: bool):
        for entry in entries or []:
            if entry.get("deleted"):
                walk(entry.get("replies"), False)
                continue
            own = entry.get("user_id") == me
            if own:
                mine.append(entry["id"])
            elif parent_mine:
                replies.append({"id": entry["id"], "author": names.get(entry.get("user_id")),
                                "text": html_to_text(entry.get("message"))[:500]})
            walk(entry.get("replies"), own)

    walk(view.get("view"), False)
    return mine, replies


# -- the student's whole account ------------------------------------------------------------


def read_all(s, courses: list[dict]) -> None:
    """The reads that span every course. A first read of each stores what is there without an alert."""
    for name, step in (("calendar", calendar), ("inbox", inbox), ("groups", groups), ("peer_reviews", peer_reviews)):
        key = f"seeded:account:{name}"
        seeded = get_meta(s.conn, key) is not None
        try:
            step(s, courses, not seeded)
        except (InvalidTokenError, ThrottledError):
            s.conn.rollback()
            raise
        except CanvasError as exc:
            s.conn.rollback()
            s.warnings.append(f"{name}: {exc}")
            log.warning("%s: %s", name, exc)
            continue
        if not seeded:
            set_meta(s.conn, key, s.now_iso)
        s.conn.commit()


def _by_code(courses: list[dict]) -> dict[str, dict]:
    return {f"course_{c['id']}": c for c in courses}


def calendar(s, courses: list[dict], quiet: bool) -> None:
    """Events the professors put in the courses' calendars (an exam, a live class, office hours): not assignments."""
    by_code = _by_code(courses)
    codes = list(by_code)
    start = timefmt.iso(s.now - timedelta(days=1))
    seen = []
    for i in range(0, len(codes), CONTEXTS_PER_READ):
        raw = s.client.get_all("calendar_events", {
            "type": "event", "context_codes[]": codes[i:i + CONTEXTS_PER_READ], "start_date": start,
            "end_date": timefmt.iso(s.now + CALENDAR_AHEAD), "per_page": 100})
        for ev in raw:
            course = by_code.get(ev.get("effective_context_code") or "") or by_code.get(ev.get("context_code") or "")
            if course is None or ev.get("workflow_state") == "deleted" or ev.get("hidden"):
                continue
            location = ", ".join(x for x in (ev.get("location_name"), ev.get("location_address")) if x) or None
            row = {"id": ev["id"], "course_id": course["id"], "title": ev.get("title") or "(sin título)",
                   "start_at": timefmt.normalize(ev.get("start_at")), "end_at": timefmt.normalize(ev.get("end_at")),
                   "all_day": int(bool(ev.get("all_day"))), "location": location,
                   "description": html_to_text(ev.get("description")) or None,
                   "html_url": ev.get("html_url") or f"{s.cfg.canvas_url}/calendar"}
            seen.append(row["id"])
            prev = s.conn.execute("SELECT * FROM calendar_events WHERE id = ?", (row["id"],)).fetchone()
            s.conn.execute(
                """INSERT INTO calendar_events(id, course_id, title, start_at, end_at, all_day, location, description,
                     html_url, active, first_seen)
                   VALUES (:id, :course_id, :title, :start_at, :end_at, :all_day, :location, :description, :html_url, 1,
                     :now)
                   ON CONFLICT(id) DO UPDATE SET course_id=excluded.course_id, title=excluded.title,
                     start_at=excluded.start_at, end_at=excluded.end_at, all_day=excluded.all_day,
                     location=excluded.location, description=excluded.description, html_url=excluded.html_url, active=1""",
                {**row, "now": s.now_iso})
            if (row["start_at"] or "") < s.now_iso:
                continue
            info = {"titulo": row["title"], "inicio": row["start_at"], "fin": row["end_at"],
                    "todo_el_dia": bool(row["all_day"]), "lugar": location,
                    "texto": (row["description"] or "")[:400], "url": row["html_url"]}
            if prev is None or not prev["active"]:
                s.emit(quiet, "new_event", course, row["id"], info)
            elif prev["start_at"] != row["start_at"]:
                s.emit(quiet, "event_changed", course, row["id"], {**info, "inicio_anterior": prev["start_at"]})
    marks = ",".join("?" * len(seen)) or "NULL"
    s.conn.execute(f"UPDATE calendar_events SET active = 0 WHERE start_at >= ? AND id NOT IN ({marks})", (start, *seen))


def inbox(s, courses: list[dict], quiet: bool) -> None:
    """What professors and assistants wrote to the student through the aula's inbox. Classmates' messages are never
    stored, and a conversation is read without marking it as read."""
    by_code = _by_code(courses)
    staff = {}
    for r in s.conn.execute("SELECT course_id, user_id FROM course_staff"):
        staff.setdefault(r["user_id"], set()).add(r["course_id"])
    since = timefmt.iso(s.now - INBOX_SINCE)
    # Newest activity first: past the first thread unchanged since the last read, or too old, nothing is new.
    for c in s.client.iter_pages("conversations", {"per_page": INBOX_PAGE}):
        last = timefmt.normalize(c.get("last_message_at"))
        prev = s.conn.execute("SELECT last_message_at FROM inbox_threads WHERE id = ?", (c["id"],)).fetchone()
        if prev is not None and prev["last_message_at"] == last or (last or "") < since:
            break
        course = by_code.get(c.get("context_code") or "")
        if course is not None:
            full = s.client.get(f"conversations/{c['id']}", {"auto_mark_as_read": "false"})
            people = {p.get("id"): p for p in full.get("participants") or []}
            for m in reversed(full.get("messages") or []):  # Canvas lists the newest first
                author = people.get(m.get("author_id")) or {}
                roles = set((author.get("common_courses") or {}).get(str(course["id"])) or [])
                if course["id"] not in staff.get(m.get("author_id"), set()) and not roles & STAFF_ENROLLMENTS:
                    continue
                if s.conn.execute("SELECT 1 FROM inbox_messages WHERE id = ?", (m["id"],)).fetchone():
                    continue
                files = [{"name": f.get("display_name"), "url": f.get("url")} for f in m.get("attachments") or []]
                row = {"id": m["id"], "conversation_id": c["id"], "course_id": course["id"],
                       "subject": c.get("subject") or full.get("subject"), "author": author.get("name"),
                       "body": (m.get("body") or "").strip(), "created_at": timefmt.normalize(m.get("created_at")),
                       "attachments": json.dumps(files, ensure_ascii=False)}
                s.conn.execute(
                    """INSERT INTO inbox_messages(id, conversation_id, course_id, subject, author, body, created_at,
                         attachments)
                       VALUES (:id, :conversation_id, :course_id, :subject, :author, :body, :created_at, :attachments)""",
                    row)
                s.emit(quiet, "new_message", course, row["id"],
                       {"asunto": row["subject"], "autor": row["author"], "texto": row["body"][:1500],
                        "adjuntos": files, "url": f"{s.cfg.canvas_url}/conversations"})
        s.conn.execute("INSERT OR REPLACE INTO inbox_threads(id, last_message_at) VALUES (?, ?)", (c["id"], last))


def groups(s, courses: list[dict], quiet: bool) -> None:
    """The student's groups in their courses (a project team), with who is in each. Read twice a day at most."""
    if _fresh(s, "groups_read", GROUPS_EVERY):
        return
    by_id = {c["id"]: c for c in courses}
    me = self_id(s)
    seen = []
    for g in s.client.get_all("users/self/groups", {"per_page": 50}):
        course = by_id.get(g.get("course_id"))
        if g.get("context_type") != "Course" or course is None:
            continue
        seen.append(g["id"])
        prev = s.conn.execute("SELECT * FROM student_groups WHERE id = ?", (g["id"],)).fetchone()
        members = prev["members"] if prev else None
        if prev is None or prev["members_count"] != g.get("members_count"):
            people = s.client.get_all(f"groups/{g['id']}/users", {"per_page": 50})
            members = json.dumps(sorted(p.get("name") or "" for p in people if p.get("id") != me), ensure_ascii=False)
        s.conn.execute(
            """INSERT INTO student_groups(id, course_id, name, members_count, members, active)
               VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET course_id=excluded.course_id, name=excluded.name,
                 members_count=excluded.members_count, members=excluded.members, active=1""",
            (g["id"], course["id"], g.get("name"), g.get("members_count"), members))
        if prev is None:
            s.emit(quiet, "new_group", course, g["id"], {"grupo": g.get("name"), "integrantes": json.loads(members)})
    marks = ",".join("?" * len(seen)) or "NULL"
    s.conn.execute(f"UPDATE student_groups SET active = 0 WHERE id NOT IN ({marks})", seen)
    set_meta(s.conn, "groups_read", s.now_iso)


def peer_reviews(s, courses: list[dict], quiet: bool) -> None:
    """Classmates' work the student must review. Read only while some assignment asks for peer reviews."""
    if not s.conn.execute("SELECT 1 FROM assignments WHERE active = 1 AND peer_reviews = 1 LIMIT 1").fetchone():
        return
    by_id = {c["id"]: c for c in courses}
    items = s.client.get_all("planner/items", {"start_date": timefmt.iso(s.now - timedelta(days=30)),
                                               "end_date": timefmt.iso(s.now + CALENDAR_AHEAD), "per_page": 100})
    for it in items:
        course = by_id.get(it.get("course_id"))
        if it.get("plannable_type") != "assessment_request" or course is None:
            continue
        p = it.get("plannable") or {}
        done = p.get("workflow_state") == "completed" or bool((it.get("planner_override") or {}).get("marked_complete"))
        row = {"id": it.get("plannable_id") or p["id"], "course_id": course["id"],
               "title": p.get("title") or it.get("plannable_title") or "Revisión entre pares",
               "due_at": timefmt.normalize(it.get("plannable_date") or p.get("todo_date")),
               "html_url": _absolute(s, it.get("html_url")), "done": int(done)}
        prev = s.conn.execute("SELECT 1 FROM peer_reviews WHERE id = ?", (row["id"],)).fetchone()
        s.conn.execute(
            """INSERT INTO peer_reviews(id, course_id, title, due_at, html_url, done, first_seen)
               VALUES (:id, :course_id, :title, :due_at, :html_url, :done, :now)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, due_at=excluded.due_at, html_url=excluded.html_url,
                 done=excluded.done""",
            {**row, "now": s.now_iso})
        if prev is None and not done:
            s.emit(quiet, "peer_review_assigned", course, row["id"],
                   {"tarea": row["title"], "due_at": row["due_at"], "url": row["html_url"]})
