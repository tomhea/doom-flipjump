"""M8 C3 -- the door kinds E1M3..E1M9 need, in the MODEL (doomfj.doors, World, combat, reference_model): the
fj mirrors are tests/fj/test_doors_c3_fj.py and tests/fj/test_shot_doors_fj.py.

  * E1M1 and E1M2 have none of it (their door text is the one it was: no keyed box, close line, latch, WR line, shot
    line, card or stay press);
  * door_tic's three new inputs (close_stride, hold, stay_press), each with a control;
  * World._doors_phase (the model's door phase) is DoorPhase.tic (every gate's) on E1M3 / E1M9 frame for frame --
    the mixed-card door, the locked / latched / stay-press switches;
  * the GR 46 lines: the picture records line 890 into the aim window (`render_wall_frame(aim_out=)`), and a GUN's
    shot at that column requests its door at rest, a swing does not (combat._line_attack).
E1M9's World needs its thing types gamedata does not have yet (C6 / C7): they are left out here, as the survey does.
"""
import random
from pathlib import Path

import pytest

from doomfj import doors as D
from doomfj import gamedata as gd
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not FULL.exists(), reason="the full episode wad is not present")


@pytest.fixture(scope="module")
def wad():
    return WadFile.from_path(str(FULL))


def _lv(wad, m):
    return wad.sectors(m), wad.linedefs(m), wad.sidedefs(m), wad.vertexes(m)


# ---- 1. E1M1 / E1M2 have none of it -------------------------------------------------------------------------------

@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
def test_e1m1_and_e1m2_have_no_c3_feature(wad, m):
    secs, lds, sds, v = _lv(wad, m)
    assert D.keyed_boxes_xy(secs, lds, sds, v) == {} and D.mixed_card_doors(secs, lds, sds) == {}
    assert D.close_strides(secs, lds, sds) == {} and D.switch_latches(secs, lds, sds) == []
    assert D.repeat_triggers(secs, lds, sds, v) == [] and D.shot_lines(secs, lds, sds) == []
    assert D.plain_switches(D.switch_entries(secs, lds, sds, v))
    assert D.requested_doors(secs, lds, sds, v) == {t[0] for t in D.walkover_triggers(secs, lds, sds, v)}


# ---- 2. door_tic ---------------------------------------------------------------------------------------------------

def _close(st, n, frames, **kw):
    out = [st]
    for _ in range(frames):
        st = D.door_tic(st, n, False, stay=True, **kw)
        out.append(st)
    return out


def test_a_close_lines_door_closes_at_its_stride():
    n = 9
    seq = _close(D.close_state((n - 1, D.IDLE, 0, 0)), n, 4, close_stride=4)
    assert [s[0] for s in seq] == [8, 4, 0, 0, 0] and seq[2][1] == D.IDLE
    # control: the opening's stride (1) is not the close's
    assert [s[0] for s in _close(D.close_state((n - 1, D.IDLE, 0, 0)), n, 4)] == [8, 7, 6, 5, 4]


def test_a_close_lines_door_holds_on_a_thing_where_a_raise_door_reverses():
    n, pass_at = 9, 5
    st = (5, D.CLOSING, 1, 0)
    held = D.door_tic(st, n, False, stay=True, blocked=True, pass_at=pass_at, close_stride=1, hold=True)
    assert held == (5, D.CLOSING, D.SPEED, 0)
    rev = D.door_tic(st, n, False, stay=True, blocked=True, pass_at=pass_at, close_stride=1)
    assert rev == (5, D.OPENING, D.SPEED, 0)                     # control: without `hold` it goes back up


def test_a_stay_press_opens_a_raise_door_for_good():
    n = 6
    st = D.door_tic((0, D.IDLE, 0, 0), n, True, stay_press=True)
    assert st[1] == D.OPENING and st[3] == D.STAY_MARK
    for _ in range(n + 3):
        st = D.door_tic(st, n, False)
    assert st == (n - 1, D.IDLE, D.SPEED, 0)                     # at the top, no wait: it never closes
    for _ in range(D.WAIT + n + 3):
        st = D.door_tic(st, n, False)
    assert st[0] == n - 1
    # control: the same door pressed plainly waits at the top and closes
    st = D.door_tic((0, D.IDLE, 0, 0), n, True)
    for _ in range(n + D.WAIT + n + 3):
        st = D.door_tic(st, n, False)
    assert st[0] == 0
    # a DR press at the top after the stay press: the raise -- it waits, then closes (EV_VerticalDoor's vld_normal)
    st = D.door_tic((n - 1, D.IDLE, D.SPEED, 0), n, True)
    assert st == (n - 1, D.IDLE, D.SPEED, D.WAIT - 1)         # (the wait already runs this tic)


