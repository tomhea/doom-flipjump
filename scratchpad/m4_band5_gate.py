"""M4-R2 -- deg_gate with BAND_NIBBLES=5: WHAT THE WIDE BAND INDEX COSTS.

The seven shippable levels need 384,156 band ids (pad 524,288), so a multi-level image needs a
5-nibble index where E1M1 ships 4. `generate_bands_walk_fj` derives its switch `pad` from the LIST
COUNT, not from the index width, so forcing 5 on E1M1 changes ONE thing: `rep(index_nibbles, i)
hex.xor vpb_dsp + 4*i, idx + i*dw` gains a nibble. The picture is therefore required to be
byte-exact and the ops are required to RISE -- identical ops would mean the width never took.

This is the LAST unknown in the +10% budget: the pid widening already spent +6.74% of it."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS
from doomfj.wireformat import encode_feed_mapunits
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from tests.fj.stream_screen import StreamScreen
from doomfj.wall_renderer import emit_wall_renderer, write_program_files

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
cfg = Config(BAND_NIBBLES=5)   # M4-R2: THE WIDE BAND INDEX
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

# ⚠ CR-2026-08 (IN-3, A0.1): `which meant the wedge subtree cull -- a mechanism that changes which marking segs
# spend budget -- was never covered by the repo's own proof. The four op counts below therefore
# CHANGED when this landed; that is the intended, one-time cost of unifying the three tiers.
parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, sprite_wad=art, tier="visual")
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
                                things=True, sprite_wad=art, degrade=True, sky=True, bbox_cull=True)
    scr = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
    term = fj.run(out, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_MAX_WORDS)
    same = bytes(scr.pixel_indices) == bytes(want)
    ok &= same
    diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
    print(f"({vx},{vy},{va:#x}): {term.op_counter:,} ops  "
          f"{'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}", flush=True)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
