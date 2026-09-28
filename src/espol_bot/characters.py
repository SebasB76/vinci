"""The party: each bot's Telegram profile photo from the captain's pixel art, and each subject
bot's name, in hermes/characters.toml.

A subject bot is named after its subject only («Estadística», «Sistemas Distribuidos»). Photos
and names are looks only: they never change a bot's tools or rules. Subjects are keyed by their
ESPOL code, so a subject's theory and práctico sections share one entry.
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
    avatar: Path | None = None
    name: str | None = None  # the subject bot's Telegram name («Sistemas Distribuidos»)
    subject: str | None = None  # the subject's official name


def _load() -> dict:
    try:
        return tomllib.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"No pude leer {FILE}: {exc}") from exc


def _character(raw: dict, where: str) -> Character:
    avatar = AVATARS / str(raw["avatar"]) if raw.get("avatar") else None
    if avatar is not None and avatar.suffix.lower() not in (".jpg", ".jpeg"):
        raise ConfigError(f"{FILE}: la foto de [{where}] debe ser un JPG (Telegram no acepta otro formato)")
    if avatar is not None and not avatar.is_file():
        raise ConfigError(f"{FILE}: no encuentro la foto de [{where}] ({avatar})")
    name = str(raw.get("name") or "").strip() or None
    if name is not None and len(name) > NAME_LIMIT:
        raise ConfigError(f"{FILE}: el nombre de [{where}] pasa de {NAME_LIMIT} caracteres (el límite de Telegram)")
    return Character(avatar, name, raw.get("subject"))


def vinci() -> Character:
    return _character(_load().get("vinci") or {}, "vinci")


def for_subject(code: str) -> Character:
    """The subject's entry, or an empty one (no name, no photo) when it has none."""
    raw = (_load().get("subjects") or {}).get(code.upper())
    return _character(raw, f"subjects.{code.upper()}") if raw else Character()


def party() -> dict[str, Character]:
    """Every subject that has an entry, by code."""
    return {code.upper(): _character(raw, f"subjects.{code}") for code, raw in (_load().get("subjects") or {}).items()}


def bot_name(code: str, subject_name: str) -> str:
    """A subject bot's Telegram name: its subject («Estadística»), in the short form characters.toml
    gives it, if any. Cut at a whole word to fit Telegram's limit."""
    name = for_subject(code).name or subject_name
    if len(name) <= NAME_LIMIT:
        return name
    return name[:NAME_LIMIT - 1].rsplit(" ", 1)[0].rstrip(" ·,") + "…"
