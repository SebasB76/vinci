"""«🆕 Novedades de Vinci»: once per person (the captain and each friend's Vinci, each with its own database), what a
release brought, followed by a button to «Todo lo que hace Vinci» (docs/funciones/).

The poll sends it (poller.Bot.poll) during the day only, so a Redeploy at night does not wake anyone up. Someone
welcomed for the first time in that poll is marked as having seen it: everything is new to them.

For a new release: change RELEASE and ITEMS. Each item's id is a feature's id in docs/funciones/funciones.js, which
marks those cards «Nuevo» for NEW_DAYS.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from aula_core.store import get_meta, set_meta
from espol_bot import whatsapp
from espol_bot.config import BotConfig

RELEASE = date(2026, 11, 9)
SEEN = "whats_new_seen"
DAY_HOURS = range(8, 21)  # local hours a news message may go out
NEW_DAYS = 30             # the page marks this release's features «Nuevo» this long
BUTTON = "✨ Todo lo que hace Vinci"
# (the feature's id in funciones.js, the line the student reads), Vinci's voice, no commands
ITEMS: tuple[tuple[str, str], ...] = (
    ("repaso", "📚 <b>Repasos interactivos.</b> Pídeme «ármame un repaso de la distribución normal para la lección». "
               "Te llega una página con la explicación, gráficos que puedes mover y un quiz."),
    ("archivos", "📤 <b>Entrega cualquier archivo.</b> Mándame tu Word, tu ZIP o tu PDF y dime «entrégalo en el deber "
                 "3». Lo subo al aula cuando votes «Entregar»."),
    ("grupo-entrega", "👥 <b>Entrega desde el grupo.</b> En el grupo del trabajo, responde al archivo de tu compañero "
                      "con «@vinci sube esto al informe final». Votas por privado y yo aviso en el grupo."),
    ("curso", "📊 <b>Tu nota frente al curso.</b> Cuando sale una nota, te digo el promedio del curso, la nota más "
              "alta y la más baja."),
    ("plan", "🧭 <b>Qué materias tomar.</b> Con tu Académico conectado, pregúntame «¿qué materias puedo tomar el "
             "próximo semestre?». Leo tu malla y te digo lo que ya puedes tomar y lo que te falta."),
    ("calendario", "🗓️ <b>El calendario de ESPOL.</b> Los feriados y el fin de clases salen en tu resumen de las "
                   "7:00. También puedes preguntarme «¿cuándo terminan las clases?»."),
    ("audio", "🔊 <b>Respuestas en audio.</b> Dime «respóndeme por audio» y te contesto con una nota de voz."),
    ("cambios", "🎴 <b>Tu álbum.</b> Hay 37 cartas nuevas y te salen menos repetidas. Cambias 3 repetidas por un sobre "
                "en «Cambios», y en el ranking ves las cartas de cada uno."),
)


def page_url(cfg: BotConfig, now: datetime) -> str:
    """The features page; on WhatsApp it carries Vinci's number, so an example opens the chat with it typed."""
    if not cfg.features_page:
        return ""
    params = {}
    number = whatsapp.own_number() if not cfg.telegram else ""
    if number:
        params["wa"] = number
    if now.astimezone(cfg.core.tz).date() - RELEASE <= timedelta(days=NEW_DAYS):
        params["n"] = ",".join(i for i, _ in ITEMS)
    return cfg.features_page + (f"#{urlencode(params, safe=',')}" if params else "")


def mark_seen(conn: sqlite3.Connection) -> None:
    set_meta(conn, SEEN, RELEASE.isoformat())


def deliver(conn: sqlite3.Connection, cfg: BotConfig, sender, now: datetime) -> list[str]:
    """This release's news, once, in the day; the texts sent. A failed send raises and waits for the next poll."""
    if get_meta(conn, SEEN) == RELEASE.isoformat() or now.astimezone(cfg.core.tz).hour not in DAY_HOURS:
        return []
    text = "🆕 <b>Novedades de Vinci</b>\n\n" + "\n\n".join(line for _, line in ITEMS)
    sender.send(text)
    mark_seen(conn)
    conn.commit()
    url = page_url(cfg, now)
    if url:  # a short message of its own: a WhatsApp button's text has a short limit
        intro = "Y todo lo demás que hago, con un ejemplo para probar cada cosa:"
        if cfg.telegram:
            sender.send(intro, reply_markup={"inline_keyboard": [[{"text": BUTTON, "url": url}]]})
        else:
            sender.send(intro, link={"text": BUTTON, "url": url})
    return [text]

