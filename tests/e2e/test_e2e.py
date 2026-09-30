"""End-to-end run of Vinci and its subject bots against a fake Canvas, a fake Telegram and
a scripted LLM, with the real Hermes Agent when it is installed.

Everything runs as real processes (the same commands Hermes cron, the gateway and the
captain run) in a throwaway HOME with its own XDG folders and no D-Bus session: the real
~/.hermes, ~/.claude, ~/.local and user services are never touched.

  1. setup.sh twice: a legacy «espol» profile becomes Vinci with its memory; the second
     run changes nothing. Then, with IPv6 to Telegram broken and IPv4 working (the captain's
     network), Vinci's own Bot API calls must not stall.
  2. `aula` CLI commands against the first fixture state: the material catalog (a module's
     subheader, folders, a copy from 2025, a big book, a guide only an assignment links to, an
     announcement's attachment) and its outside links; a file and its copy downloaded on demand.
  3. Vinci's polls, then the fixtures change (new assignment, due-date change, new
     announcement, posted grade, new material, the syllabus, a new module link, a submission),
     then polls 2-4 and the 07:00 summary (twice: the second must not resend). Only syllabi
     download on their own; while poll 2 slowly downloads the new one, `aula cursos --actualizar`
     (what setup.sh runs) must not wait for it.
  4. retrieval: sample questions must hit the right file and page, never two copies of one page.
  5. a fresh install where two resources fail at different polls: the rest keeps working,
     one alert per failure episode and resource.
  6-7. the real Hermes gateway serving Vinci over the fake Telegram. The aula uses ESPOL's
     real course codes and names, and Cálculo has a theory and a práctico course
     (`Paralelo5_MATG1049`, `Paralelo105_MATG1049`): one subject, one bot. Vinci builds the team
     from chat: its card's «Crear» buttons; Cálculo created as a Telegram managed bot (its
     token fetched with getManagedBotToken), Física from BotFather's forwarded reply (caught,
     deleted, never seen by the model; a repeated, an unknown and a stranger's token handled).
     Every press is answered at once, even one whose work is slow; a second «Crear» does not
     resend; the /start the captain sends Cálculo before the gateway serves it gets a greeting.
     Then, with both subject bots served by the same gateway: strangers get silence; the
     schedule read from a screenshot is saved only by the
     captain's «Guardar» (a stranger's press and a stale proposal are refused); a photo
     routed to Cálculo, an unknown subject refused; an alert's button and a reply to an
     alert handed to the subject bots (alerts of both Cálculo courses go to its one bot);
     the brief 30 minutes before Wednesday's class, with what is due in both courses (and on
     Monday, theory then práctico back to back, one brief before the first block, none mid-class);
     notebook capture of a photo, a voice note and a doubt (and no arbitrary files); the course
     material, without the aula's template images. The material of each subject: the catalog as
     the bot sees it; the main book read from the syllabus, asked for once from the subject bot's
     chat (it is only a SharePoint link) and then sent as a PDF; the one Física's captain names
     in Vinci's chat, asked for once, never again, and picked up from the libros/ folder; search
     with the main book first and in two languages; a scanned reading seen as an image (the image
     reaches the model) while tesseract looks missing, as before; then OCR at indexing: the next poll
     reads its waiting pages once, search finds it, the same PDF sent again calls no OCR, and a new
     scanned sheet is read as it is added (when tesseract is installed); outside links opened without a login and without any credential: a
     professor's page, the Google Doc that is all an announcement of Física says (the captain's
     case), a Drive guide Vinci reads; a private Google Doc and an ESPOL-only SharePoint refused with
     the reason, the private one not asked for again on every question (unless the captain says it is
     shared now);
     «✅ Ya lo entregué» under a reminder (the assignment stops being pending everywhere and gets no more
     reminders; its undo brings it back); the captain's own to-do list from «anota: …» (its card, «¿qué tengo
     esta semana?», the model-free reminder and 7:00 summary, closed with «✅ Hecho»); the grade calculator
     (Cálculo's bot reads its syllabus and shows the scheme, asking how the first partial goes without its exam;
     the captain's answer and «✅ Guardar esquema» save it; the figures, a what-if and a grade given in chat are
     the tool's; Vinci says it does not know Física's scheme until the captain tells it); the deliverables'
     priority (with both schemes saved and a new Física homework, the model-free 7:00 summary and «¿qué tengo
     esta semana?» put what is due within 24 h first, then the heaviest toward the grade, then, by date, what has
     no known weight);
     Vinci reading notebooks but unable to write them or reach a terminal; /quiz: Cálculo sends a short quiz
     as Telegram quiz polls citing its material (a citation of a page it never read refused first), the
     captain's votes scored with no model (a stranger's and a repeated one ignored) and what was missed noted
     as a weak topic; Física quizzes from the PDF sent after a bare /quiz; Vinci hands /quiz to Cálculo,
     which also cites its notebook's board photo; Física
     archived from Vinci's card and the gateway restarted: no repeated brief, Física
     offline, and what the captain sent Vinci meanwhile gets its answer; reactivated from
     Vinci's card, the same gateway serves it again. Each agenda really runs every minute.
  8. Canvas tokens rotate through three generations without interrupting polls. When every
     token dies, maintenance says the chain is cut (never that a replacement works) and stops
     calling Canvas with the dead tokens; the token-free calendar and announcement feeds still
     deliver useful alerts; a hidden CLI reseed restores the renewal chain. `espol-bot doctor` reads
     each of those moments (all healthy, three hours with nothing running, the chain cut, reseeded)
     without calling Canvas or the chat, and the captain's /estado in Vinci's chat, served by the
     plugin and never by the model, shows a night without poll or maintenance. setup.sh then runs
     a third time with the team in place and reports the refused token instead of «✓ Canvas
     responde».
  9. the party: Vinci got its wizard as its Telegram photo at setup (once), and no bot plays a
     character. Cálculo and Física, with no photo in the party, keep theirs. Four of the
     captain's real subjects already have bots: two still named «Vinci · <materia>», two with
     the character name, photo and stamp PR #4 gave them («El Analítico · Estadística»). The
     update (setup.sh) renames all four in place to just their subject (setMyName), with no new
     or duplicate bot and the same usernames; the photos already set are not uploaded again.
     Every bot summarizes its chat at 80K tokens, set in existing profiles without touching the rest.
     The update also moves the old `every 30m` poll and `every 1m` agendas to cron expressions in
     place, and has Vinci keep what it gets while the gateway is down.
     The fifth, Sistemas Distribuidos, is created from Vinci's «Crear» button: Telegram's
     creation screen takes its suggested name and username (the one Telegram Web once refused
     as too long). Every suggested username fits Telegram's rules. setup.sh once more asks
     Telegram for nothing.

The artifact goes to artifacts/e2e/ (override with E2E_ARTIFACT_DIR). Ports and
temporary paths are normalized, so reruns produce comparable files.
"""

from __future__ import annotations

import base64
import hashlib
import html
import itertools
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
from urllib.parse import urlsplit

import yaml

from aula_core.config import parse_env_file
from espol_bot import skill_check

HERE = Path(__file__).parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

from fake_servers import (  # noqa: E402
    DRIVE_FILE, ESPOL_ONLY_SHARE, PRIVATE_DOC, PUBLIC_DOC, BrokenIPv6, FakeCanvas, FakeTelegram, FakeWeb, ScriptedLLM)
from hermes_harness import find_hermes, telegram_support  # noqa: E402

CANVAS_TOKEN = "7~prueba-token-de-canvas"
NEW_CANVAS_TOKEN = "7~nuevo-token-de-canvas"  # after the aula virtual refused the first one
BOT_TOKEN = "123456:PRUEBA-bot-token"
SUBJECT_TOKENS = {"MATG1049": "700001:PRUEBA-token-de-calculo-xxxxxxxxxxxxxxxx",
                  "FISG1002": "700002:PRUEBA-token-de-fisica-xxxxxxxxxxxxxxxxx"}
UNKNOWN_TOKEN = "700009:PRUEBA-token-que-no-existe-xxxxxxxxxxxx"
STRANGER_TOKEN = "700008:PRUEBA-token-de-un-extrano-xxxxxxxxxxxx"
BOTFATHER_REPLY = ("Done! Congratulations on your new bot. You will find it at t.me/vinci_fisica_bot. You can now "
                   "add a description.\n\nUse this token to access the HTTP API:\n{token}\nKeep your token secure "
                   "and store it safely, it can be used by anyone to control your bot.")
MATG, FIS = SUBJECT_TOKENS["MATG1049"], SUBJECT_TOKENS["FISG1002"]
AVATARS = REPO / "hermes" / "avatars"
PARTY = {  # the captain's subjects this semester: (name in the aula, its bot's Telegram name, its photo)
    "SOFG1007": ("Ingeniería de Software I", "Ingeniería de Software I", "robot.jpg"),
    "CCPG1041": ("Dirección de Proyectos Informáticos", "Dirección de Proyectos Informáticos", "builder.jpg"),
    "CCPG1055": ("Sistemas Distribuidos y Computación en la Nube", "Sistemas Distribuidos", "server.jpg"),
    "ESTG1034": ("Estadística", "Estadística", "book.jpg"),
    "ADSG1026": ("Ciencias de la Sostenibilidad", "Ciencias de la Sostenibilidad", "sprout.jpg"),
}
# The bots the captain already has, as the two earlier versions left them: (username, name in Telegram).
EXISTING = {
    "SOFG1007": ("vinci_ingenieria_software_i_bot", "Vinci · Ingeniería de Software I"),
    "CCPG1041": ("vinci_direccion_proyectos_bot", "Vinci · Dirección de Proyectos Informáticos"),
    "ESTG1034": ("vinci_estadistica_bot", "El Analítico · Estadística"),
    "ADSG1026": ("vinci_ciencias_bot", "El Equilibrio · Sostenibilidad"),
}
ROLEPLAY = ("personaje", "personalidad", "Guía Académico", "aventurero", "El Analítico", "El Conector")
PARTY_TOKENS = {code: f"70010{i}:PRUEBA-token-de-{code.lower()}-xxxxxxxxxxxxxxxx" for i, code in enumerate(PARTY, 1)}
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
T_MONDAY = "2026-10-05T08:30:00-05:00"  # lunes: teórico 09:00–11:00 y práctico 11:00–12:00 seguidos
T_MIDCLASS = "2026-10-05T10:30:00-05:00"  # en pleno teórico, 30 min antes del práctico
T_EXAM = "2026-10-01T06:00:00-05:00"    # 2 h antes del examen parcial de Física (08:00)
T_RENEW_0 = "2026-09-29T21:00:00-05:00"
T_RENEW_1 = "2026-09-29T21:41:00-05:00"
T_RENEW_2 = "2026-09-29T22:22:00-05:00"
T_RENEW_3 = "2026-09-29T23:03:00-05:00"
T_RENEW_4 = "2026-09-29T23:33:00-05:00"  # the probe (born 22:22) turns 70 minutes old
T_RENEW_5 = "2026-09-29T23:43:00-05:00"

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
# A model citing from memory, with no tool in its turn: a page the file does not have, a book that is not in
# the material, and a real page it read before with an invented link.
FROM_MEMORY = ("La regla de L'Hôpital sale en 📄 [Capítulo 3 - Derivadas.pdf, página 9]"
               "(https://aulavirtual.espol.edu.ec/courses/101/files/5001), con más ejemplos en 📄 Stewart - Cálculo de "
               "una variable.pdf, página 120. Se apoya en la derivada de una composición: 📄 [Capítulo 3 - "
               "Derivadas.pdf, página 2](https://aulavirtual.espol.edu.ec/files/5001).")

# How each subject is graded, as the model reads it: Cálculo's syllabus weighs two partial exams and the class
# work, and says nothing of El Niño (the first partial has no exam this semester); the captain then says a
# lesson worth the same replaces it. Física's syllabus is not in the aula: the captain tells Vinci how it goes.
CALC_ACTIVITIES = {"name": "Deberes y lecciones", "weight": 30, "match": ["deber", "lección", "taller", "práctica"]}
CALC_SYLLABUS_SCHEME = {
    "periods": [{"name": "Curso", "weight": 100, "components": [
        {"name": "Examen del primer parcial", "weight": 35, "match": ["primer parcial"]},
        {"name": "Examen del segundo parcial", "weight": 35, "match": ["segundo parcial"]}, CALC_ACTIVITIES]}],
    "sources": ["Sílabo MATG1049 2026-2T.pdf, pág. 1 (J. EVALUACIÓN)"],
    "open_questions": ["¿Cómo se reemplaza el examen del primer parcial, que este semestre no se toma por El Niño?"]}
CALC_LESSON = "Lección que reemplaza el examen del primer parcial"
CALC_SCHEME = {
    "periods": [{"name": "Curso", "weight": 100,
                 "exception": "Sin examen en el primer parcial por El Niño: lo reemplaza una lección que vale lo mismo.",
                 "components": [{"name": CALC_LESSON, "weight": 35, "match": ["lección del primer parcial"]},
                                {"name": "Examen del segundo parcial", "weight": 35, "match": ["segundo parcial"]},
                                CALC_ACTIVITIES]}],
    "sources": ["Sílabo MATG1049 2026-2T.pdf, pág. 1 (J. EVALUACIÓN)", "Me lo dijo el estudiante el 30 sep"]}
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

SKILL_TOOLS = {"skills_list", "skill_view", "skill_manage"}
VINCI_TOOLS_OK = {"web_search", "web_extract", "memory", "session_search", "clarify"} | SKILL_TOOLS
SUBJECT_TOOLS_OK = {"memory", "session_search", "clarify", "ver_pagina"} | SKILL_TOOLS

IMAGE_RE = re.compile(r"\[Image attached at: ([^\]]+)\]")
VOICE_RE = re.compile(r"(?:voice message: |audio is available at: )([^\s\]]+)")
REPLY_RE = re.compile(r'\[Replying to[^:]*: "(.+?)"\]', re.S)
DOC_RE = re.compile(r"saved at:?\s*([^\s\]'\"]+\.pdf)", re.I)
QUIZ_SKILL = 'invoked the "quiz" skill'
QUIZ_TOPIC = re.compile(r"instruction alongside the skill invocation: (.+)$", re.M)
QUIZ_HANDOFF = re.compile(r"^/quiz (.+)$", re.M)


def quiz_questions(topic: str, sources: list[dict]) -> list[dict]:
    """What the scripted model asks, one question per source ({file_id, page} or {entry_id})."""
    bank = [("¿Qué dice la regla de la cadena para (f∘g)'(x)?", ["f'(g(x))·g'(x)", "f'(x)·g'(x)", "f(g'(x))"],
             "Se deriva la de afuera evaluada en la de adentro y se multiplica por la derivada de la de adentro."),
            ("¿Cuál es la derivada de sen(x²)?", ["2x·cos(x²)", "cos(x²)", "2x·sen(x)"],
             "Es la regla de la cadena con g(x) = x²."),
            ("¿Qué mide la derivada de una función en un punto?", ["La pendiente de la tangente", "El área bajo la "
             "curva", "El valor de la función"], "La derivada es la pendiente de la recta tangente en ese punto.")]
    return [{"question": f"{q} ({topic})", "options": opts, "answer": opts[0], "explanation": why, **src}
            for (q, opts, why), src in zip(bank, sources)]


# -- the model's side ------------------------------------------------------------------------


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
    return None


def subject_of(req: dict) -> str | None:
    """The subject of a subject bot's request («…el bot de la materia **Física I**…»)."""
    text = "\n".join(flatten(m.get("content")) for m in req.get("messages") or [])
    match = re.search(r"el bot de la materia \*\*([^*]+)\*\*", text)
    return match[1] if match else None


