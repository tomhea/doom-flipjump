"""M7 P5 (host) -- the model side of the monsters' attacks (docs/gp-p5-interface.md):

  * combat.palette_index IS st_stuff.c's ST_doPaletteStuff: held to a line-by-line transcription of the C over a grid
    of (damagecount, bonuscount, pw_strength), with spot values; R9: two mutants (no +7 rounding, no berserk fade)
    must part from the transcription on the grid;
  * THE DEATH MOMENT (P_DamageMobj -> P_KillMobj on the player): p_dead, the weapon's downstate, the death (or gib)
    state, exactly ONE rng_player draw (the tics roll; no pain roll), nothing more for a dead player; and the AI's
    TARGET LOSS (A_Chase: the threshold clears, P_LookForPlayers fails on a dead player, the spawn state);
  * monsters.MonsterPhase in P5's modes: `weapon` fades the damage / bonus flash after the psprites (and a dead
    player only lowers), `tic` runs the fireballs, barrels and effects after the monsters (world.tic's order), and
    `state` / `MonsterViews.rt_state` carry P5's cells in their documented units.
"""
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src")]

from doomfj import gamedata as gd                                            # noqa: E402
from doomfj import rng as R                                                  # noqa: E402
from doomfj.combat import palette_index                                      # noqa: E402
from doomfj.world import KEYS, TicEvents, World                              # noqa: E402

ART = ROOT / "assets/freedoom1.wad"


# ---------------------------------------------------------------------------------------------- the palette
def st_do_palette_stuff(damagecount, bonuscount, strength):
    """st_stuff.c ST_doPaletteStuff (Chocolate Doom), line by line, for the single player (no radiation suit)"""
    NUMREDPALS, STARTREDPALS, NUMBONUSPALS, STARTBONUSPALS = 8, 1, 4, 9
    cnt = damagecount
    if strength:
        bzc = 12 - (strength >> 6)                    # slowly fade the berzerk out
        if bzc > cnt:
            cnt = bzc
    if cnt:
        palette = (cnt + 7) >> 3
        if palette >= NUMREDPALS:
            palette = NUMREDPALS - 1
        palette += STARTREDPALS
    elif bonuscount:
        palette = (bonuscount + 7) >> 3
        if palette >= NUMBONUSPALS:
            palette = NUMBONUSPALS - 1
        palette += STARTBONUSPALS
    else:
        palette = 0
    return palette


GRID = [(dc, bc, st) for dc in (0, 1, 2, 7, 8, 9, 15, 16, 17, 24, 25, 33, 40, 41, 48, 49, 55, 56, 57, 100)
        for bc in (0, 1, 6, 8, 9, 24, 25, 40) for st in (0, 1, 63, 64, 191, 700, 767, 768, 5000, 0xFFFF)]


def _ws(dc, bc, st):
    return types.SimpleNamespace(p_damagecount=dc, p_bonuscount=bc, p_strength=st)


def test_palette_index_is_st_do_palette_stuff():
    bad = [(g, palette_index(_ws(*g)), st_do_palette_stuff(*g)) for g in GRID
           if palette_index(_ws(*g)) != st_do_palette_stuff(*g)]
    assert not bad, bad[:8]
    # every palette the rule can pick: 1 and 9 never (a count >= 1 rounds up to >= 1, so the base is never shown)
    assert {st_do_palette_stuff(*g) for g in GRID} == set(range(13)) - {1, 9}, "the grid reaches every palette"


@pytest.mark.parametrize("dc, bc, st, want", [(0, 0, 0, 0), (1, 0, 0, 2), (8, 0, 0, 2), (9, 0, 0, 3), (56, 0, 0, 8),
                                              (100, 0, 0, 8), (0, 6, 0, 10), (0, 40, 0, 12), (0, 0, 1, 3),
                                              (0, 0, 768, 0), (0, 6, 768, 10), (0, 0, 700, 2), (30, 0, 1, 5)])
def test_palette_index_spot_values(dc, bc, st, want):
    assert palette_index(_ws(dc, bc, st)) == want


def test_the_control_palette_mutants_part():
    """R9: the grid tells the rule from its two near misses"""
    def no_round(ws):
        cnt = ws.p_damagecount
        return min(7, cnt >> 3) + 1 if cnt else palette_index(ws)

    def no_berserk(ws):
        return palette_index(types.SimpleNamespace(p_damagecount=ws.p_damagecount, p_bonuscount=ws.p_bonuscount,
                                                   p_strength=0))
    for mutant in (no_round, no_berserk):
        assert any(mutant(_ws(*g)) != st_do_palette_stuff(*g) for g in GRID), mutant.__name__


# ---------------------------------------------------------------------------------------------- the death moment
def _world():
    return World(monster_tics=1, skill=gd.SK_HARD, monsters="full", player="fx")


@pytest.mark.parametrize("dmg, gib", [(10, False), (150, True)])
def test_the_death_moment(dmg, gib):
    w = _world()
    ws = w.ws
    ws.p_health = 5
    r0, ready = ws.rng_player, ws.p_ready
    ev = TicEvents(0)
    w.damage_player(dmg, ("mon", 3), ("mon", 3), ev)
    assert ws.p_dead == 1 and ev.deaths == 1 and ws.p_health == 5 - dmg
    assert ws.rng_player == R.p_random(r0)[1], "the death draws exactly one roll on the player's stream (its tics)"
    assert gd.STATE_NAMES[ws.p_wpn_state] == gd.WEAPONINFO[ready].downstate, "P_DropWeapon: the downstate"
    first = gd.MOBJINFO["MT_PLAYER"].xdeathstate if gib else gd.MOBJINFO["MT_PLAYER"].deathstate
    assert gd.STATE_NAMES[ws.p_mobj_state] == first
    assert not w.player_alive()
    snap = ws.copy().as_dict()
    w.damage_player(dmg, ("mon", 3), ("mon", 3), TicEvents(0))       # a dead player is not shootable: nothing at all
    assert ws.as_dict() == snap


