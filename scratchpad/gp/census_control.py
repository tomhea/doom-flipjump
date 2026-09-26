"""S5 census -- THE CONTROL: the instrumentation leaves the oracle's pixels unchanged.

    python scratchpad/gp/census_control.py

1. STOCK: `render_wall_frame` with nothing patched, at eleven viewpoints (spawn, the deg_gate sprite
   frames' family, the atlas profile points, and two OUTDOOR ones -- the S4 courtyard and east-yard
   checkpoints, where the sky shows), today's things, doors shut, with the census's keyword set
   (census_lib.RENDER_KW = deg_gate's = the game tier's: `sky` and `bbox_cull` on).
2. INSTRUMENTED: the same eleven through `Census.render(today_things())` -- every hook installed
   (drawable/baked swap, MONSTER_TYPES swap, sprite_art and project_thing wrappers).
   PASS = byte-identical at all eleven, and the attributed slot claims add up to the slot arrays.
3. NEGATIVE CONTROL: the instrumented path with ONE visible thing removed from the list must CHANGE
   the picture -- proof the comparison can fail.
4. THE KEYWORDS HAVE TEETH: per viewpoint, the pixels that move when `sky` is turned off (must be
   non-zero at the outdoor viewpoints, or the sky keyword was never exercised) and when `bbox_cull`
   is turned off (expected 0: the cull is a stop), plus the thing ARRIVALS the cull removes -- the
   per-thing load/project terms the fight line prices.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config                                            # noqa: E402
from doomfj.reference_model import ReferenceModel, SimState, build_scene   # noqa: E402
from doomfj.wad import WadFile                                              # noqa: E402

VPS = [("spawn", -416, 256, 0x0), ("gate664", 664, 291, 0x18000000),
       ("gate1869", 1869, 479, 0x80000000), ("h57", 2893, 2015, 0x80000000),
       ("h71", 2637, 991, 0x0), ("h100", 2637, 991, 0x40000000), ("h28", 2893, 1503, 0x0),
       ("h42", 2381, -289, 0xC0000000), ("h85", 333, -33, 0x40000000),
       ("court", 1424, 732, 0x40000000), ("eastyard", 2052, 680, 436739414)]   # S4 checkpoints
KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True, near_steps=True,
          stack_steps=True, things=True, degrade=True, sky=True, bbox_cull=True)

mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
stock_rm = ReferenceModel(Config())


def stock(kw):
    return {n: bytes(stock_rm.render_wall_frame(SimState(x << 16, y << 16, a, "E1M1"), scene,
                                                sprite_wad=art, **kw)) for n, x, y, a in VPS}


t0 = time.perf_counter()
ref = stock(KW)
nosky = stock(dict(KW, sky=False))
nocull = stock(dict(KW, bbox_cull=False))
print("stock renders: %d viewpoints x 3 keyword sets, %.1f s" % (len(ref), time.perf_counter() - t0))

import census_lib as CL                                                     # noqa: E402

assert KW == CL.RENDER_KW, "the control must check the census's own keyword set"
c = CL.Census()
ok = True
arr_on = {}
for n, x, y, a in VPS:
    th, bk, me, mt = c.today_things()
    fb, arr = c.render(th, bk, me, mt, scene=scene, state=SimState(x << 16, y << 16, a, "E1M1"))
    sa, sb = c.probe._refs if c.probe._refs else ([None] * 160, [None] * 160)
    na = sum(1 for v in sa if v is not None)
    nb = sum(1 for v in sb if v is not None)
    ca = sum(len(r["A"]) for r in arr)
    cb = sum(len(r["B"]) for r in arr)
    same = fb == ref[n]
    ok &= same and na == ca and nb == cb
    arr_on[n] = len(arr)
    print("  %-9s arrivals %3d  slotA %3d (attributed %3d)  slotB %3d (attributed %3d)  %s"
          % (n, len(arr), na, ca, nb, cb, "BYTE-IDENTICAL" if same else "!! PIXELS DIFFER"))
print("CONTROL: %s" % ("PASS" if ok else "FAIL"))

# negative control: drop the first thing that claimed a column at the heaviest viewpoint
n, x, y, a = VPS[1]
th, bk, me, mt = c.today_things()
fb, arr = c.render(th, bk, me, mt, scene=scene, state=SimState(x << 16, y << 16, a, "E1M1"))
victim = next(r["meta"] for r in arr if r["A"])
keep = [i for i, m in enumerate(me) if m is not victim]
fb2, _ = c.render([th[i] for i in keep], [bk[i] for i in keep], [me[i] for i in keep], mt, scene=scene,
                  state=SimState(x << 16, y << 16, a, "E1M1"))
diff = sum(1 for p, q in zip(fb, fb2) if p != q)
print("NEGATIVE CONTROL (%s without WAD thing %d): %d px differ -> %s"
      % (n, victim.wad, diff, "the comparison has teeth" if diff else "!! VACUOUS"))

# the keywords have teeth: what `sky` and `bbox_cull` each change, per viewpoint
CL.RENDER_KW = dict(KW, bbox_cull=False)
arr_off = {}
for n, x, y, a in VPS:
    th, bk, me, mt = c.today_things()
    _fb, arr = c.render(th, bk, me, mt, scene=scene, state=SimState(x << 16, y << 16, a, "E1M1"))
    arr_off[n] = len(arr)
CL.RENDER_KW = KW
print("KEYWORDS: px moved by sky=False | px moved by bbox_cull=False | arrivals cull on/off")
sky_seen = 0
for n, *_ in VPS:
    ds = sum(1 for p, q in zip(ref[n], nosky[n]) if p != q)
    dc = sum(1 for p, q in zip(ref[n], nocull[n]) if p != q)
    sky_seen += n in ("court", "eastyard") and ds > 0
    print("  %-9s %6d px | %4d px | %3d / %3d" % (n, ds, dc, arr_on[n], arr_off[n]))
sky_ok = sky_seen == 2
print("SKY EXERCISED at both outdoor viewpoints: %s" % ("yes" if sky_ok else "!! NO"))
sys.exit(0 if ok and diff and sky_ok else 1)
