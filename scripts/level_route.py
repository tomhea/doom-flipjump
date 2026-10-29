#!/usr/bin/env python
"""level_route.py -- a ROUTE from a map's player start to its EXIT, over the map's own geometry (M8, the episode plan
section 5): which keys to collect in order, which doors / switches / lifts / floors / teleports the path needs.

    python scripts/level_route.py --map E1M2 [--skill easy|medium|hard|all] [--out FILE.json] [--wad W]
    python scripts/level_route.py --map E1M3 --wad assets/freedoom1.wad     # a map with no fixture wad yet

THE MODEL IS THE AUTHORITY. Every rule comes from the model's own modules, so the route is the one the binary can walk:
  * collision: `ReferenceModel.check_position` (with the blockmap accelerator tests/host/test_collision.py proves
    equal to the exhaustive sweep) composed exactly as `ReferenceModel.try_move` composes it -- the opening >=
    PLAYER_HEIGHT, the step <= MAX_STEP from the floor being left; the solid things that never move (decor, barrels)
    refuse a cell by `World._solid_thing_at` at the skill played (m2_std_gate's `blocked`);
  * doors: `doors.DoorPhase` -- the door sectors, their kinds (`KIND_CARD`: the key a door needs), use boxes, the
    switch boxes that press them (S1 / SR), the W1 walk-over triggers (`doors.crossed`); a door is passable when OPEN,
    the scene `onewalk.DoorSim` builds (every door at its open height, the lines of a shut one BLOCKED);
  * movers: `movers.MoverPhase` -- the lifts (SR use boxes, WR lines) and the one-shot floor groups (S / W lines);
  * teleports: `teleport.teleporters` (WR 97: the FRONT side crossing, `crossed_front`, lands on the destination);
  * keys: the map's card / skull things the skill spawns, taken by `combat`'s touch rule (the 20 + 16 box, strict,
    and the REACH_UP / REACH_DOWN window from the floor stood on);
  * the exit: `doors.exit_boxes` (S1 exit 11, the use box) -- and, where the model has no rule yet, DOOM's: W1 exit 52
    and the secret exits 51 / 124 (a crossing / a use box), flagged `model: false`.

THE SEARCH. Grid cells of NAV_CELL units; an edge between neighbouring cell centres is a move the model accepts. A
flood in EPOCHS: the closure of what is reachable with the mechanisms active so far; every trigger the flood reaches
(a key, a use box, a switch, a walk-over line, a teleport) is recorded with the cell that reached it, and at the
epoch's end the triggered mechanisms activate (a door opens; a lift or a floor gets its other height, and a cell may
use EITHER -- a ride) and the flood resumes from the edges their geometry refused. The normal exit is preferred; a
secret exit is the fallback. The route is then the DEPENDENCY CLOSURE of the exit: the doors its path crosses, the
movers its path stands on (after they moved), and recursively what each of their triggers needed -- each key door
its key. Ordered by epoch, it becomes LEGS (a walk to each trigger to visit, then the exit), each with its own cell
path planned in the world as it is at that leg (`--out` writes them; scratchpad/gp/playthrough_gate.py steers them).

WHAT IT DOES NOT MODEL (said in the output, never silently): monsters (the steering fights them), door timing (a DR
door re-shuts after doors.WAIT frames: the steering re-opens it), lift timing (the steering rides), a W1 trigger the
path crosses on the way, and every line special the model does not have (listed per map under `unsupported`, and
marked on the route's mechanisms when the route uses a sector one of them moves).
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

NAV_CELL = 16
# the damaging floors (P_PlayerInSpecialSector: 5 / 7 / 16 / 4 / 11, the nukage and the slime) -- a leg's path pays
# HURT_COST cells for each cell on one (the flood's reachability does not care; the walk does: E1M3's NUKAGE1 pool
# by the blue card killed every early play that crossed it)
HURT_SPECIALS = frozenset({4, 5, 7, 11, 16})
HURT_COST = 12
KEY_TYPES = {5: "blue", 40: "blue", 6: "yellow", 39: "yellow", 13: "red", 38: "red"}
# DOOM's exits (p_spec.c): (trigger, which) -- the normal ones are preferred
EXIT_KINDS = {11: ("S", "normal"), 52: ("W", "normal"), 51: ("S", "secret"), 124: ("W", "secret")}
SKILLS = ("easy", "medium", "hard")
STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
# DOOM line specials (p_spec.c), used only to NAME a special the model lacks
DOOM_KINDS = {
    **{s: "door" for s in (1, 2, 3, 4, 16, 26, 27, 28, 29, 31, 32, 33, 34, 42, 46, 50, 61, 63, 75, 76, 86, 90, 99,
                           103, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 133, 134,
                           135, 136, 137)},
    **{s: "lift" for s in (10, 14, 15, 20, 21, 22, 47, 53, 62, 66, 67, 68, 87, 88, 95, 120, 121, 122, 123)},
    **{s: "floor" for s in (5, 9, 18, 19, 23, 24, 30, 36, 37, 38, 55, 56, 58, 59, 60, 64, 65, 69, 70, 71, 82, 83,
                            84, 91, 92, 93, 94, 96, 98, 101, 102, 119, 128, 129, 130, 131, 132, 140)},
    **{s: "stairs" for s in (7, 8, 100, 127)},
    **{s: "teleport" for s in (39, 97, 125, 126)},
    **{s: "exit" for s in (11, 51, 52, 124)},
    **{s: "ceiling/crusher" for s in (6, 25, 40, 41, 43, 44, 49, 57, 72, 73, 74, 77, 141)},
    **{s: "light" for s in (12, 13, 17, 35, 79, 80, 81, 104, 138, 139)},
    48: "scroll",
}


def model_specials() -> dict:
    """{special: what the model does with it}, read from the model's own tables -- a special the model learns leaves
    `unsupported` with no edit here"""
    from doomfj import doors as D
    from doomfj import movers as MV
    out = {}
    for s, k in D.MANUAL_DOOR_KINDS.items():
        out[s] = "door (manual, %s)" % k
    for s in D.WALK_DOOR_KINDS:
        out[s] = "door (walk-over)"
    for s in D.SWITCH_DOOR_KINDS:
        out[s] = "door (switch)"
    for s in MV.LIFT_WALK_SPECIALS | MV.LIFT_USE_SPECIALS:
        out[s] = "lift"
    for s in MV.FLOOR_SPECIALS:
        out[s] = "floor"
    for s in D.EXIT_SPECIALS | D.WALK_EXIT_SPECIALS:      # M8 C9: the W1 exit (52) is in the model too
        out[s] = "exit"
    try:
        from doomfj.teleport import TELEPORT_SPECIALS
        for s in TELEPORT_SPECIALS:
            out[s] = "teleport"
    except ImportError:
        pass
    try:                                     # what moves nothing a route needs: the scrolling wall, the lights
        from doomfj import world as W
        for name in dir(W):
            if name.endswith("_SPECIALS") and ("SCROLL" in name or "LIGHT" in name):
                for s in getattr(W, name):
                    if isinstance(s, int):
                        out.setdefault(s, name.lower())
    except ImportError:
        pass
    return out


def _xy(v):
    return (v.x, v.y) if hasattr(v, "x") else (v[0], v[1])


def centre(cell):
    return (cell[0] * NAV_CELL + NAV_CELL // 2, cell[1] * NAV_CELL + NAV_CELL // 2)


def cell_of(x, y):
    return (int(x) // NAV_CELL, int(y) // NAV_CELL)


def touch_candidates(x, y, kx, ky):
    """positions within half a cell of (x, y), stepped toward (kx, ky), the least moved first"""
    sx = 1 if kx > x else -1
    sy = 1 if ky > y else -1
    out = [(x + sx * i, y + sy * j) for i in (0, 4, 8, 12) for j in (0, 4, 8, 12)]
    return sorted(out, key=lambda p: (abs(p[0] - x) + abs(p[1] - y), p))


def seg_cross(p, q, a, b) -> bool:
    """do the segments p-q and a-b properly intersect (m2_std_gate.seg_cross's rule)"""
    def cross(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    d1, d2 = cross(a, b, p), cross(a, b, q)
    d3, d4 = cross(p, q, a), cross(p, q, b)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


class Level:
    """one map at one skill, as the model sees it. Each model piece is built in its own try: a refusal is RECORDED
    (`refusals`) and the planner goes on without that piece, so one missing feature does not hide the next"""

    def __init__(self, mapname: str, wad: str | None = None, skill: str = "easy"):
        from doomfj import gamedata as gd
        from doomfj.config import Config
        from doomfj.mapcompiler import bake_bsp, build_blockmap
        from doomfj.reference_model import ReferenceModel, spawn_state
        from doomfj.wad import WadFile
        self.map = mapname.upper()
        if wad is None:
            from doomfj.mapprofile import profile
            wad = profile(self.map).wad
            if not (ROOT / wad).exists():
                wad = "assets/freedoom1.wad"
        self.wad = wad
        self.skill = skill
        self.sk = gd.SKILL_NAMES[skill]
        self.refusals, self.notes = [], []
        self.mw = WadFile.from_path(str(ROOT / wad))
        self.rm = ReferenceModel(Config())
        m = self.map
        self.secs, self.lds, self.sds = self.mw.sectors(m), self.mw.linedefs(m), self.mw.sidedefs(m)
        self.verts = self.mw.vertexes(m)
        self.cmap = bake_bsp(self.mw, m)
        self.grid = build_blockmap(self.cmap, self.lds)
        self._sec_ids = list(range(len(self.secs)))
        sp = spawn_state(self.mw, m)
        self.start = (sp.x >> 16, sp.y >> 16, sp.angle)
        bit = gd.skill_bit(self.sk)
        self.things = [t for t in self.mw.things(m) if (t.flags & bit) and not (t.flags & 16)]
        self.keys = [(KEY_TYPES[t.type], t.x, t.y, t.type) for t in self.things if t.type in KEY_TYPES]
        self._doors()
        self._movers()
        self._teleports()
        self._exits()
        self._solid()
        known = model_specials()
        self.unsupported = {}
        for li, ld in enumerate(self.lds):
            if ld.special and ld.special not in known:
                self.unsupported.setdefault(ld.special, []).append(li)

    def _try(self, what, fn):
        try:
            return fn()
        except Exception as e:                                   # noqa: BLE001 -- recorded and reported
            self.refusals.append({"piece": what, "error": "%s: %s" % (type(e).__name__, str(e)[:300])})
            return None

    def _doors(self):
        from doomfj.doorcode import door_line_ids
        from doomfj.doors import DoorPhase, door_states, use_boxes_xy
        self.dp, self.door_order, self.open_h, self.lines_of = None, [], {}, {}

        def build():
            tbl = door_states(self.secs, self.lds, self.sds)
            boxes = use_boxes_xy(self.secs, self.lds, self.sds, self.cmap.vertexes)
            return tbl, DoorPhase(self.secs, self.lds, self.sds, self.verts, boxes)
        got = self._try("doors (doors.DoorPhase)", build)
        if got is None:
            return
        tbl, self.dp = got
        self.door_order = sorted(tbl)
        self.open_h = {si: (self.secs[si].floor_h, tbl[si][-1]) for si in self.door_order}
        self.lines_of = {si: list(v) for si, v in door_line_ids(self.secs, self.lds, self.sds, tbl).items()}

    def _movers(self):
        from doomfj.movers import MoverPhase
        self.mp = self._try("movers (movers.MoverPhase)", lambda: MoverPhase(self.secs, self.lds, self.sds, self.verts))

    def _teleports(self):
        from doomfj.teleport import teleporters
        self.tels = self._try("teleports (teleport.teleporters)",
                              lambda: teleporters(self.mw, self.map, rm=self.rm, cmap=self.cmap)) or []

    def _exits(self):
        from doomfj.doors import EXIT_SPECIALS, USE_RANGE, WALK_EXIT_SPECIALS
        self.exits = []
        for li, ld in enumerate(self.lds):
            if ld.special not in EXIT_KINDS:
                continue
            trig, which = EXIT_KINDS[ld.special]
            a, b = _xy(self.cmap.vertexes[ld.v1]), _xy(self.cmap.vertexes[ld.v2])
            box = (min(a[0], b[0]) - USE_RANGE, min(a[1], b[1]) - USE_RANGE,
                   max(a[0], b[0]) + USE_RANGE, max(a[1], b[1]) + USE_RANGE)
            self.exits.append({"line": li, "special": ld.special, "trigger": trig, "which": which,
                               "box": box if trig == "S" else None, "seg": (a, b),
                               "model": ld.special in EXIT_SPECIALS | WALK_EXIT_SPECIALS})
        mod = [e for e in self.exits if e["model"] and e["trigger"] == "S"]   # (a W1 exit has no box: it is crossed)
        if mod:                     # the model's own boxes (doors.exit_boxes, linedef order): the binary's, to the unit
            from doomfj.doors import exit_boxes
            boxes = self._try("exits (doors.exit_boxes)", lambda: exit_boxes(self.lds, self.cmap.vertexes))
            if boxes is not None and len(boxes) == len(mod):
                for e, bx in zip(mod, boxes):
                    e["box"] = tuple(bx)

    def _solid(self):
        """the model's solid-thing refusal for the things that never move (decor, barrels), at this skill"""
        def build():
            from doomfj.monsters import MonsterPhase
            from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
            w = MonsterPhase(self.mw, self.map, self.sk, rm=self.rm, mode=MONSTER_MODE, player=PLAYER_MODE).world

            def solid(x, y):
                hit = w._solid_thing_at(int(x) << 16, int(y) << 16)
                return hit is not None and hit[0] != "mon"
            return solid
        self.solid = self._try("solid things (monsters.MonsterPhase / World._solid_thing_at)", build)
        if self.solid is None:
            self.notes.append("solid decor / barrels NOT modelled (the world refused): the steering must go round")

    def sector_at(self, x: int, y: int) -> int:
        from doomfj.mapcompiler import seg_sector
        ss = self.cmap.subsectors[self.rm.point_in_subsector(self.cmap, x, y)]
        return seg_sector(self.lds, self.sds, self._sec_ids, self.cmap.segs[ss.firstseg])

    def sector_bbox(self, si: int):
        xs, ys = [], []
        for ld in self.lds:
            for side in (ld.front, ld.back):
                if side not in (-1, 0xFFFF) and side < len(self.sds) and self.sds[side].sector == si:
                    for v in (ld.v1, ld.v2):
                        x, y = _xy(self.cmap.vertexes[v])
                        xs.append(x)
                        ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None


class Mech:
    """one thing that changes where the player can go: a door, a lift, a floor group -- or a key (it enables doors)"""

    def __init__(self, mid: str, kind: str, sectors=(), key=None, detail=""):
        self.id, self.kind, self.sectors, self.key, self.detail = mid, kind, tuple(sectors), key, detail
        self.need_key = None            # a mixed-card door (doors.keyed_boxes_xy) opened through a KEYED box: its card
        self.epoch = None               # activated at the END of this epoch
        self.cell = None                # the cell that reached its trigger
        self.trigger = None             # "use" / "switch" / "walk" / "touch"
        self.pos = None                 # a key: the thing's position


class Planner:
    def __init__(self, lv: Level):
        from doomfj.doors import KIND_CARD
        self.lv = lv
        self.mechs = {}
        self._cp, self._scenes, self._sec, self._solid, self._hurt = {}, {}, {}, {}, {}
        for si in lv.door_order:
            kind = lv.dp.kinds[si]
            self.mechs["door:%d" % si] = Mech("door:%d" % si, "door", [si], key=KIND_CARD.get(kind), detail=kind)
        if lv.mp is not None:
            for si in lv.mp.order:
                self.mechs["lift:%d" % si] = Mech("lift:%d" % si, "lift", [si])
            for g, grp in enumerate(lv.mp.groups):
                self.mechs["floor:%d" % g] = Mech("floor:%d" % g, "floor", grp.sectors)
        self.keyspots = {}
        for col, x, y, typ in lv.keys:
            self.keyspots.setdefault(col, []).append((x, y))
            mid = "key:%s" % col
            if mid not in self.mechs:
                m = self.mechs[mid] = Mech(mid, "key", key=col, detail="thing %d at (%d, %d)" % (typ, x, y))
                m.pos = (x, y)

    # ---- scenes and the move test ------------------------------------------------------------------------------
    def _scene(self, active: frozenset, low: bool):
        """the collision scene: the ACTIVE doors' lines unblocked (every door at its open height: DoorSim's
        construction); `low` -- the active lifts and floor groups at their LAST state"""
        lv = self.lv
        movers = frozenset(a for a in active if a.startswith(("lift:", "floor:"))) if low else frozenset()
        key = (frozenset(a for a in active if a.startswith("door:")), movers)
        if key not in self._scenes:
            from doomfj.reference_model import build_scene
            blocked = frozenset(li for si in lv.door_order if "door:%d" % si not in active
                                for li in lv.lines_of.get(si, ()))
            h = dict(lv.open_h)
            if movers:
                mp = lv.mp
                lifts = tuple((len(mp.stops[si]) - 1 if "lift:%d" % si in movers else 0, 0, 0, 0) for si in mp.order)
                fs = [((grp.n - 1) if "floor:%d" % g in movers else 0, 0) for g, grp in enumerate(mp.groups)]
                h.update(mp.heights((lifts, frozenset(), mp._sw(fs))))
            self._scenes[key] = (len(self._scenes), build_scene(lv.mw, lv.mw, lv.map, h, blocked))
        return self._scenes[key]

    def scenes_for(self, active):
        hi = self._scene(frozenset(active), False)
        if any(a.startswith(("lift:", "floor:")) for a in active):
            return (hi, self._scene(frozenset(active), True))
        return (hi,)

    def cp(self, scene, cell):
        sid, sc = scene
        r = self._cp.get((sid, cell))
        if r is None:
            x, y = centre(cell)
            r = self._cp[(sid, cell)] = self.lv.rm.check_position(sc, x << 16, y << 16, blockmap=self.lv.grid)
        return r

    def move_ok(self, scene, a, b) -> bool:
        """ReferenceModel.try_move from cell a's centre to cell b's, composed from check_position as it composes it"""
        from doomfj.reference_model import MAX_STEP, PLAYER_HEIGHT
        ok, fz, cz = self.cp(scene, b)
        if not ok or (cz - fz) << 16 < PLAYER_HEIGHT:
            return False
        return not ((fz - self.cp(scene, a)[1]) << 16 > MAX_STEP)

    def pos_ok(self, scene, a, b) -> bool:
        """try_move between two map-unit POSITIONS (uncached: the touch tests' rare off-centre moves)"""
        from doomfj.reference_model import MAX_STEP, PLAYER_HEIGHT
        rm, sc, g = self.lv.rm, scene[1], self.lv.grid
        ok, fz, cz = rm.check_position(sc, b[0] << 16, b[1] << 16, blockmap=g)
        if not ok or (cz - fz) << 16 < PLAYER_HEIGHT:
            return False
        return not ((fz - rm.check_position(sc, a[0] << 16, a[1] << 16, blockmap=g)[1]) << 16 > MAX_STEP)

    def edge_ok(self, scenes, a, b) -> bool:
        return not self.solid_at(b) and any(self.move_ok(s, a, b) for s in scenes)

    def solid_at(self, cell) -> bool:
        if self.lv.solid is None:
            return False
        r = self._solid.get(cell)
        if r is None:
            r = self._solid[cell] = bool(self.lv.solid(*centre(cell)))
        return r

    def sector_of(self, cell) -> int:
        r = self._sec.get(cell)
        if r is None:
            r = self._sec[cell] = self.lv.sector_at(*centre(cell))
        return r

    def hurts(self, cell) -> bool:
        r = self._hurt.get(cell)
        if r is None:
            r = self._hurt[cell] = self.lv.secs[self.sector_of(cell)].special in HURT_SPECIALS
        return r

    def floor_at(self, scenes, cell) -> int:
        return min(self.cp(s, cell)[1] for s in scenes)

    # ---- triggers ------------------------------------------------------------------------------------------------
    def cell_triggers(self, cell, scenes):
        """[(mech id or exit index, kind)] the cell centre reaches: use boxes, switch boxes, keys, use exits"""
        from doomfj.combat import ITEM_RADIUS, PLAYER_R, REACH_DOWN, REACH_UP
        from doomfj.doors import in_use_box
        lv = self.lv
        x, y = centre(cell)
        out = []
        for si in lv.door_order:
            box = lv.dp.boxes.get(si)
            if box is not None and in_use_box(box, x, y):
                out.append(("door:%d" % si, "use", tuple(box)))
            for b in lv.dp.switches.get(si, ()):
                if in_use_box(b, x, y):
                    out.append(("door:%d" % si, "switch", tuple(b)))
            # a mixed-card door's KEYED front boxes (E1M3 150: D1 31 west, D1 32 BLUE east), each with its card --
            # the model's own (DoorPhase.keyed, the box the press is tested in after the door's own box misses)
            for b, card in getattr(lv.dp, "keyed", {}).get(si, ()):
                if in_use_box(b, x, y):
                    out.append(("door:%d" % si, "use", tuple(b), card))
        if lv.mp is not None:
            for tag, box in lv.mp.use:
                if in_use_box(box, x, y):
                    out += [("lift:%d" % si, "use", tuple(box)) for si in lv.mp.lifts_of_tag[tag]]
            for g, box in lv.mp.floor_use:
                if in_use_box(box, x, y):
                    out.append(("floor:%d" % g, "use", tuple(box)))
        bd = ITEM_RADIUS + PLAYER_R
        for col, spots in self.keyspots.items():
            for kx, ky in spots:
                if abs(kx - x) >= bd + NAV_CELL or abs(ky - y) >= bd + NAV_CELL:
                    continue
                # the touch is the model's at a POSITION, not at a cell centre: a key on a ledge the player cannot
                # climb is taken from below, within 36 units of it (E1M2's red card, 32 units up its alcove) -- so the
                # positions a cell's player can step to toward the key, the nearest first, each a move the model takes
                kz = self.floor_at(scenes, cell_of(kx, ky))
                for px, py in touch_candidates(x, y, kx, ky):
                    if abs(kx - px) >= bd or abs(ky - py) >= bd:
                        continue
                    ok = [s for s in scenes if self.pos_ok(s, (x, y), (px, py))]
                    if ok and -REACH_DOWN <= kz - min(self.lv.rm.check_position(
                            s[1], px << 16, py << 16, blockmap=self.lv.grid)[1] for s in ok) <= REACH_UP:
                        out.append(("key:%s" % col, "touch", (px, py)))
                        break
        for i, e in enumerate(lv.exits):
            if e["box"] is not None and in_use_box(e["box"], x, y):
                out.append((i, "exit"))
        return out

    def edge_triggers(self, a, b):
        """[(mech id / exit index / teleporter, kind)] the move a -> b crosses"""
        from doomfj.doors import crossed
        from doomfj.teleport import crossed_front
        lv = self.lv
        a16 = tuple(v << 16 for v in centre(a))
        b16 = tuple(v << 16 for v in centre(b))
        out = []
        if lv.dp is not None:
            out += [("door:%d" % t[0], "walk") for t in lv.dp.triggers if crossed(t, a16, b16, 16)]
        if lv.mp is not None:
            from doomfj.movers import crossed_shape
            out += [("lift:%d" % t[0], "walk") for t in lv.mp.walk if crossed(t, a16, b16, 16)]
            out += [("floor:%d" % g, "walk") for g, shape in lv.mp.floor_walk if crossed_shape(shape, a16, b16, 16)]
        out += [(tel, "teleport") for tel in lv.tels if crossed_front(tel, a16, b16, 16)]
        out += [(i, "exit") for i, e in enumerate(lv.exits)
                if e["trigger"] == "W" and seg_cross(centre(a), centre(b), *e["seg"])]
        return out

    # ---- the flood ---------------------------------------------------------------------------------------------
    def flood(self, budget_s: float = 900.0):
        """-> (exit index or None, why). Fills self.visit {cell: (parent, epoch, via, order)}"""
        lv = self.lv
        t0 = time.time()
        start = cell_of(lv.start[0], lv.start[1])
        self.start_cell = start
        self.visit = {start: (None, 0, None, 0)}
        self.active, self.keys = set(), set()
        self.exit_hits = {}                       # exit index -> cell
        self.pending_key = {}                     # key door id -> (the cell that reached its box without the key, card)
        self.touch_at = {}                        # key id -> the position the touch was found at (map units)
        self.use_box = {}                         # mech id -> the box its use press was found in (map units)
        failed = collections.defaultdict(list)    # unvisited cell -> [cells an edge from was refused]
        q = collections.deque([start])
        epoch, order, found = 0, 1, {}            # found: mech id -> (cell, kind)
        scenes = self.scenes_for(())
        for trig in self.cell_triggers(start, scenes):
            self._note(trig, start, found)
        while True:
            while q:
                a = q.popleft()
                for dx, dy in STEPS:
                    b = (a[0] + dx, a[1] + dy)
                    if b in self.visit:
                        continue
                    if not self.edge_ok(scenes, a, b):
                        failed[b].append(a)
                        continue
                    tele = None
                    for trig in self.edge_triggers(a, b):
                        if trig[1] == "teleport":
                            tele = trig[0]
                        else:
                            self._note(trig, b, found)
                    if tele is not None:          # the move lands on the destination, not on b
                        b = cell_of(*tele.dest)
                        if b in self.visit:
                            continue
                        self.visit[b] = (a, epoch, "teleport:%d" % tele.line, order)
                    else:
                        self.visit[b] = (a, epoch, None, order)
                    order += 1
                    failed.pop(b, None)
                    q.append(b)
                    for trig in self.cell_triggers(b, scenes):
                        self._note(trig, b, found)
                if time.time() - t0 > budget_s:
                    return None, "the time budget (%d s) ran out at epoch %d, %d cells" % (budget_s, epoch,
                                                                                            len(self.visit))
            normal = [i for i in self.exit_hits if lv.exits[i]["which"] == "normal"]
            if normal:
                return min(normal, key=lambda i: self.visit[self.exit_hits[i]][3]), None
            # the epoch's end: what it triggered activates -- keys first (a key door whose box was reached opens)
            new = []
            for mid, (cell, kind) in sorted(found.items(), key=lambda kv: self.visit[kv[1][0]][3]):
                m = self.mechs[mid]
                if m.kind == "key" and m.epoch is None:
                    self.keys.add(m.key)
                    m.epoch, m.cell, m.trigger = epoch, cell, kind
                    new.append(m)
            for did, (cell, card) in self.pending_key.items():
                if card in self.keys and did not in found and self.mechs[did].epoch is None:
                    found[did] = (cell, "use")
                    if card != self.mechs[did].key:       # a keyed box of a mixed door: the card is its dependency
                        self.mechs[did].need_key = card
            for mid, (cell, kind) in sorted(found.items(), key=lambda kv: self.visit[kv[1][0]][3]):
                m = self.mechs[mid]
                if m.kind == "key" or m.epoch is not None:
                    continue
                m.epoch, m.cell, m.trigger = epoch, cell, kind
                self.active.add(mid)
                new.append(m)
            if not new:
                if self.exit_hits:                 # only a secret exit was reached: take it
                    return (min(self.exit_hits, key=lambda i: self.visit[self.exit_hits[i]][3]),
                            "no normal exit reachable -- the route takes the SECRET exit")
                return None, "the flood closed at epoch %d (%d cells) with no exit reached" % (epoch, len(self.visit))
            epoch += 1
            scenes = self.scenes_for(self.active)
            boxes = [b for b in (lv.sector_bbox(si) for m in new for si in m.sectors) if b is not None]
            for b in sorted(failed, key=lambda c: min(self.visit[a][3] for a in failed[c])):
                x, y = centre(b)
                if b in self.visit or not any(x0 - 48 <= x <= x1 + 48 and y0 - 48 <= y <= y1 + 48
                                              for x0, y0, x1, y1 in boxes):
                    continue
                for a in failed[b]:
                    if self.edge_ok(scenes, a, b):
                        q.append(a)               # re-expand a in the new world (b and a's other refused edges)
                        break

    def _note(self, trig, cell, found):
        mid, kind = trig[:2]
        card = trig[3] if len(trig) > 3 else None
        if len(trig) > 2:                         # a key's touch point, or the use box a press is made in
            (self.touch_at if kind == "touch" else self.use_box).setdefault(mid, trig[2])
        if kind == "exit":
            self.exit_hits.setdefault(mid, cell)
            return
        m = self.mechs.get(mid)
        if m is None or m.epoch is not None:
            return
        need = card or (m.key if m.kind == "door" and kind == "use" else None)
        if need and need not in self.keys:
            self.pending_key.setdefault(mid, (cell, need))
            return
        found.setdefault(mid, (cell, kind))

    # ---- the route ---------------------------------------------------------------------------------------------
    def path_to(self, cell) -> list:
        out = []
        while cell is not None:
            out.append(cell)
            cell = self.visit[cell][0]
        return out[::-1]

    def door_segs(self, mid):
        lv = self.lv
        return [(_xy(lv.cmap.vertexes[lv.lds[li].v1]), _xy(lv.cmap.vertexes[lv.lds[li].v2]))
                for li in lv.lines_of.get(self.mechs[mid].sectors[0], ())]

    def needs_of_path(self, path) -> set:
        """the mechanisms a path depends on: the doors whose lines an edge crosses (or whose sector a cell stands
        in), the movers whose sector a cell stands in after they moved"""
        need = set()
        segs = {mid: self.door_segs(mid) for mid in self.active if self.mechs[mid].kind == "door"}
        for i, c in enumerate(path):
            e, sec = self.visit[c][1], self.sector_of(c)
            for mid in self.active:
                m = self.mechs[mid]
                if sec in m.sectors and m.epoch < e:
                    need.add(mid)
            if i and not self.visit[c][2]:        # (a teleport edge crosses nothing)
                p = path[i - 1]
                for mid, ss in segs.items():
                    if mid not in need and any(seg_cross(centre(p), centre(c), a, b) for a, b in ss):
                        need.add(mid)
        return need

    def route(self, exit_i):
        """the exit's dependency closure, in activation order -> (mechanism ids, the exit's cell)"""
        ecell = self.exit_hits[exit_i]
        need, todo, done = set(), [ecell], set()

        def add(mid):
            if mid in need:
                return
            need.add(mid)
            m = self.mechs[mid]
            todo.append(m.cell)
            if (m.key or m.need_key) and m.kind != "key":    # a key door: its key
                k = self.mechs.get("key:%s" % (m.key or m.need_key))
                if k is not None and k.epoch is not None:
                    add(k.id)
            if m.kind == "key":
                # the key's own floor: a mover that moved the sector it lies on before it was taken (E1M2's blue card
                # on sector 45, lowered by the S1 switch 34) is the key's dependency too
                ks = self.lv.sector_at(*m.pos)
                for oid in sorted(self.active):
                    o = self.mechs[oid]
                    if o.kind in ("lift", "floor") and ks in o.sectors and o.epoch < m.epoch:
                        add(oid)
        while todo:
            c = todo.pop()
            if c in done:
                continue
            done.add(c)
            for mid in sorted(self.needs_of_path(self.path_to(c))):
                add(mid)
        order = sorted(need, key=lambda mid: (self.mechs[mid].epoch, self.visit[self.mechs[mid].cell][3]))
        return order, ecell

    def leg_path(self, frm, goal_pred, active):
        """the cheapest walk from cell `frm` to the first cell with `goal_pred(cell)`, in the world with `active` ->
        [cells, with ("teleport", line) between the two cells of a teleport], or None. A step costs 1, a step onto a
        damaging floor 1 + HURT_COST (Dijkstra; with no such floor on the way, a BFS's shortest path)"""
        import heapq
        scenes = self.scenes_for(active)
        prev = {frm: None}
        dist = {frm: 0}
        q = [(0, 0, frm)]
        n = 1
        done = set()
        while q:
            d, _o, a = heapq.heappop(q)
            if a in done:
                continue
            done.add(a)
            if goal_pred(a):
                out = []
                while a is not None:
                    out.append(a)
                    p = prev[a]
                    if p is not None and len(p) == 3:
                        out.append(("teleport", p[2]))
                        p = p[0]
                    a = p
                return out[::-1]
            for dx, dy in STEPS:
                b = (a[0] + dx, a[1] + dy)
                if b in done or not self.edge_ok(scenes, a, b):
                    continue
                tele = next((t[0] for t in self.edge_triggers(a, b) if t[1] == "teleport"), None)
                if tele is not None:
                    b = cell_of(*tele.dest)
                    link = (a, "tele", tele.line)
                else:
                    link = a
                nd = d + 1 + (HURT_COST if self.hurts(b) else 0)
                if b not in dist or nd < dist[b]:
                    dist[b] = nd
                    prev[b] = link
                    heapq.heappush(q, (nd, n, b))
                    n += 1
        return None


# PICKUPS ON THE WAY (the steering's survival, not the route's logic): an item the model gives, reachable in the world
# of a leg, is taken first when the detour costs at most its budget in cells -- the weapons most, then armor and the
# soulsphere, then ammo boxes a little (health is the steering's to seek, when it runs low)
# Within its budget the NEAREST pickup is taken first (PICKUP_ORDER "nearest"; "cheapest" -- the smallest detour first --
# is the old order, kept for the host test's control: on E1M5 it walks past the shotgun 24 cells from the start)
PICKUP_ORDER = "nearest"
# a pickup the steering never drops for taking too long (its detour watchdog): the radiation suit -- the nukage channel
# after it is crossed whether it was taken or not (E1M4: a suit detour dropped after 471 frames, the crossing at 25
# health killed the play)
MUST_PICKUPS = frozenset({2025})
PICKUP_BUDGET = {2001: 150, 2002: 150, 2018: 50, 2019: 50, 2013: 50, 8: 40, 2049: 14, 2048: 10, 2008: 8,
                 2025: 60}     # the radiation suit (E1M4 alone: the one at the far end of its nukage channel)


def pickup_things(pl) -> list:
    from doomfj.combat import GETTABLE
    lifts = set(pl.lv.mp.order) if pl.lv.mp is not None else set()
    # not one lying on a LIFT: at rest it is up where the player below cannot reach it, and the lift waits 26 frames
    # at the bottom (E1M3's shells on lift 256: the play died circling under it)
    return [{"type": t.type, "x": t.x, "y": t.y, "budget": PICKUP_BUDGET[t.type], "taken": False}
            for t in pl.lv.things if t.type in PICKUP_BUDGET and t.type in GETTABLE
            and pl.lv.sector_at(t.x, t.y) not in lifts]


def take_pickups(pl, cur, pred, world, pickups, out):
    """legs to the pickups whose detour from `cur` to the next leg's goal (`pred`) is within their budget, cheapest
    first; -> the cell the next leg starts from"""
    from doomfj.combat import ITEM_RADIUS, PLAYER_R, REACH_DOWN, REACH_UP
    scenes = pl.scenes_for(world)
    bd = ITEM_RADIUS + PLAYER_R - 8
    while True:
        base = pl.leg_path(cur, pred, world)
        if base is None:
            return cur
        pts = [centre(c) for c in base if c[0] != "teleport"][::2]
        best = None
        for it in pickups:
            if it["taken"] or min(abs(p[0] - it["x"]) + abs(p[1] - it["y"]) for p in pts) > 16 * it["budget"]:
                continue
            iz = pl.floor_at(scenes, cell_of(it["x"], it["y"]))

            def touch(c, it=it, iz=iz):
                x, y = centre(c)
                return (abs(x - it["x"]) < bd and abs(y - it["y"]) < bd
                        and -REACH_DOWN <= iz - pl.floor_at(scenes, c) <= REACH_UP)
            tp = pl.leg_path(cur, touch, world)
            if tp is None or any(c[0] == "teleport" for c in tp):
                continue
            back = pl.leg_path(tp[-1], pred, world)
            if back is None:
                continue
            detour = len(tp) + len(back) - len(base)
            # within its budget, the NEAREST first (the walk's order): cheapest-first took a chaingun on the path 230
            # cells on before the shotgun 24 cells from E1M5's start, and the detour back to it was then too long
            rank = (len(tp), detour) if PICKUP_ORDER == "nearest" else (detour, len(tp))
            if detour <= it["budget"] and (best is None or rank < best[3]):
                best = (detour, it, tp, rank)
        if best is None:
            return cur
        detour, it, tp, _n = best
        it["taken"] = True
        out.append({"to": "item:%d" % it["type"], "kind": "item", "action": "touch", "goal": [it["x"], it["y"]],
                    "key_at": [it["x"], it["y"]], "detour_cells": detour, "path": [list(centre(c)) for c in tp]})
        if it["type"] in MUST_PICKUPS:
            out[-1]["must"] = True
        cur = tp[-1]


def legs(pl: Planner, order, ecell, exit_i, pickups=None) -> list:
    """the walk: one leg per trigger to VISIT (keys, switches, walk-over lines, lift and floor triggers), then the
    exit. A door opened by its own use box is not a leg -- the steering opens a door its path meets. Each leg's cells
    are planned in the world as it is then: the earlier legs' mechanisms active, every manual door whose key is held"""
    lv = pl.lv
    out, cur, active, keys = [], pl.start_cell, set(), set()

    def doors_openable():
        return {"door:%d" % si for si in lv.door_order if lv.dp.boxes.get(si) is not None
                and (not pl.mechs["door:%d" % si].key or pl.mechs["door:%d" % si].key in keys)}
    steps = [mid for mid in order if not (pl.mechs[mid].kind == "door" and pl.mechs[mid].trigger == "use")]
    for mid in steps + [None]:
        if mid is None:
            e = lv.exits[exit_i]
            kind, action, goal = "exit", ("use" if e["trigger"] == "S" else "cross"), centre(ecell)
            if e["box"] is not None:
                x0, y0, x1, y1 = e["box"]
                pred = lambda c: x0 <= centre(c)[0] <= x1 and y0 <= centre(c)[1] <= y1   # noqa: E731
            else:
                pred = lambda c: c == ecell                                               # noqa: E731
        else:
            m = pl.mechs[mid]
            kind, goal = m.kind, (pl.touch_at.get(mid, m.pos) if m.kind == "key" else centre(m.cell))
            action = {"touch": "touch", "use": "use", "switch": "use", "walk": "cross"}[m.trigger]
            pred = lambda c, t=m.cell: c == t                                             # noqa: E731
        box = (pl.use_box.get(mid) if mid is not None else lv.exits[exit_i]["box"]) if action == "use" else None
        if pickups is not None:
            cur = take_pickups(pl, cur, pred, active | doors_openable(), pickups, out)
        path = None
        if box is not None:
            # a press is made INSIDE the box: the first reachable cell 12 units in from its edges, so a pose near
            # the goal is inside too (the flood's own cell sits at the box's rim)
            x0, y0, x1, y1 = box
            path = pl.leg_path(cur, lambda c: x0 + 12 <= centre(c)[0] <= x1 - 12 and y0 + 12 <= centre(c)[1] <= y1 - 12,
                               active | doors_openable())
            if path is not None:
                goal = centre(path[-1])
        path = path or pl.leg_path(cur, pred, active | doors_openable())
        row = {"to": mid or "exit", "kind": kind, "action": action, "goal": list(goal)}
        if path is None:
            # the closure missed a dependency (a mechanism no cell of a path stands on): plan the leg in the world the
            # FLOOD had by then -- every mechanism activated before this one -- and say so
            ep = pl.mechs[mid].epoch if mid is not None else 1 << 30
            wide = {o for o in pl.active if pl.mechs[o].epoch < ep}
            path = pl.leg_path(cur, pred, active | wide | doors_openable())
            if path is not None:
                extra = sorted(wide - active - doors_openable())
                row["closure_gap"] = extra
                active |= wide
        if mid is not None and pl.mechs[mid].kind == "key":
            row["key_at"] = list(pl.mechs[mid].pos)
        if mid is not None and action == "use" and mid in pl.use_box:
            row["box"] = list(pl.use_box[mid])
        if mid is None and lv.exits[exit_i]["box"] is not None:
            row["box"] = list(lv.exits[exit_i]["box"])
        if path is None:
            row.update(path=None, error="no path in the world as it is at this leg")
            out.append(row)
            break
        row["path"] = [list(centre(c)) if c[0] != "teleport" else ["teleport", c[1]] for c in path]
        out.append(row)
        cur = path[-1]
        if mid is not None:
            (keys.add(pl.mechs[mid].key) if pl.mechs[mid].kind == "key" else active.add(mid))
    return out


def frontier_unsupported(pl: Planner) -> list:
    """a closed flood's likely blockers: the lines with a special the model lacks whose use box (USE_RANGE around the
    line) holds a reached cell -- the player stood where DOOM would have let him press or cross it"""
    from doomfj.doors import USE_RANGE
    lv = pl.lv
    out = []
    for s, lines in sorted(lv.unsupported.items()):
        for li in lines:
            (ax, ay), (bx, by) = _xy(lv.cmap.vertexes[lv.lds[li].v1]), _xy(lv.cmap.vertexes[lv.lds[li].v2])
            x0, y0 = min(ax, bx) - USE_RANGE, min(ay, by) - USE_RANGE
            x1, y1 = max(ax, bx) + USE_RANGE, max(ay, by) + USE_RANGE
            if any(x0 <= centre(c)[0] <= x1 and y0 <= centre(c)[1] <= y1 for c in pl.visit):
                out.append({"special": s, "doom": DOOM_KINDS.get(s, "?"), "line": li, "tag": lv.lds[li].tag,
                            "at": [(ax + bx) // 2, (ay + by) // 2]})
    return out


def plan(mapname: str, skill: str, wad: str | None = None, budget_s: float = 900.0, with_legs: bool = True,
         drop_keys=(), pickups: bool = True) -> dict:
    """the route as a JSON-able dict. `drop_keys` (the planner's negative control): key colours removed from the map"""
    t0 = time.time()
    lv = Level(mapname, wad, skill)
    if drop_keys:
        lv.keys = [k for k in lv.keys if k[0] not in drop_keys]
    pl = Planner(lv)
    out = {"map": lv.map, "skill": skill, "wad": lv.wad, "start": list(lv.start[:2]),
           "start_angle_deg": round(lv.start[2] * 360 / 2 ** 32), "nav_cell": NAV_CELL,
           "refusals": lv.refusals, "notes": list(lv.notes),
           "exits": [{"line": e["line"], "special": e["special"], "which": e["which"], "model": e["model"]}
                     for e in lv.exits],
           "unsupported": {str(s): {"doom": DOOM_KINDS.get(s, "?"), "lines": v}
                           for s, v in sorted(lv.unsupported.items())}}
    if not lv.exits:
        out.update(ok=False, why="the map has no exit line (11 / 52 / 51 / 124)", seconds=round(time.time() - t0, 1))
        return out
    exit_i, why = pl.flood(budget_s)
    out["flood"] = {"cells": len(pl.visit), "epochs": max(v[1] for v in pl.visit.values()),
                    "activated": sorted(pl.active), "keys": sorted(pl.keys)}
    if exit_i is None:
        out.update(ok=False, why=why, seconds=round(time.time() - t0, 1))
        out["frontier_unsupported"] = frontier_unsupported(pl)
        return out
    order, ecell = pl.route(exit_i)
    e = lv.exits[exit_i]
    out["ok"] = True
    if why:
        out["notes"].append(why)
    out["exit"] = {"line": e["line"], "special": e["special"], "which": e["which"], "trigger": e["trigger"],
                   "model": e["model"], "cell": list(centre(ecell)), "box": list(e["box"]) if e["box"] else None,
                   "seg": [list(p) for p in e["seg"]]}
    if not e["model"]:
        out["notes"].append("exit special %d is NOT in the model (doors.EXIT_SPECIALS): the binary cannot end the level "
                            "there yet" % e["special"])
    out["keys_order"] = [pl.mechs[m].key for m in order if pl.mechs[m].kind == "key"]
    unsup = {li: s for s, v in lv.unsupported.items() for li in v}
    out["needs"] = []
    for mid in order:
        m = pl.mechs[mid]
        row = {"id": mid, "kind": m.kind, "trigger": m.trigger, "at": list(centre(m.cell)), "epoch": m.epoch,
               "key": m.key or m.need_key, "detail": m.detail, "sectors": list(m.sectors)}
        sp = sorted({unsup[li] for li in unsup for side in (lv.lds[li].front, lv.lds[li].back)
                     if side not in (-1, 0xFFFF) and side < len(lv.sds) and lv.sds[side].sector in m.sectors})
        if sp:
            row["unsupported_specials"] = sp
        out["needs"].append(row)
    if with_legs:
        out["legs"] = legs(pl, order, ecell, exit_i, pickup_things(pl) if pickups else None)
        out["path_cells"] = sum(len(g["path"] or ()) for g in out["legs"])
    out["seconds"] = round(time.time() - t0, 1)
    return out


def summary(r: dict) -> str:
    lines = ["%s %s: %s (%.0f s)%s" % (r["map"], r["skill"], "ROUTE" if r.get("ok") else "NO ROUTE",
                                      r.get("seconds", 0), "" if r.get("ok") else " -- " + r.get("why", ""))]
    for x in r["refusals"]:
        lines.append("  model refused %s: %s" % (x["piece"], x["error"]))
    if r.get("unsupported"):
        lines.append("  specials the model lacks: " + ", ".join("%s (%s, %d lines)" % (s, v["doom"], len(v["lines"]))
                                                                 for s, v in r["unsupported"].items()))
    if r.get("flood"):
        f = r["flood"]
        lines.append("  flood: %d cells, %d epochs, keys %s" % (f["cells"], f["epochs"], f["keys"] or "-"))
    if r.get("ok"):
        e = r["exit"]
        lines.append("  exit: line %d special %d (%s, %s)%s" % (e["line"], e["special"], e["which"], e["trigger"],
                                                               "" if e["model"] else " -- NOT IN THE MODEL"))
        lines.append("  keys in order: %s" % (" -> ".join(r["keys_order"]) or "none"))
        for n in r["needs"]:
            lines.append("    %-10s %-6s by %-6s at %-14s epoch %d%s%s" % (
                n["id"], n["kind"], n["trigger"], tuple(n["at"]), n["epoch"],
                " (needs the %s key)" % n["key"] if n["key"] and n["kind"] != "key" else "",
                " UNSUPPORTED %s" % n["unsupported_specials"] if n.get("unsupported_specials") else ""))
        for g in r.get("legs", []):
            lines.append("    leg -> %-10s %-6s %4s cells%s" % (g["to"], g["action"],
                                                               len(g["path"]) if g["path"] else "--",
                                                               "" if g["path"] else " " + g.get("error", "")))
    for b in r.get("frontier_unsupported", []):
        lines.append("  reached, but the model lacks it: special %d (%s) line %d tag %d at %s" % (
            b["special"], b["doom"], b["line"], b["tag"], tuple(b["at"])))
    for g in r.get("legs", []):
        if g.get("closure_gap"):
            lines.append("  note: leg -> %s planned with the flood's world (the closure missed %s)" % (
                g["to"], g["closure_gap"]))
    for n in r.get("notes", []):
        lines.append("  note: %s" % n)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", required=True)
    ap.add_argument("--skill", default="all", choices=SKILLS + ("all",))
    ap.add_argument("--wad", default=None, help="default: the map's fixture wad, else assets/freedoom1.wad")
    ap.add_argument("--out", default=None, help="the JSON: {'map', 'skills': {skill: route}}")
    ap.add_argument("--budget", type=float, default=900.0, help="seconds per flood")
    ap.add_argument("--no-legs", action="store_true")
    a = ap.parse_args(argv)
    skills = SKILLS if a.skill == "all" else (a.skill,)
    doc = {"map": a.map.upper(), "tool": "scripts/level_route.py", "skills": {}}
    rc = 0
    for sk in skills:
        r = plan(a.map, sk, a.wad, a.budget, with_legs=not a.no_legs)
        doc["skills"][sk] = r
        print(summary(r), flush=True)
        rc |= 0 if r.get("ok") else 1
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        import re
        text = re.sub(r"\[\s*(-?\d+),\s*(-?\d+)\s*\]", r"[\1, \2]", json.dumps(doc, indent=1))   # a point a line
        Path(a.out).write_text(text + "\n", encoding="ascii")
        print("wrote %s" % a.out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
