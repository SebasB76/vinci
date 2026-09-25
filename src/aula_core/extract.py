"""Text extraction from course material, one entry per page / slide / section."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

# What a "page" means for each format, used when citing.
UNIT = {"pdf": "página", "pptx": "diapositiva", "docx": "sección"}

DOCX_SECTION_CHARS = 1800


def extract(path: Path) -> list[tuple[int, str]]:
    ext = path.suffix.lower().lstrip(".")
    if ext == "pdf":
        return _pdf(path)
    if ext == "pptx":
        return _pptx(path)
    if ext == "docx":
        return _docx(path)
    raise ValueError(f"Formato no soportado: {path.suffix}")


def _pdf(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # a single broken page should not lose the whole file
            log.warning("%s p.%d: %s", path.name, number, exc)
            text = ""
        pages.append((number, text.strip()))
    return pages


def _pptx(path: Path) -> list[tuple[int, str]]:
    from pptx import Presentation

    slides = []
    for number, slide in enumerate(Presentation(str(path)).slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(cell.text for cell in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"Notas: {notes}")
        slides.append((number, "\n".join(p for p in parts if p.strip()).strip()))
    return slides


def _docx(path: Path) -> list[tuple[int, str]]:
    from docx import Document

    doc = Document(str(path))
    blocks = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            blocks.append(" | ".join(cell.text for cell in row.cells))
    sections: list[tuple[int, str]] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        current.append(block)
        size += len(block)
        if size >= DOCX_SECTION_CHARS:
            sections.append((len(sections) + 1, "\n".join(current)))
            current, size = [], 0
    if current:
        sections.append((len(sections) + 1, "\n".join(current)))
    return sections
