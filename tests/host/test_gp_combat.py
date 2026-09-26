"""S3b: combat (`doomfj.combat`) -- the RNG call-site tables, damage and death, monster attacks,
the fireball and effect pools, barrels, pickups, and the player blocked by solid things.

Every rule is DOOM's (Chocolate Doom 895f581c) or an approved simplification named in combat.py's
docstring; every check has a negative control, a mutation it must reject (docs/cr-rules.md R9)."""
import pytest

from doomfj import combat as C
from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj import world as W
from doomfj.reference_model import SimState


def _world(skill=gd.SK_HARD, **kw):
    return W.World(skill=skill, strict=True, **kw)


def _slot(w, doomednum, nth=0):
    """The nth ACTIVE monster slot of a type."""
    return [m for m in range(w.layout.nmon)
            if w.mon_things[m].type == doomednum and w.ws.mon_active[m]][nth]


def _in_front(w, doomednum, dist, nth=0):
    """A monster of `doomednum` put `dist` units east of the player's start (the player faces
    east; that corridor is open for 256 units), awake with the player as its target."""
    m = _slot(w, doomednum, nth)
    w.teleport_monster(m, (w.ws.px >> 16) + dist, w.ws.py >> 16)
    w.ws.mon_target[m] = 1
    return m


def _ev(w):
    return W.TicEvents(w.tic_count)


# ---- the RNG call sites (D10) ------------------------------------------------------------------
def _sequential(formula, k, state):
    vals = []
    for _ in range(k):
        v, state = R.p_random(state)
        vals.append(v)
    return formula(*vals), state


def _site_mismatches(table, formula, k):
    """Every stream state at which one lookup + k disagrees with k successive P_Random calls."""
    bad = []
    for s in range(1 << R.STATE_BITS):
        got = (R.p_random_outcome(s, table) if k == 1 else C.p_random_outcome_k(s, table, k))
        if got != _sequential(formula, k, s):
            bad.append(s)
    return bad


@pytest.fixture(scope="module")
def world():
    return _world()


def test_every_call_site_table_is_its_doom_formula(world):
    forms = C.site_formulas(world.sites.col)
    sites = world.sites.all_sites()
    assert set(forms) == set(sites) and len(sites) >= 14
    for name, (k, table) in sites.items():
        fk, f = forms[name]
        assert fk == k and _site_mismatches(table, f, k) == [], name


def test_a_corrupted_table_entry_is_caught(world):
    """R9: one entry of the gunshot table changed -> exactly the state that reads it disagrees."""
    k, table = world.sites.gunshot
    bad = list(table)
    dmg, col = bad[77]
    bad[77] = (dmg + 5, col)
    f = C.site_formulas(world.sites.col)["gunshot"][1]
    assert _site_mismatches(bad, f, k) == [76]              # indexed by the POST-increment state


def test_the_k_draw_composition_reduces_to_rngs_for_one_draw():
    f = lambda v: (v * 7) % 13                              # noqa: E731
    assert C.outcome_table_k(f, 1) == R.outcome_table(f)


def test_the_pellet_columns_fill_exactly_the_aim_window(world):
    """DOOM's spread through the renderer's viewangletox lands on 72..88 (plan 6.4), every column."""
    cols = {c for _d, c in world.sites.gunshot[1]}
    assert (world.aim_lo, world.aim_centre, world.aim_hi) == (72, 80, 88)
    assert cols <= set(range(72, 89)) and len(cols) >= 15


def test_play_reads_its_damage_from_the_tables(monkeypatch):
    """The first pistol shot's damage is the table's entry at the player stream's state; corrupting
    that one entry changes the damage dealt (so the model reads the table, not a formula)."""
    def first_hit(w):
        m = _in_front(w, 3002, 96)                          # a demon: survives any pistol shot
        for _ in range(19):
            ev = w.tic({"fire": True})
            if ev.hits:
                return ev.hits[0][3], 150 - w.ws.mon_health[m]
        raise AssertionError("no hit")
    w = _world()
    k, table = w.sites.pistol_acc
    want, _ = R.p_random_outcome(R.stream_seed(R.STREAM_PLAYER), table)
    assert first_hit(w) == (want, want)
    bad = list(table)
    bad[(R.stream_seed(R.STREAM_PLAYER) + 1) & R.STATE_MASK] = 99
    w2 = _world()
    monkeypatch.setattr(w2.sites, "pistol_acc", (1, bad))
    assert first_hit(w2) == (99, 99)


