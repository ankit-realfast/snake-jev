"""Terminal rendering shared by play, run and replay: a colored board plus a
side panel with game stats and, for Jev, its probabilities as bars."""

from __future__ import annotations

import curses

BOARD_W = 42          # 20 cells x 2 chars + 2 border columns
PANEL_W = 40


class Screen:
    def __init__(self, scr):
        self.scr = scr
        curses.curs_set(0)
        self.color = curses.has_colors()
        if self.color:
            curses.start_color()
            curses.use_default_colors()
            for pair, fg in enumerate((curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED,
                                       curses.COLOR_CYAN, curses.COLOR_MAGENTA), start=1):
                curses.init_pair(pair, fg, -1)
        self.attr = {
            "body": self._pair(1), "head": self._pair(2) | curses.A_BOLD, "food": self._pair(3) | curses.A_BOLD,
            "title": self._pair(4) | curses.A_BOLD, "bar": self._pair(4), "pick": self._pair(2) | curses.A_BOLD,
            "warn": self._pair(3), "dim": curses.A_DIM, "bold": curses.A_BOLD, "plain": curses.A_NORMAL,
            "accent": self._pair(5),
        }
        # Blocks when colors tell the parts apart; otherwise the old glyphs.
        self.glyph = ({"body": "██", "tail": "▓▓", "head": "██", "food": "██", "empty": "· "} if self.color
                      else {"body": "()", "tail": "()", "head": "@@", "food": "<>", "empty": "  "})

    def _pair(self, n):
        return curses.color_pair(n) if curses.has_colors() else curses.A_NORMAL

    def put(self, y, x, text, style="plain"):
        """addstr that clips to the window instead of raising."""
        rows, cols = self.scr.getmaxyx()
        if y >= rows or x >= cols - 1:
            return
        try:
            self.scr.addstr(y, x, text[: cols - 1 - x], self.attr[style])
        except curses.error:
            pass

    def render(self, size, body, food, panel):
        """panel: list of lines; each line is a list of (text, style) segments."""
        self.scr.erase()
        rows, cols = self.scr.getmaxyx()
        side = cols >= BOARD_W + 2 + PANEL_W
        self._board(size, body, food)
        py, px = (0, BOARD_W + 2) if side else (size + 2, 0)
        for i, line in enumerate(panel):
            x = px
            for text, style in line:
                self.put(py + i, x, text, style)
                x += len(text)
        self.scr.refresh()

    def _board(self, size, body, food):
        cells = {tuple(c): "body" for c in body[1:-1]}
        if len(body) > 1:
            cells[tuple(body[-1])] = "tail"
        cells[tuple(body[0])] = "head"
        if food:
            cells[tuple(food)] = "food"
        self.put(0, 0, "┌" + "─" * (2 * size) + "┐", "dim")
        for y in range(size):
            self.put(y + 1, 0, "│", "dim")
            for x in range(size):
                kind = cells.get((x, y), "empty")
                style = {"empty": "dim", "tail": "body"}.get(kind, kind)
                self.put(y + 1, 1 + 2 * x, self.glyph[kind], style)
            self.put(y + 1, 1 + 2 * size, "│", "dim")
        self.put(size + 1, 0, "└" + "─" * (2 * size) + "┘", "dim")


def bar(p: float, width: int = 14) -> str:
    filled = round(p * width)
    return "█" * filled + "░" * (width - filled)


def stats_lines(title, game_like: dict, record: dict | None, starve_after) -> list:
    """Top of the panel: numbers that describe the position."""
    g = game_like
    lines = [
        [(title, "title")],
        [],
        [("move  ", "dim"), (f"{g['moves']:<7}", "bold"), ("score ", "dim"), (f"{g['score']}", "bold")],
        [("length", "dim"), (f" {g['length']:<6}", "bold"), ("food  ", "dim"), (f"{g['food_eaten']}", "bold")],
    ]
    if starve_after:
        hunger = g["since_food"]
        lines.append([("hunger", "dim"), (f" {hunger} / {starve_after}",
                                          "warn" if hunger > starve_after * 0.75 else "bold")])
    if record:
        path = record.get("path_after")
        lines.append([("path to food  ", "dim"), (f"{path} steps" if path is not None else "blocked", "bold")])
        lines.append([("open space    ", "dim"), (f"{record.get('space_after', '-')}", "bold")])
    return lines


def decision_lines(record: dict | None) -> list:
    """Middle of the panel: what decided this move."""
    if not record:
        return []
    lines = [[]]
    probs = record.get("probabilities")
    if probs:
        conf = record.get("confidence")
        lines.append([("JEV CHOICE", "title"), (f"      confidence {conf:.2f}" if conf is not None else "", "dim")])
        for move, p in sorted(probs.items(), key=lambda kv: -kv[1]):
            picked = move == record["move"]
            lines.append([(f"{move:<6}", "pick" if picked else "plain"), (bar(p), "bar"),
                          (f" {p:.2f}", "bold" if picked else "dim"), ("  ◀" if picked else "", "pick")])
        danger = record.get("danger")
        if danger is not None:
            label = "safe" if danger < 0.5 else "some risk" if danger < 1.5 else "trapped"
            lines.append([("danger  ", "dim"), (f"{label} ({danger:.2f} of 2)", "warn" if danger >= 0.5 else "plain")])
    elif record.get("forced"):
        lines.append([("NO CHOICE", "title")])
        lines.append([(record["forced"].replace("_", " ") + f" → {record['move']}", "plain")])
    else:
        lines.append([("BOT RULE", "title")])
        lines.append([(f"→ {record['move']}", "pick")])
    withheld = record.get("withheld_pockets")
    if withheld:
        lines.append([("hidden pockets: ", "dim"), (", ".join(withheld), "warn")])
    return lines


def controls_line(paused: bool, delay: float | None) -> list:
    speed = f"  {delay:.2f}s/move" if delay is not None else ""
    return [[], [("PAUSED  " if paused else "", "warn"),
                 ("space", "accent"), (" pause  ", "dim"), ("+/-", "accent"), (" speed  ", "dim"),
                 ("q", "accent"), (" stop", "dim"), (speed, "dim")]]


def game_dict(game) -> dict:
    return {"moves": game.moves, "score": game.score, "length": len(game.body),
            "food_eaten": game.food_eaten, "since_food": game.moves_since_food}


class Pacer:
    """Handles space / + / - / q between frames. Returns True when q is pressed."""

    def __init__(self, scr, delay: float):
        self.scr, self.delay, self.paused = scr, delay, False
        scr.nodelay(True)

    def wait(self, redraw) -> bool:
        deadline_steps = max(1, int(self.delay / 0.01))
        for _ in range(deadline_steps):
            key = self.scr.getch()
            if key == ord("q"):
                return True
            if key in (ord("+"), ord("=")):
                self.delay = max(0.0, self.delay / 1.5 if self.delay > 0.005 else 0.0)
            elif key in (ord("-"), ord("_")):
                self.delay = min(2.0, self.delay * 1.5 if self.delay > 0 else 0.02)
            elif key == ord(" "):
                self.paused = True
                redraw()
                self.scr.nodelay(False)
                while True:
                    k = self.scr.getch()
                    if k == ord("q"):
                        return True
                    if k == ord(" "):
                        break
                self.scr.nodelay(True)
                self.paused = False
            if self.delay == 0:
                break
            curses.napms(10)
        return False
