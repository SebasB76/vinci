"""Bot-specific settings: [notificaciones], [clases], [notes] and [hermes] from config.toml, plus
the Telegram secrets. The core settings come from aula_core.config."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from aula_core.config import ConfigError, CoreConfig, load_config, load_secret_values, section

PROFILE_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
DEFAULT_TELEGRAM_API = "https://api.telegram.org"
# The /token Mini App (docs/token/ on GitHub Pages). It holds no secret: any install can use this copy.
DEFAULT_TOKEN_FORM_URL = "https://sebasb76.github.io/vinci/token/"
# Removed everywhere, whatever a platform list says (Hermes applies this last).
BLOCKED_TOOLSETS = [
    "terminal", "file", "code_execution", "browser", "computer_use", "delegation", "cronjob", "kanban",
    "vision", "video", "image_gen", "video_gen", "tts", "todo", "connections", "homeassistant",
    "spotify", "x_search", "a2a",
]
# Blocked by default and switched on per bot in config.toml ([hermes.herramientas]); a subject bot also has
# web and search off.
SWITCHABLE_TOOLSETS = [*BLOCKED_TOOLSETS, "web", "search"]


@dataclass(frozen=True)
class BotConfig:
    core: CoreConfig
    poll_minutes: int
    reminder_hours: tuple[int, ...]
    summary_time: time
    max_messages_per_poll: int
    brief_minutes: int
    hermes_profile: str
    hermes_provider: str
    hermes_model: str
    telegram_api: str
    token_form_url: str = DEFAULT_TOKEN_FORM_URL
    notes_folder: Path | None = None  # the captain's class notes (notes.py); None: not read
    notes_idle_minutes: int = 15
    vinci_toolsets: tuple[str, ...] = ()
    subject_toolsets: tuple[str, ...] = ()
    subject_toolsets_by_code: dict[str, tuple[str, ...]] = field(default_factory=dict)
    handwritten_subjects: tuple[str, ...] = ()  # codes whose assignments the captain does by hand and hands in as a PDF

    def extra_toolsets(self, code: str | None) -> tuple[str, ...]:
        """Toolsets the captain switched on for Vinci (`code` None) or for one subject bot, in config.toml."""
        if code is None:
            return self.vinci_toolsets
        return (*self.subject_toolsets, *self.subject_toolsets_by_code.get(code.upper(), ()))

    def subject_profile(self, code: str) -> str:
        """Hermes profile of a subject bot: `vinci-estg1034` for Vinci's ESTG1034."""
        return f"{self.hermes_profile}-{code.lower()}"


@dataclass(frozen=True)
class TelegramSecrets:
    bot_token: str
    user_id: str


