"""fight_gate.py -- M7 P6's gate: pickups, drops, berserk, barrels, blocking, nukage (docs/gp-p67-interface.md 6.1).

    python scratchpad/gp/fight_gate.py --fjm build/<new>.fjm --labels <its label table>
    python scratchpad/gp/fight_gate.py --oracle-only [--only F6]    # the scenarios, their counters and controls
    ... [--modes PLAYER/MONSTER] [--frame-ops [FILE]]   # M7 P8a: the modes (default the game tier's); per-frame ops

hurt_gate's shape (p2a_gate.Mirror in the game tier's "full" modes, hurt_gate's Run / place / parts): each scenario
starts by POKING the game tier at frame 0's start -- the world mode, the player's pose, and every cell the scenario's
SETUP moved away from the boot level start -- and, at a LATE setup's frame, the cells and the pose it moved then
(`Mirror.late`: a teleport, a NEW GAME's follow-up); at every frame's start the held-key flags; menu keys are real key
events. The binary then runs its own tics and render. At every present the probe reads every cell the expectation
names (P6 adds p_bc p_str p_bp am_misl am_cell, bar_st bar_ti bar_hp bar_solid rng_wd, mdrop dr_live, lvtime g_rs
g_skill, thvis, the drop rows of thpos_rt / thss_rt) and the frame is held against THE ORACLE: the picture with what
the game removed, the barrels by state, the drops and the puffs; the palette with the bonus and the berserk.
STATE-, PIXEL- AND PALETTE-EXACT ON EVERY FRAME. DEATHS MUST BE 0: a scenario that kills the player FAILS, loudly
(die_gate.py's are the deaths).

THE SCENARIOS (each a list of candidates tried in order until the oracle does what it claims; `place`):
  F1  pickups at hard: a cluster walked through -- bonuses over 100, clips; the gold palette
  F1r an item out of REACH: the blue card from sector 124, 112 units below it
  F2  refused pickups: a medikit at 100 health, a clip at max ammo (poked)
  F3  the chainsaw (sector 139): owned, pending, raised; key 1 keeps it
  F4  drops: a zombieman's clip and a sergeant's shotgun (hard: the only shotgun), drawn ON the floor, then taken
  F5  berserk at MEDIUM (NEW GAME medium from the menu): PSTR taken, the red tint, a punch gibs a zombieman (x10)
  F6  a barrel shot near a sergeant: the puffs, the non-lethal hits' rng_world draws, BEXP drawn, the blast gibs the
      sergeant (which drops) and hurts the player (blue armor poked)
  F6p a barrel PUNCHED: the fist's puff is S_PUFF3
  F7  THE CHAIN: the column of barrels 6 .. 21 set off by one shot
  F8a/b/c/d blocking: a barrel, a solid decor, a live monster refuse the player; a corpse lets him through
  F9  nukage: standing in sector 23 for 70 frames; F9l on its rim, the box over a higher floor (no damage)
  F10 the blue card: pcard 1, the bonus SET to 6 then +6 = 12, the gold palette
  S2  stress: F7's chain in view (recorded, no claim on ops)

THE CONTROLS (R9): each an ORACLE MUTATION that must part from the oracle -- cells, palette, or picture -- on some
frame of its scenario, else the gate FAILS as vacuous (see `control`). Not taken from the plan's list, and why:
`order` (drops before map things) -- no dropper of E1M1 stands within a player's box of a map item of an ammo or
weapon that the order could decide; `decor_skill` -- every solid decor of E1M1 stands on every skill; `blast_order`
(barrels before monsters) -- a blast's targets draw from different streams (rng_pl, each mon_rng, rng_world), so the
order of the player, the monsters and the barrels moves no cell (host: test_p67_model holds the barrels' own order);
`blast_los` -- no blast of a barrel the player can shoot reaches a target a wall hides (MEASURED: every candidate of
F6 and F7; the plan's 96 barrel pairs all see each other), so the rule is held on the host (test_p67_model).
`drop_z` rides F4s: a zombieman's clip lies inside its corpse's columns, past the scenery budget in every candidate
of F4, so its height draws nothing there.

M7 P8a (docs/gp-final-plan.md 5.2; p8a_lib.py): the modes are the GAME TIER's (`--modes` for an --oracle-only run at the
rung's target), and section 5.2's rows join -- KNOCKBACK K1 (pushed away, decays, stops), K2 (into a wall: zeroed),
K3 (a blast throws the player and a crowd), K4s / K4d (the shotgun on a sergeant: fractions, re-tests, a relink; on a
demon: mass 400), K5 (a shotgun kill: the corpse slides, its drop stays), K6 (the chainsaw: no thrust), K7 (the
reversal; N/A when no E1M1 position reaches it); INFIGHTING I1 (a sergeant through an imp: hit, blood, switched), I2z /
I2i (an imp's fireball into a zombieman: switched; into an imp: the species rule), I3 (a stray shot kills a barrel:
bar_src), I4 (the target dies), I5 (a target behind a wall: the far LOS), I6 (the threshold); THE COMPOSITOR C1 / C2
(D3 a: a drop, blood before their monster), C3 (D3 b: a far barrel) -- each placed only where its rule decides a
pixel (`claim_ctl`); STRESS S3 (a brawl), S4 (a push storm). Each names its `rule` and `pkg`: at modes without the
rule it is N/A; while its package is not in the tree it AWAITS it and the gate ends INCOMPLETE (exit 2), never PASS.
Their controls (p8a_lib.CONTROLS) break the model from outside the packages' code; a PICTURE control (D3 a / b, A's
split) is judged on the same trace's pictures. `--frame-ops` prints each binary scenario's per-frame ops (S2-S4).
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

import probe as P                                                            # noqa: E402
import onewalk                                                               # noqa: E402
import p2a_gate as G                                                         # noqa: E402
import hurt_gate as H                                                        # noqa: E402
from doomfj import gamedata as gd                                            # noqa: E402
from doomfj.fixedpoint import _signed                                        # noqa: E402
from doomfj.things import drawable_things                                    # noqa: E402

M32 = 0xFFFFFFFF
# the game tier's modes (M7 P8a: wall_renderer's -- "full" / "full" through P6+P7, "final" / "final" from P8a; `--modes`
# sets another for an --oracle-only run); a binary run asserts them against wall_renderer's
from doomfj.wall_renderer import MONSTER_MODE as MMODE, PLAYER_MODE as PMODE   # noqa: E402
import p8a_lib as P8                                                         # noqa: E402  (M7 P8a)
NORTH, SOUTH, EAST, WEST = 0x40000000, 0xC0000000, 0, 0x80000000
I, F, B = {}, {"forward": True}, {"back": True}
FIRE = {"fire": True}
DROP_LUMPS = frozenset(("CLIPA0", "SHOTA0"))
BEXP_LUMPS = frozenset(("BEXPA0", "BEXPB0", "BEXPC0", "BEXPD0", "BEXPE0"))


# ================================================================================================
# the events and the frames a run made
# ================================================================================================
def counters(tr: list) -> dict:
    """hurt_gate's counters, and P6's: pickups (items, drops), the gold and the berserk palettes, gibs, the drops and
    the explosions drawn, barrel blasts, puffs, the blasts' kills, a barrel's hits on the player, blocking, nukage --
    and P7's (deaths, restarts) so a gate can refuse them"""
    c = H.counters(tr)
    c.update({k: 0 for k in ("pickups", "pickup_items", "pickup_drops", "bonus_frames", "berserk_frames", "gibs",
                             "drop_frames", "bexp_frames", "barrel_blasts", "puffs", "blast_kills", "barrel_hurt",
                             "player_blocked", "nukage", "restarts", "restart_requests", "level_done",
                             "barrel_hits")})
    for fr in tr:
        for k, ev in enumerate(fr["ev"]):
            if ev is None:
                continue
            c["pickups"] += len(ev.pickups)
            c["pickup_items"] += sum(1 for p in ev.pickups if p[0] == "item")
            c["pickup_drops"] += sum(1 for p in ev.pickups if p[0] == "drop")
            c["gibs"] += sum(1 for kk in ev.kills if kk[0] == "mon" and kk[2] == "gib")
            c["barrel_blasts"] += len(ev.barrel_blasts)
            c["puffs"] += sum(1 for s in ev.fx_spawns if s[1] == "puff")
            c["barrel_hurt"] += sum(1 for h in ev.player_hurt if h[0][0] == "bar")
            c["barrel_hits"] += sum(1 for h in ev.hits if h[1] == "bar")
            c["player_blocked"] += ev.player_blocked
            c["nukage"] += ev.nukage
            c["restarts"] += ev.restarts
            c["restart_requests"] += ev.restart_requests
            c["level_done"] += int(ev.level_done)
            if k == len(fr["ev"]) - 1:            # the world tic (monsters, pools, BARRELS): a blast's kills
                c["blast_kills"] += sum(1 for kk in ev.kills if kk[0] == "mon") if ev.barrel_blasts else 0
        st = fr["mstate"]
        if fr["drawn"] == "world":
            c["bonus_frames"] += 9 <= fr["pal"] <= 12
            c["berserk_frames"] += bool(st.get("p_str")) and 1 <= fr["pal"] <= 8
        c["drop_frames"] += any(len(mo) > 3 for mo in fr["mobiles"])
        c["bexp_frames"] += any(v in BEXP_LUMPS for v in (fr.get("bviews") or {}).values())
    # M7 P8a: the knock / infighting / sink counters (p8a_lib.counters), the monsters' attacks, the kills
    c.update(P8.counters(tr))
    c["mon_attacks"] = sum(len(ev.attacks) for fr in tr for ev in fr["ev"] if ev is not None)
    c["mkills"] = sum(1 for fr in tr for ev in fr["ev"] if ev is not None for kk in ev.kills if kk[0] == "mon")
    return c


