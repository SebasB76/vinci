"""The party: each bot's character from the captain's pixel art, in hermes/characters.toml.

A character is tone and looks only: its persona goes into the bot's SOUL.md, its avatar
becomes the bot's Telegram profile photo and a subject bot is named after it («El Analítico ·
Estadística»). It never changes a bot's tools or rules. Subjects are keyed by their ESPOL
code, so a subject's theory and práctico sections share one.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from aula_core.config import REPO_ROOT, ConfigError

FILE = REPO_ROOT / "hermes" / "characters.toml"
AVATARS = REPO_ROOT / "hermes" / "avatars"
NAME_LIMIT = 64  # Telegram's cap on a bot's name


@dataclass(frozen=True)
class Character:
    persona: str
    title: str | None = None
    look: str | None = None
    avatar: Path | None = None
    subject: str | None = None
    short: str | None = None  # the subject's label in the bot's name («Sist. Distribuidos»)


def _load() -> dict:
    try:
        return tomllib.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"No pude leer {FILE}: {exc}") from exc


def _character(raw: dict, where: str) -> Character:
    persona = str(raw.get("persona") or "").strip()
    if not persona:
        raise ConfigError(f"{FILE}: a [{where}] le falta «persona»")
    avatar = AVATARS / str(raw["avatar"]) if raw.get("avatar") else None
    if avatar is not None and avatar.suffix.lower() not in (".jpg", ".jpeg"):
        raise ConfigError(f"{FILE}: la foto de [{where}] debe ser un JPG (Telegram no acepta otro formato)")
    if avatar is not None and not avatar.is_file():
        raise ConfigError(f"{FILE}: no encuentro la foto de [{where}] ({avatar})")
    return Character(persona, raw.get("title"), raw.get("look"), avatar, raw.get("subject"), raw.get("short"))


def vinci() -> Character:
    return _character(_load().get("vinci") or {}, "vinci")


def for_subject(code: str) -> Character:
    """The subject's character, or the default one (no title, no avatar) when it has none."""
    data = _load()
    raw = (data.get("subjects") or {}).get(code.upper())
    if raw:
        return _character(raw, f"subjects.{code.upper()}")
    return _character(data.get("default") or {}, "default")


def party() -> dict[str, Character]:
    """Every subject that has a character, by code."""
    return {code.upper(): _character(raw, f"subjects.{code}") for code, raw in (_load().get("subjects") or {}).items()}


def bot_name(code: str, subject_name: str) -> str:
    """A subject bot's Telegram name: «El Analítico · Estadística», or the subject's name when it
    has no character. Cut at a whole word to fit Telegram's limit."""
    character = for_subject(code)
    label = character.short or subject_name
    name = f"{character.title} · {label}" if character.title else label
    if len(name) <= NAME_LIMIT:
        return name
    return name[:NAME_LIMIT - 1].rsplit(" ", 1)[0].rstrip(" ·,") + "…"
