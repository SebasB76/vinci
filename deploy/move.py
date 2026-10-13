"""Moves a PC's Vinci into the Docker image's volume.

    python deploy/move.py export [FILE]     on the PC, gateway stopped: packs the data folder, Vinci's Hermes
                                            profiles, the WhatsApp session and secrets.env into one encrypted file
    python deploy/move.py import URL|FILE   in the container: unpacks it into /opt/data and restarts the gateway

The passphrase never travels with the file: export prints it once, import asks for it. The file is a tar.gz in
ChaCha20-Poly1305 chunks, so neither side holds it in memory and a tampered or truncated file fails to open.
"""

from __future__ import annotations

import getpass
import io
import json
import os
import secrets
import shutil
import sqlite3
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from aula_core.config import secrets_path
from espol_bot.amigos import PROFILE_PREFIX
from espol_bot.config import hermes_root, load_bot_config

MAGIC = b"VINCI-MOVE-1"
CHUNK = 1 << 20
SKIP_NAMES = {"logs", "cache", "image_cache", "audio_cache", "document_cache", "runtime", "plugin-update-checks",
              "tessdata", "bot.log", "auth.json", "gateway_state.json", "provider_models_cache.json"}


def _key(passphrase: str, salt: bytes) -> ChaCha20Poly1305:
    return ChaCha20Poly1305(Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode()))


class Sealer:
    """A write-only file object: what tarfile writes goes out encrypted, chunk by chunk."""

    def __init__(self, out, passphrase: str):
        salt = os.urandom(16)
        self.out, self.aead, self.counter, self.buffer = out, _key(passphrase, salt), 0, bytearray()
        out.write(MAGIC + salt)

    def _seal(self, data: bytes, last: bool) -> None:
        sealed = self.aead.encrypt(self.counter.to_bytes(12, "big"), data, b"last" if last else b"")
        self.out.write(struct.pack(">I", len(sealed)) + sealed)
        self.counter += 1

    def write(self, data: bytes) -> int:
        self.buffer += data
        while len(self.buffer) > CHUNK:
            self._seal(bytes(self.buffer[:CHUNK]), False)
            del self.buffer[:CHUNK]
        return len(data)

    def close(self) -> None:
        self._seal(bytes(self.buffer), True)


class Opener:
    """A read-only file object over a sealed stream; raises if a chunk was altered or the end is missing."""

    def __init__(self, source, passphrase: str):
        head = source.read(len(MAGIC) + 16)
        if head[:len(MAGIC)] != MAGIC:
            raise SystemExit("Ese archivo no es una exportación de Vinci.")
        self.source, self.aead, self.counter = source, _key(passphrase, head[len(MAGIC):]), 0
        self.buffer, self.done = bytearray(), False

    def _exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            part = self.source.read(n - len(data))
            if not part:
                raise SystemExit("El archivo está incompleto: vuelve a bajarlo.")
            data += part
        return data

    def read(self, n: int = -1) -> bytes:
        while not self.done and (n < 0 or len(self.buffer) < n):
            size = struct.unpack(">I", self._exact(4))[0]
            sealed, nonce = self._exact(size), self.counter.to_bytes(12, "big")
            self.counter += 1
            for last in (False, True):
                try:
                    self.buffer += self.aead.decrypt(nonce, sealed, b"last" if last else b"")
                    self.done = last
                    break
                except Exception:
                    if last:
                        raise SystemExit("La clave no es la correcta, o el archivo cambió en el camino.") from None
        n = len(self.buffer) if n < 0 else min(n, len(self.buffer))
        data = bytes(self.buffer[:n])
        del self.buffer[:n]
        return data


