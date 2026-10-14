"""The visuals a summary section may carry (resumen.py), drawn with the PDF's own shapes so they share its look: a
flow of steps, a cycle, a side-by-side comparison, a hierarchy, a screen mockup (phone or web), or a page of the
material as an image. Each one is laid out first, so the page breaks before it instead of through it."""

from __future__ import annotations

import io
import math
from typing import Callable

NAVY, NAVY_SOFT, SKY = (27, 54, 93), (236, 242, 250), (165, 196, 235)
AMBER, AMBER_SOFT = (214, 137, 16), (254, 246, 228)
TEAL, PLUM = (21, 122, 112), (112, 72, 160)
INK, MUTED, RULE, WHITE = (38, 42, 48), (110, 118, 128), (214, 220, 228), (255, 255, 255)
SCREEN_GREY, DEVICE = (232, 235, 240), (44, 48, 56)
COLUMN_COLORS = (NAVY, AMBER, TEAL, PLUM)

KINDS = ("flujo", "ciclo", "comparacion", "jerarquia", "pantalla", "pagina")
PARTS = ("barra", "titulo", "texto", "campo", "boton", "lista", "imagen", "pestanas")
MAX_STEPS, MAX_COLUMNS, MAX_BRANCHES, MAX_PARTS = 8, 4, 5, 14


class VisualError(ValueError):
    """A visual that cannot be drawn from what the model sent."""


def _strings(values, name: str, low: int, high: int, each: int = 140) -> list[str]:
    items = [str(v).strip()[:each] for v in values or [] if str(v).strip()]
    if not low <= len(items) <= high:
        raise VisualError(f"«{name}» lleva de {low} a {high} elementos y trae {len(items)}")
    return items


def _text_height(pdf, text: str, width: float, size: float, line: float, weight: str = "") -> float:
    pdf.style(size, weight)
    return pdf.multi_cell(width, line, pdf.md(text), markdown=True, align="C", dry_run=True, output="HEIGHT")


def _centered(pdf, x: float, y: float, w: float, h: float, text: str, size: float, line: float,
              weight: str = "", color=INK, align: str = "C") -> None:
    """`text` vertically centered in the box at x, y."""
    inner = _text_height(pdf, text, w, size, line, weight)
    pdf.set_xy(x, y + (h - inner) / 2)
    pdf.style(size, weight, color)
    pdf.multi_cell(w, line, pdf.md(text), markdown=True, align=align)


def _card(pdf, x: float, y: float, w: float, h: float, fill, border=None, radius: float = 2) -> None:
    pdf.set_fill_color(*fill)
    if border:
        pdf.set_draw_color(*border)
        pdf.set_line_width(0.35)
    pdf.rect(x, y, w, h, "DF" if border else "F", round_corners=True, corner_radius=radius)


def _arrow(pdf, x1: float, y1: float, x2: float, y2: float, color=NAVY, head: float = 2.4) -> None:
    angle = math.atan2(y2 - y1, x2 - x1)
    pdf.set_draw_color(*color)
    pdf.set_fill_color(*color)
    pdf.set_line_width(0.55)
    pdf.line(x1, y1, x2 - head * math.cos(angle), y2 - head * math.sin(angle))
    wings = [(x2 - head * 1.15 * math.cos(angle + s), y2 - head * 1.15 * math.sin(angle + s)) for s in (0.45, -0.45)]
    pdf.polygon([(x2, y2), *wings], style="F")


def _edge(cx: float, cy: float, hw: float, hh: float, dx: float, dy: float, gap: float = 1.6) -> tuple[float, float]:
    """Where a line from the center of a box (half sizes hw, hh) towards (dx, dy) leaves it."""
    length = math.hypot(dx, dy) or 1
    ux, uy = dx / length, dy / length
    t = min(hw / abs(ux) if ux else math.inf, hh / abs(uy) if uy else math.inf) + gap
    return cx + ux * t, cy + uy * t


