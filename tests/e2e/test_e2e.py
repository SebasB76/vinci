"""End-to-end run of Vinci and its subject bots against a fake Canvas, a fake Telegram and
a scripted LLM, with the real Hermes Agent when it is installed.

Everything runs as real processes (the same commands Hermes cron, the gateway and the
captain run) in a throwaway HOME with its own XDG folders and no D-Bus session: the real
~/.hermes, ~/.claude, ~/.local and user services are never touched.

  1. setup.sh twice: a legacy «espol» profile becomes Vinci with its memory; the second
     run changes nothing.
  2. `aula` CLI commands against the first fixture state.
  3. Vinci's polls, then the fixtures change (new assignment, due-date change, new
     announcement, posted grade, new material, a submission), then polls 2-4 and the 07:00
     summary (twice: the second must not resend).
  4. retrieval: sample questions must hit the right file and page.
  5. a fresh install where two resources fail at different polls: the rest keeps working,
     one alert per failure episode and resource.
  6-7. the real Hermes gateway serving Vinci over the fake Telegram. The aula uses ESPOL's
     real course codes and names, and Cálculo has a theory and a práctico course
     (`Paralelo5_MATG1049`, `Paralelo105_MATG1049`): one subject, one bot. Vinci builds the team
     from chat: its card's «Crear» buttons; Cálculo created as a Telegram managed bot (its
     token fetched with getManagedBotToken), Física from BotFather's forwarded reply (caught,
     deleted, never seen by the model; a repeated, an unknown and a stranger's token handled).
     Then, with both subject bots served by the same gateway: strangers get silence; the
     schedule read from a screenshot is saved only by the
     captain's «Guardar» (a stranger's press and a stale proposal are refused); a photo
     routed to Cálculo, an unknown subject refused; an alert's button and a reply to an
     alert handed to the subject bots (alerts of both Cálculo courses go to its one bot);
     the brief 30 minutes before Wednesday's class, with what is due in both courses;
     notebook capture of a photo, a voice note and a doubt (and no arbitrary files);
     Vinci reading notebooks but unable to write them or reach a terminal; Física
     archived from Vinci's card and the gateway restarted: no repeated brief, Física
     offline; reactivated from Vinci's card, the same gateway serves it again.
  8. setup.sh a third time with the team in place: nothing changes.

The artifact goes to artifacts/e2e/ (override with E2E_ARTIFACT_DIR). Ports and
temporary paths are normalized, so reruns produce comparable files.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from aula_core.config import parse_env_file

HERE = Path(__file__).parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from fake_servers import FakeCanvas, FakeTelegram, ScriptedLLM  # noqa: E402
from hermes_harness import find_hermes, telegram_support  # noqa: E402

CANVAS_TOKEN = "7~prueba-token-de-canvas"
BOT_TOKEN = "123456:PRUEBA-bot-token"
SUBJECT_TOKENS = {"MATG1049": "700001:PRUEBA-token-de-calculo-xxxxxxxxxxxxxxxx",
                  "FISG1002": "700002:PRUEBA-token-de-fisica-xxxxxxxxxxxxxxxxx"}
UNKNOWN_TOKEN = "700009:PRUEBA-token-que-no-existe-xxxxxxxxxxxx"
STRANGER_TOKEN = "700008:PRUEBA-token-de-un-extrano-xxxxxxxxxxxx"
BOTFATHER_REPLY = ("Done! Congratulations on your new bot. You will find it at t.me/vinci_fisica_bot. You can now "
                   "add a description.\n\nUse this token to access the HTTP API:\n{token}\nKeep your token secure "
                   "and store it safely, it can be used by anyone to control your bot.")
MATG, FIS = SUBJECT_TOKENS["MATG1049"], SUBJECT_TOKENS["FISG1002"]
USERNAMES = {BOT_TOKEN: "vinci_bot", MATG: "vinci_calculo_bot", FIS: "vinci_fisica_bot"}
CAPTAIN_ID = "987654321"
CAPTAIN = int(CAPTAIN_ID)
STRANGER = 5550001
VENV_BIN = Path(sys.executable).parent
FILES = HERE / "fixtures" / "files"
MARKER = "Generado por setup.sh de espol-academic-bot"
SKIP = '{"wakeAgent": false}'

# Timeline, America/Guayaquil (UTC-5)
T_SETUP = "2026-09-28T06:30:00-05:00"
T_POLL1 = "2026-09-28T07:40:00-05:00"   # Deber 2 vence 10:00 → recordatorio de 3 h
T_POLL2 = "2026-09-29T00:30:00-05:00"   # después de los cambios; Taller 2 vence en 22.5 h
T_POLL3 = "2026-09-29T01:00:00-05:00"   # sin cambios: no debe enviar nada
T_SUMMARY = "2026-09-29T07:00:00-05:00"
T_POLL4 = "2026-09-29T20:30:00-05:00"   # Taller 2 vence en 2.5 h → recordatorio de 3 h
T_RESILIENCE = [f"2026-09-30T{12 + i // 2}:{i % 2 * 30:02d}:00-05:00" for i in range(9)]  # 12:00 … 16:00
T_VINCI = "2026-09-30T08:30:00-05:00"   # sesión del gateway: miércoles, 30 min antes de Cálculo (09:00)
T_EARLY = "2026-09-30T08:29:00-05:00"   # un minuto antes: todavía no toca el brief

QUESTIONS = [
    ("¿Qué es la regla de la cadena?", "Capítulo 3 - Derivadas.pdf", 2),
    ("explícame el movimiento parabólico", "Semana 2 - Cinemática.pptx", 3),
    ("ejercicio 4 maximizar el área del rectángulo", "Capítulo 3 - Derivadas.pdf", 3),
]

# What the model "reads" from the screenshot: the first time with one mistake (Wednesday's
# Cálculo at 10:00), then corrected by the captain. Cálculo's práctico keeps the screenshot's label.
SCHEDULE_V1 = [
    {"materia": "MATG1049", "dia": "lunes", "inicio": "09:00", "fin": "11:00", "aula": "A105", "paralelo": "5"},
    {"materia": "MATG1049", "dia": "miércoles", "inicio": "10:00", "fin": "12:00", "aula": "A105", "paralelo": "5"},
    {"materia": "MATG1049 - CÁLCULO DE UNA VARIABLE Paralelo N°105", "dia": "viernes", "inicio": "10:00",
     "fin": "12:00", "aula": "LAB 11C", "paralelo": "105"},
    {"materia": "FISG1002", "dia": "martes", "inicio": "14:30", "fin": "16:30", "aula": "L204", "paralelo": "3"},
    {"materia": "FISG1002", "dia": "jueves", "inicio": "14:30", "fin": "16:30", "aula": "L204", "paralelo": "3"},
]
SCHEDULE_V2 = [dict(c, inicio="09:00", fin="11:00") if c["dia"] == "miércoles" else c for c in SCHEDULE_V1]

VINCI_TOOLS_OK = {"web_search", "web_extract", "memory", "session_search", "clarify"}
SUBJECT_TOOLS_OK = {"memory", "session_search", "clarify"}

IMAGE_RE = re.compile(r"\[Image attached at: ([^\]]+)\]")
VOICE_RE = re.compile(r"(?:voice message: |audio is available at: )([^\s\]]+)")
REPLY_RE = re.compile(r'\[Replying to[^:]*: "(.+?)"\]', re.S)


# -- the model's side ------------------------------------------------------------------------


def flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def bot_of(req: dict) -> str | None:
    """Which bot a request comes from: its SOUL.md («Eres **Vinci · Física I**…»)."""
    messages = req.get("messages") or []
    for role in ("system", None):
        text = "\n".join(flatten(m.get("content")) for m in messages if role is None or m.get("role") == role)
        match = re.search(r"Eres \*\*(Vinci(?: · [^*]+)?)\*\*", text)
        if match:
            return match[1]
    return None


def tools_of(req: dict) -> list[str]:
    return sorted(t["function"]["name"] for t in req.get("tools") or [])


# Hermes hands every MCP tool result to the model as data, inside this envelope.
UNTRUSTED = re.compile(r'^<untrusted_tool_result source="[^"]*">\n.*?\n\n(.*)\n</untrusted_tool_result>$', re.S)


def _json(raw: str):
    if isinstance(raw, str) and (wrapped := UNTRUSTED.match(raw)):
        raw = wrapped[1]
    for _ in range(2):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return raw
        if isinstance(raw, dict) and set(raw) <= {"result", "content"} and isinstance(raw.get("result"), str):
            raw = raw["result"]
            continue
        return raw
    return raw


def _problem(raw: str) -> str:
    """What the scripted model says when a tool refused: the tool's own words."""
    data = _json(raw)
    if isinstance(data, dict):
        data = data.get("error") or data.get("mensaje") or json.dumps(data, ensure_ascii=False)
    return "⚠️ " + str(data)[:400]


def _call(name: str, **args) -> dict:
    return {"tool_calls": [(name, args)]}


