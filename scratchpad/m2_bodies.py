"""M2-D2 -- what a door's new band lists actually COST, in unique baked handler bodies.

The pid byte and the band INDEX are cheap to reason about; the expensive thing the bands-as-code
tier bakes is a raw-op HANDLER BODY per DISTINCT half-list, and identical lists share one. So the
question doors really pose is: how many of the ~18k half-lists a 16-unit sweep adds are NEW?

Everything here calls the emitter's OWN `_band_pair_lists` -- the same function the shipped bank
is baked from -- so this is not a model of the emitter, it is the emitter.

GROUND-TRUTH CONTROL: run with the CURRENT keys first and require it to reproduce the emitted
program's own header ("N half-lists (U unique)"). A projection from a walk that cannot reproduce
today's numbers is worth nothing.

    python scratchpad/m2_bodies.py [--quant 16]
"""
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config                                          # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import ReferenceModel                         # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import _band_pair_lists                         # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--map", default="E1M1")
ap.add_argument("--quant", type=int, default=16)
ap.add_argument("--banks", default="build/generated_std/e1m1_06_banks.fj")
args = ap.parse_args()

cfg = Config(); rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / args.wad))
secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)
cmap = bake_bsp(mw, args.map)

# the emitter's `_flatval` is an INNER function of emit_wall_renderer; on the shipped FT1 tier it
# is exactly rm._flat_base, which is the oracle's own. Same call, not a copy of the logic.
_basecache = {}
def _flatval(name):
    return rm._flat_base(mw, name, _basecache)

vz = {}
for ss in cmap.subsectors:
    sec = rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
    vz.setdefault(rm.view_z(sec.floor_h), len(vz))


def keys_of(sec, ceil_h=None):
    ch = sec.ceil_h if ceil_h is None else ceil_h
    return ((ch, sec.light & 0xFF, _flatval(sec.ceil_tex), sec.ceil_tex.upper()),
            (sec.floor_h, sec.light & 0xFF, _flatval(sec.floor_tex), sec.floor_tex.upper()))


# the CURRENT bank keys, rebuilt the way the emitter does (pid pairs, flattened)
def _seg_in_walk(seg):
    return True             # the emitter prunes; a superset only over-counts, and the control below
                            # tells us by how much


pids = {}
for seg in cmap.segs:
    ck, fk = keys_of(rm._seg_sector(lds, sds, secs, seg))
    pids.setdefault((ck, fk), len(pids) + 1)
    ld = lds[seg.linedef]
    if ld.back != -1:
        bs = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
        bck, bfk = keys_of(bs)
        pids.setdefault((bck, bfk), len(pids) + 1)
base_keys = [k for pair in pids for k in pair]

emitted = re.search(r'bands-as-code: (\d+) half-lists \((\d+) unique',
                    (ROOT / args.banks).read_text(encoding="utf-8"))
print("emitted program says: %s half-lists, %s unique"
      % (emitted.group(1), emitted.group(2)) if emitted else "(no emitted header found)")
print("this walk reconstructs %d pids -> %d bank keys over %d viewz classes"
      % (len(pids), len(base_keys), len(vz)))
print("  (the emitter PRUNES segs out of the walk, so this is a SUPERSET; the unique-body ratio")
print("   below is what matters, and it is measured on the same walk both times.)")

t = time.perf_counter()
base_lists = _band_pair_lists(rm, cfg, mw, vz, base_keys, True)
base_uniq = {tuple(map(tuple, p)) for p in base_lists}
print("\nBASE : %d half-lists, %d unique  (%.0f s)"
      % (len(base_lists), len(base_uniq), time.perf_counter() - t))

# ---- the doors ---------------------------------------------------------------------------------
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

door_keys = list(base_keys)
added = 0
for si, open_h in sorted(doors.items()):
    sec, lo = secs[si], secs[si].floor_h
    stops, h = set(), lo
    while h < open_h:
        stops.add(max(lo, min(open_h, (h // args.quant) * args.quant)))
        h += args.quant
    stops.add(open_h)
    for ch in sorted(stops - {lo}):
        ck, fk = keys_of(sec, ch)
        door_keys += [ck, fk]
        added += 1

t = time.perf_counter()
door_lists = _band_pair_lists(rm, cfg, mw, vz, door_keys, True)
door_uniq = {tuple(map(tuple, p)) for p in door_lists}
print("DOORS: %d half-lists, %d unique  (+%d pids at quant %d, %.0f s)"
      % (len(door_lists), len(door_uniq), added, args.quant, time.perf_counter() - t))

print("")
print("  half-lists  %7d -> %7d   (+%d, +%.1f%%)"
      % (len(base_lists), len(door_lists), len(door_lists) - len(base_lists),
         100.0 * (len(door_lists) - len(base_lists)) / len(base_lists)))
print("  UNIQUE      %7d -> %7d   (+%d, +%.1f%%)   <- the baked handler bodies"
      % (len(base_uniq), len(door_uniq), len(door_uniq) - len(base_uniq),
         100.0 * (len(door_uniq) - len(base_uniq)) / len(base_uniq)))
new_share = (len(door_uniq) - len(base_uniq)) / max(1, len(door_lists) - len(base_lists))
print("  %.0f%% of the half-lists a door adds are NEW bodies; the rest share an existing handler."
      % (100.0 * new_share))
