"""A study summary (.pdf) a bot writes from the material: a cover band, an intro, a clickable index, one section per
topic (explanation, key points, a visual, an example, its sources linked to the aula) and a closing «Para recordar».

Like the slides, the file goes to the profile's `cache/documents/`: a reply that mentions its path reaches the chat
as a file (Telegram or WhatsApp). The fonts come from the system (Noto on Arch, DejaVu in the Docker image), with
the math and symbol fonts as fallbacks; without any, the PDF's built-in Helvetica keeps only Latin-1.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from espol_bot import citations, visuales
from espol_bot.visuales import AMBER, AMBER_SOFT, INK, MUTED, NAVY, NAVY_SOFT, RULE, SKY

MAX_SECTIONS = 20
MAX_POINTS = 12
MAX_TAKEAWAYS = 8
FONT_DIRS = ("/usr/share/fonts/noto", "/usr/share/fonts/truetype/noto", "/usr/share/fonts/TTF",
             "/usr/share/fonts/truetype/dejavu")
FAMILIES = (("NotoSans-Regular", "NotoSans-Bold", "NotoSans-Italic", "NotoSans-BoldItalic"),
            ("DejaVuSans", "DejaVuSans-Bold", "DejaVuSans-Oblique", "DejaVuSans-BoldOblique"))
FALLBACKS = ("NotoSansMath-Regular", "NotoSansSymbols2-Regular", "NotoSansSymbols-Regular", "DejaVuSans")
MONTHS = "ene feb mar abr may jun jul ago sep oct nov dic".split()
MARGIN, BOTTOM, LINE = 20, 22, 6.2


class SummaryError(ValueError):
    """An outline the summary cannot be built from."""


def _font(name: str) -> Path | None:
    return next((p for d in FONT_DIRS if (p := Path(d) / f"{name}.ttf").is_file()), None)


class _Pdf(FPDF):
    def __init__(self, title: str):
        super().__init__(format="A4")
        self.title_text = title
        self.family = "helvetica"
        self.glyphs: set[int] | None = None  # None: the built-in font, Latin-1 only
        family = next((paths for names in FAMILIES if all(paths := [_font(n) for n in names])), None)
        if family:
            for style, path in zip(("", "B", "I", "BI"), family):
                self.add_font("body", style, path)
            self.family, self.glyphs = "body", set(self.fonts["body"].cmap)
            extra = []
            for n, path in enumerate(p for name in FALLBACKS if (p := _font(name))):
                self.add_font(f"fallback{n}", "", path)
                extra.append(f"fallback{n}")
                self.glyphs |= set(self.fonts[f"fallback{n}"].cmap)
            self.set_fallback_fonts(extra, exact_match=False)
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=BOTTOM)

    def clean(self, text: str) -> str:
        # A glyph no font has (an emoji) prints as an empty box: drop it.
        text = unicodedata.normalize("NFC", str(text or ""))
        if self.glyphs is None:
            return text.encode("latin-1", "ignore").decode("latin-1")
        return "".join(c for c in text if c in "\n\t" or ord(c) in self.glyphs)

    def md(self, text: str) -> str:
        return self.clean(_markdown(text))

    def style(self, size: float, weight: str = "", color=INK) -> None:
        self.set_font(self.family, weight, size)
        self.set_text_color(*color)

    def footer(self):
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(MARGIN, self.h - 14, self.w - MARGIN, self.h - 14)
        self.set_y(-12)
        self.style(8, color=MUTED)
        self.cell(self.epw * 0.8, 5, self.clean(self.title_text)[:90])
        self.cell(0, 5, f"{self.page_no()} / {{nb}}", align="R")

    def room(self, height: float) -> None:
        """A new page unless `height` more millimeters fit on this one."""
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def text_height(self, text: str, width: float, size: float = 11) -> float:
        self.style(size)
        return self.multi_cell(width, LINE, text, markdown=True, dry_run=True, output="HEIGHT")

    def box(self, label: str, text: str, fill, bar) -> None:
        """A tinted box with a colored bar on its left and a small label on top."""
        pad, width = 4.5, self.epw - 13
        body = self.md(text)
        height = pad * 2 + 6 + self.text_height(body, width)
        self.room(height)
        x, y = self.l_margin, self.get_y()
        self.set_fill_color(*fill)
        self.rect(x, y, self.epw, height, "F", round_corners=True, corner_radius=1.5)
        self.set_fill_color(*bar)
        self.rect(x, y, 1.6, height, "F")
        self.set_xy(x + 8, y + pad)
        self.style(8.5, "B", bar)
        self.set_char_spacing(0.6)
        self.cell(0, 5, self.clean(label.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_char_spacing(0)
        self.set_xy(x + 8, y + pad + 6)
        self.style(11)
        self.multi_cell(width, LINE, body, markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")
        self.set_y(y + height + 5)

    def bullet(self, text: str, color=NAVY, indent: float = 7) -> None:
        body = self.md(text)
        self.room(min(self.text_height(body, self.epw - indent), 3 * LINE))
        self.set_fill_color(*color)
        self.circle(self.l_margin + 2.2, self.get_y() + LINE / 2, 0.85, style="F")
        self.set_x(self.l_margin + indent)
        self.style(11)
        self.multi_cell(self.epw - indent, LINE, body, markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1.2)


def _markdown(text: str) -> str:
    """The model's Markdown as fpdf2's: **bold**, __italic__, [label](url); a citation becomes its linked label."""
    text = citations.LINKED.sub(lambda m: f"[{m['label'].strip()}]({m['url']})", text)
    text = text.replace("📄", "").replace("--", "–")
    text = re.sub(r"^\s*[-*•]\s+", "", text)  # the PDF draws its own bullet
    return re.sub(r"(?<![*\w])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![*\w])", r"__\1__", text)


def _sources(sources: list[str]) -> str:
    """The section's citations, one per file: «03bScrum.pdf, páginas 4, 9-10» linked once to the file."""
    singular = {plural: unit for unit, plural in citations.PLURAL.items()}
    files: dict[tuple, list] = {}
    loose = []
    for source in sources:
        match = citations.LINKED.fullmatch(source.strip()) or citations.PLAIN.fullmatch(source.strip())
        if not match:
            loose.append(source)
            continue
        name = match["name"].strip()
        word = match["label"].strip()[len(name):].lstrip(" ,").split()[0].lower()
        unit = singular.get(word, word if word in citations.PLURAL else "página")
        pages = match["first"] + (f"-{match['last']}" if match["last"] and match["last"] != match["first"] else "")
        found = files.setdefault((name, match.groupdict().get("url")), [unit, []])
        if pages not in found[1]:
            found[1].append(pages)
    parts = []
    for (name, url), (unit, pages) in files.items():
        where = f"{unit} {pages[0]}" if len(pages) == 1 and "-" not in pages[0] else \
            f"{citations.PLURAL.get(unit, unit + 's')} {', '.join(pages)}"
        parts.append(f"[{name}, {where}]({citations._url(url)})" if url else f"{name}, {where}")
    return "  ·  ".join(parts + loose)


