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
    ap.add_argument("--menu", action="store_true",
                    help="M3: boot into the menu; enter/esc toggles to the world")
    ap.add_argument("--no-reset", action="store_true",
                    help="skip the self-reset: one frame, no loop, no restore set")
    # M2-R4: the runtime doors. The shipped restore set carries the per-door state and
    # build.DOOR_PERSIST keeps it across the reset, so this is the tier the game is played on.
    ap.add_argument("--doors", action="store_true", help="M2: runtime doors (space opens them)")
    args = ap.parse_args()

    out = Path(args.out or ("build/doom_e1m1_std%s.fjm" % ("_noloop" if args.no_reset else "")))
    print("wad  : %s  map %s" % (args.wad, args.map))
    print("out  : %s" % out)
    # PHASE 2 made the emitter DERIVE the generated dir from out_fjm ('generated_' + stem), so
    # there is no --gen any more. It survived the refactor as an argument that was parsed and
    # then silently ignored -- including in the invocation docs/handoff-flags-defines.md
    # printed -- which sent this session looking in the wrong directory. Print what will
    # actually be written instead.
    print("gen  : %s" % (out.parent / ("generated_" + out.stem)))
    print("reset: %s" % ("OFF -- one frame, no loop" if args.no_reset else "ON -- the program loops"))
    print("doors: %s" % ("RUNTIME -- space opens them" if args.doors else "off"))
    t = time.perf_counter()
    # ⚠ `--menu/--doors/--no-reset` used to be three booleans forwarded straight through. The
    # SHIPPED combination is `game`; the others were only ever built while it was being assembled
    # rung by rung, and each now needs a name in wall_renderer.TIERS rather than a flag here.
    assert args.menu and args.doors and not args.no_reset, (
        "m5_build now builds the `game` tier. The partial standalone combinations (no menu, no "
        "doors, no reset) were rungs on the way to it -- add a TIERS row if one is needed again.")
    metrics = build_wall_renderer(out, wad_path=str(ROOT / args.wad), mapname=args.map,
                                  cfg=Config(), tier="game")
    print(json.dumps(metrics, indent=2))
    print("total %.0fs" % (time.perf_counter() - t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
