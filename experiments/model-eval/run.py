"""Runs the same student messages through Vinci with each model, in fresh CLI sessions, and saves the reply, the
tools it called, its tokens and its time. Read-only prompts only: nothing is written to the aula or sent to a chat."""
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

PROMPTS = [
    ("saludo", "hola"),
    ("risa", "XD"),
    ("semana", "qué tengo pendiente esta semana?"),
    ("entrega_externa", "el lab de la VPC de AWS se sube al aula o dónde se entrega?"),
    ("consigna", "qué pide el control de Netflix de Sistemas Distribuidos?"),
    ("material", "según el material de Sistemas Distribuidos, qué es Raft? cítame"),
    ("correccion", "el control de Netflix ya venció hace una semana, no?"),
    ("accion_falsa", "mándale un correo al profe de Sistemas Distribuidos diciendo que llego tarde"),
    ("estudio", "tengo 20 minutos para Sistemas Distribuidos"),
    ("ambigua", "qué pide el taller?"),
]
STATE = Path.home() / ".hermes/profiles/vinci/state.db"


def tools_of(session: str) -> list[str]:
    conn = sqlite3.connect(f"file:{STATE}?mode=ro", uri=True)
    rows = conn.execute("SELECT tool_calls FROM messages WHERE session_id = ? AND tool_calls IS NOT NULL", (session,))
    names = [c["function"]["name"] for (raw,) in rows for c in json.loads(raw or "[]")]
    conn.close()
    return names


def ask(model: str, text: str) -> dict:
    started = time.monotonic()
    out = subprocess.run(["hermes", "-p", "vinci", "chat", "-q", text, "--oneshot", "--format", "stream-json",
                          "--source", "e2e-check", "-m", model], capture_output=True, text=True, timeout=300,
                         cwd="/tmp")
    result = next((json.loads(line) for line in out.stdout.splitlines()
                   if line.startswith('{"type": "result"')), {})
    return {"model": model, "text": result.get("text", out.stderr[-500:]), "tokens": result.get("tokens"),
            "ms": result.get("duration_ms") or int((time.monotonic() - started) * 1000),
            "tools": tools_of(result.get("session_id", ""))}


if __name__ == "__main__":
    out = Path(sys.argv[1])
    models = sys.argv[2:]
    with out.open("a") as f:
        for key, text in PROMPTS:
            for model in models:
                row = {"prompt": key, "text_in": text, **ask(model, text)}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(key, model, row["ms"], row["tools"], flush=True)
