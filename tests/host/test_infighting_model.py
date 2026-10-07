"""M7 P8a package I (docs/gp-final-plan.md 1.2.2, 3.1 row I): INFIGHTING in the model -- `world.infighting_on`
("final" monsters) -- on the host:

  * targets name a thing (`mon_target`: 0 none, 1 the player, 2 + slot) and every AI rule asks the TARGET: A_Chase's
    threshold and its lost target (a dead monster target -> P_LookForPlayers all around, else the spawn state), the
    melee reach (MELEERANGE - 20 + the target's radius), the missile range, P_NewChaseDir, A_FaceTarget, the attacks;
  * DOOM's switch in P_DamageMobj: threshold 0, a source, not the target itself -> the source, BASETHRESHOLD;
  * the attack sight of a monster target is the exact 2D LOS at any range (O-B2);
  * monster bullets meet things nearer than the target (O-B5); fireballs stop on monsters and barrels -- the shooter
    passed, the same species exploding with no damage, a solid corpse stopping it with none;
  * `bar_src`: the source of the first damage that did NOT kill the barrel (DOOM's barrel target), its blast's
    source;
  * "full" and "push" are untouched (no fight): the target stays one bit and the player's.
Each claim FAILS on the pre-I model (the generalisations are absent there), then PASSES."""
import pytest

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.combat import FIREBALL_INFO, HWT_SHIFT, MISSILERANGE_U, hit_half_width, half_width_table
from doomfj.world import (MELEE_BASE, MELEE_REACH, TicEvents, World, aprox_distance, infighting_on)

C = (800, 400)            # an open spot on E1M1 (the room of slots 21-23): clear 2D sight 150 units every way


@pytest.fixture(scope="module")
def base():
    return World(skill=gd.SK_HARD, monsters="final", player="final", sight_rule="los", monster_tics=1)


@pytest.fixture
def w(base):
    base.reset(gd.SK_HARD)
    base.teleport_player(C[0] << 16, (C[1] + 300) << 16)     # behind a wall from C
    ws = base.ws
    for m in range(base.layout.nmon):                         # the room's own monsters leave the stage
        if ws.mon_active[m] and max(abs(ws.mon_x[m] - C[0]), abs(ws.mon_y[m] - C[1])) < 400:
            base._list_remove(m, ws.mon_leaf[m])
            ws.mon_active[m] = ws.mon_solid[m] = ws.mon_shootable[m] = 0
    return base


def _of(w, ty, n=0, skip=()):
    out = [m for m, t in enumerate(w.mon_things) if t.type == ty and w.ws.mon_active[m] and m not in skip]
    return out[n]


def _place(w, m, x, y, target=0):
    w.teleport_monster(m, x, y)
    w.ws.mon_target[m] = target


def test_the_rule_is_finals_alone():
    assert [m for m in ("full", "push", "final") if infighting_on(m)] == ["final"]
    for pm, mm in (("full", "full"), ("final", "push")):
        v = World(skill=gd.SK_HARD, monsters=mm, player=pm)
        assert not v._fight and next(f for f in v.schema if f.name == "mon_target").bits == 1
        assert "bar_src" not in {f.name for f in v.schema}
    v = World(skill=gd.SK_HARD, monsters="final", player="final")
    assert v._fight and next(f for f in v.schema if f.name == "mon_target").bits == 6


def test_the_target_helpers(w):
    ws = w.ws
    a, b = _of(w, 3001), _of(w, 3002)
    _place(w, a, *C, target=2 + b)
    _place(w, b, C[0] + 50, C[1] - 30)
    assert w._to_target(a) == (50, -30) and w._target_pos16(a) == ((C[0] + 50) << 16, (C[1] - 30) << 16)
    assert w._target_radius(a) == 30 and w._melee_reach(a) == MELEE_BASE + 30 == 74
    assert w.target_alive(a)
    ws.mon_target[a] = 1
    assert w._to_target(a) == w._to_player(a) and w._melee_reach(a) == MELEE_REACH == 60
    assert w.target_alive(a)
    ws.p_dead = 1
    assert not w.target_alive(a)
    ws.p_dead = 0
    ws.mon_target[a] = 2 + b
    ws.mon_shootable[b], ws.mon_health[b] = 0, 0
    assert not w.target_alive(a)
    ws.mon_target[a] = 0
    assert not w.target_alive(a)


