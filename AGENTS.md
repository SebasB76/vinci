# AGENTS.md

## Purpose

Vinci is an ESPOL academic assistant on Telegram and WhatsApp, built on Hermes Agent and
the university's Canvas (aulavirtual). It has one maintainer, called "the captain" in code
and docs, and a few friends who each get their own Vinci on WhatsApp. It is a side project:
shipping speed beats ceremony, and a bug found later is fixed in a new session.

## Status (2026-10-28)

- Live: the Docker image (`Dockerfile`, `deploy/`) on Coolify, since 2026-10-27, on DeepSeek (`VINCI_PROVIDER`,
  `VINCI_MODEL` and `DEEPSEEK_API_KEY` in Coolify's variables). One container, one Hermes gateway for `vinci` and one
  `amigo-<name>` profile per friend; all its state lives in the volume `/opt/data` (`docs/guia/servidor.md`). Coolify
  builds `main` only when someone presses **Redeploy**: no webhook, and its CLI here has no valid token.
- Off: the old laptop `vinci-server` (offline since 2026-10-19). The captain's PC only keeps a dev checkout: its
  Vinci profiles are parked in `~/.hermes/vinci-en-servidor/`, so never start a gateway with them there.
- Live: WhatsApp is the only channel (`[channels] telegram = false`): Vinci, on a separate number through
  Hermes's unofficial bridge, keeps every subject in one chat, with its notebook and the brief before each class.
  Telegram is off, not deleted: the `vinci-<code>` subject bot profiles are parked (`gateway.parked`), and
  `telegram = true` brings them and `vinci_espol_bot` back.
- Live: `docs/token/`, `docs/dashboard/` and `docs/academico/` on GitHub Pages; `relay/` on Cloudflare Workers.
- Not running: the admin panel (`espol-bot panel`, `docs/guia/panel.md`). It ran on `vinci-server`; the image
  opens no port, so Coolify has none.
- The semester ends on 2027-01-15 (`semester_end` in `config.toml`).

## Where to start

These are entry points. Follow references anywhere the task leads.

- User-facing behavior: the guides in `docs/guia/` (Spanish): `uso.md` (Telegram), `whatsapp.md`,
  `instalacion.md`, `privacidad.md`, `problemas.md`. `README.md` is only a short front page.
- How each bot talks and what it may do: `hermes/vinci/`, `hermes/materia/` and
  `hermes/amigo/` (`SOUL.md` is the personality, `SKILL.md` the tools and rules).
- Gateway hooks (buttons, `/token`, the Académico's held question, WhatsApp voice): `hermes/plugins/vinci-botones/` and
  `hermes/plugins/vinci-whatsapp/`.
- What the E2E covers: the docstring at the top of `tests/e2e/test_e2e.py`.
- A live problem, or checking a change on the real bots: the `control-vinci` skill
  (`.claude/skills/control-vinci/SKILL.md`) and its `vinci-check` CLI.
- Which feature lives where (Telegram vs WhatsApp), its code and how to verify it:
  `.claude/skills/control-vinci/references/features/README.md`.
- `experiments/` holds spikes, not production code.

## Done means

Do steps 3 to 6 without asking. A PR is not done until the bots run it.

1. Run `gh pr list` first: the PR may already exist. Run `python3 scripts/docs_check.py` and
   fix what it flags (see "Keep docs in sync"). Then open a PR against `main` with a
   conventional commit title.
2. If behavior changed, extend `tests/e2e/test_e2e.py` and run `uv run pytest` once, after
   all changes.
3. `gh pr merge <n> --merge --delete-branch` (the repo keeps merge commits).
4. Ask the captain to press **Redeploy** on Vinci's app in Coolify, and wait for **Healthy**: each boot does what
   `./setup.sh` does.
5. In the container's **Terminal**: `espol-bot doctor`.
6. There: `s6-setuidgid hermes env HOME=/opt/data /opt/vinci/.venv/bin/vinci-check smoke` (about 45 s), plus a
   `vinci-check say` or `vote` that exercises the change itself.
7. Report only what still needs the captain's phone: WhatsApp replies and iPhone webviews.

## Working rules

- The live install is the Coolify container, built from `main`: never deploy a branch there. On the PC, work in a
  git worktree of `~/Projects/espol-academic-bot`, and never run `setup.sh` on the PC.
- E2E (four tests in parallel, about 3 minutes): never run it at the start of a session or to
  "check the baseline". A failed test leaves `artifacts/e2e/fallo-<test>.md` (the error, the last
  WhatsApp messages and model turns, the gateway log): read it before rerunning anything. Skip it for small changes (copy, `SOUL.md`, `config.toml`, about 50 lines). For a
  behavior change, run it once at the end, and never rerun it for a one-line fix. The captain
  asked for this 12 times; `docs/guia/contribuir.md` is for outside contributors.
- No unit tests and no extra review rounds.
- "Improve the project" means features the student notices, not refactors.
- For a new feature idea, restate the goal and the user flow in 3 to 5 lines, then build it.
  When the captain already gave the flow, build it directly.
- Test with the real bots through `vinci-check`. The captain allows test messages to his own
  chat with Vinci; `vinci-check` refuses any other chat. When he sends a screenshot of
  a bot chat, also read that chat (`vinci-check whatsapp`) for the full thread.
- Never print or copy `secrets.env`, `~/.local/share/tg-user/credentials.env` or
  `captain.session`. To get a new secret, use a hidden prompt (`read -s`), never the chat.
- No real data in fixtures, screenshots or issues: no tokens, grades, schedules or names.
- Explain an outside tool (Coolify, Wrangler, Fly.io) in one line the first time.

## Keep docs in sync

A PR that changes behavior updates every doc it makes wrong, in the same PR. The PR body ends
with `Docs:` and lists what it updated, or says why nothing needed it.
`python3 scripts/docs_check.py` flags code changed without its docs; it only warns.

| If you change… | Update |
|---|---|
| What a bot does or says (commands, buttons, alerts) | its section in `docs/guia/` + its row in the feature map |
| A slash command (new, renamed, removed) | `uso.md` «Comandos» (and the table in `whatsapp.md`) + feature map |
| Telegram vs WhatsApp support of a feature | the first table of the feature map |
| A multi-step flow (`/token`, dashboard, Académico) | its file in `.claude/skills/control-vinci/references/features/` |
| A bot's personality or rules | `hermes/<profile>/SOUL.md` or `SKILL.md` |
| A config key | its comment in `config.toml` + `instalacion.md` «Configuración» |
| A secret | `secrets.env.example` + `instalacion.md` «4. Completa `secrets.env`» |
| What `setup.sh` touches outside the repo | the header of `setup.sh` + `instalacion.md` «Actualizar y desinstalar» |
| A `vinci-check` command | `.claude/skills/control-vinci/SKILL.md` |
| What runs live, or a command here | «Status» or «Commands» in this file |
| A known limit (fixed or new) | `problemas.md` «Límites conocidos» |
| A headline feature (new or gone) | the «Qué hace» table in `README.md` + `funciones.md` |
| The summary, dashboard, Académico or hand-in messages | `docs/images/pantallas/pantallas.html`, then `scripts/render_screens.sh` |
| A new ESPOL source (like the Académico) | «Conectado a ESPOL» in `README.md` |

## Do not re-propose

- firstmate to supervise work on this repo: the captain removed it (2026-10).
- The no-mistakes pipeline: it is blocked in the captain's settings.
- A test profile or test bots instead of the real ones.

## Commands

The commands from `./setup.sh` down to `tail -f` are for an install like the old `vinci-server`. In the Coolify
container's Terminal, run `espol-bot` and `hermes` as they are (they run as the `hermes` user), and the data lives
under `/opt/data` (`docs/guia/servidor.md`).

```bash
uv sync                                   # dependencies, dev included
uv run pytest                             # the E2E: 4 tests in parallel (fake Canvas and WhatsApp, real Hermes)
./setup.sh                                # install or update profiles, crons, `aula`; sends a test message
./setup.sh --skip-deps --sin-pruebas      # same, without touching .venv or calling Canvas/Telegram
.venv/bin/espol-bot doctor                # poller, Canvas sync and token chain (read-only)
.venv/bin/espol-bot academico             # what the Académico copy holds (read-only)
systemctl --user status vinci-panel      # the admin panel on 127.0.0.1:8787 (`tailscale serve status`)
.venv/bin/espol-bot --help                # every subcommand; most are called by the plugins
.venv/bin/vinci-check smoke               # status, /estado, both pages (and /start to each subject bot with Telegram)
.venv/bin/vinci-check say "<text>"        # a message to Vinci in the captain's WhatsApp chat, and its reply
.venv/bin/vinci-check --help              # chat, press, whatsapp, page… (see the control-vinci skill)
python3 scripts/docs_check.py             # code changed without its docs, before a PR
hermes gateway status                     # also: start, stop, restart
vinci cron list                           # Vinci's poll, maintenance and 07:00 summary
tail -f ~/.hermes/logs/gateway.log        # gateway log
tail -f ~/.local/share/espol-academic-bot/bot.log   # poller, schedule and buttons log
cd relay && npx wrangler deploy           # redeploy the relay Worker
```

Data lives in `~/.local/share/espol-academic-bot/` (`espol.db`, materials, notebooks).
Each bot's memory lives in its Hermes profile under `~/.hermes/profiles/`.

## Architecture

- `src/aula_core/`: Canvas client (GET only, except a submission), sync, SQLite store, search,
  OCR, syllabus and DSpace readers.
- `src/aula/`: the `aula` CLI over `aula_core`; also a Claude Code skill (`claude/skills/aula/`).
- `src/espol_bot/`: Vinci itself: poller and alerts (`poller.py`), Telegram and WhatsApp
  (`telegram.py`, `whatsapp.py`), buttons, schedule and class briefs, notebooks and quizzes,
  the token chain (`token_renewal.py`, `token_form.py`), the Académico sign-in and its copy
  (`portal_login.py`, `academic_portal.py`), friends (`amigos.py`), the MCP server
  the bots call (`mcp_server.py`), Hermes profile setup (`hermes_setup.py`) and `vinci-check`
  (`check.py`), the CLI agents use to drive the live bots.
- `hermes/`: profile templates (personality, skills, quizzes), plugins and the WhatsApp bridge patch.
- `docs/token/`, `docs/dashboard/`, `docs/academico/`: static pages on GitHub Pages; they store nothing.
- `docs/guia/`: the user guides the README links to.
- `relay/`: Cloudflare Worker that passes encrypted webview results back to the laptop.
- `tests/e2e/`: the E2E with its fake servers, Hermes harness and fixtures.
- `scripts/`: repo maintenance (`docs_check.py`, `render_screens.sh` for the README image).
- `.claude/skills/control-vinci/`: how agents verify on the live bots, and the feature map.

## Language

Code, comments, config keys and these instructions are in English. Spanish is only for
what the student reads: bot messages, CLI output, `README.md` and `docs/guia/`. Commits and PR titles are
conventional commits in English.
