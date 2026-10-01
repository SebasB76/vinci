"""/token: the captain hands Vinci a new Canvas token from Telegram without Telegram ever reading it.

Each /token makes a one-time RSA key pair. Its public half rides in the URL of a Mini App keyboard
button (docs/token/, a static page on GitHub Pages); the page encrypts the token on the phone with
RSA-OAEP and sends back only the ciphertext, as the button's web_app_data. The private half waits in
secrets.env until a ciphertext opens with it or FORM_TTL passes, and is then deleted: a ciphertext left
in the chat history opens nothing later, and each new /token replaces the pending key.

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
OPENED = "token_form_opened_at"
FORM_TTL = timedelta(minutes=15)
PREFIX = "v1."  # what the page puts before the base64url ciphertext
BUTTON = "🔑 Pegar token"
# WebCrypto's RSA-OAEP with hash SHA-256 also uses SHA-256 for MGF1.
OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


class FormError(Exception):
    """The data cannot become a token: expired form, a stale button, or something that is not the page's."""


def open_form(cfg: BotConfig, now: datetime, intro: str = "") -> dict:
    """A fresh one-time key and the message with the button that opens the page with its public half."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.DER,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
    conn = connect(cfg.core.db_path)
    try:
        with file_lock(cfg.core.data_dir, "bot.lock"):  # the renewal rewrites secrets.env under it too
            update_secret_values({KEY: base64.b64encode(private).decode()})
            set_meta(conn, OPENED, timefmt.iso(now))
            conn.commit()
    finally:
        conn.close()
    log.info("canvas-form: formulario abierto")
    separator = "&" if "?" in cfg.token_form_url else "?"
    url = cfg.token_form_url + separator + urlencode({"k": base64.urlsafe_b64encode(public).decode().rstrip("=")})
    minutes = int(FORM_TTL.total_seconds() // 60)
    text = (f"{intro}🔑 <b>Token nuevo de Canvas</b>\n"
            f"1. Abre <a href=\"{e(cfg.core.canvas_url)}/profile/settings\">tu perfil del aula</a> y toca "
            "«+ Nuevo token de acceso».\n"
            f"2. Copia el token, toca «{BUTTON}» aquí abajo y pégalo.\n"
            "🔒 Se cifra en tu celular antes de salir: Telegram solo lleva un texto ilegible que únicamente tu PC "
            f"puede abrir. El formulario sirve una vez y vence en {minutes} min.")
    return {"respuesta": text, "web_app_button": {"text": BUTTON, "url": url}}


def submit(cfg: BotConfig, data: str, now: datetime) -> dict:
    """The page's ciphertext: open it with the pending one-time key, which is then deleted, and reseed the chain.
    Anything that does not end in a working token answers with a fresh form."""
    try:
        token = _open(cfg, data.strip(), now)
    except FormError as exc:
        log.info("canvas-submit: %s", exc)
        return open_form(cfg, now, f"⌛ {exc} Te abro otro:\n\n")
    try:
        result = reseed(cfg.core, token, now)
    except RenewalError as exc:
        log.info("canvas-submit: reseed falló (%s)", exc.status)
        if load_secret_values().get("CANVAS_TOKEN") == token:
            return {"respuesta": "✅ Token verificado y guardado. La renovación automática falló esta vez; el "
                                 "mantenimiento la reintentará solo.", "quitar_teclado": True}
        intro = ("❌ El aula virtual no aceptó ese token (¿lo copiaste completo?). Crea otro y pégalo:\n\n"
                 if exc.status == 401 else f"❌ No pude comprobarlo con el aula virtual: {e(exc)}. Pégalo otra vez:\n\n")
        return open_form(cfg, now, intro)
    finally:
        token = ""
    if result.chain_cut:
        return open_form(cfg, now, "❌ Canvas aceptó el token pero lo rechazó al renovarlo. Crea otro y pégalo:\n\n")
    log.info("canvas-submit: token resembrado")
    suffix = " y su sucesor automático ya quedó activo" if result.renewed else ""
    return {"respuesta": f"✅ Token verificado y guardado{suffix}. La cadena de renovación volvió a funcionar.",
            "quitar_teclado": True}


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
            opened = timefmt.parse(get_meta(conn, OPENED))
            if not stored or opened is None:
                raise FormError("Ese formulario ya se usó o venció.")
            if now - opened > FORM_TTL:
                _forget(conn)
                raise FormError(f"Ese formulario venció (dura {int(FORM_TTL.total_seconds() // 60)} min).")
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
    delete_meta(conn, OPENED)
    conn.commit()