# ---- damage: armor, death, gibs, corpses, drops --------------------------------------------------
def _doom_armor(armortype, armor, damage, green_div=3):
    """P_DamageMobj's armor lines, transcribed."""
    if armortype:
        saved = damage // green_div if armortype == 1 else damage // 2
        if armor <= saved:
            saved, armortype = armor, 0
        armor -= saved
        damage -= saved
    return armortype, armor, damage


def _armor_cases(green_div=3):
    w = _world()
    out = []
    for at in (0, 1, 2):
        for ap in (0, 1, 2, 7, 50, 100, 200):
            for dmg in (1, 2, 3, 5, 10, 15, 24, 40, 128):
                ws = w.ws
                ws.p_dead, ws.p_health, ws.p_armortype, ws.p_armor = 0, 1000, at, ap
                w.damage_player(dmg, ("test", 0), _ev(w))
                got = (ws.p_armortype, ws.p_armor, 1000 - ws.p_health)
                out.append((got, _doom_armor(at, ap, dmg, green_div)))
    return out


def test_armor_absorbs_a_third_or_a_half_like_doom():
    assert all(got == want for got, want in _armor_cases())


def test_the_armor_check_can_fail():
    """R9: against a green armor that saved 1/2, the same comparison must disagree somewhere."""
    assert any(got != want for got, want in _armor_cases(green_div=2))


def test_a_monster_dies_at_exactly_zero_health():
    for hp, dmg, dies in ((15, 15, True), (16, 15, False)):
        w = _world()
        m = _slot(w, 3004)
        w.ws.mon_health[m] = hp
        ev = _ev(w)
        w.damage_monster(m, dmg, ("player", -1), ev)
        assert (ev.kills == [("mon", m, "death")]) == dies
        assert w.ws.mon_shootable[m] == (0 if dies else 1)
        if dies:
            assert gd.STATE_NAMES[w.ws.mon_state[m]] == "S_POSS_DIE1"
        else:
            assert w.ws.mon_health[m] == 1


def test_the_gib_threshold_is_below_minus_spawnhealth():
    """P_KillMobj: health < -spawnhealth (and an xdeath state) gibs. Zombieman: 20 hp, so 41
    damage (-21) gibs and 40 (-20) does not; a demon has no xdeath state and never gibs."""
    for doomednum, dmg, how, state in ((3004, 41, "gib", "S_POSS_XDIE1"),
                                       (3004, 40, "death", "S_POSS_DIE1"),
                                       (3002, 400, "death", "S_SARG_DIE1")):
        w = _world()
        m = _slot(w, doomednum)
        ev = _ev(w)
        w.damage_monster(m, dmg, ("player", -1), ev)
        assert ev.kills == [("mon", m, how)]
        assert gd.STATE_NAMES[w.ws.mon_state[m]] == state
        assert 1 <= w.ws.mon_tics[m] <= gd.STATES[state].tics          # tics -= P_Random()&3


def test_a_corpse_blocks_until_its_a_fall_frame():
    """The player walks at a zombie he just killed: stopped while the corpse is MF_SOLID, through
    once A_Fall (S_POSS_DIE3) clears it -- DOOM's frame, not the death blow's."""
    w = _world()
    m = _in_front(w, 3004, 64)
    ev = _ev(w)
    w.damage_monster(m, 20, ("player", -1), ev)
    blocked_while_solid, fall_tic, passed = 0, None, False
    for t in range(40):
        ev = w.tic({"forward": True})
        if w.ws.mon_solid[m]:
            blocked_while_solid += ev.player_blocked
        elif fall_tic is None:
            fall_tic = t
            assert gd.STATE_NAMES[w.ws.mon_state[m]] == "S_POSS_DIE3"      # A_Fall's frame
        if (w.ws.px >> 16) > w.ws.mon_x[m]:
            passed = True
            break
    assert blocked_while_solid > 0 and fall_tic is not None and passed


