"""The album: packs of three cards that Vinci gives for what the student does in the aula, with no model.

A pack comes for a deliverable handed in before its deadline, or for 8/10 or more in a lección or an exam (an
assignment whose Canvas group or name says so); a full score makes it a gold pack, with an epic card or better. One
more comes with each 07:00 summary, without the rare card a pack for the aula guarantees. Vinci
draws the cards when it gives the pack and keeps them in espol.db, so each friend's Vinci keeps an album of its own.
Nothing from before the album's first poll counts: a new install does not hand out the whole semester at once.

The page (docs/album/, on GitHub Pages) asks no server for the student's data: the pack and the collection ride in the
URL's fragment, as on «Tus notas» (grades_page.py). Only the catalog (docs/album/cards.json, also read here) comes from
the page's own site, so new cards need no change in code. Art with people's faces is stored there encrypted
(scripts/album_card.py); its key, ALBUM_ART_KEY in secrets.env, rides in the fragment too, so only a link from Vinci
shows it.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from aula_core import timefmt
from aula_core.catalog import fold
from aula_core.config import REPO_ROOT, ConfigError, load_secret_values
from aula_core.store import get_meta, set_meta
from espol_bot import messages
from espol_bot.config import CAPTAIN_SECRETS, BotConfig
from espol_bot.dashboard import MAX_URL, encode

log = logging.getLogger(__name__)

VERSION = 1
CATALOG = REPO_ROOT / "docs" / "album" / "cards.json"
RARITIES = ("com", "rare", "epic", "leg")
WEIGHTS = {"com": 55, "rare": 25, "epic": 10, "leg": 10}  # with 6 legendaries, a given one: about 1 in 4 people by their 5th pack
PACK_SIZE = 3
GOOD_SHARE = 0.8
TEST = re.compile(r"\b(leccion|lecciones|examen|examenes|parcial|parciales)\b")
SINCE = "album_since"
DAILY = "diario:"
GIFT = "regalo:"
WELCOME = f"{GIFT}bienvenida"
PENDING_HINT = ("\n\nGanas más sobres cuando entregas a tiempo y cuando sacas buenas notas. Para eso, conecta tu aula "
                "virtual desde el enlace que te mandé: yo solo la leo, no cambio nada. Si el enlace ya no abre, "
                "escríbeme /token.")
MAX_PER_POLL = 4  # the rest wait for the next poll, so a busy day does not flood the chat
BUTTON = "🎴 Abrir mi sobre"
ALBUM_BUTTON = "🎴 Ver mi álbum"


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    return tuple(json.loads(CATALOG.read_text(encoding="utf-8"))["cards"])


def draw(cards: tuple[dict, ...], rng: random.Random, *, gold: bool = False, floor: bool = True) -> list[str]:
    """Three card ids, the rarest last so the page shows it at the end. A pack has a rare or better (with `floor`); a
    gold one, an epic or better."""
    pools = {r: [c for c in cards if c["rarity"] == r] for r in RARITIES}
    rarity = {c["id"]: c["rarity"] for c in cards}

    def pick(allowed: tuple[str, ...]) -> str:
        found = [r for r in allowed if pools[r]] or [r for r in RARITIES if pools[r]]
        chosen = rng.choices(found, [WEIGHTS[r] for r in found])[0]
        return rng.choice(pools[chosen])["id"]

    picks = [pick(RARITIES) for _ in range(PACK_SIZE - 1)]
    if gold:
        picks.append(pick(("epic", "leg")))
    elif floor and all(rarity[p] == "com" for p in picks):
        picks.append(pick(("rare", "epic", "leg")))
    else:
        picks.append(pick(RARITIES))
    return sorted(picks, key=lambda p: RARITIES.index(rarity[p]))


def is_test(name: str, group: str | None) -> bool:
    """A lección or an exam, by its Canvas group («Lecciones», «Exámenes») or its own name."""
    return bool(TEST.search(fold(group or "")) or TEST.search(fold(name)))


def _score(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def earned(conn: sqlite3.Connection, since: str) -> list[dict]:
    """What earned a pack since the album started: {source, reason, gold}, oldest first."""
    found = []
    for a in conn.execute(
            "SELECT id, name, due_at, submitted_at FROM assignments WHERE active = 1 AND excused = 0 "
            "AND submitted_at IS NOT NULL AND submitted_at >= ? AND due_at IS NOT NULL AND submitted_at <= due_at "
            "ORDER BY submitted_at", (since,)):
        found.append({"source": f"entrega:{a['id']}", "at": a["submitted_at"], "gold": False,
                      "reason": f"Entregaste <b>{messages.e(a['name'])}</b> a tiempo"})
    graded = conn.execute(
        "SELECT a.id, a.name, a.score, a.points_possible, g.name AS grupo, MIN(e.created_at) AS at FROM events e "
        "JOIN assignments a ON a.id = e.ref_id LEFT JOIN assignment_groups g ON g.id = a.group_id "
        "WHERE e.kind IN ('grade_posted', 'grade_changed') AND e.created_at >= ? AND a.excused = 0 "
        "AND a.score IS NOT NULL AND a.points_possible > 0 GROUP BY a.id ORDER BY at", (since,))
    for a in graded:
        if a["score"] / a["points_possible"] < GOOD_SHARE or not is_test(a["name"], a["grupo"]):
            continue
        found.append({"source": f"nota:{a['id']}", "at": a["at"], "gold": a["score"] >= a["points_possible"],
                      "reason": f"Sacaste {_score(a['score'])}/{_score(a['points_possible'])} en "
                                f"<b>{messages.e(a['name'])}</b>"})
    return sorted(found, key=lambda f: f["at"])


def collection(conn: sqlite3.Connection) -> dict[str, int]:
    return {r["card"]: r["count"] for r in conn.execute("SELECT card, count FROM album_cards")}


def _store(conn: sqlite3.Connection, now: datetime, source: str, reason: str, picks: list[str], gold: bool) -> None:
    have = collection(conn)
    cards = []
    for card in picks:
        cards.append({"id": card, "new": have.get(card, 0) == 0})
        have[card] = have.get(card, 0) + 1
        conn.execute("INSERT INTO album_cards(card, count, first_at) VALUES (?, 1, ?) "
                     "ON CONFLICT(card) DO UPDATE SET count = count + 1", (card, timefmt.iso(now)))
    conn.execute("INSERT INTO album_packs(source, reason, gold, cards, created_at) VALUES (?, ?, ?, ?, ?)",
                 (source, reason, int(gold), json.dumps(cards), timefmt.iso(now)))


def give(conn: sqlite3.Connection, now: datetime, rng: random.Random | None = None) -> int:
    """Draws a pack for each new reason; how many it gave. The first call only starts the album."""
    since = get_meta(conn, SINCE)
    if since is None:
        set_meta(conn, SINCE, timefmt.iso(now))
        conn.commit()
        return 0
    known = {r["source"] for r in conn.execute("SELECT source FROM album_packs")}
    new = [f for f in earned(conn, since) if f["source"] not in known]
    rng = rng or random.Random()
    for found in new:
        _store(conn, now, found["source"], found["reason"], draw(catalog(), rng, gold=found["gold"]), found["gold"])
    conn.commit()
    return len(new)


def give_daily(conn: sqlite3.Connection, now: datetime, today: str, rng: random.Random | None = None) -> bool:
    """The pack of the 07:00 summary, once a day and only once the album started."""
    source = f"{DAILY}{today}"
    if get_meta(conn, SINCE) is None or conn.execute(
            "SELECT 1 FROM album_packs WHERE source = ?", (source,)).fetchone():
        return False
    picks = draw(catalog(), rng or random.Random(), floor=False)
    _store(conn, now, source, "Te llega uno cada mañana con tu resumen", picks, False)
    conn.commit()
    return True


def give_gift(conn: sqlite3.Connection, now: datetime, reason: str, rng: random.Random | None = None, *,
              start: bool = False) -> bool:
    """A pack the captain gives everyone (`espol-bot album-regalo`), once the album started; the next poll sends it.
    `start`: a friend still without a token, whose album starts with it (no poll runs for them yet)."""
    if get_meta(conn, SINCE) is None:
        if not start:
            return False
        set_meta(conn, SINCE, timefmt.iso(now))
    _store(conn, now, f"{GIFT}{timefmt.iso(now)}", reason, draw(catalog(), rng or random.Random()), False)
    conn.commit()
    return True


def give_welcome(conn: sqlite3.Connection, now: datetime, rng: random.Random | None = None) -> bool:
    """The pack someone gets with the token link, once, before Vinci reads their aula; their album starts with it."""
    if conn.execute("SELECT 1 FROM album_packs WHERE source = ?", (WELCOME,)).fetchone():
        return False
    if get_meta(conn, SINCE) is None:
        set_meta(conn, SINCE, timefmt.iso(now))
    _store(conn, now, WELCOME, "Para que empieces tu colección", draw(catalog(), rng or random.Random()), False)
    conn.commit()
    return True


def trade(conn: sqlite3.Connection, given: str, got: str, now: datetime) -> None:
    """One copy of `given` (a repeat) leaves this album and `got` comes in (trades.py)."""
    left = conn.execute("UPDATE album_cards SET count = count - 1 WHERE card = ? AND count >= 2", (given,)).rowcount
    if not left:
        raise ValueError(f"{given} no está repetida")
    conn.execute("INSERT INTO album_cards(card, count, first_at) VALUES (?, 1, ?) "
                 "ON CONFLICT(card) DO UPDATE SET count = count + 1", (got, timefmt.iso(now)))
    conn.commit()


def art_key() -> str:
    """The key of the encrypted art (base64url), or "" without one: the page then shows initials. A friend's Vinci
    reads it from the captain's secrets.env, the only one that holds it."""
    captain = os.environ.get(CAPTAIN_SECRETS)
    try:
        return load_secret_values(Path(captain) if captain else None).get("ALBUM_ART_KEY", "")
    except ConfigError:
        return ""


