"""M8 F1.3 -- every moving floor E1M2 has, as the model runs it (doomfj.movers / world / combat; docs/f1-big-map-widths.md
5, 9, 10; docs/handoff-e1m2.md L3):

  * the floor groups: one per tag of a one-shot floor line, DOOM's destinations (P_FindLowest/HighestFloorSurrounding,
    turboLower's +8, raiseFloor24), each sector on the 16-unit grid from its floor to its destination; E1M1's ONE
    group is its instant switch (switch_sectors' heights), the narrow layout and the 1-bit `f_switch` unchanged;
  * per-tag S1 (item 10): E1M2's two 23 tags fire their own groups -- a press at one leaves the other;
  * the motion: a W1 crossing fires its group once, the floor steps every FLOOR_SUB frames (turboLower every frame)
    and stays at its destination; a slanted W1 line by P_PointOnLineSide's cross product;
  * the blazing lifts stride two; a tag starts both its lifts; a monster triggers 88 and never 120;
  * the pickups on a mover's floor (item 9): the blue card's touch reads the floor of the moment.
CONTROLS (R9): the card's STATIC z refuses the touch the live floor allows (and the reverse before the switch); a
slanted crossing by the axis rule's single-axis extent parts from the slanted rule on the fuzz; one fswitch cell for
both 23 tags fires the wrong group."""
import random
from pathlib import Path

import pytest

from doomfj import doors as D
from doomfj import gamedata as gd
from doomfj import movers as MV
from doomfj import world as W
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

FIX = Path(__file__).resolve().parents[1] / "fixtures"
U = 1 << 16


@pytest.fixture(scope="module")
def m2():
    mw = WadFile.from_path(FIX / "freedoom_e1m2.wad")
    return mw.sectors("E1M2"), mw.linedefs("E1M2"), mw.sidedefs("E1M2"), mw.vertexes("E1M2")


@pytest.fixture(scope="module")
def m1():
    mw = WadFile.from_path(FIX / "freedoom_e1m1.wad")
    return mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.vertexes("E1M1")


def _w2():
    return W.World(WadFile.from_path(FIX / "freedoom_e1m2.wad"), "E1M2", skill=gd.SK_HARD, strict=True)


@pytest.fixture()
def w2():
    return _w2()


# ---- the groups ---------------------------------------------------------------------------------------------------

def test_e1m1_has_one_instant_group_the_switch(m1):
    secs, lds, sds, _v = m1
    gs = MV.floor_groups(secs, lds, sds)
    assert len(gs) == 1 and gs[0].special == 23 and gs[0].sub == 0 and gs[0].use
    assert {si: (h[1], h[0]) for si, h in gs[0].heights} == MV.switch_sectors(secs, lds, sds)
    assert not MV.floor_wide(gs) and MV.fswitch_nibbles(gs) == 1 and MV.switch_cell(0) == "fswitch"
    tab = MV.mover_table(secs, lds, sds)
    assert {si: c for si, (c, _h) in tab.items()} == {98: "lstate + 0*dw", 103: "lstate + 1*dw", 76: "fswitch",
                                                     126: "fswitch", 129: "fswitch"}
    assert all(MV.lift_stride(secs, lds, si) == 1 for si in (98, 103))
    assert MV.lift_walk_triggers(secs, lds, sds, m1[3], MV.LIFT_MONSTER_SPECIALS) == \
        MV.lift_walk_triggers(secs, lds, sds, m1[3])


def _doom_dest(secs, lds, sds, si, special):
    """the destination from DOOM's own functions, written out here (p_floor.c / p_spec.c)"""
    nb = D.two_sided_neighbours(lds, sds)[si]
    floors = [secs[n].floor_h for n in nb]
    own = secs[si].floor_h
    if special in (23, 38):                      # P_FindLowestFloorSurrounding: starts at its own floor
        return min([own] + floors)
    if special in (19, 102):                     # P_FindHighestFloorSurrounding: starts at -500
        return max([-500] + floors)
    if special == 71:
        h = max([-500] + floors)
        return h + 8 if h != own else h
    if special == 58:
        return own + 24
    raise ValueError(special)