def test_drops_sit_at_the_corpse_and_give_dropped_amounts():
    """P_KillMobj drops a clip (zombieman) or a shotgun (shotgun guy); walking over it gives half a
    clip (5 bullets) or the shotgun with ONE clip of shells (4), and makes it the pending weapon."""
    w = _world()
    z = _in_front(w, 3004, 64)
    s = _in_front(w, 9, 128)
    ev = _ev(w)
    w.damage_monster(z, 20, ("player", -1), ev)
    w.damage_monster(s, 30, ("player", -1), ev)
    assert (w.ws.mon_drop[z], w.ws.mon_drop[s]) == (1, 1)
    bullets = w.ws.p_ammo[gd.AM_CLIP]
    got = []
    for _ in range(60):
        got += w.tic({"forward": True}).pickups
    assert got == [("drop", z, 2007), ("drop", s, 2001)]
    assert w.ws.p_ammo[gd.AM_CLIP] == bullets + 5 and w.ws.p_ammo[gd.AM_SHELL] == 4
    assert w.ws.p_owned[gd.WP_SHOTGUN] and (w.ws.mon_drop[z], w.ws.mon_drop[s]) == (2, 2)


# ---- monster attacks -----------------------------------------------------------------------------
def test_the_half_width_table_is_the_geometry(world):
    """HWT[q]: the widest spread s with sin(s) * d <= 20 at d = 16q + 8 (s + 1 no longer fits)."""
    sine, hwt = world.rm.sine, world.hwt
    assert len(hwt) == 128 and all(a >= b for a, b in zip(hwt, hwt[1:]))
    for q, s in enumerate(hwt):
        d = max(16 * q + 8, C.HIT_HALF_WIDTH + 1)
        sin = lambda i: sine[i] - (1 << 32) if sine[i] >> 31 else sine[i]   # noqa: E731
        assert sin(s) * d <= C.HIT_HALF_WIDTH << 16
        assert s == 255 or sin(s + 1) * d > C.HIT_HALF_WIDTH << 16


def _hitscan_trials(sight=True):
    w = _world()
    m = _in_front(w, 3004, 200)
    if not sight:
        w.sight = lambda world, slot: False
    k, table = w.sites.mon_bullet
    dist = W.aprox_distance(*w._to_player(m))
    hits = misses = 0
    for s in range(256):
        w.ws.p_dead, w.ws.p_health, w.ws.p_armortype = 0, 1000, 0
        w.ws.mon_rng[m] = s
        (spread, dmg), _ = C.p_random_outcome_k(s, table, k)
        ev = _ev(w)
        w._monster_attack(m, "A_PosAttack", ev)
        hit = abs(spread) <= w.hwt[dist >> 4]
        assert ev.mon_shots == [(m, spread, dmg, hit and sight)]
        assert 1000 - w.ws.p_health == (dmg if hit and sight else 0)
        hits += hit and sight
        misses += not (hit and sight)
    return hits, misses


def test_monster_hitscan_hits_by_spread_against_the_width_table():
    hits, misses = _hitscan_trials()
    assert hits > 20 and misses > 20                        # both outcomes occur at 200 units


def test_monster_hitscan_needs_sight():
    hits, _misses = _hitscan_trials(sight=False)
    assert hits == 0


def test_the_imp_claws_in_melee_range_and_throws_a_fireball_outside_it():
    w = _world()
    m = _in_front(w, 3001, 40)                              # P_CheckMeleeRange: < 60, and sight
    k, table = w.sites.troop_claw
    want, _ = R.p_random_outcome(w.ws.mon_rng[m], table)
    ev = _ev(w)
    w._monster_attack(m, "A_TroopAttack", ev)
    assert ev.mon_melee == [(m, want)] and 100 - w.ws.p_health == want and not ev.proj_spawns
    w = _world()
    m = _in_front(w, 3001, 200)
    ev = _ev(w)
    w._monster_attack(m, "A_TroopAttack", ev)
    assert not ev.mon_melee and ev.proj_spawns == [(0, m)]


def test_the_demon_bites_only_in_melee_range():
    w = _world()
    m = _in_front(w, 3002, 40)
    ev = _ev(w)
    w._monster_attack(m, "A_SargAttack", ev)
    assert len(ev.mon_melee) == 1 and w.ws.p_health < 100
    w = _world()
    m = _in_front(w, 3002, 200)
    before = w.ws.mon_rng[m]
    ev = _ev(w)
    w._monster_attack(m, "A_SargAttack", ev)
    assert not ev.mon_melee and w.ws.mon_rng[m] == before  # out of range: no roll at all


