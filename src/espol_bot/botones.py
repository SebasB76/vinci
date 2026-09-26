"""What Vinci's inline buttons do. The Hermes plugin `vinci-botones` receives the
button press in Vinci's gateway, checks it comes from the captain, and runs
`espol-bot boton <callback_data>`; this module does the work and answers what the
plugin should show:

  v1:a:<aviso>:<CÓDIGO>   «Consultar con Vinci · <materia>» under an alert: queues the
                          alert as a handoff for that subject bot (once per alert and subject)
  v1:h:<propuesta>:ok     «Guardar horario»: validates the proposal again and saves horario.toml
  v1:h:<propuesta>:no     «Corregir»: discards the proposal
  v1:c:0:<CÓDIGO>         «➕ Crear Vinci · <materia>»: the subject waits for its bot and Vinci
                          sends the button that creates it (or the @BotFather steps)
  v1:x:0:<CÓDIGO>         «🗄️ Archivar»: parks the subject bot and pauses its agenda
  v1:r:0:<CÓDIGO>         «♻️ Reactivar»: undoes it
  v1:n:0:<CÓDIGO>         «Cancelar»: does nothing

No model is involved: the schedule is saved, and a bot created or archived, only by the
captain's own press.
"""

from __future__ import annotations

import re
from datetime import datetime

from aula_core import Aula
from espol_bot import equipo, horario, materias, messages, store
from espol_bot.config import BotConfig, load_telegram_secrets
from espol_bot.telegram import Telegram, TelegramError

PATTERN = re.compile(r"v1:([ahcxrn]):(\d{1,12}):([A-Za-z0-9]{2,12})")


def _answer(toast: str, reply: str | None = None, remove_buttons: bool = False) -> dict:
    return {"aviso": toast, "respuesta": reply, "quitar_botones": remove_buttons}


def handle(cfg: BotConfig, data: str, now: datetime) -> dict:
    match = PATTERN.fullmatch(data.strip())
    if not match:
        return _answer("Botón desconocido.")
    kind, ref, arg = match[1], int(match[2]), match[3]
    if kind in "cxrn":
        return _team(cfg, kind, arg.upper())
    aula = Aula(cfg.core)
    try:
        conn = store.ensure(aula.conn)
        if kind == "a":
            return _handoff(cfg, conn, ref, arg.upper(), now)
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


def _team(cfg: BotConfig, kind: str, code: str) -> dict:
    subject = materias.by_code(materias.load(cfg.core), code)
    if subject is None:
        return _answer("Esa materia ya no está en tu equipo.")
    if kind == "n":
        return _answer("Listo, no hago nada", "👌 Listo, no hice nada.", remove_buttons=True)
    if kind in "xr":
        return _answer("Hecho", equipo.set_archived(cfg, code, kind == "x"), remove_buttons=True)
    if subject.state in ("activa", "archivada"):
        return _answer(f"{subject.display} ya tiene bot ({subject.state}).")
    materias.update(cfg.core, code, state=equipo.WAITING)
    vinci = Telegram(load_telegram_secrets(), api=cfg.telegram_api)
    try:
        can_manage = bool(vinci.get_me().get("can_manage_bots"))
    except TelegramError:
        can_manage = False
    text, markup = equipo.creation_message(subject, can_manage)
    vinci.send(text, reply_markup=markup)
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
