"""The agent's door into the panel: what a coding agent on the captain's PC needs to debug the live install without
the Coolify Terminal (`vinci-check remote`, espol_bot/remote.py). Logs, errors, health, recent turns, file reads and
writes under Hermes' home, and shell commands run as the panel's user (hermes in the container).

Every route lives under /agente/ and needs AGENT_KEY, a secret of its own: PANEL_KEY, which guests get, never opens
it, and neither does the panel's loopback owner. A request carries an HMAC of its time, a nonce, the method, the path
and the body's hash, so the key itself never crosses the proxy and a captured request cannot be replayed. Anything
else gets the panel's plain 404. Without AGENT_KEY in secrets.env, /agente/ does not exist.

Log and turn routes mask phone numbers, WhatsApp ids, friends' names and message text unless `raw=1`."""

from __future__ import annotations

import codecs
import hashlib
import hmac
import json
import os
import re
import secrets
import selectors
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aula_core.config import ConfigError, load_secret_values, update_secret_values
from espol_bot import amigos, panel
from espol_bot.config import BotConfig, hermes_root

KEY_SECRET = "AGENT_KEY"
HEADER = "X-Vinci-Agent"
SKEW = 120                    # seconds a signed request stays valid
MAX_BODY = 64 * 1024 * 1024
RUN_TIMEOUT, RUN_MAX = 300, 3600
FOLLOW_MAX = 3600
GREP_BYTES = 32 * 1024 * 1024   # grep reads this much of the log's end, then keeps the last n matches
TAIL_BYTES = 8 * 1024 * 1024
HEARTBEAT = 15                # an empty line now and then keeps proxies from closing a quiet stream
_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()

QUOTED = re.compile(r"""\b(msg|text|reply_to_text|caption|content)=('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")""")
USER = re.compile(r"\b(user(?:_name)?=)(.+?)(?= chat=| user_id=|,|$)")
WA_ID = re.compile(r"\+?\d{6,}(?=@(?:lid|s\.whatsapp\.net|c\.us|g\.us))")
STAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
ALL = "all"
AUDIT = "logs/remote-access.log"  # logs/agent.log is Hermes' own
PHONE = re.compile(r"(?<![\w./-])\+?\d{10,}(?![\w.])")


def signature(key: str, stamp: str, nonce: str, method: str, target: str, body: bytes) -> str:
    message = "\n".join((stamp, nonce, method.upper(), target, hashlib.sha256(body).hexdigest()))
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def new_key() -> str:
    key = secrets.token_urlsafe(32)
    update_secret_values({KEY_SECRET: key})
    return key


def remove_key() -> None:
    update_secret_values({}, remove=(KEY_SECRET,))


def _key() -> str:
    try:
        return load_secret_values().get(KEY_SECRET, "")
    except ConfigError:
        return ""


def authorized(headers, method: str, target: str, body: bytes, now: float | None = None) -> bool:
    key = _key()
    fields = dict(part.split("=", 1) for part in (headers.get(HEADER) or "").split(",") if "=" in part)
    stamp, nonce, given = fields.get("t", ""), fields.get("n", ""), fields.get("s", "")
    if not (key and stamp.isdigit() and 16 <= len(nonce) <= 64 and given):
        return False
    now = time.time() if now is None else now
    if abs(now - int(stamp)) > SKEW:
        return False
    if not hmac.compare_digest(given, signature(key, stamp, nonce, method, target, body)):
        return False
    with _nonce_lock:
        for old, seen in list(_nonces.items()):
            if now - seen > 2 * SKEW:
                del _nonces[old]
        if nonce in _nonces:
            return False
        _nonces[nonce] = now
    return True


def _initials(name: str) -> str:
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    return "".join(f"{w[0].upper()}." for w in words) or "?"


def _names(cfg: BotConfig) -> list[tuple[re.Pattern, str]]:
    try:
        friends = amigos.load(cfg)
    except (OSError, ValueError, ConfigError):
        return []
    found = []
    for friend in friends:
        full = friend.nombre.strip()
        for part in sorted({full, *full.split()}, key=len, reverse=True):
            if len(part) >= 3:
                found.append((re.compile(rf"(?<![\w-]){re.escape(part)}(?![\w-])", re.IGNORECASE),
                              _initials(full)))
    return sorted(found, key=lambda p: len(p[0].pattern), reverse=True)


