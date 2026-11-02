"""The album: packs of three cards that Vinci gives for what the student does in the aula, with no model.

A pack comes for a deliverable handed in before its deadline, or for 8/10 or more in a lección or an exam (an
assignment whose Canvas group or name says so); a full score makes it a gold pack, with an epic card or better. Vinci
draws the cards when it gives the pack and keeps them in espol.db, so each friend's Vinci keeps an album of its own.
Nothing from before the album's first poll counts: a new install does not hand out the whole semester at once.

The page (docs/album/, on GitHub Pages) asks no server for the student's data: the pack and the collection ride in the
URL's fragment, as on «Tus notas» (grades_page.py). Only the catalog (docs/album/cards.json, also read here) comes from
the page's own site, so new cards need no change in code.
"""

from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
from datetime import datetime
from functools import lru_cache

from aula_core import timefmt
from aula_core.catalog import fold
from aula_core.config import REPO_ROOT
from aula_core.store import get_meta, set_meta
from espol_bot import messages
from espol_bot.config import BotConfig
from espol_bot.dashboard import MAX_URL, encode

log = logging.getLogger(__name__)

VERSION = 1
CATALOG = REPO_ROOT / "docs" / "album" / "cards.json"
RARITIES = ("com", "rare", "epic", "leg")
WEIGHTS = {"com": 70, "rare": 22, "epic": 7, "leg": 1}
PACK_SIZE = 3
GOOD_SHARE = 0.8
TEST = re.compile(r"\b(leccion|lecciones|examen|examenes|parcial|parciales)\b")
SINCE = "album_since"
MAX_PER_POLL = 4  # the rest wait for the next poll, so a busy day does not flood the chat
BUTTON = "🎴 Abrir mi sobre"
ALBUM_BUTTON = "🎴 Ver mi álbum"


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    return tuple(json.loads(CATALOG.read_text(encoding="utf-8"))["cards"])


def draw(cards: tuple[dict, ...], rng: random.Random, *, gold: bool = False) -> list[str]:
    """Three card ids, the rarest last so the page shows it at the end. A pack has a rare or better; a gold one, an
    epic or better."""
    pools = {r: [c for c in cards if c["rarity"] == r] for r in RARITIES}
    rarity = {c["id"]: c["rarity"] for c in cards}

    def pick(allowed: tuple[str, ...]) -> str:
        found = [r for r in allowed if pools[r]] or [r for r in RARITIES if pools[r]]
        chosen = rng.choices(found, [WEIGHTS[r] for r in found])[0]
        return rng.choice(pools[chosen])["id"]

    picks = [pick(RARITIES) for _ in range(PACK_SIZE - 1)]
    if gold:
        picks.append(pick(("epic", "leg")))
    elif all(rarity[p] == "com" for p in picks):
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
        have = collection(conn)
        cards = []
        for card in draw(catalog(), rng, gold=found["gold"]):
            cards.append({"id": card, "new": have.get(card, 0) == 0})
            have[card] = have.get(card, 0) + 1
            conn.execute("INSERT INTO album_cards(card, count, first_at) VALUES (?, 1, ?) "
                         "ON CONFLICT(card) DO UPDATE SET count = count + 1", (card, timefmt.iso(now)))
        conn.execute("INSERT INTO album_packs(source, reason, gold, cards, created_at) VALUES (?, ?, ?, ?, ?)",
                     (found["source"], found["reason"], int(found["gold"]), json.dumps(cards), timefmt.iso(now)))
    conn.commit()
    return len(new)


def snapshot(conn: sqlite3.Connection, now: datetime, pack: sqlite3.Row | None = None) -> dict:
    data = {"v": VERSION, "at": timefmt.iso(now), "have": collection(conn)}
    if pack is not None:
        data["pack"] = {"id": pack["id"], "reason": messages.plain(pack["reason"]), "gold": bool(pack["gold"]),
                        "cards": json.loads(pack["cards"])}
    return data


def page_url(cfg: BotConfig, data: dict) -> str:
    url = f"{cfg.album_page}#d={encode(data)}"
    if len(url) > MAX_URL:  # a catalog of a few hundred cards still fits; this only guards the phones' webviews
        log.warning("álbum: el enlace mide %d caracteres", len(url))
    return url


def message(pack: sqlite3.Row) -> str:
    if pack["gold"]:
        return f"🌟 {pack['reason']}: te ganaste un <b>sobre dorado</b>. Trae una carta épica o mejor."
    return f"🎴 {pack['reason']}: te ganaste un sobre con 3 cartas para tu álbum."


def deliver(conn: sqlite3.Connection, cfg: BotConfig, sender, now: datetime) -> list[str]:
    """Gives the packs earned since the last poll and sends the ones not sent yet, each with its page; the texts
    sent. A pack stays unsent until the chat takes it, so a failed send is retried on the next poll."""
    if not cfg.album_page:
        return []
    give(conn, now)
    sent = []
    pending = conn.execute("SELECT * FROM album_packs WHERE sent_at IS NULL ORDER BY id LIMIT ?",
                           (MAX_PER_POLL,)).fetchall()
    for pack in pending:
        text = message(pack)
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
    have = collection(conn)
    return {"text": ALBUM_BUTTON, "url": page_url(cfg, snapshot(conn, now)), "cards": len(have),
            "total": len(catalog())}
