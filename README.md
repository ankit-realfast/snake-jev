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
uv run python -m snake run --player claude --digest # Claude alone, same inputs as Jev
uv run python -m snake coach --games 3              # Jev + Claude, same seed each game
uv run python -m snake replay runs/bot/<time>_seed7.jsonl
```

- `--seed N` sets the food layout. The default is 7.
- `--max-moves N` caps a game.
- `--starve-after N` ends a game after N moves without food. The default is 600;
  `0` turns it off.
- `--config file.json` starts from saved settings, for example a coach `best_config.json`.
- `run` and `replay` show a live board with a side panel: score, hunger, steps to
  food, open space and Jev's probabilities as bars. Keys: `space` pauses, `q`
  stops. `--no-watch` gives text only.
- `play --tick N` sets how fast the snake moves when you steer (ms per move,
  default 120).

Set these in `.env`:

```
TYPESAFE_API_KEY=...
ANTHROPIC_API_KEY=...
COACH_MODEL=claude-sonnet-5
JEV_MODEL=jev-1.13.0
CLAUDE_PLAYER_MODEL=claude-sonnet-5
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

### What each player receives

The bot gets no payload. It is code that reads the game and applies its rule:
shortest path, otherwise the roomiest move (`BotPlayer` in `snake/players.py`):

```python
path = shortest_path(game)              # BFS around the body: (steps, first_move) or None
if path and path[1] in offered:         # offered = moves left after the safety filter
    move = path[1]
else:
    move = max(decision.offered, key=lambda m: (m.space, -m.food_distance)).move
```

Jev gets one request per move. This is move 1 with default settings:

```jsonc
{
  "model": "jev-1.13.0",
  "state": {
    "facts": {
      "head": [10, 10], "direction": "right", "length": 3, "score": 0,
      "food": [5, 8],
      "straight_line_distance_to_food": 7,
      "coordinates": "x grows to the right, y grows downward; up means y-1",
      "cells_to_wall": {"up": 10, "down": 9, "left": 10, "right": 9},
      "open_space_after_move": {"up": 398, "down": 398, "right": 398}
    },
    "board": "<20 rows of . H o T F>",
    "legend": "H head, o body, T tail, F food, . empty"
  },
  "questions": {
    "move": {
      "type": "choice",
      "instructions": "Which direction should the snake move next?",
      "criteria": {
        "up": "move up to cell [10, 9]",
        "down": "move down to cell [10, 11]",
        "right": "move right to cell [11, 10]"
      }
    },
    "danger": {
      "type": "score",
      "instructions": "How close is the snake to trapping itself?",
      "criteria": ["Safe: plenty of open space around the head",
                   "Some risk: space is getting tight",
                   "Trapped or nearly trapped"]
    }
  }
}
```

Answer: `up` 0.53, confidence 0.29.

Coached Jev gets the same request with the coach's edits applied. In the best
config (coach game 2) there are two of them:

```jsonc
"facts": { ..., "shortest_path_to_food": {"steps": 7, "first_step": "up"} },  // include_path_hint
"criteria": {                                                                 // option_style: consequences
  "up": "move up to cell [10, 9]; straight-line distance to food becomes 6; 398 open cells reachable afterwards",
  ...
}
```

Answer: `up` 0.99, confidence 0.99.

As coach, Claude never sees individual moves. After each game it gets the
current config, the digest and the score history, and returns at most 2 edits.

Claude as a player (`--player claude`, `ClaudePlayer`) gets one Messages API
request per move. This is move 1 with default settings:

```jsonc
{
  "model": "claude-sonnet-5",
  "max_tokens": 4000,
  "thinking": {"type": "adaptive"},
  "output_config": {
    "effort": "low",
    "format": {"type": "json_schema", "schema": {
      "type": "object",
      "properties": {
        "move": {"type": "string", "enum": ["up", "down", "right"]},
        "reason": {"type": "string"}
      },
      "required": ["move", "reason"],
      "additionalProperties": false
    }}
  },
  "betas": ["server-side-fallback-2026-07-01"],
  "fallbacks": "default",
  "system": "You play snake on a 20x20 board. Each turn you get the board state and a question with the allowed moves. Moves that would kill the snake immediately have already been removed. Pick the one move that best keeps the snake alive and eats food. Answer with the move and a reason of at most 12 words.",
  "messages": [{"role": "user", "content": "State:\n{\"facts\": {\"head\": [10, 10], \"direction\": \"right\", \"length\": 3, \"score\": 0, \"food\": [5, 8], \"straight_line_distance_to_food\": 7, \"coordinates\": \"x grows to the right, y grows downward; up means y-1\", \"cells_to_wall\": {\"up\": 10, \"down\": 9, \"left\": 10, \"right\": 9}, \"open_space_after_move\": {\"up\": 398, \"down\": 398, \"right\": 398}}, \"board\": \"<20 rows of . H o T F>\", \"legend\": \"H head, o body, T tail, F food, . empty\"}\n\nQuestion: Which direction should the snake move next?\nOptions:\n{\n \"up\": \"move up to cell [10, 9]\",\n \"down\": \"move down to cell [10, 11]\",\n \"right\": \"move right to cell [11, 10]\"\n}"}]
}
```

Answer: `{"move": "up", "reason": "Moves toward food, decreasing distance while avoiding walls."}`
at 675 input and 35 output tokens, 2.2 s.

| | Bot | Jev | Coached Jev | Claude |
|---|---|---|---|---|
| API call per move | none | Jev | Jev | Claude |
| Real path to food | computed and used | not given | given (`first_step`) | not given (default config) |
| Option descriptions | none | target cell | cell, distance to food, open space | target cell |
| Danger question | none | asked, not used | asked, not used | not asked |
| Returns | a move | move, probabilities, confidence | move, probabilities, confidence | move and a reason |
| Decides the move | fixed rule | Jev | Jev | Claude |

`danger` is logged and shown on the live board. Nothing acts on it yet.

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
