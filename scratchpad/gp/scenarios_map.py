"""scenarios_map.py -- M8 (docs/level-pipeline.md 4): the combat scenario machinery on ANY map, without touching
the hashed checker.

    python scratchpad/gp/scenarios_map.py --map E1M2 --suggest-checkpoints        # -> scenarios/e1m2/checkpoints.json
    python scratchpad/gp/scenarios_map.py --map E1M2 --plan --file scratchpad/gp/scenarios/combat_scenarios_e1m2_v1.json
    python scratchpad/gp/scenarios_map.py --validate --file <a set>               # the map from the set's "map"
    python scratchpad/gp/scenarios_map.py --selftest                              # R9 + E1M1 untouched (oracle)

WHY A SIDECAR. scenarios_v2.py is the CHECKER of every frozen combat set: its bytes are hashed into each set
(`PLANNER_FILE`) and a change to it needs a reviewer-named re-freeze of v10 (scenarios/README.md). census_lib.py is
hashed too. Both hard-wire E1M1 (the fixture wad in MODEL_FILES, `World()` with no map, the census's "E1M1" literals,
v1's region flood with E1M1's lifts and doors). So nothing here edits them: `install(map)` patches THEIR MODULE
NAMESPACES in this process, for a map other than E1M1 only --
  scenarios_v2: MODEL_FILES (the map's fixture wad in place of E1M1's: the set's hashes and the nav cache key follow
                the map), CENSUS_FILES (+ this file), new_world (World on the map), regions (the flood below),
                CHECKPOINTS (the map's), plan_set (the doc names its map);
  census_lib:   its WadFile (the E1M1 fixture path opens the map's wad, whose "E1M1" lookups mean the map), its World
                (on the map), SimState / build_scene (the "E1M1" literal means the map).
On E1M1 `install` does NOTHING: the frozen sets replay through the untouched files (`--selftest` checks the modules
are the originals afterwards).

THE REGION FLOOD (`regions_map`): v1's (scenarios.regions: the doors region the player starts in, the walk-over
doors, behind the lifts, behind the KEY doors, the floor switch) with the map's own LIFTS (movers), W1 doors (the
walk-over kind), LOWER (the floor switch's sectors) and key doors of EVERY colour by line special. On E1M1 it equals
v1's flood (checked by `--selftest`).

SUGGESTED CHECKPOINTS (`suggest`): per region of the flood, the sectors with the most wakeable monsters at hard within
ENGAGE units, at least SPREAD apart; runs per region in proportion to its monsters (each region with >= 5 gets one);
a standable spot in the sector as far from the nearest monster as STANDOFF allows, facing the group's centroid; the
style by what lies near (pickups: collect); one AFTERMATH run: the tightest trio of droppers / imps in region 0
injected as corpses, the player among them (v2's R0-aftermath). A checkpoint whose run no parameter set survives is
replaced by the region's next suggestion (`plan`). The PLAN is not frozen: the owner approves a freeze (as v5..v10).
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "tests", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", HERE, ROOT):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))
if __name__ == "__main__":
    from doomfj.mapprofile import take_map_arg
    take_map_arg()

E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"
ENGAGE = 640               # a checkpoint's group: the monsters within this many units
SPREAD = 768               # checkpoints at least this far apart
STANDOFF = 256             # the start spot's wanted distance from the nearest monster
N_RUNS = 11                # v10's shape: 11 runs x 100 frames
KEY_SPECIALS = (26, 27, 28, 32, 33, 34)
INSTALLED = {"map": "E1M1"}
_ORIGINALS = {}


# ================================================================================================
# install: the map into scenarios_v2 / census_lib (nothing on E1M1)
# ================================================================================================
def install(mapname: str, checkpoints=None) -> None:
    import scenarios_v2 as S
    import census_lib as CL
    from doomfj import world as W
    from doomfj import reference_model as RMOD
    from doomfj.mapprofile import profile
    from doomfj.wad import WadFile
    m = mapname.upper()
    if INSTALLED["map"] == m:
        if checkpoints is not None:
            S.CHECKPOINTS = tuple(checkpoints)
        return
    assert INSTALLED["map"] == "E1M1", "one map per process: %s is installed, %s asked" % (INSTALLED["map"], m)
    if m == "E1M1":
        return
    wad = profile(m).wad
    INSTALLED["map"] = m
    for mod, names in ((S, ("MODEL_FILES", "CENSUS_FILES", "new_world", "regions", "CHECKPOINTS", "plan_set")),
                       (CL, ("WadFile", "W", "SimState", "build_scene"))):
        for n in names:
            _ORIGINALS[(mod.__name__, n)] = getattr(mod, n)
    S.MODEL_FILES = tuple(wad if f == E1M1_WAD else f for f in S.MODEL_FILES)
    S.CENSUS_FILES = tuple(S.CENSUS_FILES) + ("scratchpad/gp/scenarios_map.py",)
    mw = WadFile.from_path(str(ROOT / wad))

    def new_world():
        return S.apply_sight_rule(W.World(mw, m, skill=S.SKILL, player=S.PLAYER_MODE, monsters=S.MONSTER_MODE))
    S.new_world = new_world
    S.regions = regions_map
    if checkpoints is not None:
        S.CHECKPOINTS = tuple(checkpoints)
    plan_set0 = S.plan_set

    def plan_set(quiet=False):
        doc = plan_set0(quiet)
        doc["map"] = m
        return doc
    S.plan_set = plan_set

    # census_lib: its fixture path opens the map's wad, whose "E1M1" lookups mean the map
    def _translated(fname):
        base = getattr(WadFile, fname)

        def f(self, mapname, _b=base):
            return _b(self, m if mapname == "E1M1" else mapname)
        f.__name__ = fname
        return f
    _MapWad = type("_MapWad", (WadFile,), {f: _translated(f) for f in (
        "vertexes", "linedefs", "sidedefs", "sectors", "things", "segs", "subsectors", "nodes", "nodes_bbox")})

    class _Wad:
        @staticmethod
        def from_path(path):
            if str(path).replace("\\", "/").endswith(E1M1_WAD):
                w = WadFile.from_path(str(ROOT / wad))
                w.__class__ = _MapWad
                return w
            return WadFile.from_path(path)

    class _W:
        def __getattr__(self, n):
            return getattr(W, n)

        @staticmethod
        def World(*a, **kw):
            kw.setdefault("mapname", m)
            return W.World(*a, **kw)
    CL.WadFile, CL.W = _Wad, _W()
    CL.SimState = lambda x, y, a, name, *r, **kw: RMOD.SimState(x, y, a, m if name == "E1M1" else name, *r, **kw)
    CL.build_scene = lambda a, b, name, *r, **kw: RMOD.build_scene(a, b, m if name == "E1M1" else name, *r, **kw)


def use_doc(doc: dict) -> None:
    """a set's map and sight rule (b0_scenarios / --validate): install the map the set names, then scenarios_v2's
    use_sight_rule"""
    import scenarios_v2 as S
    m = doc.get("map", "E1M1").upper()
    cps = None
    if m != "E1M1":
        cps = load_checkpoints(m)
    install(m, cps)
    S.use_sight_rule(doc)


def checkpoints_path(mapname: str) -> Path:
    from doomfj.mapprofile import scenario_dir
    return scenario_dir(mapname) / "checkpoints.json"


def load_checkpoints(mapname: str):
    p = checkpoints_path(mapname)
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding="ascii"))
    return [dict(c, want=tuple(c["want"]), face=tuple(c["face"]), corpses=tuple(c.get("corpses", ())))
            if c.get("corpses") else dict(c, want=tuple(c["want"]), face=tuple(c["face"]))
            for c in doc["checkpoints"]]


# ================================================================================================
# the region flood, the map's own movers and key doors
# ================================================================================================
def regions_map(w) -> dict:
    """sector -> progression stage (v1's STAGES), on any map: v1's flood with the map's lifts, W1 doors, floor-switch
    sectors and key doors (every colour)"""
    import scenarios as V1
    from doomfj import doors as D
    from doomfj.movers import lift_states, switch_sectors
    lds, sds, secs = w.lds, w.sds, w.secs
    ds = D.door_sectors(secs, lds, sds)
    nb = D.neighbours(lds, sds)
    kinds = D.door_kinds(secs, lds, sds)
    LIFTS = tuple(sorted(lift_states(secs, lds, sds)))
    W1DOORS = tuple(sorted(si for si, k in kinds.items() if k == "walkover"))
    LOWER = tuple(sorted(switch_sectors(secs, lds, sds)))

    def side_sec(sd):
        return sds[sd].sector if sd != 0xFFFF and 0 <= sd < len(sds) else None

    keyed = {side_sec(ld.back) for ld in lds if ld.special in KEY_SPECIALS}
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
            if s not in keyed or "key" in stage:
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
    for k, st in enumerate(V1.STAGES):
        r = flood(st)
        for s in r - prev:
            out[s] = k
        prev = r
    return out


# ================================================================================================
# the suggested checkpoints
# ================================================================================================
def _standable(w, x, y):
    x16, y16 = x << 16, y << 16
    return w.rm.try_move(w.scene_c, x16, y16, x16, y16) and w._solid_thing_at(x16, y16) is None


def _sector_points(w, sec, step=32):
    xs = [w.cmap.vertexes[v][0] for ld in w.lds for side in (ld.front, ld.back)
          if 0 <= side < len(w.sds) and w.sds[side].sector == sec for v in (ld.v1, ld.v2)]
    ys = [w.cmap.vertexes[v][1] for ld in w.lds for side in (ld.front, ld.back)
          if 0 <= side < len(w.sds) and w.sds[side].sector == sec for v in (ld.v1, ld.v2)]
    if not xs:
        return []
    return [(x, y) for x in range(min(xs) + 16, max(xs) - 15, step) for y in range(min(ys) + 16, max(ys) - 15, step)
            if w.leaf_sector[w.rm.point_in_subsector(w.cmap, x, y)] == sec and _standable(w, x, y)]


def suggest(n_runs: int = N_RUNS) -> dict:
    """-> {"checkpoints": [...], "reserve": [...], "regions": {...}} for the installed map (scenarios_v2.CHECKPOINTS'
    shape: name, sector, want, face, region, style, why; the aftermath with corpses)"""
    import scenarios_v2 as S
    w = S.new_world()
    reg = regions_map(w)
    ws = w.ws
    mons = []
    for k in range(w.layout.nmon):
        if not ws.mon_active[k]:
            continue
        x, y = ws.mon_x[k], ws.mon_y[k]
        sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, x, y)]
        mons.append((k, x, y, sec, w.mon_info[k].name))
    by_region = collections.Counter(reg.get(s) for _k, _x, _y, s, _n in mons)
    pk = [t for t in w.pickup_things if t.flags & __import__("doomfj.gamedata", fromlist=["x"]).skill_bit(S.SKILL)]
    # every reached sector with a monster group, scored
    cand = []
    for sec, r in sorted(reg.items()):
        pts = _sector_points(w, sec)
        if not pts:
            continue
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        group = [m for m in mons if math.hypot(m[1] - cx, m[2] - cy) <= ENGAGE and reg.get(m[3]) is not None]
        if len(group) < 2:
            continue
        gx = sum(m[1] for m in group) / len(group)
        gy = sum(m[2] for m in group) / len(group)

        def near(p):
            return min(math.hypot(m[1] - p[0], m[2] - p[1]) for m in mons)
        spot = max(pts, key=lambda p: (min(near(p), STANDOFF), -math.hypot(p[0] - gx, p[1] - gy), p))
        items = sum(1 for t in pk if math.hypot(t.x - spot[0], t.y - spot[1]) <= 512)
        kinds = collections.Counter(m[4] for m in group)
        cand.append({"score": len(group), "sector": sec, "region": r, "want": spot,
                     "face": (int(round(gx)), int(round(gy))), "items": items, "kinds": dict(kinds),
                     "nearest": int(near(spot))})
    cand.sort(key=lambda c: (-c["score"], c["sector"]))
    regions_with = sorted(r for r, n in by_region.items() if r is not None and n >= 5)
    total = sum(by_region[r] for r in regions_with) or 1
    quota = {r: max(1, round((n_runs - 1) * by_region[r] / total)) for r in regions_with}
    while sum(quota.values()) > n_runs - 1:
        r = max(quota, key=lambda r: (quota[r], r))
        quota[r] -= 1
    while sum(quota.values()) < n_runs - 1:
        r = max(regions_with, key=lambda r: (by_region[r] / quota[r], -r))
        quota[r] += 1
    chosen = []
    for spread in (SPREAD, SPREAD // 2, SPREAD // 4, 0):        # the spread relaxed until every quota fills
        for c in cand:
            if c["region"] not in quota or c in chosen:
                continue
            far = all(math.hypot(c["want"][0] - o["want"][0], c["want"][1] - o["want"][1]) >= spread
                      for o in chosen)
            if far and sum(1 for o in chosen if o["region"] == c["region"]) < quota[c["region"]]:
                chosen.append(c)
        short = {r: quota[r] - sum(1 for o in chosen if o["region"] == r) for r in quota}
        if not any(short.values()):
            break
        if spread == SPREAD // 4:                               # a region with too few groups: its runs move
            for r, k in short.items():                         # to the region with the most monsters
                if k > 0 and not [c for c in cand if c["region"] == r and c not in chosen]:
                    quota[r] -= k
                    quota[max(quota, key=lambda q: (by_region[q], -q))] += k
    reserve = [c for c in cand if c not in chosen and c["region"] in quota]
    styles = ("fight", "collect", "fight", "explore")
    out = []
    names = collections.Counter()
    for i, c in enumerate(sorted(chosen, key=lambda c: (c["region"], -c["score"], c["sector"]))):
        names[c["region"]] += 1
        style = "collect" if c["items"] >= 6 and i % 2 else styles[i % len(styles)]
        out.append(_cp(c, "R%d-s%d" % (c["region"], c["sector"]), style))
    # the aftermath: the tightest trio of droppers / imps in the start region, as corpses, the player among them
    trio_kinds = ("MT_POSSESSED", "MT_SHOTGUY", "MT_TROOP")
    r0 = [m for m in mons if reg.get(m[3]) == min(regions_with or [0]) and m[4] in trio_kinds]
    best = None
    for a in r0:
        near3 = sorted(r0, key=lambda m: (math.hypot(m[1] - a[1], m[2] - a[2]), m[0]))[:3]
        if len(near3) < 3:
            continue
        cx = sum(m[1] for m in near3) / 3
        cy = sum(m[2] for m in near3) / 3
        spread = max(math.hypot(m[1] - cx, m[2] - cy) for m in near3)
        if spread > 140:
            continue
        sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, int(cx), int(cy))]
        key = (spread, a[0])
        if reg.get(sec) is not None and (best is None or key < best[0]):
            best = (key, near3, (int(round(cx)), int(round(cy))), sec)
    if best is not None:
        _key, trio, (cx, cy), sec = best
        out.insert(1, {"name": "R%d-aftermath" % reg[sec], "sector": sec, "want": (cx, cy),
                       "face": (trio[0][1], trio[0][2]), "region": reg[sec], "style": "collect",
                       "corpses": tuple(m[0] for m in trio),
                       "why": "AFTERMATH: %s (slots %s) injected as corpses at their spawns, the player among "
                              "them -- the post-kill drawing (corpses, drops)"
                              % (", ".join(m[4] for m in trio), [m[0] for m in trio])})
    else:
        out.append(_cp(reserve.pop(0), "R%d-extra" % reserve[0]["region"], "fight"))
    return {"map": INSTALLED["map"], "checkpoints": out,
            "reserve": [_cp(c, "R%d-s%d" % (c["region"], c["sector"]), "fight") for c in reserve[:30]],
            "regions": {"sectors_per_region": dict(collections.Counter(reg.values())),
                        "monsters_per_region": {str(k): v for k, v in by_region.items()},
                        "quota": quota, "rule": "regions_map: v1's stages with the map's lifts, W1 doors, floor "
                                                "switch and key doors (every colour)"}}


def _cp(c, name, style):
    kinds = ", ".join("%d %s" % (v, k) for k, v in sorted(c["kinds"].items()))
    return {"name": name, "sector": c["sector"], "want": tuple(c["want"]), "face": tuple(c["face"]),
            "region": c["region"], "style": style,
            "why": "region %d: %d monsters within %d units (%s), the nearest %d units from the start; %d pickups "
                   "within 512" % (c["region"], c["score"], ENGAGE, kinds, c["nearest"], c["items"])}


# ================================================================================================
# the plan: scenarios_v2's plan_set, a refused checkpoint replaced from the reserve
# ================================================================================================
def plan(sugg: dict, quiet: bool = False) -> dict:
    import scenarios_v2 as S
    w0 = S.new_world()
    reg = regions_map(w0)
    runs, used = [], []
    reserve = [dict(c, want=tuple(c["want"]), face=tuple(c["face"])) for c in sugg.get("reserve", ())]
    for cp in [dict(c, want=tuple(c["want"]), face=tuple(c["face"])) for c in sugg["checkpoints"]]:
        queue = [cp] + [r for r in reserve if r["region"] == cp["region"] and not cp.get("corpses")]
        for c in queue:
            if c["name"] in used:
                continue
            try:
                t0 = time.time()
                setup = S.make_setup(c)
                pose = setup["pose"]
                sec = w0.leaf_sector[w0.rm.point_in_subsector(w0.cmap, pose[0] >> 16, pose[1] >> 16)]
                assert sec == c["sector"] and reg.get(sec) == c["region"], (c["name"], sec, reg.get(sec))
                nav = S.NavGraph.build(w0, (pose[0] >> 16, pose[1] >> 16), tag=c["name"])
                keys, pname, tried = S.plan_run(c, setup, nav)
            except AssertionError as e:
                print("  %-22s REFUSED (%s) -- the region's next suggestion" % (c["name"], str(e)[:120]), flush=True)
                used.append(c["name"])
                continue
            used.append(c["name"])
            run = {"name": c["name"], "region": S.REGION_NAMES[c["region"]], "sector": sec,
                   "why": c["why"], "style": c.get("style", "fight"), "params": pname, "setup": setup,
                   "checkpoint": {"x16": pose[0], "y16": pose[1], "angle": pose[2], "x": pose[0] >> 16,
                                  "y": pose[1] >> 16, "skill": S.SKILL, "face": list(c["face"])},
                   "keys": [S.keys_to_str(k) for k in keys]}
            rep = S.replay(run)
            run.update({"poses": rep["poses"], "model_final_digest": rep["digest"], "totals": rep["totals"]})
            if not quiet:
                print("  %-22s sector %3d params %-10s tried %-40s %5.1f s  kills %d picks %d doors %s hp %d "
                      "move %d%% strafe %d%%" % (c["name"], sec, pname, [t for t in tried], time.time() - t0,
                                                 rep["totals"]["kills"], rep["totals"]["pickups"],
                                                 rep["doors_player"], rep["health"], rep["move_key"], rep["strafe"]),
                      flush=True)
            runs.append(run)
            break
    return {"version": S.VERSION,
            "status": "PLANNED -- a PLAN for the owner's review: B0 and the owner's freeze pending (`--freeze`)",
            "player_mode": S.PLAYER_MODE, "monster_mode": S.MONSTER_MODE,
            "map": INSTALLED["map"], "skill": "hard", "frames": S.FRAMES, "tics_per_frame": 1,
            "start_state": "level start (monsters asleep at spawn, doors shut, nothing taken, pistol + 50 bullets + "
                           "100 health); injected: the player's pose, and the aftermath run's corpses (setup.corpses)",
            "aim": "doomfj.combat.aim_geometric (the model default)",
            "census_picture": S.CENSUS_PICTURE,
            "keys_legend": {c: n for n, c in S.LETTERS},
            "checkpoints_from": "scratchpad/gp/scenarios_map.py --suggest-checkpoints (scenarios/%s/checkpoints.json)"
                                % INSTALLED["map"].lower(),
            "runs": runs}


# ================================================================================================
# the selftest (oracle only)
# ================================================================================================
def selftest() -> int:
    fails = []

    def check(name, ok, detail=""):
        print("  %-78s %s%s" % (name, "PASS" if ok else "FAIL", "  (%s)" % detail if detail else ""), flush=True)
        if not ok:
            fails.append(name)
    import scenarios_v2 as S
    import census_lib as CL
    import scenarios as V1
    orig = {n: getattr(S, n) for n in ("MODEL_FILES", "CENSUS_FILES", "new_world", "regions", "CHECKPOINTS")}
    orig_cl = {n: getattr(CL, n) for n in ("WadFile", "W", "SimState", "build_scene")}
    install("E1M1")
    check("T1 install(E1M1) leaves scenarios_v2 and census_lib untouched",
          all(getattr(S, n) is v for n, v in orig.items()) and all(getattr(CL, n) is v for n, v in orig_cl.items()))
    w = S.new_world()
    a, b = V1.regions(w), regions_map(w)
    check("T2 regions_map on E1M1 equals v1's flood (scenarios.regions)", a == b,
          "%d sectors, stages %s" % (len(b), sorted(collections.Counter(b.values()).items())))
    # R9: the flood must SEE the map's key doors -- E1M1's blue doors treated as plain move sectors to R0
    import doomfj.doors as D
    saved = D.door_sectors
    try:
        keep = KEY_SPECIALS
        globals()["KEY_SPECIALS"] = ()
        c = regions_map(w)
    finally:
        globals()["KEY_SPECIALS"] = keep
        D.door_sectors = saved
    check("T3 CONTROL: without the key doors the flood differs (R3 joins earlier stages)", c != b,
          "%d sectors change stage" % sum(1 for s in b if c.get(s) != b[s]))
    print("SELFTEST %s" % ("PASS" if not fails else "FAIL: %s" % fails))
    return 1 if fails else 0


def main(argv=None) -> int:
    from doomfj.mapprofile import ACTIVE
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--suggest-checkpoints", action="store_true")
    ap.add_argument("--plan", action="store_true", help="plan the set from scenarios/<map>/checkpoints.json")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--no-census", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--runs", type=int, default=N_RUNS)
    ap.add_argument("--only", help="--plan: only the checkpoints whose name starts with this (a trial)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    import scenarios_v2 as S
    from doomfj import world as W
    if a.validate:
        doc = json.loads(Path(a.file).read_text(encoding="ascii"))
        use_doc(doc)
        t0 = time.time()
        res = S.validate(doc, census=not a.no_census, quiet=False)
        okc = all(ok for _n, ok, _d in res["criteria"])
        okf = all(ok for _n, ok, _d in res["freeze"])
        print("%s: CRITERIA %s | FREEZE %s (%.0f s)" % (doc.get("map", "E1M1"), "PASS" if okc else "FAIL",
                                                        "PASS" if okf else "FAIL", time.time() - t0))
        return 0 if okc and okf else 1
    m = ACTIVE
    if m == "E1M1":
        ap.error("E1M1's sets are scenarios_v2.py's own (this tool is for another map: --map E1Mn)")
    from doomfj.wall_renderer import MONSTER_MODE as MM, PLAYER_MODE as PM
    S.use_sight_rule({"sight_rule": "seen", "monster_tics": W.MONSTER_TICS_PER_FRAME, "player_mode": PM,
                      "monster_mode": MM})
    install(m)
    cpath = checkpoints_path(m)
    if a.suggest_checkpoints:
        t0 = time.time()
        sug = suggest(a.runs)
        sug["provenance"] = {"tool": "scratchpad/gp/scenarios_map.py --suggest-checkpoints",
                             "sight_rule": S.SIGHT_RULE, "player_mode": PM, "monster_mode": MM,
                             "seconds": round(time.time() - t0)}
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps(sug, indent=1) + "\n", encoding="ascii", newline="\n")
        for c in sug["checkpoints"]:
            print("  %-16s sector %4d region %d want %-14s face %-14s %-8s %s" % (
                c["name"], c["sector"], c["region"], tuple(c["want"]), tuple(c["face"]), c["style"], c["why"][:90]))
        print("regions: %s" % sug["regions"])
        print("wrote %s (%d checkpoints, %d in reserve)" % (cpath, len(sug["checkpoints"]), len(sug["reserve"])))
        return 0
    if a.plan:
        sug = json.loads(cpath.read_text(encoding="ascii"))
        if a.only:
            sug = dict(sug, checkpoints=[c for c in sug["checkpoints"] if c["name"].startswith(a.only)])
        import re
        v = re.search(r"_(v\d+)\.json$", Path(a.file).name)
        S.VERSION = v.group(1) if v else S.VERSION
        why = S.plan_refusal(Path(a.file))
        if why:
            print("PLAN REFUSED: %s" % why)
            return 1
        t0 = time.time()
        doc = plan(sug)
        doc["sight_rule"], doc["monster_tics"] = S.SIGHT_RULE, S.MONSTER_TICS
        res = S.validate(doc, census=not a.no_census, quiet=False)
        S.record_validation(doc, res)
        doc["hashes"] = S.code_hashes()
        doc["planned_at_git_head"] = S.git_head()
        doc["keys_sha"] = S.keys_sha(doc)
        Path(a.file).write_text(json.dumps(doc, indent=1), encoding="ascii", newline="\n")
        ok = all(ok for _n, ok, _d in res["criteria"])
        print("  wrote %s (%.0f s): %d runs, criteria %s, keys %s" % (
            a.file, time.time() - t0, len(doc["runs"]), "PASS" if ok else "FAIL", doc["keys_sha"]))
        for n, okc, d in res["criteria"]:
            print("    %-50s %s %s" % (n, "PASS" if okc else "FAIL", d))
        return 0 if ok else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
