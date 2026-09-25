"""Minimal Telegram Bot API sender. Messages only ever go to the captain's own chat
(for a private chat the chat id is the user id)."""

from __future__ import annotations

import logging
import time

import requests

from espol_bot.config import TelegramSecrets, telegram_api_base

log = logging.getLogger(__name__)

LIMIT = 4000  # Telegram caps a message at 4096 characters


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


class Telegram:
    def __init__(self, secrets: TelegramSecrets, *, sleep=time.sleep):
        self._url = f"{telegram_api_base()}/bot{secrets.bot_token}/sendMessage"
        self._chat_id = secrets.user_id
        self._sleep = sleep
        self.sent = 0

    def send(self, html_text: str) -> None:
        for part in split(html_text):
            self._send_one(part)

    def _send_one(self, text: str) -> None:
        payload = {"chat_id": self._chat_id, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        for attempt in range(4):
            try:
                resp = requests.post(self._url, json=payload, timeout=30)
            except requests.RequestException as exc:
                if attempt == 3:
                    raise TelegramError(f"No pude conectar con Telegram ({type(exc).__name__})") from None
                self._sleep(2 ** attempt)
                continue
            if resp.status_code == 429:
                retry = (resp.json().get("parameters") or {}).get("retry_after", 5)
                self._sleep(float(retry))
                continue
            if resp.status_code >= 500:
                self._sleep(2 ** attempt)
                continue
            data = resp.json() if resp.content else {}
            if not data.get("ok"):
                # The token is in the URL: never echo the URL itself.
                raise TelegramError(f"Telegram rechazó el mensaje: {data.get('description', resp.status_code)}")
            self.sent += 1
            # Stay well below Telegram's per-chat limit.
            self._sleep(0.4)
            return
        raise TelegramError("Telegram siguió rechazando el mensaje tras varios intentos")
