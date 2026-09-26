"""S7 lift spike -- the geometry questions a lift rung must settle before any fj, answered from the map.
No build, no render. Every number printed here is a fact of freedoom_e1m1.wad plus DOOM's rules.

    python scratchpad/gp/lift/lift_geometry.py

1. CRUSH: can a rising lift ever fail to fit a shootable thing (DOOM's P_ChangeSector -> the lift
   reverses)? Conservative bound: at the lift's TOP, the smallest ceiling any line of the lift touches
   minus the largest floor any of them touches, against the tallest shootable thing (56).
2. The lnrow patch: for every mover line, how many BITS of the packed row change per state step
   (openbottom only -- a floor mover cannot move a ceiling), i.e. the raw flips a step executes.
3. The trigger lines (88 WR lift / 62 SR lift / 23 S1 floor): where they are, whether they are
   axis-aligned (a side test is one compare) and which sectors they separate.
4. Doors and things: which barrels (the only static SHOOTABLE things) stand close enough to a door
   line to ever stop it closing, and whether any mover or door leaf holds a thing at spawn.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj.collision import LINE_REST_BYTES, line_rest, line_rows      # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import door_sectors, door_states, stops                 # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import ReferenceModel, apply_sector_heights   # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

rm = ReferenceModel(Config())
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
M = "E1M1"
secs, lds, sds, things = mw.sectors(M), mw.linedefs(M), mw.sidedefs(M), mw.things(M)
verts = [(v.x, v.y) for v in mw.vertexes(M)]
cmap = bake_bsp(mw, M)
LIFTS, FSWITCH = (98, 103), (76, 126, 129)
TALLEST = 56                                    # player, zombieman, shotgun guy, imp, demon (info.c)


def sec_of(sd):
    return sds[sd].sector if sd != 0xFFFF and sd < len(sds) else None


nbr = {}
lines_of = {}
for li, ld in enumerate(lds):
    f, b = sec_of(ld.front), sec_of(ld.back)
    for s in (f, b):
        if s is not None:
            lines_of.setdefault(s, []).append(li)
    if f is not None and b is not None and f != b:
        nbr.setdefault(f, set()).add(b); nbr.setdefault(b, set()).add(f)


def low_of(si):
    return min([secs[n].floor_h for n in nbr.get(si, ())] + [secs[si].floor_h])


print("1. CRUSH -- can a RISING lift fail to fit a %d-unit shootable thing?" % TALLEST)
for si in LIFTS:
    hi = secs[si].floor_h
    ns = sorted(nbr.get(si, ()))
    ceil_min = min([secs[si].ceil_h] + [secs[n].ceil_h for n in ns])
    floor_max = max([hi] + [secs[n].floor_h for n in ns])
    pair = min(min(secs[si].ceil_h, secs[n].ceil_h) - max(hi, secs[n].floor_h) for n in ns)
    print("   lift %3d top %4d ceil %4d, neighbours %s" % (si, hi, secs[si].ceil_h,
          [(n, secs[n].floor_h, secs[n].ceil_h) for n in ns]))
    print("      worst corner (min ceiling - max floor over ALL touched sectors) = %d; worst single edge = %d"
          " -> %s" % (ceil_min - floor_max, pair,
                      "NEVER crushes (no reversal logic needed)" if ceil_min - floor_max >= TALLEST
                      else ("edge-safe; a corner case needs the rule" if pair >= TALLEST
                            else "CAN crush: the reversal rule is needed")))
print("   floor switch sectors only LOWER; a lowering floor never refuses a thing (T_MovePlane down).")

print("\n2. LNROW PATCH -- raw bit flips per state step (openbottom, 16-bit two's complement):")
DOORS = door_states(secs, lds, sds, 16)
dopen = apply_sector_heights(secs, {s: (secs[s].floor_h, st[-1]) for s, st in DOORS.items()})
OB = sum(LINE_REST_BYTES[:-1])                       # openbottom is the last rest field
for si, q in [(s, 16) for s in LIFTS] + [(s, 16) for s in FSWITCH]:
    hs = list(reversed(stops(low_of(si), secs[si].floor_h, q)))
    rows_k = []
    for h in hs:
        sv = apply_sector_heights(dopen, {si: (h, secs[si].ceil_h)})
        rows_k.append(line_rows(lds, verts, sv, sds, 1))
    mlines = sorted(set(lines_of.get(si, [])))
    per_step = []
    for k in range(len(hs) - 1):
        flips = 0
        for li in mlines:
            a, b = line_rest(rows_k[k][li])[-1], line_rest(rows_k[k + 1][li])[-1]
            flips += bin((a ^ b) & 0xFFFF).count("1")
        per_step.append(flips)
    print("   sector %3d: %2d lines, %2d states, flips per step %s (max %d)"
          % (si, len(mlines), len(hs), per_step, max(per_step)))

print("\n3. TRIGGER LINES:")
for li, ld in enumerate(lds):
    if ld.special in (88, 62, 23, 2, 11):
        (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
        axis = "vertical" if x1 == x2 else ("horizontal" if y1 == y2 else "DIAGONAL")
        print("   line %4d special %3d tag %d (%5d,%5d)-(%5d,%5d) %-10s front %s back %s flags %#x"
              % (li, ld.special, ld.tag, x1, y1, x2, y2, axis, sec_of(ld.front), sec_of(ld.back),
                 ld.flags))

print("\n4. THINGS AND DOORS:")
leaf_sec = {}
for k, ss in enumerate(cmap.subsectors):
    if ss.numsegs:
        seg = cmap.segs[ss.firstseg]
        ld = lds[seg.linedef]
        leaf_sec[k] = sds[ld.front if seg.side == 0 else ld.back].sector
def sector_at(x, y):
    return leaf_sec.get(rm.point_in_subsector(cmap, x, y))
movers = set(LIFTS) | set(FSWITCH)
dsec = door_sectors(secs, lds, sds)
at_spawn = [(i, t.type, sector_at(t.x, t.y)) for i, t in enumerate(things)
            if sector_at(t.x, t.y) in movers | set(dsec)]
print("   things standing in a mover or door sector at spawn: %s" % (at_spawn or "none"))
BARREL, RAD = 2035, 10
near = []
for i, t in enumerate(things):
    if t.type != BARREL:
        continue
    for si in dsec:
        for li in lines_of.get(si, []):
            (x1, y1), (x2, y2) = verts[lds[li].v1], verts[lds[li].v2]
            if (min(x1, x2) - RAD <= t.x <= max(x1, x2) + RAD
                    and min(y1, y2) - RAD <= t.y <= max(y1, y2) + RAD):
                near.append((i, si, li))
print("   barrels whose box can touch a door line (static door blockers): %s" % (near or "none"))
