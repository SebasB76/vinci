"""The TAWS section of the album: who is a member, and their club packs, with no model.

«/taws» checks the sender: their name in Canvas (which only they can sign in to) against the members listed on
taws.espol.edu.ec. A match makes them a member at once, with a welcome pack of club cards. No match, or two, asks the
captain, who answers «/taws acepta <name>». Membership lives in each person's espol.db (meta `club:taws`), so
album.py shows the section only to them.

A member found on the site keeps their cards if they leave it later, but `espol-bot album-regalo --club taws` checks
the list again and gives nothing more to someone no longer on it. One the captain accepted stays a member.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import requests

from aula_core import Aula, timefmt
from aula_core.catalog import fold
from aula_core.enlaces import route
from aula_core.store import get_meta, set_meta
from espol_bot import album, amigos, trades, whatsapp
from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

CLUB = "taws"
MEMBERS_URL = "https://taws.espol.edu.ec/api/members?limit=500&depth=0"
PENDING = "taws-pendientes.json"  # in the captain's amigos/: who asked and was not found
TIMEOUT = 20
WELCOME = "Bienvenido a la sección TAWS de tu álbum"


def members(cfg: BotConfig) -> list[str]:
    """The full names of the active members on the club's site. Raises on a site that does not answer."""
    response = requests.get(route(MEMBERS_URL, cfg.core), timeout=TIMEOUT, headers={"User-Agent": "Vinci"})
    response.raise_for_status()
    return [str(m["fullName"]) for m in response.json().get("docs") or []
            if m.get("fullName") and m.get("status", "active") == "active"]


def matches(canvas_name: str, listed: list[str]) -> list[str]:
    """The listed names whose every word is in the Canvas name: the site shows «Name Surname», Canvas the full name."""
    words = set(fold(canvas_name).split())
    return [n for n in listed if (parts := fold(n).split()) and len(parts) >= 2 and set(parts) <= words]


def is_member(conn) -> bool:
    return bool(get_meta(conn, f"{album.CLUB}{CLUB}"))


def _join(conn, now: datetime, via: str, name: str) -> None:
    set_meta(conn, f"{album.CLUB}{CLUB}", json.dumps({"at": timefmt.iso(now), "via": via, "nombre": name}))
    conn.commit()


def _welcome(conn, owner: BotConfig, now: datetime) -> dict | None:
    """The welcome pack, already marked sent: the button that opens it, for the answer itself."""
    if not owner.album_page or not album.give_club(conn, now, CLUB, WELCOME, tag="bienvenida"):
        return None
    pack = conn.execute("SELECT * FROM album_packs ORDER BY id DESC LIMIT 1").fetchone()
    conn.execute("UPDATE album_packs SET sent_at = ? WHERE id = ?", (timefmt.iso(now), pack["id"]))
    conn.commit()
    return {"text": album.BUTTON, "url": album.page_url(owner, album.snapshot(conn, now, pack))}