def snapshot(conn: sqlite3.Connection, now: datetime, pack: sqlite3.Row | None = None) -> dict:
    data = {"v": VERSION, "at": timefmt.iso(now), "have": collection(conn)}
    if key := art_key():
        data["k"] = key
    if pack is not None:
        data["pack"] = {"id": pack["id"], "reason": messages.plain(pack["reason"]), "gold": bool(pack["gold"]),
                        "cards": json.loads(pack["cards"])}
        if pack["source"].startswith(DAILY):
            data["pack"]["daily"] = True
        elif pack["source"].startswith(GIFT):
            data["pack"]["gift"] = True
    return data


def page_url(cfg: BotConfig, data: dict) -> str:
    from espol_bot import ranking, trades  # both import this module
    try:
        if found := trades.market(cfg):
            data = {**data, "trade": found}
    except Exception:  # an extra: the album opens without its «Cambios» tab
        log.exception("álbum: no pude leer las repetidas de los demás")
    try:
        if board := ranking.page(cfg):
            data = {**data, "rank": board}
    except Exception:  # an extra too: the album opens without its «Ranking» view
        log.exception("álbum: no pude armar el ranking")
    url = f"{cfg.album_page}#d={encode(data)}"
    if len(url) > MAX_URL:  # a catalog of a few hundred cards still fits; this only guards the phones' webviews
        log.warning("álbum: el enlace mide %d caracteres", len(url))
    return url