# ---- fireballs -----------------------------------------------------------------------------------
def test_a_fireball_flies_hits_the_player_and_explodes():
    w = _world()
    m = _in_front(w, 3001, 200)
    ev = _ev(w)
    w._monster_attack(m, "A_TroopAttack", ev)
    ws = w.ws
    # R_PointToAngle2 due west is ANG180-1 (DOOM's octant quirk), so momy is a hair above 0
    an = w.rm.point_to_angle(ws.mon_x[m] << 16, ws.mon_y[m] << 16, ws.px, ws.py)
    momx, momy = w.fireball_mom[an >> w.rm.angle_shift]
    assert ws.proj_active[0] and (ws.proj_momx[0], ws.proj_momy[0]) == (momx, momy)
    assert momx == -(10 << 16) and 0 <= momy < 1 << 10
    x0, y0, impact = ws.proj_x[0], ws.proj_y[0], None
    for t in range(40):
        ev = w.tic({})
        assert w.leaf_lists() == w.leaf_lists_from_scratch()
        if ev.proj_impacts:
            impact = (t, ev.proj_impacts[0][1])
            break
        assert (ws.proj_x[0], ws.proj_y[0]) == (x0 + (t + 1) * momx, y0 + (t + 1) * momy)
    assert impact is not None
    assert 100 - ws.p_health == impact[1] and impact[1] in {3 * i for i in range(1, 9)}
    assert gd.STATE_NAMES[ws.proj_state[0]].startswith("S_TBALLX")
    for _ in range(20):
        w.tic({})
    assert not ws.proj_active[0] and w.leaf_lists() == w.leaf_lists_from_scratch()


def test_a_fireball_stops_at_a_wall():
    w = _world()
    m = _in_front(w, 3001, 200)
    w.teleport_player(w.ws.px - (400 << 16), w.ws.py)      # out of the way: behind the start
    ev = _ev(w)
    w._spawn_fireball(m, ev)                                # aimed west, at where he stands
    walls = 0
    for _ in range(120):
        walls += len(w.tic({}).proj_walls)
        if not w.ws.proj_active[0]:
            break
    assert walls == 1 and not w.ws.proj_active[0] and not w.events[-1].proj_impacts


def test_a_full_pool_fizzles_and_a_free_slot_does_not():
    w = _world()
    m = _in_front(w, 3001, 200)
    ev = _ev(w)
    for _ in range(W.FIREBALL_POOL):
        w._spawn_fireball(m, ev)
    assert sum(w.ws.proj_active) == W.FIREBALL_POOL and not ev.fizzles
    before = w.ws.digest()
    rng = w.ws.mon_rng[m]
    ev = _ev(w)
    w._monster_attack(m, "A_TroopAttack", ev)
    assert ev.fizzles == [m] and not ev.proj_spawns
    assert w.ws.mon_rng[m] == rng                           # a fizzle draws nothing
    assert sum(w.ws.proj_active) == W.FIREBALL_POOL and w.ws.digest() != before   # (it faced him)
    w.ws.proj_active[3] = 0                                 # free one slot (control)
    w._list_remove(w.layout.nmon + 3, w.ws.proj_leaf[3])
    ev = _ev(w)
    w._monster_attack(m, "A_TroopAttack", ev)
    assert ev.proj_spawns == [(3, m)] and not ev.fizzles


def test_the_effect_pool_holds_two():
    """Seven pellets into a demon at point blank: two blood spots, five skipped (the pool is 2)."""
    w = _world()
    ws = w.ws
    ws.p_owned[gd.WP_SHOTGUN], ws.p_ammo[gd.AM_SHELL] = 1, 5
    w.tic({"w3": True})
    for _ in range(40):
        w.tic({})
    _in_front(w, 3002, 64)
    evs = [w.tic({"fire": True}) for _ in range(8)]
    blast = [ev for ev in evs if ev.shots][0]
    assert len(blast.hits) == 7 and len(blast.fx_spawns) == 2 and blast.fx_skipped == 5
    assert sum(ws.fx_active) == 2


# ---- barrels -------------------------------------------------------------------------------------
def test_a_barrel_explodes_and_sets_off_its_neighbours():
    """Barrel 0 (20 hp) killed: S_BEXP, A_Explode 15 tics later (minus the tics roll) damages
    barrels 1 and 2 (32 units away: 128 - (32 - 10) = 106), which explode in turn, and every
    barrel is removed (no longer solid) after S_BEXP5."""
    w = _world()
    ws = w.ws
    far = next(b for b, t in enumerate(w.barrel_things)
               if max(abs(t.x - w.barrel_things[0].x), abs(t.y - w.barrel_things[0].y)) > 400)
    ev = _ev(w)
    w.damage_barrel(0, 20, ev)
    assert ev.kills == [("bar", 0, "death")] and gd.STATE_NAMES[ws.bar_state[0]] == "S_BEXP"
    blasts, hits = [], []
    for t in range(120):
        ev = w.tic({})
        blasts += [(t, b) for b in ev.barrel_blasts]
        hits += ev.hits
    order = [b for _t, b in blasts]
    assert order[0] == 0 and {1, 2} <= set(order)
    assert ("barrel", "bar", 1, 106) in hits and ("barrel", "bar", 2, 106) in hits
    assert all(not ws.bar_state[b] and not ws.bar_solid[b] for b in (0, 1, 2))
    assert ws.bar_state[far] and ws.bar_health[far] == 20   # out of range: untouched (control)


