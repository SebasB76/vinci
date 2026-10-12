"""The E2E's shared plumbing, here and not in e2e/ so that pytest loads it before the session starts: one artifacts
folder per run (whichever process runs the tests, with pytest-xdist), each test's report and timings put together into
REPORTE.md and tiempos.md, and a trace page for a test that fails."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ARTIFACT = Path(os.environ.get("E2E_ARTIFACT_DIR") or REPO / "artifacts" / "e2e")
ORDER = ["test_canvas", "test_whatsapp_captain", "test_whatsapp_friend", "test_academico"]


def _controller(config) -> bool:
    return not hasattr(config, "workerinput")


def pytest_sessionstart(session):
    if _controller(session.config):
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