# ================================================================================================
# the controls: ONE mutated rule each (R9)
# ================================================================================================
@contextlib.contextmanager
def control(name: str | None):
    """the oracle with rule `name` broken, for the duration (None: the oracle). hurt_gate's controls pass through."""
    from doomfj import combat as C
    from doomfj import monsters as MS
    CM = C.CombatMixin
    saved = []

    def patch(obj, attr, val):
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, val)
    if name is None:
        pass
    elif name in P8.CONTROLS:                    # M7 P8a: the final rung's controls (p8a_lib)
        with P8.control(name):
            yield
        return
    elif name == "bonus_cap":                    # a health bonus capped at 100, not 200
        patch(C, "MAX_HEALTH_BONUS", gd.MAXHEALTH)
    elif name == "bonus_round":                  # the gold palette without DOOM's +7 rounding
        orig_pal = C.palette_index

        def pal(ws):
            out = orig_pal(ws)
            if 9 <= out <= 12:
                return min(C.NUMBONUSPALS - 1, ws.p_bonuscount >> 3) + C.STARTBONUSPALS
            return out
        patch(C, "palette_index", pal)
    elif name == "reach":                        # P_TouchSpecialThing's z window dropped
        patch(C, "REACH_UP", 1 << 20)
        patch(C, "REACH_DOWN", 1 << 20)
    elif name == "give_always":                  # every give routine takes its item
        for fn in ("_give_body", "_give_ammo", "_give_armor"):
            orig = getattr(CM, fn)

            def always(self, *a, _orig=orig):
                _orig(self, *a)
                return True
            patch(CM, fn, always)
    elif name == "no_pending":                   # a new weapon is not made pending
        orig_gw = CM._give_weapon

        def gw(self, w, dropped):
            p = self.ws.p_pending
            out = orig_gw(self, w, dropped)
            self.ws.p_pending = p
            return out
        patch(CM, "_give_weapon", gw)
    elif name == "no_drop":                      # a killed dropper drops nothing
        orig_kill = CM._kill_monster

        def kill(self, m, ev):
            d = self.ws.mon_drop[m]
            orig_kill(self, m, ev)
            self.ws.mon_drop[m] = d
        patch(CM, "_kill_monster", kill)
    elif name == "drop_full_clip":               # a dropped clip gives a full clip
        orig_touch = CM._touch

        def touch(self, kind, dropped, item_z, z):
            return orig_touch(self, kind, dropped and kind != 2007, item_z, z)
        patch(CM, "_touch", touch)
    elif name == "drop_z":                       # the drop drawn at MISSILE_Z, not on the floor
        orig_mob = MS.MonsterPhase.mobiles

        def mob(self):
            return [m[:3] for m in orig_mob(self)]
        patch(MS.MonsterPhase, "mobiles", mob)
    elif name == "berserk_x10":                  # the berserk fist hits x1
        orig_melee = CM._a_melee

        def melee(self, weapon, ev):
            st = self.ws.p_strength
            self.ws.p_strength = 0
            orig_melee(self, weapon, ev)
            self.ws.p_strength = st
        patch(CM, "_a_melee", melee)
    elif name == "strength_pal":                 # the palette ignores berserk
        orig_pal = C.palette_index

        def pal(ws):
            import types
            return orig_pal(types.SimpleNamespace(p_damagecount=ws.p_damagecount, p_bonuscount=ws.p_bonuscount,
                                                  p_strength=0))
        patch(C, "palette_index", pal)
    elif name == "gib":                          # no xdeath: a gib is a plain death
        orig_kill = CM._kill_monster

        def kill(self, m, ev):
            h = self.ws.mon_health[m]
            self.ws.mon_health[m] = max(h, -self.mon_info[m].spawnhealth)
            orig_kill(self, m, ev)
            self.ws.mon_health[m] = h
        patch(CM, "_kill_monster", kill)
    elif name == "blast_los":                    # the blast ignores line of sight
        orig_ra = CM._radius_attack

        def ra(self, b, ev):
            los = self.los_points
            self.los_points = lambda p, q: True
            try:
                orig_ra(self, b, ev)
            finally:
                del self.los_points
                assert self.los_points == los
        patch(CM, "_radius_attack", ra)
    elif name == "blast_cheb":                   # the blast measures P_AproxDistance, not Chebyshev
        def ra(self, b, ev):
            from doomfj.world import aprox_distance
            ws = self.ws
            t = self.barrel_things[b]
            spot = (t.x << 16, t.y << 16)
            ev.barrel_blasts.append(b)

            def dist(x16, y16, r):
                return max(0, aprox_distance((x16 - spot[0]) >> 16, (y16 - spot[1]) >> 16) - r)
            if self.player_alive():
                d = dist(ws.px, ws.py, C.PLAYER_R)
                if d < C.BOMB_DAMAGE and self.los_points((ws.px, ws.py), spot):
                    self.damage_player(C.BOMB_DAMAGE - d, ("bar", b), ("bar", b), ev)
            for m in range(self.layout.nmon):
                if not (ws.mon_active[m] and ws.mon_shootable[m] and ws.mon_health[m] > 0):
                    continue
                p = (ws.mon_x[m] << 16, ws.mon_y[m] << 16)
                d = dist(p[0], p[1], self.mon_radius[m])
                if d < C.BOMB_DAMAGE and self.los_points(p, spot):
                    ev.hits.append(("barrel", "mon", m, C.BOMB_DAMAGE - d))
                    self.damage_monster(m, C.BOMB_DAMAGE - d, ("player", -1), ("bar", b), ev)
            for c_, tc in enumerate(self.barrel_things):
                if c_ == b or not ws.bar_state[c_] or ws.bar_health[c_] <= 0:
                    continue
                p = (tc.x << 16, tc.y << 16)
                d = dist(p[0], p[1], C.BARREL_R)
                if d < C.BOMB_DAMAGE and self.los_points(p, spot):
                    ev.hits.append(("barrel", "bar", c_, C.BOMB_DAMAGE - d))
                    self.damage_barrel(c_, C.BOMB_DAMAGE - d, ("player", -1), ev)
        patch(CM, "_radius_attack", ra)
    elif name == "barrel_pain_draw":             # a non-lethal hit on a barrel draws nothing
        orig_db = CM.damage_barrel

        def db(self, b, dmg, source, ev):
            r = self.ws.rng_world
            alive = self.ws.bar_state[b] and self.ws.bar_health[b] > 0
            orig_db(self, b, dmg, source, ev)
            if alive and self.ws.bar_health[b] > 0:
                self.ws.rng_world = r
        patch(CM, "damage_barrel", db)
    elif name == "puff_melee":                   # the fist's puff is S_PUFF1, not S_PUFF3
        orig_fx = CM._spawn_fx

        def fx(self, kind, x16, y16, dmg, melee, ev):
            return orig_fx(self, kind, x16, y16, dmg, False, ev)
        patch(CM, "_spawn_fx", fx)
    elif name == "chain_same_tic":               # a barrel killed this pass with a higher index waits a tic
        def bp(self, ev):
            from doomfj.world import TICS_FOREVER
            ws = self.ws
            start = [ws.bar_state[b] for b in range(self.layout.nbarrel)]
            for b in range(self.layout.nbarrel):
                if not ws.bar_state[b] or ws.bar_tics[b] == TICS_FOREVER:
                    continue
                if ws.bar_state[b] == gd.STATE_INDEX["S_BEXP"] and start[b] != ws.bar_state[b]:
                    continue                     # killed in this pass: not ticked until the next
                ws.bar_tics[b] -= 1
                if ws.bar_tics[b] == 0:
                    self._barrel_set_state(b, gd.STATES[gd.STATE_NAMES[ws.bar_state[b]]].next, ev)
        patch(CM, "_barrels_phase", bp)
    elif name == "walk_through":                 # the player walks through solid things
        orig_init = CM._combat_init

        def init(self, aim=None, player_blocking=True):
            orig_init(self, aim, False)
        patch(CM, "_combat_init", init)
    elif name == "corpse_blocks":                # a corpse blocks: mon_active for mon_solid
        orig_st = CM._solid_thing_at

        def sta(self, x16, y16):
            ws = self.ws
            for m in range(self.layout.nmon):
                if ws.mon_active[m] and not ws.mon_solid[m]:
                    bd = (self.mon_radius[m] + C.PLAYER_R) << 16
                    if abs((ws.mon_x[m] << 16) - x16) < bd and abs((ws.mon_y[m] << 16) - y16) < bd:
                        return ("mon", m)
            return orig_st(self, x16, y16)
        patch(CM, "_solid_thing_at", sta)
    elif name == "nuk_period":                   # nukage every 16 tics, not 32
        patch(C, "HURT_PERIOD_MASK", 0xF)
    elif name == "nuk_floor":                    # nukage without the "on the floor" test
        orig_ss = CM._special_sector

        def ss(self, ev):
            rm = self.rm
            orig_cp = rm.check_position
            sec = self.player_sector()

            def cp(scene, x, y):
                ok, _fz, c = orig_cp(scene, x, y)
                return ok, self.secs_c[sec].floor_h, c
            rm.check_position = cp
            try:
                orig_ss(self, ev)
            finally:
                del rm.check_position
        patch(CM, "_special_sector", ss)
    elif name == "card_bonus":                   # the card adds 6 (not SET 6, then +6)
        orig_touch = CM._touch

        def touch(self, kind, dropped, item_z, z):
            bc = self.ws.p_bonuscount
            out = orig_touch(self, kind, dropped, item_z, z)
            if kind == 5 and out:
                self.ws.p_bonuscount = min(bc + gd.BONUSADD, 255)
            return out
        patch(CM, "_touch", touch)
    else:
        saved_h = H.control(name)                # hurt_gate's (armor, hwt, palette, ...)
        saved_h.__enter__()
        try:
            yield
        finally:
            saved_h.__exit__(None, None, None)
        return
    try:
        yield
    finally:
        for obj, attr, val in reversed(saved):
            setattr(obj, attr, val)


