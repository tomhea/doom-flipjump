"""S3a: DOOM's engine data (`doomfj.gamedata`) -- a closed state graph with known actions, and the
handful of facts the model's behaviour hangs on, pinned so an accidental edit shows up here."""
import dataclasses

import pytest

from doomfj import gamedata as gd
from doomfj.config import DEFAULT_MAP_WAD
from doomfj.wad import WadFile


def test_the_state_graph_is_closed_and_every_action_is_known():
    assert gd.check_integrity() == []
    assert gd.STATE_NAMES[0] == gd.S_NULL and gd.STATE_INDEX[gd.S_NULL] == 0
    assert len(gd.STATE_NAMES) <= 255              # a state cell is one byte (M8 C8: the core index)
    # M8 C8: the extension states have a THING-domain index, one byte too, borrowed from weapon-only states
    assert set(gd.STATES) == set(gd.STATE_NAMES) | set(gd.EXT_STATE_NAMES)
    assert max(gd.THING_STATE_INDEX.values()) < 256 and gd.check_thing_aliases() == []
    for st in gd.STATES.values():
        assert st.action is None or st.action in gd.ACTIONS


def _mutated(states=None, infos=None, weapons=None):
    return gd.check_integrity(states or dict(gd.STATES), infos or dict(gd.MOBJINFO),
                              weapons or dict(gd.WEAPONINFO))


@pytest.mark.parametrize("what", ["dangling next", "unknown action", "wrong domain",
                                  "tics too long", "orphan state"])
def test_every_state_defect_is_reported(what):
    """R9: each defect class the checker claims to catch, planted once."""
    s = dict(gd.STATES)
    if what == "dangling next":
        s["S_POSS_RUN8"] = dataclasses.replace(s["S_POSS_RUN8"], next="S_POSS_RUN9")
    elif what == "unknown action":
        s["S_TROO_ATK3"] = dataclasses.replace(s["S_TROO_ATK3"], action="A_TroopAtack")
    elif what == "wrong domain":
        s["S_POSS_ATK2"] = dataclasses.replace(s["S_POSS_ATK2"], action="A_FirePistol")
    elif what == "tics too long":
        s["S_PLAY_ATK1"] = dataclasses.replace(s["S_PLAY_ATK1"], tics=gd.MAX_FINITE_TICS + 1)
    elif what == "orphan state":
        s["S_ORPHAN"] = gd.State("S_ORPHAN", "TROO", 0, 4, None, "S_ORPHAN")
    assert _mutated(states=s), what


def test_a_missing_entry_point_is_reported():
    infos = dict(gd.MOBJINFO)
    infos["MT_SERGEANT"] = dataclasses.replace(infos["MT_SERGEANT"], meleestate="S_SARG_ATK0")
    assert any("MT_SERGEANT" in line for line in _mutated(infos=infos))
    weapons = dict(gd.WEAPONINFO)
    weapons[gd.WP_PISTOL] = dataclasses.replace(weapons[gd.WP_PISTOL], flashstate="S_PISTOLFLASH2")
    assert any("pistol" in line for line in _mutated(weapons=weapons))


def test_the_facts_the_model_leans_on():
    F = gd.FRACUNIT
    m = gd.MOBJINFO
    assert (m["MT_POSSESSED"].speed, m["MT_SERGEANT"].speed, m["MT_SHADOWS"].speed) == (8, 10, 10)
    assert m["MT_SERGEANT"].radius == 30 * F and m["MT_TROOP"].radius == 20 * F
    core = [t for t in gd.MONSTER_DOOMEDNUMS.values() if t not in gd.EXT_MONSTER_TYPES]
    assert all(m[t].height == 56 * F for t in core)
    assert m["MT_TROOP"].meleestate == m["MT_TROOP"].missilestate == "S_TROO_ATK1"
    assert m["MT_POSSESSED"].meleestate == gd.S_NULL and m["MT_SERGEANT"].missilestate == gd.S_NULL
    assert [m[t].reactiontime for t in gd.MONSTER_DOOMEDNUMS.values()] == [8] * len(gd.MONSTER_DOOMEDNUMS)
    assert m["MT_TROOPSHOT"].speed == 10 * F and m["MT_TROOPSHOT"].damage == 3
    assert m["MT_BARREL"].spawnhealth == 20 and m["MT_SHADOWS"].flags & gd.MF_SHADOW
    assert [gd.STATES["S_%s_RUN1" % p].tics for p in ("POSS", "SPOS", "TROO", "SARG")] == [4, 3, 3, 2]
    assert gd.STATES["S_BEXP4"].action == "A_Explode"
    assert gd.WEAPONINFO[gd.WP_SHOTGUN].ammo == gd.AM_SHELL and gd.MAXAMMO == (200, 50, 300, 50)
    assert gd.XSPEED[gd.DI_NORTHEAST] == gd.YSPEED[gd.DI_NORTHEAST] == 47000
    assert [gd.OPPOSITE[d] for d in range(8)] == [4, 5, 6, 7, 0, 1, 2, 3]


