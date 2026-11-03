"""--skill reaches the model-only run: the monsters active after NEW GAME at each skill (E1M5)"""
import os, sys
from pathlib import Path
ROOT = Path('.').resolve()
os.environ["DOOMFJ_MAP"] = "E1M5"
sys.path[:0] = [str(ROOT / "scratchpad" / "gp"), str(ROOT / "scripts"), str(ROOT / "src")]
import playthrough_gate as PG, play as PLAY
for sk in ("easy", "medium", "hard"):
    pl = PG._model_player(PLAY, sk)
    r = pl.run_model([], pl.mf + 3)
    c = r["last"]["cells"]
    print(sk, "active monsters after NEW GAME:", sum(1 for v in c["mon_active"] if v), "skill cell", c.get("skill"))
