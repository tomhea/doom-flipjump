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
checker's own X scenarios: every yellow and red door used with its key (poked into the world) and without it, every
switch door pressed twice, every teleport line crossed from its front and then walked through the reaction freeze --
and (M8 F1.3) EVERY FLOOR GROUP fired by its own W1 line (slanted ones too) or S1 box and run to its last state, every
lift tag that is blazing or starts two lifts, and each TELEPORT CLOSET: the group that lowers a teleport line's pad
fires and a closet monster walks over the line and teleports. Each is placed by a pose that does it on the WORLD (a
probe run), from the World's geometry -- never the mirror's, so a mutated mirror cannot move a scenario. Each is run TWICE: the gate's
Mirror (`Mirror.run`, unchanged) and a TWIN MonsterPhase whose World tics itself (`World.tic`) on the same keys, menu
keys, setups and late setups. No picture is drawn on either side: both take the SAME stand-in for the picture's seen
marks (every active monster within SEEN_RANGE of the player), so the monsters wake, fight, knock and press doors the same
way on both sides exactly when the mirror is right. After EVERY world frame the two must agree on
  * the doors: each door's (state, dir, sub, wait), the fired walk-over bits, the pending presses, the blue card;
  * the movers: each lift's (state, dir, sub, wait), the pending triggers, the floor switch -- on E1M2 the whole
    fswitch VECTOR (each floor group's state, then its step timer: the world's f_switch and f_sub);
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
  no_floor_movers  movers.MoverPhase without F1.3's floor triggers (no W1 / S1 floor line fires a group);
  slow_lifts     movers.MoverPhase with every lift at stride 1 (before F1.3's blazing 120 / 123);
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
MUTATIONS = ("no_keys", "jump_segment", "no_floor_movers", "slow_lifts")   # on E1M2: the mirror before M8 / F1.3
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

    def walkover(x, y, cx, cy, ev=None, _orig=orig):
        r = _orig(x, y, cx, cy, ev)
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
    # M8 F1.3: the WIDE layout's fswitch vector (each floor group's state, then its step timer: f_switch, f_sub)
    if isinstance(tws["f_switch"], list):
        wsw, msw = tuple(tws["f_switch"]) + tuple(tws["f_sub"]), tuple(ms[2])
        if msw != wsw:
            out.append(("fswitch vector", msw, wsw))
    elif int(bool(ms[2])) != int(bool(tws["f_switch"])):
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

    # ---- the scenario list: (gate, name, pose, keys, pcard, setup, late); p2a's two-cell-line `look`s (S14)
    runs, looks, views, orc, injects = [], {}, {}, None, {}
    for sc in G.scenarios(dsim, card):
        if not sc.get("na"):
            runs.append(("p2a", sc["name"], sc["pose"], sc["keys"], sc["pcard"], None, None))
            if sc.get("look"):
                looks[sc["name"]] = sc["look"]
            if sc.get("fswitch") is not None:
                injects[sc["name"]] = tuple(sc["fswitch"])      # M8 F1.3 (S15): a floor group fired by a poke
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
            out = mr.run(pose, keys, pcard, fswitch=injects.get(name))
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
        mtele = tap_monster_teleports(tw.world)
        if loots:
            tw.set_card(pcard)
        if setup is not None:
            setup(tw)
        if name in injects:                                    # the poked fswitch vector: states, then timers
            ng = len(tw.world.floor_groups)
            for g_ in range(ng):
                tw.world.ws.f_switch[g_], tw.world.ws.f_sub[g_] = injects[name][g_], injects[name][ng + g_]
            tw.world._door_phase_scene()
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
                tsnaps.append({"ws": tw.world.ws.as_dict(), "calls": list(calls), "mtele": mtele[0]})
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
        if name in looks:
            if orc is None:
                import probe as P
                orc = P.Oracle()
            vc = closed_view_check if looks[name].get("kind") == "closed" else view_check
            views[name] = (vc(orc, dsim, looks[name], out), vc(orc, dsim, looks[name], out, flip=True))
    M.walkover_segments = orig_ws
    return {"part": "p2a", "map": mapname, "runs": len(runs), "skipped": skipped, "frames": frames,
            "tele_frames": tele_frames, "bad": bad, "x": x_ok, "views": views, "looks": looks,
            "seconds": time.time() - t0}


def view_check(orc, dsim, look: dict, out: list, flip: bool = False) -> dict:
    """M8 F1.3: does a two-cell-line scenario (p2a S14a / S14b, `look`) SEE the line? On each world frame of the gate's
    Mirror run whose movers are in the scenario's case, the oracle's picture at the frame's pose against the same
    picture with the floor sector toggled (its stored floor <-> its group's last stop): a frame whose pixels change
    sees the line's floor cell. -> {case: frames that see it} -- "down" (the lift at its bottom, the floor group at
    state 0), "unlowered" (state 0), "lowered" (its last state). `flip` (the control): the view turned 180 degrees."""
    import probe as P
    mp, secs = dsim.mp, dsim.secs
    sl, sf, g = look["lift"], look["floor"], look["group"]
    grp, kl = mp.groups[g], mp.order.index(sl)
    bottom, stored, last = len(mp.stops[sl]) - 1, secs[sf].floor_h, grp.floor(sf, grp.n - 1)
    seen = {"down": 0, "unlowered": 0, "lowered": 0}
    for fr in out:
        if fr["drawn"] != "world":
            continue
        gs, ls = fr["movers"][2][g], fr["movers"][0][kl][0]
        cases = [c for c, hit in (("down", ls == bottom and gs == 0), ("unlowered", gs == 0),
                                  ("lowered", gs == grp.n - 1)) if hit]
        if not cases:
            continue
        x, y, a = fr["pose"]
        a = (a + (0x80000000 if flip else 0)) & M32
        h = dict(fr["mheights"])
        cur = h.get(sf, (stored, secs[sf].ceil_h))[0]
        alt = dict(h)
        alt[sf] = (last if cur == stored else stored, secs[sf].ceil_h)
        ds = tuple(fr["phase"][0][si][0] for si in dsim.order)
        if P.px_diff(orc.render(x, y, a, ds, movers=h), orc.render(x, y, a, ds, movers=alt)):
            for c in cases:
                seen[c] += 1
    return seen


class OpenLineWad:
    """M8 F1.3 (CR of #146): the map wad with ONE line opened -- its static side's sidedef points at a copy of the
    static sector whose ceiling is the moving side's, so the line is no longer shut (the oracle's `_closed2s` false):
    the line drawn SEE-THROUGH, as r2's binary drew E1M2's 2033 / 2062 / 2050 / 2075. Every other read is the wad's."""

    def __init__(self, mw, mapname: str, line: int, static: int, ceil: int):
        import dataclasses
        self._mw, self._m = mw, mapname
        secs, sds, ld = mw.sectors(mapname), list(mw.sidedefs(mapname)), mw.linedefs(mapname)[line]
        self._extra = dataclasses.replace(secs[static], ceil_h=ceil)
        side = ld.back if sds[ld.back].sector == static else ld.front
        assert sds[side].sector == static, (line, static)
        sds[side] = dataclasses.replace(sds[side], sector=len(secs))
        self._sds = sds

    def sectors(self, m):
        return list(self._mw.sectors(m)) + [self._extra] if m == self._m else self._mw.sectors(m)

    def sidedefs(self, m):
        return list(self._sds) if m == self._m else self._mw.sidedefs(m)

    def __getattr__(self, k):
        return getattr(self._mw, k)


def closed_view_check(orc, dsim, look: dict, out: list, flip: bool = False) -> dict:
    """M8 F1.3 (CR of #146): does p2a S15 SEE its line shut at every state? On each world frame of the gate's Mirror
    run whose floor group is LOWERING (state 1 .. n-2) or LOWERED (n-1): the oracle's view at the frame's pose and
    movers against the same view with the line opened (`OpenLineWad`: see-through) -- a changed pixel sees the line
    drawn solid. `flip` (the control): the view turned 180 degrees. -> {"lowering": frames, "lowered": frames}"""
    from doomfj.doors import heights_for_states
    from doomfj.reference_model import GAME_RENDER_KW, SimState, build_scene
    g = look["group"]
    grp = dsim.mp.groups[g]
    m = orc.mapname
    proxy = OpenLineWad(orc.mw, m, look["line"], look["static"], dsim.secs[look["moving"]].ceil_h)
    seen = {"lowering": 0, "lowered": 0}
    scenes = {}
    for fr in out:
        if fr["drawn"] != "world":
            continue
        gs = fr["movers"][2][g]
        case = "lowered" if gs == grp.n - 1 else "lowering" if gs > 0 else None
        if case is None:
            continue
        x, y, a = fr["pose"]
        a = (a + (0x80000000 if flip else 0)) & M32
        h = {**heights_for_states(orc.secs, orc.lds, orc.sds,
                                  {si: fr["phase"][0][si][0] for si in dsim.order}), **fr["mheights"]}
        key = tuple(sorted(h.items()))
        if key not in scenes:
            scenes[key] = (build_scene(orc.mw, orc.mw, m, h), build_scene(proxy, proxy, m, h))
        views = [bytes(orc.rm.render_wall_frame(SimState(x, y, a, m), sc_, sprite_wad=orc.art,
                                                thing_hidden=set(orc.hidden), **GAME_RENDER_KW))   # the shared set (= probe's RENDER_KW)
                 for sc_ in scenes[key]]
        if views[0] != views[1]:
            seen[case] += 1
    return seen


def view_ok(look: dict, seen: dict) -> bool:
    """S14a must see the line with the lift down and the floor unlowered; S14b unlowered AND lowered; S15 its shut
    line solid while the floor is lowering AND once lowered"""
    if look["want"] == "lowering":
        return seen["lowering"] > 0 and seen["lowered"] > 0
    return seen["down"] > 0 if look["want"] == "down" else (seen["unlowered"] > 0 and seen["lowered"] > 0)


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
    # ---- M8 F1.3: the movers (movers.floor_groups / floor_walk_triggers / floor_use_boxes, the blazing lifts, a lift
    # tag on two sectors), each placed by a pose that WORKS on the World (the probe) -- then claimed on the twin. The
    # geometry is the WORLD's (`w0`), never the mirror's: a mutated mirror must not move the scenarios
    mp = SimpleNamespace(wide=w0.floor_wide, groups=w0.floor_groups, floor_walk=w0.floor_walk, floor_use=w0.floor_use,
                         order=list(w0.lift_order), use=w0.lift_use, walk=w0.lift_walk,
                         stops=w0.lift_stops, stride={si: w0.lift_stride[k] for k, si in enumerate(w0.lift_order)},
                         lifts_of_tag={t: tuple(w0.lift_order[k] for k in ks) for t, ks in w0.lift_of_tag.items()})
    if probe is None:
        probe = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=MONSTER_MODE, player=PLAYER_MODE)
    pw = probe.world
    tele_count = tap_monster_teleports(pw)

    def tries(pose, keys, test, setup=None):
        """run the probe World from `pose` on `keys`: does `test(world)` hold at the end?"""
        probe.reset(BOOT_SKILL)
        if setup is not None:
            setup(probe)
        ws = pw.ws
        ws.px, ws.py, ws.pangle = pose
        if not pw.rm.check_position(pw.scene_c, ws.px, ws.py)[0]:
            return False
        tele_count[0] = 0
        for kd in keys:
            pw.tic(kd)
            probe.set_seen(seen_standin(probe))
        return test(pw)

    def line_poses(x1, y1, x2, y2):
        """standing poses before a line, facing across it: both sides, a few distances, three points along it"""
        import math
        nx, ny = -(y2 - y1), (x2 - x1)
        n = math.hypot(nx, ny)
        for back in (32, 24, 40, 48, 16):
            for frac in (0.5, 0.25, 0.75):
                mx, my = x1 + (x2 - x1) * frac, y1 + (y2 - y1) * frac
                for side in (1, -1):
                    x, y = int(round(mx + side * nx / n * back)), int(round(my + side * ny / n * back))
                    yield (x << 16, y << 16, G.bam(-side * nx, -side * ny))

    def shape_ends(shape):
        if shape[0] == "d":
            return shape[1:]
        _a, c, lo, hi = shape
        return (c, lo, c, hi) if shape[0] == "x" else (lo, c, hi, c)

    def gstate(ws, g):
        return ws["f_switch"][g] if isinstance(ws["f_switch"], list) else ws["f_switch"]

    if mp.wide:
        walk_of = {}
        for g, shape in mp.floor_walk:
            walk_of.setdefault(g, []).append(shape)
        use_of = {}
        for g, box in mp.floor_use:
            use_of.setdefault(g, []).append(box)
        for g, grp in enumerate(mp.groups):
            travel = max(grp.sub, 1) * grp.n + 4
            fired = (lambda w, g=g: w.floor_state(g) or w.floor_sub(g))
            claim = (lambda ts, g=g, n=grp.n: max(gstate(t["ws"], g) for t in ts) == n - 1)
            found = None
            for shape in walk_of.get(g, ()):
                for pose in line_poses(*shape_ends(shape)):
                    if tries(pose, [F] * 10, fired):
                        found = (pose, [F] * 10 + [I] * travel, "W1 line %s" % (shape,))
                        break
                if found:
                    break
            for box in use_of.get(g, ()) if not found else ():
                try:
                    pose = G._in_box(dsim, box)
                except AssertionError:
                    continue
                if tries(pose, [I, U], fired):
                    found = (pose, [I, U] + [I] * travel, "S1 box %s" % (box,))
                    break
            if found is None:
                print("  (no pose fires floor group %d, tag %d)" % (g, grp.tag))
                continue
            out.append(("X floor group %d (tag %d, special %d, sub %d) by its %s: reaches its last state"
                        % (g, grp.tag, grp.special, grp.sub, found[2]), found[0], found[1], None, claim))
    # the blazing lifts and a tag that starts two lifts: one scenario per such tag
    for tag, sis in sorted(mp.lifts_of_tag.items()):
        if len(sis) < 2 and all(mp.stride[si] == 1 for si in sis):
            continue
        ks = [mp.order.index(si) for si in sis]
        ns = [len(mp.stops[si]) for si in sis]
        started = (lambda w, ks=ks: all(w.ws.l_state[k] for k in ks))
        claim = (lambda ts, ks=ks, ns=ns: all(max(t["ws"]["l_state"][k] for t in ts) == n - 1 for k, n in zip(ks, ns)))
        found = None
        for t_, box in mp.use:
            if t_ != tag or found:
                continue
            try:
                pose = G._in_box(dsim, box)
            except AssertionError:
                continue
            if tries(pose, [I, U, I, I], started):
                found = (pose, [I, U] + [I] * 40, "SR box")
        for trig in mp.walk if not found else ():
            if trig[0] not in sis or found:
                continue
            for pose in line_poses(*shape_ends(trig[1:])):
                if tries(pose, [F] * 6 + [I] * 2, started):
                    found = (pose, [F] * 6 + [I] * 40, "WR line %s" % (trig[1:],))
                    break
        if found is None:
            print("  (no pose starts the lifts of tag %d)" % tag)
            continue
        out.append(("X lifts %s (tag %d, strides %s) by the %s: each reaches its bottom"
                    % (list(sis), tag, [mp.stride[si] for si in sis], found[2]), found[0], found[1], None, claim))
    # the teleport closets: the floor group that lowers a teleport line's pad fires; a closet monster then walks over
    # the line and TELEPORTS (the twin's `_teleport_monster`, counted)
    if mp.wide:
        done = set()
        for tel in getattr(w0, "teleports", ()):
            ld = w0.lds[tel.line]
            pads = {w0.sds[s].sector for s in (ld.front, ld.back) if 0 <= s < len(w0.sds)}
            g = next((g for g, grp in enumerate(mp.groups) if pads & set(grp.sectors)), None)
            if g is None or g in done:
                continue
            done.add(g)
            frames = 150
            got = tele_count
            test = (lambda w, g=g: (w.floor_state(g) or w.floor_sub(g)) and got[0] > 0)
            found = None
            for shape in walk_of.get(g, ()):
                for pose in line_poses(*shape_ends(shape)):
                    keys = [F] * 10 + [I] * frames
                    if tries(pose, [F] * 10, lambda w, g=g: w.floor_state(g) or w.floor_sub(g)) \
                            and tries(pose, keys, test):
                        found = (pose, keys)
                        break
                if found:
                    break
            for box in use_of.get(g, ()) if not found else ():
                try:
                    pose = G._in_box(dsim, box)
                except AssertionError:
                    continue
                keys = [I, U] + [I] * frames
                if tries(pose, keys, test):
                    found = (pose, keys)
                    break
            if found is None:
                print("  (no pose lowers floor group %d and sees a closet monster teleport)" % g)
                continue
            out.append(("X closet of teleport line %d: floor group %d lowers its pad, a monster teleports" % (tel.line, g),
                        found[0], found[1], None,
                        lambda ts: ts and ts[-1].get("mtele", 0) > 0))
    return out


