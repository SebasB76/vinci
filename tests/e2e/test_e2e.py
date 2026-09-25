"""End-to-end run of the whole bot against a fake Canvas and a Telegram stub.

What it does, as real processes (the same commands Hermes cron and the captain run):
  1. setup.sh twice in a throwaway HOME, with the real Hermes CLI if installed
     (creates the bot's own profile there; proves the second run changes nothing).
  2. several `aula` CLI commands against the first fixture state.
  3. poll 1, then the fixtures change (new assignment, due-date change, new
     announcement, posted grade, new material, a submission), then poll 2 and 3.
  4. the 07:00 daily summary (twice: the second must not resend).
  5. retrieval: sample questions must hit the right file and page.

The artifact goes to artifacts/e2e/ (override with E2E_ARTIFACT_DIR). Ports and
temporary paths are normalized, so reruns produce the same files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from fake_servers import FakeCanvas, TelegramStub  # noqa: E402

CANVAS_TOKEN = "7~prueba-token-de-canvas"
BOT_TOKEN = "123456:PRUEBA-bot-token"
CAPTAIN_ID = "987654321"
VENV_BIN = Path(sys.executable).parent

# Timeline, America/Guayaquil (UTC-5)
T_SETUP = "2026-09-28T06:30:00-05:00"
T_POLL1 = "2026-09-28T07:40:00-05:00"   # Deber 2 vence 10:00 → recordatorio de 3 h
T_POLL2 = "2026-09-29T00:30:00-05:00"   # después de los cambios; Taller 2 vence en 22.5 h
T_POLL3 = "2026-09-29T01:00:00-05:00"   # sin cambios: no debe enviar nada
T_SUMMARY = "2026-09-29T07:00:00-05:00"
T_POLL4 = "2026-09-29T20:30:00-05:00"   # Taller 2 vence en 2.5 h → recordatorio de 3 h

QUESTIONS = [
    ("¿Qué es la regla de la cadena?", "Capítulo 3 - Derivadas.pdf", 2),
    ("explícame el movimiento parabólico", "Semana 2 - Cinemática.pptx", 3),
    ("ejercicio 4 maximizar el área del rectángulo", "Capítulo 3 - Derivadas.pdf", 3),
]


def find_hermes() -> str | None:
    for candidate in (os.environ.get("HERMES_BIN"), str(Path.home() / ".local/bin/hermes"), shutil.which("hermes")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def test_e2e(tmp_path):
    artifact = Path(os.environ.get("E2E_ARTIFACT_DIR") or REPO / "artifacts" / "e2e")
    shutil.rmtree(artifact, ignore_errors=True)
    artifact.mkdir(parents=True)
    hermes = find_hermes()
    home = tmp_path / "home"
    home.mkdir()
    data_dir = tmp_path / "datos"

    with FakeCanvas(CANVAS_TOKEN) as canvas, TelegramStub(BOT_TOKEN) as telegram:
        config = REPO.joinpath("config.toml").read_text(encoding="utf-8")
        config = config.replace('url = "https://aulavirtual.espol.edu.ec"', f'url = "{canvas.base}"')
        config = config.replace('carpeta_datos = "~/.local/share/espol-academic-bot"', f'carpeta_datos = "{data_dir}"')
        config_file = tmp_path / "config.toml"
        config_file.write_text(config, encoding="utf-8")
        secrets = tmp_path / "secrets.env"
        secrets.write_text(f"CANVAS_TOKEN={CANVAS_TOKEN}\nTELEGRAM_BOT_TOKEN={BOT_TOKEN}\nTELEGRAM_USER_ID={CAPTAIN_ID}\n")

        def normalize(text: str) -> str:
            text = text.replace(canvas.base, "https://aulavirtual.test").replace(telegram.base, "https://telegram.test")
            text = text.replace(str(data_dir), "<datos>").replace(str(home), "<home>").replace(str(tmp_path), "<tmp>")
            return text.replace(str(REPO), "<repo>").replace(str(VENV_BIN), "<repo>/.venv/bin")

        base_env = {k: v for k, v in os.environ.items() if not k.startswith(("AULA_", "HERMES_HOME"))}
        base_env.update({
            "AULA_CONFIG": str(config_file), "AULA_SECRETS": str(secrets),
            "ESPOL_TELEGRAM_API_BASE": telegram.base, "PYTHONUNBUFFERED": "1",
        })

        def run(args, now, *, env_extra=None, check=True):
            env = {**base_env, "AULA_NOW": now, **(env_extra or {})}
            proc = subprocess.run(args, env=env, capture_output=True, text=True, cwd=REPO, timeout=300)
            if check:
                assert proc.returncode == 0, f"{args} falló ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
            return proc

        sent_log: list[tuple[str, dict]] = []

        def take(label: str) -> list[dict]:
            with telegram.lock:
                new = telegram.messages[len(sent_log):]
            sent_log.extend((label, m) for m in new)
            return new

        # 1. setup.sh, twice, in an isolated HOME (never the real ~/.hermes) --------------
        setup_report = []
        if hermes:
            setup_env = {"HOME": str(home), "HERMES_BIN": hermes}
            first = run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_SETUP, env_extra=setup_env)
            second = run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_SETUP, env_extra=setup_env)
            (artifact / "setup.log").write_text(normalize(
                "$ ./setup.sh --skip-deps   # 1ª vez\n" + first.stdout + first.stderr +
                "\n$ ./setup.sh --skip-deps   # 2ª vez (idempotente)\n" + second.stdout + second.stderr), encoding="utf-8")
            profile = home / ".hermes" / "profiles" / "espol"
            jobs = json.loads((profile / "cron" / "jobs.json").read_text())["jobs"]
            assert sorted(j["name"] for j in jobs) == ["espol-resumen", "espol-sondeo"], jobs
            by_name = {j["name"]: j for j in jobs}
            assert by_name["espol-sondeo"]["schedule_display"] == "every 30m"
            assert by_name["espol-resumen"]["schedule"]["expr"] == "0 7 * * *" or \
                by_name["espol-resumen"]["schedule_display"] == "0 7 * * *"
            assert all(j["no_agent"] and j["deliver"] == f"telegram:{CAPTAIN_ID}" for j in jobs)
            assert "sin cambios" in second.stdout and "creado" not in second.stdout
            env_file = (profile / ".env").read_text()
            assert f"TELEGRAM_ALLOWED_USERS={CAPTAIN_ID}" in env_file and f"TELEGRAM_BOT_TOKEN={BOT_TOKEN}" in env_file
            profile_config = (profile / "config.yaml").read_text()
            assert "timezone: America/Guayaquil" in profile_config and "provider: anthropic" in profile_config
            skill = (profile / "skills" / "espol" / "espol-academico" / "SKILL.md").read_text()
            assert str(VENV_BIN / "aula") in skill
            assert (home / ".local" / "bin" / "aula").is_file()
            assert (home / ".claude" / "skills" / "aula" / "SKILL.md").is_file()
            assert not (home / ".hermes" / "config.yaml").exists(), "setup no debe crear config del perfil por defecto"
            setup_report.append(f"setup.sh x2 con Hermes real en HOME aislado: perfil «espol», "
                                f"{len(jobs)} cron no-agent, segunda corrida sin cambios")
            take("setup.sh (mensaje de prueba)")
        else:
            (artifact / "setup.log").write_text("Hermes no está instalado aquí: se omitió la prueba de setup.sh.\n")
            setup_report.append("setup.sh omitido: Hermes no está instalado en esta máquina")

        # 2. aula CLI against state 1 -----------------------------------------------------
        aula = str(VENV_BIN / "aula")
        cli_runs = [
            ["cursos"],
            ["tareas"],
            ["tareas", "--curso", "calculo", "--json"],
            ["anuncios", "--curso", "fisica"],
            ["notas"],
            ["archivos"],
            ["archivos", "bajar", "5001", "--json"],
            ["archivos", "leer", "5001", "--paginas", "2"],
        ]
        cli_md = ["# Salida del comando `aula` (estado 1 del aula virtual)\n"]
        cli_json = {}
        for args in cli_runs:
            proc = run([aula, *args], T_SETUP)
            cli_md.append(f"## `aula {' '.join(args)}`\n\n```\n{normalize(proc.stdout).rstrip()}\n```\n")
            if "--json" in args:
                cli_json[" ".join(args)] = json.loads(proc.stdout)
        tareas = cli_json["tareas --curso calculo --json"]
        assert [t["tarea"] for t in tareas] == ["Deber 2: Continuidad", "Taller 3: Derivadas"]
        bajado = cli_json["archivos bajar 5001 --json"][0]
        assert bajado["indexado"] == "ok" and Path(bajado["ruta_local"]).is_file()
        assert "MATG1049-5" in bajado["ruta_local"]
        assert take("aula CLI") == [], "la CLI nunca envía mensajes"

        # 3. polls -----------------------------------------------------------------------
        bot = str(VENV_BIN / "espol-bot")
        run([bot, "sondeo"], T_POLL1)
        poll1 = take("Sondeo 1 · lun 28 sep 07:40")
        assert len(poll1) == 2, poll1
        assert "Listo" in poll1[0]["text"] and "Recordatorio" in poll1[1]["text"] and "Deber 2" in poll1[1]["text"]

        canvas.state = "state2"
        run([bot, "sondeo"], T_POLL2)
        poll2 = take("Sondeo 2 · mar 29 sep 00:30 (tras los cambios)")
        texts = "\n\n".join(m["text"] for m in poll2)
        for expected in ("Nueva tarea en FÍSICA I", "Taller 2: Movimiento parabólico", "Cambió la fecha de entrega",
                         "Nuevo anuncio en CÁLCULO", "Cambio de fecha del Taller 3", "Nota publicada",
                         "Tarea 1: Vectores", "9/10", "Nuevo material en FÍSICA I", "Ya lo leí",
                         "Recordatorio", "vence en 22 h"):
            assert expected in texts, f"falta «{expected}» en el sondeo 2:\n{texts}"
        assert len(poll2) == 6, [m["text"][:40] for m in poll2]

        run([bot, "sondeo"], T_POLL3)
        assert take("Sondeo 3 · mar 29 sep 01:00 (sin cambios)") == [], "no debe repetir avisos"

        # 4. daily summary -----------------------------------------------------------------
        run([bot, "resumen"], T_SUMMARY)
        summary = take("Resumen diario · mar 29 sep 07:00")
        assert len(summary) == 1 and "Resumen de tu semana" in summary[0]["text"]
        for expected in ("Taller 2: Movimiento parabólico", "Taller 3: Derivadas", "Examen parcial",
                         "Informe de laboratorio 1", "Ya entregaste 1", "Cambio de fecha del Taller 3"):
            assert expected in summary[0]["text"], f"falta «{expected}» en el resumen"
        run([bot, "resumen"], T_SUMMARY)
        assert take("Resumen diario repetido") == [], "el resumen se envía una vez al día"

        run([bot, "sondeo"], T_POLL4)
        poll4 = take("Sondeo 4 · mar 29 sep 20:30")
        assert len(poll4) == 1 and "Taller 2" in poll4[0]["text"] and "vence en 2 h" in poll4[0]["text"]

        # 5. retrieval -------------------------------------------------------------------
        retrieval = []
        for question, expected_file, expected_page in QUESTIONS:
            hits = json.loads(run([aula, "buscar", question, "--json"], T_SUMMARY).stdout)
            top = hits[0] if hits else {}
            ok = top.get("archivo") == expected_file and top.get("pagina") == expected_page
            retrieval.append({
                "pregunta": question, "esperado": {"archivo": expected_file, "pagina": expected_page},
                "ok": ok, "resultados": [{k: h[k] for k in ("archivo", "unidad", "pagina", "curso", "fragmento", "url")}
                                         for h in hits[:3]],
            })
            assert ok, f"{question!r}: esperaba {expected_file} p.{expected_page}, obtuve {top}"
        run_cli_after = run([aula, "buscar", QUESTIONS[0][0]], T_SUMMARY)
        cli_md.append(f"## `aula buscar \"{QUESTIONS[0][0]}\"`\n\n```\n{normalize(run_cli_after.stdout).rstrip()}\n```\n")
        pend = run([aula, "tareas", "--dias", "7", "--sin-actualizar"], T_SUMMARY)
        cli_md.append(f"## `aula tareas --dias 7` (después de los cambios)\n\n```\n{normalize(pend.stdout).rstrip()}\n```\n")

        # Safety: read-only, captain-only --------------------------------------------------
        methods = {m for m, _ in canvas.requests}
        assert methods == {"GET"}, f"hubo solicitudes que no son GET: {methods}"
        assert canvas.throttled, "el 429 de prueba debió ocurrir"
        assert any("page=2" in p for _, p in canvas.requests), "debió seguir la paginación"
        assert all(str(m["chat_id"]) == CAPTAIN_ID for _, m in sent_log), "solo se escribe al capitán"
        assert not any("5002" in p and "download" in p for _, p in canvas.requests), "archivo enorme no se baja"

    # Artifact ------------------------------------------------------------------------------
    notif = ["# Mensajes de Telegram capturados (en orden)\n",
             "Cada bloque es un `sendMessage` tal como lo envió el bot (HTML de Telegram).\n"]
    current = None
    for label, message in sent_log:
        if label != current:
            notif.append(f"\n## {label}\n")
            current = label
        notif.append(f"```html\n{normalize(message['text'])}\n```\n")
    (artifact / "notificaciones.md").write_text("\n".join(notif), encoding="utf-8")
    (artifact / "resumen_diario.txt").write_text(normalize(summary[0]["text"]) + "\n", encoding="utf-8")
    (artifact / "recuperacion.json").write_text(normalize(json.dumps(retrieval, ensure_ascii=False, indent=2)) + "\n",
                                               encoding="utf-8")
    (artifact / "cli.md").write_text("\n".join(cli_md), encoding="utf-8")
    requests_log = "\n".join(f"{m} {re.sub(r'verifier=[^&]+', 'verifier=…', p)}" for m, p in canvas.requests)
    (artifact / "canvas_requests.log").write_text(requests_log + "\n", encoding="utf-8")
    counts = {label: sum(1 for l, _ in sent_log if l == label) for label in dict.fromkeys(l for l, _ in sent_log)}
    report = [
        "# Reporte E2E: bot académico ESPOL\n",
        "Resultado: **todas las verificaciones pasaron**.\n",
        *[f"- {line}" for line in setup_report],
        f"- Canvas falso: {len(canvas.requests)} solicitudes, todas GET; paginación seguida; un 429 con reintento; "
        "Física con la pestaña Archivos oculta (material encontrado vía Módulos).",
        *[f"- {label}: {n} mensaje(s)" for label, n in counts.items()],
        "- Sondeo 3 y el resumen repetido no enviaron nada (sin duplicados).",
        *[f"- Recuperación «{r['pregunta']}» → {r['resultados'][0]['archivo']}, "
          f"{r['resultados'][0]['unidad']} {r['resultados'][0]['pagina']} ✓" for r in retrieval],
        "\nArchivos: `notificaciones.md`, `resumen_diario.txt`, `recuperacion.json`, `cli.md`, "
        "`canvas_requests.log`, `setup.log`.\n",
    ]
    (artifact / "REPORTE.md").write_text("\n".join(report), encoding="utf-8")
