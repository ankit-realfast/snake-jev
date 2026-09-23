# Snake × Jev

A rebuild of the "What Jev Is and Isn't" experiment: Jev (TypeSafe's decision
model) picks every move, and Claude rewrites Jev's inputs after each death. The
same seed is replayed each time.

## Run

```sh
uv run python -m snake play                          # you play (arrows/WASD)
uv run python -m snake run --player bot --seed 7 --digest   # no-AI baseline, free
uv run python -m snake replay runs/bot/<time>_seed7.jsonl
uv run python -m snake run --player jev --seed 7 --digest
uv run python -m snake coach --games 3 --seed 7     # the full loop
```

Logs land in `runs/bot/` and `runs/jev/` (one file per game) and `runs/coach/`
(one folder per session: `game_NN.jsonl`, `coach_NN.json`, `best_config.json`).

Settings come from `.env`: `TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY`,
`COACH_MODEL` (e.g. `claude-sonnet-5`) and `JEV_MODEL` (e.g. `jev-1.13.0`).

## How the pieces fit (read in this order)

| File | Role | AI? |
|---|---|---|
| `snake/engine.py` | Rules: board, moves, seeded food, death | no |
| `snake/analysis.py` | Exact facts: legal moves, shortest path, open space (flood fill) | no |
| `snake/prompt.py` | `PromptConfig` (the only thing the coach can edit), pocket filter, state and question builder | no |
| `snake/players.py` | `BotPlayer` baseline; `JevPlayer` makes one Choice and one Score call per move (raw HTTP) | Jev |
| `snake/runner.py` | One game: filter, then ask, then re-check, then step, then log a JSON line | — |
| `snake/coach.py` | Death digest, then Claude proposes at most 2 edits with reasons | Claude |

Design rule, taken from TypeSafe's own notes on where Jev is weak: math, counting
and path-finding stay in code. Jev only gets the judgment call.

## Differences from the article

- The Jev model is pinned to `jev-1.13.0` so that replays on the same seed stay comparable.
- A game ends after 600 moves without food (`--starve-after`). Because Jev is
  deterministic, a snake that starts circling would otherwise circle forever.
- Moves with a single safe option are applied without calling Jev.
