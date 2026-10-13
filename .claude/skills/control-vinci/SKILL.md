---
name: control-vinci
description: Verify a change to Vinci or the subject bots on the live system, the way the captain would on his phone - send a message to a bot and read the reply, press a button, read what Vinci answered on WhatsApp, open the token form or the dashboard. Use after any change to bot behavior, before saying something works, when the captain reports a bot problem or sends a screenshot of a bot chat, and to find which feature lives where (Telegram vs WhatsApp).
---

# Control Vinci

`vinci-check` drives the live bots. It is installed in `.venv/bin/` of the live checkout
(`~/Projects/espol-academic-bot`). From a worktree, run the worktree's code against the live data:

```bash
AULA_CONFIG=~/Projects/espol-academic-bot/config.toml AULA_SECRETS=~/Projects/espol-academic-bot/secrets.env \
  PYTHONPATH=src ~/Projects/espol-academic-bot/.venv/bin/python -m espol_bot.check <command>
```

The bots run the live checkout's code, not the worktree's: a behavior change is only live after
"Done means" steps 3 to 5 in `AGENTS.md` (merge, `setup.sh`, gateway restart).

## Commands

| Command | Use it to |
|---|---|
| `vinci-check status` | check gateway, poller, Canvas sync and token chain |
| `vinci-check bots` | list the bots `chat` and `press` may write to |
| `vinci-check chat <bot> "<text>"` | send as the captain and get the full reply with its buttons |
| `vinci-check press <bot> "<button>"` | press a button (a unique part of its label is enough) |
| `vinci-check whatsapp [--profile vinci] [--chat dm\|group] [--last 8]` | read the latest WhatsApp turns and the tools the bot called |
| `vinci-check say "<text>"` | write to Vinci in the captain's WhatsApp chat and get its reply (it reaches his phone too) |
| `vinci-check vote "<option>"` | vote on Vinci's latest poll in the captain's WhatsApp chat |
| `vinci-check page token\|dashboard` | open the GitHub Pages page in headless Chrome; the dashboard carries the real data |
| `vinci-check smoke` | the standard round (about 45 s): status, `/estado`, both pages; with Telegram on, `/start` to each subject bot |

All take `--json` and exit 1 on failure; a failure says what to run next.

## Rules

- Telegram is off (`[channels] telegram = false`): `say` and `vote` are how you test, in the captain's own
  WhatsApp chat with Vinci. `say` puts the text in his Hermes session (the plugin injects it, as with the
  Académico's held question), so the plugin's own commands (`/estado`, `/token`) do not run through it.
- `chat` and `press` act as the captain's Telegram account and only reach his Vinci bots, with Telegram on.
  The captain allows test messages to his own chats. A message that triggers the model costs tokens: prefer
  `/estado` and polls, and send model questions only when the change needs one.
- Never `press` a button or `vote` an option with an outside effect (`📤 Entregar`, `✅ Guardar …`, `➕ Crear`,
  archive) unless the task is exactly that, since it hands in, saves or creates for real.
- Never press «🎓 Conectar Académico» or send «actualiza mi Académico»: a sign-in needs the
  captain's password and CAPTCHA. Check the saved copy with `.venv/bin/espol-bot academico`.
- `whatsapp` only reads, and `say`/`vote` reach only the captain's chat: nothing writes to a group or as a
  friend. A friend's profile (`amigo-<name>`) holds their private chats: open it only to debug a problem they
  reported, and quote no more than needed.
- When the captain sends a screenshot of a bot chat, also `chat`/`tg read` or `whatsapp` that chat.
- Report what you checked with the command output. What only a phone shows (the iPhone webview
  inside WhatsApp, how a poll looks) stays on the captain's list.

## Feature map

`references/features/README.md` lists every feature, where it lives on Telegram and on WhatsApp,
the code behind it and how to verify it. Detail files cover the multi-step flows. A PR that adds or
changes a feature updates its row (see "Keep docs in sync" in `AGENTS.md`).
