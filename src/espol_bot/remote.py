"""vinci-check remote: debug the live Vinci container from the captain's PC, through the panel's /agente/ routes
(agent_api.py). The URL and AGENT_KEY live in ~/.config/vinci/remote.env (mode 600), written by `login`.

    vinci-check remote login [https://<panel domain>]   save the URL and the key (hidden prompt), and test them
    vinci-check remote status                           gateway, WhatsApp, every Vinci's health, stuck turns, errors
    vinci-check remote errors                           errors.log of the gateway and every profile, grouped
    vinci-check remote logs [name] [-n 200] [--grep re] [-f] [--raw]
                                                        a log's tail (no name: the list; `all`: every profile's
                                                        gateway.log, each line with its profile); masked unless --raw
    vinci-check remote turns [--profile vinci] [-n 30] [--session id] [--raw]
                                                        recent turns of a profile; friends' text only with --raw
    vinci-check remote run <command…> [--timeout 300]   a shell command in the container, as hermes, in /opt/data
    vinci-check remote doctor | restart                 `espol-bot doctor` | `hermes gateway restart`
    vinci-check remote get <path> [local] | put <local> <path>
                                                        copy a file under /opt/data down or up
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import shlex
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from aula_core.config import parse_env_file
from espol_bot.agent_api import HEADER, signature

URL_KEY, SECRET_KEY = "VINCI_REMOTE_URL", "VINCI_AGENT_KEY"
NOT_FOUND = ("404: the container refused the request. Either the key is wrong (mint a new one with "
             "`espol-bot panel --clave-agente` in the Coolify Terminal, then `vinci-check remote login`), this PC's "
             "clock is more than 2 minutes off, or the container runs a build without /agente/ (Redeploy).")


class RemoteError(Exception):
    pass


def settings_path() -> Path:
    if os.environ.get("VINCI_REMOTE_FILE"):
        return Path(os.environ["VINCI_REMOTE_FILE"])
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "vinci" / "remote.env"


def _settings() -> tuple[str, str]:
    path = settings_path()
    values = parse_env_file(path) if path.exists() else {}
    url, key = values.get(URL_KEY, "").rstrip("/"), values.get(SECRET_KEY, "")
    if not (url and key):
        raise RemoteError(f"No remote access saved in {path}. Run `vinci-check remote login https://<panel domain>`.")
    return url, key


def _save(url: str, key: str) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"# vinci-check remote: full access to the live Vinci container. Never share this file.\n"
                 f"{URL_KEY}={url}\n{SECRET_KEY}={key}\n")
    os.chmod(path, 0o600)
    return path


def call(method: str, route: str, params: dict | None = None, body: bytes = b"", *, stream: bool = False,
         settings: tuple[str, str] | None = None, timeout: float = 60) -> requests.Response:
    url, key = settings or _settings()
    params = {k: v for k, v in (params or {}).items() if v not in (None, "", False)}
    target = f"/agente/{route}" + (f"?{urlencode(params)}" if params else "")
    stamp, nonce = str(int(time.time())), secrets.token_hex(16)
    sign = signature(key, stamp, nonce, method, target, body)
    try:
        response = requests.request(method, url + target, data=body or None, stream=stream, timeout=(15, timeout),
                                    headers={HEADER: f"t={stamp},n={nonce},s={sign}"}, allow_redirects=False)
    except requests.RequestException as exc:
        raise RemoteError(f"Could not reach {url}: {exc}") from exc
    if response.status_code == 404 and response.headers.get("Content-Type", "").startswith("application/json"):
        detail = response.json().get("error")
        if detail == "no existe":
            raise RemoteError(NOT_FOUND)
        raise RemoteError(json.dumps(response.json(), ensure_ascii=False))
    if response.status_code >= 400:
        raise RemoteError(f"{response.status_code}: {response.text[:1000]}")
    return response


def _lines(response: requests.Response):
    """A streamed body's lines as they arrive: iter_lines waits for a full 512-byte chunk."""
    pending = b""
    while chunk := response.raw.read1(65536):
        pending += chunk
        *done, pending = pending.split(b"\n")
        for line in done:
            yield line.decode("utf-8", errors="replace")
    if pending:
        yield pending.decode("utf-8", errors="replace")


