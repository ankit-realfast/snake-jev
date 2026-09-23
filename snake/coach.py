"""After each death: summarize the game, let Claude edit the prompt config
(at most two edits, each tied to an observation), replay the same seed.

Claude never plays. It only edits the bounded inputs in PromptConfig.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

from .prompt import PromptConfig

def digest(log_path: Path) -> dict:
    lines = [json.loads(l) for l in log_path.read_text().splitlines()]
    moves = [l for l in lines if l["type"] == "move"]
    end = lines[-1]

    longest_drought = drought = 0
    away_from_food = 0
    for m in moves:
        drought = 0 if m["ate"] else drought + 1
        longest_drought = max(longest_drought, drought)
        if not m["ate"] and m["path_before"] is not None and m["path_after"] is not None \
                and m["path_after"] > m["path_before"]:
            away_from_food += 1

    trapped_steps = sum(1 for m in moves if m["pockets_only"])
    tail = moves[-15:]
    death = end["death"]
    if death == "self" and any(m["pockets_only"] for m in tail):
        death = "trapped (walked into a confined area, then hit its own body)"

    confidences = [m["confidence"] for m in moves if m.get("confidence") is not None]
    return {
        "score": end["score"],
        "moves": end["moves"],
        "food_eaten": end["food_eaten"],
        "death": death,
        "space_trend_last_15": [m["space_after"] for m in tail],
        "moves_that_lengthened_path_to_food": away_from_food,
        "longest_stretch_without_food": longest_drought,
        "trapped_steps": trapped_steps,
        "low_confidence_decisions": sum(1 for c in confidences if c < 0.5),
        "decisions_asked": len(confidences),
        "last_moves": [{k: m.get(k) for k in ("n", "head", "move", "offered", "space_after",
                                              "confidence", "path_before")} for m in moves[-8:]],
    }


COACH_SYSTEM = """You coach a snake-playing decision model called Jev. Jev cannot be retrained; you can only change the inputs it sees, defined by a config.

Each move, Jev gets a text state (board and facts, controlled by the config) and one question: which direction to move, with options described according to option_style. Before Jev sees the options, code removes moves that die immediately and, depending on pocket_ratio, moves into confined areas ("pockets", space < pocket_ratio * snake length) when a roomier move exists.

Config fields you may edit:
- include_grid, include_wall_distances, include_path_hint, include_space (bool): which facts go in the state. include_path_hint reports the real shortest route around the body, rather than only straight-line distance.
- move_instruction (string): the wording of the move question. Jev reads literally; say exactly what you want.
- option_style: "plain" (just the target cell) or "consequences" (adds whether it eats, open space afterwards, distance to food).
- pocket_ratio (float 0-5): pocket filter strictness. Too strict starves the snake; too loose lets it walk into traps.

Rules: make at most two edits. Each edit must cite a specific observation from the digest. Prefer edits that address the cause of death or the biggest waste of moves. If a previous attempt made things worse, do not repeat it."""

EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(PromptConfig.editable())},
                    "value": {"type": "string"},
                    "observation": {"type": "string"},
                },
                "required": ["field", "value", "observation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["diagnosis", "edits"],
    "additionalProperties": False,
}


class Coach:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.environ["COACH_MODEL"]

    def propose(self, current: PromptConfig, game_digest: dict, history: list[dict]) -> dict:
        user = (
            f"Current config:\n{current.to_json()}\n\n"
            f"Digest of the game just played with it:\n{json.dumps(game_digest, indent=2)}\n\n"
            f"Every config tried so far and its score, oldest first:\n{json.dumps(history, indent=2)}\n\n"
            "Propose your edits."
        )
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium",
                           "format": {"type": "json_schema", "schema": EDIT_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=COACH_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(f"coach refused: {response.stop_details}")
        text = next(b.text for b in response.content if b.type == "text")
        proposal = json.loads(text)
        proposal["edits"] = proposal["edits"][:2]
        return proposal


def apply_edits(config: PromptConfig, edits: list[dict]) -> tuple[PromptConfig, list[dict]]:
    applied = []
    for edit in edits:
        try:
            config = config.with_edit(edit["field"], edit["value"])
            applied.append(edit)
        except (ValueError, KeyError) as exc:
            applied.append({**edit, "rejected": str(exc)})
    return config, applied
