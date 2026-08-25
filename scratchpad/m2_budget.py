"""M2-D1 -- THE DOOR BUDGET, re-derived. No build, no render: pure map + emitter arithmetic.

The handoff's first M2 instruction is that the first task is NOT a build. A door changes its
sector's CEILING HEIGHT at runtime, and the emitter identifies a sector's plane pair by
    (ceil_h, light, flatval, ceil_tex), (floor_h, light, flatval, floor_tex)
so every height a door can stop at is a DIFFERENT PID -- and a pid must fit ONE BYTE everywhere it
flows (`hex.write_byte pptr, seg_pid`; wall_renderer asserts len(lines_pid) <= 255). If the sweep
does not fit, the quantum is wrong and no amount of fj will fix it.

GROUND TRUTH for what is already spent: the emitted `skypid` dispatch table is
`[0] + [is_sky per pid]`, so its entry count is 1 + len(lines_pid). Read it out of a real emitted
program rather than recomputing it -- recomputing would mean re-implementing `_seg_in_walk` and
`_plane_keys`, which are inner functions of the emitter, and a drifting copy is what this repo
calls a second mirror.

    python scratchpad/m2_budget.py [--quant 16] [--tables build/generated_std/e1m1_01_tables.fj]
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj.wad import WadFile                                            # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--map", default="E1M1")
ap.add_argument("--quant", type=int, default=16)
ap.add_argument("--tables", default="build/generated_std/e1m1_01_tables.fj",
                help="an emitted tables part, for the CURRENT pid count")
args = ap.parse_args()

mw = WadFile.from_path(str(ROOT / args.wad))
secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)

# ---- the doors, by DOOM's rule (the same derivation scratchpad/door_gate.py uses) --------------
# A real door is STORED SHUT (ceil_h == floor_h) behind a special linedef, and P_DoorRaise opens it
# to min(neighbouring sector ceiling) - 4. Sweeping to the WAD's own ceiling instead is zero
# movement for every real door -- the mistake that made the first door gate measure a LIFT.
neighbours = {}
for ld in lds:
    f = sds[ld.front].sector if ld.front != 0xFFFF and ld.front < len(sds) else None
    b = sds[ld.back].sector if ld.back != 0xFFFF and ld.back < len(sds) else None
    if f is not None and b is not None and f != b:
        neighbours.setdefault(f, set()).add(b)
        neighbours.setdefault(b, set()).add(f)

doors, lifts = {}, []
for ld in lds:
    if ld.special and ld.back != 0xFFFF and ld.back < len(sds):
        si = sds[ld.back].sector
        s = secs[si]
        if s.ceil_h != s.floor_h:
            lifts.append(si)
            continue
        nb = neighbours.get(si)
        if nb:
            doors[si] = min(secs[n].ceil_h for n in nb) - 4

def sweep(floor_h, open_h):
    """every ceiling height the QUANTISED sweep can stop at, shut..open inclusive.

    !! THE CLAMP IS LOAD-BEARING, and door_gate.height_set() DOES NOT HAVE IT. Flooring to a
    multiple of the quantum can land BELOW the floor when the floor is not itself a multiple:
    floor -128 at quant 24 floors to -144, a ceiling under its own floor. door_gate's `door_state`
    clamps with max(lo, min(open_h, q)) and its `height_set` does not, so the two disagree for
    every quantum that does not divide the floor height -- and `height_set` is the one that would
    have sized this budget. Same rule as door_state, here, and the counts below are the clamped
    ones."""
    hs, h = set(), floor_h
    while h < open_h:
        hs.add(max(floor_h, min(open_h, (h // args.quant) * args.quant)))
        h += args.quant
    hs.add(open_h)
    hs.add(floor_h)                      # shut, which the wad already carries
    return sorted(hs)

print("%s: %d sectors, %d REAL doors (stored shut), %d already-open sectors behind a special line"
      % (args.map, len(secs), len(doors), len(set(lifts))))
print("")
print("  door  floor   open   sweep   quantised stops (quant=%d)" % args.quant)
total_new = 0
for si in sorted(doors):
    lo, hi = secs[si].floor_h, doors[si]
    stops = sweep(lo, hi)
    new = len(stops) - 1                 # the shut height is already a baked pid
    total_new += new
    print("  %4d  %5d  %5d  %5d   %2d stops -> %2d NEW pids  %s"
          % (si, lo, hi, hi - lo, len(stops), new,
             stops if len(stops) <= 8 else "%s ... %s" % (stops[:3], stops[-2:])))

distinct = sorted({h for si in doors for h in sweep(secs[si].floor_h, doors[si])})
print("")
print("  %d doors, %d NEW pids in total, %d DISTINCT ceiling heights across all of them"
      % (len(doors), total_new, len(distinct)))

# ---- what is already spent -------------------------------------------------------------------
tables = ROOT / args.tables
m = re.search(r'dispatch table "skypid": (\d+) entries', tables.read_text(encoding="utf-8")) \
    if tables.exists() else None
if m is None:
    print("\n  !! %s has no skypid table -- cannot read the CURRENT pid count. Emit one first."
          % args.tables)
    sys.exit(1)
used = int(m.group(1)) - 1               # skypid is [0] + one entry per pid
print("  MEASURED from %s: skypid has %d entries -> %d pids already baked, %d of 255 free"
      % (args.tables, used + 1, used, 255 - used))

after = used + total_new
print("")
print("  VERDICT at quant=%d:  %d + %d = %d of 255  (%.1f%%)"
      % (args.quant, used, total_new, after, 100.0 * after / 255))
if after <= 255:
    print("  FITS -- with %d pids of headroom left." % (255 - after))
else:
    print("  DOES NOT FIT -- raise the quantum or move to a runtime height cell.")

# ---- THE OTHER BUDGET, and it is the binding one ----------------------------------------------
# A pid is not just a byte: with plane_near the bank carries one KEY PER PLANE PER PID, and the
# shipping tier bakes every half-list as CODE (generate_bands_walk_fj), dispatched on an index of
# `index_nibbles` = 4 nibbles. So the real ceiling is the HALF-LIST COUNT, and it is the same
# counter docs/handoff-m5-m2-m3-m4.md hands to M4 as "the 65,536 band-index cap".
#
#     half-lists = viewz_classes x (2 keys per pid) x pids x (asc + desc)  +  sky half-lists
#
# THE MODEL IS CHECKED AGAINST GROUND TRUTH, not assumed: the emitted program states the total in
# its own header ("bands-as-code: N half-lists"), and the reconstruction below must reproduce it.
m2 = re.search(r'bands-as-code: (\d+) half-lists \((\d+) unique, pad (\d+)\)',
               tables.read_text(encoding="utf-8"))
if m2 is None:
    banks = tables.parent / tables.name.replace("_01_tables", "_06_banks")
    m2 = re.search(r'bands-as-code: (\d+) half-lists \((\d+) unique, pad (\d+)\)',
                   banks.read_text(encoding="utf-8")) if banks.exists() else None
if m2 is None:
    print("\n  (no bands-as-code header found -- skipping the band-index budget)")
    sys.exit(0 if after <= 255 else 1)

emitted, unique, pad_now = (int(g) for g in m2.groups())

from doomfj.config import Config                                          # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import ReferenceModel                         # noqa: E402
rm = ReferenceModel(Config())
cmap = bake_bsp(mw, args.map)
classes = {}
for ss in cmap.subsectors:
    sec = rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
    classes.setdefault(rm.view_z(sec.floor_h), len(classes))
nclass = len(classes)
main = nclass * (2 * used) * 2
sky = emitted - main
print("")
print("  BAND-INDEX BUDGET (the binding one)")
print("    viewz classes %d x 2 keys/pid x %d pids x 2 halves = %d main half-lists"
      % (nclass, used, main))
print("    emitted total %d  ->  sky half-lists %d   (%s)"
      % (emitted, sky, "reconstruction CHECKS OUT" if 0 <= sky < main else
         "!! RECONSTRUCTION IS WRONG -- do not trust the projection below"))
assert 0 <= sky < main, "the half-list model does not reproduce the emitted count"
per_pid = nclass * 4
cap = 1 << (4 * 4)                       # generate_bands_walk_fj's default index_nibbles = 4
print("    -> EACH PID COSTS %d half-lists; today %d of the %d cap, pad %d (%d spare -> %.1f pids)"
      % (per_pid, emitted, cap, pad_now, pad_now - emitted, (pad_now - emitted) / per_pid))
print("")
print("    quant  new pids   half-lists      total     pad   verdict")
for q in (8, 16, 24, 32, 48, 64):
    stops = 0
    for si in sorted(doors):
        lo, hi = secs[si].floor_h, doors[si]
        h, seen = lo, set()
        while h < hi:
            seen.add(max(lo, min(hi, (h // q) * q)))
            h += q
        seen.add(hi); seen.add(lo)
        stops += len(seen) - 1
    n = emitted + stops * per_pid
    pad = 1 << max(1, (n - 1).bit_length())
    print("    %5d  %8d   %+10d  %7d  %6d   %s"
          % (q, stops, stops * per_pid, n, pad,
             "OVER THE CAP" if pad > cap else
             ("fits, but the pad DOUBLES -- no room left for M4" if pad > pad_now else "free")))
print("")
print("    !! THIS IS THE SAME COUNTER M4 SPENDS. Three levels in one image sum their half-lists,")
print("       and %d x 3 = %d is already %.0f%% of the cap BEFORE any door. The handoff's 88.7%%"
      % (emitted, emitted * 3, 100.0 * emitted * 3 / cap))
print("       figure for M4 was projected from a smaller per-level count and needs the same")
print("       re-derivation this file just did for M2.")
print("    !! index_nibbles is a PARAMETER (generate_bands_walk_fj default 4), not a law. Raising")
print("       it to 5 lifts the cap to 2**20 for one extra xor per dispatch; what really scales")
print("       is `pad`, the dispatch table itself. Price that before scaling anything down.")
sys.exit(0 if after <= 255 else 1)
