"""Players pick a move from the options the filter allows. The rig, not the
player, owns safety: whatever a player answers is re-checked before use."""

from __future__ import annotations

import json
import os
import time

import anthropic
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


CLAUDE_SYSTEM = """You play snake on a 20x20 board. Each turn you get the board state and a question with the allowed moves. Moves that would kill the snake immediately have already been removed. Pick the one move that best keeps the snake alive and eats food. Answer with the move and a reason of at most 12 words."""


class ClaudePlayer:
    """Claude picks every move. It gets the same state and options Jev gets,
    so the only difference between the two players is the model."""

    name = "claude"

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.environ["CLAUDE_PLAYER_MODEL"]

    def choose(self, game: Game, config: PromptConfig, decision: Decision) -> dict:
        state = build_state(game, config, decision)
        question = build_questions(config, decision)["move"]
        schema = {
            "type": "object",
            "properties": {
                "move": {"type": "string", "enum": list(question["criteria"])},
                "reason": {"type": "string"},
            },
            "required": ["move", "reason"],
            "additionalProperties": False,
        }
        prompt = (f"State:\n{json.dumps(state)}\n\n"
                  f"Question: {question['instructions']}\n"
                  f"Options:\n{json.dumps(question['criteria'], indent=1)}")

        start = time.perf_counter()
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=CLAUDE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        latency = time.perf_counter() - start

        record = {"latency_s": round(latency, 3), "model": response.model,
                  "usage": {"input_tokens": response.usage.input_tokens,
                            "output_tokens": response.usage.output_tokens},
                  "state": state, "questions": {"move": question}}
        if response.stop_reason == "refusal":
            # The rig replaces any answer outside the options with the roomiest move.
            return {**record, "move": None, "reason": "refused"}
        answer = json.loads(next(b.text for b in response.content if b.type == "text"))
        return {**record, "move": answer["move"], "reason": answer["reason"]}


class LayaPlayer:
    """Laya, an open-source local model with Jev's question types. It gets the
    exact request Jev gets and runs on this machine, so there is no API cost."""

    name = "laya"

    def __init__(self):
        from laya import Router
        # The multilingual checkpoint accepts long inputs; the state is ~350 of
        # its tokens, and max_len leaves headroom as the snake grows.
        self.model = "multilingual"
        self.router = Router(default=self.model)

    def choose(self, game: Game, config: PromptConfig, decision: Decision) -> dict:
        state = build_state(game, config, decision)
        questions = build_questions(config, decision)
        start = time.perf_counter()
        data = self.router.predict(state, questions, model=self.model, max_len=2048)
        latency = time.perf_counter() - start
        move_answer = data["answers"]["move"]
        return {
            "move": move_answer["choice"],
            "probabilities": move_answer.get("probabilities"),
            "confidence": move_answer.get("confidence"),
            "danger": data["answers"].get("danger", {}).get("score"),
            "latency_s": round(latency, 3),
            "usage": data.get("usage"),
            "model": data.get("routing", {}).get("repo"),
            "state": state,
            "questions": questions,
        }
