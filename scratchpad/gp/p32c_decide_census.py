"""P3.2c's numbers on v5 with the full model: decisions and attack actions per frame, and the NEAR LOS -- attack-sight
calls that fall through `seen` to the exact trace (dist <= 128), with the candidate segments each tests after the bbox
reject. Run from a worktree root: python <this> [set file]

It writes docs/ship-evidence/p32c_decide_census_v5.log (the default set, v5):
    python scratchpad/gp/p32c_decide_census.py > docs/ship-evidence/p32c_decide_census_v5.log
(the log's last line, rc=0, is the runner's exit status, not this script's output)."""
import json
import statistics
import sys
sys.path[:0] = ["src", "scratchpad/gp", "scratchpad/12m"]
import scenarios_v2 as S                                     # noqa: E402
from doomfj import sight as SI                               # noqa: E402

SET = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/gp/scenarios/combat_scenarios_v5.json"
doc = json.load(open(SET))
S.use_sight_rule(doc)
dec, att, near, cands, calls = [], [], [], [], []
for run in doc["runs"]:
    w = S.start_world(run["setup"])
    base = w.attack_sight
    cnt = {"near": 0, "calls": 0}

    def counting(world, m, cnt=cnt):
        cnt["calls"] += 1
        ws = world.ws
        if not ws.mon_seen[m] and SI._dist(world, m) <= SI.NEAR:
            cnt["near"] += 1
            p, q = (ws.mon_x[m] << 16, ws.mon_y[m] << 16), (ws.px, ws.py)
            x0, x1 = min(p[0], q[0]), max(p[0], q[0])
            y0, y1 = min(p[1], q[1]), max(p[1], q[1])
            n = sum(1 for a, b, (lx0, lx1, ly0, ly1) in world._sight_walls
                    if not (lx1 < x0 or lx0 > x1 or ly1 < y0 or ly0 > y1))
            n += sum(1 for (a, b, (lx0, lx1, ly0, ly1)), fs, bs in world._sight_doors
                     if not (lx1 < x0 or lx0 > x1 or ly1 < y0 or ly0 > y1))
            cands.append(n)
        return base(world, m)
    w.attack_sight = counting
    for s in run["keys"]:
        cnt["near"] = cnt["calls"] = 0
        ev = w.tic(S.str_to_keys(s))
        dec.append(len(ev.decisions)); att.append(len(ev.attacks)); near.append(cnt["near"]); calls.append(cnt["calls"])


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


print("set %s (%s): %d frames" % (SET, doc.get("sight_rule"), len(dec)))
for name, xs in (("decisions", dec), ("attack actions", att), ("attack-sight calls", calls), ("near LOS traces", near)):
    print("  %-20s per frame: mean %.2f  p80 %d  p99 %d  max %d" % (name, statistics.mean(xs), q(xs, .8), q(xs, .99), max(xs)))
if cands:
    print("  candidate segments per near trace: mean %.1f  p80 %d  max %d  (%d traces)" % (
        statistics.mean(cands), q(cands, .8), max(cands), len(cands)))
