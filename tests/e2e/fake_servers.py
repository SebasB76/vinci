"""Local stand-ins for Canvas and the Telegram Bot API, used only by the E2E test.

FakeCanvas serves the recorded fixtures under fixtures/canvas/<state>/ (or another set) the way
Canvas does: Bearer auth, access-token creation/deletion, public iCal/Atom feeds,
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

FakeTelegram stands in for the Bot API of several bots at once (Vinci and each subject
bot, one token each): it records every call, answers getMe, keeps inline buttons, hands
queued updates (text, photo, voice, document, button presses) to getUpdates long polls,
serves the files behind getFile, and plays Telegram's part in managed bots (Bot API 9.6): a
bot marked as a manager reports can_manage_bots, the captain can "create" a bot from its
request_managed_bot button (through the creation screen Telegram shows for it), and
getManagedBotToken hands the manager that bot's token. A call listed in `throttle` answers 429
once, with that retry_after.
Each bot has a name (getMe's first_name, getMyName; setMyName renames it), and
setMyProfilePhoto (Bot API 9.4) takes only a fresh static JPG upload, as Telegram does, and keeps
every photo each bot set. Every chat message a bot sends is kept in order. As Telegram does,
deleteWebhook with drop_pending_updates discards what the bot had queued; a (token, method) in
`slow` answers that many seconds late.

FakeDSpace stands in for ESPOL's DSpace (www.dspace.espol.edu.ec, through `[test] link_hosts`): the REST
`filtered-items` search, which runs a `matches` title regex the way DSpace does, an item by its handle with its
bitstreams, and their download. Items come from fixtures/dspace/items.json; one is stored inside the
multipart/form-data envelope it was uploaded with, as many real ones are. It records every request with its headers.

BrokenIPv6 makes a server reachable as `localhost` where IPv6 is broken and IPv4 works, like
the captain's network towards api.telegram.org: `localhost` resolves to ::1 first, and a listener
there with a full accept queue drops every new SYN, so an IPv6 connect hangs until it times out.

ScriptedLLM is an OpenAI-compatible chat-completions endpoint whose answers come from a
Python function (the test's script): it sees the whole request, so it can pick a tool
the request offers, and it records each request (including the tools offered).
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_SIZE = 2
DOWNLOADS = {5001: "capitulo-3-derivadas.pdf", 5005: "capitulo-3-derivadas.pdf", 5101: "semana-2-cinematica.pptx",
             5010: "silabo-matg1049.pdf", 5301: "silabo-matg1049.pdf", 5102: "lectura-vectores-escaneada.pdf"}
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
        self.calendar_feed = ""
        self.announcement_feeds: dict[str, str] = {}
        self.lock = threading.Lock()

    @property
    def token(self) -> str:
        return self._token

    @token.setter
    def token(self, value: str) -> None:
        """Compatibility with older E2E stages: make exactly this token valid."""
        with self.lock:
            self._token = value
            self.valid_tokens = {value}
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

    def load(self, api_path: str):
        # Each stateN holds only what changed since the one before it.
        for state in (f"state{n}" for n in range(int(self.state.removeprefix("state")), 0, -1)):
            path = self.fixtures / state / (api_path.strip("/") + ".json")
            if path.is_file():
                text = path.read_text(encoding="utf-8").replace("{{BASE}}", self.base).replace("{{WEB}}", self.web)
                return json.loads(text)
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
        with canvas.lock:
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
        if url.path == "/feeds/calendars/user-e2e.ics":
            return self._send(200, canvas.calendar_feed.encode(), "text/calendar; charset=utf-8")
        if url.path in canvas.announcement_feeds:
            return self._send(200, canvas.announcement_feeds[url.path].encode(),
                              "application/atom+xml; charset=utf-8")
        if not self._authorized(canvas):
            return self._json(401, {"errors": [{"message": "Invalid access token."}]},
                              {"WWW-Authenticate": 'Bearer realm="canvas-lms"'})
        quota = {"X-Rate-Limit-Remaining": "599.12", "X-Request-Cost": "0.018"}

        if url.path == "/api/v1/users/self":
            return self._json(200, {"id": 42, "name": "Estudiante E2E"}, quota)
        if url.path == "/api/v1/users/self/user_generated_tokens":
            with canvas.lock:
                tokens = [canvas.token_json(token) for token, token_id in canvas.token_ids.items()
                          if token_id not in canvas.deleted]
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

        data = canvas.load(url.path[len("/api/v1/"):])
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

class FakeTelegram(_Server):
    """bots: {token: username}; a bot's name starts as its username. Chat ids are the captain's
    user id (private chats)."""

    def __init__(self, bots: dict[str, str]):
        super().__init__(_TelegramHandler)
        self.bots = dict(bots)
        self.calls: list[dict] = []          # every API call: {"bot", "method", "params", "at"}
        self.messages: list[dict] = []       # outgoing chat messages, in order: {"bot", "method", **params}
        self.files: dict[str, tuple[str, bytes]] = {}
        self.updates: dict[str, list[dict]] = {}
        self.pushed: dict[int, dict] = {}       # every update handed out, by update_id
        self.managers: set[str] = set()         # tokens of bots that may manage other bots
        self.managed: dict[int, tuple[str, str]] = {}  # managed bot id -> (manager token, bot token)
        self.profile_photos: dict[str, list[bytes]] = {}  # username -> every photo it set, in order
        self.names: dict[str, str] = {}  # token -> the bot's name, when it is not its username
        self.throttle: dict[tuple[str, str], int] = {}  # (username, method) -> retry_after of its next call
        self.slow: dict[tuple[str, str], float] = {}  # (token, method) -> seconds before answering
        self.cond = threading.Condition()
        self.lock = self.cond
        # Hermes remembers the update ids it already handled, even across restarts: start from the clock.
        self._next_update = int(time.time()) * 10
        self._next_message = 1

    def add_bot(self, token: str, username: str, name: str | None = None) -> None:
        with self.cond:
            self.bots[token] = username
            if name:
                self.names[token] = name

    def name_of(self, token: str) -> str:
        with self.cond:
            return self.names.get(token, self.bots[token])

    def bot_id(self, token: str) -> int:
        return int(token.split(":", 1)[0])

    # -- what the captain does -------------------------------------------------------------

    def _push(self, token: str, update: dict) -> int:
        with self.cond:
            self._next_update += 1
            update["update_id"] = self._next_update
            self.updates.setdefault(token, []).append(update)
            self.pushed[self._next_update] = update
            self.cond.notify_all()
            return self._next_update

    def _message(self, user_id: int, **fields) -> dict:
        with self.cond:
            self._next_message += 1
            message_id = self._next_message
        user = {"id": user_id, "is_bot": False, "first_name": "Capitán", "language_code": "es"}
        return {"message_id": message_id, "date": int(time.time()), "chat": {"id": user_id, "type": "private",
                "first_name": "Capitán"}, "from": user, **fields}

    def _file(self, name: str, data: bytes) -> dict:
        with self.cond:
            file_id = f"file{len(self.files) + 1}"
            self.files[file_id] = (name, data)
        return {"file_id": file_id, "file_unique_id": f"u{file_id}", "file_size": len(data)}

    def send_text(self, token: str, user_id: int, text: str, reply_to: dict | None = None) -> int:
        extra = {"reply_to_message": reply_to} if reply_to else {}
        return self._push(token, {"message": self._message(user_id, text=text, **extra)})

    def send_web_app_data(self, token: str, user_id: int, data: str, button_text: str) -> int:
        """What a Mini App opened from a keyboard button hands the bot (Telegram.WebApp.sendData)."""
        return self._push(token, {"message": self._message(user_id, web_app_data={"data": data,
                                                                                  "button_text": button_text})})

    def send_photo(self, token: str, user_id: int, data: bytes, caption: str = "") -> int:
        photo = [{**self._file("photo.jpg", data), "width": 800, "height": 600}]
        return self._push(token, {"message": self._message(user_id, photo=photo, caption=caption)})

    def send_voice(self, token: str, user_id: int, data: bytes, duration: int = 4) -> int:
        voice = {**self._file("voice.ogg", data), "duration": duration, "mime_type": "audio/ogg"}
        return self._push(token, {"message": self._message(user_id, voice=voice)})

    def send_document(self, token: str, user_id: int, name: str, data: bytes, caption: str = "",
                      mime: str = "application/pdf") -> int:
        document = {**self._file(name, data), "file_name": name, "mime_type": mime}
        return self._push(token, {"message": self._message(user_id, document=document, caption=caption)})

    def as_incoming(self, token: str, record: dict, text: str) -> dict:
        """A message this bot sent, as Telegram shows it inside an update (e.g. reply_to_message)."""
        bot = {"id": self.bot_id(token), "is_bot": True, "first_name": self.bots[token], "username": self.bots[token]}
        return {"message_id": record["message_id"], "date": int(time.time()), "from": bot, "text": text,
                "chat": {"id": int(record["chat_id"]), "type": "private"}}

    @staticmethod
    def creation_screen(request: dict) -> tuple[str, str]:
        """(name, username) as Telegram's «create bot» screen offers a request_managed_bot suggestion, or
        AssertionError with the error it shows. The screen puts the suggested username in a 29-character field
        before its own fixed «bot»; a username has letters, digits and underscores, starts with a letter and
        has 5-32 characters."""
        name, stem = str(request.get("suggested_name") or ""), str(request.get("suggested_username") or "")
        assert 0 < len(name) <= 64, f"Name is invalid: {name!r}"
        assert len(stem) <= 29, f"Username is too long. ({stem!r})"
        username = stem + "bot"
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username), f"Username is invalid. ({username!r})"
        return name, username

    def create_managed_bot(self, manager: str, user_id: int, token: str, username: str, name: str) -> int:
        """The captain pressed the manager's request_managed_bot button and confirmed the new bot."""
        self.add_bot(token, username, name)
        bot = {"id": self.bot_id(token), "is_bot": True, "first_name": name, "username": username}
        with self.cond:
            self.managed[bot["id"]] = (manager, token)
        user = {"id": user_id, "is_bot": False, "first_name": "Capitán", "language_code": "es"}
        self._push(manager, {"managed_bot": {"user": user, "bot": bot}})
        return self._push(manager, {"message": self._message(user_id, managed_bot_created={"bot": bot})})

    def press(self, token: str, user_id: int, message: dict, data: str) -> int:
        user = {"id": user_id, "is_bot": False, "first_name": "Capitán", "language_code": "es"}
        bot = {"id": self.bot_id(token), "is_bot": True, "first_name": self.bots[token], "username": self.bots[token]}
        msg = {"message_id": message["message_id"], "date": int(time.time()), "chat": {"id": user_id, "type": "private"},
               "from": bot, "text": message.get("text", "")}
        markup = message.get("reply_markup")
        if isinstance(markup, dict) and "inline_keyboard" in markup:  # as the message looks now
            msg["reply_markup"] = markup
        return self._push(token, {"callback_query": {"id": f"cb{time.time_ns()}", "from": user,
                                                     "chat_instance": "1", "data": data, "message": msg}})

    def answer_poll(self, token: str, user_id: int, poll_id: str, option_ids: list[int]) -> int:
        """The captain (or anyone) votes in a non-anonymous poll this bot sent."""
        user = {"id": user_id, "is_bot": False, "first_name": "Capitán", "language_code": "es"}
        return self._push(token, {"poll_answer": {"poll_id": poll_id, "user": user, "option_ids": option_ids,
                                                  "option_persistent_ids": [f"o{i}" for i in option_ids]}})

    def pending(self, token: str) -> int:
        with self.cond:
            return len(self.updates.get(token, []))

    def wait_for(self, predicate, timeout: float = 60.0, interval: float = 0.2):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.cond:
                found = predicate(self)
            if found:
                return found
            time.sleep(interval)
        return None

    def messages_of(self, username: str) -> list[dict]:
        with self.cond:
            return [m for m in self.messages if m["bot"] == username]


