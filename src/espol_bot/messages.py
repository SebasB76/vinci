"""Spanish Telegram messages (HTML parse mode) built without any model call."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aula_core import timefmt

KIND_TITLE = {
    "new_assignment": "📝 Tareas nuevas",
    "due_changed": "📅 Cambios de fecha",
    "new_announcement": "📢 Anuncios nuevos",
    "grade_posted": "✅ Notas publicadas",
    "grade_changed": "✏️ Notas actualizadas",
    "new_file": "📚 Material nuevo",
    "file_updated": "📚 Material actualizado",
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
        module = f" · {e(ev['modulo'])}" if ev.get("modulo") else ""
        ready = "\nYa lo leí: puedes preguntarme sobre él." if index_status == "ok" else ""
        return f"📚 <b>{verb} en {course}</b>{module}\n{e(ev['archivo'])}{ready}\n{link(ev['url'], 'Ver archivo')}"
    if kind == "new_course":
        return f"🎓 <b>Nueva materia en tu aula virtual</b>\n{course}\nDesde ahora te aviso de sus tareas y anuncios.\n{link(ev['url'])}"
    return f"{course}: {e(kind)}"


def _digest_line(ev: dict, tz: ZoneInfo) -> str:
    kind = ev["kind"]
    name = str(ev.get("tarea") or ev.get("titulo") or ev.get("archivo") or ev["curso"])
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
                   tz: ZoneInfo, now: datetime) -> str:
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
    if announcements_24h:
        blocks.append(f"<b>Anuncios de las últimas 24 h ({len(announcements_24h)})</b>\n" + "\n".join(
            f"• {e(a['curso'])}: {link(a['url'], a['titulo'])}" for a in announcements_24h))
    return "\n\n".join(blocks)


def welcome(courses: list[dict], pending_week: int, poll_minutes: int) -> str:
    names = "\n".join(f"• {e(c['nombre'])}" for c in courses) or "(no encontré materias activas)"
    return (f"👋 <b>¡Listo! Ya estoy conectado a tu aula virtual.</b>\n\n"
            f"Sigo {len(courses)} materias:\n{names}\n\n"
            f"Tienes {pending_week} entregas pendientes en los próximos 7 días.\n"
            f"Reviso cada {poll_minutes} minutos y te aviso de tareas nuevas, cambios de fecha, anuncios, "
            f"notas y material. Pregúntame «¿qué tengo pendiente?» o cualquier duda sobre el material.")


def alert(text: str) -> str:
    return f"⚠️ {e(text)}"
