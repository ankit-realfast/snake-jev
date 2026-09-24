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
checks, routing. Rule of thumb: use code when the rules are known, and Jev when
the call needs judgment.

## Results (seed 7, no move cap)

| Player | Score | Death | Cost per game |
|---|---|---|---|
| Claude alone, default inputs (`claude-sonnet-5`) | **1120** (3,121 moves) | trapped | $4.96 |
| Jev + Claude coach | 110 → **1050** → 930 | trapped | ~$0.05 per game + one coach call |
| Bot: shortest path, no AI | 800 | trapped | $0 |
| Jev alone, default inputs | 110, 270, 390 | starved | ~$0.05 |

Each score is one game. Coach game 1 uses the default inputs, so it also counts
as a Jev-alone game.

### Coaching

1. Jev's failures came from missing information, not bad judgment. Turning on
   the shortest-path hint took it from 110 to 1050.
2. Claude found that fix from the death digest alone. Jev's weights never changed.

### Jev's behavior

3. A decision takes about 0.4 s and about 630 input tokens, roughly $0.05 for a
   2,000-move game.
4. Jev is not deterministic. The same state and questions give slightly
   different probabilities (±0.05–0.07), and near-ties flip the chosen move.
   TypeSafe's docs say the same. Identical settings scored 110, 270 and 390, so
   gaps under about 100 points between single games can be noise.
5. Low confidence marks the coin-flip moves. Two identical seed-7 games split at
   a move where confidence was 0.0 and 0.1.

### Players compared

6. Claude alone scored the most (1120) without the path hint. Its reasons show
   it reads direction from coordinates, which uncoached Jev could not. It took
   about 1.9 s and $0.0016 a move: about 100× coached Jev's cost for about 7%
   more score.
7. The bot is naive. It looks one move ahead. A tail-reachability check or a
   Hamiltonian cycle would beat every player here. Coached Jev beat simple
   rules, not good code.

### Shared limit

8. Claude, coached Jev and the bot all died trapped, sliding down a wall into a
   corner. Better judgment or better inputs delay the trap, but no player looks
   ahead.

## Setup

