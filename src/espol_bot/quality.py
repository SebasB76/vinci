"""How well each Vinci answers, in numbers, from Hermes' own record of every chat (state.db) and from what the
person and the citation check flagged (quality.jsonl in each one's data folder).

    vinci-check quality [--days 14]      messages, answer time, tool failures, summaries of the chat, spend,
                                         «/mal» reports and corrected citations, per person
    vinci-check quality --feedback       the «/mal» reports themselves

The numbers carry no chat text and friends go by a masked name. A report does carry text: the person sent «/mal»
to pass that answer on to whoever maintains Vinci, and the reply to it says so.
"""
from __future__ import annotations

import json
import re
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aula_core import timefmt
from espol_bot import amigos
from espol_bot.config import BotConfig, hermes_root

EVENTS = "quality.jsonl"
CHATS = ("whatsapp", "telegram")  # the CLI, a cron job or an eval run is nobody's conversation
STAMP = re.compile(r"^\[[^\]]*\]\s*")
SUMMARY_MARKS = ("[PRIOR CONTEXT", "[CONTEXT COMPACTION")
TOOL_FAILED = re.compile(r'"isError":\s*true|"error":|^Error|Traceback|timed out')
PREFIX = re.compile(r"^mcp__[a-z]+__")
MAX_ANSWER_SECONDS = 3600
NOTE_KEPT, ASK_KEPT, REPLY_KEPT = 500, 1000, 2000


# -- what a person or a check flagged ----------------------------------------------------------

def _now() -> datetime:
    # Hermes stamps its record with the wall clock, so everything here does too: AULA_NOW moves the aula's clock only.
    return datetime.now(timezone.utc)


def record(data_dir: Path, kind: str, **fields) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / EVENTS).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": timefmt.iso(_now()), "kind": kind, **fields}, ensure_ascii=False) + "\n")


def events(data_dir: Path, since: datetime | None = None) -> list[dict]:
    try:
        lines = (data_dir / EVENTS).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    found = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        at = timefmt.parse(event.get("at"))
        if since is None or (at is not None and at >= since):
            found.append(event)
    return found


# -- Hermes' record of a profile -----------------------------------------------------------------

def _connect(profile: str) -> sqlite3.Connection | None:
    db = hermes_root() / "profiles" / profile / "state.db"
    if not db.exists():
        return None
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)


def _is_summary(content: str) -> bool:
    return "compacted into the summary" in content[:400] or content.startswith(SUMMARY_MARKS)


def _is_task(content: str) -> bool:
    return "Tarea del sistema" in content[:200] or "TAREA:" in content[:400]


def _messages(conn: sqlite3.Connection, since: float) -> list[tuple]:
    """(chat, role, content, tools called, tool name, time, session) of every chat message since then, chat by chat
    and once each: when Hermes summarizes or restarts a chat, a new session of the same chat carries its last
    messages again."""
    rows = conn.execute(
        "SELECT COALESCE(s.session_key, s.id), m.role, m.content, m.tool_calls, m.tool_name, m.timestamp, "
        "m.session_id, m.tool_call_id FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE s.source IN (?, ?) AND m.timestamp >= ? ORDER BY 1, m.timestamp, m.id", (*CHATS, since)).fetchall()
    seen, found = set(), []
    for chat, role, content, calls, tool, stamp, session, call_id in rows:
        content = content or ""
        # Hermes also keeps a person's message a second time with the hour in front, at the same instant.
        key = ((role, call_id) if role == "tool" and call_id else (role, round(stamp, 2)) if role == "user"
               else (role, round(stamp, 2), content[:80], tool))
        if key in seen:
            continue
        seen.add(key)
        try:
            names = [PREFIX.sub("", c.get("function", {}).get("name") or "") for c in json.loads(calls or "[]")
                     if isinstance(c, dict)]
        except ValueError:
            names = []
        found.append((chat, role, content, names, PREFIX.sub("", tool or ""), stamp, session))
    return found


