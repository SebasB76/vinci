"""Local stand-ins for Canvas, Hermes' WhatsApp bridge and the other services Vinci reaches, used only by the E2E test.

FakeCanvas serves the recorded fixtures under fixtures/canvas/<state>/ (or another set) the way
Canvas does: Bearer auth, access-token creation/deletion,
`Link` pagination (capped at 2 items per page so the client must follow it),
`X-Rate-Limit-Remaining`, one 429 to exercise backoff, a course whose Files tab
is hidden (401 unauthorized), and file downloads.
API paths added to `failing` answer 503 until removed (a resource that keeps failing), and a
file in `slow_downloads` takes that many seconds to download.
It answers 405 to anything but GET and records every request. `{{WEB}}` in a fixture is the
FakeWeb server's address.

FakeWeb stands in for the public internet a course links to (a professor's own page): it serves
fixtures/web/ to anyone, with no token, and records every request with its headers. Reached through
`[test] link_hosts`, it also plays Google and SharePoint for the links the fixtures carry, the way
they answer an anonymous request: a Google Doc shared with anyone exports as PDF (after the 307 to
googleusercontent.com), one that is not answers 401 with Google's «you need access» page, a Drive
file downloads after the virus-scan page Drive shows before a big file, and a SharePoint share that
only ESPOL accounts may open sends to login.microsoftonline.com. The first hop of each sets a cookie,
as Google's does, so a client that keeps cookies would send it on the next one.

Tripwire stands where the Telegram Bot API would be and records any request: Vinci lives on WhatsApp only.

FakeWhatsApp stands in for Hermes' WhatsApp bridge (bridge.js, a Baileys client on localhost): Hermes adopts it as
a bridge already running, takes what people write from GET /messages and records every message it sends.

FakeWhatsApp also takes POST /send-url-button, the route Vinci adds to the bridge (hermes/whatsapp/url_button.js);
with "send-url-button" in `missing` it answers 404, as Hermes' own bridge.js does.

FakeRelay stands in for Vinci's relay on Cloudflare Workers (relay/worker.js), with its API: a page posts to
/m/<mailbox>, Vinci's PC reads /inbox (all of it, or one mailbox's) and deletes with /ack, both with the relay's key;
the PC puts a page's status at /s/<mailbox> with the key and the page reads it back without one. It answers CORS as
the Worker does, for a page opened in a real browser.

FakePortal stands in for ESPOL's Académico (www.academico.espol.edu.ec, through `[test] link_hosts`), as ASP.NET Web
Forms behaves: a session cookie, a fresh __VIEWSTATE and __EVENTVALIDATION in every form that the next post must send
back (a stale or foreign one is a 500, as a broken viewstate MAC is), login.aspx in two steps (user name; then
password and a BotDetect CAPTCHA whose image must be fetched with the same cookie), a forms-auth cookie, and the
pages under /UI/InformacionAcademica/ in the shapes the real ones have, behind a 302 to login.aspx without it:
«Información General» with the student's card (ID, name, photo) and the career's GPA and progress in «Label:» rows;
the history with «Año Termino» and «Prom.» columns; the credits under a card with the matrícula and name; the grades
and the class timetable empty until «Consultar» is pressed with a year and a term typed in, the grades in a table
with two header rows; the exam timetable with them filled in and a parcial/final/mejoramiento drop-down, empty until
«Consultar» too; both timetables as a half-hour grid that leaves out empty hours and whose classes span rows; and a
Presentar(...) call with each subject's weights. It records every request with its session.

FakeDSpace stands in for ESPOL's DSpace (www.dspace.espol.edu.ec, through `[test] link_hosts`): the REST
`filtered-items` search, which runs a `matches` title regex the way DSpace does, an item by its handle with its
bitstreams, and their download. Items come from fixtures/dspace/items.json; one is stored inside the
multipart/form-data envelope it was uploaded with, as many real ones are. It records every request with its headers.

FakePages stands in for GitHub Pages: it serves docs/ as published, except that a page's Content-Security-Policy also
lets it reach the given relay (a local address here, a workers.dev one for real).

ScriptedLLM is an OpenAI-compatible chat-completions endpoint whose answers come from a
Python function (the test's script): it sees the whole request, so it can pick a tool
the request offers, and it records each request (including the tools offered).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_SIZE = 2
DOWNLOADS = {5001: "capitulo-3-derivadas.pdf", 5005: "capitulo-3-derivadas.pdf", 5101: "semana-2-cinematica.pptx",
             5010: "silabo-matg1049.pdf", 5301: "silabo-matg1049.pdf", 5102: "lectura-vectores-escaneada.pdf",
             6101: "taller-2-especificacion.pdf", 6102: "plantilla-taller.doc"}
THROTTLE_ONCE = "/api/v1/courses/102/assignments"
PUBLIC_DOC = "1PoliticasFisicaE2E-publico_0000000000000000"  # the Google Doc of Física's policies, shared with anyone
PRIVATE_DOC = "1RubricaFisicaE2E-privado_00000000000000000"  # the project rubric, shared only with some accounts
DRIVE_FILE = "1GuiaLaboratorioE2E-drive_000000000"  # the lab guide, a PDF in Drive shared with anyone
ESPOL_ONLY_SHARE = "EQpurcell9"  # Cálculo's Purcell in SharePoint, for ESPOL accounts only


class _Server:
    def __init__(self, handler_cls):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.httpd.owner = self
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class FakeCanvas(_Server):
    def __init__(self, token: str, fixtures: str = "canvas"):
        super().__init__(_CanvasHandler)
        self.fixtures = FIXTURES / fixtures
        self._token = token
        self.valid_tokens = {token}
        self.token_ids = {token: 1}
        self.purposes = {token: "Token personal"}
        self.created: list[str] = []  # tokens minted through POST /users/self/tokens
        self.deleted: set[int] = set()
        self.next_token = 2
        self.state = "state1"
        self.requests: list[tuple[str, str]] = []
        self.times: list[float] = []  # when each request arrived
        self.throttled = False
        self.failing: set[str] = set()
        self.slow_downloads: dict[int, float] = {}
        self.web = "http://web.invalid"
        # Other students' accounts (a friend's Vinci): token → [fixtures folder, state]. A token minted with one
        # belongs to the same account; the captain's are the rest.
        self.accounts: dict[str, list] = {}
        self.extra: dict[str, list] = {}  # API path → items a test adds to the captain's list there, on any state
        self.lock = threading.Lock()

    def add_account(self, token: str, fixtures: str, purpose: str = "Vinci") -> None:
        token_id = self.mint(token, purpose)
        with self.lock:
            self.accounts[token] = [FIXTURES / fixtures, "state1"]
        assert token_id

    def set_account_state(self, fixtures: str, state: str) -> None:
        with self.lock:
            for account in self.accounts.values():
                if account[0] == FIXTURES / fixtures:
                    account[1] = state

    def account_of(self, token: str) -> list | None:
        return self.accounts.get(token)

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        """Compatibility with older E2E stages: make exactly this token valid."""
        with self.lock:
            self._token = value
            self.valid_tokens = {value} | {t for t in self.valid_tokens if t in self.accounts}
            self.token_ids.setdefault(value, self.next_token)
            self.next_token = max(self.next_token, self.token_ids[value] + 1)

    def expire(self, token: str) -> None:
        with self.lock:
            self.valid_tokens.discard(token)

    def issued(self) -> list[str]:
        with self.lock:
            return list(self.created)

    def mint(self, token: str, purpose: str) -> int:
        """A token that exists in the account without the bot having created it in this run."""
        with self.lock:
            token_id = self.next_token
            self.next_token += 1
            self.valid_tokens.add(token)
            self.token_ids[token] = token_id
            self.purposes[token] = purpose
            return token_id

    def token_json(self, token: str, *, fresh: bool = False) -> dict:
        """The shape of canvas-lms lib/api/v1/token.rb: the value only as visible_token, and only at creation."""
        return {"id": self.token_ids[token], "created_at": "2026-09-28T11:30:00Z", "expires_at": None,
                "last_used_at": None, "purpose": self.purposes.get(token, "Token personal"),
                "real_user_id": None, "remember_access": None, "scopes": [], "updated_at": "2026-09-28T11:30:00Z",
                "user_id": 42, "workflow_state": "deleted" if self.token_ids[token] in self.deleted else "active",
                "app_name": "User-Generated", "visible_token": token if fresh else f"{token[:5]}...",
                "can_manually_regenerate": True}

    def load(self, api_path: str, account: list | None = None):
        fixtures, current = account or (self.fixtures, self.state)
        # Each stateN holds only what changed since the one before it.
        for state in (f"state{n}" for n in range(int(current.removeprefix("state")), 0, -1)):
            path = fixtures / state / (api_path.strip("/") + ".json")
            if path.is_file():
                text = path.read_text(encoding="utf-8").replace("{{BASE}}", self.base).replace("{{WEB}}", self.web)
                data = json.loads(text)
                extra = self.extra.get(api_path.strip("/")) if account is None else None
                return data + extra if extra and isinstance(data, list) else data
        return None


class FakeWeb(_Server):
    def __init__(self):
        super().__init__(_WebHandler)
        self.requests: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []  # each request's headers, in the order of `requests`
        self.lock = threading.Lock()


class _Quiet(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass

    def _send(self, status: int, body: bytes, content_type="application/json; charset=utf-8", headers=None):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):  # the client went away (e.g. a stopped long poll)
            pass

    def _json(self, status: int, data, headers=None):
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), headers=headers)


class FakeWhatsApp(_Server):
    """Hermes' WhatsApp bridge (scripts/whatsapp-bridge/bridge.js), as the adapter sees it: GET /health and
    /messages, POST /send, /send-media, /typing, /read. Hermes adopts a running bridge whose scriptHash matches
    the bridge.js it would start (here a stand-in file, `script`), so no Node process or WhatsApp is involved."""

    BOT = "593990000000@s.whatsapp.net"

    def __init__(self, script: Path):
        super().__init__(_WhatsAppHandler)
        self.script = script
        self.inbox: list[dict] = []    # what Hermes picks up on its next GET /messages
        self.sent: list[dict] = []     # every POST: {"path", **payload}
        self.served: list[float] = []  # when Hermes polled /messages
        self.failing: set[str] = set()  # POST paths that answer 503 (a bridge that lost WhatsApp) until removed
        self.missing: set[str] = set()  # POST paths that answer 404 (a route this bridge does not have)
        self.members: dict[str, set[str]] = {}  # group → whoever wrote there, as /chat/<id> lists its participants
        self.lock = threading.Lock()
        self._ids = itertools.count(1)

    def script_hash(self) -> str:
        return hashlib.sha256(self.script.read_bytes()).hexdigest()[:16]

    def say(self, chat: str, sender: str, text: str, *, name: str = "", group: bool = False,
            mentions: list[str] | None = None, quote: str | None = None) -> str:
        """A message someone writes: in a private chat (`chat` is the sender's JID) or a group (…@g.us); with
        `quote`, a reply to that text of a message Vinci's account sent."""
        message_id = f"E2E{next(self._ids):06d}"
        quoted = ({"hasQuotedMessage": True, "quotedMessageId": f"BOT{next(self._ids):06d}", "quotedText": quote,
                   "quotedParticipant": self.BOT, "quotedRemoteJid": chat} if quote else {})
        with self.lock:
            if group:
                self.members.setdefault(chat, set()).add(sender)
            self.inbox.append({"messageId": message_id, "chatId": chat, "senderId": sender,
                               "senderName": name or sender.split("@")[0], "chatName": name if not group else "Grupo",
                               "isGroup": group, "body": text, "hasMedia": False, "mediaType": "", "mediaUrls": [],
                               "mentionedIds": mentions or [], "botIds": [self.BOT], "timestamp": int(time.time()),
                               "fromMe": False, **quoted})
        return message_id

    def sticker(self, chat: str, sender: str, path: Path, *, name: str = "", group: bool = False,
                quote: str | None = None) -> str:
        """A sticker as bridge.js reports it: a .webp already in Hermes' image cache, often a reply to Vinci."""
        message_id = f"E2E{next(self._ids):06d}"
        quoted = ({"hasQuotedMessage": True, "quotedMessageId": f"BOT{next(self._ids):06d}", "quotedText": quote,
                   "quotedParticipant": self.BOT, "quotedRemoteJid": chat} if quote else {})
        with self.lock:
            self.inbox.append({"messageId": message_id, "chatId": chat, "senderId": sender,
                               "senderName": name or sender.split("@")[0], "chatName": name if not group else "Grupo",
                               "isGroup": group, "body": "[Sticker]", "hasMedia": True, "mediaType": "sticker",
                               "mime": "image/webp", "nativeType": "stickerMessage", "mediaUrls": [str(path)],
                               "mentionedIds": [], "botIds": [self.BOT], "timestamp": int(time.time()),
                               "fromMe": False, **quoted})
        return message_id

    def audio(self, chat: str, sender: str, path: Path, *, name: str = "", group: bool = False) -> str:
        """A voice note (.ogg) or an audio file (anything else) as bridge.js reports it: the file already saved in
        Hermes' audio cache, and its placeholder as the text."""
        kind = "ptt" if path.suffix == ".ogg" else "audio"
        message_id = f"E2E{next(self._ids):06d}"
        with self.lock:
            self.inbox.append({"messageId": message_id, "chatId": chat, "senderId": sender,
                               "senderName": name or sender.split("@")[0], "chatName": name if not group else "Grupo",
                               "isGroup": group, "body": f"[{kind} received]", "hasMedia": True, "mediaType": kind,
                               "mime": "audio/ogg; codecs=opus" if kind == "ptt" else "audio/mp4",
                               "nativeType": "pttMessage" if kind == "ptt" else "audioMessage",
                               "mediaUrls": [str(path)], "mentionedIds": [], "botIds": [self.BOT],
                               "timestamp": int(time.time()), "fromMe": False})
        return message_id

    def vote(self, chat: str, sender: str, poll_id: str, option: str) -> None:
        """A vote on one of Vinci's polls, in private or in a group, as bridge.js reports it: the chosen option's text,
        quoting the poll, with no mention of Vinci."""
        with self.lock:
            self.inbox.append({"messageId": f"{poll_id}:update:{next(self._ids)}", "chatId": chat, "senderId": sender,
                               "senderName": sender.split("@")[0], "chatName": chat.split("@")[0],
                               "isGroup": chat.endswith("@g.us"),
                               "body": option, "hasMedia": False, "mediaType": "poll_update",
                               "nativeType": "pollUpdateMessage", "mediaUrls": [], "mentionedIds": [],
                               "quotedMessageId": poll_id, "quotedParticipant": "", "quotedRemoteJid": chat,
                               "quotedText": "", "hasQuotedMessage": True, "botIds": [],
                               "timestamp": int(time.time()), "fromMe": False})

    def polls_to(self, chat: str, since: int = 0) -> list[dict]:
        with self.lock:
            return [m for m in self.sent[since:] if m.get("chatId") == chat and m["path"] == "send-poll"]

    def polled_since(self, mark: float) -> bool:
        with self.lock:
            return any(t >= mark for t in self.served)

    def messages_to(self, chat: str, since: int = 0) -> list[dict]:
        with self.lock:
            return [m for m in self.sent[since:] if m.get("chatId") == chat
                    and m["path"] in ("send", "send-media", "send-url-button")]

    def wait_for(self, predicate, timeout: float = 60):
        end = time.time() + timeout
        while time.time() < end:
            found = predicate(self)  # it reads through messages_to / polled_since, which take the lock
            if found:
                return found
            time.sleep(0.2)
        return None


class _WhatsAppHandler(_Quiet):
    def do_GET(self):
        bridge: FakeWhatsApp = self.server.owner
        path = urlsplit(self.path).path
        if path == "/health":
            return self._json(200, {"status": "connected", "scriptHash": bridge.script_hash(),
                                    "sendReadReceipts": False, "queueLength": len(bridge.inbox)})
        if path == "/messages":
            with bridge.lock:
                batch, bridge.inbox = bridge.inbox, []
                bridge.served.append(time.time())
            return self._json(200, batch)
        if path.startswith("/chat/"):
            chat = unquote(path[len("/chat/"):])
            with bridge.lock:
                inside = sorted(bridge.members.get(chat, ()))
            return self._json(200, {"name": chat.split("@")[0], "isGroup": chat.endswith("@g.us"), "participants": inside})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        bridge: FakeWhatsApp = self.server.owner
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        path = urlsplit(self.path).path.strip("/")
        if path in bridge.failing:
            return self._json(503, {"error": "Not connected to WhatsApp"})
        if path in bridge.missing:
            return self._json(404, {"error": f"Cannot POST /{path}"})
        if path == "send-url-button":  # read like any message; the button is its buttonText and url
            payload = {**payload, "message": payload.get("text", "")}
        with bridge.lock:
            message_id = f"OUT{len(bridge.sent) + 1:06d}"
            bridge.sent.append({"path": path, **payload, "messageId": message_id})
        return self._json(200, {"success": True, "messageId": message_id})


class FakeRelay(_Server):
    """Vinci's relay (relay/worker.js): what pages post waits until Vinci's PC fetches it with the key."""

    KEY = "e2e-relay-key"

    def __init__(self):
        super().__init__(_RelayHandler)
        self.messages: list[dict] = []  # waiting: {"id", "mailbox", "data", "at"}
        self.posted: list[dict] = []    # everything a page ever posted
        self.statuses: dict[str, dict] = {}  # mailbox → what its page reads at /s/<mailbox>
        self.status_log: list[tuple[str, dict]] = []
        self.fetches = 0
        self.lock = threading.Lock()
        self._ids = itertools.count(1)


class _RelayHandler(_Quiet):
    CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"}

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {FakeRelay.KEY}"

    def _json(self, status: int, data, headers=None):
        super()._json(status, data, headers={**self.CORS, **(headers or {})})

    def do_OPTIONS(self):
        self._send(204, b"", headers=self.CORS)

    def do_GET(self):
        relay: FakeRelay = self.server.owner
        parts = urlsplit(self.path)
        status = re.fullmatch(r"/s/([A-Za-z0-9_-]{22,64})", parts.path)
        if status:
            with relay.lock:
                found = relay.statuses.get(status[1])
            return self._json(200, found) if found is not None else self._json(404, {"error": "none"})
        if parts.path != "/inbox":
            return self._json(404, {"error": "not found"})
        if not self._authorized():
            return self._json(401, {"error": "token"})
        only = dict(parse_qsl(parts.query)).get("mailbox")
        with relay.lock:
            relay.fetches += 1
            return self._json(200, {"messages": [m for m in relay.messages if not only or m["mailbox"] == only]})

    def do_PUT(self):
        relay: FakeRelay = self.server.owner
        status = re.fullmatch(r"/s/([A-Za-z0-9_-]{22,64})", urlsplit(self.path).path)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        if not status:
            return self._json(404, {"error": "not found"})
        if not self._authorized():
            return self._json(401, {"error": "token"})
        with relay.lock:
            relay.statuses[status[1]] = json.loads(body)
            relay.status_log.append((status[1], json.loads(body)))
        return self._json(200, {"ok": True})

    def do_POST(self):
        relay: FakeRelay = self.server.owner
        path = urlsplit(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        mailbox = re.fullmatch(r"/m/([A-Za-z0-9_-]{22,64})", path)
        if mailbox:
            try:
                data = json.loads(body)
            except ValueError:
                return self._json(400, {"error": "json"})
            with relay.lock:
                entry = {"id": f"R{next(relay._ids)}", "mailbox": mailbox[1], "data": data, "at": int(time.time())}
                relay.messages.append(entry)
                relay.posted.append(entry)
            return self._json(202, {"ok": True})
        if path == "/ack":
            if not self._authorized():
                return self._json(401, {"error": "token"})
            ids = set(json.loads(body or b"{}").get("ids") or [])
            with relay.lock:
                relay.messages = [m for m in relay.messages if m["id"] not in ids]
            return self._json(200, {"ok": True})
        return self._json(404, {"error": "not found"})


class _CanvasHandler(_Quiet):
    def _refuse(self):
        canvas: FakeCanvas = self.server.owner
        with canvas.lock:
            canvas.requests.append((self.command, self.path))
            canvas.times.append(time.time())
        self._json(405, {"errors": [{"message": "El bot solo debe leer"}]})

    do_PUT = do_PATCH = _refuse

    def _authorized(self, canvas: FakeCanvas) -> bool:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        return token in canvas.valid_tokens

    def do_POST(self):
        canvas: FakeCanvas = self.server.owner
        with canvas.lock:
            canvas.requests.append(("POST", self.path))
            canvas.times.append(time.time())
        if not self._authorized(canvas):
            return self._json(401, {"errors": [{"message": "Invalid access token."}]})
        if urlsplit(self.path).path != "/api/v1/users/self/tokens":
            return self._json(405, {"errors": [{"message": "El bot no puede cambiar el aula"}]})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            payload = {}
        purpose = (payload.get("token") or {}).get("purpose")
        if not purpose:
            return self._json(400, [{"message": "token[purpose] is missing"}])
        token = f"7~{canvas.next_token:03d}-renovado-e2e-xxxxxxxxxxxxxxxx"
        canvas.mint(token, purpose)
        requester = self.headers.get("Authorization", "").removeprefix("Bearer ")
        with canvas.lock:
            if requester in canvas.accounts:
                canvas.accounts[token] = canvas.accounts[requester]
            canvas.created.append(token)
            return self._json(200, canvas.token_json(token, fresh=True))

    def do_DELETE(self):
        canvas: FakeCanvas = self.server.owner
        with canvas.lock:
            canvas.requests.append(("DELETE", self.path))
            canvas.times.append(time.time())
        if not self._authorized(canvas):
            return self._json(401, {"errors": [{"message": "Invalid access token."}]})
        match = re.fullmatch(r"/api/v1/users/self/tokens/(\d+)", urlsplit(self.path).path)
        if not match:
            return self._json(405, {"errors": [{"message": "El bot no puede cambiar el aula"}]})
        token_id = int(match[1])
        with canvas.lock:
            found = next((token for token, known_id in canvas.token_ids.items() if known_id == token_id), None)
            if not found or token_id in canvas.deleted:
                return self._json(404, {"errors": [{"message": "The specified resource does not exist."}]})
            canvas.valid_tokens.discard(found)
            canvas.deleted.add(token_id)
            return self._json(200, canvas.token_json(found))

    def do_GET(self):
        canvas: FakeCanvas = self.server.owner
        with canvas.lock:
            canvas.requests.append(("GET", self.path))
            canvas.times.append(time.time())
        url = urlsplit(self.path)
        if not self._authorized(canvas):
            return self._json(401, {"errors": [{"message": "Invalid access token."}]},
                              {"WWW-Authenticate": 'Bearer realm="canvas-lms"'})
        quota = {"X-Rate-Limit-Remaining": "599.12", "X-Request-Cost": "0.018"}

        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        account = canvas.account_of(token)
        if url.path == "/api/v1/users/self":
            return self._json(200, {"id": 43, "name": "Amigo E2E"} if account else
                              {"id": 42, "name": "Estudiante E2E"}, quota)
        if url.path == "/api/v1/users/self/user_generated_tokens":
            with canvas.lock:
                tokens = [canvas.token_json(t) for t, token_id in canvas.token_ids.items()
                          if token_id not in canvas.deleted and canvas.accounts.get(t) is account]
            return self._json(200, tokens, quota)

        if url.path.startswith("/files/") and url.path.endswith("/download"):
            file_id = int(url.path.split("/")[2])
            name = DOWNLOADS.get(file_id)
            if not name:
                return self._json(404, {"errors": [{"message": "The specified resource does not exist."}]})
            time.sleep(canvas.slow_downloads.get(file_id, 0))
            return self._send(200, (FIXTURES / "files" / name).read_bytes(), "application/octet-stream", quota)

        if not url.path.startswith("/api/v1/"):
            return self._json(404, {"errors": [{"message": "The specified resource does not exist."}]})

        if url.path in canvas.failing:
            return self._json(503, {"errors": [{"message": "Service Unavailable"}]}, {"Retry-After": "0"})

        if url.path == THROTTLE_ONCE and not canvas.throttled:
            canvas.throttled = True
            return self._send(429, b"429 Too Many Requests (Rate Limit Exceeded)", "text/plain",
                              {"X-Rate-Limit-Remaining": "0.0", "Retry-After": "0"})

        data = canvas.load(url.path[len("/api/v1/"):], account)
        if data is None:
            return self._json(404, {"errors": [{"message": "The specified resource does not exist."}]}, quota)
        if isinstance(data, dict) and "__status" in data:
            return self._json(data["__status"], data["__body"], quota)
        if not isinstance(data, list):
            return self._json(200, data, quota)

        query = parse_qsl(url.query, keep_blank_values=True)
        params = dict(query)
        page = int(params.get("page", 1))
        per_page = min(int(params.get("per_page", 10)), PAGE_SIZE)
        chunk = data[(page - 1) * per_page: page * per_page]
        links = []
        def page_url(n):
            rest = [(k, v) for k, v in query if k != "page"] + [("page", str(n))]
            return f'<{canvas.base}{url.path}?{urlencode(rest)}>'
        links.append(f'{page_url(page)}; rel="current"')
        if page * per_page < len(data):
            links.append(f'{page_url(page + 1)}; rel="next"')
        links.append(f'{page_url(1)}; rel="first"')
        return self._json(200, chunk, {**quota, "Link": ",".join(links)})


DRIVE_WARNING = f"""<!DOCTYPE html><html><head><title>Google Drive - Virus scan warning</title></head><body>
<p>Google Drive can't scan this file for viruses.</p>
<form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
<input type="submit" id="uc-download-link" value="Download anyway"/>
<input type="hidden" name="id" value="{DRIVE_FILE}"><input type="hidden" name="export" value="download">
<input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="e2e-uuid"></form></body></html>"""


class _WebHandler(_Quiet):
    COOKIE = {"Set-Cookie": "NID=e2e-cookie-de-google; Path=/"}

    def _file(self, name: str, content_type: str, shown: str) -> None:
        disposition = f"attachment; filename=\"{shown.encode('ascii', 'replace').decode()}\"; filename*=UTF-8''{quote(shown)}"
        self._send(200, (FIXTURES / "files" / name).read_bytes(), content_type, {"Content-Disposition": disposition})

    def _shared(self, path: str, query: dict) -> bool:
        """Google's and SharePoint's answers to the fixtures' links; False for anything else."""
        if path == f"/document/d/{PUBLIC_DOC}/export" and query.get("format") == "pdf":
            self._send(307, b"", "application/binary", {
                "Location": f"https://doc-0k-6c-docstext.googleusercontent.com/export/e2e/{PUBLIC_DOC}", **self.COOKIE})
        elif path == f"/export/e2e/{PUBLIC_DOC}":
            self._file("politicas-del-curso.pdf", "application/pdf", "Políticas del curso - Física I.pdf")
        elif path == f"/document/d/{PRIVATE_DOC}/export":
            self._send(401, b"<!DOCTYPE html><html><title>Google Docs: necesitas acceso</title><body>Solicita acceso "
                            b"o cambia a una cuenta con acceso.</body></html>", "text/html; charset=utf-8", self.COOKIE)
        elif path == "/uc" and query.get("id") == DRIVE_FILE:
            self._send(303, b"", "application/binary", {
                "Location": f"https://drive.usercontent.google.com/download?id={DRIVE_FILE}&export=download",
                **self.COOKIE})
        elif path == "/download" and query.get("id") == DRIVE_FILE:
            if query.get("confirm") == "t" and query.get("uuid") == "e2e-uuid":
                self._file("guia-laboratorio-1.pdf", "application/octet-stream", "guia-laboratorio-1.pdf")
            else:
                self._send(200, DRIVE_WARNING.encode(), "text/html; charset=utf-8", self.COOKIE)
        elif path.endswith("/_layouts/15/download.aspx") and query.get("share") == ESPOL_ONLY_SHARE:
            self._send(302, b"", "text/html", {
                "Location": "https://login.microsoftonline.com/common/oauth2/authorize?client_id=e2e&response_mode=form_post",
                **self.COOKIE})
        else:
            return False
        return True

    def do_GET(self):
        web: FakeWeb = self.server.owner
        with web.lock:
            web.requests.append(("GET", self.path))
            web.headers.append(dict(self.headers))
        if self._shared(urlsplit(self.path).path, dict(parse_qsl(urlsplit(self.path).query))):
            return
        path = (FIXTURES / "web" / unquote(urlsplit(self.path).path).lstrip("/")).resolve()
        if not path.is_relative_to((FIXTURES / "web").resolve()) or not path.is_file():
            return self._send(404, b"not found", "text/plain")
        return self._send(200, path.read_bytes(), "text/html; charset=utf-8")



class FakeDSpace(_Server):
    def __init__(self):
        super().__init__(_DSpaceHandler)
        self.items = json.loads((FIXTURES / "dspace" / "items.json").read_text(encoding="utf-8"))
        self.requests: list[tuple[str, str]] = []
        self.headers: list[dict] = []
        self.lock = threading.Lock()

    def item_json(self, item: dict, expand: str) -> dict:
        number = item["handle"].split("/")[1]
        data = {"uuid": f"item-{number}", "name": item["name"], "handle": item["handle"], "type": "item"}
        if "parentCollection" in expand:
            data["parentCollection"] = {"name": item["collection"], "type": "collection"}
        if "bitstreams" in expand:
            data["bitstreams"] = [{"name": "license.txt", "bundleName": "LICENSE", "sizeBytes": 1748,
                                   "retrieveLink": f"/rest/bitstreams/license-{number}/retrieve"}]
            if item["file"]:
                size = (FIXTURES / "files" / item["file"]).stat().st_size
                data["bitstreams"].append({"name": item["name"], "bundleName": "ORIGINAL", "sizeBytes": size,
                                           "retrieveLink": f"/rest/bitstreams/file-{number}/retrieve"})
        return data


class _DSpaceHandler(_Quiet):
    def _refuse(self):
        self.server.owner.requests.append((self.command, self.path))
        self._send(405, b"", "text/plain")

    do_POST = do_PUT = do_DELETE = _refuse

    def do_GET(self):
        dspace: FakeDSpace = self.server.owner
        with dspace.lock:
            dspace.requests.append(("GET", self.path))
            dspace.headers.append(dict(self.headers))
        parts = urlsplit(self.path)
        query = parse_qsl(parts.query)
        if parts.path == "/rest/filtered-items":
            values = [v for k, v in query if k == "query_val[]"]
            hits = [i for i in dspace.items if all(re.search(v, i["name"]) for v in values)]
            expand = dict(query).get("expand", "")
            return self._json(200, {"items": [dspace.item_json(i, expand) for i in hits], "item-count": len(hits),
                                    "unfiltered-item-count": len(hits)})
        if match := re.fullmatch(r"/rest/handle/(\d+/\d+)", parts.path):
            item = next((i for i in dspace.items if i["handle"] == match[1]), None)
            if item is None:  # DSpace answers an unknown handle with Tomcat's error page
                return self._send(500, b"<html><title>Apache Tomcat - Error report</title></html>", "text/html")
            return self._json(200, dspace.item_json(item, dict(query).get("expand", "")))
        if match := re.fullmatch(r"/rest/bitstreams/file-(\d+)/retrieve", parts.path):
            item = next(i for i in dspace.items if i["handle"].endswith("/" + match[1]))
            body = (FIXTURES / "files" / item["file"]).read_bytes()
            if item.get("wrapped"):
                boundary = b"------------------------------8d72aff9bce40eb"
                body = (b"\r\n" + boundary + b'\r\nContent-Disposition: form-data; name="file";filename="'
                        + item["name"].encode() + b'"\r\n Content-Type: application/octet-stream\r\n\r\n'
                        + body + b"\r\n" + boundary + b"--\r\n")
            return self._send(200, body, "application/octet-stream")
        return self._send(404, b"not found", "text/plain")

class Tripwire(_Server):
    """Where the Telegram Bot API would be: Vinci lives on WhatsApp only, so any request here is a bug. It records
    each one and answers 404."""

    def __init__(self):
        super().__init__(_TripwireHandler)
        self.requests: list[str] = []


class _TripwireHandler(_Quiet):
    def _record(self):
        self.server.owner.requests.append(f"{self.command} {self.path}")
        self._json(404, {"ok": False, "error_code": 404, "description": "Not Found"})

    do_GET = do_POST = _record


class ScriptedLLM(_Server):
    """script(request) -> {"content": str} or {"tool_calls": [(name, args), ...]}"""

    def __init__(self, script):
        super().__init__(_LLMHandler)
        self.script = script
        self.requests: list[dict] = []
        self.lock = threading.Lock()


class _LLMHandler(_Quiet):
    def do_GET(self):
        self._json(200, {"object": "list", "data": [{"id": "fake", "object": "model", "owned_by": "e2e"}]})

    def do_POST(self):
        llm: ScriptedLLM = self.server.owner
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json(404, {"error": {"message": "not found"}})
        with llm.lock:
            llm.requests.append(req)
        try:
            answer = llm.script(req) or {"content": "ok"}
        except Exception as exc:  # a bug in the script shows up in the chat, not as a hang
            answer = {"content": f"[script error: {type(exc).__name__}: {exc}]"}
        calls = [{"id": f"call_{time.time_ns()}_{i}", "type": "function",
                  "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                 for i, (name, args) in enumerate(answer.get("tool_calls") or [])]
        content = answer.get("content") if not calls else answer.get("content", "")
        finish = "tool_calls" if calls else "stop"
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        created = int(time.time())
        if not req.get("stream"):
            message = {"role": "assistant", "content": content or ("" if calls else "ok")}
            if calls:
                message["tool_calls"] = calls
            return self._json(200, {"id": "cmpl", "object": "chat.completion", "created": created, "model": "fake",
                                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                                    "usage": usage})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def chunk(delta, finish_reason=None, **extra):
            data = {"id": "cmpl", "object": "chat.completion.chunk", "created": created, "model": "fake",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}], **extra}
            self.wfile.write(f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode())

        chunk({"role": "assistant", "content": content or ""})
        for i, call in enumerate(calls):
            chunk({"tool_calls": [{"index": i, **call}]})
        chunk({}, finish, usage=usage)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


# -- ESPOL's Académico -------------------------------------------------------------------------------

PORTAL_USER, PORTAL_PASSWORD = "estudiante.prueba", "Clave-Secreta-E2E-9"
PORTAL_TERM = ("2026", "2S")  # what the exam timetable fills in; the grades and the timetable ask for it
# (Año Termino, Código, Materia, Prom., No. Vez, Estado): invented, in the shapes the portal uses. The term in
# progress is not in the history; the admission subjects (ADM…) are approved with 0,00.
PORTAL_HISTORY = [
    ("2024-1", "MATG1045", "CÁLCULO DE UNA VARIABLE", "8,20", "1", "Aprobada"),
    ("2024-1", "FISG1005", "FÍSICA: MECÁNICA", "5,10", "1", "Reprobada"),
    ("2024-1", "ADM001099", "FÍSICA (2020)", "0,00", "1", "Aprobada"),
    ("2024-1", "IDIG1006", "INGLÉS I", "8,97", "1", "Convalidada"),
    ("2024-2", "FISG1005", "FÍSICA: MECÁNICA", "7,40", "2", "Aprobada"),
    ("2024-2", "CCPG1043", "FUNDAMENTOS DE PROGRAMACIÓN", "9,10", "1", "Aprobada"),
    ("2025-1", "MATG1046", "CÁLCULO VECTORIAL", "7,90", "1", "Aprobada"),
]
PORTAL_LATE_GRADE = ("2026-1", "ADSG1026", "CIENCIAS DE LA SOSTENIBILIDAD", "8,80", "1", "Aprobada")
# Créditos por Carrera: (kind of credit, required, [(code, subject, credits, status)])
PORTAL_CREDITS = [
    ("FORMACIÓN PROFESIONAL", "53", [("CCPG1043", "FUNDAMENTOS DE PROGRAMACIÓN", "3", "APROBADA")]),
    ("MATEMÁTICAS Y CIENCIAS BÁSICAS", "21", [("MATG1045", "CÁLCULO DE UNA VARIABLE", "3", "APROBADA"),
                                              ("MATG1046", "CÁLCULO VECTORIAL", "3", "APROBADA"),
                                              ("FISG1005", "FÍSICA: MECÁNICA", "3", "APROBADA")]),
    ("EDUCACIÓN GENERAL", "23", [("IDIG1006", "INGLÉS I", "2", "CONVALIDADA")]),
]
# tbl_Calificaciones: (code, subject, paralelo teórico, práctico, exam 1, exam 2, práct., mej., prom.). A subject with
# a práctico also has a Presentar(...) link (name, parcial, final, mejoramiento, práctico, subtotal, % teórico,
# % práctico, promedio) that opens its «Ponderación» dialog.
PORTAL_GRADES = [("CCPG1055", "SISTEMAS DISTRIBUIDOS Y COMPUTACIÓN EN LA NUBE", "1", "101", "7,50", "0", "9,00", "0", "0,00"),
                 ("SOFG1007", "INGENIERÍA DE SOFTWARE I", "1", "", "8,80", "0", "", "0", "0,00")]
# Información General: the student's card (never to be kept), which also carries the GPA, and the career's figures.
PORTAL_CARD = [("Matrícula", "202499999"), ("Identificación", "0999999999"), ("Nombre", "ESTUDIANTE DE PRUEBA"),
               ("Grupo étnico", "Prueba")]
# The weekly grids: (day, from, to, cell) on a row per half hour, a class spanning its rows.
PORTAL_CLASSES = [("Lunes", "09:30", "11:30", "CCPG1055 - SISTEMAS DISTRIBUIDOS Y COMPUTACIÓN EN LA NUBE Paralelo N°1 "
                   "Aula:15A-201 CAMPUS GUSTAVO GALINDO"),
                  ("Martes", "14:30", "16:30", "SOFG1007 - INGENIERÍA DE SOFTWARE I Paralelo N°2 Aula:11C-104 CAMPUS "
                   "GUSTAVO GALINDO")]
PORTAL_EXAMS = {"PARCIAL": [("Lunes", "08:00", "10:00", "CCPG1055 - SISTEMAS DISTRIBUIDOS Y COMPUTACIÓN EN LA NUBE "
                             "Paralelo N°1 Aula:15A-AUD CAMPUS GUSTAVO GALINDO Fecha:24/11/2026")],
                "FINAL": [("Martes", "10:00", "12:00", "CCPG1055 - SISTEMAS DISTRIBUIDOS Y COMPUTACIÓN EN LA NUBE "
                           "Paralelo N°1 Aula:15A-AUD CAMPUS GUSTAVO GALINDO Fecha:2/2/2027"),
                          ("Jueves", "08:00", "10:00", "SOFG1007 - INGENIERÍA DE SOFTWARE I Paralelo N°2 Aula:11C-AUD "
                           "CAMPUS GUSTAVO GALINDO Fecha:4/2/2027")],
                "MEJORAMIENTO": [("Jueves", "08:00", "10:00", "SOFG1007 - INGENIERÍA DE SOFTWARE I Paralelo N°2 "
                                  "Aula:11C-AUD CAMPUS GUSTAVO GALINDO Fecha:11/2/2027")]}
PORTAL_EXAM_KINDS = {"1": "PARCIAL", "2": "FINAL", "M": "MEJORAMIENTO"}


class FakePortal(_Server):
    """ESPOL's Académico for one student, PORTAL_USER. `version` 2 is the portal a week later: Sostenibilidad's grade
    is published, in the history and in the credits."""

    def __init__(self):
        super().__init__(_PortalHandler)
        self.lock = threading.Lock()
        self.sessions: dict[str, dict] = {}
        self.requests: list[dict] = []   # {"method", "path", "session", "body"}
        self.logins: list[tuple[str, str]] = []  # (session, outcome)
        self.version = 1
        self.codes: list[str] = []       # every CAPTCHA code shown, in order
        self._ids = itertools.count(1)

    def last_code(self) -> str:
        with self.lock:
            return self.codes[-1]

    def history(self) -> list[tuple]:
        return PORTAL_HISTORY if self.version == 1 else [*PORTAL_HISTORY, PORTAL_LATE_GRADE]

    def gpa(self) -> str:
        return "8,15" if self.version == 1 else "8,22"

    def career(self) -> list[tuple]:
        left, progress = ("60", "40,00% *") if self.version == 1 else ("58", "42,50% *")
        return [("Año-Término", "2024-1S"), ("Carrera", "Computación|Activo"), ("Materias tomadas en ESPOL", "7"),
                ("Promedio de materias de la carrera", self.gpa()), ("Nivel", "200I"), ("Créditos por tomar", left),
                ("Avance de la carrera", progress), ("Porcentaje de créditos reprobados", "0,00%")]

    def credits(self) -> list[tuple]:
        if self.version == 1:
            return PORTAL_CREDITS
        return [(kind, required, [*rows, ("ADSG1026", "CIENCIAS DE LA SOSTENIBILIDAD", "2", "APROBADA")]
                 if kind == "EDUCACIÓN GENERAL" else rows) for kind, required, rows in PORTAL_CREDITS]


def _captcha_jpeg(code: str) -> bytes:
    import io
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (250, 40), "white")
    draw = ImageDraw.Draw(image)
    for x in range(0, 250, 9):
        draw.line([(x, 0), (x + 20, 40)], fill=(205, 215, 230))
    draw.text((70, 12), " ".join(code), fill=(30, 40, 90))
    out = io.BytesIO()
    image.save(out, "JPEG")
    return out.getvalue()


def _cells(row, tag="td") -> str:
    from html import escape
    return "".join(f"<{tag}>{escape(str(c))}</{tag}>" for c in row)


def _grid(grid_id: str, header: list[str], rows: list[tuple]) -> str:
    body = "".join(f"<tr>{_cells(r)}</tr>" for r in rows) or '<tr><td colspan="9">No existen registros</td></tr>'
    return (f'<table cellspacing="0" rules="all" border="1" id="ctl00_contenido_{grid_id}" style="border-collapse:collapse;">'
            f'<tr class="GridHeader" style="font-weight:bold;">{_cells(header, "th")}</tr>{body}</table>')


def _week_grid(entries: list[tuple]) -> str:
    """horarioView's and horarioExView's tbl_Horario: a row per half hour from 07:00 (none for the hours with
    nothing), a column per day, a class spanning its rows (the rows it covers have no cell for that day)."""
    from html import escape
    days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    slots = [f"{m // 60:02d}:{m % 60:02d}" for m in range(7 * 60, 21 * 60 + 1, 30)]
    starts = {(d, a): (slots.index(b) - slots.index(a), text) for d, a, b, text in entries}
    covered = {(d, slots[i]) for d, a, b, _ in entries for i in range(slots.index(a) + 1, slots.index(b))}
    head = '<th id="ctl00_contenido_hora"></th>' + "".join(f'<th id="ctl00_contenido_{n}">{d}</th>'
                                                             for n, d in enumerate(days, 1))
    rows = ""
    for i, (start, end) in enumerate(zip(slots, slots[1:]), 1):
        if not any((day, start) in starts or (day, start) in covered for day in days):
            continue
        cells = ""
        for n, day in enumerate(days, 1):
            if (day, start) in covered:
                continue
            span, text = starts.get((day, start), (1, ""))
            cells += (f'<td id="ctl00_contenido_{i}_{n}"{f" rowspan={chr(34)}{span}{chr(34)}" if span > 1 else ""} '
                      f'headers="ctl00_contenido_{n}">{escape(text)}</td>')
        rows += f'<tr id="ctl00_contenido_fila_{i}"><th>{start} - {end}</th>{cells}</tr>'
    return f'<table id="ctl00_contenido_tbl_Horario"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'


def _term_boxes(year: str = "", term: str = "") -> str:
    """The year and term boxes and «Consultar» of the grades and the two timetables (a layout table, as the portal)."""
    return ('<table cellspacing="1" cellpadding="1" align="center"><tr><td align="right"><b>Año:</b></td><td>'
            f'<input name="ctl00$contenido$txtAnio" type="text" value="{year}" maxlength="4" id="ctl00_contenido_txtAnio" />'
            '</td></tr><tr><td align="right"><b>Término:</b></td><td><input name="ctl00$contenido$txtTermino" '
            f'type="text" value="{term}" maxlength="2" id="ctl00_contenido_txtTermino" /></td></tr><tr><td colspan="2">'
            '{select}<input type="submit" name="ctl00$contenido$cmdConsultar" value="Consultar" '
            'id="ctl00_contenido_cmdConsultar" /></td></tr></table>')


class _PortalHandler(_Quiet):
    def _session(self, create: bool = False) -> tuple[str | None, dict | None]:
        portal: FakePortal = self.server.owner
        cookies = dict(c.strip().split("=", 1) for c in (self.headers.get("Cookie") or "").split(";") if "=" in c)
        sid = cookies.get("ASP.NET_SessionId")
        with portal.lock:
            if sid in portal.sessions:
                session = portal.sessions[sid]
                session["auth_ok"] = bool(session.get("auth")) and cookies.get(".ASPXAUTH") == session["auth"]
                return sid, session
            if not create:
                return sid, None
            sid = f"fake{next(portal._ids):04d}{hashlib.sha1(str(time.time()).encode()).hexdigest()[:16]}"
            portal.sessions[sid] = {"new": True}
            return sid, portal.sessions[sid]

    def _record(self, sid, body: str = "") -> None:
        portal: FakePortal = self.server.owner
        with portal.lock:
            portal.requests.append({"method": self.command, "path": self.path, "session": sid, "body": body})

    def _page(self, sid: str, session: dict, title: str, content: str, *, allowed: dict | None = None,
              extra_cookies: list[str] = ()) -> None:
        """A Web Forms page: its hidden fields are new on every render and remembered for the next post."""
        state = hashlib.sha256(f"{sid}{time.time()}{len(content)}".encode()).hexdigest()
        validation = hashlib.sha256(state.encode()).hexdigest()
        session.update(viewstate=state, validation=validation, allowed=allowed or {})
        hidden = (f'<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" />'
                  f'<input type="hidden" name="__EVENTARGUMENT" id="__EVENTARGUMENT" value="" />'
                  f'<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="/wEP{state}" />'
                  f'<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="C2EE9ABB" />'
                  f'<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="/wEd{validation}" />')
        html = (f'<!DOCTYPE html><html><head><title>{title}</title><script>function __doPostBack(t,a){{}}</script>'
                f'</head><body><form name="aspnetForm" method="post" action="./{urlsplit(self.path).path.rsplit("/", 1)[-1]}'
                f'{"?" + urlsplit(self.path).query if urlsplit(self.path).query else ""}" id="aspnetForm"><div>{hidden}</div>'
                f'<table class="layout" width="100%"><tr><td class="menu">Menú</td><td>{content}</td></tr></table>'
                f'</form></body></html>')
        cookies = [f"ASP.NET_SessionId={sid}; path=/; HttpOnly"] if session.pop("new", False) else []
        self._send(200, html.encode(), "text/html; charset=utf-8",
                   headers={"Set-Cookie": "; ".join(cookies + list(extra_cookies))} if cookies or extra_cookies else None)

    def _redirect(self, location: str, cookie: str = "") -> None:
        headers = {"Location": location}
        if cookie:
            headers["Set-Cookie"] = cookie
        self._send(302, b"", "text/html", headers=headers)

    def _valid(self, session: dict, form: dict) -> bool:
        if form.get("__VIEWSTATE") != f"/wEP{session.get('viewstate')}" or \
                form.get("__EVENTVALIDATION") != f"/wEd{session.get('validation')}":
            return False
        return all(form.get(name, values[0]) in values for name, values in session.get("allowed", {}).items())

    def _step1(self, sid, session):
        self._page(sid, session, "Académico ESPOL", '<div id="ctl00_contenido_paso1"><label>Usuario:</label>'
                   '<input name="ctl00$contenido$txtuser" type="text" size="15" id="ctl00_contenido_txtuser" />'
                   '<input type="submit" name="ctl00$contenido$btnSigte" value="Siguiente" id="ctl00_contenido_btnSigte" />'
                   '</div>')

    def _step2(self, sid, session, error: str = ""):
        portal: FakePortal = self.server.owner
        vcid = hashlib.md5(f"{sid}{time.time()}{len(portal.codes)}".encode()).hexdigest()
        code = "".join("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"[int(c, 16) % 32] for c in vcid[:5])
        with portal.lock:
            portal.codes.append(code)
        session.update(vcid=vcid, code=code, captcha_seen=False)
        self._page(sid, session, "Académico ESPOL", (
            '<div id="ctl00_contenido_paso2"><table id="ctl00_contenido_tbl1"><tr><td><label><b>Usuario:</b></label></td>'
            f'<td><label id="ctl00_contenido_lbluserN">{session["user"]}</label>@espol.edu.ec</td></tr>'
            '<tr><td><label><b>Contraseña:</b></label></td><td><input name="ctl00$contenido$txtpsw" type="password" '
            'id="ctl00_contenido_txtpsw" /></td></tr></table>'
            f'<input type="hidden" name="LBD_VCID_c_login_ctl00_contenido_samplecaptcha" value="{vcid}" />'
            '<img class="LBD_CaptchaImage" id="c_login_ctl00_contenido_samplecaptcha_CaptchaImage" '
            f'src="/BotDetectCaptcha.ashx?get=image&amp;c=c_login_ctl00_contenido_samplecaptcha&amp;t={vcid}" alt="CAPTCHA" />'
            '<input name="ctl00$contenido$CaptchaCodeTextBox" type="text" id="ctl00_contenido_CaptchaCodeTextBox" />'
            '<input type="submit" name="ctl00$contenido$btnIniciarSesion" value="Iniciar sesión" '
            'id="ctl00_contenido_btnIniciarSesion" /></div><div id="ctl00_contenido_diverror"><span '
            f'id="ctl00_contenido_LabelError" style="color:Red;">{error}</span></div>'))

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path.lower()
        sid, session = self._session(create=path == "/login.aspx")
        self._record(sid)
        if path == "/login.aspx":
            session.clear() if "viewstate" in session else None
            return self._step1(sid, session)
        if path == "/botdetectcaptcha.ashx":
            query = dict(parse_qsl(parts.query))
            if session is None or query.get("t") != session.get("vcid"):
                return self._send(400, b"bad captcha id", "text/plain")
            session["captcha_seen"] = True
            return self._send(200, _captcha_jpeg(session["code"]), "image/jpeg")
        if session is None or not session.get("auth_ok"):
            return self._redirect(f"/login.aspx?ReturnUrl={quote(parts.path)}")
        if path == "/default.aspx":
            return self._page(sid, session, "Inicio", f"<h2>Bienvenido, {session['user']}</h2>")
        page = path.removeprefix("/ui/informacionacademica/")
        return self._data(sid, session, page, {})

    def do_POST(self):
        portal: FakePortal = self.server.owner
        parts = urlsplit(self.path)
        path = parts.path.lower()
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)).decode()
        form = dict(parse_qsl(body, keep_blank_values=True))
        sid, session = self._session()
        self._record(sid, body)
        if session is None or not self._valid(session, form):
            return self._send(500, b"Validation of viewstate MAC failed.", "text/html")
        if path == "/login.aspx":
            if "ctl00$contenido$btnSigte" in form:
                session["user"] = form.get("ctl00$contenido$txtuser", "").strip()
                return self._step2(sid, session)
            if "ctl00$contenido$btnIniciarSesion" in form:
                if form.get("LBD_VCID_c_login_ctl00_contenido_samplecaptcha") != session.get("vcid") or \
                        not session.get("captcha_seen") or \
                        form.get("ctl00$contenido$CaptchaCodeTextBox", "").upper() != session.get("code"):
                    portal.logins.append((sid, "captcha"))
                    return self._step2(sid, session, "El código de la imagen no es correcto.")
                if session.get("user") != PORTAL_USER or form.get("ctl00$contenido$txtpsw") != PORTAL_PASSWORD:
                    portal.logins.append((sid, "password"))
                    return self._step2(sid, session, "Usuario o contraseña incorrectos.")
                portal.logins.append((sid, "ok"))
                session["auth"] = hashlib.sha256(f"auth{sid}".encode()).hexdigest()
                return self._redirect("/default.aspx", f".ASPXAUTH={session['auth']}; path=/; HttpOnly")
            return self._step1(sid, session)
        if not session.get("auth_ok"):
            return self._redirect(f"/login.aspx?ReturnUrl={quote(parts.path)}")
        return self._data(sid, session, path.removeprefix("/ui/informacionacademica/"), form)

    def _data(self, sid, session, page: str, form: dict):
        portal: FakePortal = self.server.owner
        asked = (form.get("ctl00$contenido$txtAnio", "").strip(), form.get("ctl00$contenido$txtTermino", "").strip())
        consulted = "ctl00$contenido$cmdConsultar" in form
        if page == "historiaacademica_.aspx":
            rows = "".join(f"<tr>{_cells(r)}</tr>" for r in portal.history())
            return self._page(sid, session, "Historia Académica", (
                '<h1>Historia Académica</h1><table id="ctl00_contenido_tbResultados" cellspacing="0"><thead><tr>'
                + _cells(["Año Termino", "Código", "Materia", "Prom.", "No. Vez", "Estado"], "th")
                + f"</tr></thead><tbody>{rows}</tbody></table>"))
        if page == "informaciongeneral.aspx":
            def card(rows):
                return "<table>" + "".join(f"<tr><td><b>{k}:</b></td><td><span>{v}</span></td></tr>" for k, v in rows) + "</table>"
            career = [(k, v if k != "Carrera" else
                       "<a href=javascript:AbrirVentanaMalla('http://www.mallacurricular.espol.edu.ec/Malla/Index?token=x')>"
                       + v.replace("|", "</a><br />")) for k, v in portal.career()]
            student = card([*PORTAL_CARD, ("Promedio General en las materias aprobadas", portal.gpa())])
            return self._page(sid, session, "Información General", (
                f'<h1>Información General</h1><table><tr><td>{student}</td><td><img id="ctl00_contenido_imgEstudiante" '
                f'src="data:image/jpeg;base64,AAAA" /></td></tr></table><h1>Información de la Carrera</h1>{card(career)}'))
        if page == "calificacionesbusqueda_.aspx":
            listed = ""
            if consulted and asked == PORTAL_TERM:
                from html import escape
                rows = ""
                for code, name, theory, practice, first, second, practical, better, average in PORTAL_GRADES:
                    shown = escape(name)
                    if practice:
                        args = (name, first, second, better, practical, first, "70", "30", average)
                        shown = ('<a href="javascript:Presentar(' + ",".join(f"&#39;{escape(v)}&#39;" for v in args)
                                 + f')">{shown}</a>')
                    rows += (f"<tr><td>{asked[0]} - {asked[1][0]} </td><td>{code} </td><td>{shown}</td>"
                             + _cells([theory, practice, first, second, practical, better, average, "1"]) + "<td>&nbsp;</td></tr>")
                listed = ('<div id="ctl00_contenido_panelBusqueda"><h1>Calificaciones</h1><table id="ctl00_contenido_tbl_Calificaciones">'
                          '<thead><tr><th rowspan="2">Año<br>Término</th><th rowspan="2">Código</th><th rowspan="2">Materia</th>'
                          '<th colspan="2">Paralelo</th><th colspan="4">Exámenes</th><th rowspan="2">Prom.</th>'
                          '<th rowspan="2">No.<br>Vez</th><th rowspan="2">Estado</th></tr><tr><th>Teórico</th><th>Práctico</th>'
                          '<th>&nbsp;1&nbsp;</th><th>&nbsp;2&nbsp;</th><th>Práct.</th><th>Mej.</th></tr></thead>'
                          f'<tbody>{rows}</tbody></table></div>')
            dialog = ('<div id="dialog-message3" title="Ponderación"><table><thead><tr><th colspan="2">COMPONENTE</th>'
                      '<th>NOTAS</th><th>SUBTOTAL</th><th>% PARA PROMEDIO</th><th>PROMEDIO FINAL</th></tr></thead>'
                      '<tbody><tr><td rowspan="3">Teórico</td><td>Parcial</td><td id="nota1teorico"></td>'
                      '<td rowspan="3" id="subpromedio"></td><td rowspan="3"></td><td rowspan="4" id="promedio"></td></tr>'
                      '<tr><td>Final</td><td></td></tr><tr><td>Mejoramiento</td><td></td></tr>'
                      '<tr><td>Práctico</td><td>Final</td><td></td><td></td><td></td></tr></tbody></table></div>')
            return self._page(sid, session, "Calificaciones", '<h1>Búsqueda de Calificaciones</h1>'
                              + _term_boxes(*asked).replace("{select}", "") + listed + dialog)
        if page == "creditoscarrera.aspx":
            grids = "".join(_grid(f"dlCreditos_ctl{i:02d}_GridView1", ["Cod. Materia", "Materia", "# Créditos", "Estado", ""],
                                  [(*r, "") for r in rows]) for i, (_, _, rows) in enumerate(portal.credits()))
            taken = {kind: sum(int(r[2]) for r in rows) for kind, _, rows in portal.credits()}
            summary = _grid("gridResumen", ["Tipo de Crédito", "# Tomados", "# del Flujo", "Excedente", "Reajuste"],
                            [(kind, taken[kind], req, taken[kind] - int(req), "") for kind, req, _ in portal.credits()])
            card = ('<table><tr><td>Matrícula:</td><td>202499999</td></tr><tr><td>Nombre:</td><td>ESTUDIANTE DE PRUEBA</td>'
                    '</tr><tr><td>Carrera:</td><td>Computación</td></tr></table>')
            total = (f'<table><tr><td><b>Total de Créditos:</b> <span id="ctl00_contenido_dlCreditos_ctl00_Label2">'
                     f'{sum(taken.values())}</span></td><td></td></tr></table>')
            return self._page(sid, session, "Créditos", f"<h1>Créditos por Carrera</h1>{card}{grids}{total}{summary}")
        if page == "horarioview.aspx":
            grid = _week_grid(PORTAL_CLASSES) if consulted and asked == PORTAL_TERM else ""
            return self._page(sid, session, "Horario", '<h1>Consulta tu horario</h1>'
                              + _term_boxes(*asked).replace("{select}", "") + grid)
        if page == "horarioexview.aspx":
            kind = form.get("ctl00$contenido$cmbParcial", "1")
            options = "".join(f'<option{" selected=\"selected\"" if v == kind else ""} value="{v}">{t}</option>'
                              for v, t in PORTAL_EXAM_KINDS.items())
            select = f'<select name="ctl00$contenido$cmbParcial" id="ctl00_contenido_cmbParcial">{options}</select>'
            grid = _week_grid(PORTAL_EXAMS[PORTAL_EXAM_KINDS[kind]]) if consulted and asked == PORTAL_TERM else ""
            return self._page(sid, session, "Horario de exámenes", '<h1>Consulta tu horario de Exámenes</h1>'
                              + _term_boxes(*(asked if form else PORTAL_TERM)).replace("{select}", select) + grid,
                              allowed={"ctl00$contenido$cmbParcial": list(PORTAL_EXAM_KINDS)})
        return self._send(404, b"not found", "text/html")


class FakePages(_Server):
    """docs/ as GitHub Pages serves it, to a real browser; `relay` joins each page's connect-src."""

    TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".png": "image/png"}

    def __init__(self, root: Path, relay: str):
        super().__init__(_PagesHandler)
        self.root, self.relay = root, relay


class _PagesHandler(_Quiet):
    def do_GET(self):
        pages: FakePages = self.server.owner
        path = unquote(urlsplit(self.path).path)
        target = (pages.root / path.lstrip("/")).resolve()
        if target.is_dir():
            target = target / "index.html"
        if pages.root.resolve() not in target.parents or not target.is_file():
            return self._send(404, b"not found", "text/plain")
        body = target.read_bytes()
        if target.suffix == ".html":
            body = body.replace(b"connect-src https://*.workers.dev", f"connect-src https://*.workers.dev {pages.relay}".encode())
        self._send(200, body, pages.TYPES.get(target.suffix, "application/octet-stream"))
