"""25M-CAP fast gate: stock E1M1 with the full degradation package ON, byte-exact vs the
degrade=True oracle at 4 viewpoints that exercise every lever (graduated things, B-gate,
sliver-flat, stack far gate, PNEAR 96)."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from tests.fj.stream_screen import StreamScreen
from doomfj.wall_renderer import emit_wall_renderer, write_program_files

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(664, 291, 0x18000000),        # the sprite-overlap frame: B-gate + graduated
       (1272, -724, 1073741824),      # stairs: the stack far gate
       (1869, 479, 2147483648),       # the everything frame: sliver + PNEAR + all
       (spx, spy, sp.angle)]

# ⚠ CR-2026-08 (IN-3, A0.1): `bbox_cull=True` was ADDED here so the gate certifies the SAME picture
# `build.py` ships and `scripts/walk_e1m1.py` shows. It was the one flag the walker passed and this
# gate did not, which meant the wedge subtree cull -- a mechanism that changes which marking segs
# spend budget -- was never covered by the repo's own proof. The four op counts below therefore
# CHANGED when this landed; that is the intended, one-time cost of unifying the three tiers.
parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, over_align=False,
                          floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                          plane_near=True, wall_noise=True, steps=True, stack_steps=True,
                          things=True, sprite_wad=art, bbox_cull=True, deg=True)
tmp = Path(tempfile.mkdtemp())
consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
# the emitted program is written as SEPARATE files (order is load-bearing -- see
# write_program_files); the huge generated regions no longer share a file with the program.
prog = write_program_files(parts, tmp, "e1m1")
print("program parts: " + ", ".join("%s=%s" % (p.name.split("_", 2)[2][:-3],
                                               format(p.read_text(encoding="utf-8").count(chr(10)) + 1, ","))
                                    for p in prog), flush=True)
out = tmp / "deg.fjm"
fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], *[p.resolve() for p in prog]],
            out, memory_width=W, print_time=False)
print("assembled", flush=True)

ok = True
for vx, vy, va in VPS:
    want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                wall_noise=True, near_steps=True, stack_steps=True,
                                things=True, sprite_wad=art, degrade=True)
    scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(out, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_MAX_WORDS)
    same = bytes(scr.pixel_indices) == bytes(want)
    ok &= same
    diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
    print(f"({vx},{vy},{va:#x}): {term.op_counter:,} ops  "
          f"{'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}", flush=True)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
