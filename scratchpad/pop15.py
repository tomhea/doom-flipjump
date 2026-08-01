"""Per-viewpoint POPULATION probe for the 15M campaign -- oracle-side, no fj build.

The frame's op cost is (population x unit price) summed over stages (fj-cost-model), so the way to
steer a MAP change is to watch the populations the map controls:

  xr1s     wall_x_range calls on ONE-SIDED segs (each pays the wedge cull, survivors pay 2 atans)
  infr     in-frustum segs (non-None range -> clip + occlusion scan)
  p2seg    pass-2 segs = wall_scale_setup calls on one-sided walls (~93k EACH, the dearest)
  mark     marking two-sided segs walked (plane_near attribution, ~40k each)
  face     step-face segs (V3, a ~93k scale setup each)
  thproj   project_thing calls (~20k each after the cheap rejects)
  thacc    ... of which accepted (sprite strips + record loop)
  cols     columns claimed (the 160-column budget actually spent)

Usage:
  python scratchpad/pop15.py [--wad tests/fixtures/freedoom_e1m1.wad] [--map E1M1] [--grid 5]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState, build_scene,  # noqa: E402
                                    spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--map", default="E1M1")
ap.add_argument("--grid", type=int, default=5)
ap.add_argument("--angles", type=int, default=2)
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(args.wad)
art = WadFile.from_path('assets/freedoom1.wad')
scene = build_scene(mw, mw, args.map)
sp = spawn_state(mw, args.map)
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16

lds = mw.linedefs(args.map)

C = {}


def wrap(name, orig, count):
    def f(self, *a, **k):
        r = orig(self, *a, **k)
        count(C, r, a)
        return r
    setattr(ReferenceModel, name, f)
    return orig


def c_xr(C, r, a):
    seg = a[3]
    key = "xr1s" if lds[seg.linedef].back == -1 else "mark"
    C[key] = C.get(key, 0) + 1
    if r is not None and lds[seg.linedef].back == -1:
        C["infr"] = C.get("infr", 0) + 1


o_xr = wrap("wall_x_range", ReferenceModel.wall_x_range, c_xr)
o_ws = wrap("wall_setup", ReferenceModel.wall_setup,
            lambda C, r, a: C.__setitem__("setup", C.get("setup", 0) + 1))
o_sc = wrap("scale_from_global_angle", ReferenceModel.scale_from_global_angle,
            lambda C, r, a: C.__setitem__("scale", C.get("scale", 0) + 1))
o_pt = wrap("project_thing", ReferenceModel.project_thing,
            lambda C, r, a: (C.__setitem__("thproj", C.get("thproj", 0) + 1),
                             C.__setitem__("thacc", C.get("thacc", 0) + (r is not None))))
o_sp = wrap("wall_screen_span", ReferenceModel.wall_screen_span,
            lambda C, r, a: C.__setitem__("cols", C.get("cols", 0) + 1))

VPS = [(sx, sy, sp.angle, "spawn")]
if args.map == "E1M1":
    VPS += [(1400, 1200, 0, "courtyard"), (2432, 1344, 3221225472, "tree"),
            (-309, -44, 0, "worst")]
xs = [v[0] for v in scene.cmap.vertexes]
ys = [v[1] for v in scene.cmap.vertexes]
G, NA = args.grid, args.angles
for i in range(G):
    for j in range(G):
        px = min(xs) + (max(xs) - min(xs)) * (2 * i + 1) // (2 * G)
        py = min(ys) + (max(ys) - min(ys)) * (2 * j + 1) // (2 * G)
        for k in range(NA):
            VPS.append((px, py, (k << 30) & 0xFFFFFFFF, f"g{i}{j}a{k}"))

print(f"{'viewpoint':16s} {'xr1s':>5} {'infr':>5} {'mark':>5} {'setup':>5} {'scale':>5} "
      f"{'thproj':>6} {'thacc':>5} {'cols':>5}")
rows = []
for vx, vy, va, tag in VPS:
    C.clear()
    rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level=args.map), scene,
                         wall_mode="WPX", floor_mode_ft1=True, plane_near=True,
                         wall_noise=True, sky=True, near_steps=True, things=True,
                         sprite_wad=art)
    row = dict(C)
    row["vp"] = (vx, vy, va, tag)
    rows.append(row)
    print(f"{tag:16s} {C.get('xr1s',0):5d} {C.get('infr',0):5d} {C.get('mark',0):5d} "
          f"{C.get('setup',0):5d} {C.get('scale',0):5d} {C.get('thproj',0):6d} "
          f"{C.get('thacc',0):5d} {C.get('cols',0):5d}", flush=True)

# a crude scalar to rank viewpoints: unit prices from fj-cost-model (in-context)
def score(r):
    return (r.get('xr1s', 0) * 3.4 + r.get('infr', 0) * 20 + r.get('mark', 0) * 25
            + r.get('setup', 0) * 30 + r.get('scale', 0) * 45 + r.get('thproj', 0) * 12
            + r.get('thacc', 0) * 30) / 1000.0   # ~M ops of variable cost


rows.sort(key=score, reverse=True)
print("\nheaviest viewpoints by modelled variable cost:")
for r in rows[:8]:
    vx, vy, va, tag = r["vp"]
    print(f"  {tag:12s} ({vx},{vy},{va:#x})  ~{score(r):.1f}M var  "
          f"xr1s={r.get('xr1s',0)} infr={r.get('infr',0)} mark={r.get('mark',0)} "
          f"scale={r.get('scale',0)} thproj={r.get('thproj',0)}")
print(f"\nmap totals: segs={len(scene.cmap.segs)} subsectors={len(scene.cmap.subsectors)} "
      f"nodes={len(mw.nodes(args.map))} things={len(mw.things(args.map))}")
