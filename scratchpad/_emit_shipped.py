"""Re-emit the SHIPPED program into build/generated_loop, using build.py's own flag set.

The hoist moved every address, so the restore set must be re-keyed against a label table from the
NEW layout. That needs the generated parts regenerated first; _capture_labels.py then assembles
them once and writes the table.

    python scratchpad/_emit_shipped.py && python scratchpad/_capture_labels.py
"""
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.build import _resolve_sprite_wad
from doomfj.config import Config
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer, write_program_files

t0 = time.perf_counter()
cfg = Config()
wad = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
gen = ROOT / "build" / "generated_loop"; gen.mkdir(parents=True, exist_ok=True)
spr = _resolve_sprite_wad(wad, ROOT / "assets/freedoom1.wad")   # build.py's default
# EXACTLY build.build_wall_renderer's defaults for the shipped tier (B0/A0.1): if these drift the
# label table describes a different program than the one M1 will be gated on.
parts = emit_wall_renderer(wad, "E1M1", cfg, things=True,
                           sprite_wad=spr, player_sim=True, collide=True,
                           moving_things=True, return_parts=True)
cfg.emit_fj_consts(gen / "fj_consts.fj")
paths = write_program_files(parts, gen, "E1M1")
print("emitted %d parts in %.0fs:" % (len(paths), time.perf_counter() - t0))
for p in paths:
    print("   %-28s %9d lines" % (p.name, sum(1 for _ in open(p, encoding="utf-8"))))
