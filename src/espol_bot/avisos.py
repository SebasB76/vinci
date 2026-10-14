"""Notices for the WhatsApp groups the captain turned them on in («@vinci activa los avisos», amigos.notice_groups).

Model-free. In a plain notice group, only what the whole class shares: never a grade, a submission or the notebook.
  - `class_reminders`, from Vinci's agenda tick (every minute): `brief_minutos_antes` before each class in
    horario.toml, the subject, time, room (marked when it is virtual) and what of that subject is due in 7 days,
    submitted or not, since a classmate may not have. Each class start is claimed in `briefs` as «grupo:<code>»,
    so a restart never sends it twice and the captain's own brief is not affected.
  - `send_events`, from the captain's poller: the aula's new announcements, new assignments and changed due dates,
    all of one poll in a single message.
  - `group_reminders`, from the same agenda tick: what the captain asked Vinci to remind a group of, at the time he
    gave (`group_reminder`), in any group that is on, with or without notices.

A trusted group («@vinci este grupo es de confianza», amigos.trusted_groups) is friends who agreed to share their
aula with each other. Its members are the captain and every friend with a Vinci who is in it (the bridge's
participants, matched by the LID WhatsApp shows instead of the number). There, besides:
  - the class reminder mentions the members in the captain's paralelo of that subject, carries the meeting link of
    a virtual class (Zoom, Teams or Meet, from the aula) and says who already handed in each task;
  - the news also takes the friends' own aulas, read from their folders since the last poll (`group_news_from:`
    in the captain's meta), each novelty sent once (`group_news`) and mentioning who has that course.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import requests

from aula_core import Aula, timefmt
from aula_core.queries import DONE_SQL
from aula_core.store import get_meta, set_meta
from espol_bot import amigos, horario, materias, messages, store, whatsapp
from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

EVENT_KINDS = ("new_announcement", "new_assignment", "due_changed")
DUE_DAYS = 7
MEETING = re.compile(r"https://[\w.-]*(?:zoom\.us/j/|teams\.microsoft\.com/l/(?:meetup-join|team)/|meet\.google\.com/)\S+")
PARALELO = re.compile(r"paralelo\s*(\d+)", re.I)
LATE = timedelta(hours=6)  # a reminder missed by more (the laptop was off) is dropped, not sent out of time


@dataclass
class Member:
    name: str
    db: Path
    jid: str | None = None  # «<lid>@lid» or «<number>@s.whatsapp.net»; None for the captain, not tagged in his group
    courses: dict[int, str] = field(default_factory=dict)  # course id → course code


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # a friend's aula: read, never written from here
    conn.row_factory = sqlite3.Row
    return conn


def _lid(number: str) -> str | None:
    try:
        lid = json.loads((whatsapp.session_dir() / f"lid-mapping-{number}.json").read_text(encoding="utf-8"))
        return str(lid).split("@")[0] or None
    except (OSError, ValueError):
        return None


def members(cfg: BotConfig, group: str) -> list[Member]:
    """The captain first, then each friend with a Vinci who is in the group."""
    captain = amigos.captain_number(cfg)
    names = {}
    try:
        names = json.loads((amigos.root(cfg) / "whatsapp-nombres.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    # a WhatsApp name may start with a dash or an emoji («-Sebastian B»)
    found = [Member(re.sub(r"^\W+", "", names.get(captain) or "") or "Capitán", cfg.core.data_dir / "espol.db")]
    try:
        resp = requests.get(f"{cfg.whatsapp_bridge}/chat/{group}", timeout=10)
        inside = {p.split("@")[0].split(":")[0] for p in resp.json().get("participants") or []}
    except (requests.RequestException, ValueError) as exc:
        log.error("avisos %s: no leí los miembros del grupo: %s", group, exc)
        inside = set()
    for friend in amigos.active(cfg):
        lid = _lid(friend.numero)
        db = amigos.root(cfg) / friend.slug / "espol.db"
        if db.exists() and (friend.numero in inside or (lid and lid in inside)):
            found.append(Member(friend.nombre, db, f"{lid}@lid" if lid else f"{friend.numero}@s.whatsapp.net"))
    for m in found:
        try:
            conn = _connect(m.db)
            m.courses = {r["id"]: r["course_code"] or "" for r in conn.execute(
                "SELECT id, course_code FROM courses WHERE active = 1")}
            conn.close()
        except sqlite3.Error as exc:
            log.error("avisos: no leí el aula de %s: %s", m.name, exc)
    return found


def _tags(people: list[Member]) -> tuple[str, list[str]]:
    """«@Angel @Carlos» as WhatsApp mentions (text and JIDs); the captain by name."""
    return (" ".join(f"@{m.jid.split('@')[0]}" if m.jid else m.name for m in people),
            [m.jid for m in people if m.jid])


def _send(cfg: BotConfig, groups: list[str], html_text: str, mentions: list[str] | None = None) -> None:
    text = whatsapp.from_html(html_text)
    for group in groups:
        try:
            whatsapp.send_text(cfg.whatsapp_bridge, group, text, mentions=mentions)
        except Exception as exc:  # one group the number left must not stop the rest
            log.error("avisos %s: %s", group, exc)


def _due(conn, course_ids: list[int], now: datetime) -> list:
    if not course_ids:
        return []
    return conn.execute(
        f"""SELECT id, name, due_at FROM assignments WHERE active = 1 AND due_at >= ? AND due_at < ?
            AND course_id IN ({','.join('?' * len(course_ids))}) ORDER BY due_at""",
        [timefmt.iso(now), timefmt.iso(now + timedelta(days=DUE_DAYS)), *course_ids]).fetchall()


def _meeting(conn, course_ids: list[int]) -> str | None:
    if not course_ids:
        return None
    rows = conn.execute(
        f"SELECT url FROM links WHERE active = 1 AND course_id IN ({','.join('?' * len(course_ids))})"
        " ORDER BY first_seen DESC", course_ids).fetchall()
    return next((r["url"] for r in rows if MEETING.fullmatch(r["url"])), None)


def _handed_in(people: list[Member], code: str, task) -> tuple[list[Member], list[Member]]:
    """Who of `people` with this subject already handed in `task`: the same assignment, or one of the same name in
    another paralelo's course."""
    done, missing = [], []
    for m in people:
        ids = [i for i, c in m.courses.items() if materias.base_code(c) == code]
        if not ids:
            continue
        try:
            conn = _connect(m.db)
            row = conn.execute(
                f"SELECT {DONE_SQL} AS done FROM assignments a WHERE a.active = 1 AND (a.id = ? OR"
                f" lower(trim(a.name)) = lower(trim(?)) AND a.course_id IN ({','.join('?' * len(ids))}))"
                " ORDER BY a.id = ? DESC LIMIT 1", [task["id"], task["name"], *ids, task["id"]]).fetchone()
            conn.close()
        except sqlite3.Error:
            continue
        if row is not None:
            (done if row["done"] else missing).append(m)
    return done, missing