def redact(line: str, names: list[tuple[re.Pattern, str]]) -> str:
    """A log line without what identifies a person: quoted message text becomes its length, numbers and WhatsApp
    ids keep their last 3 digits, known friends and the sender in `user=` become initials."""
    line = QUOTED.sub(lambda m: f"{m[1]}=<{len(m[2]) - 2} car.>", line)
    line = USER.sub(lambda m: m[1] + (m[2] if m[2].startswith(("uid:", "unknown")) or m[2][-3:].isdigit()
                                      else _initials(m[2])), line)
    for pattern, initials in names:
        line = pattern.sub(initials, line)
    line = WA_ID.sub(lambda m: f"…{m[0][-3:]}", line)
    return PHONE.sub(lambda m: f"…{m[0][-3:]}", line)


def _audit(root: Path, entry: str) -> None:
    (root / "logs").mkdir(parents=True, exist_ok=True)
    with (root / AUDIT).open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {entry}\n")


def _inside(root: Path, given: str) -> Path | None:
    """`given` as a path inside Hermes' home (absolute or relative to it), or None when it points outside."""
    path = Path(given) if given.startswith("/") else root / given
    path = path.resolve()
    return path if path == root.resolve() or path.is_relative_to(root.resolve()) else None


def _log_files(cfg: BotConfig, root: Path) -> dict[str, Path]:
    files = {"gateway": root / "logs" / "gateway.log", "errors": root / "logs" / "errors.log",
             "bot": cfg.core.data_dir / "bot.log", "remote-access": root / AUDIT}
    for path in sorted(root.glob("logs/*.log")) + sorted(root.glob("profiles/*/logs/*.log")):
        name = str(path.relative_to(root))
        files.setdefault(name.removeprefix("logs/").removesuffix(".log")
                         if name.startswith("logs/") else name.removeprefix("profiles/").replace("/logs/", "/")
                         .removesuffix(".log"), path)
    return files


