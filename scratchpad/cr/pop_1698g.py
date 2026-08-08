"""viewz + full column runs at x=100/108 + which record is physically visible."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile
from nb_validate import true_sector

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
verts = [(v.x, v.y) for v in mw.vertexes("E1M1")]
W, H = cfg.VIEW_W, cfg.VIEW_H
VA = 0x20000000

for tag, (vx, vy) in {"FAR": (1698, 892), "NEAR": (1715, 909)}.items():
    si = true_sector(verts, lds, sds, vx, vy)
    sec = secs[si]
    viewz = rm.view_z(sec.floor_h)
    print(f"{tag} ({vx},{vy}): sector {si} floor_h={sec.floor_h} light={sec.light} "
          f"-> viewz={viewz >> 16}")

fbs = {}
for tag, (vx, vy) in {"FAR": (1698, 892), "NEAR": (1715, 909)}.items():
    fbs[tag] = bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, VA, "E1M1"), scene,
                                          wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                          wall_noise=True, near_steps=True, stack_steps=True,
                                          sky=True, things=True, sprite_wad=art, degrade=True))


def runs(fb, x):
    col = [fb[y * W + x] for y in range(H)]
    out, s = [], 0
    for y in range(1, H + 1):
        if y == H or col[y] != col[s]:
            out.append((s, y - 1, col[s]))
            s = y
    return out

for tag in ("FAR", "NEAR"):
    print(f"\n=== {tag} full runs ===")
    for x in (100, 108):
        r = runs(fbs[tag], x)
        print(f"  x={x}: {len(r)} runs: " + " ".join(f"[{a}-{b}]:{c}" for a, b, c in r))
