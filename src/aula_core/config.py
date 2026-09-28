"""Loads config.toml, secrets.env, and the clock for the core.

The core only reads the sections it needs ([canvas], [general], [material],
[almacenamiento]); layers built on top (the bot) parse their own sections from
`CoreConfig.raw`.

Environment overrides (used by setup.sh's wrappers and by the E2E test):
  AULA_CONFIG   path to config.toml (default: repo root)
  AULA_SECRETS  path to secrets.env (default: repo root)
  AULA_NOW      ISO-8601 timestamp with offset that replaces the current time
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class CoreConfig:
    canvas_url: str
    cache_minutes: int
    tz: ZoneInfo
    material_extensions: tuple[str, ...]
    max_file_mb: float
    max_mb_per_sync: float
    request_interval: float
    data_dir: Path
    config_path: Path
    raw: dict = field(repr=False)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "espol.db"

    @property
    def materials_dir(self) -> Path:
        return self.data_dir / "materiales"


def config_path() -> Path:
    return Path(os.environ.get("AULA_CONFIG") or REPO_ROOT / "config.toml")


def secrets_path() -> Path:
    return Path(os.environ.get("AULA_SECRETS") or REPO_ROOT / "secrets.env")


def section(raw: dict, name: str) -> dict:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] en config.toml debe ser una sección")
    return value


def load_config(path: Path | None = None) -> CoreConfig:
    path = path or config_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"No encuentro el archivo de configuración: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config.toml tiene un error de formato: {exc}") from exc

    canvas = section(raw, "canvas")
    general = section(raw, "general")
    material = section(raw, "material")
    storage = section(raw, "almacenamiento")

    try:
        tz = ZoneInfo(str(general.get("zona_horaria", "America/Guayaquil")))
    except Exception as exc:
        raise ConfigError(f"zona_horaria inválida: {general.get('zona_horaria')!r}") from exc

    canvas_url = str(canvas.get("url", "https://aulavirtual.espol.edu.ec")).rstrip("/")
    if not canvas_url.startswith(("https://", "http://")):
        raise ConfigError("canvas.url debe empezar con https://")

    return CoreConfig(
        canvas_url=canvas_url,
        cache_minutes=max(0, int(canvas.get("cache_minutos", 10))),
        tz=tz,
        material_extensions=tuple(str(e).lower().lstrip(".") for e in material.get("extensiones", ["pdf", "pptx", "docx"])),
        max_file_mb=float(material.get("tamano_maximo_mb", 60)),
        max_mb_per_sync=max(0.0, float(material.get("max_mb_per_sync", 50))),
        request_interval=max(0.0, float(canvas.get("request_interval_seconds", 1.0))),
        data_dir=Path(os.path.expanduser(str(storage.get("carpeta_datos", "~/.local/share/espol-academic-bot")))),
        config_path=path,
        raw=raw,
    )


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_secret_values(path: Path | None = None) -> dict[str, str]:
    path = path or secrets_path()
    try:
        return parse_env_file(path)
    except FileNotFoundError as exc:
        raise ConfigError(
            f"No encuentro {path}. Copia secrets.env.example como secrets.env y complétalo."
        ) from exc


def canvas_token(path: Path | None = None) -> str:
    token = load_secret_values(path).get("CANVAS_TOKEN", "")
    if not token:
        raise ConfigError(f"Falta CANVAS_TOKEN en {path or secrets_path()}")
    return token


def now_utc() -> datetime:
    override = os.environ.get("AULA_NOW")
    if override:
        value = datetime.fromisoformat(override)
        if value.tzinfo is None:
            raise ConfigError("AULA_NOW debe incluir zona horaria")
        return value.astimezone(timezone.utc)
    return datetime.now(timezone.utc)
