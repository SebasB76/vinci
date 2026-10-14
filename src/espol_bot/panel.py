"""The captain's admin panel: one page with the gateway, the scheduled jobs, model spend and recent turns of every
Hermes profile. Read-only, no model, no Canvas call. It listens on 127.0.0.1 only; Tailscale Serve publishes it
to the captain's own devices (docs/guia/panel.md).

Friends' chats and WhatsApp groups show only timings and tool names: their text stays out of the panel."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aula_core import timefmt
from espol_bot import health
from espol_bot.config import BotConfig, hermes_root

PAGE = Path(__file__).with_name("panel.html")
STUCK = timedelta(minutes=5)       # a turn still holding its lease after this is reported as stuck
DAYS = 14
ERROR_WINDOW = timedelta(hours=24)
LOG_TAIL = 2_000_000               # bytes of each errors.log read; Hermes rotates it, but not often
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (WARNING|ERROR|CRITICAL) ([\w.]+): (.*)")


def _db(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def _when(stamp: float | None) -> str | None:
    return timefmt.iso(datetime.fromtimestamp(stamp, timezone.utc)) if stamp else None


def _kind(cfg: BotConfig, name: str) -> str:
    if name == cfg.hermes_profile:
        return "vinci"
    if name.startswith("amigo-"):
        return "amigo"
    if name.startswith(f"{cfg.hermes_profile}-"):
        return "materia"
    return "otro"


def _profiles(cfg: BotConfig, root: Path) -> list[dict]:
    found = []
    for path in sorted((root / "profiles").glob("*")):
        if (path / "state.db").exists():
            found.append({"name": path.name, "kind": _kind(cfg, path.name), "path": path,
                          "parked": (path / "gateway.parked").exists()})
    return found


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # another user's process (the Docker image runs Hermes as its own user)
        return True
    return True


def _gateway(root: Path) -> dict:
    try:
        state = json.loads((root / "gateway_state.json").read_text())
    except (OSError, ValueError):
        state = {}
    gateway = {"state": state.get("gateway_state") or "desconocido", "pid": state.get("pid"),
               "alive": _alive(state.get("pid")), "updated_at": state.get("updated_at"),
               "active_agents": state.get("active_agents") or 0, "version": state.get("code_version"),
               "served": state.get("served_profiles") or [],
               "platforms": {name: {k: p.get(k) for k in ("state", "error_message", "needs_attention",
                                                          "retrying_since", "updated_at")}
                             for name, p in (state.get("platforms") or {}).items()}}
    try:  # only where the gateway is a systemd user service (the laptop), never required
        out = subprocess.run(["systemctl", "--user", "show", "hermes-gateway", "-p", "NRestarts",
                              "-p", "ActiveEnterTimestamp"], capture_output=True, text=True, timeout=5).stdout
        props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        gateway["restarts"] = int(props["NRestarts"]) if props.get("NRestarts", "").isdigit() else None
        gateway["since"] = props.get("ActiveEnterTimestamp") or None
    except (OSError, subprocess.SubprocessError):
        pass
    return gateway


def _jobs(profile: dict) -> list[dict]:
    try:
        data = json.loads((profile["path"] / "cron" / "jobs.json").read_text())
    except (OSError, ValueError):
        return []
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    return [{"profile": profile["name"], "name": j.get("name"), "schedule": j.get("schedule_display"),
             "status": j.get("last_status"), "last_run": j.get("last_run_at"), "next_run": j.get("next_run_at"),
             "streak": j.get("failure_streak") or 0, "error": (j.get("last_error") or "")[:300],
             "paused": bool(j.get("paused_at")) or j.get("enabled") is False}
            for j in jobs if isinstance(j, dict)]


def _usage(conn: sqlite3.Connection, profile: str, since: float, tz) -> list[dict]:
    rows = conn.execute("SELECT model, last_seen, api_call_count, input_tokens, output_tokens, cache_read_tokens, "
                        "cache_write_tokens, estimated_cost_usd FROM session_model_usage WHERE last_seen >= ?",
                        (since,)).fetchall()
    # a session spanning midnight counts on the day of its last call
    return [{"profile": profile, "model": model,
             "day": datetime.fromtimestamp(seen, timezone.utc).astimezone(tz).date().isoformat(),
             "calls": calls, "input": i, "output": o, "cache_read": cr, "cache_write": cw, "usd": usd or 0.0}
            for model, seen, calls, i, o, cr, cw, usd in rows]


def _private(profile: dict, chat_type: str | None) -> bool:
    """Whether a session's text may show: the captain's own chats only, never a friend's or a group's."""
    return profile["kind"] in ("vinci", "materia") and chat_type != "group"


def _sessions(conn: sqlite3.Connection, profile: dict, now: float, limit: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, source, chat_type, started_at, COALESCE(last_activity_at, started_at), message_count, "
        "tool_call_count, input_tokens + output_tokens + cache_read_tokens + cache_write_tokens, estimated_cost_usd, "
        "model FROM sessions ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT ?", (limit,)).fetchall()
    found = []
    for sid, source, chat_type, started, last, messages, tools, tokens, usd, model in rows:
        asked = conn.execute("SELECT MAX(timestamp) FROM messages WHERE session_id = ? AND role = 'user'",
                             (sid,)).fetchone()[0]
        answered = conn.execute("SELECT MAX(timestamp) FROM messages WHERE session_id = ? AND role = 'assistant' "
                                "AND timestamp >= ?", (sid, asked or 0)).fetchone()[0] if asked else None
        found.append({"profile": profile["name"], "kind": profile["kind"], "id": sid, "source": source,
                      "chat_type": chat_type, "started": _when(started), "last": _when(last), "last_ts": last,
                      "messages": messages or 0, "tools": tools or 0, "tokens": tokens or 0, "usd": usd or 0.0,
                      "model": model, "reply_seconds": round(answered - asked, 1) if asked and answered else None,
                      "unanswered": bool(asked and not answered and now - asked > STUCK.total_seconds()),
                      "readable": _private(profile, chat_type)})
    return found


def _leases(conn: sqlite3.Connection, profile: str, now: float) -> list[dict]:
    rows = conn.execute("SELECT conversation_id, acquired_at FROM session_turn_leases WHERE expires_at > ?",
                        (now,)).fetchall()
    return [{"profile": profile, "conversation": cid[-12:], "seconds": round(now - acquired),
             "stuck": now - acquired > STUCK.total_seconds()} for cid, acquired in rows]


def _signature(logger: str, message: str) -> str:
    text = re.sub(r"\d+", "#", message)
    text = re.sub(r"\{.*", "{…}", text)  # provider error bodies differ in ids only
    return f"{logger}: {text[:140]}"


def _errors(logs: list[tuple[str, Path]], since: datetime) -> list[dict]:
    groups: dict[str, dict] = {}
    floor = since.strftime("%Y-%m-%d %H:%M:%S")
    for source, path in logs:
        try:
            with path.open("rb") as fh:
                fh.seek(max(0, path.stat().st_size - LOG_TAIL))
                lines = fh.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            match = LOG_LINE.match(line)
            if not match or match.group(1) < floor:
                continue
            stamp, level, logger, message = match.groups()
            key = _signature(logger, message)
            group = groups.setdefault(key, {"signature": key, "level": level, "count": 0, "last": stamp,
                                            "sources": set(), "sample": message[:400]})
            group["count"] += 1
            group["sources"].add(source)
            if stamp >= group["last"]:
                group["last"], group["sample"] = stamp, message[:400]
            if level in ("ERROR", "CRITICAL"):
                group["level"] = level
    found = sorted(groups.values(), key=lambda g: g["last"], reverse=True)
    found.sort(key=lambda g: g["level"] == "WARNING")  # errors first, each part newest first
    for group in found:
        group["sources"] = sorted(group["sources"])
    return found[:40]


def snapshot(cfg: BotConfig, now: datetime, root: Path | None = None) -> dict:
    root = root or hermes_root()
    tz = cfg.core.tz
    stamp = now.timestamp()
    start = (now.astimezone(tz) - timedelta(days=DAYS - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    profiles = _profiles(cfg, root)
    usage, sessions, leases, jobs = [], [], [], []
    for profile in profiles:
        jobs += [] if profile["parked"] else _jobs(profile)
        conn = _db(profile["path"] / "state.db")
        if conn is None:
            continue
        try:
            usage += _usage(conn, profile["name"], start.timestamp(), tz)
            sessions += _sessions(conn, profile, stamp, 15)
            leases += _leases(conn, profile["name"], stamp)
        except sqlite3.Error:  # a Hermes upgrade mid-migration: show the rest
            pass
        finally:
            conn.close()
    sessions.sort(key=lambda s: s["last_ts"] or 0, reverse=True)
    conn = health.open_readonly(cfg.core.db_path)
    try:
        checks = [{"name": c.name, "level": c.level, "detail": c.detail, "fix": c.chat_fix or c.fix}
                  for c in health.checks(cfg, conn, now)]
    finally:
        if conn is not None:
            conn.close()
    logs = [("gateway", root / "logs" / "errors.log"),
            *((p["name"], p["path"] / "logs" / "errors.log") for p in profiles)]
    local_now = now.astimezone().replace(tzinfo=None)  # Hermes logs in the machine's local time
    return {"now": timefmt.iso(now), "today": now.astimezone(tz).date().isoformat(), "days": DAYS,
            "gateway": _gateway(root), "checks": checks, "jobs": jobs, "usage": usage,
            "sessions": sessions[:30], "leases": leases,
            "errors": _errors(logs, local_now - ERROR_WINDOW),
            "profiles": [{k: p[k] for k in ("name", "kind", "parked")} for p in profiles],
            "model": f"{cfg.hermes_provider}/{cfg.hermes_model}"}


def session_detail(cfg: BotConfig, profile_name: str, session_id: str, root: Path | None = None) -> dict | None:
    root = root or hermes_root()
    profile = next((p for p in _profiles(cfg, root) if p["name"] == profile_name), None)
    conn = _db(profile["path"] / "state.db") if profile else None
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT chat_type FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        readable = _private(profile, row[0])
        rows = conn.execute("SELECT role, content, tool_calls, tool_name, timestamp, finish_reason FROM messages "
                            "WHERE session_id = ? AND active = 1 ORDER BY id DESC LIMIT 80", (session_id,)).fetchall()
    finally:
        conn.close()
    steps = []
    for role, content, tool_calls, tool_name, stamp, finish in reversed(rows):
        calls = [c.get("function", {}).get("name") or c.get("name") for c in json.loads(tool_calls or "[]")
                 if isinstance(c, dict)]
        text = (content or "").strip()
        steps.append({"role": role, "at": _when(stamp), "ts": stamp, "tool": tool_name, "finish": finish,
                      "calls": [c for c in calls if c], "chars": len(text),
                      "text": (text[:1500] if role != "tool" else text[:400]) if readable else None})
    return {"profile": profile_name, "id": session_id, "readable": readable, "steps": steps}


def serve(cfg: BotConfig, port: int, host: str = "127.0.0.1") -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode(),
                       "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/estado":
                self._json(snapshot(cfg, datetime.now(timezone.utc)))
            elif url.path == "/api/sesion":
                query = parse_qs(url.query)
                found = session_detail(cfg, (query.get("perfil") or [""])[0], (query.get("id") or [""])[0])
                self._json(found if found else {"error": "no existe"}, 200 if found else 404)
            else:
                self._json({"error": "no existe"}, 404)

        def log_message(self, *args) -> None:  # every refresh would flood the journal
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Panel de Vinci en http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
