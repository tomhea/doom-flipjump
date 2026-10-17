"""mirror_world_check.py -- M8: the gates' door / mover / card mirror against THE WORLD ITSELF, oracle vs oracle. No
binary, no build, no render.

    python scratchpad/gp/mirror_world_check.py                     # E1M1 and E1M2, each map in its own child
    python scratchpad/gp/mirror_world_check.py --map E1M2 [--part p2a|b0] [--mutate NAME] [--quick]
    python scratchpad/gp/mirror_world_check.py --selftest          # + R9: every MUTATION of the mirror is caught

WHY. A gate holds the binary to ITS MIRROR, not to the World: p2a_gate.Mirror (which hurt_gate, fight_gate and die_gate
drive, and whose door / mover / walk-over steps m2_std_gate's `tic` repeats line for line) keeps its OWN doors
(doors.DoorPhase), movers (movers.MoverPhase) and walk-over firing next to a model World (monsters.MonsterPhase) whose
doors and movers it syncs in; B0's scenarios_v2.BinaryMirror does the same. That mirror predates M8's key doors and
teleporters. If it differs from the World, a binary that matches the WORLD fails the gate -- or worse, a binary that
matches the wrong mirror passes it. THE TRUTH here is `World.tic`, stepping itself.

PART p2a. The scenarios of p2a, hurt, fight and die on the map -- their own lists, placed from the map's gate roles
(the first candidate of each; N/A, AWAITS and n/a skipped as the gates skip them) -- and, on a map that has them, this
checker's own X scenarios: every yellow and red door used with its key (poked into the world) and without it, and
every teleport line crossed from its front and then walked through the reaction freeze. Each is run TWICE: the gate's
Mirror (`Mirror.run`, unchanged) and a TWIN MonsterPhase whose World tics itself (`World.tic`) on the same keys, menu
keys, setups and late setups. No picture is drawn on either side: both take the SAME stand-in for the picture's seen
marks (every active monster within SEEN_RANGE of the player), so the monsters wake, fight, knock and press doors the same
way on both sides exactly when the mirror is right. After EVERY world frame the two must agree on
  * the doors: each door's (state, dir, sub, wait), the fired walk-over bits, the pending presses, the blue card;
  * the movers: each lift's (state, dir, sub, wait), the pending triggers, the floor switch;
  * the pose, `pusedn` (p_usedown), `lvdone` (g_leveldone);
  * EVERY OTHER CELL of the world schema (the Mirror's world against the twin's), minus OWN -- the cells the mirror
    keeps outside its world (above), and the player thing's own animation, which no gate mirrors (first person never
    draws it);
  * on a frame whose move TELEPORTED (the twin's `_walkover` was called with an end the player did not stay at): the
    gate's walk-over segments (`monsters.walkover_segments`, as the Mirror called it) are the twin's `_walkover` calls.
PART b0. Every run of the map's combat scenario set (scenarios_map's set for the map: combat_scenarios_v10 on E1M1,
combat_scenarios_e1m2_v1 on E1M2), its setup and keys replayed on a World (World.tic, the stand-in seen marks instead
of the set's SeenHook pictures: the same keys, a different trajectory, the comparison is per frame). Before each frame a
SHADOW MonsterPhase is loaded with the world's every cell, BinaryMirror steps the frame on it (the doors, fired bits,
presses, card and movers taken from the world, as b0 injects them), and after `World.tic` the two must agree as above.
A run stops being compared once its player is dead (B0's runs never die; BinaryMirror has no death think).

THE NEGATIVE CONTROLS (docs/cr-rules.md R9; `--selftest`, on E1M2, each in its own child): the mirror as it was before
M8 must be REJECTED --
  no_keys        monsters.door_keys_kw returns {} (the gate's door tic does not see the yellow / red keys);
  jump_segment   monsters.walkover_segments ignores the world's recorded segments (a teleport = one walk from the start
                 to the destination, `walk_end` and all, as before L4);
and one control on the comparison itself --
  blind_doors    the comparison drops the door term: no_keys must then PASS (so it is the door term that caught it).
and, on E1M1, a walk-over-blind mirror (no_walkovers: DoorPhase.after_move a no-op) -- the comparison is not blind there.

STATIC. m2_std_gate's mirror (`tic`, nested in its main: it needs a binary's door stamp to run) cannot be stepped here,
so its call sites are held to the two hooks by syntax, with the other two mirrors': in m2_std_gate, p2a_gate and
scenarios_v2 every `dp.tic(...)` passes `**door_keys_kw(...)` (or the `**keys_kw` p2a builds from it) and every
`dp.after_move(...)` / `mp.after_move(...)` fires over the names a `walkover_segments(...)` loop binds. Its control:
the same check on m2_std_gate's text with the keys dropped must reject it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

if __name__ == "__main__":                       # `--map E1Mn` before probe / gamespeed read their defaults
    from doomfj.mapprofile import take_map_arg
    take_map_arg(keep=True)

M32 = 0xFFFFFFFF
SEEN_RANGE = 1024                 # map units: the stand-in picture "sees" every active monster this close
MUTATIONS = ("no_keys", "jump_segment")          # on E1M2: the mirror before M8
E1M1_MUTATIONS = ("no_walkovers",)               # on E1M1: the comparison is not blind there either
# the world cells the mirror keeps OUTSIDE its world (compared against the mirror's own phases instead), and the
# player thing's animation (P_SetMobjState on the player: first person never draws it, no gate mirrors it)
OWN = frozenset({"w_fired", "d_monreq", "l_req", "p_usedown", "g_leveldone", "p_mobj_state", "p_mobj_tics"})


# ================================================================================================
# the shared pieces
# ================================================================================================
def seen_standin(mph) -> set:
    """the picture's seen marks, stood in for: every active monster within SEEN_RANGE (Chebyshev) of the player"""
    ws, w = mph.world.ws, mph.world
    px, py = ws.px >> 16, ws.py >> 16
    return {m for m in range(w.layout.nmon)
            if ws.mon_active[m] and max(abs(ws.mon_x[m] - px), abs(ws.mon_y[m] - py)) <= SEEN_RANGE}


