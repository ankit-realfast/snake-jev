"""The game itself: a 20x20 board, one food cell, seeded food sequence.

Coordinates are (x, y) with (0, 0) at the top-left. y grows downward, so
"up" means y - 1. The engine knows nothing about players or AI; it only
applies moves and reports what happened.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

Cell = tuple[int, int]

DIRS: dict[str, Cell] = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
POINTS_PER_FOOD = 10


def shift(cell: Cell, move: str) -> Cell:
    dx, dy = DIRS[move]
    return (cell[0] + dx, cell[1] + dy)


@dataclass
class Game:
    size: int = 20
    seed: int = 0
    # Stop a run that has gone this many moves without eating. Jev is
    # deterministic, so a snake that starts circling would otherwise circle
    # forever. None disables it.
    starve_after: int | None = 600

    body: deque[Cell] = field(init=False)  # body[0] is the head, body[-1] the tail
    direction: str = field(init=False, default="right")
    food: Cell | None = field(init=False, default=None)
    score: int = field(init=False, default=0)
    moves: int = field(init=False, default=0)
    food_eaten: int = field(init=False, default=0)
    moves_since_food: int = field(init=False, default=0)
    alive: bool = field(init=False, default=True)
    death: str | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        mid = self.size // 2
        self.body = deque([(mid, mid), (mid - 1, mid), (mid - 2, mid)])
        # Food positions depend only on the seed and the board, so the same
        # seed + the same moves always produce the same game.
        self._rng = random.Random(self.seed)
        self.food = self._spawn_food()

    @property
    def head(self) -> Cell:
        return self.body[0]

    def in_bounds(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.size and 0 <= cell[1] < self.size

    def _spawn_food(self) -> Cell | None:
        occupied = set(self.body)
        free = [(x, y) for y in range(self.size) for x in range(self.size) if (x, y) not in occupied]
        return self._rng.choice(free) if free else None

    def step(self, move: str) -> None:
        """Advance one move. Reversing into your own neck is treated as a
        self-collision, same as walking into any other body cell."""
        if not self.alive:
            raise RuntimeError("game is over")

        new_head = shift(self.head, move)
        eating = new_head == self.food
        # The tail moves out of the way this turn unless we grow, so its
        # cell is safe to enter.
        blocking = set(self.body) if eating else set(list(self.body)[:-1])

        self.moves += 1
        self.direction = move

        if not self.in_bounds(new_head):
            return self._die("wall")
        if new_head in blocking:
            return self._die("self")

        self.body.appendleft(new_head)
        if eating:
            self.score += POINTS_PER_FOOD
            self.food_eaten += 1
            self.moves_since_food = 0
            self.food = self._spawn_food()
            if self.food is None:
                return self._die("board_full")
        else:
            self.body.pop()
            self.moves_since_food += 1
            if self.starve_after and self.moves_since_food >= self.starve_after:
                return self._die("starved")

    def _die(self, reason: str) -> None:
        self.alive = False
        self.death = reason

    def snapshot(self) -> dict:
        return {
            "body": [list(c) for c in self.body],
            "food": list(self.food) if self.food else None,
            "direction": self.direction,
            "score": self.score,
            "moves": self.moves,
        }
