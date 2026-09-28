"""The team of subject bots: `materias.toml` in the data folder.

    [[materia]]
    codigo = "ESTG1034"            # código ESPOL (sin el paralelo)
    nombre = "Estadística"         # el bot se llama así («Estadística»)
    cursos = [12345, 12346]        # sus cursos en el aula virtual: el teórico y el práctico
    usuario = "vinci_estadistica_bot"
    estado = "activa"              # pendiente | esperando_bot | activa | archivada

Vinci writes it: `proponer_equipo` adds the courses of the aula virtual, one subject per
ESPOL code (a subject's theory and práctico sections, e.g. `Paralelo5_ESTG1034` and
`Paralelo105_ESTG1034`, are two aula courses of one subject bot), the captain's «Crear»
button marks one as waiting for its Telegram bot, the new bot's token makes it active,
and «Archivar» archives it. The captain may rename a subject by hand. A subject bot is
named after its subject (the name characters.py gives its code, else `nombre`); its Hermes
profile is named after Vinci's profile plus the code (`vinci-estg1034`).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from aula_core.config import ConfigError, CoreConfig
from aula_core.queries import fold
from espol_bot import characters, tomlfile

STATES = ("pendiente", "esperando_bot", "activa", "archivada")
CODE_RE = re.compile(r"[A-Z]{3,5}\d{3,5}")
CODE_IN_TEXT = re.compile(r"(?<![A-Z])[A-Z]{3,5}\d{3,5}(?!\d)")
# What follows the subject in a course name: « - II PAO 2026», « - PARALELO 5», « (PARALELO 5)».
NAME_SUFFIX = re.compile(r"\s+-\s+(?:PARALELO\b|[IVX]+\s+PA[OE]\b|PA[OE]\b|\d{4}\b)|\s*\(PARALELO", re.IGNORECASE)
SECTION = re.compile(r"\s*[-(]?\s*\b(?:pr[aá]ctic[oa]|te[oó]ric[oa])\)?$", re.IGNORECASE)
SMALL_WORDS = {"de", "del", "la", "las", "el", "los", "un", "una", "y", "e", "en", "a", "para", "por", "con", "o",
               "u"}
ROMAN = {"i", "ii", "iii", "iv", "v", "vi"}

HEADER = """\
Tus bots de materia. Lo escribe Vinci cuando le pides armar tu equipo (a partir de tu aula virtual).
Puedes cambiar `nombre` a mano: el bot se llama así, salvo que hermes/characters.toml le dé su nombre. Lo
demás lo maneja Vinci con tus botones.
estado: pendiente (sin bot) · esperando_bot (pulsaste «Crear») · activa · archivada (sin briefs ni respuestas;
memoria y cuaderno intactos)"""


@dataclass(frozen=True)
class Subject:
    code: str
    name: str
    course_ids: tuple[int, ...] = ()
    username: str | None = None
    state: str = "pendiente"

    @property
    def display(self) -> str:
        return characters.bot_name(self.code, self.name)

    @property
    def active(self) -> bool:
        return self.state == "activa"

    def handle(self) -> str:
        return f"@{self.username}" if self.username else self.display


def path(cfg: CoreConfig) -> Path:
    return cfg.data_dir / "materias.toml"


def base_code(text: str | None) -> str | None:
    """The ESPOL code in a course code or a schedule entry, without paralelo or section:
    'Paralelo105_ESTG1034', 'MATG1049-5', 'ESTG1034 - ESTADÍSTICA Paralelo N°105' → 'ESTG1034'.
    None when there is none."""
    match = CODE_IN_TEXT.search((text or "").upper())
    return match[0] if match else None


def short_name(course_name: str) -> str:
    """'ESTADÍSTICA - II PAO 2026 Práctico' → 'Estadística'; 'INGENIERÍA DE SOFTWARE I - PARALELO 5' →
    'Ingeniería de Software I'. The term, the paralelo and the section (teórico/práctico) are dropped."""
    name = NAME_SUFFIX.split(course_name, maxsplit=1)[0].strip()
    name = SECTION.sub("", name).strip() or name
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
        # `curso_id` is the single course of files written before a subject could have several.
        course_ids = row.get("cursos", [] if row.get("curso_id") is None else [row["curso_id"]])
        if not isinstance(course_ids, list) or not all(isinstance(i, int) for i in course_ids):
            raise ConfigError(f"{file}: «cursos» de {code} debe ser una lista de números")
        subjects.append(Subject(
            code=code, name=str(row.get("nombre") or code).strip(), course_ids=tuple(course_ids),
            username=(str(row["usuario"]).lstrip("@") or None) if row.get("usuario") else None,
            state=state,
        ))
    return subjects


def save(cfg: CoreConfig, subjects: list[Subject]) -> None:
    rows = [{"codigo": s.code, "nombre": s.name, "cursos": list(s.course_ids) or None, "usuario": s.username,
             "estado": s.state} for s in subjects]
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
    """The subject bot that covers an aula virtual course, theory or práctico (by course id, else by code)."""
    match = next((s for s in subjects if course_id is not None and course_id in s.course_ids), None)
    code = base_code(course_code)
    return match or next((s for s in subjects if code and s.code == code), None)


class Ambiguous(ConfigError):
    pass


def resolve(subjects: list[Subject], text: str) -> Subject:
    """Find the subject a free-text mention refers to ('estadística', 'ESTG1034', 'la de software', its
    bot's name: 'Sistemas Distribuidos'). Raises Ambiguous (listing the candidates) instead of guessing."""
    needle = fold(text).strip()
    needle = re.sub(r"^(vinci\s*[·.-]?\s*)", "", needle)
    if not needle:
        raise Ambiguous("No me dijiste de qué materia es.")
    exact = [s for s in subjects if needle in (fold(s.code), fold(s.name), fold(s.display))]
    if len(exact) == 1:
        return exact[0]
    words = [w for w in re.findall(r"\w+", needle) if len(w) >= 3 and w not in SMALL_WORDS]

    def word_match(word: str, name: str) -> bool:
        # 'estad' → 'estadística', 'estadisticas' → 'estadística'
        return any(n.startswith(word) or (len(n) >= 5 and word.startswith(n[:5]))
                   for n in re.findall(r"\w+", name))

    partial = [s for s in subjects
               if needle in fold(s.name) or needle in fold(s.code) or needle in fold(s.display)
               or (words and all(word_match(w, fold(s.name)) for w in words))]
    if len(partial) == 1:
        return partial[0]
    names = ", ".join(f"{s.name} ({s.code})" for s in (partial or subjects)) or "(ninguna configurada)"
    if partial:
        raise Ambiguous(f"«{text}» puede ser varias materias: {names}. Pregúntale cuál.")
    raise Ambiguous(f"No reconozco la materia «{text}». Las materias son: {names}. Pregúntale cuál.")
