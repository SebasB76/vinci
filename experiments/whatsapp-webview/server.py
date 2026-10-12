"""Backend of the WhatsApp webview experiment: the form page, its one-time sessions and the bot's confirmation.

Two listeners. The public one (the only port a tunnel may publish) serves the page and three routes guarded by the
session's capability. The admin one stays on 127.0.0.1 behind a bearer token: it creates a session for the single
recipient given at start and sends the opening message through the bridge's experiment route. The capability only
travels in that message's URL fragment, so neither the tunnel nor this server's log ever sees it in a path.

«Guardar» is the only completion: a submission is stored with its confirmation in one transaction, and a worker
delivers the confirmation to the same chat through the bridge's /send, retrying until the bridge takes it. A
bridge that sends but loses its answer makes a retry send twice: delivery is at least once, never exactly once.

Usage:
  server.py serve --public-url https://….trycloudflare.com --recipient 5939… [--bridge URL] [--state DIR]
  server.py open --variant cta_url [--ttl-seconds 1800]
  server.py report
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
PAGE = HERE / "page"
DEFAULT_STATE = Path.home() / ".local" / "state" / "vinci-webview-experiment"
VARIANTS = ("plain_url", "cta_url", "cta_url_webview", "cta_url_webview_fork", "open_webview")
EVENT_KINDS = ("load", "visible", "hidden", "pagehide")
SESSION_PATH = re.compile(r"^/api/demo/sessions/(r[a-z2-7]{8})/(submit|status|events)$")
SUBMISSION_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_VALUE = 200
MAX_BODY = 4096
RETRY_SECONDS = 2.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, capability_hash TEXT NOT NULL, chat_id TEXT NOT NULL, variant TEXT NOT NULL,
  open_message_id TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS submissions (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id), submission_id TEXT NOT NULL, value TEXT NOT NULL,
  received_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id), text TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT, delivered_at REAL, delivered_message_id TEXT);
CREATE TABLE IF NOT EXISTS events (
  session_id TEXT NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL, user_agent TEXT, framed INTEGER, opener INTEGER);
"""


def capability_hash(capability: str) -> str:
    return hashlib.sha256(capability.encode()).hexdigest()


