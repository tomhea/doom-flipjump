"""M8 C11 (E1M7): `teleport.check_one_per_move` -- the proof that both mirrors' ONE teleport a move (the first front
crossing in line order: combat._teleport_player, world._teleport_monster, teleportcode) is DOOM's, and that a mover
never stomps itself -- tested only against the lines that can share a move's spechit.

E1M7's two-way pair (lines 516 and 521, special 97) puts each destination 32 units in front of the OTHER line, ~840
units away: no move that crosses one can touch the other, but the old rule tested every destination against every
line and refused the map. A line u can fire in the move that crossed t only if u's segment is within REACH_MAX of the
new centre, itself within 2 * REACH_MAX of t's segment: a gap (`segment_gap`) above SELF_MARGIN (4 * REACH_MAX)
rules u out. The self half (u = t) is unchanged.

R9: the same pair moved within SELF_MARGIN of each other is refused; a destination near its OWN line is refused at
any distance from the others.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from doomfj.teleport import SELF_MARGIN, Teleporter, check_one_per_move, segment_gap, teleporters
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FULL_WAD = ROOT / "assets/freedoom1.wad"


def _tel(line, axis, coord, lo, hi, dest):
    return Teleporter(line=line, tag=line, axis=axis, coord=coord, lo=lo, hi=hi, front_le=True, dest=dest, angle=0,
                      dest_leaf=0, dest_sector=0, dest_floor=0)


# E1M7's pair, as its WAD has it: 516 (y = 448, x 2240..2304) -> (1568, 1312); 521 (y = 1280, x 1536..1600) -> (2272, 480)
PAIR = [_tel(516, "y", 448, 2240, 2304, (1568, 1312)), _tel(521, "y", 1280, 1536, 1600, (2272, 480))]


def test_segment_gap():
    a = _tel(1, "x", 0, 0, 64, (0, 0))
    assert segment_gap(a, a) == 0
    assert segment_gap(a, _tel(2, "y", 100, -10, 10, (0, 0))) == 36          # y: 100 - 64
    assert segment_gap(a, _tel(3, "x", 50, 200, 300, (0, 0))) == 136         # max(50, 200 - 64)
    assert segment_gap(_tel(4, "x", 50, 200, 300, (0, 0)), a) == 136         # symmetric
    assert segment_gap(a, _tel(5, "y", 32, -100, 100, (0, 0))) == 0          # crossing boxes


def test_e1m7_pair_is_admitted():
    assert segment_gap(*PAIR) > SELF_MARGIN
    check_one_per_move(PAIR)


def test_control_the_pair_near_each_other_is_refused():
    """R9: line 516 moved next to 521 (its segment 100 units below 521's, within SELF_MARGIN; its destination 132
    units from its own line): 516's destination, 32 units in front of 521, is in a move's reach again -- refused"""
    near = [replace(PAIR[0], coord=1280 - 100, lo=1536, hi=1600, dest=(1568, 1312)), PAIR[1]]
    assert segment_gap(*near) <= SELF_MARGIN
    with pytest.raises(AssertionError, match="within line 521's reach"):
        check_one_per_move(near)


def test_control_a_destination_near_its_own_line_is_refused():
    """R9: the self-stomp half is whole -- a destination 32 units from its OWN line, alone on the map"""
    with pytest.raises(AssertionError, match="line 516's destination"):
        check_one_per_move([replace(PAIR[0], dest=(2272, 480))])


@pytest.mark.skipif(not FULL_WAD.exists(), reason="the full episode wad is not present")
@pytest.mark.parametrize("m", ["E1M2", "E1M7"])
def test_the_maps_teleporters_are_admitted(m):
    """E1M2 (admitted before: the rule only relaxed) and E1M7 (refused before) build their teleporters"""
    tels = teleporters(WadFile.from_path(str(FULL_WAD)), m)
    assert tels
    check_one_per_move(tels)
    if m == "E1M7":
        assert {t.line for t in tels} >= {516, 521}
