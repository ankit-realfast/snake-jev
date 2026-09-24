"""uv run python -m snake <command>

  play                      you play, arrow keys / WASD, q to quit
  run --player bot|jev|claude|laya  one game on a live board, logged to runs/ (--no-watch for text only)
  coach --games 11          Jev plays on the live board, Claude edits the prompt between games
  replay runs/.../x.jsonl   watch a logged game
"""

from __future__ import annotations

import argparse
import curses
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from .coach import Coach, apply_edits, digest
from .engine import OPPOSITE, Game
from .players import BotPlayer, ClaudePlayer, JevPlayer, LayaPlayer
from .prompt import PromptConfig
from .runner import play_game
from . import ui

RUNS = Path("runs")
PLAY_MS_PER_MOVE = 120  # how fast the snake moves when you steer
KEYS = {curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right",
        ord("w"): "up", ord("s"): "down", ord("a"): "left", ord("d"): "right"}


class LiveView:
    """Draws the board and panel after every move. Returns True to stop."""

    def __init__(self, scr, title: str, starve_after, subtitle: str | None = None):
        self.screen, self.title, self.starve_after = ui.Screen(scr), title, starve_after
        self.subtitle = subtitle
        self.pacer = ui.Pacer(scr)

    def stats(self, game, record):
        lines = ui.stats_lines(self.title, ui.game_dict(game), record, self.starve_after)
        if self.subtitle:
            lines.insert(1, [("config ", "dim"), (self.subtitle, "accent")])
        return lines

    def draw(self, game, record):
        panel = self.stats(game, record) + ui.decision_lines(record) + ui.controls_line(self.pacer.paused)
        self.screen.render(game.size, list(game.body), game.food, panel)

    def __call__(self, game, record) -> bool:
        self.draw(game, record)
        return self.pacer.wait(lambda: self.draw(game, record))

    def game_over(self, game, record, hold_s: float | None = None):
        """Show the final board. Waits for a key, or with hold_s moves on by itself."""
        if hold_s is None:
            prompt = "any key to exit"
        else:
            prompt = "ending the session..." if game.death == "stopped" else "next game starting..."
        panel = (self.stats(game, record) + ui.decision_lines(record)
                 + [[], [("GAME OVER  ", "warn"), (f"{game.death}", "bold")], [(prompt, "dim")]])
        self.screen.render(game.size, list(game.body), game.food, panel)
        if hold_s is None:
            self.screen.scr.nodelay(False)
            self.screen.scr.getch()
        else:
            curses.napms(int(hold_s * 1000))


def watch_fits() -> bool:
    """Board needs 22 rows x 42 cols; the panel goes beside or under it."""
    try:
        cols, rows = os.get_terminal_size()
    except OSError:
        return False
    return rows >= 24 and cols >= 42


def cmd_play(args):
    def loop(scr):
        screen = ui.Screen(scr)
        scr.timeout(PLAY_MS_PER_MOVE)
        game = Game(seed=args.seed, starve_after=None)
        move = game.direction

        def panel(extra):
            return ui.stats_lines(f"SNAKE  seed {args.seed}", ui.game_dict(game), None, None) + extra

        while game.alive:
            screen.render(game.size, list(game.body), game.food,
                          panel([[], [("arrows/WASD", "accent"), (" steer  ", "dim"), ("q", "accent"), (" quit", "dim")]]))
            key = scr.getch()
            if key == ord("q"):
                return game
            wanted = KEYS.get(key)
            if wanted and wanted != OPPOSITE[game.direction]:
                move = wanted
            game.step(move)
        screen.render(game.size, list(game.body), game.food,
                      panel([[], [("GAME OVER  ", "warn"), (game.death, "bold")], [("any key to exit", "dim")]]))
        scr.timeout(-1)
        scr.getch()
        return game
    game = curses.wrapper(loop)
    print(f"score {game.score}, {game.moves} moves, death: {game.death}")


def make_player(name):
    return {"bot": BotPlayer, "jev": JevPlayer, "claude": ClaudePlayer, "laya": LayaPlayer}[name]()


def progress(game, record):
    if record["n"] % 50 == 0 or record.get("ate"):
        conf = record.get("confidence")
        conf_s = f" conf {conf:.2f}" if conf is not None else ""
        print(f"\r  move {record['n']:>5}  score {game.score:>4}  len {len(game.body):>3}{conf_s}   ",
              end="", flush=True)


def clear_progress():
    """Erase the live counter so only the final, exact result stays on screen."""
    print("\r\033[K", end="")


def play_one(player, config, seed, log, args, title, subtitle=None, hold_s=None):
    """Play one game on the live board, or as text with --no-watch."""
    def play(on_move):
        return play_game(player, config, seed, log,
                         max_moves=args.max_moves, starve_after=args.starve_after, on_move=on_move)

    if args.no_watch or not watch_fits():
        if not args.no_watch:
            print("terminal too small for the live board (needs 42x24); showing progress only")
        game = play(progress)
        clear_progress()
        return game

    def watched(scr):
        view = LiveView(scr, title, args.starve_after, subtitle)
        last = {}

        def on_move(game, record):
            last["record"] = record
            return view(game, record)

        game = play(on_move)
        view.game_over(game, last.get("record"), hold_s)
        return game
    return curses.wrapper(watched)


