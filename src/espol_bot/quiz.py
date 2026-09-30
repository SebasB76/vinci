"""Short quizzes a subject bot sends as Telegram quiz polls (its `/quiz` skill, or a quiz Vinci handed over).

The model writes the questions from what it read and calls `send_quiz`; this module checks that each
question's source is real (a page of this subject's material, or an entry of its notebook), writes the
citation itself, shuffles the options and sends one quiz poll per question. Telegram shows the right answer
and its explanation only once the captain votes. The votes come back as poll_answer updates, which the
vinci-botones plugin hands to `espol-bot quiz-respuesta` with no model: when the last question is answered
the captain gets the score with the source of every question, and what was missed goes to the notebook as a
weak topic (so the briefs and Vinci see it).

Quizzes live in the subject's notebook (cuaderno.db), next to the entries they may cite.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime

from aula_core import queries, timefmt
from aula_core.config import CoreConfig
from espol_bot.cuaderno import Notebook, NotebookError
from espol_bot.messages import e, link
from espol_bot.telegram import Telegram, TelegramError

SCHEMA = """
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS quiz_questions (
    poll_id TEXT PRIMARY KEY,
    quiz_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL,
    correct INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    chosen INTEGER,
    answered_at TEXT
);
"""
MAX_QUESTIONS = 5
MIN_OPTIONS, MAX_OPTIONS = 2, 4
# Telegram's limits for a quiz poll; the question also carries its «2/4.» prefix.
QUESTION_CHARS = 290
OPTION_CHARS = 100
EXPLANATION_CHARS = 200
NAME_CHARS = 50


class QuizError(ValueError):
    """A quiz the model must fix before it is sent: the message says what and how."""


@dataclass(frozen=True)
class Question:
    text: str
    options: list[str]
    correct: int
    explanation: str
    source: str
    source_url: str | None


def _clean(value, what: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise QuizError(f"Falta {what}.")
    if len(text) > limit:
        raise QuizError(f"{what[0].upper()}{what[1:]} tiene {len(text)} caracteres; Telegram admite hasta {limit}.")
    return text


def _short(name: str) -> str:
    return name if len(name) <= NAME_CHARS else name[:NAME_CHARS - 1].rstrip() + "…"


def file_source(conn, file_id: int, page) -> tuple[str, str | None]:
    """The citation of a page of one of the subject's files; QuizError when that page is not in the material."""
    try:
        number = int(page)
    except (TypeError, ValueError):
        raise QuizError("Con «file_id» va también «page»: la página (o diapositiva) de donde sale la pregunta.") \
            from None
    data = queries.read_pages(conn, file_id, number, number)
    if not data["descargado"]:
        raise QuizError(f"«{data['archivo']}» todavía no está bajado: bájalo, léelo y haz la pregunta de lo que dice.")
    scanned = data["indexado"] == "escaneado" and 1 <= number <= (data["paginas"] or 0)
    if not data["contenido"] and not scanned:
        raise QuizError(f"«{data['archivo']}» no tiene {data['unidad']} {number} con texto: cita la página de "
                        "donde sacaste la pregunta (búscala con buscar_material o leer_archivo).")
    return f"{_short(data['archivo'])}, {data['unidad']} {number}", data["url"]


def entry_source(notebook: Notebook, entry_id) -> tuple[str, None]:
    """The citation of a notebook entry: what the captain sent (a photo, a note, pasted text)."""
    try:
        entry = notebook.entry(int(entry_id))
    except (TypeError, ValueError):
        raise QuizError("«entry_id» debe ser el número de una entrada de tu cuaderno.") from None
    except NotebookError as exc:
        raise QuizError(str(exc)) from None
    kind = entry["tipo"].replace("_", " ")
    return f"tu cuaderno, {kind} #{entry['id']} ({timefmt.parse(entry['creado']).astimezone(notebook.tz):%d/%m})", None


def question(item: dict, position: int, source: tuple[str, str | None]) -> Question:
    """One question as the model wrote it, checked against Telegram's limits; its options come out shuffled."""
    where = f"la pregunta {position}"
    text = _clean(item.get("question"), f"el texto de {where}", QUESTION_CHARS)
    options = item.get("options")
    if not isinstance(options, list) or not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise QuizError(f"{where[0].upper()}{where[1:]} necesita de {MIN_OPTIONS} a {MAX_OPTIONS} opciones.")
    options = [_clean(o, f"una opción de {where}", OPTION_CHARS) for o in options]
    if len({o.casefold() for o in options}) != len(options):
        raise QuizError(f"{where[0].upper()}{where[1:]} repite una opción.")
    answer = _clean(item.get("answer"), f"la respuesta correcta de {where} («answer»)", OPTION_CHARS)
    matches = [o for o in options if o.casefold() == answer.casefold()]
    if not matches:
        raise QuizError(f"La respuesta de {where} («answer») debe ser una de sus opciones, escrita igual.")
    label, url = source
    citation = f"📄 {label}"
    room = EXPLANATION_CHARS - len(citation) - 1
    explanation = _clean(item.get("explanation"), f"la explicación de {where}", 10_000)
    if len(explanation) > room:
        raise QuizError(f"La explicación de {where} tiene {len(explanation)} caracteres; con la cita caben {room}.")
    random.shuffle(options)
    return Question(text, options, options.index(matches[0]), f"{explanation} {citation}", label, url)


