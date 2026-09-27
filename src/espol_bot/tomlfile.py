"""Writes the small hand-editable TOML files of the data folder (materias.toml,
horario.toml): a comment header plus a list of flat tables. tomllib reads them back."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    # A JSON string is a valid TOML basic string (same escapes).
    return json.dumps(str(value), ensure_ascii=False)


def render(header: str, table: str, rows: list[dict]) -> str:
    lines = [f"# {line}".rstrip() if line else "#" for line in header.strip("\n").splitlines()]
    for row in rows:
        lines += ["", f"[[{table}]]"]
        lines += [f"{key} = {_value(value)}" for key, value in row.items() if value is not None]
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
