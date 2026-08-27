"""Build the SELF-RESETTING binary through build.build_wall_renderer -- the wired path.

This is the wiring check: the loop must come out of the shipped entry point with a flag, not out of
a scratchpad pipeline. build_wall_renderer(self_reset=True) does the two passes itself and refuses
the binary if any baked address moved between them.

    python scratchpad/m1_wired_build.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.build import build_wall_renderer          # noqa: E402
from doomfj.config import RENDER_FLAT_MAX_WORDS       # noqa: E402

t0 = time.perf_counter()
m = build_wall_renderer(
    ROOT / "tests/fixtures/freedoom_e1m1.wad", "E1M1",
    out_fjm=ROOT / "build/doom_e1m1_loop.fjm",
    generated_dir=ROOT / "build/generated_loop",
    flat_max_words=RENDER_FLAT_MAX_WORDS,
    self_reset=True)          # restore_set defaults to the packaged src/doomfj/data set
print(json.dumps(m, indent=2))
print("total %.0fs" % (time.perf_counter() - t0))
