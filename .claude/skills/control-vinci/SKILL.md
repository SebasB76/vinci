---
name: control-vinci
description: Debug and verify Vinci on the live Coolify container from the PC (`vinci-check remote`: logs, errors, turns, commands, files), and drive the bots the way the captain would on his phone - send a message and read the reply, press a button, read what Vinci answered on WhatsApp, open the token form or the dashboard. Use first when the captain reports a live bug or error, after any change to bot behavior, before saying something works, when he sends a screenshot of a bot chat, and to find which feature lives where (Telegram vs WhatsApp).
---

# Control Vinci

`vinci-check` drives the live bots. They run in the Coolify container, and `vinci-check remote` reaches it from
the PC: run every command below as `vinci-check remote run vinci-check <command>`, with no copy-paste from the
captain. Use `.venv/bin/vinci-check` of the main checkout (`~/Projects/espol-academic-bot`) or of your worktree.

## When the captain reports a live bug, start here

1. `vinci-check remote status`: gateway, WhatsApp, every Vinci's health, stuck turns, error count.
2. `vinci-check remote errors`: the grouped `errors.log` lines of the last 24 h.
3. `vinci-check remote logs all --grep "<words>" -n 100`: what the gateway did, from every `gateway.log`. Hermes
   logs each message in the log of the profile that answers it, so the `[vinci]` or `[amigo-…]` in front of an
   `inbound message` line says who answered; `gateway` is the root log (startup, WhatsApp bridge).
4. `vinci-check remote turns --profile <vinci|amigo-…> -n 40`: the turns themselves, with tool calls.
5. Fix it: in code (a PR, then the Redeploy in `AGENTS.md` "Done means"), or live with `remote run`, `remote put`
   or `remote restart` when the cause is state in `/opt/data` (say what you changed in the report).

If `remote` says it has no saved access or answers 404, the captain must mint a key (`espol-bot panel
--clave-agente` in the Coolify Terminal) and run `vinci-check remote login https://<panel domain>` on the PC
(`docs/guia/panel.md`, «El agente desde tu PC»). Never ask for the key in the chat. Only then fall back to asking
him to run commands in the Terminal and paste the output.

## Remote access (from the PC)

| Command | Use it to |
|---|---|
| `vinci-check remote status` / `errors` | health and the grouped errors, as the panel shows them |
| `vinci-check remote logs [name] [-n 200] [--grep re] [-f] [--raw]` | tail or follow a log; no name lists them (`all`, `gateway`, `errors`, `bot`, `agent`, `<profile>/<log>`) |
| `vinci-check remote turns [--profile vinci] [-n 30] [--session id] [--raw]` | recent turns and tool calls of a profile |
| `vinci-check remote run <command>` | a shell command in the container, as `hermes`, in `/opt/data` (options before the command) |
| `vinci-check remote doctor` / `restart` | `espol-bot doctor` / `hermes gateway restart` |
| `vinci-check remote get <path> [local]` / `put <local> <path>` | copy a file under `/opt/data` (`state.db` to query it locally) |

Logs and turns mask phone numbers, WhatsApp ids, friends' names and message text by default. Add `--raw` only when
the text itself is the bug, and quote no more than needed in the report (initials, last digits). `run` and `get`
are never masked: grep before you print. Every `run`, `get` and `put` is logged in `/opt/data/logs/agent.log`.

The bots run `main` as of the last **Redeploy**: a behavior change is only live after "Done means" steps 3 and 4 in
`AGENTS.md` (merge, Redeploy).

## Commands (in the container: through `remote run`)

| Command | Use it to |
|---|---|
| `vinci-check status` | check gateway, poller, Canvas sync and token chain |
| `vinci-check bots` | list the bots `chat` and `press` may write to |
| `vinci-check chat <bot> "<text>"` | send as the captain and get the full reply with its buttons |
| `vinci-check press <bot> "<button>"` | press a button (a unique part of its label is enough) |
| `vinci-check whatsapp [--profile vinci] [--chat dm\|group] [--last 8]` | read the latest WhatsApp turns and the tools the bot called |
| `vinci-check say "<text>"` | write to Vinci in the captain's WhatsApp chat and get its reply (it reaches his phone too) |
| `vinci-check vote "<option>"` | vote on Vinci's latest poll in the captain's WhatsApp chat |
| `vinci-check page token\|dashboard\|notas` | open the GitHub Pages page in headless Chrome; the dashboard and «Tus notas» carry the real data |
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
