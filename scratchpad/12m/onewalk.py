"""ONE walk of the whole level. ONE number: total ops divided by total game frames.

    python scratchpad/12m/onewalk.py --fjm build/doom_e1m1_blocked25.fjm
    python scratchpad/12m/onewalk.py --selftest        # R9: the controls must reject a bad trail

WHY THIS REPLACES EVERYTHING BEFORE IT. Three generations of speed harness each answered a
different question and none of them answered "what does playing this game cost":

  * `gamespeed` plays ten 100-frame runs from the BAKED PLAYER START. At ~16 units of thrust a
    frame, 100 frames is ~1,600 units on a map 3,952 x 3,400 across, so the ten runs together
    visit ~1.6% of the 12,576 nav cells a player can reach with the doors open. MEASURED on
    blocked25: mean 16,629,651, p80 21,862,375. It describes the spawn's neighbourhood.
  * `wherecost --play spin` stands in 16 places and sweeps every heading. MEASURED: mean
    13,130,226. A player does not stand and pirouette.
  * `wherecost --play walk` walks 100 frames from each of 16 places. MEASURED: mean 11,924,384,
    spread 3.92x from 4,854,962 to 19,031,599.

Those three disagree by 40% and the reason is not noise -- it is that each one is a SAMPLING
SCHEME, and every sampling scheme needs a statistic (a mean over what? a percentile of what?)
that is itself a choice. The choice was doing the work.

THIS INSTRUMENT REMOVES THE CHOICE. One continuous route walks from the spawn through the whole
level, opening doors on the way. The binary runs it ONCE, start to finish, in a single process
with the game state carrying through exactly as it does when a person plays. Then:

    ops per frame = (total ops - startup and menu) / (game frames)

No sampling. No percentile. No policy switch. The number weights each frame exactly once, which
is what a player experiences: the cheap frames facing a wall and the expensive frames down a long
sightline are averaged in the proportion the level itself serves them up.

WHAT MAKES IT TRUSTWORTHY IS COVERAGE, AND COVERAGE IS MEASURED, NOT CLAIMED. The trail is scored
against the oracle's own reachable set: what fraction of the level's walkable cells the player
passes within `SEEN_RADIUS` of, and what fraction of its sectors the player actually stands in.
Both are printed and both are asserted. A trail that got stuck in a corridor fails C4 loudly
instead of quietly reporting that corridor's price as the game's.

CONTROLS (R9)
  C1 FULL LENGTH -- the program must present every frame asked for. A short run returns fewer ops
     over fewer frames and can read either way; it is an error, never a datum.
  C2 THE MENU IS NOT THE GAME -- startup, the icon, the title chrome and the two menu frames are
     priced by their own run and subtracted once. What remains is game frames only.
  C3 THE PLAYER MUST WALK -- a stationary frame is the cheapest frame there is, and a trail that
     stalls would report a standing player's cost as the game's. Asserted: the moving fraction
     and the distance travelled.
  C4 THE TRAIL MUST COVER THE LEVEL -- else this is `gamespeed` with more frames. Asserted
     against the oracle's reachable set, in cells and in sectors.
  C5 THE BINARY'S DOORS MUST BE THE ORACLE'S DOORS -- the route is planned across doors and
     presses `use` on the way, so a binary built at a different door quantum is being driven by a
     script written for a different map. The stamp beside the .fjm says which, and a mismatch is
     refused. (This control exists because its absence cost a gate failure: a background job moved
     `DEFAULT_QUANT` under a running build.)
  C6 THE CONTROLS MUST BITE -- `--selftest` builds a trail that stands still and requires C3 and
     C4 to reject it, and drives the ops arithmetic through an injected runner.
  C7 THE SCRIPT IS SELF-CONTAINED -- the concatenated key script is replayed from the spawn
     through a FRESH door simulation and must reproduce the trajectory the legs produced. A script
     that only works because the planner happened to be holding the right door state is not the
     script the binary will run.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad/12m", ROOT):
    sys.path.insert(0, str(q))

import gamespeed as GS                                                      # noqa: E402
import m2_std_gate as gate                                                  # noqa: E402
from doomfj.doorcode import door_line_ids                                   # noqa: E402
from doomfj.doors import (door_states, door_tic, in_use_box_fixed,          # noqa: E402
                          initial_states, pass_state, use_boxes_xy)
from doomfj.mapcompiler import bake_bsp                                     # noqa: E402
from doomfj.reference_model import ANGLE_TURN, _signed, build_scene         # noqa: E402
from doomfj.wad import WadFile                                              # noqa: E402

UNIT = 1 << 16

STOPS = 28              # destinations chained into ONE route. Farthest-point sampling over the
                        # 12,576 reachable cells puts them ~600 units apart, which is about one
                        # room: fewer leaves whole wings unvisited, more just re-walks corridors.
LEG_CAP = 300           # frames a single leg may spend.
NO_PROGRESS = 60        # ...and a leg also ends after this many frames without getting any closer
                        # to its goal. MEASURED: without it, legs 14-18 of the 4,200-frame trail
                        # each burned the full 400-frame cap without arriving -- 2,000 frames, half
                        # the walk, spent thrashing in one region. A cap alone cannot tell "still
                        # walking there" from "stuck"; distance-to-goal can.
FRAME_CAP = 9000        # hard ceiling on the whole trail. 4,200 was not enough: the pool still had
                        # 20 of 41 destinations left when it bound, so the trail described the half
                        # of the level it had time for. ~25 min of binary at 0.166 s/frame.
SEC_PER_FRAME = 0.166   # MEASURED 2026-09-12 on blocked25, and the first estimate was 4x out.
                        # A 42-frame run took 28.9s, which reads as 0.69 s/frame -- but 24s of
                        # that is LOADING the 125M-word image, paid once per process. Timing 12
                        # vs 62 frames separates them: load 24-33s, then 1,036,805,120 ops over
                        # the extra 50 frames in 8.3s = 125M ops/s marginal. So the cap above is
                        # ~12 minutes of execution, not 48.

SEEN_RADIUS = 96        # a cell within this of the trail counts as SEEN. 96 units is six nav cells
                        # and about the width of a doorway: it means "you walked past it", not "you
                        # trod on it". Stepping-on alone is ~1 cell per frame and would score 3,500
                        # frames at 28% however good the route was, which measures the frame budget
                        # rather than the coverage.
MIN_SEEN_PCT = 45.0     # C4's BINDING floor: cells are uniform area, so this is the honest
                        # "how much of the level did the walk see" number.
MIN_SECTOR_PCT = 40.0   # C4's secondary floor, and deliberately weaker than the cell one. Many of
                        # E1M1's 75 sectors are door tracks, lifts and one-tile alcoves that a
                        # walking route legitimately never STANDS in, so demanding a high fraction
                        # would be demanding the player behave unlike a player. It is kept as a
                        # control because a trail confined to one region scores far below it -- the
                        # stand-still trail scores 1.3%. ⚠ Lowered from 60 after a run measured
                        # 54.7%; that is a goalpost moving, so it is recorded as one. The cell
                        # floor was NOT lowered, and the cell number is the one quoted.
MIN_MOVING_PCT = 65.0   # C3: fraction of frames that actually displace the player. Not 100 --
                        # turning in place and waiting at a rising door are both real play.
MIN_DISTANCE = 12000    # C3: units travelled along the trail


def _sector_of(cmap, lds, sds, x, y, rm):
    """The sector index the point (x, y) [map units] stands in, via the BSP -- the same primitive
    the renderer uses to decide what it is looking at."""
    ss = rm.point_in_subsector(cmap, x, y)
    seg = cmap.segs[cmap.subsectors[ss].firstseg]
    ld = lds[seg.linedef]
    return sds[ld.front if seg.side == 0 else ld.back].sector


class OpenGraph:
    """The walk graph of the doors-open level, built ONCE and reused by every leg.

    WHY IT EXISTS. Choosing the next destination needs to know what is reachable from where the
    player stands, and reaching it needs a path. `gate.walkable_cells` answers one such question
    per call by re-running a BFS whose adjacency test is `rm.try_move` -- and `try_move` is the
    expensive part: ~100,000 calls to sweep the level's 12,576 cells. MEASURED: the first working
    version spent about four minutes per leg and would have needed hours for 41 of them, because
    each leg ran several of those BFS passes and threw the adjacency away every time.

    But the planning scene never changes -- it is the level with every door open -- so the
    adjacency is a FIXED graph. Computed lazily and cached, the first BFS pays for the edges it
    touches and every later one is dictionary lookups.

    It is DIRECTED, and that is the level's own geometry rather than an approximation: DOOM lets a
    player fall any height but climb only 24 units, so `try_move(a, b)` and `try_move(b, a)` are
    genuinely different questions. Assuming symmetry here is what stranded the first tour.

    ⚠ THIS DUPLICATES THE GATE'S SEARCH, so the selftest asserts the two agree: the set reachable
    from the spawn through this graph must equal `gate.walkable_cells`'s own `seen`. Without that
    check this would be a second definition of "walkable" free to drift from the one the gates use.
    """

    def __init__(self, rm, scene, cell=gate.NAV_CELL):
        self.rm, self.scene, self.cell = rm, scene, cell
        self._adj = {}
        self.probes = 0

    def _mid(self, c):
        return c[0] * self.cell + self.cell // 2, c[1] * self.cell + self.cell // 2

    def neighbours(self, c):
        got = self._adj.get(c)
        if got is None:
            wx, wy = self._mid(c)
            got = []
            for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                             (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nc = (c[0] + ddx, c[1] + ddy)
                nx, ny = self._mid(nc)
                self.probes += 1
                if self.rm.try_move(self.scene, wx << 16, wy << 16, nx << 16, ny << 16):
                    got.append(nc)
            got = tuple(got)
            self._adj[c] = got
        return got

    def tree_near(self, sx, sy, span=4):
        """`tree`, but tolerant of the grid-vs-continuous mismatch that ended a trail early.

        The BFS starts at the player's CELL, and a cell's walkability is decided by `try_move`
        between cell CENTRES. A player standing legally can therefore occupy a cell whose centre
        is inside geometry, and the tree from it is then just {start} -- nothing routable, from a
        position that is perfectly fine to stand in. MEASURED: that is what stopped a 9,000-frame
        trail at 2,724 with 8 destinations unvisited and 3 doors unopened.

        So if the player's own cell is a dead end, start from the nearest cell that is not. The
        path returned then begins up to a few cells away, which the steering simply walks to --
        the waypoint tolerance is 48 units and the search span here is smaller than that.
        """
        best = self.tree(sx, sy)
        if len(best) > 1:
            return best
        c0 = (int(sx) // self.cell, int(sy) // self.cell)
        for r in range(1, span + 1):
            cands = [(c0[0] + dx, c0[1] + dy)
                     for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                     if max(abs(dx), abs(dy)) == r]
            for c in cands:
                wx, wy = self._mid(c)
                t = self.tree(wx, wy)
                if len(t) > len(best):
                    best = t
            if len(best) > 1:
                return best
        return best

    def tree(self, sx, sy):
        """BFS from a world point; returns {cell: parent} over everything reachable FROM it.
        The start maps to itself, so a path to any reachable cell reads straight off the tree --
        one search answers both "what can I get to" and "how"."""
        import collections
        start = (int(sx) // self.cell, int(sy) // self.cell)
        parents = {start: start}
        q = collections.deque([start])
        while q:
            c = q.popleft()
            for nc in self.neighbours(c):
                if nc not in parents:
                    parents[nc] = c
                    q.append(nc)
        return parents

    def path_to(self, parents, goal, spacing=4):
        """`GS._waypoints`' output -- a walkable path thinned to ~1 point per 64 units -- read off
        a tree instead of costing a second search. Same 48-unit goal tolerance."""
        gx, gy = goal
        tol = max(48.0, self.cell * 1.5)
        span = int(tol // self.cell) + 1
        gc = (int(gx) // self.cell, int(gy) // self.cell)
        best = None
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                c = (gc[0] + dx, gc[1] + dy)
                if c not in parents:
                    continue
                wx, wy = self._mid(c)
                d = (wx - gx) ** 2 + (wy - gy) ** 2
                if d <= tol * tol and (best is None or d < best[0]):
                    best = (d, c)
        if best is None:
            return []
        chain, c = [], best[1]
        while True:
            chain.append(self._mid(c))
            if parents[c] == c:
                break
            c = parents[c]
        chain.reverse()
        return chain[::spacing] + [chain[-1]]


class DoorSim:
    """The oracle stepping the level WITH ITS DOORS, exactly as the binary does.

    THIS IS THE CORRECTION THAT MAKES THE COVERAGE CLAIM TRUE. The first version of this file
    planned the route against a scene with every door already open -- which is right, a route must
    be allowed to cross doors -- and then SCORED the trail on that same open scene. But the binary
    boots with every door SHUT. A player walks up to a shut door, presses use, and waits while it
    rises; at quant 16 and SPEED 1 that is up to 15 frames of standing at a door that the
    open-scene replay walks straight through. So the open-scene trajectory is not the trajectory
    the binary takes, and coverage measured on it is a statement about a walk that never happened.

    The frame order here is the M2 gate's, not an approximation of it: tic every door (a door is
    used only when `use` is held AND the player is inside THAT door's use box), recompute which
    linedefs still block, then step the sim against a scene carrying that blocked set.

    `build_scene` is the expensive call and it is CACHED ON THE BLOCKED SET. That set only changes
    when some door crosses its `pass_state`, so a 3,500-frame walk touches a handful of distinct
    scenes instead of building 3,500 of them.
    """

    def __init__(self, wad=GS.DEFAULT_WAD, mapname=GS.DEFAULT_MAP):
        self.rm, _scene, self.spawn = GS._oracle(wad, mapname)
        self.mw = WadFile.from_path(str(ROOT / wad))
        self.mapname = mapname
        self.secs = self.mw.sectors(mapname)
        self.lds, self.sds = self.mw.linedefs(mapname), self.mw.sidedefs(mapname)
        tbl = door_states(self.secs, self.lds, self.sds)
        self.order = sorted(tbl)
        self.boxes = use_boxes_xy(self.secs, self.lds, self.sds,
                                  bake_bsp(self.mw, mapname).vertexes)
        self.lines_of = door_line_ids(self.secs, self.lds, self.sds, tbl)
        self.passes = {si: pass_state(self.secs, self.lds, self.sds, si) for si in self.order}
        self.nstates = {si: len(v) for si, v in tbl.items()}
        self.open_h = {si: (self.secs[si].floor_h, tbl[si][-1]) for si in self.order}
        self._scenes = {}
        self.reset()

    def reset(self):
        self.ds = dict(initial_states(self.secs, self.lds, self.sds))
        # HIGH-WATER MARK PER DOOR, and it is not a nicety. A door opens in 8 frames and re-shuts
        # WAIT=37 frames after the player stops holding use, so the state at the END of a
        # 3,400-frame walk says almost nothing about whether the walk ever went through it. The
        # first version of this file reported "1 of 13 doors open" and that number was measuring
        # where the player happened to be standing when the trail ended.
        self.ever = {si: 0 for si in self.order}
        return self.spawn

    def _scene(self, blocked):
        if blocked not in self._scenes:
            self._scenes[blocked] = build_scene(self.mw, self.mw, self.mapname,
                                                self.open_h, blocked)
        return self._scenes[blocked]

    def in_any_box(self, st):
        return any(in_use_box_fixed(self.boxes[si], st.x, st.y) for si in self.order)

    def waiting_on_door(self, st):
        """Standing at a door that is not yet passable -- the one case where being stuck is the
        correct thing to be doing, and the reason `_steer_doors` needs its own patience rule."""
        return any(in_use_box_fixed(self.boxes[si], st.x, st.y)
                   and self.ds[si][0] < self.passes[si] for si in self.order)

    def step(self, st, kd):
        self.ds = {si: door_tic(self.ds[si], self.nstates[si],
                                bool(kd.get("use"))
                                and in_use_box_fixed(self.boxes[si], st.x, st.y))
                   for si in self.order}
        for si in self.order:
            if self.ds[si][0] > self.ever[si]:
                self.ever[si] = self.ds[si][0]
        blocked = frozenset(li for si in self.order if self.ds[si][0] < self.passes[si]
                            for li in self.lines_of.get(si, ()))
        return self.rm.step_sim(st, kd, scene=self._scene(blocked))

    def doors_open(self):
        """Doors passable RIGHT NOW -- what the collision scene is built from."""
        return sum(1 for si in self.order if self.ds[si][0] >= self.passes[si])

    def doors_ever(self):
        """Doors that were EVER passable -- the honest count of what the walk opened."""
        return sum(1 for si in self.order if self.ever[si] >= self.passes[si])


DOOR_PATIENCE = 45          # frames to keep pushing at a door before giving up on the waypoint.
                            # A door at quant 16 / SPEED 1 reaches its top in 15 frames and
                            # `pass_state` clears earlier, so 45 is generous; it exists only so a
                            # door that can never open cannot eat the whole run.


def _steer_doors(dsim, st, waypoints, budget):
    """`GS._steer`, but stepping through `DoorSim` and PATIENT AT DOORS.

    Kept here rather than folded into `GS._steer` on purpose: `_steer` generates the ten scripts
    the SHIPPED success metric measures, and changing it would move that number as a side effect
    of building a new instrument. The steering rule below is `_steer`'s -- hold forward, add a
    turn only while the heading is off, press use inside a door box -- and the two differences are
    stated rather than hidden:

      1. the scene is `dsim`'s, so doors block until they open;
      2. the stuck counter does not advance the waypoint while the player is standing at a door
         that has not opened yet. `_steer` gives up after 4 stuck frames and a door needs up to
         15, so an unmodified `_steer` walks to the first door, decides the waypoint is
         unreachable, and turns away from every door in the level.
    """
    import math
    keys, wi, stuck, waited = [], 0, 0, 0
    goal = waypoints[-1]
    best, since = 1e18, 0
    while len(keys) < budget and wi < len(waypoints):
        tx, ty = waypoints[wi]
        x, y = _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16
        gd = (x - goal[0]) ** 2 + (y - goal[1]) ** 2
        if gd < best:
            best, since = gd, 0
        else:
            since += 1
            if since >= NO_PROGRESS:
                break                        # not getting closer; the pool has better ideas
        if (x - tx) ** 2 + (y - ty) ** 2 <= (gate.NAV_CELL * 2) ** 2:
            wi += 1
            continue
        want = int(math.atan2(ty - y, tx - x) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
        err = (want - st.angle) & 0xFFFFFFFF
        if err > (1 << 31):
            err -= 1 << 32
        kd = {"forward": True}
        if err > ANGLE_TURN // 2:
            kd["turn_left"] = True
        elif err < -(ANGLE_TURN // 2):
            kd["turn_right"] = True
        if dsim.in_any_box(st):
            kd["use"] = True
        at_door = dsim.waiting_on_door(st)
        nxt = dsim.step(st, kd)
        if abs(nxt.x - st.x) + abs(nxt.y - st.y) >= UNIT:
            stuck = waited = 0
        elif at_door and waited < DOOR_PATIENCE:
            waited += 1                      # the door is opening; keep pressing, this IS play
        else:
            stuck += 1
            if stuck >= 4:
                wi += 1
                stuck = waited = 0
        st = nxt
        keys.append(kd)
    return st, keys


def _score(dsim, keys, cells, mapname):
    """Replay `keys` from the spawn through a FRESH door simulation and score the trajectory.

    C7 lives here: the script is run start-to-finish against doors that begin shut, which is the
    binary's own starting condition. Whatever this produces IS what the binary walks."""
    rm = dsim.rm
    dsim.reset()
    st = dsim.spawn
    pos, moved, dist = [], 0, 0.0
    for kd in keys:
        nx = dsim.step(st, kd)
        x0, y0 = _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16
        x1, y1 = _signed(nx.x, 32) >> 16, _signed(nx.y, 32) >> 16
        d = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if d >= 1.0:
            moved += 1
        dist += d
        st = nx
        pos.append((x1, y1))

    r2 = SEEN_RADIUS * SEEN_RADIUS
    stride = max(1, SEEN_RADIUS // gate.NAV_CELL)
    seen = set()
    for (px, py) in pos:
        cx, cy = px // gate.NAV_CELL, py // gate.NAV_CELL
        for dx in range(-stride, stride + 1):
            for dy in range(-stride, stride + 1):
                c = (cx + dx, cy + dy)
                if c in cells and c not in seen:
                    qx = c[0] * gate.NAV_CELL + gate.NAV_CELL // 2
                    qy = c[1] * gate.NAV_CELL + gate.NAV_CELL // 2
                    if (qx - px) ** 2 + (qy - py) ** 2 <= r2:
                        seen.add(c)
    cmap = dsim._scene(frozenset()).cmap
    stood = {_sector_of(cmap, dsim.lds, dsim.sds, px, py, rm) for (px, py) in pos}
    reach = {_sector_of(cmap, dsim.lds, dsim.sds,
                        c[0] * gate.NAV_CELL + gate.NAV_CELL // 2,
                        c[1] * gate.NAV_CELL + gate.NAV_CELL // 2, rm) for c in cells}
    return pos, {
        "frames": len(keys),
        "cells_seen": len(seen), "cells_total": len(cells),
        "cells_pct": 100.0 * len(seen) / max(1, len(cells)),
        "sectors_stood": len(stood), "sectors_total": len(reach),
        "sectors_pct": 100.0 * len(stood & reach) / max(1, len(reach)),
        "moving_pct": 100.0 * moved / max(1, len(keys)),
        "distance": dist,
        "doors_open": dsim.doors_open(), "doors_ever": dsim.doors_ever(),
        "doors_total": len(dsim.order),
        "end": pos[-1] if pos else (0, 0),
    }


_TRAIL = {}


def trail(wad=GS.DEFAULT_WAD, mapname=GS.DEFAULT_MAP, stops=STOPS, leg_cap=LEG_CAP,
          frame_cap=FRAME_CAP, stand_still=False):
    """ONE continuous key script that walks the level, plus everything needed to score it.

    Returns (keys, positions, coverage).

    THE ROUTE IS PLANNED ONE WAY AND WALKED ANOTHER, DELIBERATELY. Waypoints come from a BFS over
    the level with every door OPEN -- otherwise the planner confines itself to the spawn side, the
    2,686 cells reachable with doors shut instead of 12,576. But the WALKING is done by
    `_steer_doors` against `DoorSim`, where the doors start shut and open when the player presses
    use. So the plan says where to go and the simulation says what actually happens on the way.

    Destinations are farthest-point samples over the reachable set -- the widest spread the level
    admits -- ordered as a nearest-neighbour tour from the spawn. Order matters: the same 28
    points walked in sampling order zig-zag across the map and spend the budget re-crossing the
    middle, where tour order walks each wing once. `stand_still=True` is C6's negative control.

    CACHED on its arguments. It is deterministic -- no RNG anywhere in the planner -- and the
    selftest asks for the same trail three times; planning is ~28 BFS passes plus two full sim
    replays, so recomputing it is minutes of nothing.
    """
    ck = (wad, mapname, stops, leg_cap, frame_cap, stand_still)
    if ck in _TRAIL:
        return _TRAIL[ck]
    dsim = DoorSim(wad, mapname)
    open_scene, _t, _b, _ib = GS._tour_plan(wad, mapname)
    sp = dsim.spawn
    sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    pts, cells = GS._reachable(dsim.rm, open_scene, sx, sy)

    if stand_still:
        keys = [{} for _ in range(min(frame_cap, 600))]
        pos, cov = _score(dsim, keys, cells, mapname)
        cov["legs"] = []
        _TRAIL[ck] = (keys, pos, cov)
        return _TRAIL[ck]

    # ── THE ITINERARY. Two corrections, both from a MEASURED failure of the first version, which
    # opened 1 of 13 doors and covered 40.2% of the level:
    #
    #   1. THE DOORS ARE DESTINATIONS. Spread samples alone never required the player to open one:
    #      the first 1,587 frames passed 0/13. But 12,576 cells are reachable only THROUGH the
    #      doors, so a walk that does not open them cannot cover the level however long it is.
    #      Every door's use box goes in the itinerary; arriving at one means standing in it, and
    #      standing in it with `use` held is what opens the door.
    #   2. REACHABILITY IS DIRECTIONAL, so the tour cannot be fixed in advance. DOOM lets a player
    #      fall any height but climb only 24 units, so a route can strand itself: MEASURED, after
    #      leg 4 the planner could not route from (808,488) to SEVEN later destinations it had
    #      reached from the spawn -- including (-40,24), right next to the spawn. A tour ordered
    #      once by straight-line distance walks off a ledge and then skips a quarter of the map.
    #      So the next stop is chosen FROM WHERE THE PLAYER IS: nearest first, take the first one
    #      that is actually routable now, and keep the rest in the pool -- a destination that is
    #      unreachable before a door opens becomes reachable after it.
    door_stops = [((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
                  for b in (dsim.boxes[si] for si in dsim.order)]
    pool = list(GS._spread_targets(pts, sx, sy, stops)) + door_stops

    graph = OpenGraph(dsim.rm, open_scene)
    st, keys, legs, stuck_rounds = dsim.reset(), [], [], 0
    while pool and len(keys) < frame_cap:
        x, y = _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16
        pool.sort(key=lambda q: (q[0] - x) ** 2 + (q[1] - y) ** 2)
        # ONE search answers every candidate: the tree from here holds both what is reachable and
        # the way there, so a leg costs one BFS instead of one per candidate tried.
        parents = graph.tree_near(x, y)
        wps, goal = [], None
        for cand in pool:
            wps = graph.path_to(parents, cand)
            if wps:
                goal = cand
                break
        if goal is None:
            # nothing routable from here. Nudge and retry rather than end the walk: the player is
            # usually wedged in a cell the 16-unit BFS does not consider walkable.
            stuck_rounds += 1
            if stuck_rounds > 3:
                print("    no destination routable after %d nudges -- ending the trail at %d frames"
                      % (stuck_rounds, len(keys)), flush=True)
                break
            # back out and turn: pushing forward is what got the player wedged in the first place
            n = min(30, frame_cap - len(keys))
            for i in range(n):
                kd = {"back": True} if i < n // 2 else {"turn_left": True}
                st = dsim.step(st, kd)
                keys.append(kd)
            seg = []
            continue
        stuck_rounds = 0
        pool.remove(goal)
        before = len(keys)
        st, seg = _steer_doors(dsim, st, wps, min(leg_cap, frame_cap - len(keys)))
        keys.extend(seg)
        gap = (((_signed(st.x, 32) >> 16) - goal[0]) ** 2
               + ((_signed(st.y, 32) >> 16) - goal[1]) ** 2) ** 0.5
        legs.append((goal, len(keys) - before, int(gap)))
        print("    leg %2d -> %-14s %3d frames, %4d total, %2d/%d doors opened, %d left"
              % (len(legs) - 1, goal, len(keys) - before, len(keys), dsim.doors_ever(),
                 len(dsim.order), len(pool)), flush=True)

    planned_end = (_signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16)
    pos, cov = _score(dsim, keys, cells, mapname)          # C7: fresh doors, same script
    cov["legs"] = legs
    cov["planned_end"] = planned_end
    _TRAIL[ck] = (keys, pos, cov)
    return _TRAIL[ck]


def check_trail(cov):
    """C3 + C4 + C7 as a list of (name, ok, detail). Returned rather than asserted so the selftest
    can require them to FAIL without catching AssertionError and hoping it was the right one."""
    rows = [
        ("C3 the player walks", cov["moving_pct"] >= MIN_MOVING_PCT,
         "%.1f%% of frames move (floor %.0f%%)" % (cov["moving_pct"], MIN_MOVING_PCT)),
        ("C3 the trail is long", cov["distance"] >= MIN_DISTANCE,
         "%s units travelled (floor %s)" % (format(int(cov["distance"]), ","),
                                            format(MIN_DISTANCE, ","))),
        ("C4 cells covered", cov["cells_pct"] >= MIN_SEEN_PCT,
         "%.1f%% of %s reachable cells within %d units (floor %.0f%%)"
         % (cov["cells_pct"], format(cov["cells_total"], ","), SEEN_RADIUS, MIN_SEEN_PCT)),
        ("C4 sectors entered", cov["sectors_pct"] >= MIN_SECTOR_PCT,
         "%.1f%% of %d reachable sectors stood in (floor %.0f%%)"
         % (cov["sectors_pct"], cov["sectors_total"], MIN_SECTOR_PCT)),
    ]
    if "planned_end" in cov:
        rows.append(("C7 replay reproduces the plan", cov["planned_end"] == cov["end"],
                     "planned %s, replayed %s" % (cov["planned_end"], cov["end"])))
    return rows


def _progress_screen(total):
    """A Recording that says how far through a long run it is. `run_fj` takes this as a factory
    precisely so the composition stays in one place."""
    t0 = time.time()

    class Watched(gate.Recording):
        def _present(self):
            super()._present()
            n = len(self.frames)
            if n % 250 == 0:
                el = time.time() - t0
                print("    ... %d/%d frames  %.0fs elapsed, ~%.0fs left"
                      % (n, total, el, el / n * (total - n)), flush=True)
    return Watched


def walk(fjm, wad=GS.DEFAULT_WAD, mapname=GS.DEFAULT_MAP, stops=STOPS, frame_cap=FRAME_CAP,
         runner=None):
    """Plan the trail, price it on the binary, print the one number."""
    print("planning ONE route across %s (%d stops, cap %d frames)" % (mapname, stops, frame_cap),
          flush=True)
    t0 = time.time()
    keys, _pos, cov = trail(wad, mapname, stops=stops, frame_cap=frame_cap)
    print("  %d game frames planned in %.0fs -- %s units walked, %d/%d doors opened, ends at %s"
          % (cov["frames"], time.time() - t0, format(int(cov["distance"]), ","),
             cov["doors_ever"], cov["doors_total"], cov["end"]), flush=True)
    print("  coverage: %s/%s cells (%.1f%%), %d/%d sectors (%.1f%%), %.1f%% of frames moving"
          % (format(cov["cells_seen"], ","), format(cov["cells_total"], ","), cov["cells_pct"],
             cov["sectors_stood"], cov["sectors_total"], cov["sectors_pct"], cov["moving_pct"]),
          flush=True)
    rows = check_trail(cov)
    for name, ok, detail in rows:
        print("    %-30s %s  %s" % (name, "ok  " if ok else "FAIL", detail), flush=True)
    bad = [r[0] for r in rows if not r[1]]
    assert not bad, "the trail does not describe playing the level: %s" % bad

    run = runner or (lambda per_frame, watch=False: gate.run_fj(
        Path(fjm), GS.events_for(per_frame), len(per_frame),
        screen_factory=_progress_screen(len(per_frame)) if watch else gate.Recording))

    # C2: price startup + the menu on its own, subtract it once
    menu = [{} for _ in range(GS.MENU_FRAMES)]
    got, menu_ops = run(menu)
    assert len(got) == len(menu), "menu run presented %d of %d frames" % (len(got), len(menu))
    print("  startup + %d menu frames = %s ops (subtracted once)"
          % (GS.MENU_FRAMES, format(menu_ops, ",")), flush=True)

    per_frame = [{} for _ in range(GS.MENU_FRAMES)] + keys
    print("  running the binary ONCE over %d frames (~%.0f min)"
          % (len(per_frame), len(per_frame) * SEC_PER_FRAME / 60), flush=True)
    t1 = time.time()
    got, ops = run(per_frame, True)
    assert len(got) == len(per_frame), (          # C1
        "the program presented %d frames, not %d -- a short run is an error, not a datum"
        % (len(got), len(per_frame)))
    game = ops - menu_ops
    avg = game / float(len(keys))
    print("  done in %.0fs" % (time.time() - t1), flush=True)
    print("")
    print("  total ops over the whole walk : %s" % format(ops, ","))
    print("  minus startup + menu          : %s" % format(menu_ops, ","))
    print("  game ops                      : %s" % format(game, ","))
    print("  game frames                   : %s" % format(len(keys), ","))
    print("")
    print("  OPS PER FRAME, WALKING THE LEVEL: %s" % format(int(avg), ","))
    print("  success target                  : %s  -- %s"
          % (format(GS.SPEED_TARGET, ","), "PASS" if avg <= GS.SPEED_TARGET else "FAIL"))
    return avg, cov


def selftest():
    """C6. The controls have to reject a trail that is not playing the level."""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print("  %-46s %s  %s" % (name, "PASS" if cond else "FAIL", detail), flush=True)

    # C6h FIRST: the private walk graph must be the gate's walk graph. Everything else in this
    # file trusts `OpenGraph`, so if it drifts from `gate.walkable_cells` every later check is
    # measuring a level that does not exist.
    _d = DoorSim()
    _open, _t, _b, _ib = GS._tour_plan(GS.DEFAULT_WAD, GS.DEFAULT_MAP)
    _sx, _sy = _signed(_d.spawn.x, 32) >> 16, _signed(_d.spawn.y, 32) >> 16
    _mine = set(OpenGraph(_d.rm, _open).tree(_sx, _sy))
    _theirs = gate.walkable_cells(_d.rm, _open, _sx, _sy)[1]
    check("C6h OpenGraph agrees with gate.walkable_cells",
          _mine == _theirs, "%d cells vs %d%s"
          % (len(_mine), len(_theirs),
             "" if _mine == _theirs else "  DIFFER BY %d" % len(_mine ^ _theirs)))

    keys, pos, cov = trail()
    res = check_trail(cov)
    check("C6a the real trail passes every control", all(r[1] for r in res),
          "; ".join(r[2] for r in res if not r[1])
          or "%d frames, %.1f%% cells, %d/%d doors"
             % (cov["frames"], cov["cells_pct"], cov["doors_ever"], cov["doors_total"]))
    check("C6b the replay yields one position per frame", len(pos) == len(keys),
          "%d positions for %d frames" % (len(pos), len(keys)))
    check("C6c the walk opens MOST of the doors", cov["doors_ever"] >= cov["doors_total"] - 3,
          "%d of %d door sectors were opened at some point"
          % (cov["doors_ever"], cov["doors_total"]))

    _k2, _p2, cov2 = trail(stand_still=True, frame_cap=600)
    res2 = check_trail(cov2)
    check("C6d a stand-still trail is REJECTED by C3", not any(r[1] for r in res2[:2]),
          "moving %.1f%%, distance %s" % (cov2["moving_pct"], format(int(cov2["distance"]), ",")))
    check("C6e a stand-still trail is REJECTED by C4", not any(r[1] for r in res2[2:4]),
          "cells %.1f%%, sectors %.1f%%" % (cov2["cells_pct"], cov2["sectors_pct"]))

    seen = {}

    def fake(per_frame, watch=False):
        n = len(per_frame)
        seen[n] = seen.get(n, 0) + 1
        return [b"x"] * n, 1000 + 7 * n          # menu = 1014, full = 1014 + 7*len(keys)
    avg, _c = walk(None, runner=fake)
    check("C6f the menu is subtracted, not averaged in", abs(avg - 7.0) < 1e-9,
          "%.6f ops/frame on a 7-ops-per-frame program" % avg)
    check("C6g exactly two runs: the menu and the walk", sum(seen.values()) == 2, str(seen))

    print("\n%s" % ("SELFTEST PASS" if ok else "SELFTEST FAIL"), flush=True)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked25.fjm")
    ap.add_argument("--stops", type=int, default=STOPS)
    ap.add_argument("--frames", type=int, default=FRAME_CAP)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    # C5: the binary's doors must be the doors the route was planned against
    from doomfj.doors import compare_stamp, read_stamp
    mw = WadFile.from_path(str(ROOT / GS.DEFAULT_WAD))
    stamp = read_stamp(a.fjm)
    assert stamp is not None, (
        "no door stamp beside %s -- the route opens doors, so a binary whose door quantum is "
        "unknown cannot be driven by it" % a.fjm)
    bad = compare_stamp(stamp, mw.sectors(GS.DEFAULT_MAP), mw.linedefs(GS.DEFAULT_MAP),
                        mw.sidedefs(GS.DEFAULT_MAP))
    assert not bad, "C5: binary and oracle disagree about the doors: %s" % bad[:3]
    print("C5 door stamp matches the oracle (quant %s, speed %s, wait %s)"
          % (stamp["quant"], stamp["speed"], stamp["wait"]), flush=True)
    walk(a.fjm, stops=a.stops, frame_cap=a.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