def _flow(pdf, v: dict):
    steps = _strings(v.get("pasos"), "pasos", 2, MAX_STEPS)
    if len(steps) <= 4:  # one row, left to right
        gap = 9
        w = (pdf.epw - gap * (len(steps) - 1)) / len(steps)
        h = max(18.0, max(_text_height(pdf, s, w - 6, 9.5, 4.6) for s in steps) + 13)

        def paint(y):
            for i, step in enumerate(steps):
                x = pdf.l_margin + i * (w + gap)
                _card(pdf, x, y, w, h, NAVY_SOFT, SKY)
                pdf.set_xy(x, y + 3)
                pdf.style(7.5, "B", AMBER)
                pdf.cell(w, 4, f"PASO {i + 1}", align="C")
                _centered(pdf, x + 3, y + 7, w - 6, h - 9, step, 9.5, 4.6)
                if i:
                    _arrow(pdf, x - gap + 1.2, y + h / 2, x - 1.2, y + h / 2)
        return h, paint

    w, gap, x = 130.0, 7.0, pdf.l_margin + (pdf.epw - 130) / 2  # a column, top to bottom
    heights = [max(11.0, _text_height(pdf, s, w - 20, 9.5, 4.6) + 5) for s in steps]

    def paint(y):
        for i, (step, h) in enumerate(zip(steps, heights)):
            _card(pdf, x, y, w, h, NAVY_SOFT, SKY)
            pdf.set_fill_color(*NAVY)
            pdf.circle(x + 7, y + h / 2, 3.4, style="F")
            pdf.set_xy(x + 3.6, y + h / 2 - 2.5)
            pdf.style(8.5, "B", WHITE)
            pdf.cell(6.8, 5, str(i + 1), align="C")
            _centered(pdf, x + 14, y, w - 18, h, step, 9.5, 4.6, align="L")
            if i < len(steps) - 1:
                _arrow(pdf, x + w / 2, y + h + 0.8, x + w / 2, y + h + gap - 0.8)
            y += h + gap
    return sum(heights) + gap * (len(steps) - 1), paint


def _cycle(pdf, v: dict):
    steps = _strings(v.get("pasos"), "pasos", 3, MAX_STEPS, 90)
    center = str(v.get("centro") or "").strip()[:40]
    w = 40.0
    h = max(12.0, max(_text_height(pdf, s, w - 4, 9, 4.3) for s in steps) + 5)
    rx, ry = 63.0, 38.0 if len(steps) <= 6 else 46.0
    total = 2 * ry + h

    def paint(y):
        cx, cy = pdf.l_margin + pdf.epw / 2, y + total / 2
        spots = [(cx + rx * math.cos(a), cy + ry * math.sin(a))
                 for a in (-math.pi / 2 + 2 * math.pi * i / len(steps) for i in range(len(steps)))]
        if center:
            pdf.set_fill_color(*AMBER_SOFT)
            pdf.circle(cx, cy, 15, style="F")
            _centered(pdf, cx - 13, cy - 13, 26, 26, f"**{center}**", 9.5, 4.4, color=AMBER)
        for (ax, ay), (bx, by) in zip(spots, spots[1:] + spots[:1]):
            start = _edge(ax, ay, w / 2, h / 2, bx - ax, by - ay)
            end = _edge(bx, by, w / 2, h / 2, ax - bx, ay - by)
            _arrow(pdf, *start, *end, color=SKY)
        for i, (step, (sx, sy)) in enumerate(zip(steps, spots)):
            _card(pdf, sx - w / 2, sy - h / 2, w, h, NAVY if i == 0 else NAVY_SOFT, None if i == 0 else SKY)
            _centered(pdf, sx - w / 2 + 2, sy - h / 2, w - 4, h, step, 9, 4.3, color=WHITE if i == 0 else INK)
    return total, paint


