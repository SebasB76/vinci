"""A minimal MCP server, dependency-free: over stdio (newline-delimited JSON-RPC 2.0), or over Streamable HTTP
for every profile at once (`serve_http`).

Hermes connects to it from `mcp_servers:` in the profile's config.yaml and offers its tools to the model as
`mcp_<server>_<tool>`. It speaks the handshake plus the tools capability only: initialize, ping, tools/list,
tools/call. Anything else is "method not found".
"""

from __future__ import annotations

import gc
import json
import logging
import socketserver
import sys
import traceback
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

log = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
# Where the conversation behind a call happens: the vinci-botones plugin adds it to every call (pre_tool_call), so
# two chats at once never mix it up. It is not in any tool's schema: the model never sees or sets it.
CHANNEL_ARG = "_canal"
MAX_HTTP_BODY = 8 * 1024 * 1024


class ToolError(Exception):
    """A tool failure the model should read (bad arguments, not found, not allowed)."""


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[[dict], Any]
    properties: dict = field(default_factory=dict)
    required: list[str] = field(default_factory=list)
    read_only: bool = True

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {"type": "object", "properties": self.properties, "required": self.required,
                            "additionalProperties": False},
            "annotations": {"readOnlyHint": self.read_only, "destructiveHint": False, "openWorldHint": False},
        }


class Server:
    def __init__(self, name: str, version: str, tools: list[Tool], instructions: str = "",
                 on_channel: Callable[[dict], None] | None = None):
        self.name = name
        self.version = version
        self.tools = {t.name: t for t in tools}
        self.instructions = instructions
        self.on_channel = on_channel

    # -- one request ----------------------------------------------------------------------

    def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        msg_id = message.get("id")
        if msg_id is None:  # a notification (initialized, cancelled, ...): no answer
            return None
        try:
            result = self._dispatch(method, message.get("params") or {})
        except _RpcError as exc:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": exc.code, "message": str(exc)}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _dispatch(self, method: str | None, params: dict) -> dict:
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {
                "protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[-1],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version},
                **({"instructions": self.instructions} if self.instructions else {}),
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t.schema() for t in self.tools.values()]}
        if method == "tools/call":
            return self.call(str(params.get("name")), params.get("arguments") or {})
        raise _RpcError(-32601, f"Method not found: {method}")

    def call(self, name: str, arguments: dict) -> dict:
        tool = self.tools.get(name)
        if tool is None:
            return _text(f"No existe la herramienta «{name}». Disponibles: {', '.join(self.tools)}.", error=True)
        arguments = dict(arguments)
        channel = arguments.pop(CHANNEL_ARG, None)
        if self.on_channel is not None:
            self.on_channel(channel if isinstance(channel, dict) else {})
        unknown = set(arguments) - set(tool.properties)
        if unknown:
            return _text(f"Argumentos desconocidos para {name}: {', '.join(sorted(unknown))}.", error=True)
        missing = [k for k in tool.required if arguments.get(k) in (None, "")]
        if missing:
            return _text(f"Faltan argumentos para {name}: {', '.join(missing)}.", error=True)
        try:
            result = tool.handler(arguments)
        except ToolError as exc:
            return _text(str(exc), error=True)
        except Exception as exc:  # never kill the server over one bad call
            log.error("herramienta %s: %s\n%s", name, exc, traceback.format_exc())
            return _text(f"Error interno en {name}: {type(exc).__name__}: {exc}", error=True)
        return _text(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1))

    def reply(self, message: Any) -> dict | list | None:
        """The answer to one JSON-RPC message or batch; None for notifications and responses."""
        if isinstance(message, list):  # batches are not part of current MCP; answer each anyway
            return [r for r in (self.handle(m) for m in message if isinstance(m, dict)) if r] or None
        return self.handle(message) if isinstance(message, dict) else None

    # -- the stdio loop -------------------------------------------------------------------

    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                reply = self.reply(json.loads(line))
            except json.JSONDecodeError:
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()
        return 0


# -- Streamable HTTP, one process for every profile ------------------------------------------


def serve_http(host: str, port: int, route: Callable[[str, str], "Server | None"],
               on_ready: Callable[[int], None] | None = None) -> None:
    """Streamable HTTP, stateless and JSON-only (no session id, no SSE stream: GET is 405). Each request runs in its
    own forked child, which `route(path, authorization)` points at one profile (its env, its config) or refuses
    with None (404). The parent never loads a profile, so no profile's state or env reaches another's request."""
    httpd = _ForkingHTTPServer((host, port), _Handler)
    httpd.route = route
    gc.freeze()  # what the parent imported stays shared with each child instead of being copied on write
    if on_ready is not None:
        on_ready(httpd.server_address[1])
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


class _ForkingHTTPServer(socketserver.ForkingMixIn, HTTPServer):
    allow_reuse_address = True
    block_on_close = False
    route: Callable[[str, str], "Server | None"]

    def server_bind(self) -> None:  # HTTPServer's would look up the host's FQDN, which can stall
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "vinci-mcp"

    def do_POST(self) -> None:
        body = self._body()
        if body is None:
            return self._send(413)
        try:
            server = self.server.route(self.path, self.headers.get("Authorization") or "")
        except Exception as exc:  # a profile whose config no longer loads: Hermes retries later
            log.error("mcp http %s: %s\n%s", self.path, exc, traceback.format_exc())
            return self._send(500)
        if server is None:
            return self._send(404)
        try:
            reply = server.reply(json.loads(body))
        except (json.JSONDecodeError, UnicodeDecodeError):
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if reply is None:
            return self._send(202)
        self._send(200, json.dumps(reply, ensure_ascii=False).encode())

    def do_GET(self) -> None:  # no server-initiated stream: the client then only POSTs
        self._send(405)

    do_DELETE = do_HEAD = do_PUT = do_GET

    def _body(self) -> bytes | None:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            chunks, size = [], 0
            while (n := int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)) > 0:
                size += n
                if size > MAX_HTTP_BODY:
                    return None
                chunks.append(self.rfile.read(n))
                self.rfile.readline()
            while self.rfile.readline().strip():  # trailers
                pass
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length <= MAX_HTTP_BODY else None

    def _send(self, status: int, body: bytes = b"") -> None:
        # one request per connection, so a child never serves a second request (maybe another profile's)
        self.close_connection = True
        self.send_response(status)
        if status == 405:
            self.send_header("Allow", "POST")
        if body:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        log.debug("mcp http: " + format, *args)


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _text(text: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": error}
