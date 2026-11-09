"""Polls and the 7:00 summary outside Hermes: `espol-bot sondeo --todos --servicio`, run by the container's s6
service `vinci-sondeo` (deploy/s6/vinci-sondeo).

Hermes cron ran every profile's poll as a thread of the gateway, all at the same minute, so the readings of every
aula (and their OCR) piled up in memory at once. This loop runs apart from the gateway: at each poll slot, the
captain's poll and then each active friend's, one at a time, each a child process with its own environment and a
time limit (maintenance_service.run_one); at the summary time, the same with the summary, which polls first. A
summary missed by a restart goes out at the next slot within SUMMARY_WINDOW; Bot.summary sends it once a day.
A pass also runs BOOT_WAIT after each start, and a pass that runs past a slot starts the next one at once: with one
person after another a pass can last over 10 minutes, and waiting for the following slot left 30-minute holes.

With VINCI_POLL_SERVICE set (the Dockerfile sets it) hermes_setup removes the `*-sondeo` and `*-resumen` crons;
without it (a PC install) Hermes cron keeps running them.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta

from espol_bot import maintenance_service
from espol_bot.config import BotConfig

log = logging.getLogger(__name__)

ENV = "VINCI_POLL_SERVICE"
SERVICE = "vinci-sondeo"
LIMIT = 600           # seconds per person: a Canvas sync plus OCR_MINUTES of scanned pages
OCR_MINUTES = 3       # per person and pass (poller.OCR_MINUTES alone): a scanned book still gets read over a few polls
SUMMARY_WINDOW = timedelta(hours=2)
BOOT_WAIT = timedelta(minutes=3)  # the gateway's WhatsApp bridge is up about a minute after the container starts


def enabled() -> bool:
    return os.environ.get(ENV, "") not in ("", "0")


def run_all(cfg: BotConfig, command: str, limit: int = LIMIT) -> list[maintenance_service.Run]:
    return maintenance_service.run_all(cfg, limit, command, {"VINCI_OCR_MINUTES": str(OCR_MINUTES)})


def next_poll(now: datetime, every: int, summary_minute: int) -> datetime:
    """The next slot of hermes_setup.poll_schedule: every `every` minutes on the clock, half a period away from the
    summary; a period that does not divide the hour counts from now."""
    if 60 % every:
        return now + timedelta(minutes=every)
    first = (summary_minute + every // 2) % every
    slot = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while (slot.minute - first) % every:
        slot += timedelta(minutes=1)
    return slot


def summary_start(now: datetime, cfg: BotConfig) -> datetime:
    return now.replace(hour=cfg.summary_time.hour, minute=cfg.summary_time.minute, second=0, microsecond=0)


def summary_due(now: datetime, cfg: BotConfig, done: date | None) -> bool:
    start = summary_start(now, cfg)
    return done != now.date() and start <= now < start + SUMMARY_WINDOW


def next_wake(now: datetime, cfg: BotConfig) -> datetime:
    summary = summary_start(now, cfg)
    if summary <= now:
        summary += timedelta(days=1)
    return min(next_poll(now, cfg.poll_minutes, cfg.summary_time.minute), summary)


def serve(cfg: BotConfig, limit: int) -> None:
    """A pass BOOT_WAIT after start (a Redeploy may have cost a slot), then one at each slot; a pass that ends past
    its next slot is followed by another at once."""
    tz = cfg.core.tz
    done: date | None = None
    due = datetime.now(tz) + BOOT_WAIT
    while True:
        time.sleep(max(0.0, (due - datetime.now(tz)).total_seconds()))
        now = datetime.now(tz)
        due = next_wake(now, cfg) + timedelta(seconds=1)  # past the slot, never just before
        command = "resumen" if summary_due(now, cfg, done) else "sondeo"
        try:
            print(maintenance_service.summary(run_all(cfg, command, limit), command), flush=True)
        except Exception:  # noqa: BLE001 (the loop is what keeps every alert coming)
            log.exception("%s --todos: falló una pasada", command)
        if command == "resumen":
            done = now.date()
