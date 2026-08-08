"""Refactor safety net: sha256 of the EMITTED renderer text (+ the fj library sources) for
two configs. Byte-identical hashes before/after a refactor = the assembled binary is identical
= certification transfers without a rebuild.

    python scratchpad/cr/emit_hash.py <tag>     # writes scratchpad/cr/emit_hash_<tag>.json
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

tag = sys.argv[1]
cfg = Config()
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))

out = {"fj_sources": {}}
for f in ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj",
          "plane_render.fj", "plane_bands.fj", "stream_render.fj"):
    out["fj_sources"][f] = hashlib.sha256((ROOT / "src/fj" / f).read_bytes()).hexdigest()

CONFIGS = {
    # the certified shipping config (heavy: sprite bank, ~8-15 min)
    "certified": dict(asset_wad=aw, over_align=False, floor_mode="FT1", wall_mode="W1R",
                      raster_mode="lines", plane_near=True, wall_noise=True, sky=True,
                      steps=True, stack_steps=True, things=True, sprite_wad=art,
                      bbox_cull=True, deg=True),
    # the steps=False lines config (the config the fbspent regression hid in; fast)
    "lines_nosteps": dict(asset_wad=aw, over_align=False, floor_mode="FT1", wall_mode="WPX",
                          raster_mode="lines", plane_near=True, deg=False),
}
for name, kw in CONFIGS.items():
    t0 = time.time()
    txt = emit_wall_renderer(mw, "E1M1", cfg, **kw)
    out[name] = {"sha256": hashlib.sha256(txt.encode()).hexdigest(), "chars": len(txt),
                 "seconds": round(time.time() - t0)}
    print(f"{name}: {out[name]['sha256'][:16]}  ({len(txt):,} chars, {out[name]['seconds']}s)",
          flush=True)

(ROOT / "scratchpad/cr" / f"emit_hash_{tag}.json").write_text(json.dumps(out, indent=1))
print(f"wrote scratchpad/cr/emit_hash_{tag}.json")
