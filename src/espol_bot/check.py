"""vinci-check: drive and inspect the live bots the way the captain would, so an agent can verify its own work.

    vinci-check status                       gateway, poller, token chain and feeds
    vinci-check bots                         the bots chat/press may talk to
    vinci-check chat <bot> "<text>"          send as the captain, wait for the bot's reply
    vinci-check press <bot> "<button>"       press a button on the bot's latest message that has it
    vinci-check whatsapp [--profile vinci]   latest WhatsApp turns from Hermes's own record (read-only)
    vinci-check say "<text>"                 a message to Vinci in the captain's WhatsApp chat; waits for the reply
    vinci-check vote "<option>"              vote on Vinci's latest poll in the captain's WhatsApp chat
    vinci-check page token|dashboard         open the GitHub Pages page in headless Chrome
    vinci-check smoke                        all of the above that is safe, in about a minute

Every command takes --json and exits 1 when the check fails. chat and press act as the captain's Telegram
account through the `tg` CLI, and refuse any chat that is not one of his Vinci bots. say and vote reach only the
captain's own WhatsApp chat with Vinci: say goes into his Hermes session the way the Académico's held question
does (the vinci-whatsapp plugin injects it), so Vinci answers on his real WhatsApp; vote runs what his vote
would. Neither can write to a friend or a group.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from aula_core.config import ConfigError, load_config, now_utc
from aula_core.store import get_meta
from espol_bot import dashboard, health, materias, relay, whatsapp as wa
from espol_bot.config import BotConfig, load_bot_config, whatsapp_settings

TG = Path(os.environ.get("VINCI_TG", "~/.local/share/tg-user/tg")).expanduser()
HERMES = Path(os.environ.get("HERMES_BIN", "~/.local/bin/hermes")).expanduser()
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
BROWSER = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "browser.mjs"
CHROMES = ("chromium", "google-chrome-stable", "google-chrome", "brave")
TG_LINE = re.compile(r"^#(\d+) (\d\d:\d\d:\d\d) ([<>]) (.*?)(?:  \[buttons: (.*)\])?$")


@dataclass
class Result:
    check: str
    ok: bool
    detail: str
    messages: list[dict] = field(default_factory=list)
    fix: str | None = None


@dataclass
class Message:
    id: int
    time: str
    text: str
    buttons: list[str]


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    # TG_FULL keeps tg from cutting bot messages at 300 characters.
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env={**os.environ, "TG_FULL": "1"})


def _parse_tg(output: str) -> list[Message]:
    """Bot messages (`<` lines) from `tg send/read/click` output, oldest first."""
    found = []
    for line in output.splitlines():
        m = TG_LINE.match(line)
        if m and m[3] == "<":
            found.append(Message(int(m[1]), m[2], m[4].replace(" ⏎ ", "\n"),
                                 m[5].split(" | ") if m[5] else []))
    return found


def _sent_id(output: str) -> int:
    m = next((TG_LINE.match(line) for line in output.splitlines() if TG_LINE.match(line)), None)
    return int(m[1]) if m and m[3] == ">" else 0


def _db(cfg: BotConfig) -> sqlite3.Connection | None:
    conn = health.open_readonly(cfg.core.db_path)
    if conn is not None:
        conn.row_factory = sqlite3.Row  # the store helpers read rows by column name
    return conn


def allowed_bots(cfg: BotConfig) -> dict[str, str]:
    """username → who it is, for Vinci and every active subject bot."""
    bots = {}
    conn = _db(cfg)
    vinci = get_meta(conn, dashboard.USERNAME) if conn else None
    bots[(vinci or "vinci_espol_bot").lower()] = "Vinci"
    for s in materias.load(cfg.core):
        if s.active and s.username:
            bots[s.username.lower()] = f"{s.display} ({s.code})"
    return bots


def _guard(cfg: BotConfig, bot: str) -> str:
    if not cfg.telegram:
        raise ConfigError("Telegram is off ([channels] telegram = false): talk to Vinci with `vinci-check say`.")
    bot = bot.lstrip("@").lower()
    bots = allowed_bots(cfg)
    if bot not in bots:
        raise ConfigError(f"@{bot} is not one of the captain's Vinci bots, so vinci-check will not write to it as "
                          f"him. Allowed: {', '.join('@' + b for b in bots)}. Run `vinci-check bots` to list them.")
    if not TG.exists():
        raise ConfigError(f"No tg CLI at {TG}. Set VINCI_TG to its path.")
    return bot


def _errors_since(started: float) -> str | None:
    """The gateway's error log lines written since `started`, to explain a silent bot."""
    log = HERMES_HOME / "logs" / "errors.log"
    if not log.exists() or log.stat().st_mtime < started:
        return None
    lines = log.read_text(errors="ignore").splitlines()[-15:]
    stamp = datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M:%S")
    recent = [line for line in lines if line[:19] >= stamp]
    return "\n".join(recent[-5:]) or None


