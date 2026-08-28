"""M2-R3 -- build E1M1 with the RUNTIME door: every door baked once per state, dispatched on a
per-door state nibble (`dstate`).

R2 built one binary per door position. This builds ONE binary that holds them all, so a door moves
by writing a nibble instead of by rebuilding. What it does NOT do is decide when to write that
nibble -- that is R4 (the trigger and the state machine); here the gate writes it, which is the
honest way to test the render half on its own.

    python scratchpad/m2_rt_build.py                 # doors=True, hosted tier, self_reset off
    python scratchpad/m2_rt_build.py --no-doors      # the same build with the flag off (the control)

⚠ ONE HEAVY BUILD AT A TIME. self_reset is OFF: the loop needs its own re-keyed restore set (the
new `dstate` cells and the switch dispatch ops are cells the frame dirties), and this rung is about
the picture. The standalone/self-reset build is R4's problem, where the state actually has to
survive a frame.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj import selfreset                                              # noqa: E402
from doomfj.build import build_wall_renderer                              # noqa: E402
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS                   # noqa: E402
from doomfj.doors import door_states                                      # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--out", default="build/doom_e1m1_doors_rt.fjm")
    ap.add_argument("--gen", default="build/generated_doors_rt")
    ap.add_argument("--no-doors", action="store_true")
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    tbl = door_states(mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map))
    print("map  : %s" % args.wad)
    print("doors: %s" % ("OFF (control build)" if args.no_doors else
                         "%d, %d states total, widest %d"
                         % (len(tbl), sum(len(v) for v in tbl.values()),
                            max(len(v) for v in tbl.values()))))
    print("out  : %s" % args.out, flush=True)

    t = time.perf_counter()
    m = build_wall_renderer(ROOT / args.wad, args.map,
                            out_fjm=ROOT / args.out, generated_dir=ROOT / args.gen,
                            flat_max_words=RENDER_FLAT_MAX_WORDS,
                            doors=not args.no_doors)
    print(json.dumps(m, indent=2, default=str))
    print("built in %.0f s" % (time.perf_counter() - t))

    # The gate has to WRITE door states into this image, so the label it writes through has to
    # exist -- and a `dstate` that silently is not there would read as "every door shut, forever"
    # and the gate would report a clean pass on a picture nothing moved.
    if not args.no_doors:
        gen = ROOT / args.gen
        paths = sorted(gen.glob("*.fj"))
        print("dstate: resolving in the built image ...", flush=True)
        print("        (label capture happens in the gate; here we only assert the build shape)")
        assert m["storage_mode"] == "flat", m
        assert m["features"]["doors"], m["features"]
        print("OK -- flat, doors=True")


if __name__ == "__main__":
    main()