def test_every_e1m1_thing_type_is_known_and_the_skill_counts_are_the_owners():
    """D7: easy 17, medium 29, hard 46 monsters -- counted with P_SpawnMapThing's own bit rule."""
    things = WadFile.from_path(DEFAULT_MAP_WAD).things("E1M1")
    single = [t for t in things if t.type not in gd.NOT_THINGS and not t.flags & gd.MTF_NOTSINGLE]
    assert {t.type for t in single} <= set(gd.THING_TYPES)
    counts = [sum(1 for t in single if t.type in gd.MONSTER_DOOMEDNUMS
                  and t.flags & gd.skill_bit(sk))
              for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)]
    assert counts == [17, 29, 46]
    assert (gd.skill_bit(gd.SK_BABY), gd.skill_bit(gd.SK_NIGHTMARE)) == (1, 4)


def test_the_baron_is_info_c():
    """M8 C8: MT_BRUISER and MT_BRUISERSHOT as info.c has them (raisestate the recorded deviation: S_NULL), the two
    actions p_enemy.c gives the Baron, and A_BossDeath on E1M8's tag 666"""
    F = gd.FRACUNIT
    b, s = gd.MOBJINFO["MT_BRUISER"], gd.MOBJINFO["MT_BRUISERSHOT"]
    assert (b.doomednum, b.spawnhealth, b.painchance, b.speed, b.radius, b.height, b.mass, b.reactiontime) == (
        3003, 1000, 50, 8, 24 * F, 64 * F, 1000, 8)
    assert b.meleestate == b.missilestate == "S_BOSS_ATK1" and b.xdeathstate == gd.S_NULL
    assert b.raisestate == gd.S_NULL and b.flags == gd.MF_SOLID | gd.MF_SHOOTABLE | gd.MF_COUNTKILL
    assert (s.speed, s.radius, s.height, s.damage, s.spawnstate, s.deathstate) == (
        15 * F, 6 * F, 8 * F, 8, "S_BRBALL1", "S_BRBALLX1")
    assert gd.STATES["S_BOSS_ATK3"].action == "A_BruisAttack" and gd.STATES["S_BOSS_DIE7"].action == "A_BossDeath"
    assert gd.STATES["S_BOSS_DIE7"].tics == -1 and gd.STATES["S_BOSS_DIE4"].action == "A_Fall"
    assert [gd.STATES[x].tics for x in ("S_BOSS_STND", "S_BOSS_RUN1", "S_BOSS_ATK1", "S_BOSS_PAIN", "S_BOSS_DIE1",
                                         "S_BRBALL1", "S_BRBALLX1")] == [10, 3, 8, 2, 8, 4, 6]
    assert gd.ACTIONS["A_BruisAttack"].cls == "heavy" and gd.ACTIONS["A_BossDeath"].cls == "cheap"
    assert gd.MONSTER_DOOMEDNUMS[3003] == "MT_BRUISER" and gd.THING_TYPES[3003].radius == 24
    assert gd.MISSILE_OF["MT_BRUISER"] == "MT_BRUISERSHOT"
    assert gd.BOSS_MAPS == {"E1M8": ("MT_BRUISER", 666, "lowest")}
    # E1M1's state cells keep their meaning: every core state's thing index is its compact index
    assert all(gd.THING_STATE_INDEX[n] == i for i, n in enumerate(gd.STATE_NAMES)
               if not gd.EXT_ALIAS_BASE <= i < gd.EXT_ALIAS_BASE + len(gd.EXT_STATE_NAMES))


@pytest.mark.parametrize("base", [0, 39, 46, 51, 230])
def test_control_a_borrowed_index_a_thing_holds_is_refused(base):
    """R9: the alias run moved onto S_NULL (0), the blood (39), the imp's fireball (46), the player thing (51) and past
    the core count (230 + 27) -- each a thing cell's own meaning -- must be refused"""
    assert gd.check_thing_aliases(alias_base=base), base
