"""ESPOL's official calendar for undergraduates (holidays, the end of classes, exam weeks, holidays between terms,
when each term starts), read from the university's public page into a copy every Vinci shares.

The page is a table of activities and dates in Spanish («Feriado de Navidad | jueves, 25 de diciembre de 2026»,
«Exámenes finales | del 12 al 16 de enero de 2027»). The parser reads every table of the page and keeps each row that
has a date: a row with one cell is a heading for the rows below it (a term), and a row with several date columns
gives one entry per column, named by its header. The captain's maintenance reads it once a day; a failed read keeps
the copy it had, so a down site never empties it.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from aula_core import timefmt
from aula_core.catalog import fold
from aula_core.enlaces import route
from espol_bot import academic_portal
from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

URL = "https://www.espol.edu.ec/es/vida-politecnica/calendario-grado"
COPY = "calendario-espol.json"
REFRESH = timedelta(hours=24)
RETRY = timedelta(hours=3)  # after a failed read
TIMEOUT = (10, 30)
MAX_ENTRIES = 400

MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "set": 9,
          "oct": 10, "nov": 11, "dic": 12}
MONTH = r"(ene\w*|feb\w*|mar\w*|abr\w*|may\w*|jun\w*|jul\w*|ago\w*|sep\w*|set\w*|oct\w*|nov\w*|dic\w*)"
YEAR = r"(?:\s*(?:de|del|,|-|/)?\s*(\d{4}))?"
# «del 5 al 9 de enero de 2027», «5 - 9 ene 2027»: two days of one month
SAME_MONTH = re.compile(rf"\b(\d{{1,2}})\s*(?:al|a|-|–|y)\s*(\d{{1,2}})\s*(?:de\s+|-|/)?{MONTH}\b{YEAR}")
# «12 de enero de 2027», «12-ene-2027», «12 ene»
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s*(?:de\s+|-|/)?\s*{MONTH}\b{YEAR}")
NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")
YEARS = re.compile(r"\b(20\d\d)\s*[-–/]\s*(20\d\d)\b")


def _year(month: int, explicit: str | None, years: tuple[int, int]) -> int:
    """A date with no year belongs to the academic year: May to December the first, January to April the second."""
    if explicit:
        return int(explicit)
    return years[0] if month >= 5 else years[1]


def dates(text: str, years: tuple[int, int]) -> tuple[date, date] | None:
    """The first date or range of dates in a cell, as (start, end)."""
    low = fold(text)
    found: list[tuple[int, date]] = []
    try:
        for m in SAME_MONTH.finditer(low):
            month = MONTHS[m[3][:3]]
            y = _year(month, m[4], years)
            found += [(m.start(), date(y, month, int(m[1]))), (m.start() + 1, date(y, month, int(m[2])))]
        taken = {m.span() for m in SAME_MONTH.finditer(low)}
        for m in DAY_MONTH.finditer(low):
            if any(a <= m.start() < b for a, b in taken):
                continue
            month = MONTHS[m[2][:3]]
            found.append((m.start(), date(_year(month, m[3], years), month, int(m[1]))))
        for m in NUMERIC.finditer(low):
            found.append((m.start(), date(int(m[3]), int(m[2]), int(m[1])) if m[1] else
                          date(int(m[4]), int(m[5]), int(m[6]))))
    except ValueError:  # «31 de febrero»: not a date
        return None
    if not found:
        return None
    found.sort()
    start, end = found[0][1], found[-1][1] if len(found) > 1 else found[0][1]
    if end < start and end.month < start.month:  # «28 de diciembre al 2 de enero» with no years
        end = end.replace(year=start.year + 1)
    return (start, end) if end >= start else (start, start)


def parse(html: str, today: date) -> list[dict]:
    """[{"what", "start", "end"}] from every table of the page, in the page's order."""
    page = academic_portal.parse(html)
    text = " ".join(page.lines)
    if m := YEARS.search(text):
        years = (int(m[1]), int(m[2]))
    else:
        first = today.year if today.month >= 5 else today.year - 1
        years = (first, first + 1)
    entries = []
    for table in page.tables:
        if table.nested:
            continue
        heads = table.header_rows
        header = table.rows[heads - 1] if heads else []
        section = table.caption.strip()
        for row in table.rows[heads:]:
            cells = [c.strip() for c in row if c and c.strip()]
            if not cells:
                continue
            spans = [(i, dates(c, years)) for i, c in enumerate(row)]
            dated = [(i, d) for i, d in spans if d]
            if not dated:
                if len(set(cells)) == 1:  # a heading row (a colspan repeats its text): the term below it
                    section = cells[0]
                continue
            what = " — ".join(c.strip() for i, c in enumerate(row) if c.strip() and not dates(c, years))
            what = f"{section}: {what}" if section and what and fold(section) not in fold(what) else what or section
            for i, (start, end) in dated:
                label = header[i].strip() if len(dated) > 1 and i < len(header) and header[i].strip() else ""
                entries.append({"what": f"{what} ({label})" if label else what, "start": start.isoformat(),
                                "end": end.isoformat()})
    return entries[:MAX_ENTRIES]