def test_a_dead_player_loses_the_chasers():
    """A_Chase on a dead target: the threshold clears, P_LookForPlayers fails, the monster goes back to its spawn
    state -- and a fireball no longer hits the player's box"""
    w = _world()
    ws = w.ws
    m = 3                                                 # an imp
    ws.mon_target[m], ws.mon_threshold[m], ws.mon_reaction[m] = 1, 50, 0
    ws.mon_state[m], ws.mon_tics[m] = gd.STATE_INDEX["S_TROO_RUN1"], 1
    w.damage_player(500, ("mon", m), ("mon", m), TicEvents(0))
    assert ws.p_dead
    w._monsters_phase(TicEvents(0))
    assert ws.mon_threshold[m] == 0
    assert gd.STATE_NAMES[ws.mon_state[m]] == w.mon_info[m].spawnstate


# ---------------------------------------------------------------------------------------------- MonsterPhase in P5
def _phase():
    from doomfj.monsters import MonsterPhase
    ph = MonsterPhase(mode="full", player="fx")
    ph.world.monster_tics = 1          # M7 P6+P7 E: these test one DOOM tic (test_monster_tempo: a frame of 2)
    return ph


def test_weapon_fades_the_flashes_after_the_psprites():
    ph = _phase()
    ws = ph.world.ws
    ws.p_damagecount, ws.p_bonuscount = 10, 3
    ph.weapon({})
    assert (ws.p_damagecount, ws.p_bonuscount) == (9, 2)
    ws.p_dead, ws.p_damagecount, ws.p_bonuscount = 1, 4, 4
    ph.weapon({k: True for k in KEYS})                    # dead: P_DeathThink's psprites -- no keys, no bonus fade
    assert (ws.p_damagecount, ws.p_bonuscount) == (3, 4)
    assert ws.p_pending == gd.WP_NOCHANGE                  # the number keys were not read


def test_tic_runs_the_pools_and_state_carries_their_cells():
    """an imp told to attack: its fireball spawns in the tic (the monsters' phase), and flies in the same tic's
    projectile phase -- in state()'s units"""
    from doomfj.world import FIREBALL_POOL, FX_POOL
    ph = _phase()
    ws = ph.world.ws
    m = 3
    ws.px, ws.py, ws.pangle = 848 << 16, 864 << 16, 0x40000000
    ws.mon_target[m] = 1
    ws.mon_state[m], ws.mon_tics[m] = gd.STATE_INDEX["S_TROO_ATK2"], 1
    ev = ph.tic()                                         # tics 1 -> 0: S_TROO_ATK3, A_TroopAttack now
    assert ev.proj_spawns and ph.last_tic is ev
    s = ev.proj_spawns[0][0]
    st = ph.state()
    assert st["pj_act"][s] == 1 and len(st["pj_act"]) == FIREBALL_POOL and len(st["fx_act"]) == FX_POOL
    assert st["pj_x"][s] == ws.proj_x[s] & 0xFFFFFFFF and st["pj_st"][s] == ws.proj_state[s]
    assert gd.STATE_NAMES[st["pj_st"][s]] == "S_TBALL1"
    assert st["p_hp"] == ws.p_health & 0xFFF and st["rng_fx"] == ws.rng_fx and st["p_dead"] == 0
    x0 = ws.proj_x[s]
    ph.tic()
    assert ws.proj_x[s] != x0 or ws.proj_y[s] != 0, "the fireball flies in MonsterPhase.tic"
    mob = ph.mobiles()
    assert mob and mob[0][:2] == (ws.proj_x[s] >> 16, ws.proj_y[s] >> 16) and mob[0][2].startswith("BAL1")


@pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad (the sprite art)")
def test_rt_state_mobile_rows():
    from doomfj.monsters import MonsterViews, mobile_rows
    from doomfj.wad import WadFile
    from doomfj.world import FIREBALL_POOL, FX_POOL
    ph = _phase()
    w, ws = ph.world, ph.world.ws
    mv = MonsterViews(w.rm, w.mw, w.mapname, WadFile.from_path(str(ART)), w)
    assert mobile_rows(w) == FIREBALL_POOL + FX_POOL == 10
    rt = mv.rt_state(ph)
    assert len(rt["thpos_rt"]) == mv.nrows(ph) == mv.nrt + 10
    assert rt["thpos_rt"][mv.nrt:] == (0,) * 10 and rt["thss_rt"][mv.nrt:] == (0,) * 10, "free rows are zero"
    m = 3
    ws.px, ws.py, ws.pangle = 848 << 16, 864 << 16, 0x40000000
    ws.mon_target[m] = 1
    w._set_state(m, "S_TROO_ATK3", True, TicEvents(0))   # A_TroopAttack now
    s = next(i for i in range(FIREBALL_POOL) if ws.proj_active[i])
    rt = mv.rt_state(ph)
    x, y = ws.proj_x[s] >> 16, ws.proj_y[s] >> 16
    assert rt["thpos_rt"][mv.nrt + s] == ((x << 16) & 0xFFFFFFFF) | (((y << 16) & 0xFFFFFFFF) << 32)
    assert rt["thss_rt"][mv.nrt + s] == ws.proj_leaf[s] == w.rm.point_in_subsector(w.cmap, x, y)
    from doomfj.monsters import MonsterPhase
    before = MonsterPhase(mode="decide", player="hit")    # P4.2b's modes: no pool, no rows
    assert mobile_rows(before.world) == 0 and len(mv.rt_state(before)["thpos_rt"]) == mv.nrt == mv.nrows(before)
