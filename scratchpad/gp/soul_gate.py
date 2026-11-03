"""soul_gate.py -- M8 C8 part 2's gate: THE LOST SOUL in a running game binary, byte-, state- and palette-exact.

    python tests/fixtures/make_soul_wad.py                                   # tests/fixtures/freedoom_e1m1s.wad
    DOOMFJ_MAP=E1M1S python scratchpad/gp/soul_gate.py --fjm build/doom_e1m1s_<name>.fjm --labels <its table>
    DOOMFJ_MAP=E1M1S python scratchpad/gp/soul_gate.py --oracle-only         # the scenarios, counters and controls

THE MAP is the test map E1M1S (tests/fixtures/make_soul_wad.py): E1M1 with three lost souls in front of the start --
the soul's own maps (E1M6, E1M7) cannot build until their other clusters land. hurt_gate's shape (p2a_gate.Mirror in
the game tier's modes, hurt_gate's Run / parts / binary_scenario): each scenario POKES the binary at frame 0's start
(the world mode, the player's pose, the cells its setup moved -- the souls stay at their spawns, so no leaf list is
poked) and at every frame's start the held-key flags; the binary runs its own tics and render; at every present the
probe reads every cell the expectation names -- with MonsterPhase.soul_state's sk_fly sk_inf sk_z sk_momz sk_ceil --
STATE-, PIXEL- AND PALETTE-EXACT ON EVERY FRAME.

THE SCENARIOS (candidates tried in order until the oracle does what the scenario claims):
  L1 a soul charges the player and SLAMS him (hurt, the charge's end, its float back up to him)
  L2 a soul charges ANOTHER soul (infighting: its target poked) and slams it -- the victim turns on it
  L3 a soul shot dead with the shotgun: its death states, then REMOVED (no corpse, out of its leaf list)
  L4 a CHARGING soul shot: no pain (the roll drawn), its momentum zeroed then the thrust -- a slide at no friction
THE CONTROLS (R9: an ORACLE MUTATION each, which must part from the oracle on some frame of its scenario):
  octant_charge (the charge along the facing octant), slam_free (a slam deals no damage), no_bounce (no floor bounce),
  floor_draw (a soul drawn on its floor, not at its z: a PICTURE control), no_removal (S_NULL keeps it),
  fly_pain (a charging soul enters its pain state)
"""
from __future__ import annotations

import argparse
import contextlib
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

if __name__ == "__main__":
    from doomfj.mapprofile import take_map_arg
    take_map_arg()
import probe as P                                                            # noqa: E402
import onewalk                                                               # noqa: E402
import p2a_gate as G                                                         # noqa: E402
import hurt_gate as H                                                        # noqa: E402
from doomfj import gamedata as gd                                            # noqa: E402
from doomfj.things import drawable_things                                    # noqa: E402

I = {}


# ================================================================================================
# setups
# ================================================================================================
def wake(mph, m: int, target: int = 1) -> None:
    """soul m awake in its see state, its target `target` (1 the player, 2 + slot a monster)"""
    ws = mph.world.ws
    see = mph.world.mon_info[m].seestate
    ws.mon_state[m], ws.mon_tics[m] = gd.THING_STATE_INDEX[see], gd.STATES[see].tics
    ws.mon_target[m], ws.mon_reaction[m], ws.mon_movecount[m] = target, 0, 0


def high(mph, m: int) -> None:
    """soul m awake, as high in its room as its ceiling lets it (P_ZMovement's clamp), its target the player"""
    wake(mph, m)
    w = mph.world
    k = w.soul_of[m]
    w.ws.sk_z[k] = (min(w.ws.mon_floorz[m] + 100, w.ws.sk_ceil[k] - 56)) << 16


def freeze(mph, souls, but=None) -> None:
    """every soul but `but` held in its spawn state for ever (world.TICS_FOREVER: no A_Look, so it never wakes) --
    the cost pair's quiet souls"""
    from doomfj.world import TICS_FOREVER
    for m in souls:
        if m != but:
            mph.world.ws.mon_tics[m] = TICS_FOREVER


def shotgun(mph, shells: int = 30) -> None:
    ws = mph.world.ws
    ws.p_owned[gd.WP_SHOTGUN] = 1
    ws.p_ammo[gd.AM_SHELL] = shells


