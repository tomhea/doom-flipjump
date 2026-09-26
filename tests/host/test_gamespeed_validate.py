"""`gamespeed.py --validate` must replay the doors the binary opens.

Run 0 of the owner's speed metric presses `use` inside a door's use box on its way north-east; the
game binary opens that door and walks through it, ending at map units (831, 653) -- read from the
RUNNING binary, frame by frame, through the probe (`scratchpad/12m/gamespeed_trail.py`,
`docs/ship-evidence/blocked27_gamespeed_trail.log`). `--validate` used to step an oracle whose doors
never open, and reported (831, 485): a walk the binary never takes, quoted as ship evidence
(`docs/ship-evidence/padB_gamespeed.log`).

COST. `--validate` plans all ten routes first (~75 s; the replay itself is ~0.1 s a run), so this
test replays run 0's RECORDED keys (`tests/fixtures/gamespeed_run0_keys.json`) through
`validate_scripts`, seeding gamespeed's own script cache so nothing is planned. `gamespeed.py
--selftest` checks the recording against `script(0)` (N6g), so a planner change cannot leave this
test replaying stale keys.

The replay runs in a subprocess: gamespeed.py puts tests/, src/ and scratchpad/ at the front of
sys.path when imported, which must not leak into the rest of the suite.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = "tests/fixtures/gamespeed_run0_keys.json"
DRIVER = r"""
import json, sys
sys.path.insert(0, "scratchpad/12m")
import gamespeed as GS
keys = json.load(open(sys.argv[1], encoding="ascii"))
GS._SCRIPTS[(0, len(keys), GS.DEFAULT_WAD, GS.DEFAULT_MAP)] = keys     # recorded: nothing planned
rows, _spread = GS.validate_scripts(n_runs=1, n_frames=len(keys), quiet=True)
print("END %d %d" % rows[0][0])
"""


def _run0_end():
    out = subprocess.run([sys.executable, "-c", DRIVER, KEYS], cwd=ROOT, capture_output=True,
                         text=True, timeout=300)
    ends = [line.split()[1:] for line in out.stdout.splitlines() if line.startswith("END ")]
    assert len(ends) == 1, out.stdout + out.stderr
    return tuple(int(v) for v in ends[0])


def test_validate_replays_the_door_run_0_opens():
    assert _run0_end() == (831, 653), "run 0 must end where the binary ends"
