"""M13-W1R look check: W1 (shipped, flat walls) vs W1R (randomized runs) vs WPX (real texels).

Renders the ORACLE on the shipped stack (e1m1_lite + full features) at the gate viewpoints,
before any fj is written. Also reports the wall-run pair counts per frame (upper bound on the
fj emit delta -- ditto columns pay nothing).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image, ImageDraw
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
W, H = cfg.VIEW_W, cfg.VIEW_H
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
pal = aw.playpal()          # the lite wad carries no PLAYPAL; assets come from the full wad

sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"),
       (2432, 1344, 3221225472, "tree"), (1272, -44, 1073741824, "(1272,-44)"),
       (1869, 479, 2147483648, "(1869,479,W)")]
MODES = ["W1", "W1R", "WPX"]


def render(vx, vy, va, mode):
    st = SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1")
    return bytearray(rm.render_wall_frame(
        st, scene, wall_mode=mode, floor_mode_ft1=True, plane_near=True,
        wall_noise=True, sky=True, near_steps=True, things=True,
        sprite_wad=art, bbox_cull=True))


def count_col_runs(fb):
    """Vertical colour-change pairs per frame (all columns; ditto-free upper bound)."""
    n = 0
    for x in range(W):
        prev = None
        for y in range(H):
            c = fb[y * W + x]
            if c != prev:
                n += 1
                prev = c
    return n


if __name__ == "__main__":
    S = 3
    sheet = Image.new("RGB", (W * S * len(VPS), (H * S + 22) * len(MODES)), (14, 14, 16))
    d = ImageDraw.Draw(sheet)
    for r, mode in enumerate(MODES):
        tot = 0
        for c, (vx, vy, va, tag) in enumerate(VPS):
            fb = render(vx, vy, va, mode)
            tot += count_col_runs(fb)
            im = Image.new("RGB", (W, H))
            im.putdata([pal[p] for p in fb])
            sheet.paste(im.resize((W * S, H * S), Image.NEAREST),
                        (c * W * S, r * (H * S + 22) + 22))
        d.text((6, r * (H * S + 22) + 5), f"{mode}   colour-change pairs/frame avg {tot // len(VPS)}",
               fill=(235, 235, 240))
        print(f"{mode:5s} pairs/frame avg {tot // len(VPS)}", flush=True)
    for c, (_, _, _, tag) in enumerate(VPS):
        d.text((c * W * S + 6, 12), tag, fill=(180, 200, 180))
    sheet.save(ROOT / "scratchpad/w1r_proto.png")
    print("scratchpad/w1r_proto.png written")
