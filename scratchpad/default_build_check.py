"""Does the DEFAULT (shipped) build still assemble and stay byte-exact after V1/V2?

V1 added registers that are only USED under `rep(noise, k)`. The assembler rejects an unused label
outright, so a gated feature can break the ungated build -- this is the check for that.
"""
import hashlib, sys, tempfile, time
from pathlib import Path
ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import flipjump as fj
from doomfj.config import Config
from doomfj.fastrun import FjmRunner
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
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle), (-309, -44, 0)]
rm = ReferenceModel(cfg); scene = build_scene(mw, mw, "E1M1")
WANT = [bytes(rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"),
                                   scene, wall_mode="WPX", floor_mode_ft1=True, plane_near=True))
        for vx, vy, va in VPS]
t0 = time.time()
main = emit_wall_renderer(mw, "E1M1", cfg, asset_wad=mw, over_align=False, floor_mode="FT1",
                          wall_mode="WPX", raster_mode="lines", plane_near=True)
tmp = Path(tempfile.mkdtemp()); consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
(tmp / "m.fj").write_text(main, encoding="utf-8")
fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
            tmp / "m.fjm", memory_width=W, print_time=False)
r = FjmRunner(tmp / "m.fjm")
print(f"DEFAULT build assembles ({time.time()-t0:.0f}s)", flush=True)
for i, (vx, vy, va) in enumerate(VPS):
    scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    ops = r.run(scr)
    ok = bytes(scr.pixel_indices) == WANT[i]
    print(f"  ({vx},{vy}): {ops:,} ops  {'BYTE-EXACT' if ok else 'DIFFERS'}")