class _TelegramHandler(_Quiet):
    def _params(self) -> dict:
        self.uploads: dict[str, bytes] = {}
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("application/json"):
            return json.loads(raw or b"{}")
        if ctype.startswith("multipart/form-data"):
            message = BytesParser(policy=email_policy).parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
            out = {}
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                payload = part.get_payload(decode=True) or b""
                filename = part.get_filename()
                if filename:
                    self.uploads[name] = payload
                out[name] = {"filename": filename, "size": len(payload)} if filename else payload.decode()
            return out
        return dict(parse_qsl(raw.decode(), keep_blank_values=True)) if raw else dict(parse_qsl(urlsplit(self.path).query))

    @staticmethod
    def _decode(params: dict) -> dict:
        out = {}
        for key, value in params.items():
            if isinstance(value, str) and value[:1] in "[{":
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            out[key] = value
        return out

    def do_GET(self):
        stub: FakeTelegram = self.server.owner
        parts = unquote(urlsplit(self.path).path).split("/")  # httpx sends the token's ":" as %3A
        if len(parts) >= 4 and parts[1] == "file" and parts[2].startswith("bot"):
            token = parts[2][3:]
            file_id = parts[3]  # file_path is "<file_id>/<name>"
            if token in stub.bots and file_id in stub.files:
                return self._send(200, stub.files[file_id][1], "application/octet-stream")
            return self._json(404, {"ok": False, "error_code": 404, "description": "Not Found"})
        return self._api(self._params())

    def do_POST(self):
        return self._api(self._params())

    def _api(self, params: dict):
        stub: FakeTelegram = self.server.owner
        parts = unquote(urlsplit(self.path).path).strip("/").split("/")
        if len(parts) != 2 or not parts[0].startswith("bot"):
            return self._json(404, {"ok": False, "error_code": 404, "description": "Not Found"})
        token, method = parts[0][3:], parts[1]
        if token not in stub.bots:
            return self._json(401, {"ok": False, "error_code": 401, "description": "Unauthorized"})
        username = stub.bots[token]
        params = self._decode(params)
        with stub.cond:
            stub.calls.append({"bot": username, "method": method, "params": params, "at": time.time()})
            retry = stub.throttle.pop((username, method), None)
            delay = stub.slow.get((token, method), 0)
        time.sleep(delay)
        if retry:
            return self._json(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": retry},
                                    "description": f"Too Many Requests: retry after {retry}"})
        me = {"id": stub.bot_id(token), "is_bot": True, "first_name": stub.name_of(token), "username": username,
              "can_join_groups": False, "can_read_all_group_messages": False, "supports_inline_queries": False}
        if method == "getMe":
            return self._ok({**me, "can_manage_bots": token in stub.managers})
        if method == "getManagedBotToken":
            owner, managed_token = stub.managed.get(int(params.get("user_id", 0) or 0), (None, None))
            if owner != token:
                return self._json(400, {"ok": False, "error_code": 400, "description": "Bad Request: bot not found"})
            return self._ok(managed_token)
        if method == "getUpdates":
            return self._ok(self._updates(stub, token, params))
        if method == "getMyName":
            return self._ok({"name": stub.name_of(token)})
        if method == "setMyName":
            name = str(params.get("name", ""))
            if not 0 < len(name) <= 64 or params.get("language_code"):
                return self._json(400, {"ok": False, "error_code": 400, "description": "Bad Request: invalid name"})
            with stub.cond:
                stub.names[token] = name
            return self._ok(True)
        if method == "setMyProfilePhoto":
            photo = params.get("photo") if isinstance(params.get("photo"), dict) else {}
            upload = self.uploads.get(str(photo.get("photo", "")).removeprefix("attach://"), b"")
            if photo.get("type") != "static" or not upload.startswith(b"\xff\xd8\xff"):
                return self._json(400, {"ok": False, "error_code": 400,
                                        "description": "Bad Request: a static profile photo must be a new JPG upload"})
            with stub.cond:
                stub.profile_photos.setdefault(username, []).append(upload)
            return self._ok(True)
        if method == "getFile":
            file_id = params.get("file_id")
            if file_id not in stub.files:
                return self._json(400, {"ok": False, "error_code": 400, "description": "Bad Request: invalid file_id"})
            name, data = stub.files[file_id]
            return self._ok({"file_id": file_id, "file_unique_id": f"u{file_id}", "file_size": len(data),
                             "file_path": f"{file_id}/{name}"})
        if method in ("sendMessage", "sendPhoto", "sendDocument", "sendVoice", "sendAudio", "sendVideo"):
            with stub.cond:
                stub._next_message += 1
                message_id = stub._next_message
                record = {"bot": username, "method": method, "message_id": message_id, **params}
                stub.messages.append(record)
                stub.cond.notify_all()
            chat = {"id": int(params.get("chat_id", 0)), "type": "private"}
            result = {"message_id": message_id, "date": int(time.time()), "chat": chat, "from": me}
            if "text" in params:
                result["text"] = params["text"]
            markup = params.get("reply_markup")
            if isinstance(markup, dict) and "inline_keyboard" in markup:  # a Message only carries inline ones
                result["reply_markup"] = markup
            return self._ok(result)
        if method == "sendPoll":
            options = params.get("options") or []
            if (params.get("type") != "quiz" or not 1 <= len(str(params.get("question", ""))) <= 300
                    or not 2 <= len(options) <= 10 or any(not 1 <= len(o.get("text", "")) <= 100 for o in options)
                    or not 0 <= int(params.get("correct_option_id", -1)) < len(options)
                    or len(str(params.get("explanation", ""))) > 200):
                return self._json(400, {"ok": False, "error_code": 400, "description": "Bad Request: invalid poll"})
            with stub.cond:
                stub._next_message += 1
                message_id = stub._next_message
                poll_id = f"poll{message_id}"
                stub.messages.append({"bot": username, "method": method, "message_id": message_id,
                                      "poll_id": poll_id, **params})
                stub.cond.notify_all()
            poll = {"id": poll_id, "question": params["question"], "type": "quiz", "total_voter_count": 0,
                    "is_closed": False, "is_anonymous": bool(params.get("is_anonymous", True)),
                    "allows_multiple_answers": False, "correct_option_id": int(params["correct_option_id"]),
                    "options": [{"text": o["text"], "voter_count": 0, "persistent_id": f"o{i}"}
                                for i, o in enumerate(options)]}
            chat = {"id": int(params.get("chat_id", 0)), "type": "private"}
            return self._ok({"message_id": message_id, "date": int(time.time()), "chat": chat, "from": me,
                             "poll": poll})
        if method in ("editMessageText", "editMessageReplyMarkup"):
            message_id = int(params.get("message_id", 0) or 0)
            with stub.cond:
                for record in stub.messages:
                    if record["bot"] == username and record["message_id"] == message_id:
                        if method == "editMessageText":
                            record["text"] = params.get("text", record.get("text"))
                            record["edited"] = record.get("edited", 0) + 1
                        else:
                            record["reply_markup"] = params.get("reply_markup")
                stub.cond.notify_all()
            chat = {"id": int(params.get("chat_id", 0) or 0), "type": "private"}
            return self._ok({"message_id": int(params.get("message_id", 0) or 0), "date": int(time.time()),
                             "chat": chat, "from": me, "text": params.get("text", "")})
        if method == "deleteWebhook":
            if str(params.get("drop_pending_updates", "")).lower() in ("true", "1"):
                with stub.cond:
                    stub.updates[token] = []
            return self._ok(True)
        if method == "getWebhookInfo":
            return self._ok({"url": "", "has_custom_certificate": False, "pending_update_count": 0})
        if method in ("getMyCommands",):
            return self._ok([])
        if method == "getChat":
            return self._ok({"id": int(params.get("chat_id", 0) or 0), "type": "private"})
        return self._ok(True)  # setMyCommands, deleteWebhook, answerCallbackQuery, sendChatAction, ...

    def _ok(self, result):
        self._json(200, {"ok": True, "result": result})

    @staticmethod
    def _updates(stub: FakeTelegram, token: str, params: dict) -> list[dict]:
        offset = int(params.get("offset", 0) or 0)
        wait = min(float(params.get("timeout", 0) or 0), 2.0)
        deadline = time.time() + wait
        with stub.cond:
            while True:
                queue = stub.updates.setdefault(token, [])
                queue[:] = [u for u in queue if u["update_id"] >= offset]
                if queue or time.time() >= deadline:
                    return list(queue)
                stub.cond.wait(max(0.05, deadline - time.time()))


class BrokenIPv6:
    """`localhost:<port>` for a server that listens on 127.0.0.1 only, with IPv6 blackholed: `base` is its
    URL, or None where this machine does not resolve localhost to ::1 first (nothing to break)."""

    def __init__(self, server: _Server):
        self.port = int(server.base.rsplit(":", 1)[1])
        self.base: str | None = None
        self._sockets: list[socket.socket] = []

    def __enter__(self):
        infos = socket.getaddrinfo("localhost", self.port, type=socket.SOCK_STREAM)
        if not infos or infos[0][0] != socket.AF_INET6:
            return self
        hole = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        hole.bind(("::1", self.port))
        hole.listen(0)
        filler = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        filler.setblocking(False)
        try:  # the one connection the backlog holds; it is never accepted
            filler.connect(("::1", self.port))
        except BlockingIOError:
            pass
        self._sockets = [hole, filler]
        time.sleep(0.2)
        self.base = f"http://localhost:{self.port}"
        return self

    def __exit__(self, *exc):
        for sock in self._sockets:
            sock.close()


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
