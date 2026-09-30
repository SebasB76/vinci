"""Install check: does each bot's SKILL reach the model?

Hermes ignores `skills.auto_load` unless the agent has one of the skills toolset's tools, and it says
nothing when it does. This builds, offline (no model call, no Telegram message), the system prompt a
fresh chat session would store and fails when a line of the bot's SKILL is missing from it. (Cron agent runs
never get `auto_load`: the agent job carries its skill with `--skill`.)
It runs Hermes' own inspection agent (what `hermes prompt-size` uses) with the profile as HERMES_HOME.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

PLATFORMS = ("telegram",)
SKILL_TOOLS = {"skills_list", "skill_view", "skill_manage"}

_INSPECT = """
import json, sys
if {agent_dir!r}:
    sys.path.insert(0, {agent_dir!r})
import hermes_bootstrap
from hermes_cli.prompt_size import _build_inspection_agent
from agent.system_prompt import build_system_prompt
out = {{}}
for platform in {platforms!r}:
    agent = _build_inspection_agent(platform)
    out[platform] = {{"prompt": build_system_prompt(agent), "tools": sorted(agent.valid_tool_names)}}
print(json.dumps(out))
"""


class Unavailable(Exception):
    """The inspection itself could not run (Hermes internals moved): not a verdict on the profile."""


def skill_lines(skill_md: str, soul: str) -> list[str]:
    """The lines only the SKILL carries: no frontmatter, no HTML comments, nothing SOUL.md repeats."""
    body = re.sub(r"\A---\n.*?\n---\n", "", skill_md, flags=re.DOTALL)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    in_soul = {line.strip() for line in soul.splitlines()}
    return [line.strip() for line in body.splitlines() if line.strip() and line.strip() not in in_soul]


def _interpreters(hermes: str, env: dict) -> list[tuple[str, str | None]]:
    """(python, hermes checkout to put on sys.path) pairs that may import Hermes: a venv install's own python,
    then the runtime a git install's launcher reports."""
    found: list[tuple[str, str | None]] = []
    sibling = Path(hermes).resolve().parent / "python3"
    if sibling.exists():
        found.append((str(sibling), None))
    try:
        command = json.loads(subprocess.run([hermes, "--print-runtime-command"], env=env, capture_output=True,
                                            text=True, check=True, stdin=subprocess.DEVNULL, timeout=120).stdout)
        found.append((command[0], re.search(r"sys\.path\.insert\(0, '([^']+)'\)", command[-1])[1]))
    except (OSError, ValueError, TypeError, IndexError, subprocess.SubprocessError):
        pass
    return found


def inspect_profile(hermes: str, profile: Path) -> dict[str, dict]:
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
    error = "no Hermes interpreter found"
    for python, agent_dir in _interpreters(hermes, env):
        try:
            proc = subprocess.run([python, "-I", "-c", _INSPECT.format(agent_dir=agent_dir, platforms=PLATFORMS)],
                                  env={**env, "HERMES_HOME": str(profile)}, capture_output=True, text=True,
                                  check=True, stdin=subprocess.DEVNULL, timeout=300)
            return json.loads(proc.stdout.splitlines()[-1])
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as exc:
            detail = str(getattr(exc, "stderr", None) or exc).strip()
            error = detail.splitlines()[-1] if detail else repr(exc)
    raise Unavailable(error)


def problems(inspected: dict[str, dict], lines: list[str]) -> list[str]:
    found = []
    for platform in PLATFORMS:
        seen = inspected.get(platform) or {}
        if not SKILL_TOOLS & set(seen.get("tools") or []):
            found.append(f"{platform}: the agent has no skills tool, so Hermes drops skills.auto_load")
        prompt_lines = {line.strip() for line in (seen.get("prompt") or "").splitlines()}
        missing = [line for line in lines if line not in prompt_lines]
        if missing:
            found.append(f"{platform}: {len(missing)} of {len(lines)} SKILL lines are not in the prompt, "
                         f"e.g. «{missing[0][:80]}»")
    return found
