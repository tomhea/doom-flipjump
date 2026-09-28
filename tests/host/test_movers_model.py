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
    axis, coord, lo, hi = w._door_contact[si][1][0]
    mx, my = (((lo + hi) // 2) << 16, coord << 16) if axis == "y" else (coord << 16, ((lo + hi) // 2) << 16)
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
    x0, y0, x1, y1 = w._door_contact[si][0]
    cx, cy = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
    assert y1 - y0 == 32 or x1 - x0 == 32
    w.teleport_player(cx, cy)
    assert w.player_sector() == si
    assert w.door_touched(si)


def test_the_gate_phase_is_the_models_on_a_ride(w):
    """MoverPhase fed the model's own poses and use presses reproduces its lift cells and heights
    every frame -- a walk onto lift 98 over its WR line, a ride down and back, an SR press"""
    from doomfj.movers import MoverPhase
    mp = MoverPhase(w.secs, w.lds, w.sds, w.mw.vertexes(w.mapname))
    assert mp.order == w.lift_order
    st = mp.initial()
    w.teleport_player(128 * U, 160 * U, 0x40000000)
    keys = [{"forward": True}] * 5 + [{}] * 50 + [{"use": True}, {}, {}]
    deepest = []
    for kd in keys:
        pre = (w.ws.px, w.ws.py)
        press = kd.get("use") and not w.ws.p_usedown
        w.tic(kd)
        st = mp.tic(st)
        if press:
            st = mp.use_press(st, *pre)
        st = mp.after_move(st, pre, (w.ws.px, w.ws.py))
        cells = tuple((w.ws.l_state[k], w.ws.l_dir[k], w.ws.l_sub[k], w.ws.l_wait[k])
                      for k in range(2))
        assert st[0] == cells and st[1] == {si for k, si in enumerate(w.lift_order) if w.ws.l_req[k]}
        assert mp.heights(st) == w.mover_heights_now()
        deepest.append(st[0][0][0])
    assert max(deepest) == 9 and 0 in deepest[40:56], "the ride: all the way down and back up"
    assert deepest[-1] >= 1, "the SR press at the top starts the second ride"



def test_the_contact_rule_is_check_positions_straddle_or_the_sector(w):
    """doors.touches_door (rectangles, strict compares) against the rule it replaces: the box on one
    of the door's two-sided lines by check_position's own test (bbox, then P_BoxOnLineSide), or the
    centre's LEAF in the door sector -- at every door, over a grid round it at 16.16 steps that hit
    the lines' coordinates and their +-radius exactly, wherever a player can STAND (the collision
    scene with the doors open): in the solid wall beside a door the BSP's point location answers
    for a void and the two rules may differ, and nothing is ever there to ask"""
    from doomfj import doors as Dm
    V = w.cmap.vertexes
    r16 = 16 << 16
    checked = touched = 0
    for si in w.door_order:
        (x0, y0, x1, y1), _l = w._door_contact[si]
        segs = [(min(V[w.lds[li].v1][0], V[w.lds[li].v2][0]) << 16, max(V[w.lds[li].v1][0], V[w.lds[li].v2][0]) << 16,
                 min(V[w.lds[li].v1][1], V[w.lds[li].v2][1]) << 16, max(V[w.lds[li].v1][1], V[w.lds[li].v2][1]) << 16,
                 V[w.lds[li].v1][0] << 16, V[w.lds[li].v1][1] << 16, V[w.lds[li].v2][0] << 16, V[w.lds[li].v2][1] << 16)
                for li in w.door_lines.get(si, ())]
        for gx in range(x0 - 24, x1 + 25, 4):
            for gy in range(y0 - 24, y1 + 25, 4):
                for fx in (0, 1, -1):
                    x16, y16 = (gx << 16) + fx, (gy << 16) - fx
                    top, bottom, left, right = y16 + r16, y16 - r16, x16 - r16, x16 + r16
                    old = any(not (right <= a or left >= b or top <= c or bottom >= d)
                              and w.rm.box_on_line_side((top, bottom, left, right), ax, ay, bx, by) == -1
                              for (a, b, c, d, ax, ay, bx, by) in segs)
                    leaf = w.rm.point_in_subsector(w.cmap, x16 >> 16, y16 >> 16)
                    in_leaf = w.leaf_sector[leaf] == si
                    inside = (x0 << 16) <= x16 <= (x1 << 16) and (y0 << 16) <= y16 <= (y1 << 16)
                    if in_leaf and not inside:
                        # the VOID beside a door: a door leaf is bounded only by the door's segs, so
                        # point location answers "the door" for the solid wall around it (MEASURED:
                        # door 10's leaf 156 holds (744, 528)); walls enclose it, nothing stands there
                        continue
                    if not w.rm.check_position(w.scene_c, x16, y16)[0]:
                        continue                          # the collision refuses it: never a position
                    old = old or in_leaf
                    new = Dm.touches_door(w._door_contact[si], x16, y16, r16)
                    assert new == old, (si, gx, gy, fx, new, old)
                    checked += 1
                    touched += new
    assert checked > 5000 and 0 < touched < checked