# ================================================================================================
# the oracle: hurt_gate's Run with this gate's controls and LATE setups
# ================================================================================================
class Run(H.Run):
    controls = staticmethod(control)

    def mirror(self, setup, late=None):
        mr = G.hooked(G.Mirror(self.dsim, self.card_di), self.orc, self.dsim, self.card_di)
        mr.mmode, mr.pmode, mr.setup = MMODE, PMODE, setup
        mr.late = dict(late or {})
        return mr

    def __call__(self, pose, keys, setup, ctl=None, late=None):
        with self.controls(ctl):
            mr = self.mirror(setup, late)
            tr = mr.run(pose, keys, 0)
        return tr, mr



@contextlib.contextmanager
def drops_keep_rank():
    """M7 P8a (package C's D3 a, `rt_rank`): the oracle ranks a mobile by its POOL (reference_model.MOBILE_RANK:
    fireballs 1, blood and puffs 0) and a drop by its z 0 -- so `drop_z`'s mutant picture (the drop at MISSILE_Z, a
    3-tuple) would be refused as a mobile of no pool. While it is drawn, the drops' lumps (CLIP, SHOT) rank as the drops
    they are: the mutant moves the drop's HEIGHT only, as it did before D3 a"""
    from doomfj import reference_model as RM
    old = getattr(RM, "MOBILE_RANK", None)
    if old is None:
        yield
        return
    RM.MOBILE_RANK = dict(old, CLIP=0, SHOT=0)
    try:
        yield
    finally:
        RM.MOBILE_RANK = old


def place(run: Run, sc: dict, limit: int = 12, deaths_ok: bool = False):
    """the first candidate on which the oracle does what the scenario claims -> (cand, trace, counters). A
    candidate is (pose, setup) or (pose, setup, late). `deaths_ok` False: a candidate that kills is refused"""
    for cand in sc["cands"][:sc.get("limit", limit)]:       # M7 P8a: a scenario may try more (`limit`)
        pose, setup = cand[0], cand[1]
        late = cand[2] if len(cand) > 2 else None
        tr, _mr = run(pose, sc["keys"], setup, late=late)
        c = counters(tr)
        if sc.get("drop_px"):
            c["drop_px"] = run.px_of(tr, lambda mo: len(mo) > 3)
            # the pixels its height decides: the picture against the one with the drops at MISSILE_Z (a drop hidden
            # behind its corpse, or past the scenery budget, draws the same at both: drop_z could not see it)
            with drops_keep_rank():                   # M7 P8a (D3 a): the lifted drop still ranks as a drop
                c["drop_z_px"] = sum(P.px_diff(run.picture(fr), run.picture(fr, [mo[:3] for mo in fr["mobiles"]]))
                                 for fr in tr if fr["drawn"] == "world" and any(len(mo) > 3 for mo in fr["mobiles"]))
        if not deaths_ok and (c["deaths"] or c["dead_frames"]):
            continue
        tr[0]["start"] = pose                         # the claim may ask where the run began
        if sc["claim"](c, tr) and (not sc.get("claim_ctl") or ctl_parts(run, sc, cand, tr) is not None):
            return cand, tr, c
    return None


def ctl_parts(run: Run, sc: dict, cand, want: list, ctl: str | None = None):
    """the first frame on which control `ctl` (default the scenario's `claim_ctl`) parts from `want`, the oracle's run
    of `cand` -> (frame, what) or None. M7 P8a: a PICTURE control (p8a_lib.PICTURE_CONTROLS: a render rule) is judged
    on the SAME trace's pictures; a model control re-runs the candidate"""
    ctl = ctl or sc["claim_ctl"]
    if ctl in P8.PICTURE_CONTROLS:
        return P8.picture_parts(run, want, ctl)
    from doomfj.monsters import drop_rows
    pose, setup = cand[0], cand[1]
    late = cand[2] if len(cand) > 2 else None
    with drops_keep_rank():                           # `drop_z`'s pictures hold lifted drops (3-tuples)
        alt, mr = run(pose, sc["keys"], setup, ctl, late=late)
        return H.parts(run, want, alt, run.orc._mv(mr.mph.world).nrt, drop_rows(mr.mph.world))


# ================================================================================================
# placing: poses from the map
# ================================================================================================
def standing(dsim, x: int, y: int) -> bool:
    return G._ok(dsim, x << 16, y << 16)


def poses_facing(dsim, w, x: int, y: int, dists, los: bool = True) -> list:
    """standing poses `d` units from map point (x, y), in the 8 octants, facing it (with 2D line of sight)"""
    out = []
    for d in dists:
        for k in range(8):
            a = k * math.pi / 4
            px, py = round(x + d * math.cos(a)), round(y + d * math.sin(a))
            if standing(dsim, px, py) and (not los or w.los_points((px << 16, py << 16), (x << 16, y << 16))):
                out.append((px << 16, py << 16, G.bam(x - px, y - py)))
    return out


def sector_of(w, x: int, y: int) -> int:
    return w.leaf_sector[w.rm.point_in_subsector(w.cmap, x, y)]


def poses_in_sector(dsim, w, sec: int, step: int = 16, ledge=None) -> list:
    """standing poses whose centre lies in sector `sec` (its lines' box, every `step` units), facing north; with
    `ledge` True only those whose box stands on a HIGHER floor than the sector's (check_position), False only those on
    it"""
    xs = [w.cmap.vertexes[v][0] for ld in w.lds for side in (ld.front, ld.back)
          if 0 <= side < len(w.sds) and w.sds[side].sector == sec for v in (ld.v1, ld.v2)]
    ys = [w.cmap.vertexes[v][1] for ld in w.lds for side in (ld.front, ld.back)
          if 0 <= side < len(w.sds) and w.sds[side].sector == sec for v in (ld.v1, ld.v2)]
    out = []
    for x in range(min(xs) + 8, max(xs) - 7, step):
        for y in range(min(ys) + 8, max(ys) - 7, step):
            if sector_of(w, x, y) != sec or not standing(dsim, x, y):
                continue
            if ledge is not None:
                fz = w.rm.check_position(w.scene_c, x << 16, y << 16)[1]
                if (fz != w.secs_c[sec].floor_h) != ledge:
                    continue
            out.append((x << 16, y << 16, NORTH))
    return out


def walk_poses(dsim, x0, y0, angle, offsets) -> list:
    """standing poses at (x0, y0) moved back along `angle` by each offset, facing `angle`"""
    out = []
    ca, sa = math.cos(angle / (1 << 32) * 2 * math.pi), math.sin(angle / (1 << 32) * 2 * math.pi)
    for d in offsets:
        x, y = round(x0 - d * ca), round(y0 - d * sa)
        if standing(dsim, x, y):
            out.append((x << 16, y << 16, angle))
    return out


# ---- setups (each on the mirror's phase; the binary gets the cells they move)
def poke_hp(hp: int):
    def fn(mph):
        mph.world.ws.p_health = hp
    return fn


def armor(points: int, kind: int):
    def fn(mph):
        mph.world.ws.p_armor, mph.world.ws.p_armortype = points, kind
    return fn


def both(*fns):
    def fn(mph):
        for f in fns:
            f(mph)
    return fn


def mon_health(m: int, hp: int):
    def fn(mph):
        mph.world.ws.mon_health[m] = hp
    return fn


def bar_health(b: int, hp: int):
    def fn(mph):
        mph.world.ws.bar_health[b] = hp
    return fn


def corpse(m: int):
    """monster m a CORPSE where it stands: its death's last state, forever, neither solid nor shootable"""
    def fn(mph):
        w, ws = mph.world, mph.world.ws
        st = w.mon_info[m].deathstate
        while gd.STATES[st].tics >= 0:
            st = gd.STATES[st].next
        ws.mon_state[m], ws.mon_tics[m] = gd.STATE_INDEX[st], 15
        ws.mon_solid[m] = ws.mon_shootable[m] = 0
        ws.mon_health[m] = 0
    return fn


def teleport(pose, rng: int = 0):
    """a LATE setup: the player to `pose` (and, with `rng`, the player's stream that many draws on: a scenario
    that needs a roll the level start's stream does not give)"""
    def fn(mph, ev):
        if rng:
            from doomfj import rng as R
            mph.world.ws.rng_player = (mph.world.ws.rng_player + rng) & R.STATE_MASK
        return pose
    return fn


