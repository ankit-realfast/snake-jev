"""Deterministic facts about a position. Everything here is exact math that
code can do better than a model (see TypeSafe's jaggedness notes), so the
model is only ever asked the judgment part.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .engine import DIRS, OPPOSITE, Cell, Game, shift


def neighbors(cell: Cell, size: int):
    for move in DIRS:
        nxt = shift(cell, move)
        if 0 <= nxt[0] < size and 0 <= nxt[1] < size:
            yield move, nxt


def simulate(game: Game, move: str) -> tuple[list[Cell], bool] | None:
    """Body after `move`, and whether it ate. None if the move kills."""
    new_head = shift(game.head, move)
    if not game.in_bounds(new_head):
        return None
    eating = new_head == game.food
    body = list(game.body)
    blocking = set(body) if eating else set(body[:-1])
    if new_head in blocking:
        return None
    new_body = [new_head] + (body if eating else body[:-1])
    return new_body, eating


def open_space(body: list[Cell], size: int) -> int:
    """Cells reachable from the head, not counting the head itself.

    The article's harness had a bug here: it counted cells reachable
    *through* the head, reporting 372 open cells for a 12-cell pocket. We
    start the search at the head but never count it, and treat every body
    cell except the tail as a wall (the tail frees up next move).
    """
    head = body[0]
    walls = set(body[:-1])
    seen = {head}
    queue = deque([head])
    count = 0
    while queue:
        cell = queue.popleft()
        for _, nxt in neighbors(cell, size):
            if nxt not in seen and nxt not in walls:
                seen.add(nxt)
                count += 1
                queue.append(nxt)
    return count


def shortest_path(game: Game) -> tuple[int, str] | None:
    """(steps, first move) along the shortest route to food around the body,
    or None if the body blocks every route right now."""
    if game.food is None:
        return None
    walls = set(list(game.body)[:-1])
    seen = {game.head}
    queue = deque([(game.head, 0, None)])
    while queue:
        cell, dist, first = queue.popleft()
        for move, nxt in neighbors(cell, game.size):
            if nxt in seen or nxt in walls:
                continue
            step_first = first or move
            if nxt == game.food:
                return dist + 1, step_first
            seen.add(nxt)
            queue.append((nxt, dist + 1, step_first))
    return None


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@dataclass
class MoveInfo:
    move: str
    target: Cell
    eats: bool
    space: int           # open cells after the move
    food_distance: int   # straight-line distance to food after the move
    pocket: bool = False


def evaluate_moves(game: Game) -> list[MoveInfo]:
    """Every move that does not die immediately, with its consequences.
    Reversal is excluded: it is always a self-collision."""
    infos = []
    for move in DIRS:
        if move == OPPOSITE[game.direction]:
            continue
        result = simulate(game, move)
        if result is None:
            continue
        body, eats = result
        food = game.food if not eats else body[0]
        infos.append(MoveInfo(
            move=move,
            target=body[0],
            eats=eats,
            space=open_space(body, game.size),
            food_distance=manhattan(body[0], food) if food else 0,
        ))
    return infos


def wall_distances(game: Game) -> dict[str, int]:
    x, y = game.head
    return {"up": y, "down": game.size - 1 - y, "left": x, "right": game.size - 1 - x}
