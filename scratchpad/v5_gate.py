"""V5 fast gate: stock E1M1, W1R+FT1+plane_near+steps+STACK (+grain), no things/sky.

Byte-exact vs the stack_steps oracle at 3 viewpoints with real stairs on screen. The square
room has no two-sided lines, so only E1M1 exercises this path (the doc's own pitfall list).
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(spx, spy, sp.angle), (1272, -724, 1073741824), (-309, 636, 0)]

main = emit_wall_renderer(mw, "E1M1", cfg, over_align=False,
                          floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                          plane_near=True, wall_noise=True, steps=True, stack_steps=True)
tmp = Path(tempfile.mkdtemp())
consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
p = tmp / "v5.fj"
p.write_text(main, encoding="utf-8")
out = tmp / "v5.fjm"
fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()],
            out, memory_width=W, print_time=False)
print("assembled", flush=True)

ok = True
for vx, vy, va in VPS:
    want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                wall_noise=True, near_steps=True, stack_steps=True)
    scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(out, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=1 << 26)
    same = bytes(scr.pixel_indices) == bytes(want)
    ok &= same
    diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
    print(f"({vx},{vy},{va:#x}): {term.op_counter:,} ops  "
          f"{'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}", flush=True)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