# ================================================================================================
# counters
# ================================================================================================
def counters(tr: list, souls) -> dict:
    c = {"charges": 0, "slam_player": 0, "slam_mon": 0, "slam_other": 0, "stops": 0, "floats": 0,
         "player_hurt": 0, "deaths": 0, "dead_frames": 0, "soul_kills": 0, "removed": 0, "airborne": 0,
         "fly_hits": 0, "bounces": 0, "flyhits": 0}
    prev_active = None
    for fr in tr:
        for ev in fr["ev"]:
            if ev is None:
                continue
            for e in ev.souls:
                if e[0] == "charge":
                    c["charges"] += 1
                elif e[0] == "slam":
                    c["slam_player" if e[2] == "player" else "slam_mon" if e[2] == "mon" else "slam_other"] += 1
                elif e[0] == "stop":
                    c["stops"] += 1
                elif e[0] == "float":
                    c["floats"] += 1
                elif e[0] == "bounce":
                    c["bounces"] += 1
                elif e[0] == "flyhit":
                    c["flyhits"] += 1
            c["player_hurt"] += len(ev.player_hurt)
            c["deaths"] += ev.deaths
            c["soul_kills"] += sum(1 for k in ev.kills if k[0] == "mon" and k[1] in souls)
            c["fly_hits"] += sum(1 for h in ev.hits if h[1] == "mon" and h[2] in souls)
        st = fr["mstate"]
        c["dead_frames"] += bool(st.get("p_dead"))
        act = st.get("mon_active")
        if prev_active is not None and act is not None:
            c["removed"] += sum(1 for m in souls if prev_active[m] and not act[m])
        prev_active = act
        z, fly = st.get("sk_z"), st.get("sk_fly")
        if z is not None:
            zs = z if isinstance(z, tuple) else (z,)
            fl = st.get("mon_floorz")
            c["airborne"] += sum(1 for k, m in enumerate(souls)
                                 if ((zs[k] >> 16) - (fl[m] if fl[m] < 0x8000 else fl[m] - 0x10000)) > 0)
    return c


# ================================================================================================
# the controls
# ================================================================================================
@contextlib.contextmanager
def control(name):
    from doomfj import lostsoul as LS
    from doomfj import monsters as MS
    from doomfj import world as W
    saved = []

    def patch(obj, attr, val):
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, val)
    if name == "octant_charge":
        orig = LS.SoulMixin._a_skull_attack

        def octant(self, m, ev):
            pta = self.rm.point_to_angle
            self.rm.point_to_angle = lambda *a: pta(*a) & ~((1 << 29) - 1)
            try:
                orig(self, m, ev)
            finally:
                del self.rm.point_to_angle
        patch(LS.SoulMixin, "_a_skull_attack", octant)
    elif name == "slam_free":
        orig = LS.SoulMixin._soul_slam

        def free(self, m, hit, ev):
            orig(self, m, ("decor", -1), ev)
        patch(LS.SoulMixin, "_soul_slam", free)
    elif name == "no_bounce":
        orig = LS.SoulMixin._soul_z_move

        def nob(self, m, ev=None):
            k = self.soul_of[m]
            fly = self.ws.sk_fly[k]
            if self.ws.sk_z[k] + self.ws.sk_momz[k] <= self.ws.mon_floorz[m] << 16:
                self.ws.sk_fly[k] = 0
            orig(self, m, ev)
            self.ws.sk_fly[k] = fly
        patch(LS.SoulMixin, "_soul_z_move", nob)
    elif name == "floor_draw":
        orig = MS.MonsterViews.positions

        def flat(self, phase):
            return [p[:2] for p in orig(self, phase)]
        patch(MS.MonsterViews, "positions", flat)
    elif name == "no_removal":
        orig = W.World._set_state

        def keep(self, m, name_, run_action, ev):
            if name_ == gd.S_NULL and m in self.soul_of:
                return False
            return orig(self, m, name_, run_action, ev)
        patch(W.World, "_set_state", keep)
    elif name == "fly_pain":
        orig = LS.SoulMixin._soul_damaged

        def pain(self, m, ev=None):
            orig(self, m, ev)
            self.ws.sk_fly[self.soul_of[m]] = 0
        patch(LS.SoulMixin, "_soul_damaged", pain)
    elif name is not None:
        raise KeyError(name)
    try:
        yield
    finally:
        for obj, attr, val in reversed(saved):
            setattr(obj, attr, val)


