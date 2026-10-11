"""What a page opened from WhatsApp sends back to Vinci, through its relay (relay/worker.js, on Cloudflare Workers).

Telegram hands a Mini App's data to the bot; WhatsApp has no such channel. So each link Vinci sends on WhatsApp to
the /token page or the dashboard carries a mailbox (random, in the URL fragment: it is the link's capability) and the
relay's address. The page posts there: the Canvas token sealed to the PC's one-time key, or a tick on a deliverable.
The PC opens no port: the plugin vinci-whatsapp polls the relay (`espol-bot whatsapp-rele`) while a mailbox is open,
and this module runs what came in for the person the mailbox was issued to, never for whom a message claims.

The Académico's sign-in (portal_login.py) talks both ways: its mailbox is read by the process that holds that sign-in
(`inbox`), never by `fetch`, and the page reads back the CAPTCHA and how far it got (`set_status`, GET /s/<mailbox>).
`fetch` starts that process for each mailbox a tool asked for.

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
from aula_core.store import file_lock
from espol_bot.config import BotConfig

REGISTRY = "rele.json"
KINDS = ("token", "mark", "academico")
PORTAL = "academico"
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


def _locked(path: Path):
    """The registry is written by tools, by `fetch` and by the Académico's sign-in: one at a time."""
    return file_lock(path.parent, "rele.lock")


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


def issue(cfg: BotConfig, kind: str, number: str, ttl: timedelta, now: datetime,
          extra: dict | None = None) -> dict | None:
    """A new mailbox for `number`'s `kind` of message: {"relay", "mailbox"}, or None with no relay set up. `extra`
    rides along in the registry (what the Académico's sign-in needs to know)."""
    path = registry_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        data = read(path)
        url = str(data.get("url") or "")
        if not url or not number:
            return None
        mailbox = secrets.token_urlsafe(24)
        data["mailboxes"] = {**_open(data, now), mailbox: {
            **(extra or {}), "kind": kind, "number": number, "expires": timefmt.iso(now + ttl)}}
        _write(path, data)
    return {"relay": url, "mailbox": mailbox}


def update(path: Path, mailbox: str, now: datetime, **changes) -> dict | None:
    """Changes an open mailbox's entry (None for a key removes it); None when it is gone."""
    with _locked(path):
        data = read(path)
        box = _open(data, now).get(mailbox)
        if box is None:
            return None
        box.update(changes)
        data["mailboxes"] = {**_open(data, now), mailbox: {k: v for k, v in box.items() if v is not None}}
        _write(path, data)
    return box


def close(path: Path, mailbox: str) -> None:
    with _locked(path):
        data = read(path)
        if (data.get("mailboxes") or {}).pop(mailbox, None) is not None:
            _write(path, data)


def opened(path: Path, now: datetime) -> dict:
    return _open(read(path), now)


def key() -> str:
    """The relay's key, in the captain's secrets.env only."""
    return load_secret_values().get("WHATSAPP_RELAY_TOKEN", "")


def inbox(url: str, relay_key: str, mailbox: str) -> list[dict]:
    """What the page posted to one mailbox (the Académico's sign-in reads its own; `fetch` leaves them)."""
    try:
        response = requests.get(f"{url}/inbox", params={"mailbox": mailbox},
                                headers={"Authorization": f"Bearer {relay_key}"}, timeout=TIMEOUT)
        response.raise_for_status()
        return [m for m in response.json().get("messages") or [] if m.get("mailbox") == mailbox]
    except (requests.RequestException, ValueError) as exc:
        raise RelayError(f"el relé no responde ({exc.__class__.__name__})") from None


def ack(url: str, relay_key: str, ids: list[str]) -> None:
    try:
        requests.post(f"{url}/ack", headers={"Authorization": f"Bearer {relay_key}"}, json={"ids": ids},
                      timeout=TIMEOUT).raise_for_status()
    except requests.RequestException as exc:
        raise RelayError(f"el relé no confirmó lo recibido ({exc.__class__.__name__})") from None


def set_status(url: str, relay_key: str, mailbox: str, status: dict) -> None:
    """What the page opened with this mailbox reads back: the CAPTCHA, an error, how far the sign-in got."""
    try:
        requests.put(f"{url}/s/{mailbox}", headers={"Authorization": f"Bearer {relay_key}"}, json=status,
                     timeout=TIMEOUT).raise_for_status()
    except requests.RequestException as exc:
        raise RelayError(f"el relé no tomó el estado ({exc.__class__.__name__})") from None


def waiting(path: Path, now: datetime) -> bool:
    data = read(path)
    return bool(data.get("url")) and bool(_open(data, now))


def fetch(cfg: BotConfig, now: datetime) -> list[dict]:
    """Everything the relay holds for an open mailbox, run for its owner: [{"chat", "respuesta", "reiniciar", "button"}].
    The captain's cfg. What no open mailbox claims is dropped; a token mailbox serves once."""
    from espol_bot import amigos, whatsapp
    path = registry_path(cfg)
    data = read(path)
    url = str(data.get("url") or "")
    relay_key = key()
    if not url or not relay_key:
        return []
    from espol_bot import portal_login
    portal_login.launch(cfg, path, now)
    headers = {"Authorization": f"Bearer {relay_key}"}
    try:
        response = requests.get(f"{url}/inbox", headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        messages = response.json().get("messages") or []
    except (requests.RequestException, ValueError) as exc:
        raise RelayError(f"el relé no responde ({exc.__class__.__name__})") from None
    answers, handled = [], []
    for message in messages:
        boxes = _open(read(path), now)
        box = boxes.get(str(message.get("mailbox")))
        if box is not None and box["kind"] == PORTAL:
            continue  # the sign-in's own process reads it
        handled.append(str(message.get("id")))
        body = message.get("data") if isinstance(message.get("data"), dict) else {}
        if box is None or body.get("kind") != box["kind"]:
            continue
        if box["kind"] == "token":
            sealed = SEALED_RE.fullmatch(str(body.get("sealed") or ""))
            if not sealed:
                continue
            close(path, message["mailbox"])  # one token per mailbox, even if the page posted twice
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
