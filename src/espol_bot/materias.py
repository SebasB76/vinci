"""The team of subject bots: `materias.toml` in the data folder.

    [[materia]]
    codigo = "ESTG1034"            # código ESPOL (sin el paralelo)
    nombre = "Estadística"         # el bot se llama «Vinci · Estadística»
    curso_id = 12345               # ID de la materia en el aula virtual
    usuario = "vinci_estadistica_bot"
    estado = "activa"              # pendiente | esperando_bot | activa | archivada

Vinci writes it: `proponer_equipo` adds the courses of the aula virtual, the captain's
«Crear» button marks one as waiting for its Telegram bot, the new bot's token makes it
active, and «Archivar» archives it. The captain may rename a subject by hand. Each
subject bot is a Hermes profile named after Vinci's profile plus the code (`vinci-estg1034`).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from aula_core.config import ConfigError, CoreConfig
from aula_core.queries import fold
from espol_bot import tomlfile

STATES = ("pendiente", "esperando_bot", "activa", "archivada")
CODE_RE = re.compile(r"[A-Z]{3,5}\d{3,5}")
SMALL_WORDS = {"de", "del", "la", "las", "el", "los", "un", "una", "y", "e", "en", "a", "para", "por", "con", "o",
               "u"}
ROMAN = {"i", "ii", "iii", "iv", "v", "vi"}

HEADER = """\
Tus bots de materia. Lo escribe Vinci cuando le pides armar tu equipo (a partir de tu aula virtual).
Puedes cambiar `nombre` a mano (el bot se llama «Vinci · <nombre>»); lo demás lo maneja Vinci con tus botones.
estado: pendiente (sin bot) · esperando_bot (pulsaste «Crear») · activa · archivada (sin briefs ni respuestas;
memoria y cuaderno intactos)"""


@dataclass(frozen=True)
class Subject:
    code: str
    name: str
    course_id: int | None = None
    username: str | None = None
    state: str = "pendiente"

    @property
    def display(self) -> str:
        return f"Vinci · {self.name}"

    @property
    def active(self) -> bool:
        return self.state == "activa"

    def handle(self) -> str:
        return f"@{self.username}" if self.username else self.display


def path(cfg: CoreConfig) -> Path:
    return cfg.data_dir / "materias.toml"


def base_code(course_code: str | None) -> str | None:
    """'MATG1049-5' → 'MATG1049' (the paralelo is dropped); None when it is not an ESPOL code."""
    head = re.split(r"[-\s_]", (course_code or "").strip().upper(), maxsplit=1)[0]
    return head if CODE_RE.fullmatch(head) else None


def short_name(course_name: str) -> str:
    """'ESTADÍSTICA - PARALELO 5' → 'Estadística'; 'INGENIERÍA DE SOFTWARE I' → 'Ingeniería de Software I'."""
    name = re.split(r"\s+-\s+PARALELO\b|\s*\(PARALELO", course_name, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    words = []
    for i, word in enumerate(name.split()):
        low = word.lower()
        if low in ROMAN:
            words.append(word.upper())
        elif i > 0 and low in SMALL_WORDS:
            words.append(low)
        else:
            words.append(low[:1].upper() + low[1:])
    return " ".join(words) or course_name


def load(cfg: CoreConfig) -> list[Subject]:
    file = path(cfg)
    if not file.exists():
        return []
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file} tiene un error de formato: {exc}") from exc
    subjects = []
    for row in raw.get("materia", []):
        code = str(row.get("codigo", "")).strip().upper()
        if not CODE_RE.fullmatch(code):
            raise ConfigError(f"{file}: código de materia inválido {code!r}")
        state = str(row.get("estado", "pendiente"))
        if state not in STATES:
            raise ConfigError(f"{file}: estado inválido {state!r} en {code} (usa {', '.join(STATES)})")
        course_id = row.get("curso_id")
        subjects.append(Subject(
            code=code, name=str(row.get("nombre") or code).strip(),
            course_id=int(course_id) if course_id is not None else None,
            username=(str(row["usuario"]).lstrip("@") or None) if row.get("usuario") else None,
            state=state,
        ))
    return subjects


def save(cfg: CoreConfig, subjects: list[Subject]) -> None:
    rows = [{"codigo": s.code, "nombre": s.name, "curso_id": s.course_id, "usuario": s.username, "estado": s.state}
            for s in subjects]
    tomlfile.write_atomic(path(cfg), tomlfile.render(HEADER, "materia", rows))


def update(cfg: CoreConfig, code: str, **changes) -> Subject:
    subjects = load(cfg)
    for i, s in enumerate(subjects):
        if s.code == code:
            subjects[i] = replace(s, **changes)
            save(cfg, subjects)
            return subjects[i]
    raise ConfigError(f"No hay una materia {code} en {path(cfg)}")


def by_code(subjects: list[Subject], code: str) -> Subject | None:
    return next((s for s in subjects if s.code == code.upper()), None)


def for_course(subjects: list[Subject], course_id: int | None, course_code: str | None = None) -> Subject | None:
    """The subject bot that covers an aula virtual course (by course id, else by code)."""
    match = next((s for s in subjects if course_id is not None and s.course_id == course_id), None)
    code = base_code(course_code)
    return match or next((s for s in subjects if code and s.code == code), None)


class Ambiguous(ConfigError):
    pass


def resolve(subjects: list[Subject], text: str) -> Subject:
    """Find the subject a free-text mention refers to ('estadística', 'ESTG1034', 'la de software').
    Raises Ambiguous (listing the candidates) instead of guessing."""
    needle = fold(text).strip()
    needle = re.sub(r"^(vinci\s*[·.-]?\s*)", "", needle)
    if not needle:
        raise Ambiguous("No me dijiste de qué materia es.")
    exact = [s for s in subjects if needle in (fold(s.code), fold(s.name))]
    if len(exact) == 1:
        return exact[0]
    words = [w for w in re.findall(r"\w+", needle) if len(w) >= 3 and w not in SMALL_WORDS]

    def word_match(word: str, name: str) -> bool:
        # 'estad' → 'estadística', 'estadisticas' → 'estadística'
        return any(n.startswith(word) or (len(n) >= 5 and word.startswith(n[:5]))
                   for n in re.findall(r"\w+", name))

    partial = [s for s in subjects
               if needle in fold(s.name) or needle in fold(s.code)
               or (words and all(word_match(w, fold(s.name)) for w in words))]
    if len(partial) == 1:
        return partial[0]
    names = ", ".join(f"{s.name} ({s.code})" for s in (partial or subjects)) or "(ninguna configurada)"
    if partial:
        raise Ambiguous(f"«{text}» puede ser varias materias: {names}. Pregúntale cuál.")
    raise Ambiguous(f"No reconozco la materia «{text}». Las materias son: {names}. Pregúntale cuál.")
