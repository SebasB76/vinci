"""Each subject bot's notebook: `cuadernos/<CÓDIGO>/` in the data folder.

    cuaderno.db   one row per entry: what was covered in a class, a note, a doubt,
                  a weak topic, or an attachment (board photo, voice note, document)
                  with its summary (and the transcript of a voice note)
    adjuntos/     the attached files themselves

Only the subject bot writes its own notebook (through its tool server or its own
agenda). Vinci reads every notebook through `Notebook(..., read_only=True)`, which
opens SQLite in read-only mode and never creates a file.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from aula_core import timefmt
from aula_core.config import CoreConfig
from aula_core.materials import safe_filename

NOTE_KINDS = ("clase", "apunte", "duda", "tema_debil")
FILE_KINDS = ("foto", "audio", "documento")
KINDS = NOTE_KINDS + FILE_KINDS + ("de_vinci",)
OPEN_KINDS = ("duda", "tema_debil")
MAX_TEXT = 6000

SCHEMA = """
CREATE TABLE IF NOT EXISTS entradas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    texto TEXT NOT NULL,
    transcripcion TEXT,
    archivo TEXT,
    fecha_clase TEXT,
    estado TEXT,
    origen TEXT NOT NULL DEFAULT 'estudiante',
    creado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entradas_creado ON entradas(creado);
"""


class NotebookError(Exception):
    pass


def root(cfg: CoreConfig) -> Path:
    return cfg.data_dir / "cuadernos"


class Notebook:
    def __init__(self, cfg: CoreConfig, code: str, *, read_only: bool = False):
        self.code = code.upper()
        self.tz = cfg.tz
        self.dir = root(cfg) / self.code
        self.files = self.dir / "adjuntos"
        self.read_only = read_only
        self._conn: sqlite3.Connection | None = None

    @property
    def db_path(self) -> Path:
        return self.dir / "cuaderno.db"

    def _connect(self) -> sqlite3.Connection | None:
        if self._conn is None:
            if self.read_only:
                if not self.db_path.exists():
                    return None
                conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=30)
            else:
                self.files.mkdir(parents=True, exist_ok=True)
                # Plain rollback journal (no WAL): a read-only reader then never creates files here.
                conn = sqlite3.connect(self.db_path, timeout=30)
                conn.executescript(SCHEMA)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- writing (the subject bot only) ---------------------------------------------------

    def _writer(self) -> sqlite3.Connection:
        if self.read_only:
            raise NotebookError("Este cuaderno está abierto solo para lectura.")
        conn = self._connect()
        assert conn is not None
        return conn

    def add(self, kind: str, text: str, now: datetime, *, class_date: str | None = None,
            transcript: str | None = None, source_file: Path | None = None, move: bool = False,
            name: str | None = None, origin: str = "estudiante") -> dict:
        """`name` is the file's original name when `source_file` sits under a staging name."""
        if kind not in KINDS:
            raise NotebookError(f"Tipo de entrada inválido: {kind!r} (usa {', '.join(KINDS)}).")
        text = (text or "").strip()
        if not text and not source_file:
            raise NotebookError("La entrada está vacía.")
        if class_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", class_date):
            raise NotebookError("fecha_clase debe tener formato AAAA-MM-DD.")
        conn = self._writer()
        stored = None
        if source_file is not None:
            name = f"{now.astimezone(self.tz):%Y%m%d-%H%M%S}-{safe_filename(name or source_file.name)}"
            dest = self.files / name
            n = 1
            while dest.exists():
                dest = self.files / f"{Path(name).stem}-{n}{Path(name).suffix}"
                n += 1
            (shutil.move if move else shutil.copy2)(str(source_file), dest)
            stored = f"adjuntos/{dest.name}"
        cur = conn.execute(
            "INSERT INTO entradas(tipo, texto, transcripcion, archivo, fecha_clase, estado, origen, creado)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, text[:MAX_TEXT], (transcript or "").strip()[:MAX_TEXT] or None, stored, class_date,
             "abierta" if kind in OPEN_KINDS else None, origin, timefmt.iso(now)))
        conn.commit()
        return self.entry(int(cur.lastrowid))

    def resolve(self, entry_id: int, now: datetime) -> dict:
        conn = self._writer()
        row = conn.execute("SELECT tipo FROM entradas WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise NotebookError(f"No hay una entrada {entry_id} en el cuaderno de {self.code}.")
        if row["tipo"] not in OPEN_KINDS:
            raise NotebookError("Solo las dudas y los temas débiles se marcan como resueltos.")
        conn.execute("UPDATE entradas SET estado = 'resuelta' WHERE id = ?", (entry_id,))
        conn.commit()
        return self.entry(entry_id)

    # -- reading (anyone) -----------------------------------------------------------------

    def _row(self, r: sqlite3.Row) -> dict:
        return {"id": r["id"], "tipo": r["tipo"], "texto": r["texto"], "transcripcion": r["transcripcion"],
                "archivo": str(self.dir / r["archivo"]) if r["archivo"] else None, "fecha_clase": r["fecha_clase"],
                "estado": r["estado"], "origen": r["origen"], "creado": r["creado"]}

    def entry(self, entry_id: int) -> dict:
        conn = self._connect()
        row = conn.execute("SELECT * FROM entradas WHERE id = ?", (entry_id,)).fetchone() if conn else None
        if row is None:
            raise NotebookError(f"No hay una entrada {entry_id} en el cuaderno de {self.code}.")
        return self._row(row)

    def entries(self, *, kind: str | None = None, since: datetime | None = None, open_only: bool = False,
                limit: int = 30) -> list[dict]:
        """Newest first."""
        conn = self._connect()
        if conn is None:
            return []
        where, params = ["1 = 1"], []
        if kind:
            where.append("tipo = ?")
            params.append(kind)
        if since is not None:
            where.append("creado >= ?")
            params.append(timefmt.iso(since))
        if open_only:
            where.append("estado = 'abierta'")
        rows = conn.execute(f"SELECT * FROM entradas WHERE {' AND '.join(where)} ORDER BY creado DESC, id DESC LIMIT ?",
                            [*params, max(1, min(limit, 200))]).fetchall()
        return [self._row(r) for r in rows]

    def overview(self) -> dict:
        """Counts plus the open doubts and weak topics, for Vinci's overall view."""
        conn = self._connect()
        if conn is None:
            return {"entradas": 0, "dudas_abiertas": [], "temas_debiles": [], "ultima_entrada": None}
        total = conn.execute("SELECT COUNT(*) FROM entradas").fetchone()[0]
        last = conn.execute("SELECT creado FROM entradas ORDER BY creado DESC LIMIT 1").fetchone()
        return {
            "entradas": total,
            "dudas_abiertas": [e["texto"] for e in self.entries(kind="duda", open_only=True, limit=10)],
            "temas_debiles": [e["texto"] for e in self.entries(kind="tema_debil", open_only=True, limit=10)],
            "ultima_entrada": last[0] if last else None,
        }
