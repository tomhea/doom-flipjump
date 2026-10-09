"""`gamespeed.py --validate` must replay the game the binary plays.

Run 0 of the owner's speed metric used to press `use` inside a door's use box on its way north-east; the game binary
opened that door and walked through it, ending at map units (831, 653) -- read from the RUNNING binary, frame by
frame, through the probe (`scratchpad/12m/gamespeed_trail.py`, `docs/ship-evidence/blocked27_gamespeed_trail.log`).
`--validate` used to step an oracle whose doors never open, and reported (831, 485): a walk the binary never takes.

M7 P6+P7 (O3, docs/gp-p67-interface.md section 10): the player is now BLOCKED by monsters, picks things up, can be
hurt, and the monsters run two tics a frame -- and the turn's tap rule re-planned every route. `--validate` therefore
steps the WHOLE GAME at the game tier's modes (`gamespeed.GameSim`: the World, "full" / "full", the "seen" rule, the
tempo), and BINARY_ENDS are its PREDICTED ends until `gamespeed_trail.py` confirms them on the P6+P7 build. This test
holds runs 0 and 1 (the recorded keys) to them, and -- the R9 control -- requires the door-only replay that
`--validate` used through P5 (`doors=False`: step_sim without monsters) to PART from them on run 0: a replay that
ignores the monsters would pass a weaker test.

COST. `--validate` plans all ten routes first (~75 s), so this test replays the RECORDED keys of runs 0 and 1
(`gamespeed.RECORDED_KEYS`) through `validate_scripts`, seeding gamespeed's own script cache so nothing is planned
(~40 s: the game model renders its picture every tic, for the seen marks). Whether those recordings are still what
the planner plays is checked by `gamespeed.py --selftest` (N6g), which CI does not run: the ship gate's step 3 does.

The replay runs in a subprocess: gamespeed.py puts tests/, src/ and scratchpad/ at the front of sys.path when
imported, which must not leak into the rest of the suite.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = r"""
import json, sys
sys.path.insert(0, "scratchpad/12m")
import gamespeed as GS
runs = json.loads(GS.RECORDED_KEYS.read_text(encoding="ascii"))
for r, keys in runs.items():                                  # recorded: nothing is planned
    GS._SCRIPTS[(int(r), len(keys), GS.DEFAULT_WAD, GS.DEFAULT_MAP)] = keys
rows, _spread = GS.validate_scripts(n_runs=len(runs), n_frames=len(runs["0"]), quiet=True)
for r, row in enumerate(rows):
    print("END", r, *row[0], row[4] if len(row) > 4 else "none")
shut, _spread = GS.validate_scripts(n_runs=1, n_frames=len(runs["0"]), quiet=True, doors=False)
print("SHUT", 0, *shut[0][0], shut[0][4])
print("WANT", *[v for e in GS.BINARY_ENDS[:2] for v in e], *GS.BINARY_DOORS[:2])
"""


def _ends():
    out = subprocess.run([sys.executable, "-c", DRIVER], cwd=ROOT, capture_output=True, text=True,
                         timeout=600)
    rows = [line.split()[1:] for line in out.stdout.splitlines() if line.startswith("END ")]
    shut = [line.split()[1:] for line in out.stdout.splitlines() if line.startswith("SHUT ")]
    want = [line.split()[1:] for line in out.stdout.splitlines() if line.startswith("WANT ")]
    assert len(rows) == 2 and len(shut) == 1 and len(want) == 1, out.stdout + out.stderr
    ends = {int(r): ((int(x), int(y)), doors) for r, x, y, doors in rows}
    w = [int(v) for v in want[0]]
    return ends, ((int(shut[0][1]), int(shut[0][2])), shut[0][3]), {0: ((w[0], w[1]), str(w[4])),
                                                                    1: ((w[2], w[3]), str(w[5]))}


def test_validate_replays_the_game_the_binary_plays():
    ends, shut, want = _ends()
    assert ends[0] == want[0] == ((529, 208), "0"), "run 0 must end where BINARY_ENDS / BINARY_DOORS say"   # P8a: the final modes
    assert ends[1] == want[1] == ((-296, 120), "0"), "run 1 starts with every door shut, the world reset"
    # R9: the door-only replay (no monsters, no blocking: --validate through P5) walks elsewhere on run 0
    assert shut != ends[0], "the door-only replay ends where the game does: the comparison cannot see the monsters"
