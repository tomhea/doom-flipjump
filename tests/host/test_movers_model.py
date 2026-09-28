"""M7 P2b L0 -- the movers in the model (doomfj.world / combat on doomfj.movers): the player crossing
a WR line starts the lift on the next tic and rides it down, an SR press does the same, the floor
switch lowers its pillars at once and opens them to walking, a monster's crossing triggers a WR
lift, a monster standing on a lift keeps its floor, and NEW GAME's restart puts it all back."""
import pytest

from doomfj import doors as D
from doomfj import gamedata as gd
from doomfj import movers as MV
from doomfj import world as W

U = 1 << 16


@pytest.fixture()
def w():
    w = W.World(skill=gd.SK_HARD, strict=True)
    for _ in range(2):
        w.tic({})
    return w


def lift_k(w, si):
    return w.lift_order.index(si)


def test_the_world_has_the_movers(w):
    assert w.lift_order == [98, 103] and sorted(w.switch) == [76, 126, 129]
    assert w.layout.nlift == 2 and len(w.lift_walk) == 5 and len(w.lift_use) == 4
    assert w.mover_heights_now() == {}


def test_crossing_a_wr_line_lowers_the_lift_from_the_next_tic_and_the_player_rides_it(w):
    # lift 98 (x 64..192, y 192..320): approach its south line y=192 from below, facing north
    w.teleport_player(128 * U, 160 * U, 0x40000000)
    k = lift_k(w, 98)
    steps = 0
    while not w.ws.l_req[k] and steps < 6:
        w.tic({"forward": True})
        steps += 1
    assert w.ws.l_req[k] == 1 and w.ws.l_state[k] == 0, "the crossing asks; the lift waits a tic"
    w.tic({})
    assert w.ws.l_state[k] == 1 and w.ws.l_dir[k] == D.OPENING
    for _ in range(12):
        w.tic({})
    assert w.ws.l_state[k] == 9 and w.heights_now[98][0] == -124
    # the player is on the lift and stands on its floor
    assert w.player_sector() == 98
    assert w.rm.check_position(w.scene_c, w.ws.px, w.ws.py)[1] == -124


