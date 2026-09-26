"""The class schedule: `horario.toml` in the data folder, hand-editable.

    [[clase]]
    materia = "ESTG1034"     # código de la materia
    dia = "lunes"            # lunes … sábado
    inicio = "10:00"         # HH:MM, 24 h, hora de Ecuador
    fin = "12:00"
    aula = "A001 (bloque 9M)"
    paralelo = "5"           # opcional

Vinci fills it from a screenshot of the ESPOL schedule, but only after the captain
confirms the extracted classes (see `botones`); every write goes through `validate`.
The subject bots use it to send their brief before each class; a class that is not
in the file never gets a brief.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aula_core.config import ConfigError, CoreConfig
from aula_core.queries import fold
from espol_bot import tomlfile
from espol_bot.materias import CODE_RE, Subject

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MAX_CLASSES = 60

HEADER = """\
Tu horario de clases. Cada bot de materia te manda su brief unos minutos antes de cada clase
(config.toml → [clases] brief_minutos_antes). Vinci lo llena desde una captura de tu horario y
solo lo guarda cuando tú lo confirmas; también puedes editarlo a mano.
Una sección [[clase]] por bloque de clase:
  materia  código de la materia (ej. "ESTG1034")
  dia      lunes, martes, miércoles, jueves, viernes o sábado
  inicio   hora de inicio, HH:MM en 24 h (hora de Ecuador)
  fin      hora de fin, HH:MM
  aula     aula o lugar (texto libre)
  paralelo opcional"""


@dataclass(frozen=True)
class Clase:
    materia: str
    dia: int            # 0 = lunes
    inicio: time
    fin: time
    aula: str = ""
    paralelo: str = ""

    def as_row(self) -> dict:
        return {"materia": self.materia, "dia": DAYS[self.dia], "inicio": f"{self.inicio:%H:%M}",
                "fin": f"{self.fin:%H:%M}", "aula": self.aula, "paralelo": self.paralelo or None}

    def as_json(self) -> dict:
        return {k: v for k, v in self.as_row().items() if v is not None}

    def starts_on(self, day: date, tz: ZoneInfo) -> datetime:
        return datetime.combine(day, self.inicio, tzinfo=tz)

    def ends_on(self, day: date, tz: ZoneInfo) -> datetime:
        return datetime.combine(day, self.fin, tzinfo=tz)


def path(cfg: CoreConfig) -> Path:
    return cfg.data_dir / "horario.toml"


def _day(value) -> int | None:
    if isinstance(value, int) and 1 <= value <= 7:
        return value - 1
    text = fold(str(value)).strip()
    for i, name in enumerate(DAYS):
        if text and fold(name).startswith(text[:3]) and fold(name).startswith(text):
            return i
    return None


def _time(value) -> time | None:
    if isinstance(value, time):
        return value
    match = re.fullmatch(r"\s*(\d{1,2})[:h.](\d{2})\s*", str(value))
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        return None
    return time(int(match[1]), int(match[2]))


def validate(rows: list[dict], subjects: list[Subject] | None = None) -> tuple[list[Clase], list[str], list[str]]:
    """Rows (from the file, the model, or a proposal) → (classes, errors, warnings).
    Any error means nothing may be saved."""
    errors, warnings, classes = [], [], []
    known = {s.code for s in subjects or []}
    if not isinstance(rows, list) or not rows:
        return [], ["El horario no tiene ninguna clase."], []
    if len(rows) > MAX_CLASSES:
        return [], [f"Demasiadas clases ({len(rows)}); el máximo es {MAX_CLASSES}."], []
    for n, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"Clase {n}: formato inválido.")
            continue
        before = len(errors)
        code = str(row.get("materia", "")).strip().upper()
        day, start, end = _day(row.get("dia", "")), _time(row.get("inicio", "")), _time(row.get("fin", ""))
        label = f"Clase {n} ({code or 'sin materia'})"
        if not CODE_RE.fullmatch(code):
            errors.append(f"{label}: «materia» debe ser un código como ESTG1034.")
        elif known and code not in known:
            warnings.append(f"{label}: {code} no está en tus bots de materia.")
        if day is None:
            errors.append(f"{label}: día inválido {row.get('dia')!r} (usa lunes … sábado).")
        if start is None or end is None:
            errors.append(f"{label}: «inicio» y «fin» deben ser horas HH:MM.")
        elif end <= start:
            errors.append(f"{label}: termina ({end:%H:%M}) antes de empezar ({start:%H:%M}).")
        elif datetime.combine(date.min, end) - datetime.combine(date.min, start) > timedelta(hours=6):
            errors.append(f"{label}: dura más de 6 horas; revisa la hora de fin.")
        aula = " ".join(str(row.get("aula") or "").split())[:80]
        paralelo = " ".join(str(row.get("paralelo") or "").split())[:20]
        if len(errors) == before:
            clase = Clase(code, day, start, end, aula, paralelo)
            if clase not in classes:
                classes.append(clase)
    classes.sort(key=lambda c: (c.dia, c.inicio, c.materia))
    for a, b in zip(classes, classes[1:]):
        if a.dia == b.dia and b.inicio < a.fin:
            warnings.append(f"{DAYS[a.dia].capitalize()}: {a.materia} ({a.inicio:%H:%M}–{a.fin:%H:%M}) y "
                            f"{b.materia} ({b.inicio:%H:%M}–{b.fin:%H:%M}) se cruzan.")
    return classes, errors, warnings


def load(cfg: CoreConfig) -> list[Clase]:
    """The saved schedule; [] when there is none yet. A broken file raises ConfigError."""
    file = path(cfg)
    if not file.exists():
        return []
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file} tiene un error de formato: {exc}") from exc
    classes, errors, _ = validate(raw.get("clase", []))
    if errors:
        raise ConfigError(f"{file}: " + " ".join(errors))
    return classes


def save(cfg: CoreConfig, classes: list[Clase], now: datetime) -> Path | None:
    """Write horario.toml (keeping a copy of the previous one); returns the backup path."""
    file = path(cfg)
    backup = None
    if file.exists():
        backup = file.with_name(f"horario.anterior-{now:%Y%m%d-%H%M%S}.toml")
        shutil.copy2(file, backup)
    tomlfile.write_atomic(file, tomlfile.render(HEADER, "clase", [c.as_row() for c in classes]))
    return backup


def for_subject(classes: list[Clase], code: str) -> list[Clase]:
    return [c for c in classes if c.materia == code]


def occurrences(classes: list[Clase], start: datetime, end: datetime, tz: ZoneInfo,
                code: str | None = None) -> list[tuple[datetime, Clase]]:
    """Every class start in [start, end), in order."""
    found = []
    day = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    while day <= last:
        for c in classes:
            if (code is None or c.materia == code) and c.dia == day.weekday():
                begins = c.starts_on(day, tz)
                if start <= begins < end:
                    found.append((begins, c))
        day += timedelta(days=1)
    return sorted(found, key=lambda item: (item[0], item[1].materia))


def previous(classes: list[Clase], code: str, before: datetime, tz: ZoneInfo) -> tuple[datetime, Clase] | None:
    """The most recent class of `code` that started before `before` (up to 3 weeks back)."""
    past = occurrences(classes, before - timedelta(days=21), before, tz, code)
    return past[-1] if past else None


def names(subjects: list[Subject]) -> dict[str, str]:
    return {s.code: s.name for s in subjects}


def render(classes: list[Clase], subjects: list[Subject], *, html: bool = True) -> str:
    """The schedule grouped by weekday, for Telegram (HTML) or the terminal."""
    from html import escape

    def e(text: str) -> str:
        return escape(text, quote=False) if html else text

    label = names(subjects)
    blocks = []
    for day in range(7):
        todays = [c for c in classes if c.dia == day]
        if not todays:
            continue
        head = DAYS[day].capitalize()
        lines = [f"<b>{head}</b>" if html else head]
        for c in todays:
            name = label.get(c.materia, "")
            what = f"{name} ({c.materia})" if name else c.materia
            extra = f" · paralelo {c.paralelo}" if c.paralelo else ""
            room = f" · {c.aula}" if c.aula else ""
            lines.append(f"• {c.inicio:%H:%M}–{c.fin:%H:%M} {e(what)}{e(room)}{e(extra)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "(sin clases)"


def to_json(classes: list[Clase]) -> list[dict]:
    return [c.as_json() for c in classes]