def status(cfg: BotConfig) -> Result:
    active = _run(["systemctl", "--user", "is-active", "hermes-gateway"], 10).stdout.strip()
    found = health.checks(cfg, _db(cfg), now_utc())
    failing = [c for c in found if c.level == health.FAIL]
    warns = [c for c in found if c.level == health.WARN]
    lines = [f"gateway: {active}"] + [f"{c.level}: {c.name}: {c.detail}" for c in found]
    served = next((line for line in _run([str(HERMES), "gateway", "status"], 20).stdout.splitlines()
                   if line.startswith("Served profiles")), None)
    if served:
        lines.insert(1, served)
    ok = active == "active" and not failing
    fix = ("hermes gateway restart" if active != "active" else
           next((c.fix for c in failing if c.fix), None))
    summary = f"{len(failing)} failing, {len(warns)} warnings" if ok or failing else "gateway not running"
    return Result("status", ok, summary + "\n" + "\n".join(lines), fix=fix)


def bots(cfg: BotConfig) -> Result:
    found = allowed_bots(cfg)
    return Result("bots", True, "\n".join(f"@{u}  {who}" for u, who in found.items()))


def chat(cfg: BotConfig, bot: str, text: str, timeout: float, settle: float) -> Result:
    bot = _guard(cfg, bot)
    started = time.time()
    sent = _run([str(TG), "send", bot, text, "--wait", str(timeout)], timeout + 30)
    if sent.returncode:
        return Result("chat", False, sent.stderr.strip() or sent.stdout.strip(), fix=f"{TG} status")
    sent_id = _sent_id(sent.stdout)
    replies = _parse_tg(sent.stdout)
    if replies:
        # A bot often answers in several messages; give the rest a moment, then read them all.
        time.sleep(settle)
        later = _parse_tg(_run([str(TG), "read", bot, "--limit", "15"], 60).stdout)
        replies = [m for m in later if m.id > sent_id] or replies
    took = time.time() - started
    if not replies:
        errors = _errors_since(started)
        detail = f"No reply from @{bot} in {timeout:.0f} s."
        if errors:
            detail += f"\nThe gateway logged errors meanwhile:\n{errors}"
        return Result("chat", False, detail, fix="vinci-check status; tail -30 ~/.hermes/logs/errors.log")
    return Result("chat", True, f"@{bot} answered in {took:.1f} s ({len(replies)} message(s))",
                  [asdict(m) for m in replies])


def press(cfg: BotConfig, bot: str, label: str, message_id: int | None, timeout: float) -> Result:
    bot = _guard(cfg, bot)
    if message_id is None:
        recent = _parse_tg(_run([str(TG), "read", bot, "--limit", "15"], 60).stdout)
        holder = next((m for m in reversed(recent) if any(label in b for b in m.buttons)), None)
        if holder is None:
            shown = sorted({b for m in recent for b in m.buttons})
            return Result("press", False, f"No recent message of @{bot} has a button with {label!r}. "
                                          f"Buttons in the last 15 messages: {', '.join(shown) or 'none'}.")
        message_id = holder.id
    clicked = _run([str(TG), "click", bot, str(message_id), label, "--wait", str(timeout)], timeout + 30)
    if clicked.returncode:
        return Result("press", False, clicked.stderr.strip() or clicked.stdout.strip())
    replies = _parse_tg(clicked.stdout)
    detail = f"pressed {label!r} on #{message_id}; " + (f"{len(replies)} new message(s)" if replies else
                                                       f"no new message in {timeout:.0f} s (the bot may have "
                                                       "edited the message instead: `vinci-check chat` won't show "
                                                       "that, `tg read` will)")
    return Result("press", True, detail, [asdict(m) for m in replies])


