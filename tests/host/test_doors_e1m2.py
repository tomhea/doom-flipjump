"""M8 L2 -- every door kind E1M2 has, in the model (doomfj.doors, World._doors_phase): the classification by special
(p_doors.c EV_VerticalDoor / EV_DoDoor, p_spec.c P_CrossSpecialLine, p_switch.c P_UseSpecialLine), E1M1's
classification frozen, the key doors, the switches, the walk-over lines per line (multi-door tags, slanted lines)
and the slanted contact's box-fit guard. The fj mirror is tests/fj/test_doors_e1m2_fj.py."""
import random
from pathlib import Path

import pytest

from doomfj import doors as D
from doomfj import gamedata as gd
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

FIX = Path(__file__).resolve().parents[1] / "fixtures"
FULL = Path("assets/freedoom1.wad")


def _level(fix, m):
    mw = WadFile.from_path(FIX / fix)
    return mw, mw.sectors(m), mw.linedefs(m), mw.sidedefs(m), mw.vertexes(m)


@pytest.fixture(scope="module")
def e1m1():
    return _level("freedoom_e1m1.wad", "E1M1")


@pytest.fixture(scope="module")
def e1m2():
    return _level("freedoom_e1m2.wad", "E1M2")


# ---- E1M1: frozen (its doors' text is emitted from these) ------------------------------------------------------

def test_e1m1_classification_is_unchanged(e1m1):
    mw, secs, lds, sds, vs = e1m1
    assert list(D.door_sectors(secs, lds, sds).items()) == [
        (10, -4), (34, -4), (54, 212), (64, -60), (71, -4), (81, -4), (80, -4), (79, -4), (78, -4), (51, -4), (48, -12),
        (100, 124), (84, 60), (77, -68), (145, 228)]          # values AND order (the dict order E1M1 always had)
    kinds = D.door_kinds(secs, lds, sds)
    assert kinds == {10: "plain", 34: "plain", 48: "plain", 51: "blue", 54: "plain", 64: "plain", 71: "blue",
                     77: "walkover", 78: "plain", 79: "plain", 80: "plain", 81: "plain", 84: "blaze", 100: "plain",
                     145: "walkover"}
    assert D.walkover_triggers(secs, lds, sds, vs) == [(77, "y", 1472, 192, 512), (145, "x", 2032, -576, -256)]
    assert D.switch_door_triggers(secs, lds, sds, vs) == [] and D.switch_boxes(secs, lds, sds, vs) == {}
    assert all(D.door_states(secs, lds, sds)[si][0] == secs[si].floor_h for si in kinds)    # all stored shut


# ---- E1M2: the classification ------------------------------------------------------------------------------------

def test_e1m2_kinds(e1m2):
    mw, secs, lds, sds, vs = e1m2
    assert D.door_kinds(secs, lds, sds) == {
        27: "walkover", 29: "red", 30: "blazestay", 54: "blue", 63: "blue", 100: "yellow", 139: "red", 145: "stay",
        155: "blaze", 172: "blaze", 208: "stay", 258: "plain", 266: "blazestay", 299: "walkover", 318: "walkover"}


def test_the_key_doors_need_their_cards(e1m2):
    mw, secs, lds, sds, vs = e1m2
    kinds = D.door_kinds(secs, lds, sds)
    for si, kind in kinds.items():
        card = D.KIND_CARD.get(kind)
        for b, y, r in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)):
            want = kind != "walkover" and (card is None or {"blue": b, "yellow": y, "red": r}[card] == 1)
            assert D.can_open(kind, b, y, r) == want, (si, kind, b, y, r)
    assert D.door_card_cell("yellow") == "pcard_y" and D.door_card_cell("red") == "pcard_r"
    assert D.door_card_cell("blue") == "pcard" and D.door_card_cell("plain") is None


def test_the_stored_open_stay_door(e1m2):
    """208: D1 31 lines and an S1 103 switch, stored with its ceiling 80 over its floor 64 -- EV_DoDoor(open) from the
    ceiling it has: its stops start there, it is not passable shut (16 < 56), and it never closes"""
    mw, secs, lds, sds, vs = e1m2
    assert (secs[208].floor_h, secs[208].ceil_h) == (64, 80)
    assert D.door_states(secs, lds, sds)[208] == [80, 96, 112, 128, 140]
    assert D.pass_state(secs, lds, sds, 208) == 3               # 128 - 64 = 64 >= 56; 112 - 64 = 48 < 56
    assert D.door_stay(D.door_kinds(secs, lds, sds)[208])


def test_the_switches(e1m2):
    mw, secs, lds, sds, vs = e1m2
    trig = D.switch_door_triggers(secs, lds, sds, vs)
    got = sorted((targets, once) for _box, targets, once in trig)
    assert got == [((145,), True), ((208,), True), ((258,), False)]       # S1 103 x2, SR 63
    # the S1 latch is unobservable: its doors are open-stay (asserted inside switch_door_triggers)
    kinds = D.door_kinds(secs, lds, sds)
    assert all(D.door_stay(kinds[si]) for _b, t, once in trig if once for si in t)


