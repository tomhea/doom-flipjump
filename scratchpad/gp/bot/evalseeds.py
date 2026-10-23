"""evalseeds.py MAP SKILL SEEDS [CFG_JSON] [WORKERS] -- whole model-only plays on single seeds, in parallel: the
steering's strength on a map as a distribution (legs done, frames lived), for comparing the tactics' knobs (BOT_CFG).
A dev aid, never evidence."""
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "scratchpad" / "gp"), str(ROOT / "scripts"), str(ROOT / "src")]
if __name__ == "__main__":
    os.environ["DOOMFJ_MAP"] = sys.argv[1].upper()
    if len(sys.argv) > 4:
        os.environ["BOT_CFG"] = sys.argv[4]
    import multiprocessing as MP
    import playthrough_gate as PG
    import level_route as LR
    m, skill = sys.argv[1].upper(), sys.argv[2]
    seeds = [int(v) for v in sys.argv[3].split(",")]
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else len(seeds)
    t = time.time()
    route = LR.plan(m, skill)
    with MP.get_context("spawn").Pool(workers) as pool:
        outs = pool.map(PG._search_job, [(m, skill, route, [(0, sd)], 6000) for sd in seeds])
    for o in outs:
        print("seed %s: %s legs %d frames %d dead %s" % (o["sched"][0][1], "PASS" if o["done"] else "fail", o["legs"],
                                                       o["frames"], o["dead"] and tuple(int(v) for v in o["dead"][:3])))
    print("%s %s cfg %s: PASS %d/%d, mean legs %.1f, mean frames %.0f (%.0f s)" % (
        m, skill, os.environ.get("BOT_CFG", "{}"), sum(1 for o in outs if o["done"]), len(outs),
        sum(o["legs"] for o in outs) / len(outs), sum(o["frames"] for o in outs) / len(outs), time.time() - t))