def system_of(req: dict) -> str:
    return "\n".join(flatten(m.get("content")) for m in req.get("messages") or [] if m.get("role") == "system")


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
            return self.vinci(text, called, results)
        return self.subject(subject_of(req) or bot, text, called, results)

    def vinci(self, text: str, called: list[str], results: list[str]) -> dict:
        flow = self.vinci_material(text, called, results)
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
            elif isinstance(data, dict) and data.get("confirmacion"):
                parts.append(data["confirmacion"])
            elif isinstance(data, dict) and data.get("mensaje"):
                parts.append(data["mensaje"])
            elif isinstance(data, dict) and "entradas" in data:
                parts.append("Esto hay en el cuaderno:\n" + "\n".join(
                    f"- {e['tipo']}: {e['texto']}" for e in data["entradas"][:8]))
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

    def grades(self, text: str, called: list[str], results: list[str]) -> dict | None:
        """A subject bot's calculator: with no scheme it reads the syllabus and proposes one."""
        last = _json(results[-1]) if results else None
        if "cómo voy en la materia" in text:
            if not called:
                return _call("mcp__materia__grade_status")
            if called[-1] == "mcp__materia__grade_status" and isinstance(last, dict) and last.get("scheme", 0) is None:
                return _call("mcp__materia__archivos", nombre="sílabo")
            if called[-1] == "mcp__materia__archivos" and isinstance(last, dict):
                syllabus = next(f for f in last["material"] if "Sílabo" in f["archivo"])
                return _call("mcp__materia__leer_archivo", archivo_id=syllabus["id"])
            if called[-1] == "mcp__materia__leer_archivo":
                pages = " ".join(p["texto"] for p in (last or {}).get("contenido", []))
                if "Primer parcial 35%, segundo parcial 35%, deberes y lecciones 30%" not in pages:
                    return {"content": "No encontré en el sílabo cómo se evalúa. ¿Me dices cómo se evalúa?"}
                return _call("mcp__materia__propose_grading_scheme", **CALC_SYLLABUS_SCHEME)
            return {"content": self.grade_answer(last) or _problem(results[-1])}
        for trigger, call in (
                ("lo reemplaza una lección", lambda: _call("mcp__materia__propose_grading_scheme", **CALC_SCHEME)),
                ("y si saco 70", lambda: _call("mcp__materia__grade_status", what_if=[
                    {"period": "curso", "component": CALC_LESSON.lower(), "score": 70}])),
                ("saqué 16/20", lambda: _call("mcp__materia__record_grade", period="Curso", component=CALC_LESSON,
                                               label="Lección del primer parcial", score=16, out_of=20))):
            if trigger in text:
                return call() if not called else {"content": self.grade_answer(last) or _problem(results[-1])}
        return None

    def subject(self, name: str, text: str, called: list[str], results: list[str]) -> dict:
        flow = self.quiz(name, text, called, results)
        if flow is not None:
            return flow
        if re.search(r"^TAREA: brief_de_clase", text, re.M):  # the skill quotes it mid-line
            if not called:
                return _call("mcp__materia__buscar_material", pregunta="regla de la cadena")
            hits = _json(results[-1]) if results else None
            hits = hits.get("resultados") if isinstance(hits, dict) else hits
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
        if re.search(r"^TAREA: entrega_de_vinci", text, re.M):
            count = len(re.findall(r"^Entrega #\d+", text, re.M))
            photos = len(re.findall(r"^  - foto #\d+", text, re.M))
            extra = f", con {photos} foto(s) ya guardada(s) en tu cuaderno" if photos else ""
            return {"content": f"📨 De parte de Vinci: recibí {count} cosa(s){extra}. "
                               "Empieza por repasar la regla de la cadena."}
        for topic, (question, english, general) in CITED.items():
            if f"cítame el material sobre {topic}" in text:
                if not called:
                    return _call("mcp__materia__buscar_material", pregunta=question, traduccion=english)
                return {"content": self.cited_answer(_json(results[-1]), name, general)}
        if "en qué página está la regla de L'Hôpital" in text:
            return {"content": FROM_MEMORY}
        flow = self.grades(text, called, results)
        if flow is None:
            flow = self.material(text, called, results)
        if flow is not None:
            return flow
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
        if "qué material" in text:
            return _call("mcp__materia__archivos")
        return {"content": f"Hola, soy el bot de {name}."}

    def quiz(self, name: str, text: str, called: list[str], results: list[str]) -> dict | None:
        """/quiz on a subject bot (a topic, or the material it is sent next) and a quiz Vinci handed over."""
        last = _json(results[-1]) if results else None
        refused = bool(results) and not (isinstance(last, dict) and "quiz" in last)
        doc = DOC_RE.search(text)
        handoff = QUIZ_HANDOFF.search(text) if re.search(r"^TAREA: entrega_de_vinci", text, re.M) else None
        if QUIZ_SKILL in text and not handoff:
            topic = QUIZ_TOPIC.search(text)
            if not topic:
                return {"content": "¿De qué tema quieres el quiz? O mándame el material (texto, foto o PDF)."}
            if not called:
                return _call("mcp__materia__buscar_material", pregunta=topic[1], traduccion="chain rule")
            if called[-1] == "mcp__materia__buscar_material":
                top = last["resultados"][0]
                sources = [{"file_id": top["archivo_id"], "page": 999},  # a page it never read: refused
                           *({"file_id": h["archivo_id"], "page": h["pagina"]} for h in last["resultados"][:2])]
                return _call("mcp__materia__send_quiz", topic=topic[1], questions=quiz_questions(topic[1], sources))
            if called.count("mcp__materia__send_quiz") == 1 and refused:
                hits = _json(results[-2])["resultados"]
                sources = [{"file_id": h["archivo_id"], "page": h["pagina"]} for h in (hits * 3)[:3]]
                return _call("mcp__materia__send_quiz", topic=topic[1], questions=quiz_questions(topic[1], sources))
        elif doc and "quiz" in text:
            if not called:
                return _call("mcp__materia__agregar_material", ruta=doc[1])
            if called[-1] == "mcp__materia__agregar_material" and isinstance(last, dict) and "archivo_id" in last:
                sources = [{"file_id": last["archivo_id"], "page": 1}] * 2
                return _call("mcp__materia__send_quiz", topic="lo que me mandaste",
                             questions=quiz_questions("tu PDF", sources))
        elif handoff:
            if not called:
                return _call("mcp__materia__cuaderno", tipo="foto")
            if called[-1] == "mcp__materia__cuaderno":
                return _call("mcp__materia__buscar_material", pregunta=handoff[1])
            if called[-1] == "mcp__materia__buscar_material":
                photo = _json(results[-2])["entradas"][0]
                top = last["resultados"][0]
                sources = [{"entry_id": photo["id"]}, {"file_id": top["archivo_id"], "page": top["pagina"]}]
                return _call("mcp__materia__send_quiz", topic=handoff[1], questions=quiz_questions(handoff[1], sources))
        else:
            return None
        if refused:
            return {"content": _problem(results[-1])}
        intro = "📨 De parte de Vinci: " if handoff else ""
        return {"content": f"{intro}🧠 Ahí van {last['questions']} preguntas de {last['topic']}; al final te digo "
                           "cómo te fue."}

    def material(self, text: str, called: list[str], results: list[str]) -> dict | None:
        """The material requests that take several tools: the next call, or the answer."""
        last = _json(results[-1]) if results else None
        refused = isinstance(last, dict) and "error" in last  # ver_pagina answers text, or {"error": …}
        failed = refused or bool(results) and not isinstance(last, dict)
        doc = DOC_RE.search(text)
        if doc and "libro principal" in text:
            if not called:
                return _call("mcp__materia__agregar_material", ruta=doc[1], libro_principal=True)
            return {"content": self.subject_answer(results)}
        if doc and "agrega" in text:  # a scan is read with OCR as it is added: read it back
            if not called:
                return _call("mcp__materia__agregar_material", ruta=doc[1])
            if called == ["mcp__materia__agregar_material"] and not failed:
                return _call("mcp__materia__leer_archivo", archivo_id=last["archivo_id"])
            return {"content": self.subject_answer(results[:1]) + "\n" + self.reading_answer(results[-1])}
        for trigger, question, english in (("regla de la cadena con tu libro", "regla de la cadena", "chain rule"),
                                           ("tiro parabólico", "tiro parabólico alcance máximo",
                                            "projectile motion maximum range"),
                                           ("regla del paralelogramo", "regla del paralelogramo",
                                            "parallelogram rule")):
            if trigger in text:
                if not called:
                    return _call("mcp__materia__buscar_material", pregunta=question, traduccion=english)
                return {"content": _problem(results[-1]) if failed else self.search_answer(last)}
        if "documento de políticas" in text:  # an announcement's link: its text alone does not show it
            if not called:
                return _call("mcp__materia__anuncios")
            if called == ["mcp__materia__anuncios"] and isinstance(last, list):
                item = next(a for a in last if "políticas" in a["titulo"])
                return _call("mcp__materia__leer_archivo", enlace_id=item["enlaces"][0]["enlace_id"])
            return {"content": self.reading_answer(results[-1])}
        if "rúbrica de la tarea" in text:  # a link an assignment carries, found in the catalog
            if not called:
                return _call("mcp__materia__archivos", nombre="rúbrica")
            if called == ["mcp__materia__archivos"] and isinstance(last, dict) and last.get("enlaces"):
                retry = {"reintentar": True} if "otra vez" in text else {}
                return _call("mcp__materia__leer_archivo", enlace_id=last["enlaces"][0]["enlace_id"], **retry)
            return {"content": self.reading_answer(results[-1])}
        for trigger, pick in (("guía de optimización", lambda link: "optimización" in link["titulo"]),
                              ("SharePoint", lambda link: "SharePoint" in link["tipo"])):
            if trigger in text:
                if not called:
                    return _call("mcp__materia__archivos")
                if called == ["mcp__materia__archivos"] and not failed:
                    link = next(link for link in last.get("enlaces", []) if pick(link))
                    return _call("mcp__materia__bajar_archivo", enlace_id=link["enlace_id"])
                return {"content": self.subject_answer(results)}
        if "como imagen" in text:
            if not called:
                return _call("ver_pagina", archivo_id=5001, pagina=2)
            return {"content": ("🖼️ " + str(results[-1])[:300]) if not refused else _problem(results[-1])}
        if "lectura de vectores" in text:
            if not called:
                return _call("mcp__materia__archivos", nombre="lectura")
            if refused or called[-1] != "ver_pagina" and failed:
                return {"content": _problem(results[-1])}
            if called[-1] == "mcp__materia__archivos":
                entry = next(f for f in last["material"] if "Suma de vectores" in f["archivo"])
                return _call("mcp__materia__bajar_archivo", archivo_id=entry["id"])
            if called[-1] == "mcp__materia__bajar_archivo" and last.get("estado") == "escaneado":
                return _call("ver_pagina", archivo_id=last["archivo_id"], pagina=1)
            return {"content": "🖼️ La lectura es un escaneo, así que miré su página 1 como imagen: la suma de "
                               "vectores por el método del paralelogramo. " + str(results[-1])[:200]}
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

    @staticmethod
    def search_answer(data: dict) -> str:
        hits = data.get("resultados") or []
        if not hits:
            return "No encontré eso en tu material. " + data.get("nota", "")
        return "📚 Lo que dice tu material:\n" + "\n".join(
            f"📄 {h['archivo']}, {h.get('unidad') or 'página'} {h['pagina']}"
            + (f" ({h['prioridad']})" if h.get("prioridad") else "") + (f" [{h['idioma']}]" if h.get("idioma") else "")
            + (" (texto por OCR)" if h.get("ocr") else "") for h in hits[:4])

    @staticmethod
    def subject_answer(results: list[str]) -> str:
        data = _json(results[-1])
        if isinstance(data, dict) and "archivo_id" in data and "estado" in data:
            book = " como tu libro principal" if data.get("libro_principal") else ""
            return f"📥 Listo: «{data['archivo']}» quedó en tu material{book} ({data['estado']})."
        if isinstance(data, dict) and "material" in data:
            return "📚 Material del curso: " + "; ".join(f["archivo"] for f in data["material"]) + (
                f"\n{data['nota']}" if data.get("nota") else "")
        if isinstance(data, dict) and data.get("tipo") in ("foto", "audio", "documento"):
            icon = {"foto": "📸", "audio": "🎙️", "documento": "📄"}[data["tipo"]]
            return f"{icon} Guardé en tu cuaderno ({data['tipo']} #{data['id']}): {data['texto']}"
        if isinstance(data, dict) and data.get("tipo"):
            return f"📝 Anoté tu {data['tipo'].replace('_', ' ')} (#{data['id']}): {data['texto']}"
        return _problem(results[-1])


# -- helpers ---------------------------------------------------------------------------------


def readable(message: dict) -> str:
    if message.get("method") == "sendPoll":
        options = [o["text"] for o in message["options"]]
        return (f"📊 {message['question']}\n" + "\n".join(f"( ) {o}" for o in options)
                + f"\n[correcta al responder: {options[int(message['correct_option_id'])]}] {message['explanation']}")
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

    with FakeCanvas(CANVAS_TOKEN) as canvas, FakeTelegram({BOT_TOKEN: USERNAMES[BOT_TOKEN]}) as telegram, \
            FakeWeb() as web:
        calendar_feed_url = f"{canvas.base}/feeds/calendars/user-e2e.ics"
        announcement_feed_url = f"{canvas.base}/feeds/announcements/course-101.atom"
        canvas.web = web.base
        canvas.announcement_feeds["/feeds/announcements/course-101.atom"] = \
            '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        config = REPO.joinpath("config.toml").read_text(encoding="utf-8")
        config = config.replace('url = "https://aulavirtual.espol.edu.ec"', f'url = "{canvas.base}"')
        config = config.replace('carpeta_datos = "~/.local/share/espol-academic-bot"', f'carpeta_datos = "{data_dir}"')
        config = config.replace('proveedor = "anthropic"', 'proveedor = "fakellm"')
        config = config.replace('modelo = "claude-sonnet-5-5"', 'modelo = "fake"')
        config = config.replace("request_interval_seconds = 1.0", "request_interval_seconds = 0")  # paced below
        hosts = ", ".join(f'"{host}" = "{web.base}"' for host in (
            "docs.google.com", "drive.google.com", "drive.usercontent.google.com", "googleusercontent.com", "sharepoint.com"))
        config += f"\n[test]\nlink_hosts = {{ {hosts} }}  # Google and SharePoint are FakeWeb here\n"
        config_file = tmp_path / "config.toml"
        config_file.write_text(config, encoding="utf-8")
        secrets = tmp_path / "secrets.env"
        secrets.write_text(
            f"CANVAS_TOKEN={CANVAS_TOKEN}\n"
            f"CANVAS_CALENDAR_FEED_URL={calendar_feed_url}\n"
            f"CANVAS_ANNOUNCEMENT_FEED_URLS={announcement_feed_url}\n"
            f"TELEGRAM_BOT_TOKEN={BOT_TOKEN}\nTELEGRAM_USER_ID={CAPTAIN_ID}\n"
        )
        secrets.chmod(0o600)
        llm_ctx = ScriptedLLM(Script(pwned, secrets))
        llm = llm_ctx.__enter__()

        def normalize(text: str) -> str:
            text = text.replace(calendar_feed_url, "<calendar-feed>")
            text = text.replace(announcement_feed_url, "<announcement-feed>")
            text = text.replace(canvas.base, "https://aulavirtual.test").replace(telegram.base, "https://telegram.test")
            text = text.replace(llm.base, "https://llm.test").replace(web.base, "https://profesor.test")
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
            assert sorted(j["name"] for j in jobs) == ["vinci-mantenimiento", "vinci-resumen", "vinci-sondeo"], jobs
            by_name = {j["name"]: j for j in jobs}
            assert by_name["vinci-sondeo"]["schedule_display"] == "15,45 * * * *", "cada 30 min, lejos del resumen"
            assert by_name["vinci-mantenimiento"]["schedule_display"] == "2,12,22,32,42,52 * * * *"
            assert by_name["vinci-resumen"]["schedule"].get("expr") == "0 7 * * *" or \
                by_name["vinci-resumen"]["schedule_display"] == "0 7 * * *"
            assert all(j["no_agent"] and j["deliver"] == f"telegram:{CAPTAIN_ID}" for j in jobs)
            assert "sin cambios" in second.stdout and "creado" not in second.stdout
            for out in (first.stdout, second.stdout):
                assert "✓ vinci: su skill llega al modelo" in out and "✗" not in out and "no pude revisar" not in out, out
            # A toolset the captain switches on in config.toml leaves the blocked list; switching it off restores it.
            original = config_file.read_text(encoding="utf-8")
            vcfg_before_switch = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
            config_file.write_text(original.replace("vinci = []", 'vinci = ["terminal", "file"]'), encoding="utf-8")
            switched = run(["bash", str(REPO / "setup.sh"), "--skip-deps", "--sin-pruebas"], T_SETUP)
            scfg_on = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
            assert {"terminal", "file"} <= set(scfg_on["platform_toolsets"]["telegram"]) & set(scfg_on["platform_toolsets"]["cron"])
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
            profile_env = parse_env_file(profile / ".env")
            assert profile_env["TELEGRAM_BOT_TOKEN"] == BOT_TOKEN
            assert profile_env["TELEGRAM_ALLOWED_USERS"] == profile_env["TELEGRAM_HOME_CHANNEL"] == CAPTAIN_ID
            vcfg = yaml.safe_load((profile / "config.yaml").read_text(encoding="utf-8"))
            assert vcfg["timezone"] == "America/Guayaquil" and vcfg["model"]["provider"] == "fakellm"
            assert vcfg["model"]["default"] == "fake", "the config.toml model substitution no longer matches"
            assert set(vcfg["platform_toolsets"]["telegram"]) == {"web", "memory", "session_search", "clarify",
                                                                  "skills", "mcp-vinci"}
            assert set(vcfg["platform_toolsets"]["cli"]) == set(vcfg["platform_toolsets"]["telegram"])
            assert set(vcfg["platform_toolsets"]["cron"]) == {"web", "memory", "skills", "mcp-vinci"}
            assert {"terminal", "file", "code_execution", "delegation", "cronjob"} <= \
                set(vcfg["agent"]["disabled_toolsets"]) and "skills" not in vcfg["agent"]["disabled_toolsets"]
            assert vcfg["tools"]["tool_search"]["enabled"] == "off"
            assert vcfg["skills"]["auto_load"] == ["vinci"]
            assert vcfg["compression"]["threshold_tokens"] == 80_000, "Vinci resume su chat a los 80 mil tokens"
            assert vcfg["mcp_servers"]["vinci"]["command"] == str(VENV_BIN / "espol-bot")
            assert vcfg["mcp_servers"]["vinci"]["args"][:1] == ["mcp"]
            assert "vinci-botones" in vcfg["plugins"]["enabled"]
            assert vcfg["unauthorized_dm_behavior"] == "ignore" and vcfg["stt"]["language"] == "es"
            assert vcfg["platforms"]["telegram"]["extra"]["base_url"] == f"{telegram.base}/bot"
            assert vcfg["platforms"]["telegram"]["extra"]["drop_pending_on_cold_boot"] is False
            assert {"*secrets.env*", "*CANVAS_TOKEN*", "*api/v1*"} <= set(vcfg["approvals"]["deny"])
            assert (profile / "skills" / "vinci" / "vinci" / "SKILL.md").is_file()
            assert telegram.profile_photos.get("vinci_bot") == [(AVATARS / "wizard.jpg").read_bytes()], \
                "setup.sh le pone a Vinci su mago como foto de perfil, una sola vez"
            assert "Foto de perfil de Vinci puesta" in first.stdout and "Foto de perfil de Vinci sin cambios" in second.stdout
            soul = (profile / "SOUL.md").read_text(encoding="utf-8")
            assert "- «Sistemas Distribuidos»: Sistemas Distribuidos y Computación en la Nube (CCPG1055)" in soul \
                and "- «Estadística»: Estadística (ESTG1034)" in soul, "Vinci sabe cómo se llama cada bot de materia"
            assert not [w for w in ROLEPLAY if w in soul], "Vinci no hace de personaje"
            assert (home / ".local" / "bin" / "aula").is_file()
            assert (home / ".claude" / "skills" / "aula" / "SKILL.md").is_file()
            assert not (home / ".hermes" / "config.yaml").exists(), "setup no debe crear config del perfil por defecto"
            report.append(f"setup.sh ×2 con Hermes real en un HOME aislado: el perfil «espol» del bot anterior pasó "
                          f"a «vinci» con su memoria; {len(jobs)} cron no-agent; la segunda corrida no cambió nada")
            report.append("Vinci quedó con su foto: setup.sh le puso su mago como foto de perfil con setMyProfilePhoto "
                          "una sola vez (la segunda corrida no la volvió a subir); su SOUL.md no le da ningún personaje "
                          "y lista cada bot de materia con el nombre de su materia («Sistemas Distribuidos»…)")
            take("setup.sh (mensaje de prueba de Vinci)")
        else:
            setup_log = "Hermes no está instalado aquí: se omitió la prueba de setup.sh.\n"
            report.append("setup.sh omitido: Hermes no está instalado en esta máquina")

        # 1b. Telegram over a broken IPv6 route (IPv4 works): no Bot API call may wait on it ---------
        with BrokenIPv6(telegram) as broken:
            if broken.base:
                started = time.monotonic()
                run([str(VENV_BIN / "espol-bot"), "probar"], T_SETUP, env_extra={"ESPOL_TELEGRAM_API_BASE": broken.base})
                took = time.monotonic() - started
                probe = take("Prueba de Vinci con el IPv6 de Telegram roto")
                assert len(probe) == 1 and "Prueba" in probe[0]["text"], probe
                assert took < 5, f"con IPv6 roto, `espol-bot probar` tardó {took:.1f} s: se quedó esperando al IPv6"
                report.append("Con el IPv6 hacia Telegram roto y el IPv4 funcionando (como en la red del capitán), "
                              "Vinci envió su mensaje de prueba y consultó getMe en menos de 5 s: sus llamadas al "
                              "Bot API prueban IPv4 primero en vez de esperar a que venza el IPv6")
            else:
                report.append("IPv6 roto omitido: en esta máquina localhost no resuelve primero a ::1")

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
        assert len(poll1) == 2, poll1
        assert "Listo" in poll1[0]["text"] and "Recordatorio" in poll1[1]["text"] and "Deber 2" in poll1[1]["text"]

        canvas.state = "state2"
        canvas.slow_downloads[5010] = 8
        sondeo = subprocess.Popen([bot, "sondeo"], env={**base_env, "AULA_NOW": T_POLL2}, cwd=REPO, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        downloading = telegram.wait_for(lambda _: any("/files/5010/download" in p for _, p in list(canvas.requests)), 60)
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
                         "Nuevo material en Cálculo de una Variable</b>\nSílabo MATG1049 2026-2T.pdf",
                         "Enlace nuevo en Cálculo de una Variable</b> · Semana 4: Aplicaciones de la "
                         "derivada · ANTES de clase en vivo"):
            assert expected in texts, f"falta «{expected}» en el sondeo 2:\n{texts}"
        by_title = {m["text"].split("\n")[1]: m["text"] for m in poll2 if "\n" in m["text"]}
        assert "Ya lo leí" in by_title["Sílabo MATG1049 2026-2T.pdf"], "el sílabo se baja y se lee solo"
        assert "Lo bajo y lo leo cuando haga falta" in by_title["Semana 2 - Cinemática.pptx"], \
            "lo demás no se baja solo: queda en el catálogo"
        assert "Su bot de materia lo abre sin tu cuenta" in texts, "el enlace de un módulo avisa que el bot lo abre"
        assert len(poll2) == 8, [m["text"][:40] for m in poll2]
        for m in poll1 + poll2:  # no subject bots yet: no handoff buttons, only «Ya lo entregué» under a reminder
            assert [b["text"] for b in buttons(m)] == ([SUBMITTED] if "Recordatorio" in m["text"] else []), m

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
                     "✅ Token de Canvas: renovado hace un momento (22:22); la cadena está sana",
                     "✅ Calendario (iCal): activo", "✅ Anuncios (RSS/Atom): activo"):
            assert line in healthy, f"falta «{line}»:\n{healthy}"
        stale = doctor("tres horas después, con la PC apagada (nada corrió)", "2026-09-30T01:22:00-05:00", broken=True)
        for line in ("❌ Sondeo: no corre desde hace 3 h (mar 29 sep, 22:22); debería cada 30 min", "❌ Mantenimiento: no corre desde",
                     "❌ Token de Canvas: se creó hace 3 h", "⚠️ Aula virtual: leída por última vez hace 3 h",
                     "⚠️ Calendario (iCal): leído por última vez hace 3 h", "→ hermes gateway status"):
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
        assert "cadena automática del token" in cut_text and "resembrar" in cut_text, cut_text
        assert "Crear token nuevo" in json.dumps(cut, ensure_ascii=False)
        assert "reemplazo funciona" not in cut_text, "no hay reemplazo: la cadena está cortada"
        api = [request for request in canvas.requests[mark:] if not request[1].startswith("/feeds/")]
        assert [method for method, _ in api] == ["GET", "DELETE"], api
        assert parse_env_file(secrets)["CANVAS_TOKEN"] == fourth and len(canvas.issued()) == 4
        mark = len(canvas.requests)
        run([bot, "mantenimiento"], T_RENEW_5)
        run([bot, "sondeo"], T_RENEW_5)
        assert take("Cadena cortada · mantenimiento y sondeo siguientes") == [], "el aviso no se repite"
        assert all(path.startswith("/feeds/") for _, path in canvas.requests[mark:]), \
            "con la cadena cortada, nadie vuelve a llamar a Canvas con un token muerto"
        cut_health = doctor("la cadena del token se cortó", T_RENEW_5, broken=True)
        assert "❌ Token de Canvas: la cadena de renovación está cortada" in cut_health, cut_health
        assert "espol-bot resembrar" in cut_health and "✅ Calendario (iCal): activo" in cut_health, cut_health
        assert "✅ Sondeo" in cut_health and "✅ Mantenimiento" in cut_health, cut_health
        report.append("Con el token actual y la sonda vencidos, el mantenimiento avisó que la cadena se cortó y cómo "
                      "resembrarla (no que el reemplazo funciona), y desde entonces ni el mantenimiento ni el sondeo "
                      "llamaron a Canvas con esos tokens")

        # 6d. With every token dead, public feeds still update due dates and announcements ------------------
        canvas.calendar_feed = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:assignment-3004@canvas
