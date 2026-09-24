"""Render the best and worst game from each player folder as one GIF, all in
one row and grouped by player, plus an MP4 of the same layout. A player with a
single game gets one board. The GIF plays inline in a GitHub README; the MP4
shows every move at 60 fps and a larger scale.

All panels share one clock: a frame at move t shows move t on every board. A
player whose game has ended freezes on its last position and shows how it died.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .engine import Game

PLAYERS = ("rules", "jev", "claude", "laya")   # coach sessions are left out on purpose

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


def finished_games(folder: Path) -> list[dict]:
    return [g for g in (load(p) for p in sorted(folder.glob("*.jsonl"))) if g["end"]]


def best_and_worst(folder: Path) -> tuple[dict, dict | None] | None:
    """Best: highest score, ties to the most recent log. Worst: lowest score,
    ties to the shortest game. Worst is None when there is only one game."""
    games = finished_games(folder)
    if not games:
        return None
    best = max(games, key=lambda g: (g["end"]["score"], g["path"].name))
    rest = [g for g in games if g is not best]
    worst = min(rest, key=lambda g: (g["end"]["score"], g["end"]["moves"])) if rest else None
    return best, worst


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
    """Draws all boards for one moment in time, in one row. `cell` sets the scale."""

    def __init__(self, states, cell: int):
        # states: (player, label, config, game); boards of one player sit together.
        self.states, self.cell = states, cell
        self.board = 20 * cell
        self.pad = cell + 4            # between boards of one player
        self.gap = cell * 3            # between players, with a divider in the middle
        self.header = int(cell * 6.4)
        self.footer = int(cell * 2.6)
        self.xs, x = [], self.pad
        for i, (player, *_ ) in enumerate(states):
            if i and player != states[i - 1][0]:
                x += self.gap - self.pad
            self.xs.append(x)
            x += self.board + self.pad
        self.width = x
        self.height = self.header + self.board + self.footer
        self.big, self.small = font(int(cell * 1.6)), font(int(cell * 1.2))
        self.games = [Game(seed=g["start"]["seed"], starve_after=None) for *_, g in states]
        self.applied = [0] * len(states)

    def frame(self, now: int) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), COLORS["bg"])
        d = ImageDraw.Draw(img)
        for i, (player, label, config, g) in enumerate(self.states):
            game = self.games[i]
            # Replay moves up to `now`. The fatal move never changes the board.
            while self.applied[i] < min(now, len(g["moves"])) and game.alive:
                game.step(g["moves"][self.applied[i]])
                self.applied[i] += 1
            first = i == 0 or player != self.states[i - 1][0]
            if first and i:
                mid = self.xs[i] - self.gap // 2
                d.line([mid, int(self.cell * 0.6), mid, self.height - int(self.cell * 0.6)], fill=COLORS["border"])
            self._panel(d, self.xs[i], player.upper() if first else "", label, config, g, game, now)
        return img

    def _panel(self, d, x0, title, label, config, g, game, now):
        c, top = self.cell, self.header
        if title:
            d.text((x0, int(c * 0.6)), title, fill=COLORS["text"], font=self.big)
        d.text((x0, int(c * 2.9)), label, fill=COLORS["text"], font=self.small)
        d.text((x0, int(c * 4.5)), config, fill=COLORS["dim"], font=self.small)
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
            death = g["end"]["death"]
            w = d.textlength(death, font=self.small)
            d.text((x0 + self.board - w, y), death, fill=COLORS["food"], font=self.small)


def pick_games(runs: Path) -> list:
    """Boards as (player, label, config, game), grouped by player: best then
    worst, or one board when a player has a single game."""
    players = [p for p in PLAYERS if (runs / p).exists() and best_and_worst(runs / p)]
    if not players:
        raise SystemExit("no finished games in runs/rules, runs/jev, runs/claude or runs/laya")
    states = []
    for p in players:
        best, worst = best_and_worst(runs / p)
        if worst is None:
            states.append((p, "1 game", config_label(best["path"]), best))
        else:
            n = len(finished_games(runs / p))
            states.append((p, f"best of {n}", config_label(best["path"]), best))
            states.append((p, f"worst of {n}", config_label(worst["path"]), worst))
    return states


def ticks(states, step: int) -> list[int]:
    longest = max(len(g["moves"]) for *_, g in states)
    return list(range(0, longest, step)) + [longest]


# step must be odd. A snake can only return to the same cells after an even
# number of moves, so a loop's length is even. With an even step, a loop whose
# length divides the step shows the same position in every frame and looks
# frozen. Laya's 4-move loop did exactly that at step 4.
def write_gif(runs: Path, out: Path, step: int = 5, fps: int = 15, hold_s: float = 3.0) -> dict:
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
            "panels": [(f"{p} {label}", g["path"].name, g["end"]["score"]) for p, label, _, g in states]}


def write_mp4(runs: Path, out: Path, step: int = 1, fps: int = 60, hold_s: float = 3.0, cell: int = 20) -> dict:
    """Same layout as the GIF, but every move at 60 fps and a larger scale, since
    an MP4 has no palette or file-size limits like a GIF. Frames are piped to
    the ffmpeg bundled with imageio-ffmpeg, so no system install is needed."""
    import subprocess

    import imageio_ffmpeg

    states = pick_games(runs)
    r = Renderer(states, cell=cell)
    w, h = r.width + r.width % 2, r.height + r.height % 2   # H.264 needs even sizes
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    frames = ticks(states, step)
    canvas = Image.new("RGB", (w, h), COLORS["bg"])
    for i, now in enumerate(frames):
        canvas.paste(r.frame(now), (0, 0))
        data = canvas.tobytes()
        for _ in range(int(hold_s * fps) if i == len(frames) - 1 else 1):
            proc.stdin.write(data)
    proc.stdin.close()
    if proc.wait():
        raise SystemExit(f"ffmpeg failed writing {out}")
    shown = len(frames) - 1 + int(hold_s * fps)
    return {"out": out, "seconds": round(shown / fps, 1), "size": (w, h)}
