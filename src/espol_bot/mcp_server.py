"""A minimal MCP server over stdio (newline-delimited JSON-RPC 2.0), dependency-free.

Hermes connects to it as a stdio MCP server (`mcp_servers:` in the profile's
config.yaml) and offers its tools to the model as `mcp_<server>_<tool>`. It speaks
the handshake plus the tools capability only: initialize, ping, tools/list,
tools/call. Anything else is "method not found".
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")


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
    def __init__(self, name: str, version: str, tools: list[Tool], instructions: str = ""):
        self.name = name
        self.version = version
        self.tools = {t.name: t for t in tools}
        self.instructions = instructions

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

    # -- the stdio loop -------------------------------------------------------------------

    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            else:
                if isinstance(message, list):  # batches are not part of current MCP; answer each anyway
                    replies = [r for r in (self.handle(m) for m in message if isinstance(m, dict)) if r]
                    reply = replies or None
                else:
                    reply = self.handle(message) if isinstance(message, dict) else None
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()
        return 0


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _text(text: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": error}
