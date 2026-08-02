"""V5 population counts for pricing: pieces per column, second pieces, region rows."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
W = cfg.VIEW_W
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1272, -724, 1073741824, "stairs"),
       (1869, 479, 2147483648, "worst"), (1400, 1200, 0, "courtyard"),
       (-309, 636, 0, "s3"), (2432, 1344, 3221225472, "tree")]

for vx, vy, va, tag in VPS:
    st = SimState(vx << 16, vy << 16, va, "E1M1")
    so: list = []
    rm.render_wall_frame(st, scene, wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                         wall_noise=True, sky=True, near_steps=True, things=True,
                         sprite_wad=art, bbox_cull=True, stack_steps=True, steps_out=so)
    ups, los = so[0]
    c1 = sum(1 for x in range(W) if len(ups[x]) + len(los[x]) >= 1)
    c2u = sum(1 for x in range(W) if len(ups[x]) >= 2)
    c2l = sum(1 for x in range(W) if len(los[x]) >= 2)
    pieces = sum(len(ups[x]) + len(los[x]) for x in range(W))
    print(f"{tag:10s} face-columns {c1:4d}  2nd-upper {c2u:3d}  2nd-lower {c2l:3d}  "
          f"total pieces {pieces:4d}")
