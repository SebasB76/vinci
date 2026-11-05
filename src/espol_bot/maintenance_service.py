"""Token renewal outside Hermes: `espol-bot mantenimiento --todos`, run by the container's s6 service
`vinci-mantenimiento` (deploy/s6/vinci-mantenimiento).

ESPOL's Canvas kills a personal token after an hour, so each Vinci's maintenance (poller.Bot.maintenance) renews it
every 10 minutes. Hermes cron lives inside the gateway, so a frozen gateway used to cut every chain. This loop runs
apart from it: every 10 minutes, the captain's maintenance and then each active friend's, one at a time (no memory
burst), each a child process with its own environment and a time limit, so one that fails or hangs never stops the
others. Each child takes its own bot.lock, like the poll and the token form. A message it cannot send (the WhatsApp
bridge belongs to the gateway) is retried by a later run.

With VINCI_MAINTENANCE_SERVICE set (the Dockerfile sets it) hermes_setup removes the `*-mantenimiento` crons; without
it (a PC install) Hermes cron keeps running each maintenance.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

ENV = "VINCI_MAINTENANCE_SERVICE"
SERVICE = "vinci-mantenimiento"
EVERY = 10    # minutes; health.MAINTENANCE_LATE counts on it
OFFSET = 2    # minute of each slot (:02, :12, …), as the Hermes cron ran it: apart from the polls
LIMIT = 300   # seconds per person: the poll holds bot.lock while it reads the aula, and the bridge may hang


def enabled() -> bool:
    return os.environ.get(ENV, "") not in ("", "0")


@dataclass
class Run:
    who: str
    seconds: float
    error: str | None = None


def targets(cfg: BotConfig) -> list[tuple[str, dict[str, str]]]:
    """The captain first, then each active friend (read on every pass: one added or removed counts at once)."""
    from espol_bot import amigos
    try:
        friends = amigos.active(cfg)
    except (OSError, ValueError, TypeError) as exc:
        log.error("mantenimiento --todos: no pude leer la lista de amigos: %s", exc)
        friends = []
    return [("capitán", {})] + [(f.slug, amigos.env(cfg, f)) for f in friends]


def run_one(who: str, env: dict[str, str], limit: int) -> Run:
    started = time.monotonic()
    error = None
    try:
        proc = subprocess.run([sys.executable, "-m", "espol_bot.cli", "mantenimiento"], env={**os.environ, **env},
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=limit)
        if proc.returncode != 0:
            last = (proc.stderr.strip().splitlines() or proc.stdout.strip().splitlines() or [""])[-1]
            error = f"salió con {proc.returncode}: {last[:200]}"
    except subprocess.TimeoutExpired:  # run() killed it; its bot.lock and any half-made token go with it
        error = f"se pasó de {limit} s y lo corté"
    except OSError as exc:
        error = str(exc)
    return Run(who, time.monotonic() - started, error)


def run_all(cfg: BotConfig, limit: int = LIMIT) -> list[Run]:
    runs = []
    for who, env in targets(cfg):
        run = run_one(who, env, limit)
        if run.error:
            log.error("mantenimiento de %s: %s", who, run.error)
        runs.append(run)
    log.info("%s", summary(runs))
    return runs


def summary(runs: list[Run]) -> str:
    return "mantenimiento --todos: " + " · ".join(
        f"{r.who} ✗ {r.error}" if r.error else f"{r.who} ✓ {r.seconds:.0f} s" for r in runs)


def seconds_to_next(now: datetime, every: int) -> float:
    slot = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while (slot.minute - OFFSET) % every:
        slot += timedelta(minutes=1)
    return (slot - now).total_seconds()


def serve(cfg: BotConfig, every: int, limit: int) -> None:
    """Runs a pass at once (a restart may have taken a while), then at each slot. A pass that overruns a slot skips
    it rather than queueing passes."""
    while True:
        try:
            print(summary(run_all(cfg, limit)), flush=True)
        except Exception:  # noqa: BLE001 (the loop is what keeps every chain alive)
            log.exception("mantenimiento --todos: falló una pasada")
        time.sleep(seconds_to_next(datetime.now(), every))