def first_live(w, kind: str, near=None) -> list:
    slots = [m for m in range(w.layout.nmon) if w.ws.mon_active[m] and w.mon_info[m].name == kind]
    if near is not None:
        slots.sort(key=lambda m: (w.ws.mon_x[m] - near[0]) ** 2 + (w.ws.mon_y[m] - near[1]) ** 2)
    return slots


def scenario_list(dsim, w, card) -> list:
    """the scenarios with their candidates (hard's level start: the boot skill's world `w`)"""
    out = []
    pk = w.pickup_things
    bit_h = gd.skill_bit(gd.SK_HARD)

    # ---- F1: a cluster walked through at hard
    # straight walks that take four items each (found by stepping the model's move from 48 units behind every hard
    # pickup in the 8 octants): sector 91's four health bonuses; sector 135's three armor bonuses and a shell box;
    # two health bonuses and two shells in sector 8
    f1 = [p for xy, a in (((-160, 112), NORTH), ((32, 1440), WEST), ((174, 898), 0xE0000000))
          for p in walk_poses(dsim, xy[0], xy[1], a, (0,))]
    out.append({"name": "F1 pickups at hard: bonuses over 100, clips, the gold palette", "keys": [F] * 36 + [I] * 6,
                "controls": ["bonus_cap", "bonus_round"],
                "cands": [(p, None) for p in f1],
                "claim": lambda c, tr: c["pickups"] >= 4 and c["bonus_frames"] >= 1})
    # ---- F1r: the card from below (p2a's S4 pose: inside the card's box, 112 units under it)
    out.append({"name": "F1r an item out of reach: the card from sector 124", "keys": [F] * 3, "controls": ["reach"],
                "cands": [(G.below_card_pose(dsim, card), None)],
                "claim": lambda c, tr: c["pickups"] == 0})
    # ---- F2: refused -- a medikit at 100 health; a clip at max ammo
    medi = [i for i, t in enumerate(pk) if t.type == 2012 and t.flags & bit_h]
    clip = [i for i, t in enumerate(pk) if t.type == 2007 and t.flags & bit_h]

    def maxclip(mph):
        mph.world.ws.p_ammo[gd.AM_CLIP] = gd.MAXAMMO[gd.AM_CLIP]
    f2 = ([(p, None) for i in medi for p in poses_facing(dsim, w, pk[i].x, pk[i].y, (64, 56, 72))]
          + [(p, maxclip) for i in clip for p in poses_facing(dsim, w, pk[i].x, pk[i].y, (64, 56, 72))])
    out.append({"name": "F2 refused pickups: a medikit at 100 health, a clip at max ammo", "keys": [F] * 8,
                "controls": ["give_always"], "cands": f2,
                "claim": lambda c, tr: c["pickups"] == 0 and _touched_box(w, tr, medi + clip)})
    # ---- F3: the chainsaw
    saw = [i for i, t in enumerate(pk) if t.type == 2005]
    keys3 = [F] * 6 + [I] * 40 + [{"w1": True}] * 3 + [I] * 6
    out.append({"name": "F3 the chainsaw: owned, pending, raised; key 1 keeps it", "keys": keys3,
                "controls": ["no_pending"],
                "cands": [(p, None) for i in saw for p in poses_facing(dsim, w, pk[i].x, pk[i].y, (48, 56, 64, 40),
                                                                        los=False)],
                "claim": lambda c, tr: tr[-1]["mstate"]["wp_rdy"] == gd.WP_CHAINSAW
                and c["pickup_items"] >= 1})
    # ---- F4: drops -- a zombieman's clip, a sergeant's shotgun: shot (health poked to 1), drawn, walked over
    keys4 = [I] * 14 + [FIRE] * 2 + [I] * 30 + [F] * 10 + [I] * 4     # the blood gone before the walk: the drop shows
    f4, f4s = [], []
    for kind in ("MT_POSSESSED", "MT_SHOTGUY"):
        for m in first_live(w, kind):
            for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (96, 112, 80)):
                f4.append((p, mon_health(m, 1)))
                if kind == "MT_SHOTGUY":
                    f4s.append(f4[-1])
    from doomfj import weaponcode as WC
    own_shotgun = 1 << 4 * WC.WEAPONS.index(gd.WP_SHOTGUN)
    out.append({"name": "F4 drops: shot, drawn on the floor, taken", "keys": keys4, "drop_px": True,
                "controls": ["no_drop", "drop_full_clip"], "cands": f4,
                "claim": lambda c, tr: c["pickup_drops"] >= 1 and c["drop_px"] >= 1})
    out.append({"name": "F4s the sergeant's shotgun (hard: the only one) owned from its drop", "keys": keys4,
                "drop_px": True, "controls": ["no_drop", "drop_z"],
                "cands": f4s,
                "claim": lambda c, tr: c["pickup_drops"] >= 1 and bool(tr[-1]["mstate"]["wp_own"] & own_shotgun)
                and c["drop_z_px"] >= 1})
    # ---- F5: berserk at MEDIUM
    pstr = [i for i, t in enumerate(pk) if t.type == 2023]
    menu = [{"menu": ["esc"]}, {"menu": ["enter"]}, {"menu": ["up"]}, {"menu": ["enter"]}]
    keys5 = menu + [F] * 3 + [I] * 40 + [FIRE] * 3 + [I] * 12
    f5 = []
    wm = _world_at(gd.SK_MEDIUM)
    for i in pstr:
        for p in poses_facing(dsim, w, pk[i].x, pk[i].y, (40, 48, 32)):
            for m in first_live(wm, "MT_POSSESSED", near=(pk[i].x, pk[i].y))[:2]:
                for q in poses_facing(dsim, wm, wm.ws.mon_x[m], wm.ws.mon_y[m], (44, 40, 48)):
                    for k in range(0, 8):          # the player stream advanced k: the first punch's roll
                        f5.append((p, None, {4: teleport(p, rng=k), 44: teleport(q)}))
    out.append({"name": "F5 berserk at medium: PSTR, the red tint, a punch gibs a zombieman", "keys": keys5,
                "controls": ["berserk_x10", "strength_pal", "gib"], "cands": f5,
                "claim": lambda c, tr: c["berserk_frames"] >= 1 and c["gibs"] >= 1
                and any(fr["mstate"].get("p_str") for fr in tr)})
    # ---- F6: a barrel shot beside a sergeant: puffs, the pain draws, BEXP, a blast gib (and its drop), the player hurt
    keys6 = [I] * 14 + [FIRE] * 2 + [I] * 30
    f6, f6d = [], []
    for b, t in enumerate(w.barrel_things):
        near = [m for m in first_live(w, "MT_SHOTGUY") + first_live(w, "MT_POSSESSED")
                if max(abs(w.ws.mon_x[m] - t.x), abs(w.ws.mon_y[m] - t.y)) < 60]
        if not near:
            continue
        for p in poses_facing(dsim, w, t.x, t.y, (112, 120, 104, 96)):
            f6.append((p, both(armor(200, 2), bar_health(b, 1))))      # one pistol shot kills it
            f6d.append((p, armor(200, 2)))
    out.append({"name": "F6 a barrel shot beside a sergeant: a puff, BEXP, a blast gib, the player hurt", "keys": keys6,
                "controls": ["blast_cheb"], "cands": f6,
                "claim": lambda c, tr: c["barrel_blasts"] >= 1 and c["puffs"] >= 1 and c["blast_kills"] >= 1
                and c["barrel_hurt"] >= 1 and c["bexp_frames"] >= 1})
    out.append({"name": "F6d a barrel's non-lethal hit: its pain roll draws rng_world", "keys": [I] * 14 + [FIRE] * 2 + [I] * 6,
                "controls": ["barrel_pain_draw"], "cands": f6d,
                "claim": lambda c, tr: c["barrel_hits"] >= 1 and c["barrel_blasts"] == 0})
    # ---- F6p: a barrel punched (the fist's puff)
    keys6p = [{"w1": True}] + [I] * 34 + [FIRE] * 10 + [I] * 6
    out.append({"name": "F6p a barrel punched: the fist's puff", "keys": keys6p, "controls": ["puff_melee"],
                "cands": [(p, armor(200, 2)) for b, t in enumerate(w.barrel_things)
                          for p in poses_facing(dsim, w, t.x, t.y, (40, 44, 36))],
                "claim": lambda c, tr: c["puffs"] >= 1 and c["barrel_hits"] >= 1})
    # ---- F7: the chain
    col = [b for b, t in enumerate(w.barrel_things) if t.x == 2512]
    keys7 = [I] * 14 + [FIRE] * 2 + [I] * 30
    f7 = [(p, both(bar_health(b, 1), armor(200, 2))) for b in col
          for p in poses_facing(dsim, w, w.barrel_things[b].x, w.barrel_things[b].y, (192, 224, 160, 256))
          if p[0] >> 16 < 2512]
    out.append({"name": "F7 THE CHAIN: the column of barrels set off by one shot", "keys": keys7,
                "controls": ["chain_same_tic"], "cands": f7,
                "claim": lambda c, tr: c["barrel_blasts"] >= 3})
    # ---- F8: blocking
    keys8 = [F] * 10
    b13 = w.barrel_things[13]
    out.append({"name": "F8a blocking: a barrel", "keys": keys8, "controls": ["walk_through"],
                "cands": [(p, None) for p in poses_facing(dsim, w, b13.x, b13.y, (64, 56, 72))],
                "claim": lambda c, tr: c["player_blocked"] >= 1})
    dec = [t for t in w.decor_solid if t.flags & bit_h]
    out.append({"name": "F8b blocking: a solid decor", "keys": keys8, "controls": ["walk_through"],
                "cands": [(p, None) for t in dec[:8] for p in poses_facing(dsim, w, t.x, t.y, (64, 72))],
                "claim": lambda c, tr: c["player_blocked"] >= 1})
    out.append({"name": "F8c blocking: a live monster", "keys": [F] * 6, "controls": ["walk_through"],
                "cands": [(p, armor(200, 2)) for m in first_live(w, "MT_SERGEANT")[:6]
                          for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (72, 80, 64))],
                "claim": lambda c, tr: c["player_blocked"] >= 1})
    out.append({"name": "F8d a corpse lets the player through", "keys": [F] * 10, "controls": ["corpse_blocks"],
                "cands": [(p, corpse(m)) for m in first_live(w, "MT_POSSESSED")[:6]
                          for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (64, 72, 56))],
                "claim": lambda c, tr: c["player_blocked"] == 0 and _passed(tr)})
    # ---- F9: nukage
    out.append({"name": "F9 nukage: 70 frames in sector 23", "keys": [I] * 70, "controls": ["nuk_period"],
                "cands": [(p, None) for p in poses_in_sector(dsim, w, 23, step=32, ledge=False)[:12]],
                "claim": lambda c, tr: c["nukage"] >= 2})
    out.append({"name": "F9l nukage's rim: the box over a higher floor", "keys": [I] * 40, "controls": ["nuk_floor"],
                "cands": [(p, None) for p in poses_in_sector(dsim, w, 23, step=8, ledge=True)[:12]],
                "claim": lambda c, tr: c["nukage"] == 0})
    # ---- F10: the card
    out.append({"name": "F10 the blue card: pcard 1, the bonus 12, the gold palette", "keys": [F] * 4 + [I] * 6,
                "controls": ["card_bonus"], "cands": [(G.card_pose(dsim, card), None)],
                "claim": lambda c, tr: tr[-1]["phase"][3] == 1 and c["bonus_frames"] >= 1
                and max(fr["mstate"]["p_bc"] for fr in tr) == 12})
    # ---- S2: the stress frame (F7's chain in view), recorded
    out.append({"name": "S2 stress: the chain in view", "keys": [I] * 14 + [FIRE] * 2 + [I] * 90, "controls": [],
                "cands": f7,
                "claim": lambda c, tr: c["barrel_blasts"] >= 3})
    out += p8a_scenario_list(dsim, w, card)          # M7 P8a: section 5.2's rows (each behind its rule and package)
    return out