def measure(profile: str, since: datetime) -> dict | None:
    """One profile's numbers since then; None when Hermes has no record of it."""
    conn = _connect(profile)
    if conn is None:
        return None
    try:
        rows = _messages(conn, since.timestamp())
        spend = conn.execute(
            "SELECT COALESCE(SUM(input_tokens + cache_read_tokens + cache_write_tokens + output_tokens), 0), "
            "COALESCE(SUM(estimated_cost_usd), 0), "
            "COALESCE(SUM(CASE WHEN task = 'compression' THEN estimated_cost_usd ELSE 0 END), 0) "
            "FROM session_model_usage WHERE last_seen >= ?", (since.timestamp(),)).fetchone()
    finally:
        conn.close()
    asked = summaries = tasks = unanswered = tool_calls = 0
    failing: Counter = Counter()
    answer_seconds, days = [], set()
    open_turn = None  # (chat, asked at, last answer at) of the person's message being answered
    for chat, role, content, calls, tool, stamp, _ in rows:
        if role == "user":
            if _is_summary(content):
                summaries += 1
                continue
            if open_turn:
                answer_seconds, unanswered = _close(open_turn, answer_seconds, unanswered)
            open_turn = None
            if _is_task(content):
                tasks += 1
                continue
            asked += 1
            days.add(datetime.fromtimestamp(stamp).date())
            open_turn = (chat, stamp, None)
        elif role == "assistant" and not _is_summary(content):
            if open_turn and open_turn[0] == chat and (content.strip() or calls):
                open_turn = (chat, open_turn[1], stamp)
        elif role == "tool":
            tool_calls += 1
            if TOOL_FAILED.search(content[:600]):
                failing[tool] += 1
    if open_turn:
        answer_seconds, unanswered = _close(open_turn, answer_seconds, unanswered)
    ordered = sorted(answer_seconds)
    return {
        "messages": asked, "days": len(days), "system_tasks": tasks, "unanswered": unanswered,
        "median_seconds": round(statistics.median(ordered), 1) if ordered else None,
        "p90_seconds": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 1) if ordered else None,
        "tool_calls": tool_calls, "tool_errors": sum(failing.values()), "failing_tools": dict(failing.most_common(5)),
        "summaries": summaries, "tokens": int(spend[0]), "usd": round(spend[1], 3),
        "summary_usd": round(spend[2], 3),
    }


def _close(turn: tuple, answer_seconds: list[float], unanswered: int) -> tuple[list[float], int]:
    _, asked_at, answered_at = turn
    if answered_at is None:
        return answer_seconds, unanswered + 1
    if 0 <= answered_at - asked_at < MAX_ANSWER_SECONDS:
        answer_seconds.append(answered_at - asked_at)
    return answer_seconds, unanswered


def masked(name: str) -> str:
    return " ".join(w if len(w) < 3 else f"{w[0]}{'*' * (len(w) - 2)}{w[-1]}" for w in name.split())


def survey(cfg: BotConfig, days: int) -> list[dict]:
    """The captain, then each active friend: their numbers plus what they and the citation check flagged."""
    since = _now() - timedelta(days=days)
    people = [("captain", cfg.hermes_profile, cfg.core.data_dir)]
    people += [(masked(f.nombre), amigos.profile_name(f), amigos.folder(cfg, f)) for f in amigos.active(cfg)]
    found = []
    for who, profile, data_dir in people:
        numbers = measure(profile, since)
        if numbers is None:
            continue
        flagged = Counter(e.get("kind") for e in events(data_dir, since))
        found.append({"who": who, **numbers, "reports": flagged["feedback"], "citations_fixed": flagged["citation"]})
    return found


def feedback(cfg: BotConfig, days: int) -> list[dict]:
    since = _now() - timedelta(days=days)
    people = [("captain", cfg.core.data_dir)] + [(masked(f.nombre), amigos.folder(cfg, f)) for f in amigos.active(cfg)]
    found = [{"who": who, **e} for who, data_dir in people for e in events(data_dir, since) if e.get("kind") == "feedback"]
    return sorted(found, key=lambda e: e.get("at") or "")


# -- «/mal» ---------------------------------------------------------------------------------------

