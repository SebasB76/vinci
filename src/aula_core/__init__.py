"""Reusable, read-only core for the ESPOL aula virtual (Canvas LMS).

It holds the GET-only Canvas client, the local SQLite store and its sync, material
download/indexing, and read-side queries. It has no Telegram or Hermes dependency,
so the `aula` CLI, the Telegram bot, or a future web page can all build on it.

Gentle with Canvas: background work (the bot's poll) spaces its requests, downloads at most
`max_mb_per_sync` of material a run (only syllabi download on their own), and follows at most
CATALOG_BUDGET links a run to the material only they lead to. A token Canvas refused (401) is not used again,
and after Canvas kept throttling nothing reads it for a while, unless the reader is
`explicit` (a command the student ran); a successful read clears both.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aula_core import enlaces as _enlaces
from aula_core import materials as _materials
from aula_core import store as _store
from aula_core import sync as _sync
from aula_core import timefmt
from aula_core.canvas import CanvasClient, InvalidTokenError, ThrottledError
from aula_core.config import CoreConfig, canvas_token, load_config, now_utc

REFUSED_KEY = "canvas_token_refused"  # fingerprint of the token Canvas answered 401
PAUSED_KEY = "canvas_paused_until"    # after Canvas kept throttling, no reads before this
PAUSE = timedelta(hours=1)
CATALOG_BUDGET = 60  # reads a background sync spends on Pages and files that only a link leads to


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


@dataclass
class Aula:
    cfg: CoreConfig = field(default_factory=load_config)
    background: bool = False  # the bot's poll: paced, and a material budget per run
    explicit: bool = False    # the student asked for this read: try even a refused token or during a pause
    _conn: sqlite3.Connection | None = None
    _client: CanvasClient | None = None
    _client_token: str | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _store.connect(self.cfg.db_path)
        return self._conn

    @property
    def client(self) -> CanvasClient:
        token = canvas_token()
        if self._client is None or token != self._client_token:  # secrets.env may get a new token meanwhile
            self._client = CanvasClient(self.cfg.canvas_url, token,
                                        interval=self.cfg.request_interval if self.background else 0.0)
            self._client_token = token
        return self._client

    def now(self) -> datetime:
        return now_utc()

    def refused_token(self) -> str | None:
        """The fingerprint of the current token if Canvas refused it (401)."""
        refused = _store.get_meta(self.conn, REFUSED_KEY)
        return refused if refused == token_fingerprint(canvas_token()) else None

    @contextmanager
    def _reading(self) -> Iterator[CanvasClient]:
        if not self.explicit:
            if self.refused_token():
                raise InvalidTokenError("El token de Canvas no es válido o expiró (401); no lo vuelvo a usar hasta "
                                        "que pongas otro en secrets.env.", 401)
            paused = timefmt.parse(_store.get_meta(self.conn, PAUSED_KEY))
            if paused and self.now() < paused:
                raise ThrottledError(f"el aula virtual pidió bajar el ritmo; la vuelvo a leer desde las "
                                     f"{paused.astimezone(self.cfg.tz):%H:%M}", 429)
        client = self.client
        try:
            yield client
        except InvalidTokenError:
            _store.set_meta(self.conn, REFUSED_KEY, token_fingerprint(self._client_token or ""))
            self.conn.commit()
            raise
        except ThrottledError:
            _store.set_meta(self.conn, PAUSED_KEY, timefmt.iso(self.now() + PAUSE))
            self.conn.commit()
            raise
        _store.delete_meta(self.conn, REFUSED_KEY, PAUSED_KEY)
        self.conn.commit()

    def _sync(self) -> _sync.SyncReport:
        with self._reading() as client:
            return _sync.sync(self.conn, client, self.cfg, self.now(),
                              budget=CATALOG_BUDGET if self.background else None)

    def sync(self, *, materials: bool = False) -> _sync.SyncReport:
        with _store.sync_lock(self.cfg.data_dir):
            report = self._sync()
        if materials:
            with _store.material_lock(self.cfg.data_dir), self._reading() as client:
                _materials.sync_materials(self.conn, client, self.cfg,
                                          budget_mb=self.cfg.max_mb_per_sync if self.background else None)
        return report

    def is_stale(self, max_age_minutes: int) -> bool:
        last = _sync.last_sync(self.conn)
        return last is None or self.now() - last > timedelta(minutes=max_age_minutes)

    def ensure_fresh(self, max_age_minutes: int | None = None, *, wait: bool = True) -> _sync.SyncReport | None:
        """Sync when the saved copy is older than `max_age_minutes`. With `wait` off, a sync already running
        (the poll's, which paces its reads) is not waited for: the saved copy answers meanwhile."""
        minutes = self.cfg.cache_minutes if max_age_minutes is None else max_age_minutes
        if not self.is_stale(minutes):
            return None
        with _store.sync_lock(self.cfg.data_dir, wait=wait) as locked:
            if not locked or not self.is_stale(minutes):  # the sync this one waited for just refreshed it
                return None
            return self._sync()

    def download(self, file_id: int, *, index: bool = True):
        with _store.material_lock(self.cfg.data_dir), self._reading() as client:
            path = _materials.download(self.conn, client, self.cfg, file_id)
            row = self.conn.execute("SELECT index_status FROM files WHERE id = ?", (file_id,)).fetchone()
            ext = path.suffix.lower().lstrip(".")
            if index and ext in _materials.READABLE and not (row and row["index_status"]):
                _materials.index(self.conn, file_id)
            return path

    def fetch_link(self, link_id: int) -> int:
        """Open a public outside link of the catalog and index what it leads to (no Canvas read)."""
        return _enlaces.fetch(self.conn, self.cfg, link_id)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


__all__ = ["Aula", "CanvasClient", "CoreConfig", "load_config"]
