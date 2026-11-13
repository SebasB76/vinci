"""Joining a group of a course (a project team, «Semana 7 6») where the professor opened self sign-up.

Like submission.py, this writes to Canvas, and only from the student's own vote (botones.py, `v1:j:<group>:ok`):
the tool finds the group and shows the card; the press joins. Canvas moves the student out of their group in
the same set by itself.
"""

from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urlsplit

import requests

from aula_core import Aula
from aula_core.canvas import CanvasError
from aula_core.config import CoreConfig, canvas_token
from aula_core.extras import self_id
from aula_core.store import delete_meta

SELF_SIGNUP = ("enabled", "restricted")
TIMEOUT = (10, 30)
USER_AGENT = "espol-academic-bot/0.1 (grupos)"
TRAILING_NUMBER = re.compile(r"(\d+)\s*$")


class GroupError(Exception):
    pass


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def open_groups(aula: Aula, course_ids: list[int]) -> list[dict]:
    """Every group of these courses whose set lets students sign up by themselves, with its set."""
    found = []
    for course_id in course_ids:
        try:
            groups = aula.client.get_all(f"courses/{course_id}/groups", {"include[]": "group_category"})
        except CanvasError as exc:
            raise GroupError(f"no pude leer los grupos del aula: {exc}") from None
        for g in groups:
            category = g.get("group_category") or {}
            if category.get("self_signup") in SELF_SIGNUP:
                found.append({"id": g["id"], "name": g.get("name") or "", "course_id": course_id,
                              "set_id": category.get("id"), "set": category.get("name") or "",
                              "members": g.get("members_count") or 0, "max": g.get("max_membership")})
    return found


def choose(groups: list[dict], wanted: str, group_set: str | None) -> dict:
    """The group the student named: its number («6») or its name, inside `group_set` when they gave one."""
    if group_set:
        target = _norm(group_set)
        groups = [g for g in groups if target in _norm(g["set"])]
        if not groups:
            raise GroupError(f"no hay un conjunto de grupos «{group_set}» con inscripción abierta en esa materia.")
    wanted_norm = _norm(wanted)
    number = wanted_norm if wanted_norm.isdigit() else None
    if number is None and (m := re.fullmatch(r"(?:grupo|group|equipo|team)\s*(\d+)", wanted_norm)):
        number = m[1]
    if number is not None:
        matches = [g for g in groups if (m := TRAILING_NUMBER.search(g["name"])) and int(m[1]) == int(number)]
    else:
        matches = [g for g in groups if _norm(g["name"]) == wanted_norm] or \
            [g for g in groups if wanted_norm in _norm(g["name"])]
    if not matches:
        raise GroupError(f"no encuentro el grupo «{wanted}» entre los que tienen inscripción abierta.")
    if len(matches) > 1:
        sets = sorted({g["set"] for g in matches})
        raise GroupError(f"hay un «{wanted}» en varios conjuntos ({', '.join(sets)}): pregúntale en cuál.")
    return matches[0]


def members(aula: Aula, group_id: int) -> list[str]:
    """Who is in the group, the student left out."""
    try:
        me = self_id(aula)
        return sorted(p.get("name") or "" for p in aula.client.get_all(f"groups/{group_id}/users") if p.get("id") != me)
    except CanvasError:
        return []


def current_in_set(aula: Aula, set_id: int | None) -> dict | None:
    """The student's group in that set now, the one Canvas takes them out of."""
    try:
        mine = aula.client.get_all("users/self/groups", {"per_page": 50})
    except CanvasError:
        return None
    return next((g for g in mine if set_id is not None and g.get("group_category_id") == set_id), None)


def join(cfg: CoreConfig, group_id: int) -> dict:
    """Joins the group as the token's owner; returns the group as Canvas has it after the join."""
    base = cfg.canvas_url.rstrip("/") + "/api/v1"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {canvas_token()}", "User-Agent": USER_AGENT})

    def call(method: str, path: str, **kwargs) -> dict:
        url = f"{base}/{path}"
        if urlsplit(url).netloc != urlsplit(cfg.canvas_url).netloc:
            raise GroupError("dirección de otro sitio; no le mandé tu token.")
        try:
            resp = session.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise GroupError(f"no pude conectar con el aula ({type(exc).__name__}).") from None
        if resp.status_code == 401 and "access token" in resp.text[:500].lower():
            raise GroupError("el aula rechazó tu token. Mándale /token a Vinci y vuelve a votar.")
        if resp.status_code >= 400:
            raise GroupError(f"el aula no te dejó unirte ({resp.status_code}): {_message(resp)}")
        try:
            return resp.json()
        except ValueError:
            raise GroupError("el aula respondió algo que no entiendo.") from None

    try:
        group = call("GET", f"groups/{group_id}")
        limit = group.get("max_membership")
        if limit and (group.get("members_count") or 0) >= limit:
            raise GroupError(f"«{group.get('name')}» ya está lleno ({limit} de {limit}).")
        call("POST", f"groups/{group_id}/memberships", data={"user_id": "self"})
        return call("GET", f"groups/{group_id}")
    finally:
        session.close()


def remember(aula: Aula, group: dict, others: list[str]) -> None:
    """Records the new group as already seen, so the next poll does not announce it as news; the group left in the
    same set drops off at that poll."""
    aula.conn.execute(
        """INSERT INTO student_groups(id, course_id, name, members_count, members, active) VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, members_count=excluded.members_count,
             members=excluded.members, active=1""",
        (group["id"], group.get("course_id"), group.get("name"), group.get("members_count"),
         json.dumps(others, ensure_ascii=False)))
    delete_meta(aula.conn, "groups_read")
    aula.conn.commit()


def _message(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list) and errors:
        return "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors)
    if isinstance(errors, dict):
        return "; ".join(str(v) for v in errors.values())
    return str(body)[:200]


def describe(group: dict) -> str:
    spots = f"{group['members']}/{group['max']}" if group.get("max") else str(group["members"])
    return f"{group['name']} ({spots})"

