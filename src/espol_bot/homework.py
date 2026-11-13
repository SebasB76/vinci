"""Homework Vinci writes for an assignment (a weekly workshop, a short analysis), as the plain PDF a professor
expects: a header with the course, the title, the members and the date, then sections of paragraphs, points and
bordered tables, and the references. The model only fills fields; the layout is fixed here.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from fpdf.fonts import FontFace

from espol_bot import submission
from espol_bot.resumen import LINE, MONTHS, _Pdf
from espol_bot.visuales import INK, MUTED, NAVY, NAVY_SOFT, RULE

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


def _paragraphs(pdf: _Pdf, text: str) -> None:
    for paragraph in (p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()):
        pdf.style(11)
        pdf.multi_cell(0, LINE, pdf.md(paragraph), markdown=True, align="J", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2.5)


def _draw_table(pdf: _Pdf, table: dict) -> None:
    pdf.style(10)
    pdf.set_draw_color(*RULE)
    pdf.set_line_width(0.25)
    # The first column is usually a short label (a term, a criterion): narrower than the text beside it.
    count = len(table["columns"])
    widths = [1] * count if count != 2 else [3, 7]
    with pdf.table(col_widths=widths, line_height=5.6, markdown=True, text_align="LEFT", padding=1.8,
                   headings_style=_heading_style(pdf),
                   first_row_as_headings=True, repeat_headings=1) as grid:
        header = grid.row()
        for column in table["columns"]:
            header.cell(pdf.clean(column))
        for cells in table["rows"]:
            row = grid.row()
            for cell in cells:
                row.cell(pdf.md(cell))
    pdf.ln(4)


def _heading_style(pdf: _Pdf) -> FontFace:
    return FontFace(family=pdf.family, emphasis="BOLD", color=NAVY, fill_color=NAVY_SOFT, size_pt=10)


def build(dest: Path, document: dict, now: datetime) -> tuple[int, bytes]:
    """Writes the PDF at `dest`; returns its page count and a thumbnail of its first page."""
    doc = parse(document)
    pdf = _Pdf(doc["title"])
    pdf.add_page()
    if doc["course"]:
        pdf.style(9.5, "B", MUTED)
        pdf.multi_cell(0, 5, pdf.clean(doc["course"].upper()), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
    pdf.style(18, "B", NAVY)
    pdf.multi_cell(0, 8.5, pdf.clean(doc["title"]), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    if doc["members"]:
        pdf.style(10.5, "B")
        pdf.cell(0, 5.8, "Integrantes", new_x="LMARGIN", new_y="NEXT")
        pdf.style(10.5)
        for member in doc["members"]:
            pdf.cell(0, 5.6, pdf.clean(member), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
    pdf.style(10, color=MUTED)
    pdf.cell(0, 5.6, f"{now.day} {MONTHS[now.month - 1]} {now.year}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_draw_color(*NAVY)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    for section in doc["sections"]:
        if section["heading"]:
            pdf.room(24)
            pdf.style(13, "B", NAVY)
            pdf.multi_cell(0, 6.8, pdf.clean(section["heading"]), align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        if section["text"]:
            _paragraphs(pdf, section["text"])
        for point in section["points"]:
            pdf.bullet(point)
        if section["points"]:
            pdf.ln(1.5)
        if section["table"]:
            _draw_table(pdf, section["table"])
        pdf.ln(3)

    if doc["references"]:
        pdf.room(24)
        pdf.style(13, "B", NAVY)
        pdf.cell(0, 6.8, "Referencias", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        for reference in doc["references"]:
            pdf.style(9.5, color=INK)
            pdf.multi_cell(0, 5, pdf.md(reference), markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.2)

    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))
    return submission.preview(dest)
