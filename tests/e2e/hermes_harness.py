"""Running the real Hermes Agent inside the E2E test's throwaway HOME.

find_hermes() picks the Hermes CLI to use. `~/.local/bin/hermes` is a launcher that resolves its packages under
~/.hermes, which is exactly what a temporary HOME hides, so the test prefers HERMES_BIN, then the self-contained venv
recorded in ~/.hermes/installs/*/facts.json (read only; nothing under the real ~/.hermes is ever written).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


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


def bundled_locales(hermes: str) -> str | None:
    """The locales/ of the Hermes source tree, when the self-contained venv's own copy of the tree (its workspace/)
    has none: without it every message Hermes writes itself is its catalog key («gateway.voice.…»)."""
    workspace = Path(hermes).resolve().parents[2] / "workspace"
    source = Path.home() / ".hermes" / "hermes-agent" / "locales"
    if workspace.is_dir() and not (workspace / "locales").is_dir() and source.is_dir():
        return str(source)
    return None


def _works(hermes: str, scratch_home: Path) -> bool:
    try:
        proc = subprocess.run([hermes, "--version"], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "HOME": str(scratch_home), "PYTHONDONTWRITEBYTECODE": "1"})
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0
