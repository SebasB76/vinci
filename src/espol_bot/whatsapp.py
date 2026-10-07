"""Vinci's WhatsApp number, outside the model: messages through Hermes' bridge, and linking the number.

Hermes' WhatsApp bridge (bridge.js, a Baileys client) serves a small HTTP API on localhost; `WhatsApp` sends
through it what the poller of a friend's Vinci would send to Telegram, converted from Telegram's HTML to
WhatsApp's formatting. WhatsApp has no inline buttons, so they are dropped.

`espol-bot whatsapp-vincular` (hermes/whatsapp/vincular.mjs) links the number with an 8-character code typed on
its phone and lists its groups. It writes the session the bridge uses, ~/.hermes/platforms/whatsapp/session, so it
must not run while the gateway has WhatsApp open: two connections with one session keep kicking each other out.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

import requests

from aula_core.config import REPO_ROOT, ConfigError
from espol_bot.config import DEFAULT_WHATSAPP_BRIDGE
from espol_bot.telegram import TelegramError

SCRIPT = REPO_ROOT / "hermes" / "whatsapp" / "vincular.mjs"
LIMIT = 4000
TIMEOUT = (5, 30)


class WhatsAppError(TelegramError):
    """A message the bridge did not take. A TelegramError, so the poller retries it like any failed send."""


def jid(number: str) -> str:
    return f"{number}@s.whatsapp.net"


def number_of(user_id: str | None) -> str:
    """«593…@s.whatsapp.net» or «593…:12@s.whatsapp.net» (a device) → «593…»; a LID («…@lid») is no number."""
    user_id = str(user_id or "")
    return "" if user_id.endswith("@lid") else re.sub(r"[:@].*$", "", user_id)


def normalize_number(text: str, country: str = "593") -> str:
    """A number as people type it: «099 123 4567» (Ecuador, ESPOL's) → «593991234567»; «+57 300…» keeps its code."""
    digits = re.sub(r"[^\d+]", "", text or "")
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("0"):
        digits = country + digits[1:]
    if not re.fullmatch(r"\d{8,15}", digits):
        raise ConfigError(f"«{text}» no es un número de WhatsApp (con código de país, o 09… en Ecuador)")
    return digits


def _link(match: re.Match) -> str:
    url, label = html.unescape(match[1]), match[2]
    return url if re.sub(r"<[^>]+>", "", label).strip() in ("", url) else f"{label} ({url})"


def from_html(text: str) -> str:
    """Telegram's HTML (what messages.py writes) in WhatsApp's formatting: *bold*, _italic_, ~strike~, `code`."""
    text = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', _link, text, flags=re.S)
    for tags, mark in ((("b", "strong"), "*"), (("i", "em"), "_"), (("s", "del", "strike"), "~")):
        for tag in tags:
            text = re.sub(rf"<{tag}>(.*?)</{tag}>", lambda m: f"{mark}{m[1].strip()}{mark}" if m[1].strip() else m[1],
                          text, flags=re.S)
    text = re.sub(r"<pre>(.*?)</pre>", r"```\1```", text, flags=re.S)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.S)
    text = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>",
                  lambda m: "\n".join(f"> {line}" for line in m[1].strip().splitlines()), text, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


class WhatsApp:
    """Sends to one person's WhatsApp chat (a friend's) through the bridge, with Telegram's `send` signature."""

    def __init__(self, number: str, bridge: str = DEFAULT_WHATSAPP_BRIDGE):
        self._chat = jid(number)
        self._bridge = bridge.rstrip("/")
        self.sent = 0

    def send(self, html_text: str, buttons: list[tuple[str, str]] | None = None, *,
             reply_markup: dict | None = None) -> None:
        text = from_html(html_text)
        for start in range(0, len(text), LIMIT):
            self._post("send", {"chatId": self._chat, "message": text[start:start + LIMIT]})

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = requests.post(f"{self._bridge}/{path}", json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise WhatsAppError(f"el puente de WhatsApp no responde ({exc.__class__.__name__})") from None
        if response.status_code != 200:
            raise WhatsAppError(f"el puente de WhatsApp respondió {response.status_code}: {response.text[:200]}")
        self.sent += 1
        return response.json() if response.content else {}


def send_text(bridge: str, chat_id: str, text: str) -> None:
    """One plain message to any chat (a person's JID or a group's), as is."""
    WhatsApp("", bridge)._post("send", {"chatId": chat_id, "message": text})


# -- linking the number ---------------------------------------------------------------------------

def session_dir() -> Path:
    return Path.home() / ".hermes" / "platforms" / "whatsapp" / "session"


def _modules() -> Path:
    for bridge in (Path.home() / ".hermes" / "hermes-agent" / "scripts" / "whatsapp-bridge",
                   Path.home() / ".hermes" / "scripts" / "whatsapp-bridge"):
        if (bridge / "node_modules" / "@whiskeysockets" / "baileys").is_dir():
            return bridge / "node_modules"
    raise ConfigError("No encuentro el puente de WhatsApp de Hermes con sus dependencias. Corre `hermes whatsapp` "
                      "una vez (instala el puente) y cancélalo cuando pida el modo.")


def _bridge_running(bridge: str) -> bool:
    try:
        with urllib.request.urlopen(f"{bridge}/health", timeout=2):
            return True
    except OSError:
        return False


def link(phone: str | None, bridge: str = DEFAULT_WHATSAPP_BRIDGE) -> int:
    node = shutil.which("node")
    if node is None:
        raise ConfigError("Falta Node.js (el puente de WhatsApp de Hermes corre en Node).")
    if _bridge_running(bridge):
        raise ConfigError("El gateway de Hermes está usando el número de Vinci. Detenlo (hermes gateway stop), "
                          "corre esto y vuelve a arrancarlo (hermes gateway start).")
    number = normalize_number(phone) if phone else ""
    session_dir().mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "BAILEYS_DIR": str(_modules())}
    return subprocess.run([node, str(SCRIPT), str(session_dir()), *([number] if number else [])], env=env).returncode