def tap_walkover(world, rec: list) -> None:
    """record every `_walkover(x, y, cx, cy)` the world makes (an instance attribute over whatever is there) as
    ((x, y), (cx, cy), teleported) -- teleported: the player did not stay at the call's end"""
    orig = world._walkover

    def walkover(x, y, cx, cy, _orig=orig):
        r = _orig(x, y, cx, cy)
        rec.append(((x, y), (cx, cy), (world.ws.px, world.ws.py) != (cx, cy)))
        return r
    world._walkover = walkover


def signed_pt(p) -> tuple:
    return tuple((v & M32) - (1 << 32) if (v & M32) >> 31 else (v & M32) for v in p)


def norm_segs(segs) -> list:
    return [(signed_pt(a), signed_pt(b)) for a, b in segs]


def compare(mws: dict, tws: dict, ph, ms, pose, pusedn, lvdone, order, lift_order, blue: int,
            loots: bool, blind_doors: bool = False) -> list:
    """the differences between the mirror's frame (its world `mws`, door phase `ph`, mover phase `ms`, pose, pusedn,
    lvdone) and the twin's world `tws` -> [(what, mirror, world)]"""
    out = []
    if not blind_doors:
        for d, si in enumerate(order):
            t = (tws["d_state"][d], tws["d_dir"][d], tws["d_sub"][d], tws["d_wait"][d])
            if tuple(ph[0][si]) != t:
                out.append(("door %d" % si, tuple(ph[0][si]), t))
        if tuple(ph[1]) != tuple(tws["w_fired"]):
            out.append(("w_fired", tuple(ph[1]), tuple(tws["w_fired"])))
        req = frozenset(si for d, si in enumerate(order) if tws["d_monreq"][d])
        if frozenset(ph[2]) != req:
            out.append(("door presses", sorted(ph[2]), sorted(req)))
        if loots and int(bool(ph[3])) != int(bool(tws["p_cards"][blue])):
            out.append(("blue card", ph[3], tws["p_cards"][blue]))
    for k, si in enumerate(lift_order):
        t = (tws["l_state"][k], tws["l_dir"][k], tws["l_sub"][k], tws["l_wait"][k])
        if tuple(ms[0][k]) != t:
            out.append(("lift %d" % si, tuple(ms[0][k]), t))
    lreq = frozenset(si for k, si in enumerate(lift_order) if tws["l_req"][k])
    if frozenset(ms[1]) != lreq:
        out.append(("lift triggers", sorted(ms[1]), sorted(lreq)))
    if int(bool(ms[2])) != int(bool(tws["f_switch"])):
        out.append(("floor switch", ms[2], tws["f_switch"]))
    mp = (pose[0] & M32, pose[1] & M32, pose[2] & M32)
    tp = (tws["px"] & M32, tws["py"] & M32, tws["pangle"] & M32)
    if mp != tp:
        out.append(("pose", mp, tp))
    if pusedn is not None and int(bool(pusedn)) != int(bool(tws["p_usedown"])):
        out.append(("pusedn", pusedn, tws["p_usedown"]))
    if lvdone is not None and int(bool(lvdone)) != int(bool(tws["g_leveldone"])):
        out.append(("lvdone", lvdone, tws["g_leveldone"]))
    for k in sorted(set(mws) | set(tws)):
        if k in OWN:
            continue
        if blind_doors and k in ("d_state", "d_dir", "d_sub", "d_wait", "p_cards"):
            continue
        if mws.get(k) != tws.get(k):
            a, b = mws.get(k), tws.get(k)
            if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                i = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
                out.append(("cell %s[%d]" % (k, i), a[i], b[i]))
            else:
                out.append(("cell %s" % k, a, b))
    return out


