"""Local stand-ins for Canvas and the Telegram Bot API, used only by the E2E test.

FakeCanvas serves the recorded fixtures under fixtures/canvas/<state>/ the way
Canvas does: Bearer auth, `Link` pagination (capped at 2 items per page so the
client must follow it), `X-Rate-Limit-Remaining`, one 429 to exercise backoff,
a course whose Files tab is hidden (401 unauthorized), and file downloads.
API paths added to `failing` answer 503 until removed (a resource that keeps failing).
It answers 405 to anything but GET and records every request.

TelegramStub records each sendMessage call instead of delivering it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_SIZE = 2
DOWNLOADS = {5001: "capitulo-3-derivadas.pdf", 5101: "semana-2-cinematica.pptx"}
THROTTLE_ONCE = "/api/v1/courses/102/assignments"


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
    def __init__(self, token: str):
        super().__init__(_CanvasHandler)
        self.token = token
        self.state = "state1"
        self.requests: list[tuple[str, str]] = []
        self.throttled = False
        self.failing: set[str] = set()
        self.lock = threading.Lock()

    def load(self, api_path: str):
        for state in dict.fromkeys([self.state, "state1"]):
            path = FIXTURES / "canvas" / state / (api_path.strip("/") + ".json")
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8").replace("{{BASE}}", self.base))
        return None


class _Quiet(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass

    def _send(self, status: int, body: bytes, content_type="application/json; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data, headers=None):
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), headers=headers)


class _CanvasHandler(_Quiet):
    def _refuse(self):
        canvas: FakeCanvas = self.server.owner
        with canvas.lock:
            canvas.requests.append((self.command, self.path))
        self._json(405, {"errors": [{"message": "El bot solo debe leer"}]})

    do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

    def do_GET(self):
        canvas: FakeCanvas = self.server.owner
        with canvas.lock:
            canvas.requests.append(("GET", self.path))
        if self.headers.get("Authorization") != f"Bearer {canvas.token}":
            return self._json(401, {"errors": [{"message": "Invalid access token."}]},
                              {"WWW-Authenticate": 'Bearer realm="canvas-lms"'})
        url = urlsplit(self.path)
        quota = {"X-Rate-Limit-Remaining": "599.12", "X-Request-Cost": "0.018"}

        if url.path.startswith("/files/") and url.path.endswith("/download"):
            file_id = int(url.path.split("/")[2])
            name = DOWNLOADS.get(file_id)
            if not name:
                return self._json(404, {"errors": [{"message": "The specified resource does not exist."}]})
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


class TelegramStub(_Server):
    def __init__(self, token: str):
        super().__init__(_TelegramHandler)
        self.token = token
        self.messages: list[dict] = []
        self.lock = threading.Lock()


class _TelegramHandler(_Quiet):
    def do_POST(self):
        stub: TelegramStub = self.server.owner
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path != f"/bot{stub.token}/sendMessage":
            return self._json(404, {"ok": False, "error_code": 404, "description": "Not Found"})
        with stub.lock:
            stub.messages.append(body)
            message_id = len(stub.messages)
        self._json(200, {"ok": True, "result": {"message_id": message_id, "chat": {"id": int(body["chat_id"]),
                                                                                   "type": "private"}}})
