"""The student's path through the degree, from the Académico's copy (academic_portal.py) and a saved curriculum.

`progress` reads what the copy already holds: the credits each category of the degree still needs, the approved
subjects and the GPA. `simulate` estimates the GPA after some grades. The portal's GPA follows no formula the copy
can rebuild (the credit-weighted mean of approved and credited subjects lands within about 0.2), so the estimate is
the portal's own GPA plus the change that weighted mean shows. The curriculum, with each subject's requisites, comes
with the Académico's copy (its «malla» section, from mallacurricular.espol.edu.ec); only when it did not come, Vinci
reads it from a photo or the PDF the student sends and saves it with `save_curriculum`. With it, `progress` also says
which subjects they can take next.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from aula_core.catalog import fold
from espol_bot import academic_portal
from espol_bot.config import BotConfig

CURRICULUM = "malla.json"
MAX_SUBJECTS = 120
DONE = ("approved", "credited")
NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


class PlanError(Exception):
    pass


def _num(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    m = NUMBER.search(str(value or ""))
    return float(m.group().replace(",", ".")) if m else None


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", fold(name)).strip()


def _credits(copy: dict) -> tuple[dict[str, float], list[dict]]:
    """({subject code: credits}, [{"category", "taken", "required", "missing"}]) from the «créditos» page."""
    by_code, categories = {}, []
    for table in (copy.get("sections", {}).get("creditos") or {}).get("tablas") or []:
        for row in table.get("filas") or []:
            if not isinstance(row, dict):
                continue
            if row.get("Cod. Materia") and (credits := _num(row.get("# Créditos"))) is not None:
                by_code[row["Cod. Materia"].strip()] = credits
            elif row.get("Tipo de Crédito"):
                taken, required = _num(row.get("# Tomados")) or 0, _num(row.get("# del Flujo")) or 0
                categories.append({"category": row["Tipo de Crédito"].strip(), "taken": taken, "required": required,
                                   "missing": max(0.0, required - taken)})
    return by_code, categories


def _done(copy: dict) -> list[dict]:
    subjects = (copy.get("sections", {}).get("historial") or {}).get("materias") or []
    return [s for s in subjects if s.get("status_kind") in DONE]


def _taking(copy: dict, curriculum: dict) -> set[str]:
    """Codes of the subjects in course this term, from the history or the curriculum's own status."""
    subjects = (copy.get("sections", {}).get("historial") or {}).get("materias") or []
    codes = {(s.get("code") or "").strip().upper() for s in subjects if s.get("status_kind") == "in_progress"}
    codes |= {(s.get("code") or "").upper() for s in curriculum.get("subjects") or []
              if fold(s.get("status") or "").startswith("en curso")}
    return codes - {""}


def curriculum(cfg: BotConfig, copy: dict | None) -> dict | None:
    """The Académico's curriculum when the copy has it; otherwise the one saved from a photo."""
    from_portal = ((copy or {}).get("sections") or {}).get("malla")
    return from_portal if from_portal and from_portal.get("subjects") else load_curriculum(cfg)


def _weighted(rows: list[tuple[float, float]]) -> float | None:
    total = sum(c for _, c in rows)
    return sum(g * c for g, c in rows) / total if total else None


def curriculum_path(cfg: BotConfig) -> Path:
    return cfg.core.data_dir / CURRICULUM


