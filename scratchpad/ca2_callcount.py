"""EXACT per-frame call counts for the four dropped constant-address candidates.

The oracle mirrors the fj program call-for-call (that is the repo's contract), so counting
oracle calls counts fj calls. A saving is then price_per_call x count -- arithmetic, not a guess.

CONTROLS (R9):
  * a two-sided vacuity control: with the counters installed the frame must still be BYTE-EXACT
    against an uninstrumented render (the wrappers must not change behaviour), AND the counters
    must be non-zero (a counter that reads 0 everywhere is not evidence of a cheap call site).
  * counts are reported per viewpoint, never as a single mean.

    python scratchpad/ca2_callcount.py [--sweep 12]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                       # noqa: E402
from doomfj.fixedpoint import _signed                                  # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,          # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                         # noqa: E402
from nb_validate import true_sector, _near_any_line                    # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--sweep", type=int, default=8, help="extra walkable sweep points to sample")
ap.add_argument("--step", type=int, default=192)
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16

GATE = [(664, 291, 0x18000000), (1272, -724, 1073741824),
        (1869, 479, 2147483648), (spx, spy, sp.angle)]

# ---- the sweep's own walkable grid (same construction as scratchpad/m1_sweep.py) --------------
verts = [(v.x, v.y) for v in mw.vertexes("E1M1")]
lds, sds = mw.linedefs("E1M1"), mw.sidedefs("E1M1")
xs, ys = [v[0] for v in verts], [v[1] for v in verts]
walk = []
for x in range(min(xs) + 13, max(xs), args.step):
    for y in range(min(ys) + 7, max(ys), args.step):
        if _near_any_line(verts, lds, x, y, 24.0):
            continue
        if true_sector(verts, lds, sds, x, y) == -1:
            continue
        walk.append((x, y, 0x20000000))
step = max(1, len(walk) // max(1, args.sweep))
SWEEP = walk[::step][:args.sweep]

COUNTED = ("read_sin", "read_cos", "angle_to_x", "scale_from_global_angle",
           "point_to_angle", "point_to_dist")
counts = {}


def install():
    for nm in COUNTED:
        orig = getattr(ReferenceModel, nm)
        if getattr(orig, "_ca2", False):
            continue

        def mk(nm, orig):
            def w(self, *a, **k):
                counts[nm] = counts.get(nm, 0) + 1
                return orig(self, *a, **k)
            w._ca2 = True
            return w
        setattr(ReferenceModel, nm, mk(nm, orig))


def render(vx, vy, va):
    return rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                wall_noise=True, near_steps=True, stack_steps=True,
                                things=True, sprite_wad=art, degrade=True)


# ---- CONTROL (two-sided): uninstrumented picture first, then instrumented ---------------------
vx, vy, va = GATE[0]
clean = bytes(render(vx, vy, va))
install()
counts.clear()
instr = bytes(render(vx, vy, va))
print("CONTROL 1 (wrappers are transparent): frame %s"
      % ("BYTE-EXACT  ok" if instr == clean else "!! DIFFERS -- the counters changed behaviour"))
nz = [k for k, v in counts.items() if v]
print("CONTROL 2 (counters are live)       : %d of %d counted names fired  %s"
      % (len(nz), len(COUNTED), "ok" if len(nz) == len(COUNTED) else "!! a name never fired"))
ctl_ok = instr == clean and len(nz) == len(COUNTED)
print("")

hdr = "%-26s" % "viewpoint" + "".join("%16s" % c for c in COUNTED)
print(hdr)
print("-" * len(hdr))
rows = []
for tag, vps in (("GATE", GATE), ("SWEEP", SWEEP)):
    for vx, vy, va in vps:
        counts.clear()
        render(vx, vy, va)
        row = dict(counts)
        rows.append((tag, (vx, vy, va), row))
        print("%-26s" % ("%s (%d,%d,%#x)" % (tag, vx, vy, va))
              + "".join("%16s" % format(row.get(c, 0), ",") for c in COUNTED))

print("")
for tag in ("GATE", "SWEEP"):
    sel = [r for t, _v, r in rows if t == tag]
    if not sel:
        continue
    print("%-26s" % ("%s median" % tag)
          + "".join("%16s" % format(sorted(r.get(c, 0) for r in sel)[len(sel) // 2], ",")
                    for c in COUNTED))
print("")
print("ca2_callcount: %s" % ("PASS" if ctl_ok else "FAIL (controls)"))
sys.exit(0 if ctl_ok else 1)
