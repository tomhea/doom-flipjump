"""Build the SHIPPED tier (`self_reset=False`, sim + collision + moving things) so round 2 can be
measured on the tier the repo actually reports, not on deg_gate's reduced config.

WHY THIS EXISTS. `scratchpad/deg_gate.py` builds `emit_wall_renderer(... things=True, deg=True)`
and nothing else -- no `state_wire`, no `player_sim`, no `collide`, no `moving_things`. The shipped
binary carries all four (the whole M14 layer), and its sweep median is ~5.4M ops higher. A delta
measured on the deg tier is a valid delta, but its PERCENTAGE is against the wrong denominator and
its transfer to the shipped tier is an assumption. This removes the assumption.

`self_reset=False` deliberately: that is the config `scratchpad/fjmcache/_rssprobe.fjm` is, so the
result is comparable to the number every M1 document quotes -- and it needs no M1 restore set, which
this tree's fj edits have invalidated (the labels moved).

⚠ ONE HEAVY BUILD AT A TIME (CLAUDE.md rule 1, peak RSS ~9.5 GB on a 16.8 GB machine). Run this
once, wait, run it again for the other tree. Do not background two.

    python scratchpad/ca2_shipbuild.py --out scratchpad/fjmcache/_ca2_ship_new.fjm
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.build import build_wall_renderer                     # noqa: E402
from doomfj.config import RENDER_FLAT_MAX_WORDS                  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--gen", default="build/generated_ca2ship")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
args = ap.parse_args()

out = Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
t0 = time.perf_counter()
print("building the SHIPPED tier (self_reset=False) -> %s" % out, flush=True)
info = build_wall_renderer(ROOT / args.wad, "E1M1",
                           out_fjm=out,
                           generated_dir=ROOT / args.gen,
                           flat_max_words=RENDER_FLAT_MAX_WORDS,
                           self_reset=False)
dt = time.perf_counter() - t0
sha = hashlib.sha256(out.read_bytes()).hexdigest()
print("")
print(json.dumps({k: info[k] for k in sorted(info) if k != "self_reset"}, indent=2)[:2000])
print("")
print("out    : %s" % out)
print("sha256 : %s" % sha)
print("bytes  : %s" % format(out.stat().st_size, ","))
print("wall   : %.0f s  ! this machine's wall clock drifts ~70%%; compare OP COUNTS, not this"
      % dt)
