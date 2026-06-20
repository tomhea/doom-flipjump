"""M7 integration evidence (R2): compile the test WAD's BSP (built, not baked) and report structure +
compiled `.fjm` size + storage_mode; plus a concave-L-shape demo exercising the split path. Writes
build/m7-metrics.json. Reproducible: `python scripts/m7_evidence.py`."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.wad import WadFile
from doomfj.mapcompiler import Seg, build_bsp, compile_bsp, compile_map


def main() -> dict:
    wad = WadFile.from_path("tests/fixtures/test.wad")
    bsp = compile_bsp(wad, "MAP01")
    src = compile_map(wad, "MAP01", mode="streams")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.fj"
        p.write_text("stl.startup_and_init_all\nstl.loop\n" + src + "\n", encoding="utf-8")
        out = Path(d) / "m.fjm"
        fj.assemble([p.resolve()], out, memory_width=W, print_time=False)
        term = fj.run(out, print_time=False, print_termination=False)
        fjm_bytes = out.stat().st_size
    assert str(term.storage_mode) == "flat", "R4: compiled map not flat"

    lv = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    ll = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]
    lbsp = build_bsp(lv, [Seg(a, b, 0, i, 0, 0) for i, (a, b) in enumerate(ll)])

    metrics = {
        "square_room_MAP01": {
            "segs": len(bsp.segs), "subsectors": len(bsp.subsectors), "nodes": len(bsp.nodes),
            "root": hex(bsp.root), "seg_angles_bam16": [s.angle for s in bsp.segs],
            "compiled_fjm_bytes": fjm_bytes, "storage_mode": str(term.storage_mode),
        },
        "concave_L_shape_split_demo": {
            "input_segs": 6, "output_segs": len(lbsp.segs), "nodes": len(lbsp.nodes),
            "subsectors": len(lbsp.subsectors), "split_added_verts": len(lbsp.vertexes) - 6,
        },
    }
    out_path = Path("build/m7-metrics.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