# ================================================================================================
# PART p2a: the Mirror (p2a / hurt / fight / die) against its twin
# ================================================================================================
def p2a_part(args) -> dict:
    import onewalk
    import gate_roles
    import p2a_gate as G
    import hurt_gate as H
    import fight_gate as FG
    import die_gate as DG
    import p8a_lib as P8
    from doomfj import doors as D
    from doomfj import gamedata as gd
    from doomfj import monsters as M
    from doomfj.menu import LEVEL_DONE_ENTER, menu_step
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_MENU_SKILL, BOOT_SKILL, MONSTER_MODE, PLAYER_MODE, SKILLS
    from doomfj.world import TicEvents, player_loots

    dsim = onewalk.DoorSim()
    mapname = dsim.mapname
    R = gate_roles.roles(mapname)
    card = dsim.dp.card_at
    w0 = MonsterPhase(dsim.mw, mapname, BOOT_SKILL, rm=dsim.rm, mode=MONSTER_MODE, player=PLAYER_MODE).world
    order, lift_order = list(dsim.order), list(dsim.mp.order)
    assert order == list(w0.door_order) and lift_order == list(w0.lift_order)

    # ---- the scenario list: (gate, name, pose, keys, pcard, setup, late)
    runs = []
    for sc in G.scenarios(dsim, card):
        if not sc.get("na"):
            runs.append(("p2a", sc["name"], sc["pose"], sc["keys"], sc["pcard"], None, None))
    lists = (("hurt", H.scenario_list(dsim, w0)), ("fight", FG.scenario_list(dsim, w0, card)),
             ("die", DG.scenario_list(dsim, w0, card)))
    skipped = 0
    for gate, scs in lists:
        for sc in scs:
            tag = sc["name"].split()[0]
            if sc.get("na") or (mapname != "E1M1" and R.na_reasons.get(tag)) or not sc.get("cands") \
                    or P8.status(sc, PLAYER_MODE, MONSTER_MODE) != "run":
                skipped += 1
                continue
            cand = sc["cands"][0]
            runs.append((gate, sc["name"], cand[0], sc["keys"], 0, cand[1], cand[2] if len(cand) > 2 else None))
    if args.quick:
        runs = runs[::4]
    xs = x_scenarios(dsim, w0, R, G, D, gd)
    runs += [("X", n, p, k, 0, s, None) for n, p, k, s, _claim in xs]
    claims = {n: c for n, _p, _k, _s, c in xs}

    # ---- the recorders: the gate's walk-over segments (as the Mirror calls them), per frame
    seg_log = []
    orig_ws = M.walkover_segments

    def walkover_segments(phase, old, new):
        segs = orig_ws(phase, old, new)
        seg_log.append(segs)
        return segs
    M.walkover_segments = walkover_segments

    bad, frames, tele_frames, x_ok = [], 0, 0, {}
    t0 = time.time()
    for gate, name, pose, keys, pcard, setup, late in runs:
        # -- the MIRROR, the gate's own (no hooks: the stand-in seen marks; a snapshot at each world frame's end)
        mr = G.Mirror(dsim, -1)
        mr.mmode, mr.pmode, mr.setup = MONSTER_MODE, PLAYER_MODE, setup
        mr.late = dict(late or {})
        snaps = []

        def seenfn(mph, st, ph, ms, taken, snaps=snaps):
            snaps.append({"ws": mph.world.ws.as_dict(), "ph": ph, "ms": ms, "pose": (st.x, st.y, st.angle),
                          "segs": list(seg_log)})
            seg_log.clear()
            return seen_standin(mph)
        mr.seenfn = seenfn
        seg_log.clear()
        try:
            out = mr.run(pose, keys, pcard)
        except Exception as e:                                 # noqa: BLE001 -- a mirror that crashes is a FAIL
            bad.append((gate, name, -1, [("mirror raised", repr(e), "")]))
            continue
        world_frames = [f for f, fr in enumerate(out) if fr["drawn"] == "world"]
        assert len(world_frames) == len(snaps), (name, len(world_frames), len(snaps))
        # -- the TWIN: the same start, World.tic on the same keys
        tw = MonsterPhase(dsim.mw, mapname, BOOT_SKILL, rm=dsim.rm, mode=MONSTER_MODE, player=PLAYER_MODE)
        loots = player_loots(tw.world.player)
        calls = []
        tap_walkover(tw.world, calls)
        if loots:
            tw.set_card(pcard)
        if setup is not None:
            setup(tw)
        pending = tuple(pose)
        mode, scr, sel, live, lvdone = 0, 0, SKILLS.index(BOOT_MENU_SKILL), 1, 0
        tsnaps = []
        for f, kd in enumerate(keys):
            if late and f in late:
                got = late[f](tw, TicEvents(f))
                if got is not None:
                    pending = tuple(got)
            mev_ = set(kd.get("menu", ()))
            mode, scr, sel, ng, live = menu_step(mode, scr, sel, mev_ | ({"any"} if mev_ else set()), live)
            if ng is not None:
                tw.reset(SKILLS[ng])
                pending, lvdone = (dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle), 0
            drawn = mode == 0
            if mode == 0 and tw.restart_due():
                lvdone = 0
            if mode == 0 and not lvdone:
                ws = tw.world.ws
                if pending is not None:
                    ws.px, ws.py = signed_pt(pending[:2])
                    ws.pangle = pending[2] & M32
                    pending = None
                calls.clear()
                tw.world.tic(kd)
                if ws.g_leveldone:
                    lvdone, mode, scr = 1, 1, LEVEL_DONE_ENTER
            if drawn:
                tsnaps.append({"ws": tw.world.ws.as_dict(), "calls": list(calls)})
                calls.clear()
                tw.set_seen(seen_standin(tw))
        n = min(len(snaps), len(tsnaps))
        if len(snaps) != len(tsnaps):
            bad.append((gate, name, n, [("world frames", len(snaps), len(tsnaps))]))
        first = None
        for i in range(n):
            f = world_frames[i]
            m, t = snaps[i], tsnaps[i]
            diffs = compare(m["ws"], t["ws"], m["ph"], m["ms"], m["pose"], out[f]["pusedn"], out[f]["lvdone"],
                            order, lift_order, gd.IT_BLUECARD, loots, blind_doors=args.blind_doors)
            if any(tp for _a, _b, tp in t["calls"]):
                tele_frames += 1
                want = norm_segs((a, b) for a, b, _tp in t["calls"])
                got = [s for segs in m["segs"] for s in norm_segs(segs)]
                if got != want:
                    diffs.append(("teleport-frame segments", got, want))
            frames += 1
            if diffs and first is None:
                first = (f, diffs)
        if first is not None:
            bad.append((gate, name, first[0], first[1]))
        if gate == "X":
            x_ok[name] = claims[name](tsnaps)
    M.walkover_segments = orig_ws
    return {"part": "p2a", "map": mapname, "runs": len(runs), "skipped": skipped, "frames": frames,
            "tele_frames": tele_frames, "bad": bad, "x": x_ok, "seconds": time.time() - t0}


