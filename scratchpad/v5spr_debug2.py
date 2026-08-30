"""V5-SPR divergence: per-row bytes at a differing column + both sprite fragments."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.config import Config
from doomfj.wireformat import encode_feed_mapunits
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from doomfj.harness import W
from tests.fj.stream_screen import StreamScreen

cfg = Config()
rm = ReferenceModel(cfg)
VW, VH = cfg.VIEW_W, cfg.VIEW_H
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")

FJM = ROOT / "scratchpad" / "v5spr_dbg.fjm"
if not FJM.exists():
    main = emit_wall_renderer(mw, "E1M1", cfg, sprite_wad=art, tier="visual")
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    p = tmp / "v5d.fj"
    p.write_text(main, encoding="utf-8")
    SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                         "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                         "stream_render.fj")]
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()],
                FJM, memory_width=W, print_time=False)
    print("assembled + cached", flush=True)

vx, vy, va = 664, 291, 0x18000000
so: list = []
to: list = []
want = bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                  wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                  wall_noise=True, near_steps=True, stack_steps=True,
                                  things=True, sprite_wad=art, steps_out=so, things_out=to, sky=True, bbox_cull=True, degrade=True))
scr = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
fj.run(FJM, io_device=scr, print_time=False, print_termination=False, flat_max_words=1 << 26)
got = bytes(scr.pixel_indices)
print("diff total:", sum(1 for a, b in zip(want, got) if a != b))

ups, los = so[0]
sfrag = to[0]
for x in (85, 91):
    fr = sfrag[x]
    print(f"--- x={x}  ups={ups[x]}  los={los[x]}")
    if fr is not None:
        y0, runs, lr = fr
        print(f"    sfrag A: y0={y0} last_rel={runs[-1][0] if runs else '-'} "
              f"span=[{y0 + (0 if not runs else 0)}..{y0 + (runs[-1][0] if runs else 0)}) lr={lr} nruns={len(runs)}")
    for y in range(58, 96):
        a, b = want[y * VW + x], got[y * VW + x]
        print(f"    y={y:3d} want={a:3d} got={b:3d} {'<<' if a != b else ''}")
