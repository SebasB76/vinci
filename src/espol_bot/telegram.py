"""Minimal Telegram Bot API sender. Messages only ever go to the captain's own chat
(for a private chat the chat id is the user id)."""

from __future__ import annotations

import json
import logging
import socket
import time
from pathlib import Path

import requests

from espol_bot.config import DEFAULT_TELEGRAM_API, TelegramSecrets

log = logging.getLogger(__name__)

LIMIT = 4000  # Telegram caps a message at 4096 characters
# setMyName and friends answer 429 with waits of up to hours: past this, give up and try on the next setup.
PROFILE_MAX_WAIT = 30
TIMEOUT = (10, 30)  # (connect, read) seconds


def prefer_ipv4() -> None:
    """Try IPv4 addresses before IPv6 ones in this process. Where IPv6 to Telegram is broken but IPv4
    works (the captain's network), every Bot API call stalled on IPv6 until its connect timeout; an
    IPv6-only network still works, since IPv6 stays as the fallback."""
    original = socket.getaddrinfo
    if getattr(original, "prefers_ipv4", False):
        return

    def getaddrinfo(*args, **kwargs):
        return sorted(original(*args, **kwargs), key=lambda info: info[0] != socket.AF_INET)

    getaddrinfo.prefers_ipv4 = True
    socket.getaddrinfo = getaddrinfo


class TelegramError(Exception):
    pass


def split(text: str, limit: int = LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def keyboard(buttons: list[tuple[str, str]]) -> dict | None:
    """Inline keyboard, one button per row: [(label, callback_data), ...]."""
    if not buttons:
        return None
    return {"inline_keyboard": [[{"text": label, "callback_data": data}] for label, data in buttons]}


class Telegram:
    def __init__(self, secrets: TelegramSecrets, *, api: str = DEFAULT_TELEGRAM_API, sleep=time.sleep):
        self._base = f"{api.rstrip('/')}/bot{secrets.bot_token}"
        self._chat_id = secrets.user_id
        self._sleep = sleep
        self.sent = 0

    def send(self, html_text: str, buttons: list[tuple[str, str]] | None = None, *,
             reply_markup: dict | None = None) -> None:
        """`buttons` makes an inline keyboard; `reply_markup` passes any other markup as is."""
        parts = split(html_text)
        for i, part in enumerate(parts):
            # The buttons ride on the last part, right under the text they refer to.
            self._send_one(part, (reply_markup or keyboard(buttons or [])) if i == len(parts) - 1 else None)

    def send_document(self, path: Path, filename: str, html_caption: str, buttons: list[tuple[str, str]] | None = None,
                      *, thumbnail: bytes | None = None) -> dict:
        """A file in the captain's chat, with its caption (up to 1024 characters) and inline buttons under it."""
        payload = {"chat_id": self._chat_id, "caption": html_caption, "parse_mode": "HTML"}
        markup = keyboard(buttons or [])
        if markup:
            payload["reply_markup"] = json.dumps(markup)
        files = {"document": (filename, path.read_bytes(), "application/pdf")}
        if thumbnail:
            payload["thumbnail"] = "attach://thumb"
            files["thumb"] = ("thumb.jpg", thumbnail, "image/jpeg")
        message = self._call("sendDocument", payload, files=files)
        self.sent += 1
        self._sleep(0.4)
        return message

    def send_poll(self, question: str, options: list[str], correct: int, explanation: str) -> dict:
        """A quiz poll in the captain's chat; not anonymous, so the bot receives the captain's vote (poll_answer)."""
        message = self._call("sendPoll", {"chat_id": self._chat_id, "question": question, "type": "quiz",
                                          "options": [{"text": option} for option in options],
                                          "correct_option_id": correct, "explanation": explanation,
                                          "is_anonymous": False})
        self.sent += 1
        self._sleep(0.4)
        return message

    def get_me(self) -> dict:
        """The bot's own identity (id, username, can_manage_bots); raises TelegramError when refused."""
        return self._call("getMe", {})

    def managed_bot_token(self, bot_id: int) -> str:
        """The token of a bot the captain created for this bot to manage (Bot API 9.6 managed bots)."""
        token = self._call("getManagedBotToken", {"user_id": bot_id})
        if not isinstance(token, str) or not token:
            raise TelegramError("Telegram no devolvió el token del bot nuevo")
        return token

    def set_menu_button(self, button: dict | None) -> None:
        """The button beside the captain's text field, in that chat only; None puts Telegram's default back."""
        self._call("setChatMenuButton", {"chat_id": self._chat_id, "menu_button": button or {"type": "default"}})

    def my_name(self) -> str:
        return str(self._call("getMyName", {}, max_wait=PROFILE_MAX_WAIT).get("name") or "")

    def set_my_name(self, name: str) -> None:
        """Renames this bot for everyone (no language_code): the name in the captain's chat list."""
        self._call("setMyName", {"name": name}, max_wait=PROFILE_MAX_WAIT)

    def set_profile_photo(self, jpeg: bytes) -> None:
        """Sets this bot's own profile photo (Bot API 9.4). Telegram only takes a fresh JPG upload."""
        self._call("setMyProfilePhoto", {"photo": json.dumps({"type": "static", "photo": "attach://avatar"})},
                   files={"avatar": ("avatar.jpg", jpeg, "image/jpeg")}, max_wait=PROFILE_MAX_WAIT)

    def _send_one(self, text: str, markup: dict | None) -> None:
        payload = {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        if markup:
            payload["reply_markup"] = markup
        self._call("sendMessage", payload)
        self.sent += 1
        # Stay well below Telegram's per-chat limit.
        self._sleep(0.4)

    def _call(self, method: str, payload: dict, files: dict | None = None, max_wait: float | None = None):
        url = f"{self._base}/{method}"
        for attempt in range(4):
            try:
                resp = (requests.post(url, data=payload, files=files, timeout=TIMEOUT) if files
                        else requests.post(url, json=payload, timeout=TIMEOUT))
            except requests.RequestException as exc:
                if attempt == 3:
                    raise TelegramError(f"No pude conectar con Telegram ({type(exc).__name__})") from None
                self._sleep(2 ** attempt)
                continue
            if resp.status_code == 429:
                retry = (resp.json().get("parameters") or {}).get("retry_after", 5)
                if max_wait is not None and float(retry) > max_wait:
                    raise TelegramError(f"Telegram pide esperar {int(retry)} s antes de reintentar")
                self._sleep(float(retry))
                continue
            if resp.status_code >= 500:
                self._sleep(2 ** attempt)
                continue
            data = resp.json() if resp.content else {}
            if not data.get("ok"):
                # The token is in the URL: never echo the URL itself.
                raise TelegramError(f"Telegram rechazó la solicitud: {data.get('description', resp.status_code)}")
            return data.get("result") or {}
        raise TelegramError("Telegram siguió rechazando la solicitud tras varios intentos")
