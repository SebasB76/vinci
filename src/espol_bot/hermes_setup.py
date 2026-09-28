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
  `mcp__<server>__<tool>`). Tool Search is turned off so the model sees exactly that list.
  `skills.auto_load` pins a skill fully loaded in every session (chat and cron), so no
  bot needs the skills toolset (whose skill_manage writes files).
- Cron: `--no-agent` jobs run a script with zero model calls; an agent job with
  `--script` runs the script first and skips the model when its last line is
  `{"wakeAgent": false}`. `timezone` sets the zone cron expressions use.
- Plugins in a profile's `plugins/` load only when named in `plugins.enabled`.
- `compression.threshold_tokens` caps when a chat gets summarized (default 256K); a running
  gateway rebuilds its cached agent when it changes, so it applies at the next message.

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
import subprocess
import sys
from pathlib import Path

import yaml

from aula_core.config import REPO_ROOT, ConfigError, config_path, load_secret_values, secrets_path
from espol_bot import characters, materias
from espol_bot.config import DEFAULT_TELEGRAM_API, BotConfig, TelegramSecrets, captain_id, token_key
from espol_bot.telegram import Telegram, TelegramError

MARKER = "Generado por setup.sh de espol-academic-bot"
LEGACY_PROFILE = "espol"
PLUGIN = "vinci-botones"
SKILLS_CATEGORY = "vinci"
TEMPLATES = REPO_ROOT / "hermes"

