"""One MCP server for every Hermes profile (`espol-bot mcp-http`), instead of a stdio process per profile (~80 MB
each, one more per friend).

With VINCI_MCP_URL set (the Docker image), hermes_setup writes in each profile's folder what its stdio server would
have got (`vinci-mcp.json`: the `mcp` arguments, the env, and a token of its own) and points the profile's
config.yaml at `<VINCI_MCP_URL>/mcp/<profile>` with that token. Each request runs in a forked child that takes that
profile's env and config only (mcp_server.serve_http); deleting the profile deletes its token.
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from espol_bot.mcp_server import Server

log = logging.getLogger(__name__)

SPEC_FILE = "vinci-mcp.json"
PROFILE_PATH = re.compile(r"/mcp/([a-z0-9][a-z0-9_-]{0,63})/?")
# What Hermes hands a stdio MCP server from its own env (_build_safe_env in tools/mcp_tool_config.py); the profile's
# `env` comes on top, as there.
SAFE_ENV = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR")


def url_for(base: str, profile: str) -> str:
    return f"{base.rstrip('/')}/mcp/{profile}"


def write_spec(profile: Path, args: list[str], env: dict[str, str]) -> str:
    """The profile's spec, keeping its token across runs; returns the token."""
    path = profile / SPEC_FILE
    try:
        token = json.loads(path.read_text(encoding="utf-8")).get("token")
    except (OSError, ValueError):
        token = None
    token = token if isinstance(token, str) and len(token) >= 32 else secrets.token_urlsafe(32)
    text = json.dumps({"args": args, "env": env, "token": token}, ensure_ascii=False, indent=1) + "\n"
    try:
        if path.read_text(encoding="utf-8") == text:
            return token
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    tmp.replace(path)
    return token


def drop_spec(profile: Path) -> None:
    (profile / SPEC_FILE).unlink(missing_ok=True)


def serve(host: str, port: int) -> int:
    from espol_bot import cli, herramientas  # noqa: F401  imported once here, shared by every forked child
    from espol_bot.config import hermes_root
    from espol_bot.mcp_server import serve_http

    root = hermes_root()
    base_env = {k: v for k, v in os.environ.items() if k in SAFE_ENV or k.startswith("XDG_")}
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("bot", choices=["vinci", "materia", "amigo"])
    parser.add_argument("--curso", default=None)
    parser.add_argument("--hermes-home", default=None)

    def route(path: str, authorization: str) -> Server | None:
        """In the request's child: that profile's tools, with this process now in its env; None when the path or the
        token do not match a profile."""
        match = PROFILE_PATH.fullmatch(urlsplit(path).path)
        if not match:
            return None
        try:
            spec = json.loads((root / "profiles" / match[1] / SPEC_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        token = spec.get("token") if isinstance(spec, dict) else None
        if not isinstance(token, str) or len(token) < 32 or \
                not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
            return None
        os.environ.clear()
        os.environ.update(base_env)
        os.environ.update({str(k): str(v) for k, v in (spec.get("env") or {}).items()})
        args = parser.parse_args(spec.get("args") or [])
        cfg = cli.load_bot_config(cli.load_config())
        for handler in list(logging.root.handlers):  # the parent's stderr: this child logs to the profile's bot.log
            logging.root.removeHandler(handler)
        cli._logging(cfg)
        return cli.mcp_tools(cfg, args.bot, args.curso, args.hermes_home)

    def ready(bound: int) -> None:
        print(f"mcp-http: escuchando en http://{host}:{bound} ({root / 'profiles'})", flush=True)

    log.info("mcp-http: %s:%s", host, port)
    serve_http(host, port, route, ready)
    return 0
