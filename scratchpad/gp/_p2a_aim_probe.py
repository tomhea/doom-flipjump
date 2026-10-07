"""_p2a_aim_probe.py -- oracle only: p2a_gate's expectation (its own Mirror + hooks) for one scenario, printing the
aim window (aim_sid) the gate expects on the first N frames. Usage: python scratchpad/gp/_p2a_aim_probe.py S7 [N]"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import p2a_gate as G                                                         # noqa: E402
import probe as P                                                            # noqa: E402
import onewalk                                                               # noqa: E402
from doomfj.things import drawable_things                                    # noqa: E402

name, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3
orc = P.Oracle()
dsim = onewalk.DoorSim()
card_di = [di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
           if t.type == G.CARD_TYPE]
sc = next(s for s in G.scenarios(dsim, dsim.dp.card_at) if s["name"].startswith(name + " "))
sc = dict(sc, keys=sc["keys"][:n])
want = G.hooked(G.Mirror(dsim, card_di[0]), orc, dsim, card_di[0]).run(sc["pose"], sc["keys"], sc["pcard"])
for f, fr in enumerate(want):
    print("f%d aim_sid %s" % (f, G.expected_cells(fr, dsim.order, dsim.mp.order).get("aim_sid")))
