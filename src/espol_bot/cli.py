"""`espol-bot`: the plumbing behind Vinci and the subject bots (Hermes calls it; you rarely do).

    espol-bot sondeo                 poll + notify (Vinci's no-agent cron, every N minutes), then OCR
                                     of the scanned pages still waiting, for a few minutes
    espol-bot resumen                daily week summary (Vinci's no-agent cron, at resumen_diario)
    espol-bot mantenimiento          renew Canvas access and refresh token-free feeds (no model)
    espol-bot resembrar              securely replace a broken Canvas token from a hidden prompt
    espol-bot feeds                  securely save the iCal and announcement feed URLs
    espol-bot probar                 send a test message from Vinci to your Telegram
    espol-bot doctor                 system health: last poll and sync, token chain, feeds (read-only;
                                     exits 1 when something is broken)
    espol-bot hermes-perfil          create/update the Hermes profiles (called by setup.sh)
    espol-bot agenda --curso CÓDIGO  a subject bot's cron gate: prints {"wakeAgent": false} unless a
                                     class brief is due or Vinci handed something over
    espol-bot mcp vinci|materia      the tools of Vinci or of one subject bot (stdio MCP server)
    espol-bot boton <datos>          what one of Vinci's inline buttons does (the plugin calls it)
    espol-bot bot-creado <id>        a bot the captain created for Vinci to manage: fetch its token,
                                     store it and provision its profile (the plugin calls it)
    espol-bot token                  the same for a token read from stdin (BotFather's reply that
                                     the captain forwarded; the plugin deleted it from the chat)
    espol-bot saludo [--curso CÓDIGO]
                                     a bot's answer to /start, which Hermes ignores (the plugin calls it)
    espol-bot estado                 the same health report for Vinci's /estado (the plugin calls it)
    espol-bot canvas-form            Vinci's answer to /token: a one-time key and the button of the page that
                                     encrypts a new Canvas token on the phone (the plugin calls it)
    espol-bot canvas-submit          that page's ciphertext read from stdin: decrypt it and reseed the token
                                     chain (the plugin calls it)
    espol-bot pagina --curso CÓDIGO <archivo_id> <página>
                                     a page of the subject's PDF as a JPEG, for the plugin's ver_pagina
    espol-bot quiz-respuesta --curso CÓDIGO <poll_id> <opción>
                                     the captain's vote in a quiz poll; after the last question, the
                                     score to send (the plugin calls it)
    espol-bot citas [--curso CÓDIGO] an answer read from stdin with its citations checked against the pages
                                     that bot was shown (the plugin runs it before an answer is sent)
    espol-bot notes                  read the captain's notes folder: each note's subject, its //vinci
                                     questions and, once its class is over, its summary (Vinci's no-agent
                                     cron, every minute)
    espol-bot foto --curso CÓDIGO <entrada>
                                     a photo of the subject's notebook as a JPEG, for the plugin's ver_foto

On success `sondeo` and `resumen` print nothing, so Hermes' no-agent cron stays
silent; the bot delivers its own messages. An unexpected crash exits non-zero and
Hermes forwards the error to the captain's Telegram.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from pathlib import Path

from aula_core.config import ConfigError, load_config, now_utc
from aula_core.store import file_lock
from espol_bot.config import load_bot_config, load_telegram_secrets
from espol_bot.telegram import Telegram, TelegramError, prefer_ipv4


def _logging(cfg) -> None:
    cfg.core.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=cfg.core.data_dir / "bot.log", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _agenda(cfg, code: str) -> int:
    from espol_bot import agenda
    try:
        print(agenda.run(cfg, code.upper(), now_utc()))
    except Exception:  # a broken gate must never wake the model or spam the chat
        logging.exception("agenda %s", code)
        print(agenda.SKIP)
    return 0


def _greeting(cfg, code: str | None) -> dict:
    from espol_bot import agenda, horario, materias, messages
    if not code:
        return {"respuesta": messages.vinci_greeting()}
    subject = materias.by_code(materias.load(cfg.core), code)
    if subject is None:
        return {"respuesta": None}
    now = now_utc()
    return {"respuesta": messages.subject_greeting(
        subject.display, subject.name, subject.code, cfg.brief_minutes, horario.path(cfg.core).exists(),
        agenda.next_session(cfg, subject, now), cfg.core.tz, now)}


def _mcp(cfg, which: str, code: str | None, hermes_home: str | None) -> int:
    from espol_bot import herramientas
    from espol_bot.mcp_server import Server
    ctx = herramientas.Ctx(cfg, Path(hermes_home) if hermes_home else None, code.upper() if code else None)
    if which == "vinci":
        server = Server("vinci", "1.0", herramientas.vinci_tools(ctx),
                        "Herramientas de Vinci: aula virtual (solo lectura) de todas las materias, cuadernos "
                        "(solo lectura), horario y traspasos a los bots de materia.")
    else:
        if not code:
            raise ConfigError("mcp materia necesita --curso CÓDIGO")
        server = Server("materia", "1.0", herramientas.subject_tools(ctx),
                        f"Herramientas del bot de {code.upper()}: solo esa materia y su cuaderno.")
    logging.info("mcp %s%s: iniciado", which, f" {code}" if code else "")
    return server.serve()


def _health(cfg, *, telegram: bool) -> int:
    from espol_bot import health
    now = now_utc()
    conn = health.open_readonly(cfg.core.db_path)
    try:
        found = health.checks(cfg, conn, now)
    finally:
        if conn is not None:
            conn.close()
    if telegram:
        print(json.dumps({"respuesta": health.telegram_report(found, now, cfg.core.tz)}, ensure_ascii=False))
        return 0
    print(health.terminal_report(found, now, cfg.core.tz))
    return 1 if any(c.level == health.FAIL for c in found) else 0


def _reseed(cfg, *, from_stdin: bool = False) -> int:
    from espol_bot.token_renewal import RenewalError, reseed
    token = sys.stdin.readline() if from_stdin else getpass.getpass("Token nuevo de Canvas (no se mostrará): ")
    try:
        result = reseed(cfg.core, token, now_utc())
    except RenewalError as exc:
        print(f"Vinci: {exc}", file=sys.stderr)
        return 1
    finally:
        token = ""
    if result.chain_cut:
        print("Vinci: Canvas aceptó el token pero lo rechazó al renovarlo; crea otro y vuelve a resembrar.",
              file=sys.stderr)
        return 1
    if result.renewal_error:
        print(f"Token verificado y guardado. La renovación automática falló esta vez ({result.renewal_error}); "
              "el mantenimiento la reintentará solo.")
        return 0
    suffix = " y su sucesor automático ya quedó activo" if result.renewed else ""
    print(f"Token verificado y guardado{suffix}. La cadena de renovación volvió a funcionar.")
    return 0


def _configure_feeds(cfg) -> int:
    from aula_core import feeds
    calendar = getpass.getpass("URL de Fuente del calendario (iCal; no se mostrará): ").strip()
    raw = getpass.getpass("URLs RSS/Atom de Anuncios, separadas por espacios (no se mostrarán): ").strip()
    try:
        feeds.configure(calendar, raw.split(), cfg.core)
    except feeds.FeedError as exc:
        print(f"Vinci: {exc}", file=sys.stderr)
        return 1
    print(f"Feeds guardados de forma privada: calendario y {len(raw.split())} feed(s) de anuncios.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="espol-bot", description="Vinci y los bots de materia de ESPOL.")
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="comando")
    sub.add_parser("sondeo", help="revisar el aula virtual y notificar")
    sub.add_parser("resumen", help="enviar el resumen de la semana")
    sub.add_parser("mantenimiento", help="renovar el token y actualizar los feeds, sin usar el modelo")
    p = sub.add_parser("resembrar", help="guardar un token nuevo desde una entrada oculta y reactivar la renovación")
    p.add_argument("--stdin", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("feeds", help="guardar de forma privada los feeds iCal y RSS/Atom")
    sub.add_parser("probar", help="enviar un mensaje de prueba a tu Telegram")
    sub.add_parser("dashboard", help="poner ya el dashboard al día en el botón de menú del chat de Vinci")
    sub.add_parser("doctor", help="ver la salud del sistema: sondeo, sincronización, token y feeds (solo lectura)")
    p = sub.add_parser("hermes-perfil", help="crear o actualizar los perfiles de Hermes (lo usa setup.sh)")
    p.add_argument("--hermes", default=None, help="ruta al comando hermes")
    p = sub.add_parser("agenda", help="compuerta del cron de un bot de materia")
    p.add_argument("--curso", required=True, help="código de la materia, ej. ESTG1034")
    p = sub.add_parser("mcp", help="servidor MCP con las herramientas de Vinci o de un bot de materia")
    p.add_argument("bot", choices=["vinci", "materia"])
    p.add_argument("--curso", default=None, help="código de la materia (para «materia»)")
    p.add_argument("--hermes-home", default=None, help="carpeta del perfil de Hermes del bot")
    p = sub.add_parser("boton", help="procesar un botón de Vinci (lo usa el plugin vinci-botones)")
    p.add_argument("datos")
    p = sub.add_parser("bot-creado", help="configurar un bot creado para Vinci (lo usa el plugin vinci-botones)")
    p.add_argument("bot_id", type=int)
    sub.add_parser("token", help="configurar el bot de un token leído por stdin (lo usa el plugin vinci-botones)")
    p = sub.add_parser("saludo", help="la respuesta de un bot a /start (la usa el plugin vinci-botones)")
    p.add_argument("--curso", default=None, help="código de la materia (vacío: Vinci)")
    sub.add_parser("estado", help="la respuesta de Vinci a /estado (la usa el plugin vinci-botones)")
    sub.add_parser("canvas-form", help="la respuesta de Vinci a /token (la usa el plugin vinci-botones)")
    sub.add_parser("canvas-submit", help="el token cifrado por el formulario de /token, leído por stdin (lo usa el "
                                         "plugin vinci-botones)")
    p = sub.add_parser("pagina", help="una página de un PDF como imagen (la usa ver_pagina, del plugin vinci-botones)")
    p.add_argument("--curso", required=True, help="código de la materia")
    p.add_argument("archivo_id", type=int)
    p.add_argument("pagina", type=int)
    sub.add_parser("notes", help="leer tu carpeta de apuntes y pasárselos a los bots de materia (cron de Vinci)")
    p = sub.add_parser("foto", help="una foto del cuaderno como imagen (la usa ver_foto, del plugin vinci-botones)")
    p.add_argument("--curso", required=True, help="código de la materia")
    p.add_argument("entrada", type=int)
    p = sub.add_parser("quiz-respuesta", help="una respuesta a un quiz (la usa el plugin vinci-botones)")
    p.add_argument("--curso", required=True, help="código de la materia")
    p.add_argument("poll_id")
    p.add_argument("opciones", type=int, nargs="*")
    p = sub.add_parser("citas", help="comprobar las citas de una respuesta leída por stdin (la usa el plugin "
                                     "vinci-botones)")
    p.add_argument("--curso", default=None, help="código de la materia (vacío: Vinci)")
    args = parser.parse_args(argv)

    prefer_ipv4()
    try:
        cfg = load_bot_config(load_config())
        if args.cmd == "hermes-perfil":
            from espol_bot import hermes_setup
            return hermes_setup.provision(cfg, hermes_bin=args.hermes)
        if args.cmd in ("doctor", "estado"):
            return _health(cfg, telegram=args.cmd == "estado")
        _logging(cfg)
        if args.cmd == "resembrar":
            return _reseed(cfg, from_stdin=args.stdin)
        if args.cmd == "feeds":
            return _configure_feeds(cfg)
        if args.cmd == "agenda":
            return _agenda(cfg, args.curso)
        if args.cmd == "mcp":
            return _mcp(cfg, args.bot, args.curso, args.hermes_home)
        if args.cmd == "boton":
            from espol_bot import botones
            print(json.dumps(botones.handle(cfg, args.datos, now_utc()), ensure_ascii=False))
            return 0
        if args.cmd in ("canvas-form", "canvas-submit"):
            from espol_bot import token_form
            result = (token_form.open_form(cfg, now_utc()) if args.cmd == "canvas-form"
                      else token_form.submit(cfg, sys.stdin.read(), now_utc()))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.cmd == "saludo":
            print(json.dumps(_greeting(cfg, args.curso), ensure_ascii=False))
            return 0
        if args.cmd == "pagina":
            from espol_bot import herramientas
            from espol_bot.mcp_server import ToolError
            try:
                result = herramientas.page_image(cfg, args.curso, args.archivo_id, args.pagina)
            except ToolError as exc:
                result = {"error": str(exc)}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.cmd == "notes":
            from espol_bot import notes
            notes.scan(cfg, now_utc())
            return 0
        if args.cmd == "foto":
            from espol_bot import herramientas
            from espol_bot.mcp_server import ToolError
            try:
                result = herramientas.entry_image(cfg, args.curso, args.entrada)
            except ToolError as exc:
                result = {"error": str(exc)}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.cmd == "quiz-respuesta":
            from espol_bot import quiz
            answer = quiz.record_answer(cfg.core, args.curso, args.poll_id, args.opciones, now_utc())
            print(json.dumps({"respuesta": answer}, ensure_ascii=False))
            return 0
        if args.cmd == "citas":
            from espol_bot import herramientas
            from espol_bot.mcp_server import ToolError
            try:
                result = herramientas.check_citations(cfg, args.curso, sys.stdin.read())
            except ToolError as exc:  # a subject no longer in materias.toml: the answer goes as it is
                logging.warning("citas: %s", exc)
                result = {}
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.cmd in ("bot-creado", "token"):
            from espol_bot import equipo
            result = (equipo.managed_bot_created(cfg, args.bot_id) if args.cmd == "bot-creado"
                      else equipo.register_token(cfg, sys.stdin.read()))
            logging.info("%s: materia=%s", args.cmd, result.get("materia"))
            print(json.dumps(result, ensure_ascii=False))
            return 0
        from espol_bot.poller import Bot
        telegram = Telegram(load_telegram_secrets(), api=cfg.telegram_api)
        if args.cmd == "probar":
            telegram.send("✅ <b>Prueba</b>: Vinci puede escribirte por Telegram.")
            print("Mensaje de prueba enviado.")
            if not telegram.get_me().get("can_manage_bots"):
                print("💡 Para que Vinci cree los bots de materia con un toque: en @BotFather abre la Mini App, "
                      "elige a Vinci y activa la opción para que gestione otros bots. (Sin eso, Vinci te guía "
                      "paso a paso con /newbot.)")
            return 0
        with file_lock(cfg.core.data_dir, "bot.lock"):
            bot = Bot(cfg, telegram)
            if args.cmd == "dashboard":
                from espol_bot import dashboard
                url = dashboard.publish(bot.conn, cfg, telegram, bot.team, bot.aula.now(), force=True)
                print(f"Botón «{dashboard.BUTTON}» al día ({len(url)} caracteres en su enlace)." if url else
                      "El dashboard está apagado: dashboard.url está vacío en config.toml.")
                return 0
            if args.cmd == "sondeo":
                result = bot.poll()
            elif args.cmd == "mantenimiento":
                result = bot.maintenance()
            else:
                result = bot.summary()
        logging.info("%s: %d mensajes, %d eventos, %d recordatorios, error=%s",
                     args.cmd, len(result.sent), result.events, result.reminders, result.error)
        if args.cmd == "sondeo":  # after bot.lock: the token renewal never waits for a scanned book
            bot.read_scans()
        return 0
    except (ConfigError, TelegramError) as exc:
        if args.cmd == "agenda":  # never wake the model over a config problem
            print('{"wakeAgent": false}')
        print(f"Vinci: {exc}", file=sys.stderr)
        return 0 if args.cmd == "agenda" else 1


if __name__ == "__main__":
    raise SystemExit(main())