def _skip(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(info.name).name
    # An absolute link (a profile's WhatsApp session) fails the import's safe filter; hermes-perfil remakes it there.
    if info.issym() and os.path.isabs(info.linkname):
        return None
    return None if name in SKIP_NAMES or name.endswith(".lock") else info


def _gateway_running() -> bool:
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            args = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue
        # The gateway itself is a Python process; the container's init shell also carries `gateway run`.
        pairs = zip(args, args[1:])
        if Path(args[0].decode(errors="replace")).name.startswith("python") and (b"gateway", b"run") in pairs:
            return True
    return False


def export(target: Path) -> int:
    if _gateway_running():
        raise SystemExit("El gateway de Hermes está encendido. Apágalo (hermes gateway stop) y vuelve a correr esto: "
                         "así la copia sale entera y el número de WhatsApp no queda abierto en dos lugares.")
    cfg = load_bot_config()
    root, vinci = hermes_root(), cfg.hermes_profile
    profiles = sorted(p for p in (root / "profiles").iterdir() if p.is_dir() and (
        p.name == vinci or p.name.startswith(f"{vinci}-") or p.name.startswith(PROFILE_PREFIX)))
    session = root / "platforms" / "whatsapp" / "session"
    passphrase = secrets.token_urlsafe(18)
    manifest = json.dumps({"data_dir": str(cfg.core.data_dir), "created": time.time()}).encode()
    with open(target, "wb") as out:
        sealer = Sealer(out, passphrase)
        with tarfile.open(fileobj=sealer, mode="w|gz") as tar:
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest)
            tar.addfile(info, io.BytesIO(manifest))
            tar.add(cfg.core.data_dir, "datos", filter=_skip)
            for profile in profiles:
                tar.add(profile, f"profiles/{profile.name}", filter=_skip)
            if session.is_dir():
                tar.add(session, "whatsapp-session")
            tar.add(secrets_path(), "secrets.env")
        sealer.close()
    os.chmod(target, 0o600)
    print(f"Listo: {target} ({target.stat().st_size / 1e6:.0f} MB), con {len(profiles)} perfiles: "
          f"{', '.join(p.name for p in profiles)}.")
    print(f"Clave para importarlo (no la pegues en un chat): {passphrase}")
    print(f"Para servirlo, solo esa carpeta: python3 -m http.server 8765 --directory {target.parent}")
    return 0


def _rewrite_paths(db: Path, old: str, new: str) -> int:
    """Absolute paths into the old data folder (downloaded material, hand-ins) now point into the volume."""
    changed = 0
    with sqlite3.connect(db) as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql NOT LIKE "
                                             "'CREATE VIRTUAL%' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE "
                                             "'chunks%'")]
        for table in tables:
            for column in [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")') if r[2].upper() == "TEXT"]:
                changed += conn.execute(f'UPDATE "{table}" SET "{column}" = replace("{column}", ?, ?) '
                                        f'WHERE instr("{column}", ?) > 0', (old, new, old)).rowcount
    return changed


def _put(src: Path, dest: Path, aside: Path) -> None:
    if dest.exists():
        aside.mkdir(parents=True, exist_ok=True)
        shutil.move(dest, aside / dest.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(src, dest)


def import_(source: str) -> int:
    if not os.environ.get("VINCI_HERMES_ROOT"):
        raise SystemExit("Esto corre dentro del contenedor de Vinci, no en tu PC.")
    hermes, bot = os.environ["HERMES_BIN"], str(Path(sys.prefix) / "bin" / "espol-bot")
    passphrase = getpass.getpass("Clave de la exportación: ").strip()
    cfg, root = load_bot_config(), hermes_root()
    env = {**os.environ, "HERMES_HOME": str(root)}
    subprocess.run([hermes, "gateway", "stop"], env=env, check=False)
    staging = root / "vinci" / "import-tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    stream = urllib.request.urlopen(source, timeout=60) if "://" in source else open(source, "rb")
    with stream, tarfile.open(fileobj=Opener(stream, passphrase), mode="r|gz") as tar:
        tar.extractall(staging, filter="data")
    manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))

    aside = root / "vinci" / f"before-import-{time.strftime('%Y%m%d-%H%M%S')}"
    data = cfg.core.data_dir
    _put(staging / "datos", data, aside)
    for profile in sorted((staging / "profiles").iterdir()):
        _put(profile, root / "profiles" / profile.name, aside / "profiles")
    if (staging / "whatsapp-session").is_dir():
        _put(staging / "whatsapp-session", root / "platforms" / "whatsapp" / "session", aside)
    _put(staging / "secrets.env", secrets_path(), aside)
    os.chmod(secrets_path(), 0o600)
    shutil.rmtree(staging)

    rewritten = sum(_rewrite_paths(db, manifest["data_dir"], str(data)) for db in data.rglob("espol.db"))
    print(f"Datos en {data}; {rewritten} rutas de la PC corregidas. Lo que había antes quedó en {aside}.")
    subprocess.run([bot, "hermes-perfil"], check=False)
    subprocess.run([hermes, "gateway", "start"], env=env, check=False)
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "export":
        # A folder of its own by default: a server over the repo would also hand out secrets.env.
        folder = Path(tempfile.mkdtemp(prefix="vinci-move-"))
        return export(Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else folder / "vinci-export.bin")
    if len(sys.argv) == 3 and sys.argv[1] == "import":
        return import_(sys.argv[2])
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
