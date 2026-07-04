"""M13p0 step 3c -- host-side until-full counts (sizes M13pG1's walk-abort win). Calls the oracle's
OWN `bsp_render_order`/`wall_x_range`/`_seg_sector` (no duplicated math, no drift) and counts, at each
of 3 viewpoints: how many subsectors (and their seg ranges) are visited, and how many segs reach
`wall_x_range` BEFORE every screen column is claimed (`all(drawn)`) -- the post-full share is what
pG1's full-abort walk guard deletes.

Usage: python scripts/count_until_full.py
"""
import json
from pathlib import Path

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, build_scene, spawn_state
from doomfj.wad import WadFile

E1M1 = "tests/fixtures/freedoom_e1m1.wad"


def count_one(rm, scene, vx, vy, viewangle):
    cfg = rm.cfg
    W = cfg.VIEW_W
    lds = scene.map_wad.linedefs(scene.mapname)
    sds = scene.map_wad.sidedefs(scene.mapname)
    secs = scene.map_wad.sectors(scene.mapname)
    verts = scene.cmap.vertexes

    order = rm.bsp_render_order(scene.cmap, vx, vy)         # the front-to-back subsector visit order
    drawn = bytearray(W)

    def all_drawn():
        return all(drawn)

    total_subsectors = len(order)
    total_segs_visited = 0                                   # every one-sided seg entering the loop
    total_segs_passing_xrange = 0                             # wall_x_range returned non-None
    subsectors_until_full = None
    segs_visited_until_full = 0
    segs_passing_xrange_until_full = 0
    became_full_at_subsector = None

    for si_pos, ss_idx in enumerate(order):
        if became_full_at_subsector is None and all_drawn():
            became_full_at_subsector = si_pos
        ss = scene.cmap.subsectors[ss_idx]
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = scene.cmap.segs[si]
            ld = lds[seg.linedef]
            if ld.back != -1:
                continue
            total_segs_visited += 1
            if became_full_at_subsector is None:
                segs_visited_until_full += 1
            rng = rm.wall_x_range(vx << 16, vy << 16, viewangle, seg, verts)
            if rng is None:
                continue
            total_segs_passing_xrange += 1
            if became_full_at_subsector is None:
                segs_passing_xrange_until_full += 1
            x1, x2, _ = rng
            for x in range(x1, x2):
                drawn[x] = 1

    if became_full_at_subsector is None:
        became_full_at_subsector = total_subsectors   # never fills (shouldn't happen at a real spawn)
    subsectors_until_full = became_full_at_subsector

    return {
        "total_subsectors": total_subsectors, "subsectors_until_full": subsectors_until_full,
        "total_segs_visited": total_segs_visited, "segs_visited_until_full": segs_visited_until_full,
        "total_segs_passing_xrange": total_segs_passing_xrange,
        "segs_passing_xrange_until_full": segs_passing_xrange_until_full,
        "post_full_subsector_pct": round(100 * (1 - subsectors_until_full / max(1, total_subsectors)), 1),
        "post_full_seg_pct": round(100 * (1 - segs_visited_until_full / max(1, total_segs_visited)), 1),
    }


def main():
    cfg = Config()
    rm = ReferenceModel(cfg)
    wad = WadFile.from_path(E1M1)
    scene = build_scene(wad, wad, "E1M1")
    sp = spawn_state(wad, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = {"spawn": (spx, spy, sp.angle), "rot45": (spx, spy, A45)}
    # a genuinely valid "other sector" viewpoint (mirrors the E1M1 capstone test's convention: a map
    # THING location, not an arbitrary offset that might land outside a subsector or inside geometry)
    for t in wad.things("E1M1"):
        if (t.x, t.y) != (spx, spy):
            VIEWPOINTS["othersector"] = (t.x, t.y, sp.angle)
            break
    results = {tag: count_one(rm, scene, vx, vy, va) for tag, (vx, vy, va) in VIEWPOINTS.items()}
    Path("scratchpad/bakeoff").mkdir(parents=True, exist_ok=True)
    Path("scratchpad/bakeoff/until_full_counts.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
