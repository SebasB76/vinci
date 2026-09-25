"""Regenerates the binary course-material fixtures (committed under fixtures/files/).

    uv run python tests/e2e/make_documents.py

The PDF is written by hand (standard Helvetica font, WinAnsi encoding) so the
fixture needs no PDF library; the PPTX uses python-pptx.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).parent / "fixtures" / "files"

PDF_PAGES = [
    [
        "Calculo Diferencial - Capitulo 3: Derivadas",
        "3.1 Definicion de la derivada",
        "La derivada de f en x es el limite del cociente incremental",
        "(f(x+h) - f(x)) / h cuando h tiende a cero.",
        "Geometricamente es la pendiente de la recta tangente a la curva.",
    ],
    [
        "3.2 La regla de la cadena",
        "La regla de la cadena permite derivar una composicion de funciones.",
        "Si y = f(g(x)), entonces y' = f'(g(x)) * g'(x).",
        "Ejemplo: la derivada de sen(x^2) es cos(x^2) * 2x.",
        "Se aplica de afuera hacia adentro, capa por capa.",
    ],
    [
        "3.3 Aplicaciones: optimizacion",
        "Para hallar maximos y minimos se iguala la derivada a cero.",
        "Los puntos criticos se clasifican con el criterio de la segunda derivada.",
        "Ejercicio 4: maximizar el area de un rectangulo de perimetro 20 m.",
    ],
]

# Accented words are added per line so the extractor must decode WinAnsi bytes.
ACCENTS = {
    "Calculo": "Cálculo", "Capitulo": "Capítulo", "Definicion": "Definición", "limite": "límite",
    "Geometricamente": "Geométricamente", "composicion": "composición", "optimizacion": "optimización",
    "maximos": "máximos", "minimos": "mínimos", "criticos": "críticos", "area": "área",
    "perimetro": "perímetro",
}


def _accented(line: str) -> str:
    for plain, accented in ACCENTS.items():
        line = line.replace(plain, accented)
    return line


def _pdf_string(text: str) -> str:
    out = []
    for byte in text.encode("cp1252"):
        ch = chr(byte)
        if ch in "()\\":
            out.append("\\" + ch)
        elif 32 <= byte < 127:
            out.append(ch)
        else:
            out.append(f"\\{byte:03o}")
    return "(" + "".join(out) + ")"


def make_pdf(path: Path) -> None:
    objects: list[bytes] = []
    n_pages = len(PDF_PAGES)
    # 1 catalog, 2 pages, 3 font, then (page, content) pairs
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, lines in enumerate(PDF_PAGES):
        stream_lines = ["BT", "/F1 12 Tf", "72 740 Td", "16 TL"]
        for line in lines:
            stream_lines.append(f"{_pdf_string(_accented(line))} Tj T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        body += f"{offset:010d} 00000 n \n".encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(body))


def make_pptx(path: Path) -> None:
    from pptx import Presentation

    prs = Presentation()
    slides = [
        ("Física I - Semana 2: Cinemática", "Movimiento en una y dos dimensiones"),
        ("Movimiento rectilíneo uniforme", "La velocidad es constante: x = x0 + v·t"),
        ("Movimiento parabólico", "Un proyectil combina MRU en el eje x y caída libre en el eje y.\n"
                                  "El alcance máximo se logra con un ángulo de 45°."),
    ]
    for title, body in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    prs.core_properties.author = "ESPOL"
    # Fixed timestamps keep the file byte-stable across regenerations.
    import datetime as _dt
    prs.core_properties.created = _dt.datetime(2026, 9, 1)
    prs.core_properties.modified = _dt.datetime(2026, 9, 1)
    prs.core_properties.last_modified_by = "ESPOL"
    prs.save(str(path))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_pdf(OUT / "capitulo-3-derivadas.pdf")
    make_pptx(OUT / "semana-2-cinematica.pptx")
    print(f"Fixtures escritos en {OUT}")