def test_e1m2_groups_are_dooms_destinations_on_the_grid(m2):
    secs, lds, sds, _v = m2
    gs = MV.floor_groups(secs, lds, sds)
    assert [g.tag for g in gs] == sorted(g.tag for g in gs) and len(gs) == 11
    by_tag = {}
    for ld in lds:
        if ld.special in MV.FLOOR_SPECIALS:
            by_tag.setdefault(ld.tag, set()).add(ld.special)
    for g in gs:
        assert by_tag[g.tag] == {g.special}
        assert set(g.sectors) == {si for si, s in enumerate(secs) if s.tag == g.tag}
        assert g.sub == MV.FLOOR_SPECIALS[g.special][2]
        for si, hts in g.heights:
            assert hts[0] == secs[si].floor_h and hts[-1] == _doom_dest(secs, lds, sds, si, g.special)
            if g.sub:                                # monotone, 16-unit grid steps (the doors' zero-aligned stops)
                steps = [b - a for a, b in zip(hts, hts[1:]) if b != a]
                assert all(abs(s) <= 16 for s in steps) and len({s > 0 for s in steps}) == 1
            assert len(hts) == g.n <= D.MAX_STATES
    # the two S1 23 tags are two groups (item 10), instant both
    sw = [g for g in gs if g.special == 23]
    assert [g.tag for g in sw] == [3, 13] and all(not g.sub for g in sw)


def test_e1m2_lifts_blazing_and_shared_tags(m2):
    secs, lds, sds, verts = m2
    order = sorted(MV.lift_states(secs, lds, sds))
    assert order == [44, 47, 64, 124, 209]
    assert {si: MV.lift_stride(secs, lds, si) for si in order} == {44: 1, 47: 2, 64: 2, 124: 2, 209: 2}
    assert MV.lift_slots_of_tag(secs, order)[5] == (1, 4)
    mon = MV.lift_walk_triggers(secs, lds, sds, verts, MV.LIFT_MONSTER_SPECIALS)
    assert {t[0] for t in mon} == {44}, "a monster triggers 88 (sector 44's lines) and no blazing 120"
    allw = MV.lift_walk_triggers(secs, lds, sds, verts)
    assert sum(t[0] == 47 for t in allw) == sum(t[0] == 209 for t in allw) == 4


def test_a_blazing_lift_strides_two_and_waits_as_a_lift():
    n, st, tr = 5, (0, D.IDLE, 0, 0), []
    for f in range(40):
        st = MV.lift_tic(st, n, f == 0, stride=2)
        tr.append(st[0])
    assert tr[:3] == [2, 4, 4], tr
    assert tr.count(4) == MV.LIFT_WAIT + 1 and tr[-1] == 0          # the arrival frame and LIFT_WAIT more


def test_floor_trigger_and_tic():
    assert MV.floor_trigger(0, 0, 0) == (1, 0)            # instant
    assert MV.floor_trigger(0, 0, 4) == (0, 4)            # starts its timer
    assert MV.floor_trigger(1, 0, 4) == (1, 0) and MV.floor_trigger(0, 3, 4) == (0, 3)   # fired once
    s, u, tr = 0, 4, []
    for _ in range(20):
        s, u = MV.floor_tic(s, u, 4, 4)
        tr.append(s)
    assert tr == [0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3] + [3] * 8 and u == 0


# ---- slanted lines ------------------------------------------------------------------------------------------------

def test_the_slanted_side_is_point_on_line_side_away_from_the_line(m2):
    """line_side agrees with P_PointOnLineSide (reference_model, FixedMul truncation) wherever the cross product is
    not within the truncation's reach of 0 -- the exact rule is the model's (both mirrors run it)"""
    _secs, lds, _sds, verts = m2
    gs = MV.floor_groups(*m2[:3])
    rng = random.Random(3)
    for _g, shape in MV.floor_walk_triggers(lds, verts, gs):
        if shape[0] != "d":
            continue
        _d, x1, y1, x2, y2 = shape
        for _ in range(400):
            x = (rng.randint(min(x1, x2) - 40, max(x1, x2) + 40) << 16) + rng.randint(0, U - 1)
            y = (rng.randint(min(y1, y2) - 40, max(y1, y2) + 40) << 16) + rng.randint(0, U - 1)
            s = (y - (y1 << 16)) * (x2 - x1) - (x - (x1 << 16)) * (y2 - y1)
            if abs(s) < abs(x2 - x1) * U + abs(y2 - y1) * U:
                continue
            assert MV.line_side(shape, x, y) == ReferenceModel.point_on_line_side(
                x, y, x1 << 16, y1 << 16, x2 << 16, y2 << 16), (shape, x, y)


