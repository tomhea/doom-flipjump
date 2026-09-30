"""P3.2b's numbers, MEASURED on the frozen set v5 with the full model (the seen rule): per frame, the P_Move position
tests (tries), the moves made, the leaf changes (relinks), NewChaseDir calls and their caps, monster door presses, the
heavy slots used, and the active monsters (the thing-blocker loop's length). Run from the worktree root:
    python <this> [set file]"""
import json
import statistics
import sys
from collections import Counter

sys.path[:0] = ["src", "scratchpad/gp", "scratchpad/12m"]
import scenarios_v2 as S                                     # noqa: E402

SET = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/gp/scenarios/combat_scenarios_v5.json"
doc = json.load(open(SET))
S.use_sight_rule(doc)                                          # before any world is made
cols = ("tries", "moves", "relinks", "newchasedir", "capped", "door_uses", "heavy", "deferred", "active")
per = {c: [] for c in cols}
verdicts = Counter()
by_run = {}
for run in doc["runs"]:
    w = S.start_world(run["setup"])
    rt = []
    for s in run["keys"]:
        ev = w.tic(S.str_to_keys(s))
        n = w.layout.nmon
        row = dict(tries=ev.tries, moves=len(ev.moves), relinks=len(ev.leaf_changes), newchasedir=ev.newchasedir,
                   capped=ev.capped, door_uses=len(ev.door_uses), heavy=len(ev.heavy), deferred=len(ev.deferred),
                   active=sum(1 for m in range(n) if w.ws.mon_active[m]))
        for c in cols:
            per[c].append(row[c])
        for k, v in ev.blocked.items():
            verdicts[k] += v
        rt.append(ev.tries)
    by_run[run["name"]] = (statistics.mean(rt), max(rt))


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


print("set %s: %d runs, %d frames; sight rule %s" % (SET, len(doc["runs"]), len(per["tries"]), doc.get("sight_rule")))
for c in cols:
    xs = per[c]
    print("  %-12s per frame: mean %6.2f  p50 %3d  p80 %3d  p99 %3d  max %3d" % (
        c, statistics.mean(xs), q(xs, .5), q(xs, .8), q(xs, .99), max(xs)))
print("  refused tries by verdict:", dict(verdicts))
for k, (m, mx) in by_run.items():
    print("  %-22s tries/frame mean %.2f max %d" % (k, m, mx))