DTSTART:20260930T180000Z
SUMMARY:Taller 2: Movimiento parabólico
URL:{base}/courses/102/assignments/3004
END:VEVENT
BEGIN:VEVENT
UID:event-lectura-1@canvas
DTSTART:20261001T140000Z
SUMMARY:Lectura guiada de Cálculo
URL:{base}/courses/101/calendar_events/9001
END:VEVENT
END:VCALENDAR
""".format(base=canvas.base)
        canvas.announcement_feeds["/feeds/announcements/course-101.atom"] = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>tag:canvas,2026:topic-2999</id><title>Clase en laboratorio</title>
  <published>2026-09-30T02:20:00Z</published><author><name>Docente</name></author>
  <link href="{base}/courses/101/discussion_topics/2999" />
  <content type="html">Lleven su computador cargado.</content></entry>
</feed>
""".format(base=canvas.base)
        run([bot, "sondeo"], T_RENEW_5)
        floor = take("Piso sin token · iCal y anuncios Atom")
        floor_text = "\n".join(message["text"] for message in floor)
        assert "cadena automática del token" not in floor_text, "el corte ya se avisó una vez"
        assert "Cambió la fecha de entrega" in floor_text and "Clase en laboratorio" in floor_text
        pending_floor = json.loads(run([aula, "tareas", "--sin-actualizar", "--json"], T_RENEW_5).stdout)
        assert any(task["tarea"] == "Lectura guiada de Cálculo" for task in pending_floor)
        mark = len(canvas.requests)
        run([bot, "sondeo"], T_RENEW_5)
        assert take("Piso sin token repetido") == [], "el aviso de re-siembra y los feeds no se duplican"
        assert all(method == "GET" and path.startswith("/feeds/") for method, path in canvas.requests[mark:])
        report.append("Con toda la cadena de tokens vencida, iCal actualizó una fecha y agregó un evento, Atom trajo "
                      "un anuncio, y Vinci siguió alertando sin mandar Authorization a esos feeds")

        # 6e. A hidden terminal prompt re-seeds the chain; the token never passes through Telegram -------------
        canvas.valid_tokens.add(NEW_CANVAS_TOKEN)
        canvas.mint(NEW_CANVAS_TOKEN, "Token personal")
        reseed = run([bot, "resembrar", "--stdin"], T_RENEW_5, stdin=NEW_CANVAS_TOKEN + "\n")
        assert "verificado" in reseed.stdout.lower() and NEW_CANVAS_TOKEN not in reseed.stdout + reseed.stderr
        reseeded = parse_env_file(secrets)["CANVAS_TOKEN"]
        assert reseeded in canvas.valid_tokens
        run([bot, "sondeo"], T_RENEW_5)
        after_reseed = take("Cadena resembrada")
        assert not any("cadena automática del token" in message["text"] for message in after_reseed)
        reseeded_health = doctor("después de resembrar", T_RENEW_5, broken=False)
        assert "✅ Token de Canvas: renovado hace un momento" in reseeded_health, reseeded_health
        report.append("`espol-bot doctor` mostró sondeo, lectura del aula, mantenimiento, edad del token y feeds sin "
                      "consultar el aula ni escribir al chat: todo ✅ con la cadena sana; tres horas sin que nada "
                      "corriera, ❌ en el sondeo, el mantenimiento y el token vencido (con qué revisar); con la "
                      "cadena cortada, ❌ en el token y cómo resembrarlo, con los feeds todavía activos; y ✅ otra "
                      "vez tras resembrar")
        report.append("Tras el corte total, `espol-bot resembrar` leyó el token con entrada oculta, lo verificó y "
                      "reactivó la cadena sin imprimirlo ni enviarlo por Telegram")

        equipo_md = ["# El equipo de bots, desde el chat con Vinci\n"]
        material_md = ["# El material de cada materia (lo que vio el modelo)\n"]
        quiz_md = ["# /quiz: un quiz corto con el material de la materia\n",
                   "Cada pregunta es una encuesta tipo quiz de Telegram (sendPoll), tal como la recibió el Telegram "
                   "falso; la respuesta correcta y la explicación con su cita se ven recién al responder.\n"]
        horario_md = ["# Horario desde una captura (se guarda solo con el botón del capitán)\n"]
        briefs_md = ["# Brief antes de clase\n"]
        party_md = ["# Tu party: el nombre y la foto de cada bot\n",
                    "Cada bot de materia se llama solo como su materia. Cada foto es la que el bot subió a Telegram "
                    "(setMyProfilePhoto), tal como la recibió el Telegram falso; el texto citado abre su SOUL.md.\n"]
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
        mutations = [(method, urlsplit(path).path) for method, path in canvas.requests if method != "GET"]
        assert mutations and all(method in {"POST", "DELETE"} and
                                 (path == "/api/v1/users/self/tokens" or
                                  re.fullmatch(r"/api/v1/users/self/tokens/\d+", path))
                                 for method, path in mutations), mutations
        assert canvas.throttled, "el 429 de prueba debió ocurrir"
        assert any("page=2" in p for _, p in canvas.requests), "debió seguir la paginación"
        assert all(str(m.get("chat_id")) == CAPTAIN_ID for _, m in sent_log), \
            ("solo se escribe al capitán", [(label, {k: v for k, v in m.items() if k != "text"})
                                            for label, m in sent_log if str(m.get("chat_id")) != CAPTAIN_ID])
        assert not any("5002" in p and "download" in p for _, p in canvas.requests), "archivo enorme no se baja"
        downloaded = {int(p.split("/")[2]) for _, p in canvas.requests if p.startswith("/files/")}
        assert downloaded == {5001, 5005, 5010, 5301, 5101} | ({5102} if vinci_section else set()), \
            f"solo los sílabos se bajan solos; lo demás, cuando se pide: {sorted(downloaded)}"
        secrets_all = [CANVAS_TOKEN, NEW_CANVAS_TOKEN, first, second, third,
                       calendar_feed_url, announcement_feed_url, BOT_TOKEN,
                       *SUBJECT_TOKENS.values(), UNKNOWN_TOKEN, STRANGER_TOKEN,
                       *PARTY_TOKENS.values()]
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
    def safe_canvas_path(path: str) -> str:
        if urlsplit(path).path.startswith("/feeds/"):
            return "/feeds/<secret>"
        return re.sub(r"verifier=[^&]+", "verifier=…", path)

    requests_log = "\n".join(f"{method} {safe_canvas_path(path)}" for method, path in canvas.requests)
    (artifact / "canvas_requests.log").write_text(requests_log + "\n", encoding="utf-8")
    (artifact / "estado.md").write_text(normalize("\n".join(estado_md)), encoding="utf-8")
    if vinci_section:
        (artifact / "equipo.md").write_text(normalize("\n".join(equipo_md)), encoding="utf-8")
        (artifact / "material.md").write_text(normalize("\n".join(material_md)), encoding="utf-8")
        (artifact / "quiz.md").write_text(normalize("\n".join(quiz_md)), encoding="utf-8")
        (artifact / "horario.md").write_text(normalize("\n".join(horario_md)), encoding="utf-8")
        (artifact / "briefs.md").write_text(normalize("\n".join(briefs_md)), encoding="utf-8")
        (artifact / "party.md").write_text(normalize("\n".join(party_md)), encoding="utf-8")
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
        for secret in (CANVAS_TOKEN, NEW_CANVAS_TOKEN, first, second, third,
                       calendar_feed_url, announcement_feed_url, "/feeds/calendars/user-e2e.ics",
                       "/feeds/announcements/course-101.atom", BOT_TOKEN,
                       *SUBJECT_TOKENS.values(), UNKNOWN_TOKEN, STRANGER_TOKEN,
                       *PARTY_TOKENS.values()):
            assert secret not in text, f"{path.name} contiene un token"
    counts = {label: sum(1 for l, _ in sent_log if l == label) for label in dict.fromkeys(l for l, _ in sent_log)}
    lines = [
        "# Reporte E2E: Vinci y los bots de materia (ESPOL)\n",
        "Resultado: **todas las verificaciones pasaron**.\n",
        *[f"- {line}" for line in report],
        f"- Canvas falso: {len(canvas.requests)} solicitudes; las únicas mutaciones fueron crear/borrar los tokens "
        "propios de Vinci; paginación seguida; un 429 con reintento; "
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
        "\nArchivos: `notificaciones.md`, `equipo.md`, `horario.md`, `briefs.md`, `cuadernos.md`, `material.md` (el "
        "catálogo, el libro principal, las búsquedas y los enlaces, como los vio el modelo), `pagina-escaneada.jpg` "
        "(la página que recibió el modelo), `ocr.md` (los escaneos leídos una vez con OCR), `party.md` (con la foto "
        "de cada bot, `foto-<bot>.jpg`), `pendientes.md` "
        "(«Ya lo entregué» y la lista de pendientes), `citas.md` (citas con archivo, página y enlace, «No está en el "
        "material» y las citas de memoria que no pasaron), `notas.md` (la calculadora de notas), `prioridad.md` "
        "(el orden de las entregas con sus pesos), `estado.md` "
        "(`espol-bot doctor` y /estado), "
        "`hermes_herramientas.json`, `resumen_diario.txt`, `recuperacion.json`, `cli.md`, `canvas_requests.log`, "
        "`setup.log`.\n",
    ]
    (artifact / "REPORTE.md").write_text("\n".join(lines), encoding="utf-8")


