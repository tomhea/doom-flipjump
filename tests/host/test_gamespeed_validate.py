"""`gamespeed.py --validate` must replay the doors the binary opens.

Run 0 of the owner's speed metric presses `use` inside a door's use box on its way north-east; the
game binary opens that door and walks through it, ending at map units (831, 653) with one door
opened -- read from the RUNNING binary, frame by frame, through the probe
(`scratchpad/12m/gamespeed_trail.py`, `docs/ship-evidence/blocked27_gamespeed_trail.log`).
`--validate` used to step an oracle whose doors never open, and reported (831, 485): a walk the
binary never takes, quoted as ship evidence (`docs/ship-evidence/padB_gamespeed.log`). Run 1 opens
no door; it starts right after run 0, which is where a stepper that is not reset between runs shows.

COST. `--validate` plans all ten routes first (~75 s; the replay itself is ~0.1 s a run), so this
test replays the RECORDED keys of runs 0 and 1 (`gamespeed.RECORDED_KEYS`) through
`validate_scripts`, seeding gamespeed's own script cache so nothing is planned. Whether those
recordings are still what the planner plays is checked by `gamespeed.py --selftest` (N6g), which
CI does not run: the ship gate's step 3 does (`docs/ship-gate.md`).

The replay runs in a subprocess: gamespeed.py puts tests/, src/ and scratchpad/ at the front of
sys.path when imported, which must not leak into the rest of the suite.
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
"""


def _ends():
    out = subprocess.run([sys.executable, "-c", DRIVER], cwd=ROOT, capture_output=True, text=True,
                         timeout=300)
    rows = [line.split()[1:] for line in out.stdout.splitlines() if line.startswith("END ")]
    assert len(rows) == 2, out.stdout + out.stderr
    return {int(r): ((int(x), int(y)), doors) for r, x, y, doors in rows}


def test_validate_replays_the_door_run_0_opens():
    ends = _ends()
    assert ends[0] == ((831, 653), "1"), "run 0 must end where the binary ends, one door opened"
    assert ends[1] == ((-357, 430), "0"), "run 1 opens no door, and starts with every door shut"
