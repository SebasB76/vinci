#!/usr/bin/env python3
"""Makes an album card from photos: Codex draws it in the album's retro pixel style, then `add` encrypts the art into
docs/album/art/ and puts the card in docs/album/cards.json.

The art is encrypted because it shows real faces and the repo and its Pages are public. The page decrypts it with
ALBUM_ART_KEY, which Vinci puts in the fragment of each link it sends (espol_bot/album.py). The PNGs stay outside the
repo, in ~/.local/share/espol-academic-bot/album-art/.

  uv run scripts/album_card.py key [--copy]          # create ALBUM_ART_KEY once; --copy puts it in the clipboard
  uv run scripts/album_card.py draw --id ID --photo a.jpg [--photo b.jpg] --brief "..." [--wide]
  uv run scripts/album_card.py add --id ID --image art.png --name NAME --collection espol --group GROUP \\
      --rarity com|rare|epic|leg [--wide]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

from aula_core.config import REPO_ROOT, load_secret_values, secrets_path, update_secret_values

ALBUM = REPO_ROOT / "docs" / "album"
CATALOG = ALBUM / "cards.json"
ORIGINALS = Path.home() / ".local" / "share" / "espol-academic-bot" / "album-art"
CODEX_IMAGES = Path.home() / ".codex" / "generated_images"
MAX_SIDE = 960
RARITIES = ("com", "rare", "epic", "leg")

STYLE = """Generate exactly one image with your image generation tool. Do not create or edit any file.

It is the art of a trading card in an album that a group of ESPOL students (Guayaquil, Ecuador) collect.
Style: retro 16-bit pixel art, like a SNES game: visible pixels and dithering, crisp dark outlines, warm bright colors.
Keep every person recognizable from the reference photos: the same face shape, hairstyle, skin tone, glasses, facial
hair and expression. Do not make them look older, younger or like someone else.
Scene: {brief}
Composition: {shape}, the people centered, with room around the heads.
No frame, border, card layout or rarity label: the album draws the card's frame around this art. No text unless the
scene asks for it."""


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def key_bytes() -> bytes:
    value = load_secret_values().get("ALBUM_ART_KEY", "")
    if not value:
        sys.exit("Falta ALBUM_ART_KEY en secrets.env: corre primero `uv run scripts/album_card.py key`.")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def cmd_key(args: argparse.Namespace) -> None:
    values = load_secret_values() if secrets_path().exists() else {}
    if not values.get("ALBUM_ART_KEY"):
        update_secret_values({"ALBUM_ART_KEY": b64url(os.urandom(32))})
        print(f"Creé ALBUM_ART_KEY en {secrets_path()}.")
    else:
        print(f"ALBUM_ART_KEY ya está en {secrets_path()}.")
    if args.copy:  # the value never reaches the terminal: straight to the clipboard, for Coolify's variables
        subprocess.run(["wl-copy"], input=load_secret_values()["ALBUM_ART_KEY"].encode(), check=True)
        print("La copié al portapapeles: pégala en Coolify como la variable ALBUM_ART_KEY.")


def cmd_draw(args: argparse.Namespace) -> None:
    photos = [Path(p).expanduser().resolve() for p in args.photo]
    for photo in photos:
        if not photo.is_file():
            sys.exit(f"No encuentro {photo}")
    shape = "landscape 4:3" if args.wide else "portrait 5:7 (taller than wide)"
    prompt = STYLE.format(brief=args.brief, shape=shape)
    started = time.time()
    with tempfile.TemporaryDirectory() as work:
        command = ["codex", "exec", "--skip-git-repo-check", "-C", work, "-s", "read-only", prompt]
        for photo in photos:
            command += ["-i", str(photo)]
        print(f"Codex está dibujando «{args.id}» (1 a 3 minutos)…", flush=True)
        done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    made = sorted((p for p in CODEX_IMAGES.rglob("*.png") if p.stat().st_mtime >= started),
                  key=lambda p: p.stat().st_mtime)
    if not made:
        sys.exit(f"Codex no generó ninguna imagen.\n{done.stdout[-2000:]}\n{done.stderr[-2000:]}")
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    out = ORIGINALS / f"{args.id}-{time.strftime('%Y%m%d-%H%M%S')}.png"
    out.write_bytes(made[-1].read_bytes())
    print(out)


def encrypt_art(card_id: str, image: Path) -> str:
    """The art as WebP, encrypted with AES-GCM (12-byte IV first, the card id as associated data); its path under
    docs/album/. The name carries a hash of the art, so a redrawn card never hits a cached old file."""
    picture = Image.open(image).convert("RGB")
    picture.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    picture.save(buffer, "WEBP", quality=84, method=6)
    webp = buffer.getvalue()
    iv = os.urandom(12)
    sealed = iv + AESGCM(key_bytes()).encrypt(iv, webp, card_id.encode())
    folder = ALBUM / "art"
    folder.mkdir(exist_ok=True)
    for old in folder.glob(f"{card_id}-*.bin"):
        old.unlink()
    name = f"art/{card_id}-{hashlib.sha256(webp).hexdigest()[:10]}.bin"
    (ALBUM / name).write_bytes(sealed)
    print(f"Arte: {len(webp) // 1024} KB en WebP, {ALBUM / name}")
    return name


def cmd_add(args: argparse.Namespace) -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.collection not in {c["id"] for c in catalog["collections"]}:
        sys.exit(f"No hay una colección «{args.collection}» en cards.json")
    art = encrypt_art(args.id, Path(args.image).expanduser())
    card = next((c for c in catalog["cards"] if c["id"] == args.id), None)
    if card is None:
        card = {"id": args.id, "n": max(c["n"] for c in catalog["cards"]) + 1}
        catalog["cards"].append(card)
    card.update(name=args.name, collection=args.collection, group=args.group, rarity=args.rarity, art=art)
    card.pop("img", None)
    if args.wide:
        card["wide"] = True
    else:
        card.pop("wide", None)
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Carta Nº {card['n']:03d} «{args.name}» en {CATALOG}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hace una carta del álbum a partir de fotos.")
    sub = parser.add_subparsers(dest="command", required=True)
    key = sub.add_parser("key", help="crea ALBUM_ART_KEY en secrets.env")
    key.add_argument("--copy", action="store_true", help="la copia al portapapeles, para Coolify")
    draw = sub.add_parser("draw", help="Codex dibuja la carta desde fotos")
    draw.add_argument("--id", required=True)
    draw.add_argument("--photo", action="append", required=True)
    draw.add_argument("--brief", required=True, help="la escena, en inglés o español")
    draw.add_argument("--wide", action="store_true", help="horizontal 4:3, para una escena de grupo")
    add = sub.add_parser("add", help="cifra el arte y pone la carta en cards.json")
    add.add_argument("--id", required=True)
    add.add_argument("--image", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--collection", required=True)
    add.add_argument("--group", required=True)
    add.add_argument("--rarity", required=True, choices=RARITIES)
    add.add_argument("--wide", action="store_true")
    args = parser.parse_args()
    {"key": cmd_key, "draw": cmd_draw, "add": cmd_add}[args.command](args)


if __name__ == "__main__":
    main()
