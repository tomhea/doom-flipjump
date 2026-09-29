"""M7 P2a.1 -- set v3 never reaches P2a.1's new rules (docs/gp-doors-keys.md 4): in no run does the
model take the blue card or fire a walk-over trigger, and neither does B0's mirror (BinaryMirror,
the binary's tic on the injected poses). So B0 on v3 needs no new injection for dreq/pcard/wfired."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scenarios_v2 as S                                                   # noqa: E402

doc = json.loads((HERE / "scenarios" / "combat_scenarios_v3.json").read_text(encoding="ascii"))
bad = 0
for run in doc["runs"]:
    w = S.start_world(run["setup"])
    m = S.BinaryMirror(w)
    ci = [i for i, t in enumerate(w.pickup_things) if t.type == 5]
    assert len(ci) == 1, ci
    card = fired = req = 0
    for s in run["keys"]:
        kd = S.str_to_keys(s)
        ws = w.ws
        pre, pd = (ws.px, ws.py, ws.pangle), S.door_tuples(w)
        w.tic(kd)
        inj, bk = S.b0_injection(w.rm, pre, (ws.px, ws.py, ws.pangle), kd)
        m.step(inj, bk, pd)
        card |= m.state[3]
        fired |= any(m.state[1])
        req |= bool(m.state[2])
    model = (w.ws.pickup_taken[ci[0]], tuple(w.ws.w_fired))
    ok = not (card or fired or req or model[0] or any(model[1]))
    bad += not ok
    print("  %-20s mirror: card %d fired %d press %d | model: card %d wfired %s  %s"
          % (run["name"], card, fired, req, model[0], list(model[1]), "ok" if ok else "REACHED"))
print("V3 %s: %d of %d runs reach the card or a trigger" % ("CLEAR" if not bad else "REACHES", bad,
                                                         len(doc["runs"])))
sys.exit(1 if bad else 0)