def whatsapp(profile: str, last: int, chat_type: str | None) -> Result:
    db = HERMES_HOME / "profiles" / profile / "state.db"
    if not db.exists():
        profiles = sorted(p.name for p in (HERMES_HOME / "profiles").glob("*") if (p / "state.db").exists())
        return Result("whatsapp", False, f"No Hermes profile {profile!r}. Profiles: {', '.join(profiles)}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    where = "source = 'whatsapp'" + (" AND chat_type = ?" if chat_type else "")
    session = conn.execute(f"SELECT id, chat_type, last_activity_at FROM sessions WHERE {where} "
                           "ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 1",
                           (chat_type,) if chat_type else ()).fetchone()
    if session is None:
        return Result("whatsapp", False, f"Profile {profile!r} has no WhatsApp conversation yet.")
    rows = conn.execute("SELECT role, content, tool_calls, timestamp FROM messages WHERE session_id = ? "
                        "AND role IN ('user', 'assistant') ORDER BY id DESC LIMIT ?", (session[0], last)).fetchall()
    turns = []
    for role, content, tool_calls, stamp in reversed(rows):
        tools = [c.get("function", {}).get("name") for c in json.loads(tool_calls or "[]") if isinstance(c, dict)]
        if not (content or "").strip() and not tools:
            continue
        turns.append({"time": datetime.fromtimestamp(stamp).strftime("%m-%d %H:%M") if stamp else "",
                      "who": "bot" if role == "assistant" else "person", "text": (content or "").strip()[:800],
                      "tools": [t for t in tools if t]})
    when = datetime.fromtimestamp(session[2]).strftime("%m-%d %H:%M") if session[2] else "?"
    return Result("whatsapp", True, f"profile {profile}, latest {session[1]} chat (last activity {when}), "
                                    f"{len(turns)} turn(s)", turns)


def _captain(cfg: BotConfig) -> str:
    settings = whatsapp_settings()
    if settings is None:
        raise ConfigError("Vinci is not on WhatsApp: secrets.env has no WHATSAPP_CAPTAIN.")
    return settings.captain


def _assistant_since(cfg: BotConfig, session_key: str, since: float) -> list[dict]:
    db = HERMES_HOME / "profiles" / cfg.hermes_profile / "state.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        rows = conn.execute("SELECT m.content, m.tool_calls, m.timestamp FROM messages m JOIN sessions s ON "
                            "s.id = m.session_id WHERE s.session_key = ? AND m.role = 'assistant' AND m.timestamp > ? "
                            "ORDER BY m.id", (session_key, since)).fetchall()
    finally:
        conn.close()
    found = []
    for content, tool_calls, stamp in rows:
        tools = [c.get("function", {}).get("name") for c in json.loads(tool_calls or "[]") if isinstance(c, dict)]
        if (content or "").strip() or tools:
            found.append({"time": datetime.fromtimestamp(stamp).strftime("%m-%d %H:%M:%S"), "who": "bot",
                          "text": (content or "").strip(), "tools": [t for t in tools if t]})
    return found


def say(cfg: BotConfig, text: str, timeout: float, settle: float) -> Result:
    session = relay.captain_session(cfg, _captain(cfg))
    started = time.time()
    relay.queue_turn(cfg, session, text, timedelta(seconds=timeout))
    replies, end = [], started + timeout
    while time.time() < end:
        replies = _assistant_since(cfg, session, started)
        if any(r["text"] for r in replies):
            time.sleep(settle)  # a turn with tools writes its answer last
            replies = _assistant_since(cfg, session, started)
            break
        time.sleep(1)
    if not any(r["text"] for r in replies):
        errors = _errors_since(started)
        detail = f"No reply from Vinci on WhatsApp in {timeout:.0f} s."
        if errors:
            detail += f"\nThe gateway logged errors meanwhile:\n{errors}"
        return Result("say", False, detail, replies, fix="vinci-check status; tail -30 ~/.hermes/logs/gateway.log")
    return Result("say", True, f"Vinci answered on WhatsApp in {time.time() - started:.1f} s", replies)