def tap_monster_teleports(world) -> list:
    """count the monster teleports a World makes (`_teleport_monster` returning another place): [count]"""
    n = [0]
    orig = getattr(world, "_teleport_monster", None)
    if orig is None:
        return n

    def tm(m, ox, oy, nx, ny, _orig=orig):
        r = _orig(m, ox, oy, nx, ny)
        if tuple(r) != (nx, ny):
            n[0] += 1
        return r
    world._teleport_monster = tm
    return n


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
    elif name == "no_floor_movers":                      # the mirror without F1.3's floor movers: no W1 / S1 floor
        from doomfj import movers as MV                  # line fires a group (MoverPhase's triggers dropped)
        init = MV.MoverPhase.__init__

        def no_floors(self, *a, **kw):
            init(self, *a, **kw)
            self.floor_walk, self.floor_use = [], []
        MV.MoverPhase.__init__ = no_floors
    elif name == "slow_lifts":                           # the mirror before F1.3's blazing lifts: every stride 1
        from doomfj import movers as MV
        init = MV.MoverPhase.__init__

        def slow(self, *a, **kw):
            init(self, *a, **kw)
            self.stride = {si: 1 for si in self.stride}
        MV.MoverPhase.__init__ = slow
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
        for name, (seen, flipped) in res.get("views", {}).items():
            look = res["looks"][name]
            good, ctl = view_ok(look, seen), not view_ok(look, flipped)
            ok &= good and ctl
            print("  VIEW  %s: frames seeing linedef %d %s -- %s; CONTROL (the view turned 180): %s %s" % (
                name.split()[0], look["line"], seen, "IN VIEW" if good else "NOT IN VIEW, FAIL", flipped,
                "rejected" if ctl else "NOT rejected, FAIL"))
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
