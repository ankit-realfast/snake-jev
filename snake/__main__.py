"""uv run python -m snake <command>

  play                      you play, arrow keys / WASD, q to quit
  run --player bot|jev      one game, logged to runs/
  coach --games 11          Jev plays, Claude edits the prompt, replay same seed
  replay runs/.../x.jsonl   watch a logged game
"""

from __future__ import annotations

import argparse
import curses
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from .coach import Coach, apply_edits, digest
from .engine import OPPOSITE, Game
from .players import BotPlayer, JevPlayer
from .prompt import PromptConfig
from .runner import play_game

RUNS = Path("runs")
KEYS = {curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left", curses.KEY_RIGHT: "right",
        ord("w"): "up", ord("s"): "down", ord("a"): "left", ord("d"): "right"}


def draw(scr, size, body, food, status):
    scr.erase()
    scr.addstr(0, 0, "+" + "--" * size + "+")
    cells = {tuple(c): "()" for c in body[1:]}
    cells[tuple(body[0])] = "@@"
    if food:
        cells[tuple(food)] = "<>"
    for y in range(size):
        row = "".join(cells.get((x, y), "  ") for x in range(size))
        scr.addstr(y + 1, 0, "|" + row + "|")
    scr.addstr(size + 1, 0, "+" + "--" * size + "+")
    scr.addstr(size + 2, 0, status[: 2 * size + 2])
    scr.refresh()


def cmd_play(args):
    def loop(scr):
        curses.curs_set(0)
        scr.timeout(args.tick)
        game = Game(seed=args.seed, starve_after=None)
        move = game.direction
        while game.alive:
            draw(scr, game.size, list(game.body), game.food, f"score {game.score}  moves {game.moves}  q quits")
            key = scr.getch()
            if key == ord("q"):
                return game
            wanted = KEYS.get(key)
            if wanted and wanted != OPPOSITE[game.direction]:
                move = wanted
            game.step(move)
        draw(scr, game.size, list(game.body), game.food, f"died ({game.death}) score {game.score}. any key")
        scr.timeout(-1)
        scr.getch()
        return game
    game = curses.wrapper(loop)
    print(f"score {game.score}, {game.moves} moves, death: {game.death}")


def make_player(name):
    return BotPlayer() if name == "bot" else JevPlayer()


def progress(game, record):
    if record["n"] % 50 == 0 or record.get("ate"):
        conf = record.get("confidence")
        conf_s = f" conf {conf:.2f}" if conf is not None else ""
        print(f"\r  move {record['n']:>5}  score {game.score:>4}  len {len(game.body):>3}{conf_s}   ",
              end="", flush=True)


def clear_progress():
    """Erase the live counter so only the final, exact result stays on screen."""
    print("\r\033[K", end="")


def cmd_run(args):
    config = PromptConfig(**json.loads(Path(args.config).read_text())) if args.config else PromptConfig()
    out = RUNS / args.player / f"{time.strftime('%Y%m%d-%H%M%S')}_seed{args.seed}.jsonl"
    game = play_game(make_player(args.player), config, args.seed, out,
                     max_moves=args.max_moves, starve_after=args.starve_after, on_move=progress)
    clear_progress()
    print(f"score {game.score}, {game.moves} moves, {game.food_eaten} food, death: {game.death}")
    print(f"log: {out}")
    if args.digest:
        print(json.dumps(digest(out), indent=2))


def cmd_coach(args):
    run_dir = RUNS / "coach" / f"{time.strftime('%Y%m%d-%H%M%S')}_seed{args.seed}"
    run_dir.mkdir(parents=True)
    player, coach = make_player(args.player), Coach()
    config = PromptConfig(**json.loads(Path(args.config).read_text())) if args.config else PromptConfig()
    best, best_score = config, -1
    history = []

    for i in range(1, args.games + 1):
        print(f"\ngame {i}/{args.games}  seed {args.seed}")
        log = run_dir / f"game_{i:02d}.jsonl"
        game = play_game(player, config, args.seed, log,
                         max_moves=args.max_moves, starve_after=args.starve_after, on_move=progress)
        d = digest(log)
        clear_progress()
        print(f"  score {d['score']}  moves {d['moves']}  death {d['death']}  "
              f"longest drought {d['longest_stretch_without_food']}")
        history.append({"game": i, "score": d["score"], "config": asdict(config)})
        if d["score"] > best_score:
            best, best_score = config, d["score"]
            (run_dir / "best_config.json").write_text(best.to_json())
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
            return digest(run_dir / f"game_{h['game']:02d}.jsonl")
    raise LookupError("best config has no game")


def cmd_replay(args):
    lines = [json.loads(l) for l in Path(args.log).read_text().splitlines()]
    start = lines[0]

    def loop(scr):
        curses.curs_set(0)
        game = Game(seed=start["seed"], starve_after=None)
        for rec in lines[1:]:
            if rec["type"] != "move":
                continue
            game.step(rec["move"])
            conf = rec.get("confidence")
            status = f"move {rec['n']} {rec['move']:<5} score {game.score}" + (f" conf {conf:.2f}" if conf else "")
            if not game.alive:
                # The fatal move is never applied to the body, so the board
                # stays on the last live position; label the move that killed it.
                draw(scr, game.size, list(game.body), game.food, status + "  <- fatal")
                break
            draw(scr, game.size, list(game.body), game.food, status)
            time.sleep(args.delay)
        scr.addstr(game.size + 3, 0, f"end: {lines[-1].get('death')}  score {lines[-1].get('score')}. any key")
        scr.getch()
    curses.wrapper(loop)


def main():
    load_dotenv()
    p = argparse.ArgumentParser(prog="snake")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("play"); s.add_argument("--seed", type=int, default=0)
    s.add_argument("--tick", type=int, default=120, help="ms per move")

    for name in ("run", "coach"):
        s = sub.add_parser(name)
        s.add_argument("--player", choices=["bot", "jev"], default="jev" if name == "coach" else "bot")
        s.add_argument("--seed", type=int, default=7)
        s.add_argument("--config", help="PromptConfig JSON file")
        s.add_argument("--max-moves", type=int)
        s.add_argument("--starve-after", type=int, default=600)
        if name == "run":
            s.add_argument("--digest", action="store_true")
        else:
            s.add_argument("--games", type=int, default=11)

    s = sub.add_parser("replay"); s.add_argument("log"); s.add_argument("--delay", type=float, default=0.03)

    args = p.parse_args()
    {"play": cmd_play, "run": cmd_run, "coach": cmd_coach, "replay": cmd_replay}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