def test_the_blast_hurts_the_player_in_range_and_in_sight():
    """128 - (Chebyshev distance - radius): 100 units away -> 44. Controls: 150 away is out of
    range (150 - 16 >= 128), and the same 100 units with the blast's sight cut does nothing."""
    def hurt(dx, sight=True):
        w = _world()
        t0 = w.barrel_things[0]
        w.teleport_player((t0.x - dx) << 16, t0.y << 16)
        assert w.los_points((w.ws.px, w.ws.py), (t0.x << 16, t0.y << 16))
        if not sight:
            w.los_points = lambda p, q: False
        ev = _ev(w)
        w._radius_attack(0, ev)
        return [(s, raw) for s, raw, _d in ev.player_hurt]
    assert hurt(100) == [(("bar", 0), 128 - (100 - 16))]
    assert hurt(150) == [] and hurt(100, sight=False) == []


# ---- pickups -------------------------------------------------------------------------------------
PICKUP_CASES = [
    # (setup, thing, dropped, taken, expected)
    ({"p_health": 100}, 2011, False, False, {"p_health": 100}),            # stimpack at 100
    ({"p_health": 95}, 2011, False, True, {"p_health": 100}),              # ... capped
    ({"p_health": 90}, 2012, False, True, {"p_health": 100}),              # medikit capped
    ({"p_health": 70}, 2012, False, True, {"p_health": 95}),
    ({"p_health": 200}, 2014, False, True, {"p_health": 200}),             # bonus: over 100, to 200
    ({"p_health": 150}, 2014, False, True, {"p_health": 151}),
    ({"p_armor": 0, "p_armortype": 0}, 2015, False, True, {"p_armor": 1, "p_armortype": 1}),
    ({"p_armor": 200, "p_armortype": 2}, 2015, False, True, {"p_armor": 200, "p_armortype": 2}),
    ({"p_armor": 100, "p_armortype": 1}, 2018, False, False, {"p_armor": 100}),   # green at 100
    ({"p_armor": 99, "p_armortype": 2}, 2018, False, True, {"p_armor": 100, "p_armortype": 1}),
    ({"p_armor": 150, "p_armortype": 1}, 2019, False, True, {"p_armor": 200, "p_armortype": 2}),
    ({"clip": 200}, 2007, False, False, {"clip": 200}),                    # full
    ({"clip": 195}, 2007, False, True, {"clip": 200}),                     # capped
    ({"clip": 0}, 2007, True, True, {"clip": 5}),                          # a dropped clip: half
    ({"clip": 10}, 2048, False, True, {"clip": 60}),                       # box of bullets
    ({"shell": 0}, 2008, False, True, {"shell": 4}),
    ({"shell": 40}, 2049, False, True, {"shell": 50}),                     # box of shells, capped
    ({"cell": 0}, 2047, False, True, {"cell": 20}),
    ({"misl": 0}, 2010, False, True, {"misl": 1}),
    ({"clip": 200}, 8, False, True, {"clip": 210, "shell": 4, "p_backpack": 1}),   # backpack
]
AMMO = {"clip": gd.AM_CLIP, "shell": gd.AM_SHELL, "cell": gd.AM_CELL, "misl": gd.AM_MISL}


def _apply(w, setup):
    for k, v in setup.items():
        if k in AMMO:
            w.ws.p_ammo[AMMO[k]] = v
        else:
            setattr(w.ws, k, v)


def _read(w, keys):
    return {k: (w.ws.p_ammo[AMMO[k]] if k in AMMO else getattr(w.ws, k)) for k in keys}


@pytest.mark.parametrize("setup,thing,dropped,taken,want", PICKUP_CASES)
def test_pickups_respect_dooms_caps(setup, thing, dropped, taken, want):
    w = _world()
    _apply(w, setup)
    bonus = w.ws.p_bonuscount
    assert w._touch(thing, dropped, 0, 0) == taken
    assert _read(w, want) == want
    assert w.ws.p_bonuscount == bonus + (gd.BONUSADD if taken else 0)