def bridge_post(bridge: str, path: str, payload: dict, timeout: float = 30) -> dict:
    request = urllib.request.Request(f"{bridge.rstrip('/')}/{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def run(self, fn):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                result = fn(self._db)
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            return result


class Experiment:
    def __init__(self, store: Store, *, public_url: str, recipient: str, bridge: str):
        self.store = store
        self.public_url = public_url.rstrip("/")
        self.chat_id = f"{re.sub(r'[^0-9]', '', recipient)}@s.whatsapp.net"
        self.bridge = bridge
        self._wake = threading.Event()

    # -- admin ----------------------------------------------------------------------------------------

    def open_session(self, variant: str, ttl_seconds: float) -> dict:
        if variant not in VARIANTS:
            raise ValueError(f"unknown variant {variant}")
        session_id = "r" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz234567") for _ in range(8))
        capability = secrets.token_urlsafe(32)
        now = time.time()
        self.store.run(lambda db: db.execute(
            "INSERT INTO sessions (id, capability_hash, chat_id, variant, created_at, expires_at) VALUES (?,?,?,?,?,?)",
            (session_id, capability_hash(capability), self.chat_id, variant, now, now + ttl_seconds)))
        url = f"{self.public_url}/demo?s={session_id}#c={capability}"
        text = (f"🧪 Experimento de formulario (ejecución {session_id}, variante {variant}).\n"
                "Tócalo, escribe un texto de prueba y pulsa «Guardar». No escribas datos reales.")
        sent = bridge_post(self.bridge, "experiment/webview/send",
                           {"chatId": self.chat_id, "variant": variant, "url": url, "text": text})
        self.store.run(lambda db: db.execute("UPDATE sessions SET open_message_id = ? WHERE id = ?",
                                             (sent.get("messageId"), session_id)))
        return {"sessionId": session_id, "variant": variant, "messageId": sent.get("messageId"),
                "expiresAt": now + ttl_seconds}

    # -- public ---------------------------------------------------------------------------------------

    def _session(self, db, session_id: str, capability: str):
        row = db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        # One answer for an unknown session and a wrong capability, so the page cannot probe run ids.
        if row is None or not hmac.compare_digest(row["capability_hash"], capability_hash(capability or "")):
            raise HttpError(403, "capability")
        return row

    def status(self, session_id: str, capability: str) -> dict:
        def read(db):
            session = self._session(db, session_id, capability)
            saved = db.execute("SELECT submission_id FROM submissions WHERE session_id = ?", (session_id,)).fetchone()
            outbox = db.execute("SELECT delivered_at FROM outbox WHERE session_id = ?", (session_id,)).fetchone()
            return {"runId": session_id, "saved": saved is not None,
                    "confirmation": None if outbox is None else ("sent" if outbox["delivered_at"] else "pending"),
                    "expired": time.time() > session["expires_at"]}
        return self.store.run(read)

    def submit(self, session_id: str, capability: str, submission_id: str, value) -> dict:
        if not isinstance(submission_id, str) or not SUBMISSION_ID.fullmatch(submission_id):
            raise HttpError(400, "submissionId")
        value = value.strip() if isinstance(value, str) else ""
        if not value or len(value) > MAX_VALUE:
            raise HttpError(400, "value")

        def save(db):
            session = self._session(db, session_id, capability)
            saved = db.execute("SELECT submission_id FROM submissions WHERE session_id = ?", (session_id,)).fetchone()
            if saved is not None:
                if saved["submission_id"] != submission_id:
                    raise HttpError(409, "already saved")
                return False  # the page's retry of a submission already stored
            if time.time() > session["expires_at"]:
                raise HttpError(410, "expired")
            db.execute("INSERT INTO submissions VALUES (?,?,?,?)", (session_id, submission_id, value, time.time()))
            db.execute("INSERT INTO outbox (session_id, text) VALUES (?,?)",
                       (session_id, f"✅ Recibí el formulario de la ejecución {session_id}: «{value}». "
                                    "Quedó guardado en el servidor."))
            return True

        created = self.store.run(save)
        if created:
            self._wake.set()
        return {**self.status(session_id, capability), "duplicate": not created}

    def event(self, session_id: str, capability: str, kind, user_agent: str, framed, opener) -> None:
        if kind not in EVENT_KINDS:
            raise HttpError(400, "kind")
        self.store.run(lambda db: (self._session(db, session_id, capability), db.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            (session_id, kind, time.time(), user_agent[:300], int(bool(framed)), int(bool(opener))))))

    # -- confirmation worker --------------------------------------------------------------------------

    def deliver_pending(self) -> None:
        rows = self.store.run(lambda db: db.execute(
            "SELECT o.session_id, o.text, s.chat_id, s.open_message_id FROM outbox o JOIN sessions s "
            "ON s.id = o.session_id WHERE o.delivered_at IS NULL").fetchall())
        for row in rows:
            try:
                sent = bridge_post(self.bridge, "send", {"chatId": row["chat_id"], "message": row["text"],
                                                         "replyTo": row["open_message_id"]})
            except (OSError, ValueError) as exc:
                error = str(exc)[:200]
                self.store.run(lambda db: db.execute(
                    "UPDATE outbox SET attempts = attempts + 1, last_error = ? WHERE session_id = ?",
                    (error, row["session_id"])))
                continue
            self.store.run(lambda db: db.execute(
                "UPDATE outbox SET attempts = attempts + 1, last_error = NULL, delivered_at = ?, "
                "delivered_message_id = ? WHERE session_id = ?", (time.time(), sent.get("messageId"), row["session_id"])))

    def worker(self) -> None:
        while True:
            self._wake.wait(RETRY_SECONDS)
            self._wake.clear()
            try:
                self.deliver_pending()
            except Exception as exc:  # the worker must outlive one bad row
                print(f"worker: {exc.__class__.__name__}: {exc}", file=sys.stderr)


