"""Byte-exactness over MANY viewpoints, not four.

Every gate in this repo certifies the same four viewpoints (`deg_gate`, `deg_gate2`, the visual
feature tests). `lite_sweep.py` visits many viewpoints but only counts OPS -- it never compares a
pixel. So "the renderer is byte-exact" has, until now, meant "at four points".

M14's multi-frame gate walks the player through viewpoints nobody has ever compared, which makes
the question urgent: is a divergence there caused by the sim, or has it been sitting in the
renderer all along? This sweep answers that with the sim taken out of the picture -- every frame is
fed keys=0, so the program is a pure (state -> frame) function exactly as it was before M14.

Positions come from `check_position` (M14-d), so every one is somewhere a player could actually
stand, not a point in the void.

    python scratchpad/m14_vp_sweep.py [n] [--seed S] [--angles K]

Uses the binary `m14_gate.py` cached; run that first (it builds).
"""
import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wireformat import encode_feed
from tests.fj.stream_screen import StreamScreen

CACHE = ROOT / "scratchpad/fjmcache/m14_bin.fjm"
cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)


def walkable(rng, n):
    """`n` positions a player could stand in, drawn from the map's vertex bounding box."""
    xs = [v[0] for v in scene.cmap.vertexes]
    ys = [v[1] for v in scene.cmap.vertexes]
    out = []
    while len(out) < n:
        x, y = rng.randint(min(xs), max(xs)), rng.randint(min(ys), max(ys))
        ok, floorz, ceilingz = rm.check_position(scene, x << 16, y << 16)
        if ok and ceilingz - floorz >= 56:
            out.append((x, y))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("n", nargs="?", type=int, default=12)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--angles", type=int, default=1)
    ap.add_argument("--frac", type=lambda s: int(s, 0), default=0,
                    help="add this 16.16 fraction to x and y (0x8000 = half a map unit) "
                         "-- the regime the player sim actually produces")
    args = ap.parse_args()
    assert CACHE.exists(), f"{CACHE} missing -- run scratchpad/m14_gate.py first (it builds)"
    rng = random.Random(args.seed)
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    points = [(spx, spy)] + walkable(rng, args.n - 1)
    bad = 0
    for i, (vx, vy) in enumerate(points):
        for k in range(args.angles):
            va = (sp.angle + k * (1 << 32) // max(1, args.angles)) & 0xFFFFFFFF if i == 0 \
                else rng.randrange(1 << 32)
            x16, y16 = (vx << 16) + args.frac, (vy << 16) + args.frac
            scr = StreamScreen(stdin=encode_feed(x16, y16, va, 0))
            term = fj.run(CACHE, io_device=scr, print_time=False, print_termination=False,
                          flat_max_words=1 << 26)
            want = rm.render_wall_frame(SimState(x16, y16, va, "E1M1"), scene, **RENDER_KW)
            got = bytes(scr.pixel_indices)
            diff = sum(1 for a, b in zip(got, bytes(want)) if a != b)
            bad += diff != 0
            print(f"({vx},{vy},{va:#010x}): {term.op_counter:,} ops  "
                  f"{'BYTE-EXACT' if diff == 0 else f'!! {diff} of {len(got)} px DIFFER'}",
                  flush=True)
    total = len(points) * args.angles
    print(f"\n{total - bad}/{total} byte-exact")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
