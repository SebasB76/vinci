"""Spanish Telegram messages (HTML parse mode) built without any model call."""

from __future__ import annotations

import re
from collections import OrderedDict
from datetime import datetime, timedelta
from html import escape, unescape
from zoneinfo import ZoneInfo

from aula_core import timefmt
from aula_core.catalog import KIND_LABEL, PUBLIC, WHY_LINK_ONLY
from aula_core.materials import READABLE

KIND_TITLE = {
    "new_assignment": "📝 Tareas nuevas",
    "due_changed": "📅 Cambios de fecha",
    "new_announcement": "📢 Anuncios nuevos",
    "grade_posted": "✅ Notas publicadas",
    "grade_changed": "✏️ Notas actualizadas",
    "new_file": "📚 Material nuevo",
    "file_updated": "📚 Material actualizado",
    "new_link": "🔗 Enlaces nuevos",
    "new_course": "🎓 Materias nuevas",
}


def e(value) -> str:
    return escape(str(value if value is not None else ""), quote=False)


def link(url: str | None, label: str = "Abrir en el aula virtual") -> str:
    return f'<a href="{escape(url or "", quote=True)}">{e(label)}</a>' if url else ""


def _score(ev: dict, prefix: str = "") -> str:
    score, grade = ev.get(f"{prefix}nota"), ev.get(f"{prefix}calificacion")
    if score is None:
        return e(grade or "—")
    text = f"{score:g}" + (f"/{ev['puntos']:g}" if ev.get("puntos") else "")
    if grade and grade != f"{score:g}":
        text += f" ({grade})"
    return e(text)


def event_message(ev: dict, tz: ZoneInfo, now: datetime, index_status: str | None = None) -> str:
    kind, course = ev["kind"], e(ev["curso"])
    if kind == "new_assignment":
        due = (f"Entrega: {e(timefmt.human(ev['due_at'], tz))} ({e(timefmt.until(ev['due_at'], now))})"
               if ev.get("due_at") else "Sin fecha de entrega")
        return f"📝 <b>Nueva tarea en {course}</b>\n{e(ev['tarea'])}\n{due}\n{link(ev['url'])}"
    if kind == "due_changed":
        return (f"📅 <b>Cambió la fecha de entrega</b> — {course}\n{e(ev['tarea'])}\n"
                f"Antes: {e(timefmt.human(ev.get('due_at_anterior'), tz))}\n"
                f"Ahora: <b>{e(timefmt.human(ev.get('due_at'), tz))}</b>\n{link(ev['url'])}")
    if kind == "new_announcement":
        text = (ev.get("texto") or "").strip()
        if len(text) > 500:
            text = text[:500].rstrip() + "…"
        author = f" ({e(ev['autor'])})" if ev.get("autor") else ""
        return f"📢 <b>Nuevo anuncio en {course}</b>{author}\n<b>{e(ev['titulo'])}</b>\n{e(text)}\n{link(ev['url'])}"
    if kind == "grade_posted":
        return f"✅ <b>Nota publicada</b> — {course}\n{e(ev['tarea'])}: <b>{_score(ev)}</b>\n{link(ev['url'])}"
    if kind == "grade_changed":
        return (f"✏️ <b>Nota actualizada</b> — {course}\n{e(ev['tarea'])}: {_score(ev, '')} "
                f"(antes {_score({**ev, 'nota': ev.get('nota_anterior'), 'calificacion': ev.get('calificacion_anterior')})})\n"
                f"{link(ev['url'])}")
    if kind in ("new_file", "file_updated"):
        verb = "Nuevo material" if kind == "new_file" else "Material actualizado"
        where = "".join(f" · {e(ev[k])}" for k in ("modulo", "seccion") if ev.get(k))
        origin = ev.get("origen") or ""
        source = f"\n{e(origin)}" if origin and not origin.startswith(("Archivos", "Módulo")) else ""
        later = "\nLo bajo y lo leo cuando haga falta." if ev["archivo"].lower().endswith(
            tuple(f".{ext}" for ext in READABLE)) else ""
        ready = {"ok": "\nYa lo leí: puedes preguntarme sobre él.",
                 "escaneado": "\nEs un escaneo: su bot de materia mira sus páginas como imagen."}.get(
            index_status or "", "" if index_status else later)
        return (f"📚 <b>{verb} en {course}</b>{where}\n{e(ev['archivo'])}{source}{ready}\n"
                f"{link(ev['url'], 'Ver archivo')}")
    if kind == "new_link":
        where = "".join(f" · {e(ev[k])}" for k in ("modulo", "seccion") if ev.get(k))
        what = KIND_LABEL.get(ev.get("tipo"), ev.get("tipo") or "enlace")
        how = ("Su bot de materia lo abre sin tu cuenta cuando haga falta (si pide iniciar sesión, te lo dice)."
               if ev.get("acceso") == PUBLIC else
               f"Ábrelo tú: {e(WHY_LINK_ONLY.get(ev.get('tipo'), 'no lo puedo abrir'))}.")
        return (f"🔗 <b>Enlace nuevo en {course}</b>{where}\n{e(ev['enlace'])} ({e(what)})\n{how}\n"
                f"{link(ev['url'], 'Abrir enlace')}")
    if kind == "new_course":
        return f"🎓 <b>Nueva materia en tu aula virtual</b>\n{course}\nDesde ahora te aviso de sus tareas y anuncios.\n{link(ev['url'])}"
    return f"{course}: {e(kind)}"


