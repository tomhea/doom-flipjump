"""hurt_gate.py -- M7 P5's gate: the monsters' attacks, byte-, state- and palette-exact (docs/gp-p5-interface.md).

    python scratchpad/gp/hurt_gate.py --fjm build/<new>.fjm --labels <its label table>
    python scratchpad/gp/hurt_gate.py --oracle-only          # the scenarios, their counters and the controls

p2a_gate's shape (it drives p2a_gate.Mirror): each scenario starts by POKING the game tier at frame 0's start -- the
world mode, the player's pose, and every cell the scenario's SETUP moved away from the boot level start (a monster's
state, tics, target, reaction, movecount; the player's armor; the shotgun and its shells) -- and at every frame's
start the held-key flags. The binary then runs its own tics -- the weapon, the move, the monsters with their
attacks (hurtcode: the hitscan, the claw, the bite on the player; projcode: the fireball pool, its flight, impact
and explosion, the blood pool), the palette -- and its render. At every present the probe reads every cell the
expectation names (the doors, the monsters, the weapon, P5's p_hp p_ar p_at p_dc p_dead, the pools pj_* fx_*,
rng_fx, the mobile rows of thpos_rt / thss_rt) and the frame is held against THE ORACLE: p2a_gate.Mirror with the
model modes (MONSTER_MODE "full"; PLAYER_MODE "full" since M7 P6/P7 -- docs/gp-p67-interface.md 6.3: P5 ran them
at "fx"), its picture rendered WITH the mobiles (`render_wall_frame(mobiles=)`; P6: and the drops, the barrels by
state, what the game removed), the palette the present showed against combat.palette_index's PLAYPAL.
STATE-, PIXEL- AND PALETTE-EXACT ON EVERY FRAME. No scenario may reach a death (die_gate.py's are the deaths).

THE SCENARIOS (the monsters at their spawns; nothing is teleported, so no leaf list is poked):
  H1 a zombieman's hitscan: hits and misses (the spread against HWT at the distance)
  H2 an imp's fireball hits the player, then its explosion is drawn
  H3 an imp's fireball into a wall: the player strafes out of its path
  H4 a demon's bite, through BLUE armor
  H5 GREEN armor that runs out: the armor type falls to 0
  H6 the shotgun into a close monster: blood, and the blood the full pool skips
  S1 saturation: every imp of the boot skill told to fire at once -- 8 in flight, the rest fizzle

THE CONTROLS (R9): each is an ORACLE MUTATION, and the mutated oracle must part from the oracle on some frame of the
scenario named -- in the cells, the palette, or the picture -- else the scenario could not see the rule broken and the
gate FAILS as vacuous: `armor` (damage ignores armor), `hwt` (every monster bullet hits), `pain_draw` (the player's
pain roll draws nothing), `pool9` (a 9-slot fireball pool), `fizzle_draw` (a fizzle draws rng_fx), `fx_skip_draw` (a
skipped blood draws rng_fx), `palette` (the red palette without DOOM's +7 rounding), `relink` (a fireball never
changes leaf), `momentum` (the momentum table read one fine angle off), `explode_draw` (the explosion not drawn).
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
from doomfj import gamedata as gd                                            # noqa: E402
from doomfj.fixedpoint import _signed                                        # noqa: E402
from doomfj.things import drawable_things                                    # noqa: E402

M32 = 0xFFFFFFFF
MMODE, PMODE = "full", "full"             # the game tier's modes from P6/P7 on (docs/gp-p67-interface.md 6.3);
                                          # a binary run asserts them against wall_renderer's
KEYFLAG = {"forward": "kb_f", "back": "kb_b", "turn_left": "kb_l", "turn_right": "kb_r", "use": "kb_u",
           "strafe_left": "kb_sl", "strafe_right": "kb_sr", "fire": "kb_fi",
           "w1": "kb_w1", "w2": "kb_w2", "w3": "kb_w3", "w4": "kb_w4"}
EXPLOSION = frozenset(("BAL1C0", "BAL1D0", "BAL1E0"))   # S_TBALLX1..3's lumps
CONTROLS = ("armor", "hwt", "pain_draw", "pool9", "fizzle_draw", "fx_skip_draw", "palette", "relink",
            "momentum", "explode_draw")


# ================================================================================================
# setups: what a scenario pokes (on the mirror's phase; the binary gets the same cells)
# ================================================================================================
def slots_of(w, kind: str) -> list:
    """the active monster slots of `kind` in world `w` (the boot skill's)"""
    return [m for m in range(w.layout.nmon) if w.ws.mon_active[m] and w.mon_info[m].name == kind]


def attack(mph, m: int, state: str, tics: int = 1) -> None:
    """monster m awake and in `state` (no action run: the poke is the cells), its target the player"""
    ws = mph.world.ws
    ws.mon_state[m], ws.mon_tics[m] = gd.STATE_INDEX[state], tics
    ws.mon_target[m], ws.mon_reaction[m], ws.mon_movecount[m] = 1, 0, 0


def armor(mph, points: int, kind: int) -> None:
    ws = mph.world.ws
    ws.p_armor, ws.p_armortype = points, kind


def shotgun(mph, shells: int = 20) -> None:
    ws = mph.world.ws
    ws.p_owned[gd.WP_SHOTGUN] = 1
    ws.p_ammo[gd.AM_SHELL] = shells


# ================================================================================================
# the events a run made (p2a_gate.Mirror records each frame's weapon and tic events)
# ================================================================================================
def counters(tr: list) -> dict:
    c = {"mon_hits": 0, "mon_misses": 0, "mon_melee": 0, "proj_spawns": 0, "proj_impacts": 0, "proj_walls": 0,
         "fizzles": 0, "fx_spawns": 0, "fx_skipped": 0, "player_hurt": 0, "armor_out": 0, "deaths": 0, "dead_frames": 0,
         "max_in_flight": 0, "explosion_frames": 0, "shots_hit": 0}
    at_prev = None
    for fr in tr:
        for ev in fr["ev"]:
            if ev is None:
                continue
            c["mon_hits"] += sum(1 for s in ev.mon_shots if s[3])
            c["mon_misses"] += sum(1 for s in ev.mon_shots if not s[3])
            c["mon_melee"] += len(ev.mon_melee)
            c["proj_spawns"] += len(ev.proj_spawns)
            c["proj_impacts"] += len(ev.proj_impacts)
            c["proj_walls"] += len(ev.proj_walls)
            c["fizzles"] += len(ev.fizzles)
            c["fx_spawns"] += len(ev.fx_spawns)
            c["fx_skipped"] += ev.fx_skipped
            c["player_hurt"] += len(ev.player_hurt)
            c["deaths"] += ev.deaths
            c["shots_hit"] += len(ev.hits)
        st = fr["mstate"]
        c["dead_frames"] += bool(st.get("p_dead"))
        c["max_in_flight"] = max(c["max_in_flight"], sum(st.get("pj_act", ())))
        c["explosion_frames"] += any(mo[2] in EXPLOSION for mo in fr["mobiles"])
        at = st.get("p_at")
        c["armor_out"] += at_prev is not None and at_prev != 0 and at == 0
        at_prev = at
    return c


# ================================================================================================
# the controls: ONE mutated rule each (R9)
# ================================================================================================
@contextlib.contextmanager
def control(name: str | None):
    """the oracle with rule `name` broken, for the duration (None: the oracle)"""
    from doomfj import combat as C
    from doomfj import monsters as MS
    from doomfj import world as W
    CM = C.CombatMixin
    saved = []

    def patch(obj, attr, val):
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, val)
    if name == "armor":                          # damage ignores the armor
        orig = CM.damage_player

        def no_armor(self, dmg, source, ev):
            at = self.ws.p_armortype
            self.ws.p_armortype = 0
            orig(self, dmg, source, ev)
            if not self.ws.p_dead:
                self.ws.p_armortype = at
        patch(CM, "damage_player", no_armor)
    elif name == "hwt":                          # every monster bullet hits
        orig_init = CM._combat_init

        def wide(self, *a, **k):
            orig_init(self, *a, **k)
            self.hwt = [1 << 30] * len(self.hwt)
        patch(CM, "_combat_init", wide)
    elif name == "pain_draw":                    # the player's pain roll draws nothing
        orig_roll = CM._roll

        def roll(self, stream, site, idx=None):
            if stream == "rng_player" and site is self.sites.pain[C.PLAYER_INFO.painchance]:
                return 0
            return orig_roll(self, stream, site, idx)
        patch(CM, "_roll", roll)
    elif name == "pool9":                        # a fireball pool of 9 slots (the schema built with it)
        patch(W, "FIREBALL_POOL", 9)
    elif name == "fizzle_draw":                  # a fizzle draws the spawn's tics roll anyway
        orig_spawn = CM._spawn_fireball

        def spawn(self, m, ev):
            n = len(ev.fizzles)
            orig_spawn(self, m, ev)
            if len(ev.fizzles) > n:
                self._roll("rng_fx", self.sites.tics_roll)
        patch(CM, "_spawn_fireball", spawn)
    elif name == "fx_skip_draw":                 # a skipped blood draws its tics roll anyway
        orig_fx = CM._spawn_fx

        def fx(self, kind, x16, y16, dmg, melee, ev):
            n = ev.fx_skipped
            orig_fx(self, kind, x16, y16, dmg, melee, ev)
            if ev.fx_skipped > n:
                self._roll("rng_fx", self.sites.tics_roll)
        patch(CM, "_spawn_fx", fx)
    elif name == "palette":                      # the red palette without the +7 rounding
        orig_pal = C.palette_index

        def pal(ws):
            if ws.p_damagecount:
                return min(C.NUMREDPALS - 1, ws.p_damagecount >> 3) + C.STARTREDPALS
            return orig_pal(ws)
        patch(C, "palette_index", pal)
    elif name == "relink":                       # a fireball keeps the leaf it spawned in
        orig_try = CM._missile_try

        def stay(self, s, nx, ny, ev):
            leaf = self.ws.proj_leaf[s]
            ok = orig_try(self, s, nx, ny, ev)
            if ok and self.ws.proj_leaf[s] != leaf:
                self._list_remove(self._mobile_proj(s), self.ws.proj_leaf[s])
                self.ws.proj_leaf[s] = leaf
                self._list_insert(self._mobile_proj(s), leaf)
            return ok
        patch(CM, "_missile_try", stay)
    elif name == "momentum":                     # the momentum table read one fine angle off
        orig_init = CM._combat_init

        def off(self, *a, **k):
            orig_init(self, *a, **k)
            t = self.fireball_mom
            self.fireball_mom = [t[(i + 1) % len(t)] for i in range(len(t))]
        patch(CM, "_combat_init", off)
    elif name == "explode_draw":                 # the explosion is not drawn
        orig_mob = MS.MonsterPhase.mobiles

        def mob(self):
            return [m for m in orig_mob(self) if m[2] not in EXPLOSION]
        patch(MS.MonsterPhase, "mobiles", mob)
    elif name is not None:
        raise KeyError(name)
    try:
        yield
    finally:
        for obj, attr, val in reversed(saved):
            setattr(obj, attr, val)