def x_scenarios(dsim, w0, R, G, D, gd) -> list:
    """the checker's own scenarios on a map with yellow / red doors or teleport lines -> [(name, pose, keys, setup,
    claim(twin snapshots) -> bool)]: the claim proves the scenario NOT VACUOUS (the door opened / stayed shut, the
    player teleported)"""
    out = []
    U, I, F = {"use": True}, {}, {"forward": True}
    order = list(dsim.order)
    for colour, item in (("yellow", gd.IT_YELLOWCARD), ("red", gd.IT_REDCARD)):
        for si in (R.get("key_doors") or {}).get(colour, ()):
            if si not in dsim.boxes:
                continue
            try:
                pose = G.door_front(dsim, si)
            except AssertionError:
                continue
            d, n = order.index(si), dsim.nstates[si]
            keys = [U] * 3 + [I] * (D.SPEED * n + 2)

            def give(mph, item=item):
                mph.world.ws.p_cards[item] = 1
            out.append(("X %s door %d with the %s key: opens" % (colour, si, colour), pose, keys, give,
                        lambda ts, d=d, n=n: max(t["ws"]["d_state"][d] for t in ts) == n - 1))
            out.append(("X %s door %d without the key: stays shut" % (colour, si), pose, keys, None,
                        lambda ts, d=d: all(t["ws"]["d_state"][d] == 0 for t in ts)))
    # M8 L2: the switch doors (SR 63 / S1 103): a press in the switch's box, a second press later (an SR door at rest
    # again opens again, an S1 door stays)
    for si, bs in sorted(dsim.dp.switches.items()):
        try:
            pose = G._in_box(dsim, bs[0])
        except AssertionError:
            continue
        d, n = order.index(si), dsim.nstates[si]
        keys = [I, U] + [I] * (D.SPEED * n + D.WAIT + D.SPEED * n + 4) + [U] + [I] * 4
        out.append(("X switch door %d (%s): pressed, then again" % (si, dsim.dp.kinds[si]), pose, keys, None,
                    lambda ts, d=d: max(t["ws"]["d_state"][d] for t in ts) > 0))
    # E1M2's teleport lines are the edges of monster closets: the line's front is the closet floor, the line itself a
    # raised pad (+25 / +32: no walk climbs it) with the closet's monsters in the way. So the scenario STARTS the player
    # in the closet with his box over the pad (his floorz is the pad's) and the closet's monsters gone (the setup, on
    # both sides), and walks him over the line from its front -- the first candidate pose that teleports on the World
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE, PLAYER_MODE
    probe = None
    for tel in getattr(w0, "teleports", ()):
        found = None
        for back in (10, 12, 8, 14, 6, 4, 16, 20, 24):
            for frac in (2, 1, 3):
                mid = tel.lo + (tel.hi - tel.lo) * frac // 4
                c = tel.coord - back if tel.front_le else tel.coord + back
                x, y = (c, mid) if tel.axis == "x" else (mid, c)
                sgn = 1 if tel.front_le else -1
                ang = G.bam(sgn, 0) if tel.axis == "x" else G.bam(0, sgn)
                pose = (x << 16, y << 16, ang)

                def clear(mph, x=x, y=y):
                    ws = mph.world.ws
                    for m in range(mph.world.layout.nmon):
                        if max(abs(ws.mon_x[m] - x), abs(ws.mon_y[m] - y)) <= 96:
                            ws.mon_active[m] = 0
                if probe is None:
                    probe = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=MONSTER_MODE,
                                         player=PLAYER_MODE)
                probe.reset(BOOT_SKILL)
                clear(probe)
                ws = probe.world.ws
                ws.px, ws.py, ws.pangle = pose
                if not probe.world.rm.check_position(probe.world.scene_c, ws.px, ws.py)[0]:
                    continue
                for _f in range(6):
                    probe.world.tic(F)
                if ws.p_reaction:
                    found = (pose, clear)
                    break
            if found:
                break
        if found is None:
            print("  (no pose walks over teleport line %d from its front)" % tel.line)
            continue
        out.append(("X teleport line %d from its front (closet cleared), then walking through the freeze" % tel.line,
                    found[0], [F] * 30 + [I] * 2, found[1],
                    lambda ts: any(t["ws"]["p_reaction"] for t in ts)))
    return out