def test_the_switch_and_its_threshold(w):
    ws = w.ws
    t, s1, s2 = _of(w, 3001), _of(w, 3004), _of(w, 9)
    ws.mon_target[t], ws.mon_threshold[t] = 0, 0
    ev = TicEvents(0)
    w.damage_monster(t, 1, ("mon", s1), ("mon", s1), ev)
    assert ws.mon_target[t] == 2 + s1 and ws.mon_threshold[t] == gd.BASETHRESHOLD and ev.retargets == [(t, 2 + s1)]
    # a woken monster: the spawn state became the see state (D-WAKE)
    assert ws.mon_state[t] in (gd.STATE_INDEX[w.mon_info[t].seestate], gd.STATE_INDEX[w.mon_info[t].painstate])
    w.damage_monster(t, 1, ("mon", s2), ("mon", s2), ev)
    assert ws.mon_target[t] == 2 + s1, "the threshold refuses a second switch"
    w.damage_monster(t, 1, ("player", -1), ("player", -1), ev)
    assert ws.mon_target[t] == 2 + s1
    ws.mon_threshold[t] = 0
    w.damage_monster(t, 1, None, ("bar", 0), ev)
    assert ws.mon_target[t] == 2 + s1 and ws.mon_threshold[t] == 0, "no source: no switch"
    w.damage_monster(t, 1, ("mon", t), ("bar", 0), ev)
    assert ws.mon_target[t] == 2 + s1 and ws.mon_threshold[t] == 0, "its own barrel's blast: no switch"
    w.damage_monster(t, 1, ("player", -1), ("player", -1), ev)
    assert ws.mon_target[t] == 1 and ws.mon_threshold[t] == gd.BASETHRESHOLD


def test_the_threshold_counts_down_only_on_a_live_target(w):
    ws = w.ws
    a, b = _of(w, 3001), _of(w, 3004)
    _place(w, a, *C, target=2 + b)
    _place(w, b, C[0] + 100, C[1])
    w._set_state(a, w.mon_info[a].seestate, False, TicEvents(0))
    ws.mon_threshold[a], ws.mon_reaction[a] = 50, 8
    w._a_chase(a, TicEvents(0))
    assert ws.mon_threshold[a] == 49
    ws.mon_shootable[b], ws.mon_health[b] = 0, -3
    ws.mon_threshold[a] = 50
    w._a_chase(a, TicEvents(0))
    assert ws.mon_threshold[a] == 0, "a dead target resets it"


def test_a_dead_target_returns_to_the_look(w):
    ws = w.ws
    a, b = _of(w, 3001), _of(w, 3004)
    _place(w, a, *C, target=2 + b)
    _place(w, b, C[0] + 100, C[1])
    ws.mon_shootable[b], ws.mon_health[b] = 0, 0
    see = gd.STATE_INDEX[w.mon_info[a].seestate]
    # the player out of sight: back to the spawn state (A_Look runs, finds nothing)
    w._set_state(a, w.mon_info[a].seestate, False, TicEvents(0))
    w._a_chase(a, TicEvents(0))
    assert ws.mon_state[a] == gd.STATE_INDEX[w.mon_info[a].spawnstate] and ws.mon_target[a] == 2 + b
    # the player in sight (P_LookForPlayers all around: behind it too): the player becomes the target
    w._set_state(a, w.mon_info[a].seestate, False, TicEvents(0))
    w.teleport_player((C[0] - 100) << 16, C[1] << 16)
    ws.mon_facing[a] = gd.DI_EAST                     # facing away
    x0 = ws.mon_x[a]
    w._a_chase(a, TicEvents(0))
    assert ws.mon_target[a] == 1 and ws.mon_state[a] == see and ws.mon_x[a] == x0, "re-acquired, no move this tic"


def test_the_melee_reach_is_the_targets_radius(w):
    ws = w.ws
    a = _of(w, 3001)
    for ty, r in ((3002, 30), (3004, 20)):
        b = _of(w, ty)
        _place(w, a, *C, target=2 + b)
        for d in (MELEE_BASE + r - 1, MELEE_BASE + r):
            _place(w, b, C[0] + d, C[1])
            assert w._check_melee_range(a) == (d < MELEE_BASE + r), (ty, d)
    ws.mon_target[a] = 1
    for d in (MELEE_REACH - 1, MELEE_REACH):
        w.teleport_player((C[0] + d) << 16, C[1] << 16)
        assert w._check_melee_range(a) == (d < MELEE_REACH)