def test_repeat_act_and_close_state():
    assert D.repeat_act((1, "open"), (0, D.IDLE, 0, 0)) == "press"
    assert D.repeat_act((1, "open"), (3, D.OPENING, 1, 0)) is None
    assert D.repeat_act((1, "close"), (4, D.IDLE, 1, 0)) == "close"
    assert D.repeat_act((1, "close"), (0, D.IDLE, 0, 0)) is None         # shut at rest: the thinker ends at once
    assert D.repeat_act((1, "close"), (4, D.IDLE, 1, 7)) is None         # waiting open: a thinker
    assert D.close_state((4, D.IDLE, 1, 0)) == (4, D.CLOSING, D.SPEED, 0)


def test_front_box_is_the_lines_front_side():
    from types import SimpleNamespace as NS
    v = [(0, 0), (0, 100), (100, 0)]
    north, south = NS(v1=0, v2=1), NS(v1=1, v2=0)
    assert D.front_box(north, v, 64) == (0, -64, 64, 164)          # going north: the front is east
    assert D.front_box(south, v, 64) == (-64, -64, 0, 164)
    east, west = NS(v1=0, v2=2), NS(v1=2, v2=0)
    assert D.front_box(east, v, 64) == (-64, -64, 164, 0)          # going east: the front is south
    assert D.front_box(west, v, 64) == (-64, 0, 164, 64)


# ---- 3. World._doors_phase == DoorPhase.tic ------------------------------------------------------------------------

def _world(wad, m):
    from doomfj.world import World
    unknown = {t.type for t in wad.things(m)} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
    saved = gd.NOT_THINGS
    gd.NOT_THINGS = frozenset(saved | unknown)
    try:
        return World(wad, m, player="full")
    finally:
        gd.NOT_THINGS = saved


@pytest.mark.parametrize("m", ["E1M3", "E1M5", "E1M9"])
def test_the_worlds_door_phase_is_DoorPhase(wad, m):
    from doomfj.world import TicEvents
    w = _world(wad, m)
    secs, lds, sds, v = _lv(wad, m)
    dp = D.DoorPhase(secs, lds, sds, v, D.use_boxes_xy(secs, lds, sds, bake_bsp(wad, m).vertexes))
    assert dp.order == w.door_order
    rng = random.Random(4)
    boxes = ([b for si in dp.order for b, _c in dp.keyed.get(si, ())] + [dp.boxes[si] for si in dp.order if si in dp.boxes]
             + [b for si in dp.order for b in dp.switches.get(si, ())])
    st = dp.initial()
    ws = w.ws
    for cards in ((0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 1, 1)):
        for b in boxes:
            for f in range(10):
                x, y = (b[0] + b[2]) // 2 + rng.randint(-8, 8), (b[1] + b[3]) // 2 + rng.randint(-8, 8)
                use = f < 2 or rng.random() < 0.2
                ws.px, ws.py = x << 16, y << 16
                ws.p_cards[gd.IT_BLUECARD], ws.p_cards[gd.IT_YELLOWCARD], ws.p_cards[gd.IT_REDCARD] = cards
                w._doors_phase({"use": use}, TicEvents(0))
                st = dp.tic(st, use, x << 16, y << 16, has_blue=bool(cards[0]), has_yellow=bool(cards[1]),
                            has_red=bool(cards[2]), others=[(ws.mon_x[k] << 16, ws.mon_y[k] << 16,
                                                             w.mon_radius[k] << 16) for k in range(w.layout.nmon)
                                                            if ws.mon_active[k] and ws.mon_health[k] > 0])
                got = {si: (ws.d_state[d], ws.d_dir[d], ws.d_sub[d], ws.d_wait[d]) for d, si in enumerate(w.door_order)}
                assert got == st[0], (m, cards, b, f)
                assert tuple(ws.w_fired) == st[1]
    assert any(s[0] for s in st[0].values())


# ---- 4. the GR 46 shot lines -----------------------------------------------------------------------------------------