# ================================================================================================
# PART b0: BinaryMirror against the World, frame by frame
# ================================================================================================
def b0_part(args) -> dict:
    import scenarios_map as SM
    import scenarios_v2 as S
    from doomfj import gamedata as gd
    from doomfj import monsters as M
    from doomfj.mapprofile import ACTIVE
    from doomfj.monsters import MonsterPhase
    from doomfj.world import player_loots

    path = HERE / "scenarios" / ("combat_scenarios_v10.json" if ACTIVE == "E1M1"
                                 else "combat_scenarios_%s_v1.json" % ACTIVE.lower())
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc.get("map", "E1M1").upper() == ACTIVE, (path, doc.get("map"))
    SM.use_doc(doc)
    seg_log = []
    orig_ws = M.walkover_segments

    def walkover_segments(phase, old, new):
        segs = orig_ws(phase, old, new)
        seg_log.append(segs)
        return segs
    M.walkover_segments = walkover_segments
    bad, frames, tele_frames, deaths, t0 = [], 0, 0, 0, time.time()
    run_list = doc["runs"][:3] if args.quick else doc["runs"]
    for run in run_list:
        w = S.start_world(run["setup"])
        w.seen_hook = None                           # the stand-in instead (below), applied after the comparison
        calls = []
        tap_walkover(w, calls)
        w2 = S.start_world(run["setup"])
        w2.seen_hook = None
        sh = MonsterPhase(world=w2)
        cm = S.BinaryMirror(w2)
        loots = player_loots(w.player)
        order, lift_order = list(w.door_order), list(w.lift_order)
        first = None
        for i, s in enumerate(run["keys"]):
            if w.ws.p_dead:
                deaths += 1
                break
            kd = S.str_to_keys(s)
            ws = w.ws
            pre = (ws.px, ws.py, ws.pangle)
            # the shadow: the world's every cell, its scene, and the mirror's phases as b0 injects them
            w2.ws.load(ws.as_dict())
            # the mirror's world never holds a pending press: `MonsterPhase.requests` hands them to the mirror's phases
            # and clears them every frame (the pending ones ride cm.state / cm.mstate below)
            for arr in (w2.ws.d_monreq, w2.ws.l_req):
                for k in range(len(arr)):
                    arr[k] = 0
            for a in ("secs_c", "_mh_last", "scene_c", "blocked_now", "heights_now", "_decor_now"):
                if hasattr(w, a):
                    setattr(w2, a, getattr(w, a))
            cm.state = ({si: (ws.d_state[d], ws.d_dir[d], ws.d_sub[d], ws.d_wait[d]) for d, si in enumerate(order)},
                        tuple(ws.w_fired), frozenset(si for d, si in enumerate(order) if ws.d_monreq[d]),
                        ws.p_cards[gd.IT_BLUECARD])
            cm.mstate = S.mover_state(w)
            cm.pusedn = ws.p_usedown
            seg_log.clear()
            epose, _ = cm.step(pre, kd, None, None, others=sh.boxes(), mph=sh)
            cm.state, cm.mstate = sh.frame(cm.state, cm.mstate, epose[0] & M32, epose[1] & M32, epose[2])
            calls.clear()
            w.tic(kd)
            tws = w.ws.as_dict()
            diffs = compare(w2.ws.as_dict(), tws, cm.state, cm.mstate, epose, cm.pusedn, None, order, lift_order,
                            gd.IT_BLUECARD, loots, blind_doors=args.blind_doors)
            if any(tp for _a, _b, tp in calls):
                tele_frames += 1
                want = norm_segs((a, b) for a, b, _tp in calls)
                got = [x for segs in seg_log for x in norm_segs(segs)]
                if got != want:
                    diffs.append(("teleport-frame segments", got, want))
            frames += 1
            if diffs and first is None:
                first = (i, diffs)
            from doomfj.monsters import MonsterPhase as _MP
            _MP.set_seen(SimpleNamespace(world=w), seen_standin(SimpleNamespace(world=w)))
        if first is not None:
            bad.append(("b0", run["name"], first[0], first[1]))
    M.walkover_segments = orig_ws
    return {"part": "b0", "map": ACTIVE, "file": path.name, "runs": len(run_list), "frames": frames,
            "tele_frames": tele_frames, "deaths": deaths, "bad": bad, "seconds": time.time() - t0}


