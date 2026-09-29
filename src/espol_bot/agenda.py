"""A subject bot's agenda: the pre-run gate of its Hermes cron job (every minute).

Deterministic and model-free. Each run prints one of:
  - {"wakeAgent": false}  nothing to do; Hermes skips the agent, so the tick costs no tokens;
  - a pre-class brief task, with every fact the brief needs (last class from the
    notebook, what is due, the main book, new material and links, open doubts), when a
    class of this subject starts within `brief_minutos_antes`;
  - a handoff task with everything Vinci (or an alert button) queued for this subject.

Only the agent run that follows writes anything with the model, and its answer is
delivered by Hermes to the subject bot's own chat. Each class start is claimed in
`briefs` before waking the agent, so a restart or a second tick never repeats a
brief; a class that is not in horario.toml never gets one. Back-to-back blocks of the
subject (horario.sessions) get one brief, before the first block, never one mid-class.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from aula_core import Aula, queries, timefmt
from aula_core.config import ConfigError
from espol_bot import horario, libros, materias, store
from espol_bot.config import BotConfig
from espol_bot.cuaderno import FILE_KINDS, Notebook

log = logging.getLogger(__name__)

SKIP = json.dumps({"wakeAgent": False})


def _day_label(moment: datetime, now: datetime, tz) -> str:
    local, today = moment.astimezone(tz), now.astimezone(tz).date()
    prefix = {today: "hoy ", today - timedelta(days=1): "ayer "}.get(local.date(), "")
    return f"{prefix}{timefmt.DAYS_LONG[local.weekday()]} {local.day} {timefmt.MONTHS[local.month - 1]}"


def course_ids_for(conn, subject: materias.Subject) -> list[int]:
    """Every aula course of the subject, theory and práctico: the ones in materias.toml plus any
    active course with its code (a section that showed up after the team was made)."""
    ids = list(subject.course_ids)
    for row in conn.execute("SELECT id, course_code FROM courses WHERE active = 1 ORDER BY id").fetchall():
        if row["id"] not in ids and materias.base_code(row["course_code"]) == subject.code:
            ids.append(row["id"])
    return ids


def _entry_line(e: dict) -> str:
    when = e["fecha_clase"] or e["creado"][:10]
    extra = f" (archivo: {e['archivo']})" if e["archivo"] else ""
    heard = f"\n    transcripción: {e['transcripcion'][:400]}" if e.get("transcripcion") else ""
    return f"  - [{e['tipo']} #{e['id']} · {when}] {e['texto'][:600]}{extra}{heard}"


def _block(c: horario.Clase) -> str:
    room = f" en {c.aula}" if c.aula else ""
    paralelo = f" · paralelo {c.paralelo}" if c.paralelo else ""
    return f"{c.inicio:%H:%M}–{c.fin:%H:%M}{room}{paralelo}"


def sessions(cfg: BotConfig, subject: materias.Subject) -> dict[horario.Clase, list[horario.Clase]]:
    """The subject's class sessions in horario.toml, keyed by their first block."""
    try:
        classes = horario.for_subject(horario.load(cfg.core), subject.code)
    except ConfigError as exc:
        log.error("agenda %s: %s", subject.code, exc)
        classes = []
    return horario.sessions(classes, timedelta(minutes=cfg.brief_minutes))


def next_session(cfg: BotConfig, subject: materias.Subject, now: datetime) -> datetime | None:
    """When the subject's next class session starts, within a week."""
    upcoming = horario.occurrences(list(sessions(cfg, subject)), now, now + timedelta(days=8), cfg.core.tz,
                                   subject.code)
    return upcoming[0][0] if upcoming else None