def cmd_run(args):
    config = PromptConfig(**json.loads(Path(args.config).read_text())) if args.config else PromptConfig()
    out = RUNS / args.player / f"{time.strftime('%Y%m%d-%H%M%S')}_seed{args.seed}_{config.label()}.jsonl"
    game = play_one(make_player(args.player), config, args.seed, out, args,
                    f"{args.player.upper()}  seed {args.seed}", subtitle=config.label())
    print(f"score {game.score}, {game.moves} moves, {game.food_eaten} food, death: {game.death}")
    print(f"log: {out}")
    if args.digest:
        print(json.dumps(digest(out), indent=2))


def cmd_coach(args):
    run_dir = RUNS / "coach" / f"{time.strftime('%Y%m%d-%H%M%S')}_seed{args.seed}_{args.player}"
    run_dir.mkdir(parents=True)
    player, coach = make_player(args.player), Coach()
    config = PromptConfig(**json.loads(Path(args.config).read_text())) if args.config else PromptConfig()
    best, best_score = config, -1
    history = []

    for i in range(1, args.games + 1):
        print(f"\ngame {i}/{args.games}  seed {args.seed}")
        log = run_dir / f"game_{i:02d}_{config.label()}.jsonl"
        game = play_one(player, config, args.seed, log, args,
                        f"COACH {i}/{args.games}  {args.player.upper()}  seed {args.seed}",
                        subtitle=config.label(), hold_s=2.0)
        d = digest(log)
        print(f"  score {d['score']}  moves {d['moves']}  death {d['death']}  "
              f"longest drought {d['longest_stretch_without_food']}")
        history.append({"game": i, "score": d["score"], "config": asdict(config), "log": str(log)})
        if d["score"] > best_score:
            best, best_score = config, d["score"]
            (run_dir / "best_config.json").write_text(best.to_json())
        if game.death == "stopped":
            print("  stopped with q; ending the session")
            break
        if i == args.games:
            break

        # Failed experiments never become the baseline: always edit the best.
        proposal = coach.propose(best, d if config == best else digest_for_best(run_dir, history, best), history)
        config, applied = apply_edits(best, proposal["edits"])
        print(f"  coach: {proposal['diagnosis']}")
        for e in applied:
            flag = f"  REJECTED: {e['rejected']}" if "rejected" in e else ""
            print(f"    {e['field']} = {e['value']!r}  because {e['observation']}{flag}")
        (run_dir / f"coach_{i:02d}.json").write_text(json.dumps({"digest": d, "proposal": proposal,
                                                                 "applied": applied}, indent=2))

    print(f"\nbest score {best_score}. scores: {[h['score'] for h in history]}")
    print(f"logs and best_config.json in {run_dir}")


def digest_for_best(run_dir, history, best):
    """The coach edits the best config, so show it the best game's digest."""
    for h in reversed(history):
        if h["config"] == asdict(best):
            return digest(Path(h["log"]))
    raise LookupError("best config has no game")


def cmd_replay(args):
    lines = [json.loads(l) for l in Path(args.log).read_text().splitlines()]
    start, end = lines[0], lines[-1]

    def loop(scr):
        # Logs from before starve_after was recorded all used the 600 default.
        view = LiveView(scr, f"REPLAY {start['player'].upper()}  seed {start['seed']}",
                        start.get("starve_after", 600))
        game = Game(seed=start["seed"], starve_after=None)
        record = None
        for record in lines[1:]:
            if record["type"] != "move":
                continue
            game.step(record["move"])
            if not game.alive:
                # The fatal move is never applied to the body, so the board
                # stays on the last live position.
                break
            if view(game, record):
                break
        game.death = end.get("death") if end.get("type") == "end" else "log ends"
        view.game_over(game, record if record and record.get("type") == "move" else None)
    curses.wrapper(loop)


def main():
    load_dotenv()
    p = argparse.ArgumentParser(prog="snake")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("play"); s.add_argument("--seed", type=int, default=7)

    for name in ("run", "coach"):
        s = sub.add_parser(name)
        s.add_argument("--player", choices=["bot", "jev", "claude", "laya"], default="jev" if name == "coach" else "bot")
        s.add_argument("--seed", type=int, default=7)
        s.add_argument("--config", help="PromptConfig JSON file")
        s.add_argument("--max-moves", type=int)
        s.add_argument("--starve-after", type=int, default=600)
        s.add_argument("--no-watch", action="store_true", help="skip the live board")
        if name == "run":
            s.add_argument("--digest", action="store_true")
        else:
            s.add_argument("--games", type=int, default=11)

    s = sub.add_parser("replay"); s.add_argument("log")

    args = p.parse_args()
    {"play": cmd_play, "run": cmd_run, "coach": cmd_coach, "replay": cmd_replay}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
