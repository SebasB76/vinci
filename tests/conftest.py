"""The E2E's shared plumbing, here and not in e2e/ so that pytest loads it before the session starts: one artifacts
folder per run (whichever process runs the tests, with pytest-xdist), each test's report and timings put together into
REPORTE.md and tiempos.md, and a trace page for a test that fails."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ARTIFACT = Path(os.environ.get("E2E_ARTIFACT_DIR") or REPO / "artifacts" / "e2e")
ORDER = ["test_canvas", "test_whatsapp_captain", "test_whatsapp_friend", "test_academico"]
LAST_RUN = REPO / "artifacts" / ".e2e-last-run"
# changed lines since the last run that still count as a one-line fix
SMALL_FIX = 3


def _controller(config) -> bool:
    return not hasattr(config, "workerinput")


def _git(*args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=REPO, env=env, capture_output=True, text=True, check=True).stdout.strip()


def _snapshot() -> str:
    """The working tree, untracked files included, as a git tree id, without touching the real index."""
    with tempfile.TemporaryDirectory() as tmp:
        index = Path(tmp) / "index"
        real = REPO / _git("rev-parse", "--git-path", "index")
        if real.exists():
            shutil.copy(real, index)
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        _git("add", "-A", env=env)
        return _git("write-tree", env=env)


def _changed_lines(old: str, new: str) -> int:
    rows = (line.split("\t", 2) for line in _git("diff", "--numstat", old, new).splitlines())
    return sum(100 if added == "-" else int(added) + int(deleted) for added, deleted, _ in rows)


def _guard_e2e_run() -> None:
    """AGENTS.md's E2E rule, enforced: no baseline run, no rerun without a change, none for a one-line fix."""
    if os.environ.get("E2E_FORCE", "").strip():
        return
    try:
        tree = _snapshot()
        base = _git("merge-base", "origin/main", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        return  # not a git checkout, or no origin/main: nothing to compare against
    refusal = None
    if not _changed_lines(base, tree):
        refusal = "esta copia no cambia nada frente a main. No lo corras al empezar ni para ver la línea base."
    elif LAST_RUN.exists():
        try:
            since = _changed_lines(LAST_RUN.read_text().strip(), tree)
        except subprocess.CalledProcessError:
            since = None  # git pruned the last run's tree
        if since == 0:
            refusal = ("nada cambió desde la última corrida. Si falló, lee artifacts/e2e/fallo-*.md y corrige "
                       "antes de repetir.")
        elif since is not None and since <= SMALL_FIX:
            refusal = (f"solo {since} línea(s) cambiaron desde la última corrida. Un arreglo así no vuelve a "
                       "correr el E2E: abre el PR.")
    if refusal:
        pytest.exit(f"E2E rechazado: {refusal}\nSi el capitán lo pidió: E2E_FORCE=\"<motivo>\" uv run pytest",
                    returncode=pytest.ExitCode.USAGE_ERROR)
    LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN.write_text(tree)


def pytest_sessionstart(session):
    if _controller(session.config):
        if not session.config.option.collectonly:
            _guard_e2e_run()
        shutil.rmtree(ARTIFACT, ignore_errors=True)
        (ARTIFACT / "partes").mkdir(parents=True)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    world = getattr(item.module, "TRACE", {}).get("world")
    crash = getattr(report.longrepr, "reprcrash", None)
    where = f"{Path(crash.path).name}:{crash.lineno}" if crash else item.name
    page = [f"# {item.name} falló en {where}\n", "Léelo antes de volver a correr nada.\n", "## El error\n", "```",
            (crash.message if crash else str(report.longreprtext))[-4000:], "```\n"]
    if world is not None:
        page.append(item.module.trace_page(world))
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    (ARTIFACT / f"fallo-{item.name}.md").write_text("\n".join(page), encoding="utf-8")


def pytest_sessionfinish(session, exitstatus):
    parts = ARTIFACT / "partes"
    if not _controller(session.config) or not parts.is_dir():
        return
    names = ORDER + sorted({p.name.split(".")[0] for p in parts.glob("*.md")} - set(ORDER))
    failed = sorted(p.name for p in ARTIFACT.glob("fallo-*.md"))
    result = ("**todas las verificaciones pasaron**" if exitstatus == 0 and not failed else
              "**hubo fallas**: " + (", ".join(f"`{name}`" for name in failed) or "mira la salida de pytest"))
    report = ["# Reporte E2E: Vinci en WhatsApp (ESPOL)\n", f"Resultado: {result}.\n"]
    report += [(parts / f"{name}.md").read_text(encoding="utf-8") for name in names if (parts / f"{name}.md").exists()]
    (ARTIFACT / "REPORTE.md").write_text("\n".join(report), encoding="utf-8")
    times = ["# Tiempos del E2E\n", "Dónde espera cada prueba, por línea de test_e2e.py, de la más lenta a la más "
             "rápida. Las pruebas corren en paralelo: la corrida dura lo que la más lenta.\n"]
    times += [(parts / f"{name}.tiempos.md").read_text(encoding="utf-8") for name in names
              if (parts / f"{name}.tiempos.md").exists()]
    (ARTIFACT / "tiempos.md").write_text("\n".join(times), encoding="utf-8")
