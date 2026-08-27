"""PRICE A SUBSYSTEM AT THE MEDIAN — M1, the only method that prices in the target's own metric.

docs/handoff-perf.md §4: the band cannot be reached by removing M14 (the base renderer alone is
28.19M against a 25M ceiling), so any route to 25M goes through the base renderer or through the
picture. §7 permits removing some sprites and requires the option PRICED before it is proposed.

This builds the M14 `--things` config with one `ablate` member set and sweeps it on the same
260-frame grid, so the delta against `sweep_m14_lazy.csv` is the subsystem's cost AT THE MEDIAN.

⚠ AN ABLATED BUILD IS A MEASUREMENT, NOT A CANDIDATE. `sprnoemit` and friends do not draw the same
frame -- that is the point of them -- so the number they give is "what this subsystem costs", not
"what we would ship". Anything actually proposed has to come back through m14_gate.py.

    python scratchpad/m14_ablate_price.py sprnoemit [--sweep]
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
from doomfj.harness import W                                              # noqa: E402
from doomfj.reference_model import ReferenceModel                         # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer, write_program_files  # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj", "sim.fj")]
abl = sys.argv[1] if len(sys.argv) > 1 else "sprnoemit"
CACHE = ROOT / f"scratchpad/fjmcache/m14_abl_{abl}.fjm"

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))

if CACHE.exists() and "--rebuild" not in sys.argv:
    print(f"cache HIT {CACHE.name}", flush=True)
else:
    t0 = time.time()
    parts = emit_wall_renderer(mw, "E1M1", cfg, return_parts=True, over_align=False,
                               floor_mode="FT1", wall_mode="W1R", raster_mode="lines",
                               plane_near=True, wall_noise=True, steps=True, stack_steps=True,
                               things=True, sprite_wad=art, deg=True,
                               state_wire="bin", player_sim=True, collide=False,
                               moving_things=True, ablate=frozenset({abl}))
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    prog = write_program_files(parts, tmp, "e1m1")
    print(f"emitted (ablate={abl}) in {time.time()-t0:.0f}s -> assembling", flush=True)
    out = tmp / "a.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], *[p.resolve() for p in prog]],
                out, memory_width=W, print_time=False)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_bytes(out.read_bytes())
    print(f"assembled in {time.time()-t0:.0f}s -> {CACHE.name} "
          f"({CACHE.stat().st_size:,} bytes)", flush=True)
print(f"\nnow sweep it:\n  python scratchpad/m14_sweep.py {CACHE.relative_to(ROOT)} --things "
      f"--csv scratchpad/sweep_abl_{abl}.csv\nthen diff the median against sweep_m14_lazy.csv "
      "(35,311,166).")
