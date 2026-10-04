"""Hand in a handwritten activity: the captain's photos become one PDF, and the PDF goes to an
assignment of the aula virtual only when the captain presses «Entregar» under it.

This is the only place that writes course data to Canvas. CanvasClient stays GET-only; the upload
here follows Canvas's three steps for a submission file (ask for an upload slot, upload the file,
submit it), and the token goes only to the aula's own host, never to the file storage it hands off to.
"""

from __future__ import annotations

import io
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from aula_core import Aula, timefmt
from aula_core.canvas import CanvasError, InvalidTokenError
from aula_core.config import ConfigError, CoreConfig, canvas_token
from aula_core.materials import safe_filename

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PAGES = 30
MAX_SIDE = 2400   # pixels of a page's long side: legible handwriting, a few hundred KB per page
PAGE_INCHES = 11.69  # the long side of A4, so the PDF prints at a normal size
THUMB_SIDE = 320  # Telegram's limit for a document thumbnail
TIMEOUT = (10, 120)
USER_AGENT = "espol-academic-bot/0.1 (entrega de tareas)"


class SubmitError(Exception):
    """`final`: retrying cannot help (the aula closed the assignment, it takes no files)."""

    def __init__(self, message: str, *, final: bool = False):
        super().__init__(message)
        self.final = final


class AlreadySubmitted(Exception):
    def __init__(self, submitted_at: str):
        super().__init__(submitted_at)
        self.submitted_at = submitted_at


def folder(cfg: CoreConfig, code: str) -> Path:
    return cfg.data_dir / "submissions" / code.upper()


def build_pdf(images: list[Path], dest: Path) -> tuple[int, bytes]:
    """One page per photo, in order; returns the page count and a JPEG thumbnail of the first page."""
    pages = []
    for number, path in enumerate(images, 1):
        try:
            with Image.open(path) as img:
                page = ImageOps.exif_transpose(img).convert("RGB")
        except (UnidentifiedImageError, OSError):
            raise SubmitError(f"No pude abrir la foto {number}. Mándala como foto, no como archivo.") from None
        page.thumbnail((MAX_SIDE, MAX_SIDE))
        pages.append(page)
    dest.parent.mkdir(parents=True, exist_ok=True)
    resolution = max(max(p.size) for p in pages) / PAGE_INCHES
    pages[0].save(dest, "PDF", save_all=True, append_images=pages[1:], resolution=resolution, quality=85)
    return len(pages), _thumbnail(pages[0])


