"""Reusable, read-only core for the ESPOL aula virtual (Canvas LMS).

It holds the GET-only Canvas client, the local SQLite store and its sync, material
download/indexing, and read-side queries. It has no Telegram or Hermes dependency,
so the `aula` CLI, the Telegram bot, or a future web page can all build on it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aula_core import materials as _materials
from aula_core import store as _store
from aula_core import sync as _sync
from aula_core.canvas import CanvasClient
from aula_core.config import CoreConfig, canvas_token, load_config, now_utc


@dataclass
class Aula:
    cfg: CoreConfig = field(default_factory=load_config)
    _conn: sqlite3.Connection | None = None
    _client: CanvasClient | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = _store.connect(self.cfg.db_path)
        return self._conn

    @property
    def client(self) -> CanvasClient:
        if self._client is None:
            self._client = CanvasClient(self.cfg.canvas_url, canvas_token())
        return self._client

    def now(self) -> datetime:
        return now_utc()

    def sync(self, *, materials: bool = False) -> _sync.SyncReport:
        with _store.sync_lock(self.cfg.data_dir):
            report = _sync.sync(self.conn, self.client, self.cfg, self.now())
        if materials:
            with _store.material_lock(self.cfg.data_dir):
                _materials.sync_materials(self.conn, self.client, self.cfg)
        return report

    def is_stale(self, max_age_minutes: int) -> bool:
        last = _sync.last_sync(self.conn)
        return last is None or self.now() - last > timedelta(minutes=max_age_minutes)

    def ensure_fresh(self, max_age_minutes: int | None = None) -> _sync.SyncReport | None:
        minutes = self.cfg.cache_minutes if max_age_minutes is None else max_age_minutes
        if not self.is_stale(minutes):
            return None
        with _store.sync_lock(self.cfg.data_dir):
            if not self.is_stale(minutes):  # the sync this one waited for just refreshed it
                return None
            return _sync.sync(self.conn, self.client, self.cfg, self.now())

    def download(self, file_id: int, *, index: bool = True):
        with _store.material_lock(self.cfg.data_dir):
            path = _materials.download(self.conn, self.client, self.cfg, file_id)
            row = self.conn.execute("SELECT index_status FROM files WHERE id = ?", (file_id,)).fetchone()
            ext = path.suffix.lower().lstrip(".")
            if index and ext in ("pdf", "pptx", "docx") and not (row and row["index_status"]):
                _materials.index(self.conn, file_id)
            return path

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


__all__ = ["Aula", "CanvasClient", "CoreConfig", "load_config"]
