"""Vinci's WhatsApp number, outside the model: messages through Hermes' bridge, and linking the number.

Hermes' WhatsApp bridge (bridge.js, a Baileys client) serves a small HTTP API on localhost; `WhatsApp` sends
through it what the poller of a friend's Vinci would send to Telegram, converted from Telegram's HTML to
WhatsApp's formatting. WhatsApp has no inline buttons: a message's buttons follow it as a poll, recorded in POLLS
(poll id → option → callback data) so the plugin can run the vote as the button (`espol-bot whatsapp-comando voto`).
A card with one button gets its undo as a second option, since a poll needs two: changing the vote undoes it.

`espol-bot whatsapp-vincular` (hermes/whatsapp/vincular.mjs) links the number with an 8-character code typed on
its phone and lists its groups. It writes the session the bridge uses, ~/.hermes/platforms/whatsapp/session, so it
must not run while the gateway has WhatsApp open: two connections with one session keep kicking each other out.
"""

from __future__ import annotations

import html
import json
import logging
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
POLLS = "whatsapp-encuestas.json"
KEEP_POLLS = 300
MAX_OPTIONS = 12  # WhatsApp's limit per poll
OPTION_CHARS = 100
QUESTION_CHARS = 255
# What a poll asks, by the kind of button under it (botones.py); anything else asks the generic one.
QUESTIONS = {"s": "¿Ya lo entregaste?", "t": "¿Ya lo hiciste?", "h": "¿Guardo este horario?",
             "g": "¿Guardo este esquema de notas?", "u": "¿Lo entrego en el aula?"}
QUESTION = "Elige una opción"
NOT_YET = "⏳ Todavía no"
CANCEL = "Cancelar"

log = logging.getLogger(__name__)


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


def poll_options(buttons: list[tuple[str, str]]) -> dict[str, str]:
    """A card's buttons as poll options (label → callback data; "" does nothing), with a second option when alone."""
    options: dict[str, str] = {}
    for label, data in buttons[:MAX_OPTIONS]:
        label = label.strip()[:OPTION_CHARS]
        while label in options:  # two buttons with one label (two «✅ Hecho»): a poll needs them apart
            label = f"{label} ·"
        options[label] = data
    if len(options) == 1:
        data = buttons[0][1]
        undo = data[:-3] + ":no" if data.startswith(("v1:s:", "v1:t:")) and data.endswith(":ok") else None
        options[NOT_YET if undo else CANCEL] = undo or ""
    return options


def record_poll(data_dir: Path, poll_id: str, options: dict[str, str]) -> None:
    path = data_dir / POLLS
    polls = read_polls(data_dir)
    polls[poll_id] = options
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(list(polls.items())[-KEEP_POLLS:]), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_polls(data_dir: Path) -> dict[str, dict[str, str]]:
    try:
        polls = json.loads((data_dir / POLLS).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return polls if isinstance(polls, dict) else {}


class WhatsApp:
    """Sends to one person's WhatsApp chat through the bridge, with Telegram's `send` signature. With `polls` (the
    owner's data folder), a message's buttons follow it as a poll."""

    def __init__(self, number: str, bridge: str = DEFAULT_WHATSAPP_BRIDGE, polls: Path | None = None):
        self._chat = jid(number)
        self._bridge = bridge.rstrip("/")
        self._polls = polls
        self.sent = 0

    def send(self, html_text: str, buttons: list[tuple[str, str]] | None = None, *,
             reply_markup: dict | None = None) -> None:
        text = from_html(html_text)
        for start in range(0, len(text), LIMIT):
            self._post("send", {"chatId": self._chat, "message": text[start:start + LIMIT]})
        if buttons and self._polls is not None:
            self.poll(buttons)

    def send_document(self, path: Path, file_name: str, html_caption: str,
                      buttons: list[tuple[str, str]] | None = None) -> None:
        self._post("send-media", {"chatId": self._chat, "filePath": str(path), "mediaType": "document",
                                  "fileName": file_name, "caption": from_html(html_caption)[:LIMIT]})
        if buttons and self._polls is not None:
            self.poll(buttons)

    def poll(self, buttons: list[tuple[str, str]], question: str | None = None) -> str:
        """The buttons as a poll (its id); `question` defaults to what the kind of button asks."""
        options = poll_options(buttons)
        kind = re.match(r"v1:(\w):", buttons[0][1])
        question = question or QUESTIONS.get(kind[1] if kind else "", QUESTION)
        sent = self._post("send-poll", {"chatId": self._chat, "question": question[:QUESTION_CHARS],
                                        "options": list(options)})
        poll_id = str(sent.get("messageId") or "")
        if not poll_id:
            raise WhatsAppError("el puente de WhatsApp no devolvió el id de la encuesta")
        if self._polls is not None:
            record_poll(self._polls, poll_id, options)
        return poll_id

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = requests.post(f"{self._bridge}/{path}", json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise WhatsAppError(f"el puente de WhatsApp no responde ({exc.__class__.__name__})") from None
        if response.status_code != 200:
            raise WhatsAppError(f"el puente de WhatsApp respondió {response.status_code}: {response.text[:200]}")
        self.sent += 1
        return response.json() if response.content else {}


class Mirror:
    """The captain's Telegram, with each message also sent to his WhatsApp chat. Telegram stays the source of truth:
    a WhatsApp failure is only logged, so the poller never resends what Telegram already took."""

    def __init__(self, telegram, whatsapp: WhatsApp):
        self._telegram = telegram
        self._whatsapp = whatsapp

    def send(self, html_text: str, buttons: list[tuple[str, str]] | None = None, *,
             reply_markup: dict | None = None) -> None:
        self._telegram.send(html_text, buttons, reply_markup=reply_markup)
        if reply_markup is not None:  # a Telegram keyboard (the /token form): WhatsApp has /token for that
            return
        # «🎓 Consultar con …» hands off to a subject bot, which lives on Telegram: no poll for it here
        buttons = [b for b in buttons or [] if not b[1].startswith("v1:a:")]
        try:
            self._whatsapp.send(html_text, buttons)
        except WhatsAppError as exc:
            log.warning("WhatsApp no recibió la copia de un aviso: %s", exc)

    def __getattr__(self, name):
        return getattr(self._telegram, name)


def send_text(bridge: str, chat_id: str, text: str) -> None:
    """One plain message to any chat (a person's JID or a group's), as is."""
    WhatsApp("", bridge)._post("send", {"chatId": chat_id, "message": text})


def own_number() -> str:
    """Vinci's own WhatsApp number, from the session the bridge logged in with; empty before it is linked."""
    try:
        me = json.loads((session_dir() / "creds.json").read_text(encoding="utf-8")).get("me") or {}
    except (OSError, ValueError):
        return ""
    return number_of(me.get("id"))


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