def _comparison(pdf, v: dict):
    columns = v.get("columnas") or []
    if not 2 <= len(columns) <= MAX_COLUMNS or not all(isinstance(c, dict) for c in columns):
        raise VisualError(f"«columnas» lleva de 2 a {MAX_COLUMNS} objetos con «titulo» y «puntos»")
    gap = 5
    w = (pdf.epw - gap * (len(columns) - 1)) / len(columns)
    titles = [str(c.get("titulo") or "").strip()[:60] or "—" for c in columns]
    points = [_strings(c.get("puntos"), "puntos de una columna", 1, 8, 160) for c in columns]
    head = max(_text_height(pdf, t, w - 6, 10.5, 5, "B") for t in titles) + 6
    rows = [[_text_height(pdf, p, w - 11, 9, 4.4) + 2 for p in ps] for ps in points]
    body = max(sum(r) for r in rows) + 6

    def paint(y):
        for i, (title, ps, hs) in enumerate(zip(titles, points, rows)):
            x, color = pdf.l_margin + i * (w + gap), COLUMN_COLORS[i]
            _card(pdf, x, y, w, head + body, WHITE, RULE)
            _card(pdf, x, y, w, head, color)
            pdf.rect(x, y + head - 2, w, 2, "F")  # square off the header's lower corners
            _centered(pdf, x + 3, y, w - 6, head, title, 10.5, 5, "B", WHITE)
            top = y + head + 3
            for point, ph in zip(ps, hs):
                pdf.set_fill_color(*color)
                pdf.circle(x + 4, top + 2.3, 0.8, style="F")
                pdf.set_xy(x + 7, top)
                pdf.style(9)
                pdf.multi_cell(w - 11, 4.4, pdf.md(point), markdown=True, align="L")
                top += ph
    return head + body, paint


def _hierarchy(pdf, v: dict):
    root = str(v.get("raiz") or "").strip()[:80]
    branches = v.get("ramas") or []
    if not root or not 1 <= len(branches) <= MAX_BRANCHES or not all(isinstance(b, dict) for b in branches):
        raise VisualError(f"«jerarquia» lleva «raiz» y de 1 a {MAX_BRANCHES} «ramas» con «titulo» (y «hijos»)")
    gap, rw = 4, 72.0
    w = (pdf.epw - gap * (len(branches) - 1)) / len(branches)
    rh = _text_height(pdf, root, rw - 8, 11, 5, "B") + 7
    titles = [str(b.get("titulo") or "").strip()[:60] or "—" for b in branches]
    kids = [[str(k).strip()[:100] for k in b.get("hijos") or [] if str(k).strip()][:6] for b in branches]
    head = max(_text_height(pdf, t, w - 4, 9.5, 4.6, "B") for t in titles) + 5
    rows = [[_text_height(pdf, k, w - 8, 8.5, 4.1) + 1.5 for k in ks] for ks in kids]
    body = max((sum(r) + 4 if r else 0) for r in rows)
    link = 12

    def paint(y):
        cx = pdf.l_margin + pdf.epw / 2
        _card(pdf, cx - rw / 2, y, rw, rh, NAVY, radius=2.5)
        _centered(pdf, cx - rw / 2 + 4, y, rw - 8, rh, root, 11, 5, "B", WHITE)
        centers = [pdf.l_margin + i * (w + gap) + w / 2 for i in range(len(branches))]
        top, mid = y + rh + link, y + rh + link / 2
        pdf.set_draw_color(*SKY)
        pdf.set_line_width(0.5)
        pdf.line(cx, y + rh, cx, mid)
        pdf.line(min(centers + [cx]), mid, max(centers + [cx]), mid)
        for i, (title, ks, hs, bx) in enumerate(zip(titles, kids, rows, centers)):
            pdf.set_draw_color(*SKY)
            pdf.set_line_width(0.5)
            pdf.line(bx, mid, bx, top)
            x = bx - w / 2
            _card(pdf, x, top, w, head + body, WHITE if body else NAVY_SOFT, SKY)
            if body:
                _card(pdf, x, top, w, head, NAVY_SOFT, SKY)
            _centered(pdf, x + 2, top, w - 4, head, title, 9.5, 4.6, "B", NAVY)
            at = top + head + 2.5
            for kid, kh in zip(ks, hs):
                pdf.set_fill_color(*SKY)
                pdf.circle(x + 3.2, at + 2.1, 0.7, style="F")
                pdf.set_xy(x + 5.5, at)
                pdf.style(8.5)
                pdf.multi_cell(w - 8, 4.1, pdf.md(kid), markdown=True, align="L")
                at += kh
    return rh + link + head + body, paint