def login(url: str | None) -> int:
    url = (url or input("URL del panel (https://…): ")).strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise RemoteError("The URL must start with https://")
    if sys.stdin.isatty():
        key = getpass.getpass("Clave del agente (no se ve al escribir): ").strip()
    else:
        key = sys.stdin.readline().strip()
    if not key:
        raise RemoteError("No key given.")
    state = call("GET", "estado", settings=(url, key)).json()
    path = _save(url, key)
    print(f"Saved in {path} (mode 600). The container answers: gateway {state['gateway']['state']}.")
    return 0


def status(as_json: bool) -> int:
    state = call("GET", "estado").json()
    if as_json:
        print(json.dumps(state, ensure_ascii=False, indent=1))
        return 0
    gw = state["gateway"]
    print(f"gateway: {gw['state']} (alive: {gw['alive']}, pid {gw['pid']}, active agents {gw['active_agents']}, "
          f"updated {gw['updated_at']}), model {state['model']}")
    for name, platform in gw["platforms"].items():
        extra = f" — {platform['error_message']}" if platform.get("error_message") else ""
        print(f"  {name}: {platform['state']}{extra}")
    print(f"  served profiles: {', '.join(gw['served']) or '?'}")
    bad = 0
    for person in state["people"]:
        for check in person["checks"]:
            if check["level"] != "ok" or not person["friend"]:
                mark = {"ok": "✅", "fail": "❌"}.get(check["level"], "⚠️")
                bad += check["level"] == "fail"
                print(f"{mark} {person['name']} · {check['name']}: {check['detail']}"
                      + (f"  → {check['fix']}" if check.get("fix") and check["level"] != "ok" else ""))
    for lease in state["leases"]:
        print(f"{'❌ stuck' if lease['stuck'] else '…'} turn on {lease['profile']} for {lease['seconds']} s")
    for job in state["jobs"]:
        if job["status"] not in (None, "ok") or job["streak"]:
            print(f"❌ job {job['profile']}/{job['name']}: {job['status']} ×{job['streak']} {job['error'][:200]}")
    errors = [e for e in state["errors"] if e["level"] != "WARNING"]
    print(f"errors in 24 h: {len(errors)} kinds, warnings: {len(state['errors']) - len(errors)} kinds "
          "(`vinci-check remote errors`)")
    return 1 if bad or not gw["alive"] else 0


def errors(limit: int, as_json: bool) -> int:
    found = call("GET", "estado").json()["errors"][:limit]
    if as_json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
        return 0
    for group in found:
        print(f"[{group['level']}] ×{group['count']} last {group['last']} in {', '.join(group['sources'])}\n"
              f"  {group['sample']}")
    if not found:
        print("No errors or warnings in the last 24 h.")
    return 0