def brief_task(cfg: BotConfig, subject: materias.Subject, start: datetime, blocks: list[horario.Clase],
               firsts: list[horario.Clase], now: datetime) -> str:
    """`blocks` are the session's; `firsts` the first block of every session of the subject."""
    tz = cfg.core.tz
    aula = Aula(cfg.core)
    try:
        conn = aula.conn
        course_ids = course_ids_for(conn, subject)
        previous = horario.previous(firsts, subject.code, start, tz)
        since = previous[0] if previous else now - timedelta(days=7)
        notebook = Notebook(cfg.core, subject.code)
        recent = notebook.entries(since=since, limit=12)
        if not recent:
            recent = notebook.entries(kind="clase", limit=3)
        doubts = notebook.entries(kind="duda", open_only=True, limit=8)
        weak = notebook.entries(kind="tema_debil", open_only=True, limit=8)
        notebook.close()

        due = queries.pending(conn, now, course_ids, days=7, overdue_days=0) if course_ids else []
        events = conn.execute(
            "SELECT e.kind, e.payload, e.created_at, e.ref_id FROM events e"
            f" WHERE e.course_id IN ({','.join('?' * len(course_ids))}) AND e.created_at >= ?"
            " AND e.kind IN ('new_file', 'file_updated', 'new_link', 'new_announcement', 'due_changed',"
            " 'new_assignment') ORDER BY e.id", (*course_ids, timefmt.iso(since))).fetchall() if course_ids else []
        files = {}
        for r in events:
            if r["kind"] in ("new_file", "file_updated"):
                try:
                    files[r["ref_id"]] = queries.file_by_id(conn, r["ref_id"])
                except queries.NotFound:
                    pass
        book = libros.main_book(conn, cfg.core, subject, course_ids) if course_ids else None
    finally:
        aula.close()

    clase = blocks[0]
    room = f" en {clase.aula}" if clase.aula else ""
    paralelo = f" · paralelo {clase.paralelo}" if clase.paralelo else ""
    minutes = max(0, round((start - now).total_seconds() / 60))
    lines = [
        "TAREA: brief_de_clase",
        f"Materia: {subject.name} ({subject.code}){paralelo}",
        (f"Clase: {_day_label(start, now, tz)}, {clase.inicio:%H:%M}–{max(b.fin for b in blocks):%H:%M}{room} "
         f"(empieza en {minutes} min)"),
    ]
    if len(blocks) > 1:
        lines.append("Son bloques seguidos, con este único brief para todos: " + "; ".join(map(_block, blocks)))
    lines.append("")
    if previous:
        lines.append(f"Clase anterior: {_day_label(previous[0], now, tz)}, {previous[1].inicio:%H:%M}.")
    else:
        lines.append("Clase anterior: no está en el horario (revisa los últimos 7 días del cuaderno).")
    lines.append("Tu cuaderno desde entonces (lo más reciente primero):" if recent else
                 "Tu cuaderno: no tiene nada de la clase anterior.")
    lines += [_entry_line(e) for e in recent]
    if doubts:
        lines.append("Dudas abiertas del estudiante:")
        lines += [_entry_line(e) for e in doubts]
    if weak:
        lines.append("Temas donde se le complica:")
        lines += [_entry_line(e) for e in weak]
    lines.append("")
    lines.append("Por entregar en los próximos 7 días:" if due else "Por entregar en los próximos 7 días: nada.")
    for t in due:
        flag = " (sin entrega en línea: examen/lección presencial)" if t["sin_entrega_en_linea"] else ""
        lines.append(f"  - {t['tarea']} — vence {timefmt.human(t['vence'], tz)} ({timefmt.until(t['vence'], now)})"
                     f"{flag} · {t['url']}")
    if book and book["titulo"]:
        pdfs = "; ".join(f"«{f['archivo']}» (archivo {f['archivo_id']}, {f['estado']})" for f in book["archivos"])
        lines.append(f"Libro principal: {book['titulo']} — " + (pdfs or "no tengo su PDF: usa el resto del material."))
    readable = {*cfg.core.material_extensions, "html"}
    new_material = [f for f in files.values() if f["extension"] in readable]
    links = [json.loads(r["payload"]) | {"enlace_id": r["ref_id"]} for r in events if r["kind"] == "new_link"]
    news = [json.loads(r["payload"]) | {"kind": r["kind"]} for r in events
            if r["kind"] not in ("new_file", "file_updated", "new_link")]
    lines.append("Material nuevo desde la clase anterior:" if new_material or links else
                 "Material nuevo desde la clase anterior: ninguno.")
    for f in new_material:
        where = " · ".join(v for v in (f["modulo"], f["seccion"]) if v)
        origin = f["origen"] if f["origen"] and not f["origen"].startswith(("Archivos", "Módulo")) else None
        lines.append(f"  - {f['archivo']}" + (f" [{where}]" if where else "") + (f" ({origin})" if origin else "")
                     + f" · archivo {f['id']}, {queries.file_state(f, cfg.core.max_file_mb)} · {f['url'] or ''}")
    for link in links:
        where = " · ".join(v for v in (link.get("modulo"), link.get("seccion")) if v)
        lines.append(f"  - enlace: {link['enlace']}" + (f" [{where}]" if where else "")
                     + f" · enlace_id {link['enlace_id']} · {link['url']}")
    if news:
        lines.append("Novedades del aula desde la clase anterior:")
        for n in news:
            what = n.get("titulo") or n.get("tarea") or ""
            lines.append(f"  - {n['kind']}: {what}")
    lines += [
        "",
        "Qué hacer: escribe el brief de esta clase para Telegram, en español, breve (máx. ~250 palabras):",
        "1) Repaso de la clase anterior (desde tu cuaderno; si no hay nada, dilo en una línea).",
        "2) Qué hay por entregar (con fecha) y si algo es para pronto.",
        "3) Material nuevo desde la clase anterior (si uno «sin bajar» es de esta clase, bájalo con bajar_archivo; "
        "un enlace se lee con leer_archivo y su enlace_id).",
        "4) 3 a 5 conceptos clave para esta clase (usa buscar_material, con «traduccion» si el material está en "
        "inglés, y leer_archivo; primero el libro principal; cita archivo y página).",
        "5) Una pregunta concreta para hacerle al profesor en clase.",
        "Empieza con «📚 Brief de " + subject.name + "» y la hora. No inventes fechas ni material.",
    ]
    return "\n".join(lines)


