"""M8 (the E1M2 playtest, 2026-10-18): a door opens to DOOM's height -- P_FindLowestCeilingSurrounding over the
TWO-SIDED neighbours (getNextSector skips a line without ML_TWOSIDED or a back), minus 4 -- on every map but E1M1.

  * E1M2's five doors the legacy rule capped at 148 open to DOOM's 228 / 196 / 156 / 196 / 196, and blue door 54
    (floor 136) can now be passed: it opened 12 units, under the player's 56, so its pass state was unreachable;
  * E1M1 keeps its shipped stops (its one-byte pid budget, PR #103) -- #149: by its config.MAP_CONFIG flag
    DOOR_NEIGHBOURS "legacy", read for the map the sectors came from (wad.MapRecords), no longer by its record counts;
  * CONTROL: the legacy rule forced on E1M2 gives back the impassable door; E1M2's own records labelled E1M1 take
    it too (the NAME picks the rule, not the shape), and a list that does not know its map is refused;
  * #149: the two-sided rule tests ML_TWOSIDED as DOOM's getNextSector (and doomfj.lights) does -- the same
    neighbours as the back-side test alone on E1M1, E1M2 and (assets/freedoom1.wad present) all 36 Freedoom maps;
    CONTROL: a back side without the flag is no neighbour.
"""
from pathlib import Path

import pytest

import doomfj.doors as D
from doomfj.wad import Linedef, MapRecords, Sector, Sidedef, WadFile

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
    assert D.door_rule("E1M1") == D.door_rule("e1m1") == "legacy"
    assert {D.door_rule(m) for m in ("E1M2", "E1M3", "E2M1", "MAP01")} == {"two_sided"}     # the default
    for name in ("freedoom_e1m1.wad", "e1m1_lite.wad"):          # different counts, the same map: both legacy
        secs, lds, sds = _level(name, "E1M1")
        assert secs.mapname == "E1M1"
        assert D.door_neighbours(secs, lds, sds) == D.neighbours(lds, sds) != D.two_sided_neighbours(lds, sds)
    secs, lds, sds = _level("freedoom_e1m1.wad", "E1M1")
    assert D.door_sectors(secs, lds, sds)[145] == 228          # DOOM's would be 260: frozen (PR #103)


def test_control_the_legacy_rule_on_e1m2_traps_the_player(e1m2, monkeypatch):
    secs, lds, sds = e1m2
    monkeypatch.setattr(D, "door_neighbours", lambda s, l_, d: D.neighbours(l_, d))
    tbl = D.door_states(secs, lds, sds)
    assert tbl[54][-1] == 148 and tbl[54][-1] - secs[54].floor_h < PLAYER_HEIGHT
    assert D.pass_state(secs, lds, sds, 54) >= len(tbl[54])     # never passable


def _relabel(recs, mapname):
    out = MapRecords(recs)
    out.mapname = mapname
    return out


def test_control_the_map_name_picks_the_rule_not_its_counts(e1m2):
    """#149: E1M2's own records labelled E1M1 take E1M1's legacy rule (door 54 impassable again), and Freedoom E1M1's
    labelled as another map take DOOM's (walk-over door 145 opens to DOOM's 260, not the frozen 228)"""
    secs, lds, sds = e1m2
    as_e1m1 = _relabel(secs, "E1M1")
    assert D.door_neighbours(as_e1m1, lds, sds) == D.neighbours(lds, sds)
    assert D.door_states(as_e1m1, lds, sds)[54][-1] == 148
    s1, l1, d1 = _level("freedoom_e1m1.wad", "E1M1")
    assert D.door_sectors(_relabel(s1, "E1M3"), l1, d1)[145] == 260


def test_control_a_list_without_its_map_is_refused(e1m2):
    secs, lds, sds = e1m2
    with pytest.raises(AssertionError, match="per map"):
        D.door_neighbours(list(secs), lds, sds)
    with pytest.raises(AssertionError, match="per map"):
        D.door_sectors(secs[:], lds, sds)
    assert D.door_sectors([Sector(0, 128, "F", "C", 160, 0, 0)], [], []) == {}    # no door line: no rule asked


def _back_side_only(lds, sds):
    """the two-sided rule before #149: a back side, no flag test"""
    out: dict = {}
    for ld in lds:
        if ld.front in D.NO_SIDE or ld.back in D.NO_SIDE:
            continue
        f, b = sds[ld.front].sector, sds[ld.back].sector
        if f != b:
            out.setdefault(f, set()).add(b)
            out.setdefault(b, set()).add(f)
    return out


def test_two_sided_tests_the_flag_and_changes_no_shipped_map(e1m2):
    """#149: DOOM's getNextSector returns NULL for a line without ML_TWOSIDED (doomfj.lights tests it too). Adding the
    test moves no neighbour on E1M1 or E1M2: every line with a back side there carries the flag, and the reverse."""
    levels = [e1m2, _level("freedoom_e1m1.wad", "E1M1")]
    full = Path("assets/freedoom1.wad")                 # every Freedoom map, when the asset wad is here
    if full.exists():
        w = WadFile.from_path(full)
        levels += [(w.sectors(m), w.linedefs(m), w.sidedefs(m)) for m in w.names()
                   if len(m) == 4 and m[0] == "E" and m[2] == "M"]
        assert len(levels) == 2 + 36
    for secs, lds, sds in levels:
        assert all(bool(ld.back not in D.NO_SIDE) == bool(ld.flags & D.ML_TWOSIDED) for ld in lds)
        assert D.two_sided_neighbours(lds, sds) == _back_side_only(lds, sds)


def test_control_a_back_side_without_the_flag_is_no_neighbour():
    sds = [Sidedef(0, 0, "-", "-", "-", 0), Sidedef(0, 0, "-", "-", "-", 1)]
    flagged = [Linedef(0, 1, D.ML_TWOSIDED, 0, 0, 0, 1)]
    unflagged = [Linedef(0, 1, 0, 0, 0, 0, 1)]
    assert D.two_sided_neighbours(flagged, sds) == {0: {1}, 1: {0}}
    assert D.two_sided_neighbours(unflagged, sds) == {}
    assert _back_side_only(unflagged, sds) == {0: {1}, 1: {0}}       # the old test would have taken it
