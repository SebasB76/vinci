# AGENTS.md

## Purpose

Vinci is an ESPOL academic assistant on Telegram and WhatsApp, built on Hermes Agent and
the university's Canvas (aulavirtual). It has one maintainer, called "the captain" in code
and docs, and a few friends who each get their own Vinci on WhatsApp. It is a side project:
shipping speed beats ceremony, and a bug found later is fixed in a new session.

## Status (2026-10-11)

- Live: one Hermes gateway on the captain's laptop, as the systemd user service
  `hermes-gateway`. It serves `vinci`, one `vinci-<code>` profile per subject bot and one
  `amigo-<name>` profile per friend.
- Live: Telegram has Vinci (`vinci_espol_bot`) plus one bot per subject. WhatsApp has only
  Vinci, on a separate number, through Hermes's unofficial bridge.
- Live: `docs/token/`, `docs/dashboard/` and `docs/academico/` on GitHub Pages; `relay/` on Cloudflare Workers.
- Plan, not live: deploy to Coolify with an OpenAI key (branch `feat/coolify-deploy`).
  WhatsApp will probably become the main channel, which questions the one-bot-per-subject
  design that only Telegram has.
- The semester ends on 2027-01-15 (`semester_end` in `config.toml`).

## Where to start

These are entry points. Follow references anywhere the task leads.

- User-facing behavior: `README.md` (Spanish, about 1000 lines). Search it for the section
  you need instead of reading it whole.
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
4. In `~/Projects/espol-academic-bot`: `git pull && ./setup.sh`.
5. `hermes gateway restart`, then `.venv/bin/espol-bot doctor`.
6. `.venv/bin/vinci-check smoke` (about 45 s), plus a `vinci-check chat` or `press` that
   exercises the change itself.
7. Report only what still needs the captain's phone: WhatsApp replies and iPhone webviews.

## Working rules

- `~/Projects/espol-academic-bot` is the live install: `setup.sh` writes its own path into
  the Hermes profiles and the `.venv` is an editable install. Work in a git worktree, never
  switch branches there, and never run `setup.sh` from a worktree.
- E2E (one test, 7 to 17 minutes): never run it at the start of a session or to "check the
  baseline". Skip it for small changes (copy, `SOUL.md`, `config.toml`, about 50 lines). For a
  behavior change, run it once at the end, and never rerun it for a one-line fix. The captain
  asked for this 12 times; the README's contributing rule is for outside contributors.
- No unit tests and no extra review rounds.
- "Improve the project" means features the student notices, not refactors.
- For a new feature idea, restate the goal and the user flow in 3 to 5 lines, then build it.
  When the captain already gave the flow, build it directly.
- Test with the real bots through `vinci-check`. The captain allows test messages to his own
  Vinci and subject bots; `vinci-check` refuses any other chat. When he sends a screenshot of
  a bot chat, also read that chat (`vinci-check chat`/`whatsapp`) for the full thread.
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
| What a bot does or says (commands, buttons, alerts) | its `README.md` section + its row in the feature map |
| A slash command (new, renamed, removed) | README «Comandos» (and the WhatsApp table) + feature map |
| Telegram vs WhatsApp support of a feature | the first table of the feature map |
| A multi-step flow (`/token`, dashboard, Académico) | its file in `.claude/skills/control-vinci/references/features/` |
| A bot's personality or rules | `hermes/<profile>/SOUL.md` or `SKILL.md` |
| A config key | its comment in `config.toml` + README «Configuración» |
| A secret | `secrets.env.example` + README «Completa `secrets.env`» |
| What `setup.sh` touches outside the repo | the header of `setup.sh` + README «Actualizar y desinstalar» |
| A `vinci-check` command | `.claude/skills/control-vinci/SKILL.md` |
| What runs live, or a command here | «Status» or «Commands» in this file |
| A known limit (fixed or new) | README «Límites conocidos» |

## Do not re-propose

- firstmate to supervise work on this repo: the captain removed it (2026-10).
- The no-mistakes pipeline: it is blocked in the captain's settings.
- A test profile or test bots instead of the real ones.

## Commands

```bash
uv sync                                   # dependencies, dev included
uv run pytest                             # the E2E (fake Canvas, fake Telegram, real Hermes)
./setup.sh                                # install or update profiles, crons, `aula`; sends a test message
./setup.sh --skip-deps --sin-pruebas      # same, without touching .venv or calling Canvas/Telegram
.venv/bin/espol-bot doctor                # poller, Canvas sync, token chain and feeds (read-only)
.venv/bin/espol-bot academico             # what the Académico copy holds (read-only)
.venv/bin/espol-bot --help                # every subcommand; most are called by the plugins
.venv/bin/vinci-check smoke               # status, /estado, /start to each subject bot, both pages
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
- `relay/`: Cloudflare Worker that passes encrypted webview results back to the laptop.
- `tests/e2e/`: the E2E with its fake servers, Hermes harness and fixtures.
- `scripts/`: repo maintenance (`docs_check.py`).
- `.claude/skills/control-vinci/`: how agents verify on the live bots, and the feature map.

## Language

Code, comments, config keys and these instructions are in English. Spanish is only for
what the student reads: bot messages, CLI output and `README.md`. Commits and PR titles are
conventional commits in English.