def take_pdf(source: Path, dest: Path) -> tuple[int, bytes]:
    """A PDF the captain sent as it is; returns its page count and a thumbnail of its first page."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(str(source))
    except pdfium.PdfiumError:
        raise SubmitError("No pude abrir ese PDF; ¿está dañado o tiene contraseña?") from None
    try:
        if len(pdf) == 0:
            raise SubmitError("Ese PDF no tiene páginas.")
        width, height = pdf[0].get_size()
        first = pdf[0].render(scale=THUMB_SIDE / max(width, height, 1)).to_pil().convert("RGB")
        pages = len(pdf)
    finally:
        pdf.close()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return pages, _thumbnail(first)


def _thumbnail(page: Image.Image) -> bytes:
    thumb = page.copy()
    thumb.thumbnail((THUMB_SIDE, THUMB_SIDE))
    out = io.BytesIO()
    thumb.save(out, "JPEG", quality=80)
    return out.getvalue()


def new_pdf_path(cfg: CoreConfig, code: str, assignment_id: int, now: datetime) -> Path:
    return folder(cfg, code) / f"{now.astimezone(cfg.tz):%Y%m%d-%H%M%S}-{assignment_id}-{uuid.uuid4().hex[:6]}.pdf"


def upload_name(assignment_name: str) -> str:
    return safe_filename(assignment_name)[:100] + ".pdf"


def check(cfg: CoreConfig, course_id: int, assignment_id: int, since: datetime) -> dict:
    """The assignment as the aula has it right now; refuses what Canvas would refuse anyway, and raises
    AlreadySubmitted when it got a submission after `since` (an earlier press whose answer was lost)."""
    aula = Aula(cfg, explicit=True)
    try:
        data = aula.client.get(f"courses/{course_id}/assignments/{assignment_id}", {"include[]": ["submission"]})
    except InvalidTokenError:
        raise SubmitError("el aula rechazó tu token. Mándale /token a Vinci y vuelve a pulsar «Entregar».") from None
    except (CanvasError, ConfigError) as exc:
        raise SubmitError(f"no pude leer la tarea en el aula ({exc}). Vuelve a pulsar «Entregar» en un rato.") from None
    finally:
        aula.close()
    if "online_upload" not in (data.get("submission_types") or []):
        raise SubmitError("esta tarea no recibe archivos en el aula.", final=True)
    allowed = [ext.lower().lstrip(".") for ext in data.get("allowed_extensions") or []]
    if allowed and "pdf" not in allowed:
        raise SubmitError(f"el aula solo acepta {', '.join(allowed)} en esta tarea, no PDF.", final=True)
    if data.get("locked_for_user"):
        raise SubmitError("el aula ya cerró esta tarea.", final=True)
    sub = data.get("submission") or {}
    submitted = timefmt.parse(sub.get("submitted_at"))
    if submitted and submitted >= since:
        raise AlreadySubmitted(sub["submitted_at"])
    attempts = data.get("allowed_attempts")
    if attempts not in (None, -1) and (sub.get("attempt") or 0) >= attempts:
        raise SubmitError(f"ya usaste los {attempts} intentos que permite esta tarea.", final=True)
    return data


def submit(cfg: CoreConfig, course_id: int, assignment_id: int, pdf: Path, name: str) -> dict:
    """Upload `pdf` as `name` and submit it to the assignment; returns Canvas's submission."""
    host = urlsplit(cfg.canvas_url).netloc
    base = f"{cfg.canvas_url.rstrip('/')}/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions"
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {canvas_token()}", "User-Agent": USER_AGENT})

    def call(method: str, url: str, **kwargs) -> dict:
        if urlsplit(url).netloc != host:
            raise SubmitError("el aula respondió con una dirección de otro sitio; no le mandé tu token.")
        try:
            resp = session.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise SubmitError(f"no pude conectar con el aula ({type(exc).__name__}).") from None
        if resp.status_code == 401 and "access token" in resp.text[:500].lower():
            raise SubmitError("el aula rechazó tu token. Mándale /token a Vinci y vuelve a pulsar «Entregar».")
        if resp.status_code >= 400:
            raise SubmitError(f"el aula respondió {resp.status_code}: {_canvas_message(resp)}")
        return resp.json()

    try:
        slot = call("POST", f"{base}/self/files", data={"name": name, "size": pdf.stat().st_size,
                                                        "content_type": "application/pdf"})
        upload_url = slot.get("upload_url")
        if not upload_url:
            raise SubmitError("el aula no me dio dónde subir el archivo.")
        # The upload slot carries its own signature: the token never goes with the file.
        with pdf.open("rb") as fh:
            resp = requests.post(upload_url, data=slot.get("upload_params") or {},
                                 files={slot.get("file_param") or "file": (name, fh, "application/pdf")},
                                 headers={"User-Agent": USER_AGENT}, allow_redirects=False, timeout=TIMEOUT)
        if resp.status_code >= 400:
            raise SubmitError(f"no pude subir el PDF ({resp.status_code}).")
        uploaded = resp.json() if 200 <= resp.status_code < 300 and resp.content else {}
        if 300 <= resp.status_code < 400 or "id" not in uploaded:
            location = resp.headers.get("Location") or uploaded.get("location")
            if not location:
                raise SubmitError("el aula no confirmó el archivo subido.")
            uploaded = call("GET", urljoin(upload_url, location))
        return call("POST", base, data=[("submission[submission_type]", "online_upload"),
                                         ("submission[file_ids][]", str(uploaded["id"]))])
    except (ValueError, KeyError):
        raise SubmitError("el aula respondió algo que no entiendo.") from None
    finally:
        session.close()


def _canvas_message(resp: requests.Response) -> str:
    try:
        errors = resp.json().get("errors")
    except (ValueError, AttributeError):
        return resp.text[:200]
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("message"))[:200]
    return str(errors)[:200]
