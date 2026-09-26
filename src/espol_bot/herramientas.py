"""The tools each bot gets, served over MCP by `espol-bot mcp vinci|materia`.

Vinci (the main bot): read-only queries over the aula data of every course and over
every subject notebook, the schedule (it can read it and propose one extracted from
a screenshot; only the captain's «Guardar» button saves it), the handoff of an item
to a subject bot, and the team (it shows cards whose «Crear» / «Archivar» buttons, pressed
by the captain, create or archive a subject bot). No Vinci tool writes a notebook, reads
arbitrary files, runs commands, or sees a bot token.

A subject bot: the same queries restricted to its own course, the classes of its
subject, and its own notebook (read and write; attachments only from the files the
captain sent it, which Hermes keeps in the profile's media cache).

The Canvas token stays inside this process: no tool ever returns it.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from aula_core import Aula, queries, search, timefmt
from aula_core.canvas import CanvasError
from aula_core.config import ConfigError
from aula_core.materials import safe_filename
from espol_bot import agenda, horario, materias, messages, store
from espol_bot.config import BotConfig, load_telegram_secrets
from espol_bot.cuaderno import FILE_KINDS, KINDS, NOTE_KINDS, Notebook, NotebookError
from espol_bot.mcp_server import Tool, ToolError
from espol_bot.telegram import Telegram, TelegramError

log = logging.getLogger(__name__)

MEDIA_DIRS = ("cache", "image_cache", "audio_cache", "document_cache")
MEDIA_EXT = {
    "foto": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"},
    "audio": {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".aac"},
    "documento": {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".doc", ".ppt"},
}
MAX_ATTACHMENT = 50 * 1024 * 1024
MAX_READ_CHARS = 24000
RECENT_MEDIA = timedelta(minutes=30)


@dataclass
class Ctx:
    cfg: BotConfig
    hermes_home: Path | None = None
    code: str | None = None
    _aula: Aula | None = field(default=None, repr=False)

    @property
    def aula(self) -> Aula:
        if self._aula is None:
            self._aula = Aula(self.cfg.core)
            store.ensure(self._aula.conn)
        return self._aula

    @property
    def conn(self):
        return self.aula.conn

    def now(self) -> datetime:
        return self.aula.now()

    def subjects(self) -> list[materias.Subject]:
        return materias.load(self.cfg.core)

    def subject(self) -> materias.Subject:
        subject = materias.by_code(self.subjects(), self.code or "")
        if subject is None:
            raise ToolError(f"La materia {self.code} ya no está en materias.toml.")
        return subject

    def refresh(self) -> None:
        """Re-read the aula virtual when the local copy is stale (GET only); fall back to it on errors."""
        try:
            self.aula.ensure_fresh()
        except (CanvasError, ConfigError) as exc:
            if not queries.courses(self.conn):
                raise ToolError(f"No pude leer el aula virtual: {exc}") from None
            log.warning("uso los datos guardados: %s", exc)


# -- shared helpers ------------------------------------------------------------------------


def _int(value, name: str, default: int | None = None, lo: int = 1, hi: int = 365) -> int | None:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"«{name}» debe ser un número.") from None
    return max(lo, min(hi, number))


def _pages(value) -> tuple[int | None, int | None]:
    if value in (None, ""):
        return None, None
    first, _, last = str(value).partition("-")
    try:
        return int(first), int(last or first)
    except ValueError:
        raise ToolError("«paginas» debe ser un rango como 3-5.") from None


def _trim_hits(hits: list[dict]) -> list[dict]:
    for hit in hits:
        hit["texto"] = hit["texto"][:1500]
        hit.pop("ruta_local", None)
    return hits


def _read(conn, file_id: int, pages) -> dict:
    first, last = _pages(pages)
    data = queries.read_pages(conn, file_id, first, last)
    data.pop("descargado", None)
    total = 0
    kept = []
    for page in data["contenido"]:
        total += len(page["texto"])
        if total > MAX_READ_CHARS and kept:
            data["aviso"] = f"Texto recortado en la {data['unidad']} {kept[-1]['pagina']}; pide un rango más corto."
            break
        kept.append(page)
    data["contenido"] = kept
    if not kept:
        data["aviso"] = "El archivo no tiene texto indexado todavía."
    return data


def _schedule_json(ctx: Ctx, code: str | None = None) -> dict:
    try:
        classes = horario.load(ctx.cfg.core)
    except ConfigError as exc:
        raise ToolError(str(exc)) from None
    if code:
        classes = horario.for_subject(classes, code)
    subjects = ctx.subjects()
    return {"archivo": str(horario.path(ctx.cfg.core)), "clases": horario.to_json(classes),
            "texto": horario.render(classes, subjects, html=False) if classes else
            "Todavía no hay horario guardado. Pídele una captura de su horario de ESPOL (con la columna de horas)."}


def _upcoming(ctx: Ctx, days: int, code: str | None = None) -> list[dict]:
    try:
        classes = horario.load(ctx.cfg.core)
    except ConfigError:
        return []
    names = horario.names(ctx.subjects())
    now = ctx.now()
    return [{"materia": c.materia, "nombre": names.get(c.materia, c.materia),
             "cuando": f"{timefmt.DAYS_LONG[start.weekday()]} {start.day} {timefmt.MONTHS[start.month - 1]}, "
                       f"{c.inicio:%H:%M}–{c.fin:%H:%M}", "aula": c.aula}
            for start, c in horario.occurrences(classes, now, now + timedelta(days=days), ctx.cfg.core.tz, code)]


def _notebook_json(nb: Notebook, kind: str | None, n: int, open_only: bool = False) -> dict:
    if kind and kind not in KINDS:
        raise ToolError(f"«tipo» debe ser uno de: {', '.join(KINDS)}.")
    return {"materia": nb.code, "resumen": nb.overview(),
            "entradas": nb.entries(kind=kind, limit=n, open_only=open_only)}


# -- Vinci ---------------------------------------------------------------------------------


def _vinci_course_ids(ctx: Ctx, materia: str | None) -> list[int] | None:
    if not materia:
        return None
    subjects = ctx.subjects()
    ambiguous = None
    if subjects:
        try:
            subject = materias.resolve(subjects, materia)
            course_id = agenda.course_id_for(ctx.conn, subject)
            if course_id is not None:
                return [course_id]
        except materias.Ambiguous as exc:
            ambiguous = exc
    try:
        return queries.course_ids(ctx.conn, materia)
    except queries.NotFound as exc:
        raise ToolError(str(ambiguous or exc)) from None


def _media_file(ctx: Ctx, path: str) -> Path:
    """A file the captain sent this bot over Telegram (Hermes keeps it in the profile's media cache)."""
    if ctx.hermes_home is None:
        raise ToolError("Este servidor no conoce la carpeta de Hermes del bot; no puedo tomar adjuntos.")
    try:
        real = Path(path).expanduser().resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError):
        raise ToolError(f"No encuentro el archivo {path}.") from None
    roots = [(ctx.hermes_home / d).resolve() for d in MEDIA_DIRS if (ctx.hermes_home / d).exists()]
    if not real.is_file() or not any(real.is_relative_to(root) for root in roots):
        raise ToolError("Solo puedo tomar archivos que el estudiante te mandó por Telegram "
                        "(los que Hermes guarda en tu caché), no otros archivos del computador.")
    if real.stat().st_size > MAX_ATTACHMENT:
        raise ToolError("El archivo es demasiado grande (máximo 50 MB).")
    return real


