"""scenarios.py -- S4 of docs/plan-gameplay.md: the COMBAT SCENARIO SET v1 -- checkpoints, the oracle
autopilot that plans each run's keys on the gameplay model, and the CAP-22 validator.

    python scratchpad/gp/scenarios.py --plan        # plan every run, write scenarios/combat_scenarios_v1.json
    python scratchpad/gp/scenarios.py --validate    # replay the frozen set on the model, CAP-22 criteria
    python scratchpad/gp/scenarios.py --selftest    # R9: mutated sets must FAIL, the true one PASS
    python scratchpad/gp/scenarios.py --regions     # the region analysis the checkpoints come from

THE SET (owner decisions D1, D2, D4, D7). 10 runs x 100 frames, one tic per frame, skill HARD (the
budget case, 46 monsters). Every run STARTS FROM A CHECKPOINT: a player position and angle injected
into the level's START STATE (monsters asleep at their spawns, doors shut, nothing taken, the
start inventory: pistol, 50 bullets, 100 health). Checkpoints spread over the progression regions
of E1M1 (the spec mission's flood, `regions()`): the doors region the player starts in, the 31
sectors behind the two lifts, and the 12 behind the blue-key doors.

THE AUTOPILOT (`Autopilot`) plays the MODEL (doomfj.world + doomfj.combat, the default geometric
aim). Every frame, from the model's state only (no lookahead into the RNG):
  * COMBAT: the target is the nearest living monster it can see within 1024 units -- awake first,
    the weaker first among equals; it turns until the aim (the model's own `aim_geometric` at the
    centre column) is on a monster and fires; it keeps its distance (backs off when a monster is
    closer than its keep radius or its health is low) and closes in when the target is far.
  * TOUR: with nothing to fight it walks the shortest walkable path (a 16-unit cell graph built
    with the oracle's own try_move, plain doors open, key doors shut) to the nearest living monster
    -- taking a pickup first when one is within 192 units of path -- pressing use in a door's box.
  * STYLE: most checkpoints FIGHT FIRST (a pickup is a detour only when there is nothing to
    fight, or within a step or two, or health when hurt); the three item-rich ones (the south
    hall, the courtyard, the blue-key room's west end) COLLECT whenever no awake monster is within
    256 units -- the way a player sweeps a room's items before the fight finds him.
  * RULES: never use in a key door's box (the model needs the card, blocked27 opens without it) or
    in the exit's box; never step where a solid thing would refuse the step (the model blocks the
    player on things, blocked27 walks through them: such a step would part the two trajectories).
  * SURVIVAL: each run is planned with parameter sets from aggressive to defensive; the first set
    whose whole run survives (and never uses a forbidden door or the exit) is kept. Deterministic:
    no randomness anywhere but the model's own (seeded, in the state).

--validate REPLAYS the frozen keys from the checkpoints on the model and checks CAP-22 (plan
section 9): every run survives; >= 30% of the set's frames have an awake monster in view; >= 5
kills, all three attack kinds (hitscan, melee, fireball) and >= 3 pickups across the set; every
run moves on >= 60% of its movement frames. It also re-derives the stored poses (a set whose keys,
model or planner changed fails the freeze check), counts the frames where blocked27 would part from
the model (B0 comparability), and reports the per-frame population statistics the budget needs.

"IN VIEW" is geometric: the thing's box projects onto the 160 columns from the player's view (the
aim's own projection) and a 2D line of sight reaches its centre. It approximates the picture
(occlusion by walls is the LOS test; sprite clipping by steps is not modelled) -- the compositor
census (S5) counts what is DRAWN.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "tests", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", HERE, ROOT):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

from doomfj import gamedata as gd                                           # noqa: E402
from doomfj import world as W                                               # noqa: E402
from doomfj.doors import door_tic, in_use_box_fixed                         # noqa: E402
from doomfj.fixedpoint import _signed, fixed_mul                            # noqa: E402
from doomfj.reference_model import ANGLE_TURN, Scene, SimState              # noqa: E402

SCEN_DIR = HERE / "scenarios"
SCEN_FILE = SCEN_DIR / "combat_scenarios_v1.json"
CACHE_DIR = Path(os.environ.get("GP_NAV_CACHE", r"C:\Users\tomhe\AppData\Local\Temp\claude"
                                r"\C--Users-tomhe-Documents-doom-flipjump"
                                r"\29ddbecf-cbb7-4734-805a-36c0e391327d\scratchpad\gp_navcache"))
FRAMES = 100
SKILL = gd.SK_HARD
UNIT = 1 << 16
M32 = 0xFFFFFFFF
CELL = 16
MODEL_FILES = ("src/doomfj/world.py", "src/doomfj/combat.py", "src/doomfj/gamedata.py",
               "src/doomfj/rng.py", "src/doomfj/doors.py", "src/doomfj/doorcode.py",
               "src/doomfj/reference_model.py", "src/doomfj/fixedpoint.py",
               "src/doomfj/mapcompiler.py", "src/doomfj/config.py",
               "tests/fixtures/freedoom_e1m1.wad")
LETTERS = (("forward", "f"), ("back", "b"), ("turn_left", "l"), ("turn_right", "r"),
           ("use", "u"), ("fire", "F"), ("w1", "K"), ("w2", "P"), ("w3", "S"), ("w4", "C"))
KEY_OF = {c: n for n, c in LETTERS}
ASLEEP_ACTIONS = frozenset({"A_Look"})

# pickups the autopilot detours for: always-taken items (bonuses, weapons, ammo below the cap,
# the backpack, keys) and health or armor only when it would be taken (below 100)
PICKUP_ALWAYS = frozenset({2014, 2015, 2001, 2002, 2003, 2004, 2005, 2006, 8, 5, 6, 13, 38, 39,
                           40, 2023})
PICKUP_AMMO = frozenset({2007, 2008, 2048, 2049, 2010, 2046, 2047, 17})
PICKUP_HEALTH = frozenset({2011, 2012, 2013})
PICKUP_ARMOR = frozenset({2018, 2019})
PICKUP_DETOUR = 10           # cells of path (160 units): a pickup this close is worth the walk
DETOUR_CALM = 256            # ... when no awake monster is nearer than this

# CAP-22 criteria (plan section 9, the coordinator's S4 spec)
MIN_AWAKE_IN_VIEW = 0.30
MIN_KILLS = 5
MIN_PICKUPS = 3
MIN_MOVING = 0.60

# ================================================================================================
# the checkpoints: WHERE, facing WHAT, and WHY (resolved to a standable point by `resolve`)
# ================================================================================================
CHECKPOINTS = (
    dict(name="R0-west-hall", sector=150, want=(300, 338), face=(752, 336), region=0,
         why="the level's opening fight: the ambush trio (2 zombiemen, an imp) of sector 17, "
             "450-570 units east, a short walk from the player start"),
    dict(name="R0-south-hall", style="collect", sector=57, want=(616, -640), face=(848, -576), region=0,
         why="the south hall (11 pickups): shotgun guys at 264 and 504 units (one on the "
             "sector-112 ledge) and the imps of sector 106 at 440-900"),
    dict(name="R0-imp-court", sector=12, want=(640, 812), face=(848, 1056), region=0,
         why="the imp court (sectors 13/56): three imps at 290-460 units and a shotgun guy, 3 "
             "barrels -- fireballs"),
    dict(name="R0-northwest", sector=135, want=(300, 1450), face=(352, 1392), region=0,
         why="the densest doors-region cluster (sectors 36/66/122): 2 demons at ~400 units, a "
             "shotgun guy and zombiemen at 140-400, all but one ambush -- melee"),
    dict(name="R0-courtyard", style="collect", sector=18, want=(1424, 732), face=(1424, 1408), region=0,
         why="the tall courtyard (sector 18, ceiling 536, 6 pickups, 2 barrels): its imp and the "
             "imp court's seen across the drop at 600-950 units -- the widest open view"),
    dict(name="R2-barrel-hall", sector=134, want=(2150, -520), face=(2256, -160), region=2,
         why="behind the lifts: 16 barrels (sector 134) with 3 shotgun guys, 2 imps, 2 demons and "
             "the spectre in view at 410-630 units -- barrel chains"),
    dict(name="R2-spectre-corridor", sector=102, want=(1588, -492), face=(1656, -248), region=2,
         why="behind the lifts: a demon at 278 and a shotgun guy at 226 units, the sector-133 "
             "corridor (spectre, imps) beyond"),
    dict(name="R2-east-yard", sector=15, want=(2052, 680), face=(2192, 784), region=2,
         why="behind the lifts: the east yard's two imps at 190 and 350 units, beside the "
             "blue-key room (sector 35)"),
    dict(name="R3-west", style="collect", sector=86, want=(-120, 1768), face=(-96, 1984), region=3,
         why="behind the blue-key doors: two of sector 87's four shotgun guys at 230-360 units"),
    dict(name="R3-mid", sector=87, want=(400, 1856), face=(144, 1952), region=3,
         why="behind the blue-key doors: the same room from its middle, three shotgun guys at "
             "300-560 units"),
)

# the autopilot's parameter sets, aggressive first (SURVIVAL: the first set whose run survives)
PARAMS = (
    dict(name="aggressive", keep=128, band=48, retreat_hp=40, engage=1024),
    dict(name="steady", keep=192, band=64, retreat_hp=55, engage=1024),
    dict(name="cautious", keep=288, band=96, retreat_hp=70, engage=900),
    dict(name="defensive", keep=416, band=128, retreat_hp=85, engage=800),
)


# ================================================================================================
# small helpers
# ================================================================================================
def sha16(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def code_hashes() -> dict:
    out = {f: sha16(ROOT / f) for f in MODEL_FILES}
    out["scratchpad/gp/scenarios.py"] = sha16(Path(__file__))
    return out


def git_head() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:                                                  # noqa: BLE001
        return "?"


def keys_to_str(kd: dict) -> str:
    return "".join(c for n, c in LETTERS if kd.get(n)) or "-"


def str_to_keys(s: str) -> dict:
    return {KEY_OF[c]: True for c in s if c != "-"}


def bam(dx: float, dy: float) -> int:
    return int(round(math.atan2(dy, dx) / (2 * math.pi) * (1 << 32))) & M32


def angle_err(want: int, have: int) -> int:
    e = (want - have) & M32
    return e - (1 << 32) if e >= 1 << 31 else e


def new_world() -> "W.World":
    return W.World(skill=SKILL)


def asleep(w, m: int) -> bool:
    return gd.STATES[gd.STATE_NAMES[w.ws.mon_state[m]]].action in ASLEEP_ACTIONS


def alive(w, m: int) -> bool:
    ws = w.ws
    return bool(ws.mon_active[m]) and ws.mon_health[m] > 0


def span_on_screen(w, x: int, y: int, r: int):
    """(depth16, x1, x2) of a box of radius r at map units (x, y), projected from the player's view
    exactly as `aim_geometric` projects a target; None when it is behind the view plane."""
    ws, rm = w.ws, w.rm
    cfg = rm.cfg
    vcos, vsin = rm.read_cos(ws.pangle), rm.read_sin(ws.pangle)
    tr_x = _signed((x << 16) - ws.px, 32)
    tr_y = _signed((y << 16) - ws.py, 32)
    gxt = _signed(fixed_mul(tr_x & M32, vcos, 8, 4), 32)
    gyt = -_signed(fixed_mul(tr_y & M32, vsin, 8, 4), 32)
    tz = gxt - gyt
    if tz < (4 << 16):
        return None
    gxt2 = -_signed(fixed_mul(tr_x & M32, vsin, 8, 4), 32)
    gyt2 = _signed(fixed_mul(tr_y & M32, vcos, 8, 4), 32)
    tx = -(gyt2 + gxt2)
    xscale = rm._scale_recip_div(cfg.PROJECTION << 16, tz)
    cxf = cfg.CENTERX << 16
    x1 = (cxf + _signed(fixed_mul((tx - (r << 16)) & M32, xscale, 8, 4), 32)) >> 16
    x2 = ((cxf + _signed(fixed_mul((tx + (r << 16)) & M32, xscale, 8, 4), 32)) >> 16) - 1
    return tz, x1, x2


def in_view(w, x: int, y: int, r: int) -> bool:
    sp = span_on_screen(w, x, y, r)
    if sp is None or sp[2] < 0 or sp[1] > w.rm.cfg.VIEW_W - 1:
        return False
    return w.los_points((w.ws.px, w.ws.py), (x << 16, y << 16))


def population(w, ev) -> dict:
    """the per-frame numbers the budget needs (after the tic)"""
    ws = w.ws
    awake = inv = awake_inv = corpses_inv = 0
    for m in range(w.layout.nmon):
        if not ws.mon_active[m]:
            continue
        r = w.mon_radius[m]
        if ws.mon_health[m] > 0:
            a = not asleep(w, m)
            awake += a
            if in_view(w, ws.mon_x[m], ws.mon_y[m], r):
                inv += 1
                awake_inv += a
        elif in_view(w, ws.mon_x[m], ws.mon_y[m], r):
            corpses_inv += 1
    return {"awake": awake, "in_view": inv, "awake_in_view": awake_inv,
            "corpses_in_view": corpses_inv, "fireballs": sum(ws.proj_active),
            "deferred": len(ev.deferred), "heavy": len(ev.heavy)}


# ================================================================================================
# the region analysis (the spec mission's flood, scratchpad/plan/spec/gates.py, on the model's data)
# ================================================================================================
LIFTS = (98, 103)
W1DOORS = (77, 145)
LOWER = (76, 126, 129)
STAGES = (("doors",), ("doors", "w1"), ("doors", "w1", "lift"), ("doors", "w1", "lift", "key"),
          ("doors", "w1", "lift", "key", "lower"))
REGION_NAMES = ("R0 doors (start)", "R1 walk-over doors", "R2 behind the lifts",
                "R3 behind the blue-key doors", "R4 the floor switch")


def regions(w) -> dict:
    """sector -> progression stage (index into STAGES); unreached sectors are absent"""
    from doomfj import doors as D
    lds, sds, secs = w.lds, w.sds, w.secs
    ds = D.door_sectors(secs, lds, sds)
    nb = D.neighbours(lds, sds)

    def side_sec(sd):
        return sds[sd].sector if sd != 0xFFFF and 0 <= sd < len(sds) else None

    blue = {side_sec(ld.back) for ld in lds if ld.special in (26, 32)}
    adj = collections.defaultdict(list)
    for ld in lds:
        a, b = side_sec(ld.front), side_sec(ld.back)
        if a is None or b is None or (ld.flags & 1):
            continue
        adj[a].append(b)
        adj[b].append(a)
    start = w.leaf_sector[w.rm.point_in_subsector(w.cmap, w.ws.px >> 16, w.ws.py >> 16)]

    def flood(stage):
        fl = {i: s.floor_h for i, s in enumerate(secs)}
        cl = {i: s.ceil_h for i, s in enumerate(secs)}
        for s, oh in ds.items():
            if s not in blue or "key" in stage:
                cl[s] = oh
        if "w1" in stage:
            for s in W1DOORS:
                cl[s] = min(secs[n].ceil_h for n in nb[s]) - 4
        if "lower" in stage:
            for s in LOWER:
                fl[s] = min(secs[n].floor_h for n in nb[s])
        seen, q = {start}, collections.deque([start])
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v in seen:
                    continue
                gap = min(cl[u], cl[v]) - max(fl[u], fl[v])
                ok = gap >= 56 and fl[v] - fl[u] <= 24
                if "lift" in stage and (u in LIFTS or v in LIFTS):
                    lift = u if u in LIFTS else v
                    other = v if u in LIFTS else u
                    lo = min([secs[n].floor_h for n in nb[lift]] + [fl[lift]])
                    ok = ok or (lo - 24 <= fl[other] <= fl[lift] + 24) or fl[other] - lo <= 24
                    ok = ok and (min(cl[u], cl[v]) - max(fl[other], lo) >= 56)
                if ok:
                    seen.add(v)
                    q.append(v)
        return seen

    out, prev = {}, set()
    for k, st in enumerate(STAGES):
        r = flood(st)
        for s in r - prev:
            out[s] = k
        prev = r
    return out


# ================================================================================================
# the navigation graph: 16-unit cells, edges = the oracle's own try_move (plain doors open)
# ================================================================================================
class NavGraph:
    """Directed cell graph of where the player can walk from a seed, built by BFS with
    `ReferenceModel.try_move` against the PLAN scene: every door at its open height, the key doors'
    lines blocking, lifts at their stored floors; cells a static solid thing (barrel, solid decor)
    overlaps are left out. Cached on disk by the model's code hash and the seed cell."""

    STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

    def __init__(self, cells, adj):
        self.cells = cells
        self.index = {c: i for i, c in enumerate(cells)}
        self.adj = adj

    @staticmethod
    def plan_scene(w) -> Scene:
        key_lines = frozenset(li for si in w.door_cards for li in w.door_lines.get(si, ()))
        return Scene(w.mw, w.mw, w.mapname, w.cmap, w.open_h, key_lines)

    @staticmethod
    def static_obstacles(w):
        from doomfj.combat import BARREL_R
        obs = [(t.x, t.y, BARREL_R) for b, t in enumerate(w.barrel_things) if w.ws.bar_solid[b]]
        obs += [(t.x, t.y, w.decor_radius[t.type]) for t in w._decor_now]
        return obs

    _loaded: list = []

    @staticmethod
    def _model_key() -> str:
        h = {k: v for k, v in code_hashes().items() if k != "scratchpad/gp/scenarios.py"}
        return hashlib.sha256(json.dumps(h, sort_keys=True).encode()).hexdigest()[:12]

    @classmethod
    def build(cls, w, seed_xy, cap=20000, tag="") -> "NavGraph":
        """the region graph containing `seed_xy`: one already built (this process or the disk
        cache, same model hash) if it holds the seed's cell, else a new BFS from the seed"""
        mk = cls._model_key()
        seed_cell = (seed_xy[0] // CELL, seed_xy[1] // CELL)
        if not cls._loaded and CACHE_DIR.exists():
            for f in sorted(CACHE_DIR.glob("nav_%s_*.pkl" % mk)):
                cells, adj = pickle.loads(f.read_bytes())
                cls._loaded.append(cls(cells, adj))
        for g in cls._loaded:
            if seed_cell in g.index:
                return g
        cache = CACHE_DIR / ("nav_%s_%d_%d.pkl" % (mk, seed_cell[0], seed_cell[1]))
        t0 = time.time()
        scene = cls.plan_scene(w)
        obs = cls.static_obstacles(w)
        rm = w.rm

        def free(c):
            x, y = c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2
            return all(abs(x - ox) >= r + 16 or abs(y - oy) >= r + 16 for ox, oy, r in obs)

        start = (seed_xy[0] // CELL, seed_xy[1] // CELL)
        cells, index, adj = [start], {start: 0}, [[]]
        q = collections.deque([start])
        while q and len(cells) < cap:
            c = q.popleft()
            ci = index[c]
            wx, wy = c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2
            for dx, dy in cls.STEPS:
                n = (c[0] + dx, c[1] + dy)
                if n in index:
                    if rm.try_move(scene, wx << 16, wy << 16, (n[0] * CELL + CELL // 2) << 16,
                                   (n[1] * CELL + CELL // 2) << 16):
                        adj[ci].append(index[n])
                    continue
                if not free(n):
                    continue
                nx, ny = n[0] * CELL + CELL // 2, n[1] * CELL + CELL // 2
                if not rm.try_move(scene, wx << 16, wy << 16, nx << 16, ny << 16):
                    continue
                index[n] = len(cells)
                cells.append(n)
                adj.append([])
                adj[ci].append(index[n])
                q.append(n)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps((cells, adj)))
        print("  nav graph %s: %d cells in %.1f s (cached %s)" % (tag, len(cells), time.time() - t0,
                                                                 cache.name), flush=True)
        g = cls(cells, adj)
        cls._loaded.append(g)
        return g

    def nearest(self, x: int, y: int, within: int = 48):
        c = (x // CELL, y // CELL)
        if c in self.index:
            return self.index[c]
        best = None
        rr = within // CELL + 1
        for dx in range(-rr, rr + 1):
            for dy in range(-rr, rr + 1):
                n = (c[0] + dx, c[1] + dy)
                if n in self.index:
                    d = dx * dx + dy * dy
                    if best is None or (d, self.index[n]) < best[0]:
                        best = ((d, self.index[n]), self.index[n])
        return None if best is None else best[1]

    def bfs(self, src: int):
        """(dist, parent) from src over the directed edges"""
        dist, par = {src: 0}, {src: None}
        q = collections.deque([src])
        while q:
            u = q.popleft()
            for v in self.adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    par[v] = u
                    q.append(v)
        return dist, par

    def path(self, par, goal):
        out = []
        while goal is not None:
            out.append(goal)
            goal = par[goal]
        return out[::-1]

    def xy(self, i: int):
        c = self.cells[i]
        return c[0] * CELL + CELL // 2, c[1] * CELL + CELL // 2


# ================================================================================================
# checkpoints -> standable start poses
# ================================================================================================
def resolve(w, cp: dict):
    """the first standable point IN THE CHECKPOINT'S SECTOR on a deterministic spiral around
    `want` (8-unit rings out to 480 units): the oracle's try_move accepts it on the model's start
    scene and no solid thing overlaps it. Returns (x16, y16, angle) facing `face`."""
    wx, wy = cp["want"]
    rm = w.rm
    for ring in range(0, 61):
        pts = [(0, 0)] if ring == 0 else sorted(
            {(dx, dy) for dx in range(-ring, ring + 1) for dy in (-ring, ring)}
            | {(dx, dy) for dy in range(-ring, ring + 1) for dx in (-ring, ring)},
            key=lambda p: (p[0] * p[0] + p[1] * p[1], p))
        for dx, dy in pts:
            x, y = wx + 8 * dx, wy + 8 * dy
            if w.leaf_sector[rm.point_in_subsector(w.cmap, x, y)] != cp["sector"]:
                continue
            x16, y16 = x << 16, y << 16
            if not rm.try_move(w.scene_c, x16, y16, x16, y16):
                continue
            if w._solid_thing_at(x16, y16) is not None:
                continue
            fx, fy = cp["face"]
            return x16, y16, bam(fx - x, fy - y)
    raise AssertionError("no standable point near checkpoint %s" % cp["name"])


def start_world(cp_pose) -> "W.World":
    w = new_world()
    w.teleport_player(cp_pose[0], cp_pose[1], cp_pose[2])
    return w


# ================================================================================================
# the binary's mirror (B0 comparability): what blocked27 does from the same pre-pose and keys
# ================================================================================================
class BinaryMirror:
    """blocked27's door and player tic as the oracle computes it (onewalk.DoorSim's order): every
    door ticks with `use` pressed in its box (NO key check -- blocked27 opens key doors without a
    card), then the player steps with `step_sim` against open doors + the not-yet-passable doors'
    lines. No things: blocked27 walks through them. Fed the MODEL's pre-tic pose every frame, as
    b0 injects it, so a divergence lasts one frame and never accumulates."""

    def __init__(self, w):
        self.w = w
        self.ds = [(0, W.IDLE, 0, 0) for _ in w.door_order]
        self._scenes = {}

    def step(self, pre, kd):
        w = self.w
        used = bool(kd.get("use"))
        self.ds = [door_tic(self.ds[d], w.door_nstates[si],
                            used and in_use_box_fixed(w.door_boxes[si], pre[0], pre[1]))
                   for d, si in enumerate(w.door_order)]
        blocked = frozenset(li for d, si in enumerate(w.door_order)
                            if self.ds[d][0] < w.door_pass[si] for li in w.door_lines.get(si, ()))
        if blocked not in self._scenes:
            self._scenes[blocked] = Scene(w.mw, w.mw, w.mapname, w.cmap, w.open_h, blocked)
        st = w.rm.step_sim(SimState(pre[0], pre[1], pre[2], w.mapname), kd,
                           scene=self._scenes[blocked])
        return (st.x, st.y, st.angle), tuple(s[0] for s in self.ds)


# ================================================================================================
# the autopilot
# ================================================================================================
class Autopilot:
    def __init__(self, w, nav: NavGraph, params: dict, style: str = "fight"):
        self.w, self.nav, self.p, self.style = w, nav, params, style
        self.target = None                 # current combat target slot
        self.goal = None                   # ("mon", m) | ("pickup", i)
        self.path = []
        self.path_age = 0
        self.stuck = 0
        self.last_xy = None
        self.forbidden_boxes = [w.door_boxes[si] for si in w.door_cards] + list(w.exit_boxes)
        self.open_boxes = [(d, si, w.door_boxes[si]) for d, si in enumerate(w.door_order)
                           if si not in w.door_cards]

    # -- geometry
    def _pxy(self):
        ws = self.w.ws
        return ws.px >> 16, ws.py >> 16

    def _dist(self, x, y):
        px, py = self._pxy()
        return W.aprox_distance(x - px, y - py)

    def _turn_toward(self, x, y, kd):
        ws = self.w.ws
        err = angle_err(bam(x - (ws.px / UNIT), y - (ws.py / UNIT)), ws.pangle)
        if err > ANGLE_TURN // 2:
            kd["turn_left"] = True
        elif err < -(ANGLE_TURN // 2):
            kd["turn_right"] = True
        return err

    def _landing(self, kd):
        """where the static step (blocked27's) would put the player, and whether that is a REAL
        step: at least one map unit, the unit the validator's movement criterion counts (a slide
        along a wall that moves a fraction of a unit is not a step)"""
        w = self.w
        ws = w.ws
        st = w.rm.step_sim(SimState(ws.px, ws.py, ws.pangle, w.mapname), kd, scene=w.scene_c)
        moved = abs(_signed(st.x - ws.px, 32)) + abs(_signed(st.y - ws.py, 32)) >= UNIT
        return (st.x, st.y), moved

    def _safe_move(self, kd) -> bool:
        """a move key is allowed when the static step really moves AND no solid thing would refuse
        its landing (the model and blocked27 would part there)"""
        (lx, ly), moved = self._landing(kd)
        return moved and self.w._solid_thing_at(_signed(lx, 32), _signed(ly, 32)) is None

    # -- decisions
    def _combat_target(self):
        w, ws, p = self.w, self.w.ws, self.p
        px, py = self._pxy()
        cands = []
        for m in range(w.layout.nmon):
            if not alive(w, m):
                continue
            d = self._dist(ws.mon_x[m], ws.mon_y[m])
            if d > p["engage"]:
                continue
            if not w.los_points((ws.px, ws.py), (ws.mon_x[m] << 16, ws.mon_y[m] << 16)):
                continue
            if asleep(w, m) and d > p["keep"] + p["band"] + 64:
                continue                 # a far sleeper is a TOUR goal, not a fight yet
            cands.append((0 if not asleep(w, m) else 1, ws.mon_health[m] > 30, d, m))
        if not cands:
            return None
        if self.target is not None and any(c[3] == self.target for c in cands):
            cur = next(c for c in cands if c[3] == self.target)
            best = min(cands)
            if cur[0] <= best[0]:
                return self.target
        return min(cands)[3]

    def _threat(self):
        """distance to the nearest AWAKE living monster (any sight)"""
        w, ws = self.w, self.w.ws
        ds = [self._dist(ws.mon_x[m], ws.mon_y[m]) for m in range(w.layout.nmon)
              if alive(w, m) and not asleep(w, m)]
        return min(ds) if ds else 1 << 30

    def _wanted(self, t) -> bool:
        ws = self.w.ws
        if t.type in PICKUP_ALWAYS or t.type in PICKUP_AMMO:
            return True
        if t.type in PICKUP_HEALTH:
            return ws.p_health < 100
        if t.type in PICKUP_ARMOR:
            return ws.p_armor < 100
        return False

    def _near_pickup(self, dist, within):
        """(goal, cell) of the nearest wanted untaken pickup within `within` cells of path"""
        w, ws = self.w, self.w.ws
        best_p = None
        for i, t in enumerate(w.pickup_things):
            if ws.pickup_taken[i] or not self._wanted(t):
                continue
            c = self.nav.nearest(t.x, t.y, 24)
            if c is not None and c in dist and dist[c] <= within:
                if best_p is None or (dist[c], i) < best_p[0]:
                    best_p = ((dist[c], i), ("pickup", i), c)
        return (best_p[1], best_p[2]) if best_p is not None else (None, None)

    def _tour_goal(self, dist):
        """the nearest wanted pickup within 12 cells of path, else the nearest living monster"""
        w, ws = self.w, self.w.ws
        g, c = self._near_pickup(dist, 12)
        if g is not None:
            return g, c
        best = None
        for m in range(w.layout.nmon):
            if not alive(w, m):
                continue
            c = self.nav.nearest(ws.mon_x[m], ws.mon_y[m], 64)
            if c is None or c not in dist:
                continue
            if best is None or (dist[c], m) < best[0]:
                best = ((dist[c], m), ("mon", m), c)
        if best is not None:
            return best[1], best[2]
        return None, None

    def decide(self) -> dict:
        w, ws, p = self.w, self.w.ws, self.p
        kd = {}
        px, py = self._pxy()
        moved = self.last_xy is not None and (ws.px, ws.py) != self.last_xy
        self.last_xy = (ws.px, ws.py)
        # weapon: the shotgun once owned (a shotgun guy's drop)
        if ws.p_owned[gd.WP_SHOTGUN] and ws.p_ammo[gd.AM_SHELL] and ws.p_ready != gd.WP_SHOTGUN \
                and ws.p_pending != gd.WP_SHOTGUN:
            kd["w3"] = True
        tgt = self._combat_target()
        self.target = tgt
        aim = w.aim(w, w.aim_centre)
        fire = False
        # an ACCURATE pistol: the trigger goes down only while the weapon is ready (A_WeaponReady)
        # and up otherwise, so A_ReFire never refires -- DOOM's first shot, refire == 0, is exact
        ready = gd.STATES[gd.STATE_NAMES[ws.p_wpn_state]].action == "A_WeaponReady"
        if aim is not None and ready:
            kind, i = aim
            if kind == "mon" and alive(w, i) and self._dist(ws.mon_x[i], ws.mon_y[i]) <= p["engage"]:
                fire = True
            elif kind == "bar":
                t = w.barrel_things[i]
                near_mon = any(alive(w, m) and not asleep(w, m)
                               and W.aprox_distance(ws.mon_x[m] - t.x, ws.mon_y[m] - t.y) < 160
                               for m in range(w.layout.nmon))
                fire = near_mon and self._dist(t.x, t.y) > 256
        # PICKUPS: fight first, then collect -- except an item within reach of a step or two, and
        # health when hurt. Three rules, in order: calm (nothing to fight, no awake monster within
        # DETOUR_CALM) takes a wanted item within PICKUP_DETOUR cells; an item within 4 cells is
        # taken while no awake monster is within 160; below 50 health a health item within 16
        # cells is taken while none is within 128.
        detour = False
        threat = self._threat()
        within = 0
        if (tgt is None or self.style == "collect") and threat >= DETOUR_CALM:
            within = PICKUP_DETOUR
        elif threat >= 160:
            within = 4
        if ws.p_health < 50 and threat >= 128:
            within = max(within, 16)
        if within:
            me = self.nav.nearest(px, py, 48)
            if me is not None:
                dist, par = self.nav.bfs(me)
                g, c = self._near_pickup(dist, within)
                if g is not None and within == 16 and ws.p_health < 50 and                         w.pickup_things[g[1]].type not in PICKUP_HEALTH and                         dist[c] > (PICKUP_DETOUR if tgt is None else 4):
                    g = None                     # the hurt rule reaches far only for health
                if g is not None:
                    detour = True
                    if self.goal != g:
                        self.goal, self.path, self.path_age = g, self.nav.path(par, c), 0
        if detour:
            self._navigate(kd, moved)
        elif tgt is not None:
            tx, ty = ws.mon_x[tgt], ws.mon_y[tgt]
            if not (aim is not None and aim[0] == "mon" and alive(w, aim[1])):
                self._turn_toward(tx, ty, kd)
            d = self._dist(tx, ty)
            threat = self._threat()
            # CLOSE IN AND KEEP A BAND: walk at the target until `keep + band`, back off inside
            # `keep` or when hurt with a monster near -- a player with no strafe key moves along
            # the line he shoots down
            if (d < p["keep"] or (ws.p_health < p["retreat_hp"] and threat < 320)):
                bk = dict(kd, back=True)
                if self._safe_move(bk):
                    kd = bk
            elif d > p["keep"] + p["band"]:
                fw = dict(kd, forward=True)
                if self._safe_move(fw):
                    kd = fw
        else:
            self._navigate(kd, moved)
        if fire:
            kd["fire"] = True
        # use: only in an openable door's box, never in a key door's or the exit's
        if any(in_use_box_fixed(b, ws.px, ws.py) for b in self.forbidden_boxes):
            kd.pop("use", None)
        else:
            for d, si, box in self.open_boxes:
                if in_use_box_fixed(box, ws.px, ws.py) and ws.d_state[d] < w.door_pass[si]:
                    kd["use"] = True
                    break
        return kd

    def _navigate(self, kd, moved):
        px, py = self._pxy()
        me = self.nav.nearest(px, py, 48)
        if me is None:
            return
        if not moved and self.path:
            self.stuck += 1
        else:
            self.stuck = 0
        self.path_age += 1
        if not self.path or self.path_age >= 8 or self.stuck >= 3 or self.goal is None \
                or not self._goal_valid():
            dist, par = self.nav.bfs(me)
            self.goal, gcell = self._tour_goal(dist)
            self.path = self.nav.path(par, gcell) if gcell is not None else []
            self.path_age = 0
            if self.stuck >= 3 and len(self.path) > 4:
                self.path = self.path[2:]
            self.stuck = 0
        if not self.path:
            return
        # the waypoint: the farthest of the next 4 cells, dropping cells already reached
        while len(self.path) > 1 and self.nav.cells[self.path[0]] == self.nav.cells[me]:
            self.path.pop(0)
        wp = self.path[min(3, len(self.path) - 1)]
        wx, wy = self.nav.xy(wp)
        err = self._turn_toward(wx, wy, kd)
        if abs(err) < (1 << 30):                 # within 90 degrees: walk while turning
            fw = dict(kd, forward=True)
            if self._safe_move(fw):
                kd.update(fw)
            else:
                # a thing (or a wall) is in the way: turn harder toward the waypoint's side
                if "turn_left" not in kd and "turn_right" not in kd:
                    kd["turn_left" if err >= 0 else "turn_right"] = True

    def _goal_valid(self):
        w, ws = self.w, self.w.ws
        kind, i = self.goal
        if kind == "pickup":
            return not ws.pickup_taken[i]
        return alive(w, i)


# ================================================================================================
# planning and replay
# ================================================================================================
def forbidden_events(w, ev) -> list:
    bad = []
    if ev.level_done:
        bad.append("exit")
    if ev.deaths:
        bad.append("death")
    if ev.restart_requests or ev.restarts:
        bad.append("restart")
    return bad


def plan_run(cp: dict, pose, nav: NavGraph):
    """keys for FRAMES frames: the first parameter set whose run survives with no forbidden event"""
    tried = []
    for params in PARAMS:
        w = start_world(pose)
        ap = Autopilot(w, nav, params, cp.get("style", "fight"))
        keys, bad = [], []
        for _f in range(FRAMES):
            kd = ap.decide()
            ev = w.tic(kd)
            keys.append(kd)
            bad += forbidden_events(w, ev)
            if bad:
                break
        tried.append((params["name"], bad[:1]))
        if not bad:
            return keys, params["name"], tried
    raise AssertionError("checkpoint %s: no parameter set survives (%s)" % (cp["name"], tried))


def replay(pose, keys) -> dict:
    """the frozen run on a fresh model: poses, events, the population, B0 comparability"""
    w = start_world(pose)
    mirror = BinaryMirror(w)
    poses, pops, moving, move_frames, div_pose, div_door, blocked_by_thing = [], [], 0, 0, 0, 0, 0
    pre = (pose[0], pose[1], pose[2])
    for kd in keys:
        ev = w.tic(kd)
        ws = w.ws
        post = (ws.px, ws.py, ws.pangle)
        bpose, bdoors = mirror.step(pre, kd)
        if bpose != post:
            div_pose += 1
        if bdoors != tuple(ws.d_state):
            div_door += 1
        blocked_by_thing += ev.player_blocked > 0
        if kd.get("forward") or kd.get("back"):
            move_frames += 1
            if abs(post[0] - pre[0]) + abs(post[1] - pre[1]) >= UNIT:
                moving += 1
        poses.append([post[0], post[1], post[2]])
        pops.append(population(w, ev))
        pre = post
    totals = w.event_totals()
    return {"poses": poses, "pops": pops, "totals": totals, "moving": moving,
            "move_frames": move_frames, "div_pose": div_pose, "div_door": div_door,
            "blocked_by_thing": blocked_by_thing, "digest": w.digest(),
            "health": max(0, w.ws.p_health), "dead": w.ws.p_dead,
            "doors_opened": sum(1 for s in w.ws.d_state if s)}


# ================================================================================================
# validation (CAP-22)
# ================================================================================================
def criteria(runs_metrics) -> list:
    """[(name, ok, detail)] -- the CAP-22 checks over the set's replayed metrics"""
    out = []
    n_frames = sum(len(r["pops"]) for r in runs_metrics)
    dead = [r["name"] for r in runs_metrics if r["dead"] or r["totals"]["deaths"]]
    out.append(("every run survives", not dead and n_frames > 0,
                "deaths in %s" % dead if dead else "%d runs, 0 deaths" % len(runs_metrics)))
    aiv = sum(1 for r in runs_metrics for pp in r["pops"] if pp["awake_in_view"] > 0)
    frac = aiv / n_frames if n_frames else 0.0
    out.append((">= 30%% of frames have an awake monster in view", frac >= MIN_AWAKE_IN_VIEW,
                "%d/%d = %.1f%%" % (aiv, n_frames, 100 * frac)))
    kills = sum(r["totals"]["kills"] for r in runs_metrics)
    out.append((">= %d kills across the set" % MIN_KILLS, kills >= MIN_KILLS, "%d kills" % kills))
    kinds = {"hitscan": sum(r["totals"]["mon_shots"] for r in runs_metrics),
             "melee": sum(r["totals"]["mon_melee"] for r in runs_metrics),
             "fireball": sum(r["totals"]["proj_spawns"] for r in runs_metrics)}
    out.append(("all three attack kinds (hitscan, melee, fireball)", all(v > 0 for v in kinds.values()),
                ", ".join("%s %d" % kv for kv in kinds.items())))
    picks = sum(r["totals"]["pickups"] for r in runs_metrics)
    out.append((">= %d pickups across the set" % MIN_PICKUPS, picks >= MIN_PICKUPS,
                "%d pickups" % picks))
    worst = None
    for r in runs_metrics:
        f = r["moving"] / r["move_frames"] if r["move_frames"] else 0.0
        if worst is None or f < worst[0]:
            worst = (f, r["name"], r["moving"], r["move_frames"])
    out.append(("every run moves on >= 60% of its movement frames",
                worst is not None and worst[0] >= MIN_MOVING,
                "worst %s: %d/%d = %.0f%%" % (worst[1], worst[2], worst[3], 100 * worst[0])
                if worst else "no runs"))
    exits = sum(r["totals"]["level_done"] for r in runs_metrics)
    out.append(("no run uses the exit", exits == 0, "%d" % exits))
    return out


def dist_stats(vals) -> str:
    s = sorted(vals)
    if not s:
        return "-"
    p = lambda q: s[min(len(s) - 1, math.ceil(q * len(s)) - 1)]    # noqa: E731
    return "mean %.2f p50 %d p80 %d p99 %d max %d" % (sum(s) / len(s), p(0.5), p(0.8), p(0.99), s[-1])


def validate(doc: dict, quiet=False) -> dict:
    """replay every run of `doc`; return {"criteria": [...], "fresh": bool, "metrics": [...]}"""
    metrics, stale = [], []
    now = code_hashes()
    frozen = doc.get("hashes", {})
    changed = sorted(k for k in now if frozen.get(k) != now[k] and k != "scratchpad/gp/scenarios.py")
    for run in doc["runs"]:
        cp = run["checkpoint"]
        pose = (cp["x16"], cp["y16"], cp["angle"])
        keys = [str_to_keys(s) for s in run["keys"]]
        rep = replay(pose, keys)
        rep["name"] = run["name"]
        if rep["poses"] != run["poses"] or rep["digest"] != run["model_final_digest"]:
            stale.append(run["name"])
        metrics.append(rep)
    crit = criteria(metrics)
    crit.append(("the frozen poses and final digests replay exactly (freeze intact)", not stale,
                 "stale: %s" % stale if stale else "%d/%d runs" % (len(metrics), len(metrics))))
    if not quiet:
        print("  %-22s %4s %5s %5s %5s %5s %5s %5s %6s %6s %6s %5s"
              % ("run", "hp", "kills", "hits", "shots", "melee", "fball", "picks", "aiv%",
                 "move%", "divpos", "divdr"))
        for r in metrics:
            t = r["totals"]
            aiv = sum(1 for pp in r["pops"] if pp["awake_in_view"])
            print("  %-22s %4d %5d %5d %5d %5d %5d %5d %5.0f%% %5.0f%% %6d %5d"
                  % (r["name"], r["health"], t["kills"], t["hits"], t["mon_shots"], t["mon_melee"],
                     t["proj_spawns"], t["pickups"], 100.0 * aiv / len(r["pops"]),
                     100.0 * r["moving"] / max(1, r["move_frames"]), r["div_pose"], r["div_door"]))
        allp = [pp for r in metrics for pp in r["pops"]]
        print("  POPULATION per frame over the set (%d frames):" % len(allp))
        for k in ("awake", "in_view", "awake_in_view", "corpses_in_view", "fireballs", "deferred",
                  "heavy"):
            print("    %-16s %s" % (k, dist_stats([pp[k] for pp in allp])))
        print("  B0 comparability: %d frames where blocked27's step parts from the model's pose, "
              "%d with a door state apart, %d with the player blocked by a thing"
              % (sum(r["div_pose"] for r in metrics), sum(r["div_door"] for r in metrics),
                 sum(r["blocked_by_thing"] for r in metrics)))
        if changed:
            print("  NOTE: model files changed since the freeze: %s" % changed)
        for name, ok, det in crit:
            print("  %-66s %s  %s" % (name, "PASS" if ok else "FAIL", det))
    return {"criteria": crit, "stale": stale, "metrics": metrics, "changed": changed}


# ================================================================================================
# planning the set
# ================================================================================================
def plan_set() -> dict:
    w0 = new_world()
    reg = regions(w0)
    runs = []
    for cp in CHECKPOINTS:
        pose = resolve(w0, cp)
        sec = w0.leaf_sector[w0.rm.point_in_subsector(w0.cmap, pose[0] >> 16, pose[1] >> 16)]
        assert sec == cp["sector"] and reg.get(sec) == cp["region"], (
            "checkpoint %s: sector %d is in region %s, not %s" % (cp["name"], sec, reg.get(sec),
                                                                 cp["region"]))
        nav = NavGraph.build(w0, (pose[0] >> 16, pose[1] >> 16), tag=cp["name"])
        t0 = time.time()
        keys, pname, tried = plan_run(cp, pose, nav)
        rep = replay(pose, keys)
        print("  %-22s sector %3d (%s) params %-10s tried %s  %.1f s  kills %d pickups %d hp %d"
              % (cp["name"], sec, REGION_NAMES[cp["region"]].split()[0], pname,
                 [t[0] for t in tried], time.time() - t0, rep["totals"]["kills"],
                 rep["totals"]["pickups"], rep["health"]), flush=True)
        runs.append({"name": cp["name"], "region": REGION_NAMES[cp["region"]], "sector": sec,
                     "why": cp["why"],
                     "checkpoint": {"x16": pose[0], "y16": pose[1], "angle": pose[2],
                                    "x": pose[0] >> 16, "y": pose[1] >> 16, "skill": SKILL,
                                    "face": list(cp["face"])},
                     "params": pname, "style": cp.get("style", "fight"),
                     "keys": [keys_to_str(k) for k in keys],
                     "poses": rep["poses"], "model_final_digest": rep["digest"],
                     "totals": rep["totals"]})
    doc = {"version": "v1", "status": "DRAFT -- frozen only when the owner signs it off (D2)",
           "map": "E1M1", "skill": "hard", "frames": FRAMES, "tics_per_frame": 1,
           "start_state": "level start (monsters asleep at spawn, doors shut, nothing taken, "
                          "pistol + 50 bullets + 100 health); only the player's pose is injected",
           "aim": "doomfj.combat.aim_geometric (the model default)",
           "keys_legend": {c: n for n, c in LETTERS}, "git_head": git_head(),
           "hashes": code_hashes(), "runs": runs}
    return doc


# ================================================================================================
# R9 controls
# ================================================================================================
def selftest(doc: dict) -> int:
    fails = []

    def check(name, cond, detail=""):
        print("  %-70s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    import copy
    base = validate(doc, quiet=True)
    by = {n: ok for n, ok, _d in base["criteria"]}
    check("S0 the frozen set passes every criterion", all(by.values()),
          ", ".join(n for n, ok in by.items() if not ok))

    def verdict(mut, crit_prefix):
        res = validate(mut, quiet=True)
        return next(ok for n, ok, _d in res["criteria"] if n.startswith(crit_prefix)), res

    # S1 no fire anywhere -> no kills: the kills criterion must FAIL
    m1 = copy.deepcopy(doc)
    for run in m1["runs"]:
        run["keys"] = [k.replace("F", "") or "-" for k in run["keys"]]
    ok, _ = verdict(m1, ">= %d kills" % MIN_KILLS)
    check("S1 a set with no fire key has no kills and FAILS the kills criterion", not ok)
    # S2 nobody moves -> vacuous movement criterion must FAIL (0 movement frames is not a pass)
    m2 = copy.deepcopy(doc)
    for run in m2["runs"]:
        run["keys"] = [k.replace("f", "").replace("b", "") or "-" for k in run["keys"]]
    ok, _ = verdict(m2, "every run moves")
    check("S2 a set with no movement keys FAILS the movement criterion (vacuity)", not ok)
    # S3 facing away and silent -> nothing awake in view
    m3 = copy.deepcopy(doc)
    for run in m3["runs"]:
        run["checkpoint"]["angle"] = (run["checkpoint"]["angle"] + (1 << 31)) & M32
        run["keys"] = ["-"] * len(run["keys"])
    ok, _ = verdict(m3, ">= 30%")
    check("S3 a silent set facing away FAILS the awake-in-view criterion", not ok)
    # S4 one key changed in one run -> the freeze check must FAIL (stale poses)
    m4 = copy.deepcopy(doc)
    k0 = m4["runs"][0]["keys"]
    k0[10] = "l" if k0[10] != "l" else "r"
    ok, _ = verdict(m4, "the frozen poses")
    check("S4 one key changed in one run FAILS the freeze check", not ok)
    # S5 the criteria's logic on synthetic metrics: a death, and a set without fireballs
    fake = copy.deepcopy(base["metrics"])
    fake[0]["dead"] = 1
    check("S5 a run that died FAILS 'every run survives'",
          not next(ok for n, ok, _d in criteria(fake) if n == "every run survives"))
    fake = copy.deepcopy(base["metrics"])
    for r in fake:
        r["totals"]["proj_spawns"] = 0
    check("S5 a set without a fireball FAILS the attack-kinds criterion",
          not next(ok for n, ok, _d in criteria(fake) if n.startswith("all three")))
    fake = copy.deepcopy(base["metrics"])
    for r in fake:
        r["totals"]["pickups"] = 0
    check("S5 a set without pickups FAILS the pickups criterion",
          not next(ok for n, ok, _d in criteria(fake) if n.startswith(">= %d pickups" % MIN_PICKUPS)))
    # S6 determinism of the planner: re-planning one checkpoint gives the same keys
    w0 = new_world()
    cp = CHECKPOINTS[0]
    pose = resolve(w0, cp)
    nav = NavGraph.build(w0, (pose[0] >> 16, pose[1] >> 16), tag=cp["name"])
    keys, _pn, _t = plan_run(cp, pose, nav)
    check("S6 the planner is deterministic (checkpoint 0 re-planned = frozen keys)",
          [keys_to_str(k) for k in keys] == doc["runs"][0]["keys"])
    # S7 the binary mirror has teeth: a monster planted 40 units in front of the player makes the
    # model refuse the step that blocked27 (the mirror) takes; with the monster away, no parting
    def mirror_parts(plant: bool) -> int:
        run = doc["runs"][0]["checkpoint"]
        w = start_world((run["x16"], run["y16"], run["angle"]))
        m = next(i for i in range(w.layout.nmon) if w.ws.mon_active[i])
        if plant:
            a = run["angle"] / (1 << 32) * 2 * math.pi
            w.teleport_monster(m, run["x"] + int(round(40 * math.cos(a))),
                               run["y"] + int(round(40 * math.sin(a))))
        mirror = BinaryMirror(w)
        pre, parts = (run["x16"], run["y16"], run["angle"]), 0
        for _ in range(4):
            kd = {"forward": True}
            w.tic(kd)
            post = (w.ws.px, w.ws.py, w.ws.pangle)
            parts += mirror.step(pre, kd)[0] != post
            pre = post
        return parts
    p_on, p_off = mirror_parts(True), mirror_parts(False)
    check("S7 the binary mirror parts from the model when a thing blocks, not otherwise",
          p_on > 0 and p_off == 0, "planted %d, clear %d" % (p_on, p_off))
    print("")
    print("SCENARIOS SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                                       "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--regions", action="store_true")
    ap.add_argument("--file", default=str(SCEN_FILE))
    a = ap.parse_args()
    if a.regions:
        w = new_world()
        reg = regions(w)
        for k, nm in enumerate(REGION_NAMES):
            secs = sorted(s for s, v in reg.items() if v == k)
            mons = sum(1 for m in range(w.layout.nmon) if w.ws.mon_active[m]
                       and reg.get(w._mon_sector(m)) == k)
            print("  %-30s %3d sectors, %2d hard monsters" % (nm, len(secs), mons))
        return 0
    if a.plan:
        t0 = time.time()
        doc = plan_set()
        res = validate(doc, quiet=False)
        doc["validation"] = {n: {"ok": ok, "detail": d} for n, ok, d in res["criteria"]}
        SCEN_DIR.mkdir(parents=True, exist_ok=True)
        Path(a.file).write_text(json.dumps(doc, indent=1), encoding="ascii")
        print("  wrote %s (%.0f s)" % (a.file, time.time() - t0))
        return 0 if all(ok for _n, ok, _d in res["criteria"]) else 1
    doc = json.loads(Path(a.file).read_text(encoding="ascii"))
    if a.validate:
        res = validate(doc, quiet=False)
        ok = all(ok for _n, ok, _d in res["criteria"])
        print("VALIDATE %s" % ("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    if a.selftest:
        return selftest(doc)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
