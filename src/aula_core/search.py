"""Full-text search over indexed course material (SQLite FTS5, BM25 ranking)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from aula_core import extract
from aula_core.queries import fold

STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada como con contra cual cuales cuando
de del desde donde dos el ella ellas ellos en entre era es esa esas ese eso esos esta estan estas este esto estos
explica explicame fue ha hay la las le les lo los mas me mi mis muy nada ni no nos o os otra otro para pero poco
por porque que quien se sea segun ser si sin sobre son su sus tambien te tiene tienen todo todos tu tus un una uno
unos y ya yo dame dime resume resumen resumeme cual cuales hazme haz genera preguntas pregunta tema capitulo
the of and is what how
""".split())


def build_match(question: str) -> str | None:
    """Turn a natural question into an FTS5 query: meaningful words OR'ed, with a
    light prefix match so 'derivadas' also finds 'derivada' and 'derivación'."""
    terms = []
    for word in re.findall(r"\w+", fold(question)):
        if word in STOPWORDS or len(word) < 3:
            continue
        if len(word) > 5:
            terms.append(f'"{word[:max(5, len(word) - 2)]}"*')
        else:
            terms.append(f'"{word}"')
    return " OR ".join(dict.fromkeys(terms)) or None


def search(conn: sqlite3.Connection, question: str, *, course_ids: list[int] | None = None, limit: int = 5) -> list[dict]:
    match = build_match(question)
    if not match:
        return []
    extra, params = "", []
    if course_ids is not None:
        extra = f" AND chunks.course_id IN ({','.join('?' * len(course_ids))})"
        params = list(course_ids)
    rows = conn.execute(
        f"""SELECT chunks.file_id, chunks.page, chunks.text,
                   snippet(chunks, 0, '«', '»', ' … ', 24) AS snippet, bm25(chunks) AS score,
                   f.display_name, f.module, f.html_url, f.local_path, c.name AS course_name
            FROM chunks JOIN files f ON f.id = chunks.file_id JOIN courses c ON c.id = f.course_id
            WHERE chunks MATCH ?{extra} AND f.active = 1
            ORDER BY score LIMIT ?""",
        [match, *params, limit],
    ).fetchall()
    return [{
        "archivo": r["display_name"], "archivo_id": r["file_id"], "curso": r["course_name"], "modulo": r["module"],
        "unidad": extract.UNIT.get(Path(r["display_name"]).suffix.lower().lstrip("."), "página"),
        "pagina": int(r["page"]), "fragmento": " ".join(r["snippet"].split()), "texto": r["text"],
        "url": r["html_url"], "ruta_local": r["local_path"], "puntaje": round(-r["score"], 3),
    } for r in rows]
