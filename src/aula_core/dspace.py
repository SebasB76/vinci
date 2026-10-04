"""Past exams from ESPOL's DSpace (www.dspace.espol.edu.ec), looked for only when a bot is asked for them.

DSpace publishes some 20 000 exams, in collections named «Exámenes - <faculty>», through a REST API that needs no
login. Nothing is copied ahead of time: a search asks DSpace right then (`filtered-items` with a title regex), and
an exam is downloaded only when a bot opens it. A title is all there is to go on (no course code), typed by hand in
one of three shapes:

    EXA-2025-2S-PROGRAMACIÓN ORIENTADA A OBJETOS-2-1Par.pdf
    Examen de Programación Orientada A Objetos del 2012-2S de la 1° evaluación
    Contabilidad general I - Examen parcial II - término II - 2008

so a subject is found by the words of its name (in any order, without regard to accents or case, long words by
their stem), and a bot tries other names when one finds nothing. Many files are stored inside the multipart/form-data
envelope they were uploaded with; `unwrap` takes the document out. GET only, with no credential of any kind.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime

import requests

from aula_core import timefmt
from aula_core.canvas import USER_AGENT
from aula_core.catalog import fold
from aula_core.config import CoreConfig
from aula_core.enlaces import route, sniff

BASE = "https://www.dspace.espol.edu.ec"
HANDLE_PREFIX = "123456789"  # every item of ESPOL's DSpace
SOURCE = "DSpace ESPOL"
SHELF = -1  # course id of the exams Vinci opens; Canvas ids are positive
TIMEOUT = (10, 90)
MAX_MATCHES = 1000  # per name: more than this is not one subject
STOP_WORDS = {"de", "del", "la", "las", "el", "los", "y", "e", "a", "en", "para", "con", "al", "o", "u"}
ACCENTS = {"a": "aáAÁ", "e": "eéEÉ", "i": "iíIÍ", "o": "oóOÓ", "u": "uúüUÚÜ", "n": "nñNÑ"}
NEW = re.compile(r"^EXA-(?P<year>\d{4})-(?P<term>\d)S-(?P<subject>.+?)(?:-(?P<group>[^-]*)-(?:[123]Par|Mejora))?"
                 r"(?:\.(?:pdf|docx?|pptx?))?$", re.I)
OLD = re.compile(r"^Examen de (?P<subject>.+?) del (?P<year>\d{4})-(?P<term>\d)\s*S\b", re.I)
OLDER_SUBJECT = re.compile(r"\s*-\s*(?=ex[aá]m|lecci[oó]n|prueba)", re.I)
YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
ROMAN_TERM = re.compile(r"t[ée]rmino\s+(iii|ii|i)\b", re.I)
# Most specific first: «parcial ii» must not read as «parcial i».
EVALUATIONS = (
    ("mejoramiento", re.compile(r"mejora|\b3\s*°?\s*(?:ra)?\s*evaluaci|tercera\s+evaluaci", re.I)),
    ("3er parcial", re.compile(r"\b3\s*par\b|parcial\s+(?:iii|3)\b", re.I)),
    ("2do parcial", re.compile(r"\b2\s*par\b|parcial\s+(?:ii|2)\b|\b2\s*°?\s*(?:da)?\s*evaluaci|segunda\s+evaluaci|"
                               r"segundo\s+parcial", re.I)),
    ("1er parcial", re.compile(r"\b1\s*par\b|parcial\s+(?:i|1)\b|\b1\s*°?\s*(?:ra|era)?\s*evaluaci|primera\s+evaluaci|"
                               r"primer\s+parcial", re.I)),
)
ORDER = {"1er parcial": 1, "2do parcial": 2, "3er parcial": 3, "mejoramiento": 4}


class DSpaceError(Exception):
    pass


@dataclass(frozen=True)
class Exam:
    exam_id: int
    title: str
    subject: str
    year: int | None
    term: str | None  # «1S», «2S», «0S» (the intensive term)
    evaluation: str | None
    group: str | None  # the paralelo
    faculty: str

    @property
    def url(self) -> str:
        return page_url(self.exam_id)

    @property
    def period(self) -> str | None:
        return f"{self.year}-{self.term}" if self.year and self.term else str(self.year) if self.year else None

    def newest_first(self) -> tuple:
        return (-(self.year or 0), -int((self.term or "0S")[0]), -ORDER.get(self.evaluation or "", 0), -self.exam_id)


def page_url(exam_id: int) -> str:
    return f"{BASE}/handle/{HANDLE_PREFIX}/{exam_id}"


def faculty(collection: str | None) -> str | None:
    """«FIEC» of «Exámenes - FIEC»; None for a collection that is not exams (a thesis, a paper)."""
    folded = fold(collection)
    if not folded.startswith("examenes"):
        return None
    return re.sub(r"^ex[aá]menes\s*-?\s*", "", collection or "", flags=re.I).strip() or "ESPOL"


def parse(item: dict) -> Exam | None:
    """An exam from a DSpace item (its title, handle and collection), or None when the item is not an exam."""
    where = faculty((item.get("parentCollection") or {}).get("name"))
    prefix, _, number = str(item.get("handle") or "").partition("/")
    title = " ".join(str(item.get("name") or "").split())
    if where is None or prefix != HANDLE_PREFIX or not number.isdigit() or not title:
        return None
    group = None
    if match := NEW.match(title) or OLD.match(title):
        subject, year, term = match["subject"], int(match["year"]), f"{match['term']}S"
        group = match.groupdict().get("group") or None
    else:
        subject = OLDER_SUBJECT.split(title, maxsplit=1)[0]
        years = YEAR.findall(title)
        year = int(years[-1]) if years else None
        roman = ROMAN_TERM.search(title)
        term = f"{len(roman[1])}S" if roman else None
    evaluation = next((name for name, pattern in EVALUATIONS if pattern.search(title)), None)
    return Exam(int(number), title, subject.strip(" -"), year, term, evaluation, group, where)


def _word(word: str) -> str:
    stem = word[:-1] if len(word) >= 6 else word  # «orientada» also finds «orientado», «objetos» «objeto»
    return "".join(f"[{ACCENTS[c]}]" if c in ACCENTS else f"[{c}{c.upper()}]" if c.isalpha() else re.escape(c)
                   for c in stem)


def pattern(name: str) -> str | None:
    """A title regex that finds every word of `name` in any order. DSpace runs it in the database, so the accents
    and the case are spelled out instead of trusting its collation."""
    words = [w for w in re.findall(r"[a-z0-9]+", fold(name)) if w not in STOP_WORDS and (len(w) > 1 or w.isdigit())]
    if not words:
        return None
    return "(?i)^(?=.*[eE][xX][aA])" + "".join(f"(?=.*{_word(w)})" for w in words) + ".*"


def _session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # no .netrc login and no proxy credentials from the environment
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return session


def _get(session: requests.Session, cfg: CoreConfig, path: str, **kwargs) -> requests.Response:
    try:
        resp = session.get(route(BASE + path, cfg), timeout=TIMEOUT, allow_redirects=False, **kwargs)
    except requests.RequestException as exc:
        raise DSpaceError(f"DSpace no responde ({type(exc).__name__})") from None
    if resp.status_code != 200:
        resp.close()
        raise DSpaceError(f"DSpace respondió {resp.status_code}")
    return resp


def search(cfg: CoreConfig, names: list[str]) -> tuple[list[Exam], dict[str, int]]:
    """The exams whose title carries every word of one of `names`, and how many each name found (-1: too general)."""
    found: dict[int, Exam] = {}
    counts: dict[str, int] = {}
    session = _session()
    for name in names:
        regex = pattern(name)
        if regex is None:
            counts[name] = 0
            continue
        data = _get(session, cfg, "/rest/filtered-items", params=[
            ("query_field[]", "dc.title"), ("query_op[]", "matches"), ("query_val[]", regex),
            ("limit", MAX_MATCHES), ("expand", "parentCollection")]).json()
        exams = [exam for exam in map(parse, data.get("items") or []) if exam]
        counts[name] = -1 if (data.get("unfiltered-item-count") or 0) >= MAX_MATCHES else len(exams)
        found.update((exam.exam_id, exam) for exam in exams)
    return sorted(found.values(), key=Exam.newest_first), counts


def unwrap(body: bytes) -> bytes:
    """The document inside the multipart/form-data envelope many DSpace files were stored with, else the body."""
    if not body.lstrip(b"\r\n").startswith(b"--"):
        return body
    start, end = body.find(b"\r\n\r\n"), body.rstrip(b"\r\n").rfind(b"\r\n--")
    return body[start + 4:end] if 0 <= start < end else body


def fetch(cfg: CoreConfig, exam_id: int) -> tuple[Exam, bytes, str]:
    """(the exam, its document, «pdf» / «docx» / «pptx»), downloaded from DSpace."""
    session = _session()
    try:
        item = _get(session, cfg, f"/rest/handle/{HANDLE_PREFIX}/{exam_id}",
                    params={"expand": "bitstreams,parentCollection"}).json()
    except (DSpaceError, ValueError):
        raise DSpaceError(f"no encuentro el examen {exam_id} en DSpace") from None
    exam = parse(item or {})
    if exam is None:
        raise DSpaceError(f"{exam_id} no es un examen de DSpace (no está en una colección de exámenes)")
    originals = [b for b in item.get("bitstreams") or [] if b.get("bundleName") == "ORIGINAL" and b.get("retrieveLink")]
    if not originals:
        raise DSpaceError("ese examen no tiene archivo en DSpace")
    stream = max(originals, key=lambda b: b.get("sizeBytes") or 0)
    cap = int(cfg.max_file_mb * 1024 * 1024)
    if (stream.get("sizeBytes") or 0) > cap:
        raise DSpaceError(f"pesa más de {cfg.max_file_mb:g} MB, el tope (material.tamano_maximo_mb en config.toml)")
    body = bytearray()
    with _get(session, cfg, stream["retrieveLink"].removeprefix(BASE), stream=True) as resp:
        try:
            for chunk in resp.iter_content(65536):
                body += chunk
                if len(body) > cap:
                    raise DSpaceError(f"pesa más de {cfg.max_file_mb:g} MB, el tope")
        except requests.RequestException as exc:
            raise DSpaceError(f"se cortó la descarga ({type(exc).__name__})") from None
    document = unwrap(bytes(body))
    kind = sniff(document, "")
    if document.startswith(b"\xd0\xcf\x11\xe0"):
        raise DSpaceError("es un Word viejo (.doc) y solo leo PDF, DOCX y PPTX")
    if kind not in ("pdf", "docx", "pptx"):
        raise DSpaceError("su archivo no es PDF, DOCX ni PPTX")
    return exam, document, kind


def shelf(conn: sqlite3.Connection, now: datetime) -> int:
    """The course the exams Vinci opens belong to (a subject bot keeps them in its own): an inactive one, so no
    list of courses, pending work or material shows it."""
    conn.execute("INSERT OR IGNORE INTO courses(id, name, course_code, active, first_seen) VALUES (?, ?, NULL, 0, ?)",
                 (SHELF, "Exámenes de DSpace (ESPOL)", timefmt.iso(now)))
    conn.commit()
    return SHELF
