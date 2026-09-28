"""M7 P2a.1 -- the door kinds E1M1 adds: the blazing door's stride, the walk-over doors (open once,
stay open, triggered by crossing their line), and the blue-card check. Every rule lives in
`doomfj.doors` once; the model, every gate oracle and the fj emitter take it from there."""
import pytest

from doomfj import doors as D
from doomfj.doors import CLOSING, IDLE, OPENING, SPEED, WAIT, door_tic
from doomfj.wad import WadFile

FIX = "tests/fixtures/freedoom_e1m1.wad"
PLAYER_R = 16


@pytest.fixture(scope="module")
def m():
    mw = WadFile.from_path(FIX)
    return (mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.vertexes("E1M1"))


# ---- the kinds ------------------------------------------------------------------------------------

def test_the_walkover_sectors_are_doors_now(m):
    secs, lds, sds, _v = m
    ds = D.door_sectors(secs, lds, sds)
    assert {77, 145} <= set(ds), sorted(ds)
    assert len(ds) == 15


def test_every_door_has_one_kind(m):
    secs, lds, sds, _v = m
    kinds = D.door_kinds(secs, lds, sds)
    assert set(kinds) == set(D.door_sectors(secs, lds, sds))
    assert {si for si, k in kinds.items() if k == "blue"} == {51, 71}
    assert {si for si, k in kinds.items() if k == "blaze"} == {84}
    assert {si for si, k in kinds.items() if k == "walkover"} == {77, 145}
    assert sum(k == "plain" for k in kinds.values()) == 10


def test_the_walkover_doors_have_no_use_box(m):
    secs, lds, sds, _v = m
    boxes = D.use_boxes(secs, lds, sds)
    assert 77 not in boxes and 145 not in boxes


# ---- the stride -----------------------------------------------------------------------------------

def run(tics, n, used_at=(), stride=1, stay=False):
    st, out = (0, IDLE, 0, 0), []
    for t in range(tics):
        st = door_tic(st, n, t in used_at, stride=stride, stay=stay)
        out.append(st[0])
    return out, st


def test_stride_1_is_todays_machine():
    for n in (2, 5, 9):
        for used in ((0,), (0, 20), (0, 3, 50)):
            a = run(120, n, used)
            st, b = (0, IDLE, 0, 0), []
            for t in range(120):
                st = door_tic(st, n, t in used)
                b.append(st[0])
            assert a[0] == b


def test_the_blazing_door_moves_BLAZE_STRIDE_stops_a_frame_and_clamps():
    assert D.BLAZE_STRIDE == 4
    seq, _ = run(3, 9, (0,), stride=D.BLAZE_STRIDE)
    assert seq[:3] == [4, 8, 8]                 # 0 -> 4 -> 8 (the top, clamped), then waits
    seq, _ = run(3, 5, (0,), stride=D.BLAZE_STRIDE)
    assert seq[0] == 4                          # 5 states: one frame to the top


def test_the_blazing_door_closes_BLAZE_STRIDE_stops_a_frame():
    seq, _ = run(1 + 1 + WAIT + 4, 9, (0,), stride=D.BLAZE_STRIDE)
    top = seq.index(8)
    close = seq[top:]
    # the top is held WAIT + 1 frames (the countdown, then the frame it turns to CLOSING), as a plain door's
    assert close[:WAIT + 1] == [8] * (WAIT + 1) and close[WAIT + 1:WAIT + 3] == [4, 0], close


# ---- the stay -------------------------------------------------------------------------------------

def test_a_stay_door_opens_and_never_closes():
    seq, st = run(500, 8, (0,), stay=True)
    assert seq[6] == 7 and set(seq[7:]) == {7} and st == (7, IDLE, SPEED, 0), (seq[:10], st)


def test_a_door_that_is_not_stay_closes_again():
    seq, _ = run(200, 8, (0,))
    assert seq[-1] == 0


def test_a_second_press_on_an_open_stay_door_changes_nothing():
    _, st = run(50, 8, (0,), stay=True)
    assert door_tic(st, 8, True, stay=True) == st


# ---- the walk-over trigger ------------------------------------------------------------------------

def test_one_trigger_per_tag_on_e1m1(m):
    secs, lds, sds, verts = m
    trig = D.walkover_triggers(secs, lds, sds, verts)
    assert trig == [(77, "y", 1472, 192, 512), (145, "x", 2032, -576, -256)], trig


def fx(v):
    return v << 16


@pytest.mark.parametrize("old, new, hit", [
    ((300, 1480), (300, 1466), True),          # north -> south across y = 1472
    ((300, 1466), (300, 1480), True),          # south -> north
    ((300, 1473), (300, 1472), True),          # ONTO the line: P_PointOnLineSide puts y == L below
    ((300, 1472), (300, 1471), False),         # on the line -> below: the same side
    ((300, 1480), (300, 1474), False),         # no crossing
    ((176 + 1, 1480), (176 + 1, 1466), True),  # the extent inflated by the radius, just inside
    ((176, 1480), (176, 1466), False),         # ... and exactly at lo - R: outside (strict)
    ((528 - 1, 1480), (528 - 1, 1466), True),
    ((528, 1480), (528, 1466), False),
])
def test_the_crossing_test_on_the_horizontal_trigger(old, new, hit):
    t = (77, "y", 1472, 192, 512)
    assert D.crossed(t, (fx(old[0]), fx(old[1])), (fx(new[0]), fx(new[1])), PLAYER_R) == hit