def _kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    return next((kind for kind, exts in MEDIA_EXT.items() if ext in exts), "documento")


def _newest_media(ctx: Ctx, kind: str) -> Path | None:
    """The latest file of `kind` in the media cache from the last 30 minutes (for voice notes,
    which Hermes turns into text without telling the agent where the audio is)."""
    if ctx.hermes_home is None:
        return None
    cutoff = datetime.now().timestamp() - RECENT_MEDIA.total_seconds()
    found = []
    for d in MEDIA_DIRS:
        base = ctx.hermes_home / d
        if base.is_dir():
            found += [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_EXT.get(kind, set())
                      and p.stat().st_mtime >= cutoff]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def vinci_tools(ctx: Ctx) -> list[Tool]:
    def materias_(args):
        subjects = ctx.subjects()
        if not subjects:
            return {"materias": [], "nota": "Todavía no hay bots de materia. Usa proponer_equipo para armarlo."}
        return {"materias": [{"codigo": s.code, "nombre": s.name, "bot": s.display, "usuario": s.handle(),
                              "estado": s.state} for s in subjects]}

    def semana(args):
        days = _int(args.get("dias"), "dias", 7, 1, 31)
        ctx.refresh()
        now = ctx.now()
        pending = queries.pending(ctx.conn, now, days=days, overdue_days=7)
        notebooks = {}
        for s in ctx.subjects():
            nb = Notebook(ctx.cfg.core, s.code, read_only=True)
            notebooks[s.code] = {"nombre": s.name, "estado": s.state, **nb.overview()}
            nb.close()
        return {"hoy": timefmt.human(now, ctx.cfg.core.tz), "clases": _upcoming(ctx, days),
                "pendientes": pending, "cuadernos": notebooks}

    def tareas(args):
        ctx.refresh()
        return queries.pending(ctx.conn, ctx.now(), _vinci_course_ids(ctx, args.get("materia")),
                               days=_int(args.get("dias"), "dias"))

    def anuncios(args):
        ctx.refresh()
        return queries.announcements(ctx.conn, _vinci_course_ids(ctx, args.get("materia")),
                                     limit=_int(args.get("n"), "n", 5, 1, 30))

    def notas(args):
        ctx.refresh()
        return queries.grades(ctx.conn, _vinci_course_ids(ctx, args.get("materia")))

    def archivos(args):
        return [{k: v for k, v in f.items() if k != "descargado"}
                for f in queries.files(ctx.conn, _vinci_course_ids(ctx, args.get("materia")), args.get("nombre"))]

    def buscar(args):
        return _trim_hits(search.search(ctx.conn, str(args["pregunta"]),
                                        course_ids=_vinci_course_ids(ctx, args.get("materia")),
                                        limit=_int(args.get("n"), "n", 5, 1, 10)))

    def leer(args):
        try:
            return _read(ctx.conn, _int(args["archivo_id"], "archivo_id", hi=10**12), args.get("paginas"))
        except queries.NotFound as exc:
            raise ToolError(str(exc)) from None

    def cuaderno(args):
        try:
            subject = materias.resolve(ctx.subjects(), str(args["materia"]))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None
        nb = Notebook(ctx.cfg.core, subject.code, read_only=True)
        try:
            return _notebook_json(nb, args.get("tipo"), _int(args.get("n"), "n", 20, 1, 100))
        finally:
            nb.close()

    def horario_(args):
        return _schedule_json(ctx)

    def proponer_horario(args):
        classes, errors, warnings = horario.validate(args.get("clases"), ctx.subjects())
        if errors:
            raise ToolError("No puedo proponer ese horario:\n- " + "\n- ".join(errors)
                            + "\nCorrige con lo que ves en la captura (o pregúntale) y vuelve a proponer.")
        now = ctx.now()
        proposal_id = store.new_proposal(ctx.conn, horario.to_json(classes), now)
        card = messages.schedule_card(horario.render(classes, ctx.subjects()), len(classes), warnings)
        try:
            Telegram(load_telegram_secrets(), api=ctx.cfg.telegram_api).send(
                card, [("✅ Guardar horario", f"v1:h:{proposal_id}:ok"), ("✏️ Corregir", f"v1:h:{proposal_id}:no")])
        except (TelegramError, ConfigError) as exc:
            raise ToolError(f"No pude mostrarle la propuesta por Telegram: {exc}") from None
        return {"propuesta": proposal_id, "clases": len(classes), "advertencias": warnings,
                "mensaje": "Le mostré el horario extraído en una tarjeta con los botones «Guardar horario» y "
                           "«Corregir». Se guarda solo cuando pulse Guardar; tú no puedes guardarlo. Dile que "
                           "lo revise (sobre todo días y horas) y, si algo está mal, que te diga qué corregir."}

    def entregar(args):
        try:
            subject = materias.resolve(ctx.subjects(), str(args["materia"]))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None
        if not subject.active:
            raise ToolError(f"{subject.display} está {subject.state}: no puede recibir cosas. "
                            "Díselo al estudiante (si todavía no tiene bot, puede crearlo con proponer_equipo).")
        text = str(args["mensaje"]).strip()
        paths = args.get("adjuntos") or []
        if not isinstance(paths, list) or len(paths) > 10:
            raise ToolError("«adjuntos» debe ser una lista de hasta 10 rutas.")
        files = [_media_file(ctx, str(p)) for p in paths]
        now = ctx.now()
        folder = ctx.cfg.core.data_dir / "entregas" / subject.code
        folder.mkdir(parents=True, exist_ok=True)
        attachments = []
        for source in files:
            dest = folder / f"{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}-{safe_filename(source.name)}"
            shutil.copy2(source, dest)
            attachments.append({"tipo": _kind_of(source), "archivo": str(dest), "nombre": source.name})
        handoff_id, _ = store.queue_handoff(ctx.conn, subject.code, "vinci", text, now, attachments=attachments)
        extra = f" con {len(attachments)} adjunto(s)" if attachments else ""
        return {"entrega": handoff_id, "bot": subject.display, "usuario": subject.handle(),
                "confirmacion": f"Listo: se lo pasé a {subject.display} ({subject.handle()}){extra}. "
                                "Te responde en su chat en un minuto más o menos."}

    def card(text: str, buttons: list[tuple[str, str]]) -> None:
        try:
            Telegram(load_telegram_secrets(), api=ctx.cfg.telegram_api).send(text, buttons)
        except (TelegramError, ConfigError) as exc:
            raise ToolError(f"No pude mostrarle la tarjeta por Telegram: {exc}") from None

    def proponer_equipo(args):
        from espol_bot import equipo
        ctx.refresh()
        team, notes, gone = equipo.sync_team(ctx.cfg, ctx.conn)
        text, buttons = equipo.team_card(team, notes, gone)
        card(text, buttons)
        return {"materias": [{"codigo": s.code, "bot": s.display, "estado": s.state} for s in team],
                "mensaje": "Le mostré su equipo con un botón «➕ Crear» por cada bot que falta. Un bot se crea solo "
                           "cuando pulse ese botón y lo confirme en Telegram; tú no puedes crearlo. Si pregunta, "
                           "explícale los pasos y dile que tú nunca ves el token: se guarda solo y, si llega en un mensaje, se borra."}

    def confirm_card(args, state: str, kind: str, question: str, label: str) -> dict:
        try:
            subject = materias.resolve(ctx.subjects(), str(args["materia"]))
        except materias.Ambiguous as exc:
            raise ToolError(str(exc)) from None
        if subject.state != state:
            raise ToolError(f"{subject.display} está «{subject.state}», no «{state}».")
        card(question.format(bot=f"<b>{messages.e(subject.display)}</b>"),
             [(f"{label} {subject.display}", f"v1:{kind}:0:{subject.code}"), ("Cancelar", f"v1:n:0:{subject.code}")])
        return {"bot": subject.display,
                "mensaje": f"Le mostré el botón «{label}». Solo pasa si lo pulsa; tú no puedes hacerlo por tu cuenta."}

    def archivar(args):
        return confirm_card(args, "activa", "x", "🗄️ ¿Archivo {bot}? Deja de mandar briefs y de responder; su "
                            "memoria y su cuaderno quedan guardados y puedes reactivarlo cuando quieras.", "🗄️ Archivar")

    def reactivar(args):
        return confirm_card(args, "archivada", "r", "♻️ ¿Reactivo {bot}? Vuelve a responder y a mandar sus briefs.",
                            "♻️ Reactivar")

    materia = {"materia": {"type": "string", "description": "materia (nombre o código); vacío = todas"}}
    return [
        Tool("materias", "Los bots de materia del estudiante: nombre, código, @usuario y estado.", materias_),
        Tool("semana", "Vista general: clases de los próximos días (según el horario), entregas pendientes y "
             "atrasadas de todas las materias, y lo que dice cada cuaderno (dudas abiertas y temas débiles). "
             "Úsala para «¿qué tengo esta semana?», «¿cómo voy en todo?» y planes de estudio.", semana,
             {"dias": {"type": "integer", "description": "cuántos días hacia adelante (por defecto 7)"}}),
        Tool("tareas", "Entregas pendientes del aula virtual, por fecha.", tareas,
             {**materia, "dias": {"type": "integer", "description": "solo las que vencen en N días"}}),
        Tool("anuncios", "Anuncios recientes de los profesores.", anuncios,
             {**materia, "n": {"type": "integer", "description": "cuántos (por defecto 5)"}}),
        Tool("notas", "Notas publicadas por materia.", notas, dict(materia)),
        Tool("archivos", "Archivos (material) de las materias, con su ID.", archivos,
             {**materia, "nombre": {"type": "string", "description": "parte del nombre o del módulo (ej. 'semana 3')"}}),
        Tool("buscar_material", "Busca en el texto del material descargado; devuelve archivo, página y fragmento.",
             buscar, {"pregunta": {"type": "string"}, **materia, "n": {"type": "integer"}}, ["pregunta"]),
        Tool("leer_archivo", "Lee el texto de un archivo del material por páginas.", leer,
             {"archivo_id": {"type": "integer"}, "paginas": {"type": "string", "description": "rango, ej. 3-5"}},
             ["archivo_id"]),
        Tool("cuaderno", "Lee (solo lectura) el cuaderno de un bot de materia: clases, apuntes, dudas, temas "
             "débiles y adjuntos.", cuaderno,
             {"materia": {"type": "string"}, "tipo": {"type": "string", "enum": list(KINDS)},
              "n": {"type": "integer", "description": "cuántas entradas (por defecto 20)"}}, ["materia"]),
        Tool("horario", "El horario de clases guardado.", horario_),
        Tool("proponer_horario", "Muestra al estudiante, en una tarjeta con botones, el horario que extrajiste de "
             "su captura. Solo se guarda si el estudiante pulsa «Guardar horario». Una entrada por bloque de clase.",
             proponer_horario,
             {"clases": {"type": "array", "items": {
                 "type": "object",
                 "properties": {"materia": {"type": "string", "description": "código, ej. CCPG1055"},
                                "dia": {"type": "string", "description": "lunes … sábado"},
                                "inicio": {"type": "string", "description": "HH:MM (24 h)"},
                                "fin": {"type": "string", "description": "HH:MM (24 h)"},
                                "aula": {"type": "string"}, "paralelo": {"type": "string"}},
                 "required": ["materia", "dia", "inicio", "fin"]}}},
             ["clases"], read_only=False),
        Tool("entregar_a_materia", "Pasa algo (texto, y fotos/PDF/audios que el estudiante te mandó) al bot de "
             "una materia, que le responde en su propio chat. Úsala solo si sabes con certeza de qué materia es; "
             "si no, pregúntale.", entregar,
             {"materia": {"type": "string", "description": "nombre o código de la materia"},
              "mensaje": {"type": "string", "description": "qué le pasas: sus palabras y qué contienen los adjuntos"},
              "adjuntos": {"type": "array", "items": {"type": "string"},
                           "description": "rutas de los archivos que te mandó por Telegram"}},
             ["materia", "mensaje"], read_only=False),
        Tool("proponer_equipo", "Arma o revisa su equipo de bots de materia: lee las materias del aula virtual y le "
             "muestra una tarjeta con un botón «➕ Crear» por cada bot que falta. El bot se crea cuando lo pulsa y lo "
             "confirma en Telegram; el token nunca llega a ti.", proponer_equipo, read_only=False),
        Tool("archivar_materia", "Fin de semestre: le muestra un botón para archivar el bot de una materia (deja de "
             "responder y de mandar briefs; conserva memoria y cuaderno). Solo se archiva si lo pulsa.", archivar,
             {"materia": {"type": "string"}}, ["materia"], read_only=False),
        Tool("reactivar_materia", "Le muestra un botón para reactivar el bot archivado de una materia.", reactivar,
             {"materia": {"type": "string"}}, ["materia"], read_only=False),
    ]