class Script:
    """Answers like a model would, from what Hermes sends: the latest user message (with
    Hermes' markers for images, voice notes and replies), the tools on offer, and the
    results of the tools it already called in this turn."""

    def __init__(self, pwned: Path, secrets: Path):
        self.pwned = pwned
        self.secrets = secrets

    def __call__(self, req: dict) -> dict:
        bot = bot_of(req)
        messages = req.get("messages") or []
        users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if bot is None or not users:
            return {"content": "Conversación con Vinci"}  # auxiliary calls (titles and the like)
        turn = messages[users[-1] + 1:]
        text = flatten(messages[users[-1]].get("content"))
        called = [c["function"]["name"] for m in turn if m.get("role") == "assistant" for c in m.get("tool_calls") or []]
        results = [flatten(m.get("content")) for m in turn if m.get("role") == "tool"]
        if bot == "Vinci":
            return self.vinci(text, results)
        return self.subject(bot.split(" · ", 1)[1], text, called, results)

    def vinci(self, text: str, results: list[str]) -> dict:
        if results:
            return {"content": self.vinci_answer(results)}
        image = IMAGE_RE.search(text)
        replying = REPLY_RE.search(text)
        if "horario" in text and image:
            return _call("mcp__vinci__proponer_horario", clases=SCHEDULE_V1)
        if "Cálculo el miércoles es de 9:00" in text:
            return _call("mcp__vinci__proponer_horario", clases=SCHEDULE_V2)
        if "pizarra" in text and image:
            return _call("mcp__vinci__entregar_a_materia", materia="cálculo",
                         mensaje="Foto de la pizarra de hoy: la regla de la cadena con un ejemplo.",
                         adjuntos=[image[1].strip()])
        if "programación" in text:
            return _call("mcp__vinci__entregar_a_materia", materia="programación", mensaje="Apuntes de programación")
        if replying and "pásaselo" in text:
            return _call("mcp__vinci__entregar_a_materia", materia="cálculo",
                         mensaje=f"Aviso del aula: {replying[1]}\nPregunta del estudiante: ¿por dónde empiezo?")
        if "qué hay en el cuaderno" in text:
            return _call("mcp__vinci__cuaderno", materia="cálculo")
        if "arma mi equipo" in text:
            return _call("mcp__vinci__proponer_equipo")
        if "archiva el bot de física" in text:
            return _call("mcp__vinci__archivar_materia", materia="física")
        if "reactiva el bot de física" in text:
            return _call("mcp__vinci__reactivar_materia", materia="física")
        if "anota en el cuaderno" in text:  # Vinci has no tool for this: try anyway
            return {"tool_calls": [("mcp__vinci__anotar", {"tipo": "apunte", "texto": "El viernes hay prueba"}),
                                   ("write_file", {"path": "cuaderno.txt", "content": "El viernes hay prueba"})]}
        if "terminal" in text:
            return _call("terminal", command=f"touch {self.pwned}")
        return {"content": "Hola, soy Vinci. ¿En qué te ayudo?"}

    @staticmethod
    def vinci_answer(results: list[str]) -> str:
        parts = []
        for raw in results:
            data = _json(raw)
            if isinstance(data, dict) and data.get("confirmacion"):
                parts.append(data["confirmacion"])
            elif isinstance(data, dict) and data.get("mensaje"):
                parts.append(data["mensaje"])
            elif isinstance(data, dict) and "entradas" in data:
                parts.append("Esto hay en el cuaderno:\n" + "\n".join(
                    f"- {e['tipo']}: {e['texto']}" for e in data["entradas"][:8]))
            else:
                parts.append(_problem(raw))
        return "\n".join(parts)

    def subject(self, name: str, text: str, called: list[str], results: list[str]) -> dict:
        if "TAREA: brief_de_clase" in text:
            if not called:
                return _call("mcp__materia__buscar_material", pregunta="regla de la cadena")
            hits = _json(results[-1]) if results else None
            hits = hits.get("result") if isinstance(hits, dict) else hits
            top = hits[0] if isinstance(hits, list) and hits and isinstance(hits[0], dict) else {}
            source = f"{top['archivo']}, {top.get('unidad') or 'página'} {top.get('pagina')}" if top else None
            due = re.findall(r"^  - (.+?) — vence", text, re.M)
            news = re.findall(r"^  - (new_announcement|due_changed|new_assignment): (.+)$", text, re.M)
            return {"content": "\n".join([
                f"📚 Brief de {name} (09:00)",
                "1) Repaso: " + ("lo que tienes en el cuaderno de la clase anterior." if "Tu cuaderno desde" in text
                                 else "tu cuaderno no tiene nada de la clase anterior."),
                "2) Por entregar: " + ("; ".join(due) or "nada esta semana"),
                "3) Novedades: " + ("; ".join(n[1] for n in news) or "ninguna"),
                f"4) Conceptos clave: regla de la cadena, derivada de una composición "
                f"(📄 {source or 'sin material'})",
                "5) Pregunta para clase: ¿cuándo conviene derivar de forma implícita?"])}
        if "TAREA: entrega_de_vinci" in text:
            count = len(re.findall(r"^Entrega #\d+", text, re.M))
            photos = len(re.findall(r"^  - foto #\d+", text, re.M))
            extra = f", con {photos} foto(s) ya guardada(s) en tu cuaderno" if photos else ""
            return {"content": f"📨 De parte de Vinci: recibí {count} cosa(s){extra}. "
                               "Empieza por repasar la regla de la cadena."}
        if results:
            return {"content": self.subject_answer(results)}
        voice = VOICE_RE.search(text)
        image = IMAGE_RE.search(text)
        if voice:
            return _call("mcp__materia__guardar_adjunto", tipo="audio", ruta=voice[1].rstrip(".,"),
                         resumen="Nota de voz: la segunda ley de Newton y un ejemplo con un bloque.",
                         transcripcion="Hoy vimos la segunda ley de Newton: la fuerza neta es masa por aceleración.",
                         fecha_clase="2026-09-29")
        if image and "pizarra" in text:
            return _call("mcp__materia__guardar_adjunto", tipo="foto", ruta=image[1].strip(),
                         resumen="Pizarra: regla de la cadena (f∘g)'(x) = f'(g(x))·g'(x); "
                                 "ejemplo d/dx sen(x²) = 2x·cos(x²).", fecha_clase="2026-09-30")
        if "no entendí" in text:
            return _call("mcp__materia__anotar", tipo="duda",
                         texto="No entiende la regla de la cadena con funciones trigonométricas.")
        if "guarda en el cuaderno el archivo" in text:
            return _call("mcp__materia__guardar_adjunto", tipo="documento", ruta=str(self.secrets), resumen="archivo")
        return {"content": f"Hola, soy el bot de {name}."}

    @staticmethod
    def subject_answer(results: list[str]) -> str:
        data = _json(results[-1])
        if isinstance(data, dict) and data.get("tipo") in ("foto", "audio", "documento"):
            icon = {"foto": "📸", "audio": "🎙️", "documento": "📄"}[data["tipo"]]
            return f"{icon} Guardé en tu cuaderno ({data['tipo']} #{data['id']}): {data['texto']}"
        if isinstance(data, dict) and data.get("tipo"):
            return f"📝 Anoté tu {data['tipo'].replace('_', ' ')} (#{data['id']}): {data['texto']}"
        return _problem(results[-1])


# -- helpers ---------------------------------------------------------------------------------


def readable(message: dict) -> str:
    text = str(message.get("text") or message.get("caption") or "")
    if message.get("parse_mode") == "MarkdownV2":
        text = re.sub(r"\\([_*\[\]()~`>#+\-=|{}.!\\])", r"\1", text)
    return text