def logs(name: str | None, lines: int, grep: str | None, follow: bool, raw: bool) -> int:
    if not name:
        print("all                          every gateway.log, each line with the profile that wrote it")
        for log, info in call("GET", "logs").json().items():
            print(f"{log:28} {info['bytes']:>12,} B  {info['path']}")
        return 0
    response = call("GET", "logs", {"f": name, "n": lines, "grep": grep, "follow": "1" if follow else None,
                                    "raw": "1" if raw else None}, stream=True)
    try:
        for line in _lines(response):
            if line or not follow:  # in a follow, an empty line is the server's heartbeat
                print(line, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        response.close()
    return 0


def turns(profile: str | None, lines: int, session: str | None, raw: bool, as_json: bool) -> int:
    data = call("GET", "turnos", {"perfil": profile, "n": lines, "sesion": session,
                                  "raw": "1" if raw else None}).json()
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return 0
    print(f"profile {data['profile']} ({data['kind']}), {len(data['turns'])} message(s)")
    current = None
    for turn in data["turns"]:
        if turn["session"] != current:
            current = turn["session"]
            print(f"— session {current} ({turn['source']}, {turn['chat_type']})")
        what = turn["text"] if turn["text"] is not None else f"<{turn['chars']} car., hidden>"
        calls = f"  → {', '.join(turn['calls'])}" if turn["calls"] else ""
        tool = f"[{turn['tool']}] " if turn["tool"] else ""
        print(f"  {turn['at']} {turn['role']}: {tool}{what.replace(chr(10), chr(10) + '    ')}{calls}")
    return 0


def run(command: str, timeout: float) -> int:
    response = call("POST", "run", body=json.dumps({"sh": command, "timeout": timeout}).encode(), stream=True,
                    timeout=max(60, timeout + 30))
    code = None
    try:
        for line in _lines(response):
            if not line:
                continue
            event = json.loads(line)
            if "o" in event:
                sys.stdout.write(event["o"])
                sys.stdout.flush()
            elif "exit" in event:
                code = event["exit"]
                if event.get("stopped"):
                    print(f"\n[remote] stopped: {event['stopped']}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n[remote] interrupted: the container stops the command", file=sys.stderr)
        return 130
    finally:
        response.close()
    if code is None:
        print("[remote] the stream ended without an exit code", file=sys.stderr)
        return 255
    return code if 0 <= code < 256 else 1


def get(remote_path: str, local: str | None) -> int:
    data = call("GET", "archivo", {"ruta": remote_path}, timeout=300).content
    target = Path(local or Path(remote_path).name)
    if target.is_dir():
        target = target / Path(remote_path).name
    target.write_bytes(data)
    print(f"{remote_path} → {target} ({len(data):,} bytes)")
    return 0


def put(local: str, remote_path: str) -> int:
    answer = call("PUT", "archivo", {"ruta": remote_path}, body=Path(local).read_bytes(), timeout=300).json()
    print(f"{local} → {answer['path']} ({answer['bytes']:,} bytes)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="vinci-check remote", description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n".join(__doc__.splitlines()[1:]))
    parser.add_argument("--json", action="store_true", help="machine-readable output (status, errors, turns)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("login", help="save the panel URL and the agent key (hidden prompt), and test them")
    p.add_argument("url", nargs="?")
    sub.add_parser("status", help="gateway, WhatsApp, every Vinci's health, stuck turns, error count")
    p = sub.add_parser("errors", help="the errors.log of the gateway and every profile, grouped")
    p.add_argument("-n", type=int, default=20)
    p = sub.add_parser("logs", help="a log's tail; with no name, the list of logs")
    p.add_argument("name", nargs="?", help="all (every gateway.log, each line with its profile), gateway, errors, bot, "
                                           "agent, <profile>/<log>, or a path under /opt/data")
    p.add_argument("-n", type=int, default=200, help="lines (default 200)")
    p.add_argument("--grep", help="only lines that match this regex (case-insensitive)")
    p.add_argument("-f", "--follow", action="store_true", help="keep printing new lines (Ctrl-C stops)")
    p.add_argument("--raw", action="store_true", help="no masking of numbers, names and message text")
    p = sub.add_parser("turns", help="recent turns of a profile")
    p.add_argument("--profile", help="vinci (default) or amigo-<name>")
    p.add_argument("-n", type=int, default=30)
    p.add_argument("--session", help="only this session id")
    p.add_argument("--raw", action="store_true", help="show the text of friends' and groups' chats too")
    p = sub.add_parser("run", help="a shell command in the container, as hermes, in /opt/data")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.add_argument("--timeout", type=float, default=300)
    sub.add_parser("doctor", help="espol-bot doctor in the container")
    sub.add_parser("restart", help="hermes gateway restart in the container")
    p = sub.add_parser("get", help="download a file under /opt/data")
    p.add_argument("path")
    p.add_argument("local", nargs="?")
    p = sub.add_parser("put", help="upload a file to a path under /opt/data (replaces it)")
    p.add_argument("local")
    p.add_argument("path")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "login":
            return login(args.url)
        if args.cmd == "status":
            return status(args.json)
        if args.cmd == "errors":
            return errors(args.n, args.json)
        if args.cmd == "logs":
            return logs(args.name, args.n, args.grep, args.follow, args.raw)
        if args.cmd == "turns":
            return turns(args.profile, args.n, args.session, args.raw, args.json)
        if args.cmd == "run":
            words = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not words:
                parser.error("run needs a command")
            return run(words[0] if len(words) == 1 else shlex.join(words), args.timeout)
        if args.cmd == "doctor":
            return run("espol-bot doctor", 120)
        if args.cmd == "restart":
            return run("hermes gateway restart", 180)
        if args.cmd == "get":
            return get(args.path, args.local)
        return put(args.local, args.path)
    except RemoteError as exc:
        print(f"❌ remote: {exc}", file=sys.stderr)
        return 1
