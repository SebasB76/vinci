"""Creates or updates this bot's own Hermes profile. Idempotent.

Only touches `~/.hermes/profiles/<perfil>/` (plus the `~/.local/bin/<perfil>` alias
Hermes itself creates for a new profile). It never reads or writes the default
profile's config, `.env`, skills, or cron jobs, and it does not depend on any other
profile such as the X-feed bot's.

Mechanics, checked against Hermes Agent v0.21 docs and source:
- `hermes profile create <name> --no-skills` makes `~/.hermes/profiles/<name>`.
- `hermes -p <name> ...` scopes every command (config, cron, gateway) to that home.
- The Anthropic Claude Code login is read from ~/.claude/.credentials.json, which
  every host profile shares, so the profile only needs `model.provider: anthropic`.
- Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_USERS in the profile's `.env`.
- No-agent cron jobs run a script from `<profile>/scripts/` with zero model calls;
  empty stdout means nothing is delivered. `timezone` in config.yaml sets the zone
  cron expressions are evaluated in.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from aula_core.config import REPO_ROOT, ConfigError, config_path, secrets_path
from espol_bot.config import BotConfig, load_telegram_secrets

MARKER = "Generado por setup.sh de espol-academic-bot"
MANAGED_ENV = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL")


def find_hermes(explicit: str | None) -> str:
    for candidate in (explicit, os.environ.get("HERMES_BIN"), str(Path.home() / ".local/bin/hermes"),
                      shutil.which("hermes")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise ConfigError("No encuentro el comando hermes. ¿Está instalado Hermes Agent en ~/.local/bin/hermes?")


def _run(hermes: str, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
    proc = subprocess.run([hermes, *args], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise ConfigError(f"`hermes {' '.join(args)}` falló:\n{proc.stdout}\n{proc.stderr}".strip())
    return proc


def _deep_merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _write_if_changed(path: Path, text: str, mode: int | None = None) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    changed = not path.exists() or path.read_text(encoding="utf-8") != text
    if changed:
        path.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(path, mode)
    return changed


def _render(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def upsert_env(path: Path, values: dict[str, str]) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen, out = set(), []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            if key not in seen:
                out.append(f"{key}={values[key]}")
                seen.add(key)
            continue
        out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    return _write_if_changed(path, "\n".join(out) + "\n", 0o600)


def provision(cfg: BotConfig, *, hermes_bin: str | None = None) -> int:
    hermes = find_hermes(hermes_bin)
    tg = load_telegram_secrets()
    name = cfg.hermes_profile
    profile = Path.home() / ".hermes" / "profiles" / name
    bin_dir = Path(sys.prefix) / "bin"
    aula_bin, bot_bin = bin_dir / "aula", bin_dir / "espol-bot"
    for needed in (aula_bin, bot_bin):
        if not needed.exists():
            raise ConfigError(f"Falta {needed}; corre ./setup.sh para instalar las dependencias.")

    if profile.is_dir():
        print(f"• Perfil de Hermes «{name}» ya existe: lo actualizo.")
    else:
        _run(hermes, "profile", "create", name, "--no-skills",
             "--description", "Bot académico de ESPOL: avisos del aula virtual y preguntas sobre el material.")
        print(f"• Perfil de Hermes «{name}» creado en {profile}")

    # config.yaml: merge only the keys this bot owns.
    config_file = profile / "config.yaml"
    current = yaml.safe_load(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    current = current if isinstance(current, dict) else {}
    env_prefix = f"AULA_CONFIG='{config_path()}' AULA_SECRETS='{secrets_path()}'"
    managed = {
        "model": {"provider": cfg.hermes_provider, "default": cfg.hermes_model},
        "timezone": str(cfg.core.tz),
        "terminal": {"cwd": str(cfg.core.data_dir)},
        "quick_commands": {
            "pendientes": {"type": "exec", "command": f"{env_prefix} '{aula_bin}' tareas --sin-actualizar"},
            "semana": {"type": "exec", "command": f"{env_prefix} '{bot_bin}' resumen --imprimir"},
        },
        "approvals": {"deny": ["*secrets.env*", "*CANVAS_TOKEN*", "*api/v1*"]},
    }
    merged = _deep_merge(current, managed)
    changed = _write_if_changed(config_file, yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))
    print(f"• config.yaml {'actualizado' if changed else 'sin cambios'} (modelo {cfg.hermes_model}, zona {cfg.core.tz})")

    changed = upsert_env(profile / ".env", {
        "TELEGRAM_BOT_TOKEN": tg.bot_token,
        "TELEGRAM_ALLOWED_USERS": tg.user_id,
        "TELEGRAM_HOME_CHANNEL": tg.user_id,
    })
    print(f"• .env del perfil {'actualizado' if changed else 'sin cambios'} (Telegram solo para tu ID)")

    values = {"AULA": str(aula_bin), "BOT": str(bot_bin), "CONFIG": str(config_path()),
              "SECRETS": str(secrets_path()), "REPO": str(REPO_ROOT), "MARKER": MARKER}
    hermes_dir = REPO_ROOT / "hermes"
    changed = _write_if_changed(profile / "SOUL.md", _render(hermes_dir / "SOUL.md", values))
    changed |= _write_if_changed(profile / "skills" / "espol" / "espol-academico" / "SKILL.md",
                                 _render(hermes_dir / "skills" / "espol-academico" / "SKILL.md", values))
    scripts = {"espol-sondeo.sh": "sondeo", "espol-resumen.sh": "resumen"}
    for script, command in scripts.items():
        changed |= _write_if_changed(profile / "scripts" / script,
                                     _render(hermes_dir / "cron-script.sh", {**values, "COMMAND": command}), 0o755)
    print(f"• SOUL.md, skill espol-academico y scripts de cron {'instalados' if changed else 'sin cambios'}")

    deliver = f"telegram:{tg.user_id}"
    wanted = {
        "espol-sondeo": (f"every {cfg.poll_minutes}m", "espol-sondeo.sh"),
        "espol-resumen": (f"{cfg.summary_time.minute} {cfg.summary_time.hour} * * *", "espol-resumen.sh"),
    }
    jobs_file = profile / "cron" / "jobs.json"
    jobs = json.loads(jobs_file.read_text(encoding="utf-8")).get("jobs", []) if jobs_file.exists() else []
    for job_name, (schedule, script) in wanted.items():
        existing = [j for j in jobs if j.get("name") == job_name]
        if not existing:
            _run(hermes, "-p", name, "cron", "create", schedule, "--no-agent", "--script", script,
                 "--deliver", deliver, "--name", job_name)
            print(f"• cron «{job_name}» creado ({schedule})")
            continue
        job = existing[0]
        current_schedule = (job.get("schedule") or {}).get("display") or job.get("schedule_display")
        if (current_schedule, job.get("script"), job.get("deliver"), job.get("no_agent")) != (schedule, script, deliver, True):
            _run(hermes, "-p", name, "cron", "edit", job["id"], "--schedule", schedule, "--script", script,
                 "--deliver", deliver, "--no-agent")
            print(f"• cron «{job_name}» actualizado ({schedule})")
        else:
            print(f"• cron «{job_name}» sin cambios ({schedule})")
        if len(existing) > 1:
            print(f"  ⚠ hay {len(existing)} jobs llamados «{job_name}»; revisa con: {name} cron list")
    return 0