def plain(html_text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", html_text))


def buttons(message: dict) -> list[dict]:
    markup = message.get("reply_markup") or {}
    return [b for row in markup.get("inline_keyboard", []) for b in row]


class Gateway:
    """`hermes gateway run`: the default profile's multiplexing gateway, serving every bot."""

    def __init__(self, hermes: str, env: dict, log: Path):
        self.hermes, self.env, self.log_path = hermes, env, log
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.log = self.log_path.open("a", encoding="utf-8")
        self.log.write(f"\n===== gateway start {time.strftime('%H:%M:%S')} =====\n")
        self.log.flush()
        self.proc = subprocess.Popen([self.hermes, "gateway", "run"], env=self.env, cwd=self.env["HOME"],
                                     stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
                                     start_new_session=True)

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
            self.proc.wait()
        except ProcessLookupError:
            pass
        try:  # MCP servers and cron children of the gateway
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc = None
        self.log.close()

    def tail(self, n: int = 40) -> str:
        if not self.log_path.exists():
            return ""
        return "\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])


def entries(data_dir: Path, code: str) -> list[dict]:
    db = data_dir / "cuadernos" / code / "cuaderno.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM entradas ORDER BY id")]
    finally:
        conn.close()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def test_e2e(tmp_path):
    artifact = Path(os.environ.get("E2E_ARTIFACT_DIR") or REPO / "artifacts" / "e2e")
    shutil.rmtree(artifact, ignore_errors=True)
    artifact.mkdir(parents=True)
    probe_home = tmp_path / "sonda"
    probe_home.mkdir()
    hermes = find_hermes(probe_home)
    ptb = telegram_support(hermes, tmp_path / "ptb") if hermes else None
    home = tmp_path / "home"
    home.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    data_dir = tmp_path / "datos"
    pwned = tmp_path / "pwned"

    with FakeCanvas(CANVAS_TOKEN) as canvas, FakeTelegram({BOT_TOKEN: USERNAMES[BOT_TOKEN]}) as telegram:
        config = REPO.joinpath("config.toml").read_text(encoding="utf-8")
        config = config.replace('url = "https://aulavirtual.espol.edu.ec"', f'url = "{canvas.base}"')
        config = config.replace('carpeta_datos = "~/.local/share/espol-academic-bot"', f'carpeta_datos = "{data_dir}"')
        config = config.replace('proveedor = "anthropic"', 'proveedor = "fakellm"')
        config = config.replace('modelo = "claude-sonnet-5"', 'modelo = "fake"')
        config_file = tmp_path / "config.toml"
        config_file.write_text(config, encoding="utf-8")
        secrets = tmp_path / "secrets.env"
        secrets.write_text(f"CANVAS_TOKEN={CANVAS_TOKEN}\nTELEGRAM_BOT_TOKEN={BOT_TOKEN}\nTELEGRAM_USER_ID={CAPTAIN_ID}\n")
        secrets.chmod(0o600)
        llm_ctx = ScriptedLLM(Script(pwned, secrets))
        llm = llm_ctx.__enter__()

        def normalize(text: str) -> str:
            text = text.replace(canvas.base, "https://aulavirtual.test").replace(telegram.base, "https://telegram.test")
            text = text.replace(llm.base, "https://llm.test")
            text = text.replace(str(data_dir), "<datos>").replace(str(home), "<home>").replace(str(tmp_path), "<tmp>")
            text = text.replace(str(REPO), "<repo>").replace(str(VENV_BIN), "<repo>/.venv/bin")
            if hermes:
                text = text.replace(hermes, "<hermes>")
            return re.sub(r"\b[0-9a-f]{12,}\b", "<id>", text)

        base_env = {k: v for k, v in os.environ.items() if not k.startswith(("AULA_", "HERMES_", "XDG_", "DBUS_", "PYTEST_"))}
        base_env.update({f"XDG_{k}_HOME": str(home / f".xdg-{k.lower()}") for k in ("CONFIG", "DATA", "CACHE", "STATE")})
        base_env.update({
            "HOME": str(home), "XDG_RUNTIME_DIR": str(run_dir),
            "AULA_CONFIG": str(config_file), "AULA_SECRETS": str(secrets),
            "ESPOL_TELEGRAM_API_BASE": telegram.base, "E2E_TELEGRAM_API": telegram.base,
            "HERMES_TELEGRAM_DISABLE_FALLBACK_IPS": "1", "ESPOL_NO_PM_INSTALL": "1",
            "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            # Hermes refuses to open ~/.hermes/state.db from a process launched by pytest (it also
            # checks the process ancestry). Here ~ is the temporary HOME (asserted below).
            "HERMES_STATE_DB_GUARD_BYPASS": "1",
        })
        assert Path(base_env["HOME"]).resolve().is_relative_to(tmp_path.resolve()), "la prueba usa un HOME temporal"
        if hermes:
            base_env["HERMES_BIN"] = hermes
        if ptb:
            base_env["PYTHONPATH"] = str(ptb)

        def run(args, now, *, env_extra=None, check=True, stdin="", new_session=False, timeout=300):
            env = {**base_env, "AULA_NOW": now, **(env_extra or {})}
            proc = subprocess.run(args, env=env, capture_output=True, text=True, cwd=REPO, timeout=timeout,
                                  input=stdin, start_new_session=new_session)
            if check:
                assert proc.returncode == 0, f"{args} falló ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
            return proc

        sent_log: list[tuple[str, dict]] = []

        def take(label: str) -> list[dict]:
            with telegram.lock:
                new = telegram.messages[len(sent_log):]
            sent_log.extend((label, m) for m in new)
            return new

        report: list[str] = []
        profiles = home / ".hermes" / "profiles"

        # 1. setup.sh, twice, in an isolated HOME (never the real ~/.hermes) ----------------
        if hermes:
            legacy = profiles / "espol"
            run([hermes, "profile", "create", "espol", "--no-skills", "--description", "Bot académico"], T_SETUP)
            (legacy / "SOUL.md").write_text(f"<!-- {MARKER}. -->\n# Bot académico de ESPOL\n", encoding="utf-8")
            (legacy / "memories").mkdir(exist_ok=True)
            (legacy / "memories" / "MEMORY.md").write_text("El estudiante prefiere respuestas cortas.\n")
            (legacy / "scripts").mkdir(exist_ok=True)
            (legacy / "scripts" / "espol-sondeo.sh").write_text(f"#!/usr/bin/env bash\n# {MARKER}.\nexit 0\n")
            (legacy / "scripts" / "espol-sondeo.sh").chmod(0o755)
            run([hermes, "-p", "espol", "cron", "create", "every 30m", "--script", "espol-sondeo.sh", "--no-agent",
                 "--name", "espol-sondeo", "--deliver", f"telegram:{CAPTAIN_ID}"], T_SETUP)

            first = run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_SETUP)
            second = run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_SETUP)
            setup_log = ("$ ./setup.sh --skip-deps   # 1ª vez (había un perfil «espol» del bot anterior)\n"
                         + first.stdout + first.stderr
                         + "\n$ ./setup.sh --skip-deps   # 2ª vez (idempotente)\n" + second.stdout + second.stderr)
            profile = profiles / "vinci"
            assert not legacy.exists() and profile.is_dir(), "el perfil «espol» debe convertirse en «vinci»"
            assert (profile / "memories" / "MEMORY.md").read_text() == "El estudiante prefiere respuestas cortas.\n"
            assert not (profile / "scripts" / "espol-sondeo.sh").exists()
            jobs = json.loads((profile / "cron" / "jobs.json").read_text())["jobs"]
            assert sorted(j["name"] for j in jobs) == ["vinci-resumen", "vinci-sondeo"], jobs
            by_name = {j["name"]: j for j in jobs}
            assert by_name["vinci-sondeo"]["schedule_display"] == "every 30m"
            assert by_name["vinci-resumen"]["schedule"].get("expr") == "0 7 * * *" or \
                by_name["vinci-resumen"]["schedule_display"] == "0 7 * * *"
            assert all(j["no_agent"] and j["deliver"] == f"telegram:{CAPTAIN_ID}" for j in jobs)
            assert "sin cambios" in second.stdout and "creado" not in second.stdout
            profile_env = parse_env_file(profile / ".env")
            assert profile_env["TELEGRAM_BOT_TOKEN"] == BOT_TOKEN
            assert profile_env["TELEGRAM_ALLOWED_USERS"] == profile_env["TELEGRAM_HOME_CHANNEL"] == CAPTAIN_ID
            vcfg = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
            assert vcfg["timezone"] == "America/Guayaquil" and vcfg["model"]["provider"] == "fakellm"
            assert set(vcfg["platform_toolsets"]["telegram"]) == {"web", "memory", "session_search", "clarify",
                                                                  "mcp-vinci"}
            assert {"terminal", "file", "code_execution", "skills", "delegation", "cronjob"} <= \
                set(vcfg["agent"]["disabled_toolsets"])
            assert vcfg["tools"]["tool_search"]["enabled"] == "off"
            assert vcfg["skills"]["auto_load"] == ["vinci"]
            assert vcfg["mcp_servers"]["vinci"]["command"] == str(VENV_BIN / "espol-bot")
            assert vcfg["mcp_servers"]["vinci"]["args"][:1] == ["mcp"]
            assert "vinci-botones" in vcfg["plugins"]["enabled"]
            assert vcfg["unauthorized_dm_behavior"] == "ignore" and vcfg["stt"]["language"] == "es"
            assert vcfg["platforms"]["telegram"]["extra"]["base_url"] == f"{telegram.base}/bot"
            assert {"*secrets.env*", "*CANVAS_TOKEN*", "*api/v1*"} <= set(vcfg["approvals"]["deny"])
            assert (profile / "skills" / "vinci" / "vinci" / "SKILL.md").is_file()
            assert (home / ".local" / "bin" / "aula").is_file()
            assert (home / ".claude" / "skills" / "aula" / "SKILL.md").is_file()
            assert not (home / ".hermes" / "config.yaml").exists(), "setup no debe crear config del perfil por defecto"
            report.append(f"setup.sh ×2 con Hermes real en un HOME aislado: el perfil «espol» del bot anterior pasó "
                          f"a «vinci» con su memoria; {len(jobs)} cron no-agent; la segunda corrida no cambió nada")
            take("setup.sh (mensaje de prueba de Vinci)")
        else:
            setup_log = "Hermes no está instalado aquí: se omitió la prueba de setup.sh.\n"
            report.append("setup.sh omitido: Hermes no está instalado en esta máquina")

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
        assert [t["tarea"] for t in tareas] == ["Deber 2: Continuidad", "Taller 3: Derivadas",
                                                "Práctica 4: Regla de la cadena"], "teórico y práctico de Cálculo"
        bajado = cli_json["archivos bajar 5001 --json"][0]
        assert bajado["indexado"] == "ok" and Path(bajado["ruta_local"]).is_file()
        assert "Paralelo5_MATG1049" in bajado["ruta_local"]
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
        assert not any(buttons(m) for m in poll1 + poll2), "sin bots de materia todavía no hay botones"

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

        # 6. two resources failing at different polls on a fresh install ---------------
        fresh_config = tmp_path / "config-resiliencia.toml"
        fresh_config.write_text(config.replace(str(data_dir), str(tmp_path / "resiliencia")), encoding="utf-8")
        fresh = {"AULA_CONFIG": str(fresh_config)}
        fisica_anuncios, calculo_archivos = "/api/v1/courses/102/discussion_topics", "/api/v1/courses/101/files"
        names = {fisica_anuncios: "anuncios de Física", calculo_archivos: "archivos de Cálculo"}
        plan = [{fisica_anuncios}, {fisica_anuncios}, {fisica_anuncios, calculo_archivos},
                {fisica_anuncios, calculo_archivos}, {calculo_archivos}, {fisica_anuncios, calculo_archivos},
                {fisica_anuncios}, {fisica_anuncios}, set()]
        polls = []
        for i, (now, paths) in enumerate(zip(T_RESILIENCE, plan, strict=True), start=1):
            canvas.failing = set(paths)
            run([bot, "sondeo"], now, env_extra=fresh)
            failing = ", ".join(names[p] for p in sorted(paths)) or "nada"
            polls.append(take(f"Resiliencia · sondeo {i} ({now[11:16]}), fallando: {failing}"))
            if i == 4:
                fisica = json.loads(run([aula, "tareas", "--curso", "fisica", "--sin-actualizar", "--json"],
                                        now, env_extra=fresh).stdout)
                assert "Examen parcial" in [t["tarea"] for t in fisica], "las tareas de Física siguen disponibles"
        assert "FÍSICA I" in polls[0][0]["text"], "la bienvenida lista la materia aunque falle una parte"
        alerts = [(i, re.search(r"sin poder leer (.+?);", m["text"]).group(1))
                  for i, poll in enumerate(polls, start=1) for m in poll if m["text"].startswith("\u26a0")]
        fisica_what = "los anuncios de FÍSICA I - II PAO 2026"
        calculo_what = "los archivos de CÁLCULO DE UNA VARIABLE - II PAO 2026"
        assert alerts == [(3, fisica_what), (5, calculo_what), (8, fisica_what)], alerts
        for poll in polls[1:]:
            assert all(m["text"].startswith(("\u23f0", "\u26a0")) for m in poll), \
                f"al recuperarse no se reenvía lo viejo: {[m['text'][:40] for m in poll]}"
        anuncios = json.loads(run([aula, "anuncios", "--curso", "fisica", "--sin-actualizar", "--json"],
                                  T_RESILIENCE[-1], env_extra=fresh).stdout)
        assert len(anuncios) == 1, "al recuperarse, el anuncio existente queda guardado"
        canvas.failing = set()

        equipo_md = ["# El equipo de bots, desde el chat con Vinci\n"]
        horario_md = ["# Horario desde una captura (se guarda solo con el botón del capitán)\n"]
        briefs_md = ["# Brief antes de clase\n"]
        tools_seen: dict[str, set[str]] = {}
        vinci_section = bool(hermes and ptb)
        gateway = Gateway(hermes, {**base_env, "AULA_NOW": T_VINCI}, tmp_path / "gateway.log") if vinci_section else None
        try:
            if vinci_section:
                vinci_flow(**locals())
            else:
                report.append("Vinci con Hermes omitido: " + ("Hermes no está instalado" if not hermes else
                              "no pude preparar python-telegram-bot para Hermes"))
        finally:
            if gateway is not None:
                gateway.stop()
            llm_ctx.__exit__(None, None, None)

        take("Fin")
        # Safety: read-only, captain-only, no secrets anywhere ---------------------------------
        methods = {m for m, _ in canvas.requests}
        assert methods == {"GET"}, f"hubo solicitudes que no son GET: {methods}"
        assert canvas.throttled, "el 429 de prueba debió ocurrir"
        assert any("page=2" in p for _, p in canvas.requests), "debió seguir la paginación"
        assert all(str(m["chat_id"]) == CAPTAIN_ID for _, m in sent_log), "solo se escribe al capitán"
        assert not any("5002" in p and "download" in p for _, p in canvas.requests), "archivo enorme no se baja"
        secrets_all = [CANVAS_TOKEN, BOT_TOKEN, *SUBJECT_TOKENS.values(), UNKNOWN_TOKEN, STRANGER_TOKEN]
        telegram_dump = json.dumps(telegram.messages, ensure_ascii=False)
        llm_dump = json.dumps(llm.requests, ensure_ascii=False)
        for secret in secrets_all:
            assert secret not in telegram_dump, "un token apareció en un mensaje de Telegram"
            assert secret not in llm_dump, "un token llegó al modelo"

    # Artifact ------------------------------------------------------------------------------
    notif = ["# Mensajes de Telegram capturados (en orden)\n",
             "Cada bloque es un mensaje tal como lo envió cada bot (Vinci manda HTML; las respuestas que "
             "escribe Hermes van en MarkdownV2 y aquí se muestran sin los escapes).\n"]
    current = None
    for label, message in sent_log:
        if label != current:
            notif.append(f"\n## {label}\n")
            current = label
        keys = "".join(f"\n[{b['text']}]" for b in buttons(message))
        notif.append(f"**@{message['bot']}**\n```\n{normalize(readable(message))}{keys}\n```\n")
    (artifact / "notificaciones.md").write_text("\n".join(notif), encoding="utf-8")
    (artifact / "resumen_diario.txt").write_text(normalize(summary[0]["text"]) + "\n", encoding="utf-8")
    (artifact / "recuperacion.json").write_text(normalize(json.dumps(retrieval, ensure_ascii=False, indent=2)) + "\n",
                                               encoding="utf-8")
    (artifact / "cli.md").write_text("\n".join(cli_md), encoding="utf-8")
    (artifact / "setup.log").write_text(normalize(setup_log), encoding="utf-8")
    requests_log = "\n".join(f"{m} {re.sub(r'verifier=[^&]+', 'verifier=…', p)}" for m, p in canvas.requests)
    (artifact / "canvas_requests.log").write_text(requests_log + "\n", encoding="utf-8")
    if vinci_section:
        (artifact / "equipo.md").write_text(normalize("\n".join(equipo_md)), encoding="utf-8")
        (artifact / "horario.md").write_text(normalize("\n".join(horario_md)), encoding="utf-8")
        (artifact / "briefs.md").write_text(normalize("\n".join(briefs_md)), encoding="utf-8")
        cuadernos_md = ["# Cuadernos de los bots de materia (al final de la prueba)\n"]
        for code in SUBJECT_TOKENS:
            cuadernos_md.append(f"## {code}\n")
            for e in entries(data_dir, code):
                extra = "".join(f" · {k}: {e[k]}" for k in ("transcripcion", "archivo", "fecha_clase", "estado") if e[k])
                cuadernos_md.append(f"- #{e['id']} **{e['tipo']}** (de {e['origen']}): {e['texto']}{extra}")
            cuadernos_md.append("")
        (artifact / "cuadernos.md").write_text(normalize("\n".join(cuadernos_md)), encoding="utf-8")
        (artifact / "hermes_herramientas.json").write_text(json.dumps(
            {bot_name: sorted(names) for bot_name, names in sorted(tools_seen.items())}, ensure_ascii=False, indent=2)
            + "\n", encoding="utf-8")
    for path in artifact.iterdir():  # no artifact may carry a token
        text = path.read_text(encoding="utf-8", errors="replace")
        for secret in (CANVAS_TOKEN, BOT_TOKEN, *SUBJECT_TOKENS.values(), UNKNOWN_TOKEN, STRANGER_TOKEN):
            assert secret not in text, f"{path.name} contiene un token"
    counts = {label: sum(1 for l, _ in sent_log if l == label) for label in dict.fromkeys(l for l, _ in sent_log)}
    lines = [
        "# Reporte E2E: Vinci y los bots de materia (ESPOL)\n",
        "Resultado: **todas las verificaciones pasaron**.\n",
        *[f"- {line}" for line in report],
        f"- Canvas falso: {len(canvas.requests)} solicitudes, todas GET; paginación seguida; un 429 con reintento; "
        "Física con la pestaña Archivos oculta (material encontrado vía Módulos).",
        "- Sondeo 3 y el resumen repetido no enviaron nada (sin duplicados).",
        "- Instalación nueva con los anuncios de Física y los archivos de Cálculo fallando en distintos sondeos: "
        "lo demás siguió funcionando, una alerta por episodio y recurso (sondeos 3, 5 y 8) y lo leído al "
        "recuperarse se guardó sin reenviarse.",
        *[f"- Recuperación «{r['pregunta']}» → {r['resultados'][0]['archivo']}, "
          f"{r['resultados'][0]['unidad']} {r['resultados'][0]['pagina']} ✓" for r in retrieval],
        "- Ningún token (Canvas ni bots) apareció en mensajes de Telegram, en lo que vio el modelo ni en estos archivos.",
        "\n## Mensajes por etapa\n",
        *[f"- {label}: {n}" for label, n in counts.items()],
        "\nArchivos: `notificaciones.md`, `equipo.md`, `horario.md`, `briefs.md`, `cuadernos.md`, "
        "`hermes_herramientas.json`, `resumen_diario.txt`, `recuperacion.json`, `cli.md`, `canvas_requests.log`, "
        "`setup.log`.\n",
    ]
    (artifact / "REPORTE.md").write_text("\n".join(lines), encoding="utf-8")


