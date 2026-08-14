"""Ops at NAMED viewpoints, on a cached binary — the reconciliation control for the profiler.

`opprof.py --m14` reports a per-macro breakdown of ONE frame. That breakdown is only worth reading
if its total is the same frame the fast native runner counts, and if the M14 delta it attributes is
the same delta the pre-M14 binary shows at the SAME viewpoint. This prints both sides:

  * `--m14 <fjm>`   the M14 `--things` wire (state + 251 spawn positions + WARM bindings, keys=0),
                    i.e. exactly what `m14_sweep.py` feeds and what `opprof.py --m14` feeds;
  * `--dec <fjm>`   the pre-M14 DECIMAL wire (`vx\\nvy\\nva\\n`), i.e. the certified binary.

Same viewpoints, both binaries, so the difference is MEASURED per frame rather than inferred from
two different sweeps' medians (docs/handoff-perf.md §4 does the latter, and says so).

    python scratchpad/m14_vp_ops.py --m14 scratchpad/fjmcache/m14_bin_things.fjm \\
                                    --dec scratchpad/fjmcache/b_272d37507ca58434.fjm
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed_mapunits,     # noqa: E402
                               encode_things)
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--m14", default=None, help="a bin-wire --things binary")
ap.add_argument("--dec", default=None, help="a pre-M14 decimal-wire binary")
ap.add_argument("--vp", action="append", default=[],
                help="X,Y,ANG (repeatable). Default: the four gate viewpoints + spawn.")
ap.add_argument("--oracle", action="store_true",
                help="also diff each binary against TODAY's degrade=True oracle -- says WHICH "
                     "binary moved when the two disagree")
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = ([tuple(int(v, 0) for v in s.split(",")) for s in args.vp] or
       [(664, 291, 0x18000000), (1272, -724, 1073741824), (1869, 479, 2147483648),
        (spx, spy, sp.angle)])

scene = build_scene(mw, mw, "E1M1") if args.oracle else None
RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)
cmap = bake_bsp(mw, "E1M1")
DRAW = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
THINGS = (encode_things([(t.x << 16, t.y << 16) for t in DRAW])
          + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in DRAW]))
print(f"{len(DRAW)} drawable things, WARM bindings, keys=0")

runners = {}
if args.m14:
    runners["M14 bin+things"] = (FjmRunner(str(ROOT / args.m14)), True)
if args.dec:
    runners["pre-M14 dec  "] = (FjmRunner(str(ROOT / args.dec)), False)

print(f"\n{'viewpoint':30s} " + " ".join(f"{k:>17s}" for k in runners) +
      ("           delta  pixels" if len(runners) == 2 else ""))
all_same = True
for vx, vy, va in VPS:
    got, px = [], []
    for name, (r, m14) in runners.items():
        feed = (encode_feed_mapunits(vx, vy, va, 0) + THINGS if m14
                else f"{vx}\n{vy}\n{va}\n".encode())
        scr = StreamScreen(stdin=feed, n_things=len(DRAW) if m14 else 0)
        got.append(r.run(scr))
        px.append(bytes(scr.pixel_indices))
    if args.oracle:
        # today's oracle, with m14_gate.py's RENDER_KW -- the definition of the frame both
        # binaries are supposed to draw. `m14_gate.py` phase 1 already certifies the M14 binary
        # against it, so a mismatch on the OTHER column localises the change to the old binary.
        want = bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                          **RENDER_KW))
        for nm, p in zip(runners, px):
            nd = sum(1 for a, b in zip(p, want) if a != b)
            print(f"    vs TODAY's oracle: {nm.strip():16s} "
                  + ("BYTE-EXACT" if nd == 0 else f"!! {nd} of {len(want)} px DIFFER"), flush=True)
    line = f"({vx},{vy},{va:#x})".ljust(30) + " ".join(f"{o:17,}" for o in got)
    if len(got) == 2:
        # ⚠ THE CONTROL. A delta between two binaries is "what M14 costs" only if the two draw the
        # SAME FRAME. If they do not, the difference also contains whatever else changed between
        # them, and calling it M14's overhead would be exactly the unevidenced attribution
        # docs/handoff-perf.md §0 forbids.
        same = px[0] == px[1]
        nd = sum(1 for a, b in zip(*px) if a != b)
        all_same &= same
        line += f"  {got[0] - got[1]:+14,}  " + ("IDENTICAL" if same else f"!! {nd} px DIFFER")
    print(line, flush=True)
if len(runners) == 2:
    print("\nthe two binaries draw the SAME FRAME at every viewpoint -- the delta is M14's cost"
          if all_same else
          "\n!! THE BINARIES DRAW DIFFERENT FRAMES -- the delta is NOT M14's cost alone")
