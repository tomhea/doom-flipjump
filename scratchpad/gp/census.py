"""S5 -- THE COMPOSITOR CENSUS and the FIGHT LINE (docs/plan-gameplay.md sections 5 and 7).

    python scratchpad/gp/census.py [--scen NAME[,NAME...]] [--tics N] [--every K]
    python scratchpad/gp/census.py --scenarios scratchpad/gp/scenarios/combat_scenarios_v1.json

Each scenario runs the gameplay model (doomfj.world) tic by tic; after every K-th tic the ORACLE
renders the frame the player sees under several pictures and compositor rules (census_lib does the
wiring and proves it pixel-neutral: census_control.py). One JSON line per (frame, variant) goes to
scratchpad/gp/census_out/<scenario>.jsonl; census_report.py turns them into the tables.

VARIANTS (the D3 options of plan section 5, plus two references):
  today    blocked27's picture at this viewpoint: every WAD thing at spawn, today's art and rules (B0)
  todayR4  the same, skill-filtered (the R4 filter) -- the fight line's baseline
  game     the model's picture under TODAY's compositor rules: animated monsters, corpses, drops,
           fireballs, puffs/blood, exploding barrels (size stand-ins, census_lib docstring)
  a        (a) drops and effects ordered before monsters
  b        (b) awake monsters, projectiles and barrels exempt from the soft budgets
  c        (c) corpses count as scenery
  d        (d) depth order among runtime things inside a leaf
  abcd     all four together
(e) -- "seen" and the aim window recorded at column-open time, before the budget test -- changes no
pixel; every variant's record carries its (e) versions of seen and aim alongside the drawn ones.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import census_lib as CL                                                     # noqa: E402
from census_lib import gd, W                                                # noqa: E402

OUT = HERE / "census_out"
VARIANTS_ONLY = None
LETTERS = {"f": "forward", "b": "back", "l": "turn_left", "r": "turn_right", "u": "use",
           "F": "fire", "K": "w1", "P": "w2", "S": "w3", "C": "w4", "-": None}


def keys_of(script: str) -> list:
    import re
    out = []
    for tok in script.split():
        m = re.fullmatch(r"([fblruFKPSC-]+)(\d*)", tok)
        held = {LETTERS[ch]: True for ch in m.group(1) if LETTERS[ch]}
        out += [dict(held) for _ in range(int(m.group(2) or 1))]
    return out


def place(w, spec):
    ws, placed = w.ws, []
    px, py = ws.px >> 16, ws.py >> 16
    for num, dx, dy in spec:
        m = next(m for m in range(w.layout.nmon)
                 if w.mon_things[m].type == num and ws.mon_active[m] and m not in placed)
        w.teleport_monster(m, px + dx, py + dy)
        ws.mon_target[m] = 1
        w._set_state(m, w.mon_info[m].seestate, False, W.TicEvents(w.tic_count))
        placed.append(m)
    return placed


def give_shotgun(w):
    ws = w.ws
    ws.p_owned[gd.WP_SHOTGUN] = 1
    ws.p_ammo[gd.AM_SHELL] = 50


# name -> (setup(world), key script); the player starts at (-416, 256) facing east, a corridor that
# opens at dx ~256 into a room (dx 256..768, dy -192..192)
SCENARIOS = {
    "placed_pistol": (lambda w: place(w, [(3004, 300, -40), (3004, 360, 60), (9, 420, 0),
                                          (3001, 500, -100), (3001, 540, 110), (3002, 400, 140)]),
                      "F30 Fl2 F30 Fr4 F30 Fl2 F40 -60"),
    "shotgun_imps": (lambda w: (give_shotgun(w), place(w, [(3001, 280, -60), (3001, 340, 80),
                                                           (3001, 460, -120), (3001, 520, 40),
                                                           (3004, 380, 0), (9, 600, -40)])),
                     "S3 F40 Fl2 F40 Fr4 F40 -71"),
    "demons_close": (lambda w: place(w, [(3002, 200, 0), (3002, 260, 60), (3002, 320, -60),
                                         (3001, 420, 0)]),
                     "F60 b10 F60 -70"),
    "wake_all": (lambda w: w.wake_all(), "f18 F40 fl3 F40 fr6 F40 f10 F43"),
    # the barrel line of sector 134 and the shotgun guys / imps / demon of sector 120, from the side
    "barrel_room": (lambda w: (give_shotgun(w),
                               w.teleport_player(2200 << 16, -420 << 16, 0x15555555)),
                    "S3 F50 Fl3 F40 Fr6 F40 -58"),
    "quiet_walk": (lambda w: None, "f18 l4 f20 r8 f25 l4 f20 r20 f30 l10 f41"),
}


def analyse(c, arr, W_):
    """Per-frame counts of one render (see the module docstring and census_report)."""
    wd, ws = c.world, c.world.ws
    rec = {"arr_rt": 0, "arr_bk": 0, "acc": 0, "colsA": 0, "colsB": 0, "runs": 0,
           "deg": {}, "small": {"things": 0, "part_hidden": 0, "all_hidden": 0, "deg": 0,
                             "hidden_cols": 0, "wanted_cols": 0},
           "inv": {"baked_first": 0, "index": 0, "cross_leaf": 0},
           "inv_pairs": {"baked_first": 0, "index": 0, "cross_leaf": 0},
           "near_hidden": 0, "corpses_acc_soft": 0, "live_deg_after_corpse": 0,
           "rt_leaves_multi": 0, "rt_pairs_in_leaf": 0}
    per_col = [[] for _ in range(W_)]            # (order, tz, slot, arrival)
    wanted_of, base_of = {}, {}
    seen_draw, seen_e = set(), set()
    first_live_deg = None
    corpses_before = 0
    by_leaf_rt = {}

    def cols(r, pr):
        x1, x2, _ytop, _h, istep, _tz = pr
        a, drawn = r["art"], r["drawn"]
        out, frac = [], (max(0, x1) - x1) * istep
        for x in range(max(0, x1), min(W_, x2 + 1)):
            u = min(a[2] - 1, max(0, frac >> 16))
            frac += istep
            if not drawn[x] and any(v >= 0 for v in a[0][u]):
                out.append(x)
        return out

    for k, r in enumerate(arr):
        m = r["meta"]
        role = m.role if m else "static"
        if m is not None and not m.baked:
            rec["arr_rt"] += 1
            by_leaf_rt.setdefault(r["leaf"], []).append(k)
        else:
            rec["arr_bk"] += 1
        res, rb = r["res"], r["rbase"]
        if rb is not None:
            base_of[k] = cols(r, rb)
        if res is not None:
            rec["acc"] += 1
            wanted_of[k] = cols(r, res)
            if role == "corpse" and r["mon"] and r["n_mon"] < 4:
                rec["corpses_acc_soft"] += 1
            if role == "corpse" and r["mon"]:
                corpses_before += 1
        elif rb is not None and r["used"] != r["base"]:
            rec["deg"][role] = rec["deg"].get(role, 0) + 1
            if role == "live" and first_live_deg is None:
                first_live_deg = k
                rec["live_deg_after_corpse"] = corpses_before
        rec["colsA"] += len(r["A"])
        rec["colsB"] += len(r["B"])
        rec["runs"] += r["runs"]
        if r["A"] or r["B"]:
            rk = role + ("_awake" if role == "live" and m.awake else "")
            rec.setdefault("drawn", {})[rk] = rec.setdefault("drawn", {}).get(rk, 0) + 1
            cr = rec.setdefault("cols_role", {})
            cr[role] = cr.get(role, 0) + len(r["A"]) + len(r["B"])
        if m is not None and not m.baked:
            rr = rec.setdefault("arr_role", {})
            rr[role] = rr.get(role, 0) + 1
        if role == "live" and (r["A"] or r["B"]):
            seen_draw.add(m.idx)
        if role == "live" and base_of.get(k):
            seen_e.add(m.idx)
        tz = (res or rb or (0, 0, 0, 0, 0, 0))[5]
        for x in r["A"]:
            per_col[x].append((k, tz, "A", r))
        for x in r["B"]:
            per_col[x].append((k, tz, "B", r))
        if res is not None:
            got = set(r["A"]) | set(r["B"])
            hid = [x for x in wanted_of[k] if x not in got]
            for x in hid:
                per_col[x].append((k, tz, "H", r))
            if role in CL.SMALL:
                s = rec["small"]
                s["things"] += 1
                s["wanted_cols"] += len(wanted_of[k])
                s["hidden_cols"] += len(hid)
                if hid:
                    s["part_hidden"] += 1
                if wanted_of[k] and not got:
                    s["all_hidden"] += 1
        elif rb is not None and role in CL.SMALL and r["used"] != r["base"]:
            rec["small"]["deg"] += 1
    # depth inversions: a farther fragment in front of (or hiding) a nearer one, by class
    pairs = {"baked_first": set(), "index": set(), "cross_leaf": set()}
    for x in range(W_):
        L = per_col[x]
        if len(L) < 2:
            continue
        a = next((e for e in L if e[2] == "A"), None)
        if a is None:
            continue
        hit = set()
        for e in L:
            if e is a or e[1] >= a[1]:
                continue                                  # not nearer than the front fragment
            ra, re_ = a[3], e[3]
            if e[2] == "H":
                rec["near_hidden"] += 1
            if ra["leaf"] != re_["leaf"]:
                cls = "cross_leaf"
            elif ra["meta"] is not None and ra["meta"].baked and not (re_["meta"] and re_["meta"].baked):
                cls = "baked_first"
            else:
                cls = "index"
            hit.add(cls)
            pairs[cls].add((a[0], e[0]))
        for cls in hit:
            rec["inv"][cls] += 1
    for cls in pairs:
        rec["inv_pairs"][cls] = len(pairs[cls])
    for leaf, ks in by_leaf_rt.items():
        if len(ks) > 1:
            rec["rt_leaves_multi"] += 1
            rec["rt_pairs_in_leaf"] += len(ks) * (len(ks) - 1) // 2
    # the aim window: picture (first SHOOTABLE fragment writer) vs (e) vs geometric
    def key_of(meta):
        return ("mon", meta.idx) if meta.role == "live" else ("bar", meta.idx)
    aim = {"pic": 0, "pn": 0, "e": 0, "ed": 0, "pic80": 0, "pn80": 0, "e80": 0, "ed80": 0,
           "geo_any": 0}
    for col in range(CL.AIM_LO, CL.AIM_HI + 1):
        geo = wd.aim_geometric(wd, col)
        if geo is not None:
            aim["geo_any"] += 1
        drawn_sh = [e for e in sorted(per_col[col], key=lambda e: e[0])
                    if e[2] in "AB" and e[3]["meta"] is not None and e[3]["meta"].shoot]
        pic = key_of(drawn_sh[0][3]["meta"]) if drawn_sh else None            # first writer
        pn = key_of(min(drawn_sh, key=lambda e: e[1])[3]["meta"]) if drawn_sh else None  # nearest drawn
        cand = [(k, r) for k, r in enumerate(arr) if r["meta"] is not None and r["meta"].shoot
                and col in base_of.get(k, ())]
        e_first = key_of(cand[0][1]["meta"]) if cand else None
        e_near = key_of(min(cand, key=lambda kr: kr[1]["rbase"][5])[1]["meta"]) if cand else None
        for name, v in (("pic", pic), ("pn", pn), ("e", e_first), ("ed", e_near)):
            if v != geo:
                aim[name] += 1
                if col == 80:
                    aim[name + "80"] += 1
    rec["aim"] = aim
    # seen: picture vs 2D line of sight, for every active LIVE monster
    sn = {"los": 0, "los_drawn": 0, "los_not_drawn": 0, "los_not_drawn_inview": 0,
          "drawn_no_los": 0, "e_los_not": 0, "e_not_los": 0, "e_los_not_inview": 0,
          "why": {}}
    arrived = {r["meta"].idx: r for r in arr if r["meta"] is not None and r["meta"].role == "live"}
    for m in range(wd.layout.nmon):
        if not ws.mon_active[m] or ws.mon_health[m] <= 0:
            continue
        los = W.World.los_to_player(wd, m)
        drawn = m in seen_draw
        r = arrived.get(m)
        inview = r is not None and r["rbase"] is not None
        if los:
            sn["los"] += 1
            if drawn:
                sn["los_drawn"] += 1
            else:
                sn["los_not_drawn"] += 1
                if inview:
                    sn["los_not_drawn_inview"] += 1
                why = ("not reached" if r is None else "out of view" if r["rbase"] is None else
                       "degraded" if r["res"] is None else
                       "wall-occluded" if not base_of.get(next(k for k, q in enumerate(arr) if q is r))
                       else "slots")
                sn["why"][why] = sn["why"].get(why, 0) + 1
            if m not in seen_e:
                sn["e_los_not"] += 1
                if inview:
                    sn["e_los_not_inview"] += 1
        else:
            if drawn:
                sn["drawn_no_los"] += 1
            if m in seen_e:
                sn["e_not_los"] += 1
    rec["seen"] = sn
    return rec


def frame_state(c):
    ws = c.world.ws
    alive = sum(1 for m in range(c.world.layout.nmon) if ws.mon_active[m] and ws.mon_health[m] > 0)
    awake = sum(1 for m in range(c.world.layout.nmon)
                if ws.mon_active[m] and ws.mon_health[m] > 0 and ws.mon_target[m])
    corpses = sum(1 for m in range(c.world.layout.nmon) if ws.mon_active[m] and ws.mon_health[m] <= 0)
    return {"alive": alive, "awake": awake, "corpses": corpses,
            "fireballs": sum(ws.proj_active), "fx": sum(ws.fx_active),
            "drops": sum(1 for m in range(c.world.layout.nmon) if ws.mon_drop[m] == 1),
            "player": [ws.px >> 16, ws.py >> 16, ws.pangle], "health": ws.p_health,
            "dead": ws.p_dead}


def run(name, setup, keys, every, tics=None, start=None, digest=None, skill=gd.SK_HARD):
    c = CL.Census(skill)
    w = c.world
    if start is not None:
        start(c)
    if setup is not None:
        setup(w)
    keys = keys[:tics] if tics else keys
    OUT.mkdir(exist_ok=True)
    path = OUT / (name + ".jsonl")
    t0 = time.perf_counter()
    kills = 0
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        for i, k in enumerate(keys):
            ev = w.tic(k)
            kills += len(ev.kills)
            if i % every:
                continue
            st = frame_state(c)
            st["kills_so_far"] = kills
            exempt_b = (lambda m: (m.role == "live" and m.awake) or m.role in ("fireball", "barrel"))
            variants = [
                ("today", lambda: c.today_things(), None),
                ("todayR4", lambda: c.today_things_r4(), None),
                ("game", lambda: c.game_things(), None),
                ("a", lambda: c.game_things(effects_first=True), None),
                ("b", lambda: c.game_things(), exempt_b),
                ("c", lambda: c.game_things(corpse_as_monster=False), None),
                ("d", lambda: c.game_things(depth_order=True), None),
                ("abcd", lambda: c.reorder_small_first(*c.game_things(corpse_as_monster=False,
                                                                      depth_order=True)), exempt_b),
                # the RECOMMENDED set: (a) + (c) + (d), and (b) for projectiles and barrels only --
                # awake monsters stay under the soft budget, because (e) decouples sight and aim
                ("rec", lambda: c.reorder_small_first(*c.game_things(corpse_as_monster=False,
                                                                     depth_order=True)),
                 lambda m: m.role in ("fireball", "barrel")),
            ]
            if VARIANTS_ONLY:
                variants = [v for v in variants if v[0] in VARIANTS_ONLY]
            for vname, build, ex in variants:
                th, bk, me, mt = build()
                _fb, arr = c.render(th, bk, me, mt, exempt=ex)
                rec = analyse(c, arr, c.W)
                rec.update({"scen": name, "tic": i, "variant": vname, **st})
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            if i % 20 == 0:
                print("  %s tic %3d  alive %2d awake %2d corpses %2d fb %d fx %d drops %d  %.0f s"
                      % (name, i, st["alive"], st["awake"], st["corpses"], st["fireballs"],
                         st["fx"], st["drops"], time.perf_counter() - t0), flush=True)
    print("%s: %d tics, %d kills, events %s -> %s (%.0f s)"
          % (name, len(keys), kills, {k: v for k, v in w.event_totals().items() if v}, path,
             time.perf_counter() - t0), flush=True)
    if digest is not None:
        print("  REPLAY CONTROL %s: model digest %s the frozen final digest" % (
            name, "EQUALS" if w.digest() == digest else "!! DIFFERS FROM"), flush=True)


def main():
    global OUT, VARIANTS_ONLY
    ap = argparse.ArgumentParser()
    ap.add_argument("--scen", default=",".join(SCENARIOS))
    ap.add_argument("--tics", type=int, default=0)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--scenarios", help="S4's combat_scenarios_v1.json (when it lands)")
    ap.add_argument("--out", default=str(OUT), help="directory for the JSON lines")
    ap.add_argument("--variants", help="render only these pictures (comma list)")
    a = ap.parse_args()
    OUT = Path(a.out)
    VARIANTS_ONLY = set(a.variants.split(",")) if a.variants else None
    if a.scenarios:
        run_s4(a.scenarios, a.every, a.tics)
        return
    for name in a.scen.split(","):
        setup, script = SCENARIOS[name]
        run(name, setup, keys_of(script), a.every, a.tics or None)


def run_s4(path, every, tics):
    """S4's set (combat_scenarios_v1.json): level start, the player's pose injected from each run's
    checkpoint, the per-tic key strings. The REPLAY CONTROL: after the run the model's digest must
    equal the file's `model_final_digest`, or this census did not see the frames S4 froze."""
    import hashlib
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    print("S4 set %s, sha256 %s, status: %s" % (path, hashlib.sha256(raw).hexdigest()[:16],
                                                 data.get("status")), flush=True)
    for r in data["runs"]:
        keys = [{LETTERS[ch]: True for ch in s if LETTERS.get(ch)} for s in r["keys"]]
        cp = r["checkpoint"]

        def st(c, cp=cp):
            c.world.teleport_player(cp["x16"], cp["y16"], cp["angle"])
        run("s4_" + r["name"], None, keys, every, tics or None, start=st,
            digest=None if tics else r.get("model_final_digest"), skill=cp.get("skill", gd.SK_HARD))


if __name__ == "__main__":
    main()
