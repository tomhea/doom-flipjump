"""V4 increment A — the THINGS RECORD half, with nothing reading the fragments.

Nothing consumes `spslot`/`sprflag` yet, so the frame must be BYTE-EXACT against the V3 oracle
(`things=False`) -- which makes the ops delta the record half's price on its own, cleanly, without
the "a stub prices itself plus everything downstream" trap. Increment B adds the emit splice and
gates against `things=True`.

`--emit` switches to the full gate once the splice exists.
"""
import hashlib
import sys
import tempfile
import time
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
EMIT = "--emit" in sys.argv                      # increment B: the oracle draws the sprites too
cfg = Config()
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"),
       (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")]
WAS = [26_545_502, 27_604_046, None, 32_137_393]     # V1+V2+V3, the shipped tier before V4

rm = ReferenceModel(cfg)
scene = build_scene(mw, mw, "E1M1")
WANT = [bytes(rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"),
                                   scene, wall_mode="WPX", floor_mode_ft1=True, plane_near=True,
                                   wall_noise=True, sky=True, near_steps=True,
                                   things=EMIT, sprite_wad=art))
        for vx, vy, va, _ in VPS]
print("oracle frames:", [hashlib.sha256(w).hexdigest()[:12] for w in WANT], flush=True)

t0 = time.time()
main = emit_wall_renderer(mw, "E1M1", cfg, asset_wad=mw, over_align=False, floor_mode="FT1",
                          wall_mode="WPX", raster_mode="lines", plane_near=True,
                          wall_noise=True, sky=True, steps=True, things=True, sprite_wad=art)
print(f"emitted {len(main):,} chars ({time.time() - t0:.0f}s)", flush=True)
tmp = Path(tempfile.mkdtemp())
consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
(tmp / "m.fj").write_text(main, encoding="utf-8")
fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
            tmp / "m.fjm", memory_width=W, print_time=False)
print(f"assembled ({time.time() - t0:.0f}s)", flush=True)
r = FjmRunner(tmp / "m.fjm")

for i, (vx, vy, va, tag) in enumerate(VPS):
    scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    ops = r.run(scr)
    got = bytes(scr.pixel_indices)
    ok = got == WANT[i]
    d = f"({ops - WAS[i]:+11,} vs V3)" if WAS[i] else "(no V3 baseline)"
    line = f"{tag:10s} ({vx:5d},{vy:5d}): {ops:11,} ops   {d:24s} {'BYTE-EXACT' if ok else 'DIFFERS'}"
    if not ok:
        bad = [j for j in range(len(got)) if got[j] != WANT[i][j]]
        cols = sorted({j % cfg.VIEW_W for j in bad})
        line += (f"  -- {len(bad)} px, first at (col {bad[0] % cfg.VIEW_W}, "
                 f"row {bad[0] // cfg.VIEW_W}), {len(cols)} columns: {cols[:12]}")
    print(line, flush=True)