def _shot_frame(wad, x, y, ang, render=None):
    from doomfj.config import GAME_CFG
    from doomfj.reference_model import ReferenceModel, Scene, SimState
    rm = ReferenceModel(GAME_CFG)
    out = [0] * 17
    sc = Scene(wad, wad, "E1M9", bake_bsp(wad, "E1M9"), {}, frozenset())
    (render or rm.render_wall_frame)(SimState(x << 16, y << 16, ang, "E1M9"), sc, aim_things={}, aim_out=out,
                                      things=True, sprite_wad=wad)
    return out


def test_the_picture_records_a_shot_line(wad):
    secs, lds, sds, _v = _lv(wad, "E1M9")
    shots = D.shot_lines(secs, lds, sds)
    assert [li for li, _t in shots] == [167, 170, 890, 1271] and shots[2][1] == (184,)
    out = _shot_frame(wad, 0, 3395, 0x80000000)                  # east of line 890, facing west
    assert set(out) == {0, D.shot_sid(2)} and out.count(D.shot_sid(2)) >= 4
    # control: the record needs the line to be the column's wall -- facing east, nothing
    assert set(_shot_frame(wad, 0, 3395, 0)) <= {0}


def test_a_gun_opens_the_shot_door_and_a_swing_does_not(wad):
    from doomfj.combat import CombatMixin, MISSILERANGE_U
    from doomfj.world import TicEvents
    w = _world(wad, "E1M9")
    ws = w.ws
    d = w.door_order.index(184)
    k = 2
    w.aim = lambda world, col: ("shot", k)
    w._p_resolve = True
    ev = TicEvents(0)
    w._line_attack("fist", 80, 5, 64, ev)
    assert ws.d_monreq[d] == 0                                     # a swing: no target
    w._line_attack("pistol", 80, 5, MISSILERANGE_U, ev)
    assert ws.d_monreq[d] == 1 and ev.shots[-1] == ("pistol", 80, ("shot", k), 5)
    # a door at work is not pressed (EV_DoDoor skips a sector with a thinker)
    ws.d_monreq[d], ws.d_dir[d] = 0, D.OPENING
    w._line_attack("pistol", 80, 5, MISSILERANGE_U, ev)
    assert ws.d_monreq[d] == 0
    # the window's ids: the shot lines' from the top of the byte, the monsters' and barrels' below
    ws.aim_sid[0] = D.shot_sid(k)
    assert CombatMixin.window_aim(w, w.aim_lo) == ("shot", k)
    ws.aim_sid[0] = D.shot_sid(len(w.door_shots))                 # one under the lowest: a monster / barrel id
    assert CombatMixin.window_aim(w, w.aim_lo)[0] != "shot"


# ---- 5. the tic's writes stay the doors' own ------------------------------------------------------------------------

@pytest.mark.parametrize("m", ["E1M3", "E1M6", "E1M7", "E1M9"])
def test_the_c3_door_tic_writes_only_door_cells_and_its_latches(wad, m):
    """test_doorcode's census on the C3 maps: the new branches READ the cards and write only the door cells -- and
    `wfired`, the S1 latches' W1 bits (E1M6, E1M9)"""
    import re
    from doomfj import doorcode
    secs, lds, sds, v = _lv(wad, m)
    cv = bake_bsp(wad, m).vertexes
    tbl = D.door_states(secs, lds, sds)
    slots = sorted(tbl)
    text = "\n".join(doorcode.door_tic_lines(
        slots, {si: len(tbl[si]) for si in slots}, D.use_boxes_xy(secs, lds, sds, cv), D.door_kinds(secs, lds, sds),
        contact=D.door_contact_geo(secs, lds, sds, cv), passes={si: D.pass_state(secs, lds, sds, si) for si in slots},
        switches=D.switch_boxes(secs, lds, sds, cv), walked=D.requested_doors(secs, lds, sds, v),
        keyed=D.keyed_boxes_xy(secs, lds, sds, cv),
        switch_info={si: [e[1:] for e in es] for si, es in D.switch_entries(secs, lds, sds, cv).items()},
        nwalk=len(D.walkover_triggers(secs, lds, sds, v)), close=D.close_strides(secs, lds, sds)))
    written = {mm.group(1) for mm in re.finditer(r"hex\.(?:set|zero|inc|dec|xor_by|mov) (?:\d+, )?([A-Za-z_]\w*)",
                                                text)}
    written = {w_ for w_ in written if not re.match(r"dr\d+_", w_)}       # a slanted line's own scratch (L2)
    assert written <= {"dstate", "ddir", "dsub", "dwait", "duse", "dbox", "dreq", "wfired"}, sorted(written)
    assert ("wfired" in written) == bool(D.switch_latches(secs, lds, sds))