def test_walkover_per_line_and_a_tag_opening_two_doors(e1m2):
    mw, secs, lds, sds, vs = e1m2
    assert D.walkover_triggers(secs, lds, sds, vs) == [
        (27, "x", 800, -1088, -976), (30, "x", 960, -2336, -2208), (266, "x", 960, -2336, -2208),
        (299, "x", 816, -2912, -2656), (318, "x", 848, -2912, -2656)]


@pytest.mark.skipif(not FULL.exists(), reason="the full episode wad is not present")
def test_e1m3s_ring_is_six_lines_two_slanted_opening_two_doors():
    """docs/f1-big-map-widths.md 11: E1M3's tag 11 -- six W1 lines in a ring, two slanted, opening doors 82 and 83"""
    mw = WadFile.from_path(str(FULL))
    secs, lds, sds, vs = mw.sectors("E1M3"), mw.linedefs("E1M3"), mw.sidedefs("E1M3"), mw.vertexes("E1M3")
    trig = D.walkover_triggers(secs, lds, sds, vs)
    ring = [t for t in trig if t[0] in (82, 83)]
    assert len(ring) == 12 and sum(t[1] == "d" for t in ring) == 4
    assert {t[1:] for t in ring if t[0] == 82} == {t[1:] for t in ring if t[0] == 83}


# ---- DoorPhase: the oracle every gate steps ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dp2(e1m2):
    mw, secs, lds, sds, vs = e1m2
    boxes = D.use_boxes_xy(secs, lds, sds, bake_bsp(mw, "E1M2").vertexes)
    return D.DoorPhase(secs, lds, sds, vs, boxes)


