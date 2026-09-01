"""Run scratchpad/deg_gate.py, printing WHICH stl it is about to build against.

Set PYTHONPATH to the flipjump worktree to gate the one-shadow setters; leave it unset to get
the stock editable install. The printed line is the only thing that distinguishes the two runs,
so it goes first and unbuffered.
"""
import runpy
import sys
from pathlib import Path

import flipjump

print("STL: " + str(Path(flipjump.__file__).resolve().parent / "stl"), flush=True)
DEG = Path(__file__).resolve().parents[1] / "deg_gate.py"
sys.argv = [str(DEG)]
runpy.run_path(str(DEG), run_name="__main__")