# -- subject bot -----------------------------------------------------------------------------


def subject_tools(ctx: Ctx) -> list[Tool]:
    def course_id() -> int:
        cid = agenda.course_id_for(ctx.conn, ctx.subject())
        if cid is None:
            raise ToolError(f"No encuentro {ctx.code} entre las materias del aula virtual.")
        return cid

    def own_file(file_id) -> int:
        fid = _int(file_id, "archivo_id", hi=10**12)
        try:
            info = queries.file_by_id(ctx.conn, fid)
        except queries.NotFound as exc:
            raise ToolError(str(exc)) from None
        if info["curso_id"] != course_id():
            raise ToolError("Ese archivo es de otra materia; solo puedes usar el material de la tuya.")
        return fid

    def resumen(args):
        ctx.refresh()
        s, cid, now = ctx.subject(), course_id(), ctx.now()
        nb = Notebook(ctx.cfg.core, s.code)
        try:
            notebook = {"resumen": nb.overview(), "ultimas": nb.entries(limit=5)}
        finally:
            nb.close()
        return {"materia": s.name, "codigo": s.code, "bot": s.display, "proximas_clases": _upcoming(ctx, 7, s.code),
                "pendientes": queries.pending(ctx.conn, now, [cid], days=14),
                "anuncios": queries.announcements(ctx.conn, [cid], limit=3), "cuaderno": notebook}

    def tareas(args):
        ctx.refresh()
        return queries.pending(ctx.conn, ctx.now(), [course_id()], days=_int(args.get("dias"), "dias"))

    def anuncios(args):
        ctx.refresh()
        return queries.announcements(ctx.conn, [course_id()], limit=_int(args.get("n"), "n", 5, 1, 30))

    def notas(args):
        ctx.refresh()
        return queries.grades(ctx.conn, [course_id()])

    def archivos(args):
        return [{k: v for k, v in f.items() if k != "descargado"}
                for f in queries.files(ctx.conn, [course_id()], args.get("nombre"))]

    def buscar(args):
        return _trim_hits(search.search(ctx.conn, str(args["pregunta"]), course_ids=[course_id()],
                                        limit=_int(args.get("n"), "n", 5, 1, 10)))

    def leer(args):
        return _read(ctx.conn, own_file(args["archivo_id"]), args.get("paginas"))

    def bajar(args):
        fid = own_file(args["archivo_id"])
        try:
            ctx.aula.download(fid)
        except CanvasError as exc:
            raise ToolError(f"No pude bajar el archivo: {exc}") from None
        info = queries.file_by_id(ctx.conn, fid)
        return {"archivo": info["archivo"], "indexado": info["indexado"], "paginas": info["paginas"], "url": info["url"]}

    def horario_(args):
        return _schedule_json(ctx, ctx.code)

    def notebook() -> Notebook:
        return Notebook(ctx.cfg.core, ctx.subject().code)

    def cuaderno(args):
        nb = notebook()
        try:
            return _notebook_json(nb, args.get("tipo"), _int(args.get("n"), "n", 20, 1, 100), bool(args.get("abiertas")))
        finally:
            nb.close()

    def anotar(args):
        kind = str(args["tipo"])
        if kind not in NOTE_KINDS:
            raise ToolError(f"«tipo» debe ser uno de: {', '.join(NOTE_KINDS)} (para archivos usa guardar_adjunto).")
        nb = notebook()
        try:
            return nb.add(kind, str(args["texto"]), ctx.now(), class_date=args.get("fecha_clase") or None)
        except NotebookError as exc:
            raise ToolError(str(exc)) from None
        finally:
            nb.close()

    def resolver(args):
        nb = notebook()
        try:
            return nb.resolve(_int(args["entrada_id"], "entrada_id", hi=10**9), ctx.now())
        except NotebookError as exc:
            raise ToolError(str(exc)) from None
        finally:
            nb.close()

    def guardar_adjunto(args):
        kind = str(args["tipo"])
        if kind not in FILE_KINDS:
            raise ToolError(f"«tipo» debe ser uno de: {', '.join(FILE_KINDS)}.")
        if args.get("ruta"):
            source = _media_file(ctx, str(args["ruta"]))
        else:
            source = _newest_media(ctx, kind)
            if source is None and kind != "audio":
                raise ToolError("Dime la ruta del archivo (aparece como «Image attached at: …» o «saved at: …»).")
        nb = notebook()
        try:
            entry = nb.add(kind, str(args["resumen"]), ctx.now(), class_date=args.get("fecha_clase") or None,
                           transcript=args.get("transcripcion"), source_file=source)
        except NotebookError as exc:
            raise ToolError(str(exc)) from None
        finally:
            nb.close()
        if source is None:
            entry["aviso"] = "No encontré el audio en tu caché; guardé solo la transcripción y el resumen."
        return entry

    return [
        Tool("resumen", "Tu materia de un vistazo: próximas clases, pendientes, anuncios y tu cuaderno.", resumen),
        Tool("tareas", "Entregas pendientes de tu materia.", tareas,
             {"dias": {"type": "integer", "description": "solo las que vencen en N días"}}),
        Tool("anuncios", "Anuncios recientes de tu materia.", anuncios, {"n": {"type": "integer"}}),
        Tool("notas", "Notas publicadas de tu materia.", notas),
        Tool("archivos", "Material de tu materia, con su ID.", archivos,
             {"nombre": {"type": "string", "description": "parte del nombre o módulo"}}),
        Tool("buscar_material", "Busca en el texto del material de tu materia (archivo, página, fragmento).",
             buscar, {"pregunta": {"type": "string"}, "n": {"type": "integer"}}, ["pregunta"]),
        Tool("leer_archivo", "Lee un archivo del material de tu materia, por páginas.", leer,
             {"archivo_id": {"type": "integer"}, "paginas": {"type": "string", "description": "rango, ej. 3-5"}},
             ["archivo_id"]),
        Tool("bajar_archivo", "Baja (solo lectura del aula) e indexa un archivo de tu materia que aún no tenga texto.",
             bajar, {"archivo_id": {"type": "integer"}}, ["archivo_id"], read_only=False),
        Tool("horario", "Las clases de tu materia según el horario.", horario_),
        Tool("cuaderno", "Lee tu cuaderno: lo visto en cada clase, apuntes, dudas, temas débiles y adjuntos.",
             cuaderno, {"tipo": {"type": "string", "enum": list(KINDS)}, "n": {"type": "integer"},
                        "abiertas": {"type": "boolean", "description": "solo dudas/temas sin resolver"}}),
        Tool("anotar", "Escribe en tu cuaderno: «clase» (lo que se vio en una clase), «apunte», «duda» o "
             "«tema_debil» (algo que le cuesta).", anotar,
             {"tipo": {"type": "string", "enum": list(NOTE_KINDS)}, "texto": {"type": "string"},
              "fecha_clase": {"type": "string", "description": "AAAA-MM-DD de la clase, si aplica"}},
             ["tipo", "texto"], read_only=False),
        Tool("resolver", "Marca como resuelta una duda o un tema débil de tu cuaderno.", resolver,
             {"entrada_id": {"type": "integer"}}, ["entrada_id"], read_only=False),
        Tool("guardar_adjunto", "Guarda en tu cuaderno una foto (ej. de la pizarra), una nota de voz o un documento "
             "que el estudiante te mandó, con tu resumen (y la transcripción, si es audio).", guardar_adjunto,
             {"tipo": {"type": "string", "enum": list(FILE_KINDS)},
              "resumen": {"type": "string", "description": "qué contiene, en 1-5 líneas"},
              "ruta": {"type": "string", "description": "ruta del archivo que te llegó (para audio puede ir vacía)"},
              "transcripcion": {"type": "string", "description": "texto de la nota de voz, si lo tienes"},
              "fecha_clase": {"type": "string", "description": "AAAA-MM-DD de la clase, si aplica"}},
             ["tipo", "resumen"], read_only=False),
    ]