def message(pack: sqlite3.Row) -> str:
    if pack["source"].startswith(DAILY):
        return "🎴 Tu sobre del día: 3 cartas para tu álbum. Mañana con el resumen te llega otro."
    if pack["source"].startswith(GIFT):
        return f"🎁 {pack['reason']}: te llegó un <b>sobre de regalo</b> con 3 cartas para tu álbum."
    if pack["gold"]:
        return f"🌟 {pack['reason']}: te ganaste un <b>sobre dorado</b>. Trae una carta épica o mejor."
    return f"🎴 {pack['reason']}: te ganaste un sobre con 3 cartas para tu álbum."


def deliver(conn: sqlite3.Connection, cfg: BotConfig, sender, now: datetime, hint: str = "") -> list[str]:
    """Gives the packs earned since the last poll and sends the ones not sent yet, each with its page; the texts
    sent. A pack stays unsent until the chat takes it, so a failed send is retried on the next poll. `hint` goes
    after each message."""
    if not cfg.album_page:
        return []
    give(conn, now)
    sent = []
    pending = conn.execute("SELECT * FROM album_packs WHERE sent_at IS NULL ORDER BY id LIMIT ?",
                           (MAX_PER_POLL,)).fetchall()
    for pack in pending:
        text = message(pack) + hint
        url = page_url(cfg, snapshot(conn, now, pack))
        if cfg.telegram:
            sender.send(text, reply_markup={"inline_keyboard": [[{"text": BUTTON, "url": url}]]})
        else:
            sender.send(text, link={"text": BUTTON, "url": url})
        conn.execute("UPDATE album_packs SET sent_at = ? WHERE id = ?", (timefmt.iso(now), pack["id"]))
        conn.commit()
        sent.append(text)
    return sent


def whatsapp_link(conn: sqlite3.Connection, cfg: BotConfig, now: datetime) -> dict | None:
    """The album with no pack to open, as a WhatsApp URL button ({"text", "url", "cards", "total"}); None with no
    page."""
    if not cfg.album_page:
        return None
    ids = {c["id"] for c in catalog()}  # a card taken out of the catalog no longer counts
    have = collection(conn)
    return {"text": ALBUM_BUTTON, "url": page_url(cfg, snapshot(conn, now)), "cards": len(ids & have.keys()),
            "total": len(ids)}