def normalized(cells: dict, nrt: int, ndrop: int = 0) -> dict:
    """`pool9`'s run reads 9 fireball slots and 9 fireball rows; the comparison takes the oracle's 8 (a ninth slot is
    not a difference in itself -- what it does to the other cells is). M7 P6: the rows after the pools (the blood,
    then `ndrop` drop rows) keep their place: the ninth fireball row is the one taken out"""
    from doomfj.world import FIREBALL_POOL, FX_POOL
    out = dict(cells)
    for k, v in cells.items():
        if k.startswith("pj_") and isinstance(v, tuple):
            out[k] = v[:FIREBALL_POOL]
    for k in ("thpos_rt", "thss_rt"):
        v = cells.get(k)
        extra = len(v) - (nrt + FIREBALL_POOL + FX_POOL + ndrop) if v is not None else 0
        if extra > 0:
            out[k] = v[:nrt + FIREBALL_POOL] + v[nrt + FIREBALL_POOL + extra:]
    return out


# ================================================================================================
# the scenarios, placed from the map
# ================================================================================================
def _standing(dsim, x: int, y: int) -> bool:
    return G._ok(dsim, x << 16, y << 16)


def facing_pose(dsim, w, m: int, dist: int):
    """standing poses `dist` units from monster m, facing it, with 2D line of sight to it -- the monster's facing
    side first (it sees the player), then the others"""
    mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
    f = w.ws.mon_facing[m]
    out = []
    for k in range(8):
        octant = (f + (k + 1) // 2 * (1 if k % 2 else -1)) % 8
        a = octant * math.pi / 4
        x, y = round(mx + dist * math.cos(a)), round(my + dist * math.sin(a))
        if _standing(dsim, x, y) and w.los_points((x << 16, y << 16), (mx << 16, my << 16)):
            out.append((x << 16, y << 16, G.bam(mx - x, my - y)))
    return out


def scenario_list(dsim, w) -> list:
    """the scenarios as candidates: each a list of (pose, setup) tried in order until the oracle does what the
    scenario claims (`place`)"""
    I, F = {}, {"fire": True}
    zomb, imps, demons = slots_of(w, "MT_POSSESSED"), slots_of(w, "MT_TROOP"), slots_of(w, "MT_SERGEANT")
    out = []

    def cands(slots, dists, setup_of):
        return [(pose, setup_of(m)) for m in slots for d in dists for pose in facing_pose(dsim, w, m, d)]

    out.append({
        "name": "H1 a zombieman's hitscan: hits and misses", "keys": [I] * 90, "controls": ["hwt", "pain_draw"],
        "cands": cands(zomb, (128, 160, 96, 192), lambda m: (lambda mph, m=m: attack(mph, m, "S_POSS_ATK1"))),
        "claim": lambda c: c["mon_hits"] >= 1 and c["mon_misses"] >= 1})
    out.append({
        "name": "H2 an imp's fireball hits the player; the explosion is drawn", "keys": [I] * 60,
        "controls": ["palette", "momentum", "explode_draw"],
        "cands": cands(imps, (192, 256, 160, 224), lambda m: (lambda mph, m=m: attack(mph, m, "S_TROO_ATK1"))),
        "claim": lambda c: c["proj_impacts"] >= 1 and c["explosion_px"] >= 1})
    # M7 P6+P7: the monsters' tempo x2 (world.MONSTER_TICS_PER_FRAME) -- the imp throws and the fireball flies twice
    # as many tics a frame: 33 frames are the 66 monster tics the scenario always had (at 66 frames the imp throws 5
    # and some land), and the strafe out of the first one's path starts at frame 4
    strafe = [I] * 4 + [{"strafe_left": True}] * 8 + [I] * 21
    out.append({
        "name": "H3 an imp's fireball into a wall (the player strafes out of its path)", "keys": strafe,
        "controls": ["relink"],
        "cands": cands(imps, (256, 320, 224, 192), lambda m: (lambda mph, m=m: attack(mph, m, "S_TROO_ATK1"))),
        "claim": lambda c: c["proj_walls"] >= 1 and c["proj_impacts"] == 0})
    out.append({
        "name": "H4 a demon's bite through blue armor", "keys": [I] * 50, "controls": ["armor"],
        "cands": cands(demons, (48, 52, 44), lambda m: (lambda mph, m=m: (attack(mph, m, "S_SARG_ATK1"),
                                                                          armor(mph, 100, 2)))),
        "claim": lambda c: c["mon_melee"] >= 1 and c["player_hurt"] >= 1})
    out.append({
        "name": "H5 green armor runs out: the armor type falls to 0", "keys": [I] * 90, "controls": ["armor"],
        "cands": cands(zomb, (128, 96, 160), lambda m: (lambda mph, m=m: (attack(mph, m, "S_POSS_ATK1"),
                                                                          armor(mph, 2, 1)))),
        "claim": lambda c: c["armor_out"] >= 1})
    gun = [{"w3": True}] + [I] * 40 + [F] * 12 + [I] * 12
    out.append({
        "name": "H6 the shotgun into a close monster: blood, and blood the full pool skips", "keys": gun,
        "controls": ["fx_skip_draw"],
        "cands": [(pose, (lambda mph: shotgun(mph))) for m in zomb for d in (96, 80, 112)
                  for pose in facing_pose(dsim, w, m, d)],
        "claim": lambda c: c["fx_spawns"] >= 1 and c["fx_skipped"] >= 1})
    out.append({
        "name": "S1 saturation: every imp fires at once -- 8 in flight, the rest fizzle", "keys": [I] * 30,
        "controls": ["pool9", "fizzle_draw"],
        "cands": [((dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle),
                   (lambda mph: [attack(mph, m, "S_TROO_ATK2") for m in slots_of(mph.world, "MT_TROOP")]))],
        "claim": lambda c: c["max_in_flight"] == 8 and c["fizzles"] >= 1})
    return out


# ================================================================================================
# the oracle
# ================================================================================================
class Run:
    """one scenario candidate on the oracle (`ctl`: a control's mutated rule)"""

    def __init__(self, orc, dsim, card_di):
        self.orc, self.dsim, self.card_di = orc, dsim, card_di

    def mirror(self, setup):
        mr = G.hooked(G.Mirror(self.dsim, self.card_di), self.orc, self.dsim, self.card_di)
        mr.mmode, mr.pmode, mr.setup = MMODE, PMODE, setup
        return mr

    def __call__(self, pose, keys, setup, ctl=None):
        with control(ctl):
            mr = self.mirror(setup)
            tr = mr.run(pose, keys, 0)
        return tr, mr

    def picture(self, fr, mobiles=None):
        """the oracle's picture of a frame -- M7 P6: with what the game removed, the barrels by state, and the bar's
        card the world's (`p2a_gate.picture`'s keywords)"""
        orc, dsim = self.orc, self.dsim
        return orc.render(fr["pose"][0], fr["pose"][1], fr["pose"][2],
                          tuple(fr["phase"][0][si][0] for si in dsim.order), hidden_extra=(),
                          movers=fr["mheights"], views=fr["views"], positions=fr["positions"],
                          screen_kw=fr.get("skw"), mobiles=fr["mobiles"] if mobiles is None else mobiles,
                          removed=fr.get("removed"), barrel_views=fr.get("bviews"), card=fr["phase"][3])

    def explosion_px(self, tr) -> int:
        """the pixels an explosion drew: on the frames whose mobiles hold one, the picture with them against the
        picture without the explosion"""
        n = 0
        for fr in tr:
            if any(mo[2] in EXPLOSION for mo in fr["mobiles"]):
                rest = [mo for mo in fr["mobiles"] if mo[2] not in EXPLOSION]
                n += P.px_diff(self.picture(fr), self.picture(fr, rest))
        return n


def place(run: Run, sc: dict, limit: int = 12):
    """the first candidate on which the oracle does what the scenario claims -> (pose, setup, trace, counters)"""
    for pose, setup in sc["cands"][:limit]:
        tr, _mr = run(pose, sc["keys"], setup)
        c = counters(tr)
        c["explosion_px"] = run.explosion_px(tr) if c["explosion_frames"] else 0
        if c["deaths"] == 0 and c["dead_frames"] == 0 and sc["claim"](c):
            return pose, setup, tr, c
    return None


def parts(run: Run, want: list, alt: list, nrt: int, ndrop: int = 0):
    """the first frame the mutated oracle's run differs from the oracle's -- cells, palette, or the picture (drawn
    only where the cells and the palette agree and the mobiles, the removals or the barrels' frames do not) --
    or None"""
    order, morder = run.dsim.order, run.dsim.mp.order
    for f, (x, y) in enumerate(zip(want, alt)):
        if normalized(G.expected_cells(x, order, morder), nrt, ndrop) \
                != normalized(G.expected_cells(y, order, morder), nrt, ndrop):
            return f, "cells"
        if x["pal"] != y["pal"]:
            return f, "palette"
        if (x["mobiles"], x.get("removed"), x.get("bviews")) != (y["mobiles"], y.get("removed"), y.get("bviews")) \
                and run.picture(x) != run.picture(y):
            return f, "picture"
    return None


# ================================================================================================
# the run
# ================================================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fjm")
    ap.add_argument("--labels")
    ap.add_argument("--oracle-only", action="store_true", help="the scenarios, counters and controls, no binary")
    ap.add_argument("--only", help="run only the scenarios whose name starts with this (e.g. H2)")
    a = ap.parse_args(argv)
    if not a.oracle_only and not (a.fjm and a.labels):
        ap.error("--fjm and --labels (the build's label table), or --oracle-only")
    t0 = time.time()
    orc = P.Oracle()
    dsim = onewalk.DoorSim()
    assert dsim.order == orc.door_order
    card_di = [di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
               if t.type == G.CARD_TYPE][0]
    run = Run(orc, dsim, card_di)
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_SKILL
    w0 = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=MMODE, player=PMODE)
    nrt = orc._mv(w0.world).nrt
    from doomfj.monsters import drop_rows
    ndrop = drop_rows(w0.world)
    orc.player_mode = PMODE
    scen = [s for s in scenario_list(dsim, w0.world) if not a.only or s["name"].startswith(a.only)]
    ok = True
    print("HURT GATE -- %d scenarios (MONSTER_MODE %s, PLAYER_MODE %s)%s"
          % (len(scen), MMODE, PMODE, "" if a.oracle_only else ", %s" % a.fjm))
    if not a.oracle_only:
        from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
        assert (MONSTER_MODE, PLAYER_MODE) == (MMODE, PMODE), (
            "the binary is built at %s/%s, this gate checks P5's %s/%s" % (MONSTER_MODE, PLAYER_MODE, MMODE, PMODE))
        gb = P.GameBinary(ROOT / a.fjm)
        cells = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis)
        for k in KEYFLAG.values():
            cells.setdefault(k, P.Cell(k, "hex", 1))
        table = P.LabelTable.load(ROOT / a.labels, {c.label for c in cells.values()})
        assert not table.absent & {"p_hp", "pj_act", "fx_act"}, (
            "the label table has no %s: a binary before P5" % sorted(table.absent))
    totals = {}
    for sc in scen:
        got = place(run, sc)
        print("\n%s -- %d frames" % (sc["name"], len(sc["keys"])))
        if got is None:
            ok = False
            print("  the oracle does what the scenario claims: NO candidate of %d -- FAIL" % len(sc["cands"][:12]))
            continue
        pose, setup, want, c = got
        print("  from (%.0f, %.0f) angle %08x: the oracle does what the scenario claims: yes"
              % (pose[0] / 65536, pose[1] / 65536, pose[2]))
        print("  counters: " + ", ".join("%s %d" % kv for kv in c.items()))
        print("  frame 0 pokes (the cells the setup moved): %s" % sorted(poke_cells(run, setup)))
        for k, v in c.items():
            totals[k] = totals.get(k, 0) + v
        for ctl in sc["controls"]:
            alt, _mr = run(pose, sc["keys"], setup, ctl)
            pt = parts(run, want, alt, nrt, ndrop)
            ok &= pt is not None
            print("  CONTROL %-12s the oracle without the rule parts at frame %s%s" % (
                ctl, "%d (%s)" % pt if pt else None,
                "" if pt is not None else " -- NEVER: the scenario is VACUOUS, FAIL"))
        if a.oracle_only:
            continue
        ok &= binary_scenario(gb, cells, table, run, sc, pose, setup, want)
    need = ("mon_hits", "mon_misses", "mon_melee", "proj_spawns", "proj_impacts", "proj_walls", "fizzles",
            "fx_spawns", "fx_skipped", "player_hurt", "armor_out", "explosion_frames", "explosion_px")
    zero = [k for k in need if not totals.get(k)] if not a.only else []
    ok &= not zero and totals.get("deaths", 0) == 0 and totals.get("dead_frames", 0) == 0
    print("\nTOTALS: " + ", ".join("%s %d" % kv for kv in totals.items()))
    print("every event counter nonzero: %s; deaths %d"
          % ("yes" if not zero else "NO -- %s" % zero, totals.get("deaths", 0)))
    print("\nHURT GATE %s%s (%.0f s)" % ("PASS" if ok else "FAIL", " (oracle only)" if a.oracle_only else "",
                                         time.time() - t0))
    return 0 if ok else 1


