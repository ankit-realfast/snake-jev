"""Plays one full game and writes one JSON line per move."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .analysis import shortest_path
from .engine import Game
from .prompt import PromptConfig, filter_moves


def play_game(player, config: PromptConfig, seed: int, log_path: Path,
              max_moves: int | None = None, starve_after: int | None = 600,
              on_move=None) -> Game:
    game = Game(seed=seed, starve_after=starve_after)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        log.write(json.dumps({"type": "start", "seed": seed, "player": player.name,
                              "config": asdict(config), "snapshot": game.snapshot()}) + "\n")
        while game.alive and (max_moves is None or game.moves < max_moves):
            decision = filter_moves(game, config)
            path_before = shortest_path(game)

            if not decision.offered:
                # No move survives. Keep going straight and die honestly.
                record = {"move": game.direction, "forced": "no_legal_moves"}
            elif len(decision.offered) == 1:
                # One option: nothing to decide, so no API call.
                record = {"move": decision.offered[0].move, "forced": "single_option"}
            else:
                record = player.choose(game, config, decision)
                offered = {m.move for m in decision.offered}
                if record["move"] not in offered:
                    # Should be impossible with a Choice, but the rig never
                    # applies an unchecked answer.
                    record["rejected"] = record["move"]
                    record["move"] = max(decision.offered, key=lambda m: m.space).move

            chosen = next((m for m in decision.all_moves if m.move == record["move"]), None)
            record.update({
                "type": "move",
                "n": game.moves + 1,
                "head": list(game.head),
                "food": list(game.food) if game.food else None,
                "offered": [m.move for m in decision.offered],
                "withheld_pockets": [m.move for m in decision.all_moves if m not in decision.offered],
                "pockets_only": decision.pockets_only,
                "space_after": chosen.space if chosen else 0,
                "path_before": path_before[0] if path_before else None,
            })
            game.step(record["move"])
            if record.get("forced") == "no_legal_moves":
                game.death = "trapped"
            path_after = shortest_path(game) if game.alive else None
            record["path_after"] = path_after[0] if path_after else None
            record["ate"] = game.moves_since_food == 0 and game.alive
            record["score"] = game.score
            log.write(json.dumps(record) + "\n")
            if on_move:
                on_move(game, record)

        if game.alive:
            game.death = "move_cap"
        log.write(json.dumps({"type": "end", "score": game.score, "moves": game.moves,
                              "food_eaten": game.food_eaten, "death": game.death,
                              "snapshot": game.snapshot()}) + "\n")
    return game
