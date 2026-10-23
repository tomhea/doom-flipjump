"""the texture memo changes no cell: 200 E1M3 world frames of the steering, cells per frame, without then with it"""
import sys, time
from pathlib import Path
ROOT=Path('.').resolve()
sys.path[:0]=[str(ROOT/"scratchpad"/"gp"),str(ROOT/"scripts"),str(ROOT/"src")]
sys.argv=[sys.argv[0],"--map","E1M3"]
from doomfj.mapprofile import take_map_arg; take_map_arg()
import playthrough_gate as PG, play as PLAY, level_route as LR
route=LR.plan("E1M3","easy"); lv=LR.Level("E1M3",None,"easy")
out=[]
for memo in (False, True):
    if not memo:
        PLAY.memo_textures = lambda: None
    else:
        import importlib; importlib.reload(PLAY)
    pl=PG._model_player(PLAY,"easy"); pl.workers=0
    cells=[]
    t=time.time()
    steer=PLAY.Steer(route, lv=lv, log=lambda s: None, seed=0); steer.rt=pl.monster_rows()
    r=pl.run_model([], pl.mf+1+200, decide=steer.decide, on_frame=lambda rec: cells.append(rec["cells"]) and None)
    out.append(cells); print("memo", memo, "%.1f s" % (time.time()-t), len(cells), flush=True)
bad=[i for i,(a,b) in enumerate(zip(*out)) if a!=b]
print("frames", len(out[0]), "differ", len(bad), bad[:5])