def vote(cfg: BotConfig, option: str) -> Result:
    captain = _captain(cfg)
    polls = wa.read_polls(cfg.core.data_dir)
    if not polls:
        return Result("vote", False, "Vinci has sent no poll yet.")
    poll_id, options = list(polls.items())[-1]
    label = next((o for o in options if option.lower() in o.lower()), None)
    if label is None:
        return Result("vote", False, f"The latest poll has no option with {option!r}: {', '.join(options)}.")
    bot = Path(sys.executable).with_name("espol-bot")
    done = subprocess.run([str(bot), "whatsapp-comando", "voto", captain, "--json"], capture_output=True, text=True,
                          timeout=120, input=json.dumps({"encuesta": poll_id, "opcion": label}))
    if done.returncode:
        return Result("vote", False, done.stderr.strip()[-500:] or "espol-bot whatsapp-comando failed")
    answer = json.loads(done.stdout or "{}")
    reply = str(answer.get("respuesta") or "")
    if reply:  # what the plugin would send after his vote, to his chat
        wa.send_text(cfg.whatsapp_bridge, wa.jid(captain), reply)
    return Result("vote", True, f"voted {label!r} on poll {poll_id}",
                  [{"time": datetime.now().strftime("%m-%d %H:%M:%S"), "who": "bot", "text": reply, "tools": []}])


def _chrome() -> str | None:
    return os.environ.get("CHROME") or next((p for p in map(shutil.which, CHROMES) if p), None)


