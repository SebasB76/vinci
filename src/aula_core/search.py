"""Full-text search over indexed course material (SQLite FTS5, BM25 ranking).

Pages matching every meaningful word of the question come first; pages matching only some fill the
rest and say so (`coincide: parcial`), since one common word («model», «software») is enough for a
match. Within that, the main book (`prefer`) weighs more and material of an earlier semester less,
and a page that is a copy of one already listed (the same slides in Slides/2021 and Slides/2026)
is left out. Each hit carries its file's language: the question is in Spanish, many books are not, and
says when its text came from OCR (a scanned page), which may misread a formula or a figure.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from aula_core import extract
from aula_core.catalog import fold, is_old, normalized_name, term_year

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada como con contra cual cuales cuando
de del desde donde dos el ella ellas ellos en entre era es esa esas ese eso esos esta estan estas este esto estos
explica explicame fue ha hay la las le les lo los mas me mi mis muy nada ni no nos o os otra otro para pero poco
por porque que quien se sea segun ser si sin sobre son su sus tambien te tiene tienen todo todos tu tus un una uno
unos y ya yo dame dime resume resumen resumeme cual cuales hazme haz genera preguntas pregunta tema capitulo
the of and is what how
""".split())
MAIN_BOOK = 1.6
EARLIER_SEMESTER = 0.6
CANDIDATES = 8  # rows read per result wanted, before copies are dropped


def terms(question: str) -> list[str]:
    """The meaningful words as FTS5 terms, with a light prefix match so 'derivadas' also finds
    'derivada' and 'derivación'."""
    found = []
    for word in re.findall(r"\w+", fold(question)):
        if word in STOPWORDS or len(word) < 3:
            continue
        found.append(f'"{word[:max(5, len(word) - 2)]}"*' if len(word) > 5 else f'"{word}"')
    return list(dict.fromkeys(found))


def build_match(question: str, joiner: str = "OR") -> str | None:
    return f" {joiner} ".join(terms(question)) or None


def _fingerprint(text: str) -> str:
    return hashlib.sha1(re.sub(r"\W+", "", fold(text[:600])).encode()).hexdigest()


def search(conn: sqlite3.Connection, question: str, *, course_ids: list[int] | None = None, limit: int = 5,
           prefer: set[int] | frozenset[int] = frozenset()) -> list[dict]:
    words = terms(question)
    if not words:
        return []
    extra, params = "", []
    if course_ids is not None:
        extra = f" AND chunks.course_id IN ({','.join('?' * len(course_ids))})"
        params = list(course_ids)
    hits, seen = [], set()
    queries = [("todas", " AND ".join(words))] + ([("parcial", " OR ".join(words))] if len(words) > 1 else [])
    for match_kind, match in queries:
        rows = conn.execute(
            f"""SELECT chunks.file_id, chunks.page, chunks.text,
                       snippet(chunks, 0, '«', '»', ' … ', 24) AS snippet, bm25(chunks) AS score,
                       f.display_name, f.module, f.section, f.folder, f.html_url, f.local_path, f.language,
                       c.name AS course_name, c.term_start, c.term,
                       EXISTS(SELECT 1 FROM ocr_pages o WHERE o.digest = f.digest AND o.page = chunks.page
                              AND o.text != '') AS ocr
                FROM chunks JOIN files f ON f.id = chunks.file_id JOIN courses c ON c.id = f.course_id
                WHERE chunks MATCH ?{extra} AND f.active = 1
                ORDER BY score LIMIT ?""",
            [match, *params, limit * CANDIDATES],
        ).fetchall()
        ranked = []
        for r in rows:
            old = is_old(r["folder"], r["display_name"], term_year(r["term_start"], r["course_name"], r["term"]))
            weight = MAIN_BOOK if r["file_id"] in prefer else EARLIER_SEMESTER if old else 1.0
            ranked.append((-r["score"] * weight, r, old))
        for relevance, r, old in sorted(ranked, key=lambda item: -item[0]):
            keys = {("texto", _fingerprint(r["text"])), ("pagina", normalized_name(r["display_name"]), r["page"]),
                    ("fila", r["file_id"], r["page"])}
            if keys & seen:
                continue
            seen |= keys
            hits.append({
                "archivo": r["display_name"], "archivo_id": r["file_id"], "curso": r["course_name"],
                "modulo": r["module"], "seccion": r["section"], "carpeta": r["folder"],
                "unidad": extract.UNIT.get(Path(r["local_path"] or r["display_name"]).suffix.lower().lstrip("."), "página"),
                "pagina": int(r["page"]), "fragmento": " ".join(r["snippet"].split()), "texto": r["text"],
                "url": r["html_url"], "ruta_local": r["local_path"], "idioma": r["language"] or None,
                "prioridad": "libro principal" if r["file_id"] in prefer else "semestre anterior" if old else None,
                "coincide": match_kind, "ocr": True if r["ocr"] else None, "puntaje": round(relevance, 3),
            })
            if len(hits) >= limit:
                return hits
    return hits
