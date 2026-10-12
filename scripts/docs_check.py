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
GUIDE = "docs/guia/"
# (changed code, docs that cover it, guide section to look at)
RULES = [
    (["src/espol_bot/whatsapp.py", "src/espol_bot/amigos.py", "src/espol_bot/relay.py", "relay/*",
      "hermes/plugins/vinci-whatsapp/*", "hermes/whatsapp/*"],
     [GUIDE + "whatsapp.md", FEATURES], "whatsapp.md"),
    (["src/espol_bot/token_form.py", "src/espol_bot/token_renewal.py", "docs/token/*"],
     [GUIDE + "uso.md", GUIDE + "whatsapp.md", FEATURES + "token.md"], "uso.md «Token nuevo desde Telegram»"),
    (["src/espol_bot/portal_login.py", "src/espol_bot/academic_portal.py", "docs/academico/*"],
     [GUIDE + "uso.md", FEATURES + "academico.md"], "uso.md «Tu Académico de ESPOL»"),
    (["src/espol_bot/dashboard.py", "docs/dashboard/*"],
     [GUIDE + "uso.md", FEATURES + "dashboard.md"], "uso.md «El dashboard de entregas»"),
    (["src/espol_bot/config.py", "src/aula_core/config.py"],
     ["config.toml", "secrets.env.example", GUIDE + "instalacion.md"], "instalacion.md «Configuración»"),
    (["setup.sh"], [GUIDE + "instalacion.md", "AGENTS.md"], "instalacion.md «5. Corre el setup» / «Actualizar y desinstalar»"),
    (["src/espol_bot/cli.py", "src/aula/cli.py"],
     [GUIDE + "terminal.md", GUIDE + "problemas.md", "AGENTS.md"], "terminal.md / problemas.md"),
    (["src/espol_bot/check.py"], [".claude/skills/control-vinci/SKILL.md"], None),
    (["src/espol_bot/*.py", "src/aula_core/*.py", "hermes/plugins/*"],
     ["README.md", GUIDE, FEATURES], "the section of the feature you changed"),
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
        where = f" (look at {section})" if section else ""
        warnings.append(f"⚠ {', '.join(hits)} changed, but none of: {', '.join(docs)}{where}")
    if warnings:
        print("\n".join(warnings))
        print("If no doc needed it, say why in the PR's \"Docs:\" line.")
    else:
        print("✅ every changed area has its docs in the change, or needs none")


if __name__ == "__main__":
    main()
