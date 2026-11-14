"""Homework Vinci writes for an assignment (a weekly workshop, a short analysis), as a plain student document: black
Arial-like text, the title centered, «Asignatura:», the members as A., B., C., then sections of paragraphs, points
and simple bordered tables, and the references only when the work has them. The model only fills fields; the layout
is fixed here, and it must read like a document a student typed in Word, not a designed report.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fpdf.fonts import FontFace

from espol_bot import resumen, submission
from espol_bot.resumen import _Pdf

MAX_SECTIONS = 20
MAX_POINTS = 20
MAX_COLUMNS = 6
MAX_ROWS = 60
MAX_MEMBERS = 8
MAX_REFERENCES = 30


class HomeworkError(ValueError):
    """A document the PDF cannot be built from; the message tells the model what to fix."""


def _text(value, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _items(values, limit: int, each: int, name: str) -> list[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, list):
        raise HomeworkError(f"«{name}» es una lista de textos")
    items = [_text(v, each) for v in values if _text(v, each)]
    if len(items) > limit:
        raise HomeworkError(f"«{name}» tiene {len(items)}; el máximo es {limit}")
    return items


def _table(value, where: str) -> dict | None:
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise HomeworkError(f"la «table» de {where} es un objeto con «columns» y «rows»")
    columns = _items(value.get("columns"), MAX_COLUMNS, 120, f"columns de {where}")
    rows = value.get("rows")
    if not columns or not isinstance(rows, list) or not rows:
        raise HomeworkError(f"la «table» de {where} necesita «columns» (los títulos) y «rows» (al menos una fila)")
    if len(rows) > MAX_ROWS:
        raise HomeworkError(f"la tabla de {where} tiene {len(rows)} filas; el máximo es {MAX_ROWS}")
    cells = []
    for n, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(columns):
            raise HomeworkError(f"la fila {n} de la tabla de {where} debe tener {len(columns)} celdas, una por columna")
        cells.append([_text(c, 2000) for c in row])
    return {"columns": columns, "rows": cells}


def parse(document: dict) -> dict:
    """The document checked and trimmed, or HomeworkError saying what is missing."""
    if not isinstance(document, dict):
        raise HomeworkError("«document» es un objeto con «title» y «sections»")
    title = _text(document.get("title"), 160)
    if not title:
        raise HomeworkError("falta «title», el título del trabajo (el de la tarea o el del documento del profesor)")
    sections = document.get("sections")
    if not isinstance(sections, list) or not sections:
        raise HomeworkError("faltan «sections»: al menos una, con «heading» y su «text», «points» o «table»")
    if len(sections) > MAX_SECTIONS:
        raise HomeworkError(f"son {len(sections)} secciones; el máximo es {MAX_SECTIONS}")
    parsed = []
    for n, section in enumerate(sections, 1):
        if not isinstance(section, dict):
            raise HomeworkError(f"la sección {n} es un objeto con «heading» y «text», «points» o «table»")
        heading = _text(section.get("heading"), 200)
        where = f"la sección {n}" + (f" («{heading}»)" if heading else "")
        text = _text(section.get("text"), 8000)
        points = _items(section.get("points"), MAX_POINTS, 1500, f"points de {where}")
        table = _table(section.get("table"), where)
        if not (text or points or table):
            raise HomeworkError(f"{where} no trae «text», «points» ni «table»")
        parsed.append({"heading": heading, "text": text, "points": points, "table": table})
    return {"title": title, "course": _text(document.get("course"), 160),
            "members": _items(document.get("members"), MAX_MEMBERS, 120, "members"), "sections": parsed,
            "references": _items(document.get("references"), MAX_REFERENCES, 500, "references")}


BLACK = (0, 0, 0)
LINE = 6
# Liberation Sans has Arial's metrics (fonts-liberation in the Docker image); without it, the summaries' fonts.
FAMILIES = (("LiberationSans-Regular", "LiberationSans-Bold", "LiberationSans-Italic", "LiberationSans-BoldItalic"),
            *resumen.FAMILIES)


class _Plain(_Pdf):
    def __init__(self, title: str):
        super().__init__(title, FAMILIES)
        self.set_margins(25, 25, 25)
        self.set_auto_page_break(True, margin=20)

    def style(self, size: float, weight: str = "", color=BLACK) -> None:
        super().style(size, weight, color)

    def footer(self):
        self.set_y(-14)
        self.style(9)
        self.cell(0, 5, str(self.page_no()), align="C")

    def bold_line(self, text: str, size: float = 11, align: str = "L") -> None:
        self.style(size, "B")
        self.multi_cell(0, LINE, self.clean(text), align=align, new_x="LMARGIN", new_y="NEXT")


def _paragraphs(pdf: _Plain, text: str) -> None:
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()):
        pdf.style(11)
        pdf.multi_cell(0, LINE, pdf.md(paragraph), markdown=True, align="J", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)


def _draw_table(pdf: _Plain, table: dict) -> None:
    pdf.style(11)
    pdf.set_draw_color(*BLACK)
    pdf.set_line_width(0.2)
    count = len(table["columns"])
    # Two columns are usually a term and its explanation: the explanation gets the room.
    widths = [1] * count if count != 2 else [3, 7]
    heading = FontFace(family=pdf.family, emphasis="BOLD", color=BLACK, size_pt=11)
    with pdf.table(col_widths=widths, line_height=5.4, markdown=True, text_align="LEFT", padding=1.5,
                   headings_style=heading, first_row_as_headings=True, repeat_headings=1) as grid:
        header = grid.row()
        for column in table["columns"]:
            header.cell(pdf.clean(column))
        for cells in table["rows"]:
            row = grid.row()
            for cell in cells:
                row.cell(pdf.md(cell))
    pdf.ln(4)


def build(dest: Path, document: dict, now: datetime) -> tuple[int, bytes]:
    """Writes the PDF at `dest`; returns its page count and a thumbnail of its first page."""
    doc = parse(document)
    pdf = _Plain(doc["title"])
    pdf.add_page()
    pdf.bold_line(doc["title"], 13, "C")
    pdf.ln(4)
    pdf.style(11)
    if doc["course"]:
        pdf.multi_cell(0, LINE, pdf.clean(f"Asignatura: {doc['course']}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
    if doc["members"]:
        pdf.cell(0, LINE, "Integrantes:", new_x="LMARGIN", new_y="NEXT")
        for letter, member in zip("ABCDEFGH", doc["members"]):
            pdf.cell(0, LINE, pdf.clean(f"{letter}. {member}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    for section in doc["sections"]:
        if section["heading"]:
            pdf.room(20)
            pdf.bold_line(section["heading"])
            pdf.ln(2)
        if section["text"]:
            _paragraphs(pdf, section["text"])
        for point in section["points"]:
            pdf.bullet(point, color=BLACK)
        if section["points"]:
            pdf.ln(2)
        if section["table"]:
            _draw_table(pdf, section["table"])
        pdf.ln(2)

    if doc["references"]:
        pdf.room(20)
        pdf.bold_line("Referencias")
        pdf.ln(2)
        for reference in doc["references"]:
            pdf.style(10)
            pdf.multi_cell(0, 5.2, pdf.md(reference), markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)

    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))
    return submission.preview(dest)