def poke_cells(run: Run, setup, *, mmode: str = MMODE, pmode: str = PMODE, lists: bool = False) -> dict:
    """the cells a scenario's setup moved from the boot level start -- what frame 0 writes into the binary.
    M7 P6+P7 (B0's aftermath, which lays DROPS): `lists` adds the runtime things' leaf lists (`leaf_list_cells`:
    sshead / thnext) -- a setup that makes a drop lie must LINK its row, as the binary's drop_link<k> does, or the
    binary never draws it; `mmode` / `pmode` the phases' modes (default this gate's)"""
    ca, cb = setup_cells(run, setup, mmode=mmode, pmode=pmode, lists=lists)
    return {k: v for k, v in cb.items() if ca.get(k) != v}


def setup_cells(run: Run, setup, *, mmode: str = MMODE, pmode: str = PMODE, lists: bool = False) -> tuple:
    """(the boot level start's cells, the cells after `setup`) -- `poke_cells`' two sides; a caller that checks the
    binary's cells BEFORE poking them (b0_scenarios) reads the first"""
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_SKILL
    orc, dsim = run.orc, run.dsim

    def cells_of(ph):
        return {**ph.state(), **orc.monster_rt(ph), **ph.weapon_state(),
                **(leaf_list_cells(orc, ph, BOOT_SKILL) if lists else {})}
    a = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=mmode, player=pmode)
    b = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=mmode, player=pmode)
    setup(b)
    return cells_of(a), cells_of(b)