def test_a_monster_targets_attack_sight_is_the_far_los(w):
    """O-B2: the exact LOS at any range -- the "seen" mark and NEAR are the player's"""
    ws = w.ws
    a, b = _of(w, 3001), _of(w, 3004)
    for sight_rule in ("los", "seen"):
        w.set_sight_rule(sight_rule)
        _place(w, a, *C, target=2 + b)
        _place(w, b, C[0], C[1] - 300)               # 300 units, the way clear
        ws.mon_seen[a] = 0
        assert w.attack_sight(w, a) and w.los_to_target(w, a)
        _place(w, b, C[0], C[1] + 300)               # 300 units, a wall between
        ws.mon_seen[a] = 1                           # seen by the player: irrelevant to a monster target
        assert not w.attack_sight(w, a)
    w.set_sight_rule("los")


def test_the_chase_dir_and_the_facing_go_to_the_target(w):
    ws = w.ws
    a, b = _of(w, 3001), _of(w, 3004)
    _place(w, a, *C, target=2 + b)
    _place(w, b, C[0] - 120, C[1] - 120)
    w.teleport_player((C[0] + 100) << 16, (C[1] + 100) << 16)
    w._a_face_target(a)
    assert ws.mon_facing[a] == gd.DI_SOUTHWEST
    ws.mon_movedir[a] = gd.DI_NODIR
    w._new_chase_dir(a, TicEvents(0))
    assert ws.mon_movedir[a] == gd.DI_SOUTHWEST


def _stream_for(w, m, want):
    """a monster-stream state whose first bullet's spread satisfies `want`"""
    for s in range(1 << R.STATE_BITS):
        spread, _dmg = w.sites.mon_bullet[1][(s + 1) & R.STATE_MASK]     # combat.p_random_outcome_k's index
        if want(spread):
            return s
    raise AssertionError("no state")


def test_an_intervening_thing_takes_the_bullet(w):
    ws = w.ws
    z, imp, far = _of(w, 3004), _of(w, 3001), _of(w, 3001, 1)
    _place(w, z, *C, target=1)
    _place(w, imp, C[0] + 100, C[1])                 # on the line to the player
    w.teleport_player((C[0] + 140) << 16, C[1] << 16)
    a_t = w.rm.point_to_angle(C[0] << 16, C[1] << 16, ws.px, ws.py)
    assert w._bullet_victim(z, 0, a_t, 140) == ("mon", imp)
    assert w._bullet_victim(z, 0, a_t, 100) is None, "not nearer than the target"
    hw = w.hwt_r[20][100 >> HWT_SHIFT]
    assert w._bullet_victim(z, hw, a_t, 140) == ("mon", imp), "the edge of its width"
    assert w._bullet_victim(z, hw + 1, a_t, 140) is None, "just outside the imp's width"
    _place(w, far, C[0] + 30, C[1] + 1)
    assert w._bullet_victim(z, 0, a_t, 140) == ("mon", far), "the nearest"
    ws.mon_shootable[far], ws.mon_health[far] = 0, 0
    assert w._bullet_victim(z, 0, a_t, 140) == ("mon", imp), "a corpse takes nothing"
    ws.mon_target[z] = 2 + imp                        # the target itself is never "in the way"
    assert w._bullet_victim(z, 0, w.rm.point_to_angle(C[0] << 16, C[1] << 16, (C[0] + 60) << 16, C[1] << 16),
                            60) is None
    # the whole attack: a zombieman aims at the player, the imp in the line is hit, bleeds and turns on it
    ws.mon_target[z] = 1
    st = _stream_for(w, z, lambda sp: abs(sp) <= 2)
    ws.mon_rng[z], ws.mon_threshold[imp] = st, 0
    hp = ws.mon_health[imp]
    ev = TicEvents(0)
    w._mon_hitscan(z, 1, ev)
    assert ev.mon_hits and ev.mon_hits[0][:4] == (z, "bullet", "mon", imp) and ws.mon_health[imp] < hp
    assert ws.mon_target[imp] == 2 + z and ev.fx_spawns and ev.fx_spawns[0][1] == "blood"
    assert ws.p_health == 100