def vinci_flow(*, hermes, home, profiles, data_dir, canvas, telegram, web, llm, run, take, report, gateway, artifact,
               equipo_md, horario_md, briefs_md, party_md, material_md, quiz_md, tools_seen, pwned, secrets, base_env,
               real_tesseract, ocr_log, ocr_off, normalize, estado_md, **_) -> None:
    """Sections 6-8: the gateway session (team, schedule, routing, agenda, notebooks, archive and
    reactivation) and the last setup.sh. The caller owns `gateway` and always stops it."""
    bot = str(VENV_BIN / "espol-bot")
    telegram.managers.add(BOT_TOKEN)  # Vinci has "manage other bots" on in BotFather

    def patch_profile(name: str) -> None:
        """Test-only: the scripted model, images passed natively, no speech-to-text engine, and Vinci's clock."""
        cfg_file = profiles / name / "config.yaml"
        data = yaml.safe_load(cfg_file.read_text())
        data["providers"] = {"fakellm": {"api": f"{llm.base}/v1", "api_key": "e2e", "discover_models": False,
                                         "models": ["fake"]}}
        data.setdefault("agent", {})["image_input_mode"] = "native"
        data.setdefault("model", {})["supports_vision"] = True  # the fake model: ver_pagina's image goes to it
        data.setdefault("stt", {})["enabled"] = False
        if name == "vinci":  # Vinci's tools on the test clock: its to-do dates are checked against «today»
            data["mcp_servers"]["vinci"]["env"]["AULA_NOW"] = T_VINCI
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
                if m.get("role") == "user" and re.search(rf"^TAREA: {kind}", text, re.M) and text not in found:
                    found.append(text)
        return found

    def last_run(code: str) -> str | None:
        jobs = json.loads((profiles / f"vinci-{code.lower()}" / "cron" / "jobs.json").read_text())["jobs"]
        return next((j.get("last_run_at") for j in jobs if j["name"] == "vinci-agenda"), None)

    def agenda_starts(code: str) -> list[datetime]:
        """When each scheduled run of a subject bot's agenda started, from Hermes' executions ledger."""
        conn = sqlite3.connect(profiles / f"vinci-{code.lower()}" / "cron" / "executions.db")
        try:
            rows = conn.execute("SELECT claimed_at FROM executions WHERE scheduled_instant IS NOT NULL").fetchall()
        finally:
            conn.close()
        return sorted(datetime.fromisoformat(row[0]) for row in rows)

    def show(title: str, text: str) -> None:
        equipo_md.append(f"## {title}\n\n```\n{text.rstrip()}\n```\n")

    gate_before = run([bot, "agenda", "--curso", "MATG1049"], T_VINCI).stdout.strip()
    assert gate_before == SKIP, "sin bots, horario ni entregas la agenda no despierta al modelo"

    mark_calls = len(telegram.calls)
    sessions = [time.time()]  # when the gateway starts and stops serving
    gateway.start()
    polling({"vinci_bot"}, mark_calls)
    take("Gateway encendido (solo Vinci)")

    # /estado: the health report, from the plugin and never from the model; nothing ran overnight
    status = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "/estado"), "vinci_bot", "Estado de Vinci")
    status_text = plain(status["text"])
    for line in ("❌ Sondeo: no corre desde hace 9 h (mar 29 sep, 23:43)", "❌ Mantenimiento: no corre desde hace 9 h",
                 "❌ Token de Canvas: se creó hace 9 h", "⚠️ Aula virtual: leída por última vez hace 9 h",
                 "En una terminal: hermes gateway status"):
        assert line in status_text, f"falta «{line}» en /estado:\n{status_text}"
    assert "<b>Sondeo</b>" in status["text"] and "<code>" in status["text"]
    consumed(BOT_TOKEN, telegram.send_text(BOT_TOKEN, STRANGER, "/estado"))
    time.sleep(1)
    assert not [m for m in telegram.messages if str(m.get("chat_id")) == str(STRANGER)], "/estado solo para el capitán"
    asked = [r for r in llm.requests for m in r.get("messages") or []
             if m.get("role") == "user" and flatten(m.get("content")).strip() == "/estado"]
    assert not asked, "/estado no pasa por el modelo"
    estado_md.append(f"## /estado en el chat de Vinci · mié 30 sep 08:30, tras una noche sin sondeo ni mantenimiento"
                     f"\n\n```\n{status_text}\n```\n\nUn extraño que manda /estado no recibe nada.\n")
    report.append("/estado en el chat de Vinci contestó sin el modelo, con el sondeo, el mantenimiento y el token en ❌ "
                  "tras una noche sin correr (y qué revisar); a un extraño no le contestó nada")
    take("/estado")

    # 6. Vinci builds the team from chat ---------------------------------------------------------
    mark = len(telegram.messages)
    telegram.send_text(BOT_TOKEN, CAPTAIN, "arma mi equipo de bots por materia")
    card = wait_msg("vinci_bot", mark, "Tu equipo de bots")
    wait_msg("vinci_bot", mark, "Un bot se crea solo cuando pulse ese botón")
    assert [b["text"] for b in buttons(card)] == ["➕ Crear Cálculo de una Variable", "➕ Crear Física I"]
    assert len(re.findall(r"^• ", plain(card["text"]), re.M)) == 2 and "reconocible" not in card["text"], \
        "tres cursos del aula, dos materias: el práctico de Cálculo no es otro bot"
    assert {c: (m["estado"], m["cursos"]) for c, m in team().items()} == {
        "MATG1049": ("pendiente", [101, 103]), "FISG1002": ("pendiente", [102])}
    assert not (profiles / "vinci-matg1049").exists(), "proponer no crea nada"
    show("Vinci arma el equipo («arma mi equipo de bots por materia»)",
         plain(card["text"]) + "\n" + "".join(f"[{b['text']}]" for b in buttons(card)))
    create = {b["text"]: b["callback_data"] for b in buttons(card)}

    # Cálculo: Telegram's managed bots (the token never touches the chat)
    calls, pressed = len(telegram.calls), time.time()
    keyboard_msg = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, card, create["➕ Crear Cálculo de una Variable"]),
                        "vinci_bot", "Creemos Cálculo de una Variable")
    assert toast(calls, "Creemos")["at"] - pressed < 5, "el botón debe contestar en segundos"
    assert "Si Telegram te pide esperar porque creaste muchos bots seguidos" in plain(keyboard_msg["text"])
    calls, mark = len(telegram.calls), len(telegram.messages)
    telegram.press(BOT_TOKEN, CAPTAIN, card, create["➕ Crear Cálculo de una Variable"])
    again = toast(calls, "Ya te mandé el botón")
    time.sleep(1)
    assert not [m for m in telegram.messages[mark:] if "Creemos" in readable(m)], "un segundo «Crear» no reenvía"
    request = keyboard_msg["reply_markup"]["keyboard"][0][0]["request_managed_bot"]
    assert telegram.creation_screen(request) == ("Cálculo de una Variable", "vinci_calculo_variable_bot")
    assert team()["MATG1049"]["estado"] == "esperando_bot"
    show("Pulsa «➕ Crear Cálculo de una Variable» (Vinci puede gestionar bots)",
         plain(keyboard_msg["text"]) + f"\n[botón de Telegram: {keyboard_msg['reply_markup']['keyboard'][0][0]['text']} → "
         f"request_managed_bot {json.dumps(request, ensure_ascii=False)}]\n\nLo pulsa otra vez → aviso: "
         f"«{again['params']['text']}» (sin reenviar nada)")
    mark_start = len(telegram.messages)

    def create_and_start():
        # The captain opens the new bot and presses START at once, before the gateway serves it.
        telegram.create_managed_bot(BOT_TOKEN, CAPTAIN, MATG, "vinci_calculo_bot", "Cálculo de una Variable")
        telegram.send_text(MATG, CAPTAIN, "/start")

    created = turn(create_and_start, "vinci_bot", "quedó creado y activo", timeout=180)
    patch_profile("vinci-matg1049")
    assert created["reply_markup"] == {"remove_keyboard": True}
    assert any(c["method"] == "getManagedBotToken" and int(c["params"]["user_id"]) == 700001 for c in telegram.calls)
    show("Telegram le comparte a Vinci el bot creado (managed_bot_created)", plain(created["text"]))

    # Física: BotFather's reply forwarded (the plugin deletes it before Hermes sees it)
    telegram.add_bot(FIS, USERNAMES[FIS], "Física I")  # the captain created it with /newbot in @BotFather
    telegram.slow[(BOT_TOKEN, "getMe")] = 6  # the work behind this press is slow
    calls, pressed = len(telegram.calls), time.time()
    turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, card, create["➕ Crear Física I"]), "vinci_bot",
         "Creemos Física I")
    telegram.slow.clear()
    assert toast(calls, "Un momento")["at"] - pressed < 5, "un botón lento contesta enseguida y trabaja después"
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
        assert set(scfg["platform_toolsets"]["telegram"]) == {"memory", "session_search", "clarify", "skills",
                                                              "mcp-materia", "vinci-paginas"}
        assert set(scfg["platform_toolsets"]["cron"]) == {"memory", "skills", "mcp-materia", "vinci-paginas"}
        assert {"web", "terminal", "file"} <= set(scfg["agent"]["disabled_toolsets"])
        assert "skills" not in scfg["agent"]["disabled_toolsets"]
        assert scfg["mcp_servers"]["materia"]["args"][:4] == ["mcp", "materia", "--curso", code]
        assert scfg["unauthorized_dm_behavior"] == "ignore" and scfg["skills"]["auto_load"] == ["vinci-materia"]
        assert "vinci-botones" in scfg["plugins"]["enabled"]
        assert scfg["compression"]["threshold_tokens"] == 80_000
        jobs = json.loads((sp / "cron" / "jobs.json").read_text())["jobs"]
        assert [(j["name"], j["schedule_display"], j["no_agent"], j["script"], j["enabled"]) for j in jobs] == [
            ("vinci-agenda", "* * * * * */30", False, "vinci-agenda.sh", True)], jobs
    for token in (MATG, FIS, UNKNOWN_TOKEN):  # where a token may live: secrets.env and its own profile's .env
        holders = sorted(str(f.relative_to(home)) for f in home.rglob("*") if f.is_file()
                         and token.encode() in f.read_bytes())
        allowed = {f".hermes/profiles/vinci-{c.lower()}/.env" for c, t in SUBJECT_TOKENS.items() if t == token}
        assert set(holders) <= allowed, f"el token apareció en {holders}"
    assert "Congratulations on your new bot" not in json.dumps(llm.requests, ensure_ascii=False)
    for code in SUBJECT_TOKENS:
        soul = (profiles / f"vinci-{code.lower()}" / "SOUL.md").read_text(encoding="utf-8")
        assert "cercano y claro, como un compañero que se sabe la materia" in " ".join(soul.split())
        assert not [w for w in ROLEPLAY if w in soul]
    assert not {"vinci_calculo_bot", "vinci_fisica_bot"} & set(telegram.profile_photos), \
        "un bot sin foto en la party conserva la suya de Telegram"
    assert (telegram.name_of(MATG), telegram.name_of(FIS)) == ("Cálculo de una Variable", "Física I")
    assert not [c for c in telegram.calls if c["method"] == "setMyName"], \
        "creados con el nombre sugerido, no hay que renombrarlos"
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
    hello = wait_msg("vinci_calculo_bot", mark_start, "Soy el bot de Cálculo de una Variable", timeout=120)
    assert "Todavía no tengo tu horario" in plain(hello["text"])
    starts = [r for r in llm.requests for m in r.get("messages") or []
              if m.get("role") == "user" and flatten(m.get("content")).strip() == "/start"]
    assert not starts, "el saludo a /start no pasa por el modelo"
    show("El capitán le manda /start a Cálculo apenas lo crea (antes de que el gateway lo atienda)", plain(hello["text"]))
    report.append("Botones de Vinci: cada toque contestó en menos de 5 s, también uno cuyo trabajo tardaba (primero "
                  "«⏳ Un momento…» y después su respuesta); un segundo «➕ Crear» no reenvió el mensaje, y el mensaje "
                  "para crear el bot avisa que Telegram puede pedir esperar si se crearon muchos seguidos")
    report.append("El /start que el capitán le mandó a Cálculo apenas lo creó, antes de que el gateway lo atendiera, "
                  "tuvo respuesta: un saludo sin modelo que dice qué hace el bot y cuándo llega su brief")
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
                  "vinci_bot", "se lo pasé a Cálculo de una Variable")
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
    polled = take("Sondeo · mié 30 sep 08:30 (avisos con botón, y Cálculo pide su libro)")
    reminders = [m for m in polled if m["bot"] == "vinci_bot"]
    asks = [m for m in polled if m["bot"] != "vinci_bot"]
    assert len(reminders) == 3, [m["text"][:60] for m in reminders]
    assert [m["bot"] for m in asks] == ["vinci_calculo_bot"], [(m["bot"], m["text"][:60]) for m in asks]
    calc_ask = plain(asks[0]["text"])
    for expected in ("El libro principal de Cálculo de una Variable", "Según el sílabo es: Purcell, E., Varberg",
                     "solo está como enlace (SharePoint de ESPOL) y no lo pude abrir: pide tu cuenta de ESPOL",
                     "Hasta 20 MB: mándamelo aquí",
                     f"{data_dir}/libros/MATG1049", "No te lo vuelvo a pedir"):
        assert expected in calc_ask, f"falta «{expected}» en el pedido del libro:\n{calc_ask}"
    assert (data_dir / "libros" / "MATG1049").is_dir() and (data_dir / "libros" / "FISG1002").is_dir()
    assert [p for _, p in web.requests if ESPOL_ONLY_SHARE in p] == [
        f"/sites/MATG1049/_layouts/15/download.aspx?share={ESPOL_ONLY_SHARE}"], \
        "antes de pedir el libro, el sondeo abre sin cuenta el enlace de SharePoint del aula"
    material_md += ["## El bot de Cálculo pide su libro principal (una vez, desde su chat)\n",
                    f"```\n{calc_ask}\n```\n"]
    calc_alert = next(m for m in reminders if "Taller 3" in m["text"])
    practico_alert = next(m for m in reminders if "Práctica 4" in m["text"])
    fis_alert = next(m for m in reminders if "Examen parcial" in m["text"])
    assert "Cálculo de una Variable (práctico)" in practico_alert["text"]
    for alert in (calc_alert, practico_alert):  # theory and práctico: the same one bot
        assert [b["text"] for b in buttons(alert)] == ["🎓 Consultar con Cálculo de una Variable", SUBMITTED]
        assert re.fullmatch(r"v1:a:\d+:MATG1049", buttons(alert)[0]["callback_data"])
        assert re.fullmatch(r"v1:s:\d+:ok", buttons(alert)[1]["callback_data"])
        passed = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, alert, buttons(alert)[0]["callback_data"]),
                      "vinci_bot", "Le pasé el aviso")
        assert "Le pasé el aviso a Cálculo de una Variable" in plain(passed["text"])
    calc_avisos = [h for h in handoffs() if h["materia"] == "MATG1049" and h["origen"] == "aviso"]
    assert len(calc_avisos) == 2 and "Taller 3" in calc_avisos[0]["texto"] and "Práctica 4" in calc_avisos[1]["texto"]
    assert [b["text"] for b in buttons(fis_alert)] == ["🎓 Consultar con Física I", SUBMITTED]
    fis_data = buttons(fis_alert)[0]["callback_data"]
    assert re.fullmatch(r"v1:a:\d+:FISG1002", fis_data)
    turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, fis_alert, fis_data), "vinci_bot", "Le pasé el aviso")
    turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, fis_alert, fis_data), "vinci_bot", "Ya le había pasado")
    assert len([h for h in handoffs() if h["materia"] == "FISG1002"]) == 1, "un aviso se pasa una sola vez"
    reply_to = telegram.as_incoming(BOT_TOKEN, calc_alert, plain(calc_alert["text"]))
    turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "pásaselo al bot de cálculo, ¿por dónde empiezo?",
                                    reply_to=reply_to), "vinci_bot", "se lo pasé a Cálculo de una Variable")
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
                     "2 o 3 conceptos clave", "Una pregunta concreta",
                     "Libro principal: Purcell, E., Varberg, D. y Rigdon, S. (2007). Cálculo (9a ed.). Pearson — no tengo",
                     "  - Sílabo MATG1049 2026-2T.pdf · archivo 5010, leído",
                     "  - enlace: Guía de optimización (página del profesor) [Semana 4: Aplicaciones de la derivada · "
                     "ANTES de clase en vivo]", "con «traduccion» si el material está en inglés"):
        assert expected in task, f"falta «{expected}» en la tarea del brief:\n{task}"
    assert "Taller 3: Derivadas" in readable(brief) and "📄 [Capítulo 3 - Derivadas.pdf, página 2]" \
        f"({canvas.base}/courses/101/files/5001)" in readable(brief), \
        "el brief cita el material del curso, con el enlace del aula que le puso la revisión de citas"
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

    # 7e2. «✅ Ya lo entregué» under a reminder, and the captain's own to-do list («anota: …»)
    pendientes_md = ["# «Ya lo entregué» y tu lista de pendientes\n"]

    def fis_pending() -> list[str]:
        out = run([str(VENV_BIN / "aula"), "tareas", "--curso", "fisica", "--sin-actualizar", "--json"], T_VINCI).stdout
        return [t["tarea"] for t in json.loads(out)]

    def todo_rows() -> list[dict]:
        conn = sqlite3.connect(data_dir / "espol.db")
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM todos ORDER BY id")]
        finally:
            conn.close()

    def press(message: dict, data: str, expected: str) -> str:
        """Press a button and wait for its toast and for the pressed button to be swapped; the keyboard after."""
        before = buttons(message)
        label = next(b["text"] for b in before if b["callback_data"] == data)
        calls = len(telegram.calls)
        telegram.press(BOT_TOKEN, CAPTAIN, message, data)
        said = toast(calls, expected)["params"]["text"]
        assert telegram.wait_for(lambda _: buttons(message) != before, 30), fail(f"el botón «{label}» no cambió")
        return f"[{label}] → «{said}»; quedan: " + " ".join(f"[{b['text']}]" for b in buttons(message))

    assert "Examen parcial" in fis_pending()
    submit = buttons(fis_alert)[1]["callback_data"]
    assert re.fullmatch(r"v1:s:\d+:ok", submit)
    steps = [press(fis_alert, submit, "cuenta como entregada")]
    assert [b["text"] for b in buttons(fis_alert)] == ["🎓 Consultar con Física I", "↩️ Aún no lo entregué"]
    assert "Examen parcial" not in fis_pending(), "lo que se entregó fuera del aula ya no está pendiente"
    exam_undo = buttons(fis_alert)[1]["callback_data"]
    assert exam_undo == submit.replace(":ok", ":no")
    steps.append(press(fis_alert, exam_undo, "vuelve a tus pendientes"))
    assert [b["text"] for b in buttons(fis_alert)] == ["🎓 Consultar con Física I", SUBMITTED]
    assert "Examen parcial" in fis_pending(), "deshacer lo devuelve a los pendientes"
    steps.append(press(fis_alert, submit, "cuenta como entregada"))
    assert "Examen parcial" not in fis_pending()
    pendientes_md += ["## «✅ Ya lo entregué» bajo el recordatorio del examen de Física\n",
                      f"```\n{plain(fis_alert['text'])}\n```\n",
                      "El capitán pulsa «✅ Ya lo entregué», después «↩️ Aún no lo entregué» y otra vez «✅ Ya lo "
                      "entregué»:\n", "```\n" + "\n".join(steps) + "\n```\n"]

    cards, replies = {}, {}
    for trigger in TODOS:
        mark = len(telegram.messages)
        telegram.send_text(BOT_TOKEN, CAPTAIN, f"anota: {trigger}")
        refused = "lunes" in trigger
        replies[trigger] = wait_msg("vinci_bot", mark, "Esa fecha ya pasó" if refused else "📌 Anotado:")
        card = [m for m in telegram.messages[mark:] if m["bot"] == "vinci_bot" and "Anotado en tu lista" in m["text"]]
        assert len(card) == (0 if refused else 1), card
        cards[trigger] = card[0] if card else None
    rows = todo_rows()
    fis_name, calc_name = team()["FISG1002"]["nombre"], team()["MATG1049"]["nombre"]
    assert [(r["text"], r["subject"], r["due_at"], r["all_day"], r["done_at"]) for r in rows] == [
        ("Estudiar cap. 3", fis_name, "2026-10-03T04:59:00Z", 1, None),
        ("Llevar el certificado de matrícula a secretaría", None, "2026-09-30T16:00:00Z", 0, None),
        ("Leer el paper que recomendó el profe", calc_name, None, 0, None)], rows
    study, errand, paper = (cards[t] for t in list(TODOS)[:3])
    assert f"{fis_name}: Estudiar cap. 3" in plain(study["text"]) and "Para: vie 2 oct" in plain(study["text"])
    assert "Te lo recuerdo 24 h y 3 h antes" in plain(study["text"])
    assert "Para: mié 30 sep, 11:00" in plain(errand["text"]) and "Sin fecha" in plain(paper["text"])
    for card, row in zip((study, errand, paper), rows):
        assert [(b["text"], b["callback_data"]) for b in buttons(card)] == [("✅ Hecho", f"v1:t:{row['id']}:ok")]
    pendientes_md.append("## «anota: …» en el chat de Vinci\n")
    for trigger in TODOS:
        card = cards[trigger]
        pendientes_md.append(f"El capitán: «anota: {trigger}»\n\n```\n"
                             + (plain(card["text"]) + "\n" + "".join(f"[{b['text']}]" for b in buttons(card)) + "\n\n"
                                if card else "") + f"Vinci: {readable(replies[trigger])}\n```\n")

    week = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "¿qué tengo esta semana?"), "vinci_bot", "Tu lista")
    for expected in ("Estudiar cap. 3 (vie 2 oct)",
                     "Llevar el certificado de matrícula a secretaría (mié 30 sep, 11:00)", "Leer el paper que recomendó el profe", "Informe de laboratorio 1"):
        assert expected in readable(week), f"falta «{expected}» en «¿qué tengo esta semana?»:\n{readable(week)}"
    assert "Examen parcial" not in readable(week), "lo marcado como entregado no sale en la semana"
    pendientes_md += ["## «¿qué tengo esta semana?»\n", f"```\n{readable(week)}\n```\n"]
    take("Ya lo entregué y la lista de pendientes")

    run([bot, "sondeo"], T_VINCI)
    reminded = take("Sondeo: recordatorio de un pendiente (sin modelo)")
    assert len(reminded) == 1, [m["text"][:60] for m in reminded]
    assert "Llevar el certificado de matrícula a secretaría" in reminded[0]["text"] and \
        "vence en 2 h" in reminded[0]["text"]
    assert [(b["text"], b["callback_data"]) for b in buttons(reminded[0])] == [("✅ Hecho", f"v1:t:{rows[1]['id']}:ok")]
    requests_before = len(llm.requests)
    run([bot, "resumen"], T_VINCI)
    daily = take("Resumen de las 7:00 con tu lista")
    assert len(llm.requests) == requests_before, "el recordatorio y el resumen no llaman al modelo"
    assert len(daily) == 1, [m["text"][:60] for m in daily]
    daily_text = plain(daily[0]["text"])
    for expected in ("Vence en menos de 24 h\n• hoy 11:00 — 📌 Llevar el certificado de matrícula a secretaría\n"
                     "• hoy 23:59 — Cálculo de una Variable: Taller 3: Derivadas\n",
                     "Sin peso conocido, por fecha\n• mañana 09:00 — Cálculo de una Variable: Lectura guiada de Cálculo\n"
                     f"• vie 2 oct — 📌 {fis_name}: Estudiar cap. 3\n",
                     "Sin esquema de notas, por fecha: Cálculo de una Variable, Física I. Dime cómo se evalúan",
                     f"📌 Tu lista, sin fecha (1)\n• {calc_name}: Leer el paper que recomendó el profe",
                     "Ya entregaste 1 de esta semana"):
        assert expected in daily_text, f"falta «{expected}» en el resumen:\n{daily_text}"
    assert "Después, lo que más pesa" not in daily_text, "sin esquema de notas no hay pesos que ordenar"
    assert "Examen parcial" not in daily_text, "el resumen no insiste con lo que ya entregó"
    done_buttons = [b for b in buttons(daily[0]) if b["callback_data"].startswith("v1:t:")]
    assert [b["callback_data"] for b in done_buttons] == [f"v1:t:{rows[i]['id']}:ok" for i in (1, 0, 2)]
    assert done_buttons[1]["text"] == "✅ Estudiar cap. 3" and done_buttons[0]["text"].endswith("…")
    pendientes_md += ["## Recordatorio del sondeo (2 h antes, sin modelo)\n",
                      f"```\n{plain(reminded[0]['text'])}\n[✅ Hecho]\n```\n",
                      "## Resumen de las 7:00 (sin el examen marcado como entregado)\n",
                      f"```\n{daily_text}\n" + "".join(f"[{b['text']}]" for b in buttons(daily[0])) + "\n```\n"]

    steps = [press(reminded[0], f"v1:t:{rows[1]['id']}:ok", "Hecho"),
             press(daily[0], done_buttons[1]["callback_data"], "Hecho")]
    assert [b["text"] for b in buttons(reminded[0])] == ["↩️ Deshacer: Llevar el certificado de ma…"]
    assert [b["text"] for b in buttons(daily[0]) if b["callback_data"].startswith("v1:t:")][:2] == \
        [done_buttons[0]["text"], "↩️ Deshacer: Estudiar cap. 3"], "solo cambia el botón pulsado"
    steps.append(press(daily[0], f"v1:t:{rows[0]['id']}:no", "vuelve a tu lista"))
    assert [b["text"] for b in buttons(daily[0]) if b["callback_data"].startswith("v1:t:")][1] == \
        "✅ Estudiar cap. 3", "deshacer en el resumen devuelve el botón con su pendiente"
    steps.append(press(daily[0], done_buttons[1]["callback_data"], "Hecho"))
    assert [bool(r["done_at"]) for r in todo_rows()] == [True, True, False]
    run([bot, "sondeo"], T_VINCI)
    assert take("Sondeo: nada que recordar") == []
    pendientes_md += ["## El capitán pulsa «✅ Hecho» en el recordatorio y en el resumen\n",
                      "```\n" + "\n".join(steps) + "\n```\n"]
    report.append("«✅ Ya lo entregué»: cada recordatorio de una entrega lo trae; al pulsarlo en el del examen de "
                  "Física (en papel) dejó de estar pendiente para `aula tareas`, «¿qué tengo esta semana?» y el "
                  "resumen de las 7:00, y el botón pasó a «↩️ Aún no lo entregué», que lo deshace")
    report.append("Lista de pendientes: «anota: …» en el chat de Vinci guardó cada pendiente con su materia y su fecha "
                  "(«el viernes» → vie 2 oct; una fecha pasada se rechaza) y mostró su tarjeta con «✅ Hecho»; salió en "
                  "«¿qué tengo esta semana?» y en el resumen de las 7:00; el sondeo mandó su recordatorio 2 h antes, "
                  "sin llamar al modelo; «✅ Hecho» en el recordatorio y en el resumen lo cerró y ya no se recordó más")
    take("Pendientes cerrados")

    # 7e3. The grade calculator. Cálculo's bot reads its syllabus and shows the scheme, asking what the syllabus
    # cannot say (how the first partial goes without its exam, El Niño); the captain tells it and saves it with
    # «Guardar esquema» (a discarded and a superseded card save nothing). Vinci says it does not know Física's
    # scheme until the captain tells it. Every figure comes from the tool; the model only shows it.
    notas_md = ["# Calculadora de notas\n"]

    def scheme_rows() -> dict:
        conn = sqlite3.connect(data_dir / "espol.db")
        conn.row_factory = sqlite3.Row
        try:
            return {r["subject"]: json.loads(r["scheme"]) for r in conn.execute("SELECT * FROM grading_schemes")}
        finally:
            conn.close()

    def keys(message: dict) -> dict:
        return {b["text"]: b["callback_data"] for b in buttons(message)}

    def show_card(title: str, card: dict, said: dict) -> None:
        notas_md.extend([f"## {title}\n", f"```\n{plain(card['text'])}\n"
                         + "".join(f"[{b['text']}]" for b in buttons(card)) + f"\n\n{readable(said)}\n```\n"])

    def show_turn(title: str, asked: str, said: dict) -> None:
        notas_md.extend([f"## {title}\n", f"El capitán: «{asked}»\n", f"```\n{readable(said)}\n```\n"])

    from espol_bot import grades
    mark = len(telegram.messages)
    telegram.send_text(MATG, CAPTAIN, "¿cómo voy en la materia?")
    card1 = wait_msg("vinci_calculo_bot", mark, "Así entiendo que se evalúa Cálculo de una Variable")
    said = wait_msg("vinci_calculo_bot", mark, "Te mostré cómo entiendo que se evalúa")
    for expected in ("Para aprobar: 60/100", "• Curso: 100 % de la nota",
                     "– Examen del primer parcial: 35 % (todavía nada del aula)",
                     "– Deberes y lecciones: 30 % (del aula: Lección 1: Límites, Deber 2: Continuidad, Taller 3: "
                     "Derivadas, Práctica 4: Regla de la cadena)", "⚠️ No lo pude confirmar",
                     "¿Cómo se reemplaza el examen del primer parcial, que este semestre no se toma por El Niño?",
                     "Fuente: Sílabo MATG1049 2026-2T.pdf, pág. 1 (J. EVALUACIÓN)"):
        assert expected in plain(card1["text"]), f"falta «{expected}» en la tarjeta del esquema:\n{plain(card1['text'])}"
    assert list(keys(card1)) == ["✅ Guardar esquema", "✏️ Corregir"]
    save1 = keys(card1)["✅ Guardar esquema"]
    assert "El Niño" in readable(said), "el bot pregunta lo que el sílabo no dice"
    assert scheme_rows() == {}, "proponer no guarda"
    show_card("1. «¿Cómo voy en la materia?» al bot de Cálculo: no hay esquema; lee el sílabo y lo propone", card1, said)
    fixed = turn(lambda: telegram.press(MATG, CAPTAIN, card1, keys(card1)["✏️ Corregir"]), "vinci_calculo_bot",
                 "no lo guardé")
    assert scheme_rows() == {}
    notas_md.extend(["## 2. El capitán pulsa «Corregir»\n", f"```\n{plain(fixed['text'])}\n```\n"])
    told = "no hay examen en el primer parcial por El Niño: lo reemplaza una lección que vale lo mismo"
    mark = len(telegram.messages)
    telegram.send_text(MATG, CAPTAIN, told)
    card2 = wait_msg("vinci_calculo_bot", mark, "Así entiendo que se evalúa Cálculo de una Variable")
    said = wait_msg("vinci_calculo_bot", mark, "Te mostré cómo entiendo que se evalúa")
    for expected in ("↳ Sin examen en el primer parcial por El Niño: lo reemplaza una lección que vale lo mismo.",
                     f"– {CALC_LESSON}: 35 % (todavía nada del aula)", "Me lo dijo el estudiante el 30 sep"):
        assert expected in plain(card2["text"]), f"falta «{expected}» en la tarjeta corregida:\n{plain(card2['text'])}"
    assert "No lo pude confirmar" not in plain(card2["text"])
    show_card(f"3. «{told}»: el bot propone el esquema corregido", card2, said)
    calls = len(telegram.calls)
    telegram.press(MATG, CAPTAIN, card1, save1)
    toast(calls, "Ese esquema ya fue descartado")
    assert scheme_rows() == {}, "una tarjeta descartada no se puede guardar"
    saved = turn(lambda: telegram.press(MATG, CAPTAIN, card2, keys(card2)["✅ Guardar esquema"]), "vinci_calculo_bot",
                 "Guardé cómo se evalúa Cálculo de una Variable")
    assert scheme_rows() == {"MATG1049": grades.validate(CALC_SCHEME)}
    for expected in ("Llevas 4,8 de 6 puntos calificados (promedio 80 %). Falta calificar 94 de 100.",
                     "Para aprobar necesitas un promedio de 58,7 % en lo que falta (como máximo puedes sacar 98,8).",
                     "– Deberes y lecciones (30 %): 80 % en el 20 % calificado · Lección 1: Límites 8/10",
                     f"– {CALC_LESSON} (35 %): sin notas todavía"):
        assert expected in plain(saved["text"]), f"falta «{expected}» al guardar:\n{plain(saved['text'])}"
    notas_md.extend(["## 4. «Guardar esquema» en la tarjeta descartada: «Ese esquema ya fue descartado.» y no se "
                     "guarda. El capitán pulsa «Guardar esquema» en la corregida\n", f"```\n{plain(saved['text'])}\n```\n"])
    asked = "¿y si saco 70 en la lección del primer parcial?"
    what_if = turn(lambda: telegram.send_text(MATG, CAPTAIN, asked), "vinci_calculo_bot", "cómo vas")
    assert "Falta calificar 94 de 100." in readable(what_if), readable(what_if)
    assert "Con lo que supusiste en 35 de esos puntos, sumarías 24,5; quedan 59 sin suponer." in readable(what_if)
    assert "Para aprobar necesitas un promedio de 52 % en lo que falta" in readable(what_if), readable(what_if)
    show_turn("5. Una nota supuesta (no se guarda)", asked, what_if)
    asked = "saqué 16/20 en la lección del primer parcial"
    recorded = turn(lambda: telegram.send_text(MATG, CAPTAIN, asked), "vinci_calculo_bot", "cómo vas")
    for expected in ("Llevas 32,8 de 41 puntos calificados (promedio 80 %). Falta calificar 59 de 100.",
                     "Para aprobar necesitas un promedio de 46,1 % en lo que falta",
                     f"– {CALC_LESSON} (35 %): 80 % en el 100 % calificado · Lección del primer parcial 16/20 (me lo dijiste)"):
        assert expected in readable(recorded), f"falta «{expected}» tras anotar la nota:\n{readable(recorded)}"
    show_turn("6. Una nota que no está en el aula, anotada", asked, recorded)

    asked = "¿cómo voy en notas?"
    overview = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, asked), "vinci_bot", "cómo vas")
    assert "Para aprobar necesitas un promedio de 46,1 % en lo que falta" in readable(overview)
    assert f"Todavía no sé cómo se evalúa {fis_name}" in readable(overview), "sin esquema, Vinci lo dice: no adivina"
    show_turn("7. Vinci, todas las materias: Física todavía no tiene esquema", asked, overview)
    told = ("en Física no hay examen en el primer parcial por El Niño: todo el parcial son deberes y laboratorio, "
            "mitad y mitad; en el segundo, examen 60, laboratorio 20 y deberes 20")
    mark = len(telegram.messages)
    telegram.send_text(BOT_TOKEN, CAPTAIN, told)
    fis_card = wait_msg("vinci_bot", mark, f"Así entiendo que se evalúa {fis_name}")
    said = wait_msg("vinci_bot", mark, "Te mostré cómo entiendo que se evalúa")
    for expected in ("• Primer parcial: 50 % de la nota", "↳ Sin examen por El Niño: todo el parcial son deberes y laboratorio.",
                     "– Deberes: 50 % (del aula: Taller 2: Movimiento parabólico, Tarea 1: Vectores)",
                     "– Examen: 60 % (del aula: Examen parcial)"):
        assert expected in plain(fis_card["text"]), f"falta «{expected}» en la tarjeta de Física:\n{plain(fis_card['text'])}"
    show_card(f"8. «{told}» a Vinci", fis_card, said)
    saved = turn(lambda: telegram.press(BOT_TOKEN, CAPTAIN, fis_card, keys(fis_card)["✅ Guardar esquema"]), "vinci_bot",
                 f"Guardé cómo se evalúa {fis_name}")
    for expected in ("Llevas 11,3 de 12,5 puntos calificados (promedio 90 %).",
                     "Para aprobar necesitas un promedio de 55,7 % en lo que falta",
                     "• Primer parcial (50 % de la nota): 90 % en lo calificado"):
        assert expected in plain(saved["text"]), f"falta «{expected}» al guardar Física:\n{plain(saved['text'])}"
    assert set(scheme_rows()) == {"MATG1049", "FISG1002"}
    notas_md.extend(["## 9. El capitán pulsa «Guardar esquema»\n", f"```\n{plain(saved['text'])}\n```\n"])
    (artifact / "notas.md").write_text("\n".join(notas_md), encoding="utf-8")
    report.append("Calculadora de notas: sin esquema, el bot de Cálculo leyó su sílabo y le mostró los pesos en una "
                  "tarjeta, preguntando lo que el sílabo no dice (el primer parcial sin examen por El Niño); con lo que "
                  "le dijo el capitán propuso otra, y solo «✅ Guardar esquema» la guardó (ni la descartada ni proponer "
                  "guardan). Las cuentas son del código: 4,8 de 6 puntos (80 %), 58,7 % para aprobar; con una nota "
                  "supuesta, 52 %; con la lección anotada, 46,1 %. Vinci dijo que no sabía cómo se evalúa Física hasta "
                  "que el capitán se lo contó y lo guardó (90 % en lo calificado, 55,7 % para aprobar)")
    take("Calculadora de notas")

    # 7e4. With both schemes saved, the 7:00 summary orders what is pending by what it counts toward the grade:
    # what is due within 24 h first, by date; then the heaviest; then, by date, what has no known weight. A new
    # Física homework due before the lab report comes after it, as it counts less. «¿Qué tengo esta semana?»
    # (Vinci's `semana`) follows the same order. Weights are the calculator's; nothing calls the model to rank.
    canvas.state = "state3"
    conn = sqlite3.connect(data_dir / "espol.db")
    try:  # another morning's summary within the same test day
        conn.execute("DELETE FROM meta WHERE key = 'bot_last_summary'")
        conn.commit()
    finally:
        conn.close()
    requests_before = len(llm.requests)
    run([bot, "resumen"], T_VINCI)
    ranked = take("Resumen de las 7:00 con los pesos de la calculadora")
    assert len(llm.requests) == requests_before, "el resumen ordena sin llamar al modelo"
    assert any("Tarea 3: Dinámica" in m["text"] and "Nueva tarea" in m["text"] for m in ranked), \
        [m["text"][:60] for m in ranked]
    ranked_text = plain(next(m["text"] for m in ranked if "Resumen de tu semana" in m["text"]))
    expected_order = ("Por entregar (5)\nVence en menos de 24 h\n"
                      "• hoy 23:59 — Cálculo de una Variable: Taller 3: Derivadas · vale 12 % de tu nota\n"
                      "• mañana 07:00 — Cálculo de una Variable (práctico): Práctica 4: Regla de la cadena · vale 6 % de tu nota\n"
                      "Después, lo que más pesa en tu nota\n"
                      "• vie 2 oct, 23:59 — Física I: Informe de laboratorio 1 · vale 25 % de tu nota\n"
                      "• vie 2 oct, 12:00 — Física I: Tarea 3: Dinámica · vale 8,3 % de tu nota\n"
                      "Sin peso conocido, por fecha\n"
                      "• mañana 09:00 — Cálculo de una Variable: Lectura guiada de Cálculo · no sé a qué parte de la nota va\n\n"
                      "Atrasadas sin entregar (1)\n"
                      "• Física I: Taller 2: Movimiento parabólico (venció mar 29 sep, 23:00) · vale 8,3 % de tu nota")
    assert expected_order in ranked_text, f"el resumen no quedó en orden:\n{ranked_text}"
    assert "Sin esquema de notas" not in ranked_text
    week = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "¿qué tengo esta semana?"), "vinci_bot", "Tu lista")
    fis, calc = "FÍSICA I - II PAO 2026", "CÁLCULO DE UNA VARIABLE - II PAO 2026"
    lines = [line for line in readable(week).splitlines() if line.startswith("- ")]
    assert lines[:6] == [
        f"- Taller 2: Movimiento parabólico ({fis}) · vale 8,3 % de tu nota",
        f"- Taller 3: Derivadas ({calc}) · vale 12 % de tu nota",
        f"- Práctica 4: Regla de la cadena ({calc} Práctico) · vale 6 % de tu nota",
        f"- Informe de laboratorio 1 ({fis}) · vale 25 % de tu nota",
        f"- Tarea 3: Dinámica ({fis}) · vale 8,3 % de tu nota",
        f"- Lectura guiada de Cálculo ({calc}) · no sé a qué parte de la nota va"], readable(week)
    (artifact / "prioridad.md").write_text("\n".join([
        "# Prioridad de las entregas\n",
        "## Resumen de las 7:00 sin esquemas de notas: lo urgente por fecha y el resto por fecha, sin pesos\n",
        f"```\n{daily_text}\n```\n",
        "## Con los esquemas de Cálculo y Física guardados (y una tarea nueva de Física)\n",
        f"```\n{ranked_text}\n```\n",
        "## «¿qué tengo esta semana?»: `semana` trae el mismo orden y el peso de cada una\n",
        f"```\n{readable(week)}\n```\n"]), encoding="utf-8")
    report.append("Prioridad de las entregas: el resumen de las 7:00 (sin modelo) puso primero lo que vence en 24 h, "
                  "por fecha; después lo que más pesa según la calculadora (el informe de Física, 25 %, antes que la "
                  "tarea 3, 8,3 %, que vence antes) y al final, por fecha, lo que no tiene peso conocido (sin esquema, "
                  "o que no calza con ninguna parte); «¿qué tengo esta semana?» trajo el mismo orden con cada peso")
    take("Prioridad de las entregas")

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
            data = stored.read_bytes()
            assert CANVAS_TOKEN.encode() not in data and NEW_CANVAS_TOKEN.encode() not in data, \
                "un archivo con secretos llegó al cuaderno"
    report.append("Cuaderno: el bot de Física guardó una nota de voz (audio y transcripción) y el de Cálculo una "
                  "foto de la pizarra y una duda; pedirle guardar un archivo del computador (secrets.env) fue "
                  "rechazado: «" + readable(attack)[:70].replace("\n", " ") + "…»")
    take("Cuaderno: foto, nota de voz y duda")

    # the course material: the aula's template images (silabos.png) are not material
    material = turn(lambda: telegram.send_text(MATG, CAPTAIN, "¿qué material del curso tienes?"), "vinci_calculo_bot",
                    "Material del curso")
    tool_results = [flatten(m.get("content")) for r in llm.requests for m in r.get("messages") or []
                    if m.get("role") == "tool"]
    assert any(isinstance(data := _json(t), dict) and "material" in data for t in tool_results), \
        "el bot no listó el material"
    assert not any("silabos.png" in t for t in tool_results), "la imagen del aula llegó al modelo como material"
    assert "Capítulo 3 - Derivadas.pdf" in readable(material) and "1 archivo(s) más" in readable(material)
    assert "silabos.png" not in readable(material)
    report.append("Material del curso: el bot de Cálculo listó solo lo que puede leer (el PDF del capítulo 3 y el "
                  "sílabo en PDF); la imagen silabos.png de la página del aula no llegó al modelo como material, "
                  "solo una nota de que hay 1 archivo más que no es material del curso")
    take("Material del curso, sin las imágenes del aula")

    # 7f2. the material of each subject: catalog, main book, two languages, a scan, outside links
    def tool_result(match) -> dict:
        """The newest tool result the model got that `match` accepts."""
        for req in reversed(llm.requests):
            for m in reversed(req.get("messages") or []):
                if m.get("role") == "tool" and isinstance(data := _json(flatten(m.get("content"))), dict) and match(data):
                    return data
        return {}

    def db_rows(sql: str, *args) -> list[dict]:
        conn = sqlite3.connect(f"file:{data_dir / 'espol.db'}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, args)]
        finally:
            conn.close()

    def dump(title: str, data) -> None:
        material_md.append(f"## {title}\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=1)}\n```\n")

    calc_catalog = tool_result(lambda d: "material" in d and "libro_principal" in d)
    by_id = {f["id"]: f for f in calc_catalog.get("material", [])}
    assert calc_catalog["libro_principal"]["titulo"].startswith("Purcell"), calc_catalog.get("libro_principal")
    assert by_id[5002]["estado"] == "muy grande para bajar" and by_id[5002]["seccion"] == "ANTES de clase: lecturas"
    assert 5005 not in by_id and by_id[5001]["copias"] == 1, "la copia de 2025 se lista una vez, en el original"
    assert by_id[5010]["estado"] == by_id[5301]["estado"] == "leído" and by_id[5001]["estado"] == "leído"
    assert by_id[5006]["estado"] == "sin bajar" and by_id[5006]["origen"] == "Tarea «Taller 3: Derivadas»"
    assert by_id[5007]["origen"] == "Anuncio «Bienvenidos al curso»"
    links = {link["tipo"]: link for link in calc_catalog["enlaces"]}
    purcell_link = links["SharePoint de ESPOL"]
    assert purcell_link["acceso"] == "no se abre" and "pide tu cuenta de ESPOL" in purcell_link["motivo"], purcell_link
    assert links["video"]["acceso"] == "solo enlace" and links["video"]["motivo"].startswith("es un video")
    assert purcell_link["origen"] == "Programa del curso"
    assert links["archivo de Dropbox"]["acceso"] == "se puede abrir"
    web_links = [link for link in calc_catalog["enlaces"] if link["tipo"] == "página web"]
    assert {link["titulo"] for link in web_links} == {"Guía de optimización (página del profesor)",
                                                     "este applet de GeoGebra"}, web_links
    dump("`archivos` de Cálculo: el catálogo que ve su bot", calc_catalog)
    report.append("Catálogo del material (lo que recibe el bot de Cálculo): cada documento con su módulo, la sección "
                  "del módulo («ANTES de clase: lecturas»), su carpeta («Libros») y de dónde salió (una guía que solo "
                  "enlaza una tarea, el adjunto de un anuncio), la copia de 2025 del capítulo 3 una sola vez, el libro "
                  "de 250 MB como «muy grande para bajar», y los enlaces de fuera: el Purcell del «Programa del curso» "
                  "en SharePoint como «no se abre» (el sondeo lo intentó sin cuenta y pidió la de ESPOL), el video "
                  "como «solo enlace», el Dropbox y la página del profesor como «se puede abrir»; nada se bajó sin "
                  "pedirlo salvo los sílabos")

    purcell = (FILES / "purcell-calculo.pdf").read_bytes()
    turn(lambda: telegram.send_document(MATG, CAPTAIN, "purcell-calculo-9a-ed.pdf", purcell,
                                        caption="este es el libro principal de la materia, el Purcell"),
         "vinci_calculo_bot", "quedó en tu material como tu libro principal")
    sent = db_rows("SELECT * FROM files WHERE source = 'Lo mandó el estudiante'")
    assert len(sent) == 1 and sent[0]["index_status"] == "ok" and sent[0]["id"] < 0
    stored = db_rows("SELECT * FROM libros WHERE materia = 'MATG1049'")[0]
    assert json.loads(stored["archivos"]) == [sent[0]["id"]] and stored["pedido"], stored
    chain = turn(lambda: telegram.send_text(MATG, CAPTAIN, "explícame la regla de la cadena con tu libro"),
                 "vinci_calculo_bot", "Lo que dice tu material")
    hits = tool_result(lambda d: "resultados" in d)["resultados"]
    assert hits[0]["archivo"] == "purcell-calculo-9a-ed.pdf" and hits[0]["prioridad"] == "libro principal", hits[0]
    assert 5005 not in [h["archivo_id"] for h in hits], "la copia de 2025 no aparece junto al original"
    assert len({(h["archivo"], h["pagina"]) for h in hits}) == len(hits)
    dump("`buscar_material` en Cálculo: «regla de la cadena» (y «chain rule»)", hits)
    report.append("Libro principal de Cálculo: el sílabo en PDF (BÁSICA y COMPLEMENTARIA lado a lado) dice que es el "
                  "Purcell; en el aula solo está como enlace de SharePoint, que el sondeo intentó abrir sin cuenta "
                  "(SharePoint pidió la cuenta de ESPOL), así que su bot se lo pidió al capitán una vez, "
                  "desde su propio chat y sin el modelo, explicando cómo pasar un PDF de más de 20 MB (la carpeta "
                  "libros/MATG1049). El capitán le mandó el PDF, que quedó en su material como libro principal, y al "
                  "preguntar por la regla de la cadena el Purcell salió primero: «" + readable(chain)[:120] + "…»")

    guide = turn(lambda: telegram.send_text(MATG, CAPTAIN, "abre la guía de optimización del profesor"),
                 "vinci_calculo_bot", "quedó en tu material")
    assert [p for _, p in web.requests if p.startswith("/profesor/")] == ["/profesor/optimizacion.html"], web.requests
    opened = db_rows("SELECT f.*, l.url FROM links l JOIN files f ON f.id = l.file_id")
    assert len(opened) == 1 and opened[0]["index_status"] == "ok" and opened[0]["source"].startswith("Enlace «Guía")
    refused = turn(lambda: telegram.send_text(MATG, CAPTAIN, "ábreme el Purcell del SharePoint"), "vinci_calculo_bot",
                   "Ábrelo tú")
    assert "pide tu cuenta de ESPOL" in readable(refused) and "sharepoint.com" in readable(refused)
    report.append("Enlaces de fuera: el bot de Cálculo abrió la guía de optimización de la página pública del profesor "
                  "cuando se la pidieron (un GET sin token, solo esa página) y quedó leída en su material; el Purcell de "
                  "SharePoint, que solo abre con cuenta de ESPOL, lo rechazó con ese motivo: «"
                  + readable(refused)[:110].replace("\n", " ") + "…»")
    material_md += ["## Enlaces: la guía del profesor se abre, el SharePoint no\n",
                    f"```\n{readable(guide)}\n\n{readable(refused)}\n```\n"]

    told = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "el libro de Física es el Serway"), "vinci_bot",
                "Anotado")
    assert db_rows("SELECT titulo FROM libros WHERE materia = 'FISG1002'")[0]["titulo"] == "Serway"
    take("El material de Cálculo: catálogo, libro principal y enlaces")
    run([bot, "sondeo"], T_VINCI)
    asked = take("Sondeo: Física pide el libro que el capitán nombró")
    assert [m["bot"] for m in asked] == ["vinci_fisica_bot"], [(m["bot"], m["text"][:60]) for m in asked]
    fis_ask = plain(asked[0]["text"])
    assert "Me dijiste que es: Serway" in fis_ask and f"{data_dir}/libros/FISG1002" in fis_ask, fis_ask
    run([bot, "sondeo"], T_VINCI)
    assert take("Sondeo: sin el PDF todavía") == [], "el libro se pide una sola vez"
    shutil.copy(FILES / "serway-physics.pdf", data_dir / "libros" / "FISG1002" / "Serway - Physics for Scientists.pdf")
    run([bot, "sondeo"], T_VINCI)
    assert take("Sondeo: el PDF ya está en la carpeta") == []
    dropped = db_rows("SELECT * FROM files WHERE source = 'Carpeta libros'")
    assert len(dropped) == 1 and dropped[0]["index_status"] == "ok" and dropped[0]["language"] == "en", dropped
    assert Path(dropped[0]["local_path"]).parent == data_dir / "libros" / "FISG1002", "se lee donde lo puso"
    projectile = turn(lambda: telegram.send_text(FIS, CAPTAIN, "explícame el tiro parabólico y el alcance máximo"),
                      "vinci_fisica_bot", "Lo que dice tu material")
    fis_hits = tool_result(lambda d: "resultados" in d)["resultados"]
    assert fis_hits[0]["archivo"] == "Serway - Physics for Scientists.pdf" and fis_hits[0]["idioma"] == "en" \
        and fis_hits[0]["prioridad"] == "libro principal", fis_hits[0]
    assert "Semana 2 - Cinemática.pptx" in [h["archivo"] for h in fis_hits], "también encuentra lo que está en español"
    dump("`buscar_material` en Física: «tiro parabólico alcance máximo» y «projectile motion maximum range»", fis_hits)
    material_md += ["## Física: el libro que nombró el capitán, pedido una vez\n",
                    f"```\n{readable(told)}\n\n{fis_ask}\n```\n"]
    report.append("Libro principal de Física: el capitán le dijo a Vinci «el libro de Física es el Serway»; el bot de "
                  "Física se lo pidió una vez y el sondeo siguiente no insistió; el PDF que el capitán puso en "
                  "libros/FISG1002 (para los de más de 20 MB) se leyó ahí mismo en el sondeo siguiente, y una pregunta "
                  "en español encontró el Serway en inglés primero y las diapositivas en español: «"
                  + readable(projectile)[:110].replace("\n", " ") + "…»")

    # Each subject bot's ver_pagina is its own: Cálculo's shows Cálculo's PDF, Física's refuses it.
    calc_page = turn(lambda: telegram.send_text(MATG, CAPTAIN, "muéstrame la página 2 del capítulo 3 como imagen"),
                     "vinci_calculo_bot", "🖼️")
    assert "Página 2 de 3 de «Capítulo 3 - Derivadas.pdf»" in readable(calc_page), readable(calc_page)
    other = turn(lambda: telegram.send_text(FIS, CAPTAIN, "muéstrame la página 2 del capítulo 3 como imagen"),
                 "vinci_fisica_bot", "otra materia")
    scan = turn(lambda: telegram.send_text(FIS, CAPTAIN, "léeme la lectura de vectores que dejó el profe"),
                "vinci_fisica_bot", "escaneo")
    scanned = db_rows("SELECT * FROM files WHERE id = 5102")[0]
    assert scanned["index_status"] == "escaneado" and scanned["source"] == "Página «Lectura recomendada»", scanned
    images = [part["image_url"]["url"] for req in llm.requests for m in req.get("messages") or []
              if isinstance(m.get("content"), list) for part in m["content"]
              if isinstance(part, dict) and part.get("type") == "image_url"
              and str(part["image_url"].get("url", "")).startswith("data:image/jpeg;base64,")]
    assert len(images) >= 2, fail("las páginas no le llegaron al modelo como imagen")
    page = base64.b64decode(images[-1].split(",", 1)[1])
    assert page[:3] == b"\xff\xd8\xff" and len(page) > 10_000
    (artifact / "pagina-escaneada.jpg").write_bytes(page)
    material_md += ["## Física: una lectura escaneada, mirada como imagen\n",
                    f"```\n{readable(scan)}\n```\n", "La página que recibió el modelo (ver_pagina):\n",
                    "![página 1 de la lectura escaneada](pagina-escaneada.jpg)\n"]
    report.append("PDF escaneado: la lectura de vectores que enlaza una Página de Física se bajó cuando se la pidieron, "
                  "quedó marcada «escaneado» (sus páginas no tienen texto) y el bot la miró con ver_pagina: la página "
                  "le llegó al modelo como imagen JPEG (pagina-escaneada.jpg), no como una ruta. Cada bot ve solo sus "
                  "PDF: el de Cálculo mostró su capítulo 3 y el de Física se negó: «"
                  + readable(other)[:80].replace("\n", " ") + "…»")
    take("El material de Física: búsqueda en dos idiomas y una lectura escaneada")

    # 7f2b. OCR at indexing. Up to here tesseract looked missing, so the scan above stayed images, as before
    def ocr_calls() -> int:
        return sum("stdin" in line for line in ocr_log.read_text().splitlines()) if ocr_log.exists() else 0

    def waiting() -> int:
        return db_rows("SELECT COUNT(*) AS n FROM ocr_pages o WHERE text IS NULL AND EXISTS (SELECT 1 FROM files f"
                       " WHERE f.digest = o.digest AND f.local_path IS NOT NULL)")[0]["n"]

    scan_digest = db_rows("SELECT digest FROM files WHERE id = 5102")[0]["digest"]
    assert [(r["page"], r["text"]) for r in db_rows("SELECT page, text FROM ocr_pages WHERE digest = ? ORDER BY page",
                                                    scan_digest)] == [(1, None), (2, None)], "sus 2 páginas esperan OCR"
    fallback = tool_result(lambda d: d.get("archivo_id") == 5102 and "estado" in d)
    assert "ocr" not in fallback and "OCR" not in fallback["aviso"] and ocr_calls() == 0, fallback
    ocr_md = ["# OCR de los PDF escaneados: una vez, al indexar\n",
              "## Sin motor de OCR, como antes\n",
              "Con tesseract ausente, la lectura escaneada de Física quedó «escaneado» con sus 2 páginas esperando "
              "OCR, y su bot la miró como imagen. Lo que le devolvió `bajar_archivo`:\n",
              f"```json\n{json.dumps(fallback, ensure_ascii=False, indent=1)}\n```\n"]
    if real_tesseract:
        ocr_off.unlink()
        pending = waiting()
        run([bot, "sondeo"], T_VINCI)
        take("Sondeo con OCR")
        read = db_rows("SELECT page, text, confidence FROM ocr_pages WHERE digest = ? ORDER BY page", scan_digest)
        assert waiting() == 0 and ocr_calls() == pending, (pending, ocr_calls())
        assert "paralelogramo" in read[0]["text"] and "vector" in read[1]["text"], read
        found = turn(lambda: telegram.send_text(FIS, CAPTAIN, "¿dónde sale la regla del paralelogramo en mi material?"),
                     "vinci_fisica_bot", "Lo que dice tu material")
        hits = tool_result(lambda d: "resultados" in d)["resultados"]
        assert (hits[0]["archivo_id"], hits[0]["pagina"], hits[0].get("ocr")) == (5102, 1, True), hits[0]
        assert "(texto por OCR)" in readable(found)

        before = ocr_calls()
        copy = turn(lambda: telegram.send_document(FIS, CAPTAIN, "lectura-vectores.pdf",
                                                   (FILES / "lectura-vectores-escaneada.pdf").read_bytes(),
                                                   caption="agrega esta lectura al material"),
                    "vinci_fisica_bot", "quedó en tu material")
        again = tool_result(lambda d: d.get("estado") == "escaneado" and d.get("archivo_id", 0) < 0)
        after = ocr_calls()
        assert again["ocr"]["read"] == 2 and after == before, ("la misma lectura no se vuelve a leer", again)
        assert "paralelogramo" in readable(copy), readable(copy)

        sheet = turn(lambda: telegram.send_document(MATG, CAPTAIN, "ejercicios-derivadas.pdf",
                                                    (FILES / "ejercicios-derivadas-escaneados.pdf").read_bytes(),
                                                    caption="agrega estos ejercicios escaneados al material"),
                     "vinci_calculo_bot", "quedó en tu material")
        added = tool_result(lambda d: d.get("estado") == "escaneado" and d.get("archivo_id", 0) < 0)
        page = tool_result(lambda d: d.get("archivo_id") == added["archivo_id"] and "contenido" in d)["contenido"][0]
        assert added["ocr"]["read"] == 1 and ocr_calls() == before + 1, added
        assert page.get("ocr") and "Ejercicio 4" in page["texto"] and "OCR" in added["aviso"], (page, added)
        engine = next(line for line in ocr_log.read_text().splitlines() if "stdin" in line).split(" -l ")[1].split()[0]
        ocr_md += ["## Con tesseract: el sondeo lee lo que esperaba\n",
                   f"El sondeo siguiente leyó con OCR las {pending} página(s) que esperaban (idiomas: {engine}). "
                   "Lo que salió de la lectura de vectores (la fórmula sale mal: para eso sigue ver_pagina):\n",
                   *[f"- página {r['page']} (confianza {r['confidence']}):\n\n```\n{r['text']}\n```\n" for r in read],
                   "## La búsqueda la encuentra\n", f"```\n{readable(found)}\n```\n",
                   "## La misma lectura otra vez: cero OCR\n",
                   f"El capitán le mandó a Física el mismo PDF: llamadas a tesseract antes {before}, después "
                   f"{after}; su texto salió del OCR ya hecho.\n", f"```\n{readable(copy)}\n```\n",
                   "## Unos ejercicios escaneados nuevos: OCR al agregarlos\n",
                   "Una llamada más a tesseract, dentro de `agregar_material`; el bot ya tiene su texto:\n",
                   f"```json\n{json.dumps(added, ensure_ascii=False, indent=1)}\n```\n", f"```\n{readable(sheet)}\n```\n"]
        report.append(f"OCR al indexar: sin tesseract la lectura escaneada de Física quedó como antes (imágenes para "
                      f"ver_pagina, 2 páginas en espera); con tesseract, el sondeo siguiente leyó las {pending} "
                      "página(s) que esperaban y la búsqueda «regla del paralelogramo» la encontró (marcada `ocr`); "
                      "el mismo PDF mandado otra vez no llamó a tesseract (OCR guardado por el contenido del archivo), "
                      "y unos ejercicios escaneados nuevos se leyeron al agregarlos (1 llamada) (ocr.md)")
    else:
        run([bot, "sondeo"], T_VINCI)
        take("Sondeo sin OCR")
        assert waiting() >= 2, "sin motor de OCR, las páginas siguen esperando"
        ocr_md.append("tesseract no está instalado en esta máquina: se probó solo que todo sigue como antes.\n")
        report.append("OCR al indexar: tesseract no está instalado aquí; la lectura escaneada siguió como antes "
                      "(imágenes para ver_pagina) y sus páginas quedaron esperando un motor de OCR")
    (artifact / "ocr.md").write_text(normalize("\n".join(ocr_md)), encoding="utf-8")
    take("OCR de los escaneos")

    # 7f3. Outside links open without a login: the captain's case, an announcement that is only a Google Doc link;
    # a private Doc an assignment links refused with its reason and not asked for again; a Drive guide Vinci reads
    def asked(fragment: str) -> list[str]:
        return [p for _, p in web.requests if fragment in p]

    def listed(match) -> list:
        """The newest list result (anuncios) the model got that `match` accepts."""
        for req in reversed(llm.requests):
            for m in reversed(req.get("messages") or []):
                if m.get("role") == "tool" and isinstance(data := _json(flatten(m.get("content"))), list) and match(data):
                    return data
        return []

    policies = turn(lambda: telegram.send_text(FIS, CAPTAIN, "¿qué dice el documento de políticas del curso del anuncio?"),
                    "vinci_fisica_bot", "📄")
    assert "la asistencia mínima para aprobar es del 70 %" in readable(policies), readable(policies)
    news = listed(lambda d: any("políticas" in a.get("titulo", "") for a in d))
    announcement = next(a for a in news if "políticas" in a["titulo"])
    assert announcement["texto"].startswith("https://docs.google.com/document/d/"), "el anuncio es solo el enlace"
    assert [(link["tipo"], link["acceso"]) for link in announcement["enlaces"]] == [("Google Docs", "se puede abrir")]
    assert asked(PUBLIC_DOC) == [f"/document/d/{PUBLIC_DOC}/export?format=pdf", f"/export/e2e/{PUBLIC_DOC}"], \
        "el Google Doc se pide como PDF, siguiendo la redirección de Google"
    doc = db_rows("SELECT f.* FROM links l JOIN files f ON f.id = l.file_id WHERE l.url LIKE ?", f"%{PUBLIC_DOC}%")
    assert len(doc) == 1 and doc[0]["display_name"] == "Políticas del curso - Física I.pdf" and doc[0]["pages"] == 2 \
        and doc[0]["index_status"] == "ok" and doc[0]["id"] < 0, doc

    rubric = turn(lambda: telegram.send_text(FIS, CAPTAIN, "ábreme la rúbrica de la tarea de vectores"),
                  "vinci_fisica_bot", "⚠️")
    for expected in ("Google pide iniciar sesión", "cualquier persona con el enlace", f"{PRIVATE_DOC}/edit",
                     "descárgalo en PDF y pásamelo"):
        assert expected in readable(rubric), f"falta «{expected}» al negar la rúbrica:\n{readable(rubric)}"
    again = turn(lambda: telegram.send_text(FIS, CAPTAIN, "ábreme la rúbrica de la tarea de vectores"),
                 "vinci_fisica_bot", "lo intenté")
    assert asked(PRIVATE_DOC) == [f"/document/d/{PRIVATE_DOC}/export?format=pdf"], \
        "un enlace privado no se vuelve a pedir en cada pregunta"
    shared = turn(lambda: telegram.send_text(FIS, CAPTAIN, "ya la compartieron, abre la rúbrica de la tarea otra vez"),
                  "vinci_fisica_bot", "Google pide iniciar sesión")
    assert len(asked(PRIVATE_DOC)) == 2, "si el capitán dice que ya lo compartieron, se prueba otra vez"
    remembered = db_rows("SELECT problem FROM links WHERE url LIKE ?", f"%{PRIVATE_DOC}%")[0]["problem"]
    assert remembered.startswith("Google pide iniciar sesión"), remembered

    guide = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "¿qué dice la guía del laboratorio de física?"),
                 "vinci_bot", "📄")
    assert "riel de aire" in readable(guide) and "guía del laboratorio 1.pdf" in readable(guide), readable(guide)
    assert asked(DRIVE_FILE) == [f"/uc?export=download&id={DRIVE_FILE}", f"/download?id={DRIVE_FILE}&export=download",
                                 f"/download?id={DRIVE_FILE}&export=download&confirm=t&uuid=e2e-uuid"], \
        "el archivo de Drive se baja sin cuenta, pasando la página del antivirus de Drive"
    recap = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "¿qué dice el documento de políticas del anuncio de física?"),
                 "vinci_bot", "📄")
    assert "70 %" in readable(recap) and len(asked(PUBLIC_DOC)) == 2, "Vinci lee la copia que ya abrió el bot de Física"
    vinci_news = listed(lambda d: any("políticas" in a.get("titulo", "") for a in d))
    assert next(a for a in vinci_news if "políticas" in a["titulo"])["enlaces"][0]["acceso"] == "abierto"
    for (_, path), headers in zip(web.requests, web.headers, strict=True):
        sent = {key.lower() for key in headers}
        assert not sent & {"authorization", "cookie"} and "7~" not in json.dumps(headers), \
            f"{path} llevó credenciales: {headers}"
    dump("`anuncios` de Física: el anuncio que es solo un enlace de Google Docs, como lo ve su bot", announcement)
    replies = "\n\n".join(readable(m) for m in (policies, rubric, again, shared, guide, recap))
    replies = re.sub(r"lo intenté el [^;]+;", "lo intenté el <fecha>;", replies)  # the MCP server's own clock
    material_md += ["## Enlaces que se abren sin cuenta: Google Docs, Drive; uno privado se niega\n",
                    f"```\n{replies}\n```\n"]
    report.append("Enlaces sin cuenta (el caso del capitán): un anuncio de Física que es solo un enlace de Google Docs; "
                  "su bot vio el enlace en `anuncios`, lo pidió como PDF sin cuenta (siguiendo la redirección de Google) "
                  "y lo leyó como un PDF del aula: «" + readable(policies)[:90].replace("\n", " ") + "…». La rúbrica "
                  "que enlaza una tarea, un Google Doc privado (Google responde 401), la negó con el motivo y pidiendo "
                  "el PDF; al preguntar "
                  "otra vez no la volvió a pedir, y cuando el capitán dijo que ya la compartieron la probó de nuevo. "
                  "Vinci leyó la guía de laboratorio que una tarea enlaza en Drive (pasando la página del antivirus) y "
                  "el documento del anuncio (la copia que ya abrió el bot de Física). Ninguna de esas solicitudes llevó "
                  "token, cookie ni credencial, aunque cada sitio puso una cookie en el camino")
    take("Enlaces sin cuenta: Google Docs, Drive y uno privado")

    # 7f4. Verifiable citations: the tools hand out each page's citation and record what each bot was shown; an
    # answer's citations are checked against that record before it is sent (the plugin), and a question the material
    # does not cover is answered «No está en el material»
    citas_md = ["# Citas verificables: archivo, página y enlace del aula\n"]
    calc_url = f"{canvas.base}/courses/101/files/5001"
    for chat, user, who, ask in ((MATG, "vinci_calculo_bot", "El bot de Cálculo", "cítame el material sobre"),
                                 (BOT_TOKEN, "vinci_bot", "Vinci", "cítame el material de Cálculo sobre")):
        cited = turn(lambda: telegram.send_text(chat, CAPTAIN, f"{ask} la regla de la cadena"), user, "Según tu material")
        found = tool_result(lambda d: "resultados" in d and d["resultados"])["resultados"]
        assert all(h["cita"] == (f"📄 [{h['archivo']}, {h['unidad']} {h['pagina']}]({h['url']})" if h.get("url")
                                 else f"📄 {h['archivo']}, {h['unidad']} {h['pagina']}") for h in found), found
        chapter = next(h for h in found if h["archivo_id"] == 5001)
        assert chapter["cita"] == f"📄 [Capítulo 3 - Derivadas.pdf, página 2]({calc_url})", chapter
        assert chapter in found[:2] and all(h["cita"] in readable(cited) for h in found[:2]), readable(cited)
        assert "⚠️" not in readable(cited), "una cita que salió de las herramientas pasa tal cual"
        missing = turn(lambda: telegram.send_text(chat, CAPTAIN, f"{ask} la transformada de Laplace"), user,
                       "No está en el material")
        empty = tool_result(lambda d: "resultados" in d and not d["resultados"])
        assert empty["en_el_material"] is False and "«No está en el material»" in empty["nota"], empty
        assert readable(missing).startswith("No está en el material") and "📄" not in readable(missing)
        hits = [{k: h[k] for k in ("archivo", "pagina", "fragmento", "cita")} for h in found[:3]]
        citas_md += [f"## {who}: una respuesta con material\n",
                     f"El capitán: «{ask} la regla de la cadena». `buscar_material` devolvió (fragmento y cita):\n",
                     f"```json\n{json.dumps(hits, ensure_ascii=False, indent=1)}\n```\n",
                     f"Llegó a Telegram:\n\n```\n{readable(cited)}\n```\n",
                     f"## {who}: lo que el material no trae\n",
                     f"El capitán: «{ask} la transformada de Laplace». `buscar_material` devolvió:\n",
                     f"```json\n{json.dumps(empty, ensure_ascii=False, indent=1)}\n```\n",
                     f"Llegó a Telegram:\n\n```\n{readable(missing)}\n```\n"]
    shown = {(r["bot"], r["file_id"], r["page"]) for r in db_rows("SELECT * FROM shown_pages")}
    assert ("MATG1049", 5001, 2) in shown and ("vinci", 5001, 2) in shown, shown

    memory = turn(lambda: telegram.send_text(MATG, CAPTAIN, "¿en qué página está la regla de L'Hôpital?"),
                  "vinci_calculo_bot", "L'Hôpital")
    checked = readable(memory)
    assert "⚠️ «Capítulo 3 - Derivadas.pdf, página 9» (esa página no salió del material que leí" in checked, checked
    assert "⚠️ «Stewart - Cálculo de una variable.pdf, página 120» (ese archivo no está en el material" in checked
    assert f"📄 [Capítulo 3 - Derivadas.pdf, página 2]({calc_url})" in checked, checked
    assert "aulavirtual.espol.edu.ec" not in checked, "ningún enlace inventado llega al capitán"
    log = [line.split(": ", 1)[-1] for line in (data_dir / "bot.log").read_text(encoding="utf-8").splitlines()
           if ": citas MATG1049: " in line]
    assert [line.split(" «")[0] for line in log[-3:]] == [
        "citas MATG1049: página no leída", "citas MATG1049: archivo desconocido", "citas MATG1049: enlace corregido"], log
    mark = len(llm.requests)
    turn(lambda: telegram.send_text(MATG, CAPTAIN, "gracias"), "vinci_calculo_bot", "Hola")
    replayed = [flatten(m.get("content")) for req in llm.requests[mark:] for m in req.get("messages") or []
                if m.get("role") == "assistant" and "L'Hôpital" in flatten(m.get("content"))]
    assert replayed and all("página 9](" not in text and "⚠️" in text for text in replayed), \
        "la conversación guarda lo que se envió, no la cita inventada"
    citas_md += ["## Citas de memoria, sin herramientas en ese turno\n",
                 "El capitán: «¿en qué página está la regla de L'Hôpital?». El modelo contestó de memoria:\n",
                 f"```\n{FROM_MEMORY}\n```\n",
                 "Antes de enviarse, el plugin corrió `espol-bot citas`: el capítulo 3 tiene 3 páginas (la 9 no se la "
                 "mostró ninguna herramienta), el Stewart no está en el material, y la página 2 sí la leyó, pero con "
                 "otro enlace. Llegó a Telegram (y así quedó en la conversación):\n",
                 f"```\n{checked}\n```\n", "Lo que anotó `bot.log`:\n", "```\n" + "\n".join(log[-3:]) + "\n```\n"]
    (artifact / "citas.md").write_text(normalize("\n".join(citas_md)), encoding="utf-8")
    report.append("Citas verificables: `buscar_material` y `leer_archivo` traen la cita de cada página lista para "
                  "copiar (archivo, página o diapositiva y el enlace del aula) y guardan qué páginas vio cada bot. El "
                  "bot de Cálculo y Vinci citaron el capítulo 3 con su enlace; sobre la transformada de Laplace, que el "
                  "material no trae, la búsqueda dijo `en_el_material: false` y ambos contestaron «No está en el "
                  "material» antes del conocimiento general, sin cita. Un modelo que cita de memoria no llega así al "
                  "capitán: antes de enviarse, la página 9 que el capítulo no tiene y un libro que no está en el "
                  "material se cambiaron por un aviso, y el enlace inventado de la página 2 se corrigió al del aula")
    take("Citas verificables")

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
    assert all("ver_pagina" in tools_seen[b] for b in ("Cálculo de una Variable", "Física I")), tools_seen
    assert "mcp__vinci__libro_principal" in vinci_tools
    assert {"mcp__vinci__cuaderno", "mcp__vinci__entregar_a_materia", "mcp__vinci__proponer_horario",
            "mcp__vinci__proponer_equipo", "web_search"} <= vinci_tools
    assert all(t.startswith("mcp__vinci__") or t in VINCI_TOOLS_OK for t in vinci_tools), vinci_tools
    assert not {"mcp__vinci__anotar", "mcp__vinci__guardar_adjunto"} & vinci_tools
    for who, names in tools_seen.items():
        if who != "Vinci":
            assert all(t.startswith("mcp__materia__") or t in SUBJECT_TOOLS_OK for t in names), (who, names)
    everything = json.dumps(llm.requests, ensure_ascii=False)
    assert "very first message ever" in everything, "Hermes debía marcar el primer mensaje de cada bot"
    assert "build a short profile" not in everything, "ningún bot ofrece armar un perfil del estudiante"
    report.append("Vinci leyó el cuaderno de Cálculo (la foto y la duda), pero al intentar escribirlo o usar una "
                  f"terminal Hermes respondió que esas herramientas no existen: «{readable(shell)[:60]}…»; el "
                  "cuaderno no cambió y no se creó ningún archivo")
    report.append("Herramientas que Hermes le ofreció al modelo (ver hermes_herramientas.json): Vinci, solo las "
                  "suyas + búsqueda web, memoria, historial, preguntas y skills; los bots de materia, solo las de su "
                  "materia + memoria (sin web); todos con las skills de Hermes; ninguno con terminal, archivos ni código")
    report.append("El primer mensaje de cada bot trae solo la presentación de Hermes: ninguno le ofrece al estudiante "
                  "«armar un perfil tuyo» (onboarding.profile_build: off)")
    take("Vinci lee cuadernos, no los escribe, sin terminal")

    # 7g2. /quiz: a short quiz from the material as Telegram quiz polls, the score counted with no model
    def polls(user: str, mark: int) -> list[dict]:
        return [m for m in telegram.messages[mark:] if m["bot"] == user and m["method"] == "sendPoll"]

    def vote(token: str, poll: dict, option: int, user: int = CAPTAIN) -> None:
        consumed(token, telegram.answer_poll(token, user, poll["poll_id"], [option]))

    def right(poll: dict) -> int:
        return int(poll["correct_option_id"])

    def quiz_rows(code: str) -> list[dict]:
        conn = sqlite3.connect(f"file:{data_dir / 'cuadernos' / code / 'cuaderno.db'}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM quiz_questions ORDER BY quiz_id, position")]
        finally:
            conn.close()

    def quiz_block(title: str, messages: list[dict]) -> None:
        quiz_md.append(f"## {title}\n\n" + "\n\n".join(f"```\n{readable(m)}\n```" for m in messages) + "\n")

    # Cálculo, straight from its chat: a topic; a citation of a page it never read is refused first
    mark = len(telegram.messages)
    reply = turn(lambda: telegram.send_text(MATG, CAPTAIN, "/quiz regla de la cadena"), "vinci_calculo_bot", "Ahí van")
    calc_polls = polls("vinci_calculo_bot", mark)
    assert len(calc_polls) == 3, [readable(m) for m in calc_polls]
    assert all(p["type"] == "quiz" and p["is_anonymous"] is False and p["question"].startswith(f"{i}/3. ")
               for i, p in enumerate(calc_polls, 1)), calc_polls
    hits = tool_result(lambda d: "resultados" in d)["resultados"]
    cited = {f"📄 {h['archivo']}, {h.get('unidad') or 'página'} {h['pagina']}" for h in hits}
    assert all(p["explanation"].endswith(tuple(cited)) for p in calc_polls), \
        ([p["explanation"] for p in calc_polls], cited)
    assert [p["options"][right(p)]["text"] for p in calc_polls] == [
        "f'(g(x))·g'(x)", "2x·cos(x²)", "La pendiente de la tangente"], "la opción correcta es la que dijo el modelo"
    tool_texts = [flatten(m.get("content")) for r in llm.requests for m in r.get("messages") or []
                  if m.get("role") == "tool"]
    assert any("no tiene página 999 con texto" in t for t in tool_texts), "una cita a una página que no existe se rechaza"
    assert "f'(g(x))·g'(x)" not in readable(reply) and "2x·cos" not in readable(reply), "la respuesta no revela nada"
    before = len(telegram.messages)
    vote(MATG, calc_polls[0], right(calc_polls[0]), user=STRANGER)
    assert all(r["chosen"] is None for r in quiz_rows("MATG1049")), "el voto de un extraño no cuenta"
    vote(MATG, calc_polls[0], right(calc_polls[0]))
    vote(MATG, calc_polls[1], (right(calc_polls[1]) + 1) % len(calc_polls[1]["options"]))
    time.sleep(1)
    assert len(telegram.messages) == before, "no hay puntaje hasta responder la última pregunta"
    mark = len(telegram.messages)
    vote(MATG, calc_polls[2], right(calc_polls[2]))
    score = wait_msg("vinci_calculo_bot", mark, "Quiz: regla de la cadena")
    assert "2 de 3" in readable(score) and "❌ 2." in readable(score) and "era «2x·cos(x²)»" in readable(score), \
        readable(score)
    assert score["parse_mode"] == "HTML" and readable(score).count("📄 ") == 3, "cada pregunta con su fuente"
    assert '<a href="' in readable(score), "la fuente que está en el aula va con su enlace (el PDF que mandó, sin él)"
    assert "Anoté lo que fallaste" in readable(score)
    vote(MATG, calc_polls[2], right(calc_polls[2]))
    time.sleep(1)
    assert len(telegram.messages) == mark + 1, "un voto repetido no manda otro puntaje"
    weak = [e for e in entries(data_dir, "MATG1049") if e["tipo"] == "tema_debil" and e["origen"] == "quiz"]
    assert len(weak) == 1 and "Quiz «regla de la cadena»" in weak[0]["texto"] and "sen(x²)" in weak[0]["texto"], weak
    quiz_block("Cálculo: «/quiz regla de la cadena» (las 3 preguntas y la respuesta del bot)", [*calc_polls, reply])
    quiz_block("Cálculo: el puntaje al responder la última (sin el modelo; la 2 a propósito mal)", [score])

    # Física: /quiz with no topic, then the material the captain sends right after it
    ask = turn(lambda: telegram.send_text(FIS, CAPTAIN, "/quiz"), "vinci_fisica_bot", "De qué tema")
    mark = len(telegram.messages)
    lab = (FILES / "guia-laboratorio-1.pdf").read_bytes()
    lab_reply = turn(lambda: telegram.send_document(FIS, CAPTAIN, "guia-laboratorio-1.pdf", lab,
                                                    caption="hazme el quiz con esto"), "vinci_fisica_bot", "Ahí van")
    fis_polls = polls("vinci_fisica_bot", mark)
    assert len(fis_polls) == 2 and all(", página 1" in p["explanation"] for p in fis_polls), fis_polls
    added = tool_result(lambda d: "archivo_id" in d and "estado" in d and "laboratorio" in str(d.get("archivo")).lower())
    assert added and added["estado"] == "leído", "el PDF que mandó quedó en el material antes del quiz"
    for poll in fis_polls:
        vote(FIS, poll, right(poll))
    perfect = wait_msg("vinci_fisica_bot", mark, "2 de 2, ¡perfecto!")
    assert not any(e["origen"] == "quiz" for e in entries(data_dir, "FISG1002")), "sin fallas, nada al cuaderno"
    quiz_block("Física: «/quiz» sin tema y luego el PDF que manda el capitán", [ask, *fis_polls, lab_reply, perfect])

    # Vinci: /quiz in its chat goes to the subject bot, which quizzes from its material and its notebook
    mark = len(telegram.messages)
    confirm = turn(lambda: telegram.send_text(BOT_TOKEN, CAPTAIN, "/quiz derivadas de cálculo"), "vinci_bot",
                   "se lo pasé a")
    handed = wait_msg("vinci_calculo_bot", mark, "De parte de Vinci", timeout=200)
    handed_polls = polls("vinci_calculo_bot", mark)
    assert len(handed_polls) == 2, [readable(m) for m in handed_polls]
    assert "tu cuaderno, foto #" in handed_polls[0]["explanation"], "la foto de la pizarra de su cuaderno, citada"
    assert re.search(r"📄 .+, (página|diapositiva) \d+$", handed_polls[1]["explanation"]), handed_polls[1]
    assert any(QUIZ_HANDOFF.search(t) for t in cron_tasks("entrega_de_vinci")), "el quiz llegó como entrega de Vinci"
    quiz_block("Vinci: «/quiz derivadas de cálculo» se lo pasa al bot de Cálculo", [confirm, *handed_polls, handed])
    report.append("/quiz: el bot de Cálculo mandó 3 encuestas tipo quiz de Telegram sobre la regla de la cadena, citando "
                  "archivo y página del material (una cita a una página que no leyó fue rechazada antes); al responder "
                  "la última le llegó el puntaje (2 de 3) con la fuente de cada pregunta, sin el modelo, y lo que falló "
                  "quedó como tema débil; el voto de un extraño y uno repetido no cuentan. Física, tras «/quiz» sin "
                  "tema, armó el quiz con el PDF que le mandó el capitán; y Vinci pasó «/quiz derivadas de cálculo» al "
                  "bot de Cálculo, que citó la foto de la pizarra de su cuaderno")
    take("/quiz: quiz cortos con el material")

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
    sessions.append(time.time())
    gate_after = run([bot, "agenda", "--curso", "MATG1049"], T_VINCI).stdout.strip()
    gate_fis = run([bot, "agenda", "--curso", "FISG1002"], T_VINCI).stdout.strip()
    assert gate_after == SKIP and gate_fis == SKIP
    monday = run([bot, "agenda", "--curso", "MATG1049"], T_MONDAY).stdout
    for expected in ("Clase: hoy lunes 5 oct, 09:00–12:00 en A105 (empieza en 30 min)",
                     "con este único brief para todos: 09:00–11:00 en A105 · paralelo 5; 11:00–12:00 en LAB 11C · paralelo 105"):
        assert expected in monday, f"falta «{expected}» en el brief del lunes:\n{monday}"
    midclass = run([bot, "agenda", "--curso", "MATG1049"], T_MIDCLASS).stdout.strip()
    assert midclass == SKIP, f"a las 10:30, en pleno teórico, no toca el brief del práctico de las 11:00:\n{midclass}"
    briefs_md += ["## Lunes: teórico 09:00–11:00 y práctico 11:00–12:00 seguidos\n",
                  "A las 08:30, la agenda le pasa al bot un solo brief para los dos bloques:\n",
                  f"```\n{monday.strip()}\n```\n",
                  f"A las 10:30, en pleno teórico (30 min antes del práctico): `{midclass}`\n"]
    report.append("Bloques seguidos de una misma materia (el lunes, teórico 09:00–11:00 y práctico 11:00–12:00): un "
                  "solo brief a las 08:30 que cubre los dos; a las 10:30, en plena clase, ninguno")
    restart = datetime.now().astimezone()
    briefs_before, tasks_before = len(cron_tasks("brief_de_clase")), len(cron_tasks("entrega_de_vinci"))
    mark_calls, mark_msgs = len(telegram.calls), len(telegram.messages)
    telegram.send_text(BOT_TOKEN, CAPTAIN, "hola, ¿estás?")  # while the gateway is down
    sessions.append(time.time())
    gateway.start()
    polling({"vinci_bot", "vinci_calculo_bot"}, mark_calls)
    wait_msg("vinci_bot", mark_msgs, "¿En qué te ayudo?")
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
                  "cada minuto sin nada que hacer tampoco llama al modelo; y Vinci contestó el mensaje que le "
                  "llegó con el gateway apagado, en vez de descartarlo al arrancar")
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
    sessions.append(time.time())
    gaps = []  # seconds between back-to-back agenda runs of one bot while the same gateway served it
    for code in SUBJECT_TOKENS:
        starts = agenda_starts(code)
        for start, end in zip(sessions[::2], sessions[1::2]):
            served = [s for s in starts if start <= s.timestamp() <= end]
            gaps += [(b - a).total_seconds() for a, b in zip(served, served[1:])]
    assert gaps and max(gaps) < 90, f"la agenda de un bot de materia se saltó un minuto: {gaps}"
    report.append(f"La agenda de cada bot de materia corre cada minuto de verdad («* * * * * */30»): entre una corrida y "
                  f"la siguiente con el mismo gateway pasaron {', '.join(f'{g:.0f} s' for g in gaps)}, también después "
                  f"de un brief o una entrega que despertó al modelo; con «every 1m» Hermes la corría cada 2 min")

    for job_id in vinci_jobs.values():
        run([hermes, "-p", "vinci", "cron", "resume", job_id], T_VINCI)

    # 7j. The next morning, 2 h before Física's exam: marked as handed in, it gets no 3 h reminder; undone, it does
    run([bot, "sondeo"], T_EXAM)
    quiet = take("Sondeo · jue 1 oct 06:00, con el examen marcado como entregado")
    assert not [m for m in quiet if "Examen parcial" in readable(m)], [readable(m)[:60] for m in quiet]
    undone = json.loads(run([bot, "boton", exam_undo], T_EXAM).stdout)
    assert "vuelve a tus pendientes" in undone["aviso"], undone
    run([bot, "sondeo"], T_EXAM)
    loud = [m for m in take("Sondeo · jue 1 oct 06:00, tras «↩️ Aún no lo entregué»") if "Examen parcial" in readable(m)]
    assert len(loud) == 1 and "vence en 2 h" in loud[0]["text"] and SUBMITTED in [b["text"] for b in buttons(loud[0])]
    pendientes_md += ["## Al día siguiente, 2 h antes del examen\n",
                      "Marcado como entregado, el sondeo de las 06:00 no manda el recordatorio de 3 h. Tras "
                      f"«↩️ Aún no lo entregué» (aviso: «{undone['aviso']}»), el siguiente sondeo sí:\n",
                      f"```\n{plain(loud[0]['text'])}\n"
                      + "".join(f"[{b['text']}]" for b in buttons(loud[0])) + "\n```\n"]
    (artifact / "pendientes.md").write_text("\n".join(pendientes_md), encoding="utf-8")
    report.append("«Ya lo entregué» detiene de verdad los recordatorios: al día siguiente, 2 h antes del examen de "
                  "Física, el sondeo no mandó el de 3 h mientras estaba marcado; tras «↩️ Aún no lo entregué», sí")

    # 8. setup.sh with the team in place (idempotent), just as the aula virtual stops taking the token -------
    canvas.token = "7~otro-token-que-el-aula-si-acepta"
    third = run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_VINCI)
    canvas.token = NEW_CANVAS_TOKEN
    show("`./setup.sh --skip-deps` con el equipo armado (3ª vez), con el token de Canvas ya rechazado",
         third.stdout + third.stderr)
    for word in ("creado", "actualizado", "reanudado", "pausado", "instalados"):
        assert word not in third.stdout, f"«{word}» en la 3ª corrida de setup.sh:\n{third.stdout}"
    assert third.stdout.count("sin cambios") >= 6
    assert "✓ Canvas responde" not in third.stdout, "setup.sh no puede decir que Canvas responde si rechazó el token"
    assert "no es válido o expiró" in third.stderr and "No pude leer el aula virtual" in third.stderr, third.stderr
    report.append("setup.sh por tercera vez, con Vinci y los dos bots de materia: nada cambió; y como el aula virtual "
                  "ya rechazaba el token, dijo «⚠ No pude leer el aula virtual» en vez de «✓ Canvas responde»")
    take("setup.sh (3ª vez, mensaje de prueba)")

    # 9. the party: what reached the model, then the captain's own subjects -------------------------
    def soul_md(name: str) -> str:
        return (profiles / name / "SOUL.md").read_text(encoding="utf-8")

    def profile_calls(mark: int) -> list[tuple[str, str]]:
        return [(c["bot"], c["method"]) for c in telegram.calls[mark:]
                if c["method"] in ("getMyName", "setMyName", "setMyProfilePhoto")]

    def setup_again() -> subprocess.CompletedProcess:
        return run(["bash", str(REPO / "setup.sh"), "--skip-deps"], T_VINCI)

    vinci_systems = [" ".join(system_of(r).split()) for r in llm.requests if bot_of(r) == "Vinci"]
    calc_systems = [" ".join(system_of(r).split()) for r in llm.requests if bot_of(r) == "Cálculo de una Variable"]
    assert vinci_systems and all("buen compañero de estudio" in t and not [w for w in ROLEPLAY if w in t]
                                 for t in vinci_systems), "ningún turno de Vinci trae un personaje"
    assert calc_systems and all("como un compañero que se sabe la materia" in t for t in calc_systems)
    # skills.auto_load: Hermes drops it silently when the agent has no skills tool, so every SKILL line must be
    # in what the model got (a line SOUL.md repeats would prove nothing).
    def assert_skill_reached(who: str, profile_name: str, skill: str) -> None:
        lines = skill_check.skill_lines(
            (profiles / profile_name / "skills" / "vinci" / skill / "SKILL.md").read_text("utf-8"), soul_md(profile_name))
        assert len(lines) > 20, f"{who}: la skill no tiene líneas propias"
        for req in (r for r in llm.requests if bot_of(r) == who):
            # A chat has the skill in its system prompt; a cron agent run (no clarify tool) in its job prompt.
            source = system_of(req) if "clarify" in tools_of(req) else "\n".join(
                flatten(m.get("content")) for m in req["messages"])
            seen = " ".join(source.split())
            gone = [line for line in lines if " ".join(line.split()) not in seen]
            assert not gone, f"{who}: su skill no llegó al modelo ({len(gone)} líneas, p. ej. «{gone[0][:60]}»)"

    assert_skill_reached("Vinci", "vinci", "vinci")
    assert_skill_reached("Cálculo de una Variable", "vinci-matg1049", "vinci-materia")
    from aula_core.config import load_config
    from espol_bot import equipo, materias, messages
    core = load_config(Path(base_env["AULA_CONFIG"]))

    # 9a. Four of the captain's bots already exist: two still «Vinci · <materia>» from before PR #4, two with
    # the character name, photo and stamp PR #4 set. The update renames all four in place to their subject.
    existing = [materias.Subject(code=code, name=PARTY[code][0], state="activa", username=username)
                for code, (username, _) in EXISTING.items()]
    materias.save(core, materias.load(core) + existing + [materias.Subject(code="CCPG1055", name=PARTY["CCPG1055"][0])])
    with secrets.open("a", encoding="utf-8") as f:  # as Vinci stored them when it created those bots
        f.writelines(f"TELEGRAM_BOT_TOKEN_{s.code}={PARTY_TOKENS[s.code]}\n" for s in existing)
    for code, (username, old_name) in EXISTING.items():
        telegram.add_bot(PARTY_TOKENS[code], username, old_name)
        if not old_name.startswith("Vinci · "):  # what PR #4's setup left: the profile, the photo and the stamp
            profile, avatar = f"vinci-{code.lower()}", (AVATARS / PARTY[code][2]).read_bytes()
            run([hermes, "profile", "create", profile, "--no-skills", "--no-alias", "--description", old_name], T_VINCI)
            (profiles / profile / "SOUL.md").write_text(f"Tu personaje es **{old_name.split(' · ')[0]}**.\n")
            cfg_file = profiles / profile / "config.yaml"  # PR #4 set no summary trigger; a hand-set key must stay
            cfg = yaml.safe_load(cfg_file.read_text()) if cfg_file.exists() else None
            cfg = cfg if isinstance(cfg, dict) else {}
            cfg.setdefault("compression", {})["protect_last_n"] = 30
            cfg_file.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
            (profiles / profile / "telegram-profile.json").write_text(json.dumps(
                {"bot": PARTY_TOKENS[code].split(":")[0], "name": old_name,
                 "photo": hashlib.sha256(avatar).hexdigest()}, ensure_ascii=False) + "\n", encoding="utf-8")
            telegram.profile_photos[username] = [avatar]
    # As the previous setup.sh left Vinci and the team: interval schedules, and Vinci dropping what it got while
    # the gateway was down.
    old_jobs = {}
    for name, job_name, schedule in (("vinci", "vinci-sondeo", "every 30m"), ("vinci-matg1049", "vinci-agenda", "every 1m"),
                                     ("vinci-fisg1002", "vinci-agenda", "every 1m")):
        job = next(j for j in json.loads((profiles / name / "cron" / "jobs.json").read_text())["jobs"]
                   if j["name"] == job_name)
        run([hermes, "-p", name, "cron", "edit", job["id"], "--schedule", schedule], T_VINCI)
        old_jobs[name] = (job_name, job["id"])
    vinci_cfg = profiles / "vinci" / "config.yaml"
    cfg = yaml.safe_load(vinci_cfg.read_text())
    del cfg["platforms"]["telegram"]["extra"]["drop_pending_on_cold_boot"]
    vinci_cfg.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    throttled = EXISTING["ADSG1026"][0]
    telegram.throttle[(throttled, "setMyName")] = 3600  # Telegram's setMyName flood waits can last hours
    mark_calls = len(telegram.calls)
    update = setup_again()
    calls = telegram.calls[mark_calls:]
    assert sorted((c["bot"], c["params"]["name"]) for c in calls if c["method"] == "setMyName") == \
        sorted((username, PARTY[code][1]) for code, (username, _) in EXISTING.items())
    assert "⚠ No pude ponerle el nombre «Ciencias de la Sostenibilidad» en Telegram (Telegram pide esperar " \
           "3600 s antes de reintentar)" in update.stdout, update.stdout
    assert not [c for c in calls if c["method"] == "getManagedBotToken"]
    assert {c: (m["estado"], m.get("usuario")) for c, m in team().items() if c in EXISTING} == \
        {code: ("activa", username) for code, (username, _) in EXISTING.items()}, "los mismos bots, con su mismo usuario"
    assert len(team()) == len(SUBJECT_TOKENS) + len(PARTY), "ningún bot duplicado"
    for code, (username, old_name) in EXISTING.items():
        bot_name, avatar = PARTY[code][1], (AVATARS / PARTY[code][2]).read_bytes()
        assert materias.by_code(materias.load(core), code).display == bot_name
        assert telegram.profile_photos.get(username) == [avatar], "cada bot con su foto, subida una sola vez"
        if not old_name.startswith("Vinci · "):
            assert (username, "setMyProfilePhoto") not in [(c["bot"], c["method"]) for c in calls], \
                "la foto que puso PR #4 no se vuelve a subir"
        if username != throttled:
            assert telegram.name_of(PARTY_TOKENS[code]) == bot_name
            assert f"• {bot_name}: su nombre en Telegram quedó «{bot_name}»" in update.stdout
    assert telegram.name_of(PARTY_TOKENS["ADSG1026"]) == "El Equilibrio · Sostenibilidad"
    for name, (job_name, job_id) in old_jobs.items():
        jobs = [(j["id"], j["schedule_display"]) for j in json.loads((profiles / name / "cron" / "jobs.json").read_text())[
            "jobs"] if j["name"] == job_name]
        assert jobs == [(job_id, "15,45 * * * *" if name == "vinci" else "* * * * * */30")], f"{name}: {jobs}"
    assert "• cron «vinci-sondeo» actualizado (15,45 * * * *)" in update.stdout, update.stdout
    assert yaml.safe_load(vinci_cfg.read_text())["platforms"]["telegram"]["extra"]["drop_pending_on_cold_boot"] is False
    report.append("Actualizar con bots de materia ya creados, dos con el nombre de antes de PR #4 («Vinci · Ingeniería "
                  "de Software I») y dos con el de su personaje («El Analítico · Estadística», con la foto y el registro "
                  "que dejó PR #4): setup.sh los renombró ahí mismo con su propio token a solo su materia (setMyName: "
                  "«Ingeniería de Software I», «Estadística»…); mismos bots y usuarios, ningún bot nuevo ni duplicado, y "
                  "la foto que ya tenían no se volvió a subir")
    report.append("La misma actualización corrigió ahí mismo los cron que dejó la versión anterior, sin duplicar "
                  "ninguno (mismo id): el sondeo de Vinci de «every 30m» a «15,45 * * * *» y la agenda de Cálculo y "
                  "Física de «every 1m» a «* * * * * */30»; y Vinci dejó de descartar lo que le llega con el gateway apagado "
                  "(drop_pending_on_cold_boot: false, como los bots de materia)")
    take("setup.sh (4ª vez: la actualización renombra los bots de antes)")

    # 9b. Telegram throttled Ciencias de la Sostenibilidad's rename: the next setup.sh renames it, nothing else.
    mark_calls = len(telegram.calls)
    retry = setup_again()
    assert profile_calls(mark_calls) == [(throttled, "getMyName"), (throttled, "setMyName")], profile_calls(mark_calls)
    assert telegram.name_of(PARTY_TOKENS["ADSG1026"]) == "Ciencias de la Sostenibilidad"
    assert "• Ciencias de la Sostenibilidad: su nombre en Telegram quedó «Ciencias de la Sostenibilidad»" in retry.stdout
    report.append("Telegram respondió 429 (esperar 3600 s) al renombrar Ciencias de la Sostenibilidad: setup.sh avisó y "
                  "siguió con los demás sin esperar; la siguiente corrida lo renombró (solo getMyName y setMyName de ese "
                  "bot)")
    take("setup.sh (5ª vez: reintenta el nombre que Telegram frenó)")

    # 9c. Sistemas Distribuidos is created now, from Vinci's «Crear» button. Telegram Web refused its old suggested
    # username (vinci_sistemas_distribuidos_bot plus its own «bot»: «Username is too long.»).
    team_now = materias.load(core)
    distributed = materias.by_code(team_now, "CCPG1055")
    card_text, card_buttons = equipo.team_card(team_now, [], [])
    assert ("➕ Crear Sistemas Distribuidos", "v1:c:0:CCPG1055") in card_buttons
    assert all(f"• <b>{PARTY[code][1]}</b> ({code})" in card_text for code in PARTY), card_text
    mark_msgs = len(telegram.messages)
    pressed = json.loads(run([bot, "boton", "v1:c:0:CCPG1055"], T_VINCI).stdout)
    assert pressed["aviso"] == "Creemos Sistemas Distribuidos", pressed
    offer = telegram.messages[mark_msgs]
    key = offer["reply_markup"]["keyboard"][0][0]
    assert key["text"] == "🤖 Crear Sistemas Distribuidos"
    assert "Creemos Sistemas Distribuidos" in plain(offer["text"])
    assert "«Sistemas Distribuidos» y el usuario @vinci_sistemas_distribuidos_bot" in plain(offer["text"])
    name, username = telegram.creation_screen(key["request_managed_bot"])
    assert (name, username) == ("Sistemas Distribuidos", "vinci_sistemas_distribuidos_bot")
    token = PARTY_TOKENS["CCPG1055"]
    mark_calls = len(telegram.calls)
    telegram.create_managed_bot(BOT_TOKEN, CAPTAIN, token, username, name)
    created = json.loads(run([bot, "bot-creado", str(telegram.bot_id(token))], T_VINCI).stdout)
    assert created["materia"] == "CCPG1055" and "Sistemas Distribuidos quedó creado y activo" in \
        plain(created["respuesta"]), created
    assert (username, "setMyName") not in profile_calls(mark_calls), "ya tiene el nombre sugerido"
    assert telegram.profile_photos.get(username) == [(AVATARS / "server.jpg").read_bytes()]
    assert team()["CCPG1055"]["usuario"] == username
    botfather, _ = equipo.creation_message(distributed, can_manage=False)
    assert "2. Nombre: <code>Sistemas Distribuidos</code>" in botfather
    assert "3. Usuario: <code>vinci_sistemas_distribuidos_bot</code>" in botfather
    stats = materias.by_code(team_now, "ESTG1034")
    assert messages.handoff_button(stats.display) == "🎓 Consultar con Estadística"
    assert "Le pasé el aviso a <b>Estadística</b>" in messages.handoff_queued(stats.display, stats.handle())
    assert materias.resolve(team_now, "Vinci · Estadística") == materias.resolve(team_now, "estadística") == stats
    assert materias.resolve(team_now, "Sistemas Distribuidos").code == "CCPG1055"
    party_md.append("## Dónde se ve el nombre de cada bot\n")
    party_md.append("Tarjeta del equipo:\n\n```\n" + plain(card_text) + "\n" +
                    "".join(f"[{label}]" for label, _ in card_buttons) + "\n```\n")
    party_md.append(f"Al pulsar «Crear»: botón «{key['text']}», request_managed_bot "
                    f"`{json.dumps(key['request_managed_bot'], ensure_ascii=False)}`; la pantalla de Telegram ofrece "
                    f"el nombre «{name}» y el usuario @{username}.\n")
    party_md.append("Pasos de @BotFather (sin gestión de bots):\n\n```\n" + plain(botfather) + "\n```\n")
    party_md.append(f"Botón bajo un aviso: «{messages.handoff_button(stats.display)}»; al pulsarlo: "
                    f"«{plain(messages.handoff_queued(stats.display, stats.handle()))}»\n")
    report.append("Crear Sistemas Distribuidos desde el botón de Vinci: la tarjeta, el botón «Crear», el nombre y el usuario "
                  "sugeridos, los pasos de @BotFather, el botón de un aviso y la confirmación de entrega usan solo el "
                  "nombre de la materia; la pantalla de Telegram acepta el usuario (vinci_sistemas_distribuidos_bot, con "
                  "un solo «bot») y el bot creado queda con su foto, sin renombrarlo")
    take("Crear Sistemas Distribuidos")

    # 9d. Every suggested username fits Telegram's creation screen and ends in a single «bot».
    usernames_md = ["## Usuario sugerido para cada materia\n", "| Bot | Sugerido a Telegram | Usuario final |",
                    "|---|---|---|"]
    long_official = materias.Subject(code="ZZZZ1000", name=PARTY["CCPG1055"][0])  # no short form in the party
    for subject in [*materias.load(core), long_official]:
        _, markup = equipo.creation_message(subject, can_manage=True)
        request = markup["keyboard"][0][0]["request_managed_bot"]
        screen_name, screen_username = telegram.creation_screen(request)
        assert screen_name == subject.display and screen_username == equipo.suggested_username(subject)
        assert screen_username.endswith("_bot") and "botbot" not in screen_username
        usernames_md.append(f"| {subject.display} | `{request['suggested_username']}` | @{screen_username} |")
    party_md += [*usernames_md, ""]
    report.append("Usuario sugerido: para las 7 materias del equipo (y para el nombre oficial largo de Sistemas "
                  "Distribuidos) Telegram recibe el usuario sin su «bot», que su pantalla agrega: el usuario final "
                  "tiene 5 a 32 caracteres, cabe en el campo de Telegram Web y termina en un solo «bot»")

    for code, (name, bot_name, _) in PARTY.items():
        profile = profiles / f"vinci-{code.lower()}"
        soul = soul_md(profile.name)
        assert f"en Telegram te llamas «{bot_name}»" in " ".join(soul.split())
        assert not [w for w in ROLEPLAY if w in soul], f"{bot_name} no hace de personaje"
        for rule in ("Reglas firmes:", f"Solo {name}.", "Solo lectura del aula virtual", "No tienes web, terminal"):
            assert rule in soul, f"{bot_name} no cambia sus reglas: falta «{rule}»"
        scfg = yaml.safe_load((profile / "config.yaml").read_text())
        assert set(scfg["platform_toolsets"]["telegram"]) == {"memory", "session_search", "clarify", "skills",
                                                              "mcp-materia", "vinci-paginas"}
        assert set(scfg["platform_toolsets"]["cron"]) == {"memory", "skills", "mcp-materia", "vinci-paginas"}
        assert {"web", "terminal", "file"} <= set(scfg["agent"]["disabled_toolsets"])
        assert "skills" not in scfg["agent"]["disabled_toolsets"]
        assert scfg["compression"]["threshold_tokens"] == 80_000, f"{bot_name} resume su chat a los 80 mil tokens"
        if code in EXISTING and not EXISTING[code][1].startswith("Vinci · "):
            assert scfg["compression"]["protect_last_n"] == 30, "setup.sh no toca lo demás de un perfil que ya existía"
        assert parse_env_file(profile / ".env")["TELEGRAM_ALLOWED_USERS"] == CAPTAIN_ID
    for token in PARTY_TOKENS.values():  # a token lives only in secrets.env and its own profile's .env
        holders = {str(f.relative_to(home)) for f in home.rglob("*") if f.is_file() and token.encode() in f.read_bytes()}
        assert len(holders) == 1 and holders <= {f".hermes/profiles/vinci-{c.lower()}/.env" for c in PARTY}, holders
    report.append("Memoria de conversación corta: Vinci y cada bot de materia resumen su chat a los 80 000 tokens "
                  "(compression.threshold_tokens; Hermes por defecto espera a 256 000); en los perfiles que ya "
                  "existían setup.sh puso ese valor sin tocar lo demás (un ajuste de compression hecho a mano siguió)")

    mark_calls = len(telegram.calls)
    again = setup_again()
    assert profile_calls(mark_calls) == [], "con todo puesto, setup.sh no le pide nada más a Telegram"
    assert "quedó «" not in again.stdout and "puesta" not in again.stdout, again.stdout
    report.append("Tu party completa: cada bot de las 5 materias del capitán se llama solo como su materia («Sistemas "
                  "Distribuidos» en corto), tiene su foto y el tono de siempre en su SOUL.md, sin personaje, con sus "
                  "reglas, herramientas y acceso solo del capitán intactos; Cálculo y Física, sin foto en la party, "
                  "conservan la suya; lo que vio el modelo en cada turno no trae ningún personaje; setup.sh otra vez no "
                  "le pidió nada más a Telegram")
    take("setup.sh (6ª vez, con la party completa)")

    rows = [("Vinci", None, BOT_TOKEN, "wizard.jpg", soul_md("vinci")),
            ("Cálculo de una Variable", None, MATG, None, soul_md("vinci-matg1049")),
            ("Física I", None, FIS, None, soul_md("vinci-fisg1002"))]
    rows += [(telegram.name_of(PARTY_TOKENS[code]), EXISTING.get(code, (None, None))[1], PARTY_TOKENS[code], avatar,
              soul_md(f"vinci-{code.lower()}")) for code, (_, _, avatar) in PARTY.items()]
    party_md.append("## Cada bot\n")
    for name, old, token, avatar, text in rows:
        username = USERNAMES.get(token) or telegram.bots[token]
        photos = telegram.profile_photos.get(username, [])
        intro = next(p for p in text.split("\n\n") if p.startswith("Eres "))
        party_md.append(f"### {name} (@{username})\n")
        if old:
            party_md.append(f"Antes se llamaba «{old}»; setup.sh lo renombró en Telegram.\n")
        if avatar:
            assert photos == [(AVATARS / avatar).read_bytes()]
            (artifact / f"foto-{username}.jpg").write_bytes(photos[0])
            party_md.append(f"![{name}](foto-{username}.jpg)\n\nFoto subida una vez, idéntica a "
                            f"`hermes/avatars/{avatar}`.\n")
        else:
            assert not photos
            party_md.append("Ninguna foto subida: conserva la que tenga en Telegram.\n")
        party_md.append("> " + intro.replace("\n", "\n> ") + "\n")
