"""V5-SPR divergence fingerprint: where do the 381 px live (columns/rows/values)?"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from PIL import Image
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from doomfj.harness import W
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
cfg = Config()
rm = ReferenceModel(cfg)
VW, VH = cfg.VIEW_W, cfg.VIEW_H
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")

main = emit_wall_renderer(mw, "E1M1", cfg, over_align=False,
                          floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                          plane_near=True, wall_noise=True, steps=True, stack_steps=True,
                          things=True, sprite_wad=art)
tmp = Path(tempfile.mkdtemp())
consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
p = tmp / "v5d.fj"
p.write_text(main, encoding="utf-8")
out = tmp / "v5d.fjm"
fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()],
            out, memory_width=W, print_time=False)
print("assembled", flush=True)

vx, vy, va = 664, 291, 0x18000000
want = bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                  wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                  wall_noise=True, near_steps=True, stack_steps=True,
                                  things=True, sprite_wad=art))
scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
fj.run(out, io_device=scr, print_time=False, print_termination=False, flat_max_words=1 << 26)
got = bytes(scr.pixel_indices)

so: list = []
to: list = []
rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                     wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                     wall_noise=True, near_steps=True, stack_steps=True,
                     things=True, sprite_wad=art, steps_out=so, things_out=to)
ups, los = so[0]
sfrag = to[0]

cols: dict = {}
for i, (a, b) in enumerate(zip(want, got)):
    if a != b:
        y, x = divmod(i, VW)
        cols.setdefault(x, []).append((y, a, b))
print(f"{sum(len(v) for v in cols.values())} px differ across {len(cols)} columns")
for x in sorted(cols):
    v = cols[x]
    print(f"  x={x:3d} rows {v[0][0]}..{v[-1][0]} n={len(v)} "
          f"spr={'Y' if sfrag[x] is not None else 'n'} "
          f"ups={[(a, b) for a, b, *_ in ups[x]]} los={[(a, b) for a, b, *_ in los[x]]} "
          f"first(want={v[0][1]},got={v[0][2]})")
    if x > min(cols) + 12 and len(cols) > 14:
        print("  ...")
        break
pal = mw.playpal()
im = Image.new("RGB", (VW * 2, VH))
im.putdata([pal[c] for c in want] and [])
imw = Image.new("RGB", (VW, VH)); imw.putdata([pal[c] for c in want])
img = Image.new("RGB", (VW, VH)); img.putdata([pal[c] for c in got])
im.paste(imw, (0, 0)); im.paste(img, (VW, 0))
im.resize((VW * 4, VH * 2), Image.NEAREST).save(ROOT / "scratchpad/v5spr_diff.png")
print("scratchpad/v5spr_diff.png written (left oracle | right fj)")
