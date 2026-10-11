"""What a page opened from WhatsApp sends back to Vinci, through its relay (relay/worker.js, on Cloudflare Workers).

Telegram hands a Mini App's data to the bot; WhatsApp has no such channel. So each link Vinci sends on WhatsApp to
the /token page or the dashboard carries a mailbox (random, in the URL fragment: it is the link's capability) and the
relay's address. The page posts there: the Canvas token sealed to the PC's one-time key, or a tick on a deliverable.
The PC opens no port: the plugin vinci-whatsapp polls the relay (`espol-bot whatsapp-rele`) while a mailbox is open,
and this module runs what came in for the person the mailbox was issued to, never for whom a message claims.

The mailboxes live in <captain's data>/amigos/rele.json, shared by every friend's Vinci (their data folders sit
inside it), with the relay's address setup.sh writes there. Only the captain's secrets.env holds the relay's key.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import requests

from aula_core import timefmt
from aula_core.config import ConfigError, load_secret_values
from espol_bot.config import BotConfig

REGISTRY = "rele.json"
KINDS = ("token", "mark")
DASHBOARD_TTL = timedelta(hours=12)
TIMEOUT = (5, 20)
SEALED_RE = re.compile(r"v1\.[A-Za-z0-9_-]{200,}")
MARK_RE = re.compile(r"[st]\d{1,12}")

log = logging.getLogger(__name__)


class RelayError(ConfigError):
    pass


def registry_path(cfg: BotConfig) -> Path:
    # A friend's data folder is <captain's data>/amigos/<slug> (amigos.folder)
    return (cfg.core.data_dir.parent if cfg.friend else cfg.core.data_dir / "amigos") / REGISTRY


def read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def set_url(path: Path, url: str) -> bool:
    """The relay's address (setup.sh, from secrets.env); empty turns the relay off. Whether it changed."""
    data = read(path)
    if data.get("url", "") == url:
        return False
    data["url"] = url
    _write(path, data)
    return True


def _open(data: dict, now: datetime) -> dict:
    return {k: v for k, v in (data.get("mailboxes") or {}).items()
            if (timefmt.parse(v.get("expires")) or now) > now}


def owner(cfg: BotConfig) -> str:
    """Whose WhatsApp chat this install answers: a friend's own number, else the captain's."""
    from espol_bot.config import whatsapp_settings
    if cfg.friend:
        return load_secret_values().get("WHATSAPP_OWNER", "")
    wa = whatsapp_settings()
    return wa.captain if wa else ""


def issue(cfg: BotConfig, kind: str, number: str, ttl: timedelta, now: datetime) -> dict | None:
    """A new mailbox for `number`'s `kind` of message: {"relay", "mailbox"}, or None with no relay set up."""
    path = registry_path(cfg)
    data = read(path)
    url = str(data.get("url") or "")
    if not url or not number:
        return None
    mailbox = secrets.token_urlsafe(24)
    data["mailboxes"] = {**_open(data, now),
                         mailbox: {"kind": kind, "number": number, "expires": timefmt.iso(now + ttl)}}
    _write(path, data)
    return {"relay": url, "mailbox": mailbox}


def waiting(path: Path, now: datetime) -> bool:
    data = read(path)
    return bool(data.get("url")) and bool(_open(data, now))


def fetch(cfg: BotConfig, now: datetime) -> list[dict]:
    """Everything the relay holds for an open mailbox, run for its owner: [{"chat", "respuesta", "reiniciar", "button"}].
    The captain's cfg. What no open mailbox claims is dropped; a token mailbox serves once."""
    from espol_bot import amigos, whatsapp
    path = registry_path(cfg)
    data = read(path)
    url, key = str(data.get("url") or ""), load_secret_values().get("WHATSAPP_RELAY_TOKEN", "")
    if not url or not key:
        return []
    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = requests.get(f"{url}/inbox", headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        messages = response.json().get("messages") or []
    except (requests.RequestException, ValueError) as exc:
        raise RelayError(f"el relé no responde ({exc.__class__.__name__})") from None
    answers, handled = [], []
    for message in messages:
        handled.append(str(message.get("id")))
        boxes = _open(read(path), now)
        box = boxes.get(str(message.get("mailbox")))
        body = message.get("data") if isinstance(message.get("data"), dict) else {}
        if box is None or body.get("kind") != box["kind"]:
            continue
        if box["kind"] == "token":
            sealed = SEALED_RE.fullmatch(str(body.get("sealed") or ""))
            if not sealed:
                continue
            current = read(path)  # one token per mailbox, even if the page posted twice
            current.get("mailboxes", {}).pop(message["mailbox"], None)
            _write(path, current)
            outcome = (amigos.command(cfg, "token-cifrado", box["number"], sealed[0], now)
                       if box["number"] == amigos.captain_number(cfg)
                       else amigos.submit_token(cfg, box["number"], sealed[0], now))
        else:
            item = str(body.get("id") or "")
            if not MARK_RE.fullmatch(item):
                continue
            outcome = amigos.command(cfg, "marca", box["number"], f"{item} {'ok' if body.get('done') else 'no'}", now)
        answers.append({"chat": whatsapp.jid(box["number"]), "respuesta": outcome.respuesta,
                        "reiniciar": outcome.reiniciar, "button": outcome.button, "image": outcome.image})
    if handled:
        try:
            requests.post(f"{url}/ack", headers=headers, json={"ids": handled}, timeout=TIMEOUT).raise_for_status()
        except requests.RequestException as exc:  # the next round sees them again; a used token mailbox is gone
            log.warning("el relé no confirmó lo recibido: %s", exc)
    return answers