def _pending(cfg: BotConfig) -> dict:
    try:
        return json.loads((amigos.root(cfg) / PENDING).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_pending(cfg: BotConfig, data: dict) -> None:
    amigos._write(amigos.root(cfg) / PENDING, data)


def command(cfg: BotConfig, number: str, text: str, now: datetime) -> amigos.Outcome:
    """«/taws» from anyone with a Vinci; «/taws acepta <name>» from the captain."""
    people = trades._people(cfg)
    person = next(p for p in people if p.number == number)
    words = text.strip().split(" ", 1)
    if person.friend is None and fold(words[0]) in ("acepta", "aceptar", "si"):
        return _accept(cfg, people, words[1] if len(words) > 1 else "", now)
    with trades._album(cfg, person, lock=True) as (owner, conn):
        if is_member(conn):
            link = album.whatsapp_link(conn, owner, now)
            return amigos.Outcome("Ya eres de TAWS: tu sección está en tu álbum.",
                                  button={"text": album.ALBUM_BUTTON, "url": link["url"]} if link else None)
        if not album.club_catalog(CLUB):
            return amigos.Outcome("La sección TAWS del álbum todavía no está lista en este Vinci.")
        aula = Aula(owner.core)
        try:
            canvas_name = str(aula.client.get("users/self").get("name") or "")
        except Exception:
            log.exception("taws: no pude leer el nombre en Canvas de %s", person.name)
            return amigos.Outcome("Para comprobar que eres de TAWS necesito leer tu nombre en el aula virtual, y ahora "
                                  "no pude. Si tu aula no está conectada, escribe /token.")
        finally:
            aula.close()
        try:
            found = matches(canvas_name, members(owner))
        except (requests.RequestException, ValueError, KeyError):
            log.exception("taws: no pude leer la lista de miembros")
            found = []
        if len(found) == 1:
            _join(conn, now, "web", found[0])
            button = _welcome(conn, owner, now)
            return amigos.Outcome("✅ Estás en la lista de miembros de TAWS: ya tienes la sección TAWS en tu álbum. "
                                  "Te dejo tu primer sobre del club.", button=button)
    asked = _pending(cfg)
    asked[number] = {"nombre": person.name, "canvas": canvas_name, "at": timefmt.iso(now)}
    _save_pending(cfg, asked)
    captain = amigos.captain_number(cfg)
    first = person.name.split(" ")[0]
    try:
        whatsapp.WhatsApp(captain, cfg.whatsapp_bridge).send(
            f"🎴 {person.name} pide la sección TAWS del álbum. En el aula se llama «{canvas_name}», y no lo encontré "
            f"{'una sola vez ' if found else ''}en la lista de taws.espol.edu.ec.\n\nSi es del club: /taws acepta {first}")
    except whatsapp.WhatsAppError:
        log.exception("taws: no pude avisarle al capitán")
    return amigos.Outcome("No te encontré en la lista de miembros de taws.espol.edu.ec, así que le pregunté al "
                          "capitán. Cuando te acepte, te llega tu primer sobre TAWS.")


def _accept(cfg: BotConfig, people: list, who: str, now: datetime) -> amigos.Outcome:
    asked = _pending(cfg)
    waiting = [p for p in people if p.number in asked]
    found = trades._who(who, waiting) if who else None
    if found is None:
        names = ", ".join(p.name for p in waiting) or "nadie"
        return amigos.Outcome(f"Así: /taws acepta <nombre>. Esperando: {names}.")
    person = found[0]
    with trades._album(cfg, person, lock=True) as (owner, conn):
        _join(conn, now, "capitan", asked[person.number].get("canvas") or person.name)
        button = _welcome(conn, owner, now)
    asked.pop(person.number)
    _save_pending(cfg, asked)
    if person.friend is not None:
        try:
            text = "✅ El capitán te aceptó en TAWS: ya tienes la sección TAWS en tu álbum. Tu primer sobre del club:"
            sender = whatsapp.WhatsApp(person.number, cfg.whatsapp_bridge)
            sender.send(text, link=button) if button else sender.send(text)
        except whatsapp.WhatsAppError:
            log.exception("taws: no pude avisarle a %s", person.name)
    return amigos.Outcome(f"Listo: {person.name} ya es de TAWS en el álbum.")


def gift(cfg: BotConfig, reason: str, now: datetime) -> list[str]:
    """A club pack for each member still a member (`album-regalo --club taws`), sent at once; a line per person."""
    try:
        listed = members(cfg)
    except (requests.RequestException, ValueError, KeyError) as exc:
        return [f"No pude leer la lista de taws.espol.edu.ec ({exc}): no regalé nada."]
    lines = []
    for person in trades._people(cfg):
        with trades._album(cfg, person, lock=True) as (owner, conn):
            joined = get_meta(conn, f"{album.CLUB}{CLUB}")
            if not joined:
                continue
            info = json.loads(joined)
            if info.get("via") == "web" and info.get("nombre") not in listed:
                lines.append(f"· {person.name}: ya no está en la lista de la web, no le llega")
                continue
            if not album.give_club(conn, now, CLUB, reason):
                lines.append(f"· {person.name}: sin catálogo TAWS")
                continue
            try:
                album.deliver(conn, owner, whatsapp.WhatsApp(person.number, owner.whatsapp_bridge), now)
                lines.append(f"🎁 {person.name}: ya se lo mandé")
            except whatsapp.WhatsAppError as exc:
                lines.append(f"· {person.name}: le llega en el próximo sondeo ({exc})")
    return lines or ["Nadie es de TAWS todavía."]
