"""P3.2's sight decision, MEASURED on the frozen set v4 with the full model: how many sight checks a frame makes, how
many candidate lines each tests after the bounding-box reject (the work an exact 2D LOS does per check), and how often
sight is true. Run from the worktree root: python <this> [set file]"""
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path[:0] = ["src", "scratchpad/gp", "scratchpad/12m"]
import scenarios_v2 as S                                     # noqa: E402
from doomfj.world import World, segments_touch               # noqa: E402

SET = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/gp/scenarios/combat_scenarios_v4.json"
import json                                                   # noqa: E402
doc = json.load(open(SET))

per_frame, per_call, by_run, truth = [], [], {}, Counter()
for run in doc["runs"]:
    w = S.start_world(run["setup"])
    calls = [0]

    def counting(world, m, calls=calls):
        ws = world.ws
        p, q = (ws.mon_x[m] << 16, ws.mon_y[m] << 16), (ws.px, ws.py)
        x0, x1 = min(p[0], q[0]), max(p[0], q[0])
        y0, y1 = min(p[1], q[1]), max(p[1], q[1])
        n = sum(1 for a, b, (lx0, lx1, ly0, ly1) in world._sight_walls
                if not (lx1 < x0 or lx0 > x1 or ly1 < y0 or ly0 > y1))
        n += sum(1 for (a, b, (lx0, lx1, ly0, ly1)), fs, bs in world._sight_doors
                 if not (lx1 < x0 or lx0 > x1 or ly1 < y0 or ly0 > y1))
        per_call.append(n)
        calls[0] += 1
        r = World.los_to_player(world, m)
        truth[r] += 1
        return r
    w.sight = counting
    frames = []
    for s in run["keys"]:
        calls[0] = 0
        w.tic(S.str_to_keys(s))
        frames.append(calls[0])
    per_frame += frames
    by_run[run["name"]] = (statistics.mean(frames), max(frames))


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


print("set %s: %d runs, %d frames" % (SET, len(doc["runs"]), len(per_frame)))
print("sight checks per frame: mean %.2f  p50 %d  p80 %d  p99 %d  max %d" % (
    statistics.mean(per_frame), q(per_frame, .5), q(per_frame, .8), q(per_frame, .99), max(per_frame)))
print("candidate lines per check (after the bbox reject): mean %.1f  p50 %d  p80 %d  p99 %d  max %d" % (
    statistics.mean(per_call), q(per_call, .5), q(per_call, .8), q(per_call, .99), max(per_call)))
print("line tests per frame (checks x candidates): mean %.1f" % (sum(per_call) / len(per_frame)))
print("sight true %d / false %d" % (truth[True], truth[False]))
for k, (m, mx) in by_run.items():
    print("  %-22s checks/frame mean %.2f max %d" % (k, m, mx))
