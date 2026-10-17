"""M8 L0: the model's E1M2 additions -- the doors that are not four-line rectangles, and the new pickups.

- The door contact (`doors.touches_door`) on EVERY E1M2 door against the rule it stands for (test_movers_model's E1M1
  test): the box on one of the door's two-sided lines by check_position's own test (strict bbox overlap, then
  P_BoxOnLineSide -- `reference_model.box_on_line_side`, DOOM's FixedMul truncation and its "on the line is the back"
  rule), or the centre's LEAF in the door sector, over a grid round each door that hits the lines and +-radius exactly,
  wherever the collision lets a player stand. Doors 299 and 318 have slanted sides; door 27's long side is five pieces.
- The pickups (combat._touch): P_GiveCard (the flash SET on a new card), the soulsphere (+100, capped at 200), the map.
CONTROL (R9): the previous slanted rule (exact cross products, a corner ON the line ignored) disagrees on the grid."""
from pathlib import Path

import pytest

from doomfj import doors as Dm
from doomfj import gamedata as gd
from doomfj.wad import WadFile
from doomfj import world as W

FIX = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def w2():
    w = W.World(WadFile.from_path(FIX / "freedoom_e1m2.wad"), "E1M2", skill=gd.SK_HARD, strict=True)
    # every door OPEN, so the collision scene lets a player stand across and in it (the grid's positions)
    stops = Dm.door_states(w.secs, w.lds, w.sds)
    for d, si in enumerate(w.door_order):
        w.ws.d_state[d] = len(stops[si]) - 1                # the top stop: fully open
    w._door_phase_scene()
    return w


def _old_slanted(geo, x16, y16, r16):
    """the rule L0 first shipped for slanted lines (exact cross products, a corner on the line ignored): the control"""
    area, lines = geo
    for ln in lines:
        if ln[0] != "d":
            continue
        _, ax, ay, bx, by = ln
        ax, ay, bx, by = ax << 16, ay << 16, bx << 16, by << 16
        if not (min(ax, bx) - r16 < x16 < max(ax, bx) + r16 and min(ay, by) - r16 < y16 < max(ay, by) + r16):
            continue
        sides = {(bx - ax) * (cy - ay) - (by - ay) * (cx - ax) > 0
                 for cx in (x16 - r16, x16 + r16) for cy in (y16 - r16, y16 + r16)
                 if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) != 0}
        if len(sides) == 2:
            return True
    return False


def _grid(w, rule):
    """(checked, touched, mismatches) of `rule(si, x16, y16, r16)` against the reference over every door's grid"""
    V = w.cmap.vertexes
    r16 = 16 << 16
    checked = touched = 0
    bad = []
    for si in w.door_order:
        area, _l = w._door_contact[si]
        if area[0] == "poly":
            xs = [p for e in area[1] for p in (e[0], e[2])]
            ys = [p for e in area[1] for p in (e[1], e[3])]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        else:
            x0, y0, x1, y1 = area
        segs = [(min(V[w.lds[li].v1][0], V[w.lds[li].v2][0]) << 16, max(V[w.lds[li].v1][0], V[w.lds[li].v2][0]) << 16,
                 min(V[w.lds[li].v1][1], V[w.lds[li].v2][1]) << 16, max(V[w.lds[li].v1][1], V[w.lds[li].v2][1]) << 16,
                 V[w.lds[li].v1][0] << 16, V[w.lds[li].v1][1] << 16, V[w.lds[li].v2][0] << 16, V[w.lds[li].v2][1] << 16)
                for li in w.door_lines.get(si, ())]
        for gx in range(x0 - 24, x1 + 25, 4):
            for gy in range(y0 - 24, y1 + 25, 4):
                for fx in (0, 1, -1):
                    x16, y16 = (gx << 16) + fx, (gy << 16) - fx
                    top, bottom, left, right = y16 + r16, y16 - r16, x16 - r16, x16 + r16
                    ref = any(not (right <= a or left >= b or top <= c or bottom >= d)
                              and w.rm.box_on_line_side((top, bottom, left, right), ax, ay, bx, by) == -1
                              for (a, b, c, d, ax, ay, bx, by) in segs)
                    leaf = w.rm.point_in_subsector(w.cmap, x16 >> 16, y16 >> 16)
                    in_leaf = w.leaf_sector[leaf] == si
                    inside = (x0 << 16) <= x16 <= (x1 << 16) and (y0 << 16) <= y16 <= (y1 << 16)
                    if in_leaf and not inside:
                        continue                          # the void beside a door (test_movers_model)
                    if not w.rm.check_position(w.scene_c, x16, y16)[0]:
                        continue                          # never a position
                    ref = ref or in_leaf
                    got = rule(si, x16, y16, r16)
                    checked += 1
                    touched += got
                    if got != ref:
                        bad.append((si, gx, gy, fx, got, ref))
    return checked, touched, bad


def test_every_e1m2_door_is_check_positions_straddle_or_the_sector(w2):
    kinds = {si: w2._door_contact[si][0][0] == "poly" for si in w2.door_order}
    # doors 299 and 318 (slanted sides), M8 L2's 30 (two strips) and 208 (two squares: a box fits, the inside test kept)
    assert {si for si, poly in kinds.items() if poly} == {30, 208, 299, 318}, kinds
    checked, touched, bad = _grid(w2, lambda si, x, y, r: Dm.touches_door(w2._door_contact[si], x, y, r))
    assert not bad, bad[:5]
    assert checked > 5000 and 0 < touched < checked


def test_control_the_first_slanted_rule_is_caught(w2):
    def rule(si, x, y, r):
        geo = w2._door_contact[si]
        if geo[0][0] != "poly":
            return Dm.touches_door(geo, x, y, r)
        return Dm._inside_poly(geo[0][1], x, y) or _old_slanted(geo, x, y, r) or any(
            Dm.touches_door(((0, 0, 0, 0), [ln]), x, y, r) for ln in geo[1] if ln[0] != "d")
    assert _grid(w2, rule)[2], "the grid cannot tell the first slanted rule from DOOM's"


def test_a_split_side_is_still_a_rectangle(w2):
    area, lines = w2._door_contact[27]
    assert area == (704, 64, 1024, 80)                      # the long side is five collinear lines


def test_inside_poly_is_strict():
    sq = ((0, 0, 10, 0), (10, 0, 10, 10), (10, 10, 0, 10), (0, 10, 0, 0))
    assert Dm._inside_poly(sq, 5 << 16, 5 << 16)
    assert not Dm._inside_poly(sq, 10 << 16, 5 << 16)       # on an edge: not inside
    assert not Dm._inside_poly(sq, 11 << 16, 5 << 16)


def test_the_new_pickups(w2):
    ws = w2.ws
    ws.p_bonuscount = 0
    assert w2._touch(13, False, 0, 0) and ws.p_cards[gd.IT_REDCARD] == 1 and ws.p_bonuscount == 2 * gd.BONUSADD
    ws.p_bonuscount = 0
    assert w2._touch(13, False, 0, 0) and ws.p_bonuscount == gd.BONUSADD   # a held card: the flash only adds
    assert w2._touch(6, False, 0, 0) and ws.p_cards[gd.IT_YELLOWCARD] == 1
    ws.p_health = 150
    assert w2._touch(2013, False, 0, 0) and ws.p_health == 200            # capped at 200
    assert w2._touch(2026, False, 0, 0)
