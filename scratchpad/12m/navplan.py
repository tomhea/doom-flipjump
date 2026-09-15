"""A route planner that NAVIGATES, for gates whose beam search only worked by tunnelling.

`m2_std_gate.plan_to` is a width-24 beam sorted by straight-line distance to the goal. MEASURED:
the 24-frame route it certifies at FORWARD_MOVE=50 crosses TWO one-sided linedefs -- it reaches
door 48 by walking through walls, which the 50-unit unswept step allowed (see the note on
FORWARD_MOVE in reference_model.py). Once the step is small enough that walls actually stop the
player, that route does not exist and the beam finds nothing: a greedy frontier cannot walk around
an obstacle, and its pose de-dup buckets angle at 11.25 degrees while one turn is 3.5 degrees, so
three consecutive turns collapse into one state and are pruned -- the search cannot even turn.

This plans in two stages instead:

  1. GRID BFS over walkable cells, where two cells are adjacent only if `try_move` actually accepts
     the step between them. So the path obeys the same collision the game runs, and "no path" means
     genuinely unreachable rather than "the search gave up".
  2. STEERING along the resulting waypoints: each tic, turn toward the next waypoint if the heading
     error exceeds half a turn step, else walk. This emits the same key dicts the gate feeds the
     binary.

    python scratchpad/12m/navplan.py                 # plan to the nearest door, report
    python scratchpad/12m/navplan.py --selftest

CONTROLS (R9)
  C1 THE PATH IS WALKABLE -- every step of the returned key script is re-simulated and checked
     against every one-sided linedef. A planner that tunnels is exactly the bug being fixed, so a
     route that crosses a solid wall is REJECTED, not returned.
  C2 THE REACHABILITY TEST SEPARATES -- BFS must find a target in open space and must NOT find one
     walled off. A search that always succeeds proves nothing about reachability.
  C3 NON-VACUITY -- an empty route, or one that never enters the goal box, is reported as failure
     rather than as success.
"""
import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scratchpad"))

import doomfj.reference_model as rm_mod                                    # noqa: E402
from doomfj.reference_model import (ReferenceModel, spawn_state,           # noqa: E402
                                    build_scene, _signed)
from doomfj.config import Config                                           # noqa: E402
from doomfj.wad import WadFile                                             # noqa: E402
from doomfj.mapcompiler import bake_bsp                                    # noqa: E402
from doomfj import build as buildmod                                       # noqa: E402

KEY_NAMES = ("forward", "back", "turn_left", "turn_right", "use")
CELL = 16                     # map units per grid cell


def _keys(*on):
    return {k: (k in on) for k in KEY_NAMES}


