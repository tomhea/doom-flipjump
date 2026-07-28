"""M13-lines smoke: assemble + run the square room in raster_mode="lines", compare byte-exact vs
the W1/flat oracle at the 5 gate viewpoints. Fast (square table is tiny)."""
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

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/square_room.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_assets.wad"))
scene = build_scene(mw, aw, "MAP01")
sp = spawn_state(mw, "MAP01")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
A45 = 0x20000000
VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45), (24, 24, A45)]

main = emit_wall_renderer(mw, "MAP01", cfg, asset_wad=aw, over_align=False,
                          floor_mode="flat", wall_mode="W1", raster_mode="lines")
tmp = Path(tempfile.mkdtemp())
consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
(tmp / "m.fj").write_text(main, encoding="utf-8")
fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
            tmp / "m.fjm", memory_width=W, print_time=False)
print("assembled OK")

for vx, vy, va in VIEWPOINTS:
    want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                floor_texturing=False, wall_mode="W1")
    screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(tmp / "m.fjm", io_device=screen, print_time=False, print_termination=False)
    got = bytes(screen.pixel_indices)
    ok = got == bytes(want)
    diff = sum(1 for a, b in zip(got, want) if a != b)
    print(f"({vx},{vy},{va:#x}): {'OK' if ok else f'DIFF {diff} px'}  ops={term.op_counter:,}")