def _last_turn(profile: str) -> dict | None:
    """The person's latest message and what Vinci answered to it."""
    conn = _connect(profile)
    if conn is None:
        return None
    try:
        rows = _messages(conn, 0)
    finally:
        conn.close()
    asked = [i for i, row in enumerate(rows)
             if row[1] == "user" and not _is_summary(row[2]) and not _is_task(row[2])
             and not STAMP.sub("", row[2]).lstrip().lower().startswith("/mal")]
    if not asked:
        return None
    start = max(asked, key=lambda i: rows[i][5])
    chat, _, ask, _, _, asked_at, session = rows[start]
    tools, reply = [], ""
    for other, role, content, calls, _, stamp, _ in rows[start + 1:]:
        if other != chat or (role == "user" and not _is_summary(content)):
            break
        # After a summary the new session repeats older answers with the time of the summary: the last one is his.
        if role == "assistant" and not _is_summary(content) and stamp >= asked_at:
            tools += calls
            reply = content.strip() or reply
    return {"session": session, "ask": STAMP.sub("", ask).strip()[:ASK_KEPT], "reply": reply[:REPLY_KEPT],
            "tools": tools}


def report_problem(cfg: BotConfig, profile: str, note: str) -> tuple[str, bool]:
    """«/mal [what was wrong]»: keeps the person's last message and Vinci's answer for whoever maintains it, and
    returns the reply and whether there was something to keep. `cfg` is the person's own, so the report lands in
    their data folder."""
    note = " ".join((note or "").split())[:NOTE_KEPT]
    turn = _last_turn(profile)
    if turn is None and not note:
        return "No encuentro una respuesta mía reciente que anotar. Cuéntame qué pasó: /mal <qué estuvo mal>", False
    record(cfg.core.data_dir, "feedback", note=note, **(turn or {}))
    text = ("📝 Anotado. Le paso a quien me mantiene tu último mensaje y lo que te contesté, para que lo arregle."
            if turn else "📝 Anotado. Se lo paso a quien me mantiene.")
    return (text if note else f"{text} Si me dices qué estuvo mal, mejor: «/mal la fecha estaba equivocada»."), True


# -- the report -----------------------------------------------------------------------------------

def _seconds(value: float | None) -> str:
    return "–" if value is None else f"{value:.0f} s"


def render(people: list[dict], days: int) -> str:
    lines = [f"quality, last {days} days",
             f"{'who':<16}{'msgs':>5}{'days':>5}{'median':>8}{'p90':>7}{'tools':>7}{'failed':>10}{'summaries':>14}"
             f"{'no reply':>9}{'tokens':>9}{'usd':>7}{'/mal':>5}{'cites fixed':>12}"]
    for p in people:
        failed = f"{p['tool_errors']} ({100 * p['tool_errors'] / p['tool_calls']:.0f}%)" if p["tool_calls"] else "0"
        per_100 = f"{p['summaries']} ({100 * p['summaries'] / p['messages']:.0f}/100)" if p["messages"] else "0"
        lines.append(f"{p['who'][:15]:<16}{p['messages']:>5}{p['days']:>5}{_seconds(p['median_seconds']):>8}"
                     f"{_seconds(p['p90_seconds']):>7}{p['tool_calls']:>7}{failed:>10}{per_100:>14}"
                     f"{p['unanswered']:>9}{p['tokens'] / 1e6:>8.1f}M{p['usd']:>7.2f}{p['reports']:>5}"
                     f"{p['citations_fixed']:>12}")
    for p in people:
        if p["failing_tools"]:
            lines.append(f"{p['who']}: failing tools: "
                         + ", ".join(f"{tool} ×{n}" for tool, n in p["failing_tools"].items()))
        if p["summary_usd"] and p["usd"]:
            lines.append(f"{p['who']}: summarizing the chat took {100 * p['summary_usd'] / p['usd']:.0f}% of the spend")
    if any(p["reports"] for p in people):
        lines.append("reports: vinci-check quality --feedback")
    return "\n".join(lines)


def render_feedback(reports: list[dict]) -> str:
    if not reports:
        return "no «/mal» reports in this period"
    blocks = []
    for r in reports:
        tools = f"  (tools: {', '.join(r['tools'])})" if r.get("tools") else ""
        blocks.append(f"— {r.get('at', '?')} {r['who']}: {r.get('note') or '(no note)'}\n"
                      f"  asked: {r.get('ask') or '?'}\n  answered: {r.get('reply') or '?'}{tools}")
    return "\n".join(blocks)
