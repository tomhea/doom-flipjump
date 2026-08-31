"""`doomfj.doors` — the door model, which BOTH mirrors now go through.

It is one small module, and every one of these tests exists because the property it pins has
already been got wrong once in this repo:

  * a "door" that is really a LIFT — the first door gate swept floor -> the wad's ceiling, which is
    zero movement for a stored-shut door, and proudly reported 1,451 px that came from a lift;
  * a quantised height BELOW its own floor — flooring to a multiple of the quantum when the floor
    is not one (floor -128 at quant 24 -> -144);
  * a door that can never fully OPEN — flooring alone never reaches an `open_h` that is not a
    multiple of the quantum, and no E1M1 door opens to one;
  * a `frac=0` override that is not a no-op — which would move every existing golden.
"""
from pathlib import Path

import pytest

from doomfj.doors import (DEFAULT_QUANT, MAX_STATES, OPEN_GAP, door_sectors, door_states,
                          heights_at, neighbours, quantise, stops)
from doomfj.reference_model import apply_sector_heights
from doomfj.wad import WadFile

MAP = "E1M1"


@pytest.fixture(scope="module")
def level():
    wad = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
    return wad.sectors(MAP), wad.linedefs(MAP), wad.sidedefs(MAP)


# -- what counts as a door ----------------------------------------------------------------------

def test_every_door_is_stored_shut(level):
    """A door's sector has ceil_h == floor_h in the wad. Anything behind a special line that is
    already open is a lift or a trigger sector, and sweeping it is measuring the wrong thing."""
    secs, lds, sds = level
    doors = door_sectors(secs, lds, sds)
    assert doors, "no doors found at all"
    for si in doors:
        assert secs[si].ceil_h == secs[si].floor_h, (
            "sector %d is not stored shut (%d..%d) -- it is a lift, not a door"
            % (si, secs[si].floor_h, secs[si].ceil_h))


def test_a_lift_is_not_a_door(level):
    """The specific mistake: E1M1 has sectors behind special linedefs that are already open."""
    secs, lds, sds = level
    doors = door_sectors(secs, lds, sds)
    behind_special = {sds[ld.back].sector for ld in lds
                      if ld.special and ld.back != 0xFFFF and ld.back < len(sds)}
    excluded = behind_special - set(doors)
    assert excluded, "the map has no already-open special sectors, so this test proves nothing"
    for si in excluded:
        assert secs[si].ceil_h != secs[si].floor_h


def test_open_height_is_p_doorraise(level):
    """min(neighbouring sector ceiling) - 4, and the neighbour set is non-empty for every door."""
    secs, lds, sds = level
    nb = neighbours(lds, sds)
    for si, open_h in door_sectors(secs, lds, sds).items():
        assert nb[si], si
        assert open_h == min(secs[n].ceil_h for n in nb[si]) - OPEN_GAP


def test_every_door_actually_opens(level):
    """A door whose open height is at or below its floor would be a no-op dressed as a feature."""
    secs, lds, sds = level
    for si, open_h in door_sectors(secs, lds, sds).items():
        assert open_h > secs[si].floor_h, (si, secs[si].floor_h, open_h)


# -- the rounding rule --------------------------------------------------------------------------

@pytest.mark.parametrize("lo,open_h", [(-128, -4), (-128, -12), (0, 124), (144, 212), (0, 60)])
@pytest.mark.parametrize("quant", [8, 16, 24, 32, 64])
def test_quantise_never_leaves_the_sweep(lo, open_h, quant):
    for i in range(-3, 40):
        h = lo + i * (open_h - lo) / 32.0
        q = quantise(lo, open_h, h, quant)
        assert lo <= q <= open_h, (lo, open_h, quant, h, q)


@pytest.mark.parametrize("quant", [8, 16, 24, 32, 64])
def test_both_endpoints_are_exact(level, quant):
    """frac 1.0 must reach the REAL open height, not the largest multiple below it. No E1M1 door
    opens to a multiple of 16, so a floor-only rule leaves every door in the game short."""
    secs, lds, sds = level
    for si, open_h in door_sectors(secs, lds, sds).items():
        lo = secs[si].floor_h
        assert quantise(lo, open_h, open_h, quant) == open_h
        assert quantise(lo, open_h, lo, quant) == lo


