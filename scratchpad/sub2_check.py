"""M13-subsample: (1) square-room sub=2 frames byte-exact vs the col_subsample=2 oracle;
(2) PNGs of E1M1 spawn full vs subsampled for the owner's look-check."""
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

def build(mw, mapname, cfg, aw, sub):
    main = emit_wall_renderer(mw, mapname, cfg, asset_wad=aw, over_align=False,
                              floor_mode="flat", wall_mode="W1", raster_mode="lines",
                              lines_subsample=sub)
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    (tmp / "m.fj").write_text(main, encoding="utf-8")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
                tmp / "m.fjm", memory_width=W, print_time=False)
    return tmp / "m.fjm"

def run(fjm, vx, vy, va):
    screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(fjm, io_device=screen, print_time=False, print_termination=False,
                  flat_max_words=1 << 26)
    return bytes(screen.pixel_indices), term.op_counter

cfg = Config()
rm = ReferenceModel(cfg)

# -- square, 5 viewpoints, sub=2 vs the subsampled oracle
mw = WadFile.from_path(str(ROOT / "tests/fixtures/square_room.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_assets.wad"))
scene = build_scene(mw, aw, "MAP01")
sp = spawn_state(mw, "MAP01")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
A45 = 0x20000000
VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45), (24, 24, A45)]
fjm2 = build(mw, "MAP01", cfg, aw, 2)
for vx, vy, va in VIEWPOINTS:
    want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                floor_texturing=False, wall_mode="W1", col_subsample=2)
    got, ops = run(fjm2, vx, vy, va)
    diff = sum(1 for a, b in zip(got, want) if a != b)
    print(f"square sub2 ({vx},{vy},{va:#x}): {'OK' if diff == 0 else f'DIFF {diff}'}  ops={ops:,}")

# -- E1M1 spawn: sub=2 vs subsampled oracle + PNGs of both variants
mw2 = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
scene2 = build_scene(mw2, mw2, "E1M1")
sp2 = spawn_state(mw2, "E1M1")
s2x, s2y = _signed(sp2.x, 32) >> 16, _signed(sp2.y, 32) >> 16
fjm_e2 = build(mw2, "E1M1", cfg, mw2, 2)
got2, ops2 = run(fjm_e2, s2x, s2y, sp2.angle)
want2 = rm.render_wall_frame(SimState(sp2.x, sp2.y, sp2.angle, "E1M1"), scene2,
                             floor_texturing=False, wall_mode="W1", col_subsample=2)
diff2 = sum(1 for a, b in zip(got2, bytes(want2)) if a != b)
print(f"E1M1 sub2 spawn: {'OK' if diff2 == 0 else f'DIFF {diff2}'}  ops={ops2:,}")

# PNGs (3x nearest-neighbour upscale so the owner can see them)
full = rm.render_wall_frame(SimState(sp2.x, sp2.y, sp2.angle, "E1M1"), scene2,
                            floor_texturing=False, wall_mode="W1")
pal = mw2.playpal()
from PIL import Image
def to_png(pix, path, scale=3):
    img = Image.new("RGB", (cfg.VIEW_W, cfg.VIEW_H))
    img.putdata([pal[b] for b in pix])
    img = img.resize((cfg.VIEW_W * scale, cfg.VIEW_H * scale), Image.NEAREST)
    img.save(path)
to_png(bytes(full), ROOT / "scratchpad/sub_full.png")
to_png(got2, ROOT / "scratchpad/sub_half.png")
changed = sum(1 for a, b in zip(bytes(full), got2) if a != b)
print(f"PNGs written; vs FULL resolution: {changed}/16000 pixels differ "
      f"({100*changed/16000:.1f}%)")