def _screen(pdf, v: dict):
    web = str(v.get("formato") or "").lower().startswith("web")
    parts = v.get("elementos") or []
    if not 1 <= len(parts) <= MAX_PARTS or not all(isinstance(p, dict) for p in parts):
        raise VisualError(f"«pantalla» lleva de 1 a {MAX_PARTS} «elementos», cada uno con «tipo» y «texto»")
    for p in parts:
        if p.get("tipo") not in PARTS:
            raise VisualError(f"un elemento de pantalla es de tipo {', '.join(PARTS)}; llegó «{p.get('tipo')}»")
    fw = 150.0 if web else 70.0
    inner = fw - (14 if web else 10)
    top_pad = 14.0 if web else 11.0

    def size(part) -> float:
        kind, text = part["tipo"], str(part.get("texto") or "").strip()[:200]
        if kind == "titulo":
            return _text_height(pdf, text, inner, 12, 5.4, "B")
        if kind == "texto":
            return _text_height(pdf, text, inner, 8.5, 4.1)
        if kind == "lista":
            return 10.0 * max(1, len([t for t in text.split(";") if t.strip()][:6]))
        return {"barra": 10.0, "campo": 9.0, "boton": 9.5, "imagen": 30.0, "pestanas": 9.0}[kind]

    heights = [size(p) for p in parts]
    fh = top_pad + sum(heights) + 3.5 * (len(parts) - 1) + 10

    def paint(y):
        fx = pdf.l_margin + (pdf.epw - fw) / 2
        pdf.set_draw_color(*DEVICE)
        pdf.set_line_width(0.9 if not web else 0.5)
        pdf.set_fill_color(*WHITE)
        pdf.rect(fx, y, fw, fh, "DF", round_corners=True, corner_radius=2.5 if web else 7)
        if web:
            pdf.set_fill_color(*SCREEN_GREY)
            pdf.rect(fx + 0.3, y + 0.3, fw - 0.6, 8, "F", round_corners=True, corner_radius=2.2)
            for i, color in enumerate(((236, 95, 89), (245, 190, 79), (98, 196, 98))):
                pdf.set_fill_color(*color)
                pdf.circle(fx + 5 + i * 4.5, y + 4.3, 1.2, style="F")
            _card(pdf, fx + 22, y + 2, fw - 30, 4.6, WHITE, radius=2.2)
        else:
            _card(pdf, fx + fw / 2 - 8, y + 3.5, 16, 2.4, DEVICE, radius=1.2)
            _card(pdf, fx + fw / 2 - 12, y + fh - 4.5, 24, 1.4, DEVICE, radius=0.7)
        x, at = fx + (fw - inner) / 2, y + top_pad
        for part, h in zip(parts, heights):
            kind, text = part["tipo"], str(part.get("texto") or "").strip()[:200]
            if kind == "barra":
                _card(pdf, x, at, inner, h, NAVY, radius=1.5)
                pdf.set_fill_color(*WHITE)
                for k in range(3):
                    pdf.rect(x + 3, at + 3.4 + k * 1.4, 4, 0.5, "F")
                _centered(pdf, x + 9, at, inner - 12, h, text, 9.5, 4.4, "B", WHITE, align="L")
            elif kind == "titulo":
                pdf.set_xy(x, at)
                pdf.style(12, "B")
                pdf.multi_cell(inner, 5.4, pdf.md(text), markdown=True, align="L")
            elif kind == "texto":
                pdf.set_xy(x, at)
                pdf.style(8.5, color=MUTED)
                pdf.multi_cell(inner, 4.1, pdf.md(text), markdown=True, align="L")
            elif kind == "campo":
                _card(pdf, x, at, inner, h, WHITE, RULE, radius=1.5)
                _centered(pdf, x + 3, at, inner - 6, h, text, 8.5, 4.1, color=MUTED, align="L")
            elif kind == "boton":
                _card(pdf, x, at, inner, h, AMBER, radius=2)
                _centered(pdf, x, at, inner, h, text, 9.5, 4.4, "B", WHITE)
            elif kind == "lista":
                for k, item in enumerate([t.strip() for t in text.split(";") if t.strip()][:6] or [""]):
                    row = at + 10 * k
                    pdf.set_fill_color(*SCREEN_GREY)
                    pdf.circle(x + 3.5, row + 5, 3, style="F")
                    _centered(pdf, x + 9, row, inner - 9, 10, item, 8.5, 4.1, align="L")
                    pdf.set_draw_color(*RULE)
                    pdf.set_line_width(0.25)
                    pdf.line(x + 9, row + 10, x + inner, row + 10)
            elif kind == "imagen":
                _card(pdf, x, at, inner, h, SCREEN_GREY, radius=1.5)
                pdf.set_draw_color(*RULE)
                pdf.set_line_width(0.3)
                pdf.line(x, at, x + inner, at + h)
                pdf.line(x, at + h, x + inner, at)
                if text:
                    w = min(inner - 6, pdf.get_string_width(pdf.clean(text)) + 8)
                    _card(pdf, x + (inner - w) / 2, at + h / 2 - 3.5, w, 7, WHITE, radius=1.5)
                    _centered(pdf, x, at, inner, h, text, 8, 4, color=MUTED)
            elif kind == "pestanas":
                tabs = [t.strip() for t in text.split(";") if t.strip()][:5] or ["—"]
                tw = inner / len(tabs)
                pdf.style(8.5, "B")
                fits = max(pdf.get_string_width(pdf.clean(t)) for t in tabs) <= tw - 2
                for k, tab in enumerate(tabs):  # a smaller font rather than a tab broken mid-word
                    _centered(pdf, x + k * tw, at, tw, h - 1, tab, 8.5 if fits else 6.5, 4.1, "B" if k == 0 else "",
                              NAVY if k == 0 else MUTED)
                pdf.set_fill_color(*RULE)
                pdf.rect(x, at + h - 0.4, inner, 0.4, "F")
                pdf.set_fill_color(*NAVY)
                pdf.rect(x, at + h - 1, tw, 1, "F")
            at += h + 3.5
    return fh, paint


