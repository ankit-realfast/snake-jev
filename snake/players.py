"""Players pick a move from the options the filter allows. The rig, not the
player, owns safety: whatever a player answers is re-checked before use."""

from __future__ import annotations

import os
import time

import httpx

from .analysis import shortest_path
from .engine import Game
from .prompt import Decision, PromptConfig, build_questions, build_state

JEV_URL = "https://api.typesafe.ai/v1/systemone"


class BotPlayer:
    """Baseline with no AI: follow the shortest path if the filter allows
    that step, otherwise take the roomiest option."""

    name = "bot"

    def choose(self, game: Game, config: PromptConfig, decision: Decision) -> dict:
        offered = {m.move: m for m in decision.offered}
        path = shortest_path(game)
        if path and path[1] in offered:
            move = path[1]
        else:
            move = max(decision.offered, key=lambda m: (m.space, -m.food_distance)).move
        return {"move": move}


class JevPlayer:
    """Asks Jev one Choice (which way) and one Score (how dangerous) per move.

    Uses the raw HTTP API rather than the SDK so the request and response
    are visible in the logs exactly as sent.
    """

    name = "jev"

    def __init__(self, max_retries: int = 6):
        # Pin a version (jev-1.13.0), not jev-latest: an alias can move under
        # us and break same-seed comparisons between runs.
        self.model = os.environ["JEV_MODEL"]
        self.max_retries = max_retries
        self.http = httpx.Client(
            timeout=30,
            headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"},
        )

    def ask(self, state: dict, questions: dict) -> tuple[dict, float]:
        body = {"model": self.model, "state": state, "questions": questions}
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            resp = self.http.post(JEV_URL, json=body)
            latency = time.perf_counter() - start
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self.max_retries:
                    resp.raise_for_status()
                wait = float(resp.headers.get("retry-after", 2 ** attempt))
                time.sleep(min(wait, 30))
                continue
            resp.raise_for_status()
            return resp.json(), latency
        raise RuntimeError("unreachable")

    def choose(self, game: Game, config: PromptConfig, decision: Decision) -> dict:
        state = build_state(game, config, decision)
        questions = build_questions(config, decision)
        data, latency = self.ask(state, questions)
        move_answer = data["answers"]["move"]
        danger = data["answers"].get("danger", {})
        return {
            "move": move_answer["choice"],
            "probabilities": move_answer.get("probabilities"),
            "confidence": move_answer.get("confidence"),
            "danger": danger.get("score"),
            "latency_s": round(latency, 3),
            "usage": data.get("usage"),
            "model": data.get("model"),
            "state": state,
            "questions": questions,
        }
