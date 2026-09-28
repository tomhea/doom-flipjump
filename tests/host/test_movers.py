"""M7 P2b L0 -- the movers' rules (doomfj.movers, docs/gp-lift-spike.md): E1M1's two lifts and its
floor switch as the WAD and DOOM's rules make them, the lift's cycle in frames (D-L1: 9 down, 26
waiting, 9 up), a trigger taken only at rest, the triggers' geometry and the height override."""
import pytest

from doomfj import doors as D
from doomfj import movers as MV
from doomfj.wad import WadFile

FIX = "tests/fixtures/freedoom_e1m1.wad"


@pytest.fixture(scope="module")
def m():
    mw = WadFile.from_path(FIX)
    return mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.vertexes("E1M1")


def test_the_lifts_are_98_and_103(m):
    secs, lds, sds, _v = m
    assert MV.lift_sectors(secs, lds, sds) == {98: (-124, 12), 103: (8, 136)}


def test_a_lift_has_ten_stops_from_its_stored_floor_down(m):
    secs, lds, sds, _v = m
    st = MV.lift_states(secs, lds, sds)
    assert st[98] == [12, 0, -16, -32, -48, -64, -80, -96, -112, -124]
    assert st[103] == [136, 128, 112, 96, 80, 64, 48, 32, 16, 8]


def test_the_floor_switch_lowers_three_pillars_to_the_lowest_neighbour(m):
    secs, lds, sds, _v = m
    # 129's lowest neighbour is sector 101's floor 8 (the spike's 18 states at quant 16)
    assert MV.switch_sectors(secs, lds, sds) == {76: (136, 272), 126: (144, 264), 129: (8, 264)}
    assert all(secs[si].floor_h == secs[si].ceil_h for si in (76, 126, 129))   # shut until lowered


def test_no_mover_is_a_door(m):
    secs, lds, sds, _v = m
    doors = set(D.door_sectors(secs, lds, sds))
    assert not doors & (set(MV.lift_sectors(secs, lds, sds)) | set(MV.switch_sectors(secs, lds, sds)))


def run(n, frames, trig_at=()):
    st, out = (0, D.IDLE, 0, 0), []
    for f in range(frames):
        st = MV.lift_tic(st, n, f in trig_at)
        out.append(st[0])
    return out


def test_the_lift_cycle_is_9_down_26_waiting_9_up():
    """frames 0-8 step down (the trigger frame too); the bottom holds on the arrival frame and
    LIFT_WAIT more (the last one turns it round, as a door's wait does); 9 frames up; it stays"""
    tr = run(10, 60, trig_at={0})
    w = MV.LIFT_WAIT
    assert tr[:9] == list(range(1, 10))
    assert tr[8:9 + w] == [9] * (w + 1)
    assert tr[9 + w:18 + w] == list(range(8, -1, -1))
    assert tr[18 + w:] == [0] * (60 - 18 - w)


def test_a_trigger_on_a_moving_or_waiting_lift_is_ignored():
    once = run(10, 60, trig_at={0})
    assert run(10, 60, trig_at={0, 3, 12, 20, 38, 40}) == once


def test_a_trigger_at_rest_after_the_cycle_starts_another():
    once = run(10, 60, trig_at={0})
    back = once.index(0)
    again = run(10, 60 + back + 1, trig_at={0, back + 1})
    assert again[back + 1:back + 10] == list(range(1, 10))


def test_the_door_tic_is_unchanged_by_its_wait_parameter():
    for used in (False, True):
        st = (3, D.OPENING, 1, 0)
        assert D.door_tic(st, 9, used) == D.door_tic(st, 9, used, wait_frames=D.WAIT)


def test_the_lift_walk_triggers_are_the_wr_lines(m):
    secs, lds, sds, verts = m
    trig = MV.lift_walk_triggers(secs, lds, sds, verts)
    assert trig == [(98, "y", 320, 64, 192), (98, "y", 192, 64, 192), (98, "x", 64, 192, 320),
                    (103, "y", -384, 1272, 1584), (103, "x", 1584, -504, -384)]


def test_the_use_lines_are_the_sr_lifts_and_the_switch(m):
    secs, lds, _sds, verts = m
    sr = MV.use_line_boxes(secs, lds, verts, MV.LIFT_USE_SPECIALS)
    assert [t for t, _b in sr] == [1, 2, 2, 2]          # 594; 620, 1064, 1075
    assert (1, (192 - 64, 192 - 64, 192 + 64, 320 + 64)) in sr
    sw = MV.use_line_boxes(secs, lds, verts, MV.FLOOR_SWITCH_SPECIALS)
    assert sw == [(3, (2048 - 64, -221 - 64, 2080 + 64, -221 + 64))]


def test_the_height_override_holds_only_movers_off_their_stored_floor(m):
    secs, lds, sds, _v = m
    ls = MV.lift_states(secs, lds, sds)
    sw = MV.switch_sectors(secs, lds, sds)
    assert MV.mover_heights(secs, ls, {98: 0, 103: 0}, sw, False) == {}
    h = MV.mover_heights(secs, ls, {98: 9, 103: 1}, sw, True)
    assert h == {98: (-124, 128), 103: (128, 264), 76: (136, 272), 126: (144, 264), 129: (8, 264)}


# ---- door reversal on things (docs/gp-lift-spike.md section 4) -----------------------------------

def test_a_blocked_closing_door_reverses_at_its_pass_step_without_moving():
    # a 9-state door closing at its pass state 4
    st = (4, D.CLOSING, 1, 0)
    assert D.door_tic(st, 9, False, blocked=True, pass_at=4) == (4, D.OPENING, D.SPEED, 0)
    assert D.door_tic(st, 9, False, blocked=False, pass_at=4)[0] == 3


def test_reversal_is_asked_only_across_the_pass_step():
    for state in (8, 6, 5):                              # above: it steps down as ever
        assert D.door_tic((state, D.CLOSING, 1, 0), 9, False, blocked=True, pass_at=4)[0] == state - 1
    assert D.door_tic((3, D.CLOSING, 1, 0), 9, False, blocked=True, pass_at=4)[0] == 2   # below


def test_a_blazing_door_reverses_when_its_stride_would_cross_the_pass_state():
    st = (4, D.CLOSING, 1, 0)                            # 5 states, stride 4: 4 -> 0 crosses pass 2
    assert D.door_tic(st, 5, False, stride=4, blocked=True, pass_at=2) == (4, D.OPENING, D.SPEED, 0)
    assert D.door_tic(st, 5, False, stride=4, blocked=False, pass_at=2)[0] == 0