def _page(pdf, v: dict):
    from PIL import Image

    image = v.get("imagen")
    if not image:
        raise VisualError("«pagina» lleva «archivo_id» y «pagina» de un PDF del material")
    picture = Image.open(io.BytesIO(image)).convert("RGB")
    # A slide's white margins only shrink what matters: crop to the ink, keeping a little air.
    box = Image.eval(picture.convert("L"), lambda px: 255 if px < 235 else 0).getbbox()
    if box:
        pad = int(0.03 * max(picture.size))
        picture = picture.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                                min(box[2] + pad, picture.width), min(box[3] + pad, picture.height)))
        out = io.BytesIO()
        picture.save(out, "JPEG", quality=85)
        image = out.getvalue()
    iw, ih = picture.size
    w = 150.0 if iw > ih else 105.0
    h = w * ih / iw
    if h > 150:
        w, h = w * 150 / h, 150.0

    def paint(y):
        x = pdf.l_margin + (pdf.epw - w) / 2
        pdf.image(io.BytesIO(image), x=x, y=y, w=w, h=h)
        pdf.set_draw_color(*RULE)
        pdf.set_line_width(0.3)
        pdf.rect(x, y, w, h)
    return h, paint


LAYOUTS: dict[str, Callable] = {"flujo": _flow, "ciclo": _cycle, "comparacion": _comparison, "jerarquia": _hierarchy,
                                "pantalla": _screen, "pagina": _page}


def _laid_out(pdf, visual: dict, figure: int):
    kind = visual.get("tipo")
    if kind not in LAYOUTS:
        raise VisualError(f"«tipo» es uno de {', '.join(KINDS)}; llegó «{kind}»")
    height, paint = LAYOUTS[kind](pdf, visual)
    caption = " · ".join(s for s in (f"**Figura {figure}**", str(visual.get("titulo") or "").strip()[:150],
                                      str(visual.get("cita") or "")) if s)
    return height, paint, caption, _text_height(pdf, caption, pdf.epw - 20, 8.5, 4.4)


def height(pdf, visual: dict) -> float:
    """How much of the page the visual and its caption take."""
    shape, _, _, caption_height = _laid_out(pdf, visual, 0)
    return shape + caption_height + 10


def draw(pdf, visual: dict, figure: int) -> None:
    """The visual and its caption («Figura N · …», with the page's citation for a page of the material)."""
    height, paint, caption, caption_height = _laid_out(pdf, visual, figure)
    pdf.room(height + caption_height + 8)
    y = pdf.get_y() + 2
    paint(y)
    pdf.set_xy(pdf.l_margin + 10, y + height + 3)
    pdf.style(8.5, color=MUTED)
    pdf.multi_cell(pdf.epw - 20, 4.4, pdf.md(caption), markdown=True, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