def test_a_monster_target_is_shot_with_its_own_width(w):
    ws = w.ws
    z, dm = _of(w, 3004), _of(w, 3002)
    _place(w, z, *C, target=2 + dm)
    _place(w, dm, C[0], C[1] - 200)
    d = aprox_distance(*w._to_target(z))
    hw30 = half_width_table(w.rm.sine, hit_half_width(30))
    assert hw30[d >> HWT_SHIFT] > w.hwt[d >> HWT_SHIFT], "a demon is wider than the player"
    st = _stream_for(w, z, lambda sp: w.hwt[d >> HWT_SHIFT] < abs(sp) <= hw30[d >> HWT_SHIFT])
    ws.mon_rng[z] = st
    hp = ws.mon_health[dm]
    ev = TicEvents(0)
    w._mon_hitscan(z, 1, ev)
    assert ev.mon_shots[0][3] and ws.mon_health[dm] < hp, "within the demon's width, outside the player's"


def test_the_claw_lands_on_a_monster_target(w):
    ws = w.ws
    imp, z = _of(w, 3001), _of(w, 3004)
    _place(w, imp, *C, target=2 + z)
    _place(w, z, C[0] + 40, C[1])
    ws.mon_threshold[z] = 0
    hp = ws.mon_health[z]
    ev = TicEvents(0)
    w._monster_attack(imp, "A_TroopAttack", ev)
    assert ev.mon_melee and ws.mon_health[z] == hp - ev.mon_melee[0][1] and not ev.fx_spawns
    assert ws.mon_target[z] == 2 + imp and ws.p_health == 100


def test_the_fireball_aims_at_the_target(w):
    ws = w.ws
    imp, z = _of(w, 3001), _of(w, 3004)
    _place(w, imp, *C, target=2 + z)
    _place(w, z, C[0], C[1] - 120)                   # due south
    ev = TicEvents(0)
    w._spawn_fireball(imp, ev)
    s = ev.proj_spawns[0][0]
    assert ws.proj_momx[s] == 0 or abs(ws.proj_momx[s]) < 0x100 and ws.proj_momy[s] < -(9 << 16)


def _fly(w, s, tics=40):
    ev = TicEvents(0)
    for _ in range(tics):
        if not w.ws.proj_active[s] or w.ws.proj_state[s] != gd.STATE_INDEX[FIREBALL_INFO.spawnstate] and \
                w.ws.proj_momx[s] == 0 and w.ws.proj_momy[s] == 0:
            break
        w._projectiles_phase(ev)
    return ev


def test_fireballs_hit_monsters_and_pass_their_shooter(w):
    ws = w.ws
    imp, z = _of(w, 3001), _of(w, 3004)
    _place(w, imp, *C, target=2 + z)
    _place(w, z, C[0] + 100, C[1])
    ws.mon_threshold[z] = 0
    hp = ws.mon_health[z]
    ev = TicEvents(0)
    w._spawn_fireball(imp, ev)
    s = ev.proj_spawns[0][0]
    assert ws.proj_active[s] and ws.proj_momx[s] > 0, "spawned beside its shooter, not stopped by it"
    ev = _fly(w, s)
    assert [h[:4] for h in ev.mon_hits] == [(imp, "fireball", "mon", z)] and ws.mon_health[z] < hp
    assert ws.mon_target[z] == 2 + imp


def test_the_same_species_explodes_with_no_damage(w):
    ws = w.ws
    imp, imp2 = _of(w, 3001), _of(w, 3001, 1)
    _place(w, imp, *C, target=2 + imp2)
    _place(w, imp2, C[0] + 100, C[1])
    hp, fx = ws.mon_health[imp2], ws.rng_fx
    ev = TicEvents(0)
    w._spawn_fireball(imp, ev)
    s = ev.proj_spawns[0][0]
    ev = _fly(w, s)
    assert [h[:4] for h in ev.mon_hits] == [(imp, "fireball", "species", imp2)] and ws.mon_health[imp2] == hp
    assert ws.proj_state[s] == gd.STATE_INDEX[FIREBALL_INFO.deathstate] or not ws.proj_active[s]
    assert ws.mon_target[imp2] != 2 + imp


