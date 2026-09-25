"""Timestamps: Canvas ISO strings in, Spanish human text out."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
DAYS_LONG = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize(value: str | None) -> str | None:
    parsed = parse(value)
    return iso(parsed) if parsed else None


def human(value: str | datetime | None, tz: ZoneInfo) -> str:
    """'lun 29 sep, 23:59' in the configured time zone."""
    moment = parse(value) if isinstance(value, str) or value is None else value
    if moment is None:
        return "sin fecha"
    local = moment.astimezone(tz)
    return f"{DAYS[local.weekday()]} {local.day} {MONTHS[local.month - 1]}, {local:%H:%M}"


def until(value: str | datetime | None, now: datetime) -> str:
    """'en 3 h', 'en 2 días', 'hace 5 h'."""
    moment = parse(value) if isinstance(value, str) or value is None else value
    if moment is None:
        return ""
    seconds = (moment - now).total_seconds()
    ahead = seconds >= 0
    seconds = abs(seconds)
    if seconds < 3600:
        amount = f"{max(1, round(seconds / 60))} min"
    elif seconds < 48 * 3600:
        amount = f"{round(seconds / 3600)} h"
    else:
        days = round(seconds / 86400)
        amount = f"{days} días"
    return f"en {amount}" if ahead else f"hace {amount}"