# ================================================================================================
# M7 P8a (package V, docs/gp-final-plan.md 5.2): knockback (K), infighting (I), the compositor (C), the stress
# ================================================================================================
def _dist(w, fr, m) -> int:
    from doomfj.world import aprox_distance
    x, y = _signed(fr["pose"][0], 32) >> 16, _signed(fr["pose"][1], 32) >> 16
    mx, my = fr["mxy"][m] if fr.get("mxy") else (w.ws.mon_x[m], w.ws.mon_y[m])
    return aprox_distance(mx - x, my - y)


def _moved_away(w, tr, m) -> bool:
    """the pose moved (no key moves it: every frame is idle) and the distance to monster m grew"""
    return any(a["pose"][:2] != b["pose"][:2] and _dist(w, b, m) > _dist(w, a, m) for a, b in zip(tr, tr[1:]))


def _knock_stopped(tr) -> bool:
    """the player's knock momentum went to zero after it was not"""
    k = [bool(fr["mstate"].get("p_kmx") or fr["mstate"].get("p_kmy")) for fr in tr]
    return any(a and not b for a, b in zip(k, k[1:]))


def _dead_hp(h) -> bool:
    return h == 0 or bool(h & 0x800)          # the 12-bit health read unsigned: <= 0


def _died(tr, m):
    return next((f for f, fr in enumerate(tr) if _dead_hp(fr["mstate"]["mon_health"][m])), None)


def _mon_hurt(tr) -> int:
    """frames on which some monster's health fell (the player idle: a monster's doing)"""
    n = 0
    for a, b in zip(tr, tr[1:]):
        n += any(not _dead_hp(x) and (_dead_hp(y) or y < x)
                 for x, y in zip(a["mstate"]["mon_health"], b["mstate"]["mon_health"]))
    return n


def chase(m: int, state: str, target: int):
    """monster m awake in `state` with target `target` (0 none, 1 the player, 2 + slot: world.infighting_on)"""
    def fn(mph):
        ws = mph.world.ws
        ws.mon_state[m], ws.mon_tics[m] = gd.STATE_INDEX[state], 1
        ws.mon_target[m], ws.mon_reaction[m], ws.mon_movecount[m] = target, 0, 0
    return fn


def own_chainsaw(mph):
    mph.world.ws.p_owned[gd.WP_CHAINSAW] = 1


def ray_poses(dsim, w, x: int, y: int, d0: int = 48, d1: int = 320, step: int = 2, back=None) -> list:
    """M7 P8a: along each of 16 rays from map point (x, y), the LAST standable pose before the ray leaves standable
    ground (a wall or a ledge right behind the player), facing (x, y), with line of sight -- `back` (a function of the
    pose and its facing unit vector) narrows them further"""
    out = []
    for k in range(16):
        a = k * math.pi / 8
        ca, sa = math.cos(a), math.sin(a)
        last = None
        for d in range(d0, d1, step):
            px, py = round(x + d * ca), round(y + d * sa)
            if standing(dsim, px, py):
                last = (px, py)
            elif last is not None:
                break
        if last is None:
            continue
        px, py = last
        if not w.los_points((px << 16, py << 16), (x << 16, y << 16)):
            continue
        if back is not None and not back(px, py, ca, sa):
            continue
        out.append((px << 16, py << 16, G.bam(x - px, y - py)))
    return out


def line_poses(dsim, w, s: int, i: int, dists=(48, 64, 96, 128)) -> list:
    """M7 P8a: poses on the line from monster s THROUGH thing i (a monster slot, or ("bar", b)), `dists` beyond i,
    facing s, with line of sight to s -- what stands in s's line of fire at the player"""
    sx, sy = w.ws.mon_x[s], w.ws.mon_y[s]
    if isinstance(i, tuple):
        t = w.barrel_things[i[1]]
        ix, iy = t.x, t.y
    else:
        ix, iy = w.ws.mon_x[i], w.ws.mon_y[i]
    dx, dy = ix - sx, iy - sy
    n = math.hypot(dx, dy)
    if not n:
        return []
    out = []
    for d in dists:
        px, py = round(ix + dx / n * d), round(iy + dy / n * d)
        if standing(dsim, px, py) and w.los_points((px << 16, py << 16), (sx << 16, sy << 16)):
            out.append((px << 16, py << 16, G.bam(sx - px, sy - py)))
    return out


def pairs(w, a_kinds, b_kinds, lo: int, hi: int, los: bool = True) -> list:
    """(a, b) monster slot pairs `lo`..`hi` units apart, with (or, `los` False, WITHOUT) 2D line of sight"""
    from doomfj.world import aprox_distance
    out = []
    for a in [m for k in a_kinds for m in first_live(w, k)]:
        for b in [m for k in b_kinds for m in first_live(w, k)]:
            if a == b:
                continue
            ws = w.ws
            d = aprox_distance(ws.mon_x[a] - ws.mon_x[b], ws.mon_y[a] - ws.mon_y[b])
            if lo <= d <= hi and w.los_points((ws.mon_x[a] << 16, ws.mon_y[a] << 16),
                                              (ws.mon_x[b] << 16, ws.mon_y[b] << 16)) == los:
                out.append((a, b))
    return out


