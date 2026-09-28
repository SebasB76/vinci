"""Read-only Canvas LMS REST client.

Every Canvas request in the bot goes through `CanvasClient`, and the client only
knows how to issue HTTP GET. There is deliberately no code path that submits,
posts, messages, or changes anything on the aula virtual.

Behaviour, per the public Canvas API docs:
- Bearer auth with the student's personal access token.
- Pagination follows the `Link: <...>; rel="next"` header.
- Throttling: Canvas reports the remaining quota in `X-Rate-Limit-Remaining`
  and answers 429 (older versions: 403 "Rate Limit Exceeded") when it runs out.
  Requests are sequential; we slow down when the quota gets low and back off on 429.

Beyond what Canvas enforces, the client stays gentle so the traffic never looks like abuse:
background work (the bot's poll) asks for at most one request per `interval` seconds, and
ThrottledError tells the caller when Canvas keeps throttling after the retries, so it stops
reading instead of moving on to the next resource.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit

import requests

log = logging.getLogger(__name__)

USER_AGENT = "espol-academic-bot/0.1 (solo lectura)"
LOW_QUOTA = 100.0
MAX_RETRIES = 5


class CanvasError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class InvalidTokenError(CanvasError):
    pass


class ThrottledError(CanvasError):
    pass


class CanvasClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0, sleep=time.sleep,
                 interval: float = 0.0):
        self.base_url = base_url.rstrip("/")
        self.api = self.base_url + "/api/v1"
        self._host = urlsplit(self.base_url).netloc
        self._timeout = timeout
        self._sleep = sleep
        self._interval = interval
        self._last = 0.0
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT})
        self.requests_made = 0

    # -- the only HTTP verb this client ever uses ------------------------------------

    def _get(self, url: str, *, params: dict | list | None = None, stream: bool = False) -> requests.Response:
        if urlsplit(url).netloc != self._host:
            # Never send the token to another host. Redirects to file storage are
            # followed by requests itself, which drops Authorization across hosts.
            raise CanvasError(f"URL fuera del aula virtual, no se consulta: {url}")
        delay = 1.0
        throttled = False
        for attempt in range(MAX_RETRIES + 1):
            self._pace()
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout, stream=stream)
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES:
                    raise CanvasError(f"No pude conectar con el aula virtual: {exc}") from exc
                self._sleep(delay)
                delay = min(delay * 2, 60)
                continue
            self.requests_made += 1
            self._respect_quota(resp)
            throttled = self._is_throttled(resp)
            if throttled or resp.status_code >= 500:
                if attempt == MAX_RETRIES:
                    break
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else delay
                log.warning("Canvas respondió %s; espero %.1fs", resp.status_code, wait)
                resp.close()
                self._sleep(wait)
                delay = min(delay * 2, 60)
                continue
            if resp.status_code == 401 and self._is_bad_token(resp):
                raise InvalidTokenError("El token de Canvas no es válido o expiró (401). Crea uno nuevo.", 401)
            if resp.status_code >= 400:
                # 401/403/404 without a token problem: this student cannot see that
                # resource (for example a course whose Files tab is hidden).
                raise CanvasError(f"Canvas respondió {resp.status_code} para {urlsplit(url).path}", resp.status_code)
            return resp
        if throttled:
            raise ThrottledError(f"el aula virtual sigue pidiendo bajar el ritmo ({resp.status_code})", 429)
        raise CanvasError(f"Canvas sigue limitando o fallando ({resp.status_code}) para {urlsplit(url).path}", resp.status_code)

    def _pace(self) -> None:
        if self._interval > 0:
            self._sleep(max(0.0, self._last + self._interval - time.monotonic()))
            self._last = time.monotonic()

    @staticmethod
    def _is_bad_token(resp: requests.Response) -> bool:
        # Canvas answers "Invalid access token." / "Expired access token." for a bad token,
        # and {"status": "unauthorized", ...} when the user just lacks permission.
        return "access token" in resp.text[:500].lower()

    @staticmethod
    def _is_throttled(resp: requests.Response) -> bool:
        if resp.status_code == 429:
            return True
        return resp.status_code == 403 and "rate limit exceeded" in resp.text[:500].lower()

    def _respect_quota(self, resp: requests.Response) -> None:
        remaining = resp.headers.get("X-Rate-Limit-Remaining")
        if remaining is None:
            return
        try:
            value = float(remaining)
        except ValueError:
            return
        if value < LOW_QUOTA:
            # The bucket refills over time; pause longer the emptier it is.
            self._sleep(min(30.0, (LOW_QUOTA - value) / 10.0 + 1.0))

    # -- public read helpers ----------------------------------------------------------

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else self.api + "/" + path.lstrip("/")

    @staticmethod
    def _json(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError as exc:
            raise CanvasError(f"Canvas no respondió JSON para {urlsplit(resp.url).path}") from exc

    def get(self, path: str, params: dict | list | None = None) -> Any:
        return self._json(self._get(self._url(path), params=params))

    def get_all(self, path: str, params: dict | list | None = None) -> list[Any]:
        return list(self.iter_pages(path, params))

    def iter_pages(self, path: str, params: dict | list | None = None) -> Iterator[Any]:
        url: str | None = self._url(path)
        query = _with_per_page(params)
        while url:
            resp = self._get(url, params=query)
            data = self._json(resp)
            if isinstance(data, list):
                yield from data
            else:
                yield data
            nxt = resp.links.get("next", {}).get("url")
            url = urljoin(url, nxt) if nxt else None
            query = None  # the next link already carries every query parameter

    def download(self, url: str, dest: Path, *, max_bytes: int) -> int:
        """Download a file (GET) to `dest`; returns the size written."""
        resp = self._get(url, stream=True)
        tmp = dest.with_name(dest.name + ".part")
        size = 0
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise CanvasError(f"Archivo demasiado grande: {dest.name}")
                    fh.write(chunk)
            tmp.replace(dest)
        except (requests.RequestException, OSError) as exc:
            raise CanvasError(f"No pude bajar {dest.name}: {exc}") from exc
        finally:
            resp.close()
            tmp.unlink(missing_ok=True)
        return size


def _with_per_page(params: dict | list | None) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = list(params.items()) if isinstance(params, dict) else list(params or [])
    expanded: list[tuple[str, Any]] = []
    for key, value in items:
        if isinstance(value, (list, tuple)):
            expanded.extend((key, v) for v in value)
        else:
            expanded.append((key, value))
    if not any(k == "per_page" for k, _ in expanded):
        expanded.append(("per_page", 100))
    return expanded