def test_a_solid_corpse_stops_a_fireball_a_fallen_one_does_not(w):
    ws = w.ws
    imp, z = _of(w, 3001), _of(w, 3004)
    _place(w, imp, *C, target=1)
    _place(w, z, C[0] + 100, C[1])
    w.teleport_player((C[0] + 300) << 16, C[1] << 16)
    ws.mon_shootable[z], ws.mon_health[z] = 0, -5           # dying: still MF_SOLID
    ev = TicEvents(0)
    w._spawn_fireball(imp, ev)
    ev = _fly(w, ev.proj_spawns[0][0])
    assert [h[:3] for h in ev.mon_hits] == [(imp, "fireball", "corpse")]
    ws.mon_solid[z] = 0                                     # after A_Fall
    for s in range(8):
        ws.proj_active[s] = 0
    ev = TicEvents(0)
    w._spawn_fireball(imp, ev)
    ev = _fly(w, ev.proj_spawns[0][0])
    assert not ev.mon_hits


def test_bar_src_is_the_first_non_lethal_damager(w):
    ws = w.ws
    z, imp = _of(w, 3004), _of(w, 3001)
    ev = TicEvents(0)
    w.damage_barrel(0, 1, ("mon", z), ev)
    assert ws.bar_src[0] == 2 + z
    w.damage_barrel(0, 1, ("player", -1), ev)
    assert ws.bar_src[0] == 2 + z, "the first"
    w.damage_barrel(1, 1, None, ev)
    assert ws.bar_src[1] == 0
    w.damage_barrel(1, 1, ("player", -1), ev)
    assert ws.bar_src[1] == 1, "the first WITH a source"
    w.damage_barrel(2, 100, ("mon", imp), ev)
    assert ws.bar_src[2] == 0 and ws.bar_health[2] <= 0, "the killing blow sets no target"


def test_the_blast_blames_bar_src(w):
    ws = w.ws
    b = 0
    bt = w.barrel_things[b]
    z, imp = _of(w, 3004), _of(w, 3001)
    near = [(bt.x + dx, bt.y + dy) for dx in (100, -100, 110, -110) for dy in (0, 30, -30)]
    spot = next(p for p in near if w.los_points((p[0] << 16, p[1] << 16), (bt.x << 16, bt.y << 16)))
    _place(w, imp, *spot, target=0)
    ws.mon_threshold[imp] = 0
    pl = next((bt.x + dx, bt.y + dy) for dx, dy in ((50, 50), (-50, 50), (50, -50), (-50, -50), (0, 60), (0, -60))
              if w.los_points(((bt.x + dx) << 16, (bt.y + dy) << 16), (bt.x << 16, bt.y << 16)))
    w.teleport_player(pl[0] << 16, pl[1] << 16)
    ws.p_armor = 0
    ws.bar_src[b] = 2 + z
    ev = TicEvents(0)
    w._radius_attack(b, ev)
    assert ws.mon_target[imp] == 2 + z and ws.p_attacker == z + 1


def test_a_brawl_keeps_the_invariants():
    """300 tics with every awake monster targeting another: the cells stay in range, mon_shootable is exactly "active
    and health > 0" (the fj reads it as the target's life), the fight happens (switches, hits, kills by monsters)"""
    w = World(skill=gd.SK_HARD, monsters="final", player="final", sight_rule="los")
    w.wake_all()
    ws, n = w.ws, w.layout.nmon
    act = [m for m in range(n) if ws.mon_active[m]]
    # pack the courtyard's crowd: every awake monster targets its neighbour in slot order
    for k, m in enumerate(act):
        ws.mon_target[m] = 2 + act[(k + 1) % len(act)]
    w.teleport_player(-416 << 16, 256 << 16)
    tot = {"retargets": 0, "mon_hits": 0, "kills": 0}
    for _ in range(300):
        ev = w.tic({})
        for k in tot:
            tot[k] += len(getattr(ev, k))
        for m in range(n):
            assert bool(ws.mon_shootable[m]) == bool(ws.mon_active[m] and ws.mon_health[m] > 0), m
            assert 0 <= ws.mon_target[m] <= n + 1 and ws.mon_target[m] != 2 + m
        assert all(0 <= v <= n + 1 for v in ws.bar_src)
    assert tot["retargets"] and tot["mon_hits"], tot