def leaf_list_cells(orc, ph, skill) -> dict:
    """the binary's per-leaf runtime-thing lists for phase `ph` as the probe reads them: {"sshead": one byte per leaf,
    "thnext": one byte per row} -- built FROM SCRATCH (things.spawn_leaf_lists: each leaf's rows in ascending index,
    stored t + 1), which is what the binary's incremental links keep (pw_link / leaf_link insert in index order:
    barrelcode's "linked in that leaf's list in index order"). A row is linked when it is present: a runtime thing
    the skill spawns and the game has not removed (`MonsterViews.hidden`), a live mobile, a lying drop (mdrop 1).
    At the level start this is the restart block's own `things.skill_level_start` (tests/host hold the two equal)."""
    from doomfj.monsters import drop_rows, droppers, mobile_rows
    from doomfj.things import skill_absent, spawn_leaf_lists
    from doomfj.world import FIREBALL_POOL, FX_POOL
    mv, ws = orc._mv(ph.world), ph.world.ws
    thss = orc.monster_rt(ph)["thss_rt"]
    gone = skill_absent(mv.drawable, skill) | set(mv.hidden(ph))
    present = [mv.rt_drawable[t] not in gone for t in range(mv.nrt)]
    if mobile_rows(ph.world):
        present += [bool(ws.proj_active[s]) for s in range(FIREBALL_POOL)]
        present += [bool(ws.fx_active[s]) for s in range(FX_POOL)]
    if drop_rows(ph.world):
        present += [ws.mon_drop[m] == 1 for m in droppers(ph.world)]
    assert len(present) == len(thss), (len(present), len(thss))
    head, nxt = spawn_leaf_lists(thss, len(mv.cmap.subsectors), present)
    return {"sshead": tuple(head), "thnext": tuple(nxt)}


