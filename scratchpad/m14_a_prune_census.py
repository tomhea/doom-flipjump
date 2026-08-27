"""M14-a, step 1: census the two prunes BEFORE changing them (handoff-m14.md section 3).

A leaf with no walk-relevant seg is dropped twice -- `_lines_prune` at emit and the `tsstop` node
gate at runtime -- and both are currently taught liveness by `things_by_ss`, i.e. by where the
things happen to STAND at emit time. With moving things that predicate is wrong and it fails
silently. This script prices the three candidate replacements without building anything:

  today   : live iff the leaf holds a thing AT EMIT TIME              (unsound once things move)
  ever    : live iff a thing could EVER be in the leaf                (sound; the section 3 option 1)
  all     : live always                                                (the trivial upper bound)

"could ever be in the leaf" is deliberately conservative: a thing needs somewhere to stand, so the
only leaves it excludes are those whose sector has no space at all (ceil_h <= floor_h -- closed
doors, wall fillers). Anything a monster could conceivably walk into stays live.

Reported per candidate: leaves kept by the emit prune, and nodes still eligible for the runtime
tsstop gate -- that second number is the one that costs ops.

Usage:  python scratchpad/m14_a_prune_census.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.mapcompiler import bake_bsp, NF_SUBSECTOR
from doomfj.reference_model import ReferenceModel, THING_SPRITE
from doomfj.wad import WadFile

MAPNAME = "E1M1"
cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cmap = bake_bsp(mw, MAPNAME)
lds, sds, secs = mw.linedefs(MAPNAME), mw.sidedefs(MAPNAME), mw.sectors(MAPNAME)

sys.setrecursionlimit(20000)


def seg_marks(seg) -> bool:
    ld = lds[seg.linedef]
    if ld.back == -1:
        return True
    fs = secs[sds[ld.front if seg.side == 0 else ld.back].sector]
    bs = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
    return ((fs.ceil_h, fs.light & 0xFF, fs.ceil_tex.upper())
            != (bs.ceil_h, bs.light & 0xFF, bs.ceil_tex.upper())
            or (fs.floor_h, fs.light & 0xFF, fs.floor_tex.upper())
            != (bs.floor_h, bs.light & 0xFF, bs.floor_tex.upper()))


def seg_as_solid(seg) -> bool:
    return lds[seg.linedef].back == -1


def seg_in_walk(seg) -> bool:                    # plane_near=True, the shipped lines tier
    return seg_as_solid(seg) or seg_marks(seg)


def leaf_sector(si0):
    return rm._seg_sector(lds, sds, secs, cmap.segs[cmap.subsectors[si0].firstseg])


# --- the three liveness candidates -------------------------------------------------------------
spr_cache = {}
things_by_ss = {}
for t in mw.things(MAPNAME):
    if rm.sprite_art(art, t.type, spr_cache) is None:
        continue
    things_by_ss.setdefault(rm.point_in_subsector(cmap, t.x, t.y), []).append(t)

CANDIDATES = {
    "today (emit-time occupancy)": lambda si0: si0 in things_by_ss,
    "ever  (a thing fits here)": lambda si0: leaf_sector(si0).ceil_h > leaf_sector(si0).floor_h,
    "all   (every leaf)": lambda si0: True,
}


def census(live):
    """Returns (leaves kept by the emit prune, nodes eligible for the runtime tsstop gate)."""
    walk_below, solid_below = {}, {}

    def cnt(child, pred, memo):
        if child & NF_SUBSECTOR:
            si0 = child & (NF_SUBSECTOR - 1)
            if live(si0):
                return 1
            ss = cmap.subsectors[si0]
            return sum(1 for si in range(ss.firstseg, ss.firstseg + ss.numsegs)
                       if pred(cmap.segs[si]))
        n = cmap.nodes[child]
        tot = cnt(n.left, pred, memo) + cnt(n.right, pred, memo)
        memo[child] = tot
        return tot

    cnt(cmap.root, seg_in_walk, walk_below)
    cnt(cmap.root, seg_as_solid, solid_below)

    kept = 0
    for si0 in range(len(cmap.subsectors)):
        ss = cmap.subsectors[si0]
        pruned = (not live(si0)) and not any(seg_in_walk(cmap.segs[si])
                                             for si in range(ss.firstseg, ss.firstseg + ss.numsegs))
        kept += not pruned
    gated = sum(1 for i in range(len(cmap.nodes)) if solid_below.get(i, 1) == 0)
    return kept, gated


def main():
    nss, nnodes = len(cmap.subsectors), len(cmap.nodes)
    print(f"{MAPNAME}: {nss} subsectors, {nnodes} nodes, {len(cmap.segs)} segs, "
          f"{sum(len(v) for v in things_by_ss.values())} drawable things in "
          f"{len(things_by_ss)} leaves (max {max(map(len, things_by_ss.values()))}/leaf)")
    print(f"{'liveness predicate':32s} {'leaves kept':>14s} {'nodes tsstop-gatable':>22s}")
    base = None
    for name, live in CANDIDATES.items():
        kept, gated = census(live)
        if base is None:
            base = (kept, gated)
        print(f"{name:32s} {kept:6d} / {nss:<5d} {kept / nss:5.1%}   {gated:5d} / {nnodes:<5d} "
              f"{gated / nnodes:5.1%}   (vs today: leaves {kept - base[0]:+d}, "
              f"gatable nodes {gated - base[1]:+d})")

    # the leaves 'ever' still drops -- print them, because THIS is the set the runtime guard must
    # prove a thing never reaches
    dead = [si0 for si0 in range(nss)
            if not CANDIDATES["ever  (a thing fits here)"](si0)]
    print(f"\nleaves 'ever' calls uninhabitable (ceil_h <= floor_h): {len(dead)}")
    for si0 in dead[:12]:
        sec = leaf_sector(si0)
        print(f"  ss{si0}: floor {sec.floor_h} ceil {sec.ceil_h}")
    if len(dead) > 12:
        print(f"  ... and {len(dead) - 12} more")
    # control: no thing may currently stand in a leaf 'ever' calls uninhabitable
    bad = sorted(set(things_by_ss) & set(dead))
    print(f"control: emit-time things inside an 'uninhabitable' leaf: {len(bad)} "
          f"{'OK' if not bad else '!! ' + str(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
