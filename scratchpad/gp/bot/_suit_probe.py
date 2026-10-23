"""the player's health, suit counter and sector special per frame near the end of a play (MAP SKILL SEED F0 F1)"""
import os, sys
from pathlib import Path
ROOT = Path('.').resolve()
os.environ["DOOMFJ_MAP"] = sys.argv[1].upper()
sys.path[:0] = [str(ROOT / "scratchpad" / "gp"), str(ROOT / "scripts"), str(ROOT / "src")]
import playthrough_gate as PG, play as PLAY, level_route as LR
m, sk, seed, f0, f1 = sys.argv[1].upper(), sys.argv[2], PG.parse_seed(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
pl = PG._model_player(PLAY, sk); pl.workers = 0
route = LR.plan(m, sk); lv = LR.Level(m, None, sk)
orig = pl.run_model


def run_model(keylog, frames, decide=None, on_frame=None):
    def of(rec):
        c = rec["cells"]
        if f0 <= rec["f"] <= f1 and rec["f"] % 4 == 0:
            x, y, a = PLAY.pose_of(c)
            si = lv.sector_at(int(x), int(y))
            print(rec["f"], "(%d,%d)" % (x, y), "hp", c.get("p_hp"), "sector", si, "special", lv.secs[si].special,
                  "suit", c.get("p_rad", c.get("p_ironfeet")), "atk", c.get("p_atk"), flush=True)
        return on_frame(rec)
    return orig(keylog, min(frames, f1 + 2), decide=decide, on_frame=of)


pl.run_model = run_model
PG.play(PLAY, pl, route, lv, seed, 9000, True)     # the gate's own play (its on_frame feeds the steering's hurt_f)