def _digest_line(ev: dict, tz: ZoneInfo) -> str:
    kind = ev["kind"]
    name = str(ev.get("tarea") or ev.get("titulo") or ev.get("archivo") or ev.get("enlace") or ev["curso"])
    extra = ""
    if kind in ("new_assignment", "due_changed") and ev.get("due_at"):
        extra = f" — vence {e(timefmt.human(ev['due_at'], tz))}"
    elif kind in ("grade_posted", "grade_changed"):
        extra = f" — {_score(ev)}"
    return f"• {e(ev['curso'])}: {link(ev.get('url'), name) or e(name)}{extra}"


def digest(events: list[dict], tz: ZoneInfo) -> str:
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for ev in events:
        groups.setdefault(ev["kind"], []).append(ev)
    blocks = [f"🔔 <b>{len(events)} novedades en tu aula virtual</b>"]
    for kind, items in groups.items():
        blocks.append(f"<b>{KIND_TITLE.get(kind, kind)}</b>\n" + "\n".join(_digest_line(ev, tz) for ev in items))
    return "\n\n".join(blocks)


def reminder_message(task: dict, hours: int, tz: ZoneInfo, now: datetime) -> str:
    offline = "\n(No tiene entrega en línea: revisa cómo se entrega.)" if task["sin_entrega_en_linea"] else ""
    return (f"⏰ <b>Recordatorio: vence {e(timefmt.until(task['vence'], now))}</b>\n"
            f"{e(task['curso'])}: {e(task['tarea'])}\n"
            f"Entrega: {e(timefmt.human(task['vence'], tz))}\n"
            f"Aún no la has entregado.{offline}\n{link(task['url'])}")


def _day_label(day, today) -> str:
    if day == today:
        return "Hoy"
    if day == today + timedelta(days=1):
        return "Mañana"
    return f"{timefmt.DAYS_LONG[day.weekday()].capitalize()} {day.day} {timefmt.MONTHS[day.month - 1]}"