def p8a_scenario_list(dsim, w, card) -> list:
    """M7 P8a: section 5.2's fight_gate rows -- each with its `rule` (the P8a rule its game must have) and `pkg` (the
    packages whose behaviour it tests); `p8a_lib.status` says whether it runs, is N/A, or awaits a package"""
    out = []
    zomb, sgt, imps = first_live(w, "MT_POSSESSED"), first_live(w, "MT_SHOTGUY"), first_live(w, "MT_TROOP")
    demons = first_live(w, "MT_SERGEANT")
    idle40 = [I] * 40
    gun = [{"w3": True}] + [I] * 40 + [FIRE] * 6 + [I] * 30
    shoot = [I] * 14 + [FIRE] * 2 + [I] * 30

    def att(m, st):
        return lambda mph, m=m: H.attack(mph, m, st)
    # ---- K1: a zombieman's bullets push the player away; the push decays and stops
    k1 = [(p, both(att(m, "S_POSS_ATK1"), armor(200, 2))) for m in zomb[:8]
          for p in H.facing_pose(dsim, w, m, 128) + H.facing_pose(dsim, w, m, 96)]
    out.append({"name": "K1 knockback: a zombieman's hits push the player away, the push decays and stops",
                "keys": [I] * 64, "limit": 30, "rule": "knock", "pkg": ("K",), "need": ("knock_frames",),
                "controls": ["no_thrust", "thrust_sign", "no_friction", "stopspeed"], "cands": k1,
                # stopped by the STOPSPEED stop, not by a wall (K2 is the wall): `stopspeed` must decide it
                "claim": lambda c, tr: c["knock_frames"] >= 1 and _knock_stopped(tr) and c["knock_refused"] == 0
                and any(_moved_away(w, tr, m) for m in zomb)})
    # ---- K2: pushed into a wall: the knock momentum zeroed
    k2 = []
    for m in zomb[:8] + sgt[:6]:
        mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
        st = "S_POSS_ATK1" if m in zomb else "S_SPOS_ATK1"
        for p in ray_poses(dsim, w, mx, my, back=lambda px, py, ca, sa: not standing(dsim, round(px + 4 * ca),
                                                                                         round(py + 4 * sa))):
            k2.append((p, both(att(m, st), armor(200, 2))))
    out.append({"name": "K2 knockback into a wall: the knock momentum is zeroed", "keys": idle40,
                "rule": "knock", "pkg": ("K",), "need": ("knock_walls",), "controls": ["wall_keeps"], "cands": k2,
                "limit": 48,
                "claim": lambda c, tr: c["knock_walls"] >= 1})
    # ---- K3: a barrel blast throws the player and a crowd from the barrel
    k3 = []
    for b, t in enumerate(w.barrel_things):
        near = [m for m in zomb + sgt + imps if max(abs(w.ws.mon_x[m] - t.x), abs(w.ws.mon_y[m] - t.y)) < 96]
        if near:
            k3 += [(p, both(armor(200, 2), bar_health(b, 1))) for p in poses_facing(dsim, w, t.x, t.y, (104, 112, 120))]
    out.append({"name": "K3 a barrel blast throws the player and the monsters from the barrel", "keys": shoot,
                "rule": "knock", "pkg": ("K",), "need": ("mon_knock_frames",), "controls": ["blast_inflictor"],
                "cands": k3,
                "claim": lambda c, tr: c["barrel_blasts"] >= 1 and c["knock_frames"] >= 1 and c["mon_knock_frames"] >= 1})
    # ---- K4: the shotgun on a sergeant (7 thrusts) and on a demon (mass 400): fractions, re-tests, a relink
    def wall_behind(m, p, ds=(32, 48, 64, 96, 128)):
        """a wall (the player's box cannot stand) some `ds` units beyond monster m, away from pose p: its knock is
        refused there"""
        mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
        dx, dy = mx - (p[0] >> 16), my - (p[1] >> 16)
        n = math.hypot(dx, dy) or 1
        return any(not standing(dsim, round(mx + dx / n * d), round(my + dy / n * d)) for d in ds)
    for tag, kinds, ctls, refused in (
            ("K4s the shotgun on a sergeant: its fraction cells, a re-test refused, a relink", sgt,
             ["frac_drop", "no_retest"], True),
            ("K4d the shotgun on a demon: mass 400", demons, ["mass"], False)):
        cands = [(p, both(shotgun_(), armor(200, 2), mon_health(m, 600))) for m in kinds[:8]
                 for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (80, 96, 64))
                 if not refused or wall_behind(m, p)]
        out.append({"name": tag, "keys": gun, "rule": "knock", "pkg": ("K",), "need": ("frac_frames",),
                    "controls": ctls, "cands": cands, "limit": 40,
                    "claim": lambda c, tr, kinds=kinds, refused=refused: c["mon_knock_frames"] >= 1
                    and c["frac_frames"] >= 1 and any(mon_moved_(tr, m) for m in kinds)
                    and (not refused or c["mon_knock_refused"] >= 1)})
    # ---- K5: a kill by the shotgun: the corpse slides, its drop stays where it died
    k5 = [(p, both(shotgun_(), armor(200, 2), mon_health(m, 10))) for m in zomb[:8]
          for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (72, 88, 64))]
    out.append({"name": "K5 a shotgun kill: the corpse slides, its drop lies (and is drawn) where it died",
                "keys": gun + [F] * 10, "rule": "knock", "pkg": ("K",), "need": ("corpse_slides",),
                "controls": ["drop_follows"], "cands": k5, "drop_px": True,
                "claim": lambda c, tr: c["drop_frames"] >= 1 and c["corpse_slides"] >= 1 and c["drop_px"] >= 1})
    # ---- K6: the chainsaw on an imp: no thrust
    k6 = [(p, both(own_chainsaw, armor(200, 2), mon_health(m, 600))) for m in imps[:8]
          for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (40, 44, 48))]
    out.append({"name": "K6 the chainsaw on an imp: no thrust", "keys": [{"w1": True}] + [I] * 34 + [FIRE] * 12,
                "rule": "knock", "pkg": ("K",), "controls": ["saw_thrust"], "cands": k6,
                "claim": lambda c, tr: c["shots_hit"] >= 1 and c["mon_knock_frames"] == 0
                and tr[-1]["mstate"]["wp_rdy"] == gd.WP_CHAINSAW})
    # ---- K7: the reversal -- a monster > 64 above the player, a killing shot under 40: the coin; reversed x4
    k7 = []
    for m in [m for k in ("MT_POSSESSED", "MT_SHOTGUY", "MT_TROOP") for m in first_live(w, k)]:
        for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (96, 128, 160, 192, 256)):
            fz = w.rm.check_position(w.scene_c, p[0], p[1])[1]
            if w.ws.mon_floorz[m] - fz > 64:
                for k in range(4):                   # the target's stream k draws on: both coins tried
                    k7.append((p, both(mon_health(m, 1), mon_rng_(m, k))))
    out.append({"name": "K7 the falling-forward reversal: a kill from more than 64 below, the coin on the target's "
                        "stream", "keys": shoot, "rule": "knock", "pkg": ("K",), "na_if_no_cands":
                "no E1M1 position puts a shootable monster > 64 above a standing player with line of sight: "
                "test_knock_fj carries the reversal on a forced state (docs/gp-final-plan.md 5.2)",
                "controls": ["no_reverse", "reverse_rng"], "cands": k7, "limit": 48,
                "claim": lambda c, tr: c["mon_knock_frames"] >= 1 and c["corpse_slides"] >= 1})
    # ---- I1: a sergeant fires through an imp standing in its line: the imp is hit, bleeds, turns on it
    i1 = [(p, both(att(s, "S_SPOS_ATK1"), armor(200, 2), mon_health(i, 600)))
          for s, i in pairs(w, ("MT_SHOTGUY",), ("MT_TROOP",), 64, 400)[:10] for p in line_poses(dsim, w, s, i)]
    out.append({"name": "I1 a sergeant fires through an imp in its line: the imp hit, blood, the imp turns on it",
                "keys": idle40, "rule": "fight", "pkg": ("I",), "need": ("infight",),
                "controls": ["pass_through", "no_switch", "fx_none"], "cands": i1,
                "claim": lambda c, tr: c["infight"] >= 1 and c["fx_spawns"] >= 1})
    # ---- I2: an imp's fireball through a zombieman (damaged, switched) / into another imp (explodes, no damage)
    i2z = [(p, both(att(s, "S_TROO_ATK1"), armor(200, 2), mon_health(z, 600)))
           for s, z in pairs(w, ("MT_TROOP",), ("MT_POSSESSED", "MT_SHOTGUY"), 128, 480)[:10]
           for p in line_poses(dsim, w, s, z)]
    out.append({"name": "I2z an imp's fireball into a zombieman: damaged and switched; the shooter passed",
                "keys": idle40, "rule": "fight", "pkg": ("I",), "controls": ["hits_shooter"], "cands": i2z,
                "claim": lambda c, tr: c["infight"] >= 1 and c["proj_spawns"] >= 1})
    i2i = [(p, both(att(s, "S_TROO_ATK1"), armor(200, 2)))
           for s, j in pairs(w, ("MT_TROOP",), ("MT_TROOP",), 128, 480)[:10] for p in line_poses(dsim, w, s, j)]
    out.append({"name": "I2i an imp's fireball into another imp: it explodes, no damage (the species rule)",
                "keys": idle40, "rule": "fight", "pkg": ("I",), "controls": ["species"], "cands": i2i,
                "claim": lambda c, tr: c["proj_spawns"] >= 1 and c["explosion_frames"] >= 1 and c["player_hurt"] == 0
                and _mon_hurt(tr) == 0})
    # ---- I3: a monster's stray shot kills a barrel: the blast's source is that monster. bar_src is the source of the
    # first NON-lethal damage (P_DamageMobj returns after P_KillMobj, before the switch: a barrel killed by its first
    # hit blames nobody -- DOOM's, combat.damage_barrel), so the barrel starts at 16: no first bullet (3 .. 15) kills
    # it, and the sergeants (3 pellets an attack) come first (the P8a integration: at 1 no candidate could place)
    i3 = []
    for b, t in enumerate(w.barrel_things):
        for s in sgt + zomb:
            if 64 <= max(abs(w.ws.mon_x[s] - t.x), abs(w.ws.mon_y[s] - t.y)) <= 320 and \
                    w.los_points((w.ws.mon_x[s] << 16, w.ws.mon_y[s] << 16), (t.x << 16, t.y << 16)):
                st = "S_POSS_ATK1" if s in zomb else "S_SPOS_ATK1"
                i3 += [((p, both(att(s, st), armor(200, 2), bar_health(b, 16))), s, b)
                       for p in line_poses(dsim, w, s, ("bar", b), (96, 128, 160))]
    out.append({"name": "I3 a monster's stray shot kills a barrel: the blast's source is that monster",
                "keys": idle40, "rule": "fight", "pkg": ("I",), "controls": ["bar_src_player"],
                "cands": [c_[0] for c_ in i3[:12]],
                "claim": lambda c, tr: c["barrel_blasts"] >= 1 and any(v >= 2 for fr in tr
                                                                      for v in fr["mstate"].get("bar_src", ()))})
    # ---- I4: the target dies: the monster looks for the player (allaround) or returns to its spawn state
    i4 = []
    for m, t in pairs(w, ("MT_TROOP", "MT_SHOTGUY"), ("MT_POSSESSED",), 96, 400)[:10]:
        for p in poses_facing(dsim, w, w.ws.mon_x[t], w.ws.mon_y[t], (96, 128)):
            i4.append((p, both(chase(m, w.mon_info[m].seestate, 2 + t), mon_health(t, 1), armor(200, 2))))
    out.append({"name": "I4 the target dies: the monster looks for the player or returns to its spawn state",
                "keys": shoot, "rule": "fight", "pkg": ("I",), "controls": ["target_stale"], "cands": i4,
                "claim": lambda c, tr: c["mkills"] >= 1 and any(
                    all(v < 2 for v in fr["mstate"]["mon_target"]) for fr in tr[-5:])})
    # ---- I5: a monster target behind a wall at range: no attack (the far line of sight)
    i5 = [(p, both(chase(m, w.mon_info[m].seestate, 2 + t), armor(200, 2)))
          for m, t in pairs(w, ("MT_TROOP", "MT_SHOTGUY", "MT_POSSESSED"), ("MT_POSSESSED", "MT_TROOP"), 256, 900,
                            los=False)[:10]
          for p in [(dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle)]]
    out.append({"name": "I5 a monster target behind a wall at range: no attack (the far LOS)", "keys": idle40,
                "rule": "fight", "pkg": ("I",), "controls": ["los_ignored"], "cands": i5,
                "claim": lambda c, tr: c["mon_attacks"] == 0 and c["infight"] == 0})
    # ---- I6: the threshold -- a monster switched to A refuses B inside 100 tics
    i6 = []
    for m, a in pairs(w, ("MT_TROOP",), ("MT_POSSESSED", "MT_SHOTGUY"), 64, 800)[:16]:
        for b in [z for z in zomb + sgt if z not in (m, a)][:12]:
            if not w.los_points((w.ws.mon_x[b] << 16, w.ws.mon_y[b] << 16), (w.ws.mon_x[m] << 16, w.ws.mon_y[m] << 16)):
                continue
            st = "S_POSS_ATK1" if b in zomb else "S_SPOS_ATK1"

            def thr(mph, m=m):
                mph.world.ws.mon_threshold[m] = 60
            i6.append(((dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle),
                       both(chase(m, w.mon_info[m].seestate, 2 + a), thr, chase(b, st, 2 + m), mon_health(m, 600))))
    out.append({"name": "I6 the threshold: a monster switched to one refuses another inside 100 tics", "keys": idle40,
                "rule": "fight", "pkg": ("I",), "controls": ["threshold_ignored"], "cands": i6,
                "claim": lambda c, tr: _mon_hurt(tr) >= 1 and c["infight"] == 0})
    # ---- C1 / C2 / C3: the compositor rules (each candidate must be one where the rule decides a pixel)
    # C1: a kill whose drop shares its leaf with its corpse. Under knockback the corpse slides AWAY from the shooter,
    # so most kills draw the drop first by depth alone -- the candidates run deep (`limit`), and `claim_ctl` keeps only
    # one where the rank decides a pixel (MEASURED: (656, 336), rank_off and rank_swap part at frame 24)
    out.append({"name": "C1 D3 a: a drop in its corpse's leaf drawn in front of the corpse", "keys": shoot + [I] * 10,
                "rule": "p8a", "pkg": ("C",), "controls": ["rank_off", "rank_swap"], "claim_ctl": "rank_off", "drop_px": True,
                "limit": 48,
                "cands": [(p, mon_health(m, 1)) for d in (96, 128, 160, 80, 192) for m in zomb[:8] + sgt[:6]
                          for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (d,))],
                "claim": lambda c, tr: c["drop_frames"] >= 1})
    out.append({"name": "C2 D3 a: blood on a monster drawn before it", "keys": gun,
                "rule": "p8a", "pkg": ("C",), "controls": ["rank_off", "rank_swap"], "claim_ctl": "rank_off",
                "cands": [(p, both(shotgun_(), armor(200, 2), mon_health(m, 600))) for m in zomb[:8]
                          for p in poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (80, 96, 112))],
                "claim": lambda c, tr: c["fx_spawns"] >= 1})
    out.append({"name": "C3 D3 b: a far barrel past three scenery things is drawn", "keys": [I] * 3,
                "rule": "p8a", "pkg": ("C",), "controls": ["barrel_soft"], "claim_ctl": "barrel_soft",
                "cands": [(p, None) for b, t in enumerate(w.barrel_things)
                          for p in poses_facing(dsim, w, t.x, t.y, (320, 448, 576, 704))],
                "claim": lambda c, tr: True})
    # ---- S3: the brawl -- every imp firing into the zombiemen, every zombieman at an imp
    def brawl(mph):
        from doomfj.world import aprox_distance
        ws, wd = mph.world.ws, mph.world
        zs = [m for m in range(wd.layout.nmon) if ws.mon_active[m] and wd.mon_info[m].name in ("MT_POSSESSED",
                                                                                                 "MT_SHOTGUY")]
        ts = [m for m in range(wd.layout.nmon) if ws.mon_active[m] and wd.mon_info[m].name == "MT_TROOP"]
        for a, others, st in [(i, zs, "S_TROO_ATK1") for i in ts] + [(z, ts, None) for z in zs]:
            if not others:
                continue
            t = min(others, key=lambda o: aprox_distance(ws.mon_x[o] - ws.mon_x[a], ws.mon_y[o] - ws.mon_y[a]))
            chase(a, st or wd.mon_info[a].missilestate, 2 + t)(mph)
        armor(200, 2)(mph)
    court = [p for xy in ((1424, 732), (1424, 760), (1400, 732)) for p in walk_poses(dsim, xy[0], xy[1],
                                                                                      0x40000000, (0,))]
    out.append({"name": "S3 stress: a brawl -- the imps firing into the zombiemen, infighting saturated",
                "keys": [I] * 60, "rule": "fight", "pkg": ("I",), "controls": [], "cands": [(p, brawl) for p in court],
                "claim": lambda c, tr: _mon_hurt(tr) >= 1})
    # ---- S4: a push storm -- a barrel chain inside a crowd
    col = [b for b, t in enumerate(w.barrel_things) if t.x == 2512]
    s4 = [(p, both(bar_health(b, 1), armor(200, 2))) for b in col
          for p in poses_facing(dsim, w, w.barrel_things[b].x, w.barrel_things[b].y, (192, 224, 160, 256))
          if p[0] >> 16 < 2512]                      # F7's candidates (S2 places among them)
    out.append({"name": "S4 stress: a push storm -- a barrel chain inside a crowd, every knock move at once",
                "keys": shoot + [I] * 30, "rule": "knock", "pkg": ("K",), "controls": [], "cands": s4, "limit": 40,
                "claim": lambda c, tr: c["barrel_blasts"] >= 3
                and max(fr["mstate"].get("kb_live", 0) for fr in tr) >= 3})
    return out


