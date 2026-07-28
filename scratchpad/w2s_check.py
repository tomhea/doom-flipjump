"""W2S tier: fj lines-mode frames byte-exact vs the wall_mode="W2S" oracle, + an E1M1 PNG."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
        "plane_bands.fj", "stream_render.fj")]


def build(mw, mapname, cfg, aw, wall_mode):
    main = emit_wall_renderer(mw, mapname, cfg, asset_wad=aw, over_align=False,
                              floor_mode="flat", wall_mode=wall_mode, raster_mode="lines")
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    (tmp / "m.fj").write_text(main, encoding="utf-8")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
                tmp / "m.fjm", memory_width=W, print_time=False)
    return tmp / "m.fjm"


def run(fjm, vx, vy, va):
    s = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(fjm, io_device=s, print_time=False, print_termination=False,
                  flat_max_words=1 << 26)
    return bytes(s.pixel_indices), term.op_counter


cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/square_room.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_assets.wad"))
scene = build_scene(mw, aw, "MAP01")
sp = spawn_state(mw, "MAP01")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
A45 = 0x20000000
VP = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45), (24, 24, A45)]
fjm = build(mw, "MAP01", cfg, aw, "W2S")
for vx, vy, va in VP:
    want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                floor_texturing=False, wall_mode="W2S")
    got, ops = run(fjm, vx, vy, va)
    d = sum(1 for a, b in zip(got, bytes(want)) if a != b)
    print(f"square W2S ({vx},{vy},{va:#x}): {'OK' if d == 0 else f'DIFF {d}'}  ops={ops:,}")

mw2 = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
scene2 = build_scene(mw2, mw2, "E1M1")
sp2 = spawn_state(mw2, "E1M1")
s2x, s2y = _signed(sp2.x, 32) >> 16, _signed(sp2.y, 32) >> 16
fjm2 = build(mw2, "E1M1", cfg, mw2, "W2S")
got2, ops2 = run(fjm2, s2x, s2y, sp2.angle)
want2 = rm.render_wall_frame(SimState(sp2.x, sp2.y, sp2.angle, "E1M1"), scene2,
                             floor_texturing=False, wall_mode="W2S")
d2 = sum(1 for a, b in zip(got2, bytes(want2)) if a != b)
print(f"E1M1 W2S spawn: {'OK' if d2 == 0 else f'DIFF {d2}'}  ops={ops2:,}")

from PIL import Image
pal = mw2.playpal()
img = Image.new("RGB", (cfg.VIEW_W, cfg.VIEW_H))
img.putdata([pal[b] for b in got2])
img.resize((cfg.VIEW_W * 3, cfg.VIEW_H * 3), Image.NEAREST).save(ROOT / "scratchpad/fj_w2s.png")
print("scratchpad/fj_w2s.png written")