def weekly_summary(week: list[dict], overdue: list[dict], announcements_24h: list[dict],
                   tz: ZoneInfo, now: datetime, todos: list[dict] = ()) -> str:
    local_now = now.astimezone(tz)
    today = local_now.date()
    end = today + timedelta(days=6)
    pending = [t for t in week if not t["entregada"]]
    done = [t for t in week if t["entregada"]]
    head = (f"☀️ <b>Resumen de tu semana</b>\n"
            f"{_day_label(today, today)} {today.day} {timefmt.MONTHS[today.month - 1]} → "
            f"{timefmt.DAYS[end.weekday()]} {end.day} {timefmt.MONTHS[end.month - 1]}")
    blocks = [head]
    if pending:
        by_day: OrderedDict = OrderedDict()
        for t in pending:
            by_day.setdefault(timefmt.parse(t["vence"]).astimezone(tz).date(), []).append(t)
        lines = [f"<b>Por entregar ({len(pending)})</b>"]
        for day, items in by_day.items():
            lines.append(f"<i>{_day_label(day, today)}</i>")
            for t in items:
                hour = timefmt.parse(t["vence"]).astimezone(tz).strftime("%H:%M")
                lines.append(f"• {hour} — {e(t['curso'])}: {link(t['url'], t['tarea'])}")
        blocks.append("\n".join(lines))
    else:
        blocks.append("No tienes entregas pendientes esta semana. 🎉")
    if overdue:
        blocks.append(f"<b>Atrasadas sin entregar ({len(overdue)})</b>\n" + "\n".join(
            f"• {e(t['curso'])}: {link(t['url'], t['tarea'])} (venció {e(timefmt.human(t['vence'], tz))})"
            for t in overdue))
    if done:
        blocks.append(f"Ya entregaste {len(done)} de esta semana ✓")
    if todos:
        blocks.append(f"<b>📌 Tu lista ({len(todos)})</b>\n" + "\n".join(todo_line(t, tz, now) for t in todos))
    if announcements_24h:
        blocks.append(f"<b>Anuncios de las últimas 24 h ({len(announcements_24h)})</b>\n" + "\n".join(
            f"• {e(a['curso'])}: {link(a['url'], a['titulo'])}" for a in announcements_24h))
    return "\n\n".join(blocks)


SUBMITTED_BUTTON = "✅ Ya lo entregué"
UNSUBMITTED_BUTTON = "↩️ Aún no lo entregué"
TODO_DONE_BUTTON = "✅ Hecho"


def _todo_short(text: str) -> str:
    return text if len(text) <= 28 else text[:27].rstrip() + "…"


def todo_done_button(text: str) -> str:
    """The summary lists several to-dos: each button says which one it closes."""
    return f"✅ {_todo_short(text)}"


def todo_undo_button(text: str) -> str:
    return f"↩️ Deshacer: {_todo_short(text)}"


def todo_due(todo: dict, tz: ZoneInfo) -> str:
    due = timefmt.parse(todo["due_at"])
    if due is None:
        return "sin fecha"
    local = due.astimezone(tz)
    return f"{timefmt.DAYS[local.weekday()]} {local.day} {timefmt.MONTHS[local.month - 1]}" if todo["all_day"] \
        else timefmt.human(due, tz)


def _todo_what(todo: dict) -> str:
    return f"{e(todo['subject'])}: {e(todo['text'])}" if todo["subject"] else e(todo["text"])


def todo_line(todo: dict, tz: ZoneInfo, now: datetime) -> str:
    due = timefmt.parse(todo["due_at"])
    if due is None:
        return f"• {_todo_what(todo)}"
    late = f" (venció {e(timefmt.until(due, now))})" if due < now else ""
    return f"• {e(todo_due(todo, tz))} — {_todo_what(todo)}{late}"


def todo_card(todo: dict, tz: ZoneInfo, reminder_hours: list[int]) -> str:
    when = (f"Para: <b>{e(todo_due(todo, tz))}</b>\nTe lo recuerdo "
            + " y ".join(f"{h} h" for h in sorted(reminder_hours, reverse=True)) + " antes y sale en tu resumen de "
            "las 7:00." if todo["due_at"] else "Sin fecha: sale en tu resumen de las 7:00 hasta que lo marques.")
    return (f"📌 <b>Anotado en tu lista</b>\n{_todo_what(todo)}\n{when}\n"
            f"Cuando lo termines, pulsa <b>{TODO_DONE_BUTTON}</b>.")


def todo_reminder(todo: dict, tz: ZoneInfo, now: datetime) -> str:
    return (f"⏰ <b>Recordatorio: vence {e(timefmt.until(todo['due_at'], now))}</b>\n"
            f"📌 {_todo_what(todo)}\nPara: {e(todo_due(todo, tz))}")