# ================================================================================================
# the mutations (R9) and the report
# ================================================================================================
STATIC_FILES = ("scratchpad/m2_std_gate.py", "scratchpad/gp/p2a_gate.py", "scratchpad/gp/scenarios_v2.py")


def static_problems(text: str) -> list:
    """the door-tic and walk-over call sites of one mirror's source that do not read the world's hooks"""
    import ast
    tree = ast.parse(text)
    seg_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Call) \
                and getattr(node.iter.func, "id", getattr(node.iter.func, "attr", None)) == "walkover_segments":
            seg_names |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
    out, tics = [], 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        recv = ast.unparse(node.func.value)
        if node.func.attr == "tic" and recv.split(".")[-1] == "dp":
            tics += 1
            if not any(k.arg is None and "keys_kw" in ast.unparse(k.value) for k in node.keywords):
                out.append("line %d: %s.tic without **door_keys_kw" % (node.lineno, recv))
        if node.func.attr == "after_move" and recv.split(".")[-1] in ("dp", "mp"):
            ends = [ast.unparse(x) for x in node.args[1:3]]
            if len(ends) != 2 or not all(e in seg_names for e in ends):
                out.append("line %d: %s.after_move over %s, not a walkover_segments segment" % (node.lineno, recv,
                                                                                                  ends))
    if not tics:
        out.append("no dp.tic call found (the check would be vacuous)")
    return out


