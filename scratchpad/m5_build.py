"""M5 -- build the STANDALONE .fjm: no host in the loop, keyboard in, 0x0B frames out.

    python scratchpad/m5_build.py                       # the shipped standalone tier (loops)
    python scratchpad/m5_build.py --no-reset            # one frame, no loop: the cheap smoke test
    python scratchpad/m5_build.py --wad tests/fixtures/arena.wad --map MAP01 --out build/std_arena.fjm

⚠ ONE HEAVY BUILD AT A TIME (CLAUDE.md rule 1).

Everything except `standalone=True` is `build_wall_renderer`'s SHIPPING default, deliberately: the
standalone artifact and the certified artifact must be the same program, which is the divergence
A0.1 closed and the reason those defaults live in one place.

`--no-reset` is the useful intermediate. Without the self-reset there is no loop, so the program
renders exactly one frame -- the player start, with no keys pressed -- and halts. That is enough to
prove the emit half (the baked spawn, the baked thing bindings and visibility, the keyboard poll
not disturbing the frame, the stock 8-byte init) without spending an hour on the two-pass build,
and it needs no restore set at all.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.build import build_wall_renderer                # noqa: E402
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--out", default=None)
    ap.add_argument("--gen", default=None)
    ap.add_argument("--menu", action="store_true",
                    help="M3: boot into the menu; enter/esc toggles to the world")
    ap.add_argument("--no-reset", action="store_true",
                    help="skip the self-reset: one frame, no loop, no restore set")
    args = ap.parse_args()

    out = Path(args.out or ("build/doom_e1m1_std%s.fjm" % ("_noloop" if args.no_reset else "")))
    gen = Path(args.gen or ("build/generated_std%s" % ("_noloop" if args.no_reset else "")))
    print("wad  : %s  map %s" % (args.wad, args.map))
    print("out  : %s" % out)
    print("reset: %s" % ("OFF -- one frame, no loop" if args.no_reset else "ON -- the program loops"))
    t = time.perf_counter()
    metrics = build_wall_renderer(
        str(ROOT / args.wad), args.map, cfg=Config(), out_fjm=out, generated_dir=gen,
        flat_max_words=RENDER_FLAT_MAX_WORDS, standalone=True, menu=args.menu,
        self_reset=not args.no_reset)
    print(json.dumps(metrics, indent=2))
    print("total %.0fs" % (time.perf_counter() - t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
