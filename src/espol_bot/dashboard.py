"""The dashboard behind the menu button of Vinci's chat: the term's progress, the pending deliverables and the
aula's latest news, with no model.

The page (docs/dashboard/, a static page on GitHub Pages) asks no server for anything: after each poll that
changed what it shows, Vinci compresses the snapshot into the fragment of the menu button's URL
(`#d=<base64url of raw DEFLATE JSON>`, set with setChatMenuButton for the captain's chat only). A browser
never sends the fragment, so GitHub never sees it. Ticking a deliverable on the page opens
`t.me/<vinci>?start=s_<id>_ok` (a to-do: `t_…`): the plugin `vinci-botones` runs it as the
«✅ Ya lo entregué» / «✅ Hecho» button would, and the menu button gets a fresh snapshot.

On WhatsApp, /entregas answers with a link to the same page (`whatsapp_url`), whose snapshot carries Vinci's number
(«wa») instead of the bot's username: a tick opens Vinci's chat with «/marca s<id> ok» typed, which the plugin
vinci-whatsapp runs as the button too.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import sqlite3
import zlib
from collections import Counter
from datetime import datetime, time, timedelta

from aula_core import queries, timefmt
from aula_core.config import ConfigError
from aula_core.store import delete_meta, get_meta, set_meta
from espol_bot import materias, priority, store
from espol_bot.config import BotConfig, load_telegram_secrets
from espol_bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

VERSION = 1
BUTTON = "📋 Entregas"
DIGEST = "dashboard_digest"      # what the menu button shows now, so an unchanged snapshot is not sent again
USERNAME = "vinci_username"      # the page's ticks open a deep link to this bot
NEWS_DAYS = 7
MAX_NEWS = 10
MAX_ITEMS = 40
# Telegram documents no limit for a Mini App URL. Its menu button kept 16,000 characters intact in a test;
# this stays well below, for the phones' webviews. A semester's snapshot takes about 2,000.
MAX_URL = 4000
TERM_SUFFIX = re.compile(r"\s*-\s*pr[aá]ctico\s*$", re.IGNORECASE)
NEWS_KINDS = {"new_assignment": "assignment", "due_changed": "due", "new_announcement": "announcement",
              "grade_posted": "grade", "grade_changed": "grade", "new_file": "file", "file_updated": "file",
              "new_link": "link", "new_course": "course"}


def snapshot(conn: sqlite3.Connection, cfg: BotConfig, team: list[materias.Subject], now: datetime) -> dict:
    """What the page shows, in the 7:00 summary's order; `at` is set by publish, once it differs from the last."""
    tz = cfg.core.tz
    tasks = [t for t in queries.pending(conn, now, overdue_days=7) if t["vence"]]
    todos = store.open_todos(conn)
    entries = priority.ordered(conn, team, tz, now, tasks, [t for t in todos if t["due_at"]])
    items = [_todo(e.item) if e.todo else _task(e.item, e.weight) for e in entries]
    items += [_todo(t) for t in todos if not t["due_at"]]
    return {"v": VERSION, "term": term(conn, cfg), "items": items[:MAX_ITEMS], "more": max(0, len(items) - MAX_ITEMS),
            "news": news(conn, now)}


def _task(task: dict, weight: float | None) -> dict:
    return {"id": f"s{task['id']}", "title": task["tarea"], "course": materias.short_name(task["curso"]),
            "due": task["vence"], "weight": round(weight, 1) if weight is not None else None,
            "quiz": task["quiz"] is not None}


def _todo(todo: dict) -> dict:
    return {"id": f"t{todo['id']}", "title": todo["text"], "course": todo["subject"], "due": todo["due_at"],
            "allDay": todo["all_day"], "todo": True}


def term(conn: sqlite3.Connection, cfg: BotConfig) -> dict | None:
    """The term most active courses are in. Its end is config's semester_end (the last day of classes) when set:
    the aula's term also spans the exams and the make-up weeks."""
    rows = conn.execute("SELECT term, term_start, term_end FROM courses WHERE active = 1 AND term_start IS NOT NULL"
                        ).fetchall()
    if not rows:
        return None
    name = Counter(TERM_SUFFIX.sub("", r["term"] or "").strip() for r in rows).most_common(1)[0][0]
    start = min(r["term_start"] for r in rows)
    if cfg.semester_end is not None:
        end = timefmt.iso(datetime.combine(cfg.semester_end, time(23, 59), tzinfo=cfg.core.tz))
    else:
        end = max((r["term_end"] for r in rows if r["term_end"]), default=None)
    return {"name": name or None, "start": start, "end": end} if end and end > start else None


