"""_die_turn_probe.py -- oracle only: die_gate's expectation for one scenario (its own Run / place), per frame the
player's pose, p_dead, p_attacker, and the attacker's position. Usage: python scratchpad/gp/_die_turn_probe.py D1 [N]"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import die_gate as D                                                         # noqa: E402
import fight_gate as FG                                                      # noqa: E402
import p2a_gate as G                                                         # noqa: E402
import probe as P                                                            # noqa: E402
import onewalk                                                               # noqa: E402
from doomfj.things import drawable_things                                    # noqa: E402
from doomfj.monsters import MonsterPhase                                     # noqa: E402
from doomfj.wall_renderer import BOOT_SKILL                                  # noqa: E402

name, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4
G.PLAYER_MODE_OVERRIDE = FG.PMODE
orc = P.Oracle()
orc.player_mode = FG.PMODE
dsim = onewalk.DoorSim()
card_di = [di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
           if t.type == G.CARD_TYPE][0]
run = D.Run(orc, dsim, card_di)
w0 = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=FG.MMODE, player=FG.PMODE)
sc = next(s for s in D.scenario_list(dsim, w0.world, dsim.dp.card_at) if s["name"].startswith(name + " "))
got = FG.place(run, sc, deaths_ok=True)
cand = got[0]
pose, setup, late = cand[0], cand[1], (cand[2] if len(cand) > 2 else None)
tr2, mr = run(pose, sc["keys"], setup, late=late)
print("pose", pose)
for f, fr in enumerate(tr2[:n]):
    st = fr["mstate"]
    print("f%d pose %s angle %08x p_dead %s p_atk %s" % (f, fr["pose"][:2], fr["pose"][2] & 0xFFFFFFFF,
                                                       st.get("p_dead"), st.get("p_atk")))
ws = mr.mph.world.ws
m = ws.p_attacker - 1
print("end: player", ws.px, ws.py, "angle %08x" % ws.pangle, "attacker slot", m, "at", ws.mon_x[m], ws.mon_y[m])
a = mr.mph.world.rm.point_to_angle(ws.px, ws.py, ws.mon_x[m] << 16, ws.mon_y[m] << 16)
print("model point_to_angle %08x" % a)
