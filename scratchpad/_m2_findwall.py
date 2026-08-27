"""Find a heading from the E1M1 spawn that walks into geometry, so the M5 gate can cover the
collision path. Oracle only -- step_sim, no rendering."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ANGLE_TURN, ReferenceModel, build_scene, spawn_state
from doomfj.wad import WadFile

mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
rm = ReferenceModel(Config())
scene = build_scene(mw, mw, "E1M1")
spawn = spawn_state(mw, "E1M1")
FWD = {"forward": True, "back": False, "turn_left": False, "turn_right": False}
TURN = {"forward": False, "back": False, "turn_left": False, "turn_right": True}
NONE = {"forward": False, "back": False, "turn_left": False, "turn_right": False}

print("turn-right frames -> angle, then hold W: first frame collision changes the outcome")
best = None
for turns in range(0, 64):
    st = spawn
    for _ in range(turns):
        st = rm.step_sim(st, TURN, scene=scene)
    blocked_at, nblocked = None, 0
    for f in range(turns, turns + 20):
        free = rm.step_sim(st, FWD)
        got = rm.step_sim(st, FWD, scene=scene)
        if (free.x, free.y) != (got.x, got.y):
            nblocked += 1
            if blocked_at is None:
                blocked_at = f
        st = got
    if blocked_at is not None:
        print("  turns=%2d ang=%#010x -> first blocked at frame %d, %d blocked of 20"
              % (turns, (spawn.angle + turns * (-ANGLE_TURN & 0xFFFFFFFF)) & 0xFFFFFFFF,
                 blocked_at, nblocked))
        if best is None or blocked_at < best[1]:
            best = (turns, blocked_at, nblocked)
print("")
print("BEST: turns=%s  first blocked frame %s  %s blocked of 20" % (best if best else ("none",)*3))