def copy_path(cfg: BotConfig) -> Path:
    """In the captain's data folder, shared by every friend's Vinci (amigos/<slug>/ lives under it)."""
    data_dir = cfg.core.data_dir
    home = data_dir.parent.parent if data_dir.parent.name == "amigos" else data_dir
    return home / COPY


def load(cfg: BotConfig) -> dict | None:
    try:
        return json.loads(copy_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def refresh(cfg: BotConfig, now: datetime, *, force: bool = False) -> bool:
    """Reads the page again when the copy is a day old (or `force`); True when it saved a new copy."""
    copy = load(cfg) or {}
    if not force:
        last = max(copy.get("read_at") or "", copy.get("tried_at") or "")
        wait = REFRESH if (copy.get("read_at") or "") >= (copy.get("tried_at") or "") else RETRY
        if last and timefmt.parse(last) > now - wait:
            return False
    today = now.astimezone(cfg.core.tz).date()
    try:
        response = requests.get(route(URL, cfg.core), timeout=TIMEOUT, headers={"User-Agent": academic_portal.USER_AGENT,
                                                                "Accept-Language": "es"})
        response.raise_for_status()
        entries = parse(response.text, today)
        if not entries:
            raise ValueError("la página no trae ninguna fecha")
    except (requests.RequestException, ValueError) as exc:
        log.warning("calendario de ESPOL: no pude leerlo (%s); sigo con la copia anterior", exc)
        _write(copy_path(cfg), {**copy, "tried_at": timefmt.iso(now), "error": str(exc)[:200]})
        return False
    _write(copy_path(cfg), {"url": URL, "read_at": timefmt.iso(now), "entries": entries})
    return True


def between(copy: dict | None, first: date, last: date) -> list[dict]:
    """The entries that touch [first, last], by start date."""
    found = [e for e in (copy or {}).get("entries") or []
             if e["start"] <= last.isoformat() and e["end"] >= first.isoformat()]
    return sorted(found, key=lambda e: e["start"])


def search(copy: dict | None, words: str) -> list[dict]:
    terms = fold(words).split()
    return [e for e in (copy or {}).get("entries") or [] if all(t in fold(e["what"]) for t in terms)]


def when(entry: dict) -> str:
    """«jue 25 dic» or «lun 12 ene → vie 16 ene»."""
    def one(day: str) -> str:
        d = date.fromisoformat(day)
        return f"{timefmt.DAYS[d.weekday()]} {d.day} {timefmt.MONTHS[d.month - 1]}"
    return one(entry["start"]) if entry["start"] == entry["end"] else f"{one(entry['start'])} → {one(entry['end'])}"
