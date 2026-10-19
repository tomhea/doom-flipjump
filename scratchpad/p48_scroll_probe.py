"""M8 (special 48): run from the repo root with PYTHONPATH=src. Is special 48's horizontal texture offset VISIBLE in the game tier (W1R)?  Render the oracle with the two
scrolling sidedefs at x_off = k (k = leveltime under P_UpdateSpecials) and diff the frames.
CONTROL: the same in wall_mode='textured' (the real texture u) MUST differ, else the viewpoint never sees the wall."""
import sys, time
from pathlib import Path
from dataclasses import replace
from doomfj.wad import WadFile
from doomfj import reference_model as R
from doomfj.config import GAME_CFG, map_cfg

w = WadFile.from_path(Path("tests/fixtures/freedoom_e1m2.wad"))
cfg = map_cfg(GAME_CFG, "E1M2")
rm = R.ReferenceModel(cfg)
sc = R.build_scene(w, w, "E1M2", {})
orig_sides = list(w.sidedefs("E1M2"))
SCROLL = (1810, 1939)

def with_xoff(k):
    sides = list(orig_sides)
    for s in SCROLL:
        sides[s] = replace(sides[s], x_off=(orig_sides[s].x_off + k))
    w.sidedefs = lambda name, _s=sides: _s

def sector_at(x, y):
    ss = sc.cmap.subsectors[rm.point_in_subsector(sc.cmap, x, y)]
    seg = sc.cmap.segs[ss.firstseg]
    ld = w.linedefs("E1M2")[seg.linedef]
    sd = orig_sides[ld.front if seg.side == 0 else ld.back]
    return sd.sector

ANG90 = 0x40000000
views = [(816, -1300, ANG90), (816, -1480, 3 * ANG90), (816, -1392, ANG90), (816, -1392, 3 * ANG90),
         (700, -1392, ANG90 // 2), (900, -1500, ANG90 + ANG90 // 2)]
KW = dict(R.GAME_RENDER_KW); KW["things"] = False
for (x, y, a) in views:
    st = R.SimState(x << 16, y << 16, a, "E1M2")
    out = {}
    for mode, kw in (("game", KW), ("textured", dict(wall_mode="textured"))):
        fr = []
        for k in (0, 1, 2, 5, 17, 64):
            with_xoff(k)
            fr.append(rm.render_wall_frame(st, sc, **kw))
        out[mode] = [sum(a != b for a, b in zip(fr[0], f)) for f in fr[1:]]
    print("view", (x, y, hex(a)), "sector", sector_at(x, y),
          "pixels differing from k=0 at k=1,2,5,17,64:", out, flush=True)
