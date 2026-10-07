"""/token: the captain hands Vinci a new Canvas token from Telegram without Telegram ever reading it.

Each /token makes a one-time RSA key pair. Its public half rides in the URL of a Mini App keyboard
button (docs/token/, a static page on GitHub Pages); the page encrypts the token on the phone with
RSA-OAEP and sends back only the ciphertext, as the button's web_app_data. The private half waits in
secrets.env until a ciphertext opens with it or the form expires, and is then deleted: a ciphertext left
in the chat history opens nothing later, and each new form replaces the pending key.

When Canvas refuses the token, the poller sends this same form on its own, valid for AUTO_FORM_TTL: the
captain may only read it hours later, and does not have to type /token.

A friend's Vinci (amigos.py) talks on WhatsApp, which has no Mini Apps: its form is a plain link (?w=1) whose page
shows the ciphertext to copy, and the friend pastes it in the chat; the plugin of the default profile takes it out
of the chat before Hermes sees it (`espol-bot amigo token`).

The plugin `vinci-botones` runs `espol-bot canvas-form` for /token and `espol-bot canvas-submit` (the
ciphertext on stdin) for the button's data, before Hermes sees either; the token never reaches the
model, a session log or bot.log.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from aula_core import timefmt
from aula_core.config import load_secret_values, update_secret_values
from aula_core.store import connect, delete_meta, file_lock, get_meta, set_meta
from espol_bot.config import BotConfig
from espol_bot.messages import e
from espol_bot.token_renewal import RenewalError, reseed

log = logging.getLogger(__name__)

KEY = "TOKEN_FORM_KEY"
EXPIRES = "token_form_expires_at"
FORM_TTL = timedelta(minutes=15)
AUTO_FORM_TTL = timedelta(hours=24)
PREFIX = "v1."  # what the page puts before the base64url ciphertext
BUTTON = "🔑 Pegar token"
# WebCrypto's RSA-OAEP with hash SHA-256 also uses SHA-256 for MGF1.
OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


class FormError(Exception):
    """The data cannot become a token: expired form, a stale button, or something that is not the page's."""


def open_form(cfg: BotConfig, now: datetime, intro: str = "", *, whatsapp: bool = False) -> dict:
    """A fresh one-time key and the message with the button that opens the page with its public half (on WhatsApp,
    which has no Mini Apps, a link to the page in its copy mode)."""
    conn = connect(cfg.core.db_path)
    try:
        with file_lock(cfg.core.data_dir, "bot.lock"):  # the renewal rewrites secrets.env under it too
            return new_form(cfg, conn, now, intro, whatsapp=whatsapp)
    finally:
        conn.close()


def new_form(cfg: BotConfig, conn, now: datetime, intro: str = "", ttl: timedelta = FORM_TTL, *,
             whatsapp: bool = False) -> dict:
    """open_form for a caller that already holds bot.lock (flock would block on a second open in this process)."""
    whatsapp = whatsapp or bool(cfg.friend)  # a friend's Vinci talks only on WhatsApp
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.DER,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    update_secret_values({KEY: base64.b64encode(private).decode()})
    set_meta(conn, EXPIRES, timefmt.iso(now + ttl))
    conn.commit()
    log.info("canvas-form: formulario abierto")
    separator = "&" if "?" in cfg.token_form_url else "?"
    query = {"k": base64.urlsafe_b64encode(public).decode().rstrip("="), **({"w": "1"} if whatsapp else {})}
    url = cfg.token_form_url + separator + urlencode(query)
    if whatsapp:
        text = (f"{intro}🔑 <b>Tu token del aula</b>\n"
                f"1. Abre <a href=\"{e(cfg.core.canvas_url)}/profile/settings\">tu perfil del aula</a> y toca "
                "«+ Nuevo token de acceso» (en «Propósito» pon Vinci).\n"
                f"2. Copia el token y abre esta página: {e(url)}\n"
                "3. Pega el token ahí, toca «Cifrar» y pega aquí el texto que te da (empieza con v1.).\n"
                "🔒 Se cifra en tu celular: por este chat solo pasa un texto ilegible que únicamente la PC de Vinci "
                f"puede abrir. El enlace sirve una vez y vence en {_duration(ttl)}.")
        return {"respuesta": text, "url": url}
    text = (f"{intro}🔑 <b>Token nuevo de Canvas</b>\n"
            f"1. Abre <a href=\"{e(cfg.core.canvas_url)}/profile/settings\">tu perfil del aula</a> y toca "
            "«+ Nuevo token de acceso».\n"
            f"2. Copia el token, toca «{BUTTON}» aquí abajo y pégalo.\n"
            "🔒 Se cifra en tu celular antes de salir: Telegram solo lleva un texto ilegible que únicamente tu PC "
            f"puede abrir. El formulario sirve una vez y vence en {_duration(ttl)}.")
    return {"respuesta": text, "web_app_button": {"text": BUTTON, "url": url}}


