"""Build tests/fixtures/e1m1_lite.wad: E1M1, simplified for the 15M frame budget.

Pipeline: stock wad -> mapsimplify.simplify -> nodebuilder (fresh SEGS/SSECTORS/NODES) -> validate:
  * point location vs the exact ray oracle on a dense walkable grid (nb_validate)
  * every kept monster/weapon/key/start still resolves to a sector with its original floor +-tol
  * oracle renders at the four PLAYABLE gates (the old worst gate (-309,-44) is VOID -- replaced
    by the heaviest walkable stress points pop15 found)
  * population table before/after (the numbers the op cost actually follows)
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.mapsimplify import simplify, MONSTERS, WEAPONS, KEYS, STARTS  # noqa: E402
from doomfj.nodebuilder import NodeBuilder, lumps, write_map_wad          # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState, build_scene,  # noqa: E402
                                    spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402
import struct                                                             # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="tests/fixtures/e1m1_lite.wad")
ap.add_argument("--floor-tol", type=int, default=24)
ap.add_argument("--ceil-tol", type=int, default=32)
ap.add_argument("--light-tol", type=int, default=32)
ap.add_argument("--angle-tol", type=float, default=25.0)
ap.add_argument("--no-thin", action="store_true")
ap.add_argument("--render", action="store_true", help="render gate PNGs + diff vs stock")
args = ap.parse_args()

SRC = "tests/fixtures/freedoom_e1m1.wad"
M = "E1M1"
w = WadFile.from_path(SRC)
verts0 = [(v.x, v.y) for v in w.vertexes(M)]
lds0, sds0, secs0, ths0 = w.linedefs(M), w.sidedefs(M), w.sectors(M), w.things(M)

verts, lds, sds, secs, ths, st = simplify(
    verts0, lds0, sds0, secs0, ths0,
    floor_tol=args.floor_tol, ceil_tol=args.ceil_tol, light_tol=args.light_tol,
    angle_tol_deg=args.angle_tol, thin_things=not args.no_thin)

print(f"simplify: {st}")
print(f"lumps: verts {len(verts0)}->{len(verts)}  lines {len(lds0)}->{len(lds)} "
      f"(1s {sum(1 for l in lds0 if l.back==-1)}->{sum(1 for l in lds if l.back==-1)}) "
      f" sectors {len(secs0)}->{len(secs)}  things {len(ths0)}->{len(ths)}")

nb = NodeBuilder(verts, lds, sds)
nb.build()
print(f"bsp: segs {len(nb.out_segs)} (stock 2057)  ss {len(nb.out_ss)} (682)  "
      f"nodes {len(nb.out_nodes)} (681)  mixed {nb.mixed_leaves}")

ld_lumps = lumps(nb)


def _tex8(s):
    return s.encode().ljust(8, b"\0")


ld_lumps["LINEDEFS"] = b"".join(struct.pack("<7h", l.v1, l.v2, l.flags, l.special, l.tag,
                                            l.front, l.back) for l in lds)
ld_lumps["SIDEDEFS"] = b"".join(struct.pack("<2h8s8s8sh", s.x_off, s.y_off, _tex8(s.upper),
                                            _tex8(s.lower), _tex8(s.middle), s.sector)
                                for s in sds)
ld_lumps["SECTORS"] = b"".join(struct.pack("<2h8s8s3h", s.floor_h, s.ceil_h, _tex8(s.floor_tex),
                                           _tex8(s.ceil_tex), s.light, s.special, s.tag)
                               for s in secs)
ld_lumps["THINGS"] = b"".join(struct.pack("<5h", t.x, t.y, t.angle, t.type, t.flags) for t in ths)
write_map_wad(args.out, M, ld_lumps)
print(f"wrote {args.out}")

# ── validation 1: point location — STOCK ray oracle decides walkability + expected sector.
# (both trees glue VOID onto arbitrary leaves; only stock-walkable points are gameplay-real.)
from nb_validate import true_sector, tree_sector, _near_any_line            # noqa: E402
from doomfj.mapcompiler import bake_bsp as _bake                            # noqa: E402
wl_ = WadFile.from_path(args.out)
cml = _bake(wl_, M)
ldsl_, sdsl_, secsl_ = wl_.linedefs(M), wl_.sidedefs(M), wl_.sectors(M)
xs0 = [v[0] for v in verts0]
ys0 = [v[1] for v in verts0]
n = bad = 0
misses = []
for x in range(min(xs0) + 13, max(xs0), 32):
    for y in range(min(ys0) + 7, max(ys0), 32):
        if _near_any_line(verts0, lds0, x, y, 2.0) or _near_any_line(verts, lds, x, y, 2.0):
            continue
        orig = true_sector(verts0, lds0, sds0, x, y)
        if orig == -1:
            continue                                     # void: the player can never stand here
        want = st.sector_map[orig]
        got = tree_sector(cml, ldsl_, sdsl_, x, y)
        n += 1
        ws, gs = secs[want], secsl_[got]
        if (ws.floor_h, ws.light, ws.floor_tex, ws.ceil_h) != \
           (gs.floor_h, gs.light, gs.floor_tex, gs.ceil_h):
            bad += 1
            misses.append((x, y, want, got))
print(f"point location: {n} stock-walkable points, {bad} render-real mismatches")
for m in misses[:6]:
    print(f"   miss ({m[0]},{m[1]}) want lite sec {m[2]} got {m[3]}")

# ── validation 2: important things keep their footing ──
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
wl = WadFile.from_path(args.out)
cm = bake_bsp(wl, M)
ldsl, sdsl, secsl = wl.linedefs(M), wl.sidedefs(M), wl.sectors(M)
rm = ReferenceModel(Config())


def sector_at(x, y):
    ss = cm.subsectors[rm.point_in_subsector(cm, x, y)]
    seg = cm.segs[ss.firstseg]
    ld = ldsl[seg.linedef]
    return secsl[sdsl[ld.back if seg.side else ld.front].sector]


important = [t for t in ths if t.type in MONSTERS | WEAPONS | KEYS | STARTS]
bad_things = 0
for t in important:
    old = true_sector(verts0, lds0, sds0, t.x, t.y)
    if old == -1:
        continue
    nf = sector_at(t.x, t.y).floor_h
    if abs(nf - secs0[old].floor_h) > 32:
        bad_things += 1
        print(f"   !! thing type {t.type} at ({t.x},{t.y}): floor {secs0[old].floor_h} -> {nf}")
print(f"important things: {len(important)}, {bad_things} with floor shifted >32")

# ── validation 3 + populations: oracle renders at PLAYABLE gates ──
art = WadFile.from_path('assets/freedoom1.wad')
sc0 = build_scene(w, w, M)
scl = build_scene(wl, w, M)
sp = spawn_state(w, M)
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
GATES = [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"),
         (2432, 1344, 3221225472, "tree"), (1272, -724, 0x40000000, "stress1"),
         (1272, -44, 0x40000000, "stress2"), (-309, 636, 0, "stress3")]
kw = dict(wall_mode="WPX", floor_mode_ft1=True, plane_near=True, wall_noise=True,
          sky=True, near_steps=True, things=True, sprite_wad=art)
for vx, vy, va, tag in GATES:
    stt = SimState(x=vx << 16, y=vy << 16, angle=va, level=M)
    f0 = rm.render_wall_frame(stt, sc0, **kw)
    f1 = rm.render_wall_frame(stt, scl, **kw)
    d = sum(1 for a, b in zip(f0, f1) if a != b)
    print(f"render {tag:10s}: {d:6d} px differ vs stock ({d/160:.0f} cols worth)")
    if args.render:
        from PIL import Image                                             # noqa: E402
        pal = w.playpal()
        for name, fb in (("stock", f0), ("lite", f1)):
            img = Image.new("RGB", (160, 100))
            img.putdata([pal[b] for b in fb])
            img.resize((640, 400), Image.NEAREST).save(f"scratchpad/lite_{tag}_{name}.png")
