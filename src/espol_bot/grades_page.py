"""«Tus notas»: the grade calculator of every subject on one page, sent as a WhatsApp URL button by Vinci's
`show_page`, with no model in the figures.

Like the dashboard (dashboard.py), the page (docs/notas/ on GitHub Pages) asks no server for anything: the snapshot
rides in the URL's fragment (`#d=<base64url of raw DEFLATE JSON>`), which a browser never sends. The figures are the
ones grades.compute gives the chat's «¿cómo voy?»; the page only lays them out.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from aula_core import timefmt
from espol_bot import grades, materias
from espol_bot.config import BotConfig
from espol_bot.dashboard import MAX_URL, encode

VERSION = 1
BUTTON = "📊 Ver mis notas"
STATUS = {"graded": "g", "pending": "p", "excused": "e"}


def _subject(subject: materias.Subject, result: dict, saved_at: str | None) -> dict:
    periods = []
    for p in result["periods"]:
        comps = [{"name": c["name"], "weight": c["weight"], "avg": c["average"], "share": c["graded_share"],
                  **({"missing": c["not_in_canvas_yet"]} if c.get("not_in_canvas_yet") else {}),
                  # [name, score, out of, status, told by the student]: graded and excused only, the rest is a count
                  "items": [[i["name"], i["score"], i["out_of"], STATUS[i["status"]], 1 if i.get("manual") else 0]
                            for i in c["items"] if i["status"] != "pending"],
                  "pending": sum(1 for i in c["items"] if i["status"] == "pending")}
                 for c in p["components"]]
        periods.append({"name": p["name"], "weight": p.get("weight"), "so_far": p["grade_so_far"],
                        **({"imp": p["replaces"] or ["tu parcial más bajo"]} if p.get("improvement") else {}),
                        **({"exception": p["exception"]} if p.get("exception") else {}), "comps": comps})
    improvement = result["improvement"]
    return {"name": materias.short_name(subject.name), "verdict": result["verdict"], "target": result["target"],
            "passing": result["passing_grade"], "secured": result["points_secured"],
            "graded": result["graded_share"], "avg": result["average_so_far"],
            "needed": result["needed_on_remaining"], "max": result["max_possible"],
            "remaining": result["remaining_share"],
            **({"improvement": improvement} if improvement else {}),
            **({"replaced": result["replaced"]} if result["replaced"] else {}),
            "loose": len(result["unassigned_grades"]), "questions": result["open_questions"],
            "periods": periods, "saved": saved_at}


def snapshot(conn: sqlite3.Connection, cfg: BotConfig, now: datetime) -> dict:
    """Every subject that is not archived: its calculator result, or its name among those with no scheme yet."""
    subjects, without = [], []
    for subject in materias.load(cfg.core):
        if subject.state == "archivada":
            continue
        data = grades.status(conn, subject, cfg.core.tz)
        if data is None:
            without.append(materias.short_name(subject.name))
        else:
            subjects.append(_subject(subject, data["result"], data["saved_at"]))
    return {"v": VERSION, "at": timefmt.iso(now), "subjects": subjects, "without": without}


def page_url(cfg: BotConfig, data: dict) -> str:
    """The page with the snapshot in its fragment; to fit, the longest component loses its last grades first (the
    figures above them stay whole)."""
    data = {**data, "subjects": [{**s, "periods": [{**p, "comps": [{**c, "items": list(c["items"])} for c in p["comps"]]}
                                                   for p in s["periods"]]} for s in data["subjects"]]}
    while True:
        url = f"{cfg.grades_page}#d={encode(data)}"
        comps = [c for s in data["subjects"] for p in s["periods"] for c in p["comps"] if c["items"]]
        if len(url) <= MAX_URL or not comps:
            return url
        longest = max(comps, key=lambda c: len(c["items"]))
        longest["items"].pop()
        longest["cut"] = longest.get("cut", 0) + 1


def whatsapp_link(conn: sqlite3.Connection, cfg: BotConfig, now: datetime) -> dict | None:
    """The page as a WhatsApp URL button ({"text", "url", "subjects", "without"}); None with no page."""
    if not cfg.grades_page:
        return None
    data = snapshot(conn, cfg, now)
    return {"text": BUTTON, "url": page_url(cfg, data), "subjects": len(data["subjects"]), "without": data["without"]}
