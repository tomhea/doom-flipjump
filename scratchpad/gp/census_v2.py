"""S5 on the FROZEN combat scenario set v2 (843f28a): the census and the fight line for the handoff's
budget table. No build, no binary, no tracked file touched -- this drives the committed S5 census
(census.run + census_lib, unchanged) and replays the set through scenarios_v2's own setup and key
parser.

    python scratchpad/gp/census_v2.py [--file scratchpad/gp/scenarios/combat_scenarios_v2.json]
                                      [--out scratchpad/gp/census_out/s4v2] [--runs NAME[,NAME...]]
    python scratchpad/gp/census_v2_report.py      -> census_out/s4v2/report_s4v2.txt

THE REPLAY is scenarios_v2.replay's: `apply_setup` on the census's own World (the player's pose, and
the aftermath run's corpses), then one `World.tic` per frozen key string (`str_to_keys`, strafe
included). census.run renders every tic under four pictures and writes one JSON line per (frame,
picture) to <out>/s4v2_<run>.jsonl:
  today    blocked27's picture -- what B0 measured
  todayR4  the same, skill-filtered: the fight line's baseline
  game     the model's picture under TODAY's compositor rules
  rec      the model's picture under the DECIDED D3 (a + c + d + e; b for projectiles and barrels)

THREE CONTROLS per run -- a run that fails one is reported FAILED and must not be priced:
  DIGEST   the model's final digest equals the frozen `model_final_digest`;
  POSES    every frame's player position (map units) and angle equal the frozen `poses`;
  PICTURE  the `rec` picture's drawn population equals the frozen `pops`, frame by frame
           (d_live, d_corpse, d_drop, d_fireball, d_fx, d_barrel). scenarios_v2.drawn_population
           counted them with the same wiring (census_lib sha16 3afbe3212c879baf, recorded in the
           set), so this proves the census drew the very frames the set froze, under the decided
           rules. (d_awake is reported, not checked: the set counts "not in A_Look", the census
           "has a target".)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import census as CS                                                          # noqa: E402
import census_lib as CL                                                      # noqa: E402
import scenarios_v2 as SV2                                                   # noqa: E402

PICTURES = ("today", "todayR4", "game", "rec")
POPS = ("d_live", "d_corpse", "d_drop", "d_fireball", "d_fx", "d_barrel")
_made = []


class _KeptCensus(CL.Census):
    """census_lib.Census, remembered, so the controls can read the World census.run stepped"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        _made.append(self)


def rec_pop(r: dict) -> dict:
    d = r.get("drawn", {})
    return {"d_live": d.get("live", 0) + d.get("live_awake", 0), "d_awake": d.get("live_awake", 0),
            "d_corpse": d.get("corpse", 0), "d_drop": d.get("drop", 0),
            "d_fireball": d.get("fireball", 0), "d_fx": d.get("fx", 0), "d_barrel": d.get("barrel", 0)}


def controls(run: dict, path: Path, c) -> bool:
    recs = [json.loads(line) for line in open(path)]
    rec = {r["tic"]: r for r in recs if r["variant"] == "rec"}
    n = len(run["keys"])
    have = sorted({(r["tic"], r["variant"]) for r in recs})
    complete = len(have) == n * len(PICTURES) and sorted(rec) == list(range(n))
    digest_ok = c.world.digest() == run["model_final_digest"]
    pose_bad = pic_bad = awake_same = 0
    first_bad = None
    for i in range(n):
        r = rec.get(i)
        x16, y16, a = run["poses"][i]
        if r is None or r["player"] != [x16 >> 16, y16 >> 16, a]:
            pose_bad += 1
        frozen = dict(zip(SV2.POP_FIELDS, run["pops"][i]))
        mine = rec_pop(r) if r else {}
        if any(mine.get(k) != frozen[k] for k in POPS):
            pic_bad += 1
            if first_bad is None:
                first_bad = (i, {k: (mine.get(k), frozen[k]) for k in POPS if mine.get(k) != frozen[k]})
        awake_same += bool(mine) and mine["d_awake"] == frozen["d_awake"]
    tot = {k: v for k, v in c.world.event_totals().items() if v}
    ftot = {k: v for k, v in run["totals"].items() if v and k in c.world.event_totals()}
    ok = complete and digest_ok and not pose_bad and not pic_bad
    print("  CONTROLS %-20s %s: records %s | DIGEST %s | POSES %d/%d | PICTURE %d/%d frames equal the"
          " frozen drawn population%s | d_awake same on %d/%d | event totals %s"
          % (run["name"], "PASS" if ok else "!! FAILED", "complete" if complete else "!! INCOMPLETE",
             "EQUAL" if digest_ok else "!! DIFFERS", n - pose_bad, n, n - pic_bad, n,
             "" if first_bad is None else " (first miss: frame %d %s)" % first_bad,
             awake_same, n, "equal" if tot == ftot else "differ: %s vs %s" % (tot, ftot)), flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(HERE / "scenarios" / "combat_scenarios_v2.json"))
    ap.add_argument("--out", default=str(HERE / "census_out" / "s4v2"))
    ap.add_argument("--runs", help="comma list of run names (default: all)")
    a = ap.parse_args()
    raw = Path(a.file).read_bytes()
    doc = json.loads(raw)
    print("S4 set %s: sha256 %s, version %s, status %s, keys_sha %s (recomputed %s), %d runs"
          % (a.file, hashlib.sha256(raw).hexdigest()[:16], doc["version"], doc["status"][:6],
             doc["keys_sha"], SV2.keys_sha(doc), len(doc["runs"])), flush=True)
    bad = [f for f, h in doc["hashes"].items()
           if (Path(SV2.ROOT) / f).exists() and SV2.sha16(Path(SV2.ROOT) / f) != h]
    print("recorded file hashes: %d files, %s" % (len(doc["hashes"]),
                                                   "all EQUAL" if not bad else "!! DIFFER: %s" % bad),
          flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    CS.OUT = out
    CS.VARIANTS_ONLY = set(PICTURES)
    CS.CL.Census = _KeptCensus
    want = set(a.runs.split(",")) if a.runs else None
    t0 = time.perf_counter()
    results = {}
    for run in doc["runs"]:
        if want and run["name"] not in want:
            continue
        keys = [SV2.str_to_keys(s) for s in run["keys"]]
        setup = run["setup"]
        CS.run("s4v2_" + run["name"], None, keys, 1, None,
               start=lambda c, s=setup: SV2.apply_setup(c.world, s),
               digest=run["model_final_digest"], skill=SV2.SKILL)
        results[run["name"]] = controls(run, out / ("s4v2_%s.jsonl" % run["name"]), _made[-1])
    n_ok = sum(results.values())
    print("ALL CONTROLS: %d/%d runs PASS (%.0f s)%s" % (
        n_ok, len(results), time.perf_counter() - t0,
        "" if n_ok == len(results) else " -- !! FAILED: %s" % [k for k, v in results.items() if not v]),
          flush=True)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
