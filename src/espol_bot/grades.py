"""The grade calculator: a subject's evaluation scheme applied to the captain's grades, with no model.

A scheme is what the syllabus, the course policies, an announcement or the captain say about how a
subject is graded this semester. It is a list of periods («Primer parcial», «Segundo parcial», or a
single «Curso» when the syllabus weighs everything at once), each weighing the final grade and made of
weighted components («Examen 35 %», «Lecciones 30 %»). A component takes its grades from the Canvas
assignments whose name matches it (within the period's dates, when it has them) plus the grades the
captain told a bot about (on paper, outside Canvas). An improvement period («Mejoramiento») weighs
nothing by itself: when graded, it replaces the lowest of the periods it replaces, if it is higher.

A period can say why it differs from the syllabus (`exception`: this semester the first partial has no
exam because of El Niño, and each subject handles that its own way), and what the bot could not
establish goes in `open_questions`, shown with every result until the captain settles it.

All figures are points of the final grade out of 100. A component's average is points-based (the sum
of its scores over the sum of what they were out of), like Canvas within an assignment group; the part
of a component already graded is its graded points over all its points: the ones graded, the ones of
its assignments still ungraded and, when the scheme says how many it will have (`expected_count`: «4
lecciones»), the ones not created in Canvas yet, at the mean points of the rest.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from aula_core import timefmt
from aula_core.catalog import fold
from espol_bot import agenda, materias, store

DEFAULT_PASSING = 60.0
TOLERANCE = 0.01
MAX_PERIODS = 8
MAX_COMPONENTS = 12


class SchemeError(ValueError):
    """A scheme that cannot be applied: the errors are in Spanish, for the model to fix and propose again."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


# -- the scheme ------------------------------------------------------------------------------------


