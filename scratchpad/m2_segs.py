"""M2-R0 -- WHICH SEGS a door actually touches, and what each one has baked into it.

The handoff says "a compile-time-addressed dynamic height cell for the 7.8% of segs touching door
sectors". This checks that 7.8% and, more usefully, splits it by WHAT the seg has baked, because
the two halves need different machinery:

  FRONT-side segs  -- the seg's own sector is the door. Its plane pair (pid) and its wall/render
                      constants are baked from that sector's ceil_h.
  BACK-side segs   -- the seg looks AT the door. Its V5 stacked upper piece (the bit of wall
                      between this side's ceiling and the door's) is baked from the door's ceil_h.
                      This is the half a player actually watches move.

    python scratchpad/m2_segs.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
cmap = bake_bsp(mw, "E1M1")

nb = {}
for ld in lds:
    f = sds[ld.front].sector if ld.front != 0xFFFF and ld.front < len(sds) else None
    b = sds[ld.back].sector if ld.back != 0xFFFF and ld.back < len(sds) else None
    if f is not None and b is not None and f != b:
        nb.setdefault(f, set()).add(b); nb.setdefault(b, set()).add(f)
doors = {}
for ld in lds:
    if ld.special and ld.back != 0xFFFF and ld.back < len(sds):
        si = sds[ld.back].sector
        if secs[si].ceil_h == secs[si].floor_h and nb.get(si):
            doors[si] = min(secs[n].ceil_h for n in nb[si]) - 4


def sides(seg):
    """(front sector, back sector-or-None) for a seg, the way the emitter reads them."""
    ld = lds[seg.linedef]
    f = sds[ld.front if seg.side == 0 else ld.back].sector
    b = (sds[ld.back if seg.side == 0 else ld.front].sector) if ld.back != -1 else None
    return f, b


front_hits, back_hits, both = set(), set(), set()
for i, seg in enumerate(cmap.segs):
    f, b = sides(seg)
    if f in doors:
        front_hits.add(i)
    if b is not None and b in doors:
        back_hits.add(i)
for i in front_hits & back_hits:
    both.add(i)

n = len(cmap.segs)
print("E1M1: %d segs, %d subsectors, %d door sectors" % (n, len(cmap.subsectors), len(doors)))
print("")
print("  segs whose OWN sector is a door (pid + render consts) : %4d  (%.1f%%)"
      % (len(front_hits), 100.0 * len(front_hits) / n))
print("  segs LOOKING AT a door (V5 stacked upper piece)       : %4d  (%.1f%%)"
      % (len(back_hits), 100.0 * len(back_hits) / n))
print("  both sides                                            : %4d" % len(both))
print("  UNION -- segs a door can change at all                : %4d  (%.1f%%)"
      % (len(front_hits | back_hits), 100.0 * len(front_hits | back_hits) / n))

ss_hit = set()
for k, ss in enumerate(cmap.subsectors):
    for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
        f, _b = sides(cmap.segs[si])
        if f in doors:
            ss_hit.add(k)
            break
print("  subsectors INSIDE a door sector (thing_live, walk)    : %4d  (%.1f%%)"
      % (len(ss_hit), 100.0 * len(ss_hit) / len(cmap.subsectors)))
print("")
print("  per door sector:")
for si in sorted(doors):
    fh = sum(1 for i in front_hits if sides(cmap.segs[i])[0] == si)
    bh = sum(1 for i in back_hits if sides(cmap.segs[i])[1] == si)
    print("    sector %4d  open->%5d   %2d own segs, %2d segs looking at it"
          % (si, doors[si], fh, bh))
