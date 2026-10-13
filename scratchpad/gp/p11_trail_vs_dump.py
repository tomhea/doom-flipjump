"""P11: GameSim (the trail's reference, with whatever SeenHook the tree has) stepped over gamespeed run R against the
binary's dump (trail_seen_dump.py): per frame the pose, doors, lifts, monster states and seen flags -- the first frame
and cell that part, and the count of equal frames. Run in a doom-flipjump checkout:
PYTHONPATH="src;scratchpad/12m;scratchpad/gp;scratchpad" python trail_vs_dump.py DUMP.json"""
import json
import sys
from pathlib import Path

sys.path[:0] = ["scratchpad/12m", "scratchpad/gp", "scratchpad", "src"]
import gamespeed as GS  # noqa: E402

M32 = 0xFFFFFFFF
dump = json.loads(Path(sys.argv[1]).read_text(encoding="ascii"))
R, N = dump["run"], dump["frames"]
sim = GS.GameSim()
st = sim.reset()
w = sim.w
n = w.layout.nmon
equal, first = 0, None
for f, kd in enumerate(GS.script(R, N)):
    st = sim.step(st, kd)
    ws = w.ws
    b = dump["per_frame"][str(f)]
    model = {"pose": [ws.px & M32, ws.py & M32, ws.pangle & M32], "dstate": list(ws.d_state),
             "lstate": list(ws.l_state), "mon_active": [int(v) for v in ws.mon_active][:n],
             "mon_state": [int(v) for v in ws.mon_state][:n], "thseen": [int(v) for v in ws.mon_seen][:n]}
    binary = {"pose": [b["viewx"] & M32, b["viewy"] & M32, b["viewangle"] & M32], "dstate": b["dstate"],
              "lstate": b["lstate"], "mon_active": b["mon_active"][:n], "mon_state": b["mon_state"][:n],
              "thseen": b["thseen"][:n]}
    parts = [k for k in model if model[k] != binary[k]]
    if parts:
        if first is None:
            first = f
            for k in parts:
                mv, bv = model[k], binary[k]
                idx = [i for i, (x, y) in enumerate(zip(mv, bv)) if x != y]
                print("frame %d: %s parts at %s -- model %s, binary %s" % (f, k, idx[:6], [mv[i] for i in idx[:6]],
                                                                         [bv[i] for i in idx[:6]]))
    else:
        equal += 1
print("run %d: %d of %d frames equal; first parted frame: %s" % (R, equal, N, first))
