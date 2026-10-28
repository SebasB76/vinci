"""The captain's admin panel: one page with the gateway, the scheduled jobs, model spend and recent turns of every
Hermes profile. Read-only, no model, no Canvas call. It listens on 127.0.0.1 only; Tailscale Funnel publishes it
(docs/guia/panel.md).

Two viewers. The captain, on his tailnet (Tailscale's identity headers) or on the machine itself, sees everything.
Anyone else reaches it through Funnel and gets a 404 unless they bring PANEL_KEY from secrets.env (the link
`--nueva-clave` prints); with it they see the same panel without any chat text. Friends' chats and WhatsApp groups
never show their text, not even to the captain."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aula_core import timefmt
from aula_core.config import ConfigError, load_secret_values, update_secret_values
from espol_bot import health
from espol_bot.config import BotConfig, hermes_root

PAGE = Path(__file__).with_name("panel.html")
STUCK = timedelta(minutes=5)       # a turn still holding its lease after this is reported as stuck
DAYS = 14
ERROR_WINDOW = timedelta(hours=24)
LOG_TAIL = 2_000_000               # bytes of each errors.log read; Hermes rotates it, but not often
KEY_SECRET = "PANEL_KEY"
COOKIE = "vinci_panel"
COOKIE_DAYS = 30
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
    rows = conn.execute("SELECT session_id, model, first_seen, last_seen, api_call_count, input_tokens, output_tokens, "
                        "cache_read_tokens, cache_write_tokens, estimated_cost_usd FROM session_model_usage "
                        "WHERE last_seen >= ?", (since,)).fetchall()
    first_day = _day(since, tz)
    found = []
    for sid, model, first, last, calls, i, o, cr, cw, usd in rows:
        for day, share in _call_days(conn, sid, first, last, tz).items():
            if day >= first_day:
                found.append({"profile": profile, "model": model, "day": day, "calls": calls * share,
                              "input": i * share, "output": o * share, "cache_read": cr * share,
                              "cache_write": cw * share, "usd": (usd or 0.0) * share})
    return found


def _day(stamp: float, tz) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).astimezone(tz).date().isoformat()


def _call_days(conn: sqlite3.Connection, session: str, first: float | None, last: float, tz) -> dict[str, float]:
    """How a session's spend splits over the days its calls happened: Hermes keeps one running total per session, so
    each day takes the share of the session's answers given that day. One that spans midnight is split, not put
    whole on its last day."""
    if first is None or _day(first, tz) == _day(last, tz):
        return {_day(last, tz): 1.0}
    days: dict[str, int] = {}
    for (stamp,) in conn.execute("SELECT timestamp FROM messages WHERE session_id = ? AND role = 'assistant'",
                                 (session,)):
        days[_day(stamp, tz)] = days.get(_day(stamp, tz), 0) + 1
    total = sum(days.values())
    return {day: n / total for day, n in days.items()} if total else {_day(last, tz): 1.0}


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


def snapshot(cfg: BotConfig, now: datetime, root: Path | None = None, *, guest: bool = False) -> dict:
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
    if guest:
        for session in sessions:
            session["readable"] = False
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
    errors = _errors(logs, local_now - ERROR_WINDOW)
    if guest:  # a log line may quote a message
        for group in errors:
            group["sample"] = None
    return {"viewer": "guest" if guest else "owner", "now": timefmt.iso(now),
            "today": now.astimezone(tz).date().isoformat(), "days": DAYS,
            "gateway": _gateway(root), "checks": checks, "jobs": jobs, "usage": usage,
            "sessions": sessions[:30], "leases": leases,
            "errors": errors,
            "profiles": [{k: p[k] for k in ("name", "kind", "parked")} for p in profiles],
            "model": f"{cfg.hermes_provider}/{cfg.hermes_model}"}


def session_detail(cfg: BotConfig, profile_name: str, session_id: str, root: Path | None = None, *,
                   guest: bool = False) -> dict | None:
    root = root or hermes_root()
    profile = next((p for p in _profiles(cfg, root) if p["name"] == profile_name), None)
    conn = _db(profile["path"] / "state.db") if profile else None
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT chat_type FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        readable = not guest and _private(profile, row[0])
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


def new_key() -> str:
    """A fresh PANEL_KEY in secrets.env; the link with the old one stops working at once."""
    key = secrets.token_urlsafe(32)
    update_secret_values({KEY_SECRET: key})
    return key


def public_url() -> str | None:
    """This machine's https://<name>.<tailnet>.ts.net, where Funnel serves the panel."""
    try:
        out = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=10).stdout
        name = (json.loads(out).get("Self") or {}).get("DNSName", "").rstrip(".")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return f"https://{name}" if name else None


def _current_key() -> str:
    try:
        return load_secret_values().get(KEY_SECRET, "")
    except ConfigError:
        return ""


def viewer(headers, cookies: dict[str, str], query_key: str | None) -> str | None:
    """"owner", "guest" or None (not allowed). Tailscale Serve sets the identity headers on tailnet requests and drops
    any a Funnel client sends; a request with no proxy headers at all came from this machine (or an SSH tunnel)."""
    if headers.get("Tailscale-Funnel-Request") is None:
        if headers.get("Tailscale-User-Login") or headers.get("X-Forwarded-For") is None:
            return "owner"
    key = _current_key()
    if not key:
        return None
    for given in (query_key, cookies.get(COOKIE)):
        if given and hmac.compare_digest(given.encode(), key.encode()):
            return "guest"
    return None


def serve(cfg: BotConfig, port: int, host: str = "127.0.0.1") -> None:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Robots-Tag", "noindex")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode(),
                       "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 (http.server's name)
            url = urlparse(self.path)
            query = parse_qs(url.query)
            cookies = dict(part.strip().split("=", 1) for part in (self.headers.get("Cookie") or "").split(";")
                           if "=" in part)
            who = viewer(self.headers, cookies, (query.get("k") or [None])[0])
            if who is None:  # the same answer as a missing page: nothing says a panel lives here
                self._json({"error": "no existe"}, 404)
            elif "k" in query:  # keep the key out of the address bar and the history
                self.send_response(303)
                if who == "guest":
                    self.send_header("Set-Cookie", f"{COOKIE}={query['k'][0]}; Max-Age={COOKIE_DAYS * 86400}; "
                                                   "Path=/; HttpOnly; Secure; SameSite=Strict")
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif url.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/estado":
                self._json(snapshot(cfg, datetime.now(timezone.utc), guest=who == "guest"))
            elif url.path == "/api/sesion":
                found = session_detail(cfg, (query.get("perfil") or [""])[0], (query.get("id") or [""])[0],
                                       guest=who == "guest")
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
