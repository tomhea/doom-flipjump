"""Price the BUDGET knobs in PICTURE, oracle-side, before spending builds on them.

STEP_SEG_BUDGET (V3 step faces) and PNEAR_SEG_BUDGET (rung-3a plane attribution) both bound
per-frame work directly, so they are the cheapest ops levers available -- but both change pixels.
This reports how many, per viewpoint, against the current settings.

    python scratchpad/knob_probe.py
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import doomfj.config as CFGM                                              # noqa: E402
import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state  # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
VPS = [(_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle, "spawn"),
       (1400, 1200, 0, "courtyard"), (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")]
KW = dict(wall_mode="WPX", floor_mode_ft1=True, plane_near=True, wall_noise=True, sky=True,
          near_steps=True, things=True, sprite_wad=art)


def frame(vx, vy, va, step, pnear):
    RM.STEP_SEG_BUDGET, CFGM.PNEAR_SEG_BUDGET = step, pnear
    RM.PNEAR_SEG_BUDGET = pnear                       # bound at import in reference_model too
    return bytes(rm.render_wall_frame(
        SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene, **KW))


BASE = (12, 128)
SETTINGS = [(12, 128), (8, 128), (6, 128), (4, 128), (12, 64), (12, 32), (12, 16),
            (6, 32), (4, 16), (2, 8)]
print(f"{'STEP/PNEAR':>12s} " + "".join(f"{t:>12s}" for _a, _b, _c, t in VPS))
ref = {t: frame(vx, vy, va, *BASE) for vx, vy, va, t in VPS}
for step, pnear in SETTINGS:
    row = []
    for vx, vy, va, t in VPS:
        fb = frame(vx, vy, va, step, pnear)
        row.append(sum(1 for i in range(len(fb)) if fb[i] != ref[t][i]))
    print(f"{step:5d}/{pnear:<6d} " + "".join(f"{n:11d}px" for n in row))