def welcome(courses: list[dict], pending_week: int, poll_minutes: int) -> str:
    names = "\n".join(f"• {e(c['nombre'])}" for c in courses) or "(no encontré materias activas)"
    return (f"👋 <b>¡Listo! Ya estoy conectado a tu aula virtual.</b>\n\n"
            f"Sigo {len(courses)} materias:\n{names}\n\n"
            f"Tienes {pending_week} entregas pendientes en los próximos 7 días.\n"
            f"Reviso cada {poll_minutes} minutos y te aviso de tareas nuevas, cambios de fecha, anuncios, "
            f"notas y material. Pregúntame «¿qué tengo pendiente?» o cualquier duda sobre el material.")


def vinci_greeting() -> str:
    return ("👋 <b>¡Hola! Soy Vinci</b>, tu guía académico de ESPOL.\n"
            "• Pregúntame lo que quieras de tus materias: pendientes, anuncios, notas o el material.\n"
            "• Pásame lo de una materia (texto, foto, PDF o nota de voz) y se lo doy a su bot.\n"
            "• Te aviso de lo nuevo en tu aula virtual.\n"
            "Si todavía no tienes tus bots de materia, dime «arma mi equipo».")


def subject_greeting(display: str, name: str, code: str, brief_minutes: int, has_schedule: bool,
                     next_class: datetime | None, tz: ZoneInfo, now: datetime) -> str:
    who = f"el bot de {e(name)}" if display == name else f"{e(display)}, el bot de {e(name)}"
    lines = [f"👋 <b>¡Hola! Soy {who}</b> ({e(code)}).",
             (f"• {brief_minutes} minutos antes de cada clase te mando un brief: repaso, lo que vence, material "
              "nuevo y los conceptos clave."),
             ("• Cuéntame lo que vieron en clase o mándame fotos de la pizarra y notas de voz: lo guardo en mi "
              "cuaderno."),
             "• Pregúntame del material del curso o pídeme preguntas tipo examen."]
    if next_class:
        start = next_class.astimezone(tz)
        brief = start - timedelta(minutes=brief_minutes)
        day = _day_label(start.date(), now.astimezone(tz).date()).lower()
        lines.append(f"📅 Tu próxima clase: {day}, {start:%H:%M}. El brief te llega a las {brief:%H:%M}.")
    elif has_schedule:
        lines.append("📅 Tu horario no tiene clases de esta materia; si falta alguna, mándale a Vinci otra captura.")
    else:
        lines.append("📅 Todavía no tengo tu horario: mándale a Vinci una captura y te aviso antes de cada clase.")
    return "\n".join(lines)


def alert(text: str) -> str:
    return f"⚠️ {e(text)}"


def plain(html_text: str) -> str:
    """Telegram HTML → plain text (links keep their URL), for storing and handing off."""
    text = re.sub(r'<a href="([^"]*)">(.*?)</a>', lambda m: f"{m[2]} ({unescape(m[1])})", html_text, flags=re.S)
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()


def handoff_button(display: str) -> str:
    return f"🎓 Consultar con {display}"


def handoff_queued(display: str, handle: str, *, again: bool = False) -> str:
    chat = f"su chat ({e(handle)})" if handle != display else "su chat"
    if again:
        return f"📨 Ya le había pasado ese aviso a <b>{e(display)}</b>. Revisa {chat}."
    return f"📨 Le pasé el aviso a <b>{e(display)}</b>. Te responde en {chat} en un momento."


def schedule_card(rendered_html: str, count: int, warnings: list[str]) -> str:
    parts = [f"🗓️ <b>Esto es lo que leí de tu horario</b> ({count} clases)", rendered_html]
    if warnings:
        parts.append("\n".join(f"⚠️ {e(w)}" for w in warnings))
    parts.append("¿Está bien? Pulsa <b>Guardar horario</b> y cada bot de materia te mandará su brief antes de "
                 "cada clase. Si algo está mal, pulsa <b>Corregir</b> y dime qué cambiar.")
    return "\n\n".join(parts)