def _text(value, name: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise SummaryError(f"falta «{name}»")
    return text[:limit]


def _items(values, limit: int, each: int) -> list[str]:
    return [str(v).strip()[:each] for v in values or [] if str(v).strip()][:limit]


def _cover(pdf: _Pdf, title: str, subtitle: str, now: datetime) -> None:
    pdf.style(24, "B")
    lines = len(pdf.multi_cell(pdf.epw, 11, pdf.clean(title), align="L", dry_run=True, output="LINES"))
    height = 42 + 11 * lines
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, height, "F")
    pdf.set_fill_color(*AMBER)
    pdf.rect(0, height, pdf.w, 1.4, "F")
    pdf.set_xy(MARGIN, 15)
    pdf.style(9, "B", SKY)
    pdf.set_char_spacing(1.2)
    pdf.cell(0, 5, "RESUMEN DE ESTUDIO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_char_spacing(0)
    pdf.set_y(23)
    pdf.style(24, "B", (255, 255, 255))
    pdf.multi_cell(pdf.epw, 11, pdf.clean(title), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)
    pdf.style(11, color=SKY)
    meta = "  ·  ".join(s for s in (subtitle, f"{now.day} {MONTHS[now.month - 1]} {now.year}") if s)
    pdf.multi_cell(pdf.epw, 6, pdf.clean(meta), new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(height + 10)


def _index(pdf: _Pdf, headings: list[str]) -> list[int]:
    """The «En este resumen» list, each line a link to its section; the links to point once each section is drawn."""
    pdf.style(8.5, "B", MUTED)
    pdf.set_char_spacing(0.6)
    pdf.cell(0, 6, "EN ESTE RESUMEN", new_x="LMARGIN", new_y="NEXT")
    pdf.set_char_spacing(0)
    links = []
    for n, heading in enumerate(headings, 1):
        link = pdf.add_link()
        links.append(link)
        pdf.style(10.5, "B", NAVY)
        pdf.cell(8, 6.5, f"{n:02d}", link=link)
        pdf.style(10.5)
        pdf.cell(0, 6.5, pdf.clean(heading), link=link, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    return links


def _opening(pdf: _Pdf, body: str, points: list[str], visual: dict | None) -> float:
    """What stays on one page with the heading: a short text with its visual, or a long text's start (the visual then
    goes where it fits, instead of leaving most of a page blank)."""
    pdf.style(11)
    height = 18 + sum(pdf.multi_cell(0, LINE, pdf.md(p.strip()), markdown=True, dry_run=True, output="HEIGHT") + 2.5
                      for p in re.split(r"\n\s*\n", body) if p.strip())
    height += sum(pdf.multi_cell(pdf.epw - 7, LINE, pdf.md(p), markdown=True, dry_run=True, output="HEIGHT") + 1.2
                  for p in points)
    if height > 70:
        return 32
    return height + (visuales.height(pdf, visual) if visual else 0)


def _heading(pdf: _Pdf, n: int, heading: str, keep: float) -> None:
    # The heading, its text and its visual go on one page when they fit on one; at least the heading and some text.
    pdf.room(keep if keep <= pdf.page_break_trigger - pdf.t_margin else 32)
    pdf.ln(3)
    y = pdf.get_y()
    pdf.set_fill_color(*NAVY)
    pdf.rect(pdf.l_margin, y, 10, 10, "F", round_corners=True, corner_radius=2)
    pdf.set_xy(pdf.l_margin, y)
    pdf.style(11, "B", (255, 255, 255))
    pdf.cell(10, 10, str(n), align="C")
    pdf.set_xy(pdf.l_margin + 14, y + 1.2)
    pdf.style(15, "B", NAVY)
    pdf.multi_cell(pdf.epw - 14, 7.6, pdf.clean(heading), align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(max(pdf.get_y(), y + 10) + 4)


def build(folder: Path, title: str, sections: list[dict], subtitle: str = "", intro: str = "",
          takeaways: list[str] | None = None, now: datetime | None = None) -> tuple[Path, int]:
    """The PDF's path and its page count."""
    now = now or datetime.now()
    title = _text(title, "titulo", 120)
    if not sections:
        raise SummaryError("faltan las secciones: manda al menos una con su título y su texto o sus puntos")
    if len(sections) > MAX_SECTIONS:
        raise SummaryError(f"son {len(sections)} secciones; el máximo es {MAX_SECTIONS}")
    parsed = []
    for n, section in enumerate(sections, 1):
        if not isinstance(section, dict):
            raise SummaryError(f"la sección {n} no es un objeto con «titulo» y «texto» o «puntos»")
        # The PDF numbers the sections itself: a «3. Cuestionarios» from the model would read «9  3. Cuestionarios».
        heading = re.sub(r"^\s*\d+\s*[.)\-:]\s*", "", _text(section.get("titulo"), f"titulo de la sección {n}", 120))
        body = str(section.get("texto") or "").strip()[:4000]
        points = _items(section.get("puntos"), MAX_POINTS, 600)
        if not body and not points:
            raise SummaryError(f"la sección {n} («{heading}») no trae «texto» ni «puntos»")
        visual = section.get("visual") or None
        if visual is not None and (not isinstance(visual, dict) or visual.get("tipo") not in visuales.KINDS):
            raise SummaryError(f"el «visual» de la sección {n} lleva «tipo»: uno de {', '.join(visuales.KINDS)}")
        parsed.append((heading, body, points, visual, str(section.get("ejemplo") or "").strip()[:1500],
                       _items(section.get("fuentes"), 12, 400)))

    pdf = _Pdf(title)
    pdf.add_page()
    _cover(pdf, title, str(subtitle or "").strip()[:200], now)
    intro = str(intro or "").strip()[:2000]
    if intro:
        pdf.box("De qué trata", intro, NAVY_SOFT, NAVY)
    links = _index(pdf, [p[0] for p in parsed]) if len(parsed) >= 3 else []

    figures = 0
    for n, (heading, body, points, visual, example, sources) in enumerate(parsed, 1):
        try:
            _heading(pdf, n, heading, _opening(pdf, body, points, visual))
        except visuales.VisualError as exc:
            raise SummaryError(f"el visual de la sección {n} («{heading}»): {exc}") from None
        if links:
            pdf.set_link(links[n - 1], page=pdf.page_no(), y=pdf.get_y() - 18)
        for paragraph in (p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()):
            pdf.style(11)
            pdf.multi_cell(0, LINE, pdf.md(paragraph), markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2.5)
        for point in points:
            pdf.bullet(point)
        if points:
            pdf.ln(1.5)
        if visual:
            figures += 1
            try:
                visuales.draw(pdf, visual, figures)
            except visuales.VisualError as exc:
                raise SummaryError(f"el visual de la sección {n} («{heading}»): {exc}") from None
        if example:
            pdf.box("Ejemplo", example, AMBER_SOFT, AMBER)
        if sources:
            line = pdf.md("**Fuente:** " + _sources(sources))
            pdf.style(8.5, color=MUTED)
            # Kept with its section: a source alone atop the next page reads as the next section's. A short one
            # may use the space above the footer.
            end = pdf.get_y() + pdf.multi_cell(0, 4.8, line, markdown=True, dry_run=True, output="HEIGHT")
            keep = pdf.page_break_trigger < end <= pdf.h - 15
            pdf.set_auto_page_break(not keep, margin=BOTTOM)
            pdf.multi_cell(0, 4.8, line, markdown=True, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.set_auto_page_break(True, margin=BOTTOM)
        pdf.ln(6)

    takeaways = _items(takeaways, MAX_TAKEAWAYS, 300)
    if takeaways:
        pdf.box("Para recordar", "\n".join(f"{n}.  {t}" for n, t in enumerate(takeaways, 1)), NAVY_SOFT, NAVY)

    folder.mkdir(parents=True, exist_ok=True)
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^A-Za-z0-9]+", "-", plain).strip("-").lower()[:60] or "resumen"
    path = folder / f"{slug}-{now.strftime('%Y%m%d-%H%M%S')}.pdf"
    pdf.output(str(path))
    return path, pdf.page_no()
