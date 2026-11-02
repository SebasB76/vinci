---
name: album-card
description: Make a new card for Vinci's album from photos the captain sends - Codex draws it in the album's retro pixel style, then the art is encrypted into docs/album/art/ and the card added to docs/album/cards.json. Use when the captain sends photos of a person, a group or a place for the album, asks for a new card, or wants a card redrawn.
---

# Album card

The captain sends photos (in the chat they arrive as attachment paths) and says who or what the card is. You run
`scripts/album_card.py`, show the result, and ship the card in a PR.

## Steps

1. Restate the card in one line: id (kebab-case, English or the proper name), name, collection (`espol` or
   `iconos`), group (the small line under the name), rarity (`com`, `rare`, `epic`, `leg`) and whether it is wide
   (a group scene, 4:3) or a portrait (5:7). Ask only for what you cannot guess; the captain decides the rarity.
2. Draw it from the main checkout, which holds `secrets.env`:
   `uv run scripts/album_card.py draw --id <id> --photo <a> [--photo <b>] --brief "<scene>" [--wide]`.
   The brief is the scene in one or two sentences: the place (an ESPOL building is a good default), the clothes, what
   they hold. It takes 1 to 3 minutes and prints the PNG path under `~/.local/share/espol-academic-bot/album-art/`.
3. Show the PNG to the captain (Read it, then link the path). Redraw with a sharper brief if a face is off; never ship
   one the captain did not approve.
4. In a worktree, add it: `AULA_SECRETS=~/Projects/espol-academic-bot/secrets.env uv run scripts/album_card.py add
   --id <id> --image <png> --name "<name>" --collection <c> --group "<group>" --rarity <r> [--wide]`. A PNG the captain
   made elsewhere (ChatGPT) goes straight to this step.
5. Bump `album.js`'s and `album.css`'s `?v=` only if the page changed; a card alone needs no bump (the art's file name
   carries its hash and `cards.json` is fetched fresh).
6. PR and merge. The page shows the card once Pages builds, but Vinci draws packs from its own copy of
   `cards.json`: the card only drops after a Redeploy in Coolify.

## Rules

- Never commit a PNG or any unencrypted art of a real person: the repo and its Pages are public. Only `art/*.bin`.
- Never print `ALBUM_ART_KEY`. `key --copy` puts it in the clipboard for Coolify's variables.
- A card of a public figure or place with no faces of friends can use a plain `img` instead, but encrypted is fine
  for everything.
- No names of real people in commit messages or the PR beyond the card's own name.