def test_control_the_axis_extent_rule_parts_from_the_slanted_one(m2):
    """R9: testing a slanted line's extent on ONE axis (the axis lines' rule) fires where the slanted rule does not"""
    _secs, lds, _sds, verts = m2
    gs = MV.floor_groups(*m2[:3])
    shape = next(s for _g, s in MV.floor_walk_triggers(lds, verts, gs) if s[0] == "d")
    _d, x1, y1, x2, y2 = shape
    rng = random.Random(5)

    def one_axis(old, new):
        if MV.line_side(shape, *old) == MV.line_side(shape, *new):
            return False
        return ((min(x1, x2) - 16) << 16) < new[0] < ((max(x1, x2) + 16) << 16)
    differ = 0
    for _ in range(4000):
        new = ((rng.randint(min(x1, x2) - 60, max(x1, x2) + 60) << 16), (rng.randint(min(y1, y2) - 300,
                                                                                    max(y1, y2) + 300) << 16))
        old = (new[0] + rng.randint(-20 * U, 20 * U), new[1] + rng.randint(-20 * U, 20 * U))
        differ += MV.crossed_shape(shape, old, new, 16) != one_axis(old, new)
    assert differ > 0


# ---- the world ----------------------------------------------------------------------------------------------------

def test_e1m1_world_keeps_its_narrow_switch():
    w = W.World(skill=gd.SK_HARD, strict=True)
    assert w.layout.nfloor == 0 and not w.floor_wide
    f = [x for x in w.schema if x.name.startswith("f_")]
    assert [(x.name, x.bits, x.count, x.array) for x in f] == [("f_switch", 1, 1, False)]
    assert w.lift_walk_mon == w.lift_walk and w.lift_stride == [1, 1]


def test_e1m2_world_layout(w2):
    assert w2.floor_wide and w2.layout.nfloor == 11
    f = {x.name: (x.bits, x.count) for x in w2.schema if x.name.startswith("f_")}
    assert f == {"f_switch": (4, 11), "f_sub": (4, 11)}


