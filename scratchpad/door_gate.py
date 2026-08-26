"""D0 — THE GATE THAT CAN SEE A DOOR MOVE. Oracle-only; no fj build.

WHY THIS EXISTS, AND WHY IT COMES FIRST. Doors change a sector's ceiling height at runtime, and
this repo's contract is that both mirrors agree byte-for-byte. But MEASURED (design investigation,
2026-08-19): with EVERY door and lift on the map fully open, `deg_gate`'s four certified viewpoints
render **0 pixels different**. So today the repo could ship a completely broken door and every gate
would pass. Writing door code before this gate exists would produce rungs that cannot be verified —
CLAUDE.md rule 2.

WHAT IT DOES
  1. finds the door/lift sectors from the map itself (the back side of any special linedef);
  2. searches viewpoints for ones where opening a door actually CHANGES PIXELS, and reports how
     many — a viewpoint that cannot see a door is useless as a door gate no matter how pretty;
  3. asserts the three properties a door gate must have:
       * CLOSED renders exactly what the door-free scene renders (so adding the mechanism with
         every door shut is a no-op -- this is what keeps every existing golden valid);
       * OPEN differs from CLOSED at a viewpoint that can see it (non-vacuity -- the control the
         plane-gate bug and the visibility flag both needed);
       * a MID height differs from both (the door really sweeps; it does not teleport).

⚠ WHAT IT DOES NOT DO. This is the ORACLE half. It proves the reference model moves a door and that
the movement is visible. It says NOTHING about the fj side -- that needs a build, and it is the
next rung. Do not quote this as "doors work".

    python scratchpad/door_gate.py [--wad tests/fixtures/freedoom_e1m1.wad] [--search]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import door_sectors, heights_at, stops                  # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--map", default="E1M1")
ap.add_argument("--search", action="store_true",
                help="scan a grid for the viewpoints that see a door best (slow: one render each)")
ap.add_argument("--quant", type=int, default=16,
                help="door height quantum. MEASURED: a 2-unit sweep visits 785 distinct ceiling "
                     "heights and the emitter's pid field is ONE BYTE (255, 152 already used); at "
                     "16 units it is 26 -- which is also the right visual step at ~7 fps, where a "
                     "2-unit door would take 64 frames to open.")
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)

secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)

# -- the doors, from doomfj.doors -------------------------------------------------------------
# THE MODEL LIVES IN ONE PLACE. It used to be written out here, and the emitter would have had to
# write it out again: see doomfj/doors.py for what a door is (stored shut, opens to
# min(neighbouring ceiling) - 4) and why the first version of this file measured a LIFT instead.
doors = door_sectors(secs, lds, sds)
print(f"{args.map}: {len(secs)} sectors, {len(doors)} REAL doors (stored shut), "
      f"{len(set(doors.values()))} distinct open heights {sorted(set(doors.values()))}", flush=True)


def door_state(frac):
    """`frac` 0.0 = shut (ceiling on the floor), 1.0 = fully open."""
    return heights_at(secs, lds, sds, frac, args.quant)


def height_set():
    """Every ceiling height a quantised sweep can produce. The emitter bakes a pid per (ceiling,
    floor) PAIR, so this is NOT the pid cost -- 13 doors sharing 27 heights at quant 16 cost 94
    pids, not 27. scratchpad/m2_budget.py does that arithmetic against the real baked count."""
    return {h for si, oh in doors.items() for h in stops(secs[si].floor_h, oh, args.quant)}


def render(vp, frac=None):
    sc = build_scene(mw, mw, args.map, None if frac is None else door_state(frac))
    vx, vy, va = vp
    return bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, va, args.map), sc, **RENDER_KW))


def diff(a, b):
    return sum(1 for x, y in zip(a, b) if x != y)


sp = spawn_state(mw, args.map)
SPX, SPY = sp.x >> 16, sp.y >> 16
# The gate set is TWO groups with different jobs:
#   DOOR viewpoints -- found by --search over a 384-unit grid x 4 angles, ranked by how many pixels
#     a door actually moves. These are what makes the gate NON-VACUOUS; the certified four could
#     not do it (two of them see 0 px with every door open).
#   CERTIFIED viewpoints -- deg_gate's four. They see little or nothing of a door, and that is the
#     point: they are the NO-REGRESSION half, proving the door mechanism does not disturb the
#     picture everywhere else.
DOOR_VPS = [(461, 2015, 0x40000000),     # 2,720 px shut->open  (MEASURED 2026-08-19)
            (845, 1631, 0xC0000000),     # 2,664 px
            (461, 863, 0x40000000)]      # 693 px
VPS = DOOR_VPS + [(SPX, SPY, sp.angle), (664, 291, 0x18000000),
                  (1272, -724, 0x40000000), (1869, 479, 0x80000000)]

if args.search:
    # a viewpoint that cannot SEE a door is worthless as a door gate; find ones that can
    print("\nsearching for viewpoints that see a door (open vs shut):", flush=True)
    from nb_validate import true_sector, _near_any_line
    verts = [(v.x, v.y) for v in mw.vertexes(args.map)]
    xs, ys = [v[0] for v in verts], [v[1] for v in verts]
    best = []
    for x in range(min(xs) + 13, max(xs), 384):
        for y in range(min(ys) + 7, max(ys), 384):
            if _near_any_line(verts, lds, x, y, 24.0) or true_sector(verts, lds, sds, x, y) == -1:
                continue
            for va in (0, 0x40000000, 0x80000000, 0xC0000000):
                d = diff(render((x, y, va), 0.0), render((x, y, va), 1.0))
                if d:
                    best.append((d, (x, y, va)))
    best.sort(reverse=True)
    for d, vp in best[:10]:
        print(f"  {d:>6} px  ({vp[0]},{vp[1]},{vp[2]:#010x})", flush=True)
    if not best:
        print("  !! NO viewpoint on the grid sees a door -- widen the grid before trusting this")
    VPS = [vp for _d, vp in best[:3]] or VPS

print(f"\nviewpoints under test: {[f'({a},{b},{c:#x})' for a, b, c in VPS]}", flush=True)
ok, saw_change, saw_mid = True, 0, 0
for vp in VPS:
    base = render(vp, None)          # the door-free scene: no override at all
    shut = render(vp, 0.0)
    mid = render(vp, 0.5)
    open_ = render(vp, 1.0)
    # ⚠ THE CONTROL THAT KEEPS EVERY EXISTING GOLDEN VALID: a door at frac=0 IS the wad's stored
    # state, so the override must be a no-op there -- if this differs, adding the door mechanism
    # would move every existing golden and nothing else in this gate can be believed.
    d_noop = diff(base, shut)
    d_open = diff(shut, open_)
    d_mid_s = diff(shut, mid)
    d_mid_o = diff(mid, open_)
    noop_ok = d_noop == 0
    ok &= noop_ok
    saw_change += d_open > 0
    saw_mid += (d_mid_s > 0 and d_mid_o > 0)
    print(f"  ({vp[0]},{vp[1]},{vp[2]:#010x}): shut->open {d_open:>6} px   "
          f"shut->mid {d_mid_s:>6}   mid->open {d_mid_o:>6}   "
          f"{'shut==wad ok' if noop_ok else '!! SHUT DIFFERS FROM THE WAD (%d px)' % d_noop}",
          flush=True)

print(f"\nCONTROLS:")
print(f"  1. a viewpoint actually SEES a door open ....... "
      f"{'ok -- %d of %d' % (saw_change, len(VPS)) if saw_change else 'FAIL -- VACUOUS, this gate proves nothing'}")
print(f"  2. the door SWEEPS (mid differs from both) .... "
      f"{'ok -- %d of %d' % (saw_mid, len(VPS)) if saw_mid else 'FAIL -- the door teleports'}")
ok = bool(ok and saw_change and saw_mid)
print(f"\n{'PASS -- this gate can see a door move' if ok else 'FAIL -- do not build doors against this gate'}")
sys.exit(0 if ok else 1)