def pending(conn, now: datetime) -> bool:
    """Whether a form is still waiting for its ciphertext (from /token or sent by the poller)."""
    expires = timefmt.parse(get_meta(conn, EXPIRES))
    return bool(load_secret_values().get(KEY)) and expires is not None and now < expires


def keyboard(button: dict) -> dict:
    """The Bot API reply markup for a form's button: only a keyboard button may send web_app_data back."""
    return {"keyboard": [[{"text": button["text"], "web_app": {"url": button["url"]}}]],
            "resize_keyboard": True, "one_time_keyboard": True}


def _duration(ttl: timedelta) -> str:
    minutes = int(ttl.total_seconds() // 60)
    return f"{minutes // 60} h" if minutes >= 60 and minutes % 60 == 0 else f"{minutes} min"


def submit(cfg: BotConfig, data: str, now: datetime, *, whatsapp: bool = False) -> dict:
    """The page's ciphertext: open it with the pending one-time key, which is then deleted, and reseed the chain.
    Anything that does not end in a working token answers with a fresh form."""
    try:
        token = _open(cfg, data.strip(), now)
    except FormError as exc:
        log.info("canvas-submit: %s", exc)
        return open_form(cfg, now, f"⌛ {exc} Te abro otro:\n\n", whatsapp=whatsapp)
    try:
        result = reseed(cfg.core, token, now)
    except RenewalError as exc:
        log.info("canvas-submit: reseed falló (%s)", exc.status)
        intro = ("❌ El aula virtual no aceptó ese token (¿lo copiaste completo?). Crea otro y pégalo:\n\n"
                 if exc.status == 401 else f"❌ No pude comprobarlo con el aula virtual: {e(exc)}. Pégalo otra vez:\n\n")
        return open_form(cfg, now, intro, whatsapp=whatsapp)
    finally:
        token = ""
    if result.chain_cut:
        return open_form(cfg, now, "❌ Canvas aceptó el token pero lo rechazó al renovarlo. Crea otro y pégalo:\n\n",
                         whatsapp=whatsapp)
    if result.renewal_error:
        log.info("canvas-submit: token resembrado; la renovación falló (%s)", result.renewal_error)
        return {"respuesta": "✅ Token verificado y guardado. La renovación automática falló esta vez; el "
                             "mantenimiento la reintentará solo.", "quitar_teclado": True, "ok": True}
    log.info("canvas-submit: token resembrado")
    suffix = " y su sucesor automático ya quedó activo" if result.renewed else ""
    return {"respuesta": f"✅ Token verificado y guardado{suffix}. La cadena de renovación volvió a funcionar.",
            "quitar_teclado": True, "ok": True}


def _open(cfg: BotConfig, data: str, now: datetime) -> str:
    if not data.startswith(PREFIX):
        raise FormError("Eso no vino del formulario de /token.")
    body = data[len(PREFIX):]
    try:
        sealed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (binascii.Error, ValueError):
        raise FormError("Eso no vino del formulario de /token.") from None
    conn = connect(cfg.core.db_path)
    try:
        with file_lock(cfg.core.data_dir, "bot.lock"):
            stored = load_secret_values().get(KEY, "")
            expires = timefmt.parse(get_meta(conn, EXPIRES))
            if not stored or expires is None:
                raise FormError("Ese formulario ya se usó o venció.")
            if now > expires:
                _forget(conn)
                raise FormError("Ese formulario venció.")
            key = serialization.load_der_private_key(base64.b64decode(stored), password=None)
            try:
                plain = key.decrypt(sealed, OAEP)
            except ValueError:  # sealed with the key of an earlier /token
                raise FormError("Ese botón era de un /token anterior.") from None
            _forget(conn)
    finally:
        conn.close()
    token = plain.decode("utf-8", errors="replace").strip()
    if not token:
        raise FormError("El formulario llegó vacío.")
    return token


def _forget(conn) -> None:
    update_secret_values({}, remove=(KEY,))
    delete_meta(conn, EXPIRES)
    conn.commit()
