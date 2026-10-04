"""What Vinci's inline buttons do. The Hermes plugin `vinci-botones` receives the
button press in Vinci's gateway, checks it comes from the captain, and runs
`espol-bot boton <callback_data>`; this module does the work and answers what the
plugin should show:

  v1:a:<aviso>:<CÓDIGO>   «Consultar con <bot>» under an alert: queues the
                          alert as a handoff for that subject bot (once per alert and subject)
  v1:h:<propuesta>:ok     «Guardar horario»: validates the proposal again and saves horario.toml
  v1:h:<propuesta>:no     «Corregir»: discards the proposal
  v1:c:0:<CÓDIGO>         «➕ Crear <bot>»: the subject waits for its bot and Vinci
                          sends the button that creates it (or the @BotFather steps); pressed
                          again within minutes, it points at what it already sent
  v1:x:0:<CÓDIGO>         «🗄️ Archivar»: parks the subject bot and pauses its agenda
  v1:r:0:<CÓDIGO>         «♻️ Reactivar»: undoes it
  v1:n:0:<CÓDIGO>         «Cancelar»: does nothing
  v1:s:<tarea>:ok|no      «✅ Ya lo entregué» under a reminder: the assignment counts as submitted
                          (handed in outside Canvas), so no reminder or summary lists it again;
                          its button turns into «↩️ Aún no lo entregué», which undoes it
  v1:t:<pendiente>:ok|no  «✅ Hecho» under a to-do (its card, a reminder, the summary): closes it;
                          the button turns into «↩️ Deshacer: <pendiente>», which undoes it
  v1:g:<propuesta>:ok     «Guardar esquema» under a grading scheme a bot proposed (in Vinci's chat or the
                          subject bot's): saves it as how that subject is graded and answers how the captain
                          is doing under it
  v1:g:<propuesta>:no     «Corregir»: discards it
  v1:k:<nota>:<CÓDIGO>    a subject under a note of the captain's notes folder (notes.py): the note is that
                          subject's, its //vinci questions and its summary go to that bot
  v1:k:<nota>:no          «No es de clase»: the note is never read again
  v1:k:<nota>:cambiar     «Cambiar materia»: sends the card with every subject

No model is involved: the schedule and a grading scheme are saved, and a bot created or archived,
only by the captain's own press.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from aula_core import Aula, timefmt
from aula_core.store import file_lock, get_meta, set_marked_submitted, set_meta
from espol_bot import equipo, grades, horario, materias, messages, store
from espol_bot.config import BotConfig, load_telegram_secrets
from espol_bot.telegram import Telegram, TelegramError

PATTERN = re.compile(r"v1:([aghckxrnst]):(-?\d{1,20}):([A-Za-z0-9]{2,12})")  # feed-only items have negative ids
OFFER_KEY = "bot_creation_offer"  # the last creation message sent: {"code", "sent_at", "keyboard"}
# A second «Crear» this soon is a double press: the keyboard button already sent is still the chat's latest.
OFFER_AGAIN = timedelta(minutes=5)


def _answer(toast: str, reply: str | None = None, remove_buttons: bool = False,
            replace_button: tuple[str, str] | None = None) -> dict:
    """`replace_button` swaps the pressed button for (label, callback data), leaving the others."""
    answer = {"aviso": toast, "respuesta": reply, "quitar_botones": remove_buttons}
    if replace_button:
        answer["replace_button"] = list(replace_button)
    return answer


def handle(cfg: BotConfig, data: str, now: datetime) -> dict:
    match = PATTERN.fullmatch(data.strip())
    if not match:
        return _answer("Botón desconocido.")
    kind, ref, arg = match[1], int(match[2]), match[3]
    if kind in "cxrn":
        return _team(cfg, kind, arg.upper(), now)
    aula = Aula(cfg.core)
    try:
        conn = store.ensure(aula.conn)
        if kind == "a":
            return _handoff(cfg, conn, ref, arg.upper(), now)
        if kind == "s":
            return _submitted(conn, ref, arg == "ok", now)
        if kind == "t":
            return _todo_done(conn, ref, arg == "ok", now)
        if kind == "g":
            return _grading_scheme(cfg, conn, ref, arg == "ok", now)
        if kind == "k":
            from espol_bot import notes
            return notes.choose(cfg, conn, ref, arg, now)
        return _save_schedule(cfg, conn, ref, now) if arg == "ok" else _discard(conn, ref, now)
    finally:
        aula.close()


def _handoff(cfg: BotConfig, conn, alert_id: int, code: str, now: datetime) -> dict:
    alert = store.alert(conn, alert_id)
    if alert is None or code not in alert["materias"]:
        return _answer("Ese aviso ya no está disponible.")
    subject = materias.by_code(materias.load(cfg.core), code)
    if subject is None or not subject.active:
        return _answer(f"El bot de {subject.name if subject else code} no está activo.")
    _, created = store.queue_handoff(conn, code, "aviso", alert["texto"], now, alert_id=alert_id)
    toast = f"Enviado a {subject.display}" if created else f"Ya estaba enviado a {subject.display}"
    return _answer(toast, messages.handoff_queued(subject.display, subject.handle(), again=not created))


def _submitted(conn, assignment_id: int, submitted: bool, now: datetime) -> dict:
    row = conn.execute("SELECT name FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if row is None:
        return _answer("Esa tarea ya no está en tu aula virtual.")
    set_marked_submitted(conn, assignment_id, submitted, timefmt.iso(now))
    if submitted:
        return _answer(f"Listo: «{row['name']}» cuenta como entregada; no te la recuerdo más.",
                       replace_button=(messages.UNSUBMITTED_BUTTON, f"v1:s:{assignment_id}:no"))
    return _answer(f"«{row['name']}» vuelve a tus pendientes.",
                   replace_button=(messages.SUBMITTED_BUTTON, f"v1:s:{assignment_id}:ok"))


def _todo_done(conn, todo_id: int, done: bool, now: datetime) -> dict:
    todo = store.todo(conn, todo_id)
    if todo is None:
        return _answer("Ese pendiente ya no está en tu lista.")
    store.set_todo_done(conn, todo_id, done, now)
    if done:
        return _answer(f"✅ Hecho: «{todo['text']}».", replace_button=(messages.todo_undo_button(todo["text"]), f"v1:t:{todo_id}:no"))
    return _answer(f"«{todo['text']}» vuelve a tu lista.",
                   replace_button=(messages.todo_done_button(todo["text"]), f"v1:t:{todo_id}:ok"))


def _grading_scheme(cfg: BotConfig, conn, proposal_id: int, save: bool, now: datetime) -> dict:
    proposal = store.scheme_proposal(conn, proposal_id)
    if proposal is None:
        return _answer("No encuentro ese esquema.")
    if not store.resolve_scheme_proposal(conn, proposal_id, save, now):
        state = {"saved": "guardado", "discarded": "descartado"}.get(proposal["state"], proposal["state"])
        return _answer(f"Ese esquema ya fue {state}.", remove_buttons=True)
    subject = materias.by_code(materias.load(cfg.core), proposal["subject"])
    name = subject.name if subject else proposal["subject"]
    if not save:
        return _answer("No lo guardé", (
            f"✏️ Listo, no lo guardé. Dime qué cambiar de cómo se evalúa {messages.e(name)} (por ejemplo «el examen del "
            "primer parcial lo reemplaza una lección que vale lo mismo») y te muestro otro."), remove_buttons=True)
    reply = f"✅ <b>Guardé cómo se evalúa {messages.e(name)}</b>."
    if subject is not None:
        reply += "\n\n" + messages.e(grades.status(conn, subject, cfg.core.tz)["summary"])
    return _answer("Esquema guardado", reply, remove_buttons=True)


def _team(cfg: BotConfig, kind: str, code: str, now: datetime) -> dict:
    subject = materias.by_code(materias.load(cfg.core), code)
    if subject is None:
        return _answer("Esa materia ya no está en tu equipo.")
    if kind == "n":
        return _answer("Listo, no hago nada", "👌 Listo, no hice nada.", remove_buttons=True)
    if kind in "xr":
        return _answer("Hecho", equipo.set_archived(cfg, code, kind == "x"), remove_buttons=True)
    if subject.state in ("activa", "archivada"):
        return _answer(f"{subject.display} ya tiene bot ({subject.state}).")
    with file_lock(cfg.core.data_dir, "equipo.lock"):  # two quick presses: only one sends
        aula = Aula(cfg.core)
        try:
            last = json.loads(get_meta(aula.conn, OFFER_KEY) or "{}")
            sent = timefmt.parse(last.get("sent_at"))
            if subject.state == equipo.WAITING and last.get("code") == code and sent and now - sent < OFFER_AGAIN:
                return _answer(f"Ya te mandé el botón «🤖 Crear {subject.display}»: está en el teclado de abajo."
                               if last.get("keyboard") else
                               f"Ya te mandé los pasos para crear {subject.display}: están justo arriba.")
            materias.update(cfg.core, code, state=equipo.WAITING)
            vinci = Telegram(load_telegram_secrets(), api=cfg.telegram_api)
            try:
                can_manage = bool(vinci.get_me().get("can_manage_bots"))
            except TelegramError:
                can_manage = False
            text, markup = equipo.creation_message(subject, can_manage)
            vinci.send(text, reply_markup=markup)
            set_meta(aula.conn, OFFER_KEY, json.dumps({"code": code, "sent_at": timefmt.iso(now),
                                                       "keyboard": markup is not None}))
            aula.conn.commit()
        finally:
            aula.close()
    return _answer(f"Creemos {subject.display}")


def _save_schedule(cfg: BotConfig, conn, proposal_id: int, now: datetime) -> dict:
    proposal = store.proposal(conn, proposal_id)
    if proposal is None:
        return _answer("No encuentro esa propuesta de horario.")
    if proposal["estado"] != "pendiente":
        return _answer(f"Esa propuesta ya fue {proposal['estado']}.", remove_buttons=True)
    classes, errors, _ = horario.validate(proposal["clases"], materias.load(cfg.core))
    if errors:
        return _answer("No pude guardarlo: el horario no es válido.", "⚠️ " + messages.e(" ".join(errors)))
    horario.save(cfg.core, classes, now.astimezone(cfg.core.tz))
    store.resolve_proposal(conn, proposal_id, "guardada", now)
    return _answer("Horario guardado", (
        f"✅ <b>Guardé tu horario</b>: {len(classes)} clases.\n"
        f"Cada bot de materia te mandará su brief {cfg.brief_minutes} minutos antes de cada clase. "
        "Si algo cambia, mándame otra captura o edita el archivo horario.toml."), remove_buttons=True)


def _discard(conn, proposal_id: int, now: datetime) -> dict:
    if not store.resolve_proposal(conn, proposal_id, "descartada", now):
        return _answer("Esa propuesta ya no estaba pendiente.", remove_buttons=True)
    return _answer("No lo guardé", (
        "✏️ Listo, no lo guardé. Dime qué corregir (por ejemplo «Estadística el jueves es de 10:00 a 12:00») "
        "y te muestro otra propuesta."), remove_buttons=True)
