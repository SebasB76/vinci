"""Running the real Hermes Agent inside the E2E test's throwaway HOME.

- find_hermes(): the Hermes CLI to use. `~/.local/bin/hermes` is a launcher that resolves
  its packages under ~/.hermes, which is exactly what a temporary HOME hides, so the test
  prefers HERMES_BIN, then the self-contained venv recorded in ~/.hermes/installs/*/facts.json
  (read only; nothing under the real ~/.hermes is ever written).
- telegram_support(): python-telegram-bot, which Hermes needs for its Telegram adapter and
  for cron delivery, installed into a temporary folder that goes on PYTHONPATH (never into
  Hermes' own venv), plus a `sitecustomize` that points every python-telegram-bot `Bot` at
  the fake Bot API. Hermes' gateway already honors `platforms.telegram.extra.base_url`, but
  its standalone cron sender always uses api.telegram.org: with this hook nothing in the
  test can reach the real Telegram.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

SITECUSTOMIZE = '''\
# E2E only: every python-telegram-bot Bot talks to the fake Bot API, never api.telegram.org.
import importlib.abc, importlib.util, os, sys

_BASE = os.environ.get("E2E_TELEGRAM_API")
_DEFAULTS = {"base_url": ("https://api.telegram.org/bot", 1), "base_file_url": ("https://api.telegram.org/file/bot", 2)}


def _patch(module):
    init = module.Bot.__init__

    def __init__(self, *args, **kwargs):
        args = list(args)
        for key, (default, index) in _DEFAULTS.items():
            new = _BASE + default[len("https://api.telegram.org"):]
            if len(args) > index:
                if args[index] in (None, default):
                    args[index] = new
            elif kwargs.get(key) in (None, default):
                kwargs[key] = new
        init(self, *args, **kwargs)

    module.Bot.__init__ = __init__


class _Hook(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "telegram._bot":
            return None
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        run = spec.loader.exec_module

        def exec_module(module):
            run(module)
            _patch(module)

        spec.loader.exec_module = exec_module
        return spec


if _BASE:
    sys.meta_path.insert(0, _Hook())
'''


def find_hermes(scratch_home: Path) -> str | None:
    candidates = [os.environ.get("HERMES_BIN")]
    for facts in sorted(Path.home().glob(".hermes/installs/*/facts.json")):
        try:
            env = json.loads(facts.read_text(encoding="utf-8"))["packages"]["venv"]["environment"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        candidates.append(str(Path(env) / "bin" / "hermes"))
    candidates += [str(Path.home() / ".local/bin/hermes"), shutil.which("hermes")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK) and _works(candidate, scratch_home):
            return candidate
    return None


def _works(hermes: str, scratch_home: Path) -> bool:
    try:
        proc = subprocess.run([hermes, "--version"], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "HOME": str(scratch_home), "PYTHONDONTWRITEBYTECODE": "1"})
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def hermes_python(hermes: str) -> Path | None:
    python = Path(hermes).resolve().parent / "python3"
    return python if python.exists() else None


def telegram_support(hermes: str, target: Path) -> Path | None:
    """A PYTHONPATH folder with python-telegram-bot (the version Hermes pins) and the hook."""
    python = hermes_python(hermes)
    if python is None:
        return None
    probe = subprocess.run([str(python), "-c", "import telegram; print(telegram.__version__)"],
                           capture_output=True, text=True)
    target.mkdir(parents=True, exist_ok=True)
    (target / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    if probe.returncode == 0:
        return target
    pyproject = python.parents[1].parent / "workspace" / "pyproject.toml"
    match = re.search(r'"python-telegram-bot(?:\[[^\]]*\])?==([\d.]+)"',
                      pyproject.read_text(encoding="utf-8") if pyproject.exists() else "")
    spec = f"python-telegram-bot=={match[1]}" if match else "python-telegram-bot"
    installer = ([shutil.which("uv"), "pip", "install", "--quiet", "--python", str(python)] if shutil.which("uv")
                 else [str(python), "-m", "pip", "install", "--quiet"])
    proc = subprocess.run([*installer, "--no-deps", "--target", str(target), spec], capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    check = subprocess.run([str(python), "-c", "import telegram.ext"], capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": str(target)})
    return target if check.returncode == 0 else None
