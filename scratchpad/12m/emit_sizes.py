"""Emit-only: which PART of the hosted-loop tier is the 60M-word overshoot? No assembly.

The overflow probe showed peak wflip address ~= first_address = 194M words of STATIC emission,
44.8% over the 2^27 ceiling. This emits the parts (return_parts=True) and reports each part's
size, so the oversized region is named. Compared to P9-1's ritual-logged part LINE counts
(visual tier + S2): entry 32, tables 338,599, main 68, segconsts 44,419, walk 73,942, state 437,
banks 2,137,148.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.build import DEFAULT_WAD, _resolve_sprite_wad, DEFAULT_SPRITE_WAD  # noqa: E402
from doomfj.config import Config                                                # noqa: E402
from doomfj.wad import WadFile                                                   # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer, tier_flags                  # noqa: E402

tier = sys.argv[1] if len(sys.argv) > 1 else "hosted-loop"
print("emitting tier %r ..." % tier, flush=True)
cfg = Config()
wad = WadFile.from_path(DEFAULT_WAD)
spr = _resolve_sprite_wad(wad, DEFAULT_SPRITE_WAD) if tier_flags(tier)["things"] else None
parts = emit_wall_renderer(wad, "E1M1", cfg, sprite_wad=spr, tier=tier, return_parts=True)

# parts is an ordered list of (name, text) or a dict -- normalise
items = parts.items() if hasattr(parts, "items") else [(getattr(p, "name", str(i)), p)
                                                        for i, p in enumerate(parts)]
print("%-22s %14s %16s" % ("part", "lines", "chars (~bytes)"), flush=True)
print("-" * 56, flush=True)
tot_l = tot_c = 0
for name, text in items:
    if not isinstance(text, str):
        text = getattr(text, "text", str(text))
    lines = text.count("\n")
    chars = len(text)
    tot_l += lines
    tot_c += chars
    print("%-22s %14s %16s" % (str(name)[:22], format(lines, ","), format(chars, ",")), flush=True)
print("-" * 56, flush=True)
print("%-22s %14s %16s" % ("TOTAL", format(tot_l, ","), format(tot_c, ",")), flush=True)
print("DONE", flush=True)
