"""ESPOL's Académico (www.academico.espol.edu.ec): signing in, reading its pages, and the copy Vinci keeps.

The portal is ASP.NET Web Forms with no API: every page is a form whose hidden fields (__VIEWSTATE,
__EVENTVALIDATION, BotDetect's CAPTCHA id) must go back with the next post, from the same cookies. Signing in takes
two posts to login.aspx: the user name first, then the password with the CAPTCHA that the second page shows. `Portal`
holds one requests session for the whole sign-in and the reading after it, and is thrown away at the end.

The pages hand their data out as HTML tables, so `extract` keeps each table as headers and rows, plus the
«label: value» lines around them (a credit count) and the year and term each page asked for. The history also becomes
one record per subject with its grade and its status sorted out (approved, failed, credited, in progress). The grades,
the class timetable and the exam timetable show nothing until «Consultar» is pressed with a year and a term; the exam
timetable is the one page that comes with them filled in, so its year and term are the ones the other two ask for. The
grades table has two header rows; each subject's theory/practice weights are only in the arguments of a JavaScript
call, `Presentar(...)`. Both timetables are a grid of half hours (without the empty ones) whose classes span rows.

The GPA, the progress and the credits left are on «Información General», in label/value rows next to the student's
ID, ethnic group and photo: only the academic rows are kept (`GENERAL_FACTS`). What is left of the degree, subject by
subject, needs the curriculum, which this does not read yet.

The copy lives in <data>/academico.json (0600), with when it was read and the term it belongs to. It holds no
credential and no cookie.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import requests

from aula_core import timefmt
from aula_core.catalog import fold
from aula_core.enlaces import route
from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

COPY = "academico.json"
LOGIN = "/login.aspx"
PAGES = "/UI/InformacionAcademica/"
TIMEOUT = (10, 60)
MAX_CAPTCHA = 200_000
MAX_ROWS = 400
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 "
              "espol-academic-bot")
# (key, page, short name, while reading it). The exam timetable goes before the two pages that ask for its year and
# term.
SECTIONS = (
    ("general", "informaciongeneral.aspx", "promedio y avance", "tu promedio y tu avance"),
    ("historial", "historiaacademica_.aspx", "historial", "tu historial académico"),
    ("creditos", "CreditosCarrera.aspx", "créditos", "tus créditos y requisitos"),
    ("examenes", "horarioExView.aspx", "exámenes", "tu horario de exámenes"),
    ("calificaciones", "calificacionesbusqueda_.aspx", "calificaciones", "tus calificaciones del período"),
    ("horario", "horarioView.aspx", "horario", "tu horario de clases"),
)
# Folded header → the history record's field.
COLUMNS = {
    "code": ("codigo", "cod", "cod materia", "codigo materia", "sigla"),
    "name": ("materia", "asignatura", "nombre", "nombre materia", "descripcion"),
    "year": ("ano", "anio", "year"),
    "term": ("ano termino", "termino", "periodo", "semestre", "pao"),  # the history's «Año Termino»: 2024-1
    "grade": ("prom", "nota", "nota final", "calificacion", "promedio", "calificacion final"),
    "status": ("estado", "observacion", "situacion"),
    "attempt": ("vez", "veces", "intento", "no vez", "num vez"),
    "credits": ("creditos", "cred", "creditos materia"),
}
EXAM_KINDS = re.compile(r"parcial|final|mejora", re.I)
SEARCH_BUTTON = re.compile(r"consult|busca|ver|mostrar|cargar", re.I)
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
# Presentar(nombre, nota1, nota2, nota3, nota2practica, subpromedio, porcentajeteorico, porcentajepractico, promedio)
BREAKDOWN = ("subject", "partial", "final", "improvement", "practical", "theory_subtotal", "theory_weight",
             "practical_weight", "average")
# Labels of the student's identity, never kept: the credits page shows the matrícula and name above its tables.
PERSONAL = re.compile(r"matr[ií]cula|identificaci|c[eé]dula|nombre|[eé]tnic|sanci[oó]n|\bise\b", re.I)
# The rows of «Información General» worth keeping: not the ID, the name, the ethnic group, the sanctions or the photo.
# Not «Año-Término» (2024-1S): the page does not say which term that is, and it is not the current one.
GENERAL_FACTS = re.compile(r"promedio|cr[eé]dito|materias|nivel|avance|carrera|reprobad|regular", re.I)
PRESENT_CALL = re.compile(r"(?<!function )\bPresentar\s*\(([^()]*)\)")
JS_ARG = re.compile(r"""\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"|([^,]*?))\s*(?:,|$)""")