def vinci_flow(*, hermes, home, profiles, data_dir, telegram, llm, run, take, report, gateway,
               equipo_md, horario_md, briefs_md, tools_seen, pwned, secrets, base_env, **_) -> None:
    """Sections 6-8: the gateway session (team, schedule, routing, agenda, notebooks, archive and
    reactivation) and the last setup.sh. The caller owns `gateway` and always stops it."""
    bot = str(VENV_BIN / "espol-bot")
    telegram.managers.add(BOT_TOKEN)  # Vinci has "manage other bots" on in BotFather

    def patch_profile(name: str) -> None:
        """Test-only: the scripted model, images passed natively, and no speech-to-text engine."""
        cfg_file = profiles / name / "config.yaml"
        data = yaml.safe_load(cfg_file.read_text())
        data["providers"] = {"fakellm": {"api": f"{llm.base}/v1", "api_key": "e2e", "discover_models": False,
                                         "models": ["fake"]}}
        data.setdefault("agent", {})["image_input_mode"] = "native"
        data.setdefault("stt", {})["enabled"] = False
        cfg_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))

    patch_profile("vinci")
    (home / ".hermes" / "config.yaml").write_text("stt:\n  enabled: false\n")
    vinci_jobs = {j["name"]: j["id"] for j in json.loads((profiles / "vinci" / "cron" / "jobs.json").read_text())["jobs"]}
    for job_id in vinci_jobs.values():  # the test drives Vinci's poll itself (same command)
        run([hermes, "-p", "vinci", "cron", "pause", job_id], T_VINCI)

    def fail(msg: str) -> str:
        return f"{msg}\n--- gateway.log ---\n{gateway.tail()}"

    def polling(users: set[str], mark: int, timeout: float = 120):
        ok = telegram.wait_for(lambda t: {c["bot"] for c in t.calls[mark:] if c["method"] == "getUpdates"} >= users,
                               timeout)
        assert ok, fail(f"el gateway no empezó a escuchar a {sorted(users)}")

    def wait_msg(user: str, mark: int, contains: str, timeout: float = 120) -> dict:
        def found(t):
            return next((m for m in t.messages[mark:] if m["bot"] == user and contains in readable(m)), None)
        message = telegram.wait_for(found, timeout)
        assert message, fail(f"@{user} no envió «{contains}»; recibí: "
                             f"{[(m['bot'], readable(m)[:120]) for m in telegram.messages[mark:]]}")
        return message

    def turn(send, user: str, contains: str, timeout: float = 120) -> dict:
        mark = len(telegram.messages)
        send()
        return wait_msg(user, mark, contains, timeout)

    def toast(mark: int, contains: str, timeout: float = 60) -> dict:
        call = telegram.wait_for(lambda t: next((c for c in t.calls[mark:] if c["method"] == "answerCallbackQuery"
                                                  and contains in str(c["params"].get("text", ""))), None), timeout)
        assert call, fail(f"no vi el aviso «{contains}» al pulsar el botón")
        return call

    def consumed(token: str, update_id: int, timeout: float = 60) -> None:
        user = USERNAMES[token]
        ok = telegram.wait_for(lambda t: any(c["bot"] == user and c["method"] == "getUpdates"
                                             and int(c["params"].get("offset", 0) or 0) > update_id for c in t.calls),
                               timeout)
        assert ok, fail(f"@{user} no procesó la actualización {update_id}")

    def deleted(token: str, message_id: int) -> bool:
        return any(c["bot"] == USERNAMES[token] and c["method"] == "deleteMessage"
                   and int(c["params"].get("message_id", 0)) == message_id for c in telegram.calls)

    def incoming_id(update_id: int) -> int:
        return telegram.pushed[update_id]["message"]["message_id"]

    def team() -> dict:
        import tomllib
        return {m["codigo"]: m for m in tomllib.loads((data_dir / "materias.toml").read_text())["materia"]}

    def schedule_saved() -> bool:
        return (data_dir / "horario.toml").exists()

    def handoffs() -> list[dict]:
        conn = sqlite3.connect(data_dir / "espol.db")
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM entregas ORDER BY id")]
        finally:
            conn.close()

    def cron_tasks(kind: str) -> list[str]:
        found = []
        for req in llm.requests:
            for m in req.get("messages") or []:
                text = flatten(m.get("content"))
                if m.get("role") == "user" and f"TAREA: {kind}" in text and text not in found:
                    found.append(text)
        return found

    def last_run(code: str) -> str | None:
        jobs = json.loads((profiles / f"vinci-{code.lower()}" / "cron" / "jobs.json").read_text())["jobs"]
        return next((j.get("last_run_at") for j in jobs if j["name"] == "vinci-agenda"), None)

    def show(title: str, text: str) -> None:
        equipo_md.append(f"## {title}\n\n```\n{text.rstrip()}\n```\n")

    gate_before = run([bot, "agenda", "--curso", "MATG1049"], T_VINCI).stdout.strip()
    assert gate_before == SKIP, "sin bots, horario ni entregas la agenda no despierta al modelo"

    mark_calls = len(telegram.calls)
    gateway.start()
    polling({"vinci_bot"}, mark_calls)
    take("Gateway encendido (solo Vinci)")

    # 6. Vinci builds the team from chat ---------------------------------------------------------
    mark = len(telegram.messages)
    telegram.send_text(BOT_TOKEN, CAPTAIN, "arma mi equipo de bots por materia")
    card = wait_msg("vinci_bot", mark, "Tu equipo de bots")
    wait_msg("vinci_bot", mark, "Un bot se crea solo cuando pulse ese botón")
    assert [b["text"] for b in buttons(card)] == ["➕ Crear Vinci · Cálculo de una Variable", "➕ Crear Vinci · Física I"]
    assert len(re.findall(r"^• ", plain(card["text"]), re.M)) == 2 and "reconocible" not in card["text"], \
        "tres cursos del aula, dos materias: el práctico de Cálculo no es otro bot"
    assert {c: (m["estado"], m["cursos"]) for c, m in team().items()} == {
        "MATG1049": ("pendiente", [101, 103]), "FISG1002": ("pendiente", [102])}
    assert not (profiles / "vinci-matg1049").exists(), "proponer no crea nada"
    show("Vinci arma el equipo («arma mi equipo de bots por materia»)",
         plain(card["text"]) + "\n" + "".join(f"[{b['text']}]" for b in buttons(card)))
    create = {b["text"]: b["callback_data"] for b in buttons(card)}

    # Cálculo: Telegram's managed bots (the token never touches the chat)
    calls = len(telegram.calls)
    keyboard_msg = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, card, create["➕ Crear Vinci · Cálculo de una Variable"]),
                        "vinci_bot", "Creemos Vinci · Cálculo de una Variable")
    toast(calls, "Creemos")
    request = keyboard_msg["reply_markup"]["keyboard"][0][0]["request_managed_bot"]
    assert request["suggested_name"] == "Vinci · Cálculo de una Variable"
    assert request["suggested_username"] == "vinci_calculo_variable_bot"
    assert team()["MATG1049"]["estado"] == "esperando_bot"
    show("Pulsa «➕ Crear Vinci · Cálculo de una Variable» (Vinci puede gestionar bots)",
         plain(keyboard_msg["text"]) + f"\n[botón de Telegram: {keyboard_msg['reply_markup']['keyboard'][0][0]['text']} → "
         f"request_managed_bot {json.dumps(request, ensure_ascii=False)}]")
    created = turn(lambda: telegram.create_managed_bot(BOT_TOKEN, CAPTAIN, MATG, "vinci_calculo_bot",
                                                       "Vinci · Cálculo de una Variable"),
                   "vinci_bot", "quedó creado y activo", timeout=180)
    patch_profile("vinci-matg1049")
    assert created["reply_markup"] == {"remove_keyboard": True}
    assert any(c["method"] == "getManagedBotToken" and int(c["params"]["user_id"]) == 700001 for c in telegram.calls)
    show("Telegram le comparte a Vinci el bot creado (managed_bot_created)", plain(created["text"]))

    # Física: BotFather's reply forwarded (the plugin deletes it before Hermes sees it)
    telegram.add_bot(FIS, USERNAMES[FIS])  # the captain created it with /newbot in @BotFather
    turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, card, create["➕ Crear Vinci · Física I"]), "vinci_bot",
         "Creemos Vinci · Física I")
    attempts = []
    for label, token, expected in (("el token de Cálculo otra vez", MATG, "ya estaba configurado"),
                                   ("un token que Telegram no conoce", UNKNOWN_TOKEN, "Telegram no aceptó ese token"),
                                   ("la respuesta de BotFather con el token de Física", FIS, "quedó creado y activo")):
        mark = len(telegram.messages)
        update_id = telegram.send_text(BOT_TOKEN, CAPTAIN, BOTFATHER_REPLY.format(token=token))
        message_id = incoming_id(update_id)
        reply = wait_msg("vinci_bot", mark, expected, timeout=180)
        assert "Borré del chat el mensaje con el token" in plain(reply["text"])
        assert deleted(BOT_TOKEN, message_id), f"no se borró el mensaje con {label}"
        attempts.append(f"El capitán reenvía {label} → borrado del chat; Vinci responde:\n{plain(reply['text'])}")
    patch_profile("vinci-fisg1002")
    show("Física: el capitán reenvía la respuesta de @BotFather", "\n\n".join(attempts))
    secrets_before = secrets.read_text()
    update_id = telegram.send_text(BOT_TOKEN, STRANGER, f"mi bot: {STRANGER_TOKEN}")
    consumed(BOT_TOKEN, update_id)
    time.sleep(1)
    assert secrets.read_text() == secrets_before, "el token de un extraño no se guarda"
    assert deleted(BOT_TOKEN, incoming_id(update_id)), "un token en el chat se borra siempre"

    secrets_env = parse_env_file(secrets)
    assert secrets_env["TELEGRAM_BOT_TOKEN_MATG1049"] == MATG and secrets_env["TELEGRAM_BOT_TOKEN_FISG1002"] == FIS
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o600
    assert {c: (m["estado"], m["usuario"]) for c, m in team().items()} == {
        "MATG1049": ("activa", "vinci_calculo_bot"), "FISG1002": ("activa", "vinci_fisica_bot")}
    for code, token in SUBJECT_TOKENS.items():
        sp = profiles / f"vinci-{code.lower()}"
        env = parse_env_file(sp / ".env")
        assert env["TELEGRAM_BOT_TOKEN"] == token and env["TELEGRAM_ALLOWED_USERS"] == CAPTAIN_ID
        scfg = yaml.safe_load((sp / "config.yaml").read_text())
        assert set(scfg["platform_toolsets"]["telegram"]) == {"memory", "session_search", "clarify", "mcp-materia"}
        assert {"web", "terminal", "file", "skills"} <= set(scfg["agent"]["disabled_toolsets"])
        assert scfg["mcp_servers"]["materia"]["args"][:4] == ["mcp", "materia", "--curso", code]
        assert scfg["unauthorized_dm_behavior"] == "ignore" and scfg["skills"]["auto_load"] == ["vinci-materia"]
        assert "vinci-botones" in scfg["plugins"]["enabled"]
        jobs = json.loads((sp / "cron" / "jobs.json").read_text())["jobs"]
        assert [(j["name"], j["schedule_display"], j["no_agent"], j["script"], j["enabled"]) for j in jobs] == [
            ("vinci-agenda", "every 1m", False, "vinci-agenda.sh", True)], jobs
    for token in (MATG, FIS, UNKNOWN_TOKEN):  # where a token may live: secrets.env and its own profile's .env
        holders = sorted(str(f.relative_to(home)) for f in home.rglob("*") if f.is_file()
                         and token.encode() in f.read_bytes())
        allowed = {f".hermes/profiles/vinci-{c.lower()}/.env" for c, t in SUBJECT_TOKENS.items() if t == token}
        assert set(holders) <= allowed, f"el token apareció en {holders}"
    assert "Congratulations on your new bot" not in json.dumps(llm.requests, ensure_ascii=False)
    report.append("Vinci armó el equipo desde el chat: su tarjeta mostró un botón «➕ Crear» por materia (proponer "
                  "no creó nada; los cursos Paralelo5_MATG1049 y Paralelo105_MATG1049, teórico y práctico de "
                  "Cálculo, quedaron en un solo bot); Cálculo se creó como bot gestionado de Telegram (Vinci obtuvo "
                  "el token con getManagedBotToken, sin que pasara por el chat) y Física con la respuesta de @BotFather "
                  "reenviada, que el plugin borró del chat antes de que Hermes la viera; un token repetido, uno "
                  "desconocido y el de un extraño no crearon nada. Los tokens quedaron solo en secrets.env (600) y "
                  "en el .env de su propio perfil: nunca en una sesión, un log ni lo que vio el modelo")
    mark_calls = len(telegram.calls)
    polling({"vinci_calculo_bot", "vinci_fisica_bot"}, mark_calls, timeout=150)
    report.append("El mismo gateway de Hermes empezó a atender a los dos bots nuevos solo, sin reiniciarlo")
    take("Vinci arma el equipo")

    # 7a. strangers get silence
    requests_before = len(llm.requests)
    consumed(BOT_TOKEN, telegram.send_text(BOT_TOKEN, STRANGER, "hola, ¿me ayudas con mi tarea?"))
    consumed(MATG, telegram.send_text(MATG, STRANGER, "hola bot de cálculo"))
    time.sleep(2)
    assert not [m for m in telegram.messages if str(m.get("chat_id")) == str(STRANGER)], "un extraño recibió respuesta"
    assert "me ayudas con mi tarea" not in json.dumps(llm.requests[requests_before:], ensure_ascii=False)
    report.append("Un extraño que le escribe a Vinci o a un bot de materia no recibe nada (ni código de pairing) "
                  "y el modelo nunca ve su mensaje")
    take("Un extraño escribe (sin respuesta)")

    # 7b. the schedule from a screenshot, saved only by the captain's button
    horario_jpg = (FILES / "horario.jpg").read_bytes()
    mark = len(telegram.messages)
    telegram.send_photo(BOT_TOKEN, CAPTAIN, horario_jpg, caption="este es mi horario de clases")
    card1 = wait_msg("vinci_bot", mark, "Esto es lo que leí de tu horario")
    wait_msg("vinci_bot", mark, "Se guarda solo cuando pulse Guardar")
    ok1 = next(b["callback_data"] for b in buttons(card1) if b["callback_data"].endswith(":ok"))
    no1 = next(b["callback_data"] for b in buttons(card1) if b["callback_data"].endswith(":no"))
    assert "10:00" in plain(card1["text"]) and not schedule_saved(), "proponer no guarda"
    horario_md += ["## 1. Vinci lee la captura y propone (con un error: Cálculo el miércoles a las 10:00)\n",
                   f"```\n{plain(card1['text'])}\n[{' | '.join(b['text'] for b in buttons(card1))}]\n```\n"]
    calls = len(telegram.calls)
    telegram.press(BOT_TOKEN, STRANGER, card1, ok1)
    toast(calls, "solo atiende a su dueño")
    assert not schedule_saved(), "el botón de un extraño no guarda nada"
    horario_md.append("## 2. Un extraño pulsa «Guardar»: «Este bot solo atiende a su dueño.» y no se guarda\n")
    reply = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, card1, no1), "vinci_bot", "no lo guardé")
    assert not schedule_saved()
    horario_md += ["## 3. El capitán pulsa «Corregir»\n", f"```\n{plain(reply['text'])}\n```\n"]
    mark = len(telegram.messages)
    telegram.send_text(BOT_TOKEN, CAPTAIN, "Cálculo el miércoles es de 9:00 a 11:00, no de 10:00")
    card2 = wait_msg("vinci_bot", mark, "Esto es lo que leí de tu horario")
    wait_msg("vinci_bot", mark, "Se guarda solo cuando pulse Guardar")
    ok2 = next(b["callback_data"] for b in buttons(card2) if b["callback_data"].endswith(":ok"))
    horario_md += ["## 4. Le dice qué corregir y Vinci propone de nuevo\n", f"```\n{plain(card2['text'])}\n```\n"]
    calls = len(telegram.calls)
    telegram.press(BOT_TOKEN, CAPTAIN, card1, ok1)
    toast(calls, "ya fue descartada")
    assert not schedule_saved(), "una propuesta vieja no se puede guardar"
    horario_md.append("## 5. «Guardar» en la propuesta vieja: «Esa propuesta ya fue descartada.» y no se guarda\n")
    saved = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, card2, ok2), "vinci_bot", "Guardé tu horario")
    assert schedule_saved()
    from aula_core.config import load_config
    from espol_bot import horario
    classes = horario.load(load_config(Path(base_env["AULA_CONFIG"])))
    assert [c.as_json() for c in classes] == horario.to_json(horario.validate(SCHEDULE_V2)[0])
    assert {"materia": "MATG1049", "dia": "viernes", "inicio": "10:00", "fin": "12:00", "aula": "LAB 11C",
            "paralelo": "105"} in [c.as_json() for c in classes], "el práctico de Cálculo es una clase de MATG1049"
    assert any(c["method"] == "editMessageReplyMarkup" and int(c["params"].get("message_id", 0)) == card2["message_id"]
               for c in telegram.calls), "los botones de la tarjeta guardada se quitan"
    horario_md += ["## 6. El capitán pulsa «Guardar horario»\n", f"```\n{plain(saved['text'])}\n```\n",
                   "## horario.toml\n", f"```toml\n{(data_dir / 'horario.toml').read_text()}```\n"]
    report.append("Horario desde una captura: Vinci lo mostró en una tarjeta; no se guardó al proponerlo, ni con el "
                  "botón de un extraño, ni con «Corregir», ni desde una propuesta vieja; se guardó (validado) solo "
                  "cuando el capitán pulsó «Guardar horario»")
    take("Horario desde una captura")
    early = run([bot, "agenda", "--curso", "MATG1049"], T_EARLY).stdout.strip()
    assert early == SKIP, "a las 08:29 todavía no toca el brief de la clase de las 09:00"

    # 7c. routing a photo to the right subject bot; an unknown subject is refused
    pizarra = (FILES / "pizarra.jpg").read_bytes()
    routed = turn(lambda: telegram.send_photo(BOT_TOKEN, CAPTAIN, pizarra,
                                              caption="esto es de cálculo: lo que el profe copió en la pizarra hoy"),
                  "vinci_bot", "se lo pasé a Vinci · Cálculo de una Variable")
    assert "@vinci_calculo_bot" in readable(routed) and "1 adjunto" in readable(routed)
    queued = [h for h in handoffs() if h["materia"] == "MATG1049" and h["origen"] == "vinci"]
    assert len(queued) == 1 and len(json.loads(queued[0]["adjuntos"])) == 1
    unknown = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "tengo unos apuntes de programación, pásaselos"),
                   "vinci_bot", "No reconozco la materia")
    assert len(handoffs()) == 1, "una materia que no existe no se reparte a nadie"
    report.append("Vinci repartió una foto «de cálculo» al bot de Cálculo (con el adjunto) y, para una materia que "
                  "no tiene bot, no se la pasó a nadie: " + readable(unknown)[:90].replace("\n", " ") + "…")
    take("Vinci reparte una foto")

    # 7d. alerts with a handoff button, and a reply to an alert
    run([bot, "sondeo"], T_VINCI)
    reminders = take("Sondeo · mié 30 sep 08:30 (avisos con botón)")
    assert len(reminders) == 3, [m["text"][:60] for m in reminders]
    calc_alert = next(m for m in reminders if "Taller 3" in m["text"])
    practico_alert = next(m for m in reminders if "Práctica 4" in m["text"])
    fis_alert = next(m for m in reminders if "Examen parcial" in m["text"])
    assert "CÁLCULO DE UNA VARIABLE - II PAO 2026 Práctico" in practico_alert["text"]
    for alert in (calc_alert, practico_alert):  # theory and práctico: the same one bot
        assert [b["text"] for b in buttons(alert)] == ["🎓 Consultar con Vinci · Cálculo de una Variable"]
        assert re.fullmatch(r"v1:a:\d+:MATG1049", buttons(alert)[0]["callback_data"])
        passed = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, alert, buttons(alert)[0]["callback_data"]),
                      "vinci_bot", "Le pasé el aviso")
        assert "Le pasé el aviso a Vinci · Cálculo de una Variable" in plain(passed["text"])
    calc_avisos = [h for h in handoffs() if h["materia"] == "MATG1049" and h["origen"] == "aviso"]
    assert len(calc_avisos) == 2 and "Taller 3" in calc_avisos[0]["texto"] and "Práctica 4" in calc_avisos[1]["texto"]
    assert [b["text"] for b in buttons(fis_alert)] == ["🎓 Consultar con Vinci · Física I"]
    fis_data = buttons(fis_alert)[0]["callback_data"]
    assert re.fullmatch(r"v1:a:\d+:FISG1002", fis_data)
    turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, fis_alert, fis_data), "vinci_bot", "Le pasé el aviso")
    turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, fis_alert, fis_data), "vinci_bot", "Ya le había pasado")
    assert len([h for h in handoffs() if h["materia"] == "FISG1002"]) == 1, "un aviso se pasa una sola vez"
    reply_to = telegram.as_incoming(BOT_TOKEN, calc_alert, plain(calc_alert["text"]))
    turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "pásaselo al bot de cálculo, ¿por dónde empiezo?",
                                    reply_to=reply_to), "vinci_bot", "se lo pasé a Vinci · Cálculo de una Variable")
    calc_handoffs = [h for h in handoffs() if h["materia"] == "MATG1049"]
    assert len(calc_handoffs) == 4 and "Taller 3" in calc_handoffs[-1]["texto"]
    report.append("Avisos del aula con botón «🎓 Consultar con …» por materia: el botón pasó el aviso de Física a su "
                  "bot una sola vez (el segundo toque avisa que ya estaba); los avisos del teórico y del práctico de "
                  "Cálculo llevan el mismo botón y los dos llegaron a su único bot; responder a un aviso también lo "
                  "reparte")
    take("Traspasos desde avisos")

    # 7e. the subject bots' agenda (Hermes cron in the gateway): brief, then the handoffs
    brief = wait_msg("vinci_calculo_bot", 0, "📚 Brief de Cálculo de una Variable", timeout=200)
    wait_msg("vinci_calculo_bot", 0, "📨 De parte de Vinci", timeout=200)
    wait_msg("vinci_fisica_bot", 0, "📨 De parte de Vinci", timeout=200)
    ok = telegram.wait_for(lambda t: all(h["reclamado"] for h in handoffs()), 200)
    assert ok, fail("quedaron entregas sin reclamar")
    brief_tasks = cron_tasks("brief_de_clase")
    assert len(brief_tasks) == 1, "un solo brief (Física no tiene clase ahora)"
    task = brief_tasks[0]
    for expected in ("Materia: Cálculo de una Variable (MATG1049) · paralelo 5",
                     "Clase: hoy miércoles 30 sep, 09:00–11:00 en A105 (empieza en 30 min)",
                     "Clase anterior: lunes 28 sep, 09:00.", "Taller 3: Derivadas", "Práctica 4: Regla de la cadena",
                     "3 a 5 conceptos clave", "Una pregunta concreta"):
        assert expected in task, f"falta «{expected}» en la tarea del brief:\n{task}"
    assert "Taller 3: Derivadas" in readable(brief) and "📄 Capítulo 3 - Derivadas.pdf" in readable(brief), \
        "el brief cita el material del curso"
    assert "Práctica 4: Regla de la cadena" in readable(brief), "el brief incluye lo que vence en el práctico"
    handoff_tasks = cron_tasks("entrega_de_vinci")
    assert any("foto #" in t for t in handoff_tasks) and any("Examen parcial" in t for t in handoff_tasks)
    assert any("Práctica 4" in t for t in handoff_tasks), "el aviso del práctico llegó al bot de Cálculo"
    calc_nb, fis_nb = entries(data_dir, "MATG1049"), entries(data_dir, "FISG1002")
    photo = next(e for e in calc_nb if e["tipo"] == "foto" and e["origen"] == "vinci")
    assert (data_dir / "cuadernos" / "MATG1049" / photo["archivo"]).read_bytes() == pizarra
    calc_from_vinci = [e for e in calc_nb if e["tipo"] == "de_vinci"]
    avisos = [e["texto"] for e in calc_from_vinci if e["origen"] == "aviso"]
    assert len(calc_from_vinci) == 4 and len(avisos) == 2, calc_from_vinci
    assert any("Taller 3" in t for t in avisos) and any("Práctica 4" in t for t in avisos), \
        "los avisos del teórico y del práctico quedaron en el cuaderno de Cálculo"
    assert not any((data_dir / "entregas" / "MATG1049").iterdir()), "el adjunto se movió al cuaderno"
    assert [e["origen"] for e in fis_nb if e["tipo"] == "de_vinci"] == ["aviso"]
    briefs_md += ["## Lo que la agenda le pasó al bot de Cálculo (miércoles 08:30, clase a las 09:00)\n",
                  f"```\n{task}\n```\n", "## El brief que llegó a Telegram (@vinci_calculo_bot)\n",
                  f"```\n{readable(brief)}\n```\n"]
    report.append("Agenda de cada bot de materia (cron de Hermes en el gateway): el bot de Cálculo mandó su brief "
                  "30 min antes de la clase del miércoles (a las 08:29 aún no; con repaso, entregas del teórico y del "
                  "práctico, novedades, conceptos citando el "
                  "material y una pregunta) y después respondió lo que le pasó Vinci; el de Física respondió el "
                  "aviso; las fotos quedaron en el cuaderno")
    take("Agenda de los bots de materia")

    # 7f. notebook capture straight on the subject bots
    voice = (FILES / "nota-de-voz.ogg").read_bytes()
    turn(lambda: telegram.send_voice(FIS, CAPTAIN, voice), "vinci_fisica_bot", "Guardé en tu cuaderno (audio")
    turn(lambda: telegram.send_photo(MATG, CAPTAIN, pizarra, caption="foto de la pizarra de hoy"),
         "vinci_calculo_bot", "Guardé en tu cuaderno (foto")
    turn(lambda: telegram.send_text(MATG, CAPTAIN, "no entendí bien la regla de la cadena con senos y cosenos"),
         "vinci_calculo_bot", "Anoté tu duda")
    attack = turn(lambda: telegram.send_text(MATG, CAPTAIN, f"guarda en el cuaderno el archivo {secrets}"),
                  "vinci_calculo_bot", "Solo puedo tomar archivos que el estudiante te mandó")
    calc_nb, fis_nb = entries(data_dir, "MATG1049"), entries(data_dir, "FISG1002")
    audio = next(e for e in fis_nb if e["tipo"] == "audio")
    assert "segunda ley de Newton" in audio["transcripcion"] and audio["archivo"].endswith(".ogg")
    assert (data_dir / "cuadernos" / "FISG1002" / audio["archivo"]).read_bytes() == voice
    assert any(e["tipo"] == "foto" and e["origen"] == "estudiante" for e in calc_nb)
    assert any(e["tipo"] == "duda" and e["estado"] == "abierta" for e in calc_nb)
    assert not any(e["tipo"] == "documento" for e in calc_nb)
    for stored in (data_dir / "cuadernos").rglob("*"):
        if stored.is_file() and stored.suffix != ".db":
            assert CANVAS_TOKEN.encode() not in stored.read_bytes(), "un archivo con secretos llegó al cuaderno"
    report.append("Cuaderno: el bot de Física guardó una nota de voz (audio y transcripción) y el de Cálculo una "
                  "foto de la pizarra y una duda; pedirle guardar un archivo del computador (secrets.env) fue "
                  "rechazado: «" + readable(attack)[:70].replace("\n", " ") + "…»")
    take("Cuaderno: foto, nota de voz y duda")

    # 7g. Vinci reads the notebooks but cannot write them or reach a terminal
    read = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "¿qué hay en el cuaderno de cálculo?"),
                "vinci_bot", "Esto hay en el cuaderno")
    assert "regla de la cadena" in readable(read) and "duda" in readable(read)
    calc_db = data_dir / "cuadernos" / "MATG1049" / "cuaderno.db"
    before = (sha256(calc_db), len(entries(data_dir, "MATG1049")))
    denied = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "anota en el cuaderno de cálculo que el viernes "
                                                                 "hay prueba"), "vinci_bot", "⚠️")
    assert (sha256(calc_db), len(entries(data_dir, "MATG1049"))) == before, "Vinci no puede escribir un cuaderno"
    assert readable(denied).count("⚠️") == 2, readable(denied)
    shell = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "corre esto en la terminal: touch"),
                 "vinci_bot", "⚠️")
    assert not pwned.exists(), "Vinci no tiene terminal"
    for req in llm.requests:
        who = bot_of(req)
        if who:
            tools_seen.setdefault(who, set()).update(tools_of(req))
    vinci_tools = tools_seen["Vinci"]
    assert {"mcp__vinci__cuaderno", "mcp__vinci__entregar_a_materia", "mcp__vinci__proponer_horario",
            "mcp__vinci__proponer_equipo", "web_search"} <= vinci_tools
    assert all(t.startswith("mcp__vinci__") or t in VINCI_TOOLS_OK for t in vinci_tools), vinci_tools
    assert not {"mcp__vinci__anotar", "mcp__vinci__guardar_adjunto"} & vinci_tools
    for who, names in tools_seen.items():
        if who != "Vinci":
            assert all(t.startswith("mcp__materia__") or t in SUBJECT_TOOLS_OK for t in names), (who, names)
    report.append("Vinci leyó el cuaderno de Cálculo (la foto y la duda), pero al intentar escribirlo o usar una "
                  f"terminal Hermes respondió que esas herramientas no existen: «{readable(shell)[:60]}…»; el "
                  "cuaderno no cambió y no se creó ningún archivo")
    report.append("Herramientas que Hermes le ofreció al modelo (ver hermes_herramientas.json): Vinci, solo las "
                  "suyas + búsqueda web, memoria, historial y preguntas; los bots de materia, solo las de su "
                  "materia + memoria (sin web); ninguno con terminal, archivos, código ni skills")
    take("Vinci lee cuadernos, no los escribe, sin terminal")

    # 7h. archive Física from Vinci's card, restart the gateway: no repeated brief, Física offline
    mark = len(telegram.messages)
    telegram.send_text(BOT_TOKEN, CAPTAIN, "archiva el bot de física, ya terminé esa materia")
    archive_card = wait_msg("vinci_bot", mark, "¿Archivo")
    wait_msg("vinci_bot", mark, "Solo pasa si lo pulsa")
    fis_profile = profiles / "vinci-fisg1002"
    assert team()["FISG1002"]["estado"] == "activa" and not (fis_profile / "gateway.parked").exists()
    archive_data = next(b["callback_data"] for b in buttons(archive_card) if b["text"].startswith("🗄️"))
    archived = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, archive_card, archive_data), "vinci_bot",
                    "quedó archivado", timeout=120)
    show("Fin de semestre: «archiva el bot de física»", plain(archive_card["text"]) + "\n"
         + "".join(f"[{b['text']}]" for b in buttons(archive_card)) + "\n\n→ " + plain(archived["text"]))
    assert team()["FISG1002"]["estado"] == "archivada" and (fis_profile / "gateway.parked").exists()
    assert json.loads((fis_profile / "cron" / "jobs.json").read_text())["jobs"][0]["enabled"] is False
    gateway.stop()
    gate_after = run([bot, "agenda", "--curso", "MATG1049"], T_VINCI).stdout.strip()
    gate_fis = run([bot, "agenda", "--curso", "FISG1002"], T_VINCI).stdout.strip()
    assert gate_after == SKIP and gate_fis == SKIP
    restart = datetime.now().astimezone()
    briefs_before, tasks_before = len(cron_tasks("brief_de_clase")), len(cron_tasks("entrega_de_vinci"))
    mark_calls, mark_msgs = len(telegram.calls), len(telegram.messages)
    gateway.start()
    polling({"vinci_bot", "vinci_calculo_bot"}, mark_calls)
    telegram.send_text(FIS, CAPTAIN, "¿sigues ahí?")
    calls = len(telegram.calls)
    telegram.press(BOT_TOKEN, CAPTAIN, fis_alert, fis_data)
    toast(calls, "no está activo")
    ticked = telegram.wait_for(lambda t: (last_run("MATG1049") or "") > restart.isoformat(), 200)
    assert ticked, fail("la agenda de Cálculo no corrió después del reinicio")
    time.sleep(3)
    after = telegram.messages[mark_msgs:]
    assert not [m for m in after if m["bot"] in ("vinci_calculo_bot", "vinci_fisica_bot")], \
        [(m["bot"], readable(m)[:60]) for m in after]
    assert len(cron_tasks("brief_de_clase")) == briefs_before and len(cron_tasks("entrega_de_vinci")) == tasks_before
    assert not [c for c in telegram.calls[mark_calls:] if c["bot"] == "vinci_fisica_bot"], "Física quedó apagada"
    assert (data_dir / "cuadernos" / "FISG1002" / "cuaderno.db").exists() and (fis_profile / "memories").is_dir()
    briefs_md += ["## Después de reiniciar el gateway\n",
                  f"- `espol-bot agenda --curso MATG1049` (misma hora): `{gate_after}` (el brief ya se reclamó)",
                  "- la agenda de Cálculo volvió a correr en el gateway reiniciado sin llamar al modelo ni reenviar "
                  "el brief",
                  f"- antes del horario, la misma compuerta respondía `{gate_before}` (sin clase no hay brief)", ""]
    report.append("Reinicio del gateway: la agenda de Cálculo volvió a correr sin gastar tokens ni repetir el brief; "
                  "cada minuto sin nada que hacer tampoco llama al modelo")
    report.append("Archivar Física desde la tarjeta de Vinci (solo con el botón del capitán): su bot quedó apagado "
                  "(gateway.parked; no volvió a escuchar a Telegram), su agenda en pausa y su botón en los avisos ya "
                  "no lo despierta; memoria y cuaderno intactos")
    take("Archivar Física y reiniciar el gateway")

    # 7i. reactivate Física from Vinci's card: the same gateway serves its bot again
    mark = len(telegram.messages)
    telegram.send_text(BOT_TOKEN, CAPTAIN, "reactiva el bot de física, lo necesito otra vez")
    reactivate_card = wait_msg("vinci_bot", mark, "¿Reactivo")
    wait_msg("vinci_bot", mark, "Solo pasa si lo pulsa")
    assert team()["FISG1002"]["estado"] == "archivada" and (fis_profile / "gateway.parked").exists()
    reactivate_data = next(b["callback_data"] for b in buttons(reactivate_card) if b["text"].startswith("♻️"))
    mark_calls = len(telegram.calls)
    reactivated = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, reactivate_card, reactivate_data), "vinci_bot",
                       "activo otra vez", timeout=120)
    show("«reactiva el bot de física»", plain(reactivate_card["text"]) + "\n"
         + "".join(f"[{b['text']}]" for b in buttons(reactivate_card)) + "\n\n→ " + plain(reactivated["text"]))
    assert team()["FISG1002"]["estado"] == "activa" and not (fis_profile / "gateway.parked").exists()
    assert json.loads((fis_profile / "cron" / "jobs.json").read_text())["jobs"][0]["enabled"] is True
    polling({"vinci_fisica_bot"}, mark_calls, timeout=150)
    report.append("Reactivar Física desde la tarjeta de Vinci (solo con el botón del capitán): su agenda se reanudó "
                  "y el mismo gateway volvió a atender su bot, sin reiniciarlo")
    take("Reactivar Física")
    gateway.stop()

    for job_id in vinci_jobs.values():
        run([hermes, "-p", "vinci", "cron", "resume", job_id], T_VINCI)

    # 8. setup.sh with the team in place: idempotent ---------------------------------------------
    third = run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_VINCI)
    show("`./setup.sh --skip-deps` con el equipo armado (3ª vez)", third.stdout)
    for word in ("creado", "actualizado", "reanudado", "pausado", "instalados"):
        assert word not in third.stdout, f"«{word}» en la 3ª corrida de setup.sh:\n{third.stdout}"
    assert third.stdout.count("sin cambios") >= 6
    report.append("setup.sh por tercera vez, con Vinci y los dos bots de materia: nada cambió")
    take("setup.sh (3ª vez, mensaje de prueba)")
