"""CR round-2 refactor check: sha256 of the emitted lines_nosteps text (baseline
9f0f85cb214a1299...), plus a `pnearwalk`-ablate emission -- ablate forces ascode=0, which is
the ONLY path that calls _lines_bake_bank (the item-2 refactor target); lines_nosteps takes
the bands-as-code path and never runs it.

    python scratchpad/cr/r2_check.py <tag>      # writes scratchpad/cr/r2_check_<tag>.json
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer

tag = sys.argv[1] if len(sys.argv) > 1 else "now"
cfg = Config()
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))

CONFIGS = {
    # the round's designated check config (expected sha256 prefix 9f0f85cb214a1299)
    "lines_nosteps": dict(asset_wad=aw, over_align=False, floor_mode="FT1", wall_mode="WPX",
                          raster_mode="lines", plane_near=True, deg=False),
    # same, ablated so ascode=0 => the _lines_bake_bank DATA bank is emitted and hashed
    "lines_databank": dict(asset_wad=aw, over_align=False, floor_mode="FT1", wall_mode="WPX",
                           raster_mode="lines", plane_near=True, deg=False,
                           ablate=frozenset({"pnearwalk"})),
}
out = {}
for name, kw in CONFIGS.items():
    t0 = time.time()
    txt = emit_wall_renderer(mw, "E1M1", cfg, **kw)
    out[name] = {"sha256": hashlib.sha256(txt.encode()).hexdigest(), "chars": len(txt),
                 "seconds": round(time.time() - t0)}
    print(f"{name}: {out[name]['sha256'][:16]}  ({len(txt):,} chars, {out[name]['seconds']}s)",
          flush=True)

(ROOT / "scratchpad/cr" / f"r2_check_{tag}.json").write_text(json.dumps(out, indent=1))
print(f"wrote scratchpad/cr/r2_check_{tag}.json")