def handoff_task(cfg: BotConfig, subject: materias.Subject, items: list[dict], now: datetime) -> str:
    """The subject bot's task for the handoffs claimed this tick. Their attachments move into
    its notebook first, together with a «de_vinci» entry per handoff."""
    notebook = Notebook(cfg.core, subject.code)
    lines = ["TAREA: entrega_de_vinci",
             f"{len(items)} cosa(s) para {subject.display} que llegaron por Vinci. Ya quedaron en tu cuaderno."]
    try:
        for item in items:
            saved = []
            for att in item["adjuntos"]:
                source = Path(att["archivo"])
                if not source.is_file():
                    continue
                kind = att.get("tipo") if att.get("tipo") in FILE_KINDS else "documento"
                saved.append(notebook.add(kind, att.get("descripcion") or f"Recibido de Vinci: "
                                          f"{att.get('nombre', source.name)}", now,
                                          source_file=source, move=True, name=att.get("nombre"),
                                          origin="vinci"))
            origin = "aviso" if item["origen"] == "aviso" else "vinci"
            note = notebook.add("de_vinci", item["texto"], now, origin=origin)
            how = (f"el estudiante pulsó «Consultar con {subject.display}» en un aviso del aula virtual"
                   if origin == "aviso" else "Vinci te lo pasó de parte del estudiante")
            lines += ["", f"Entrega #{item['id']} ({how}); en tu cuaderno como entrada #{note['id']}:", item["texto"]]
            if saved:
                lines.append("Adjuntos (ya guardados en tu cuaderno):")
                lines += [f"  - {e['tipo']} #{e['id']}: {e['archivo']} — {e['texto']}" for e in saved]
    finally:
        notebook.close()
    lines += [
        "",
        "Qué hacer: respóndele directamente al estudiante en un solo mensaje (le llega a tu chat).",
        "- Si es un aviso del aula: explica qué implica en esta materia y qué debería hacer, "
        "usando tu material y tu cuaderno.",
        "- Si son apuntes, fotos o audio de clase: di en 2-4 viñetas qué contienen y confirma que los guardaste "
        "en tu cuaderno; si corresponden a una clase, registra lo visto con anotar (tipo «clase»).",
        "- Si es una pregunta: respóndela citando el material del curso.",
        "- Si es un documento del curso (el PDF del libro principal, unas diapositivas): agrégalo al material con "
        "agregar_material (la ruta del adjunto en tu cuaderno; libro_principal si es ese libro).",
        "Empieza con «📨 De parte de Vinci:». Sé breve.",
    ]
    return "\n".join(lines)


def run(cfg: BotConfig, code: str, now: datetime) -> str:
    """The gate's stdout for one tick of the subject `code`."""
    subject = materias.by_code(materias.load(cfg.core), code)
    if subject is None or not subject.active:
        return SKIP
    found = sessions(cfg, subject)
    upcoming = [(start, c) for start, c in horario.occurrences(
        list(found), now, now + timedelta(minutes=cfg.brief_minutes, seconds=1), cfg.core.tz, subject.code)
        if now < start <= now + timedelta(minutes=cfg.brief_minutes)]

    aula = Aula(cfg.core)
    try:
        conn = store.ensure(aula.conn)
        for start, clase in upcoming:
            if store.claim_brief(conn, subject.code, start, now):
                log.info("agenda %s: brief de la clase %s", code, start.isoformat())
                return brief_task(cfg, subject, start, found[clase], list(found), now)
        items = store.claim_handoffs(conn, subject.code, now)
    finally:
        aula.close()
    if items:
        log.info("agenda %s: entregas %s", code, ", ".join(f"#{i['id']}" for i in items))
        return handoff_task(cfg, subject, items, now)
    return SKIP