def _centre(box):
    return ((box[0] + box[2]) // 2) << 16, ((box[1] + box[3]) // 2) << 16


def _run(dp, st, n, use, x, y, **cards):
    for _ in range(n):
        st = dp.tic(st, use, x, y, **cards)
    return st


@pytest.mark.parametrize("si, kw", [(100, "has_yellow"), (29, "has_red"), (139, "has_red")])
def test_a_key_door_refuses_then_opens(dp2, si, kw):
    x, y = _centre(dp2.boxes[si])
    st0 = dp2.initial()
    assert dp2.tic(st0, True, x, y, has_blue=True)[0][si] == st0[0][si]          # the wrong card: shut
    other = "has_red" if kw == "has_yellow" else "has_yellow"
    assert dp2.tic(st0, True, x, y, **{other: True})[0][si] == st0[0][si]
    assert dp2.tic(st0, True, x, y, **{kw: True})[0][si][1] == D.OPENING           # its card: it opens


def test_the_sr_switch_presses_its_door_only_at_rest(dp2):
    (box,) = dp2.switches[258]
    x, y = _centre(box)
    st = dp2.tic(dp2.initial(), True, x, y)
    assert st[0][258][1] == D.OPENING
    n = dp2.nstates[258]
    st = _run(dp2, st, n + 3, False, x, y)                        # open, waiting
    ds = st[0][258]
    assert ds[0] == n - 1 and ds[1] == D.IDLE and ds[3] > 0
    pressed = dp2.tic(st, True, x, y)[0][258]                       # EV_DoDoor skips it: the wait runs on
    idle = dp2.tic(st, False, x, y)[0][258]
    assert pressed == idle
    # the door's OWN DR line restarts the wait (EV_VerticalDoor's, this repo's level-triggered press)
    dx, dy = _centre(dp2.boxes[258])
    assert dp2.tic(st, True, dx, dy)[0][258][3] == D.WAIT - 1           # restarted, and run down this tic
    st = _run(dp2, st, D.WAIT + n + 3, False, x, y)                # closed again: at rest, a press opens it
    assert st[0][258] == (0, D.IDLE, D.SPEED, 0) or st[0][258][:2] == (0, D.IDLE)
    assert dp2.tic(st, True, x, y)[0][258][1] == D.OPENING


@pytest.mark.parametrize("si", [145, 208])
def test_an_s1_switch_opens_its_door_for_good(dp2, si):
    (box,) = dp2.switches[si]
    x, y = _centre(box)
    st = _run(dp2, dp2.initial(), 40, True, x, y)                  # held: the door rises and stays
    assert st[0][si][0] == dp2.nstates[si] - 1 and st[0][si][1] == D.IDLE
    st = _run(dp2, st, 200, False, x, y)
    assert st[0][si][0] == dp2.nstates[si] - 1


def test_the_blazing_walkover_opens_both_doors_and_stays(dp2):
    """W1 109 (tag 16): one crossing fires both 30 and 266 -- blazing (BLAZE_STRIDE stops a frame), open for good"""
    ks = [k for k, t in enumerate(dp2.triggers) if t[0] in (30, 266)]
    assert len(ks) == 2
    y = -2272 << 16
    st = dp2.after_move(dp2.initial(), (952 << 16, y), (968 << 16, y))
    assert st[2] == {30, 266} and all(st[1][k] for k in ks)
    st = dp2.tic(st, False, 0, 0)
    for si in (30, 266):
        assert st[0][si][0] == min(D.BLAZE_STRIDE, dp2.nstates[si] - 1)
    st = _run(dp2, st, 300, False, 0, 0)
    assert all(st[0][si][0] == dp2.nstates[si] - 1 for si in (30, 266))
    st2 = dp2.after_move(st, (968 << 16, y), (952 << 16, y))         # W1: once
    assert not st2[2]


# ---- the slanted crossing: DOOM's two tests ------------------------------------------------------------------------

def _doom_crossed(seg, old, new, r):
    """P_TryMove's spechit (PIT_CheckLine: strict bbox overlap, P_BoxOnLineSide -1) and side change, written from
    reference_model's own primitives"""
    rm = ReferenceModel.__new__(ReferenceModel)
    ax, ay, bx, by = (v << 16 for v in seg)
    pol = ReferenceModel.point_on_line_side
    if pol(*old, ax, ay, bx, by) == pol(*new, ax, ay, bx, by):
        return False
    R = r << 16
    top, bottom, left, right = new[1] + R, new[1] - R, new[0] - R, new[0] + R
    if right <= min(ax, bx) or left >= max(ax, bx) or top <= min(ay, by) or bottom >= max(ay, by):
        return False
    return rm.box_on_line_side((top, bottom, left, right), ax, ay, bx, by) == -1


def test_a_slanted_trigger_is_crossed_as_doom_crosses_it():
    rng = random.Random(4)
    seg = (404, 2576, 436, 2640)
    hits = 0
    for _ in range(4000):
        t = rng.random()
        px, py = 404 + 32 * t + rng.uniform(-40, 40), 2576 + 64 * t + rng.uniform(-40, 40)
        old = (int(px * 65536), int(py * 65536))
        new = (old[0] + rng.randint(-16 << 16, 16 << 16), old[1] + rng.randint(-16 << 16, 16 << 16))
        got = D.crossed((0, "d") + seg, old, new, 16)
        assert got == _doom_crossed(seg, old, new, 16), (old, new)
        hits += got
    assert hits > 100


# ---- the box-fit guard of a slanted door's contact -----------------------------------------------------------------

def test_square_fits():
    sq = lambda s: ((0, 0, s, 0), (s, 0, s, s), (s, s, 0, s), (0, s, 0, 0))    # noqa: E731
    assert D._square_fits(sq(32), 0, 0, 32, 32, 32)
    assert D._square_fits(sq(40), 0, 0, 40, 40, 32)
    assert not D._square_fits(sq(30), 0, 0, 30, 30, 32)                           # control: too small
    assert not D._square_fits(((0, 0, 512, 0), (512, 0, 512, 16), (512, 16, 0, 16), (0, 16, 0, 0)), 0, 0, 512, 16, 32)


def test_e1m2_slanted_doors_fit_flags(e1m2):
    mw, secs, lds, sds, vs = e1m2
    geo = D.door_contact_geo(secs, lds, sds, vs)
    assert {si: a[2] for si, (a, _l) in geo.items() if a[0] == "poly"} == {30: False, 208: True, 299: False,
                                                                           318: False}


# ---- the World's door phase: the switch press ----------------------------------------------------------------------

@pytest.fixture(scope="module")
def w2():
    from doomfj import world as W
    return W.World(WadFile.from_path(FIX / "freedoom_e1m2.wad"), "E1M2", skill=gd.SK_HARD, strict=True)


def test_the_world_presses_a_door_from_its_switch(w2):
    from doomfj.world import TicEvents
    d = w2.door_order.index(258)
    (box,) = w2.door_switches[258]
    ws = w2.ws
    ws.px, ws.py = _centre(box)
    w2._doors_phase({"use": False}, TicEvents(0))
    assert ws.d_dir[d] == D.IDLE
    w2._doors_phase({"use": True}, TicEvents(0))
    assert ws.d_dir[d] == D.OPENING
    # a yellow door refuses the player without the yellow card (combat.player_can_open), and opens with it
    dy = w2.door_order.index(100)
    ws.px, ws.py = _centre(w2.door_boxes[100])
    w2._doors_phase({"use": True}, TicEvents(0))
    assert ws.d_dir[dy] == D.IDLE
    ws.p_cards[gd.IT_YELLOWCARD] = 1
    w2._doors_phase({"use": True}, TicEvents(0))
    assert ws.d_dir[dy] == D.OPENING
    ws.p_cards[gd.IT_YELLOWCARD] = 0