def page(cfg: BotConfig, which: str) -> Result:
    if which == "dashboard":
        conn = _db(cfg)
        if not cfg.dashboard_page or conn is None:
            return Result("page", False, "No dashboard: dashboard.url is empty or espol.db does not exist yet.")
        # The data rides in the URL fragment, which the browser never sends to GitHub Pages.
        url = dashboard.page_url(cfg, dashboard.snapshot(conn, cfg, materias.load(cfg.core), now_utc()),
                                 base=cfg.dashboard_page)
        probe = "document.title + ' | ' + document.body.innerText.slice(0, 300)"
    else:
        url = cfg.token_form_url
        probe = "document.title + ' | form:' + !!document.querySelector('form') + ' | ' + " \
                "document.body.innerText.slice(0, 200)"
    chrome, node = _chrome(), shutil.which("node")
    if not (chrome and node):
        return Result("page", False, "Needs node and a Chrome/Chromium binary (set CHROME to its path).")
    script = json.dumps({"op": "open", "url": url}) + "\n"
    proc = subprocess.Popen([node, str(BROWSER), chrome], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        proc.stdin.write(script)
        proc.stdin.flush()
        opened = json.loads(proc.stdout.readline())
        if "error" in opened:
            return Result("page", False, f"{which}: {opened['error']}")
        time.sleep(1.5)  # let the page's script render after the load event
        proc.stdin.write(json.dumps({"op": "eval", "id": opened["id"], "expr": probe}) + "\n")
        proc.stdin.flush()
        seen = json.loads(proc.stdout.readline())
    finally:
        proc.stdin.close()
        proc.wait(timeout=20)
    text = str(seen.get("value") or seen.get("error") or "")
    ok = "error" not in seen and len(text.split(" | ", 1)[-1].strip()) > 0
    return Result("page", ok, f"{which}: {url.split('#')[0]}\n{text}")


def estado(cfg: BotConfig) -> Result:
    """Vinci's /estado as the captain's WhatsApp would get it (no model; not sent)."""
    bot = Path(sys.executable).with_name("espol-bot")
    done = subprocess.run([str(bot), "whatsapp-comando", "estado", _captain(cfg), "--json"], capture_output=True,
                          text=True, timeout=120)
    if done.returncode:
        return Result("estado", False, done.stderr.strip()[-500:])
    return Result("estado", True, str(json.loads(done.stdout or "{}").get("respuesta") or "")[:1500])


def smoke(cfg: BotConfig, timeout: float) -> list[Result]:
    if not cfg.telegram:
        return [status(cfg), estado(cfg), page(cfg, "token"), page(cfg, "dashboard")]
    results = [status(cfg), chat(cfg, next(iter(allowed_bots(cfg))), "/estado", timeout, 3)]
    for username in list(allowed_bots(cfg))[1:]:
        results.append(chat(cfg, username, "/start", timeout, 2))
    results += [page(cfg, "token"), page(cfg, "dashboard")]
    return results


def _print(results: list[Result], as_json: bool) -> None:
    if as_json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=1))
        return
    for r in results:
        print(f"{'✅' if r.ok else '❌'} {r.check}: {r.detail}")
        for m in r.messages:
            if "who" in m:
                tools = f"  (tools: {', '.join(m['tools'])})" if m["tools"] else ""
                text = m["text"].replace("\n", "\n    ")
                print(f"  [{m['time']}] {m['who']}: {text}{tools}")
            else:
                buttons = f"\n    buttons: {' | '.join(m['buttons'])}" if m["buttons"] else ""
                text = m["text"].replace("\n", "\n    ")
                print(f"  #{m['id']} {m['time']}: {text}{buttons}")
        if r.fix and not r.ok:
            print(f"  → {r.fix}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vinci-check", description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n".join(__doc__.splitlines()[1:]))
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="gateway, poller, token chain and feeds")
    sub.add_parser("bots", help="the bots chat and press may talk to")
    p = sub.add_parser("chat", help="send a message as the captain and wait for the reply")
    p.add_argument("bot")
    p.add_argument("text")
    p.add_argument("--timeout", type=float, default=90, help="seconds to wait for the first reply (default 90)")
    p.add_argument("--settle", type=float, default=4, help="seconds to wait for follow-up messages (default 4)")
    p = sub.add_parser("press", help="press a button on the bot's latest message that has it")
    p.add_argument("bot")
    p.add_argument("label", help="the button text, or a unique part of it (emoji can be left out)")
    p.add_argument("--message", type=int, help="the message id, when not the latest one with that button")
    p.add_argument("--timeout", type=float, default=30)
    p = sub.add_parser("whatsapp", help="latest WhatsApp turns from Hermes's record (read-only)")
    p.add_argument("--profile", default="vinci", help="vinci (default) or amigo-<name>")
    p.add_argument("--last", type=int, default=8, help="how many messages (default 8)")
    p.add_argument("--chat", choices=("dm", "group"), help="only direct chats or only groups")
    p = sub.add_parser("say", help="a message to Vinci in the captain's WhatsApp chat; waits for the reply")
    p.add_argument("text")
    p.add_argument("--timeout", type=float, default=120, help="seconds to wait for the reply (default 120)")
    p.add_argument("--settle", type=float, default=4, help="seconds to wait for the rest of the turn (default 4)")
    p = sub.add_parser("vote", help="vote on Vinci's latest poll in the captain's WhatsApp chat")
    p.add_argument("option", help="the option text, or a unique part of it")
    p = sub.add_parser("page", help="open a GitHub Pages page in headless Chrome")
    p.add_argument("which", choices=("token", "dashboard"))
    p = sub.add_parser("smoke", help="status, /estado to Vinci, /start to each subject bot (with Telegram on), both pages")
    p.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args(argv)

    try:
        cfg = load_bot_config(load_config())
        if args.cmd == "status":
            results = [status(cfg)]
        elif args.cmd == "bots":
            results = [bots(cfg)]
        elif args.cmd == "chat":
            results = [chat(cfg, args.bot, args.text, args.timeout, args.settle)]
        elif args.cmd == "press":
            results = [press(cfg, args.bot, args.label, args.message, args.timeout)]
        elif args.cmd == "whatsapp":
            results = [whatsapp(args.profile, args.last, args.chat)]
        elif args.cmd == "say":
            results = [say(cfg, args.text, args.timeout, args.settle)]
        elif args.cmd == "vote":
            results = [vote(cfg, args.option)]
        elif args.cmd == "page":
            results = [page(cfg, args.which)]
        else:
            results = smoke(cfg, args.timeout)
    except (ConfigError, subprocess.TimeoutExpired) as exc:
        results = [Result(args.cmd, False, str(exc))]
    _print(results, args.json)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
