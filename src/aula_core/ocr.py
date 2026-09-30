"""Text of a PDF page that is only an image (a scan, a photo of a handout), read with tesseract.

Tesseract is a system program (`sudo pacman -S tesseract`): without it there is no engine, and those
pages stay images that a subject bot looks at with ver_pagina, as before. Its Spanish and English
models live in `<carpeta_datos>/tessdata` when setup.sh could download them there (no sudo), else in
the system's tessdata. Which pages to read, and never reading one twice, is materials.py's job.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

LANGUAGES = ("spa", "eng")  # both at once: much of the material is in English
DPI = 300
MAX_EDGE = 5000         # pixels: a poster-sized page is not rendered at full DPI
MIN_WORD_CONFIDENCE = 30  # below this a "word" is usually a stroke of a figure read as letters
DOUBTFUL_CONFIDENCE = 70
DOUBTFUL_WORDS = 0.75  # of the tokens, the share that are words: a diagram reads as «<< |. — ~_< a»
WORD = re.compile(r"^\W*[^\W\d_]{2,}\W*$")
PAGE_TIMEOUT = 120


@dataclass(frozen=True)
class Engine:
    binary: str
    tessdata: Path | None  # None: the system's
    languages: str

    def _base(self) -> list[str]:
        return [self.binary, *(["--tessdata-dir", str(self.tessdata)] if self.tessdata else [])]


def tessdata_dir(data_dir: Path) -> Path:
    return data_dir / "tessdata"


def engine(data_dir: Path) -> Engine | None:
    binary = shutil.which("tesseract")
    if not binary:
        return None
    own = tessdata_dir(data_dir)
    candidate = Engine(binary, own if (own / "spa.traineddata").exists() else None, "")
    try:
        out = subprocess.run([*candidate._base(), "--list-langs"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("tesseract no responde: %s", exc)
        return None
    have = {line.strip() for line in out.stdout.splitlines()[1:]} if out.returncode == 0 else set()
    languages = [lang for lang in LANGUAGES if lang in have]
    return Engine(binary, candidate.tessdata, "+".join(languages)) if languages else None


def read_page(eng: Engine, path: Path, number: int, *, background: bool = False) -> tuple[str, float | None]:
    """Page `number` (from 1) of a PDF: its text and the mean confidence (0-100) tesseract gives it."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[number - 1]
        width, height = page.get_size()  # points: 72 a inch
        scale = min(DPI / 72, MAX_EDGE / max(width, height, 1))
        image = page.render(scale=scale, grayscale=True).to_pil()
    finally:
        pdf.close()
    png = io.BytesIO()
    image.save(png, "PNG")
    out = subprocess.run(
        [*eng._base(), "stdin", "stdout", "-l", eng.languages, "--dpi", str(round(scale * 72)),
         "-c", "tessedit_create_tsv=1", "-c", "tessedit_create_txt=0"],
        input=png.getvalue(), capture_output=True, timeout=PAGE_TIMEOUT,
        # one core, at low priority in the poll: the PC stays usable while a scanned book is read
        env={**os.environ, "OMP_THREAD_LIMIT": "1"}, preexec_fn=(lambda: os.nice(10)) if background else None)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode(errors="replace").strip()[-300:] or f"tesseract salió con {out.returncode}")
    return parse_tsv(out.stdout.decode("utf-8", errors="replace"))


def parse_tsv(tsv: str) -> tuple[str, float | None]:
    """Tesseract's TSV (one row per word, with its block, paragraph and line) back into text, one paragraph
    per block of lines, and its confidence weighted by word length."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    weighted = letters = 0.0
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        word, confidence = cols[11].strip(), float(cols[10])
        if not word or confidence < MIN_WORD_CONFIDENCE:
            continue
        lines.setdefault((int(cols[2]), int(cols[3]), int(cols[4])), []).append(word)
        weighted += confidence * len(word)
        letters += len(word)
    parts, last = [], None
    for (block, paragraph, _), words in lines.items():
        if last is not None and last != (block, paragraph):
            parts.append("")
        parts.append(" ".join(words))
        last = (block, paragraph)
    return "\n".join(parts).strip(), round(weighted / letters, 1) if letters else None


def doubtful(text: str, confidence: float | None) -> bool:
    """Whether OCR probably misread the page (a diagram, a poster, handwriting): look at it as an image."""
    tokens = text.split()
    words = sum(1 for t in tokens if WORD.match(t)) / len(tokens) if tokens else 0
    return (confidence or 0) < DOUBTFUL_CONFIDENCE or words < DOUBTFUL_WORDS