def news(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    """The aula's alerts of the last days, newest first: what Vinci already told the captain, one line each."""
    since = timefmt.iso(now - timedelta(days=NEWS_DAYS))
    rows = conn.execute("SELECT * FROM events WHERE delivered_at IS NOT NULL AND created_at >= ? "
                        "ORDER BY created_at DESC, id DESC LIMIT ?", (since, MAX_NEWS)).fetchall()
    found = []
    for r in rows:
        payload = json.loads(r["payload"])
        kind = NEWS_KINDS.get(r["kind"])
        title = payload.get("tarea") or payload.get("titulo") or payload.get("archivo") or payload.get("enlace") \
            or payload.get("curso")
        if kind is None or not title:
            continue
        item = {"id": r["id"], "kind": kind, "title": str(title), "course": materias.short_name(payload.get("curso") or ""),
                "at": r["created_at"]}
        if kind == "due" and payload.get("due_at"):
            item["due"] = payload["due_at"]
        if kind == "grade":
            score = payload.get("calificacion") or payload.get("nota")
            if score is not None:
                item["score"] = str(score)
        if r["kind"] == "new_assignment" and payload.get("quiz"):
            item["quiz"] = True
        found.append(item)
    return found


def encode(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw DEFLATE: the page's DecompressionStream("deflate-raw")
    return base64.urlsafe_b64encode(packer.compress(raw) + packer.flush()).decode().rstrip("=")


def decode(payload: str) -> dict:
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)), -15))


def page_url(cfg: BotConfig, data: dict, base: str | None = None) -> str:
    """The page with the snapshot in its fragment, trimmed (oldest news first, then the last deliverables) to fit."""
    data = {**data, "news": list(data["news"]), "items": list(data["items"])}
    while True:
        url = f"{base or cfg.dashboard_url}#d={encode(data)}"
        if len(url) <= MAX_URL or not (data["news"] or data["items"]):
            return url
        if data["news"]:
            data["news"].pop()
        else:
            data["items"].pop()
            data["more"] += 1


def publish(conn: sqlite3.Connection, cfg: BotConfig, telegram: Telegram, team: list[materias.Subject],
            now: datetime, *, force: bool = False) -> str | None:
    """Points the menu button at a fresh snapshot when it changed; the URL set, or None when nothing was sent."""
    if not cfg.dashboard_url:
        if get_meta(conn, DIGEST) is not None:  # switched off in config.toml: the chat gets its usual menu back
            telegram.set_menu_button(None)
            delete_meta(conn, DIGEST)
            conn.commit()
        return None
    data = snapshot(conn, cfg, team, now)
    data["bot"] = bot_username(conn, telegram)
    digest = hashlib.sha256(f"{cfg.dashboard_url}\n{json.dumps(data, sort_keys=True)}".encode()).hexdigest()
    if not force and get_meta(conn, DIGEST) == digest:
        return None
    data["at"] = timefmt.iso(now)
    url = page_url(cfg, data)
    telegram.set_menu_button({"type": "web_app", "text": BUTTON, "web_app": {"url": url}})
    set_meta(conn, DIGEST, digest)
    conn.commit()
    log.info("dashboard: botón de menú actualizado (%d caracteres)", len(url))
    return url


def whatsapp_url(conn: sqlite3.Connection, cfg: BotConfig, team: list[materias.Subject], now: datetime,
                 vinci_number: str) -> str | None:
    """The page for /entregas on WhatsApp, its ticks pointed back at Vinci's WhatsApp chat; None with no page."""
    if not cfg.dashboard_page:
        return None
    data = {**snapshot(conn, cfg, team, now), "wa": vinci_number, "at": timefmt.iso(now)}
    return page_url(cfg, data, base=cfg.dashboard_page)


def bot_username(conn: sqlite3.Connection, telegram: Telegram) -> str:
    username = get_meta(conn, USERNAME)
    if not username:
        username = str(telegram.get_me().get("username") or "")
        set_meta(conn, USERNAME, username)
        conn.commit()
    return username


def refresh(cfg: BotConfig, conn: sqlite3.Connection, now: datetime) -> None:
    """publish() from outside the poll (a deliverable ticked in the chat or on the page); a failure only waits
    for the next poll."""
    try:
        publish(conn, cfg, Telegram(load_telegram_secrets(), api=cfg.telegram_api), materias.load(cfg.core), now)
    except (TelegramError, ConfigError) as exc:
        log.info("dashboard: no pude actualizarlo ahora (%s)", exc)
