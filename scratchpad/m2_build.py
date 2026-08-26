"""M2-R2 -- build E1M1 with the doors baked at a chosen open FRACTION.

The first buildable rung of doors. It moves no fj code at all: it hands the emitter a
`sector_heights` override -- the SAME one the oracle takes -- and asks whether the renderer, the
pid bank, the V5 stacked pieces, collision and thing-liveness all come out byte-exact with a door
somewhere other than where the wad stored it. Everything the runtime door needs is built on top of
this; if a STATIC open door does not render correctly, an animated one cannot.

    python scratchpad/m2_build.py                 # doors fully open
    python scratchpad/m2_build.py --frac 0.5      # half open (quantised)
    python scratchpad/m2_build.py --frac 0.0      # SHUT: must be byte-identical to the stock build

⚠ ONE HEAVY BUILD AT A TIME. self_reset is OFF -- the loop needs its own re-keyed restore set and
this rung is about the picture, not the loop.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj.build import build_wall_renderer                              # noqa: E402
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS                   # noqa: E402
from doomfj.doors import heights_at                                       # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402


def door_heights(mw, mapname, frac, quant):
    """The override, from doomfj.doors -- the SAME module the oracle-side gate and the budget
    tools use. Writing the door model out again here is exactly how the two mirrors drift."""
    return heights_at(mw.sectors(mapname), mw.linedefs(mapname), mw.sidedefs(mapname),
                      frac, quant)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--frac", type=float, default=1.0)
    ap.add_argument("--quant", type=int, default=16)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    heights = door_heights(mw, args.map, args.frac, args.quant)
    tag = "%02d" % round(args.frac * 100)
    out = Path(args.out or ("build/doom_e1m1_doors%s.fjm" % tag))
    print("doors at frac %.2f (quant %d): %d sectors" % (args.frac, args.quant, len(heights)))
    for si in sorted(heights):
        print("   sector %4d -> floor %5d ceil %5d" % (si, *heights[si]))
    print("out: %s" % out, flush=True)
    t = time.perf_counter()
    metrics = build_wall_renderer(
        str(ROOT / args.wad), args.map, cfg=Config(), out_fjm=out,
        generated_dir=Path("build/generated_doors%s" % tag),
        flat_max_words=RENDER_FLAT_MAX_WORDS, self_reset=False, sector_heights=heights)
    print(json.dumps(metrics, indent=2))
    print("total %.0fs" % (time.perf_counter() - t))
    return 0


if __name__ == "__main__":
    sys.exit(main())