def shotgun_():
    return lambda mph: H.shotgun(mph)


def mon_rng_(m: int, k: int):
    def fn(mph):
        from doomfj import rng as R
        ws = mph.world.ws
        ws.mon_rng[m] = (ws.mon_rng[m] + k) & R.STATE_MASK
    return fn


def mon_moved_(tr, m: int) -> bool:
    return len({fr["mxy"][m] for fr in tr if fr.get("mxy")}) > 1



_WORLDS = {}


def _world_at(skill):
    """a World at `skill`'s level start (the placing of a scenario that starts with NEW GAME there)"""
    if skill not in _WORLDS:
        from doomfj.world import World
        _WORLDS[skill] = World(skill=skill, monsters="idle")
    return _WORLDS[skill]


def _touched_box(w, tr, items) -> bool:
    """some frame's pose is inside one of `items`' pickup boxes (the refusal was tested, not missed)"""
    from doomfj.combat import ITEM_RADIUS, PLAYER_R
    bd = ITEM_RADIUS + PLAYER_R
    for fr in tr:
        x, y = _signed(fr["pose"][0], 32) / 65536, _signed(fr["pose"][1], 32) / 65536
        for i in items:
            t = w.pickup_things[i]
            if abs(t.x - x) < bd and abs(t.y - y) < bd:
                return True
    return False


def _passed(tr) -> bool:
    """the player moved every frame (nothing stopped him)"""
    return all(a["pose"][:2] != b["pose"][:2] for a, b in zip(tr, tr[1:]))


# ================================================================================================
# the run
# ================================================================================================
NEED = ("pickups", "pickup_items", "pickup_drops", "bonus_frames", "berserk_frames", "gibs", "drop_frames",
        "bexp_frames", "barrel_blasts", "puffs", "blast_kills", "barrel_hurt", "player_blocked", "nukage",
        "barrel_hits", "fx_spawns")


