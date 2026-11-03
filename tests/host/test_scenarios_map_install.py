"""M8 (the gate-tool audit): scenarios_map.install on a map with NO checkpoints file leaves no E1M1 checkpoint behind
(use_doc passed None and E1M1's 11 hand-placed CHECKPOINTS stayed in the process), and R3 names every colour's key
doors there. Control: on E1M1 install changes nothing (its 11 checkpoints, its region names).
Each map in its own process (install is one map per process).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODE = r"""
import json, sys
sys.path[:0] = [r"{root}/src", r"{root}/scratchpad", r"{root}/scratchpad/12m", r"{root}/scratchpad/gp", r"{root}/tests"]
import scenarios_map as SM, scenarios_v2 as S
SM.install("{m}", None)
print("RESULT " + json.dumps({{"n": len(S.CHECKPOINTS), "r3": S.REGION_NAMES[3]}}))
"""


def _run(m):
    r = subprocess.run([sys.executable, "-c", CODE.format(root=ROOT.as_posix(), m=m)], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=600)
    line = [x for x in r.stdout.splitlines() if x.startswith("RESULT ")]
    assert line, r.stdout[-1000:] + r.stderr[-2000:]
    return json.loads(line[0][7:])


def test_no_e1m1_checkpoints_on_another_map():
    got = _run("E1M2")
    assert got == {"n": 0, "r3": "R3 behind the key doors"}, got


def test_control_e1m1_untouched():
    got = _run("E1M1")
    assert got["n"] == 11 and got["r3"] == "R3 behind the blue-key doors", got
