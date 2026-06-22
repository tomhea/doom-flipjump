"""M12i integration evidence (R2): BAKE the BSP from the WAD's precompiled NODES/SSECTORS/SEGS (the
M7 builder is gone) and report the baked structure for both the pre-baked square room and the full real
E1M1 — counts, the render-order permutation invariant, the spawn subsector, a few visible-wall screen
x-ranges, and that the compiled map assembles flat (R4). Writes build/m12i-metrics.json. Reproducible:
`python scripts/m12i_evidence.py` (square room needs no source WAD; E1M1 uses the committed fixture)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.mapcompiler import NF_SUBSECTOR, bake_bsp, compile_map
from doomfj.reference_model import ReferenceModel, spawn_state
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"
E1M1 = "tests/fixtures/freedoom_e1m1.wad"
U = 1 << 16


def _assembles_flat(wad, mapname) -> tuple[str, int]:
    src = compile_map(wad, mapname, mode="streams")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.fj"
        p.write_text("stl.startup_and_init_all\nstl.loop\n" + src + "\n", encoding="utf-8")
        out = Path(d) / "m.fjm"
        fj.assemble([p.resolve()], out, memory_width=W, print_time=False)
        term = fj.run(out, print_time=False, print_termination=False)
        return str(term.storage_mode), out.stat().st_size


def main() -> dict:
    rm = ReferenceModel()
    metrics = {}

    # ── pre-baked square room (DOOM-wound, exact values) ──
    room = WadFile.from_path(ROOM)
    rb = bake_bsp(room, "MAP01")
    nrm_rwd = [rm.wall_setup(128 * U, 128 * U, s, rb.vertexes) for s in rb.segs]
    faced = rm.wall_x_range(128 * U, 128 * U, 0, rb.segs[2], rb.vertexes)   # east wall, facing east
    mode, size = _assembles_flat(room, "MAP01")
    metrics["square_room"] = {
        "segs": len(rb.segs), "subsectors": len(rb.subsectors), "nodes": len(rb.nodes),
        "root": hex(rb.root), "seg_angles": [s.angle for s in rb.segs],
        "rw_distance_each_wall": [round(d / U, 3) for _, d in nrm_rwd],
        "east_wall_facing_east_xrange": faced[:2],
        "east_wall_centre_scale": rm.scale_from_global_angle(0, 0, *nrm_rwd[2]),
        "compiled_storage_mode": mode, "compiled_fjm_bytes": size,
    }

    # ── full real E1M1 (the strong test bed) ──
    e = WadFile.from_path(E1M1)
    eb = bake_bsp(e, "E1M1")
    sp = spawn_state(e, "E1M1")
    order = rm.bsp_render_order(eb, sp.x >> 16, sp.y >> 16)
    visible = sum(1 for s in eb.segs
                  if rm.wall_x_range(sp.x, sp.y, sp.angle, s, eb.vertexes) is not None)
    metrics["e1m1"] = {
        "segs": len(eb.segs), "subsectors": len(eb.subsectors), "nodes": len(eb.nodes),
        "root_is_node": not (eb.root & NF_SUBSECTOR), "root": eb.root,
        "spawn_xy": [sp.x >> 16, sp.y >> 16],
        "spawn_subsector": rm.point_in_subsector(eb, sp.x >> 16, sp.y >> 16),
        "render_order_is_permutation": sorted(order) == list(range(len(eb.subsectors))),
        "render_order_first": order[0],
        "segs_with_visible_xrange_from_spawn": visible,
    }

    out_path = Path("build/m12i-metrics.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
