"""Bot-specific settings: [notificaciones] and [hermes] from config.toml, plus the
Telegram secrets. The core settings come from aula_core.config."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import time

from aula_core.config import ConfigError, CoreConfig, load_config, load_secret_values, section


@dataclass(frozen=True)
class BotConfig:
    core: CoreConfig
    poll_minutes: int
    reminder_hours: tuple[int, ...]
    summary_time: time
    max_messages_per_poll: int
    hermes_profile: str
    hermes_provider: str
    hermes_model: str


@dataclass(frozen=True)
class TelegramSecrets:
    bot_token: str
    user_id: str


def load_bot_config(core: CoreConfig | None = None) -> BotConfig:
    core = core or load_config()
    notif = section(core.raw, "notificaciones")
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

    profile = str(hermes.get("perfil", "espol"))
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile) or profile == "default":
        raise ConfigError(f"perfil de Hermes inválido: {profile!r}")

    return BotConfig(
        core=core,
        poll_minutes=poll_minutes,
        reminder_hours=reminder_hours,
        summary_time=time(int(match[1]), int(match[2])),
        max_messages_per_poll=max(1, int(notif.get("max_mensajes_por_sondeo", 8))),
        hermes_profile=profile,
        hermes_provider=str(hermes.get("proveedor", "anthropic")),
        hermes_model=str(hermes.get("modelo", "claude-sonnet-5")),
    )


def load_telegram_secrets() -> TelegramSecrets:
    values = load_secret_values()
    token = values.get("TELEGRAM_BOT_TOKEN", "")
    user_id = values.get("TELEGRAM_USER_ID", "")
    missing = [k for k, v in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_USER_ID", user_id)) if not v]
    if missing:
        raise ConfigError(f"Faltan valores en secrets.env: {', '.join(missing)}")
    if not re.fullmatch(r"\d+", user_id):
        raise ConfigError("TELEGRAM_USER_ID debe ser tu ID numérico de Telegram (pídeselo a @userinfobot)")
    return TelegramSecrets(token, user_id)


def telegram_api_base() -> str:
    """Telegram Bot API base URL; the E2E test points it at a local stub."""
    return os.environ.get("ESPOL_TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")