def reminder_text(cfg: BotConfig, subject, start: datetime, blocks: list[horario.Clase], due: list,
                  now: datetime, *, people: list[Member] | None = None, meeting: str | None = None
                  ) -> tuple[str, list[str]]:
    """The reminder and the JIDs it mentions; `people` (a trusted group's members) adds the tags and who handed in."""
    tz, clase = cfg.core.tz, blocks[0]
    minutes = max(1, round((start - now).total_seconds() / 60))
    local = start.astimezone(tz)
    day = "Hoy" if local.date() == now.astimezone(tz).date() else "Mañana"
    lines = [f"🔔 <b>Clase en {minutes} min: {messages.e(subject.name)}</b>",
             f"{day} {timefmt.DAYS_LONG[local.weekday()]} {local.day} {timefmt.MONTHS[local.month - 1]}, "
             f"{clase.inicio:%H:%M}–{max(b.fin for b in blocks):%H:%M}"
             + (f" · {messages.e(clase.aula)}" if clase.aula else "")]
    if "virtual" in (clase.aula or "").lower():
        lines.append(f"🖥️ Es virtual: {messages.e(meeting)}" if meeting else
                     "🖥️ Es virtual: el enlace está en el aula virtual.")
    jids: list[str] = []
    if people:
        mates = [m for m in people[1:] if any(
            materias.base_code(c) == subject.code and (m_ := PARALELO.search(c)) and m_[1] == clase.paralelo
            for c in m.courses.values())]
        if mates:
            text, jids = _tags(mates)
            lines.append(f"👥 {text}")
    if due:
        lines.append("\n<b>Vence esta semana</b>")
        for r in due:
            lines.append(f"• {messages.e(r['name'])}: {messages.e(timefmt.human(r['due_at'], tz))} "
                         f"({messages.e(timefmt.until(r['due_at'], now))})")
            if people:
                done, missing = _handed_in(people, subject.code, r)
                parts = ([f"✅ {', '.join(messages.e(m.name) for m in done)}"] if done else []) + \
                        ([f"⏳ falta {_tags(missing)[0]}"] if missing else [])
                jids += [j for j in _tags(missing)[1] if j not in jids]
                if parts:
                    lines.append("  " + " · ".join(parts))
    return "\n".join(lines), jids


def class_reminders(cfg: BotConfig, subjects: list, now: datetime) -> None:
    from espol_bot import agenda
    groups = amigos.notice_groups(cfg)
    if not groups:
        return
    trusted = set(amigos.trusted_groups(cfg))
    for subject in subjects:
        found = agenda.sessions(cfg, subject)
        lead = timedelta(minutes=cfg.brief_minutes)
        upcoming = [(start, c) for start, c in horario.occurrences(
            list(found), now, now + lead + timedelta(seconds=1), cfg.core.tz, subject.code)
            if now < start <= now + lead]
        if not upcoming:
            continue
        aula = Aula(cfg.core)
        try:
            conn = store.ensure(aula.conn)
            for start, clase in upcoming:
                if not store.claim_brief(conn, f"grupo:{subject.code}", start, now):
                    continue
                course_ids = agenda.course_ids_for(conn, subject)
                due = _due(conn, course_ids, now)
                log.info("avisos: clase de %s %s a %d grupos", subject.code, start.isoformat(), len(groups))
                for group in groups:
                    if group in trusted:
                        text, jids = reminder_text(cfg, subject, start, found[clase], due, now,
                                                   people=members(cfg, group), meeting=_meeting(conn, course_ids))
                    else:
                        text, jids = reminder_text(cfg, subject, start, found[clase], due, now)
                    _send(cfg, [group], text, jids)
        finally:
            aula.close()