def load_bot_config(core: CoreConfig | None = None) -> BotConfig:
    core = core or load_config()
    notif = section(core.raw, "notificaciones")
    clases = section(core.raw, "clases")
    hermes = section(core.raw, "hermes")

    summary_raw = str(notif.get("resumen_diario", "07:00"))
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", summary_raw)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ConfigError(f"resumen_diario debe tener formato HH:MM, no {summary_raw!r}")

    poll_minutes = int(notif.get("intervalo_minutos", 30))
    if poll_minutes < 5:
        raise ConfigError("intervalo_minutos debe ser al menos 5 para no saturar el aula virtual")

    reminder_hours = tuple(sorted({int(h) for h in notif.get("recordatorios_horas", [24, 3])}, reverse=True))
    if any(h <= 0 for h in reminder_hours):
        raise ConfigError("recordatorios_horas solo admite números positivos")

    brief_minutes = int(clases.get("brief_minutos_antes", 30))
    if not 5 <= brief_minutes <= 180:
        raise ConfigError("brief_minutos_antes debe estar entre 5 y 180")

    profile = str(hermes.get("perfil", "vinci"))
    if not PROFILE_RE.fullmatch(profile) or profile == "default":
        raise ConfigError(f"perfil de Hermes inválido: {profile!r}")

    tools = section(hermes, "herramientas")
    by_code = section(tools, "por_materia")

    api = os.environ.get("ESPOL_TELEGRAM_API_BASE") or DEFAULT_TELEGRAM_API
    if not api.startswith(("https://", "http://")):
        raise ConfigError("ESPOL_TELEGRAM_API_BASE debe empezar con https://")

    handwritten = section(core.raw, "submissions").get("handwritten", [])
    if not isinstance(handwritten, list) or not all(isinstance(c, str) and c.strip() for c in handwritten):
        raise ConfigError('[submissions] handwritten debe ser una lista de códigos de materia, ej. ["ESTG1034"]')

    notes = section(core.raw, "notes")
    folder = str(notes.get("folder") or "").strip()
    idle = int(notes.get("idle_minutes", 15))
    if not 5 <= idle <= 240:
        raise ConfigError("[notes] idle_minutes debe estar entre 5 y 240")

    form_url = str(section(core.raw, "canvas").get("token_form_url") or DEFAULT_TOKEN_FORM_URL)
    if not form_url.startswith("https://"):
        raise ConfigError("canvas.token_form_url debe empezar con https:// (Telegram solo abre Mini Apps así)")

    return BotConfig(
        core=core,
        poll_minutes=poll_minutes,
        reminder_hours=reminder_hours,
        summary_time=time(int(match[1]), int(match[2])),
        max_messages_per_poll=max(1, int(notif.get("max_mensajes_por_sondeo", 8))),
        brief_minutes=brief_minutes,
        hermes_profile=profile,
        hermes_provider=str(hermes.get("proveedor", "anthropic")),
        hermes_model=str(hermes.get("modelo", "claude-sonnet-5-5")),
        telegram_api=api.rstrip("/"),
        token_form_url=form_url,
        notes_folder=Path(folder).expanduser() if folder else None,
        notes_idle_minutes=idle,
        vinci_toolsets=_names(tools.get("vinci", []), "vinci"),
        subject_toolsets=_names(tools.get("materias", []), "materias"),
        subject_toolsets_by_code={code.upper(): _names(names, f"por_materia.{code}") for code, names in by_code.items()},
        handwritten_subjects=tuple(c.strip().upper() for c in handwritten),
    )


def _names(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError(f"[hermes.herramientas] {key} debe ser una lista de nombres de herramientas, ej. [\"terminal\"]")
    unknown = [v.strip() for v in value if v.strip() not in SWITCHABLE_TOOLSETS]
    if unknown:
        raise ConfigError(f"[hermes.herramientas] {key}: no conozco {', '.join(unknown)}. Las que se pueden activar: "
                          f"{', '.join(SWITCHABLE_TOOLSETS)}")
    return tuple(dict.fromkeys(v.strip() for v in value))


def captain_id(values: dict[str, str] | None = None) -> str:
    values = load_secret_values() if values is None else values
    user_id = values.get("TELEGRAM_USER_ID", "")
    if not user_id:
        raise ConfigError("Falta TELEGRAM_USER_ID en secrets.env")
    if not re.fullmatch(r"\d+", user_id):
        raise ConfigError("TELEGRAM_USER_ID debe ser tu ID numérico de Telegram (pídeselo a @userinfobot)")
    return user_id


def token_key(code: str | None = None) -> str:
    """secrets.env key of a bot token: Vinci's own, or one subject bot's."""
    return f"TELEGRAM_BOT_TOKEN_{code.upper()}" if code else "TELEGRAM_BOT_TOKEN"


def load_telegram_secrets(code: str | None = None) -> TelegramSecrets:
    """Vinci's bot token (or a subject bot's) plus the captain's user ID."""
    values = load_secret_values()
    key = token_key(code)
    token = values.get(key, "")
    if not token:
        raise ConfigError(f"Falta {key} en secrets.env")
    return TelegramSecrets(token, captain_id(values))