def walkable_path(rm, scene, sx, sy, goal_pred, cell=CELL, cap=200000):
    """BFS over grid cells; adjacency is `try_move` accepting the step. Returns [(x,y), ...]."""
    start = (int(sx) // cell, int(sy) // cell)
    seen = {start}
    q = collections.deque([(start, [start])])
    steps = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    expanded = 0
    while q and expanded < cap:
        (cx, cy), path = q.popleft()
        wx, wy = cx * cell + cell // 2, cy * cell + cell // 2
        if goal_pred(wx, wy):
            return [(px * cell + cell // 2, py * cell + cell // 2) for px, py in path], expanded
        for ddx, ddy in steps:
            nc = (cx + ddx, cy + ddy)
            if nc in seen:
                continue
            nx, ny = nc[0] * cell + cell // 2, nc[1] * cell + cell // 2
            expanded += 1
            # the SAME collision the game runs -- not a bbox approximation
            if not rm.try_move(scene, wx << 16, wy << 16, nx << 16, ny << 16):
                continue
            seen.add(nc)
            q.append((nc, path + [nc]))
    return None, expanded


def steer(rm, scene, start, waypoints, accept, max_tics=600):
    """Turn toward each waypoint, then walk to it. Emits the gate's key dicts."""
    import math
    st = start
    script = []
    turn = rm_mod.ANGLE_TURN
    for (wx, wy) in waypoints[1:]:
        for _ in range(max_tics):
            if len(script) >= max_tics:
                return None
            x, y = _signed(st.x, 32) / 65536.0, _signed(st.y, 32) / 65536.0
            if (x - wx) ** 2 + (y - wy) ** 2 <= (CELL * 0.9) ** 2:
                break
            want = int(math.atan2(wy - y, wx - x) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
            diff = (want - st.angle) & 0xFFFFFFFF
            if diff > (1 << 31):
                diff -= 1 << 32
            if abs(diff) > turn // 2:
                kd = _keys("turn_left") if diff > 0 else _keys("turn_right")
            else:
                kd = _keys("forward")
            st = rm.step_sim(st, kd, scene=scene)
            script.append(kd)
            if accept(st):
                return script
    return script if accept(st) else None


def crossings(rm, scene, start, script, lds, verts):
    """Every solid (one-sided) linedef the centre path crosses. Must be zero."""
    def seg_cross(ax, ay, bx, by, cx, cy, dx, dy):
        def cr(ox, oy, px, py, qx, qy):
            return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)
        d1, d2 = cr(cx, cy, dx, dy, ax, ay), cr(cx, cy, dx, dy, bx, by)
        d3, d4 = cr(ax, ay, bx, by, cx, cy), cr(ax, ay, bx, by, dx, dy)
        return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))
    st, out = start, []
    for kd in script:
        ns = rm.step_sim(st, kd, scene=scene)
        a = (_signed(st.x, 32) / 65536.0, _signed(st.y, 32) / 65536.0)
        b = (_signed(ns.x, 32) / 65536.0, _signed(ns.y, 32) / 65536.0)
        if a != b:
            for li, ld in enumerate(lds):
                if ld.back != -1:
                    continue
                v1, v2 = verts[ld.v1], verts[ld.v2]
                if seg_cross(a[0], a[1], b[0], b[1], v1.x, v1.y, v2.x, v2.y):
                    out.append(li)
        st = ns
    return out, st


def setup():
    import m2_std_gate as G
    mw = WadFile.from_path(str(buildmod.DEFAULT_WAD))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(mw, "E1M1")
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    tbl = G.door_states(secs, lds, sds)
    boxes = G.use_boxes_xy(secs, lds, sds, cmap.vertexes)
    sp = spawn_state(mw, "E1M1")
    target = min(sorted(tbl), key=lambda si: ((boxes[si][0] + boxes[si][2]) // 2 - (sp.x >> 16)) ** 2
                 + ((boxes[si][1] + boxes[si][3]) // 2 - (sp.y >> 16)) ** 2)
    return G, mw, rm, lds, mw.vertexes("E1M1"), boxes, sp, target, build_scene(mw, mw, "E1M1")


def report(move):
    G, mw, rm, lds, verts, boxes, sp, target, scene = setup()
    rm_mod.FORWARD_MOVE = move << 16
    box = boxes[target]
    print("move %d u/tic; door %d, use box %s; spawn (%d,%d)"
          % (move, target, box, sp.x >> 16, sp.y >> 16))
    inbox = lambda wx, wy: box[0] <= wx <= box[2] and box[1] <= wy <= box[3]   # noqa: E731
    path, exp = walkable_path(rm, scene, _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, inbox)
    if not path:
        print("  GRID BFS: NO WALKABLE PATH (%d cells expanded) -- the door is genuinely "
              "unreachable at this speed" % exp)
        return 1
    print("  GRID BFS: %d waypoints (%d cells expanded)" % (len(path), exp))
    accept = lambda st: G.in_use_box_fixed(box, st.x, st.y)                   # noqa: E731
    script = steer(rm, scene, sp, path, accept)
    if not script:
        print("  STEERING: failed to land in the use box")
        return 1
    bad, end = crossings(rm, scene, sp, script, lds, verts)
    print("  STEERING: %d frames, ends (%d,%d), in use box: %s"
          % (len(script), _signed(end.x, 32) >> 16, _signed(end.y, 32) >> 16, accept(end)))
    print("  C1 solid-wall crossings: %d  %s"
          % (len(bad), "WALKABLE" if not bad else "REJECTED -- tunnels through %s" % sorted(set(bad))))
    return 0 if (not bad and accept(end)) else 1


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-56s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("navplan selftest -- a search that always succeeds proves no reachability")
    G, mw, rm, lds, verts, boxes, sp, target, scene = setup()
    rm_mod.FORWARD_MOVE = 16 << 16
    sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16

    near = lambda wx, wy: (wx - sx) ** 2 + (wy - sy) ** 2 <= 64 ** 2         # noqa: E731
    p, _e = walkable_path(rm, scene, sx, sy, near)
    check("C2 BFS reaches a target beside the spawn", bool(p))

    far = lambda wx, wy: wx > 100000                                        # noqa: E731
    p2, e2 = walkable_path(rm, scene, sx, sy, far, cap=40000)
    check("C2 ...and does NOT reach one outside the level", p2 is None, "%d expanded" % e2)

    # C1 must be able to SEE a tunnel: at the old 50-unit step the gate's own route crosses walls.
    rm_mod.FORWARD_MOVE = 50 << 16
    box = boxes[target]
    route = G.plan_to(rm, scene, sp, ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0), 40,
                      maxf=90, accept=lambda st: G.in_use_box_fixed(box, st.x, st.y))
    if route:
        bad, _end = crossings(rm, scene, sp, route, lds, verts)
        check("C1 detects the OLD beam route tunnelling", bool(bad),
              "crosses %s" % sorted(set(bad)))
    else:
        check("C1 detects the OLD beam route tunnelling", False, "beam found no route to compare")
    rm_mod.FORWARD_MOVE = 16 << 16
    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--move", type=int, default=16)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else report(a.move))
