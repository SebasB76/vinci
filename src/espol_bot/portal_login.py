"""Connecting the Académico from the chat: a button, a page, one sign-in, and the student's question answered.

    1. The model needs the Académico and has no copy (academic_portal.py): its tool calls `request`, which opens an
       «academico» mailbox in the relay's registry (relay.py) with the chat and the Hermes session it came from.
    2. On the captain's side, `espol-bot whatsapp-rele` (the plugin vinci-whatsapp, every 3 s) sees it and starts
       `espol-bot portal-worker <mailbox>`, a process of its own for this one sign-in.
    3. The worker makes a one-time RSA key, sends the «🎓 Conectar Académico» button (the page docs/academico/, with
       the public half, the relay and the mailbox in its link) and opens the portal's login page.
    4. The page asks for the user name, then for the password and the CAPTCHA the worker publishes through the relay
       (GET /s/<mailbox>). Each answer travels sealed to the worker's key: the relay, the chat and the model see only
       ciphertext. A wrong CAPTCHA or password comes back with the portal's words and a new CAPTCHA.
    5. Signed in, the worker reads every section, saves the copy, tells the chat, and leaves the question for the
       plugin to put back in the same Hermes session (ctx.inject_message): Vinci answers it with the copy.

The key, the credentials and the portal's cookies live only in the worker's memory; it drops them and exits when
the sign-in ends, fails or the button expires. Nothing of them reaches a log, the registry or a file.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aula_core.config import ConfigError
from espol_bot import academic_portal, relay, whatsapp
from espol_bot.config import BotConfig, load_telegram_secrets
from espol_bot.telegram import Telegram, TelegramError
from espol_bot.token_form import OAEP

log = logging.getLogger(__name__)

BUTTON = "🎓 Conectar Académico"
SEALED_RE = re.compile(r"v2\.([A-Za-z0-9_-]{300,})\.([A-Za-z0-9_-]{16})\.([A-Za-z0-9_-]{20,2000})")
TURNS = "turns"
POLL_SECONDS = 1.0
MAX_TRIES = 5
TURN_TTL = timedelta(minutes=10)
RELAY_DOWN_SECONDS = 120  # the relay unreachable this long: give the sign-in up


class LoginError(ConfigError):
    """Why a connection cannot start: no relay, a group chat, no chat to answer in."""


def request(cfg: BotConfig, channel: dict, topic: str, question: str, now: datetime) -> dict:
    """Asks the captain's side for a sign-in whose button goes to this chat and whose answer goes back to this
    Hermes session. `channel`: what the vinci-botones plugin noted before the tool call (canal.json)."""
    platform, session = channel.get("canal", ""), channel.get("sesion", "")
    if channel.get("tipo") not in ("dm", "private", ""):
        raise LoginError("Conectar el Académico se hace por privado: pídele que te escriba en su chat contigo.")
    if not session or platform not in ("whatsapp", "telegram"):
        raise LoginError("No sé en qué chat estamos: el Académico se conecta desde una conversación de Telegram o "
                         "WhatsApp.")
    if platform == "telegram" and cfg.friend:
        raise LoginError("Este Vinci solo conversa por WhatsApp.")
    number = relay.owner(cfg)
    to = number if platform == "whatsapp" else _telegram_chat()
    if not to:
        raise LoginError("No sé a qué chat mandar el botón.")
    path = relay.registry_path(cfg)
    for mailbox, box in relay.opened(path, now).items():  # one sign-in per person: a new button replaces the last
        if box["kind"] == relay.PORTAL and box["number"] == number:
            relay.close(path, mailbox)
    ttl = timedelta(minutes=cfg.portal_login_minutes)
    box = relay.issue(cfg, relay.PORTAL, number, ttl, now, {
        "state": "requested", "chat": {"platform": platform, "to": to}, "friend": cfg.friend,
        "turn": {"session": session, "topic": topic, "question": question[:500]}})
    if box is None:
        raise LoginError("Para conectar el Académico, Vinci necesita su relé (ver «El relé» en el README): sin él, la "
                         "página no puede mostrarte el CAPTCHA.")
    log.info("academico: conexión pedida (%s)", platform)
    return {"minutes": cfg.portal_login_minutes}


def _telegram_chat() -> str:
    try:
        return load_telegram_secrets().user_id
    except ConfigError:
        return ""


def launch(cfg: BotConfig, path: Path, now: datetime) -> None:
    """Starts a worker for each sign-in a tool asked for (the captain's side, from `espol-bot whatsapp-rele`)."""
    for mailbox, box in relay.opened(path, now).items():
        if box["kind"] != relay.PORTAL or box.get("state") != "requested":
            continue
        relay.update(path, mailbox, now, state="starting")
        subprocess.Popen([sys.executable, "-m", "espol_bot", "portal-worker", mailbox], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env={k: v for k, v in os.environ.items() if k not in ("AULA_DATA_DIR", "ESPOL_AMIGO")})
        log.info("academico: proceso de ingreso iniciado")


def unseal(key: rsa.RSAPrivateKey, sealed: str, aad: bytes) -> dict:
    """The page's answer: RSA-OAEP wraps an AES-GCM key, which sealed the JSON bound to this mailbox and step."""
    match = SEALED_RE.fullmatch(sealed or "")
    if not match:
        raise ValueError("not sealed by the page")
    try:
        wrapped, iv, body = (base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)) for p in match.groups())
        plain = AESGCM(key.decrypt(wrapped, OAEP)).decrypt(iv, body, aad)
        data = json.loads(plain)
    except (binascii.Error, ValueError, InvalidTag) as exc:
        raise ValueError("does not open with this key") from exc
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