def static_check() -> bool:
    ok = True
    for f in STATIC_FILES:
        text = (ROOT / f).read_text(encoding="utf-8")
        probs = static_problems(text)
        ok &= not probs
        print("  STATIC %-30s %s" % (f, "every door tic reads the world's keys, every walk-over a recorded segment"
                                     if not probs else "FAIL: %s" % "; ".join(probs)))
    # the control: m2_std_gate with the keys dropped from its door tic must be rejected
    text = (ROOT / STATIC_FILES[0]).read_text(encoding="utf-8")
    bad = text.replace("**door_keys_kw(mph))", ")")
    caught = bad != text and bool(static_problems(bad))
    ok &= caught
    print("  STATIC control (m2_std_gate without **door_keys_kw): %s" % ("REJECTED" if caught else
                                                                         "NOT rejected -- FAIL"))
    return ok


def mutate(name: str) -> None:
    from doomfj import monsters as M
    if name == "no_keys":
        M.door_keys_kw = lambda phase: {}
    elif name == "no_walkovers":                         # the mirror's door walk-overs never fire
        from doomfj import doors as D
        D.DoorPhase.after_move = lambda self, state, old16, new16, radius=16: state
    elif name == "jump_segment":
        orig = M.walkover_segments

        def old_segments(phase, old, new):              # the segments before M8 L4: walk_end, or old -> new
            if phase is not None and getattr(phase, "walk_segs", None) is not None:
                phase = SimpleNamespace(walk_end=phase.walk_end)
            return orig(phase, old, new)
        M.walkover_segments = old_segments
    elif name:
        raise SystemExit("unknown mutation %r" % name)


def report(res: dict) -> bool:
    ok = not res["bad"]
    extra = ""
    if res["part"] == "p2a":
        vac = [n for n, v in res["x"].items() if not v]
        ok &= not vac
        extra = ", %d skipped (N/A / awaits), %d X scenarios%s" % (
            res["skipped"], len(res["x"]), (" -- VACUOUS: %s" % vac) if vac else " (each did what it claims)")
    else:
        extra = ", set %s, %d runs stopped at a death" % (res["file"], res["deaths"])
    print("  %s on %s: %d runs, %d world frames compared, %d teleport frames%s (%.0f s)"
          % (res["part"], res["map"], res["runs"], res["frames"], res["tele_frames"], extra, res["seconds"]))
    for gate, name, f, diffs in res["bad"][:12]:
        print("    PART  %-5s %s -- frame %s: %s" % (gate, name, f, "; ".join(
            "%s mirror %s world %s" % (a, str(b)[:120], str(c)[:120]) for a, b, c in diffs[:4])))
    if len(res["bad"]) > 12:
        print("    ... and %d more" % (len(res["bad"]) - 12))
    return ok