def _db(notebook: Notebook):
    conn = notebook.connection()
    conn.executescript(SCHEMA)
    return conn


def send(telegram: Telegram, notebook: Notebook, topic: str, questions: list[Question], now: datetime) -> dict:
    """One quiz poll per question in the captain's chat, recorded so the plugin can score the answers."""
    topic = _clean(topic, "el tema del quiz («topic»)", 100)
    if not 1 <= len(questions) <= MAX_QUESTIONS:
        raise QuizError(f"Un quiz corto lleva de 1 a {MAX_QUESTIONS} preguntas.")
    conn = _db(notebook)
    quiz_id = int(conn.execute("INSERT INTO quizzes(topic, created_at) VALUES (?, ?)",
                               (topic, timefmt.iso(now))).lastrowid)
    conn.commit()
    total = len(questions)
    for position, q in enumerate(questions, 1):
        try:
            message = telegram.send_poll(f"{position}/{total}. {q.text}", q.options, q.correct, q.explanation)
            poll_id = str(message["poll"]["id"])
        except (TelegramError, KeyError, TypeError) as exc:
            if position == 1:
                conn.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
                conn.commit()
                raise QuizError(f"Telegram no aceptó el quiz: {exc}. Hazle las preguntas por escrito, con las "
                                "respuestas al final.") from None
            raise QuizError(f"Telegram no aceptó la pregunta {position}: {exc}. Le llegaron las {position - 1} "
                            "primeras; dile que las responda.") from None
        conn.execute("INSERT INTO quiz_questions(poll_id, quiz_id, position, question, options, correct, source, "
                     "source_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (poll_id, quiz_id, position, q.text, json.dumps(q.options, ensure_ascii=False), q.correct,
                      q.source, q.source_url))
        conn.commit()
    return {"quiz": quiz_id, "topic": topic, "questions": total, "sources": sorted({q.source for q in questions}),
            "message": f"Le mandé {total} pregunta(s) como quiz de Telegram: ve la respuesta correcta y la explicación "
                       "recién al responder cada una, y al terminar le llega su puntaje con la fuente de cada "
                       "pregunta. Contéstale en una línea, sin repetir las preguntas ni revelar las respuestas."}


def record_answer(core: CoreConfig, code: str, poll_id: str, option_ids: list[int], now: datetime) -> str | None:
    """The captain voted in a quiz poll: None until the quiz's last question, then its score (HTML)."""
    notebook = Notebook(core, code)
    try:
        if not notebook.db_path.exists() or not option_ids:
            return None
        conn = _db(notebook)
        row = conn.execute("SELECT quiz_id, chosen FROM quiz_questions WHERE poll_id = ?", (poll_id,)).fetchone()
        if row is None or row["chosen"] is not None:
            return None
        conn.execute("UPDATE quiz_questions SET chosen = ?, answered_at = ? WHERE poll_id = ?",
                     (int(option_ids[0]), timefmt.iso(now), poll_id))
        conn.commit()
        quiz_id = row["quiz_id"]
        if conn.execute("SELECT COUNT(*) FROM quiz_questions WHERE quiz_id = ? AND chosen IS NULL",
                        (quiz_id,)).fetchone()[0]:
            return None
        # Two answers landing together both see none left: only one scores the quiz.
        if conn.execute("UPDATE quizzes SET finished_at = ? WHERE id = ? AND finished_at IS NULL",
                        (timefmt.iso(now), quiz_id)).rowcount != 1:
            return None
        conn.commit()
        return _score(notebook, conn, quiz_id, now)
    finally:
        notebook.close()


def _score(notebook: Notebook, conn, quiz_id: int, now: datetime) -> str:
    topic = conn.execute("SELECT topic FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()["topic"]
    rows = conn.execute("SELECT * FROM quiz_questions WHERE quiz_id = ? ORDER BY position", (quiz_id,)).fetchall()
    lines, missed = [], []
    for r in rows:
        options = json.loads(r["options"])
        source = link(r["source_url"], r["source"]) if r["source_url"] else e(r["source"])
        stem = r["question"] if len(r["question"]) <= 90 else r["question"][:89].rstrip() + "…"
        if r["chosen"] == r["correct"]:
            lines.append(f"✅ {r['position']}. {e(stem)} · 📄 {source}")
        else:
            lines.append(f"❌ {r['position']}. {e(stem)} → era «{e(options[r['correct']])}» · 📄 {source}")
            missed.append(f"«{stem}» (era «{options[r['correct']]}»; {r['source']})")
    right = len(rows) - len(missed)
    head = f"🧠 <b>Quiz: {e(topic)}</b> — {right} de {len(rows)}" + (", ¡perfecto!" if not missed else ".")
    tail = []
    if missed:
        notebook.add("tema_debil", f"Quiz «{topic}»: fallé " + "; ".join(missed), now, origin="quiz")
        tail = ["Anoté lo que fallaste como tema débil en tu cuaderno."]
    return "\n".join([head, *lines, *tail])
