"""End-to-end run of Vinci on WhatsApp against a fake Canvas, a fake WhatsApp bridge and a scripted LLM, with the real
Hermes Agent when it is installed. Vinci lives on WhatsApp alone (`[channels] telegram = false`, the repo's setting);
where the Telegram Bot API would be, a tripwire fails the test on any request.

Everything runs as real processes (the same commands Hermes cron, the gateway and the captain run) in a throwaway HOME
with its own XDG folders and no D-Bus session: the real ~/.hermes, ~/.claude, ~/.local and user services are never
touched. Each test builds its own install (`world`), so pytest-xdist runs them in parallel:

test_canvas, no gateway:
  1. setup.sh twice: a legacy «espol» profile becomes Vinci with its memory; the second run changes nothing; a toolset
     switched on in config.toml leaves the blocked list and a typo is refused.
  2. `aula` CLI commands against the first fixture state: the material catalog (a module's subheader, folders, a copy
     from 2025, a big book, a guide only an assignment links to, an announcement's attachment) and its outside links;
     a file and its copy downloaded on demand.
  3. Vinci's polls, then the fixtures change (new assignment, due-date change, new announcement, posted grade, new
     material, the syllabus, a new module link, a submission), then polls 2-4 and the 07:00 summary (twice: the second
     must not resend), each in the captain's WhatsApp chat, a reminder's «Ya lo entregué» as a poll. Only syllabi
     download on their own; while poll 2 slowly downloads the new one, `aula cursos --actualizar` must not wait for it.
     Then reading quizzes, against a Canvas of their own: a new quiz's alert and reminders carry its questions, time
     limit, attempts and when it opens and closes; a test open for 30 minutes warns before it opens, once; each quiz
     is read once (again only when it changes), never one already closed, and never its questions.
  4. retrieval: sample questions must hit the right file and page, never two copies of one page.
  5. a fresh install where two resources fail at different polls: the rest keeps working, one alert per failure
     episode and resource.
  6. Canvas tokens rotate through three generations without interrupting polls. When every token dies, maintenance
     says the chain is cut (never that a replacement works) and stops calling Canvas with the dead tokens; the alert
     itself carries the token form's link (valid 24 h); the captain fills it 26 min later, it comes back sealed through the relay, and the
     chain comes back; a hidden CLI reseed also works. `espol-bot doctor` reads each of those moments without calling
     Canvas or the chat.

test_whatsapp_captain, the gateway serving the captain's chat: setup.sh routes his WhatsApp to Vinci (and anyone else
  to Vinci's guest tools); his week; work handed in outside the aula stays pending and late until he says it is done
  (and back with «todavía no»), an exam held in class leaves on its own, and the summary lists the same; /start and /token without the model; the 07:00 summary in WhatsApp's format; the
  brief before a class as a system task Vinci answers in his chat; Vinci writes the notebook of the subject he names,
  and a note with no subject goes to the one he named a moment ago (the focus in every turn's context); a /quiz left
  half answered stays open in that context («respondió 1 de 2») and «sigamos con el quiz» re-sends only the missing
  poll; «tengo 20 minutos» plans from his open doubts and saves what he struggled with to the notebook, and a jury
  first asks what it judges; a PDF waiting for his vote shows in every private turn as not handed in; `vinci-check say` talks to it;
  `espol-bot panel` shows the gateway, health, jobs, spend and his chat step by step.

test_whatsapp_friend: a group the captain turns on, a note that holds in that group only (every turn ends with the clock
  and that chat's notes), reminders he asks for there that the agenda sends to the group at their time, once (one
  missed by days never goes out), and its notices (a reminder before a class; trusted, a friend's
  news tagging him, once); his friend Angel invited with a Vinci of his own (his token through
  the page and Vinci's relay, his week next to the captain's in the group, slides, mentions, an assignment found by
  its words and searched in its own attachments first, a PDF summary that refuses a citation of an unread page, a quote, a sticker, a group
  that goes idle, a poll for a button, a quiz a guest asks for in the group: one results message once the guest, Angel
  and the captain answered it all, and another quiz that closes after its 15 minutes; his dashboard, his commands);
  voice notes and audio files heard by the real local
  Whisper (in a group, only one that says «Vinci»; a silent one is said to be unheard, never guessed at); his alerts; the block for whoever is not a Vinci's owner; Angel
  removed with his tokens.

test_academico: ESPOL's Académico (FakePortal: ASP.NET Web Forms, two-step login, a BotDetect CAPTCHA). The captain
  asks for his GPA with no copy; the tool asks for a sign-in and a «🎓 Conectar Académico» button reaches his chat. On
  its page (in a real headless Chromium when there is one) he gives his user, then a wrong CAPTCHA and the right one;
  one portal session reads every section, the copy is saved with its date and term, and his question comes back to
  Vinci by itself in the same Hermes session. Later questions are answered from the copy; «actualiza mi Académico»
  brings a second sign-in and the portal's new figures. No credential reaches the model, a chat, the relay in clear, a
  log or the data folder, and the sign-in's process exits.

The artifacts go to artifacts/e2e/ (override with E2E_ARTIFACT_DIR): REPORTE.md, tiempos.md, and fallo-<test>.md for a
test that failed. Ports and temporary paths are normalized, so reruns produce comparable files.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import html
import itertools
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pypdf
import pytest
import requests
import yaml

from aula_core.config import parse_env_file
from espol_bot import quiz as quiz_module
from espol_bot.config import DEFAULT_TOKEN_FORM_URL

HERE = Path(__file__).parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from fake_servers import (  # noqa: E402
    PORTAL_CARD, PORTAL_PASSWORD, PORTAL_USER, FakeCanvas, FakeDSpace, FakePages, FakePortal, FakeRelay, FakeWeb,
    FakeWhatsApp, ScriptedLLM, Tripwire)
from hermes_harness import find_hermes  # noqa: E402

ARTIFACT = Path(os.environ.get("E2E_ARTIFACT_DIR") or REPO / "artifacts" / "e2e")  # tests/conftest.py's too
TRACE: dict = {}  # this test's world, for the trace page tests/conftest.py writes when it fails
GROUP_IDLE = 25  # seconds a WhatsApp group stays one conversation here (4 h live)
BOOK_ASK = "📘 *El libro principal de "
GROUP_REMINDER = "Historias de usuario en formato requerimiento: se entregan el vie 2 oct"


@pytest.fixture(autouse=True)
def timings(request, monkeypatch):
    """Where each test waits, by line of this file, slowest first: artifacts/e2e/tiempos.md (conftest.py merges)."""
    spent: dict[str, list] = {}

    depth = [0]  # only the outermost wait counts: a sleep inside wait_for is the same time

    def timed(kind, fn):
        def wrapper(*args, **kwargs):
            if threading.current_thread() is not threading.main_thread() or depth[0]:
                return fn(*args, **kwargs)
            start = time.monotonic()
            depth[0] += 1
            try:
                return fn(*args, **kwargs)
            finally:
                depth[0] -= 1
                frames, frame = [], sys._getframe(1)
                while frame:
                    if frame.f_code.co_filename == __file__:
                        frames.append(frame)
                    frame = frame.f_back
                if frames:  # the step in the test (or in the flow it calls), not the helper that waited
                    top = frames[-1]
                    if top.f_code.co_name.startswith("test_") and len(frames) > 1 and \
                            frames[-2].f_code.co_name.endswith("_flow"):
                        top = frames[-2]
                    entry = spent.setdefault(f"{top.f_code.co_name}:{top.f_lineno}", [0.0, 0, set()])
                    entry[0] += time.monotonic() - start
                    entry[1] += 1
                    entry[2].add(kind)
        return wrapper

    for owner, name in [(time, "sleep"), (subprocess, "run"), (subprocess.Popen, "communicate"),
                        (FakeWhatsApp, "wait_for"), (Gateway, "stop")]:
        monkeypatch.setattr(owner, name, timed(name, getattr(owner, name)))
    start = time.monotonic()
    yield
    total = time.monotonic() - start
    rows = sorted(spent.items(), key=lambda kv: -kv[1][0])
    lines = [f"## {request.node.name}: {total / 60:.1f} min\n", "| línea | s | veces | qué |", "|---|---|---|---|"]
    lines += [f"| {where} | {s:.1f} | {n} | {', '.join(sorted(kinds))} |" for where, (s, n, kinds) in rows[:25]]
    parts = ARTIFACT / "partes"
    parts.mkdir(parents=True, exist_ok=True)
    (parts / f"{request.node.name}.tiempos.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


CANVAS_TOKEN = "7~prueba-token-de-canvas"
NEW_CANVAS_TOKEN = "7~nuevo-token-de-canvas"  # after the aula virtual refused the first one
AUTO_FORM_TOKEN = ("Automatico5SinPedirlo" * 4)[:64]   # pasted in the form Vinci sent on its own
ROLEPLAY = ("personaje", "personalidad", "Guía Académico", "aventurero", "El Analítico", "El Conector")
# WhatsApp (Vinci's number, through Hermes' bridge): the captain, his friend Angel, someone else in the group.
CAPTAIN_WA, ANGEL_WA, STRANGER_WA = "593980000001", "593990000002", "593990000003"
CAPTAIN_LID = "770000000000001"  # how WhatsApp names the captain when it hides his number
CAPTAIN_JID = f"{CAPTAIN_WA}@s.whatsapp.net"
GROUP_WA = "120363000000000001@g.us"
ANGEL_TOKEN = ("AngelTokenDelAula8" * 4)[:64]  # Angel's own aula token, pasted in the page Vinci sends him
CAPTAIN_WA_TOKEN = ("CapitanTokenWhatsApp9" * 4)[:64]  # a new one for the captain, after his /token on WhatsApp
SLIDES = {"titulo": "Integrales dobles", "subtitulo": "Cálculo de varias variables",
          "diapositivas": [{"titulo": "¿Qué es una integral doble?", "puntos": ["Volumen bajo una superficie",
                                                                                "Se integra en una región R"]},
                           {"titulo": "Cómo se calcula", "puntos": ["Teorema de Fubini", "Orden dx dy o dy dx"],
                            "notas": "Mostrar un ejemplo en el pizarrón."}]}
SUMMARY = {"titulo": "Taller 2: Integrales dobles", "subtitulo": "Cálculo de varias variables",
           "introduccion": "Lo que pide el taller, para repasar antes de resolverlo."}
SUMMARY_STEPS = ["Copia el enunciado", "Resuelve en su hoja", "Junta todo en un PDF"]
SUMMARY_FAKE_CITE = "📄 [Capítulo 9 - Inventado.pdf, página 99](https://aulavirtual.espol.edu.ec/courses/1/files/9)"
VENV_BIN = Path(sys.executable).parent
FILES = HERE / "fixtures" / "files"
MARKER = "Generado por setup.sh de espol-academic-bot"

# Timeline, America/Guayaquil (UTC-5)
T_SETUP = "2026-09-28T06:30:00-05:00"
T_POLL1 = "2026-09-28T07:40:00-05:00"   # Deber 2 vence 10:00 → recordatorio de 3 h
T_POLL2 = "2026-09-29T00:30:00-05:00"   # después de los cambios; Taller 2 vence en 22.5 h
T_POLL3 = "2026-09-29T01:00:00-05:00"   # sin cambios: no debe enviar nada
T_SUMMARY = "2026-09-29T07:00:00-05:00"
T_POLL4 = "2026-09-29T20:30:00-05:00"   # Taller 2 vence en 2.5 h → recordatorio de 3 h
T_RESILIENCE = [f"2026-09-30T{12 + i // 2}:{i % 2 * 30:02d}:00-05:00" for i in range(9)]  # 12:00 … 16:00
# Work the aula takes no upload for, in Física, all due before T_VINCI: a lab on another platform, an exam held in
# class, and one whose instructions do not say how it is handed in.
ELSEWHERE_TASKS = [
    (3101, "Práctica 2 en el simulador", ["none"], "2026-09-28T04:59:59Z",
     "<p>Resuelve la práctica 2 en la plataforma del simulador y sube allí tu captura final: "
     "<a href=\"https://simulador.example.org/p2\">simulador</a>. En el aula no hay entregable.</p>"),
    (3102, "Lección 2", ["on_paper"], "2026-09-29T13:00:00Z", ""),
    (3103, "Trabajo de vectores", ["none"], "2026-09-29T04:59:59Z", "<p>Trabajo grupal sobre vectores. Revisen la guía "
                                                                    "del capítulo 3.</p>"),
]
T_VINCI = "2026-09-30T08:30:00-05:00"   # sesión del gateway: miércoles, 30 min antes de Cálculo (09:00)
T_NO_TELEGRAM = "2026-10-07T08:30:00-05:00"  # Telegram off: the next Wednesday, 30 min before Cálculo
T_RENEW_0 = "2026-09-29T21:00:00-05:00"
T_RENEW_1 = "2026-09-29T21:41:00-05:00"
T_RENEW_2 = "2026-09-29T22:22:00-05:00"
T_RENEW_3 = "2026-09-29T23:03:00-05:00"
T_RENEW_4 = "2026-09-29T23:33:00-05:00"  # the probe (born 22:22) turns 70 minutes old
T_RENEW_5 = "2026-09-29T23:43:00-05:00"
T_RENEW_6 = "2026-09-29T23:59:00-05:00"  # 26 min after the cut: a /token form (15 min) would have expired

QUESTIONS = [
    ("¿Qué es la regla de la cadena?", "Capítulo 3 - Derivadas.pdf", 2),
    ("explícame el movimiento parabólico", "Semana 2 - Cinemática.pptx", 3),
    ("ejercicio 4 maximizar el área del rectángulo", "Capítulo 3 - Derivadas.pdf", 3),
]

# What the model "reads" from the screenshot: the first time with one mistake (Wednesday's
# Cálculo at 10:00), then corrected by the captain. Cálculo's práctico keeps the screenshot's label.
SCHEDULE_V1 = [
    {"materia": "MATG1049", "dia": "lunes", "inicio": "09:00", "fin": "11:00", "aula": "A105", "paralelo": "5"},
    {"materia": "MATG1049", "dia": "lunes", "inicio": "11:00", "fin": "12:00", "aula": "LAB 11C", "paralelo": "105"},
    {"materia": "MATG1049", "dia": "miércoles", "inicio": "10:00", "fin": "12:00", "aula": "A105", "paralelo": "5"},
    {"materia": "MATG1049 - CÁLCULO DE UNA VARIABLE Paralelo N°105", "dia": "viernes", "inicio": "10:00",
     "fin": "12:00", "aula": "LAB 11C", "paralelo": "105"},
    {"materia": "FISG1002", "dia": "martes", "inicio": "14:30", "fin": "16:30", "aula": "L204", "paralelo": "3"},
    {"materia": "FISG1002", "dia": "jueves", "inicio": "14:30", "fin": "16:30", "aula": "L204", "paralelo": "3"},
]
SCHEDULE_V2 = [dict(c, inicio="09:00", fin="11:00") if c["dia"] == "miércoles" else c for c in SCHEDULE_V1]

# What the captain asks Vinci to note («anota: …») and what the model makes of it (today is Wednesday 30 Sep).
TODOS = {
    "estudiar cap. 3 de Física para el viernes": {"text": "Estudiar cap. 3", "subject": "Física", "due": "2026-10-02"},
    "llevar el certificado de matrícula a secretaría hoy a las 11:00": {
        "text": "Llevar el certificado de matrícula a secretaría", "due": "2026-09-30 11:00"},
    "leer el paper que recomendó el profe de Cálculo": {"text": "Leer el paper que recomendó el profe",
                                                        "subject": "cálculo"},
    "devolver el libro a la biblioteca el lunes": {"text": "Devolver el libro a la biblioteca", "due": "2026-09-28"},
}
SUBMITTED = "✅ Ya lo entregué"

# «cítame el material sobre …» (to a subject bot, or «… de Cálculo sobre …» to Vinci): (search, its English,
# what the model knows when the material has nothing on it)
CITED = {
    "la regla de la cadena": ("regla de la cadena", "chain rule", None),
    "la transformada de Laplace": ("transformada de Laplace", "Laplace transform",
                                   "la transformada de Laplace convierte una función del tiempo en una función de s "
                                   "y sirve para resolver ecuaciones diferenciales."),
}

FIS_SCHEME = {
    "periods": [{"name": "Primer parcial", "weight": 50,
                 "exception": "Sin examen por El Niño: todo el parcial son deberes y laboratorio.",
                 "components": [{"name": "Deberes", "weight": 50, "match": ["tarea", "taller"]},
                                {"name": "Laboratorio", "weight": 50, "match": ["informe"]}]},
                {"name": "Segundo parcial", "weight": 50, "components": [
                    {"name": "Examen", "weight": 60, "match": ["examen"]},
                    {"name": "Laboratorio", "weight": 20, "match": ["informe"]},
                    {"name": "Deberes", "weight": 20, "match": ["tarea", "taller"]}]}],
    "sources": ["Me lo dijo el estudiante el 30 sep"]}

# The Académico (academic_record): what the captain asks → (topic, whether he asks to update the copy).
PORTAL_ASKS = {
    "cuál es mi promedio y cuántas materias aprobé": ("historial", False),
    "qué materias aprobé": ("historial", False),
    "cuándo son mis exámenes finales": ("examenes", False),
    "cuánto me falta para graduarme": ("avance", False),
    "actualiza mi Académico y dime mi promedio": ("promedio", True),
}
PORTAL_BACK = "Ya conecté mi Académico"  # how the question comes back after the sign-in (portal_login.py)


IMAGE_RE = re.compile(r"\[Image attached at: ([^\]]+)\]")
REPLY_RE = re.compile(r'\[Replying to[^:]*: "(.+?)"\]', re.S)
QUIZ_SKILL = 'invoked the "quiz" skill'
QUIZ_TOPIC = re.compile(r"instruction alongside the skill invocation: (.+)$", re.M)


# -- the model's side ------------------------------------------------------------------------


NODE = shutil.which("node")


def page_seal(url: str, token: str) -> str:
    """What the page does with the token the captain pastes: docs/token/form.js on Node's WebCrypto."""
    key = parse_qs(urlsplit(url).query)["k"][0]
    if NODE is None:  # the same RSA-OAEP / SHA-256 the page uses, without the page itself
        from cryptography.hazmat.primitives import serialization
        from espol_bot.token_form import OAEP
        public = serialization.load_der_public_key(base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)))
        return "v1." + base64.urlsafe_b64encode(public.encrypt(token.encode(), OAEP)).decode().rstrip("=")
    script = (f"const page = await import({json.dumps((REPO / 'docs' / 'token' / 'form.js').as_uri())});"
              "if (!page.TOKEN_RE.test(process.argv[2])) { console.error('the page refuses it'); process.exit(3); }"
              "process.stdout.write(await page.seal(process.argv[1], process.argv[2]));")
    proc = subprocess.run([NODE, "--input-type=module", "-e", script, key, token], capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _node_module(path: Path, call: str, *args: str) -> None:
    script = f"const page = await import({json.dumps(path.as_uri())}); {call}"
    proc = subprocess.run([NODE, "--input-type=module", "-e", script, *args], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def page_send(url: str, token: str) -> None:
    """The page opened from WhatsApp with Vinci's relay (?r=, #m=): it seals the token and posts it there
    (docs/token/form.js's own deliver)."""
    sealed, relay, mailbox = page_seal(url, token), parse_qs(urlsplit(url).query)["r"][0], urlsplit(url).fragment[2:]
    if NODE is None:
        requests.post(f"{relay}/m/{mailbox}", json={"kind": "token", "sealed": sealed}, timeout=10).raise_for_status()
        return
    _node_module(REPO / "docs" / "token" / "form.js",
                 "await page.deliver(process.argv[1], process.argv[2], process.argv[3]);", relay, mailbox, sealed)


def page_tick(snapshot: dict, item: str, done: bool = True) -> None:
    """A tick on the dashboard opened from WhatsApp with the relay: docs/dashboard/dashboard.js's postMark."""
    if NODE is None:
        requests.post(f"{snapshot['relay']}/m/{snapshot['mailbox']}", json={"kind": "mark", "id": item, "done": done},
                      timeout=10).raise_for_status()
        return
    _node_module(REPO / "docs" / "dashboard" / "dashboard.js",
                 "if (!(await page.postMark(JSON.parse(process.argv[1]), process.argv[2], process.argv[3] === '1')))"
                 " process.exit(4);", json.dumps(snapshot), item, "1" if done else "0")


def flatten(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def bot_of(req: dict) -> str | None:
    """Which bot a request comes from: its SOUL.md («Eres **Vinci**, el bot principal…», «Eres el bot de la
    materia **Física I**…»)."""
    messages = req.get("messages") or []
    for role in ("system", None):
        text = "\n".join(flatten(m.get("content")) for m in messages if role is None or m.get("role") == role)
        match = re.search(r"Eres \*\*(Vinci)\*\*, el bot principal|Eres el bot de la materia \*\*([^*]+)\*\*", text)
        if match:
            return match[1] or match[2]
        match = re.search(r"Eres \*\*Vinci\*\*, el asistente académico de \*\*([^*]+)\*\*", text)
        if match:  # a friend's own Vinci (amigos.py)
            return f"amigo:{match[1]}"
    return None


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


# Past exams the captain asks to solve: (the names the model searches DSpace by, the filters it adds).
EXAMS_TO_SOLVE = {
    "resuélveme el primer parcial más reciente": (["cálculo de una variable"], {"evaluation": "1er parcial"}),
    "resuélveme el examen de POO del 2026": (["programación orientada a objetos"], {"from_year": 2026}),
    "resuélveme el primer parcial 2025-2S de cálculo": (["cálculo de una variable"],
                                                        {"from_year": 2025, "to_year": 2025, "evaluation": "1er parcial"}),
}


def read_if_there(path: Path) -> bytes:
    """A file's bytes; nothing when the gateway removed it (a temporary state file) after it was listed."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


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
            return self.vinci(text, called, results)
        if bot.startswith("amigo:"):
            return self.friend(text, called, results)
        return {"content": f"(sin guion para {bot})"}

    def friend(self, text: str, called: list[str], results: list[str]) -> dict:
        """A friend's Vinci on WhatsApp: their week, what an assignment asks for, and slides whose file goes back to
        the chat."""
        if "anota: repasar integrales dobles" in text:
            if not called:
                return _call("mcp__vinci__add_todo", text="repasar integrales dobles")
            return {"content": "Anotado: repasar integrales dobles."}
        if "qué pide el taller 2" in text:
            if not called:
                return _call("mcp__vinci__tareas")
            if called == ["mcp__vinci__tareas"]:
                taller = next(t for t in _json(results[-1]) if t["tarea"].startswith("Taller 2"))
                return _call("mcp__vinci__ver_tarea", tarea_id=taller["id"])
            if called[-1] == "mcp__vinci__ver_tarea":
                template = next(f for f in _json(results[-1])["archivos"] if f["archivo"].endswith(".doc"))
                return _call("mcp__vinci__leer_archivo", archivo_id=template["archivo_id"])
            task, template = _json(results[-2]), _json(results[-1])["contenido"][0]
            rubric = "; ".join(f"{c['criterio']}, {c['puntos']:g} pts" for c in task["rubrica"]["criterios"])
            return {"content": f"El Taller 2 pide esto: {task['consigna']}\nVence {task['vence']}; el aula lo recibe "
                               f"atrasado hasta {task['cierra']}. Rúbrica: {rubric}.\nAnexos: "
                               + ", ".join(f["archivo"] for f in task["archivos"])
                               + f". La plantilla pide: {template['texto']} ({template['cita']})"}
        if "en el taller de integrales" in text:
            if not called:
                return _call("mcp__vinci__tareas", buscar="taller integrales")
            if called == ["mcp__vinci__tareas"]:
                first = _json(results[-1])["candidatas"][0]
                return _call("mcp__vinci__buscar_material", pregunta="ejercicio hoja enunciado", tarea_id=first["id"])
            official = [h for h in _json(results[-1])["resultados"] if h.get("de_la_tarea")]
            return {"content": "\n".join(f"La tarea dice: {h['fragmento']} {h['cita']}" for h in official)
                    or _problem(results[-1])}
        if "resumen en pdf del taller de integrales" in text:
            if not called:
                return _call("mcp__vinci__tareas", buscar="taller integrales")
            if called == ["mcp__vinci__tareas"]:
                first = _json(results[-1])["candidatas"][0]
                return _call("mcp__vinci__buscar_material", pregunta="ejercicio hoja enunciado", tarea_id=first["id"])
            last = _json(results[-1])
            if isinstance(last, dict) and last.get("ruta"):
                return {"content": f"Tu resumen tiene {last['paginas']} página(s):\n{last['ruta']}"}
            hits = next(d["resultados"] for d in map(_json, results) if isinstance(d, dict) and d.get("resultados"))
            hit, pdf_hit = hits[0], next(h for h in hits if h["archivo"].endswith(".pdf"))
            # The first try also cites a page it never read: the tool refuses it, and the model drops it.
            sources = [hit["cita"]] + ([] if called.count("mcp__vinci__crear_resumen") else [SUMMARY_FAKE_CITE])
            return _call("mcp__vinci__crear_resumen", **SUMMARY, secciones=[
                {"titulo": "1. Qué pide el taller", "texto": f"El enunciado dice: **{hit['fragmento'][:200]}**",
                 "puntos": ["Cada ejercicio va aparte", "Se entrega un solo PDF"], "fuentes": sources,
                 "visual": {"tipo": "flujo", "titulo": "Cómo entregarlo", "pasos": SUMMARY_STEPS}},
                {"titulo": "La hoja del profe", "texto": "Así se ve la especificación.",
                 "visual": {"tipo": "pagina", "titulo": "La especificación", "archivo_id": pdf_hit["archivo_id"],
                            "pagina": pdf_hit["pagina"]}}],
                para_recordar=["Un ejercicio por hoja", "Un solo PDF"])
        if results:
            last = _json(results[-1])
            if isinstance(last, dict) and last.get("ruta"):
                return {"content": f"Tu presentación tiene {last['diapositivas']} diapositivas:\n{last['ruta']}"}
            return {"content": self.vinci_answer(results)}
        if "qué tengo esta semana" in text:
            return _call("mcp__vinci__semana")
        if "diapositivas" in text:
            return _call("mcp__vinci__crear_diapositivas", **SLIDES)
        return {"content": "Hola, soy tu Vinci. ¿En qué te ayudo?"}

    def exams(self, prefix: str, text: str, called: list[str], results: list[str]) -> dict | None:
        """Past exams from DSpace: a list found by a second name after a first one finds nothing, and an exam solved
        question by question, each citing its page."""
        find, open_ = f"mcp__{prefix}__find_past_exams", f"mcp__{prefix}__open_past_exam"
        last = _json(results[-1]) if results else None
        if "exámenes anteriores de POO" in text:
            if not called:
                return _call(find, names=["POO"])
            if called == [find]:
                return _call(find, names=["programación orientada a objetos", "prog orientada objetos"])
            return {"content": "Encontré estos exámenes de Programación Orientada a Objetos en DSpace:\n" + "\n".join(
                f"- {e.get('period', 'sin fecha')} · {e.get('evaluation', 'examen')}"
                + (f" · paralelo {e['group']}" if e.get("group") else "") + f": {e['url']}" for e in last["exams"])}
        for ask, (names, filters) in EXAMS_TO_SOLVE.items():
            if ask in text:
                if not called:
                    return _call(find, names=names, **filters)
                if called == [find]:
                    return _call(open_, exam_id=last["exams"][0]["exam_id"])
                questions = [f"- {line} ({page['cita']})" for page in last["contenido"]
                             for line in page["texto"].splitlines() if line.startswith("Tema")]
                return {"content": f"Resolución de {last['archivo']}:\n" + "\n".join(questions)
                                   + "\nLa resolución es mía, no la oficial del profesor."}
        return None

    def pending(self, text: str, called: list[str], results: list[str]) -> dict | None:
        """Física's pending list with how each is handed in; «ya hice …» marks the lab done, «todavía no» undoes it,
        and «se entrega por correo» says how the unclear one is handed in."""
        if "qué tengo pendiente en Física" in text:
            if not called:
                return _call("mcp__vinci__tareas", materia="física")
            return {"content": "Pendiente en Física:\n" + "\n".join(
                f"- {t['tarea']} [{t['delivery']}{', atrasada' if t['atrasada'] else ''}]" for t in _json(results[-1]))}
        for ask, name, extra in (("ya hice la práctica del simulador", "Práctica 2", {}),
                                 ("la práctica del simulador todavía no", "Práctica 2", {"entregada": False}),
                                 ("el trabajo de vectores se entrega por correo", "Trabajo de vectores", None)):
            if ask not in text:
                continue
            if not called:
                return _call("mcp__vinci__ver_tarea", tarea_id=next(t[0] for t in ELSEWHERE_TASKS if t[1].startswith(name)))
            if len(called) == 1 and extra is None:
                return _call("mcp__vinci__set_assignment_delivery", tarea_id=_json(results[-1])["id"],
                             delivery="external_submission")
            if len(called) == 1:
                return _call("mcp__vinci__marcar_entregada", tarea_id=_json(results[-1])["id"], **extra)
            return {"content": self.vinci_answer(results[-1:])}
        return None

    def vinci(self, text: str, called: list[str], results: list[str]) -> dict:
        task = re.search(r"\[Tarea del sistema para (.+?) \(", text)
        if task and "TAREA: brief_de_clase" in text:  # Telegram off: the brief comes to Vinci's chat as a task
            return {"content": f"📚 Brief de {task[1]}: repasa lo de la clase anterior y revisa lo que vence."}
        if "en el cuaderno de Cálculo pon que hoy vimos integrales dobles" in text and not called:
            return _call("mcp__vinci__anotar", materia="Cálculo", tipo="clase", texto="Integrales dobles",
                         fecha_clase="2026-09-30")
        if "pon en el cuaderno que no entendí la regla de L'Hôpital" in text and not called:
            return _call("mcp__vinci__anotar", tipo="duda", texto="La regla de L'Hôpital")
        if "háblanos en plural" in text and not called:
            return _call("mcp__vinci__chat_note", text="Hablarles en plural, como «nosotros»")
        if "recuérdanos" in text and not called:
            return _call("mcp__vinci__group_reminder", text=GROUP_REMINDER, at=["2026-10-01 09:00", "2026-10-02 12:00"])
        flow = (self.portal(text, called, results) or self.exams("vinci", text, called, results)
                or self.vinci_material(text, called, results) or self.pending(text, called, results)
                or self.vinci_study(text, called, results) or self.group_quiz(text, called, results))
        if flow is not None:
            return flow
        if results:
            return {"content": self.vinci_answer(results)}
        if QUIZ_SKILL in text:
            topic = QUIZ_TOPIC.search(text)
            if not topic:
                return {"content": "¿De qué tema y de qué materia quieres el quiz?"}
            return _call("mcp__vinci__entregar_a_materia", materia="cálculo",
                         mensaje=f"/quiz {topic[1].replace(' de cálculo', '')}")
        for trigger, todo in TODOS.items():
            if f"anota: {trigger}" in text:
                return _call("mcp__vinci__add_todo", **todo)
        if "cómo voy en notas" in text:
            return _call("mcp__vinci__grade_status")
        if "en Física no hay examen en el primer parcial" in text:
            return _call("mcp__vinci__propose_grading_scheme", subject="física", **FIS_SCHEME)
        if "qué tengo esta semana" in text:
            return _call("mcp__vinci__semana")
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
        if "el libro de Física es" in text:
            return _call("mcp__vinci__libro_principal", materia="física", titulo="Serway")
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
    def vinci_study(text: str, called: list[str], results: list[str]) -> dict | None:
        """/quiz on WhatsApp: questions from the notebook, sent as polls; left for something else and taken up again
        («sigamos con el quiz»), which sends back only the ones still unanswered."""
        if "Hazme un quiz corto de integrales dobles" in text:
            if not called:
                return _call("mcp__vinci__cuaderno", materia="cálculo")
            if called == ["mcp__vinci__cuaderno"]:
                entries = _json(results[-1])["entradas"][:2]
                return _call("mcp__vinci__send_quiz", materia="cálculo", topic="Integrales dobles", questions=[
                    {"question": f"¿Qué anotaste el {e['creado'][:10]} (#{e['id']})?",
                     "options": [e["texto"], "La serie de Taylor", "Nada"], "answer": e["texto"],
                     "explanation": "Lo dice tu cuaderno.", "entry_id": e["id"]} for e in entries])
            data = _json(results[-1])
            return {"content": f"📝 Te mandé el quiz: {data['questions']} preguntas como encuestas."
                    if isinstance(data, dict) and data.get("quiz") else _problem(results[-1])}
        if "tengo 20 minutos para Cálculo" in text:
            if not called:
                return _call("mcp__vinci__study_activity", action="start", kind="study", materia="cálculo", minutes=20,
                             topic="Límites")
            plan = _json(results[-1])["para_planear"]
            return {"content": "⏱️ 20 minutos. Empecemos por tu duda: " + "; ".join(plan["dudas_abiertas"])}
        if "me costó el 0/0" in text:
            if not called:
                return _call("mcp__vinci__study_activity", action="progress", done="Ejercicio 1 de L'Hôpital",
                             struggled="límites 0/0")
            return {"content": "Anotado. Sigamos con otro."}
        if "guarda lo que me costó" in text:
            if not called:
                return _call("mcp__vinci__study_activity", action="finish", done="Repasamos L'Hôpital", save_weak=True)
            data = _json(results[-1])
            return {"content": "Listo. En tu cuaderno: " + "; ".join(data.get("guardado_en_cuaderno") or ["nada"])}
        if "hazme de jurado" in text:
            if not called:
                return _call("mcp__vinci__study_activity", action="start", kind="jury", materia="física",
                             topic="Exposición de vectores")
            return {"content": _problem(results[-1])}
        if "sigamos con el quiz" in text:
            if not called:
                return _call("mcp__vinci__study_activity", action="resume")
            data = _json(results[-1])
            return {"content": data.get("message") if isinstance(data, dict) and data.get("message")
                    else _problem(results[-1])}
        return None

    @staticmethod
    def group_quiz(text: str, called: list[str], results: list[str]) -> dict | None:
        """A guest asks for a quiz in the group: two questions from the syllabus page buscar_material finds."""
        if "quiz del sílabo de cálculo" not in text:
            return None
        if not called:
            return _call("mcp__vinci__buscar_material", pregunta="unidades del curso: la integral definida",
                         materia="cálculo")
        if called == ["mcp__vinci__buscar_material"]:
            hits = (_json(results[-1]) or {}).get("resultados") if isinstance(_json(results[-1]), dict) else None
            if not hits:
                return {"content": _problem(results[-1])}
            source = {"file_id": hits[0]["archivo_id"], "page": hits[0]["pagina"]}
            return _call("mcp__vinci__send_quiz", materia="cálculo", topic="Sílabo de Cálculo", questions=[
                {"question": "¿Qué unidad trata la integral definida?", "options": ["Unidad 4", "Unidad 1", "Unidad 2"],
                 "answer": "Unidad 4", "explanation": "Lo dice el sílabo en Contenidos.", **source},
                {"question": "¿Cuántos créditos tiene la materia?", "options": ["4", "2", "6"], "answer": "4",
                 "explanation": "Lo dice el sílabo en Información general.", **source}])
        data = _json(results[-1])
        return {"content": "📝 Ahí va el quiz en el grupo." if isinstance(data, dict) and data.get("quiz")
                else _problem(results[-1])}

    def portal(self, text: str, called: list[str], results: list[str]) -> dict | None:
        """The Académico: asked with no copy, the tool sends the sign-in button; the question comes back on its own
        once the copy is saved («Ya conecté mi Académico…»), and later ones are answered from the copy."""
        for ask, (topic, refresh) in PORTAL_ASKS.items():
            if ask not in text:
                continue
            if not called:
                again = refresh and PORTAL_BACK not in text
                return _call("mcp__vinci__academic_record", topic=topic, question=ask, **({"refresh": True} if again else {}))
            return {"content": self.portal_answer(topic, _json(results[-1]))}
        return None

    @staticmethod
    def portal_answer(topic: str, data) -> str:
        if not isinstance(data, dict) or data.get("error"):
            return _problem(json.dumps(data, ensure_ascii=False))
        if data.get("connect"):
            return ("🎓 Te mando el botón «Conectar Académico»: ábrelo y entra con tu usuario, tu contraseña y el código "
                    "de la imagen. Tu contraseña no pasa por este chat.")
        when = f"Según tu Académico ({data['period']}, leído el {data['saved_at']})"
        gpa = next(iter((data.get("gpa") or {}).values()), None)
        if topic == "historial":
            approved = data["subjects"].get("approved", [])
            credited = data["subjects"].get("credited", [])
            return (f"{when}: tu promedio general es {gpa}. Aprobaste {len(approved)} materias: "
                    + ", ".join(s["name"].title() for s in approved)
                    + (f". Convalidada: {', '.join(s['name'].title() for s in credited)}." if credited else "."))
        if topic == "promedio":
            return f"{when}: tu promedio general es {gpa}." if gpa else f"{when}: tu copia no tiene tu promedio."
        if topic == "examenes":
            return f"{when}, tus exámenes finales:\n" + "\n".join(
                f"- {e['text']} ({e['day']} {e['start']}-{e['end']})" for e in data["exams"].get("FINAL") or [])
        if topic == "avance":
            career, facts = data["career"], data["credits"]["facts"]
            return (f"{when}: llevas {career.get('Avance de la carrera')} de avance, {facts.get('Total de Créditos')} "
                    f"créditos, y te faltan {career.get('Créditos por tomar')} créditos por tomar. Cuántas materias te "
                    "faltan depende de tu malla, que todavía no leo.")
        return json.dumps(data, ensure_ascii=False)[:500]

    def vinci_material(self, text: str, called: list[str], results: list[str]) -> dict | None:
        """Vinci reading an outside link: one an assignment carries (found in the catalog) or an announcement's;
        or citing the material."""
        last = _json(results[-1]) if results else None
        for topic, (question, english, general) in CITED.items():
            if f"cítame el material de Cálculo sobre {topic}" in text:
                if not called:
                    return _call("mcp__vinci__buscar_material", pregunta=question, traduccion=english, materia="cálculo")
                return {"content": self.cited_answer(last, "Cálculo", general)}
        if "guía del laboratorio" in text:
            if not called:
                return _call("mcp__vinci__archivos", materia="física", nombre="laboratorio")
            if called == ["mcp__vinci__archivos"] and isinstance(last, dict) and last.get("enlaces"):
                return _call("mcp__vinci__leer_archivo", enlace_id=last["enlaces"][0]["enlace_id"])
            return {"content": self.reading_answer(results[-1])}
        if "documento de políticas" in text:
            if not called:
                return _call("mcp__vinci__anuncios", materia="física")
            if called == ["mcp__vinci__anuncios"] and isinstance(last, list):
                item = next(a for a in last if "políticas" in a["titulo"])
                return _call("mcp__vinci__leer_archivo", enlace_id=item["enlaces"][0]["enlace_id"])
            return {"content": self.reading_answer(results[-1])}
        return None

    @staticmethod
    def reading_answer(raw: str) -> str:
        """What the model says after leer_archivo: the document's first page, or why it did not open."""
        data = _json(raw)
        if isinstance(data, dict) and data.get("contenido"):
            page = data["contenido"][0]
            return f"📄 {data['archivo']}, {data['unidad']} {page['pagina']}: {page['texto'][:300]}"
        return _problem(raw)

    @staticmethod
    def vinci_answer(results: list[str]) -> str:
        parts = []
        for raw in results:
            data = _json(raw)
            grade = Script.grade_answer(data)
            if grade is not None:
                parts.append(grade)
            elif isinstance(data, dict) and data.get("todo"):
                todo = data["todo"]
                when = f", para el {todo['due']}" if todo.get("due") else ""
                parts.append(f"📌 Anotado: {todo['text']}{when}.")
            elif isinstance(data, dict) and "todos" in data:  # semana: its order, each with its «peso»
                parts.append("Esta semana:\n" + "\n".join(
                    (f"- {t['text']} ({t['due']})" if t["tipo"] == "tu_lista" else f"- {t['tarea']} ({t['curso']})")
                    + (f" · {t['peso']}" if t.get("peso") else "") for t in data["pendientes"])
                             + "\nTu lista:\n" + "\n".join(f"- {t['text']}" for t in data["todos"]))
            elif isinstance(data, dict) and "chat_notes" in data:
                parts.append(f"📝 {data['message']}")
            elif isinstance(data, dict) and "group_reminders" in data:
                parts.append(f"⏰ {data['message']}")
            elif isinstance(data, dict) and data.get("hecho"):
                parts.append(data["hecho"])
            elif isinstance(data, dict) and data.get("delivery_basis"):
                parts.append(f"Anotado: «{data['tarea']}» {data['delivery']} ({data['delivery_basis']}).")
            elif isinstance(data, dict) and data.get("confirmacion"):
                parts.append(data["confirmacion"])
            elif isinstance(data, dict) and data.get("mensaje"):
                parts.append(data["mensaje"])
            elif isinstance(data, dict) and "entradas" in data:
                parts.append("Esto hay en el cuaderno:\n" + "\n".join(
                    f"- {e['tipo']}: {e['texto']}" for e in data["entradas"][:8]))
            elif isinstance(data, dict) and data.get("materia") and data.get("tipo") and data.get("id"):
                parts.append(f"📘 {data['materia']} · anotado en el cuaderno (#{data['id']}): {data['texto']}")
            elif isinstance(data, dict) and data.get("titulo") and data.get("materia"):
                parts.append(f"📘 Anotado: el libro principal de {data['materia']} es «{data['titulo']}». "
                             f"{data.get('nota', '')}")
            else:
                parts.append(_problem(raw))
        return "\n".join(parts)

    @staticmethod
    def grade_answer(data) -> str | None:
        """What the model says after a calculator tool: its summary as is, or that the scheme is unknown."""
        if not isinstance(data, dict):
            return None
        if "subjects" in data:
            return "\n\n".join(s.get("summary") or f"Todavía no sé cómo se evalúa {s['subject']}: ¿me dices cómo "
                                 "se evalúa, o lo busco en su sílabo?" for s in data["subjects"])
        if data.get("summary"):
            return data["summary"]
        if "scheme" in data and data["scheme"] is None:
            return f"Todavía no sé cómo se evalúa {data['subject']}."
        if data.get("proposal"):
            return "📊 Te mostré cómo entiendo que se evalúa, para que lo guardes. " + " ".join(data["open_questions"])
        return None

    @staticmethod
    def cited_answer(data, subject: str, general: str | None) -> str:
        """A model that copies the tools' citations, and says so when the material has nothing."""
        if not isinstance(data, dict):
            return _problem(json.dumps(data))
        hits = data.get("resultados") or []
        if not hits:
            said = (f"No está en el material de {subject}." if data.get("en_el_material") is False
                    else "[la búsqueda no dijo si está en el material]")
            return f"{said} Por conocimiento general (no sale del material): {general}"
        return f"Según tu material: {hits[0]['fragmento'][:140]} " + " ".join(h["cita"] for h in hits[:2])


# -- helpers ---------------------------------------------------------------------------------


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


def wa_messages(sent: list[dict], chat: str) -> list[dict]:
    """What one WhatsApp chat got, as its owner sees it: each message with the poll that follows it as its
    `options` (WhatsApp's stand-in for buttons), and the picture sent just before it as its `image`."""
    shown: list[dict] = []
    image = None
    for m in sent:
        if m.get("chatId") != chat:
            continue
        if m["path"] == "send-poll":
            if shown:
                shown[-1].update(options=list(m["options"]), poll=m)
        elif m["path"] == "send-media" and m.get("mediaType") == "image" and not m.get("caption"):
            image = m.get("filePath")
        elif m["path"] in ("send", "send-media", "send-url-button"):
            shown.append({"text": m.get("message") or m.get("caption") or "", "options": [], "image": image,
                          "button": m.get("buttonText"), "url": m.get("url"), "file": m.get("filePath"),
                          "path": m["path"]})
            image = None
    return shown


def shown_text(message: dict) -> str:
    keys = (f"\n[botón «{message['button']}»]" if message.get("button") else "") + \
        (f"\n[encuesta: {' / '.join(message['options'])}]" if message.get("options") else "")
    return message["text"] + keys


def write_part(name: str, title: str, report: list[str], started: float) -> None:
    """This test's lines for REPORTE.md (conftest.py puts the parts together)."""
    parts = ARTIFACT / "partes"
    parts.mkdir(parents=True, exist_ok=True)
    took = (time.monotonic() - started) / 60
    (parts / f"{name}.md").write_text(f"## {title} ({took:.1f} min)\n\n" + "".join(f"- {line}\n" for line in report),
                                      encoding="utf-8")


@contextlib.contextmanager
def world(tmp_path: Path):
    """One install of Vinci in a throwaway HOME with every outside service faked; each test starts its own, so the
    tests run in parallel. Vinci lives on WhatsApp alone (`[channels] telegram = false`, the repo's setting): where
    the Telegram Bot API would be, a tripwire records any request."""
    probe_home = tmp_path / "sonda"
    probe_home.mkdir()
    hermes = find_hermes(probe_home)
    home, run_dir, data_dir = tmp_path / "home", tmp_path / "run", tmp_path / "datos"
    home.mkdir()
    run_dir.mkdir(mode=0o700)
    stand_in = tmp_path / "whatsapp-bridge"
    (stand_in / "node_modules").mkdir(parents=True)
    (stand_in / "bridge.js").write_text("// E2E: el puente lo hace FakeWhatsApp\n")
    (stand_in / "package.json").write_text("{}\n")
    (stand_in / "node_modules" / ".hermes-pkg-hash").write_text(hashlib.sha256(b"{}\n").hexdigest()[:16])
    session = home / ".hermes" / "platforms" / "whatsapp" / "session"
    session.mkdir(parents=True)
    # paired (the real pairing is `espol-bot whatsapp-vincular`); its «me» says which ids are Vinci's own
    (session / "creds.json").write_text(json.dumps({"me": {"id": f"{FakeWhatsApp.BOT.split('@')[0]}:7@s.whatsapp.net",
                                                           "lid": "880000000000001:7@lid"}}))
    # the bridge's record of the captain's LID, which Hermes reads to give his chat one key in either form
    (session / f"lid-mapping-{CAPTAIN_WA}.json").write_text(json.dumps(CAPTAIN_LID))
    (session / f"lid-mapping-{CAPTAIN_LID}_reverse.json").write_text(json.dumps(CAPTAIN_WA))

    with contextlib.ExitStack() as stack:
        canvas = stack.enter_context(FakeCanvas(CANVAS_TOKEN))
        web, dspace, portal = (stack.enter_context(s) for s in (FakeWeb(), FakeDSpace(), FakePortal()))
        tripwire = stack.enter_context(Tripwire())
        wa = stack.enter_context(FakeWhatsApp(stand_in / "bridge.js"))
        relay = stack.enter_context(FakeRelay())
        canvas.web = web.base
        config = REPO.joinpath("config.toml").read_text(encoding="utf-8")
        config = config.replace('url = "https://aulavirtual.espol.edu.ec"', f'url = "{canvas.base}"')
        config = config.replace('carpeta_datos = "~/.local/share/espol-academic-bot"', f'carpeta_datos = "{data_dir}"')
        config = config.replace('proveedor = "anthropic"', 'proveedor = "fakellm"')
        config = re.sub(r'^modelo = ".*"$', 'modelo = "fake"', config, count=1, flags=re.M)
        config = config.replace("request_interval_seconds = 1.0", "request_interval_seconds = 0")  # paced below
        assert "\ntelegram = false\n" in config, "Vinci vive solo en WhatsApp"
        hosts = ", ".join(f'"{host}" = "{web.base}"' for host in (
            "docs.google.com", "drive.google.com", "drive.usercontent.google.com", "googleusercontent.com", "sharepoint.com"))
        hosts += f', "dspace.espol.edu.ec" = "{dspace.base}", "academico.espol.edu.ec" = "{portal.base}"'
        config += (f"\n[test]\nlink_hosts = {{ {hosts} }}  # Google and SharePoint are FakeWeb here, DSpace FakeDSpace\n"
                   f'whatsapp_puente = "{wa.base}"\nwhatsapp_script = "{stand_in / "bridge.js"}"\n'
                   "whatsapp_sin_reinicio = true  # the test restarts its own gateway\n"
                   f"whatsapp_grupo_inactivo_segundos = {GROUP_IDLE}\n")
        config_file = tmp_path / "config.toml"
        config_file.write_text(config, encoding="utf-8")
        secrets = tmp_path / "secrets.env"
        secrets.write_text(f"CANVAS_TOKEN={CANVAS_TOKEN}\nWHATSAPP_CAPTAIN={CAPTAIN_WA}\n"
                           f"WHATSAPP_RELAY_URL={relay.base}\nWHATSAPP_RELAY_TOKEN={FakeRelay.KEY}\n")
        secrets.chmod(0o600)
        llm = stack.enter_context(ScriptedLLM(Script(tmp_path / "pwned", secrets)))

        def normalize(text: str) -> str:
            text = text.replace(canvas.base, "https://aulavirtual.test").replace(relay.base, "https://rele.test")
            text = text.replace(llm.base, "https://llm.test").replace(web.base, "https://profesor.test")
            text = text.replace(dspace.base, "https://dspace.test")
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
            "ESPOL_TELEGRAM_API_BASE": tripwire.base, "ESPOL_NO_PM_INSTALL": "1",
            "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            # Hermes refuses to open ~/.hermes/state.db from a process launched by pytest (it also
            # checks the process ancestry). Here ~ is the temporary HOME (asserted below).
            "HERMES_STATE_DB_GUARD_BYPASS": "1",
            # Whisper's model, from the real cache: the temporary HOME would download it on every run
            "HF_HUB_CACHE": os.environ.get("HF_HUB_CACHE") or str(Path.home() / ".cache" / "huggingface" / "hub"),
        })
        # OCR: the real tesseract behind a wrapper that logs each call; while `ocr_off` exists it looks missing
        real_tesseract = shutil.which("tesseract")
        ocr_log, ocr_off = tmp_path / "tesseract.log", tmp_path / "tesseract-off"
        if real_tesseract:
            (tmp_path / "bin").mkdir()
            wrapper = tmp_path / "bin" / "tesseract"
            wrapper.write_text(f'#!/usr/bin/env bash\n[ -e "{ocr_off}" ] && exit 127\n'
                               f'echo "$*" >> "{ocr_log}"\nexec "{real_tesseract}" "$@"\n')
            wrapper.chmod(0o755)
            ocr_off.touch()
            base_env["PATH"] = f"{wrapper.parent}:{base_env.get('PATH', '')}"
        assert Path(base_env["HOME"]).resolve().is_relative_to(tmp_path.resolve()), "la prueba usa un HOME temporal"
        if hermes:
            base_env["HERMES_BIN"] = hermes

        def run(args, now, *, env_extra=None, check=True, stdin="", new_session=False, timeout=300):
            env = {**base_env, "AULA_NOW": now, **(env_extra or {})}
            proc = subprocess.run(args, env=env, capture_output=True, text=True, cwd=REPO, timeout=timeout,
                                  input=stdin, start_new_session=new_session)
            if check:
                assert proc.returncode == 0, f"{args} falló ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
            return proc

        sent_log: list[tuple[str, dict]] = []
        books: list[tuple[str, str]] = []
        taken = [0]

        def take(label: str) -> list[dict]:
            """What reached the captain's WhatsApp chat since the last take."""
            with wa.lock:
                new, taken[0] = wa.sent[taken[0]:], len(wa.sent)
            assert all(m.get("chatId") == CAPTAIN_JID for m in new), ("solo se escribe al capitán", new)
            shown = wa_messages(new, CAPTAIN_JID)
            sent_log.extend((label, m) for m in shown)
            # Vinci asks once per subject for a main book it cannot download: kept apart from the alerts
            books.extend((label, m["text"]) for m in shown if m["text"].startswith(BOOK_ASK))
            return [m for m in shown if not m["text"].startswith(BOOK_ASK)]

        w = SimpleNamespace(
            tmp_path=tmp_path, hermes=hermes, home=home, data_dir=data_dir, profiles=home / ".hermes" / "profiles",
            session=session, canvas=canvas, web=web, dspace=dspace, portal=portal, tripwire=tripwire, wa=wa,
            relay=relay, llm=llm, config=config, config_file=config_file, secrets=secrets, base_env=base_env,
            ocr_off=ocr_off,
            normalize=normalize, run=run, take=take, sent_log=sent_log, books=books, report=[], md=[], gateway=None)
        TRACE.clear()
        TRACE["world"] = w
        try:
            yield w
        finally:
            if w.gateway is not None:
                w.gateway.stop()
        assert tripwire.requests == [], f"nada va a Telegram: {tripwire.requests}"


def trace_page(w) -> str:
    """What a failed test leaves to read before rerunning anything (conftest.py writes it to fallo-<test>.md)."""
    lines = ["## Lo último que llegó a WhatsApp\n"]
    for m in w.wa.sent[-15:]:
        text = m.get("message") or m.get("caption") or m.get("question") or m.get("filePath") or ""
        lines.append(f"- {m.get('chatId')} · {m['path']}: {w.normalize(str(text))[:300]}")
    lines.append("\n## Los últimos turnos del modelo\n")
    for req in w.llm.requests[-3:]:
        users = [m for m in req.get("messages") or [] if m.get("role") == "user"]
        if users:
            lines.append(f"- {bot_of(req)}: {w.normalize(flatten(users[-1].get('content')))[-400:]}")
    if w.gateway is not None:
        lines += ["\n## gateway.log (cola)\n", "```", w.normalize(w.gateway.tail(80)), "```"]
    if w.tripwire.requests:
        lines.append(f"\n## Llamadas a Telegram (no debía haber ninguna)\n\n{w.tripwire.requests}")
    return "\n".join(lines) + "\n"


def ready_gateway(w, *, voice: bool = False) -> None:
    """setup.sh once more, now with Hermes, and the gateway serving Vinci's WhatsApp: the data of two polls, the
    schedule saved, the scripted model, the test clock. With `voice`, Hermes' local Whisper is on from the start."""
    run, profiles, home = w.run, w.profiles, w.home
    run([str(VENV_BIN / "espol-bot"), "sondeo"], T_POLL1)
    w.canvas.state = "state2"
    run([str(VENV_BIN / "espol-bot"), "sondeo"], T_POLL2)
    script = ("import json, sys; from datetime import datetime; from aula_core.config import load_config; "
              "from espol_bot import horario; classes, errors, _ = horario.validate(json.loads(sys.argv[1])); "
              "assert not errors, errors; horario.save(load_config(), classes, datetime.now())")
    run([sys.executable, "-c", script, json.dumps(SCHEDULE_V2)], T_VINCI)
    setup = run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_VINCI)
    assert "• WhatsApp: tu chat" in setup.stdout, setup.stdout
    w.take("setup.sh y los sondeos")

    def patch_profile(name: str) -> None:
        """Test-only: the scripted model, the test clock, and Whisper only when this test hears voice."""
        cfg_file = profiles / name / "config.yaml"
        data = yaml.safe_load(cfg_file.read_text())
        data["providers"] = {"fakellm": {"api": f"{w.llm.base}/v1", "api_key": "e2e", "discover_models": False,
                                         "models": ["fake"]}}
        data["model"]["context_length"] = 256_000  # no lookup of the fake model's window on each start
        data.setdefault("stt", {}).update(enabled=voice, **({"provider": "local"} if voice else {}))
        data["mcp_servers"]["vinci"]["env"]["AULA_NOW"] = T_VINCI
        cfg_file.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))

    def pause_crons() -> None:
        """setup.sh resumes every cron; the test runs each poll itself, on its own clock."""
        for jobs_file in profiles.glob("*/cron/jobs.json"):
            for job in json.loads(jobs_file.read_text())["jobs"]:
                if job.get("enabled") is not False:
                    run([w.hermes, "-p", jobs_file.parents[1].name, "cron", "pause", job["id"]], T_VINCI)

    patch_profile("vinci")
    pause_crons()
    default_file = home / ".hermes" / "config.yaml"
    default_cfg = yaml.safe_load(default_file.read_text())
    default_cfg.setdefault("stt", {}).update(enabled=voice, **({"provider": "local"} if voice else {}))
    default_file.write_text(yaml.safe_dump(default_cfg, allow_unicode=True, sort_keys=False))
    w.gateway = Gateway(w.hermes, {**w.base_env, "AULA_NOW": T_VINCI}, w.tmp_path / "gateway.log")
    w.patch_profile, w.pause_crons = patch_profile, pause_crons

    def fail(msg: str) -> str:
        return f"{msg}\n--- gateway.log ---\n{w.gateway.tail(60)}"

    def start() -> None:
        mark = time.time()
        w.gateway.start()
        assert w.wa.wait_for(lambda b: b.polled_since(mark), 120), fail("Hermes no tomó el puente de WhatsApp")

    md = w.md

    def say(chat: str, sender: str, text: str, name: str, *, group: bool = False, expect: int = 1,
            timeout: float = 120, mentions: list[str] | None = None, quote: str | None = None) -> list[dict]:
        mark = len(w.wa.sent)
        w.wa.say(chat, sender, text, name=name, group=group, mentions=mentions, quote=quote)
        shown = ("[el texto cifrado que dio la página]" if text.startswith("v1.")
                 else text.replace(ANGEL_TOKEN, "<el token de Angel>"))
        md.append(f"**{name}** ({'grupo' if group else 'privado'}): {shown}\n")
        if not expect:
            time.sleep(6)
            got = w.wa.messages_to(chat, mark)
            assert not got, f"nadie debía contestar a «{text}»: {got}"
            md.append("→ (sin respuesta)\n")
            return []
        got = w.wa.wait_for(lambda b: (lambda m: m if len(m) >= expect else None)(b.messages_to(chat, mark)),
                            timeout)
        assert got, fail(f"nadie contestó a «{text}»")
        for m in got:
            shown = m.get("message") or f"[archivo {Path(m.get('filePath', '')).name}]"
            md.append(f"→ Vinci: {w.normalize(shown)}\n")
        return got

    w.fail, w.start, w.say = fail, start, say
    start()