def _number(value, what: str, errors: list[str], lo: float = 0.0, hi: float = 100.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{what} debe ser un número.")
        return None
    if not lo <= number <= hi:
        errors.append(f"{what} debe estar entre {lo:g} y {hi:g}.")
        return None
    return number


def _texts(value, what: str, errors: list[str]) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errors.append(f"{what} debe ser una lista de textos.")
        return []
    return [" ".join(v.split()) for v in value if v.strip()]


def _day(value, what: str, errors: list[str]) -> str | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        errors.append(f"{what} debe ser una fecha AAAA-MM-DD.")
        return None


def validate(raw: dict) -> dict:
    """The scheme in its stored form, or SchemeError listing everything wrong with it."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise SchemeError(["El esquema debe ser un objeto con «periods»."])
    passing = _number(raw.get("passing_grade", DEFAULT_PASSING), "«passing_grade»", errors, 1, 100)
    periods_raw = raw.get("periods")
    if not isinstance(periods_raw, list) or not periods_raw:
        errors.append("«periods» debe traer al menos un período (por ejemplo «Primer parcial»).")
        periods_raw = []
    if len(periods_raw) > MAX_PERIODS:
        errors.append(f"Como mucho {MAX_PERIODS} períodos.")
    periods = []
    for i, p in enumerate(periods_raw[:MAX_PERIODS], 1):
        if not isinstance(p, dict):
            errors.append(f"El período {i} debe ser un objeto.")
            continue
        name = " ".join(str(p.get("name") or "").split())
        label = f"«{name}»" if name else f"El período {i}"
        if not name:
            errors.append(f"El período {i} no tiene «name».")
        improvement = bool(p.get("improvement"))
        weight = None if improvement else _number(p.get("weight"), f"El peso de {label}", errors)
        start, end = _day(p.get("start"), f"«start» de {label}", errors), _day(p.get("end"), f"«end» de {label}", errors)
        if start and end and start > end:
            errors.append(f"{label} empieza después de terminar.")
        components = []
        comps_raw = p.get("components")
        if not isinstance(comps_raw, list) or not comps_raw:
            errors.append(f"{label} no tiene «components».")
            comps_raw = []
        for j, c in enumerate(comps_raw[:MAX_COMPONENTS], 1):
            if not isinstance(c, dict):
                errors.append(f"El componente {j} de {label} debe ser un objeto.")
                continue
            cname = " ".join(str(c.get("name") or "").split())
            if not cname:
                errors.append(f"El componente {j} de {label} no tiene «name».")
            cweight = _number(c.get("weight"), f"El peso de «{cname or j}» en {label}", errors)
            ids = c.get("assignment_ids") or []
            if not isinstance(ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids):
                errors.append(f"«assignment_ids» de «{cname}» debe ser una lista de IDs de tareas.")
                ids = []
            expected = c.get("expected_count")
            if expected not in (None, "") and (not isinstance(expected, int) or isinstance(expected, bool)
                                               or not 1 <= expected <= 100):
                errors.append(f"«expected_count» de «{cname}» debe ser cuántas notas tendrá (1 a 100).")
                expected = None
            components.append({"name": cname, "weight": cweight, "match": _texts(c.get("match"), f"«match» de «{cname}»",
                                                                                   errors),
                               "assignment_ids": ids, "expected_count": expected or None})
        if len(comps_raw) > MAX_COMPONENTS:
            errors.append(f"{label}: como mucho {MAX_COMPONENTS} componentes.")
        names = [c["name"] for c in components]
        if len(set(map(fold, names))) != len(names):
            errors.append(f"{label} repite el nombre de un componente.")
        total = sum(c["weight"] or 0 for c in components)
        if components and all(c["weight"] is not None for c in components) and abs(total - 100) > TOLERANCE:
            errors.append(f"Los componentes de {label} suman {total:g} %, no 100 %.")
        periods.append({"name": name, "weight": weight, "improvement": improvement,
                        "replaces": _texts(p.get("replaces"), f"«replaces» de {label}", errors) if improvement else [],
                        "start": start, "end": end, "exception": " ".join(str(p.get("exception") or "").split()) or None,
                        "components": components})
    regular = [p for p in periods if not p["improvement"]]
    if periods and not regular:
        errors.append("Hace falta al menos un período que no sea de mejoramiento.")
    names = [fold(p["name"]) for p in periods]
    if len(set(names)) != len(names):
        errors.append("Dos períodos tienen el mismo nombre.")
    total = sum(p["weight"] or 0 for p in regular)
    if regular and all(p["weight"] is not None for p in regular) and abs(total - 100) > TOLERANCE:
        errors.append(f"Los pesos de los períodos suman {total:g} %, no 100 % (el mejoramiento no lleva peso).")
    for p in periods:
        unknown = [r for r in p["replaces"] if fold(r) not in {fold(q["name"]) for q in regular}]
        if unknown:
            errors.append(f"«{p['name']}» reemplaza períodos que no existen: {', '.join(unknown)}.")
    sources = _texts(raw.get("sources"), "«sources»", errors)
    if not sources:
        errors.append("«sources» debe decir de dónde sale cada peso (archivo y página, un anuncio, o «me lo dijo "
                      "el estudiante»).")
    open_questions = _texts(raw.get("open_questions"), "«open_questions»", errors)
    if errors:
        raise SchemeError(errors)
    return {"passing_grade": passing, "periods": periods, "sources": sources, "open_questions": open_questions}


# -- matching grades to components ------------------------------------------------------------------


@dataclass
class _Item:
    label: str
    points: float | None
    score: float | None
    assignment_id: int | None = None
    due: str | None = None
    manual: bool = False
    excused: bool = False

    @property
    def graded(self) -> bool:
        return self.score is not None and bool(self.points) and not self.excused

    @property
    def pending(self) -> bool:
        return self.score is None and bool(self.points) and not self.excused


def _local_day(value: str | None, tz: ZoneInfo) -> str | None:
    moment = timefmt.parse(value)
    return moment.astimezone(tz).date().isoformat() if moment else None


def _in_period(period: dict, day: str | None) -> bool:
    if not (period["start"] or period["end"]):
        return True
    if day is None:
        return False
    return (period["start"] or "") <= day <= (period["end"] or "9999")


def _matches(component: dict, name: str) -> bool:
    folded = fold(name)
    return any(fold(m) in folded for m in component["match"])


def assign(scheme: dict, assignments: list[dict], tz: ZoneInfo) -> tuple[dict, list[dict]]:
    """{(period, component): [assignments]} and the graded assignments no component takes. Each
    assignment feeds one component: its ID named in a component first, then the first name match."""
    taken: dict[int, tuple[str, str]] = {}
    slots: dict[tuple[str, str], list[dict]] = {(p["name"], c["name"]): [] for p in scheme["periods"]
                                                for c in p["components"]}
    by_id = {a["id"]: a for a in assignments}
    for p in scheme["periods"]:
        for c in p["components"]:
            for aid in c["assignment_ids"]:
                if aid in by_id and aid not in taken:
                    taken[aid] = (p["name"], c["name"])
    for a in assignments:
        if a["id"] in taken:
            continue
        day = _local_day(a["due_at"], tz)
        for p in scheme["periods"]:
            c = next((c for c in p["components"] if _in_period(p, day) and _matches(c, a["name"])), None)
            if c is not None:
                taken[a["id"]] = (p["name"], c["name"])
                break
    for aid, slot in taken.items():
        slots[slot].append(by_id[aid])
    loose = [a for a in assignments if a["id"] not in taken and a["score"] is not None and a["points"]]
    return slots, loose


# -- the arithmetic ---------------------------------------------------------------------------------


def _round(value: float | None) -> float | None:
    """One decimal, halves up as a person rounds (11.25 → 11.3; Python's round() would give 11.2)."""
    if value is None:
        return None
    return float(Decimal(repr(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) + 0.0


def _points(component: dict, items: list[_Item]) -> tuple[float, float, int]:
    """The component's graded points, its points still ungraded and how many grades it lacks in Canvas."""
    graded = [i for i in items if i.graded]
    pending = [i for i in items if i.pending]
    graded_points = sum(i.points for i in graded)
    pending_points = sum(i.points for i in pending)
    missing = (component.get("expected_count") or 0) - len(graded) - len(pending)
    if missing > 0:  # not created in Canvas yet: as many points as the mean known one (any unit when none is)
        pending_points += missing * ((graded_points + pending_points) / (len(graded) + len(pending)) if graded or pending else 1)
    return graded_points, pending_points, missing


def _component(component: dict, items: list[_Item], what_if: float | None) -> dict:
    graded = [i for i in items if i.graded]
    graded_points, pending_points, missing = _points(component, items)
    known = graded_points + pending_points
    share = graded_points / known if known else 0.0          # part of the component already graded
    average = sum(i.score for i in graded) / graded_points if graded_points else None
    result = {"name": component["name"], "weight": component["weight"], "graded_share": share, "average": average,
              **({"not_in_canvas_yet": missing} if missing > 0 else {}),
              "items": [{"name": i.label, "score": i.score, "out_of": i.points,
                         "status": "excused" if i.excused else "graded" if i.graded else "pending",
                         **({"manual": True} if i.manual else {}), **({"due": i.due} if i.due else {})}
                        for i in items if i.points or i.score is not None]}
    if what_if is not None:
        result["what_if"] = what_if
    return result


def _items(period: dict, component: dict, slots: dict, manual: list[dict]) -> list[_Item]:
    items = [_Item(a["name"], a["points"], a["score"], a["id"], a["due_at"], excused=bool(a["excused"]))
             for a in slots[(period["name"], component["name"])]]
    return items + [_Item(m["label"], m["out_of"], m["score"], manual=True) for m in manual
                    if (fold(m["period"]), fold(m["component"])) == (fold(period["name"]), fold(component["name"]))]


def compute(scheme: dict, assignments: list[dict], manual: list[dict], tz: ZoneInfo, *,
            what_if: dict[tuple[str, str], float] | None = None, target: float | None = None) -> dict:
    """How the captain is doing under `scheme`: every figure is deterministic arithmetic.

    `assignments`: {id, name, due_at, points, score, excused} of the subject's courses. `manual`: grades the
    captain gave ({period, component, label, score, out_of}). `what_if`: {(period, component): percent} to
    assume on what is still ungraded there. `target`: the final grade to aim at (default: passing)."""
    what_if = {(fold(p), fold(c)): v for (p, c), v in (what_if or {}).items()}
    slots, loose = assign(scheme, assignments, tz)
    passing = scheme["passing_grade"]
    goal = passing if target is None else target
    periods = []
    stray_manual = []
    known = {(fold(p["name"]), fold(c["name"])) for p in scheme["periods"] for c in p["components"]}
    for m in manual:
        if (fold(m["period"]), fold(m["component"])) not in known:
            stray_manual.append(m)
    for p in scheme["periods"]:
        comps = [_component(c, _items(p, c, slots, manual), what_if.get((fold(p["name"]), fold(c["name"]))))
                 for c in p["components"]]
        done = sum(c["weight"] * c["graded_share"] for c in comps)                    # of the period's 100
        earned = sum(c["weight"] * c["graded_share"] * c["average"] for c in comps if c["average"] is not None)
        assumed = sum(c["weight"] * (1 - c["graded_share"]) * c["what_if"] / 100 for c in comps if "what_if" in c)
        assumed_share = sum(c["weight"] * (1 - c["graded_share"]) for c in comps if "what_if" in c)
        periods.append({"name": p["name"], "weight": p["weight"], "improvement": p["improvement"],
                        "replaces": p["replaces"], "exception": p["exception"], "components": comps,
                        "graded": done, "earned": earned, "assumed": assumed, "assumed_share": assumed_share,
                        "grade_so_far": earned / done * 100 if done > TOLERANCE else None,
                        "complete": done >= 100 - TOLERANCE})
    regular = [p for p in periods if not p["improvement"]]
    graded = sum(p["weight"] * p["graded"] / 100 for p in regular)                   # of the final 100
    secured = sum(p["weight"] * p["earned"] / 100 for p in regular)
    assumed = sum(p["weight"] * p["assumed"] / 100 for p in regular)
    assumed_share = sum(p["weight"] * p["assumed_share"] / 100 for p in regular)
    remaining = max(0.0, 100 - graded - assumed_share)
    replaced = None
    for imp in (p for p in periods if p["improvement"] and p["complete"]):
        names = {fold(n) for n in imp["replaces"]} or {fold(p["name"]) for p in regular}
        candidates = [p for p in regular if fold(p["name"]) in names and p["complete"]]
        lowest = min(candidates, key=lambda p: p["earned"], default=None)
        if lowest is not None and imp["earned"] > lowest["earned"]:
            secured += lowest["weight"] * (imp["earned"] - lowest["earned"]) / 100
            replaced = {"improvement": imp["name"], "replaced": lowest["name"]}
    projected = secured + assumed
    needed = (goal - projected) / remaining * 100 if remaining > TOLERANCE else None
    if graded < TOLERANCE and not assumed_share:
        verdict = "no_grades"
    elif projected >= goal - TOLERANCE:
        verdict = "reached"
    elif remaining <= TOLERANCE or needed > 100 + TOLERANCE:
        verdict = "out_of_reach"
    else:
        verdict = "reachable"
    improvement = _improvement(periods, regular, secured, goal) if verdict == "out_of_reach" else None
    return {
        "passing_grade": passing, "target": goal, "verdict": verdict,
        "graded_share": _round(graded), "points_secured": _round(secured), "points_assumed": _round(assumed) or None,
        "assumed_share": _round(assumed_share) or None,
        "average_so_far": _round(secured / graded * 100) if graded > TOLERANCE and not replaced else None,
        "remaining_share": _round(remaining),
        "needed_on_remaining": _round(needed) if needed is not None and verdict == "reachable" else None,
        "max_possible": _round(projected + remaining),
        "improvement": improvement, "replaced": replaced,
        "periods": [_period_json(p) for p in periods],
        "unassigned_grades": [{"assignment_id": a["id"], "name": a["name"], "score": a["score"], "out_of": a["points"]}
                              for a in loose],
        "unassigned_manual": stray_manual,
        "open_questions": scheme["open_questions"], "sources": scheme["sources"],
    }


def weights(scheme: dict, assignments: list[dict], manual: list[dict], tz: ZoneInfo) -> dict[int, float | None]:
    """How many points of the final 100 each assignment a component takes is worth: its share of the
    component's points (graded, ungraded and not in Canvas yet) times the component's and its period's weight.
    None for one it takes but cannot weigh (no points in Canvas, excused, an improvement exam); absent when
    no component takes it."""
    slots, _ = assign(scheme, assignments, tz)
    result: dict[int, float | None] = {}
    for p in scheme["periods"]:
        for c in p["components"]:
            graded_points, pending_points, _ = _points(c, _items(p, c, slots, manual))
            total = graded_points + pending_points
            for a in slots[(p["name"], c["name"])]:
                weighable = not p["improvement"] and total and a["points"] and not a["excused"]
                result[a["id"]] = p["weight"] * c["weight"] / 100 * a["points"] / total if weighable else None
    return result


def _improvement(periods: list[dict], regular: list[dict], secured: float, goal: float) -> dict | None:
    """What the improvement exam would need, once the periods it replaces are complete."""
    imp = next((p for p in periods if p["improvement"] and not p["complete"]), None)
    if imp is None:
        return None
    names = {fold(n) for n in imp["replaces"]} or {fold(p["name"]) for p in regular}
    candidates = [p for p in regular if fold(p["name"]) in names]
    if not candidates or not all(p["complete"] for p in candidates):
        return {"name": imp["name"], "needed": None}
    lowest = min(candidates, key=lambda p: p["earned"])
    needed = lowest["earned"] + (goal - secured) / lowest["weight"] * 100
    return {"name": imp["name"], "replaces": lowest["name"], "needed": _round(needed) if needed <= 100 + TOLERANCE else None,
            "possible": needed <= 100 + TOLERANCE}


def _period_json(p: dict) -> dict:
    return {"name": p["name"], **({"weight": p["weight"]} if not p["improvement"] else
                                  {"improvement": True, "replaces": p["replaces"]}),
            **({"exception": p["exception"]} if p["exception"] else {}),
            "graded_share": _round(p["graded"]), "grade_so_far": _round(p["grade_so_far"]),
            "components": [{"name": c["name"], "weight": c["weight"], "graded_share": _round(c["graded_share"] * 100),
                            "average": _round(c["average"] * 100 if c["average"] is not None else None),
                            **({k: c[k] for k in ("what_if", "not_in_canvas_yet") if k in c}), "items": c["items"]}
                           for c in p["components"]]}


# -- the text the bots show -------------------------------------------------------------------------


def num(value: float | None) -> str:
    """58.7 → «58,7»; 60.0 → «60»."""
    if value is None:
        return "—"
    text = f"{_round(value):.1f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _item_text(item: dict) -> str:
    score = f"{num(item['score'])}/{num(item['out_of'])}" if item["status"] == "graded" else (
        "exonerada" if item["status"] == "excused" else "sin nota")
    return f"{item['name']} {score}" + (" (me lo dijiste)" if item.get("manual") else "")


def summary(name: str, result: dict) -> str:
    """The Spanish summary a bot shows as is (plain text, a line per idea)."""
    goal, verdict = result["target"], result["verdict"]
    aim = "aprobar" if goal == result["passing_grade"] else "llegar a"
    lines = [f"📊 {name}: cómo vas (para {aim}: {num(goal)}/100)"]
    if verdict == "no_grades":
        lines.append(f"Todavía no hay notas en lo que cuenta para la nota final. Para {aim} necesitas un promedio de "
                     f"{num(goal)} % en todo.")
    else:
        so_far = (f" (promedio {num(result['average_so_far'])} %)" if result["average_so_far"] is not None else "")
        ungraded = result["remaining_share"] + (result["assumed_share"] or 0)
        lines.append(f"Llevas {num(result['points_secured'])} de {num(result['graded_share'])} puntos calificados"
                     f"{so_far}. Falta calificar {num(ungraded)} de 100.")
        if result["assumed_share"]:
            lines.append(f"Con lo que supusiste en {num(result['assumed_share'])} de esos puntos, sumarías "
                         f"{num(result['points_assumed'])}; quedan {num(result['remaining_share'])} sin suponer.")
        if result["replaced"]:
            lines.append(f"{result['replaced']['improvement']} reemplazó a {result['replaced']['replaced']}.")
        if verdict == "reached":
            lines.append(f"✅ Ya tienes {num(goal)} asegurados: pase lo que pase en lo que falta, llegas.")
        elif verdict == "reachable":
            lines.append(f"Para {aim} necesitas un promedio de {num(result['needed_on_remaining'])} % en lo que falta "
                         f"(como máximo puedes sacar {num(result['max_possible'])}).")
        else:
            imp = result["improvement"]
            lines.append(f"⚠️ Ni con 100 % en lo que falta llegas a {num(goal)}: como máximo sacas "
                         f"{num(result['max_possible'])}.")
            if imp and imp.get("needed") is not None:
                lines.append(f"En {imp['name']} (reemplaza {imp['replaces']}) necesitas {num(imp['needed'])} %.")
            elif imp and imp.get("possible") is False:
                lines.append(f"Ni con {imp['name']} alcanzas {num(goal)}.")
            elif imp:
                lines.append(f"{imp['name']} puede reemplazar tu parcial más bajo cuando esté completo.")
    for p in result["periods"]:
        weight = (f" ({num(p['weight'])} % de la nota)" if "weight" in p else
                  f" (reemplaza {' o '.join(p['replaces']) or 'tu parcial más bajo'} si es mayor)")
        grade = f": {num(p['grade_so_far'])} % en lo calificado" if p["grade_so_far"] is not None else ""
        lines.append(f"• {p['name']}{weight}{grade}")
        if p.get("exception"):
            lines.append(f"  ↳ {p['exception']}")
        for c in p["components"]:
            if c["average"] is not None:
                detail = f"{num(c['average'])} % en el {num(c['graded_share'])} % calificado"
            else:
                detail = "sin notas todavía"
            if c.get("not_in_canvas_yet"):
                detail += f"; faltan {c['not_in_canvas_yet']} que el aula aún no tiene"
            if "what_if" in c:
                detail += f"; supones {num(c['what_if'])} % en lo que falta"
            graded = [_item_text(i) for i in c["items"] if i["status"] != "pending"]
            lines.append(f"  – {c['name']} ({num(c['weight'])} %): {detail}" + (f" · {'; '.join(graded)}" if graded else ""))
    if result["unassigned_grades"]:
        lines.append("❓ Notas que no sé a qué parte van: " + "; ".join(
            f"{g['name']} {num(g['score'])}/{num(g['out_of'])}" for g in result["unassigned_grades"]))
    if result["unassigned_manual"]:
        lines.append("❓ Notas que me diste y ya no calzan con el esquema: " + "; ".join(
            f"{m['label']} ({m['period']} · {m['component']})" for m in result["unassigned_manual"]))
    if result["open_questions"]:
        lines.append("⚠️ Falta confirmar: " + " ".join(q if q.endswith("?") else q + "." for q in result["open_questions"]))
    lines.append("Fuente: " + "; ".join(result["sources"]))
    return "\n".join(lines)


def scheme_text(scheme: dict, slots: dict) -> list[str]:
    """The scheme as the captain reviews it before saving: each part, its weight and what it takes from Canvas."""
    lines = [f"Para aprobar: {num(scheme['passing_grade'])}/100"]
    for p in scheme["periods"]:
        dates = " · ".join(filter(None, (f"desde {p['start']}" if p["start"] else "", f"hasta {p['end']}" if p["end"] else "")))
        head = (f"• {p['name']}: {num(p['weight'])} % de la nota" if not p["improvement"] else
                f"• {p['name']}: reemplaza " + (", ".join(p["replaces"]) or "tu parcial más bajo") + " si es mayor")
        lines.append(head + (f" ({dates})" if dates else ""))
        if p["exception"]:
            lines.append(f"  ↳ {p['exception']}")
        for c in p["components"]:
            feeds = [a["name"] for a in slots[(p["name"], c["name"])]]
            source = (f"del aula: {', '.join(feeds[:4])}" + (f" y {len(feeds) - 4} más" if len(feeds) > 4 else "")
                      if feeds else "todavía nada del aula")
            count = f", {c['expected_count']} en total" if c["expected_count"] else ""
            lines.append(f"  – {c['name']}: {num(c['weight'])} %{count} ({source})")
    return lines


def dumps(scheme: dict) -> str:
    return json.dumps(scheme, ensure_ascii=False)


# -- one subject, from the store --------------------------------------------------------------------


def assignments(conn: sqlite3.Connection, course_ids: list[int]) -> list[dict]:
    """The subject's Canvas assignments (theory and práctico) as compute() takes them."""
    rows = conn.execute(
        f"""SELECT id, name, due_at, points_possible, score, excused FROM assignments
            WHERE active = 1 AND course_id IN ({','.join('?' * len(course_ids)) or 'NULL'}) ORDER BY due_at, id""",
        course_ids).fetchall()
    return [{"id": r["id"], "name": r["name"], "due_at": r["due_at"], "points": r["points_possible"],
             "score": r["score"], "excused": r["excused"]} for r in rows]


def status(conn: sqlite3.Connection, subject: materias.Subject, tz: ZoneInfo, *,
           what_if: dict[tuple[str, str], float] | None = None, target: float | None = None) -> dict | None:
    """The subject's saved scheme applied to its grades now ({"summary", "result", "saved_at"}); None
    when no scheme is saved for it."""
    saved = store.grading_scheme(conn, subject.code)
    if saved is None:
        return None
    result = compute(saved["scheme"], assignments(conn, agenda.course_ids_for(conn, subject)),
                     store.manual_grades(conn, subject.code), tz, what_if=what_if, target=target)
    return {"summary": summary(subject.name, result), "result": result, "saved_at": saved["saved_at"]}


def component_names(scheme: dict) -> list[str]:
    return [f"{p['name']} · {c['name']}" for p in scheme["periods"] for c in p["components"]]


def find_component(scheme: dict, period: str, component: str) -> tuple[str, str] | None:
    """The (period, component) of the scheme these names refer to (accent- and case-insensitive)."""
    for p in scheme["periods"]:
        if fold(p["name"]) == fold(period):
            for c in p["components"]:
                if fold(c["name"]) == fold(component):
                    return p["name"], c["name"]
    return None
