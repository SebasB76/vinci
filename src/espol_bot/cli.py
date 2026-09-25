"""`espol-bot`: the Telegram side of the academic bot.

    espol-bot sondeo              poll + notify (Hermes no-agent cron, every N minutes)
    espol-bot resumen             daily week summary (Hermes no-agent cron, at resumen_diario)
    espol-bot resumen --imprimir  print the summary instead of sending it (/semana)
    espol-bot probar              send a test message to your Telegram
    espol-bot hermes-perfil       create/update the Hermes profile (called by setup.sh)

On success `sondeo` and `resumen` print nothing, so Hermes' no-agent cron stays
silent; the bot delivers its own messages. An unexpected crash exits non-zero and
Hermes forwards the error to the captain's Telegram.
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys

from aula_core import Aula
from aula_core.config import ConfigError, load_config
from aula_core.store import file_lock
from espol_bot.config import load_bot_config, load_telegram_secrets
from espol_bot.poller import Bot
from espol_bot.telegram import Telegram, TelegramError


def _logging(cfg) -> None:
    cfg.core.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=cfg.core.data_dir / "bot.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="espol-bot", description="Bot académico de ESPOL para Telegram.")
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="comando")
    sub.add_parser("sondeo", help="revisar el aula virtual y notificar")
    p = sub.add_parser("resumen", help="enviar el resumen de la semana")
    p.add_argument("--imprimir", action="store_true", help="solo imprimir (no enviar ni sincronizar)")
    sub.add_parser("probar", help="enviar un mensaje de prueba a tu Telegram")
    p = sub.add_parser("hermes-perfil", help="crear o actualizar el perfil de Hermes (lo usa setup.sh)")
    p.add_argument("--hermes", default=None, help="ruta al comando hermes")
    args = parser.parse_args(argv)

    try:
        cfg = load_bot_config(load_config())
        if args.cmd == "hermes-perfil":
            from espol_bot import hermes_setup
            return hermes_setup.provision(cfg, hermes_bin=args.hermes)
        _logging(cfg)
        if args.cmd == "resumen" and args.imprimir:
            aula = Aula(cfg.core)
            print(plain(Bot(cfg, telegram=None, aula=aula).summary_text(aula.now())))  # type: ignore[arg-type]
            return 0
        telegram = Telegram(load_telegram_secrets())
        if args.cmd == "probar":
            telegram.send("✅ <b>Prueba</b>: el bot académico puede escribirte por Telegram.")
            print("Mensaje de prueba enviado.")
            return 0
        with file_lock(cfg.core.data_dir, "bot.lock"):
            bot = Bot(cfg, telegram)
            result = bot.poll() if args.cmd == "sondeo" else bot.summary()
        logging.info("%s: %d mensajes, %d eventos, %d recordatorios, error=%s",
                     args.cmd, len(result.sent), result.events, result.reminders, result.error)
        return 0
    except (ConfigError, TelegramError) as exc:
        print(f"Bot académico: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