def turn_context(requests: list[dict]) -> str:
    """What the bot read as the student's message in the first of these turns, with the chat's context at its end."""
    first = next(r for r in requests if bot_of(r))
    return flatten([m for m in first["messages"] if m.get("role") == "user"][-1].get("content"))


def text_of(messages: list[dict]) -> str:
    return "\n".join(m.get("message", "") for m in messages)


def secrets_in(w) -> list[str]:
    """Every token this world handed out: none may reach a chat, the model or an artifact."""
    values = set(parse_env_file(w.secrets).values()) | set(w.canvas.valid_tokens) | set(w.canvas.accounts)
    values |= {CANVAS_TOKEN, NEW_CANVAS_TOKEN, AUTO_FORM_TOKEN, ANGEL_TOKEN, CAPTAIN_WA_TOKEN, PORTAL_PASSWORD}
    return sorted(v for v in values if len(v) >= 16 and v not in (CAPTAIN_WA, w.relay.base) and "@" not in v)


def assert_no_secrets(w, name: str) -> None:
    dumps = json.dumps(w.wa.sent, ensure_ascii=False) + json.dumps(w.llm.requests, ensure_ascii=False) + \
        json.dumps(w.relay.posted)
    for secret in secrets_in(w):
        assert secret not in dumps, f"{name}: un token llegó a WhatsApp, al relé o al modelo"
    for path in ARTIFACT.glob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            assert not [s for s in secrets_in(w) if s in text], f"{path.name} contiene un token"