def main(argv=None, gate="FIGHT", scen_fn=None, need=NEED, deaths_ok=False, run_cls=None, doc=None) -> int:
    ap = argparse.ArgumentParser(description=(doc or __doc__ or "").split("\n")[0])
    ap.add_argument("--fjm")
    ap.add_argument("--labels")
    ap.add_argument("--oracle-only", action="store_true", help="the scenarios, counters and controls, no binary")
    ap.add_argument("--only", help="run only the scenarios whose name starts with this (e.g. F6)")
    ap.add_argument("--modes", metavar="PLAYER/MONSTER", help="M7 P8a: the model modes (default the game tier's)")
    ap.add_argument("--frame-ops", nargs="?", const="-", metavar="FILE",
                    help="M7 P8a: each binary scenario's per-frame ops (and, with FILE, as JSON)")
    a = ap.parse_args(argv)
    if not a.oracle_only and not (a.fjm and a.labels):
        ap.error("--fjm and --labels (the build's label table), or --oracle-only")
    t0 = time.time()
    P8.set_modes(*P8.parse_modes(a.modes))
    H.FRAME_OPS = a.frame_ops
    MMODE, PMODE = sys.modules[__name__].MMODE, sys.modules[__name__].PMODE   # as set_modes left them
    G.PLAYER_MODE_OVERRIDE = PMODE
    orc = P.Oracle()
    orc.player_mode = PMODE
    dsim = onewalk.DoorSim()
    assert dsim.order == orc.door_order
    card_di = [di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
               if t.type == G.CARD_TYPE][0]
    run = (run_cls or Run)(orc, dsim, card_di)
    from doomfj.monsters import MonsterPhase, drop_rows
    from doomfj.wall_renderer import BOOT_SKILL
    w0 = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=MMODE, player=PMODE)
    nrt, ndrop = orc._mv(w0.world).nrt, drop_rows(w0.world)
    scen = [s for s in (scen_fn or scenario_list)(dsim, w0.world, dsim.dp.card_at)
            if not a.only or s["name"].startswith(a.only)]
    ok = True
    print("%s GATE -- %d scenarios (MONSTER_MODE %s, PLAYER_MODE %s)%s"
          % (gate, len(scen), MMODE, PMODE, "" if a.oracle_only else ", %s" % a.fjm), flush=True)
    if not a.oracle_only:
        from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
        assert (MONSTER_MODE, PLAYER_MODE) == (MMODE, PMODE), (
            "the binary is built at %s/%s, this gate checks P6/P7's %s/%s" % (MONSTER_MODE, PLAYER_MODE, MMODE, PMODE))
        gb = P.GameBinary(ROOT / a.fjm)
        cells = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis, modes=(PMODE, MMODE))
        for k in H.KEYFLAG.values():
            cells.setdefault(k, P.Cell(k, "hex", 1))
        table = P.LabelTable.load(ROOT / a.labels, {c.label for c in cells.values()})
        assert not table.absent & {"p_bc", "bar_st", "mdrop", "lvtime"}, (
            "the label table has no %s: a binary before P6/P7" % sorted(table.absent))
    totals = {}
    awaiting, ran_need = [], set()                    # M7 P8a: what waits for a package; the P8a counters owed
    for sc in scen:
        stat = P8.status(sc, PMODE, MMODE)            # M7 P8a: the scenario's rule at these modes, its packages
        if stat != "run":
            print("\n%s -- %s (%d candidates placed from the map)" % (
                sc["name"], ("AWAITS " + stat[len("awaits "):]) if stat.startswith("awaits") else stat.upper(),
                len(sc["cands"])), flush=True)
            if stat.startswith("awaits"):
                awaiting.append(sc["name"])
            continue
        if not sc["cands"] and sc.get("na_if_no_cands"):
            print("\n%s -- N/A: %s" % (sc["name"], sc["na_if_no_cands"]), flush=True)
            continue
        ran_need |= set(sc.get("need", ()))
        got = place(run, sc, deaths_ok=deaths_ok)
        print("\n%s -- %d frames" % (sc["name"], len(sc["keys"])), flush=True)
        if got is None:
            ok = False
            print("  the oracle does what the scenario claims: NO candidate of %d -- FAIL"
                  % len(sc["cands"][:sc.get("limit", 12)]))
            continue
        cand, want, c = got
        pose, setup, late = cand[0], cand[1], (cand[2] if len(cand) > 2 else None)
        print("  from (%.0f, %.0f) angle %08x%s: the oracle does what the scenario claims: yes"
              % (pose[0] / 65536, pose[1] / 65536, pose[2],
                 "" if not late else ", late setups at frames %s" % sorted(late)))
        print("  counters: " + ", ".join("%s %d" % kv for kv in c.items() if isinstance(kv[1], int) and kv[1]))
        print("  frame 0 pokes: %s" % sorted(H.poke_cells(run, setup or (lambda mph: None))))
        for f, fr in enumerate(want):
            if fr.get("poke"):
                print("  frame %d pokes: %s" % (f, sorted(fr["poke"])))
        for k, v in c.items():
            totals[k] = totals.get(k, 0) + v
        for ctl in sc["controls"]:
            try:                                      # M7 P8a: a picture control on the same trace; a control
                pt = ctl_parts(run, sc, cand, want, ctl)   # whose package is not in the tree AWAITS it
            except P8.Awaits as e:
                awaiting.append("%s / %s" % (sc["name"].split()[0], ctl))
                print("  CONTROL %-16s AWAITS %s" % (ctl, e), flush=True)
                continue
            ok &= pt is not None
            print("  CONTROL %-16s the oracle without the rule parts at frame %s%s" % (
                ctl, "%d (%s)" % pt if pt else None,
                "" if pt is not None else " -- NEVER: the scenario is VACUOUS, FAIL"), flush=True)
        if a.oracle_only:
            continue
        ok &= binary_scenario(gb, cells, table, run, sc, pose, setup or (lambda mph: None), want)
    zero = [k for k in tuple(need) + tuple(sorted(ran_need)) if not totals.get(k)] if not a.only else []
    deaths = totals.get("deaths", 0)
    ok &= not zero and (deaths_ok or (deaths == 0 and totals.get("dead_frames", 0) == 0))
    print("\nTOTALS: " + ", ".join("%s %d" % kv for kv in totals.items()))
    print("every event counter nonzero: %s; deaths %d" % ("yes" if not zero else "NO -- %s" % zero, deaths))
    H.write_frame_ops()
    # M7 P8a: a gate with scenarios or controls AWAITING a package has not checked them: INCOMPLETE, never PASS
    verdict = "FAIL" if not ok else ("INCOMPLETE" if awaiting else "PASS")
    if awaiting:
        print("AWAITING packages: %d -- %s" % (len(awaiting), "; ".join(awaiting)))
    print("\n%s GATE %s%s (%.0f s)" % (gate, verdict, " (oracle only)" if a.oracle_only else "", time.time() - t0))
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}[verdict]


def binary_scenario(gb, cells, table, run, sc, pose, setup, want) -> bool:
    """hurt_gate's binary half with the LATE pokes (each frame's `poke`) and the menu keys as key events"""
    poke = H.poke_cells(run, setup)
    reads = []
    p = P.Probe(cells, table, gb.width)
    missing = sorted(k for fr in [{"poke": poke}] + want for k in fr["poke"] if k not in p.cells)
    assert not missing, "a setup moves cells the probe cannot write: %s" % missing
    keys = sc["keys"]

    def start(pr, f):
        vals = {k: int(bool(keys[f].get(n))) for n, k in H.KEYFLAG.items() if k in pr.cells}
        if f == 0:
            vals.update({"mode": 0, "viewx": _signed(pose[0], 32), "viewy": _signed(pose[1], 32),
                         "viewangle": pose[2], **poke})
        if f < len(want):
            vals.update(want[f].get("poke", {}))
        pr.write_cells(vals)
    order, morder = run.dsim.order, run.dsim.mp.order
    names = sorted({k for fr in want for k in G.expected_cells(fr, order, morder)})
    names = [k for k in names if k in p.cells]
    p.on_frame_start(start)
    p.on_present(lambda pr, f: reads.append(pr.read_cells(names)))
    r = gb.run(len(keys), G.menu_events(keys), p)
    s_bad = x_bad = p_bad = None
    for f, fr in enumerate(want):
        exp = G.expected_cells(fr, order, morder)
        got = reads[f] if f < len(reads) else {}
        if s_bad is None and any(got.get(k) != v for k, v in exp.items()):
            s_bad = (f, {k: (got.get(k), v) for k, v in exp.items() if got.get(k) != v})
        pic = run.picture(fr) if fr["drawn"] == "world" else G.screen(run.orc, fr["drawn"][1], fr["drawn"][2])
        if x_bad is None and (f >= len(r.frames) or r.frames[f] != pic):
            x_bad = (f, P.px_diff(r.frames[f], pic) if f < len(r.frames) else -1)
        if p_bad is None and (f >= len(r.palettes) or r.palettes[f] != run.orc.palette_sha(fr["pal"])):
            p_bad = (f, fr["pal"])
    print("  binary: %d frames, %s ops -- STATE %s, PIXELS %s, PALETTE %s" % (
        len(r.frames), format(r.ops, ","),
        "exact on every frame" if s_bad is None else "PART at frame %d: %s" % s_bad,
        "byte-exact on every frame" if x_bad is None else "PART at frame %d (%d px)" % x_bad,
        "exact on every frame" if p_bad is None else "PART at frame %d (the oracle's PLAYPAL %d)" % p_bad))
    H.frame_ops_report(sc["name"], p.frame_ops())                  # M7 P8a: --frame-ops
    return s_bad is None and x_bad is None and p_bad is None


if __name__ == "__main__":
    sys.exit(main())