def test_the_endpoint_is_not_free_of_charge(level):
    """The control for the test above: on this map the exact endpoint is NOT what flooring gives,
    so `== open_h` is a real requirement rather than a coincidence."""
    secs, lds, sds = level
    floored_short = 0
    for si, open_h in door_sectors(secs, lds, sds).items():
        if (open_h // DEFAULT_QUANT) * DEFAULT_QUANT != open_h:
            floored_short += 1
    assert floored_short == len(door_sectors(secs, lds, sds)), floored_short


@pytest.mark.parametrize("quant", [8, 16, 24, 32, 64])
def test_quantise_is_monotone(level, quant):
    """A door must not move backwards as its animation advances."""
    secs, lds, sds = level
    for si, open_h in door_sectors(secs, lds, sds).items():
        lo = secs[si].floor_h
        seen = [quantise(lo, open_h, lo + (open_h - lo) * (i / 64.0), quant) for i in range(65)]
        assert seen == sorted(seen), (si, quant, seen)


@pytest.mark.parametrize("quant", [8, 16, 24, 32, 64])
def test_stops_are_the_reachable_heights(level, quant):
    """`stops` must be exactly the set `quantise` can produce -- the budget tools count states
    with `stops` and the gate produces them with `quantise`, so a disagreement would price a
    door wrongly (it did: an earlier copy counted a fully-open stop the gate could not reach)."""
    secs, lds, sds = level
    for si, open_h in door_sectors(secs, lds, sds).items():
        lo = secs[si].floor_h
        st = stops(lo, open_h, quant)
        assert st[0] == lo and st[-1] == open_h
        assert st == sorted(set(st)), st
        reachable = {quantise(lo, open_h, lo + (open_h - lo) * (i / 512.0), quant)
                     for i in range(513)}
        assert reachable <= set(st), sorted(reachable - set(st))


# -- the override ------------------------------------------------------------------------------

def test_frac_zero_is_a_no_op(level):
    """THE property that keeps every existing golden valid: a door at frac 0 IS the wad's stored
    state, so applying the override must change nothing at all."""
    secs, lds, sds = level
    assert apply_sector_heights(secs, heights_at(secs, lds, sds, 0.0)) == list(secs)


def test_no_override_returns_the_list_untouched(level):
    secs, _lds, _sds = level
    assert apply_sector_heights(secs, None) is secs
    assert apply_sector_heights(secs, {}) is secs


def test_the_override_moves_only_ceilings_of_doors(level):
    secs, lds, sds = level
    doors = door_sectors(secs, lds, sds)
    moved = apply_sector_heights(secs, heights_at(secs, lds, sds, 1.0))
    for i, (before, after) in enumerate(zip(secs, moved)):
        if i in doors:
            assert after.ceil_h == doors[i] and after.floor_h == before.floor_h
            assert after.light == before.light and after.ceil_tex == before.ceil_tex
        else:
            assert after == before, "sector %d moved and is not a door" % i


# -- M4: the nine-map facts ----------------------------------------------------------------------
# `door_sectors` used to accept any sector behind a special linedef whose ceiling sits on its floor.
# On five of the nine E1 maps that admits a sector whose min(neighbouring ceiling) - 4 is BELOW its
# own floor, i.e. a "door" that opens downward through the floor -- and `stops` returns a SORTED
# list, so the two ends swapped and `door_states` threw. These pin the fix AND its E1M1 neutrality.

FULL_WAD = Path("assets/freedoom1.wad")
E1 = ["E1M%d" % i for i in range(1, 10)]


@pytest.fixture(scope="module")
def full():
    if not FULL_WAD.exists():
        pytest.skip("the full episode wad is not present")
    return WadFile.from_path(str(FULL_WAD))


def test_door_states_works_on_every_e1_map(full):
    """The regression this fix exists for: five of nine used to raise."""
    for m in E1:
        secs, lds, sds = full.sectors(m), full.linedefs(m), full.sidedefs(m)
        tbl = door_states(secs, lds, sds)                  # must not raise
        for si, st in tbl.items():
            assert st[0] == secs[si].floor_h, (m, si, st)
            assert st[-1] == door_sectors(secs, lds, sds)[si], (m, si, st)
            assert len(st) <= MAX_STATES, (m, si, st)


def test_the_excluded_sectors_are_exactly_the_downward_ones(full):
    """A door is dropped for ONE reason and it is checkable: its open height is below its floor.
    Anything else leaving the dict is a different bug wearing this fix's clothes."""
    for m in E1:
        secs, lds, sds = full.sectors(m), full.linedefs(m), full.sidedefs(m)
        nb = neighbours(lds, sds)
        kept = door_sectors(secs, lds, sds)
        for ld in lds:
            if not ld.special or ld.back == 0xFFFF or ld.back >= len(sds):
                continue
            si = sds[ld.back].sector
            s = secs[si]
            if s.ceil_h != s.floor_h or not nb.get(si):
                continue
            open_h = min(secs[n].ceil_h for n in nb[si]) - OPEN_GAP
            assert (si in kept) == (open_h >= s.floor_h), (m, si, s.floor_h, open_h)


def test_e1m1_and_e1m2_lose_no_door(full):
    """THE byte-exactness argument. The shipped build is E1M1; if the filter removed one of its 13
    doors the picture would move, so this is the pin that says it cannot."""
    for m, n in (("E1M1", 13), ("E1M2", 8)):
        secs, lds, sds = full.sectors(m), full.linedefs(m), full.sidedefs(m)
        assert len(door_sectors(secs, lds, sds)) == n
        assert all(door_sectors(secs, lds, sds)[si] > secs[si].floor_h
                   for si in door_sectors(secs, lds, sds))


def test_the_filter_has_teeth(full):
    """A negative control (R9): the maps it fires on, and the sectors it drops, are named. If a
    later change makes this list empty the test above stops proving anything."""
    dropped = {}
    for m in E1:
        secs, lds, sds = full.sectors(m), full.linedefs(m), full.sidedefs(m)
        nb = neighbours(lds, sds)
        n = 0
        for ld in lds:
            if not ld.special or ld.back == 0xFFFF or ld.back >= len(sds):
                continue
            si = sds[ld.back].sector
            s = secs[si]
            if s.ceil_h == s.floor_h and nb.get(si) and (
                    min(secs[k].ceil_h for k in nb[si]) - OPEN_GAP) < s.floor_h:
                n += 1
        if n:
            dropped[m] = len({si for si in ()} ) or n
    assert set(dropped) == {"E1M3", "E1M4", "E1M5", "E1M6", "E1M7", "E1M9"}