def test_canvas(tmp_path):
    """Sections 1 to 6f: setup.sh, the `aula` CLI, the polls and the 07:00 summary, quizzes, retrieval, a fresh install
    with failing resources and the token chain, all without the gateway; every alert reaches the captain's WhatsApp."""
    started = time.monotonic()
    with world(tmp_path) as w:
        canvas, run, take, normalize, report = w.canvas, w.run, w.take, w.normalize, w.report
        config, config_file, secrets, home, profiles, hermes = w.config, w.config_file, w.secrets, w.home, w.profiles, w.hermes
        data_dir, wa, base_env = w.data_dir, w.wa, w.base_env

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
                 "--name", "espol-sondeo", "--deliver", "local"], T_SETUP)

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
            assert sorted(j["name"] for j in jobs) == ["vinci-agenda", "vinci-apuntes", "vinci-mantenimiento",
                                                       "vinci-resumen", "vinci-sondeo"], jobs
            by_name = {j["name"]: j for j in jobs}
            assert by_name["vinci-sondeo"]["schedule_display"] == "5,15,25,35,45,55 * * * *", "cada 10 min, lejos del resumen"
            assert by_name["vinci-mantenimiento"]["schedule_display"] == "2,12,22,32,42,52 * * * *"
            assert by_name["vinci-apuntes"]["schedule_display"] == "* * * * *", "la carpeta de notas, cada minuto"
            assert by_name["vinci-resumen"]["schedule"].get("expr") == "0 7 * * *" or \
                by_name["vinci-resumen"]["schedule_display"] == "0 7 * * *"
            assert all(j["no_agent"] and j["deliver"] == "local" for j in jobs), "Vinci escribe por WhatsApp él mismo"
            assert "sin cambios" in second.stdout and "creado" not in second.stdout
            for out in (first.stdout, second.stdout):
                assert "✓ vinci: su skill llega al modelo" in out and "✗" not in out and "no pude revisar" not in out, out
            # A toolset the captain switches on in config.toml leaves the blocked list; switching it off restores it.
            original = config_file.read_text(encoding="utf-8")
            vcfg_before_switch = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
            config_file.write_text(original.replace("vinci = []", 'vinci = ["terminal", "file"]'), encoding="utf-8")
            switched = run(["bash", str(REPO / "setup.sh"), "--skip-deps", "--sin-pruebas"], T_SETUP)
            scfg_on = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
            assert {"terminal", "file"} <= set(scfg_on["platform_toolsets"]["whatsapp"]) & set(scfg_on["platform_toolsets"]["cron"])
            assert not {"terminal", "file"} & set(scfg_on["agent"]["disabled_toolsets"])
            assert {"code_execution", "browser", "delegation"} <= set(scfg_on["agent"]["disabled_toolsets"])
            assert "herramientas extra activadas en config.toml: terminal, file" in switched.stdout, switched.stdout
            vinci_skill = profile / "skills" / "vinci" / "vinci" / "SKILL.md"
            prompts_on = (profile / "SOUL.md").read_text(encoding="utf-8") + vinci_skill.read_text(encoding="utf-8")
            assert "terminal" not in prompts_on.replace("(terminal, file)", ""), "un switch encendido no se niega al modelo"
            config_file.write_text(original.replace("vinci = []", 'vinci = ["terminall"]'), encoding="utf-8")
            typo = run(["bash", str(REPO / "setup.sh"), "--skip-deps", "--sin-pruebas"], T_SETUP, check=False)
            assert typo.returncode != 0 and "no conozco terminall" in typo.stdout + typo.stderr
            config_file.write_text(original, encoding="utf-8")
            run(["bash", str(REPO / "setup.sh"), "--skip-deps", "--sin-pruebas"], T_SETUP)
            assert yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8")) == vcfg_before_switch
            assert "No tienes terminal ni acceso a archivos del computador" in (profile / "SOUL.md").read_text(encoding="utf-8")
            assert "- Sin terminal ni archivos del computador;" in vinci_skill.read_text(encoding="utf-8")
            assert not [k for k in parse_env_file(profile / ".env") if k.startswith("TELEGRAM_")], "sin Telegram"
            assert "Telegram apagado ([channels] telegram = false): Vinci te habla solo por WhatsApp" in first.stdout
            vcfg = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
            assert vcfg["timezone"] == "America/Guayaquil" and vcfg["model"]["provider"] == "fakellm"
            assert vcfg["model"]["default"] == "fake", "the config.toml model substitution no longer matches"
            assert set(vcfg["platform_toolsets"]["whatsapp"]) == {"web", "memory", "session_search", "clarify",
                                                                  "skills", "mcp-vinci", "vinci-paginas"}
            assert set(vcfg["platform_toolsets"]["cli"]) == set(vcfg["platform_toolsets"]["whatsapp"])
            assert set(vcfg["platform_toolsets"]["cron"]) == {"web", "memory", "skills", "mcp-vinci", "vinci-paginas"}
            assert {"terminal", "file", "code_execution", "delegation", "cronjob"} <= \
                set(vcfg["agent"]["disabled_toolsets"]) and "skills" not in vcfg["agent"]["disabled_toolsets"]
            assert vcfg["tools"]["tool_search"]["enabled"] == "off"
            assert vcfg["skills"]["auto_load"] == ["vinci"]
            assert vcfg["compression"]["threshold_tokens"] == 80_000, "Vinci resume su chat a los 80 mil tokens"
            assert vcfg["mcp_servers"]["vinci"]["command"] == str(VENV_BIN / "espol-bot")
            assert vcfg["mcp_servers"]["vinci"]["args"][:1] == ["mcp"]
            assert "vinci-botones" in vcfg["plugins"]["enabled"]
            assert vcfg["unauthorized_dm_behavior"] == "ignore" and vcfg["stt"]["language"] == "es"
            assert {"*secrets.env*", "*CANVAS_TOKEN*", "*api/v1*"} <= set(vcfg["approvals"]["deny"])
            assert (profile / "skills" / "vinci" / "vinci" / "SKILL.md").is_file()
            soul = (profile / "SOUL.md").read_text(encoding="utf-8")
            assert not [word for word in ROLEPLAY if word in soul], "Vinci no hace de personaje"
            assert (home / ".local" / "bin" / "aula").is_file()
            assert (home / ".claude" / "skills" / "aula" / "SKILL.md").is_file()
            report.append(f"setup.sh ×2 con Hermes real en un HOME aislado: el perfil «espol» del bot anterior pasó "
                          f"a «vinci» con su memoria; {len(jobs)} cron no-agent; la segunda corrida no cambió nada")
            probe = take("setup.sh (mensaje de prueba de Vinci)")
            assert [m["text"] for m in probe] == ["✅ *Prueba*: Vinci puede escribirte por WhatsApp."] * 2, \
                "una prueba por WhatsApp en cada corrida de setup.sh"
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
            ["archivos", "--json"],
            ["enlaces"],
            ["archivos", "bajar", "5001", "--json"],
            ["archivos", "bajar", "5005", "--json"],
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
        catalog = {f["id"]: f for f in cli_json["archivos --json"]}
        assert not any(f["descargado"] for f in cli_json["archivos --json"]), "nada se baja sin pedirlo"
        stewart, guide, formulario = catalog[5002], catalog[5006], catalog[5007]
        assert (stewart["modulo"], stewart["seccion"], stewart["carpeta"]) == (
            "Semana 1: Límites", "ANTES de clase: lecturas", "Libros"), stewart
        assert catalog[5005]["copia_de"] == 5001 and catalog[5005]["anterior"] and catalog[5001]["copia_de"] is None
        assert guide["origen"] == "Tarea «Taller 3: Derivadas»" and formulario["origen"] == "Anuncio «Bienvenidos al curso»"
        assert catalog[5301]["curso"].endswith("Práctico")
        assert cli_json["archivos bajar 5005 --json"][0]["indexado"] == "ok"
        assert take("aula CLI") == [], "la CLI nunca envía mensajes"

        # 3. polls -----------------------------------------------------------------------
        bot = str(VENV_BIN / "espol-bot")
        token_md = ["# El formulario del token, cuando la cadena se corta\n",
                    "Lo que el capitán ve en su chat de WhatsApp. La página del formulario (docs/token/form.js) cifra "
                    "con la llave pública de un uso que trae su enlace (aquí, `k=<llave de un uso>`) y lo deja en el "
                    "relé; solo viaja el texto cifrado.\n"]
        estado_md = ["# Estado del sistema: `espol-bot doctor` y /estado\n",
                     "Lo que ve el capitán en cada momento de la prueba. Solo lee lo que dejaron el sondeo y el "
                     "mantenimiento: ninguna consulta al aula, ningún mensaje, ningún modelo.\n"]

        def doctor(label: str, now: str, broken: bool) -> str:
            mark_canvas = len(canvas.requests)
            proc = run([bot, "doctor"], now, check=False)
            assert proc.returncode == (1 if broken else 0), f"doctor ({label}): {proc.returncode}\n{proc.stdout}{proc.stderr}"
            assert len(canvas.requests) == mark_canvas and take(f"doctor · {label}") == [], "doctor no toca el aula ni el chat"
            estado_md.append(f"## `espol-bot doctor` · {label}\n\n```\n{normalize(proc.stdout).rstrip()}\n```\n")
            return proc.stdout

        installed = doctor("recién instalado, antes del primer sondeo", T_POLL1, broken=False)
        assert "⚠️ Sondeo: todavía no registra ninguna corrida" in installed, installed
        assert "⚠️ Token de Canvas: todavía no sé su edad" in installed, installed
        run([bot, "sondeo"], T_POLL1)
        poll1 = take("Sondeo 1 · lun 28 sep 07:40")
        assert [(label, text.split("\n")[0]) for label, text in w.books] == [
            ("Sondeo 1 · lun 28 sep 07:40", "📘 *El libro principal de Cálculo de una Variable*")], w.books
        assert "mándamelo aquí" in w.books[0][1] and "SharePoint" in w.books[0][1], w.books[0][1]
        assert len(poll1) == 2, poll1
        assert "Listo" in poll1[0]["text"] and "Recordatorio" in poll1[1]["text"] and "Deber 2" in poll1[1]["text"]

        canvas.state = "state2"
        canvas.slow_downloads[5010] = 8
        sondeo = subprocess.Popen([bot, "sondeo"], env={**base_env, "AULA_NOW": T_POLL2}, cwd=REPO, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        downloading = wa.wait_for(lambda _: any("/files/5010/download" in p for _, p in list(canvas.requests)), 60)
        assert downloading, "el sondeo 2 debía bajar el sílabo nuevo de Cálculo"
        started = time.monotonic()
        refresh = run([aula, "cursos", "--actualizar"], T_POLL2)
        took = time.monotonic() - started
        assert sondeo.poll() is None and took < 5, \
            f"`aula cursos --actualizar` tardó {took:.1f} s: esperó a que el sondeo terminara de bajar el material"
        out, err = sondeo.communicate(timeout=120)
        assert sondeo.returncode == 0, f"el sondeo 2 falló:\n{out}\n{err}"
        canvas.slow_downloads.clear()
        assert "FÍSICA I" in refresh.stdout
        report.append("Mientras el sondeo bajaba el sílabo nuevo (una descarga de 8 s), `aula cursos --actualizar` "
                      "(lo que corre setup.sh, y lo mismo que refresca una herramienta de un bot) leyó el aula en "
                      "menos de 5 s: la descarga ya no retiene el candado de la sincronización")
        poll2 = take("Sondeo 2 · mar 29 sep 00:30 (tras los cambios)")
        texts = "\n\n".join(m["text"] for m in poll2)
        for expected in ("Nueva tarea en Física I", "Taller 2: Movimiento parabólico", "Cambió la fecha de entrega",
                         "Nuevo anuncio en Cálculo de una Variable", "Cambio de fecha del Taller 3", "Nota publicada",
                         "Tarea 1: Vectores", "9/10", "Nuevo material en Física I", "Recordatorio", "vence en 22 h",
                         "Nuevo material en Cálculo de una Variable*\nSílabo MATG1049 2026-2T.pdf",
                         "Enlace nuevo en Cálculo de una Variable* · Semana 4: Aplicaciones de la "
                         "derivada · ANTES de clase en vivo"):
            assert expected in texts, f"falta «{expected}» en el sondeo 2:\n{texts}"
        by_title = {m["text"].split("\n")[1]: m["text"] for m in poll2 if "\n" in m["text"]}
        assert "Ya lo leí" in by_title["Sílabo MATG1049 2026-2T.pdf"], "el sílabo se baja y se lee solo"
        assert "Lo bajo y lo leo cuando haga falta" in by_title["Semana 2 - Cinemática.pptx"], \
            "lo demás no se baja solo: queda en el catálogo"
        assert "Su bot de materia lo abre sin tu cuenta" in texts, "el enlace de un módulo avisa que el bot lo abre"
        assert len(poll2) == 8, [m["text"][:40] for m in poll2]
        for m in poll1 + poll2:  # WhatsApp has no buttons: a reminder's «Ya lo entregué» is a poll after it
            assert m["options"][:1] == ([SUBMITTED] if "Recordatorio" in m["text"] else []), m

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
        assert len(w.books) == 1, f"el libro se pide una sola vez: {w.books}"
        report.append("El sílabo de Cálculo dice que su libro es el Purcell, que en el aula es un SharePoint que pide la "
                      "cuenta de ESPOL: Vinci se lo pidió al capitán una sola vez, en su chat de WhatsApp")

        # 4b. reading quizzes: a Canvas of its own (Sistemas Distribuidos), so the timeline above stays as it is ----
        with FakeCanvas(CANVAS_TOKEN, "canvas-controles") as quiz_canvas:
            quiz_dir = tmp_path / "controles"
            quiz_config = tmp_path / "config-controles.toml"
            quiz_config.write_text(config.replace(canvas.base, quiz_canvas.base).replace(str(data_dir), str(quiz_dir)),
                                   encoding="utf-8")
            quiz_secrets = tmp_path / "secrets-controles.env"
            quiz_secrets.write_text(f"CANVAS_TOKEN={CANVAS_TOKEN}\nWHATSAPP_CAPTAIN={CAPTAIN_WA}\n")
            quiz_secrets.chmod(0o600)
            quiz_env = {"AULA_CONFIG": str(quiz_config), "AULA_SECRETS": str(quiz_secrets)}
            controles_md = ["# Cuestionarios del aula (controles): lo que llega al chat\n",
                            "Un aula aparte, Sistemas Distribuidos, con un control de vídeo abierta una semana y un "
                            "test que abre a las 19:00 por 30 minutos. Solo se lee la configuración de cada "
                            "cuestionario (GET); nunca sus preguntas ni un intento.\n"]

            def quiz_poll(label: str, now: str) -> tuple[list[dict], list[str]]:
                mark = len(quiz_canvas.requests)
                run([bot, "sondeo"], now, env_extra=quiz_env)
                reads = [path for _, path in quiz_canvas.requests[mark:] if "/quizzes" in path]
                sent = take(label)
                controles_md.append(f"## {label}\n\nLecturas de cuestionarios: "
                                    f"{', '.join(f'`GET {r}`' for r in reads) or 'ninguna'}\n")
                controles_md.extend(f"```\n{shown_text(m)}\n```\n" for m in sent)
                return sent, reads

            sent, reads = quiz_poll("Primer sondeo · jue 1 oct 10:00 (solo un test del término pasado)",
                                    "2026-10-01T10:00:00-05:00")
            assert len(sent) == 1 and "Listo" in sent[0]["text"], sent
            assert reads == [], "un cuestionario ya cerrado nunca se consulta"
            quiz_canvas.state = "state2"
            sent, reads = quiz_poll("Sondeo · jue 1 oct 12:00 (dos cuestionarios nuevos)", "2026-10-01T12:00:00-05:00")
            assert sorted(reads) == ["/api/v1/courses/401/quizzes/455542", "/api/v1/courses/401/quizzes/456084"], reads
            texts = {m["text"].split("\n")[1]: m["text"] for m in sent}
            memcache = texts["Control: Scaling Memcache at Facebook"]
            assert "Nuevo cuestionario en Sistemas Distribuidos" in memcache, memcache
            assert "3 preguntas, sin límite de tiempo, 1 intento" in memcache, memcache
            assert "Entrega: mié 7 oct, 23:59 (en 6 días) · cierra jue 8 oct, 07:00" in memcache, memcache
            test = [m["text"] for m in sent if "Test de tiempos y costos" in m["text"]]
            assert len(test) == 2, "el aviso del test nuevo y su recordatorio de 24 h"
            assert all("5 preguntas, 30 min para resolverlo, 1 intento, no muestra resultados" in t and
                       "Abre: *jue 1 oct, 19:00*" in t and "cierra jue 1 oct, 20:00" in t for t in test), test
            assert "Aún no lo has respondido" in test[1], test
            sent, reads = quiz_poll("Sondeo · jue 1 oct 12:30 (sin cambios)", "2026-10-01T12:30:00-05:00")
            assert sent == [] and reads == [], "un cuestionario sin cambios no se vuelve a leer"
            # a poll every 10 minutes warns 15 minutes ahead (poller.OPENING_LEAD)
            sent, reads = quiz_poll("Sondeo · jue 1 oct 18:50 (el test abre a las 19:00)", "2026-10-01T18:50:00-05:00")
            opening = [m["text"] for m in sent if "Abre en" in m["text"]]
            assert len(sent) == 2 and len(opening) == 1, [m["text"] for m in sent]
            assert "⏳ *Abre en 10 min* — Sistemas Distribuidos" in opening[0], opening
            assert "Abre: jue 1 oct, 19:00 · cierra *jue 1 oct, 20:00*" in opening[0], opening
            sent, reads = quiz_poll("Sondeo · jue 1 oct 19:05 (ya abrió)", "2026-10-01T19:05:00-05:00")
            assert sent == [], "el aviso de apertura sale una vez"
            pending = json.loads(run([aula, "tareas", "--sin-actualizar", "--json"], "2026-10-01T19:05:00-05:00",
                                     env_extra=quiz_env).stdout)
            by_name = {t["tarea"]: t["quiz"] for t in pending}
            assert by_name["Test de tiempos y costos"] == {
                "question_count": 5, "time_limit": 30, "allowed_attempts": 1, "unlock_at": "2026-10-02T00:00:00Z",
                "lock_at": "2026-10-02T01:00:00Z", "hide_results": "always"}, by_name
            assert all(method == "GET" for method, _ in quiz_canvas.requests)
            assert not any("/submissions" in path or "/questions" in path for _, path in quiz_canvas.requests)
        (ARTIFACT / "controles.md").write_text(normalize("\n".join(controles_md)).replace(quiz_canvas.base,
                                               "https://aulavirtual.test"), encoding="utf-8")
        report.append("Cuestionarios del aula: el aviso de uno nuevo y sus recordatorios dicen cuántas preguntas tiene, "
                      "el tiempo para resolverlo, los intentos, cuándo abre y cuándo cierra; un test que abre a una "
                      "hora fija por poco tiempo avisa antes de abrir, una vez. Cada cuestionario se lee una vez "
                      "(y otra solo si cambia), nunca uno ya cerrado, y jamás sus preguntas ni un intento")

        # 5. retrieval -------------------------------------------------------------------
        run([aula, "archivos", "bajar", "5101", "--json"], T_SUMMARY)  # material comes down when it is asked for
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
        chain = json.loads(run([aula, "buscar", QUESTIONS[0][0], "--json", "-n", "8"], T_SUMMARY).stdout)
        pages = [(h["archivo"], h["pagina"]) for h in chain]
        assert len(pages) == len(set(pages)) and 5005 not in [h["archivo_id"] for h in chain], \
            f"la copia de 2025 del capítulo 3 no se repite en la búsqueda: {pages}"
        run_cli_after = run([aula, "buscar", QUESTIONS[0][0]], T_SUMMARY)
        cli_md.append(f"## `aula buscar \"{QUESTIONS[0][0]}\"`\n\n```\n{normalize(run_cli_after.stdout).rstrip()}\n```\n")
        pend = run([aula, "tareas", "--dias", "7", "--sin-actualizar"], T_SUMMARY)
        cli_md.append(f"## `aula tareas --dias 7` (después de los cambios)\n\n```\n{normalize(pend.stdout).rstrip()}\n```\n")

        # 6. two resources failing at different polls on a fresh install ---------------
        fresh_config = tmp_path / "config-resiliencia.toml"
        fresh_config.write_text(config.replace(str(data_dir), str(tmp_path / "resiliencia"))
                                .replace("request_interval_seconds = 0", "request_interval_seconds = 0.1")
                                .replace("max_mb_per_sync = 50", "max_mb_per_sync = 0.001"), encoding="utf-8")
        fresh = {"AULA_CONFIG": str(fresh_config)}
        fisica_anuncios, calculo_archivos = "/api/v1/courses/102/discussion_topics", "/api/v1/courses/101/files"
        names = {fisica_anuncios: "anuncios de Física", calculo_archivos: "archivos de Cálculo"}
        plan = [{fisica_anuncios}, {fisica_anuncios}, {fisica_anuncios, calculo_archivos},
                {fisica_anuncios, calculo_archivos}, {calculo_archivos}, {fisica_anuncios, calculo_archivos},
                {fisica_anuncios}, {fisica_anuncios}, set()]
        polls, downloads = [], []
        for i, (now, paths) in enumerate(zip(T_RESILIENCE, plan, strict=True), start=1):
            canvas.failing = set(paths)
            mark = len(canvas.requests)
            run([bot, "sondeo"], now, env_extra=fresh)
            with canvas.lock:
                sent, times = canvas.requests[mark:], canvas.times[mark:]
            downloads.append([int(path.split("/")[2]) for _, path in sent if path.startswith("/files/")])
            if i == 1:
                gaps = [b - a for a, b in itertools.pairwise(times)]
                assert len(times) > 10 and min(gaps) >= 0.08, f"el sondeo no espació sus consultas: {min(gaps):.3f} s"
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
        assert len(anuncios) == 2, "al recuperarse, los anuncios existentes quedan guardados"
        canvas.failing = set()
        assert downloads[:2] == [[5010], [5301]] and not any(downloads[2:]), downloads
        report.append("El sondeo trata el aula virtual con suavidad: espació cada consulta (con el ritmo de prueba de "
                      "0,1 s) y solo bajó los sílabos, de a poco (con un tope de prueba de 1 KB por sondeo, el del "
                      "teórico en el primero y el del práctico en el segundo), en vez de todo el material de golpe")

        # 6b. Token renewal survives several generations before the one-hour Canvas expiry ----------------
        orphan = canvas.mint("7~huerfano-de-una-renovacion-rota", "Vinci (renovación automática)")
        other = canvas.mint("7~otro-token-del-capitan", "Mi script")
        run([bot, "mantenimiento"], T_RENEW_0)
        first = parse_env_file(secrets)["CANVAS_TOKEN"]
        assert first != CANVAS_TOKEN and first in canvas.valid_tokens
        assert CANVAS_TOKEN in canvas.valid_tokens, "la semilla queda viva como sonda"
        assert orphan in canvas.deleted and other not in canvas.deleted, \
            "solo se borra el huérfano de renovación, nunca otro token del capitán"
        canvas.expire(CANVAS_TOKEN)

        run([bot, "mantenimiento"], T_RENEW_1)
        second = parse_env_file(secrets)["CANVAS_TOKEN"]
        assert second not in (CANVAS_TOKEN, first) and second in canvas.valid_tokens
        canvas.expire(first)

        run([bot, "mantenimiento"], T_RENEW_2)
        third = parse_env_file(secrets)["CANVAS_TOKEN"]
        assert third not in (CANVAS_TOKEN, first, second) and third in canvas.valid_tokens
        assert len(canvas.issued()) == 3
        assert canvas.token_ids[first] in canvas.deleted, "el antecesor ya reemplazado se borró de Canvas"
        run([bot, "sondeo"], T_RENEW_2)
        assert take("Renovación automática · tres generaciones") == [], "renovar no manda ruido al chat"
        healthy = doctor("todo al día (tercera generación del token)", T_RENEW_2, broken=False)
        assert "✅ todo en orden" in healthy and "⚠️" not in healthy and "❌" not in healthy, healthy
        for line in ("✅ Sondeo: corrió hace un momento", "✅ Mantenimiento: corrió hace un momento",
                     "✅ Token de Canvas: renovado hace un momento (22:22); la cadena está sana"):
            assert line in healthy, f"falta «{line}»:\n{healthy}"
        stale = doctor("tres horas después, con la PC apagada (nada corrió)", "2026-09-30T01:22:00-05:00", broken=True)
        for line in ("❌ Sondeo: no corre desde hace 3 h (mar 29 sep, 22:22); debería cada 10 min", "❌ Mantenimiento: no corre desde",
                     "❌ Token de Canvas: se creó hace 3 h", "⚠️ Aula virtual: leída por última vez hace 3 h",
                     "→ hermes gateway status"):
            assert line in stale, f"falta «{line}»:\n{stale}"
        report.append("La renovación creó y verificó tres generaciones de token en segundo plano (leyendo el valor "
                      "de visible_token, como lo devuelve Canvas); después de expirar cada antecesor, el sondeo "
                      "siguió leyendo con el sucesor, borró el huérfano de una renovación rota sin tocar otros "
                      "tokens del capitán, y ningún token apareció en el chat")

        # 6c. The current token and the probe both die: the chain is cut, and Canvas is left alone -----------
        run([bot, "mantenimiento"], T_RENEW_3)
        fourth = parse_env_file(secrets)["CANVAS_TOKEN"]
        assert parse_env_file(secrets).get("CANVAS_TOKEN_PROBE") == third, "el antecesor queda como sonda"
        for token in list(canvas.valid_tokens):
            canvas.expire(token)
        mark = len(canvas.requests)
        run([bot, "mantenimiento"], T_RENEW_4)
        cut = take("Cadena cortada · sonda y token actual vencidos")
        cut_text = "\n".join(message["text"] for message in cut)
        assert "cadena automática del token" in cut_text and "No hace falta que escribas /token" in cut_text, cut_text
        assert "resembrar" not in cut_text, "el aviso no manda a la terminal"
        assert len(cut) == 1 and "Tu token del aula" in cut_text and "/profile/settings" in cut_text, cut_text
        assert "vence en 24 h" in cut_text, "el formulario que llega solo dura lo bastante para verlo más tarde"
        auto_url = cut[0]["url"]
        assert cut[0]["button"] == "🔑 Abrir formulario" and cut[0]["image"], cut[0]
        assert auto_url.startswith(DEFAULT_TOKEN_FORM_URL + "?k=") and "TOKEN_FORM_KEY" in parse_env_file(secrets)
        assert parse_qs(urlsplit(auto_url).query).get("r") == [w.relay.base] and "#m=" in auto_url, auto_url
        token_md.append(f"## La cadena se corta: Vinci manda el formulario solo, sin que el capitán escriba /token\n\n"
                        f"```\n{cut[0]['text']}\n[botón «{cut[0]['button']}» → "
                        f"{re.sub(r'k=[A-Za-z0-9_-]+', 'k=<llave de un uso>', auto_url.split('#')[0])}]\n```\n")
        assert "reemplazo funciona" not in cut_text, "no hay reemplazo: la cadena está cortada"
        api = canvas.requests[mark:]
        assert [method for method, _ in api] == ["GET", "DELETE"], api
        assert parse_env_file(secrets)["CANVAS_TOKEN"] == fourth and len(canvas.issued()) == 4
        mark = len(canvas.requests)
        run([bot, "mantenimiento"], T_RENEW_5)
        run([bot, "sondeo"], T_RENEW_5)
        assert take("Cadena cortada · mantenimiento y sondeo siguientes") == [], \
            "el aviso no se repite mientras su formulario sigue vigente"
        assert canvas.requests[mark:] == [], \
            "con la cadena cortada, nadie vuelve a llamar a Canvas con un token muerto"
        cut_health = doctor("la cadena del token se cortó", T_RENEW_5, broken=True)
        assert "❌ Token de Canvas: la cadena de renovación está cortada" in cut_health, cut_health
        assert "→ /token en el chat de Vinci, o aquí:" in cut_health and "espol-bot resembrar" in cut_health, cut_health
        assert "✅ Sondeo" in cut_health and "✅ Mantenimiento" in cut_health, cut_health
        report.append("Con el token actual y la sonda vencidos, el mantenimiento avisó que la cadena se cortó (no que el "
                      "reemplazo funciona) y en el mismo mensaje mandó el formulario cifrado de /token, válido 24 h, "
                      "sin que el capitán lo pidiera; desde entonces ni el mantenimiento ni el sondeo llamaron a Canvas "
                      "con esos tokens, ni repitieron el aviso")

        # 6e. The captain fills the form Vinci sent on its own, 26 min later: the chain comes back ---------------
        canvas.mint(AUTO_FORM_TOKEN, "Token personal")  # the captain creates it in the aula's settings
        page_send(auto_url, AUTO_FORM_TOKEN)  # the page seals it and leaves it in the relay
        assert w.relay.posted and AUTO_FORM_TOKEN not in json.dumps(w.relay.posted)
        # what the plugin vinci-whatsapp runs while a link may still post to the relay
        answers = json.loads(run([bot, "whatsapp-rele", "--json"], T_RENEW_6).stdout)["respuestas"]
        assert [a["chat"] for a in answers] == [CAPTAIN_JID], answers
        auto_done = answers[0]
        assert "Token verificado y guardado" in auto_done["respuesta"], auto_done
        assert w.relay.messages == [], "Vinci borra del relé lo que atendió"
        from_form = parse_env_file(secrets)
        assert from_form["CANVAS_TOKEN"] in canvas.valid_tokens and from_form["CANVAS_TOKEN"] != AUTO_FORM_TOKEN
        assert "TOKEN_FORM_KEY" not in from_form, "la llave de un uso se borró al abrir el envío"
        mark = len(canvas.requests)
        run([bot, "sondeo"], T_RENEW_6)
        assert not any("cadena automática del token" in m["text"] for m in take("Cadena resembrada con el formulario"))
        assert canvas.requests[mark:], "el sondeo volvió a leer el aula"
        token_md.append(f"## El capitán pega el token en ese formulario 26 min después\n\nVinci responde:\n\n"
                        f"```\n{auto_done['respuesta']}\n```\n")
        report.append("26 minutos después del corte (un formulario de /token ya habría vencido), el capitán pegó un "
                      "token en el formulario que Vinci mandó solo por WhatsApp (llegó cifrado por el relé): Vinci lo verificó, dejó activo su sucesor y el "
                      "sondeo volvió a leer el aula")

        # 6f. A hidden terminal prompt re-seeds the chain too; the token never passes through a chat --------------
        canvas.valid_tokens.add(NEW_CANVAS_TOKEN)
        canvas.mint(NEW_CANVAS_TOKEN, "Token personal")
        reseed = run([bot, "resembrar", "--stdin"], T_RENEW_6, stdin=NEW_CANVAS_TOKEN + "\n")
        assert "verificado" in reseed.stdout.lower() and NEW_CANVAS_TOKEN not in reseed.stdout + reseed.stderr
        reseeded = parse_env_file(secrets)["CANVAS_TOKEN"]
        assert reseeded in canvas.valid_tokens
        run([bot, "sondeo"], T_RENEW_6)
        after_reseed = take("Cadena resembrada")
        assert not any("cadena automática del token" in message["text"] for message in after_reseed)
        reseeded_health = doctor("después de resembrar", T_RENEW_6, broken=False)
        assert "✅ Token de Canvas: renovado hace un momento" in reseeded_health, reseeded_health
        report.append("`espol-bot doctor` mostró sondeo, lectura del aula, mantenimiento y edad del token sin "
                      "consultar el aula ni escribir al chat: todo ✅ con la cadena sana; tres horas sin que nada "
                      "corriera, ❌ en el sondeo, el mantenimiento y el token vencido (con qué revisar); con la "
                      "cadena cortada, ❌ en el token y cómo resembrarlo; y ✅ otra "
                      "vez tras resembrar")
        report.append("`espol-bot resembrar` también leyó un token con entrada oculta, lo verificó y lo dejó activo "
                      "sin imprimirlo ni enviarlo al chat")

        # Safety: read-only, captain-only, no secrets anywhere ---------------------------------
        mutations = [(method, urlsplit(path).path) for method, path in canvas.requests if method != "GET"]
        assert mutations and all(method in {"POST", "DELETE"} and
                                 (path == "/api/v1/users/self/tokens" or
                                  re.fullmatch(r"/api/v1/users/self/tokens/\d+", path))
                                 for method, path in mutations), mutations
        assert canvas.throttled, "el 429 de prueba debió ocurrir"
        assert any("page=2" in p for _, p in canvas.requests), "debió seguir la paginación"
        assert not any("5002" in p and "download" in p for _, p in canvas.requests), "archivo enorme no se baja"
        downloaded = {int(p.split("/")[2]) for _, p in canvas.requests if p.startswith("/files/")}
        assert downloaded == {5001, 5005, 5010, 5301, 5101}, \
            f"solo los sílabos se bajan solos; lo demás, cuando se pide: {sorted(downloaded)}"

        notif = ["# Mensajes de WhatsApp al capitán (en orden)\n",
                 "Cada bloque es un mensaje tal como llegó a su chat; una encuesta después de un mensaje son sus "
                 "botones.\n"]
        current = None
        for label, message in w.sent_log:
            if label != current:
                notif.append(f"\n## {label}\n")
                current = label
            notif.append(f"```\n{normalize(shown_text(message))}\n```\n")
        (ARTIFACT / "notificaciones.md").write_text("\n".join(notif), encoding="utf-8")
        (ARTIFACT / "resumen_diario.txt").write_text(normalize(summary[0]["text"]) + "\n", encoding="utf-8")
        (ARTIFACT / "recuperacion.json").write_text(normalize(json.dumps(retrieval, ensure_ascii=False, indent=2))
                                                    + "\n", encoding="utf-8")
        (ARTIFACT / "cli.md").write_text("\n".join(cli_md), encoding="utf-8")
        (ARTIFACT / "setup.log").write_text(normalize(setup_log), encoding="utf-8")
        requests_log = "\n".join(f"{method} {safe_canvas_path(path)}" for method, path in canvas.requests)
        (ARTIFACT / "canvas_requests.log").write_text(requests_log + "\n", encoding="utf-8")
        (ARTIFACT / "estado.md").write_text(normalize("\n".join(estado_md)), encoding="utf-8")
        (ARTIFACT / "token.md").write_text(normalize("\n".join(token_md)), encoding="utf-8")
        report += [
            f"Canvas falso: {len(canvas.requests)} solicitudes; las únicas mutaciones fueron crear y borrar los tokens "
            "propios de Vinci; paginación seguida; un 429 con reintento; Física con la pestaña Archivos oculta "
            "(material encontrado vía Módulos)",
            "Sondeo 3 y el resumen repetido no enviaron nada (sin duplicados)",
            "Instalación nueva con los anuncios de Física y los archivos de Cálculo fallando en distintos sondeos: lo "
            "demás siguió funcionando, una alerta por episodio y recurso (sondeos 3, 5 y 8) y lo leído al recuperarse "
            "se guardó sin reenviarse",
            *[f"Recuperación «{r['pregunta']}» → {r['resultados'][0]['archivo']}, {r['resultados'][0]['unidad']} "
              f"{r['resultados'][0]['pagina']} ✓" for r in retrieval],
        ]
        assert_no_secrets(w, "canvas")
    write_part("test_canvas", "Instalación, sondeos y token (sin gateway)", report, started)


def safe_canvas_path(path: str) -> str:
    return re.sub(r"verifier=[^&]+", "verifier=…", path)


def test_whatsapp_captain(tmp_path):
    """Section 10 for the captain, in his own chat: setup.sh routes his WhatsApp to Vinci; his week; /start and
    /token without the model (the page's ciphertext pasted when the relay is out of reach); the 07:00 summary with
    polls instead of buttons; the brief before a class as a system task Vinci answers in his chat; Vinci writes the
    notebook of the subject he names and asks which one when nothing says it; `vinci-check say` talks to it."""
    started = time.monotonic()
    with world(tmp_path) as w:
        if not w.hermes:
            pytest.skip("Hermes no está instalado aquí")
        w.md += ["# Vinci en WhatsApp: el chat del capitán\n"]
        ready_gateway(w)
        wa, llm, canvas, data_dir, profiles, home, md = w.wa, w.llm, w.canvas, w.data_dir, w.profiles, w.home, w.md
        say, fail, run, report, session, secrets = w.say, w.fail, w.run, w.report, w.session, w.secrets
        normalize = w.normalize
        bot = str(VENV_BIN / "espol-bot")
        captain_jid = CAPTAIN_JID

        default_env = parse_env_file(home / ".hermes" / ".env")
        assert default_env["WHATSAPP_ALLOWED_USERS"] == CAPTAIN_WA and default_env["WHATSAPP_GROUP_POLICY"] == "open"
        default_cfg = yaml.safe_load((home / ".hermes" / "config.yaml").read_text())
        routes = default_cfg["gateway"]["profile_routes"]
        assert [(r.get("user_id") or r.get("chat_id"), r["profile"]) for r in routes] == [
            (f"{CAPTAIN_WA}@s.whatsapp.net", "vinci"), (f"{CAPTAIN_LID}@lid", "vinci"), (CAPTAIN_WA, "vinci"),
            (None, "vinci")], \
            "el capitán va a Vinci; cualquier otro remitente, a las herramientas de invitado de Vinci y nunca al " \
            f"perfil por defecto: {routes}"
        shared = profiles / "vinci" / "platforms" / "whatsapp" / "session"
        assert shared.is_symlink() and shared.readlink() == session, "Vinci ve las equivalencias de LID del puente"
        assert "vinci-whatsapp" in default_cfg["plugins"]["enabled"]
        assert default_cfg["plugins"]["entries"]["vinci-whatsapp"]["allow_gateway_injection"] is True, \
            "only this plugin may put a question back in its chat (the Académico's sign-in)"
        plugin_src = (home / ".hermes" / "plugins" / "vinci-whatsapp" / "__init__.py").read_text()
        assert "{{" not in plugin_src and CAPTAIN_WA in plugin_src
        relay_line = f'RELAY = "{data_dir / "amigos" / "rele.json"}"'
        assert relay_line in plugin_src, "the default profile's copy polls the relay"
        assert (profiles / "vinci" / "plugins" / "vinci-whatsapp" / "__init__.py").read_text() == \
            plugin_src.replace(relay_line, 'RELAY = ""'), \
            "the gateway runs the dispatch hook with the routed profile's plugins: Vinci's needs it too (it does not poll)"
        assert not list(profiles.glob("vinci-*")), "sin Telegram no hay bots de materia: Vinci lleva cada materia"
        soul = (profiles / "vinci" / "SOUL.md").read_text()
        skill = (profiles / "vinci" / "skills" / "vinci" / "vinci" / "SKILL.md").read_text()
        assert "entregar_a_materia" not in soul + skill and "<!-- solo" not in soul + skill
        assert "Tus materias, en un solo chat" in skill, skill[:1500]
        report.append("setup.sh con WHATSAPP_CAPTAIN: el perfil por defecto de Hermes recibe el puente de WhatsApp, "
                      "una ruta por remitente (el capitán → Vinci; cualquier otro, a las herramientas de invitado de "
                      "Vinci) y el plugin vinci-whatsapp; no hay bots de materia, y el SOUL.md y la skill de Vinci "
                      "traen solo sus partes de WhatsApp")

        # 10a. The captain's own chat: his Vinci, his aula, no line per tool call
        week = say(captain_jid, captain_jid, "qué tengo esta semana", "Capitán")
        assert "Esta semana:" in text_of(week) and not any("⚙️" in m.get("message", "") for m in week), week

        # 10a'. Work handed in outside the aula stays pending, late, until he says it is done (and back with «todavía
        # no»); an exam held in class leaves on its own; one the aula does not explain stays, as unknown, until he says.
        template = json.loads((HERE / "fixtures" / "canvas" / "state1" / "courses" / "102" / "assignments.json")
                              .read_text())[-1]
        canvas.extra["courses/102/assignments"] = [
            {**template, "id": tid, "name": name, "submission_types": types, "due_at": due, "lock_at": None,
             "description": html_text, "html_url": f"{canvas.base}/courses/102/assignments/{tid}"}
            for tid, name, types, due, html_text in ELSEWHERE_TASKS]
        run([bot, "sondeo"], T_VINCI)
        listed = text_of(say(captain_jid, captain_jid, "qué tengo pendiente en Física", "Capitán"))
        assert "- Práctica 2 en el simulador [external_submission, atrasada]" in listed, listed
        assert "- Trabajo de vectores [unknown, atrasada]" in listed and "Lección 2" not in listed, listed
        done = text_of(say(captain_jid, captain_jid, "ya hice la práctica del simulador", "Capitán"))
        assert "cuenta como entregada" in done, done
        assert "Práctica 2" not in text_of(say(captain_jid, captain_jid, "qué tengo pendiente en Física", "Capitán"))
        undone = text_of(say(captain_jid, captain_jid, "me equivoqué, la práctica del simulador todavía no", "Capitán"))
        assert "vuelve a tus pendientes" in undone, undone
        said = text_of(say(captain_jid, captain_jid, "el trabajo de vectores se entrega por correo", "Capitán"))
        assert "external_submission (student)" in said, said
        report.append("Lo que se entrega fuera del aula sigue pendiente y atrasado aunque Canvas no reciba nada, en el "
                      "chat y en el resumen; con «ya hice…» sale y con «todavía no» vuelve. Un examen presencial que ya "
                      "pasó sale solo, y uno que el aula no explica queda como «unknown» hasta que él dice cómo se "
                      "entrega. El resumen de las 7:00 usa la misma lista")

        # 10g. Vinci's commands on WhatsApp, without the model
        calls = len(llm.requests)
        captain_hello = text_of(say(captain_jid, captain_jid, "/start", "Capitán"))
        assert "/amigo agregar" in captain_hello and "/estado" in captain_hello, captain_hello
        wa.missing.add("send-url-button")  # Hermes' own bridge.js: the page goes as a plain link
        form = text_of(say(captain_jid, captain_jid, "/token", "Capitán", expect=2))  # the guide, then the form
        wa.missing.discard("send-url-button")
        form_url = re.search(r"https://\S+[?&]k=[\w-]+\S*", form)[0]
        assert parse_qs(urlsplit(form_url).query).get("w") == ["1"], form_url
        # pasting what the page shows still works: what it does when it cannot reach the relay
        canvas.valid_tokens.add(CAPTAIN_WA_TOKEN)
        canvas.mint(CAPTAIN_WA_TOKEN, "Token personal")
        reseeded = text_of(say(captain_jid, captain_jid, page_seal(form_url, CAPTAIN_WA_TOKEN), "Capitán"))
        assert "Token verificado y guardado" in reseeded, reseeded
        assert parse_env_file(secrets)["CANVAS_TOKEN"] in canvas.valid_tokens
        assert len(llm.requests) == calls, "/start, /token y el texto cifrado no pasan por el modelo"
        mark = len(wa.sent)
        run([bot, "resumen"], T_VINCI)
        summary = wa.messages_to(captain_jid, mark)
        assert summary and "Resumen de tu semana" in text_of(summary), summary
        assert "Práctica 2 en el simulador" in text_of(summary) and "Lección 2" not in text_of(summary), \
            "the summary lists the late lab handed in elsewhere, as the chat does, and not the exam already held"
        assert "<b>" not in text_of(summary), text_of(summary)
        assert not any("Consultar con" in o for p in wa.polls_to(captain_jid, mark) for o in p["options"]), \
            "sin bots de materia no hay «Consultar con …»"
        md.append(f"**(resumen de las 7:00 del capitán)** → Vinci: {normalize(text_of(summary))[:300]}…\n")
        report.append("Los comandos de Vinci van por WhatsApp sin el modelo: /start (con los de /amigo, solo para el "
                      "capitán) y /token. Con un puente sin la ruta de botones, /token llega como enlace; el capitán "
                      "pegó el texto cifrado que muestra la página cuando no alcanza el relé, y su cadena del token "
                      "volvió a arrancar. El resumen de las 7:00 llega con formato de WhatsApp, sin HTML")

        # 10m. The brief before a class reaches the captain's chat as a system task Vinci answers there; Vinci
        # writes the notebooks itself («materia», or a question when no class tells which); vinci-check say.
        wa_mark, calls = len(wa.sent), len(llm.requests)
        run([bot, "agenda"], T_NO_TELEGRAM)
        brief = wa.wait_for(lambda b: [m for m in b.messages_to(captain_jid, wa_mark)
                                       if "📚 Brief de Cálculo" in m.get("message", "")], 120)
        assert brief, fail("el brief de Cálculo no llegó al chat de WhatsApp")
        seen = json.dumps(llm.requests[calls:], ensure_ascii=False)
        assert "[Tarea del sistema para Cálculo" in seen and "TAREA: brief_de_clase" in seen, seen[-1500:]
        md.append(f"→ Vinci (brief, tarea del sistema): {normalize(brief[0]['message'])}\n")

        calls = len(llm.requests)
        noted = text_of(say(captain_jid, captain_jid, "en el cuaderno de Cálculo pon que hoy vimos integrales dobles",
                            "Capitán"))
        assert "📘 Cálculo de una Variable · anotado en el cuaderno" in noted, noted
        offered = {t["function"]["name"] for r in llm.requests[calls:] if bot_of(r) == "Vinci"
                   for t in r.get("tools") or []}
        assert {"mcp__vinci__anotar", "mcp__vinci__guardar_adjunto", "ver_pagina", "ver_foto"} <= offered, offered
        assert not offered & {"mcp__vinci__entregar_a_materia", "mcp__vinci__proponer_equipo"}, offered
        calls = len(llm.requests)
        which = text_of(say(captain_jid, captain_jid, "pon en el cuaderno que no entendí la regla de L'Hôpital",
                            "Capitán"))
        assert "📘 Cálculo de una Variable · anotado en el cuaderno" in which, \
            f"sin materia, la nota va a la que nombró hace un momento: {which}"
        assert "Materia en foco: Cálculo de una Variable" in turn_context(llm.requests[calls:]), which

        # 10m'. A quiz left for something else stays open, out of the way, and is taken up where it was
        mark = len(wa.sent)
        say(captain_jid, captain_jid, "/quiz integrales dobles", "Capitán")
        polls = wa.wait_for(lambda b: b.polls_to(captain_jid, mark) if len(b.polls_to(captain_jid, mark)) == 2
                            else None, 30)
        assert polls and polls[0]["question"].startswith("1/2."), fail(f"el quiz no llegó: {wa.sent[mark:]}")
        mark = len(wa.sent)
        wa.vote(captain_jid, captain_jid, polls[0]["messageId"], polls[0]["options"][0])
        assert wa.wait_for(lambda b: b.messages_to(captain_jid, mark), 60), fail("el voto no tuvo respuesta")
        calls = len(llm.requests)
        assert "Esta semana:" in text_of(say(captain_jid, captain_jid, "qué tengo esta semana", "Capitán"))
        seen = turn_context(llm.requests[calls:])
        assert re.search(r"Actividades abiertas aquí: #\d+ quiz «Integrales dobles» de Cálculo de una Variable "
                         r"\(en curso\): respondió 1 de 2", seen), seen
        mark = len(wa.sent)
        resumed = text_of(say(captain_jid, captain_jid, "sigamos con el quiz", "Capitán"))
        assert "Le mandé de nuevo las 1 pregunta(s)" in resumed, resumed
        again = wa.polls_to(captain_jid, mark)
        assert [p["question"][:4] for p in again] == ["2/2."], again
        mark = len(wa.sent)
        wa.vote(captain_jid, captain_jid, again[0]["messageId"], again[0]["options"][0])
        score = wa.wait_for(lambda b: [m for m in b.messages_to(captain_jid, mark) if "Quiz: Integrales dobles" in m.get("message", "")],
                            60)
        assert score, fail(f"sin puntaje al terminar: {wa.messages_to(captain_jid, mark)}")
        # 10m3. «Tengo 20 minutos»: a session planned from his open doubts; what he struggled with goes to the
        # notebook once he says yes. A jury asks first what it judges.
        planned = text_of(say(captain_jid, captain_jid, "tengo 20 minutos para Cálculo", "Capitán"))
        assert "La regla de L'Hôpital" in planned, planned
        say(captain_jid, captain_jid, "me costó el 0/0", "Capitán")
        calls = len(llm.requests)
        saved = text_of(say(captain_jid, captain_jid, "listo, guarda lo que me costó", "Capitán"))
        assert "Sesión de estudio «Límites»: límites 0/0" in saved, saved
        assert "sesión de estudio «Límites»" in turn_context(llm.requests[calls:]), "la sesión estaba abierta"
        jury = text_of(say(captain_jid, captain_jid, "hazme de jurado para la exposición", "Capitán"))
        assert "El jurado pregunta sobre algo concreto" in jury, jury
        md.append(f"**Capitán**: tengo 20 minutos para Cálculo → Vinci: {normalize(planned)}; «me costó el 0/0»; "
                  f"«listo, guarda lo que me costó» → {normalize(saved)}\n")

        # 10m''. What became of a PDF comes from the table the vote writes, in every private turn
        db = sqlite3.connect(data_dir / "espol.db")
        db.execute("INSERT INTO submission_proposals(subject, course_id, assignment_id, assignment_name, pdf, pages, "
                   "created_at) VALUES ('FIS', 102, 3005, 'Tarea 3: Dinámica', '/tmp/tarea3.pdf', 2, "
                   "'2026-09-30T13:00:00Z')")
        db.commit()
        db.close()
        calls = len(llm.requests)
        say(captain_jid, captain_jid, "ya quedó entregada la tarea 3?", "Capitán")
        seen = turn_context(llm.requests[calls:])
        assert "el PDF de «Tarea 3: Dinámica» (2 pág.) espera su voto «Entregar»: todavía NO está entregado" in seen, seen
        md.append(f"**Capitán**: /quiz integrales dobles → [2 encuestas]; vota la 1; «qué tengo esta semana»; "
                  f"«sigamos con el quiz» → Vinci: {normalize(resumed)} → [la 2/2 otra vez]; vota → "
                  f"{normalize(text_of(score))[:200]}\n")

        checked = run([str(VENV_BIN / "vinci-check"), "say", "qué tengo esta semana", "--timeout", "150"], T_VINCI,
                      check=False)
        assert checked.returncode == 0 and "Esta semana:" in checked.stdout, checked.stdout + checked.stderr
        report.append("`espol-bot agenda` pone el brief de Cálculo en el chat del capitán como tarea del sistema y "
                      "Vinci lo contesta ahí; Vinci escribe el cuaderno de la materia que le nombran, y una nota sin "
                      "materia va a la de la que venían hablando (la «materia en foco» que ve en cada mensaje). Un "
                      "quiz que deja a medias para preguntar otra cosa sigue abierto en el contexto («respondió 1 de "
                      "2»); «sigamos con el quiz» le vuelve a mandar solo la pregunta que faltaba, y al votarla llega "
                      "el puntaje. `vinci-check say` le escribe por WhatsApp y lee su respuesta")

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        panel = subprocess.Popen([bot, "panel", "--puerto", str(port)], env={**w.base_env, "AULA_NOW": T_VINCI},
                                 cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(50):
                with contextlib.suppress(requests.ConnectionError):
                    page = requests.get(base, timeout=5)
                    break
                time.sleep(0.2)
            assert page.status_code == 200 and "Vinci · panel" in page.text
            state = requests.get(f"{base}/api/estado", timeout=30).json()
            assert state["gateway"]["alive"] and state["gateway"]["state"] == "running", state["gateway"]
            assert {c["name"] for c in state["checks"]} == {"Sondeo", "Aula virtual", "Mantenimiento",
                                                            "Token de Canvas"}, state["checks"]
            assert {"vinci-sondeo", "vinci-mantenimiento", "vinci-resumen"} <= {j["name"] for j in state["jobs"]}
            assert any(u["profile"] == "vinci" and u["calls"] for u in state["usage"]), "el gasto de Vinci sale"
            chat = next(s for s in state["sessions"] if s["profile"] == "vinci" and s["source"] == "whatsapp"
                        and s["chat_type"] == "dm")
            assert chat["readable"] and chat["reply_seconds"] is not None, chat
            detail = requests.get(f"{base}/api/sesion", params={"perfil": "vinci", "id": chat["id"]}, timeout=10).json()
            assert any("qué tengo esta semana" in (st["text"] or "") for st in detail["steps"]), detail["steps"][-6:]
            assert requests.get(f"{base}/api/sesion", params={"perfil": "vinci", "id": "nada"}, timeout=10
                                ).status_code == 404
        finally:
            panel.terminate()
            panel.wait(10)
        report.append("`espol-bot panel` muestra el gateway vivo, la salud de Vinci, sus tareas automáticas, su gasto "
                      "y la conversación del capitán con sus pasos, sin tocar el modelo ni el aula")
        (ARTIFACT / "whatsapp-capitan.md").write_text("\n".join(md), encoding="utf-8")
        assert_no_secrets(w, "capitán")
    write_part("test_whatsapp_captain", "WhatsApp: el chat del capitán", w.report, started)


def test_academico(tmp_path):
    """Section 10k: ESPOL's Académico from the captain's WhatsApp chat (academico_flow)."""
    started = time.monotonic()
    with world(tmp_path) as w:
        if not w.hermes:
            pytest.skip("Hermes no está instalado aquí")
        ready_gateway(w)
        academico_flow(w)
    write_part("test_academico", "El Académico de ESPOL", w.report, started)


def test_whatsapp_friend(tmp_path):
    """Section 10 for a friend: a group the captain turns on, Angel invited with a Vinci of his own (his token through
    the page and Vinci's relay, his week, slides, a quote, a sticker, a group that goes idle, a poll for a button, his
    dashboard, his commands), voice notes and audio files heard by the real local Whisper (in a group, only one that
    says «Vinci»), his alerts, the block for whoever is not a Vinci's owner, and Angel removed with his tokens."""
    started = time.monotonic()
    with world(tmp_path) as w:
        if not w.hermes:
            pytest.skip("Hermes no está instalado aquí")
        w.md += ["# Vinci en WhatsApp: el grupo y el Vinci de Angel\n",
                 "Lo que llega al puente de WhatsApp de Hermes (aquí FakeWhatsApp): cada mensaje con quién lo escribe, y "
                 "lo que Vinci contesta.\n"]
        ready_gateway(w, voice=True)
        wa, llm, relay, canvas, data_dir, profiles, home, md = w.wa, w.llm, w.relay, w.canvas, w.data_dir, w.profiles, w.home, w.md
        say, fail, gateway, start, run, report, session = w.say, w.fail, w.gateway, w.start, w.run, w.report, w.session
        patch_profile, pause_crons, normalize = w.patch_profile, w.pause_crons, w.normalize
        bot = str(VENV_BIN / "espol-bot")
        captain_jid, angel_jid, stranger_jid = (f"{n}@s.whatsapp.net" for n in (CAPTAIN_WA, ANGEL_WA, STRANGER_WA))
        # 10a. The captain's week, to compare with Angel's in the group
        week = say(captain_jid, captain_jid, "qué tengo esta semana", "Capitán")
        assert "Esta semana:" in text_of(week) and not any("⚙️" in m.get("message", "") for m in week), week
        captain_week = text_of(week)

        # 10b. A group that is off: nothing, not even to the captain; he turns it on
        say(GROUP_WA, captain_jid, "@vinci hola", "Capitán", group=True, expect=0)
        on = say(GROUP_WA, captain_jid, "@vinci activa este grupo", "Capitán", group=True)
        assert "le contesto a quien me mencione" in text_of(on)
        assert json.loads((data_dir / "amigos" / "whatsapp.json").read_text())["grupos"] == [GROUP_WA]
        calls = len(llm.requests)
        nobody = text_of(say(GROUP_WA, stranger_jid, "@vinci qué tengo esta semana", "Alguien", group=True))
        assert "Eso es del dueño" in nobody and "Esta semana:" not in nobody, nobody
        guest_turns = [flatten([m for m in r["messages"] if m.get("role") == "user"][-1].get("content"))
                       for r in llm.requests[calls:] if bot_of(r) == "Vinci"]
        assert guest_turns and "[Alguien, invitado sin su propio Vinci, te escribe" in guest_turns[0], guest_turns
        report.append("Un grupo apagado no recibe nada; con «@vinci activa este grupo» el capitán lo enciende, y a "
                      "quien no tiene su Vinci le contesta Vinci como invitado: el modelo sabe que es un invitado y el "
                      "gancho pre_tool_call le niega los datos del capitán")

        # 10b''. What holds in one chat stays there: the group asks to be spoken to in plural (chat_note). Every turn
        # ends with the clock and that chat's notes; the captain's private chat gets the clock, not the group's note.
        planned = say(GROUP_WA, captain_jid, "@vinci recuérdanos mañana a las 9 y el viernes a mediodía que hay que "
                      "entregar las historias de usuario", "Capitán", group=True)
        assert "sale en este grupo el jue 1 oct, 09:00 y el vie 2 oct, 12:00" in text_of(planned), text_of(planned)
        noted = say(GROUP_WA, captain_jid, "@vinci en este grupo háblanos en plural", "Capitán", group=True)
        assert "Guardada como #" in text_of(noted), text_of(noted)
        calls = len(llm.requests)
        say(GROUP_WA, captain_jid, "@vinci hola", "Capitán", group=True)
        say(captain_jid, captain_jid, "hola", "Capitán")
        turns = [flatten([m for m in r["messages"] if m.get("role") == "user"][-1].get("content"))
                 for r in llm.requests[calls:] if bot_of(r) == "Vinci"]
        in_group = [t for t in turns if "te escribe en un grupo" in t]
        in_private = [t for t in turns if "te escribe en un grupo" not in t]
        assert in_group and in_private, turns
        assert "Ahora: miércoles 30 sep 2026, 08:30" in in_group[-1] and "en plural" in in_group[-1], in_group[-1]
        assert "Chat: su chat privado contigo." in in_private[-1] and "en plural" not in in_private[-1], in_private[-1]
        assert "Recordatorios que el sistema mandará a este grupo: #" in in_group[-1], in_group[-1]
        assert "Recordatorios que" not in in_private[-1], in_private[-1]
        mark = len(wa.sent)
        for _ in range(2):  # the second tick must not repeat it
            run([bot, "agenda"], "2026-10-01T09:00:20-05:00")
        time.sleep(2)
        reminded = [m for m in wa.messages_to(GROUP_WA, mark) if "Recordatorio" in m.get("message", "")]
        assert len(reminded) == 1 and GROUP_REMINDER in reminded[0]["message"], reminded
        assert "<b>" not in reminded[0]["message"], reminded[0]["message"]
        md.append(f"→ Vinci (recordatorio al grupo, jue 09:00): {normalize(reminded[0]['message'])}\n")
        report.append("Cada turno termina con la hora de ahora y las notas de ese chat: «háblanos en plural» queda como "
                      "nota del grupo (chat_note) y llega en cada mensaje del grupo, nunca al chat privado del capitán")
        report.append("«@vinci recuérdanos mañana a las 9 y el viernes a mediodía…» programa dos recordatorios del grupo "
                      "(group_reminder) que Vinci ve en el contexto del grupo; `espol-bot agenda` manda el del jueves "
                      "al grupo a su hora, una sola vez y sin el modelo")

        # 10b'. «@vinci activa los avisos»: the agenda tick before a class reminds the group, without the model, once
        notices = say(GROUP_WA, captain_jid, "@vinci activa los avisos", "Capitán", group=True)
        assert "aviso antes de cada clase" in text_of(notices), text_of(notices)
        assert json.loads((data_dir / "amigos" / "whatsapp.json").read_text())["avisos"] == [GROUP_WA]
        mark = len(wa.sent)
        run([bot, "agenda"], T_NO_TELEGRAM)
        reminder = wa.wait_for(lambda b: [m for m in b.messages_to(GROUP_WA, mark)
                                          if "Clase en 30 min: Cálculo" in m.get("message", "")], 30)
        assert reminder, fail("el recordatorio de Cálculo no llegó al grupo")
        assert "<b>" not in reminder[0]["message"], reminder[0]["message"]
        assert wa.wait_for(lambda b: [m for m in b.messages_to(captain_jid, mark)
                                      if "📚 Brief de Cálculo" in m.get("message", "")], 120), \
            fail("con los avisos del grupo, el brief del capitán no llegó")
        run([bot, "agenda"], T_NO_TELEGRAM)
        time.sleep(2)
        assert len([m for m in wa.messages_to(GROUP_WA, mark) if "Clase en 30 min" in m.get("message", "")]) == 1
        assert not [m for m in wa.messages_to(GROUP_WA, mark) if "Recordatorio" in m.get("message", "")], \
            "el recordatorio del viernes, días tarde, no debe salir"
        md.append(f"→ Vinci (aviso al grupo): {normalize(reminder[0]['message'])}\n")
        report.append("Con «@vinci activa los avisos», `espol-bot agenda` manda al grupo un recordatorio antes de la "
                      "clase, una sola vez y sin el modelo, y el brief del capitán sigue llegando a su chat")

        # 10c. The captain invites Angel: his own private chat gets the link to the page
        invited = say(captain_jid, captain_jid, "/amigo agregar 099 000 0002 Angel", "Capitán")
        assert "Le escribí a Angel" in text_of(invited)
        got = wa.wait_for(lambda b: (lambda m: m if len(m) >= 2 else None)(b.messages_to(angel_jid)), 30)
        assert got and got[0]["path"] == "send-media" and got[0]["filePath"].endswith("token-guide.png"), \
            f"the guide with the steps comes first: {got}"
        letter = got[1:]
        assert "Hola, Angel" in letter[0]["message"] and "Integraciones aprobadas" in letter[0]["message"], letter
        assert letter[0]["path"] == "send-url-button" and letter[0]["buttonText"] == "🔑 Abrir formulario", letter
        url = letter[0]["url"]
        query = parse_qs(urlsplit(url).query)
        assert query.get("w") == ["1"] and query.get("r") == [relay.base], url
        assert re.fullmatch(r"m=[\w-]{22,64}", urlsplit(url).fragment), "the mailbox rides in the fragment"
        assert "toca «Enviar cifrado a Vinci»" in letter[0]["message"] and "v1." not in letter[0]["message"], letter
        md.append(f"→ a Angel, por privado: {normalize(letter[0]['message'])} [botón «{letter[0]['buttonText']}»]\n")
        friends = json.loads((data_dir / "amigos" / "amigos.json").read_text())["amigos"]
        assert [(f["nombre"], f["numero"], f["estado"]) for f in friends] == [("Angel", ANGEL_WA, "pendiente")]
        calls = len(llm.requests)
        say(GROUP_WA, angel_jid, "@vinci hola", "Angel", group=True)
        waiting = [flatten([m for m in r["messages"] if m.get("role") == "user"][-1].get("content"))
                   for r in llm.requests[calls:] if bot_of(r) == "Vinci"]
        assert waiting and "[Angel, invitado: ya lo agregaron y le falta conectar su aula" in waiting[0], waiting
        raw = say(angel_jid, angel_jid, f"este es mi token {ANGEL_TOKEN}", "Angel")
        assert "bórralo de este chat" in text_of(raw)

        # 10d. Angel sends his token from the page: it reaches Vinci through the relay, sealed; his token is checked,
        # his aula read, his Vinci set up, and he is told in his chat. Nothing to paste.
        canvas.add_account(ANGEL_TOKEN, "canvas-amigo")
        calls, mark = len(llm.requests), len(wa.sent)
        relay.messages.append({"id": "R-stray", "mailbox": "M" * 32, "data": {"kind": "token", "sealed": "v1.x"},
                               "at": 0})  # someone posting to a mailbox Vinci never issued
        page_send(url, ANGEL_TOKEN)
        done = wa.wait_for(lambda b: [m for m in b.messages_to(angel_jid, mark)
                                      if "ya veo tus 2 materias" in m.get("message", "")], 240)
        assert done, fail(f"el token de Angel no llegó por el relé: {wa.sent[mark:]}")
        md.append(f"**Angel** pulsa «Enviar» en la página (por el relé) → Vinci: {normalize(done[0]['message'])}\n")
        assert len(llm.requests) == calls, "el texto cifrado no pasa por el modelo"
        assert relay.messages == [], "Vinci borra del relé lo que atendió, y lo que nadie pidió"
        assert all(m["data"].get("sealed", "").startswith("v1.") for m in relay.posted), "el relé solo ve cifrado"
        page_send(url, ANGEL_TOKEN)  # the same link again: its mailbox served once
        time.sleep(8)
        assert not [m for m in wa.messages_to(angel_jid, mark) if "materias" in m.get("message", "")][1:], \
            "un enlace, un token"
        told = wa.wait_for(lambda b: [m for m in b.messages_to(captain_jid) if "Angel ya tiene su Vinci" in
                                      m.get("message", "")], 30)
        assert told, "el capitán se entera de que Angel ya tiene su Vinci"
        angel_profile = profiles / "amigo-angel"
        assert (angel_profile / "SOUL.md").exists() and "Angel" in (angel_profile / "SOUL.md").read_text()
        angel_dir = data_dir / "amigos" / "angel"
        angel_secrets = parse_env_file(angel_dir / "secrets.env")
        assert angel_secrets["WHATSAPP_OWNER"] == ANGEL_WA and angel_secrets["CANVAS_TOKEN"] != ANGEL_TOKEN, \
            "el token de Angel ya tiene un sucesor de su propia cadena"
        assert stat.S_IMODE(angel_dir.stat().st_mode) == 0o700
        default_env = parse_env_file(home / ".hermes" / ".env")
        assert default_env["WHATSAPP_ALLOWED_USERS"] == f"{CAPTAIN_WA},{ANGEL_WA}"
        routes = yaml.safe_load((home / ".hermes" / "config.yaml").read_text())["gateway"]["profile_routes"]
        assert (f"{ANGEL_WA}@s.whatsapp.net", "amigo-angel") in [(r.get("user_id"), r["profile"]) for r in routes]
        assert (angel_profile / "platforms" / "whatsapp" / "session").readlink() == session
        jobs = {j["name"]: j for j in json.loads((angel_profile / "cron" / "jobs.json").read_text())["jobs"]}
        assert set(jobs) == {"amigo-sondeo", "amigo-mantenimiento", "amigo-resumen"}
        assert all(j["deliver"] == "local" for j in jobs.values())
        report.append("«/amigo agregar 099 000 0002 Angel»: Vinci le escribe a Angel por privado con un botón a la "
                      "página (modo WhatsApp, con el relé y un buzón de un uso en el enlace); Angel pulsa «Enviar» y "
                      "el token llega cifrado por el relé, sin pegar nada ni pasar por el modelo: se verifica, "
                      "arranca su propia cadena de renovación, se lee su aula y queda su Vinci (perfil amigo-angel, "
                      "sus crons, su ruta). El mismo enlace no sirve dos veces, y Vinci descarta lo que llega a un "
                      "buzón que no abrió")

        # 10e. After the restart that loads his route: Angel's own week, in the same group as the captain
        gateway.stop()
        patch_profile("amigo-angel")
        pause_crons()  # his own, and any the provisioning resumed
        start()
        his = text_of(say(GROUP_WA, angel_jid, "@vinci qué tengo esta semana", "Angel", group=True))
        assert "Integrales dobles" in his and "EDO de primer orden" in his, his
        mine = text_of(say(GROUP_WA, captain_jid, "@vinci qué tengo esta semana", "Capitán", group=True))
        assert "Integrales dobles" not in mine and mine.splitlines()[1:3] == captain_week.splitlines()[1:3], mine
        items = [{line for line in answer.splitlines() if line.startswith("- ")} for answer in (his, mine)]
        assert items[0] and items[1] and not items[0] & items[1], "cada uno ve solo lo suyo"
        report.append("En el mismo grupo, «@vinci qué tengo esta semana» le contesta a Angel con su aula (Cálculo "
                      "de varias variables, Ecuaciones diferenciales) y al capitán con la suya: ninguna entrega se "
                      "cruza")

        # 10f. Slides: the file reaches the chat
        mark = len(wa.sent)
        say(angel_jid, angel_jid, "hazme unas diapositivas de integrales dobles", "Angel")
        media = wa.wait_for(lambda b: [m for m in b.sent[mark:] if m["path"] == "send-media"], 60)
        assert media and media[0]["filePath"].endswith(".pptx"), fail(f"no llegó el .pptx: {wa.sent[mark:]}")
        from pptx import Presentation
        deck = Presentation(media[0]["filePath"])
        assert [s.shapes.title.text for s in deck.slides] == ["Integrales dobles", "¿Qué es una integral doble?",
                                                             "Cómo se calcula"]
        report.append("«hazme unas diapositivas»: crear_diapositivas arma el .pptx (portada y una diapositiva por "
                      "tema, con notas) y Hermes lo adjunta en el chat de WhatsApp")

        # 10f2. WhatsApp mentions arrive as «@<number>»: Vinci gets «@vinci» and the person's name instead, and
        # reads what an assignment asks for (its instructions, as the professor wrote them)
        # In a group WhatsApp writes the mention with Vinci's LID, which Hermes does not strip (only the number).
        bot_lid = "880000000000001"
        calls = len(llm.requests)
        taller = text_of(say(GROUP_WA, angel_jid, f"@{bot_lid} qué pide el taller 2? y avísale a @{CAPTAIN_WA}",
                             "Angel", group=True, mentions=[FakeWhatsApp.BOT]))
        assert "ejercicios 3, 5 y 8 de la sección 15.2" in taller and "un solo PDF" in taller, taller
        # The annexes come from a «Proyectos/2023» folder the Files tab already lists, the first one linked by
        # an icon with no text: they are still this assignment's, and the .doc template gets read.
        task = next(data for req in llm.requests[calls:] for m in req.get("messages") or [] if m.get("role") == "tool"
                    for data in [_json(flatten(m.get("content")))] if isinstance(data, dict) and "consigna" in data)
        assert [f["archivo"] for f in task["archivos"]] == ["taller-2-especificacion.pdf", "plantilla-taller.doc"]
        assert "semestre_anterior" not in json.dumps(task), task
        assert (task["vence"], task["cierra"]) == ("jue 1 oct, 23:59", "vie 2 oct, 23:59"), task
        assert task["rubrica"]["criterios"][0] == {
            "criterio": "Planteamiento de los límites", "puntos": 6,
            "detalle": "Dibuja la región y fija bien los límites de integración",
            "niveles": ["Completo: 6 pts", "Sin planteamiento: 0 pts"]}, task["rubrica"]
        assert "Resultado final, 4 pts" in taller and "hasta vie 2 oct, 23:59" in taller, taller
        assert "Cada ejercicio con su gráfica de la región de integración" in taller, taller
        seen = json.dumps(llm.requests[calls:], ensure_ascii=False)
        assert "@vinci qué pide el taller 2? y avísale a @Capitán" in seen, seen[-2000:]
        assert f"@{bot_lid}" not in seen and f"@{CAPTAIN_WA}" not in seen
        assert "[Angel te escribe en un grupo de WhatsApp]\\n@vinci qué pide el taller 2?" in seen, seen[-2000:]
        report.append("En un grupo, una mención llega a WhatsApp como «@número»: el plugin se la pasa al modelo como "
                      "«@vinci» o con el nombre de la persona (Angel ve «@Capitán»). «¿Qué pide el taller 2?»: "
                      "ver_tarea le trae la consigna que escribió el profesor (ejercicios, formato, páginas), la "
                      "rúbrica del aula, la fecha y el cierre en hora de Ecuador, y los anexos que enlaza aunque "
                      "estén en una carpeta de 2023; la plantilla .doc se lee con LibreOffice")

        # 10f2b. Every Vinci in a group speaks from the same account: a quote is this Vinci's own only when its
        # text is in this conversation. A sticker reaches no Vinci. A group idle for GROUP_IDLE seconds
        # starts a new conversation, with no notice to anyone.
        def last_turn(since: int) -> str:  # what this message brought; the requests also carry the chat so far
            req = next(r for r in llm.requests[since:] if bot_of(r))
            return flatten([m for m in req["messages"] if m.get("role") == "user"][-1].get("content"))

        calls = len(llm.requests)
        say(GROUP_WA, angel_jid, "@vinci y eso?", "Angel", group=True, mentions=[FakeWhatsApp.BOT],
            quote=taller.splitlines()[0])
        mine = last_turn(calls)
        assert "Replying to your previous message" in mine and "no está en tu conversación" not in mine, mine
        calls = len(llm.requests)
        say(GROUP_WA, angel_jid, "@vinci y eso?", "Angel", group=True, mentions=[FakeWhatsApp.BOT],
            quote=text_of(on))
        theirs = last_turn(calls)
        assert "no está en tu conversación" in theirs and "your previous message" not in theirs, theirs

        def plugin_skips(reason: str) -> int:
            return sum(f.read_text(errors="replace").count(f"vinci-whatsapp: {reason}")
                       for f in (home / ".hermes").glob("**/logs/gateway.log"))

        webp = home / ".hermes" / "cache" / "images" / "sticker_e2e.webp"
        webp.parent.mkdir(parents=True, exist_ok=True)
        webp.write_bytes(b"RIFF\x1a\x00\x00\x00WEBPVP8L\r\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07\x00")
        mark, calls, before = len(wa.sent), len(llm.requests), plugin_skips("sticker")
        wa.sticker(GROUP_WA, angel_jid, webp, name="Angel", group=True, quote=taller.splitlines()[0])
        md.append("**Angel** (grupo): [un sticker, en respuesta a Vinci]\n→ (sin respuesta)\n")
        assert wa.wait_for(lambda _: plugin_skips("sticker") > before, 60), fail("el sticker llegó a un Vinci")
        time.sleep(3)
        assert not wa.messages_to(GROUP_WA, mark) and len(llm.requests) == calls

        time.sleep(GROUP_IDLE + 2)
        mark, calls = len(wa.sent), len(llm.requests)
        fresh = say(GROUP_WA, angel_jid, "@vinci hola de nuevo", "Angel", group=True, mentions=[FakeWhatsApp.BOT])
        first = next(r for r in llm.requests[calls:] if bot_of(r))
        assert not [m for m in first["messages"] if m.get("role") == "assistant"], "la charla vieja del grupo siguió"
        assert len(fresh) == 1 and "Hola, soy tu Vinci" in text_of(fresh), fresh
        report.append("En un grupo, cada mensaje le llega a su Vinci con quién lo escribe, ya revisado por su número. "
                      "Todos los Vincis escriben desde la misma cuenta: una cita es «tu mensaje anterior» solo si "
                      "su texto está en esa conversación, y si no, el modelo sabe que es del Vinci de otra persona. "
                      f"Un sticker no llega a ningún Vinci. Tras un rato sin mensajes (4 h; {GROUP_IDLE} s aquí), el grupo "
                      "empieza una conversación nueva, sin aviso")

        # 10f2c. A question about an assignment: first which one (by its words, among all of the semester), then its
        # own attachments, marked, before the rest of the course's material
        calls = len(llm.requests)
        how = text_of(say(angel_jid, angel_jid, "en el taller de integrales, cómo va cada ejercicio?", "Angel"))
        tool_data = [data for req in llm.requests[calls:] for m in req.get("messages") or [] if m.get("role") == "tool"
                     for data in [_json(flatten(m.get("content")))] if isinstance(data, dict)]
        found = next(d for d in tool_data if "candidatas" in d)
        assert found["candidatas"][0]["tarea"] == "Taller 2: Integrales dobles", found
        searched = next(d for d in tool_data if "resultados" in d)
        assert searched["tarea"]["id"] == found["candidatas"][0]["id"], searched
        assert searched["resultados"][0].get("de_la_tarea") and searched["resultados"][0]["archivo"] in (
            "taller-2-especificacion.pdf", "plantilla-taller.doc"), searched["resultados"]
        assert "aparte, con el «enunciado» copiado arriba" in how and "📄 taller-2-especificacion.pdf" in how, how
        md.append(f"**Angel**: en el taller de integrales, cómo va cada ejercicio? → Vinci: {normalize(how)}\n")
        report.append("«En el taller de integrales…»: `tareas` con `buscar` encuentra el Taller 2 por sus palabras, y "
                      "`buscar_material` con su `tarea_id` trae primero sus anexos, marcados «de_la_tarea», con su cita")

        # 10f2d. A PDF summary: a citation of a page Vinci never read is refused, and the PDF links the real one
        mark, calls = len(wa.sent), len(llm.requests)
        say(angel_jid, angel_jid, "hazme un resumen en pdf del taller de integrales", "Angel")
        media = wa.wait_for(lambda b: [m for m in b.sent[mark:] if m["path"] == "send-media"], 60)
        assert media and media[0]["filePath"].endswith(".pdf"), fail(f"no llegó el PDF: {wa.sent[mark:]}")
        tool_text = [flatten(m.get("content")) for req in llm.requests[calls:] for m in req.get("messages") or []
                     if m.get("role") == "tool"]
        assert any("no salen de páginas que leíste" in t and "Inventado.pdf" in t for t in tool_text), tool_text
        summary = pypdf.PdfReader(media[0]["filePath"])
        summary_text = " ".join(page.extract_text() for page in summary.pages)
        links = [a.get_object()["/A"]["/URI"] for page in summary.pages for a in page.get("/Annots") or []]
        assert all(t in summary_text for t in ("Taller 2: Integrales dobles", "Qué pide el taller", "Un ejercicio por hoja",
                                               "Figura 1", *SUMMARY_STEPS, "Figura 2")), summary_text
        assert "1. Qué pide" not in summary_text, "el PDF numera las secciones, sin el número del modelo"
        assert any(page.images for page in summary.pages), "la página del material va como imagen"
        assert "Inventado" not in summary_text and links and all("/files/9" not in u for u in links), links
        report.append("«hazme un resumen en pdf»: crear_resumen rechaza una cita de una página que Vinci no leyó, y "
                      "el PDF (portada, índice, secciones con un flujo dibujado y la página del material como imagen, fuentes con su enlace del aula y «Para recordar») llega al chat de WhatsApp")

        # 10f3. WhatsApp has no buttons: a card arrives as a message and a poll, and a vote is the button
        mark = len(wa.sent)
        say(angel_jid, angel_jid, "anota: repasar integrales dobles", "Angel")
        polls = wa.wait_for(lambda b: b.polls_to(angel_jid, mark), 30)
        assert polls and polls[0]["options"] == ["✅ Hecho", "⏳ Todavía no"], fail(f"sin encuesta: {wa.sent[mark:]}")
        card = text_of(wa.messages_to(angel_jid, mark))
        assert "repasar integrales dobles" in card, card
        # the vote only after the model's own reply: a late «Anotado» would pass for the vote's answer
        assert wa.wait_for(lambda b: [m for m in b.messages_to(angel_jid, mark)
                                      if m.get("message", "").startswith("Anotado")], 60), wa.sent[mark:]
        calls, mark = len(llm.requests), len(wa.sent)
        wa.vote(angel_jid, angel_jid, polls[0]["messageId"], "✅ Hecho")
        # the vote's answer, not the model's «Anotado» if it lands after the poll
        done = wa.wait_for(lambda b: [m for m in b.messages_to(angel_jid, mark)
                                      if "Hecho: «repasar integrales dobles»" in m.get("message", "")], 60)
        assert done, wa.messages_to(angel_jid, mark)
        assert len(llm.requests) == calls, "un voto se resuelve sin el modelo"
        md.append(f"→ a Angel: [encuesta «{polls[0]['question']}»: {' / '.join(polls[0]['options'])}]\n"
                  f"**Angel** vota «✅ Hecho» → Vinci: {normalize(text_of(done))}\n")
        report.append("WhatsApp no tiene botones: «anota: repasar integrales dobles» le llega a Angel como mensaje y "
                      "una encuesta «✅ Hecho / ⏳ Todavía no» en su chat privado; su voto cierra el pendiente como "
                      "lo haría un botón, sin el modelo")

        # 10f3b. A quiz asked for in the group goes to the group: anyone there votes (a guest, Angel, the captain), the
        # first vote counts, and the group gets everyone's results once all three answered it all; a second quiz only
        # Angel finishes closes when its 15 minutes are up, with his results alone
        def group_quiz() -> list[dict]:
            mark = len(wa.sent)
            asked = say(GROUP_WA, stranger_jid, "@vinci hazme un quiz del sílabo de cálculo aquí", "Alguien", group=True)
            polls = wa.wait_for(lambda b: (lambda p: p if len(p) == 2 else None)(b.polls_to(GROUP_WA, mark)), 30)
            assert polls, fail(f"el quiz no llegó al grupo: {text_of(asked)} {wa.sent[mark:]}")
            assert not wa.polls_to(captain_jid, mark), "un quiz pedido en el grupo no va al chat privado del capitán"
            assert all(o[0] in quiz_module.GROUP_LETTERS and o[1] == " " for p in polls for o in p["options"]), polls
            return polls

        def option(poll: dict, answer: str) -> str:
            return next(o for o in poll["options"] if o[2:] == answer)

        def results(since: int) -> list[dict]:
            return [m for m in wa.messages_to(GROUP_WA, since) if "Quiz: Sílabo de Cálculo" in m.get("message", "")]

        units, credits = group_quiz()
        calls, mark = len(llm.requests), len(wa.sent)
        wa.vote(GROUP_WA, stranger_jid, units["messageId"], option(units, "Unidad 4"))
        wa.vote(GROUP_WA, stranger_jid, units["messageId"], option(units, "Unidad 1"))  # a changed vote: not counted
        wa.vote(GROUP_WA, stranger_jid, credits["messageId"], option(credits, "2"))
        wa.vote(GROUP_WA, angel_jid, units["messageId"], option(units, "Unidad 4"))
        wa.vote(GROUP_WA, angel_jid, credits["messageId"], option(credits, "4"))
        wa.vote(GROUP_WA, captain_jid, units["messageId"], option(units, "Unidad 1"))
        time.sleep(6)
        assert not results(mark), f"nada antes de que respondan todos: {wa.messages_to(GROUP_WA, mark)}"
        wa.vote(GROUP_WA, captain_jid, credits["messageId"], option(credits, "4"))
        everyone = wa.wait_for(lambda b: results(mark), 60)
        assert everyone, fail(f"sin resultados con todos respondidos: {wa.messages_to(GROUP_WA, mark)}")
        board = everyone[0]["message"]
        assert board.startswith("🧠 *Quiz: Sílabo de Cálculo* — resultados\n"
                                f"🥇 @{ANGEL_WA} · 2 de 2\n"), board
        assert f"🥈 @{STRANGER_WA} · 1 de 2" in board and f"🥈 @{CAPTAIN_WA} · 1 de 2" in board, board
        assert "→ «Unidad 4»" in board and "→ «4»" in board and "📄" in board, board
        assert sorted(everyone[0]["mentions"]) == sorted([angel_jid, stranger_jid, captain_jid]), everyone[0]
        weak = [e["texto"] for e in entries(data_dir, "MATG1049") if e["tipo"] == "tema_debil"]
        assert any(t.startswith("Quiz «Sílabo de Cálculo»: fallé «¿Qué unidad") for t in weak), \
            f"lo que falló el capitán queda como tema débil en su cuaderno: {weak}"
        time.sleep(3)
        assert len(results(mark)) == 1 and len(llm.requests) == calls, "un solo mensaje de resultados, sin el modelo"
        md.append(f"→ al grupo: [2 encuestas: {' / '.join(units['options'])}]\n"
                  "**Alguien** vota la 1 bien, cambia su voto y falla la 2; **Angel** vota las dos bien; **Capitán** "
                  f"falla la 1 y acierta la 2 → Vinci: {normalize(board)}\n")

        units, credits = group_quiz()
        mark = len(wa.sent)
        wa.vote(GROUP_WA, angel_jid, units["messageId"], option(units, "Unidad 4"))
        wa.vote(GROUP_WA, angel_jid, credits["messageId"], option(credits, "4"))
        closes = data_dir / "amigos" / "quiz-cierres.json"
        waiting = wa.wait_for(lambda b: (lambda c: c if c else None)(
            json.loads(closes.read_text())["quizzes"] if closes.exists() else {}), 30)
        assert waiting and [c["grupo"] for c in waiting.values()] == [GROUP_WA], waiting
        time.sleep(4)
        assert not results(mark), "con uno solo que respondió, el quiz espera sus 15 minutos"
        closes.write_text(json.dumps({"quizzes": {k: {**c, "a": "2026-09-30T13:00:00Z"} for k, c in waiting.items()}}))
        late = wa.wait_for(lambda b: results(mark), 30)
        assert late, fail(f"a los 15 minutos no llegaron los resultados: {wa.messages_to(GROUP_WA, mark)}")
        assert f"🥇 @{ANGEL_WA} · 2 de 2" in late[0]["message"] and late[0]["mentions"] == [angel_jid], late[0]
        assert json.loads(closes.read_text())["quizzes"] == {}, "el quiz cerrado sale de la lista"
        md.append(f"Otro quiz que solo Angel termina, pasados sus 15 minutos → Vinci: {normalize(late[0]['message'])}\n")
        report.append("Un quiz pedido en el grupo (aquí por un invitado) sale como encuestas en el grupo, con opciones "
                      "🇦 🇧 🇨: el patrón de mención de Hermes deja pasar esos votos sin mencionar a Vinci, y el "
                      "votante sale del recuento del puente, que da a Vinci como remitente. Cuenta el primer voto de "
                      "cada uno; cuando los tres del grupo responden todo, llega un solo mensaje con los resultados "
                      "de todos, medallas, menciones y las respuestas, sin el modelo, y lo que falló el capitán va a "
                      "su cuaderno. Un quiz que no todos terminan cierra a los 15 minutos con quien respondió")

        # 10f4. /entregas: a button to the dashboard on WhatsApp; a tick on it comes back through the relay, and
        # typed as /marca still works (what the page does when the relay fails)
        calls = len(llm.requests)
        [panel] = say(angel_jid, angel_jid, "/entregas", "Angel")
        assert panel["path"] == "send-url-button" and panel["buttonText"] == "📋 Ver mis entregas", panel
        link = re.search(r"#d=([\w-]+)", panel["url"])
        assert link and "#d=" not in panel["message"], panel
        from espol_bot import dashboard as dashboard_module
        snap = dashboard_module.decode(link[1])
        assert snap["wa"] == FakeWhatsApp.BOT.split("@")[0] and "bot" not in snap, snap
        assert snap["relay"] == relay.base and re.fullmatch(r"[\w-]{22,64}", snap["mailbox"]), snap
        taller = next(i for i in snap["items"] if i["title"].startswith("Taller 2"))
        mark = len(wa.sent)
        page_tick(snap, taller["id"])
        ticked = wa.wait_for(lambda b: b.messages_to(angel_jid, mark), 60)
        assert ticked and "cuenta como entregada" in text_of(ticked), fail(f"la marca no llegó: {wa.sent[mark:]}")
        md.append(f"**Angel** marca «{taller['title']}» en el panel (por el relé) → Vinci: "
                  f"{normalize(text_of(ticked))}\n")
        page_tick(snap, taller["id"], done=False)
        both = wa.wait_for(lambda b: (lambda m: m if len(m) >= 2 else None)(b.messages_to(angel_jid, mark)), 60)
        assert both, "desmarcar también llega por el relé"
        marked = text_of(say(angel_jid, angel_jid, f"/marca {taller['id']} ok · {taller['title']}", "Angel"))
        assert "cuenta como entregada" in marked, marked
        assert len(llm.requests) == calls, "/entregas y /marca no pasan por el modelo"
        private = text_of(say(GROUP_WA, angel_jid, "@vinci /entregas", "Angel", group=True))
        assert "por privado" in private, private
        report.append("/entregas le da a Angel un botón a su panel de entregas, que en el iPhone "
                      "abre dentro de WhatsApp: marcar una llega a Vinci por el relé y Vinci la cuenta como entregada "
                      "sin el modelo, igual que «/marca s… ok» escrito en el chat; en un grupo, /entregas pide ir "
                      "por privado")

        # 10g. Vinci's commands on WhatsApp, each over the sender's own aula; Hermes' own pass through
        calls = len(llm.requests)
        hello = text_of(say(angel_jid, angel_jid, "/start", "Angel"))
        assert "Hola, Angel" in hello and "/estado" in hello and "/amigo" not in hello, hello
        health = text_of(say(angel_jid, angel_jid, "/estado", "Angel"))
        assert "Estado de Vinci" in health and "<b>" not in health, health
        private = text_of(say(GROUP_WA, angel_jid, "@vinci /token", "Angel", group=True))
        assert "por privado" in private, private
        assert len(llm.requests) == calls, "/start, /estado y /token no pasan por el modelo"
        say(angel_jid, angel_jid, "/quiz integrales dobles", "Angel")
        assert "quiz corto de integrales dobles" in json.dumps(llm.requests[-1], ensure_ascii=False), \
            "«/quiz tema» le llega al modelo como pedido de un quiz"
        report.append("Los comandos de Vinci van sobre el aula de quien escribe y sin el modelo: /start (con los "
                      "comandos, sin los de /amigo), /estado y /token (en un grupo, piden ir por privado). «/quiz "
                      "integrales dobles» llega al modelo como pedido de un quiz, que Vinci manda como encuestas "
                      "(send_quiz)")

        # 10g2. Voice: Hermes' local Whisper (on in this test from the start) hears voice notes and audio files
        def skips(reason: str) -> int:  # the gateway logs each message under the profile it is routed to
            return sum(f.read_text(errors="replace").count(reason)
                       for f in (home / ".hermes").glob("**/logs/gateway.log"))

        def speak(chat: str, sender: str, fixture: str, name: str, *, group: bool = False,
                  skipped: str = "") -> str:
            """An audio from the fixtures, saved where the bridge saves it; with `skipped`, the plugin's reason
            for dropping it, and nothing reaches the chat or the model."""
            audio = home / ".hermes" / "cache" / "audio" / f"aud_{next(audio_ids)}{Path(fixture).suffix}"
            audio.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(FILES / fixture, audio)
            mark, calls, seen = len(wa.sent), len(llm.requests), skips(skipped) if skipped else 0
            wa.audio(chat, sender, audio, name=name, group=group)
            md.append(f"**{name}** ({'grupo' if group else 'privado'}): [{'nota de voz' if audio.suffix == '.ogg'
                                                                           else 'audio'} {fixture}]\n")
            if skipped:
                dropped = wa.wait_for(lambda _: skips(skipped) > seen, 120)
                assert dropped, fail(f"el plugin no descartó {fixture} ({skipped})")
                time.sleep(3)
                assert not wa.messages_to(chat, mark) and len(llm.requests) == calls, wa.messages_to(chat, mark)
                md.append("→ (sin respuesta)\n")
                return ""
            got = wa.wait_for(lambda b: (lambda m: m if any(not x.get("message", "").startswith("🎙️") for x in m)
                                         else None)(b.messages_to(chat, mark)), 180)
            assert got, fail(f"nadie contestó a {fixture}")
            for m in got:
                md.append(f"→ Vinci: {normalize(m.get('message', ''))}\n")
            return text_of(got)

        audio_ids = itertools.count(1)
        calls = len(llm.requests)
        heard = speak(captain_jid, captain_jid, "whatsapp-voz-vinci.ogg", "Capitán")
        assert "Esta semana:" in heard and "qué tengo esta semana" in heard, \
            f"Hermes muestra lo que entendió y Vinci contesta: {heard}"
        assert "nota de voz que transcribió Whisper" in turn_context(llm.requests[calls:]), \
            "una nota de voz llega con su aviso: un nombre o un término pudo salir mal escrito"
        his = speak(GROUP_WA, angel_jid, "whatsapp-voz-vinci.ogg", "Angel", group=True)
        assert "EDO de primer orden" in his, his  # his week; /marca above closed the Taller 2
        speak(GROUP_WA, captain_jid, "whatsapp-voz-charla.ogg", "Capitán", group=True,
              skipped="audio que no llama a Vinci")
        speak(GROUP_WA, stranger_jid, "whatsapp-voz-vinci.ogg", "Alguien", group=True,
              skipped="audio de alguien sin Vinci")
        calls = len(llm.requests)
        file_week = speak(angel_jid, angel_jid, "whatsapp-audio-semana.m4a", "Angel")
        assert "EDO de primer orden" in file_week, file_week
        assert '"Oye, ¿qué tengo esta semana?' in json.dumps(llm.requests[calls:], ensure_ascii=False), \
            "un archivo de audio le llega al modelo transcrito, como una nota de voz"
        calls = len(llm.requests)
        speak(angel_jid, angel_jid, "whatsapp-voz-silencio.ogg", "Angel")
        assert "Su nota de voz no se pudo oír: es un problema del audio" in turn_context(llm.requests[calls:]), \
            "una nota de voz en silencio no se contesta como si dijera algo"
        report.append("Voz en WhatsApp, con el Whisper local de Hermes: una nota de voz por privado («Vinci, ¿qué "
                      "tengo esta semana?») recibe la semana del capitán. En un grupo encendido, la nota de voz de "
                      "Angel que dice «Vinci» recibe su semana; una charla del capitán sin «Vinci» y la nota de "
                      "alguien sin su Vinci no llegan al modelo (la de ese alguien ni se transcribe). Un archivo de "
                      "audio (.m4a), que Hermes no transcribe, lo transcribe el plugin. Cada nota de voz llega con "
                      "un aviso en el contexto (un término pudo salir mal escrito); una en silencio, con que no se "
                      "oyó y no hay que adivinar")

        # 10i. Angel's alerts reach his own chat, never the captain's
        angel_env = {"AULA_SECRETS": str(angel_dir / "secrets.env"), "AULA_DATA_DIR": str(angel_dir),
                     "ESPOL_AMIGO": "angel"}
        trust = say(GROUP_WA, captain_jid, "@vinci este grupo es de confianza", "Capitán", group=True)
        assert "es de confianza" in text_of(trust), text_of(trust)
        assert json.loads((data_dir / "amigos" / "whatsapp.json").read_text())["confianza"] == [GROUP_WA]
        run([bot, "sondeo"], "2026-09-30T08:50:00-05:00")  # the captain's poll starts reading Angel's news from here
        canvas.set_account_state("canvas-amigo", "state2")
        mark = len(wa.sent)
        run([bot, "sondeo"], "2026-09-30T09:00:00-05:00", env_extra=angel_env)
        alert = wa.wait_for(lambda b: [m for m in b.messages_to(angel_jid, mark) if "Coordenadas polares" in
                                       m.get("message", "")], 30)
        assert alert and "<b>" not in alert[0]["message"], alert
        md.append(f"→ a Angel (sondeo de su Vinci): {normalize(alert[0]['message'])}\n")
        # 10i'. In a trusted group the captain's poll passes on Angel's news too, tagging him, in one message, once
        run([bot, "sondeo"], "2026-09-30T09:05:00-05:00")
        news = [m for m in wa.messages_to(GROUP_WA, mark) if "Novedades del aula" in m.get("message", "")]
        assert len(news) == 1 and "Coordenadas polares" in news[0]["message"], news
        assert f"@{ANGEL_WA}" in news[0]["message"] and news[0].get("mentions") == [angel_jid], news[0]
        run([bot, "sondeo"], "2026-09-30T09:15:00-05:00")
        assert len([m for m in wa.messages_to(GROUP_WA, mark) if "Novedades del aula" in m.get("message", "")]) == 1
        md.append(f"→ al grupo de confianza (sondeo del capitán): {normalize(news[0]['message'])}\n")
        report.append("En un grupo de confianza («@vinci este grupo es de confianza»), el sondeo del capitán pasa al "
                      "grupo lo nuevo del aula de Angel, en un solo mensaje que lo menciona, y no lo repite")
        before = set(parse_env_file(angel_dir / "secrets.env").values())
        canvas.expire(ANGEL_TOKEN)  # ESPOL's hour: the seed, kept as the chain's probe, is dead by 09:45
        run([bot, "mantenimiento"], "2026-09-30T09:45:00-05:00", env_extra=angel_env)
        assert parse_env_file(angel_dir / "secrets.env")["CANVAS_TOKEN"] not in before, \
            "la cadena del token de Angel se renueva sola"
        report.append("El sondeo del Vinci de Angel le avisa por su chat de WhatsApp (formato de WhatsApp, sin "
                      "HTML) y nunca por el del capitán; su mantenimiento renueva su propia cadena de token")

        # 10h. Should someone reach a Vinci that is not theirs, its owner's data stays shut
        gateway.stop()
        plugin = angel_profile / "plugins" / "vinci-botones" / "__init__.py"
        plugin.write_text(plugin.read_text().replace(f'WHATSAPP_OWNER = "{ANGEL_WA}"', f'WHATSAPP_OWNER = "{STRANGER_WA}"'))
        start()
        blocked = text_of(say(angel_jid, angel_jid, "qué tengo esta semana", "Angel"))
        assert "Eso es del dueño" in blocked and "Integrales dobles" not in blocked, blocked
        report.append("Si alguien llegara al Vinci de otro (aquí, Angel con su perfil marcado como de otra persona), "
                      "el gancho pre_tool_call del plugin le niega las herramientas con datos del dueño")

        # 10j. The captain lists and removes Angel; then turns the group off
        listed = say(captain_jid, captain_jid, "/amigos", "Capitán")
        assert "Angel: tiene su Vinci" in text_of(listed)
        gone = say(captain_jid, captain_jid, "/amigo quitar Angel", "Capitán", timeout=180)
        assert "quité a Angel" in text_of(gone) and "token" in text_of(gone), gone
        assert not angel_profile.exists() and not angel_dir.exists()
        assert not [t for t in canvas.valid_tokens if t in canvas.accounts and t != ANGEL_TOKEN], \
            "no queda ningún token que Vinci creó en el aula de Angel (el suyo vence con su hora)"
        assert parse_env_file(home / ".hermes" / ".env")["WHATSAPP_ALLOWED_USERS"] == CAPTAIN_WA
        off = say(GROUP_WA, captain_jid, "@vinci desactiva este grupo", "Capitán", group=True)
        assert "ya no contesto" in text_of(off)
        say(GROUP_WA, captain_jid, "@vinci hola", "Capitán", group=True, expect=0)
        report.append("«/amigo quitar Angel» borra del aula todos los tokens que creó su cadena, su perfil y su carpeta; "
                      "«@vinci desactiva este grupo» lo apaga")

        (ARTIFACT / "whatsapp-amigo.md").write_text("\n".join(md), encoding="utf-8")
        assert_no_secrets(w, "amigo")
    write_part("test_whatsapp_friend", "WhatsApp: un grupo y el Vinci de un amigo", w.report, started)


class PortalPage:
    """The page behind «🎓 Conectar Académico» (docs/academico/), as the student uses it: in a real headless Chromium
    when there is one (served as GitHub Pages would, by FakePages), else its own module's `answer` on Node. Either
    way it reads what to ask from the relay and posts each answer sealed."""

    def __init__(self, url: str, relay: FakeRelay, pages: FakePages | None, browser):
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.key, self.relay_url, self.mailbox = query["k"][0], query["r"][0], parts.fragment.removeprefix("m=")
        self.relay, self.browser, self.sent = relay, browser, 0
        self.page = browser.open(f"{pages.base}/academico/?{parts.query}#{parts.fragment}") if browser else None

    def status(self, state: str, timeout: float = 60, error: str = "") -> dict:
        end = time.time() + timeout
        while time.time() < end:
            found = self.relay.statuses.get(self.mailbox) or {}
            if found.get("state") == state and error in (found.get("error") or "") and found.get("handled", 0) >= self.sent:
                return found
            time.sleep(0.3)
        raise AssertionError(f"la página nunca llegó a «{state}»: {self.relay.statuses.get(self.mailbox)}")

    def _until(self, expr: str, timeout: float = 30):
        end = time.time() + timeout
        while time.time() < end:
            value = self.browser.eval(self.page, expr)
            if value:
                return value
            time.sleep(0.2)
        raise AssertionError(f"la página nunca cumplió {expr}: {self.browser.eval(self.page, 'document.body.innerText')}")

    def _answer(self, step: str, data: dict) -> None:
        self.sent += 1
        if self.browser is None:
            _node_module(REPO / "docs" / "academico" / "portal.js",
                         "await page.answer(process.argv[1], process.argv[2], process.argv[3], process.argv[4], "
                         "Number(process.argv[5]), JSON.parse(process.argv[6]));",
                         self.key, self.relay_url, self.mailbox, step, str(self.sent), json.dumps(data))
            return
        if step == "user":
            self._until("!document.getElementById('user-form').hidden && !document.getElementById('user').disabled")
            self.browser.eval(self.page, f"document.getElementById('user').value = {json.dumps(data['user'])};"
                                         "document.getElementById('user-form').requestSubmit(); true")
        else:
            self._until("!document.getElementById('login-form').hidden && !document.getElementById('code').disabled"
                        " && document.getElementById('captcha').src.startsWith('data:image/jpeg')")
            self.browser.eval(self.page, f"document.getElementById('password').value = {json.dumps(data['password'])};"
                                         f"document.getElementById('code').value = {json.dumps(data['captcha'])};"
                                         "document.getElementById('login-form').requestSubmit(); true")

    def sign_in(self, user: str) -> None:
        self.status("user")
        self._answer("user", {"user": user})
        self.status("login")

    def log_in(self, password: str, code: str) -> None:
        self._answer("login", {"password": password, "captcha": code})

    def shown(self) -> str:
        return self.browser.eval(self.page, "document.body.innerText") if self.browser else ""

    def done(self, timeout: float = 120) -> str:
        message = self.status("done", timeout)["message"]
        if self.browser:
            self._until("document.body.dataset.done === '1'")
            self.browser.close(self.page)
        return message


def academico_flow(w) -> None:
    """Section 10k: ESPOL's Académico. The captain asks for his GPA; with no copy, Vinci's tool asks for the sign-in
    and a «🎓 Conectar Académico» button reaches his chat. On its page he gives his user, then his password with a
    wrong CAPTCHA (the portal's words and a new one come back), then the right one: the worker signs in with one
    session, reads every section, saves the copy and tells the chat, and his question comes back to Vinci by itself
    in the same session, answered from the copy. Later questions use the copy without the portal; asked to update it,
    a new sign-in brings the portal's new figures. No credential reaches the model, the chat, the relay in clear, a log
    or the copy."""
    wa, relay, portal, llm, data_dir, say, fail = w.wa, w.relay, w.portal, w.llm, w.data_dir, w.say, w.fail
    report, normalize, gateway, captain_jid = w.report, w.normalize, w.gateway, CAPTAIN_JID
    from test_webview_experiment import CHROMIUM, Browser
    browser = Browser() if NODE and CHROMIUM else None
    pages_ctx = FakePages(REPO / "docs", relay.base) if browser else None
    pages = pages_ctx.__enter__() if pages_ctx else None
    md = ["# El Académico de ESPOL\n",
          "Lo que pregunta el capitán, el botón que le llega, lo que hace en la página (" +
          ("un Chromium real" if browser else "el módulo de la página en Node") + ") y lo que contesta Vinci. El "
          "Académico es FakePortal: ASP.NET con VIEWSTATE, EVENTVALIDATION, ingreso en dos pasos y CAPTCHA.\n"]
    copy_file = data_dir / "academico.json"
    try:
        # 1. No copy yet: the tool asks for the sign-in, the button arrives, nothing secret is asked in the chat. His
        # chat arrives as WhatsApp often names it, by his LID (bridge.js still gives his number as the sender): the
        # question must still come back to this session.
        mark, calls = len(wa.sent), len(llm.requests)
        lid_jid = f"{CAPTAIN_LID}@lid"
        asked = say(lid_jid, captain_jid, "cuál es mi promedio y cuántas materias aprobé", "Capitán")
        assert "Conectar Académico" in text_of(asked), text_of(asked)
        button = wa.wait_for(lambda b: [m for m in b.sent[mark:] if m["path"] == "send-url-button"
                                        and m["buttonText"] == "🎓 Conectar Académico"], 60)
        assert button, fail(f"no llegó el botón del Académico: {wa.sent[mark:]}")
        url = button[0]["url"]
        assert url.startswith("https://sebasb76.github.io/vinci/academico/?k=") and "#m=" in url, url
        assert "contraseña" in button[0]["message"] and "vence en 15 min" in button[0]["message"], button[0]
        assert not copy_file.exists() and not portal.logins, "nada se guardó ni se intentó todavía"
        md.append(f"**Capitán**: cuál es mi promedio y cuántas materias aprobé\n→ Vinci: {normalize(text_of(asked))}\n"
                  f"→ Vinci: {normalize(button[0]['message'])} [botón «{button[0]['buttonText']}»]\n")

        # 2. The page: user, a wrong CAPTCHA, the right one
        page = PortalPage(url, relay, pages, browser)
        page.sign_in(PORTAL_USER)
        page.log_in(PORTAL_PASSWORD, "AAAAA")
        refused = page.status("login", error="no es correcto")
        assert refused["captcha"].startswith("data:image/jpeg;base64,"), refused
        if browser:
            page._until("document.getElementById('status').textContent.includes('no es correcto')")
        md.append("**Capitán**, en la página: escribe su usuario → la PC entra al primer paso y le muestra el CAPTCHA; "
                  f"pone su contraseña y un código equivocado → la página dice «{refused['error']}» con un CAPTCHA "
                  "nuevo; pone el código correcto.\n")
        mark = len(wa.sent)
        page.log_in(PORTAL_PASSWORD, portal.last_code())
        finished = page.done()
        assert "Vinci te responde en el chat" in finished, finished

        # 3. The chat: the copy saved, then the question answered by itself in the same session
        # one chat on his phone: the worker writes to his number, Vinci answers where the question came from
        def to_him(b):
            return [m for m in b.sent[mark:] if m.get("chatId") in (captain_jid, lid_jid)
                    and m["path"] in ("send", "send-media", "send-url-button")]
        answer = wa.wait_for(lambda b: [m for m in to_him(b) if "8,15" in m.get("message", "")], 120)
        assert answer, fail(f"la pregunta no volvió a su chat: {to_him(wa)}")
        told = text_of(to_him(wa))
        assert "✅ Listo: guardé tu Académico del 2026 · 2S" in told, told
        assert "Aprobaste 5 materias" in told and "Convalidada: Inglés I" in told and "promedio general es 8,15" in told, told
        returned = next(r for r in reversed(llm.requests) if PORTAL_BACK in json.dumps(r, ensure_ascii=False))
        assert "never one you work out from the grades" in json.dumps(returned, ensure_ascii=False), \
            "el promedio es el de Información General, nunca uno calculado por el modelo"
        back = [r for r in llm.requests[calls:] if PORTAL_BACK in json.dumps(r, ensure_ascii=False)]
        assert back and "cuál es mi promedio y cuántas materias aprobé" in json.dumps(back[0], ensure_ascii=False), \
            "la pregunta vuelve a la misma conversación de Hermes, sin que el capitán la repita"
        md.append(f"→ Vinci: {normalize(told)}\n")
        sessions = {r["session"] for r in portal.requests}
        assert len(sessions) == 1 and None not in sessions, f"un solo ingreso, una sola sesión: {sessions}"
        assert [outcome for _, outcome in portal.logins] == ["captcha", "ok"], portal.logins
        copy = json.loads(copy_file.read_text())
        assert stat.S_IMODE(copy_file.stat().st_mode) == 0o600
        assert copy["period"] == "2026 · 2S" and copy["saved_at"] and not copy["errors"], copy["errors"]
        sections = copy["sections"]
        assert set(sections) == {"general", "historial", "calificaciones", "creditos", "horario", "examenes"}
        general = sections["general"]["datos"]
        assert general.get("Promedio General en las materias aprobadas") == "8,15" and \
            general.get("Carrera") == "Computación Activo" and general.get("Avance de la carrera") == "40,00% *", general
        assert not {"Matrícula", "Identificación", "Nombre", "Grupo étnico", "Año-Término"} & set(general), general
        assert "Matrícula" not in sections["creditos"]["datos"] and \
            not [t for t in sections["creditos"]["tablas"] if t["columnas"][0].endswith(":")], "sin la tarjeta del estudiante"
        grades = sections["calificaciones"]["tablas"][0]
        assert grades["columnas"][3:9] == ["Paralelo Teórico", "Paralelo Práctico", "Exámenes 1", "Exámenes 2",
                                           "Exámenes Práct.", "Exámenes Mej."], grades["columnas"]
        assert grades["filas"][0]["Exámenes 1"] == "7,50" and grades["filas"][0]["Año Término"] == "2026 - 2", grades
        assert {(s["code"], s.get("term"), s.get("grade")) for s in sections["historial"]["materias"]} >= \
            {("MATG1045", "2024-1", "8,20"), ("ADM001099", "2024-1", "0,00")}, "cada materia con su período y su nota"
        assert [(c["day"], c["start"], c["end"]) for c in sections["horario"]["classes"]] == \
            [("Lunes", "09:30", "11:30"), ("Martes", "14:30", "16:30")], sections["horario"]
        assert [(g["subject"], g["theory_weight"]) for g in sections["calificaciones"]["breakdowns"]] == \
            [("SISTEMAS DISTRIBUIDOS Y COMPUTACIÓN EN LA NUBE", "70")], "solo la materia con práctico tiene ponderación"
        exams = sections["examenes"]["exams"]
        assert set(exams) == {"PARCIAL", "FINAL", "MEJORAMIENTO"} and "Fecha:24/11/2026" in exams["PARCIAL"][0]["text"], \
            "el primer tipo de examen también se consulta"
        mailboxes = json.loads((data_dir / "amigos" / "rele.json").read_text()).get("mailboxes", {})
        assert not [b for b in mailboxes.values() if b["kind"] == "academico"], "el buzón del ingreso se cerró"
        time.sleep(2)
        alive = subprocess.run(["pgrep", "-f", "espol_bot portal-worker"], capture_output=True, text=True)
        assert alive.returncode == 1, f"el proceso del ingreso terminó y soltó la sesión: {alive.stdout}"
        report.append("El Académico: «¿cuál es mi promedio y cuántas materias aprobé?» sin copia → academic_record pide "
                      "el ingreso y al chat le llega el botón «🎓 Conectar Académico». En su página (" +
                      ("Chromium" if browser else "Node") + ") el capitán pone su usuario, después su contraseña y un "
                      "CAPTCHA equivocado (vuelve la frase del portal con otro CAPTCHA) y luego el correcto. La PC entra "
                      "con una sola sesión de ASP.NET (VIEWSTATE, EVENTVALIDATION, cookies), lee historial, "
                      "créditos, exámenes (parcial, final y mejoramiento), calificaciones y horario con el año y el "
                      "término que trae la página de exámenes, guarda la copia con su fecha y su período (2026 · 2S) y "
                      "avisa en el chat; la pregunta vuelve sola a la misma conversación y Vinci contesta el promedio "
                      "de Información General (8,15) y las 5 aprobadas, con Inglés I aparte como convalidada. De esa "
                      "página la copia guarda el promedio y el avance, no la identificación, el nombre ni la foto")

        # 4. From the copy, without the portal
        seen = len(portal.requests)
        approved = text_of(say(captain_jid, captain_jid, "qué materias aprobé", "Capitán"))
        assert "Aprobaste 5 materias" in approved and "Física: Mecánica" in approved, approved
        finals = text_of(say(captain_jid, captain_jid, "cuándo son mis exámenes finales", "Capitán"))
        assert "Fecha:2/2/2027 (Martes 10:00-12:00)" in finals and "Fecha:4/2/2027" in finals, finals
        progress = text_of(say(captain_jid, captain_jid, "cuánto me falta para graduarme", "Capitán"))
        assert "40,00% * de avance" in progress and "60 créditos por tomar" in progress and "malla" in progress, progress
        avance = next(r for r in reversed(llm.requests) if "cuánto me falta para graduarme" in json.dumps(r, ensure_ascii=False))
        assert "Never work out the remaining subjects" in json.dumps(avance, ensure_ascii=False), \
            "la herramienta le prohíbe al modelo restar las aprobadas de un total"
        assert len(portal.requests) == seen, "con copia, Vinci no vuelve a entrar al Académico"
        for asked_, said in (("qué materias aprobé", approved), ("cuándo son mis exámenes finales", finals),
                             ("cuánto me falta para graduarme", progress)):
            md.append(f"**Capitán**: {asked_}\n→ Vinci: {normalize(said)}\n")
        report.append("Con la copia, «¿qué materias aprobé?», «¿cuándo son mis exámenes finales?» y «¿cuánto me falta "
                      "para graduarme?» se contestan sin volver al Académico; para el avance la herramienta da los "
                      "créditos que dice el portal y le prohíbe al modelo calcular lo que falta restando de un total, "
                      "porque la malla todavía no se lee")

        # 5. Updating it: a new sign-in, the portal's new figures
        portal.version = 2
        mark = len(wa.sent)
        say(captain_jid, captain_jid, "actualiza mi Académico y dime mi promedio", "Capitán")
        again = wa.wait_for(lambda b: [m for m in b.sent[mark:] if m["path"] == "send-url-button"
                                       and m["buttonText"] == "🎓 Conectar Académico"], 120)
        assert again, fail(f"no llegó el botón para actualizar: {wa.sent[mark:]}")
        page = PortalPage(again[0]["url"], relay, pages, browser)
        page.sign_in(PORTAL_USER)
        page.log_in(PORTAL_PASSWORD, portal.last_code())
        page.done()
        updated = wa.wait_for(lambda b: [m for m in to_him(b) if "8,22" in m.get("message", "")], 120)
        assert updated, fail(f"la pregunta no volvió a su chat: {to_him(wa)}")
        copy = json.loads(copy_file.read_text())
        assert next(s for s in copy["sections"]["historial"]["materias"] if s["code"] == "ADSG1026")["status_kind"] == \
            "approved", "la copia nueva trae la nota que el portal publicó después"
        md.append("**Capitán**: actualiza mi Académico y dime mi promedio\n→ Vinci: otro botón «🎓 Conectar "
                  f"Académico»; entra otra vez\n→ Vinci: {normalize(text_of(updated))}\n")
        report.append("«Actualiza mi Académico»: otro botón, otro ingreso, y la respuesta vuelve sola a su chat con el "
                      "promedio nuevo (8,22) y Sostenibilidad aprobada")

        # 6. Nothing secret anywhere
        files = b"".join(read_if_there(f) for f in data_dir.rglob("*") if f.is_file())
        dumps = (json.dumps(llm.requests, ensure_ascii=False) + json.dumps(wa.sent, ensure_ascii=False)
                 + json.dumps(relay.posted)
                 + json.dumps(relay.status_log, ensure_ascii=False) + gateway.tail(100000))
        for secret in (PORTAL_PASSWORD, f'"user": "{PORTAL_USER}"'):
            assert secret not in dumps, f"«{secret}» llegó al modelo, al chat, al relé o al registro del gateway"
        assert PORTAL_PASSWORD.encode() not in files and PORTAL_USER.encode() not in files, \
            "ni la contraseña ni el usuario quedan en la carpeta de datos (copia, bot.log, registro del relé)"
        assert all(re.fullmatch(r"v2\.[\w-]+\.[\w-]{16}\.[\w-]+", m["data"]["sealed"]) for m in relay.posted
                   if m["data"].get("kind") == "academico"), "el relé solo ve texto cifrado"
        assert not any(c in copy_file.read_text() for c in ("ASP.NET_SessionId", ".ASPXAUTH", "__VIEWSTATE",
                                                            *{r["session"] for r in portal.requests})), \
            "la copia no guarda la sesión"
        for value in (v for k, v in PORTAL_CARD if k != "Grupo étnico"):
            assert value not in copy_file.read_text() and value not in json.dumps(llm.requests, ensure_ascii=False), \
                f"la matrícula, la identificación y el nombre del estudiante ({value}) no quedan en la copia ni van al modelo"
        report.append("Ni la contraseña ni el usuario aparecen en lo que vio el modelo, en los chats, en el relé (solo "
                      "texto cifrado v2), en el registro del gateway ni en la carpeta de datos; la copia no guarda "
                      "cookies ni campos de sesión, y el proceso del ingreso termina al acabar")
    finally:
        if browser:
            browser.quit()
        if pages_ctx:
            pages_ctx.__exit__(None, None, None)
        (ARTIFACT / "academico.md").write_text("\n".join(md), encoding="utf-8")