class Worker:
    """One sign-in, from the button to the answer. The captain's cfg; a friend's copy is saved in their folder."""

    def __init__(self, cfg: BotConfig, mailbox: str, now: datetime):
        self.cfg, self.mailbox, self.now = cfg, mailbox, now
        self.path = relay.registry_path(cfg)
        self.box = relay.opened(self.path, now).get(mailbox)
        self.url = str(relay.read(self.path).get("url") or "")
        self.key_ = relay.key()
        self.seq = 0
        self.portal: academic_portal.Portal | None = None
        self.private: rsa.RSAPrivateKey | None = None
        self.state = "user"
        self.tries = 0
        self.handled = 0

    def status(self, state: str, **extra) -> None:
        self.seq += 1
        payload = {"state": state, "seq": self.seq, "handled": self.handled, **extra}
        try:
            relay.set_status(self.url, self.key_, self.mailbox, payload)
        except relay.RelayError as exc:
            log.warning("academico: %s", exc)

    def say(self, text: str, link: dict | None = None) -> None:
        chat = self.box["chat"]
        try:
            if chat["platform"] == "whatsapp":
                if link:
                    whatsapp.send_link(self.cfg.whatsapp_bridge, whatsapp.jid(chat["to"]), text, link)
                else:
                    whatsapp.send_text(self.cfg.whatsapp_bridge, whatsapp.jid(chat["to"]), text)
                return
            markup = {"inline_keyboard": [[{"text": link["text"], "web_app": {"url": link["url"]}}]]} if link else None
            Telegram(load_telegram_secrets(), api=self.cfg.telegram_api).send(text, reply_markup=markup)
        except (TelegramError, ConfigError) as exc:
            log.warning("academico: no pude escribir en el chat: %s", exc)

    def run(self) -> int:
        if self.box is None or self.box.get("state") != "starting" or not self.url or not self.key_:
            return 0
        relay.update(self.path, self.mailbox, self.now, state="running")
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = self.private.public_key().public_bytes(serialization.Encoding.DER,
                                                        serialization.PublicFormat.SubjectPublicKeyInfo)
        query = urlencode({"k": base64.urlsafe_b64encode(public).decode().rstrip("="), "r": self.url})
        separator = "&" if "?" in self.cfg.portal_form_url else "?"
        link = f"{self.cfg.portal_form_url}{separator}{query}#m={self.mailbox}"
        minutes = self.cfg.portal_login_minutes
        self.say(f"🎓 Para responderte necesito tu Académico de ESPOL. Toca «{BUTTON}», escribe tu usuario y tu "
                 f"contraseña y el código de la imagen.\n🔒 Se cifran en tu celular y solo esta PC los puede abrir; no "
                 f"los guardo, y la copia de tu Académico se queda en la PC. El botón vence en {minutes} min.",
                 {"text": BUTTON, "url": link})
        try:
            self.portal = academic_portal.Portal(self.cfg)
            self.portal.begin()
        except academic_portal.PortalError as exc:
            log.warning("academico: %s", exc)
            self.status("failed", message=f"No pude abrir el Académico: {exc}. Vuelve a pedírselo a Vinci en un rato.")
            self.say(f"⚠️ No pude abrir el Académico ({exc}). Pídemelo otra vez en un rato.")
            return self.finish()
        self.status("user")
        deadline, last_ok = time.monotonic() + minutes * 60, time.monotonic()
        while time.monotonic() < deadline:
            if self.mailbox not in (relay.read(self.path).get("mailboxes") or {}):  # a newer button replaced it
                self.status("replaced", message="Este enlace ya no sirve: usa el último botón que te mandó Vinci.")
                return self.finish()
            try:
                messages = relay.inbox(self.url, self.key_, self.mailbox)
                last_ok = time.monotonic()
            except relay.RelayError as exc:
                if time.monotonic() - last_ok > RELAY_DOWN_SECONDS:
                    log.warning("academico: %s; dejo el ingreso", exc)
                    return self.finish()
                time.sleep(POLL_SECONDS * 3)
                continue
            if messages:
                try:
                    relay.ack(self.url, self.key_, [str(m["id"]) for m in messages])
                except relay.RelayError as exc:
                    log.warning("academico: %s", exc)
            for message in messages:
                done = self.handle(message.get("data") if isinstance(message.get("data"), dict) else {})
                if done:
                    return self.finish()
            time.sleep(POLL_SECONDS)
        self.status("expired", message="El botón venció. Pídele a Vinci uno nuevo.")
        log.info("academico: el botón venció sin ingreso")
        return self.finish()

    def handle(self, body: dict) -> bool:
        """One answer from the page; whether the sign-in is over."""
        step = str(body.get("step") or "")
        if body.get("kind") != relay.PORTAL:
            return False
        if step != self.state:  # a page that fell behind (reloaded, or a retry): show it where things stand
            self.status(self.state, **({"captcha": self.portal.captcha_data_url()} if self.state == "login" else {}))
            return False
        try:
            data = unseal(self.private, str(body.get("sealed") or ""), f"{self.mailbox}:{step}".encode())
        except ValueError:
            log.info("academico: llegó algo que no abre con la llave de este ingreso")
            return False
        n = body.get("n")
        self.handled = n if isinstance(n, int) else self.handled + 1
        self.tries += 1
        try:
            if step == "user":
                return self._user(str(data.get("user") or "").strip())
            return self._login(str(data.get("password") or ""), str(data.get("captcha") or "").strip())
        finally:
            data.clear()

    def _user(self, user: str) -> bool:
        user = user.removesuffix("@espol.edu.ec")
        if not re.fullmatch(r"[A-Za-z0-9._-]{2,60}", user):
            self.status("user", error="Escribe solo tu usuario de ESPOL, sin @espol.edu.ec.")
            return False
        try:
            self.portal.submit_user(user)
        except academic_portal.LoginRefused as exc:
            return self._refused(exc.message, "user")
        except academic_portal.PortalError as exc:
            return self._broken(exc)
        log.info("academico: usuario aceptado; pido contraseña y CAPTCHA")
        self.state, self.tries = "login", 0
        self.status("login", captcha=self.portal.captcha_data_url())
        return False

    def _login(self, password: str, code: str) -> bool:
        if not password or not code:
            self.status("login", error="Falta la contraseña o el código de la imagen.",
                        captcha=self.portal.captcha_data_url())
            return False
        try:
            self.portal.submit_login(password, code)
        except academic_portal.LoginRefused as exc:
            if self.portal.captcha is None:  # the portal went back to the user name
                self.state = "user"
                return self._refused(exc.message, "user")
            return self._refused(exc.message, "login")
        except academic_portal.PortalError as exc:
            return self._broken(exc)
        log.info("academico: ingreso aceptado; leo las secciones")
        self.status("working", message="Entré. Leyendo tu Académico…")
        extracted = self.portal.extract(lambda text: self.status("working", message=text))
        if not extracted["sections"]:
            self.status("failed", message="Entré, pero no pude leer ninguna sección del Académico.")
            self.say("⚠️ Entré a tu Académico, pero no pude leer ninguna sección. Lo reviso y lo intentamos otra vez.")
            return True
        copy = self._save(extracted)
        self.status("done", message="✅ Listo. Ya puedes cerrar esta ventana: Vinci te responde en el chat.")
        period = f" del {copy['period']}" if copy.get("period") else ""
        missing = (f" No pude leer: {', '.join(sorted(extracted['errors']))}." if extracted["errors"] else "")
        self.say(f"✅ Listo: guardé tu Académico{period} ({academic_portal.summary(copy)}).{missing} Ya te respondo.")
        self._queue_turn()
        return True

    def _refused(self, message: str, state: str) -> bool:
        log.info("academico: el portal no aceptó el paso %s", state)
        if self.tries >= MAX_TRIES:
            self.status("failed", message=f"{message} Fueron {MAX_TRIES} intentos: pídele a Vinci un botón nuevo.")
            return True
        extra = {"captcha": self.portal.captcha_data_url()} if state == "login" and self.portal.captcha else {}
        self.status(state, error=message, **extra)
        return False

    def _broken(self, exc: Exception) -> bool:
        log.warning("academico: %s", exc)
        self.status("failed", message=f"El Académico falló: {exc}. Pídele a Vinci un botón nuevo en un rato.")
        return True

    def _save(self, extracted: dict) -> dict:
        slug = self.box.get("friend")
        if not slug:
            return academic_portal.save(self.cfg, extracted, self.now)
        from espol_bot import amigos
        friend = next((f for f in amigos.load(self.cfg) if f.slug == slug), None)
        if friend is None:
            raise ConfigError("ese amigo ya no está")
        with amigos.scope(self.cfg, friend) as fcfg:
            return academic_portal.save(fcfg, extracted, self.now)

    def _queue_turn(self) -> None:
        """The question, for the plugin to put back in the Hermes session it came from."""
        turn = self.box.get("turn") or {}
        folder = self.path.parent / TURNS
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        question = turn.get("question") or "lo que te pregunté del Académico"
        text = f"Ya conecté mi Académico desde tu botón. Contéstame ahora lo que te pregunté: «{question}»"
        tmp = folder / f".{secrets.token_hex(8)}.tmp"
        tmp.write_text(json.dumps({"session": turn.get("session"), "text": text,
                                   "expires": time.time() + TURN_TTL.total_seconds()}, ensure_ascii=False),
                       encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, folder / f"{tmp.stem.lstrip('.')}.json")

    def finish(self) -> int:
        relay.close(self.path, self.mailbox)
        if self.portal is not None:
            self.portal.close()
        self.portal = self.private = None
        return 0


def run_worker(cfg: BotConfig, mailbox: str, now: datetime) -> int:
    worker = Worker(cfg, mailbox, now)
    try:
        return worker.run()
    except Exception:  # its output goes nowhere: leave a trace, and drop the session all the same
        log.exception("academico: el proceso de ingreso falló")
        worker.status("failed", message="Algo falló de mi lado. Pídele a Vinci un botón nuevo en un rato.")
        return worker.finish() or 1