def test_an_sr_press_lowers_the_lift(w):
    k = lift_k(w, 98)
    (_tag, (x0, y0, x1, y1)), = [e for e in w.lift_use if e[0] == 1]
    w.teleport_player(((x0 + x1) // 2 + 40) * U, ((y0 + y1) // 2) * U)   # east of line 594
    w.ws.p_usedown = 0
    w.tic({"use": True})
    assert w.ws.l_req[k] == 1
    w.tic({})
    assert w.ws.l_state[k] == 1


def test_a_held_use_does_not_press_the_sr_line(w):
    k = lift_k(w, 98)
    (_tag, (x0, y0, x1, y1)), = [e for e in w.lift_use if e[0] == 1]
    w.teleport_player(((x0 + x1) // 2 + 40) * U, ((y0 + y1) // 2) * U)
    w.ws.p_usedown = 1
    w.tic({"use": True})
    assert w.ws.l_req[k] == 0


def test_the_floor_switch_lowers_its_pillars_at_once_and_once(w):
    (x0, y0, x1, y1), = w.switch_boxes
    w.teleport_player(((x0 + x1) // 2) * U, (y0 + 20) * U)
    w.ws.p_usedown = 0
    w.tic({"use": True})
    assert w.ws.f_switch == 1
    assert {si: w.heights_now[si] for si in (76, 126, 129)} == {
        76: (136, 272), 126: (144, 264), 129: (8, 264)}
    assert w.secs_c[76].floor_h == 136                   # the monsters' collision map too
    w.ws.p_usedown = 0
    w.tic({"use": True})                                 # S1: nothing more
    assert w.ws.f_switch == 1


def test_a_monster_crossing_a_wr_line_triggers_the_lift(w):
    k = lift_k(w, 103)
    m = next(m for m in range(w.layout.nmon) if w.ws.mon_active[m])
    w.teleport_monster(m, 1400, -370)                     # north of line 618 (y = -384)
    w._move_monster(m, 1400, -400, w.secs_c[103].floor_h, W.TicEvents(0))
    assert w.ws.l_req[k] == 1


def test_a_monster_on_a_lift_keeps_its_floor(w):
    k = lift_k(w, 103)
    m = next(m for m in range(w.layout.nmon) if w.ws.mon_active[m])
    w.teleport_monster(m, 1428, -444)                     # on lift 103
    assert w.leaf_sector[w.ws.mon_leaf[m]] == 103 and w.ws.mon_floorz[m] == 136
    w.ws.l_req[k] = 1
    for _ in range(3):
        w.tic({})
    assert w.ws.mon_floorz[m] == w.heights_now[103][0] < 136


def test_new_game_puts_the_movers_back(w):
    w.ws.l_req[lift_k(w, 98)] = 1
    w.ws.f_switch = 1
    for _ in range(4):
        w.tic({})
    assert w.mover_heights_now()
    w.new_game(gd.SK_HARD)
    w.tic({})
    assert w.mover_heights_now() == {} and w.ws.f_switch == 0
    assert list(w.ws.l_state) == [0, 0] and list(w.ws.l_req) == [0, 0]


def test_the_movers_are_dynamic_for_sight_and_sound(w):
    nodes = {w.sector_node[si] for si in w.mover_order}
    assert len(nodes) == 5 and not nodes & {w.sector_node[si] for si in w.door_order}
    assert w.nsound == w.layout.nsound


def test_a_door_closing_on_the_player_goes_back_up(w):
    """door 10: open it, stand in the doorway, and wait: it closes to its pass state and reverses"""
    si = 10
    d = w.door_order.index(si)
    x0, y0, x1, y1 = w.door_boxes[si]
    geo = w._door_line_geo[si][0]
    mx, my = ((geo[4] + geo[6]) // 2), ((geo[5] + geo[7]) // 2)     # a door line's middle, 16.16
    w.teleport_player(mx, my)
    n, p = w.door_nstates[si], w.door_pass[si]
    w.ws.d_state[d], w.ws.d_dir[d], w.ws.d_sub[d], w.ws.d_wait[d] = n - 1, D.IDLE, 0, 1
    seen = []
    for _ in range(3 * n + 10):
        w.tic({})
        seen.append(w.ws.d_state[d])
    assert min(seen) == p, "the door never went below its pass state while the player stood in it"
    assert w.door_touched(si)


def test_a_door_closes_when_nothing_is_in_it(w):
    si = 10
    d = w.door_order.index(si)
    n = w.door_nstates[si]
    w.ws.d_state[d], w.ws.d_dir[d], w.ws.d_sub[d], w.ws.d_wait[d] = n - 1, D.IDLE, 0, 1
    for _ in range(n + 3):
        w.tic({})
    assert w.ws.d_state[d] == 0 and not w.door_touched(si)


def test_a_player_centred_in_a_32_thick_door_touches_it(w):
    """door 10 is 32 units thick: a 32-wide box centred in it has its edges ON both lines, which
    the strict bbox test does not count -- the centre-in-the-sector half of the contact rule is
    what holds the door"""
    si = 10
    ys = sorted({g[5] for g in w._door_line_geo[si]} | {g[7] for g in w._door_line_geo[si]})
    xs = sorted({g[4] for g in w._door_line_geo[si]} | {g[6] for g in w._door_line_geo[si]})
    cx, cy = (xs[0] + xs[-1]) // 2, (ys[0] + ys[-1]) // 2
    assert ys[-1] - ys[0] == 32 << 16 or xs[-1] - xs[0] == 32 << 16
    w.teleport_player(cx, cy)
    assert w.player_sector() == si
    assert w.door_touched(si)
