#!/usr/bin/env python3
"""Warn when a change touches code whose docs did not change in the same branch.

Usage: python3 scripts/docs_check.py [--base origin/main]

It only warns (exit 0): a refactor can touch these files without changing anything a person
sees. The PR body's "Docs:" line says what was updated, or why nothing needed it.
"""
import argparse
import fnmatch
import subprocess

FEATURES = ".claude/skills/control-vinci/references/features/"
# (changed code, docs that cover it, README section to look at)
RULES = [
    (["src/espol_bot/whatsapp.py", "src/espol_bot/amigos.py", "src/espol_bot/relay.py", "relay/*",
      "hermes/plugins/vinci-whatsapp/*", "hermes/whatsapp/*"],
     ["README.md", FEATURES], "«Vinci en WhatsApp»"),
    (["src/espol_bot/token_form.py", "src/espol_bot/token_renewal.py", "docs/token/*"],
     ["README.md", FEATURES + "token.md"], "«Token nuevo desde Telegram»"),
    (["src/espol_bot/dashboard.py", "docs/dashboard/*"],
     ["README.md", FEATURES + "dashboard.md"], "«El dashboard de entregas»"),
    (["src/espol_bot/config.py", "src/aula_core/config.py"],
     ["config.toml", "secrets.env.example", "README.md"], "«Configuración»"),
    (["setup.sh"], ["README.md", "AGENTS.md"], "«Inicio rápido» / «Actualizar y desinstalar»"),
    (["src/espol_bot/cli.py", "src/aula/cli.py"],
     ["README.md", "AGENTS.md"], "«Desde la terminal y Claude Code» / «Solución de problemas»"),
    (["src/espol_bot/check.py"], [".claude/skills/control-vinci/SKILL.md"], None),
    (["src/espol_bot/*.py", "src/aula_core/*.py", "hermes/plugins/*"],
     ["README.md", FEATURES], "the section of the feature you changed"),
]


def changed(base: str) -> set[str]:
    def names(*args):
        out = subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout
        return set(filter(None, out.splitlines()))
    # Committed on the branch, plus staged, unstaged and new files not committed yet.
    return (names("diff", "--name-only", f"{base}...HEAD") | names("diff", "--name-only", "HEAD")
            | names("ls-files", "--others", "--exclude-standard"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    files = changed(ap.parse_args().base)
    claimed = set()
    warnings = []
    for code, docs, section in RULES:
        hits = sorted(f for f in files if f not in claimed and any(fnmatch.fnmatch(f, p) for p in code))
        if not hits:
            continue
        claimed.update(hits)
        if any(f == d or (d.endswith("/") and f.startswith(d)) for f in files for d in docs):
            continue
        where = f" (README {section})" if section and "README.md" in docs else ""
        warnings.append(f"⚠ {', '.join(hits)} changed, but none of: {', '.join(docs)}{where}")
    if warnings:
        print("\n".join(warnings))
        print("If no doc needed it, say why in the PR's \"Docs:\" line.")
    else:
        print("✅ every changed area has its docs in the change, or needs none")


if __name__ == "__main__":
    main()