def _cross(shape, g):
    """walk the player across axis line `shape` from 24 units on either side (a fresh world each) -> (the world, the
    frame the group fired) or (None, None)"""
    for sign in (1, -1):
        w = _w2()
        if shape[0] == "y":
            _a, y, x0, x1 = shape
            start, angle = (((x0 + x1) // 2) * U, (y - 24 * sign) * U), 0x40000000 if sign > 0 else 0xC0000000
        else:
            _a, x, y0, y1 = shape
            start, angle = ((x - 24 * sign) * U, ((y0 + y1) // 2) * U), 0 if sign > 0 else 0x80000000
        w.teleport_player(start[0], start[1], angle)
        for f in range(8):
            w.tic({"forward": True})
            if w.floor_sub(w.floor_groups.index(w.floor_groups[g])) or w.floor_state(g):
                return w, f
    return None, None


def test_a_w1_floor_lowers_over_frames_and_fires_once():
    g = 1                                        # tag 4: W1 38, sectors 53 and 352 (304 -> 240)
    shape = next(s for gg, s in _w2().floor_walk if gg == g)
    w2, f = _cross(shape, g)
    assert w2 is not None, "the player's walk across the W1 line fires it"
    grp = w2.floor_groups[g]
    assert w2.floor_sub(g) == grp.sub and w2.floor_state(g) == 0
    seen = []
    for _ in range(grp.sub * grp.n + 4):
        w2.tic({})
        seen.append(w2.floor_state(g))
    assert seen[grp.sub - 1] == 1 and seen[-1] == grp.n - 1 and w2.floor_sub(g) == 0
    assert w2.heights_now[53][0] == 240 and w2.secs_c[352].floor_h == 240
    w2.floor_fire(g)
    assert (w2.floor_state(g), w2.floor_sub(g)) == (grp.n - 1, 0), "fired once"


def test_each_s1_tag_fires_its_own_group(w2):
    g3 = next(k for k, g in enumerate(w2.floor_groups) if g.tag == 3)
    g13 = next(k for k, g in enumerate(w2.floor_groups) if g.tag == 13)
    (_g, (x0, y0, x1, y1)), = [e for e in w2.floor_use if e[0] == g3]
    w2.teleport_player(((x0 + x1) // 2) * U, ((y0 + y1) // 2 + 40) * U)
    w2.ws.p_usedown = 0
    w2.tic({"use": True})
    assert w2.floor_state(g3) == 1 and w2.floor_state(g13) == 0
    assert w2.heights_now[45][0] == 240 and 240 not in w2.heights_now


def test_control_one_switch_cell_fires_both_tags(w2):
    """R9: E1M2 with ONE fswitch cell for both 23 tags (the pre-F1.3 machine) lowers tag 13's sectors on tag 3's press"""
    sw = MV.switch_sectors(w2.secs, w2.lds, w2.sds)
    assert {45, 240} <= set(sw)
    lowered = MV.mover_heights(w2.secs, {}, {}, sw, True)
    assert 240 in lowered, "the one-cell machine moves the other tag's floor"


def test_a_monster_crossing_a_blazing_wr_line_does_nothing(w2):
    (si, axis, coord, lo, hi) = next(t for t in w2.lift_walk if t[0] == 47)
    k47, k209 = w2.lift_order.index(47), w2.lift_order.index(209)
    m = 0
    old = ((lo + hi) // 2, coord - 8) if axis == "y" else (coord - 8, (lo + hi) // 2)
    new = ((lo + hi) // 2, coord + 8) if axis == "y" else (coord + 8, (lo + hi) // 2)
    w2.ws.mon_x[m], w2.ws.mon_y[m] = old
    w2._move_monster(m, new[0], new[1], 0, W.TicEvents(0), step=False)
    assert w2.ws.l_req[k47] == 0 and w2.ws.l_req[k209] == 0
    # the player's crossing of the same line starts BOTH lifts of the tag
    w2._walkover(old[0] * U, old[1] * U, new[0] * U, new[1] * U)
    assert w2.ws.l_req[k47] == 1 and w2.ws.l_req[k209] == 1


# ---- the pickup on a mover's floor (item 9) ---------------------------------------------------------------------

def test_the_blue_card_rides_the_switch_floor(w2):
    i = next(k for k, t in enumerate(w2.pickup_things) if t.type == 5)
    assert w2.pickup_on_mover[i] and w2.pickup_sector[i] == 45 and w2.pickup_z[i] == 304
    t = w2.pickup_things[i]
    g3 = next(k for k, g in enumerate(w2.floor_groups) if g.tag == 3)
    # standing at 240 (the floor around), the card at 304 is out of reach (64 > 56) until the switch lowers it
    assert not w2._touch(5, False, w2.secs_c[45].floor_h, 240)
    w2.floor_fire(g3)
    assert w2.secs_c[45].floor_h == 240
    ev = W.TicEvents(0)
    w2._touch_specials(t.x * U, t.y * U, 240, ev)
    assert ("item", i, 5) in ev.pickups and w2.ws.pickup_taken[i]


def test_control_the_static_z_refuses_the_lowered_card(w2):
    """R9: with the card's z the STORED floor (304, the pre-F1.3 rule), the player at 240 after the switch cannot
    take it -- the live floor is what lets him"""
    i = next(k for k, t in enumerate(w2.pickup_things) if t.type == 5)
    g3 = next(k for k, g in enumerate(w2.floor_groups) if g.tag == 3)
    w2.floor_fire(g3)
    assert not w2._touch(5, False, w2.pickup_z[i], 240)
    assert w2._touch(5, False, w2.secs_c[w2.pickup_sector[i]].floor_h, 240)


def test_mover_heights_now_is_mover_phase_heights(w2):
    """the gates' MoverPhase and the model agree on the heights through a run of fires and tics"""
    mp = MV.MoverPhase(w2.secs, w2.lds, w2.sds, w2.mw.vertexes("E1M2"))
    st = mp.initial()
    rng = random.Random(9)
    for f in range(120):
        w2._movers_phase(W.TicEvents(0))
        st = mp.tic(st)
        for g in range(len(w2.floor_groups)):
            if rng.random() < 0.03:
                w2.floor_fire(g)
                fs = mp._fs(st[2])
                fs[g] = MV.floor_trigger(*fs[g], w2.floor_groups[g].sub)
                st = (st[0], st[1], mp._sw(fs))
        assert mp.heights(st) == w2.mover_heights_now(), f
        assert list(st[2]) == list(w2.ws.f_switch) + list(w2.ws.f_sub)


# ---- 10b: the one line between two cells (E1M2's 1199: blazing lift 47 / S1 floor 206) ---------------------------

def _line_1199(w):
    ld = w.lds[1199]
    return w.sds[ld.front].sector, w.sds[ld.back].sector


def test_the_two_cell_line_reads_the_cell_its_opening_depends_on(w2):
    """for EVERY pair of states the model's heights give the opening line_states' cell gives (sight, sound, missiles),
    and the collision's opening floor / low floor are 206's / 47's (mover_line_states)"""
    from doomfj import monstersight as MS
    from doomfj import monstermove as MM
    from doomfj.collision import mover_line_states
    a, b = _line_1199(w2)
    assert {a, b} == {47, 206}
    cell, n, pairs = MS.line_states(w2, a, b)
    g206 = next(k for k, g in enumerate(w2.floor_groups) if 206 in g.sectors)
    assert cell == MV.switch_cell(g206)
    k47 = w2.lift_order.index(47)
    ci = MM.world_cell_inputs(w2, D.DEFAULT_QUANT)
    ob = mover_line_states(w2.lds, w2.sds, ci["msecs"], ci["mcell"], max)[1199]
    lf = mover_line_states(w2.lds, w2.sds, ci["msecs"], ci["mcell"], min)[1199]
    assert ob[0] == cell and lf[0] == "lstate + %d*dw" % k47
    for i in range(len(w2.lift_stops[47])):
        for j in range(w2.floor_groups[g206].n):
            w2.ws.l_state[k47], w2.ws.f_switch[g206] = i, j
            w2._door_phase_scene()
            h = w2.heights_now
            (fa, ca), (fb, cb) = (h.get(s, (w2.secs[s].floor_h, w2.secs[s].ceil_h)) for s in (a, b))
            (pa, qa), (pb, qb) = pairs[j]
            assert min(ca, cb) - max(fa, fb) == min(qa, qb) - max(pa, pb), (i, j)
            assert max(fa, fb) == ob[1][j] and min(fa, fb) == lf[1][i], (i, j)


def test_control_the_lifts_cell_cannot_read_line_1199(w2):
    """R9: read through the LIFT's cell (its state, 206 at rest), the opening parts from the model's on some pair"""
    from doomfj import monstersight as MS
    a, b = _line_1199(w2)
    ca, na, ha = MS.closed_states(w2, 47)
    g206 = next(k for k, g in enumerate(w2.floor_groups) if 206 in g.sectors)
    k47 = w2.lift_order.index(47)
    parted = 0
    for i in range(na):
        for j in range(w2.floor_groups[g206].n):
            w2.ws.l_state[k47], w2.ws.f_switch[g206] = i, j
            w2._door_phase_scene()
            h = w2.heights_now
            (fa, ca_), (fb, cb_) = (h.get(s, (w2.secs[s].floor_h, w2.secs[s].ceil_h)) for s in (a, b))
            (pa, qa), (pb, qb) = (ha[i].get(s, (w2.secs[s].floor_h, w2.secs[s].ceil_h)) for s in (a, b))
            parted += min(ca_, cb_) - max(fa, fb) != min(qa, qb) - max(pa, pb)
    assert parted