def test_pickups_are_out_of_reach_above_the_head_or_below_the_feet():
    w = _world()
    w.ws.p_health = 50
    assert not w._touch(2011, False, 57, 0) and not w._touch(2011, False, -9, 0)
    assert w._touch(2011, False, 56, 0) and w._touch(2011, False, -8, 0)


def test_shells_from_empty_switch_to_an_owned_shotgun():
    """P_GiveAmmo: ammo from zero switches a pistol-holder to the shotgun; ammo on top of some does
    not (the control)."""
    for shells, want in ((0, gd.WP_SHOTGUN), (1, gd.WP_NOCHANGE)):
        w = _world()
        w.ws.p_owned[gd.WP_SHOTGUN], w.ws.p_ammo[gd.AM_SHELL] = 1, shells
        assert w._touch(2008, False, 0, 0) and w.ws.p_pending == want


def test_the_blue_key_opens_the_blue_doors_and_nothing_else_needs_it():
    """EV_VerticalDoor: without the card a blue door stays shut; with it, it opens. A plain door
    opens without any card (the control)."""
    def press(si, card):
        w = _world()
        box = w.door_boxes[si]
        w.teleport_player(((box[0] + box[2]) // 2) << 16, ((box[1] + box[3]) // 2) << 16)
        w.ws.p_cards[gd.IT_BLUECARD] = card
        for _ in range(4):
            w.tic({"use": True})
        return w.ws.d_state[w.door_order.index(si)]
    assert set(_world().door_cards) == {51, 71}
    for si in (51, 71):
        assert press(si, 0) == 0 and press(si, 1) > 0
    assert press(10, 0) > 0
    w = _world()
    key = [i for i, t in enumerate(w.pickup_things) if t.type == 5][0]
    assert w._touch(5, False, 0, 0) and w.ws.p_cards[gd.IT_BLUECARD] == 1
    assert w.ws.p_bonuscount == 2 * gd.BONUSADD             # P_GiveCard sets 6, the tail adds 6
    assert key >= 0


# ---- the player blocked by solid things ---------------------------------------------------------
def _barrel_lane(w):
    """A barrel with a straight east-west lane through it: the player 64 west of it, facing east,
    no wall on the way to 64 east of it."""
    for b, t in enumerate(w.barrel_things):
        if not w.ws.bar_solid[b]:
            continue
        ok = all(w.check_lines((t.x + dx) << 16, t.y << 16, W.PLAYER_R << 16, monster=False)[0]
                 == W.OK for dx in range(-64, 65, 8))
        others = [c for c, u in enumerate(w.barrel_things) if c != b
                  and abs(u.y - t.y) < 36 and abs(u.x - t.x) < 120]
        if ok and not others:
            return b, t
    raise AssertionError("no free lane through a barrel")


@pytest.mark.parametrize("blocking", [True, False])
def test_the_player_is_blocked_by_a_barrel_unless_legacy(blocking):
    w = _world(player_blocking=blocking)
    b, t = _barrel_lane(w)
    w.teleport_player((t.x - 64) << 16, t.y << 16, angle=0)
    xs = [w.ws.px >> 16]
    for _ in range(10):
        w.tic({"forward": True})
        xs.append(w.ws.px >> 16)
    closest = min(abs(x - t.x) for x in xs)
    if blocking:
        assert closest >= C.BARREL_R + W.PLAYER_R and max(xs) < t.x
    else:
        assert max(xs) > t.x                                # walked straight through it


def test_legacy_walking_is_the_oracles_step_sim():
    """With `player_blocking` off, the player's move is `ReferenceModel.step_sim` exactly (the
    walk-through regression the flag exists for); with it on it is too where nothing is in the way."""
    for blocking in (False, True):
        w = _world(player_blocking=blocking)
        st = SimState(w.ws.px, w.ws.py, w.ws.pangle, w.mapname)
        keys = ([{"forward": True}] * 12 + [{"turn_left": True, "forward": True}] * 9
                + [{"back": True}] * 6 + [{"turn_right": True}] * 4 + [{"forward": True}] * 20)
        for k in keys:
            w.tic(k)
            st = w.rm.step_sim(st, k, scene=w.scene_c)
            assert (w.ws.px, w.ws.py, w.ws.pangle) == (st.x, st.y, st.angle)