# ================================================================================================
# the scenarios
# ================================================================================================
def scenario_list(dsim, w) -> list:
    souls = list(w.soul_slots)
    out = []

    def cands(dists, setup_of, slots=souls):
        return [(pose, setup_of(m)) for m in slots for d in dists for pose in H.facing_pose(dsim, w, m, d)]
    out.append({
        "name": "L1 a soul charges the player and slams him", "keys": [I] * 70,
        "controls": ["octant_charge", "slam_free", "floor_draw"],
        "cands": cands((192, 160, 224, 256), lambda m: (lambda mph, m=m: wake(mph, m))),
        "claim": lambda c: c["charges"] >= 1 and c["slam_player"] >= 1 and c["player_hurt"] >= 1})
    pairs = [(a, b) for a in souls for b in souls if a != b]
    out.append({
        "name": "L2 a soul charges another soul and slams it", "keys": [I] * 50,
        "controls": ["slam_free"],
        "cands": [(pose, (lambda mph, a=a, b=b: wake(mph, a, 2 + b))) for a, b in pairs
                  for pose in H.facing_pose(dsim, w, b, 320)],
        "claim": lambda c: c["slam_mon"] >= 1})
    gun = [{"w3": True}] + [I] * 30 + [{"fire": True}] * 24 + [I] * 30
    out.append({
        "name": "L3 a soul shot dead: its death, then removed", "keys": gun, "controls": ["no_removal"],
        "cands": cands((112, 128, 96, 144), lambda m: (lambda mph: shotgun(mph))),
        "claim": lambda c: c["soul_kills"] >= 1 and c["removed"] >= 1})
    gun2 = [{"w3": True}] + [I] * 20 + [{"fire": True}] * 30 + [I] * 10
    out.append({
        "name": "L4 a charging soul shot: no pain, the thrust's slide", "keys": gun2, "controls": ["fly_pain"],
        "cands": cands((256, 224, 288, 192, 320, 352, 160), lambda m: (lambda mph, m=m: (shotgun(mph), wake(mph, m)))),
        "claim": lambda c: c["flyhits"] >= 1})
    dodge = [I] * 3 + [{"strafe_left": True}] * 12 + [I] * 35
    out.append({
        "name": "L5 a soul charges down from high: it misses and BOUNCES off the floor", "keys": dodge,
        "controls": ["no_bounce"],
        "cands": cands((192, 224, 256, 160), lambda m: (lambda mph, m=m: high(mph, m))),
        "claim": lambda c: c["bounces"] >= 1})
    return out


def place(run, sc, souls, limit: int = 16):
    for pose, setup in sc["cands"][:limit]:
        tr, _mr = run(pose, sc["keys"], setup)
        c = counters(tr, souls)
        if c["deaths"] == 0 and c["dead_frames"] == 0 and sc["claim"](c):
            return pose, setup, tr, c
    return None


class Run(H.Run):
    def __call__(self, pose, keys, setup, ctl=None):
        with control(ctl):
            mr = self.mirror(setup)
            tr = mr.run(pose, keys, 0)
        return tr, mr


