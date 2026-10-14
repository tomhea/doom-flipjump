"""P11: gamespeed run R, the trail's drive (menu, NEW GAME, the tour's keys; nothing injected) -- the BINARY's seen
flags (thseen), pose and door states at every game frame's present, dumped to JSON (the evidence the SeenHook fix is
pinned to). Run in a doom-flipjump checkout:
PYTHONPATH="src;scratchpad/12m;scratchpad/gp;scratchpad" python trail_seen_dump.py FJM LABELS OUT.json [R] [N]"""
import json
import sys
from pathlib import Path

sys.path[:0] = ["scratchpad/12m", "scratchpad/gp", "scratchpad", "src"]
import b0_scenarios as B  # noqa: E402
import gamespeed as GS  # noqa: E402
import m2_std_gate as gate  # noqa: E402
import probe as P  # noqa: E402

R = int(sys.argv[4]) if len(sys.argv) > 4 else 7
N = int(sys.argv[5]) if len(sys.argv) > 5 else 100
CELLS = ("thseen", "viewx", "viewy", "viewangle", "dstate", "lstate", "mon_active", "mon_state")
with P.binary_lock("trail-seen-dump"):
    orc = P.Oracle()
    specs = B.setup_cell_specs(orc)
    table = P.LabelTable.load(Path(sys.argv[2]), {c.label for c in specs.values()})
    gb = P.GameBinary(Path(sys.argv[1]))
    p = P.Probe(specs, table, gb.width)
    got = {}
    mf = gate.MENU_FRAMES

    def present(pr, f):
        if f >= mf:
            got[f - mf] = pr.read_cells([c for c in CELLS if c in p.cells])
    p.on_present(present)
    per = GS.full_script(R, N)
    gb.run(len(per), GS.events_for(per), p, pre_run=lambda pr: pr.verify_known(orc.known_pristine()))
out = {"fjm": sys.argv[1], "run": R, "frames": N,
       "per_frame": {str(f): {k: (list(v) if isinstance(v, tuple) else v) for k, v in got[f].items()}
                     for f in sorted(got)}}
Path(sys.argv[3]).write_text(json.dumps(out), encoding="ascii")
print("dumped %d frames of run %d to %s" % (len(got), R, sys.argv[3]))