def load_curriculum(cfg: BotConfig) -> dict | None:
    try:
        return json.loads(curriculum_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_curriculum(cfg: BotConfig, career: str, subjects: list[dict]) -> dict:
    """Keeps the curriculum Vinci read from the student's photo or PDF: [{"code"?, "name", "credits"?, "level"?,
    "prerequisites": [code or name]}]."""
    if not subjects or len(subjects) > MAX_SUBJECTS:
        raise PlanError(f"La malla debe tener entre 1 y {MAX_SUBJECTS} materias.")
    clean = []
    for s in subjects:
        name = str(s.get("name") or "").strip()
        if not name:
            raise PlanError("Cada materia de la malla necesita su nombre.")
        clean.append({"code": str(s.get("code") or "").strip().upper() or None, "name": name,
                      "credits": _num(s.get("credits")), "level": s.get("level"),
                      "prerequisites": [str(p).strip() for p in s.get("prerequisites") or [] if str(p).strip()]})
    data = {"career": str(career or "").strip() or None, "subjects": clean}
    path = curriculum_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return data


def _next(curriculum: dict, done: list[dict], taking: set[str] = frozenset()) -> dict:
    """The curriculum's subjects not passed yet: those in course, those whose prerequisites are all passed, and the
    rest with what they still lack. A prerequisite is matched by code or by name; a corequisite is taken along."""
    passed = {s.get("code", "").strip().upper() for s in done} | {_key(s.get("name") or "") for s in done}
    subjects = curriculum.get("subjects") or []
    names = {(s.get("code") or "").upper(): s["name"] for s in subjects if s.get("code")}
    codes = {_key(s["name"]): s["code"].upper() for s in subjects if s.get("code")}

    def is_passed(ref: str) -> bool:
        return bool(ref) and (ref.upper() in passed or _key(ref) in passed
                              or _key(names.get(ref.upper(), "")) in passed or codes.get(_key(ref)) in passed)

    ready, locked, current = [], [], []
    for s in subjects:
        if is_passed(s.get("code") or "") or _key(s["name"]) in passed:
            continue
        row = {"name": s["name"], **{k: s[k] for k in ("code", "credits", "level") if s.get(k) is not None}}
        if (s.get("code") or "").upper() in taking:
            current.append(row)
            continue
        lacking = [names.get(p.upper(), p) for p in s.get("prerequisites") or [] if not is_passed(p)]
        if s.get("min_passed") and len(done) < s["min_passed"]:
            lacking.append(f"{s['min_passed']} materias aprobadas (lleva {len(done)})")
        along = [names.get(c.upper(), c) for c in s.get("corequisites") or [] if not is_passed(c)]
        if along:
            row["take_with"] = along
        if lacking:
            locked.append({**row, "lacks": lacking})
        else:
            ready.append(row)
    # A locked subject that unlocks many others is worth taking soon: count how many wait on each ready one.
    for r in ready:
        refs = {(r.get("code") or "").upper(), _key(r["name"])} - {""}
        r["unlocks"] = sum(1 for s in subjects
                           if any(p.upper() in refs or _key(p) in refs for p in s.get("prerequisites") or []))
    ready.sort(key=lambda r: (-r["unlocks"], str(r.get("level") or ""), r["name"]))
    return {"in_course": current, "can_take": ready, "locked": locked}


def progress(cfg: BotConfig) -> dict:
    copy = academic_portal.load(cfg)
    if copy is None:
        raise PlanError("No tengo tu Académico: conéctalo primero (academic_record).")
    facts = (copy.get("sections", {}).get("general") or {}).get("datos") or {}
    by_code, categories = _credits(copy)
    done = _done(copy)
    answer = {
        "read_at": copy.get("saved_at"), "period": copy.get("period"),
        "career": facts.get("Carrera"), "level": facts.get("Nivel"),
        "gpa": _num(facts.get("Promedio General en las materias aprobadas")),
        "progress": facts.get("Avance de la carrera"), "credits_to_take": _num(facts.get("Créditos por tomar")),
        "categories": [c for c in categories if c["required"]],
        "passed": [{"code": s.get("code"), "name": s.get("name"), "grade": _num(s.get("grade")),
                    "credits": by_code.get((s.get("code") or "").strip())} for s in done],
    }
    found = curriculum(cfg, copy)
    if found:
        answer["curriculum"] = {"from": found.get("source") or "su foto o PDF", "career": found.get("career"),
                                **_next(found, done, _taking(copy, found))}
    else:
        answer["curriculum"] = None
    return answer


def simulate(cfg: BotConfig, grades: list[dict]) -> dict:
    """The GPA estimated after `grades` ([{"subject", "grade", "credits"?}]): the portal's GPA plus the change in the
    credit-weighted mean. A subject's credits come from the call, the saved curriculum or the «créditos» page."""
    copy = academic_portal.load(cfg)
    if copy is None:
        raise PlanError("No tengo tu Académico: conéctalo primero (academic_record).")
    facts = (copy.get("sections", {}).get("general") or {}).get("datos") or {}
    gpa = _num(facts.get("Promedio General en las materias aprobadas"))
    by_code, _ = _credits(copy)
    found = curriculum(cfg, copy) or {}
    known = {_key(s["name"]): s.get("credits") for s in found.get("subjects") or []}
    known |= {(s.get("code") or "").upper(): s.get("credits") for s in found.get("subjects") or [] if s.get("code")}
    now = [(_num(s.get("grade")), by_code.get((s.get("code") or "").strip())) for s in _done(copy)]
    now = [(g, c) for g, c in now if g is not None and c]
    added, unknown = [], []
    for item in grades:
        subject, grade = str(item.get("subject") or "").strip(), _num(item.get("grade"))
        credits = _num(item.get("credits")) or known.get(subject.upper()) or known.get(_key(subject))
        if grade is None or not 0 <= grade <= 10:
            raise PlanError(f"La nota de «{subject}» debe ir de 0 a 10.")
        if not credits:
            unknown.append(subject)
            continue
        added.append((grade, credits))
    if unknown:
        return {"needs_credits": unknown, "note": "Ask how many credits each of these subjects has, then call again."}
    before, after = _weighted(now), _weighted(now + added)
    if gpa is None or before is None or after is None:
        raise PlanError("Tu Académico no trae tu promedio ni tus créditos: actualízalo (academic_record con refresh).")
    return {"gpa_now": gpa, "gpa_estimated": round(gpa + after - before, 2),
            "note": "An estimate: the portal's own formula is not public. Say so in one line."}