def binary_scenario(gb, cells, table, run: Run, sc, pose, setup, want) -> bool:
    poke = poke_cells(run, setup)
    reads = []
    p = P.Probe(cells, table, gb.width)
    missing = sorted(k for k in poke if k not in p.cells)
    assert not missing, "the setup moves cells the probe cannot write: %s" % missing
    keys = sc["keys"]

    def start(pr, f):
        vals = {k: int(bool(keys[f].get(n))) for n, k in KEYFLAG.items() if k in pr.cells}
        if f == 0:
            vals.update({"mode": 0, "viewx": _signed(pose[0], 32), "viewy": _signed(pose[1], 32),
                         "viewangle": pose[2], **poke})
        pr.write_cells(vals)
    order, morder = run.dsim.order, run.dsim.mp.order
    names = sorted({k for fr in want for k in G.expected_cells(fr, order, morder)})
    names = [k for k in names if k in p.cells]
    p.on_frame_start(start)
    p.on_present(lambda pr, f: reads.append(pr.read_cells(names)))
    r = gb.run(len(keys), [], p)
    s_bad = x_bad = p_bad = None
    for f, fr in enumerate(want):
        exp = G.expected_cells(fr, order, morder)
        got = reads[f] if f < len(reads) else {}
        if s_bad is None and any(got.get(k) != v for k, v in exp.items()):
            s_bad = (f, {k: (got.get(k), v) for k, v in exp.items() if got.get(k) != v})
        if x_bad is None and (f >= len(r.frames) or r.frames[f] != run.picture(fr)):
            x_bad = (f, P.px_diff(r.frames[f], run.picture(fr)) if f < len(r.frames) else -1)
        if p_bad is None and (f >= len(r.palettes) or r.palettes[f] != run.orc.palette_sha(fr["pal"])):
            p_bad = (f, fr["pal"])
    print("  binary: %d frames, %s ops -- STATE %s, PIXELS %s, PALETTE %s" % (
        len(r.frames), format(r.ops, ","),
        "exact on every frame" if s_bad is None else "PART at frame %d: %s" % s_bad,
        "byte-exact on every frame" if x_bad is None else "PART at frame %d (%d px)" % x_bad,
        "exact on every frame" if p_bad is None else "PART at frame %d (the oracle's PLAYPAL %d)" % p_bad))
    return s_bad is None and x_bad is None and p_bad is None


if __name__ == "__main__":
    sys.exit(main())
