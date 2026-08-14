"""THE HONEST PRE-M14 BASELINE — today's renderer, today's picture, no M14 wire.

WHY THIS EXISTS. docs/handoff-perf.md §1.1 subtracts `sweep_crfix2.csv`'s median from today's and
calls the difference "M14's cost, measured". `m14_vp_ops.py --oracle` shows that the binary behind
that sweep (`b_272d37507ca58434.fjm`) is NOT byte-exact against today's oracle at any gate
viewpoint -- 1091 / 844 / 3256 / 5300 of 16000 pixels -- while today's M14 binary IS byte-exact at
all four. A baseline that draws a different picture cannot price a feature: the difference contains
the feature AND the picture change, and there is no way to tell them apart afterwards.
`m14_baseline_id.py` ruled out the cheap explanations (sky, bbox_cull, degrade, the lite map).

So this builds the baseline the comparison actually needs: `deg_gate.py`'s emit call VERBATIM --
which is `m14_gate.py`'s minus `state_wire="bin"`, `player_sim=True`, `moving_things=True` -- from
TODAY's source. Both binaries are then byte-exact against the same oracle, so a per-frame op
difference is M14's runtime cost and nothing else.

  1. build (cached at scratchpad/fjmcache/base_dec_today.fjm)
  2. GATE it: byte-exact vs today's degrade=True oracle at deg_gate's 4 viewpoints. ⚠ If this
     fails, the build is not a baseline and no number from it may be used.
  3. then: python scratchpad/lite_sweep_csv.py scratchpad/fjmcache/base_dec_today.fjm \
              --out scratchpad/sweep_base_today.csv
     and join against sweep_m14e_b1.csv with m14_delta_join.py.

⚠ ONE HEAVY BUILD AT A TIME (CLAUDE.md rule 1).

    python scratchpad/m14_basegate.py [--rebuild]
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer, write_program_files  # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

# deg_gate.py's SRC -- no sim.fj, because there is no sim in this build
SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
# --nothings: the SAME gated config with things=False. Not a candidate build -- it draws a
# different picture by construction -- but it bounds the WHOLE sprite bill at the median, which
# is what §7 needs before any sprite option can be proposed (docs/handoff-perf.md §4, §7).
NOTHINGS = "--nothings" in sys.argv
CACHE = ROOT / ("scratchpad/fjmcache/base_dec_today%s.fjm" % ("_nothings" if NOTHINGS else ""))

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(664, 291, 0x18000000), (1272, -724, 1073741824),
       (1869, 479, 2147483648), (spx, spy, sp.angle)]
RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=not NOTHINGS,
                 sprite_wad=None if NOTHINGS else art, degrade=True)

if CACHE.exists() and "--rebuild" not in sys.argv:
    print(f"cache HIT {CACHE.name} ({CACHE.stat().st_size:,} bytes)", flush=True)
else:
    t0 = time.time()
    # ⚠ deg_gate.py's emit call, verbatim. Any drift here and this stops being the baseline.
    parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, over_align=False,
                               floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                               plane_near=True, wall_noise=True, steps=True, stack_steps=True,
                               things=not NOTHINGS,
                               sprite_wad=None if NOTHINGS else art, deg=True)
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    prog = write_program_files(parts, tmp, "e1m1")        # ⚠ order is the contract
    print(f"emitted in {time.time() - t0:.0f}s -> assembling", flush=True)
    out = tmp / "base.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], *[p.resolve() for p in prog]],
                out, memory_width=W, print_time=False)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_bytes(out.read_bytes())
    print(f"assembled in {time.time() - t0:.0f}s -> {CACHE.name} "
          f"({CACHE.stat().st_size:,} bytes)", flush=True)

ok = True
for vx, vy, va in VPS:
    want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene, **RENDER_KW)
    scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(CACHE, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=1 << 26)
    diff = sum(1 for a, b in zip(bytes(scr.pixel_indices), bytes(want)) if a != b)
    ok &= diff == 0
    print(f"({vx},{vy},{va:#x}): {term.op_counter:,} ops  "
          f"{'BYTE-EXACT vs today oracle' if diff == 0 else f'!! {diff} px DIFFER'}", flush=True)
print("\nPASS -- this is a valid baseline: same picture as the M14 binary, no M14 wire"
      if ok else "\nFAIL -- NOT a baseline; do not sweep it")
sys.exit(0 if ok else 1)