def _friend_events(cfg: BotConfig, conn, people: list[Member]) -> list[dict]:
    """What the friends' polls found since the captain's last poll; the first time, only from now on."""
    found = []
    for m in people[1:]:
        key = f"group_news_from:{m.db.parent.name}"
        try:
            friend = _connect(m.db)
            last = friend.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]
            since = get_meta(conn, key)
            if since is not None:
                rows = friend.execute("SELECT * FROM events WHERE id > ? AND id <= ? ORDER BY id",
                                      (int(since), last)).fetchall()
                found += [{"kind": r["kind"], "course_id": r["course_id"], "ref_id": r["ref_id"],
                           **json.loads(r["payload"])} for r in rows if r["kind"] in EVENT_KINDS]
            friend.close()
            set_meta(conn, key, str(last))
        except sqlite3.Error as exc:
            log.error("avisos: no leí lo nuevo de %s: %s", m.name, exc)
    conn.commit()
    return found


def _key(ev: dict) -> str:
    return f"{ev['kind']}:{ev.get('course_id')}:{ev.get('ref_id')}:{ev.get('due_at') if ev['kind'] == 'due_changed' else ''}"


def news_text(events: list[dict], tz, people: list[Member] | None = None) -> tuple[str, list[str]]:
    """Every novelty of one poll as one message, so the group gets a single notice, not one per event."""
    blocks, jids = ["📢 <b>Novedades del aula</b>"], []
    for kind in EVENT_KINDS:
        lines = []
        for ev in (ev for ev in events if ev["kind"] == kind):
            line = messages._digest_line(ev, tz)
            if people:
                who = [m for m in people[1:] if ev.get("course_id") in m.courses]
                if who:
                    text, tagged = _tags(who)
                    line += f" · {text}"
                    jids += [j for j in tagged if j not in jids]
            text = " ".join((ev.get("texto") or "").split()) if kind == "new_announcement" else ""
            lines.append(line + (f"\n  {messages.e(text[:200].rstrip())}{'…' if len(text) > 200 else ''}" if text else ""))
        if lines:
            blocks.append(f"<b>{messages.KIND_TITLE[kind]}</b>\n" + "\n".join(lines))
    return "\n\n".join(blocks), jids


def send_events(cfg: BotConfig, conn, events: list[dict], now: datetime) -> None:
    groups = amigos.notice_groups(cfg)
    if not groups:
        return
    trusted = set(amigos.trusted_groups(cfg))
    own = [ev for ev in events if ev["kind"] in EVENT_KINDS]
    for group in groups:
        people = members(cfg, group) if group in trusted else None
        batch = own + (_friend_events(cfg, conn, people) if people else [])
        fresh, seen = [], set()
        for ev in batch:
            key = _key(ev)
            if key in seen or conn.execute("SELECT 1 FROM group_news WHERE grupo = ? AND clave = ?",
                                           (group, key)).fetchone():
                continue
            seen.add(key)
            fresh.append(ev)
        if not fresh:
            continue
        text, jids = news_text(fresh, cfg.core.tz, people)
        _send(cfg, [group], text, jids)
        conn.executemany("INSERT OR IGNORE INTO group_news(grupo, clave, enviado) VALUES (?, ?, ?)",
                         [(group, _key(ev), timefmt.iso(now)) for ev in fresh])
        conn.commit()


def group_reminders(cfg: BotConfig, now: datetime) -> None:
    aula = Aula(cfg.core)
    try:
        conn = store.ensure(aula.conn)
        due = conn.execute("SELECT * FROM group_reminders WHERE sent_at IS NULL AND remind_at <= ? ORDER BY remind_at, id",
                           (timefmt.iso(now),)).fetchall()
        for r in due:
            # claimed before it goes out, so a second tick or a restart never sends it twice
            if conn.execute("UPDATE group_reminders SET sent_at = ? WHERE id = ? AND sent_at IS NULL",
                            (timefmt.iso(now), r["id"])).rowcount != 1:
                continue
            conn.commit()
            if now - timefmt.parse(r["remind_at"]) > LATE:
                log.warning("avisos: recordatorio #%d de %s no salió a tiempo; lo descarto", r["id"], r["remind_at"])
                continue
            group = r["chat"].removeprefix("whatsapp:")
            if group not in amigos.groups(cfg):
                log.info("avisos: recordatorio #%d de un grupo apagado; no sale", r["id"])
                continue
            log.info("avisos: recordatorio #%d al grupo", r["id"])
            _send(cfg, [group], f"⏰ <b>Recordatorio</b>\n{messages.e(r['text'])}")
    finally:
        aula.close()
