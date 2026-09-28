"""Keep ESPOL's one-hour Canvas personal tokens alive without touching course data.

The legacy User-Generated developer key on ESPOL's Canvas silently expires each token
after an hour. This manager creates a verified successor before then, swaps it into the
gitignored secrets file atomically, and deletes superseded tokens only after the swap.
One predecessor is retained briefly as a probe: if it still works after 70 minutes, the
server-side bug was fixed and automatic renewal disables itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import requests

from aula_core import timefmt, token_fingerprint
from aula_core.config import CoreConfig, load_secret_values, update_secret_values
from aula_core.store import delete_meta, get_meta, set_meta

CURRENT_FINGERPRINT = "canvas_renewal_fingerprint"
CURRENT_CREATED = "canvas_renewal_created_at"
CURRENT_ID = "canvas_renewal_token_id"
PROBE_CREATED = "canvas_renewal_probe_created_at"
PROBE_ID = "canvas_renewal_probe_id"
DISABLED = "canvas_renewal_disabled"
PROBE_TOKEN_KEY = "CANVAS_TOKEN_PROBE"

RENEW_AFTER = timedelta(minutes=40)
PROBE_AFTER = timedelta(minutes=70)
PERMANENT_EXPIRY = timedelta(days=119)
TIMEOUT = (10, 30)


class RenewalError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RenewalResult:
    renewed: bool = False
    server_fixed: bool = False


class TokenRenewal:
    def __init__(self, cfg: CoreConfig, conn, now: datetime):
        self.cfg = cfg
        self.conn = conn
        self.now = now
        self.api = cfg.canvas_url.rstrip("/") + "/api/v1"
        self.host = urlsplit(cfg.canvas_url).netloc

    def maintain(self, *, force: bool = False) -> RenewalResult:
        values = load_secret_values()
        current = values.get("CANVAS_TOKEN", "")
        if not current:
            raise RenewalError("Falta CANVAS_TOKEN en secrets.env")

        if get_meta(self.conn, DISABLED) == "server-fixed":
            return RenewalResult(server_fixed=True)

        probe_result = self._check_probe(values, current)
        if probe_result is not None:
            return probe_result

        fingerprint = token_fingerprint(current)
        tracked = get_meta(self.conn, CURRENT_FINGERPRINT)
        created = timefmt.parse(get_meta(self.conn, CURRENT_CREATED)) if tracked == fingerprint else None
        if created is not None and not force and self.now - created < RENEW_AFTER:
            return RenewalResult()

        old_id = self._integer(get_meta(self.conn, CURRENT_ID)) if tracked == fingerprint else None
        if old_id is None:
            old_id = self._find_token_id(current)
        token_data = self._create(current)
        successor = str(token_data.get("token") or "")
        successor_id = self._integer(token_data.get("id"))
        if not successor or successor_id is None:
            raise RenewalError("Canvas creó un reemplazo incompleto; conservé el token actual")
        self._verify(successor)

        probe = values.get(PROBE_TOKEN_KEY, "")
        updates = {"CANVAS_TOKEN": successor}
        if not probe:
            updates[PROBE_TOKEN_KEY] = current
        update_secret_values(updates)

        set_meta(self.conn, CURRENT_FINGERPRINT, token_fingerprint(successor))
        set_meta(self.conn, CURRENT_CREATED, timefmt.iso(self.now))
        set_meta(self.conn, CURRENT_ID, str(successor_id))
        if not probe:
            set_meta(self.conn, PROBE_CREATED, timefmt.iso(created or self.now))
            if old_id is not None:
                set_meta(self.conn, PROBE_ID, str(old_id))
        self.conn.commit()

        if probe and old_id is not None:
            self._delete(successor, old_id)
        return RenewalResult(renewed=True)

    def reseed(self, token: str) -> RenewalResult:
        token = token.strip()
        if not token:
            raise RenewalError("No recibí ningún token")
        self._verify(token)
        update_secret_values({"CANVAS_TOKEN": token}, remove=(PROBE_TOKEN_KEY,))
        delete_meta(self.conn, CURRENT_FINGERPRINT, CURRENT_CREATED, CURRENT_ID,
                    PROBE_CREATED, PROBE_ID, DISABLED, "canvas_token_refused")
        self.conn.commit()
        return self.maintain(force=True)

    def _check_probe(self, values: dict[str, str], current: str) -> RenewalResult | None:
        probe = values.get(PROBE_TOKEN_KEY, "")
        born = timefmt.parse(get_meta(self.conn, PROBE_CREATED))
        if not probe or born is None or self.now - born < PROBE_AFTER:
            return None
        response = self._request("GET", "/users/self", probe)
        probe_id = self._integer(get_meta(self.conn, PROBE_ID))
        fixed = response.status_code == 200
        if not fixed and not (response.status_code == 401 and self._is_bad_token(response)):
            raise RenewalError("No pude comprobar el token sonda; lo intentaré otra vez", response.status_code)
        if probe_id is not None:
            self._delete(current, probe_id)
        update_secret_values({}, remove=(PROBE_TOKEN_KEY,))
        delete_meta(self.conn, PROBE_CREATED, PROBE_ID)
        if fixed:
            set_meta(self.conn, DISABLED, "server-fixed")
        self.conn.commit()
        return RenewalResult(server_fixed=fixed) if fixed else None

    def _create(self, token: str) -> dict[str, Any]:
        expires = timefmt.iso(self.now + PERMANENT_EXPIRY)
        response = self._request(
            "POST", "/users/self/tokens", token,
            json={"token": {"purpose": "Vinci (renovación automática)", "expires_at": expires}},
        )
        if response.status_code == 401 and self._is_bad_token(response):
            raise RenewalError("El token venció antes de poder crear su reemplazo", 401)
        if response.status_code == 403:
            raise RenewalError("Canvas no permitió crear el token de reemplazo (403)", 403)
        if response.status_code >= 400:
            raise RenewalError(f"Canvas rechazó la renovación ({response.status_code})", response.status_code)
        try:
            data = response.json()
        except ValueError as exc:
            raise RenewalError("Canvas no devolvió JSON al crear el reemplazo") from exc
        return data if isinstance(data, dict) else {}

    def _verify(self, token: str) -> None:
        response = self._request("GET", "/users/self", token)
        if response.status_code != 200:
            raise RenewalError(f"Canvas no aceptó el token nuevo ({response.status_code}); conservé el anterior",
                               response.status_code)

    def _find_token_id(self, token: str) -> int | None:
        response = self._request("GET", "/users/self/user_generated_tokens?per_page=100", token)
        if response.status_code != 200:
            return None
        try:
            items = response.json()
        except ValueError:
            return None
        for item in items if isinstance(items, list) else []:
            hint = str(item.get("token_hint") or "")
            if hint and token.startswith(hint):
                return self._integer(item.get("id"))
        return None

    def _delete(self, current: str, token_id: int) -> None:
        response = self._request("DELETE", f"/users/self/tokens/{token_id}", current)
        if response.status_code not in (200, 204, 404):
            raise RenewalError(f"El reemplazo funciona, pero Canvas no borró el token anterior "
                               f"({response.status_code})", response.status_code)

    def _request(self, method: str, path: str, token: str, **kwargs) -> requests.Response:
        url = self.api + path
        if urlsplit(url).netloc != self.host:
            raise RenewalError("La renovación intentó salir del dominio del aula")
        try:
            return requests.request(method, url, headers={"Authorization": f"Bearer {token}",
                                                           "User-Agent": "espol-academic-bot/0.1"},
                                    timeout=TIMEOUT, allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise RenewalError(f"No pude conectar con Canvas para renovar ({type(exc).__name__})") from None

    @staticmethod
    def _is_bad_token(response: requests.Response) -> bool:
        return "access token" in response.text[:500].lower()

    @staticmethod
    def _integer(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