def cost_pair(gb, cells, table, run, souls, pose, m) -> bool:
    """the op cost of ONE ACTIVE SOUL a frame: C1 (soul m awake: its chase, charge, flight, slam, float -- and its
    sprite where it flies) minus C0 (every soul frozen in its spawn state, drawn where it spawned), frame by frame"""
    keys = [I] * 40
    ok, ops = True, {}
    for name, setup in (("C1 one soul active (cost)", lambda mph: (freeze(mph, souls, m), wake(mph, m))),
                        ("C0 every soul frozen (cost)", lambda mph: freeze(mph, souls))):
        sc = {"name": name, "keys": keys}
        want, _mr = run(pose, keys, setup)
        c = counters(want, souls)
        print("\n%s -- %d frames; counters: %s" % (name, len(keys), ", ".join("%s %d" % kv for kv in c.items() if kv[1])))
        before = len(H.FRAME_OPS_LOG)
        ok &= H.binary_scenario(gb, cells, table, run, sc, pose, setup, want)
        ops[name[:2]] = H.FRAME_OPS_LOG.get(name) if len(H.FRAME_OPS_LOG) > before else None
    if ops["C1"] and ops["C0"]:
        d = [a - b for a, b in zip(ops["C1"], ops["C0"])]
        ds = sorted(d)
        print("\nCOST of one active soul (C1 - C0 ops a frame, %d frames): median %s, min %s, max %s, mean %s; "
              "C0's median frame %s" % (len(d), format(ds[len(d) // 2], ","), format(ds[0], ","), format(ds[-1], ","),
                                         format(sum(d) // len(d), ","), format(sorted(ops["C0"])[len(d) // 2], ",")))
        print("  per frame: " + " ".join(str(v) for v in d))
    else:
        print("\nCOST: no frame ops recorded (run with --frame-ops)")
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fjm")
    ap.add_argument("--labels")
    ap.add_argument("--oracle-only", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--frame-ops", nargs="?", const="-", metavar="FILE")
    ap.add_argument("--cost", action="store_true",
                    help="after L1: THE COST PAIR -- L1's pose, 40 idle frames, (C1) L1's soul awake and every other "
                         "soul frozen, (C0) every soul frozen; both state/pixel-exact, their per-frame ops differenced")
    a = ap.parse_args(argv)
    if not a.oracle_only and not (a.fjm and a.labels):
        ap.error("--fjm and --labels, or --oracle-only")
    H.FRAME_OPS = a.frame_ops
    t0 = time.time()
    orc = P.Oracle()
    dsim = onewalk.DoorSim()
    card_di = [di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
               if t.type == G.CARD_TYPE][0]
    run = Run(orc, dsim, card_di)
    from doomfj.monsters import MonsterPhase, drop_rows
    from doomfj.wall_renderer import BOOT_SKILL
    w0 = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=H.MMODE, player=H.PMODE)
    souls = list(w0.world.soul_slots)
    assert souls, "the map has no lost soul: run with DOOMFJ_MAP=E1M1S (tests/fixtures/make_soul_wad.py)"
    nrt = orc._mv(w0.world).nrt
    ndrop = drop_rows(w0.world)
    orc.player_mode = H.PMODE
    scen = [s for s in scenario_list(dsim, w0.world) if not a.only or s["name"].startswith(a.only)]
    ok = True
    print("SOUL GATE -- %d scenarios on %s (souls %s)%s" % (len(scen), dsim.mapname, souls,
                                                          "" if a.oracle_only else ", %s" % a.fjm))
    if not a.oracle_only:
        gb = P.GameBinary(ROOT / a.fjm)
        cells = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis,
                             modes=(H.PMODE, H.MMODE))
        for k in H.KEYFLAG.values():
            cells.setdefault(k, P.Cell(k, "hex", 1))
        table = P.LabelTable.load(ROOT / a.labels, {c.label for c in cells.values()})
        assert not table.absent & {"sk_z", "sk_fly"}, "the label table has no soul cells: not a soul binary"
    totals = {}
    for sc in scen:
        got = place(run, sc, souls)
        print("\n%s -- %d frames" % (sc["name"], len(sc["keys"])))
        if got is None:
            ok = False
            print("  the oracle does what the scenario claims: NO candidate -- FAIL")
            continue
        pose, setup, want, c = got
        print("  from (%.0f, %.0f) angle %08x: the oracle does what the scenario claims: yes"
              % (pose[0] / 65536, pose[1] / 65536, pose[2]))
        print("  counters: " + ", ".join("%s %d" % kv for kv in c.items()))
        for k, v in c.items():
            totals[k] = totals.get(k, 0) + v
        for ctl in sc["controls"]:
            alt, _mr = run(pose, sc["keys"], setup, ctl)
            pt = H.parts(run, want, alt, nrt, ndrop)
            if pt is None and ctl == "floor_draw":       # a picture control: the cells agree, the pictures must not
                pt = next(((f, "picture") for f, (x, y) in enumerate(zip(want, alt))
                           if x["drawn"] == "world" and run.picture(x) != run.picture(y)), None)
            ok &= pt is not None
            print("  CONTROL %-14s the oracle without the rule parts at frame %s%s" % (
                ctl, "%d (%s)" % pt if pt else None, "" if pt else " -- NEVER: VACUOUS, FAIL"))
        if a.oracle_only:
            continue
        ok &= H.binary_scenario(gb, cells, table, run, sc, pose, setup, want)
        if a.cost and sc["name"].startswith("L1"):
            ok &= cost_pair(gb, cells, table, run, souls, pose, setup.__defaults__[0])
    need = ("charges", "slam_player", "slam_mon", "player_hurt", "soul_kills", "removed", "airborne", "fly_hits",
            "flyhits", "bounces")
    zero = [k for k in need if not totals.get(k)] if not a.only else []
    ok &= not zero
    print("\nTOTALS: " + ", ".join("%s %d" % kv for kv in totals.items()))
    print("every soul counter nonzero: %s" % ("yes" if not zero else "NO -- %s" % zero))
    H.write_frame_ops()
    print("\nSOUL GATE %s%s (%.0f s)" % ("PASS" if ok else "FAIL", " (oracle only)" if a.oracle_only else "",
                                         time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
