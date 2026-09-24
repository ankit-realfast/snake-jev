"""The bounded inputs the coach is allowed to edit, and how they turn a game
position into a Jev request (state + questions).

Jev's weights never change. Everything that changes between experiments
lives in PromptConfig, so a score difference between two runs on the same
seed can be traced to a config difference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields

from .analysis import MoveInfo, evaluate_moves, manhattan, shortest_path, wall_distances
from .engine import Game


@dataclass
class PromptConfig:
    # Which facts go into the state.
    include_grid: bool = True
    include_wall_distances: bool = True
    include_path_hint: bool = False   # the article's biggest single win; off at start
    include_space: bool = True
    # How the question is worded.
    move_instruction: str = "Which direction should the snake move next?"
    # How the options are described: "plain" names the cell, "consequences"
    # adds what the move leads to (eats food, open space, distance to food).
    option_style: str = "plain"
    # Pocket filter strictness: withhold a move when the space it leaves is
    # smaller than pocket_ratio * snake length, if a roomier move exists.
    pocket_ratio: float = 1.0

    @classmethod
    def editable(cls) -> dict[str, str]:
        """Field name -> type name, for the coach's schema."""
        return {f.name: f.type for f in fields(cls)}

    def with_edit(self, name: str, raw: str) -> "PromptConfig":
        kind = self.editable()[name]
        if kind == "bool":
            value = raw.strip().lower() in ("true", "1", "yes", "on")
        elif kind == "float":
            value = max(0.0, min(float(raw), 5.0))
        elif name == "option_style":
            if raw not in ("plain", "consequences"):
                raise ValueError(f"option_style must be plain or consequences, got {raw!r}")
            value = raw
        else:
            value = raw
        return PromptConfig(**{**asdict(self), name: value})

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def label(self) -> str:
        """Short name for log files: "default", or the changes from the
        defaults joined with "+", e.g. "path_hint+consequences". A rewritten
        move_instruction becomes "instr-" plus a hash of its text."""
        default, parts = PromptConfig(), []
        if self.include_grid != default.include_grid:
            parts.append("no_grid")
        if self.include_wall_distances != default.include_wall_distances:
            parts.append("no_walls")
        if self.include_path_hint != default.include_path_hint:
            parts.append("path_hint")
        if self.include_space != default.include_space:
            parts.append("no_space")
        if self.move_instruction != default.move_instruction:
            parts.append("instr-" + hashlib.sha1(self.move_instruction.encode()).hexdigest()[:6])
        if self.option_style != default.option_style:
            parts.append(self.option_style)
        if self.pocket_ratio != default.pocket_ratio:
            parts.append(f"pocket{self.pocket_ratio:g}")
        return "+".join(parts) or "default"


@dataclass
class Decision:
    """What the filter hands the player: the options Jev is allowed to see."""
    offered: list[MoveInfo]
    all_moves: list[MoveInfo]
    pockets_only: bool  # every legal move was a pocket, so the filter stood down


def filter_moves(game: Game, config: PromptConfig) -> Decision:
    moves = evaluate_moves(game)
    length_after = len(game.body) + 1
    for m in moves:
        m.pocket = m.space < config.pocket_ratio * length_after
    roomy = [m for m in moves if not m.pocket]
    return Decision(offered=roomy or moves, all_moves=moves, pockets_only=bool(moves) and not roomy)


def render_grid(game: Game) -> str:
    rows = []
    body = list(game.body)
    for y in range(game.size):
        row = []
        for x in range(game.size):
            c = (x, y)
            if c == game.head:
                row.append("H")
            elif c == body[-1]:
                row.append("T")
            elif c in body:
                row.append("o")
            elif c == game.food:
                row.append("F")
            else:
                row.append(".")
        rows.append("".join(row))
    return "\n".join(rows)


def build_state(game: Game, config: PromptConfig, decision: Decision) -> dict:
    facts: dict = {
        "head": list(game.head),
        "direction": game.direction,
        "length": len(game.body),
        "score": game.score,
        "food": list(game.food) if game.food else None,
        "straight_line_distance_to_food": manhattan(game.head, game.food) if game.food else None,
        "coordinates": "x grows to the right, y grows downward; up means y-1",
    }
    if config.include_wall_distances:
        facts["cells_to_wall"] = wall_distances(game)
    if config.include_path_hint:
        path = shortest_path(game)
        facts["shortest_path_to_food"] = (
            {"steps": path[0], "first_step": path[1]} if path
            else "no route: the body currently blocks every path to the food"
        )
    if config.include_space:
        facts["open_space_after_move"] = {m.move: m.space for m in decision.offered}
    if decision.pockets_only:
        facts["warning"] = "every available move leads into a confined area; pick the one with the most space"

    state: dict = {"facts": facts}
    if config.include_grid:
        state["board"] = render_grid(game)
        state["legend"] = "H head, o body, T tail, F food, . empty"
    return state


def describe_option(m: MoveInfo, style: str) -> str:
    text = f"move {m.move} to cell {list(m.target)}"
    if style == "consequences":
        bits = ["eats the food" if m.eats else f"straight-line distance to food becomes {m.food_distance}",
                f"{m.space} open cells reachable afterwards"]
        text += "; " + "; ".join(bits)
    return text


def build_questions(config: PromptConfig, decision: Decision) -> dict:
    return {
        "move": {
            "type": "choice",
            "instructions": config.move_instruction,
            "criteria": {m.move: describe_option(m, config.option_style) for m in decision.offered},
        },
        "danger": {
            "type": "score",
            "instructions": "How close is the snake to trapping itself?",
            "criteria": [
                "Safe: plenty of open space around the head",
                "Some risk: space is getting tight",
                "Trapped or nearly trapped",
            ],
        },
    }
