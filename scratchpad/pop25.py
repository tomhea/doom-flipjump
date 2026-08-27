"""Population probe for the 25M-cap campaign: oracle-side counts for every sweep frame,
joined with measured fj ops (scratchpad/sweep_frames.csv), plus a least-squares fit of
per-population unit prices. The fit is the cheap predictor that lets degradation levers be
trialed WITHOUT a 25-minute fj build each.

    python scratchpad/pop25.py [--csv scratchpad/sweep_frames.csv] [--out scratchpad/pop25.csv]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config, PNEAR_SEG_BUDGET                        # noqa: E402
from doomfj.reference_model import ReferenceModel, SimState, build_scene  # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="scratchpad/sweep_frames.csv")
ap.add_argument("--out", default="scratchpad/pop25.csv")
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
W = cfg.VIEW_W
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
lds = mw.linedefs("E1M1")

frames = []
with open(args.csv, encoding="utf-8") as f:
    next(f)
    for line in f:
        x, y, a, o = line.strip().split(",")
        frames.append((int(x), int(y), int(a), int(o)))
print(f"{len(frames)} frames from {args.csv}")

C: dict = {}


def wrap(name, count):
    orig = getattr(ReferenceModel, name)

    def f(self, *a, **k):
        r = orig(self, *a, **k)
        count(C, r, a)
        return r
    setattr(ReferenceModel, name, f)


def c_xr(C, r, a):
    seg = a[3]
    two = lds[seg.linedef].back != -1
    C["mark" if two else "xr1s"] = C.get("mark" if two else "xr1s", 0) + 1
    if r is not None:
        C["infr2s" if two else "infr"] = C.get("infr2s" if two else "infr", 0) + 1


wrap("wall_x_range", c_xr)
wrap("wall_setup", lambda C, r, a: C.__setitem__("setup", C.get("setup", 0) + 1))
wrap("scale_from_global_angle",
     lambda C, r, a: C.__setitem__("scale", C.get("scale", 0) + 1))
wrap("project_thing",
     lambda C, r, a: (C.__setitem__("thproj", C.get("thproj", 0) + 1),
                      C.__setitem__("thacc", C.get("thacc", 0) + (r is not None))))
_orig_sstrip = ReferenceModel.sprite_strip


def _sstrip(*a, **k):                       # staticmethod: no self to inject
    C["sstrip"] = C.get("sstrip", 0) + 1
    return _orig_sstrip(*a, **k)


ReferenceModel.sprite_strip = staticmethod(_sstrip)
wrap("wall_screen_span", lambda C, r, a: C.__setitem__("cols", C.get("cols", 0) + 1))

rows = []
for i, (vx, vy, va, ops) in enumerate(frames):
    C.clear()
    so: list = []
    rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene,
                         wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                         wall_noise=True, sky=True, near_steps=True, things=True,
                         sprite_wad=art, bbox_cull=True, stack_steps=True, steps_out=so)
    ups, los = so[0]
    pieces = sum(len(ups[x]) + len(los[x]) for x in range(W))
    fcols = sum(1 for x in range(W) if len(ups[x]) + len(los[x]) >= 1)
    r = dict(C)
    r.update(x=vx, y=vy, angle=va, ops=ops, pieces=pieces, fcols=fcols)
    rows.append(r)
    if (i + 1) % 40 == 0:
        print(f"  ...{i+1}/{len(frames)}", flush=True)

KEYS = ["xr1s", "mark", "infr", "infr2s", "setup", "scale", "thproj", "thacc",
        "sstrip", "cols", "pieces", "fcols"]
with open(args.out, "w", encoding="utf-8") as f:
    f.write("x,y,angle,ops," + ",".join(KEYS) + "\n")
    for r in rows:
        f.write(f"{r['x']},{r['y']},{r['angle']},{r['ops']},"
                + ",".join(str(r.get(k, 0)) for k in KEYS) + "\n")
print(f"wrote {args.out}")

# ---- least-squares unit prices: ops ~= base + sum(price_k * pop_k)
import numpy as np                                                        # noqa: E402

A = np.array([[1.0] + [r.get(k, 0) for k in KEYS] for r in rows])
b = np.array([r["ops"] for r in rows], dtype=float)
coef, res, rank, _sv = np.linalg.lstsq(A, b, rcond=None)
pred = A @ coef
err = pred - b
print(f"\nfit over {len(rows)} frames  rank {rank}/{A.shape[1]}")
print(f"residual: mean|err| {np.mean(np.abs(err))/1e6:.3f}M  max|err| "
      f"{np.max(np.abs(err))/1e6:.3f}M  R2 {1 - np.var(err)/np.var(b):.4f}")
print(f"{'term':>8s} {'price':>12s}")
print(f"{'base':>8s} {coef[0]:12,.0f}")
for k, c in zip(KEYS, coef[1:]):
    print(f"{k:>8s} {c:12,.0f}")

# the worst frames' population profile
rows.sort(key=lambda r: -r["ops"])
print(f"\n{'ops':>12s} {'vp':>22s}  " + " ".join(f"{k:>6s}" for k in KEYS))
for r in rows[:12]:
    vp = f"({r['x']},{r['y']},{r['angle']>>28:x})"
    print(f"{r['ops']:12,} {vp:>22s}  " + " ".join(f"{r.get(k, 0):6d}" for k in KEYS))
