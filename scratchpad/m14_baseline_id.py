"""WHICH CONFIG is `b_272d37507ca58434.fjm`? — identifying the campaign's baseline binary.

docs/handoff-perf.md §1.1 uses `sweep_crfix2.csv` as "certified, pre-M14" and subtracts its median
from today's to get "M14 costs +13.7M, measured". `m14_vp_ops.py --oracle` shows that binary is NOT
byte-exact against today's oracle at any gate viewpoint (844-5300 of 16000 px), while today's M14
binary IS. Two explanations, and they have opposite consequences:

  (a) the PICTURE changed during M14 -- then the +13.7M is M14's cost plus a visual change, and
      §4's arithmetic is measuring two things at once;
  (b) the baseline binary is a DIFFERENT RENDERER CONFIG -- `b_*` binaries come from `bench.py`,
      whose FLAGS default `bbox_cull=True` and `sky=True`, neither of which `deg_gate.py` or
      `m14_gate.py` pass (both default False). Then the baseline was never comparable at all.

This decides it by rendering the oracle under each candidate flag set and diffing against the
binary's own pixels. A byte-exact hit NAMES the config; nothing else is claimed.

    python scratchpad/m14_baseline_id.py scratchpad/fjmcache/b_272d37507ca58434.fjm
"""
import itertools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

fjm = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/fjmcache/b_272d37507ca58434.fjm"
cfg = Config()
rm = ReferenceModel(cfg)
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))

# BASE = m14_gate.py's RENDER_KW. The two candidate flags are the ones bench.py turns on and the
# gates do not; `degrade` is varied too because it is the whole DEG package and a non-deg build
# would also differ.
BASE = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
            near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)
r = FjmRunner(str(ROOT / fjm) if not Path(fjm).is_absolute() else fjm)

ASSETS = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_assets.wad"))
for wad in ("tests/fixtures/freedoom_e1m1.wad", "tests/fixtures/e1m1_lite.wad"):
    mw = WadFile.from_path(str(ROOT / wad))
    # ⚠ lite carries no COLORMAP -- its assets come from the asset wad, as build_doom does it
    scene = build_scene(mw, mw if wad.endswith("freedoom_e1m1.wad") else ASSETS, "E1M1")
    sp = spawn_state(mw, "E1M1")
    vx, vy, va = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle
    scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    ops = r.run(scr)
    got = bytes(scr.pixel_indices)
    print(f"\n=== {Path(wad).name} spawn ({vx},{vy},{va:#x}) -- binary ran {ops:,} ops ===",
          flush=True)
    for sky, bbox, deg in itertools.product((False, True), (False, True), (True, False)):
        kw = dict(BASE, sky=sky, bbox_cull=bbox, degrade=deg)
        try:
            want = bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"),
                                              scene, **kw))
        except Exception as e:                       # a flag combination the oracle refuses
            print(f"  sky={sky:<5} bbox_cull={bbox:<5} degrade={deg:<5} -> {type(e).__name__}: {e}")
            continue
        nd = sum(1 for a, b in zip(got, want) if a != b)
        print(f"  sky={sky:<5} bbox_cull={bbox:<5} degrade={deg:<5} -> "
              + ("BYTE-EXACT  <== THIS IS THE CONFIG" if nd == 0
                 else f"{nd:5d} of {len(want)} px differ"), flush=True)
