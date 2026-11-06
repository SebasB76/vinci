"""Card trades on WhatsApp between people with a Vinci (the captain and each friend with their token), with no model.

«/cambio» lists the sender's repeated cards and, for the cards they lack, who has them repeated. «/cambio Angel
Bosque por Lago» offers one of the sender's repeats for one of Angel's: Angel gets the offer privately with a poll,
and a «✅ Acepto» vote swaps the two cards in both albums (each person's espol.db). Only a repeat changes hands, so
nobody loses a card from their album. An offer lasts OFFER_HOURS; a new one to the same person replaces it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from aula_core import timefmt
from aula_core.catalog import fold
from aula_core.config import load_secret_values
from aula_core.store import connect, file_lock
from espol_bot import album, amigos, whatsapp
from espol_bot.config import CAPTAIN_SECRETS, BotConfig, whatsapp_settings
from espol_bot.store import ensure as store_ensure

log = logging.getLogger(__name__)

OFFERS = "cambios.json"
OFFER_HOURS = 48
ACCEPT, DECLINE = "✅ Acepto el cambio", "❌ No, gracias"
VOTE_RE = re.compile(r"c:([0-9a-f]{6,16}):(ok|no)")
CAPTAIN_WORDS = ("capitan", "el capitan")
HOW = "Así: /cambio Angel Bosque protector por Lago ESPOL (tu repetida primero, después la suya)."
SHOWN = 6  # cards per person in the overview
TRADES_BUTTON = "🔁 Ver los cambios"


@dataclass
class Person:
    number: str
    name: str
    friend: amigos.Friend | None  # None: the captain
    db: Path


def _people(cfg: BotConfig) -> list[Person]:
    return _roster(amigos.root(cfg).parent, amigos.captain_number(cfg))


def _roster(home: Path, captain: str) -> list[Person]:
    """The captain and each active friend; `home` is the captain's data folder, where amigos/ lives."""
    def read(name: str) -> dict:
        try:
            return json.loads((home / "amigos" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    names, friends = read("whatsapp-nombres.json"), read("amigos.json").get("amigos") or []
    # a WhatsApp name may start with a dash or an emoji («-Sebastian B»), as in avisos.members
    first = re.sub(r"^\W+", "", str(names.get(captain) or "")).strip() or "Capitán"
    active = [amigos.Friend(**f) for f in friends if f.get("estado") == amigos.ACTIVE]
    return [Person(captain, first, None, home / "espol.db"),
            *(Person(f.numero, f.nombre, f, home / "amigos" / f.slug / "espol.db") for f in active)]


@contextmanager
def _album(cfg: BotConfig, person: Person, lock: bool = False):
    """(that person's BotConfig, their espol.db); `lock` holds their bot.lock, as a poll does."""
    with nullcontext(cfg) if person.friend is None else amigos.scope(cfg, person.friend) as owner:
        conn = store_ensure(connect(owner.core.db_path))
        try:
            with file_lock(owner.core.data_dir, "bot.lock") if lock else nullcontext():
                yield owner, conn
        finally:
            conn.close()


def _names() -> dict[str, dict]:
    return {c["id"]: c for c in album.catalog()}


def _card(text: str) -> dict | list[dict]:
    """The card `text` names: by its whole name or id, else the only one whose name contains it; a list when it is
    none or several."""
    wanted = fold(re.sub(r"\s+", " ", text)).strip(" .«»\"'")
    cards = album.catalog()
    exact = [c for c in cards if wanted in (fold(c["name"]), c["id"])]
    if exact:
        return exact[0]
    found = [c for c in cards if wanted and wanted in fold(c["name"])]
    return found[0] if len(found) == 1 else found


def _who(text: str, people: list[Person]) -> tuple[Person, str] | None:
    """The person `text` starts with (their whole name, or their first name) and what follows."""
    folded = fold(text)
    options = []
    for p in people:
        for name in {fold(p.name), fold(p.name).split(" ")[0], *(CAPTAIN_WORDS if p.friend is None else ())}:
            if name and (folded == name or folded.startswith(name + " ")):
                options.append((len(name), p))
    if not options:
        return None
    size, person = max(options, key=lambda o: o[0])
    return person, text[size:].strip()


def _repeats(have: dict[str, int]) -> dict[str, int]:
    known = _names()
    return {card: n for card, n in have.items() if n >= 2 and card in known}


def market(cfg: BotConfig) -> dict:
    """The album page's «Cambios» tab: Vinci's number and every other person's repeats ({"wa", "people": [{"name",
    "cards"}]}); {} off WhatsApp or with no friends. `cfg` may be the captain's or a friend's (amigos/<slug>/)."""
    data_dir = cfg.core.data_dir
    home = data_dir.parent.parent if data_dir.parent.name == "amigos" else data_dir
    if not (home / "amigos" / "amigos.json").exists():
        return {}
    captain = os.environ.get(CAPTAIN_SECRETS)  # a friend's Vinci reads the captain's number from his secrets.env
    wa = whatsapp_settings(load_secret_values(Path(captain) if captain else None))
    if wa is None:
        return {}
    people = []
    for p in _roster(home, wa.captain):
        if p.db == cfg.core.db_path or not p.db.exists():
            continue
        try:
            conn = sqlite3.connect(f"{p.db.as_uri()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                cards = _repeats(album.collection(conn))
            finally:
                conn.close()
        except sqlite3.Error:  # an album not started yet
            continue
        if cards:
            people.append({"name": p.name, "cards": cards})
    return {"wa": whatsapp.own_number(), "people": people}


def _load(cfg: BotConfig, now: datetime) -> dict[str, dict]:
    try:
        offers = json.loads((amigos.root(cfg) / OFFERS).read_text(encoding="utf-8")).get("ofertas") or {}
    except (OSError, ValueError):
        return {}
    cutoff = timefmt.iso(now - timedelta(hours=OFFER_HOURS))
    return {k: o for k, o in offers.items() if o.get("at", "") >= cutoff}


def _save(cfg: BotConfig, offers: dict[str, dict]) -> None:
    path = amigos.root(cfg) / OFFERS
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ofertas": offers}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _send(cfg: BotConfig, person: Person, text: str, link: dict | None = None) -> None:
    try:
        whatsapp.WhatsApp(person.number, cfg.whatsapp_bridge).send(text, link=link)
    except whatsapp.WhatsAppError as exc:
        log.warning("cambio: no pude escribirle a %s: %s", person.name, exc)


def command(cfg: BotConfig, number: str, text: str, now: datetime) -> amigos.Outcome:
    """«/cambio» (the overview) or «/cambio <persona> <tu carta> por <su carta>» (an offer)."""
    people = _people(cfg)
    me = next(p for p in people if p.number == number)
    if not text.strip():
        return _overview(cfg, me, people, now)
    return _offer(cfg, me, people, text, now)


def _overview(cfg: BotConfig, me: Person, people: list[Person], now: datetime) -> amigos.Outcome:
    known = _names()
    with _album(cfg, me) as (owner, conn):
        mine = album.collection(conn)
        link = album.whatsapp_link(conn, owner, now)
    repeats = _repeats(mine)
    lines = ["🔁 *Cambio de cartas*", ""]
    if repeats:
        lines.append("Tus repetidas: " + ", ".join(f"{known[c]['name']} ×{n}" for c, n in sorted(
            repeats.items(), key=lambda r: album.RARITIES.index(known[r[0]]["rarity"]))) + ".")
    else:
        lines.append("Todavía no tienes cartas repetidas, y solo se cambian las repetidas.")
    missing = set(known) - set(mine)
    lines.append(f"Te faltan {len(missing)} de {len(known)} cartas.")
    offers = []
    for p in people:
        if p.number == me.number:
            continue
        with _album(cfg, p) as (_, conn):
            theirs = [c for c in _repeats(album.collection(conn)) if c in missing]
        if theirs:
            theirs.sort(key=lambda c: -album.RARITIES.index(known[c]["rarity"]))
            more = f" y {len(theirs) - SHOWN} más" if len(theirs) > SHOWN else ""
            offers.append(f"• {p.name}: {', '.join(known[c]['name'] for c in theirs[:SHOWN])}{more}")
    if offers:
        lines += ["", "Tienen repetidas las que te faltan:", *offers]
    elif missing:
        lines += ["", "Nadie tiene repetida una carta que te falte, por ahora."]
    waiting = [o for o in _load(cfg, now).values() if o["to"] == me.number]
    for o in waiting:
        sender = next((p.name for p in people if p.number == o["from"]), "alguien")
        lines += ["", f"📨 {sender} te ofrece {known[o['give']]['name']} por tu {known[o['take']]['name']}: "
                      "contesta en la encuesta que te mandé."]
    if repeats:
        lines += ["", HOW]
    button = {"text": TRADES_BUTTON, "url": f"{link['url']}&t=cambios"} if link else None
    return amigos.Outcome("\n".join(lines), button=button)


def _offer(cfg: BotConfig, me: Person, people: list[Person], text: str, now: datetime) -> amigos.Outcome:
    found = _who(text, people)
    if found is None:
        names = ", ".join(p.name for p in people if p.number != me.number) or "nadie todavía"
        return amigos.Outcome(f"No sé con quién quieres cambiar. Pueden cambiar: {names}.\n{HOW}")
    partner, rest = found
    if partner.number == me.number:
        return amigos.Outcome(f"Ese eres tú 😄. {HOW}")
    parts = re.split(r"\s+por\s+", rest, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return amigos.Outcome(HOW)
    give, take = _card(parts[0]), _card(parts[1])
    for asked, card in ((parts[0], give), (parts[1], take)):
        if isinstance(card, list):
            hint = f" ¿Cuál de estas? {', '.join(c['name'] for c in card[:5])}." if card else ""
            return amigos.Outcome(f"No encontré la carta «{asked.strip()}» en el álbum.{hint}")
    if give["id"] == take["id"]:
        return amigos.Outcome("Es la misma carta: pide una que te falte.")
    with _album(cfg, me) as (_, conn):
        mine = album.collection(conn)
    if mine.get(give["id"], 0) < 2:
        return amigos.Outcome(f"No tienes {give['name']} repetida, y solo se cambian las repetidas. Escribe /cambio "
                              "para ver las tuyas.")
    if mine.get(take["id"], 0):
        return amigos.Outcome(f"Ya tienes {take['name']}: pide una que te falte.")
    with _album(cfg, partner) as (_, conn):
        theirs = album.collection(conn)
    if theirs.get(take["id"], 0) < 2:
        return amigos.Outcome(f"{partner.name} no tiene {take['name']} repetida. Escribe /cambio para ver quién "
                              "tiene repetidas las que te faltan.")
    with file_lock(amigos.root(cfg), f"{OFFERS}.lock"):
        offers = {k: o for k, o in _load(cfg, now).items()
                  if (o["from"], o["to"]) != (me.number, partner.number)}  # a new offer replaces the last one
        key = secrets.token_hex(4)
        offers[key] = {"from": me.number, "to": partner.number, "give": give["id"], "take": take["id"],
                       "at": timefmt.iso(now)}
        _save(cfg, offers)
    note = "" if theirs.get(give["id"], 0) else " Esa no la tienes todavía."
    with _album(cfg, partner) as (owner, _):
        chat = whatsapp.WhatsApp(partner.number, cfg.whatsapp_bridge, polls=owner.core.data_dir)
        try:
            chat.send(f"🔁 {me.name} te ofrece *{give['name']}* ({_rarity(give)}) por tu *{take['name']}* repetida "
                      f"({_rarity(take)}).{note}")
            chat.poll([(ACCEPT, f"c:{key}:ok"), (DECLINE, f"c:{key}:no")], question="¿Hacemos el cambio?")
        except whatsapp.WhatsAppError as exc:
            log.warning("cambio: no pude mandarle la oferta a %s: %s", partner.name, exc)
            return amigos.Outcome(f"No pude escribirle a {partner.name} ahora. Inténtalo en un rato.")
    log.info("cambio: oferta %s de %s a %s", key, me.name, partner.name)
    return amigos.Outcome(f"📨 Le mandé tu oferta a {partner.name}: tu {give['name']} por su {take['name']}. Te aviso "
                          f"cuando conteste; la oferta dura {OFFER_HOURS // 24} días.")


def _rarity(card: dict) -> str:
    return {"com": "común", "rare": "rara", "epic": "épica", "leg": "legendaria"}[card["rarity"]]


def vote(cfg: BotConfig, number: str, friend: amigos.Friend | None, data: str, now: datetime) -> amigos.Outcome | None:
    """A vote on a trade's poll (None: a vote on any other poll). The poll lives in the voter's own folder."""
    vote = json.loads(data or "{}")
    with nullcontext(cfg) if friend is None else amigos.scope(cfg, friend) as owner:
        options = whatsapp.read_polls(owner.core.data_dir).get(str(vote.get("encuesta") or "")) or {}
    match = VOTE_RE.fullmatch(options.get(str(vote.get("opcion") or "").strip(), ""))
    if not match:
        return None
    return _respond(cfg, number, match[1], match[2] == "ok", now)


def _respond(cfg: BotConfig, number: str, key: str, accept: bool, now: datetime) -> amigos.Outcome:
    people = _people(cfg)
    known = _names()
    with file_lock(amigos.root(cfg), f"{OFFERS}.lock"):
        offers = _load(cfg, now)
        offer = offers.pop(key, None)
        if offer is None or offer["to"] != number:
            return amigos.Outcome("Esa oferta ya no está: venció, la cambiaron por otra o ya la contestaste.")
        _save(cfg, offers)
        me = next(p for p in people if p.number == number)
        sender = next((p for p in people if p.number == offer["from"]), None)
        give, take = known[offer["give"]], known[offer["take"]]
        if sender is None:
            return amigos.Outcome("Esa oferta ya no está: quien te la mandó ya no tiene su Vinci.")
        if not accept:
            _send(cfg, sender, f"{me.name} prefirió no cambiar su {take['name']} por tu {give['name']}.")
            return amigos.Outcome("Listo, no hice el cambio.")
        with ExitStack() as stack:
            their_cfg, their_conn = stack.enter_context(_album(cfg, sender, lock=True))
            my_cfg, my_conn = stack.enter_context(_album(cfg, me, lock=True))
            theirs, mine = album.collection(their_conn), album.collection(my_conn)
            if theirs.get(give["id"], 0) < 2:
                _send(cfg, sender, f"No se hizo tu cambio con {me.name}: ya no tienes {give['name']} repetida.")
                return amigos.Outcome(f"No se pudo: {sender.name} ya no tiene {give['name']} repetida.")
            if mine.get(take["id"], 0) < 2:
                _send(cfg, sender, f"No se hizo tu cambio con {me.name}: ya no tiene {take['name']} repetida.")
                return amigos.Outcome(f"No se pudo: ya no tienes {take['name']} repetida.")
            album.trade(their_conn, give["id"], take["id"], now)
            album.trade(my_conn, take["id"], give["id"], now)
            their_link = album.whatsapp_link(their_conn, their_cfg, now)
            my_link = album.whatsapp_link(my_conn, my_cfg, now)
    log.info("cambio: %s hecho entre %s y %s", key, sender.name, me.name)
    _send(cfg, sender, f"🤝 ¡Cambio hecho! {me.name} aceptó: ya tienes *{take['name']}* en tu álbum.",
          link=_button(their_link))
    return amigos.Outcome(f"🤝 ¡Cambio hecho! Ya tienes *{give['name']}* en tu álbum.", button=_button(my_link))


def _button(found: dict | None) -> dict | None:
    return {"text": found["text"], "url": found["url"]} if found else None
