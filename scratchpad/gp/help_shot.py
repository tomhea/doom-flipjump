"""Render the HELP screen (doomfj.menu.help_pixels, the oracle's picture) to a PNG, x4. Usage:
    python scratchpad/gp/help_shot.py OUT.png"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from PIL import Image                                          # noqa: E402
from doomfj import menu as M                                   # noqa: E402
from doomfj.wad import WadFile                                 # noqa: E402

wad = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
pal = [tuple(rgb) for rgb in wad.playpal(0)]
colours = M.palette_colours(bytes(b for rgb in pal for b in rgb))
px = M.help_pixels(160, 100, colours)
img = Image.new("RGB", (160, 100))
img.putdata([pal[i] for i in px])
img.resize((640, 400), Image.NEAREST).save(sys.argv[1])
print("wrote", sys.argv[1])