class HttpError(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


class _Handler(BaseHTTPRequestHandler):
    server_version = "webview-experiment"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Paths carry only the public run id; the capability lives in the fragment and in bodies.
        print(f"{self.server.name} {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}",
              file=sys.stderr)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                         "base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise HttpError(413, "too large")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise HttpError(400, "json") from None
        if not isinstance(body, dict):
            raise HttpError(400, "json")
        return body

    def _handle(self, fn) -> None:
        try:
            fn()
        except HttpError as exc:
            self._json(exc.status, {"error": exc.reason})
        except (urllib.error.URLError, OSError) as exc:
            self._json(502, {"error": f"bridge: {exc}"[:200]})
        except ValueError as exc:
            self._json(400, {"error": str(exc)})


class PublicHandler(_Handler):
    STATIC = {"/demo": ("index.html", "text/html; charset=utf-8"), "/demo.js": ("demo.js", "text/javascript"),
              "/demo.css": ("demo.css", "text/css")}

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in self.STATIC:
            name, content_type = self.STATIC[path]
            return self._send(200, (PAGE / name).read_bytes(), content_type)
        match = SESSION_PATH.match(path)
        if match and match[2] == "status":
            auth = self.headers.get("Authorization", "")
            capability = auth[7:] if auth.startswith("Bearer ") else ""
            return self._handle(lambda: self._json(200, self.server.experiment.status(match[1], capability)))
        self._json(404, {"error": "not found"})

    def do_POST(self):
        match = SESSION_PATH.match(urlsplit(self.path).path)
        if not match or match[2] == "status":
            return self._json(404, {"error": "not found"})

        def run():
            body = self._body()
            experiment: Experiment = self.server.experiment
            if match[2] == "submit":
                self._json(200, experiment.submit(match[1], body.get("capability"), body.get("submissionId"),
                                                  body.get("value")))
            else:
                experiment.event(match[1], body.get("capability"), body.get("kind"),
                                 self.headers.get("User-Agent", ""), body.get("framed"), body.get("opener"))
                self._json(200, {"ok": True})
        self._handle(run)


class AdminHandler(_Handler):
    def do_POST(self):
        if urlsplit(self.path).path != "/api/demo/sessions":
            return self._json(404, {"error": "not found"})
        token = self.headers.get("Authorization", "")
        if not hmac.compare_digest(token, f"Bearer {self.server.admin_token}"):
            return self._json(401, {"error": "admin token"})

        def run():
            body = self._body()
            self._json(200, self.server.experiment.open_session(str(body.get("variant")),
                                                                float(body.get("ttlSeconds") or 1800)))
        self._handle(run)


def _listen(handler, port: int, name: str, experiment: Experiment, admin_token: str = "") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.name, server.experiment, server.admin_token = name, experiment, admin_token
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def serve(args) -> None:
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    token_file = state / "admin-token"
    admin_token = secrets.token_urlsafe(24)
    token_file.write_text(admin_token)
    token_file.chmod(0o600)
    experiment = Experiment(Store(state / "experiment.sqlite"), public_url=args.public_url,
                            recipient=args.recipient, bridge=args.bridge)
    public = _listen(PublicHandler, args.port, "public", experiment)
    admin = _listen(AdminHandler, args.admin_port, "admin", experiment, admin_token)
    (state / "admin-port").write_text(str(admin.server_address[1]))
    print(f"public 127.0.0.1:{public.server_address[1]} admin 127.0.0.1:{admin.server_address[1]}", flush=True)
    experiment.worker()


def open_command(args) -> None:
    state = Path(args.state)
    port = (state / "admin-port").read_text().strip()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/demo/sessions",
        data=json.dumps({"variant": args.variant, "ttlSeconds": args.ttl_seconds}).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {(state / 'admin-token').read_text()}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(response.read().decode())
    except urllib.error.HTTPError as exc:
        sys.exit(f"{exc.code}: {exc.read().decode()}")


def report(args) -> None:
    db = sqlite3.connect(Path(args.state) / "experiment.sqlite")
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT s.id, s.variant, s.created_at, s.open_message_id IS NOT NULL AS sent,
               (SELECT group_concat(kind, ',') FROM events e WHERE e.session_id = s.id) AS events,
               (SELECT user_agent FROM events e WHERE e.session_id = s.id AND kind = 'load' ORDER BY at LIMIT 1) AS ua,
               (SELECT max(framed) FROM events e WHERE e.session_id = s.id) AS framed,
               sub.received_at, o.attempts, o.delivered_at
        FROM sessions s LEFT JOIN submissions sub ON sub.session_id = s.id LEFT JOIN outbox o ON o.session_id = s.id
        ORDER BY s.created_at""").fetchall()
    for row in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row["created_at"]))
        confirmation = "-" if row["attempts"] is None else (
            f"sent after {row['attempts']} attempt(s)" if row["delivered_at"] else f"pending ({row['attempts']})")
        print(f"{row['id']}  {row['variant']:<21} {stamp}  opened={'yes' if row['sent'] else 'no'}  "
              f"events={row['events'] or '-'}  framed={row['framed']}  saved={'yes' if row['received_at'] else 'no'}"
              f"  confirmation={confirmation}\n    ua={row['ua'] or '-'}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve")
    serve_parser.add_argument("--public-url", required=True)
    serve_parser.add_argument("--recipient", required=True, help="the only chat this server ever writes to")
    serve_parser.add_argument("--bridge", default="http://127.0.0.1:3000")
    serve_parser.add_argument("--port", type=int, default=8787)
    serve_parser.add_argument("--admin-port", type=int, default=8788)
    open_parser = commands.add_parser("open")
    open_parser.add_argument("--variant", required=True, choices=VARIANTS)
    open_parser.add_argument("--ttl-seconds", type=float, default=1800)
    commands.add_parser("report")
    args = parser.parse_args(argv)
    {"serve": serve, "open": open_command, "report": report}[args.command](args)


if __name__ == "__main__":
    main()
