"""M14.5 — the ZERO-COST GLYPH proposals, rendered for approval.

The hidden classes cost what they cost because the walk LOADS them and then rejects 94.1% of them
(docs/handoff-perf.md §1.5) — NOT because of drawing. So a simpler picture does not by itself make
a sprite cheap; BAKING it does (7,252,305 baked vs 14,352,586 runtime for the same 251 sprites).
A glyph is what makes the *drawn* remainder near-free once the load is gone: few colour RUNS per
column is exactly what `sprite_strip` bakes, so a 1-2 run glyph is the cheapest thing this renderer
can put on screen.

Each glyph below is a tiny pixel grid drawn in the class's OWN dominant palette colours, sampled
from its real sprite, so it still reads as the thing it replaces.

    python scratchpad/glyph_sheet.py [--out scratchpad/glyph_sheet.png]
"""
import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image, ImageDraw                                          # noqa: E402

from doomfj.config import Config                                          # noqa: E402
import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.reference_model import ReferenceModel                         # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="scratchpad/glyph_sheet.png")
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
pal = list(WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_assets.wad")).playpal())

# `.` transparent, `A` primary colour, `B` secondary, `C` tertiary (darker/accent)
GLYPHS = {
    2014: ("BON1", "health bonus",      ["..", ".A", "AA", "AA"]),
    2015: ("BON2", "armour bonus",      ["..", ".A", "AA", "AA"]),
    2035: ("BAR1", "BARREL",            ["BBB", "AAA", "AAA", "AAA", "AAA", "BBB"]),
    47:   ("SMIT", "stalagmite",        ["..A..", ".AAA.", ".AAA.", "AAAAA", "AAAAA"]),
    2008: ("SHEL", "shotgun shells",    ["AAA", "ABA", "AAA"]),
    54:   ("TRE2", "large tree",        [".AAA.", "AAAAA", "AAAAA", ".AAA.", "..B..", "..B.."]),
    43:   ("TRE1", "small tree",        [".A.", "AAA", "AAA", ".B.", ".B."]),
    2010: ("ROCK", "rubble",            [".AA.", "AAAA", "AAAA"]),
    2028: ("COLU", "column",            ["AAA", "AAA", "AAA", "AAA", "AAA", "BBB"]),
    2011: ("STIM", "stimpack  = PLUS",  ["..A..", "..A..", "AAAAA", "..A..", "..A.."]),
    2049: ("SBOX", "shell box",         ["AAAA", "ABBA", "AAAA"]),
    2048: ("AMMO", "clip box",          ["AAAA", "ABBA", "AAAA"]),
    48:   ("ELEC", "tech pillar",       [".B.", "AAA", "AAA", "AAA", "AAA", "AAA"]),
    2007: ("CLIP", "ammo clip",         ["AA", "AA"]),
    2018: ("ARM1", "green armour",      [".AAA.", "AAAAA", "AAAAA", ".AAA.", "..A.."]),
    2019: ("ARM2", "blue armour",       [".AAA.", "AAAAA", "AAAAA", ".AAA.", "..A.."]),
    2002: ("MGUN", "chaingun",          ["AAAA.", "AAAAA", ".BB.."]),
    2003: ("LAUN", "rocket launcher",   ["AAAAB", "AAAAA", ".BB.."]),
    2046: ("BROK", "rocket box",        ["ABA", "ABA", "ABA"]),
}
COUNT = {2014: 30, 2015: 22, 2035: 22, 47: 18, 2008: 18, 54: 15, 43: 12, 2010: 8, 2028: 7,
         2011: 6, 2049: 5, 2048: 4, 48: 4, 2007: 3, 2018: 2, 2002: 2, 2046: 2, 2003: 2, 2019: 1}


def dominant(kind, n=3):
    """The class's own most-common opaque palette indices, so the glyph keeps its identity."""
    RM.THING_SPRITE = RM.THING_SPRITE_ALL
    a = rm.sprite_art(art, kind, {})
    if a is None:
        return [4, 8, 0]
    hist = collections.Counter(p for col in a[0] for p in col if p >= 0)
    top = [p for p, _ in hist.most_common(12)]
    return (top + top + [0, 0, 0])[:n]


def runs_per_col(rows):
    """Colour RUNS per column — what `sprite_strip` bakes, i.e. the drawing cost."""
    w = max(len(r) for r in rows)
    worst = 0
    for x in range(w):
        col = [(r[x] if x < len(r) else ".") for r in rows]
        n, prev = 0, None
        for c in col:
            if c != prev:
                n += 1 if c != "." else 0
                prev = c
        worst = max(worst, n)
    return worst


Z = 9                                            # zoom for the sheet
rowsz, colw = 78, 300
sheet = Image.new("RGB", (colw * 2, rowsz * ((len(GLYPHS) + 1) // 2) + 34), (18, 18, 20))
d = ImageDraw.Draw(sheet)
d.text((8, 8), "M14.5 ZERO-COST GLYPH PROPOSALS  -  approve / redo per row", fill=(235, 235, 235))
d.text((8, 20), "glyph drawn in each class's OWN dominant colours; 'runs' = colour runs per "
                "column (the drawing cost)", fill=(150, 150, 150))

for i, (kind, (spr, label, rows)) in enumerate(GLYPHS.items()):
    cx, cy = (i % 2) * colw + 10, 34 + (i // 2) * rowsz
    cols = dominant(kind)
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch == ".":
                continue
            p = cols[{"A": 0, "B": 1, "C": 2}[ch]]
            d.rectangle([cx + x * Z, cy + y * Z, cx + x * Z + Z - 1, cy + y * Z + Z - 1],
                        fill=tuple(pal[p]))
    tx = cx + 66
    d.text((tx, cy), f"{spr}  x{COUNT[kind]}", fill=(235, 235, 235))
    d.text((tx, cy + 12), label, fill=(165, 165, 165))
    w = max(len(r) for r in rows)
    d.text((tx, cy + 26), f"{w}x{len(rows)} px, {runs_per_col(rows)} run(s)/col",
           fill=(130, 180, 130))

out = ROOT / args.out
sheet.save(out)
print(f"wrote {out}  -- {len(GLYPHS)} classes")
for kind, (spr, label, rows) in GLYPHS.items():
    print(f"  {spr:5s} x{COUNT[kind]:<3d} {max(len(r) for r in rows)}x{len(rows)} "
          f"{runs_per_col(rows)} run/col   {label}")