class PortalError(Exception):
    """The portal did not answer as expected: down, changed, or a session that ended."""


class LoginRefused(PortalError):
    """The portal turned the sign-in down; `message` is its own words (a wrong CAPTCHA, a wrong password)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# -- reading a page ----------------------------------------------------------------------------


@dataclass
class Table:
    id: str = ""
    caption: str = ""
    rows: list[list[str]] = field(default_factory=list)
    header_rows: int = 0  # leading rows of headers only: the grades have two (Paralelo over Teórico and Práctico)
    nested: bool = False  # a layout table: one of its cells holds another table
    carried: dict[int, list] = field(default_factory=dict)  # column → [rows still to fill, text]: a rowspan cell


@dataclass
class Select:
    name: str
    options: list[tuple[str, str]] = field(default_factory=list)  # (value, text)
    selected: str | None = None

    def value(self) -> str:
        return self.selected if self.selected is not None else (self.options[0][0] if self.options else "")

    def text(self) -> str:
        return next((t for v, t in self.options if v == self.value()), "")


@dataclass
class Form:
    action: str = ""
    inputs: dict[str, str] = field(default_factory=dict)       # hidden and text fields with their values
    types: dict[str, str] = field(default_factory=dict)
    selects: dict[str, Select] = field(default_factory=dict)
    buttons: dict[str, str] = field(default_factory=dict)      # submit name → value

    def field(self, pattern: str) -> str | None:
        """The name of the field or button whose name ends like `pattern` (ASP.NET prefixes ctl00$contenido$)."""
        regex = re.compile(pattern, re.I)
        return next((n for n in [*self.inputs, *self.buttons, *self.selects] if regex.search(n)), None)

    def data(self, values: dict[str, str] | None = None, *, button: str | None = None) -> dict[str, str]:
        """What a browser posts: every field as it stands, the selects' choices, then `values`, with the button
        pressed."""
        data = {name: value for name, value in self.inputs.items() if self.types.get(name) not in ("checkbox", "radio")}
        data.update({name: select.value() for name, select in self.selects.items()})
        data.update(values or {})
        if button:
            data[button] = self.buttons.get(button, "")
        return data


class _Page(HTMLParser):
    """One pass over a page: its first form, its tables (rows of the innermost table only), its spans' and labels'
    text by id, its images, and its visible text in lines."""

    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "form", "span", "label", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.form: Form | None = None
        self._in_form = 0
        self.tables: list[Table] = []
        self._tables: list[Table] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._rowspan = self._colspan = 1
        self._header_row = False
        self._all_th = True
        self._select: Select | None = None
        self._option: tuple[str, bool] | None = None
        self._option_text: list[str] = []
        self.labels: dict[str, str] = {}
        self._label: tuple[str, list[str]] | None = None
        self.images: list[dict[str, str]] = []
        self.lines: list[str] = []
        self._line: list[str] = []
        self._skip = 0
        self._caption: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag in self.BLOCK:
            self._flush()
        if tag == "form" and self.form is None:
            self.form = Form(action=a.get("action", ""))
            self._in_form = 1
        elif tag == "input" and self.form is not None and self._in_form:
            name, kind = a.get("name"), a.get("type", "text").lower()
            if name and kind in ("submit", "image"):
                self.form.buttons[name] = a.get("value", "")
            elif name and kind not in ("button", "reset", "file") and (kind not in ("checkbox", "radio")
                                                                         or "checked" in a):
                self.form.inputs[name], self.form.types[name] = a.get("value", ""), kind
        elif tag == "select" and self.form is not None:
            self._select = Select(a.get("name", ""))
        elif tag == "option" and self._select is not None:
            self._option, self._option_text = (a.get("value", ""), "selected" in a), []
        elif tag == "textarea" and self.form is not None and a.get("name"):
            self.form.inputs[a["name"]] = ""
        elif tag == "table":
            if self._tables:
                self._tables[-1].nested = True
            self._tables.append(Table(id=a.get("id", "")))
        elif tag == "caption" and self._tables:
            self._caption = []
        elif tag == "tr" and self._tables:
            self._row, self._header_row = [], "header" in (a.get("class", "") + a.get("style", "")).lower()
            self._all_th = True
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._rowspan = int(a["rowspan"]) if a.get("rowspan", "").isdigit() else 1
            self._colspan = int(a["colspan"]) if a.get("colspan", "").isdigit() else 1
            self._all_th = self._all_th and tag == "th"
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")  # «Año<br>Término», «Computación<br>Activo»
        elif tag in ("span", "label") and a.get("id"):
            self._label = (a["id"], [])
        elif tag == "img":
            self.images.append(a)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "form":
            self._in_form = 0
        elif tag == "option" and self._select is not None and self._option is not None:
            value, chosen = self._option
            text = " ".join("".join(self._option_text).split())
            self._select.options.append((value or text, text))
            if chosen:
                self._select.selected = value or text
            self._option = None
        elif tag == "select" and self._select is not None:
            if self._select.name:
                self.form.selects[self._select.name] = self._select
            self._select = None
        elif tag == "caption" and self._caption is not None and self._tables:
            self._tables[-1].caption = " ".join("".join(self._caption).split())
            self._caption = None
        elif tag in ("td", "th") and self._cell is not None and self._row is not None and self._tables:
            self._carry(self._tables[-1])
            text = " ".join("".join(self._cell).split())
            for _ in range(min(self._colspan, 50)):
                if self._rowspan > 1:
                    self._tables[-1].carried[len(self._row)] = [self._rowspan - 1, text]
                self._row.append(text)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._tables:
            table = self._tables[-1]
            self._carry(table, trailing=True)
            if any(self._row):
                if (self._header_row or self._all_th) and len(table.rows) == table.header_rows:
                    table.header_rows += 1
                table.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._tables:
            self.tables.append(self._tables.pop())
            self._row = self._cell = None
        elif tag in ("span", "label") and self._label is not None:
            self.labels[self._label[0]] = " ".join("".join(self._label[1]).split())
            self._label = None
        if tag in self.BLOCK:
            self._flush()

    def handle_data(self, data):
        if self._skip:
            return
        if self._option is not None:
            self._option_text.append(data)
            return
        if self._cell is not None:
            self._cell.append(data)
        if self._caption is not None:
            self._caption.append(data)
        if self._label is not None:
            self._label[1].append(data)
        self._line.append(data)

    def _carry(self, table: Table, trailing: bool = False) -> None:
        """The cells an earlier row's rowspan covers, at their column (the timetables' classes span several rows)."""
        while len(self._row) in table.carried or (trailing and any(c > len(self._row) for c in table.carried)):
            column = len(self._row)
            if column not in table.carried:
                self._row.append("")
                continue
            span = table.carried[column]
            self._row.append(span[1])
            span[0] -= 1
            if not span[0]:
                del table.carried[column]

    def _flush(self):
        line = " ".join("".join(self._line).split())
        if line:
            self.lines.append(line)
        self._line = []


def parse(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    page._flush()
    return page


def data_tables(page: _Page) -> list[dict]:
    """The tables that hold data, not layout: a header and at least one row, no table inside, and a figure somewhere
    in the rows (a code, a grade, an hour). Without that it is the year/term form or the grades page's empty dialog.
    «Label:» rows are a card, not data (the student's matrícula and name on the credits page): `rows` reads those.
    Two header rows become one (Paralelo Teórico, Exámenes 1)."""
    found = []
    for table in page.tables:
        rows = table.rows
        if table.nested or len(rows) < 2 or max(len(r) for r in rows) < 2 or rows[0][0].endswith(":"):
            continue
        heads = max(table.header_rows, 1)
        header = [" ".join(dict.fromkeys(r[i] for r in rows[:heads] if i < len(r) and r[i]))
                  for i in range(max(len(r) for r in rows[:heads]))]
        body = rows[heads:]
        if not any(re.search(r"\d", c) for r in body for c in r):
            continue
        found.append({"id": table.id, "titulo": table.caption, "columnas": header,
                      "filas": [dict(zip(header, r + [""] * (len(header) - len(r)))) if len(r) <= len(header) else
                                {**dict(zip(header, r)), "extra": " | ".join(r[len(header):])} for r in body[:MAX_ROWS]]})
    return found


FACT_RE = re.compile(r"^([^:]{3,60}?)\s*:\s*(\S.{0,120})$")


def facts(page: _Page) -> dict[str, str]:
    """The page's «label: value» lines (Promedio general: 8,35; Créditos aprobados: 120), as the portal wrote them."""
    found: dict[str, str] = {}
    lines = page.lines
    cells = {cell for table in page.tables if not table.nested for row in table.rows for cell in row}
    for i, line in enumerate(lines):
        match = FACT_RE.match(line)
        if match and line in cells:  # a table's cell (FÍSICA: MECÁNICA): the table already has it
            continue
        if match:
            found.setdefault(match[1].strip(), match[2].strip())
        elif line.endswith(":") and 2 < len(line) < 62 and i + 1 < len(lines) and re.search(r"\d", lines[i + 1]):
            found.setdefault(line[:-1].strip(), lines[i + 1][:120])  # «Promedio general:» with its figure apart
    return {k: v for k, v in found.items()
            if not k.lower().startswith(("http", "javascript")) and not PERSONAL.search(k)}


def rows(page: _Page) -> dict[str, str]:
    """The «Label: | value» rows of the page's two-column tables (Información General), as the portal wrote them."""
    found: dict[str, str] = {}
    for table in page.tables:
        for row in table.rows:
            if len(row) == 2 and row[0].endswith(":") and row[1]:
                found.setdefault(row[0][:-1].strip(), row[1])
    return found


def chosen(form: Form | None) -> dict[str, str]:
    """The year and term the page asked for (its txtAnio and txtTermino boxes) and what each drop-down has selected
    (the kind of exam), by what it is for."""
    if form is None:
        return {}
    picked = {}
    for key, pattern in (("anio", r"txtanio$"), ("termino", r"txttermino$")):
        name = form.field(pattern)
        if name in form.inputs and form.inputs[name].strip():
            picked[key] = form.inputs[name].strip()
    for name, select in form.selects.items():
        label = fold(re.sub(r"^.*\$", "", name))
        key = ("anio" if re.search(r"an(i)?o|year", label) else "termino" if re.search(r"term|period", label)
               else "tipo" if EXAM_KINDS.search(" ".join(t for _, t in select.options)) else label)
        picked[key] = select.text()
    return picked


def _header_key(header: str) -> str | None:
    plain = re.sub(r"[^a-z0-9 ]", "", fold(header)).strip()
    plain = re.sub(r"\s+", " ", plain)
    for key, names in COLUMNS.items():
        if plain in names:
            return key
    for key, names in COLUMNS.items():
        if any(plain.startswith(n) for n in names if len(n) > 3):
            return key
    return None


def status_kind(status: str) -> str:
    plain = fold(status).strip()
    if re.search(r"convalid|homolog|equival|reconoc|exoner", plain):
        return "credited"
    if re.search(r"reprob|^rp\b|^r$", plain):
        return "failed"
    if re.search(r"aprob|^ap\b|^a$", plain):
        return "approved"
    if re.search(r"curso|matric|cursando|pendiente", plain):
        return "in_progress"
    if re.search(r"retir|anul|abandon", plain):
        return "withdrawn"
    return "other"


def history(tables: list[dict]) -> list[dict]:
    """One record per subject from the history's tables whose headers name a subject and its status."""
    records = []
    for table in tables:
        keys = {h: _header_key(h) for h in table["columnas"]}
        if "name" not in keys.values() or not {"status", "grade"} & set(keys.values()):
            continue
        for row in table["filas"]:
            record = {key: row.get(h, "") for h, key in keys.items() if key}
            if not record.get("name"):
                continue
            record["status_kind"] = status_kind(record.get("status", ""))
            records.append(record)
    return records


def breakdowns(html: str) -> list[dict]:
    """Each subject's grades as the grades page hands them to its «Ponderación» dialog: Presentar('NOMBRE', ...)."""
    found, seen = [], set()
    for call in PRESENT_CALL.finditer(unescape(html)):
        args = [next((g for g in m.groups() if g is not None), "").strip()
                for m in JS_ARG.finditer(call[1]) if m.group(0)]
        if len(args) != len(BREAKDOWN) or not args[0] or args[0] in seen:
            continue
        seen.add(args[0])
        found.append({key: value for key, value in zip(BREAKDOWN, args) if value})
    return found


def timetable(tables: list[dict]) -> list[dict]:
    """A weekly grid (a row per half hour, a column per day; the portal leaves out the hours with nothing) as the
    classes in it: one entry per day and class, its back-to-back half hours joined."""
    entries = []
    for table in tables:
        days = [h for h in table["columnas"] if fold(h).strip() in WEEKDAYS]
        if not days:
            continue
        hour = next((h for h in table["columnas"] if h not in days), None)
        if hour is None:
            continue
        for day in days:
            current = None
            for row in table["filas"]:
                start, _, end = (part.strip() for part in row.get(hour, "").partition("-"))
                text = row.get(day, "").strip()
                if current and text == current["text"] and start == current["end"]:
                    current["end"] = end
                    continue
                current = {"day": day, "start": start, "end": end, "text": text} if text else None
                if current:
                    entries.append(current)
    return entries


# -- the session ---------------------------------------------------------------------------------


class Portal:
    """One visit to the Académico, from the login page to the last table, with one set of cookies."""

    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.base = cfg.portal_url
        self.http = requests.Session()
        self.http.trust_env = False  # no proxy or .netrc credentials from the environment
        self.http.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-EC,es;q=0.9"})
        self.form: Form | None = None
        self.page: _Page | None = None
        self.html = ""  # the current page as it came, for what the parser drops (the grades' Presentar calls)
        self.url = ""  # where the last answer came from (the real address, before [test] routing)
        self.captcha: tuple[bytes, str] | None = None
        self.dump: Path | None = None  # `espol-bot academico --html`: each page's HTML, to check the reader

    def close(self) -> None:
        self.http.cookies.clear()
        self.http.close()
        self.form = self.page = self.captcha = None
        self.html = ""

    def _address(self, path: str) -> str:
        return urljoin(self.url or self.base + "/", path)

    def _send(self, method: str, url: str, data: dict | None = None) -> requests.Response:
        """One request and its redirects, all to the portal's own host; the answer's page becomes the current one."""
        host = urlsplit(self.base).netloc
        stand_in = urlsplit(route(self.base, self.cfg.core)).netloc  # the E2E test's portal ([test] link_hosts)
        for _ in range(6):
            if urlsplit(url).netloc != host:
                raise PortalError(f"el Académico quiso llevarme a otro sitio ({urlsplit(url).hostname})")
            try:
                response = self.http.request(method, route(url, self.cfg.core), data=data, timeout=TIMEOUT,
                                             allow_redirects=False, headers={"Referer": self.url or url})
            except requests.RequestException as exc:
                raise PortalError(f"el Académico no responde ({exc.__class__.__name__})") from None
            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
                parts = urlsplit(urljoin(url, response.headers["Location"]))
                url = parts._replace(scheme="https", netloc=host).geturl() if parts.netloc == stand_in else parts.geturl()
                method, data = ("GET", None) if response.status_code in (301, 302, 303) else (method, data)
                continue
            if response.status_code != 200:
                raise PortalError(f"el Académico respondió {response.status_code}")
            self.url = url
            if "text/html" in response.headers.get("Content-Type", "text/html"):
                self.html, self.page = response.text, parse(response.text)
                self.form = self.page.form
                if self.dump is not None and not self._on_login():
                    name = re.sub(r"[^A-Za-z0-9_.-]", "_", urlsplit(url).path.rsplit("/", 1)[-1]) or "pagina"
                    (self.dump / f"{len(list(self.dump.iterdir())) + 1:02d}-{name}.html").write_text(
                        response.text, encoding="utf-8")
            return response
        raise PortalError("el Académico me redirigió demasiadas veces")

    def _on_login(self) -> bool:
        return urlsplit(self.url).path.lower().endswith(LOGIN)

    def _post(self, data: dict[str, str]) -> requests.Response:
        return self._send("POST", self._address(self.form.action or self.url), data)

    def begin(self) -> None:
        """The login page: its first step asks for the user name."""
        self._send("GET", self.base + LOGIN)
        if self.form is None or not self.form.field(r"txtuser$"):
            raise PortalError("no reconozco la página de ingreso del Académico")

    def submit_user(self, user: str) -> None:
        """Step 1: the user name. The second step's page brings the password field and the CAPTCHA."""
        name, button = self.form.field(r"txtuser$"), self.form.field(r"btnsigte$")
        self._post(self.form.data({name: user}, button=button))
        if self.form is None or not self.form.field(r"txtpsw$"):
            raise LoginRefused(self._error() or "El Académico no aceptó ese usuario.")
        self._fetch_captcha()

    def submit_login(self, password: str, code: str) -> None:
        """Step 2: password and CAPTCHA. Refused, the page brings a new CAPTCHA, already fetched."""
        form = self.form
        values = {form.field(r"txtpsw$"): password, form.field(r"captchacode"): code}
        self._post(form.data(values, button=form.field(r"btniniciar")))
        if self._on_login() and self.form is not None and (self.form.field(r"txtpsw$") or self.form.field(r"txtuser$")):
            message = self._error() or "El Académico no aceptó el ingreso."
            if self.form.field(r"txtpsw$"):
                self._fetch_captcha()
            else:
                self.captcha = None
            raise LoginRefused(message)

    def _error(self) -> str:
        if self.page is None:
            return ""
        return next((t for k, t in self.page.labels.items() if re.search(r"error|mensaje|msg", k, re.I) and t), "")

    def _fetch_captcha(self) -> None:
        image = next((i for i in self.page.images if "captchaimage" in (i.get("class", "") + i.get("id", "")).lower()),
                     None)
        if image is None or not image.get("src"):
            raise PortalError("el Académico no mostró el CAPTCHA")
        here = self.url
        response = self._send("GET", self._address(image["src"]))
        self.url = here
        kind = response.headers.get("Content-Type", "").split(";")[0]
        if not kind.startswith("image/") or len(response.content) > MAX_CAPTCHA:
            raise PortalError("el CAPTCHA del Académico no es una imagen")
        self.captcha = (response.content, kind)

    def captcha_data_url(self) -> str:
        content, kind = self.captcha
        return f"data:{kind};base64,{base64.b64encode(content).decode()}"

    def open(self, page: str) -> None:
        """A page of the student's information; back at the login page means the session ended."""
        self._send("GET", self.base + PAGES + page)
        if self._on_login():
            raise PortalError("la sesión del Académico se cerró")

    def _search(self, term: dict[str, str]) -> None:
        """calificaciones and horario show nothing until «Consultar»: press it with `term` in the empty year and term
        boxes."""
        if self.form is None:
            return
        button = next((n for n, v in self.form.buttons.items() if SEARCH_BUTTON.search(v + n)), None)
        boxes = {self.form.field(r"txtanio$"): "anio", self.form.field(r"txttermino$"): "termino"}
        if button is None or None in boxes:
            return
        values = {name: self.form.inputs.get(name, "").strip() or term.get(key, "") for name, key in boxes.items()}
        if all(values.values()):
            self._post(self.form.data(values, button=button))

    def _section(self) -> dict:
        tables = data_tables(self.page)
        return {"tablas": tables, "datos": facts(self.page), "seleccion": chosen(self.form)}

    def extract(self, progress: Callable[[str], None] = lambda _: None) -> dict:
        """Every section the portal lets this student see; one that fails is noted and the rest still read."""
        sections, errors, term = {}, {}, {}
        for key, page, _, label in SECTIONS:
            progress(f"Leyendo {label}…")
            try:
                self.open(page)
                if key == "examenes":
                    sections[key] = self._exams()
                    term = {k: v for k, v in sections[key]["seleccion"].items() if k in ("anio", "termino")}
                    continue
                self._search(term)
                section = self._section()
                if key == "general":
                    section = {"datos": {label: value for label, value in rows(self.page).items()
                                         if GENERAL_FACTS.search(label)}}
                elif key == "historial":
                    section["materias"] = history(section["tablas"])
                elif key == "calificaciones":
                    section["breakdowns"] = breakdowns(self.html)
                elif key == "horario":
                    section["classes"] = timetable(section["tablas"])
                sections[key] = section
            except PortalError as exc:
                log.warning("academico: %s no se pudo leer (%s)", key, exc)
                errors[key] = str(exc)
                if "sesión" in str(exc):
                    break
        return {"sections": sections, "errors": errors}

    def _exams(self) -> dict:
        """horarioExView: one timetable per kind of exam its drop-down offers (parcial, final, mejoramiento), each
        shown after «Consultar». The page comes with the current year and term filled in."""
        base = self._section()
        select = next((s for s in (self.form.selects.values() if self.form else [])
                       if EXAM_KINDS.search(" ".join(t for _, t in s.options))), None)
        button = self.form and next((n for n, v in self.form.buttons.items() if SEARCH_BUTTON.search(v + n)), None)
        if select is None or not button:
            return {**base, "por_tipo": {}, "exams": {}}
        tables, exams = {}, {}
        for value, text in [o for o in select.options if EXAM_KINDS.search(o[1])]:
            self._post(self.form.data({select.name: value}, button=button))
            tables[text] = data_tables(self.page)
            exams[text] = timetable(tables[text])
        return {**base, "tablas": [], "por_tipo": tables, "exams": exams}


# -- the copy ---------------------------------------------------------------------------------------


def copy_path(cfg: BotConfig) -> Path:
    return cfg.core.data_dir / COPY


def period_of(sections: dict) -> str | None:
    """The academic term the copy belongs to, as the portal names it: the year and term its schedule has selected."""
    for key in ("horario", "calificaciones", "examenes"):
        picked = (sections.get(key) or {}).get("seleccion") or {}
        if picked.get("anio") and picked.get("termino"):
            return f"{picked['anio']} · {picked['termino']}"
    return None


def save(cfg: BotConfig, extracted: dict, now: datetime, *, just_saved: bool = True) -> dict:
    """`just_saved`: the next question is answered from this copy, even one that asks to refresh it (it is the
    question the sign-in was for coming back)."""
    copy = {"version": 1, "saved_at": timefmt.iso(now), "period": period_of(extracted["sections"]),
            "source": cfg.portal_url, "just_saved": just_saved, **extracted}
    _write(copy_path(cfg), copy)
    return copy


def mark_used(cfg: BotConfig, copy: dict) -> None:
    copy["just_saved"] = False
    _write(copy_path(cfg), copy)


def _write(path: Path, copy: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(copy, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load(cfg: BotConfig) -> dict | None:
    try:
        copy = json.loads(copy_path(cfg).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    return copy if isinstance(copy, dict) and copy.get("sections") else None


def summary(copy: dict) -> str:
    """What the copy holds, in a line for the chat: «historial (42 materias), créditos, horario»."""
    parts = []
    for key, _, name, _ in SECTIONS:
        section = copy["sections"].get(key)
        if section is None:
            continue
        materias = section.get("materias") or []
        parts.append(f"{name} ({len(materias)} materias)" if materias else name)
    return ", ".join(parts)
