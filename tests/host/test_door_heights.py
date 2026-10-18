"""M8 (the E1M2 playtest, 2026-10-18): a door opens to DOOM's height -- P_FindLowestCeilingSurrounding over the
TWO-SIDED neighbours (getNextSector skips a line without a back), minus 4 -- on every map but the E1M1 family.

  * E1M2's five doors the legacy rule capped at 148 open to DOOM's 228 / 196 / 156 / 196 / 196, and blue door 54
    (floor 136) can now be passed: it opened 12 units, under the player's 56, so its pass state was unreachable;
  * the E1M1 family keeps its shipped stops (doors.LEGACY_NEIGHBOUR_MAPS: its one-byte pid budget, PR #103);
  * CONTROL: the legacy rule forced on E1M2 gives back the impassable door.
"""
from pathlib import Path

import pytest

import doomfj.doors as D
from doomfj.wad import WadFile

FIX = Path(__file__).resolve().parents[1] / "fixtures"
PLAYER_HEIGHT = 56


def _level(name, m):
    w = WadFile.from_path(FIX / name)
    return w.sectors(m), w.linedefs(m), w.sidedefs(m)


@pytest.fixture(scope="module")
def e1m2():
    return _level("freedoom_e1m2.wad", "E1M2")


def test_e1m2_doors_open_to_dooms_height(e1m2):
    secs, lds, sds = e1m2
    got = D.door_sectors(secs, lds, sds)
    assert {si: got[si] for si in (54, 258, 139, 30, 266)} == {54: 228, 258: 196, 139: 156, 30: 196, 266: 196}
    nb = D.two_sided_neighbours(lds, sds)
    for si, open_h in got.items():
        assert open_h == min(secs[n].ceil_h for n in nb[si]) - D.OPEN_GAP, si


def test_blue_door_54_can_be_passed(e1m2):
    secs, lds, sds = e1m2
    tbl = D.door_states(secs, lds, sds)
    assert tbl[54][-1] - secs[54].floor_h >= PLAYER_HEIGHT
    assert D.pass_state(secs, lds, sds, 54) < len(tbl[54])


def test_the_e1m1_family_keeps_its_stops():
    for name in ("freedoom_e1m1.wad", "e1m1_lite.wad"):
        secs, lds, sds = _level(name, "E1M1")
        assert (len(secs), len(lds), len(sds)) in D.LEGACY_NEIGHBOUR_MAPS
        assert D.door_neighbours(secs, lds, sds) == D.neighbours(lds, sds)
    secs, lds, sds = _level("freedoom_e1m1.wad", "E1M1")
    assert D.door_sectors(secs, lds, sds)[145] == 228          # DOOM's would be 260: frozen (PR #103)


def test_control_the_legacy_rule_on_e1m2_traps_the_player(e1m2, monkeypatch):
    secs, lds, sds = e1m2
    monkeypatch.setattr(D, "door_neighbours", lambda s, l_, d: D.neighbours(l_, d))
    tbl = D.door_states(secs, lds, sds)
    assert tbl[54][-1] == 148 and tbl[54][-1] - secs[54].floor_h < PLAYER_HEIGHT
    assert D.pass_state(secs, lds, sds, 54) >= len(tbl[54])     # never passable
