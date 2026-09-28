"""Which course file is the syllabus, and which books it names as the main one.

ESPOL's syllabi come in three official layouts and each sets the main book apart:
  - «CONTENIDO DE ASIGNATURA» (IG1002-4, uploaded by the professor): «I. BIBLIOGRAFÍA» with a
    BÁSICA and a COMPLEMENTARIA column, side by side;
  - «Sílabo del Curso» (EUR-ACE): «8. Lectura obligatoria» then «9. Lectura adicional»;
  - ABET («SPA-Syllabus-…»): «4. Texto guía, título, autor y año» then «Otro material suplementario».
The parser reads the text that keeps a PDF's columns apart (extract.layout_text) or a DOCX's table
cells (joined with « | »), and returns every entry of the main block and of the other one.
"""

from __future__ import annotations

import re
from collections import Counter

from aula_core.catalog import fold

SYLLABUS_NAME = re.compile(r"s[iy]labo|syl+abus|contenido\s+de\s+(la\s+)?asignatura|programa\s+anal[iy]tico"
                           r"|programa\s+de\s+(la\s+)?asignatura|^contenido\.(pdf|docx)$")

# (where the main books start, where the other ones start)
BLOCKS = [
    (re.compile(r"\bB[AÁ]SICA\b"), re.compile(r"\bCOMPLEMENTARIA\b")),
    (re.compile(r"Lectura\s+obligatoria", re.I), re.compile(r"Lectura\s+adicional", re.I)),
    (re.compile(r"Texto\s+gu[ií]a[^\n]*", re.I), re.compile(r"(?:Otro\s+)?material\s+suplementario", re.I)),
]
BIBLIOGRAPHY = re.compile(r"BIBLIOGRAF[IÍ]A", re.I)
# A numbered part of the syllabus: «8. Lectura obligatoria», «I. BIBLIOGRAFÍA», «a. Otro material…».
LABEL = re.compile(r"^\s*(\d{1,2}|[A-Za-z])\s*[.)]\s")
# Page furniture repeated on every page of the EUR-ACE layout.
FOOTER = re.compile(r"^\s*(Guayaquil\s*-\s*Ecu|Campus Gustavo Galindo|www\s*\.\s*espo|S[ií]labo del Curso|Emitido (por|el)"
                    r"|Carrera:|P[aá]g\.\s*\d|\d+\s+Emitido el|[A-Z]{4}\d{4}\s+-\s+|LA NUBE$)", re.I)
BULLET = re.compile(r"^\s*(?:[•●▪◦*·-]|\d{1,2}[.)]|[a-z][.)])\s+")
MAX_BLOCK = 2000


def is_syllabus(name: str | None) -> bool:
    """By its name («Sílabo…», «SYLLABUS DETALLADO», «Contenido de Asignatura…»); the caller checks it is a document."""
    return bool(SYLLABUS_NAME.search(fold(name).strip()))


def _entries(block: str) -> list[str]:
    """One string per book: a bullet or a number starts one; a wrapped line continues it."""
    entries: list[str] = []
    for raw in block.split("\n"):
        line = raw.strip(" :\t")
        if not line or re.fullmatch(r"[-_=.·•\s]+", line):
            continue
        if BULLET.match(raw) or not entries:
            entries.append(BULLET.sub("", line.lstrip()))
        else:
            entries[-1] += " " + line
    return [re.sub(r"\s+", " ", e).strip(" .;") for e in entries if len(e.strip()) > 5]


def _next_label(line: str) -> str | None:
    """The label the part after this one starts with: «8.» → «9», «I.» → «J»."""
    match = LABEL.match(line)
    if not match:
        return None
    label = match[1]
    return str(int(label) + 1) if label.isdigit() else chr(ord(label) + 1)


def _until(lines: list[str], labels: tuple[str | None, ...], stop: re.Pattern | None = None) -> int:
    """Index of the first line that starts one of the parts `labels` (or matches `stop`)."""
    for i, line in enumerate(lines):
        match = LABEL.match(line)
        if (match and match[1] in labels) or (stop and stop.search(line)):
            return i
    return len(lines)


def _column(lines: list[str], header: int) -> int:
    """Where the right column starts: the commonest start of text after a gap, near the right header (the
    text extraction may place the header a few characters off its column)."""
    starts = Counter(m.end() for line in lines for m in re.finditer(r"\s{2,}(?=\S)", line) if abs(m.end() - header) <= 30)
    return starts.most_common(1)[0][0] if starts else header


def _split(line: str, column: int) -> tuple[str, str]:
    """A table row cut into its two columns at the gap nearest to where the right column starts."""
    gaps = [m.end() for m in re.finditer(r"\s{2,}", line) if abs(m.end() - column) <= 12]
    at = min(gaps, key=lambda g: abs(g - column)) if gaps else column
    return line[:at], line[at:]


def parse(text: str) -> dict:
    """{'main': [...], 'others': [...]} from a syllabus' text; both empty when no known layout is there."""
    lines = [line.rstrip() for line in text.replace("\r", "").split("\n") if not FOOTER.match(line)]
    start = next((i for i, line in enumerate(lines) if BIBLIOGRAPHY.search(line)), None)
    section_end = _next_label(lines[start]) if start is not None else None
    lines = lines[start or 0:]
    for main, other in BLOCKS:
        at = next((i for i, line in enumerate(lines) if main.search(line)), None)
        if at is None:
            continue
        head = lines[at]
        end_label = _next_label(head) or section_end
        if other.search(head):  # BÁSICA and COMPLEMENTARIA side by side: two columns, or two cells of a row
            body = lines[at + 1:][:_until(lines[at + 1:], (section_end,))]
            column = _column(body, other.search(head).start())
            cells = ([(line.split("|", 1) + [""])[:2] for line in body] if "|" in head
                     else [_split(line, column) for line in body])
            main_text, other_text = "\n".join(c[0] for c in cells), "\n".join(c[1] for c in cells)
        else:
            rest = lines[at + 1:]
            first = [main.split(head, 1)[-1]] if main.search(head).end() < len(head.rstrip()) else []
            cut = _until(rest, (end_label,), other)
            main_text = "\n".join(first + rest[:cut])
            other_text = ""
            if cut < len(rest) and other.search(rest[cut]):
                after = rest[cut + 1:]
                other_text = "\n".join(after[:_until(after, (_next_label(rest[cut]), end_label, section_end))])
        books = _entries(main_text[:MAX_BLOCK])
        if books:
            return {"main": books, "others": _entries(other_text[:MAX_BLOCK])}
    return {"main": [], "others": []}
