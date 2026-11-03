"""the model's door cells and keys around a frame of a play (MAP SKILL SEED F0 F1)"""
import os, sys
from pathlib import Path
ROOT = Path('.').resolve()
os.environ["DOOMFJ_MAP"] = sys.argv[1].upper()
sys.path[:0] = [str(ROOT / "scratchpad" / "gp"), str(ROOT / "scripts"), str(ROOT / "src")]
import playthrough_gate as PG, play as PLAY, level_route as LR
m, sk, seed, f0, f1 = sys.argv[1].upper(), sys.argv[2], PG.parse_seed(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
pl = PG._model_player(PLAY, sk); pl.workers = 0
route = LR.plan(m, sk); lv = LR.Level(m, None, sk)
from doomfj.doors import door_kinds, door_states, use_boxes_xy
print("door order", lv.door_order)
print("kinds", {si: lv.dp.kinds[si] for si in lv.door_order})
print("nstates", {si: lv.dp.nstates[si] for si in lv.door_order})
print("boxes", {si: lv.dp.boxes.get(si) for si in lv.door_order})
print("switches", {si: lv.dp.switches.get(si) for si in lv.door_order if lv.dp.switches.get(si)})
print("walk triggers", lv.dp.triggers)
steer = PLAY.Steer(route, lv=lv, log=lambda s: None, seed=seed); steer.rt = pl.monster_rows()
def of(rec):
    if f0 <= rec["f"] <= f1:
        c = rec["cells"]; x, y, a = PLAY.pose_of(c)
        print(rec["f"], "(%d,%d) a%d" % (x, y, a), PLAY.keys_str(rec["keys"]), "dstate", c.get("dstate"), "ddir", c.get("ddir"), "dwait", c.get("dwait"), steer.why)
    return "stop" if rec["f"] > f1 else None
pl.run_model([], f1 + 2, decide=steer.decide, on_frame=of)
