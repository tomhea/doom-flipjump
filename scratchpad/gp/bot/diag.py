"""diag.py MAP SKILL SEED FROM TO EVERY [budget] -- a model-only play (playthrough_gate.play) with the oracle's picture
saved every EVERY world frames in [FROM, TO) to scratchpad/gp/bot/diag_<map>/ (a dev aid, never evidence)"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scratchpad" / "gp"), str(ROOT / "scripts"), str(ROOT / "src")]
from doomfj.mapprofile import take_map_arg
mapname = sys.argv[1].upper()
sys.argv = [sys.argv[0], "--map", mapname] + sys.argv[2:]
take_map_arg(keep=False)
args = sys.argv[1:]
skill, seed, f0, f1, ev = args[0], args[1], int(args[2]), int(args[3]), int(args[4])
budget = int(args[5]) if len(args) > 5 else 6000
import playthrough_gate as PG
import play as PLAY
import level_route as LR
from PIL import Image
pl = PG._model_player(PLAY, skill)
pl.workers = 0
route = LR.plan(mapname, skill)
print(LR.summary(route))
lv = LR.Level(mapname, route.get("wad"), skill)
out = ROOT / "scratchpad" / "gp" / "bot" / ("diag_%s" % mapname.lower())
out.mkdir(exist_ok=True)
W, H = pl.orc.rm.cfg.W, pl.orc.rm.cfg.H
pal = list(pl.orc.art.playpal(0))
orig = pl.run_model
def run_model(keylog, frames, decide=None, on_frame=None):
    def of(rec):
        w = rec["f"] - pl.mf
        if f0 <= w < f1 and (w - f0) % ev == 0 and rec["fr"]["drawn"] == "world":
            px = PLAY_G.picture(pl.orc, pl.dsim, rec["fr"], pl.card_di)
            im = Image.new("RGB", (W, H)); im.putdata([tuple(pal[v]) for v in px])
            x, y, a = PLAY.pose_of(rec["cells"])
            im.resize((W * 3, H * 3), Image.NEAREST).save(out / ("w%05d.png" % w))
        return on_frame(rec)
    return orig(keylog, frames, decide=decide, on_frame=of)
PLAY_G = pl.G
pl.run_model = run_model
res = PG.play(PLAY, pl, route, lv, PG.parse_seed(seed), budget, True, trace=True)
st = res["st"]
print("RESULT done", st["done"], "dead", st["dead"], "legs", len(res["steer"].events), "/", len(res["steer"].legs))