@pytest.mark.parametrize("old, new, hit", [
    ((2040, -400), (2028, -400), True),
    ((2028, -400), (2040, -400), True),
    ((2040, -400), (2033, -400), False),
    ((2040, -240 - 1), (2028, -240 - 1), True),
    ((2040, -240), (2028, -240), False),
])
def test_the_crossing_test_on_the_vertical_trigger(old, new, hit):
    t = (145, "x", 2032, -576, -256)
    assert D.crossed(t, (fx(old[0]), fx(old[1])), (fx(new[0]), fx(new[1])), PLAYER_R) == hit


def test_a_crossing_in_fractional_units_is_decided_in_16_16():
    t = (77, "y", 1472, 192, 512)
    L = fx(1472)
    assert D.crossed(t, (fx(300), L + 1), (fx(300), L), PLAYER_R)          # onto the line
    assert not D.crossed(t, (fx(300), L), (fx(300), L - 1), PLAYER_R)


# ---- the card check ---------------------------------------------------------------------------------

def test_the_blue_doors_need_the_blue_card(m):
    secs, lds, sds, _v = m
    kinds = D.door_kinds(secs, lds, sds)
    for si, k in kinds.items():
        assert D.can_open(k, has_blue=False) == (k not in ("blue", "walkover"))
        assert D.can_open(k, has_blue=True) == (k != "walkover")      # walk-over: never by use


# ---- the blue card in the gate oracles: DoorPhase.touch is the model's rule ---------------------------

def test_the_card_constants_are_the_models():
    from doomfj import combat as C
    assert D.CARD_BOX == C.ITEM_RADIUS + C.PLAYER_R
    assert (D.CARD_REACH_UP, D.CARD_REACH_DOWN) == (C.REACH_UP, C.REACH_DOWN)


def _boxes():
    from doomfj.mapcompiler import bake_bsp
    mw = WadFile.from_path(FIX)
    return D.use_boxes_xy(mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1"),
                          bake_bsp(mw, "E1M1").vertexes)


@pytest.fixture(scope="module")
def card_world():
    from doomfj import world as W
    w = W.World(strict=True)
    i = [k for k, t in enumerate(w.pickup_things) if t.type == 5]
    assert len(i) == 1
    return w, i[0]


def test_the_oracles_card_is_the_models(card_world):
    from doomfj.config import Config
    from doomfj.reference_model import ReferenceModel, build_scene
    w, i = card_world
    mw = WadFile.from_path(FIX)
    got = ReferenceModel(Config()).blue_card_at(build_scene(mw, mw, "E1M1"))
    t = w.pickup_things[i]
    assert got == (t.x, t.y, w.pickup_z[i]) == (2192, 576, 136)


def test_DoorPhase_touch_takes_the_card_exactly_when_the_model_does(m, card_world):
    """every probe from an untaken card: the edges of the box (strict) on both axes and the edges
    of the reach, against combat's `_touch_specials` on a fresh level start"""
    from doomfj import world as W
    w, i = card_world
    secs, lds, sds, verts = m
    kx, ky, kz = 2192, 576, 136
    dp = D.DoorPhase(secs, lds, sds, verts, _boxes(), card_at=(kx, ky, kz))
    bd = D.CARD_BOX
    probes = []
    for z in (kz - 57, kz - 56, kz - 55, kz, kz + 7, kz + 8, kz + 9, 24):
        for d in (-bd, -bd + 1, 0, bd - 1, bd):
            for f in (-1, 0, 1):
                probes += [(((kx + d) << 16) + f, ky << 16, z), (kx << 16, ((ky + d) << 16) + f, z)]
    start = w.ws.copy()
    taken = 0
    for x16, y16, z in probes:
        w.ws = start.copy()
        w._touch_specials(x16, y16, z, W.TicEvents(0))
        want = w.ws.pickup_taken[i]
        got = dp.touch(dp.initial(), x16, y16, z)[3]
        assert got == want, (x16 - (kx << 16), y16 - (ky << 16), z - kz)
        taken += want
    assert 0 < taken < len(probes)
    w.ws = start


def test_a_taken_card_stays_taken_and_opens_the_blue_door(m):
    secs, lds, sds, verts = m
    boxes = _boxes()
    dp = D.DoorPhase(secs, lds, sds, verts, boxes, card_at=(2192, 576, 136))
    blue = [si for si, k in D.door_kinds(secs, lds, sds).items() if k == "blue"]
    assert sorted(blue) == [51, 71]
    st0 = dp.initial()
    st1 = dp.touch(st0, 2192 << 16, 576 << 16, 136)
    assert st0[3] == 0 and st1[3] == 1 and dp.touch(st1, 0, 0, 0)[3] == 1
    for si in blue:
        x0, y0, x1, y1 = boxes[si]
        cx, cy = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
        assert dp.tic(st0, True, cx, cy)[0][si] == st0[0][si]           # no card: shut
        assert dp.tic(st1, True, cx, cy)[0][si][1] != 0                 # the card: it moves
