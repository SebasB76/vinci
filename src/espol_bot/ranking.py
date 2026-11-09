"""The album ranking on WhatsApp among the people with a Vinci who joined it, with no model.

«/ranking» shows who has the most cards (distinct cards of the catalog; legendaries, then epics break a tie).
Nobody is in it until they write «/ranking entrar»; «/ranking salir» takes them out. The list of who joined lives in
the captain's amigos/ranking.json; each album is read from that person's espol.db, as trades.py does.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from aula_core.catalog import fold
from aula_core.config import load_secret_values
from espol_bot import album, amigos, trades, whatsapp
from espol_bot.config import CAPTAIN_SECRETS, BotConfig, whatsapp_settings

JOINED = "ranking.json"
SHOWN = 10
MEDALS = ("🥇", "🥈", "🥉")
RANKING_BUTTON = "🏆 Ver el ranking"


def _home(cfg: BotConfig) -> Path:
    """The captain's data folder, where amigos/ lives, from his cfg or a friend's (amigos/<slug>/)."""
    data_dir = cfg.core.data_dir
    return data_dir.parent.parent if data_dir.parent.name == "amigos" else data_dir


def _joined(home: Path) -> list[str]:
    try:
        return list(json.loads((home / "amigos" / JOINED).read_text(encoding="utf-8")).get("numeros") or [])
    except (OSError, ValueError):
        return []


def _save(home: Path, numbers: list[str]) -> None:
    path = home / "amigos" / JOINED
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"numeros": numbers}), encoding="utf-8")
    os.replace(tmp, path)


def _score(db: Path) -> dict | None:
    """{"n": distinct cards, "leg": legendaries, "epic": epics}; None for an album not started yet."""
    if not db.exists():
        return None
    rarity = {c["id"]: c["rarity"] for c in album.catalog()}
    try:
        conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            have = [c for c in album.collection(conn) if c in rarity]
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return {"n": len(have), "leg": sum(rarity[c] == "leg" for c in have), "epic": sum(rarity[c] == "epic" for c in have)}


def table(home: Path, captain: str) -> list[dict]:
    """Who joined, best first: [{"name", "number", "n", "leg", "epic"}]."""
    joined = set(_joined(home))
    rows = []
    for p in trades._roster(home, captain):
        if p.number in joined and (score := _score(p.db)) is not None:
            rows.append({"name": p.name, "number": p.number, **score})
    return sorted(rows, key=lambda r: (-r["n"], -r["leg"], -r["epic"], fold(r["name"])))


def page(cfg: BotConfig) -> dict:
    """The album page's «Ranking» view: {"wa", "in", "people": [{"name", "n", "leg", "me"?}]}; {} off WhatsApp or with
    no friends."""
    home = _home(cfg)
    if not (home / "amigos" / "amigos.json").exists():
        return {}
    captain = os.environ.get(CAPTAIN_SECRETS)  # a friend's Vinci reads the captain's number from his secrets.env
    wa = whatsapp_settings(load_secret_values(Path(captain) if captain else None))
    if wa is None:
        return {}
    me = next((p.number for p in trades._roster(home, wa.captain) if p.db == cfg.core.db_path), None)
    people = [{"name": r["name"], "n": r["n"], "leg": r["leg"], **({"me": 1} if r["number"] == me else {})}
              for r in table(home, wa.captain)]
    return {"wa": whatsapp.own_number(), "in": me in _joined(home), "people": people}


def command(cfg: BotConfig, number: str, text: str, now: datetime) -> amigos.Outcome:
    """«/ranking», «/ranking entrar» or «/ranking salir»."""
    home, word = amigos.root(cfg).parent, fold(text.strip()).split(" ")[0]
    captain = amigos.captain_number(cfg)
    joined = _joined(home)
    note = ""
    if word in ("entrar", "unirme", "si"):
        if number not in joined:
            _save(home, joined := [*joined, number])
        note = "✅ Listo: sales en el ranking del álbum. Para salir, escribe /ranking salir.\n\n"
    elif word in ("salir", "no"):
        if number in joined:
            _save(home, joined := [n for n in joined if n != number])
        return amigos.Outcome("Listo: ya no sales en el ranking. Para volver, escribe /ranking entrar.")
    rows = table(home, captain)
    total = len(album.catalog())
    lines = [f"{note}🏆 *Ranking del álbum*", ""]
    for i, r in enumerate(rows[:SHOWN]):
        place = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
        legend = f" · {r['leg']} ★" if r["leg"] else ""
        you = " (tú)" if r["number"] == number else ""
        lines.append(f"{place} {r['name']}{you}: {r['n']} de {total}{legend}")
    if not rows:
        lines.append("Todavía nadie entró al ranking.")
    mine = next((i for i, r in enumerate(rows) if r["number"] == number), None)
    if mine is not None and mine >= SHOWN:
        lines.append(f"…\n{mine + 1}. Tú: {rows[mine]['n']} de {total}")
    if number not in joined:
        lines += ["", "No sales en el ranking: entra solo quien quiere. Para entrar, escribe /ranking entrar."]
    person = next(p for p in trades._people(cfg) if p.number == number)
    with trades._album(cfg, person) as (owner, conn):
        link = album.whatsapp_link(conn, owner, now)
    button = {"text": RANKING_BUTTON, "url": f"{link['url']}&t=ranking"} if link else None
    return amigos.Outcome("\n".join(lines), button=button)
