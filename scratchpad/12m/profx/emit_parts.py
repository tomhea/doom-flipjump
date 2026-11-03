"""A map's game-tier generated parts, EMITTED only (no assembly) -> <out>/<map>_0N_<part>.fj.

`maps.py` reads three part boundaries (segconsts, state, banks) from the top-level label NAMES the generated parts
define, and takes their ADDRESSES from the binary's label table. The episode creator removes a build's
`generated_doom_<map>` directory (G8), so a shipped level's parts are re-emitted here from the current source: the
names are what matters, and `maps.py` refuses a part whose names the binary's label table lacks.

    python emit_parts.py E1M6 --out <dir>      # minutes; the emission's RAM, not the assembler's
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("map", type=str.upper)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from doomfj.build import DEFAULT_SPRITE_WAD, WadFile, _resolve_sprite_wad
    from doomfj.config import Config, map_cfg
    from doomfj.mapprofile import profile
    from doomfj.wall_renderer import emit_wall_renderer, tier_cfg, write_program_files
    wad = WadFile.from_path(ROOT / (profile(a.map).wad or "tests/fixtures/freedoom_e1m1.wad"))
    cfg = tier_cfg(map_cfg(Config(), a.map), "game")
    parts = emit_wall_renderer(wad, a.map, cfg, sprite_wad=_resolve_sprite_wad(wad, DEFAULT_SPRITE_WAD),
                               tier="game", return_parts=True)
    for p in write_program_files(parts, Path(a.out), a.map):
        print(p)


if __name__ == "__main__":
    main()
