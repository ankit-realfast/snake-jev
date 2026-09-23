# Snake × Jev

Snake played by [Jev](https://docs.typesafe.ai/introduction), TypeSafe's decision
model, and coached by Claude. It rebuilds the experiment from
["What Jev Is and Isn't"](https://www.linkedin.com/pulse/what-jev-isnt-how-use-surendran-balachandran-cmuhe/).

## Why snake

Snake is a test lab for Jev, not a contest Jev is meant to win. Good code can
solve snake completely, so beating well-written rules is not the goal.

Snake is useful because every decision can be checked:

- The score is an exact number, so no human judge is needed.
- Seeded food means every game can be replayed.
- A game has thousands of decisions and takes minutes to play, for cents.
- The best possible score is known: 3,970, which fills the board.

The goal is to learn how Jev behaves and whether a coaching loop improves it.
Then the same loop can be used where no rules exist: ticket urgency, policy
checks, routing. Rule of thumb: use code when the rules are
known, and Jev when the call needs judgment.

## Results (seed 7, no move cap)

| Player | Score | Death |
|---|---|---|
| Bot: shortest path, no AI | 800 | trapped |
| Jev alone, default inputs | 270, 110 | starved |
| Jev + Claude coach | 110 → **1050** → 930 | trapped |

What the runs showed:

1. Jev takes about 0.4 s and about 630 input tokens per decision, roughly $0.05 for a 2,000-move game.
2. Jev's failures came from missing information, not bad judgment. Turning on
   the shortest-path hint took it from 110 to 1050.
3. Claude found that fix from the death digest alone. Jev's weights never changed.
4. Jev is not deterministic. The same state and questions give slightly
   different probabilities (±0.05–0.07), and near-ties flip the chosen move.
   TypeSafe's docs say the same. One game per config is therefore noisy.
5. Low confidence marked the coin-flip moves. The two seed-7 games split at a
   move where confidence was 0.0 and 0.1.
6. The bot is naive. It looks one move ahead, and a tail-reachability check or a
   Hamiltonian cycle would beat coached Jev. Coached Jev beat simple rules,
   not good code.

## Run

```sh
uv run python -m snake play                         # you play (arrows/WASD, q quits)
uv run python -m snake run --player bot --digest    # baseline, free
uv run python -m snake run --player jev --digest    # Jev alone
uv run python -m snake coach --games 3              # Jev + Claude, same seed each game
uv run python -m snake replay runs/bot/<time>_seed7.jsonl
```

- `--seed N` sets the food layout. The default is 7.
- `--max-moves N` caps a game.
- `--starve-after N` ends a game after N moves without food. The default is 600;
  `0` turns it off.
- `--config file.json` starts from saved settings, for example a coach `best_config.json`.

Set these in `.env`:

```
TYPESAFE_API_KEY=...
ANTHROPIC_API_KEY=...
COACH_MODEL=claude-sonnet-5
JEV_MODEL=jev-1.13.0
```

## How it works

Each move:

1. Code removes moves into walls or the body. It also withholds pocket moves
   (open space < `pocket_ratio` × length) when a roomier move exists.
2. Jev is asked one Choice (which direction) and one Score (how dangerous). The
   state holds whatever facts `PromptConfig` turns on.
3. Code re-checks Jev's answer before applying it.
4. Everything is logged as one JSON line.

After each game, Claude reads a digest of it. The digest holds the score, the
cause of death, the longest drought, moves away from food, and low-confidence
count. Claude proposes
at most 2 edits to `PromptConfig`, each tied to an observation. The next game
plays the best config so far plus those edits. A worse result never becomes the
new baseline.

| File | Role |
|---|---|
| `snake/engine.py` | Rules: board, moves, seeded food, death |
| `snake/analysis.py` | Exact facts: legal moves, shortest path, open space (flood fill) |
| `snake/prompt.py` | `PromptConfig` (the only thing the coach edits), pocket filter, Jev state and questions |
| `snake/players.py` | `BotPlayer`; `JevPlayer` (raw HTTP to `/v1/systemone`) |
| `snake/runner.py` | One game loop and its logging |
| `snake/coach.py` | Digest and Claude's edits (structured JSON output) |

Math, counting and path-finding stay in code, because TypeSafe documents Jev as
weak at them. Jev only makes the judgment call.

## Logs

- `runs/bot/` and `runs/jev/` hold one `<time>_seed<N>.jsonl` per game.
- `runs/coach/<time>_seed<N>/` holds a session's `game_NN.jsonl`, `coach_NN.json`
  (the digest, Claude's proposal and the applied edits) and `best_config.json`.

## Differences from the article

- The Jev model is pinned (`JEV_MODEL`), because `jev-latest` can move to a new model.
- The 600-move starvation cap. Without it, a circling snake never ends.
- Moves with only one safe option skip the Jev call.
- The article describes Jev as deterministic. It isn't (see result 4).