VINCI_TOOLSETS = ["web", "memory", "session_search", "clarify", "mcp-vinci"]
SUBJECT_TOOLSETS = ["memory", "session_search", "clarify", "mcp-materia"]
# Removed everywhere, whatever a platform list says (Hermes applies this last). `skills` goes
# too: its skill_manage tool writes files; each bot's own skill is pinned with skills.auto_load.
BLOCKED_TOOLSETS = [
    "terminal", "file", "code_execution", "browser", "computer_use", "delegation", "cronjob", "kanban",
    "skills", "vision", "video", "image_gen", "video_gen", "tts", "todo", "connections", "homeassistant",
    "spotify", "x_search", "a2a",
]
APPROVALS_DENY = ["*secrets.env*", "*CANVAS_TOKEN*", "*api/v1*"]
# Every message resends the chat so far. After a summary the fixed prompt, the summary and Hermes'
# 25K verbatim tail already weigh ~50K, so a lower trigger would summarize again every question or two.
COMPRESSION_THRESHOLD_TOKENS = 80_000


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
        self.secrets = load_secret_values()
        self.captain = captain_id(self.secrets)
        self.values = {"BOT": str(self.bot_bin), "CONFIG": str(config_path()), "SECRETS": str(secrets_path()),
                       "MARKER": MARKER, "USER_ID": self.captain, "MINUTOS": str(cfg.brief_minutes),
                       "VINCI": cfg.hermes_profile, "HERMES": self.hermes}

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

    def base_config(self, toolsets: list[str], blocked: list[str], mcp_name: str, mcp_args: list[str],
                    skill: str) -> dict:
        managed = {
            "model": {"provider": self.cfg.hermes_provider, "default": self.cfg.hermes_model},
            "timezone": str(self.cfg.core.tz),
            "platform_toolsets": {"telegram": toolsets, "cli": toolsets,
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
            # Voice notes are in Spanish (Hermes' Whisper hint defaults to English).
            "stt": {"language": "es"},
        }
        if self.cfg.telegram_api != DEFAULT_TELEGRAM_API:
            # A local Bot API server (or the E2E test's stand-in) for Hermes' own Telegram client and
            # the MCP server too.
            managed["platforms"] = {"telegram": {"extra": {"base_url": f"{self.cfg.telegram_api}/bot",
                                                           "base_file_url": f"{self.cfg.telegram_api}/file/bot"}}}
            managed["mcp_servers"][mcp_name]["env"]["ESPOL_TELEGRAM_API_BASE"] = self.cfg.telegram_api
        return managed

    def telegram_env(self, profile: Path, token: str) -> bool:
        return upsert_env(profile / ".env", {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_ALLOWED_USERS": self.captain,
                                             "TELEGRAM_HOME_CHANNEL": self.captain})

    def jobs(self, name: str) -> list[dict]:
        jobs_file = self.profile_dir(name) / "cron" / "jobs.json"
        return json.loads(jobs_file.read_text(encoding="utf-8")).get("jobs", []) if jobs_file.exists() else []

    def reconcile_job(self, name: str, job_name: str, schedule: str, script: str, *, no_agent: bool,
                      prompt: str | None = None, skills: tuple[str, ...] = (), enabled: bool = True) -> None:
        deliver = f"telegram:{self.captain}"
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
        managed = self.base_config(VINCI_TOOLSETS, BLOCKED_TOOLSETS, "vinci", ["vinci", "--hermes-home", str(profile)],
                                   "vinci")
        changed = self.managed_config(profile, managed, plugins=[PLUGIN])
        print(f"• config.yaml {'actualizado' if changed else 'sin cambios'} (modelo {self.cfg.hermes_model}, "
              f"zona {self.cfg.core.tz}; herramientas: búsqueda web, memoria y las de Vinci; sin terminal ni archivos)")
        changed = self.telegram_env(profile, token)
        print(f"• .env de Vinci {'actualizado' if changed else 'sin cambios'} (Telegram solo para tu ID)")

        party = "\n".join(f"- «{characters.bot_name(code, c.subject or code)}»: {c.subject} ({code})"
                          for code, c in characters.party().items())
        values = {**self.values, "PROFILE_HOME": str(profile), "PARTY": party}
        changed = _write_if_changed(profile / "SOUL.md", _render(TEMPLATES / "vinci" / "SOUL.md", values))
        changed |= _write_if_changed(profile / "skills" / SKILLS_CATEGORY / "vinci" / "SKILL.md",
                                     _render(TEMPLATES / "vinci" / "SKILL.md", values))
        for script, command in {"vinci-sondeo.sh": "sondeo", "vinci-resumen.sh": "resumen"}.items():
            changed |= _write_if_changed(profile / "scripts" / script,
                                         _render(TEMPLATES / "cron-script.sh", {**values, "COMMAND": command}), 0o755)
        changed |= self._install_plugin(profile, values)
        changed |= self._drop_legacy_files(profile)
        print(f"• SOUL.md, skill vinci, plugin de botones y scripts de cron {'instalados' if changed else 'sin cambios'}")
        self.telegram_profile(profile, token, characters.vinci(), "Vinci")

        self.remove_jobs(name, ("espol-sondeo", "espol-resumen"))
        self.reconcile_job(name, "vinci-sondeo", f"every {self.cfg.poll_minutes}m", "vinci-sondeo.sh", no_agent=True)
        self.reconcile_job(name, "vinci-resumen", f"{self.cfg.summary_time.minute} {self.cfg.summary_time.hour} * * *",
                           "vinci-resumen.sh", no_agent=True)

    @staticmethod
    def _install_plugin(profile: Path, values: dict[str, str]) -> bool:
        changed = False
        for plugin_file in sorted((TEMPLATES / "plugins" / PLUGIN).glob("*.*")):
            changed |= _write_if_changed(profile / "plugins" / PLUGIN / plugin_file.name, _render(plugin_file, values))
        return changed

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
        managed = self.base_config(SUBJECT_TOOLSETS, BLOCKED_TOOLSETS + ["web", "search"], "materia",
                                   ["materia", "--curso", subject.code, "--hermes-home", str(profile)], "vinci-materia")
        managed["cron"] = {"wrap_response": False}
        changed = self.managed_config(profile, managed, plugins=[PLUGIN])
        changed |= self.telegram_env(profile, token)
        values = {**self.values, "NOMBRE": subject.name, "CODIGO": subject.code, "BOT_NOMBRE": subject.display,
                  "PROFILE_HOME": str(profile)}
        changed |= _write_if_changed(profile / "SOUL.md", _render(TEMPLATES / "materia" / "SOUL.md", values))
        changed |= _write_if_changed(profile / "skills" / SKILLS_CATEGORY / "vinci-materia" / "SKILL.md",
                                     _render(TEMPLATES / "materia" / "SKILL.md", values))
        changed |= self._install_plugin(profile, values)
        changed |= _write_if_changed(profile / "scripts" / "vinci-agenda.sh", _render(
            TEMPLATES / "cron-script.sh", {**values, "COMMAND": f"agenda --curso {subject.code}"}), 0o755)
        print(f"• {subject.display}: config, .env, SOUL.md, skill, plugin y agenda {'instalados' if changed else 'sin cambios'}"
              f" (solo su materia y su cuaderno; sin web, terminal ni archivos)")
        self.telegram_profile(profile, token, characters.for_subject(subject.code), subject.display,
                              name=subject.display)
        prompt = (f"Eres el bot de la materia {subject.name} ({subject.code}). El script de tu "
                  "agenda (arriba) te dice qué hacer ahora: el brief antes de una clase o algo que Vinci te pasó. "
                  "Sigue sus instrucciones; tu respuesta final le llega al estudiante en tu chat de Telegram.")
        active = subject.state == "activa"
        self.reconcile_job(name, "vinci-agenda", "every 1m", "vinci-agenda.sh", no_agent=False, prompt=prompt,
                           enabled=active)
        if self.set_parked(name, not active):
            print(f"• {subject.display}: {'archivada (gateway.parked)' if not active else 'reactivada'}")


def provision(cfg: BotConfig, *, hermes_bin: str | None = None) -> int:
    setup = Setup(cfg, hermes_bin=hermes_bin)
    setup.vinci()
    for subject in materias.load(cfg.core):
        if subject.state != "pendiente":
            setup.subject(subject)
    return 0
