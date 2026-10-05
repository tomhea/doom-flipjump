"""p67e_v6_record.py -- M7 P6+P7 package E: the combat set v6, RE-RECORDED from v5 under the owner's new model.

The owner (2026-10-05) asked for the monsters' tempo x2 (world.MONSTER_TICS_PER_FRAME) and for monsters and fireballs
always drawn (reference_model.GAME_RENDER_KW `exempt_actors`). Both move what v5 recorded: the replays (tempo) and the
drawn populations (the census picture is the game picture). A behaviour change is a NEW VERSION (scenarios README);
the coordinator decided v6 keeps v5's CHECKPOINTS AND SCRIPTS -- the same runs, setups and keys, byte for byte -- and
re-records what the model does with them. This tool does that, ORACLE ONLY, and never freezes:

  * every run's name, region, sector, why, style, params, setup, checkpoint and keys are copied from v5 unchanged (the
    keys hash is v5's, asserted);
  * `monster_tics` = world.MONSTER_TICS_PER_FRAME and the sight rule v5's ("seen"), applied through
    scenarios_v2.use_sight_rule, so every later load of v6 replays this model;
  * each run is replayed with the census (`scenarios_v2.replay(census=True)`, the game picture: `exempt_actors`) and
    its poses, final digest, totals, drawn populations and player-opened doors are recorded; the CAP-22 criteria are
    evaluated and stored (`validation`) -- a FAIL is recorded, not hidden;
  * the source hashes are taken now; `status` is PLANNED, with no B0 and no approval: B0 is measured on the built
    binary (`b0_scenarios.py --file <v6>`), and the freeze is the owner's.

    PYTHONPATH="src;." python scratchpad/gp/p67e_v6_record.py [--out scratchpad/gp/scenarios/combat_scenarios_v6.json]
    PYTHONPATH="src;." python scratchpad/gp/p67e_v6_record.py --check F    # F's keys are v5's, its tempo the game's

NOTE for the freeze: `scenarios_v2.py --freeze` RE-PLANS the set and requires the autopilot to give identical keys. v6's
keys are v5's by decision (not re-planned under the new tempo), so a first freeze of v6 needs the owner's approval AND a
freeze path that accepts inherited keys (or a re-plan, which would be a different set) -- the coordinator's choice.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

import scenarios_v2 as S                                                     # noqa: E402
from doomfj import world as W                                                # noqa: E402

V5 = HERE / "scenarios" / "combat_scenarios_v5.json"
V6 = HERE / "scenarios" / "combat_scenarios_v6.json"
KEEP = ("name", "region", "sector", "why", "style", "params", "setup", "checkpoint", "keys")


def build_v6(v5: dict) -> dict:
    doc = {k: copy.deepcopy(v) for k, v in v5.items()
           if k not in ("runs", "validation", "hashes", "b0", "owner_approval", "freeze", "freeze_history",
                        "rehash_log", "planned_at_git_head", "keys_sha")}
    doc.update({"version": "v6",
                "status": "PLANNED -- B0 and the owner's freeze pending (keys inherited from v5: see "
                          "scratchpad/gp/p67e_v6_record.py's note)",
                "monster_tics": W.MONSTER_TICS_PER_FRAME,
                "derived_from": {"set": "combat_scenarios_v5.json", "keys_sha": v5["keys_sha"],
                                 "rule": "v5's checkpoints and scripts, re-recorded under the monster tempo x2 "
                                         "and the actors rule (M7 P6+P7 package E, the owner 2026-10-05)"},
                "runs": [{k: copy.deepcopy(run[k]) for k in KEEP} for run in v5["runs"]]})
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--v5", default=str(V5))
    ap.add_argument("--out", default=str(V6))
    ap.add_argument("--check", metavar="F", help="check F: keys are v5's, tempo the game's, status not FROZEN")
    a = ap.parse_args()
    v5 = json.loads(Path(a.v5).read_text(encoding="ascii"))
    if a.check:
        d = json.loads(Path(a.check).read_text(encoding="ascii"))
        ok = (S.keys_sha(d) == v5["keys_sha"] == d["derived_from"]["keys_sha"]
              and d.get("monster_tics") == W.MONSTER_TICS_PER_FRAME and d.get("status") != "FROZEN")
        print("v6 check: keys %s (v5 %s), tempo %s, status %r -> %s" % (
            S.keys_sha(d), v5["keys_sha"], d.get("monster_tics"), d.get("status"), "OK" if ok else "FAIL"))
        return 0 if ok else 1
    assert v5.get("status") == "FROZEN" and v5.get("sight_rule") == "seen", (v5.get("status"), v5.get("sight_rule"))
    assert S.keys_sha(v5) == v5["keys_sha"], "v5's keys do not hash to its own keys_sha"
    doc = build_v6(v5)
    assert S.keys_sha(doc) == v5["keys_sha"], "v6 must carry v5's scripts unchanged"
    S.use_sight_rule(doc)
    assert S.MONSTER_TICS == W.MONSTER_TICS_PER_FRAME and S.SIGHT_RULE == "seen"
    t0 = time.time()
    print("v6 from %s: %d runs, keys %s, monster tempo %d, sight %s" % (
        Path(a.v5).name, len(doc["runs"]), v5["keys_sha"], S.MONSTER_TICS, S.SIGHT_RULE), flush=True)
    # the replay and the CAP-22 criteria (scenarios_v2.validate's first half; its freeze checks need a frozen set)
    ms = [S.replay(run, census=True) for run in doc["runs"]]
    res = {"criteria": S.criteria(ms), "metrics": ms}
    for run, r in zip(doc["runs"], res["metrics"]):
        run.update({"poses": r["poses"], "model_final_digest": r["digest"], "totals": r["totals"]})
        old = next(x for x in v5["runs"] if x["name"] == run["name"])
        moved = next((f for f in range(len(r["poses"])) if r["poses"][f] != old["poses"][f]), None)
        print("  %-20s first pose moved at frame %s; dead %d (health %d); kills %d (v5 %d); player hurt %d (v5 %d)"
              % (run["name"], moved, r["dead"], r["health"], r["totals"]["kills"], old["totals"]["kills"],
                 r["totals"]["player_hurt"], old["totals"]["player_hurt"]), flush=True)
    S.record_validation(doc, res)
    doc["hashes"] = S.code_hashes()
    doc["planned_at_git_head"] = S.git_head()
    doc["keys_sha"] = S.keys_sha(doc)
    Path(a.out).write_text(json.dumps(doc, indent=1), encoding="ascii", newline="\n")
    okc = all(ok for _n, ok, _d in res["criteria"])
    print("wrote %s (%.0f s): criteria %s; keys %s (v5's)" % (a.out, time.time() - t0, "PASS" if okc else "FAIL",
                                                             doc["keys_sha"]))
    for n, ok, d in res["criteria"]:
        if not ok:
            print("  FAIL  %s  %s" % (n, d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