Needs [uv](https://docs.astral.sh/uv/) and a terminal of at least 42×24 for the
live board. Put these in `.env`:

```
TYPESAFE_API_KEY=...
ANTHROPIC_API_KEY=...
JEV_MODEL=jev-1.13.0
COACH_MODEL=claude-sonnet-5
CLAUDE_PLAYER_MODEL=claude-sonnet-5
```

## Run

```sh
uv run python -m snake play                         # you play (arrows/WASD, q quits)
uv run python -m snake run --player bot --digest    # bot, free
uv run python -m snake run --player jev --digest    # Jev alone
uv run python -m snake run --player claude --digest # Claude alone, same inputs as Jev
uv run python -m snake coach --games 3              # Jev + Claude coach, same seed each game
uv run python -m snake replay runs/bot/<time>_seed7.jsonl
```

| Flag | Commands | Effect |
|---|---|---|
| `--seed N` | all | Food layout. Default 7. |
| `--player bot\|jev\|claude` | `run`, `coach` | Who plays. `run` defaults to `bot`, `coach` to `jev`. |
| `--config file.json` | `run`, `coach` | Start from a saved config, such as a coach `best_config.json`. |
| `--max-moves N` | `run`, `coach` | Cap a game. |
| `--starve-after N` | `run`, `coach` | End a game after N moves without food. Default 600; `0` turns it off. |
| `--games N` | `coach` | Games per session. Default 11. |
| `--digest` | `run` | Print the death digest at the end. |
| `--no-watch` | `run` | Text progress only, no live board. |
| `--tick N` | `play` | Milliseconds per move when you steer. Default 120. |

`run` and `replay` show a live board with a side panel. The panel has score,
hunger, steps to food, open space, and the current decision. For Jev that is its
probabilities as bars, and for Claude it is its reason. `space` pauses and `q`
stops.

## How it works

Math, counting and path-finding stay in code, because TypeSafe documents Jev as
weak at them. The model only makes the judgment call.

### Each move

1. Code builds the options. It drops moves into a wall or the body, and pocket
   moves (see `pocket_ratio`).
2. With one option left, it is applied without asking anyone.
3. Otherwise the player picks. The bot applies its rule. Jev or Claude gets a
   request built from the config.
4. Code re-checks the answer before applying it. An answer outside the options
   is replaced by the roomiest move and logged as `rejected`. None has occurred.
5. The move, the request and the answer are logged as one JSON line.

### Coaching loop

After each game, Claude reads a digest of it. The digest has the score, the
cause of death, the longest drought, moves away from food, trapped steps and the
count of low-confidence decisions. Claude sees the digest, the current config
and the score history, not individual moves. It returns at most 2 config edits,
each tied to an observation. The next game plays the best config so far plus
those edits, so a worse result never becomes the new baseline.

### Config

A `PromptConfig` (in `snake/prompt.py`) controls what goes into Jev's and
Claude's requests. The config itself is not sent. These are the defaults, used
whenever `--config` isn't passed, including every coach session's game 1:

```json
{
  "include_grid": true,
  "include_wall_distances": true,
  "include_path_hint": false,
  "include_space": true,
  "move_instruction": "Which direction should the snake move next?",
  "option_style": "plain",
  "pocket_ratio": 1.0
}
```

The best coached config (`runs/coach/20260923-163558_seed7/best_config.json`)
changes two fields: `"include_path_hint": true` and
`"option_style": "consequences"`.

| Field | What it controls |
|---|---|
| `include_grid` | Adds `board` and `legend` to the state. |
| `include_wall_distances` | Adds `cells_to_wall`. |
| `include_path_hint` | Adds `shortest_path_to_food` (steps and first step, routed around the body). |
| `include_space` | Adds `open_space_after_move` for each option. |
| `move_instruction` | The text of the move question. |
| `option_style` | The text of each option. |
| `pocket_ratio` | Which cramped moves are hidden from the options. |

`move_instruction` values that have been used:

- Default: `"Which direction should the snake move next?"`
- Claude's edit in an early coach test: `"Pick the direction that most reduces
  the shortest-path distance to the food, unless that direction leaves less open
  space than the snake's length; then pick the safest direction with the most
  open space."`

`option_style` for the same move-1 option:

| Style | Text for `up` |
|---|---|
| `plain` | `move up to cell [10, 9]` |
| `consequences` | `move up to cell [10, 9]; straight-line distance to food becomes 6; 398 open cells reachable afterwards` |

When a move eats the food, `consequences` says `eats the food` in place of the
distance.

`pocket_ratio`: a move is a pocket if the open space after it is less than
`pocket_ratio` × the snake's length after the move. Pockets are hidden unless
every move is a pocket. Then all moves are shown and a warning is added to the
state. This example has a snake of length 20, which is 21 after the move:

| Move | Open space after | Hidden at 0.5 (< 10.5) | at 1.0 (< 21) | at 2.0 (< 42) |
|---|---|---|---|---|
| up | 350 | no | no | no |
| left | 30 | no | no | yes |
| right | 8 | yes | yes | yes |

A lower ratio hides fewer moves, so the snake can enter traps. A higher ratio
hides more, including routes to food, so the snake can starve. The article found
an optimum: 640 when too strict, 290 when too loose, 850 in the middle. Here 1.6
scored 930 against 1050 at 1.0, one game each.

### What each player receives

**Bot.** No request. `BotPlayer` in `snake/players.py` applies this rule:

```python
path = shortest_path(game)              # BFS around the body: (steps, first_move) or None
if path and path[1] in offered:         # offered = moves left after the safety filter
    move = path[1]
else:
    move = max(decision.offered, key=lambda m: (m.space, -m.food_distance)).move
```

**Jev.** One `POST /v1/systemone` per move. Move 1 with the default config:

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

Answer: `up` 0.53, confidence 0.29. `danger` is logged and shown on the live
board, but nothing acts on it yet.

**Coached Jev.** The same request built from the best config. Its two edits
change these parts:

```jsonc
"facts": { ..., "shortest_path_to_food": {"steps": 7, "first_step": "up"} },  // include_path_hint
"criteria": {                                                                 // option_style: consequences
  "up": "move up to cell [10, 9]; straight-line distance to food becomes 6; 398 open cells reachable afterwards",
  ...
}
```

Answer: `up` 0.99, confidence 0.99.

**Claude as player.** `ClaudePlayer` sends one Messages API request per move,
with the same state and options as Jev. Move 1 with the default config:

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

**Claude as coach** gets no per-move request (see Coaching loop).

| | Bot | Jev | Coached Jev | Claude |
|---|---|---|---|---|
| API call per move | none | Jev | Jev | Claude |
| Real path to food | computed and used | not given | given (`first_step`) | not given (default config) |
| Option descriptions | none | target cell | cell, distance to food, open space | target cell |
| Danger question | none | asked, not used | asked, not used | not asked |
| Returns | a move | move, probabilities, confidence | move, probabilities, confidence | move and a reason |
| Decides the move | fixed rule | Jev | Jev | Claude |

### Code

| File | Role |
|---|---|
| `snake/engine.py` | Rules: board, moves, seeded food, death |
| `snake/analysis.py` | Exact facts: legal moves, shortest path, open space (flood fill) |
| `snake/prompt.py` | `PromptConfig`, the pocket filter, and the state and questions |
| `snake/players.py` | `BotPlayer`, `JevPlayer` (raw HTTP to `/v1/systemone`), `ClaudePlayer` |
| `snake/runner.py` | One game loop and its logging |
| `snake/coach.py` | Digest and Claude's edits (structured JSON output) |
| `snake/ui.py` | Board, side panel, pause and stop |
| `snake/__main__.py` | Commands and flags |

## Logs

- `runs/bot/`, `runs/jev/` and `runs/claude/` hold one `<time>_seed<N>.jsonl`
  per game.
- `runs/coach/<time>_seed<N>/` holds a session's `game_NN.jsonl`, `coach_NN.json`
  (the digest, Claude's proposal and the applied edits) and `best_config.json`.
- A log's first line records the seed, player and config, and in logs made
  after 2026-09-24 03:20, the starvation cap. The last line records the score, moves and
  death.

## Differences from the article

- The Jev model is pinned (`JEV_MODEL`), because `jev-latest` can move to a new model.
- The 600-move starvation cap. Without it, a circling snake never ends.
- Moves with only one safe option skip the model call.
- The article describes Jev as deterministic. It isn't (see result 4).
- The article has no Claude-alone player.
