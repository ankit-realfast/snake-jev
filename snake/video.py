"""Render the best game from each player folder side by side as one GIF.
A GIF plays inline in a GitHub README, which an MP4 does not.

All panels share one clock: a frame at move t shows move t on every board. A
player whose game has ended freezes on its last position and shows how it died.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .engine import Game

PLAYERS = ("bot", "jev", "claude", "laya")   # coach sessions are left out on purpose

COLORS = {
    "bg": (13, 17, 23), "grid": (22, 27, 34), "border": (48, 54, 61),
    "body": (63, 185, 80), "tail": (38, 120, 52), "head": (227, 179, 65),
    "food": (248, 81, 73), "text": (230, 237, 243), "dim": (139, 148, 158),
}


def load(path: Path) -> dict:
    lines = [json.loads(l) for l in path.read_text().splitlines()]
    end = lines[-1] if lines[-1]["type"] == "end" else None
    return {"path": path, "start": lines[0], "end": end,
            "moves": [l["move"] for l in lines if l["type"] == "move"]}


def best_game(folder: Path) -> dict | None:
    """Highest final score; ties go to the most recent log."""
    games = [g for g in (load(p) for p in sorted(folder.glob("*.jsonl"))) if g["end"]]
    return max(games, key=lambda g: (g["end"]["score"], g["path"].name)) if games else None


def config_label(path: Path) -> str:
    # Logs are named <time>_seed<N>_<config>.jsonl
    parts = path.stem.split("_", 2)
    return parts[2] if len(parts) == 3 else "default"


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow < 10.1 has one fixed-size default font
        return ImageFont.load_default()


class Renderer:
    """Draws all panels for one moment in time. `cell` sets the scale."""

    def __init__(self, states, cell: int):
        self.states, self.cell = states, cell
        self.board = 20 * cell
        self.pad = cell + 4
        self.header = int(cell * 5)
        self.footer = int(cell * 2.6)
        self.width = self.pad + len(states) * (self.board + self.pad)
        self.height = self.header + self.board + self.footer
        self.big, self.small = font(int(cell * 1.6)), font(int(cell * 1.2))
        self.games = [Game(seed=g["start"]["seed"], starve_after=None) for _, g in states]
        self.applied = [0] * len(states)

    def frame(self, now: int) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), COLORS["bg"])
        d = ImageDraw.Draw(img)
        for i, (player, g) in enumerate(self.states):
            game = self.games[i]
            # Replay moves up to `now`. The fatal move never changes the board.
            while self.applied[i] < min(now, len(g["moves"])) and game.alive:
                game.step(g["moves"][self.applied[i]])
                self.applied[i] += 1
            self._panel(d, self.pad + i * (self.board + self.pad), player, g, game, now)
        return img

    def _panel(self, d, x0, player, g, game, now):
        c, top = self.cell, self.header
        d.text((x0, int(c * 0.6)), player.upper(), fill=COLORS["text"], font=self.big)
        d.text((x0, int(c * 2.7)), config_label(g["path"]), fill=COLORS["dim"], font=self.small)
        d.rectangle([x0 - 1, top - 1, x0 + self.board, top + self.board], outline=COLORS["border"])
        for y in range(20):
            for x in range(20):
                if (x + y) % 2 == 0:
                    d.rectangle([x0 + x * c, top + y * c, x0 + x * c + c - 1, top + y * c + c - 1],
                                fill=COLORS["grid"])
        body = list(game.body)
        cells = [(p, "body") for p in body[1:-1]] + [(body[-1], "tail"), (body[0], "head")]
        if game.food:
            cells.append((game.food, "food"))
        inset = max(1, c // 9)
        for (cx, cy), kind in cells:
            d.rectangle([x0 + cx * c + inset, top + cy * c + inset,
                         x0 + cx * c + c - 1 - inset, top + cy * c + c - 1 - inset], fill=COLORS[kind])
        y = top + self.board + int(c * 0.6)
        d.text((x0, y), f"move {min(now, len(g['moves']))}", fill=COLORS["dim"], font=self.small)
        d.text((x0 + int(self.board * 0.42), y), f"score {game.score}", fill=COLORS["text"], font=self.small)
        if now >= len(g["moves"]):
            label = g["end"]["death"]
            w = d.textlength(label, font=self.small)
            d.text((x0 + self.board - w, y), label, fill=COLORS["food"], font=self.small)


def pick_games(runs: Path) -> list:
    states = [(p, g) for p in PLAYERS if (runs / p).exists() and (g := best_game(runs / p))]
    if not states:
        raise SystemExit("no finished games in runs/bot, runs/jev, runs/claude or runs/laya")
    return states


def ticks(states, step: int) -> list[int]:
    longest = max(len(g["moves"]) for _, g in states)
    return list(range(0, longest, step)) + [longest]


def write_gif(runs: Path, out: Path, step: int = 4, fps: int = 15, hold_s: float = 3.0) -> dict:
    states = pick_games(runs)
    r = Renderer(states, cell=13)
    palette = Image.new("P", (1, 1))
    flat = [v for rgb in COLORS.values() for v in rgb]
    palette.putpalette(flat + [0] * (768 - len(flat)))
    frames = [r.frame(now).quantize(palette=palette, dither=Image.Dither.NONE) for now in ticks(states, step)]
    ms = round(1000 / fps)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:], loop=0, optimize=True,
                   duration=[ms] * (len(frames) - 1) + [int(hold_s * 1000)])
    return {"out": out, "seconds": round((len(frames) - 1) * ms / 1000 + hold_s, 1), "size": (r.width, r.height),
            "panels": [(p, g["path"].name, g["end"]["score"]) for p, g in states]}