def child(mapname: str, part: str, mutation: str = "", quick: bool = False, blind: bool = False):
    cmd = [sys.executable, str(Path(__file__).resolve()), "--map", mapname, "--part", part, "--json"]
    if mutation:
        cmd += ["--mutate", mutation]
    if quick:
        cmd.append("--quick")
    if blind:
        cmd.append("--blind-doors")
    env = dict(os.environ, DOOMFJ_MAP=mapname, PYTHONPATH=str(ROOT / "src"))
    p = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    line = [ln for ln in p.stdout.splitlines() if ln.startswith("JSON ")]
    if p.returncode not in (0, 1) or not line:
        print(p.stdout[-3000:], p.stderr[-3000:])
        raise SystemExit("child %s %s %s died (exit %s)" % (mapname, part, mutation, p.returncode))
    return json.loads(line[-1][5:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map")
    ap.add_argument("--part", choices=("p2a", "b0", "both"), default="both")
    ap.add_argument("--mutate", default="")
    ap.add_argument("--quick", action="store_true", help="a quarter of the gate scenarios, three B0 runs")
    ap.add_argument("--blind-doors", action="store_true", help="the comparison without its door term (a control)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    t0 = time.time()
    if a.map:
        mutate(a.mutate)
        parts = ("p2a", "b0") if a.part == "both" else (a.part,)
        res = [p2a_part(a) if p == "p2a" else b0_part(a) for p in parts]
        if a.json:
            print("JSON " + json.dumps([dict(r, bad=[[g, n, f, [[str(x) for x in d] for d in ds]]
                                                     for g, n, f, ds in r["bad"]]) for r in res]))
            return 0
        ok = all([report(r) for r in res])
        print("MIRROR-WORLD %s on %s%s" % ("PASS" if ok else "FAIL", a.map, " (mutation %s)" % a.mutate
                                           if a.mutate else ""))
        return 0 if ok else 1
    ok = True
    print("MIRROR-WORLD CHECK -- the gates' door / mover / card mirror against World.tic, oracle vs oracle")
    ok &= static_check()
    for m in ("E1M1", "E1M2"):
        for part in ("p2a", "b0"):
            for r in child(m, part, quick=a.quick):
                ok &= report(r)
    if a.selftest:
        print("\nR9 -- the mirror as it was before M8 (on E1M2), and a walk-over-blind mirror (on E1M1): each must be "
              "REJECTED")
        for mut, m in [(x, "E1M2") for x in MUTATIONS] + [(x, "E1M1") for x in E1M1_MUTATIONS]:
            caught = []
            for part in ("p2a", "b0"):
                for r in child(m, part, mut, quick=a.quick):
                    caught += [(r["part"], g, n, f, ds[0][0]) for g, n, f, ds in r["bad"]]
            ok &= bool(caught)
            print("  MUTATION %-13s %s %s" % (mut, m, ("CAUGHT by %d runs, first: %s %s %s frame %s (%s)"
                                                % ((len(caught),) + tuple(caught[0]))) if caught
                                           else "NOT CAUGHT -- the check is BLIND to it, FAIL"))
        rs = child("E1M2", "p2a", "no_keys", quick=a.quick, blind=True)
        blind_bad = [b for r in rs for b in r["bad"]]
        ok &= not blind_bad
        print("  CONTROL  blind_doors   no_keys with the door term dropped: %s" % (
            "PASSES (so the door term is what catches it)" if not blind_bad
            else "still parts on %s -- the door term is not shown to be the catcher, FAIL" % blind_bad[0][1]))
    print("\nMIRROR-WORLD %s (%.0f s)" % ("PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
