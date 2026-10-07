"""Creates or updates the Hermes profiles of Vinci and of every subject bot. Idempotent.

Only touches `~/.hermes/profiles/<vinci>/` and `~/.hermes/profiles/<vinci>-<código>/`
(plus the `~/.local/bin/<vinci>` alias Hermes creates for Vinci's profile). It never
reads or writes the default profile's config, `.env`, skills, or cron jobs.

Mechanics, checked against Hermes Agent 2026.9 (docs under ~/.hermes/hermes-agent/website/docs):
- `hermes profile create <name> --no-skills` makes `~/.hermes/profiles/<name>`; `hermes -p
  <name> ...` scopes config, cron and gateway commands to it. `profile rename` keeps memory.
- One host gateway (the default profile's) serves every profile, each with its own
  Telegram token; a `gateway.parked` file in a profile takes it offline and excludes
  its cron jobs from the ticks.
- Tools: `platform_toolsets.<platform>` lists what each platform may use and
  `agent.disabled_toolsets` removes toolsets everywhere, after everything else; a
  stdio MCP server in `mcp_servers:` becomes the `mcp-<server>` toolset (tools
  `mcp__<server>__<tool>`), and a plugin's tool its own toolset (ver_pagina: `vinci-paginas`, the one
  way a tool's image reaches the model). Tool Search is turned off so the model sees exactly that list.
  `skills.auto_load` pins a skill fully loaded in every chat session (a cron agent run only loads the
  skills its job names with `--skill`), but Hermes ignores
  it unless the agent has one of the skills toolset's tools (skills_list, skill_view, skill_manage), so
  every bot gets that toolset. Its skill_manage writes files under the bot's own profile `skills/`.
  Every skill in a profile's `skills/` is also a slash command in its Telegram chat: the `quiz` skill is
  `/quiz <tema>`, whose text reaches the model with the skill. The shared gateway builds each bot's command
  menu from the default profile's skills, so the plugin sets a menu for the captain's chat that lists /quiz.
- Cron: `--no-agent` jobs run a script with zero model calls; an agent job with
  `--script` runs the script first and skips the model when its last line is
  `{"wakeAgent": false}`. `timezone` sets the zone cron expressions use. The ticker checks
  once a minute and plans a job's next run from when its last run ended, so `every 1m` misses
  the next check and runs every 2 minutes (`every 30m`, every 31); a cron expression keeps the
  clock, and its optional sixth field is seconds.
- Plugins in a profile's `plugins/` load only when named in `plugins.enabled`. A running gateway
  looks for a profile's plugins once, as soon as `profile create` announces it (before setup
  installs any), and again only on its `reload-plugins` control-socket verb, which `hermes plugins
  enable` sends; setup sends it itself after installing the plugin, before the bot's token.
- `compression.threshold_tokens` caps when a chat gets summarized (default 256K); a running
  gateway rebuilds its cached agent when it changes, so it applies at the next message.
- A profile's first message ever gets an onboarding note; `onboarding.profile_build: off` makes it a
  plain introduction instead of an offer to build a profile of the user.
- Telegram updates that arrive while a bot is not served yet are dropped when the gateway starts
  serving it, unless `platforms.telegram.extra.drop_pending_on_cold_boot` is false.

Each bot sets its own Telegram profile photo from the party (characters.py; setMyProfilePhoto,
Bot API 9.4) and a subject bot its name, just its subject («Estadística», setMyName), with its
own token, so neither BotFather nor the manager bot is involved and an existing bot is renamed
in place.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import yaml

from aula_core.config import (
    REPO_ROOT,
    ConfigError,
    config_path,
    load_secret_values,
    secrets_path,
    update_secret_values,
)
from espol_bot import characters, herramientas, materias, skill_check
from espol_bot.config import (
    BLOCKED_TOOLSETS,
    DEFAULT_TELEGRAM_API,
    BotConfig,
    TelegramSecrets,
    captain_id,
    token_key,
    whatsapp_settings,
)
from espol_bot.telegram import Telegram, TelegramError

MARKER = "Generado por setup.sh de espol-academic-bot"
LEGACY_PROFILE = "espol"
PLUGIN = "vinci-botones"
SKILLS_CATEGORY = "vinci"
TEMPLATES = REPO_ROOT / "hermes"

# `skills` is what makes skills.auto_load pin each bot's own skill (see the docstring).
VINCI_TOOLSETS = ["web", "memory", "session_search", "clarify", "skills", "mcp-vinci"]
SUBJECT_TOOLSETS = ["memory", "session_search", "clarify", "skills", "mcp-materia", "vinci-paginas"]
APPROVALS_DENY = ["*secrets.env*", "*CANVAS_TOKEN*", "*api/v1*"]
# Every message resends the chat so far. After a summary the fixed prompt, the summary and Hermes'
# 25K verbatim tail already weigh ~50K, so a lower trigger would summarize again every question or two.
COMPRESSION_THRESHOLD_TOKENS = 80_000
# Hermes tools (besides the MCP ones in herramientas.GUEST_TOOLS) someone in a WhatsApp group other than the
# captain may use: the web and reading skills and past chats. Not memory or skill_manage: what a guest says must
# never become something Vinci remembers or does for the captain.
GUEST_HERMES_TOOLS = ["web_search", "web_extract", "skills_list", "skill_view", "session_search", "clarify"]
WHATSAPP_ROUTE_PREFIX = "vinci-whatsapp-"
WHATSAPP_PLUGIN = "vinci-whatsapp"


def find_hermes(explicit: str | None) -> str:
    for candidate in (explicit, os.environ.get("HERMES_BIN"), str(Path.home() / ".local/bin/hermes"),
                      shutil.which("hermes")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise ConfigError("No encuentro el comando hermes. ¿Está instalado Hermes Agent en ~/.local/bin/hermes?")


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


def poll_schedule(minutes: int, summary_minute: int) -> str:
    """Every `minutes` on the clock, half a period away from the daily summary, which polls Canvas itself.
    A period that does not divide the hour stays a Hermes interval (a minute late each run)."""
    if 60 % minutes:
        return f"every {minutes}m"
    first = (summary_minute + minutes // 2) % minutes
    return ",".join(map(str, range(first, 60, minutes))) + " * * * *"


def _join_ni(names: list[str]) -> str:
    """«web, terminal ni archivos»."""
    return f"{', '.join(names[:-1])} ni {names[-1]}" if len(names) > 1 else "".join(names)


def _render(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def upsert_env(path: Path, values: dict[str, str]) -> bool:
    return update_secret_values(values, path=path)


class Setup:
    """One provisioning run: the shared facts (hermes binary, paths, captain) plus the steps."""

    def __init__(self, cfg: BotConfig, *, hermes_bin: str | None = None):
        self.cfg = cfg
        self.hermes = find_hermes(hermes_bin)
        self.root = Path.home() / ".hermes"
        self.bin_dir = Path(sys.prefix) / "bin"
        self.bot_bin = self.bin_dir / "espol-bot"
        if not self.bot_bin.exists():
            raise ConfigError(f"Falta {self.bot_bin}; corre ./setup.sh para instalar las dependencias.")
        self.configured: list[tuple[str, str]] = []  # (profile, its pinned skill) for check_skills
        self.secrets = load_secret_values()
        self.captain = captain_id(self.secrets)
        self.whatsapp = whatsapp_settings(self.secrets)
        guests = {**{f"mcp__vinci__{name}": sorted(args) for name, args in herramientas.GUEST_TOOLS.items()},
                  **{name: [] for name in GUEST_HERMES_TOOLS}}
        self.values = {"BOT": str(self.bot_bin), "CONFIG": str(config_path()), "SECRETS": str(secrets_path()),
                       "MARKER": MARKER, "USER_ID": self.captain, "MINUTOS": str(cfg.brief_minutes),
                       "VINCI": cfg.hermes_profile, "HERMES": self.hermes,
                       # Whose Vinci a profile is, on WhatsApp: the captain's number here, a friend's in theirs.
                       "WHATSAPP_OWNER": self.whatsapp.captain if self.whatsapp else "",
                       "GUEST_TOOLS": json.dumps(guests, sort_keys=True),
                       # A friend's profile points the same code at its own folder (amigos.env); empty here.
                       "DATA_DIR": "", "AMIGO": "", "ENV_EXTRA": ""}

    # -- plumbing -------------------------------------------------------------------------

    def profile_dir(self, name: str) -> Path:
        return self.root / "profiles" / name

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
        proc = subprocess.run([self.hermes, *args], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if check and proc.returncode != 0:
            raise ConfigError(f"`hermes {' '.join(args)}` falló:\n{proc.stdout}\n{proc.stderr}".strip())
        return proc

    def ensure_profile(self, name: str, description: str, *, alias: bool) -> Path:
        profile = self.profile_dir(name)
        if profile.is_dir():
            print(f"• Perfil de Hermes «{name}» ya existe: lo actualizo.")
        else:
            self.run("profile", "create", name, "--no-skills", *([] if alias else ["--no-alias"]),
                     "--description", description)
            print(f"• Perfil de Hermes «{name}» creado en {profile}")
        return profile

    def managed_config(self, profile: Path, managed: dict, *, plugins: list[str] | None = None) -> bool:
        config_file = profile / "config.yaml"
        current = yaml.safe_load(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        current = current if isinstance(current, dict) else {}
        merged = _deep_merge(copy.deepcopy(current), managed)
        if plugins:
            section = merged.setdefault("plugins", {})
            enabled = section.get("enabled") if isinstance(section.get("enabled"), list) else []
            section["enabled"] = enabled + [p for p in plugins if p not in enabled]
        if merged == current and config_file.exists():  # Hermes may re-serialize the file: compare values
            return False
        return _write_if_changed(config_file, yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))

    def toolset_switches(self, code: str | None, toolsets: list[str], blocked: list[str],
                         label: str) -> tuple[list[str], list[str]]:
        """The bot's toolsets and blocked list once the captain's [hermes.herramientas] switches are applied."""
        extra = self.cfg.extra_toolsets(code)
        if extra:
            print(f"• {label}: herramientas extra activadas en config.toml: {', '.join(extra)} (riesgos en el README)")
        return toolsets + [t for t in extra if t not in toolsets], [t for t in blocked if t not in extra]

    def _closed(self, code: str | None, files: str) -> list[str]:
        """Which of web (subject bots only), terminal and file the bot still lacks, named for the prompts."""
        extra = set(self.cfg.extra_toolsets(code))
        wanted = (*([("web", "web")] if code else []), ("terminal", "terminal"), (files, "file"))
        return [name for name, toolset in wanted if toolset not in extra]

    def _closed_note(self, code: str | None) -> str:
        closed = self._closed(code, "archivos")
        return f"; sin {' ni '.join(closed)}" if closed else ""

    def _tool_limits(self, code: str | None) -> dict[str, str]:
        """The SOUL.md and SKILL.md lines that deny a tool, so a tool switched on is never denied to the model.

        With every switch at its default they render exactly the text the templates used to hardcode."""
        closed = self._closed(code, "archivos del computador")
        denied = _join_ni(closed)
        if code:
            only = (" (solo los adjuntos que te manda por Telegram y los\n  enlaces públicos del aula)"
                    if "archivos del computador" in closed else "")
            skill = f"- Sin {denied}{only}.\n" if closed else ""
            soul = f"No tienes {_join_ni(self._closed(code, 'acceso a archivos del computador'))}. " if closed else ""
            return {"SIN_HERRAMIENTAS": soul, "LIMITE_HERRAMIENTAS": skill}
        extra = self.cfg.extra_toolsets(None)
        if not extra:
            soul = ("No tienes terminal ni acceso a archivos del computador, y no los necesitas: tus herramientas son\n"
                    "  las de Vinci (`mcp__vinci__*`), la búsqueda web y tu memoria.")
        else:
            lacking = self._closed(None, "acceso a archivos del computador")
            soul = ((f"No tienes {_join_ni(lacking)}. " if lacking else "")
                    + "Tus herramientas son las de Vinci (`mcp__vinci__*`), la búsqueda web, tu memoria y las que el "
                    f"estudiante activó en config.toml ({', '.join(extra)}).")
        skill = f"- Sin {denied}; no leas" if closed else "- No leas"
        return {"SIN_HERRAMIENTAS": soul, "LIMITE_HERRAMIENTAS": skill}

    def base_config(self, toolsets: list[str], blocked: list[str], mcp_name: str, mcp_args: list[str],
                    skill: str) -> dict:
        managed = {
            "model": {"provider": self.cfg.hermes_provider, "default": self.cfg.hermes_model},
            "timezone": str(self.cfg.core.tz),
            "platform_toolsets": {"telegram": toolsets, "whatsapp": toolsets, "cli": toolsets,
                                  "cron": [t for t in toolsets if t not in ("clarify", "session_search")]},
            "agent": {"disabled_toolsets": blocked},
            "tools": {"tool_search": {"enabled": "off"}},
            "skills": {"auto_load": [skill], "project_discovery": False},
            "compression": {"threshold_tokens": COMPRESSION_THRESHOLD_TOKENS},
            "mcp_servers": {mcp_name: {
                "command": str(self.bot_bin), "args": ["mcp", *mcp_args],
                "env": {"AULA_CONFIG": self.values["CONFIG"], "AULA_SECRETS": self.values["SECRETS"]},
                "timeout": 180, "tools": {"resources": False, "prompts": False},
            }},
            "approvals": {"deny": APPROVALS_DENY},
            # Only the captain (TELEGRAM_ALLOWED_USERS): anyone else gets silence, not a pairing code.
            "unauthorized_dm_behavior": "ignore",
            # Hermes' WhatsApp default posts a line per tool call («⚙️ mcp__vinci__semana…»); Telegram's is off.
            "display": {"platforms": {"whatsapp": {"tool_progress": "off", "busy_ack_detail": False}}},
            # Voice notes are in Spanish (Hermes' Whisper hint defaults to English).
            "stt": {"language": "es"},
            # No generic «shall I build a profile of you?» in a bot's first reply: each bot knows its job.
            "onboarding": {"profile_build": "off"},
            # By default the gateway drops what a bot got while it was not serving it: whatever the captain sent
            # during a restart, or a new bot's first /start (it serves a new bot a minute after it is created).
            "platforms": {"telegram": {"extra": {"drop_pending_on_cold_boot": False}}},
        }
        if self.cfg.telegram_api != DEFAULT_TELEGRAM_API:
            # A local Bot API server (or the E2E test's stand-in) for Hermes' own Telegram client and
            # the MCP server too.
            managed["platforms"]["telegram"]["extra"].update(base_url=f"{self.cfg.telegram_api}/bot",
                                                             base_file_url=f"{self.cfg.telegram_api}/file/bot")
            managed["mcp_servers"][mcp_name]["env"]["ESPOL_TELEGRAM_API_BASE"] = self.cfg.telegram_api
        return managed

    def telegram_env(self, profile: Path, token: str) -> bool:
        return upsert_env(profile / ".env", {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_ALLOWED_USERS": self.captain,
                                             "TELEGRAM_HOME_CHANNEL": self.captain})

    def jobs(self, name: str) -> list[dict]:
        jobs_file = self.profile_dir(name) / "cron" / "jobs.json"
        return json.loads(jobs_file.read_text(encoding="utf-8")).get("jobs", []) if jobs_file.exists() else []

    def reconcile_job(self, name: str, job_name: str, schedule: str, script: str, *, no_agent: bool,
                      prompt: str | None = None, skills: tuple[str, ...] = (), enabled: bool = True,
                      deliver: str | None = None) -> None:
        deliver = deliver or f"telegram:{self.captain}"
        existing = [j for j in self.jobs(name) if j.get("name") == job_name]
        if not existing:
            self.run("-p", name, "cron", "create", schedule, *([prompt] if prompt else []), "--script", script,
                     "--deliver", deliver, "--name", job_name, *(["--no-agent"] if no_agent else []),
                     *[arg for skill in skills for arg in ("--skill", skill)],
                     *([] if enabled else ["--paused", "--paused-reason", "materia archivada"]))
            print(f"• cron «{job_name}» creado ({schedule})")
            return
        job = existing[0]
        current_schedule = (job.get("schedule") or {}).get("display") or job.get("schedule_display")
        wanted = (schedule, script, deliver, no_agent, prompt or "", list(skills))
        have = (current_schedule, job.get("script"), job.get("deliver"), bool(job.get("no_agent")),
                job.get("prompt") or "", list(job.get("skills") or []))
        changes = []
        if have != wanted:
            self.run("-p", name, "cron", "edit", job["id"], "--schedule", schedule, "--script", script,
                     "--deliver", deliver, "--no-agent" if no_agent else "--agent",
                     *(["--prompt", prompt] if prompt else []),
                     *([arg for skill in skills for arg in ("--skill", skill)] if skills else ["--clear-skills"]))
            changes.append("actualizado")
        if enabled and job.get("enabled") is False:
            self.run("-p", name, "cron", "resume", job["id"])
            changes.append("reanudado")
        elif not enabled and job.get("enabled") is not False:
            self.run("-p", name, "cron", "pause", job["id"])
            changes.append("pausado")
        print(f"• cron «{job_name}» {' y '.join(changes) or 'sin cambios'} ({schedule})")
        for extra in existing[1:]:
            self.run("-p", name, "cron", "remove", extra["id"])
            print(f"  · quité un «{job_name}» duplicado")

    def remove_jobs(self, name: str, job_names: tuple[str, ...]) -> None:
        for job in self.jobs(name):
            if job.get("name") in job_names:
                self.run("-p", name, "cron", "remove", job["id"])
                print(f"• cron viejo «{job['name']}» quitado")

    def telegram_profile(self, profile: Path, token: str, character: characters.Character, label: str,
                         name: str | None = None) -> None:
        """Sets the bot's Telegram photo (its avatar from the party) and, for a subject bot, its name, with its
        own token. A stamp records what was set on which bot, so a rerun calls Telegram only when the
        wanted name or photo changes, and a name or photo the captain later changed by hand stays."""
        stamp_file = profile / "telegram-profile.json"
        bot_id = token.split(":", 1)[0]
        try:
            stamp = json.loads(stamp_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            stamp = {}
        stamp = stamp if isinstance(stamp, dict) and stamp.get("bot") == bot_id else {"bot": bot_id}
        telegram = Telegram(TelegramSecrets(token, self.captain), api=self.cfg.telegram_api)
        retry = "Lo intento de nuevo la próxima vez que corras ./setup.sh"
        if name is not None:
            if stamp.get("name") == name:
                print(f"• {label}: nombre en Telegram sin cambios")
            else:
                try:
                    if telegram.my_name() != name:
                        telegram.set_my_name(name)
                    stamp["name"] = name
                    print(f"• {label}: su nombre en Telegram quedó «{name}»")
                except TelegramError as exc:
                    print(f"⚠ No pude ponerle el nombre «{name}» en Telegram ({exc}). {retry}, o cámbialo tú en "
                          "@BotFather con /setname.")
        if character.avatar is None:
            print(f"• {label}: sin foto propia en la party; su foto de Telegram queda como está")
        else:
            photo = character.avatar.read_bytes()
            digest = hashlib.sha256(photo).hexdigest()
            if stamp.get("photo") == digest:
                print(f"• Foto de perfil de {label} sin cambios ({character.avatar.name})")
            else:
                try:
                    telegram.set_profile_photo(photo)
                    stamp["photo"] = digest
                    print(f"• Foto de perfil de {label} puesta ({character.avatar.name})")
                except TelegramError as exc:
                    print(f"⚠ No pude ponerle su foto a {label} ({exc}). {retry}, o pónsela tú en @BotFather con "
                          f"/setuserpic ({character.avatar}).")
        _write_if_changed(stamp_file, json.dumps(stamp, ensure_ascii=False) + "\n")

    def set_parked(self, name: str, parked: bool) -> bool:
        marker = self.profile_dir(name) / "gateway.parked"
        if parked and not marker.exists():
            marker.write_text(f"{MARKER}: materia archivada (pídele a Vinci reactivarla)\n", encoding="utf-8")
            return True
        if not parked and marker.exists() and MARKER in marker.read_text(encoding="utf-8", errors="replace"):
            marker.unlink()
            return True
        return False

    # -- Vinci --------------------------------------------------------------------------

    def migrate_legacy(self) -> None:
        """The pre-Vinci bot lived in the `espol` profile: rename it so Vinci keeps its memory."""
        name, legacy = self.cfg.hermes_profile, self.profile_dir(LEGACY_PROFILE)
        if name == LEGACY_PROFILE or not legacy.is_dir() or self.profile_dir(name).exists():
            return
        soul = legacy / "SOUL.md"
        if not soul.exists() or MARKER not in soul.read_text(encoding="utf-8", errors="replace"):
            return  # somebody else's profile called espol: leave it alone
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        unit = config_home / "systemd" / "user" / f"hermes-gateway-{LEGACY_PROFILE}.service"
        if unit.exists():
            raise ConfigError(
                f"Antes de convertir el bot «{LEGACY_PROFILE}» en Vinci, apaga su servicio viejo:\n"
                f"  {LEGACY_PROFILE} gateway stop && {LEGACY_PROFILE} gateway uninstall\n"
                "y vuelve a correr ./setup.sh (desde ahora un solo gateway de Hermes atiende a todos tus bots).")
        self.run("profile", "rename", LEGACY_PROFILE, name)
        print(f"• Perfil «{LEGACY_PROFILE}» renombrado a «{name}»: Vinci conserva la memoria y las conversaciones "
              "del bot académico.")

    def vinci(self) -> None:
        name = self.cfg.hermes_profile
        token = self.secrets.get(token_key(), "")
        if not token:
            raise ConfigError("Falta TELEGRAM_BOT_TOKEN (el bot de Vinci) en secrets.env")
        self.migrate_legacy()
        profile = self.ensure_profile(name, "Vinci: tu bot principal de ESPOL (avisos del aula, consultas generales, "
                                            "reparte cosas a los bots de cada materia).", alias=True)
        toolsets, blocked = self.toolset_switches(None, VINCI_TOOLSETS, BLOCKED_TOOLSETS, "Vinci")
        managed = self.base_config(toolsets, blocked, "vinci", ["vinci", "--hermes-home", str(profile)], "vinci")
        changed = self.managed_config(profile, managed, plugins=[PLUGIN])
        self.configured.append((name, "vinci"))
        print(f"• config.yaml {'actualizado' if changed else 'sin cambios'} (modelo {self.cfg.hermes_model}, "
              f"zona {self.cfg.core.tz}; herramientas: búsqueda web, memoria, skills y las de Vinci"
              f"{self._closed_note(None)})")
        changed = self.telegram_env(profile, token)
        print(f"• .env de Vinci {'actualizado' if changed else 'sin cambios'} (Telegram solo para tu ID)")

        party = "\n".join(f"- «{characters.bot_name(code, c.subject or code)}»: {c.subject} ({code})"
                          for code, c in characters.party().items())
        values = {**self.values, "PROFILE_HOME": str(profile), "PARTY": party, "CODIGO": "",
                  **self._tool_limits(None)}
        changed = _write_if_changed(profile / "SOUL.md", _render(TEMPLATES / "vinci" / "SOUL.md", values))
        changed |= _write_if_changed(profile / "skills" / SKILLS_CATEGORY / "vinci" / "SKILL.md",
                                     _render(TEMPLATES / "vinci" / "SKILL.md", values))
        changed |= _write_if_changed(profile / "skills" / SKILLS_CATEGORY / "quiz" / "SKILL.md",
                                     _render(TEMPLATES / "vinci" / "quiz" / "SKILL.md", values))
        for script, command in {"vinci-sondeo.sh": "sondeo", "vinci-resumen.sh": "resumen",
                                "vinci-mantenimiento.sh": "mantenimiento", "vinci-apuntes.sh": "notes"}.items():
            changed |= _write_if_changed(profile / "scripts" / script,
                                         _render(TEMPLATES / "cron-script.sh", {**values, "COMMAND": command}), 0o755)
        plugin_changed = self._install_plugin(profile, values)
        if plugin_changed:
            self._reload_gateway_plugins(profile)
        changed |= plugin_changed | self._drop_legacy_files(profile)
        print(f"• SOUL.md, skills vinci y quiz, plugin de botones y scripts de cron {'instalados' if changed else 'sin cambios'}")
        self.telegram_profile(profile, token, characters.vinci(), "Vinci")

        self.remove_jobs(name, ("espol-sondeo", "espol-resumen"))
        self.reconcile_job(name, "vinci-sondeo", poll_schedule(self.cfg.poll_minutes, self.cfg.summary_time.minute),
                           "vinci-sondeo.sh", no_agent=True)
        self.reconcile_job(name, "vinci-mantenimiento", "2,12,22,32,42,52 * * * *",
                           "vinci-mantenimiento.sh", no_agent=True)
        self.reconcile_job(name, "vinci-resumen", f"{self.cfg.summary_time.minute} {self.cfg.summary_time.hour} * * *",
                           "vinci-resumen.sh", no_agent=True)
        self.reconcile_job(name, "vinci-apuntes", "* * * * *", "vinci-apuntes.sh", no_agent=True)

    def whatsapp_session(self) -> Path:
        return self.root / "platforms" / "whatsapp" / "session"

    def whatsapp_on(self) -> None:
        """Vinci on WhatsApp. Hermes' WhatsApp bridge belongs to the default profile (one number for the whole
        gateway), so this is the one step that writes the default profile: its .env (who may write), its
        config.yaml (a route per sender: the captain to Vinci, each friend to their own Vinci) and its plugin
        vinci-whatsapp, which sorts every WhatsApp message before Hermes does (hermes/plugins/vinci-whatsapp)."""
        wa = self.whatsapp
        if wa is None:
            return
        from espol_bot import amigos
        friends = amigos.active(self.cfg)
        paired = (self.whatsapp_session() / "creds.json").exists()
        env = {"WHATSAPP_MODE": "bot", "WHATSAPP_ALLOWED_USERS": ",".join([wa.captain, *(f.numero for f in friends)]),
               "WHATSAPP_HOME_CHANNEL": wa.captain,
               # Every group reaches the plugin, which answers only in the groups the captain turned on; only a
               # mention of Vinci gets that far, the rest of a group's talk stays in the bridge. Hermes accepts an
               # open group policy only with allow-all: the plugin drops strangers, and the catch-all route below
               # sends any it missed to Vinci's guest tools, never to the default profile.
               "WHATSAPP_GROUP_POLICY": "open", "WHATSAPP_ALLOW_ALL_USERS": "true", "WHATSAPP_REQUIRE_MENTION": "true"}
        if paired:  # enabled without a session, every gateway start would wait on a bridge that only shows a QR
            env["WHATSAPP_ENABLED"] = "true"
        changed = update_secret_values(env, remove=("WHATSAPP_GROUP_ALLOWED_USERS",), path=self.root / ".env")

        config_file = self.root / "config.yaml"
        current = yaml.safe_load(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
        current = current if isinstance(current, dict) else {}
        merged = copy.deepcopy(current)
        gateway = merged.setdefault("gateway", {})
        gateway["multiplex_profiles"] = True
        routes = [r for r in gateway.get("profile_routes") or []
                  if not str((r or {}).get("name", "")).startswith(WHATSAPP_ROUTE_PREFIX)]
        for key, number, profile in [("captain", wa.captain, self.cfg.hermes_profile),
                                     *((f.slug, f.numero, amigos.profile_name(f)) for f in friends)]:
            routes += self._whatsapp_routes(f"{WHATSAPP_ROUTE_PREFIX}{key}", number, profile)
        routes.append({"name": f"{WHATSAPP_ROUTE_PREFIX}others", "platform": "whatsapp",
                       "profile": self.cfg.hermes_profile})
        gateway["profile_routes"] = routes
        section = merged.setdefault("whatsapp", {})
        section.pop("group_allowed_chats", None)  # groups are the plugin's now
        section.update({
            "reply_prefix": "",
            "unauthorized_dm_behavior": "ignore",
            # «vinci, …» or «@vinci …» typed by hand also counts, not only a mention picked from the list.
            "mention_patterns": [r"(?<![\w@])@?vinci\w*\b"],
        })
        test = self.cfg.core.raw.get("test") or {}
        if test.get("whatsapp_puente"):  # E2E: the stand-in bridge already running on its own port
            section["bridge_port"] = int(str(test["whatsapp_puente"]).rsplit(":", 1)[1])
            section["bridge_script"] = str(test["whatsapp_script"])
        _deep_merge(merged, {"display": {"platforms": {"whatsapp": {"tool_progress": "off", "busy_ack_detail": False}}}})
        plugins = merged.setdefault("plugins", {})
        enabled = plugins.get("enabled") if isinstance(plugins.get("enabled"), list) else []
        plugins["enabled"] = enabled + [p for p in [WHATSAPP_PLUGIN] if p not in enabled]
        if merged != current:
            changed |= _write_if_changed(config_file, yaml.safe_dump(merged, allow_unicode=True, sort_keys=False))

        values = {**self.values, "CAPTAIN": wa.captain, "REGISTRY": str(amigos.registry_path(self.cfg)),
                  "GROUPS": str(amigos.groups_path(self.cfg)), "BRIDGE": self.cfg.whatsapp_bridge,
                  "RESTART": "" if test.get("whatsapp_sin_reinicio") else "1"}
        # The gateway runs pre_gateway_dispatch with the plugins of the profile the sender is routed to, so the
        # plugin goes in every profile a WhatsApp route reaches, plus the default for anything unrouted.
        routed = [self.profile_dir(self.cfg.hermes_profile), *(self.profile_dir(amigos.profile_name(f)) for f in friends)]
        for home in [self.root, *routed]:
            plugin_changed = home != self.root and self.managed_config(home, {}, plugins=[WHATSAPP_PLUGIN])
            for plugin_file in sorted((TEMPLATES / "plugins" / WHATSAPP_PLUGIN).glob("*.*")):
                plugin_changed |= _write_if_changed(home / "plugins" / WHATSAPP_PLUGIN / plugin_file.name,
                                                    _render(plugin_file, values))
            if plugin_changed:
                self._reload_gateway_plugins(home)
            changed |= plugin_changed
        who = f"tu chat y {len(friends)} amigo{'s' if len(friends) != 1 else ''}" if friends else "tu chat"
        print(f"• WhatsApp: {who} y los grupos que actives {'(actualizado)' if changed else '(sin cambios)'}")
        if not paired:
            print("⚠ WhatsApp: el número de Vinci no está vinculado. Corre `.venv/bin/espol-bot whatsapp-vincular "
                  "<número>` y vuelve a correr ./setup.sh.")
        elif changed:
            print("  Reinicia el gateway para que lo tome: hermes gateway restart")

    def _whatsapp_routes(self, name: str, number: str, profile: str) -> list[dict]:
        """One person's routes. Hermes compares a route's user_id with the sender as the bridge gives it: the
        phone JID, or the LID when WhatsApp hides the number (known once the session saw it). In a private
        chat, the chat_id route matches either form."""
        senders = [f"{number}@s.whatsapp.net"]
        try:
            lid = json.loads((self.whatsapp_session() / f"lid-mapping-{number}.json").read_text(encoding="utf-8"))
            senders += [f"{str(lid).split('@')[0]}@lid"] if str(lid).strip() else []
        except (OSError, ValueError):
            pass
        return [*({"name": name, "platform": "whatsapp", "user_id": s, "profile": profile} for s in senders),
                {"name": name, "platform": "whatsapp", "chat_id": number, "profile": profile}]

    def friend(self, friend) -> None:
        """A friend's own Vinci (amigos.py): a profile like Vinci's, over the friend's folder, answering on WhatsApp
        only; its poll, token renewal and 7:00 summary write to the friend's chat through the bridge."""
        from espol_bot import amigos
        name = amigos.profile_name(friend)
        profile = self.ensure_profile(name, f"El Vinci de {friend.nombre}: su aula de ESPOL por WhatsApp.", alias=False)
        env = amigos.env(self.cfg, friend)
        toolsets, blocked = VINCI_TOOLSETS, BLOCKED_TOOLSETS
        managed = self.base_config(toolsets, blocked, "vinci", ["amigo", "--hermes-home", str(profile)], "amigo")
        managed["mcp_servers"]["vinci"]["env"].update(env)
        changed = self.managed_config(profile, managed, plugins=[PLUGIN])
        self.configured.append((name, "amigo"))
        extra = "".join(f"export {key}='{env[key]}'\n" for key in ("AULA_DATA_DIR", "ESPOL_AMIGO"))
        values = {**self.values, "PROFILE_HOME": str(profile), "NOMBRE": friend.nombre, "CODIGO": "",
                  "SECRETS": env["AULA_SECRETS"], "DATA_DIR": env["AULA_DATA_DIR"], "AMIGO": friend.slug,
                  "WHATSAPP_OWNER": friend.numero, "ENV_EXTRA": extra}
        changed |= _write_if_changed(profile / "SOUL.md", _render(TEMPLATES / "amigo" / "SOUL.md", values))
        changed |= _write_if_changed(profile / "skills" / SKILLS_CATEGORY / "amigo" / "SKILL.md",
                                     _render(TEMPLATES / "amigo" / "SKILL.md", values))
        for script, command in {"amigo-sondeo.sh": "sondeo", "amigo-resumen.sh": "resumen",
                                "amigo-mantenimiento.sh": "mantenimiento"}.items():
            changed |= _write_if_changed(profile / "scripts" / script,
                                         _render(TEMPLATES / "cron-script.sh", {**values, "COMMAND": command}), 0o755)
        plugin_changed = self._install_plugin(profile, values)
        if plugin_changed:
            self._reload_gateway_plugins(profile)
        print(f"• Vinci de {friend.nombre}: {'instalado' if changed | plugin_changed else 'sin cambios'}")
        self.reconcile_job(name, "amigo-sondeo", poll_schedule(self.cfg.poll_minutes, self.cfg.summary_time.minute),
                           "amigo-sondeo.sh", no_agent=True, deliver="local")
        self.reconcile_job(name, "amigo-mantenimiento", "2,12,22,32,42,52 * * * *", "amigo-mantenimiento.sh",
                           no_agent=True, deliver="local")
        self.reconcile_job(name, "amigo-resumen", f"{self.cfg.summary_time.minute} {self.cfg.summary_time.hour} * * *",
                           "amigo-resumen.sh", no_agent=True, deliver="local")

    def drop_friend(self, friend) -> None:
        from espol_bot import amigos
        name = amigos.profile_name(friend)
        if self.profile_dir(name).is_dir():
            (self.profile_dir(name) / "gateway.parked").touch()  # the running gateway lets it go first
            self.run("profile", "delete", "-y", name)
            print(f"• Vinci de {friend.nombre}: perfil borrado")

    @staticmethod
    def _install_plugin(profile: Path, values: dict[str, str]) -> bool:
        changed = False
        for plugin_file in sorted((TEMPLATES / "plugins" / PLUGIN).glob("*.*")):
            changed |= _write_if_changed(profile / "plugins" / PLUGIN / plugin_file.name, _render(plugin_file, values))
        return changed

    def _reload_gateway_plugins(self, profile: Path) -> None:
        """Has a running gateway load the profile's plugins now, like `hermes plugins enable` does (that command
        also runs Hermes' package-manager admission, which can refuse on an install without its lock file)."""
        sock = self.root / "gateway.sock"
        pointer = self.root / "gateway.sock.path"  # where Hermes puts it when the path is too long for a socket
        if not sock.exists() and pointer.is_file():
            sock = Path(pointer.read_text(encoding="utf-8-sig").strip())
        if not sock.exists():
            return  # no gateway running: it finds the plugin when it starts
        request = {"verb": "reload-plugins", "id": 1, "protocol": 1, "params": {"home": str(profile)}}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(30)
                conn.connect(str(sock))
                conn.sendall(json.dumps(request).encode() + b"\n")
                answer = json.loads(conn.makefile("rb").readline() or b"{}")
        except (OSError, ValueError) as exc:
            answer = {"error": str(exc)}
        if not (answer.get("ok") and (answer.get("result") or {}).get("reloaded")):
            print(f"⚠ El gateway de Hermes no cargó el plugin de {profile.name} ({answer.get('error') or answer}); "
                  "reinícialo: hermes gateway stop && hermes gateway start")

    @staticmethod
    def _drop_legacy_files(profile: Path) -> bool:
        changed = False
        old_skill = profile / "skills" / "espol" / "espol-academico" / "SKILL.md"
        if old_skill.exists() and MARKER in old_skill.read_text(encoding="utf-8", errors="replace"):
            shutil.rmtree(old_skill.parent)
            changed = True
        for script in ("espol-sondeo.sh", "espol-resumen.sh"):
            path = profile / "scripts" / script
            if path.exists() and MARKER in path.read_text(encoding="utf-8", errors="replace"):
                path.unlink()
                changed = True
        return changed

    # -- subject bots ---------------------------------------------------------------------

    def subject(self, subject: materias.Subject) -> None:
        name = self.cfg.subject_profile(subject.code)
        token = self.secrets.get(token_key(subject.code), "")
        if not token:
            print(f"• {subject.display}: falta su token ({token_key(subject.code)}); créalo desde Vinci (pídele «arma mi equipo»).")
            return
        if token == self.secrets.get(token_key()):
            raise ConfigError(f"{subject.display} usa el mismo token que Vinci; cada bot necesita el suyo.")
        profile = self.ensure_profile(name, f"El bot de la materia {subject.name} ({subject.code}).", alias=False)
        toolsets, blocked = self.toolset_switches(subject.code, SUBJECT_TOOLSETS, BLOCKED_TOOLSETS + ["web", "search"],
                                                  subject.display)
        managed = self.base_config(toolsets, blocked, "materia",
                                   ["materia", "--curso", subject.code, "--hermes-home", str(profile)], "vinci-materia")
        managed["cron"] = {"wrap_response": False}
        changed = self.managed_config(profile, managed, plugins=[PLUGIN])
        self.configured.append((name, "vinci-materia"))
        values = {**self.values, "NOMBRE": subject.name, "CODIGO": subject.code, "BOT_NOMBRE": subject.display,
                  "PROFILE_HOME": str(profile), **self._tool_limits(subject.code)}
        changed |= _write_if_changed(profile / "SOUL.md", _render(TEMPLATES / "materia" / "SOUL.md", values))
        changed |= _write_if_changed(profile / "skills" / SKILLS_CATEGORY / "vinci-materia" / "SKILL.md",
                                     _render(TEMPLATES / "materia" / "SKILL.md", values))
        changed |= _write_if_changed(profile / "skills" / SKILLS_CATEGORY / "quiz" / "SKILL.md",
                                     _render(TEMPLATES / "materia" / "quiz" / "SKILL.md", values))
        if self._install_plugin(profile, values):
            changed = True
            self._reload_gateway_plugins(profile)
        # The token last: the gateway connects the bot once its .env has one, and the /start the captain may
        # have sent already must find the plugin loaded.
        changed |= self.telegram_env(profile, token)
        changed |= _write_if_changed(profile / "scripts" / "vinci-agenda.sh", _render(
            TEMPLATES / "cron-script.sh", {**values, "COMMAND": f"agenda --curso {subject.code}"}), 0o755)
        print(f"• {subject.display}: config, .env, SOUL.md, skill, plugin y agenda {'instalados' if changed else 'sin cambios'}"
              f" (solo su materia, su cuaderno y sus skills{self._closed_note(subject.code)})")
        self.telegram_profile(profile, token, characters.for_subject(subject.code), subject.display,
                              name=subject.display)
        prompt = (f"Eres el bot de la materia {subject.name} ({subject.code}). El script de tu "
                  "agenda (arriba) te dice qué hacer ahora: el brief antes de una clase o algo que Vinci te pasó. "
                  "Sigue sus instrucciones; tu respuesta final le llega al estudiante en tu chat de Telegram.")
        active = subject.state == "activa"
        # Due every half minute (a sixth field is seconds) and run at each once-a-minute check. `* * * * *` would
        # skip a minute whenever a run ends just past the mark, and every other minute for good if the gateway's
        # check falls in a minute's last second.
        self.reconcile_job(name, "vinci-agenda", "* * * * * */30", "vinci-agenda.sh", no_agent=False,
                           prompt=prompt, skills=("vinci-materia",), enabled=active)
        if self.set_parked(name, not active):
            print(f"• {subject.display}: {'archivada (gateway.parked)' if not active else 'reactivada'}")


    # -- install check --------------------------------------------------------------------

    def check_skills(self) -> bool:
        """False when a bot's SKILL does not reach the prompt a fresh session would store."""
        ok = True
        for name, skill in self.configured:
            profile = self.profile_dir(name)
            try:
                lines = skill_check.skill_lines(
                    (profile / "skills" / SKILLS_CATEGORY / skill / "SKILL.md").read_text(encoding="utf-8"),
                    (profile / "SOUL.md").read_text(encoding="utf-8"))
                found = skill_check.problems(skill_check.inspect_profile(self.hermes, profile), lines)
            except skill_check.Unavailable as exc:
                print(f"⚠ {name}: no pude revisar si su skill llega al modelo ({exc}).")
                continue
            except OSError as exc:
                found = [f"no leí su skill o su SOUL.md ({exc})"]
            if found:
                ok = False
                print(f"✗ {name}: su skill NO llega al modelo, así que el bot no sigue sus reglas:"
                      + "".join(f"\n    {line}" for line in found)
                      + f"\n  Arréglalo: vuelve a correr ./setup.sh y luego `hermes gateway restart`. Si sigue igual, "
                        f"revisa que `skills` no esté en agent.disabled_toolsets de {profile / 'config.yaml'}.")
            else:
                print(f"✓ {name}: su skill llega al modelo ({len(lines)} líneas en su prompt de Telegram)")
        return ok


def provision(cfg: BotConfig, *, hermes_bin: str | None = None) -> int:
    setup = Setup(cfg, hermes_bin=hermes_bin)
    setup.vinci()
    from espol_bot import amigos
    for friend in amigos.active(cfg):
        setup.friend(friend)
    setup.whatsapp_on()
    subjects = materias.load(cfg.core)
    stray = sorted(set(cfg.subject_toolsets_by_code) - {s.code for s in subjects})
    if stray:
        print(f"⚠ [hermes.herramientas.por_materia] {', '.join(stray)} no es ninguna de tus materias en materias.toml; revisa el código.")
    for subject in subjects:
        if subject.state != "pendiente":
            setup.subject(subject)
    return 0 if setup.check_skills() else 1
