"""Look-check: the SKY1 walls (x=-544, y 288-352) with the new white-brick treatment."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
pal = aw.playpal(0)
W, H = cfg.VIEW_W, cfg.VIEW_H

VPS = [(-300, 320, 0x80000000, "west-at-skywalls"),
       (1869, 479, 0x80000000, "everything-gate")]
img = Image.new("RGB", (W * len(VPS) + 8 * (len(VPS) - 1), H))
for i, (vx, vy, va, tag) in enumerate(VPS):
    fb = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                              wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                              wall_noise=True, near_steps=True, stack_steps=True, sky=True,
                              things=True, sprite_wad=art, degrade=True)
    t = Image.new("RGB", (W, H))
    t.putdata([pal[b] for b in bytes(fb)])
    img.paste(t, (i * (W + 8), 0))
img = img.resize((img.width * 4, H * 4), Image.NEAREST)
img.save(ROOT / "scratchpad" / "cr" / "skywall_look.png")
print("saved scratchpad/cr/skywall_look.png")
