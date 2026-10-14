"""Where does the BINARY part from the MODEL on a key script? GameSim (gamespeed's model of the game) is stepped with the
keys; the binary runs the same keys (m2_std_gate's events, menu boot pick included) and the probe reads its view pose
and health at every present. Prints the first frame where (viewx, viewy, viewangle, p_hp) differ, with context.
PYTHONPATH="src;scratchpad;scratchpad/12m;scratchpad/gp" python scratchpad/gp/p12_diverge.py FJM LABELS KEYS.json [N]"""
import json
import sys
from pathlib import Path

sys.path[:0] = ["scratchpad", "scratchpad/12m", "scratchpad/gp", "src"]
import b0_scenarios as B  # noqa: E402
import gamespeed as GS  # noqa: E402
import m2_std_gate as gate  # noqa: E402
import probe as P  # noqa: E402

fjm, labels, kpath = sys.argv[1], sys.argv[2], sys.argv[3]
keys = json.loads(Path(kpath).read_text(encoding="ascii"))
n = int(sys.argv[4]) if len(sys.argv) > 4 else len(keys)
keys = keys[:n]

g = GS.GameSim()
st = g.reset()
model = []
for kd in keys:
    st = g.step(st, kd)
    ws = g.w.ws
    model.append((ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, ws.pangle & 0xFFFFFFFF, ws.p_health,
                  tuple(ws.mon_health), tuple(ws.mon_state), tuple(ws.mon_tics), tuple(ws.mon_rng)))

with P.binary_lock("p12-diverge"):
    orc = P.Oracle()
    specs = {k: c for k, c in B.setup_cell_specs(orc).items() if k in ("viewx", "viewy", "viewangle", "p_hp", "mon_health",
                                                                  "mon_state", "mon_tics", "mon_rng")}
    table = P.LabelTable.load(Path(labels), {c.label for c in specs.values()})
    gb = P.GameBinary(Path(fjm))
    p = P.Probe(specs, table, gb.width)
    mf = gate.MENU_FRAMES
    got = {}

    def present(pr, f):
        if f >= mf:
            c = pr.read_cells(["viewx", "viewy", "viewangle", "p_hp", "mon_health", "mon_state", "mon_tics", "mon_rng"])
            got[f - mf] = (c["viewx"] & 0xFFFFFFFF, c["viewy"] & 0xFFFFFFFF, c["viewangle"] & 0xFFFFFFFF, c["p_hp"],
                           tuple(c["mon_health"]), tuple(c["mon_state"]), tuple(c["mon_tics"]), tuple(c["mon_rng"]))
    p.on_present(present)
    full = [{} for _ in range(mf)] + keys
    gb.run(len(full), gate.to_events(full) + gate.menu_exit_events(), p)

first = None
for f in range(n):
    b = got.get(f)
    m = model[f]
    if b is None or tuple(b[:4]) != m[:4] or any(tuple(x) != tuple(y) for x, y in zip(b[4:], m[4:])):
        first = f
        break
print("frames compared: %d; first divergence: %s" % (n, first))
if first is not None:
    b, m = got.get(first), model[first]
    names = ("mon_health", "mon_state", "mon_tics", "mon_rng")
    for i, nm in enumerate(names):
        d = [(k, m[4 + i][k], b[4 + i][k]) for k in range(min(len(m[4 + i]), len(b[4 + i]))) if m[4 + i][k] != b[4 + i][k]]
        if d:
            print("  %s differs at slots (slot, model, binary): %s" % (nm, d[:8]))
    for f in range(max(0, first - 3), min(n, first + 4)):
        print("  frame %4d keys %-60s model %s  binary %s" % (f, sorted(k for k, v in keys[f].items() if v),
                                                            [hex(v) if i < 3 else v for i, v in enumerate(model[f][:4])],
                                                            [hex(v) if i < 3 else v for i, v in enumerate((got.get(f) or ())[:4])]))
