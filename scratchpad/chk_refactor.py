import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.wireformat import encode_feed_mapunits
from doomfj.fastrun import FjmRunner
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from tests.fj.stream_screen import StreamScreen

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path("tests/fixtures/e1m1_lite.wad")
aw = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
art = WadFile.from_path("assets/freedoom1.wad")
scene = build_scene(mw, aw, "E1M1")
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
r = FjmRunner("scratchpad/fjmcache/b_727527e30e11bca1.fjm")
ok = True
for vx, vy, va, tag in [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"),
                        (664, 291, 0x18000000, "overlap")]:
    want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                wall_noise=True, sky=True, near_steps=True, things=True,
                                sprite_wad=art, bbox_cull=True)
    scr = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
    r.run(scr)
    same = bytes(scr.pixel_indices) == bytes(want)
    ok &= same
    print(tag, "BYTE-EXACT" if same else "DIFFERS")
print("refactor", "OK" if ok else "BROKE THE ORACLE")
sys.exit(0 if ok else 1)
