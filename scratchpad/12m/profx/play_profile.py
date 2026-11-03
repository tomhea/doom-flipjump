"""Profile a level's PLAYTHROUGH: playthrough_gate's binary play on the FJPROFX engine, then prof_dump.

    python play_profile.py <prefix> --map E1M6 --fjm <fjm> --labels <labels.tsv.gz> [playthrough_gate options]

The play is the gate's own (its pinned seed, its steering, the oracle beside the binary), so the profile is of the
level's speed set's game, op for op. The engine's counters cover the whole process, so the gate's R9 controls --
binary runs of their own -- are off (`--no-controls`): this is a measurement, never the gate's evidence. Writes
<prefix>.log.bin / .marks.bin / .self.bin / .incl.bin and .runs.json (as drive.py; heatsites.py reads them),
<prefix> relative to <WORK>.

Run `maps.py` for the same binary first (PROFX_LABELS_TSV, --gen-dir): the engine reads its maps from <WORK>.
"""
import importlib.util
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, engine_env, engine_pyd, load_marks, work_dir  # noqa: E402


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    if os.environ.get("FJPROFX_MAP") is None:
        # the engine reads its inputs from the environment at the first flat allocation (as drive.py)
        return subprocess.run([sys.executable, "-u", str(Path(__file__).resolve())] + argv, env=engine_env()).returncode
    prefix = Path(argv[0])
    prefix = prefix if prefix.is_absolute() else work_dir() / prefix
    spec = importlib.util.spec_from_file_location("flipjump.interpreter._fjcore", str(engine_pyd()))
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    sys.modules["flipjump.interpreter._fjcore"] = core
    sys.argv = ["playthrough_gate.py", "--no-controls"] + argv[1:]
    try:
        runpy.run_path(str(ROOT / "scratchpad" / "gp" / "playthrough_gate.py"), run_name="__main__")
        rc = 0
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    prefix.parent.mkdir(parents=True, exist_ok=True)
    print("prof_dump: %d present records -> %s.*" % (core.prof_dump(str(prefix)), prefix), flush=True)
    # heatsites.py reads the run list for its per-frame divisor (drive.py's shape: a run's frames, of which it takes
    # all but 2 as game frames); the play's game frames are phases.py's, marker 1 to marker 1
    from phases import frames
    games = sum(1 for _ in frames(load_marks(str(prefix) + ".marks.bin")))
    fjm = argv[argv.index("--fjm") + 1] if "--fjm" in argv else ""
    Path(str(prefix) + ".runs.json").write_text(json.dumps(
        {"mode": "playthrough", "fjm": fjm, "runs": [{"name": "playthrough", "frames": games + 2}]}), encoding="ascii")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
