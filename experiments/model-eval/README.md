# Model comparison for Vinci

`run.py` sends the same ten student messages to Vinci with each model given, each in a fresh `hermes chat` session
(`--source e2e-check`), and appends the reply, the tools called, the tokens and the time to a JSONL file. The prompts
only read: nothing is written to the aula or sent to a chat. The replies hold real course data, so keep the output
outside the repo:

```bash
python3 experiments/model-eval/run.py ~/.local/share/espol-academic-bot/model-eval/results.jsonl \
    claude-haiku-5-5 claude-sonnet-5-5
```

The live model is `modelo` under `[hermes]` in `config.toml`; this script never changes it.

## Run of 2026-10-13 (Haiku 5.5, the live model, vs Sonnet 5.5)

| | Haiku 5.5 | Sonnet 5.5 |
|---|---|---|
| Median time per reply | 8.0 s | 7.3 s |
| Total for the 10 prompts | 81.5 s | 82.4 s |
| Output tokens | 9 302 | 5 726 |
| Tool calls for «qué es Raft según el material» | 5 | 1 |

Both replied to «hola» and «XD» in kind, corrected a wrong due date from the data, said they cannot send an email
and left a draft, and found where an external lab is handed in. Sonnet was better where judgment mattered: it
started a 20-minute session with a plan and a first question, listed only current workshops for an ambiguous «el
taller», and said which search hit did not cover the topic. Haiku listed two workshops from a past term as pending.
