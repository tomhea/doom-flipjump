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
    assert len(gd.STATES) <= 255                   # a state cell is one byte
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
    assert all(m[t].height == 56 * F for t in gd.MONSTER_DOOMEDNUMS.values())
    assert m["MT_TROOP"].meleestate == m["MT_TROOP"].missilestate == "S_TROO_ATK1"
    assert m["MT_POSSESSED"].meleestate == gd.S_NULL and m["MT_SERGEANT"].missilestate == gd.S_NULL
    assert [m[t].reactiontime for t in gd.MONSTER_DOOMEDNUMS.values()] == [8] * 5
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