def _tail(path: Path, lines: int, limit: int) -> tuple[list[str], int]:
    """The last `lines` lines of a log, read from at most its last `limit` bytes, and the file's size."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - limit))
        data = fh.read(size - fh.tell())
    if size > limit:
        data = data[data.find(b"\n") + 1:]  # the first line is cut
    found = data.decode("utf-8", errors="replace").splitlines()
    return found[-lines:] if lines else [], size


class Request:
    """One /agente/ request on panel.serve's handler."""

    def __init__(self, handler, cfg: BotConfig, body: bytes):
        self.h, self.cfg, self.body = handler, cfg, body
        url = urlparse(handler.path)
        self.path = url.path.removeprefix("/agente/").strip("/")
        self.query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        self.root = hermes_root()
        self.raw = self.query.get("raw") == "1"

    def json(self, data, status: int = 200) -> None:
        self.h._json(data, status)

    def _stream_start(self, kind: str) -> None:
        self.h.send_response(200)
        self.h.send_header("Content-Type", kind)
        self.h.send_header("Cache-Control", "no-store")
        self.h.send_header("X-Accel-Buffering", "no")
        self.h.send_header("Connection", "close")
        self.h.end_headers()
        self.h.close_connection = True

    def _emit(self, data: dict) -> None:
        self.h.wfile.write((json.dumps(data, ensure_ascii=False) + "\n").encode())
        self.h.wfile.flush()

    def handle(self) -> None:
        method = self.h.command
        route = (method, self.path)
        if route == ("GET", "estado"):
            self.status()
        elif route == ("GET", "logs"):
            self.logs()
        elif route == ("GET", "turnos"):
            self.turns()
        elif route == ("POST", "run"):
            self.run()
        elif route == ("GET", "archivo"):
            self.read_file()
        elif route == ("PUT", "archivo"):
            self.write_file()
        else:
            self.json({"error": "no existe"}, 404)

    def status(self) -> None:
        state = panel.snapshot(self.cfg, datetime.now(timezone.utc), self.root)
        state["viewer"] = "agent"
        if not self.raw:
            names = _names(self.cfg)
            for group in state["errors"]:
                group["sample"] = redact(group["sample"] or "", names)
            for person in state["people"]:
                person["name"] = _initials(person["name"]) if person["friend"] else person["name"]
        self.json(state)

    def logs(self) -> None:
        files = _log_files(self.cfg, self.root)
        name = self.query.get("f")
        if not name:
            self.json({k: {"path": str(p), "bytes": p.stat().st_size} for k, p in files.items() if p.exists()})
            return
        if name == ALL:  # Hermes logs each message in the gateway.log of the profile that answers it
            sources = [(label, path) for label, path in
                       [("gateway", files["gateway"]), *((p.parent.parent.name, p)
                                                         for p in sorted(self.root.glob("profiles/*/logs/gateway.log")))]
                       if path.is_file()]
        else:
            path = files.get(name) or _inside(self.root, name)
            sources = [(None, path)] if path is not None and path.is_file() else []
        if not sources:
            self.json({"error": f"no hay log {name!r}",
                       "logs": [ALL, *sorted(k for k, p in files.items() if p.exists())]}, 404)
            return
        try:
            pattern = re.compile(self.query["grep"], re.IGNORECASE) if self.query.get("grep") else None
        except re.error as exc:
            self.json({"error": f"grep inválido: {exc}"}, 400)
            return
        lines = min(int(self.query.get("n") or 200), 100_000)
        names = [] if self.raw else _names(self.cfg)

        def shown(label: str | None, batch: list[str]) -> list[tuple[str, str]]:
            """(timestamp, line) of the lines kept; a traceback line takes the time of the line above it."""
            found, stamp = [], ""
            for line in batch:
                stamp = line[:23] if STAMP.match(line) else stamp
                if not pattern or pattern.search(line):
                    text = line if self.raw else redact(line, names)
                    found.append((stamp, f"[{label}] {text}" if label else text))
            return found

        offsets, merged = {}, []
        for index, (label, path) in enumerate(sources):
            batch, offsets[path] = _tail(path, 10**9 if pattern else lines, GREP_BYTES if pattern else TAIL_BYTES)
            merged += [(stamp, index, n, text) for n, (stamp, text) in enumerate(shown(label, batch))]
        merged.sort()
        self._stream_start("text/plain; charset=utf-8")
        self.h.wfile.write("".join(f"{row[3]}\n" for row in merged[-lines:]).encode())
        self.h.wfile.flush()
        if self.query.get("follow") != "1":
            return
        inodes = {path: path.stat().st_ino for _, path in sources}
        end, quiet = time.monotonic() + FOLLOW_MAX, time.monotonic()
        try:
            while time.monotonic() < end:
                time.sleep(1)
                for label, path in sources:
                    stat = path.stat() if path.exists() else None
                    if stat is None:
                        continue
                    if stat.st_ino != inodes[path] or stat.st_size < offsets[path]:  # rotated
                        inodes[path], offsets[path] = stat.st_ino, 0
                    if stat.st_size > offsets[path]:
                        with path.open("rb") as fh:
                            fh.seek(offsets[path])
                            data = fh.read(stat.st_size - offsets[path])
                        complete = data.rfind(b"\n") + 1
                        offsets[path] += complete
                        out = shown(label, data[:complete].decode("utf-8", errors="replace").splitlines())
                        if out:
                            self.h.wfile.write("".join(f"{text}\n" for _, text in out).encode())
                            self.h.wfile.flush()
                            quiet = time.monotonic()
                if time.monotonic() - quiet > HEARTBEAT:
                    self.h.wfile.write(b"\n")
                    self.h.wfile.flush()
                    quiet = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def turns(self) -> None:
        name = self.query.get("perfil") or self.cfg.hermes_profile
        profile = next((p for p in panel._profiles(self.cfg, self.root) if p["name"] == name), None)
        conn = panel._db(profile["path"] / "state.db") if profile else None
        if conn is None:
            self.json({"error": f"no hay perfil {name!r}",
                       "perfiles": [p["name"] for p in panel._profiles(self.cfg, self.root)]}, 404)
            return
        limit = min(int(self.query.get("n") or 30), 500)
        where, args = "", []
        if self.query.get("sesion"):
            where, args = "WHERE m.session_id = ?", [self.query["sesion"]]
        try:
            rows = conn.execute(
                "SELECT m.session_id, s.source, s.chat_type, m.role, m.content, m.tool_calls, m.tool_name, "
                f"m.timestamp, m.finish_reason FROM messages m JOIN sessions s ON s.id = m.session_id {where} "
                "ORDER BY m.id DESC LIMIT ?", (*args, limit)).fetchall()
        finally:
            conn.close()
        names = _names(self.cfg)
        found = []
        for sid, source, chat_type, role, content, tool_calls, tool_name, stamp, finish in reversed(rows):
            try:
                calls = [c.get("function", {}).get("name") or c.get("name") for c in json.loads(tool_calls or "[]")
                         if isinstance(c, dict)]
            except ValueError:
                calls = []
            text = (content or "").strip()
            readable = self.raw or panel._private(profile, chat_type)
            found.append({"session": sid, "source": source, "chat_type": chat_type, "role": role,
                          "at": panel._when(stamp), "tool": tool_name, "calls": [c for c in calls if c],
                          "finish": finish, "chars": len(text),
                          "text": (text if self.raw else redact(text[:2000], names)) if readable else None})
        self.json({"profile": name, "kind": profile["kind"], "turns": found})

    def run(self) -> None:
        try:
            order = json.loads(self.body or b"{}")
            command = str(order["sh"])
        except (ValueError, KeyError, TypeError):
            self.json({"error": 'falta {"sh": "<comando>"}'}, 400)
            return
        timeout = max(1, min(float(order.get("timeout") or RUN_TIMEOUT), RUN_MAX))
        env = {**os.environ, "HOME": os.environ.get("HOME") or str(self.root), "PYTHONUNBUFFERED": "1",
               "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '/usr/bin:/bin')}"}
        started = time.monotonic()
        proc = subprocess.Popen(["/bin/sh", "-c", command], cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        self._stream_start("application/x-ndjson")
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        selector = selectors.DefaultSelector()
        selector.register(proc.stdout, selectors.EVENT_READ)
        reason, last = None, time.monotonic()
        try:
            while True:
                if time.monotonic() - started > timeout:
                    reason = f"timeout de {timeout:.0f} s"
                    break
                ready = selector.select(0.5)
                if ready:
                    data = os.read(proc.stdout.fileno(), 65536)
                    if not data:
                        break
                    self._emit({"o": decoder.decode(data)})
                    last = time.monotonic()
                elif proc.poll() is not None:
                    break  # a background child may keep the pipe open: the command itself is done
                elif time.monotonic() - last > HEARTBEAT:
                    self._emit({})
                    last = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            reason = "el cliente se desconectó"
        finally:
            selector.close()
        if proc.poll() is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                    proc.wait(5)
                    break
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    continue
        code = proc.wait()
        proc.stdout.close()
        took = time.monotonic() - started
        _audit(self.root, f"run exit={code} {took:.1f}s{' (' + reason + ')' if reason else ''} sh={command[:300]!r}")
        try:
            self._emit({"exit": code, "seconds": round(took, 1), **({"stopped": reason} if reason else {})})
        except (BrokenPipeError, ConnectionResetError):
            pass

    def read_file(self) -> None:
        path = _inside(self.root, self.query.get("ruta") or "")
        if path is None or not path.is_file():
            self.json({"error": "no existe o está fuera de " + str(self.root)}, 404)
            return
        _audit(self.root, f"get {path}")
        self.h._send(200, path.read_bytes(), "application/octet-stream")

    def write_file(self) -> None:
        path = _inside(self.root, self.query.get("ruta") or "")
        if path is None or path == self.root.resolve() or path.is_dir():
            self.json({"error": "ruta fuera de " + str(self.root)}, 400)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, prefix=f".{path.name}.") as tmp:
            tmp.write(self.body)
        os.chmod(tmp.name, mode)
        os.replace(tmp.name, path)
        _audit(self.root, f"put {path} {len(self.body)} bytes")
        self.json({"ok": True, "path": str(path), "bytes": len(self.body)})


def handle(handler, cfg: BotConfig) -> None:
    """Answer one /agente/ request, or the panel's 404 when it is not a valid signed one."""
    length = int(handler.headers.get("Content-Length") or 0)
    if length > MAX_BODY:
        handler._json({"error": "no existe"}, 404)
        return
    body = handler.rfile.read(length) if length else b""
    if not authorized(handler.headers, handler.command, handler.path, body):
        handler._json({"error": "no existe"}, 404)
        return
    try:
        Request(handler, cfg, body).handle()
    except (BrokenPipeError, ConnectionResetError):
        pass
    except (OSError, sqlite3.Error, ValueError) as exc:
        handler._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
