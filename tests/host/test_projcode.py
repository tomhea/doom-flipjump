"""M7 P5 (doomfj.projcode): the host half of the fireball and blood pools -- the tables against the model's own
sources, and the missile cells' COVERAGE proof (a radius-6 box is narrower than a 32-unit cell, so
`collision.cell_lists`' corner argument does not apply and the lists carry their own proof).

The proof: a box of half-width r centred at P escapes the bbox reject of a line iff, on BOTH axes, P lies in the OPEN
interval (min - r, max + r) of that axis. Each axis' escape set is an interval around [min, max], so if any centre of
a cell escapes on an axis, the centre of the cell NEAREST to [min, max] on that axis does too; the axes are
independent. So a cell may leave a line out exactly when its nearest point P* to the line's bbox is rejected -- the
test checks that at P* for every (cell, line) pair the lists leave out within reach, and the control (lists built at
radius 0) must fail it.
"""
import pytest

from doomfj import gamedata as gd
from doomfj import projcode as PC
from doomfj import rng as R
from doomfj.collision import CELL_SHIFT, cell_lists
from doomfj.combat import FIREBALL_INFO, FIREBALL_R, fireball_momentum_table, site_formulas
from doomfj.world import World

S = 1 << CELL_SHIFT


@pytest.fixture(scope="module")
def world():
    return World(monsters="full", player="full")


def test_the_momentum_is_ten_finesines(world):
    """the fj's x10 (`_times10`) on finesine at angle >> 20 is the model's FixedMul(speed, ...) table, all 4096"""
    assert PC.momentum_values(world.rm) == fireball_momentum_table(world.rm)
    assert len(PC.momentum_values(world.rm)) == 4096


def test_the_x10_wraps_like_the_model(world):
    """the fj multiplies the 32-bit word: 10 * v mod 2^32 read signed is 10 * v (|v| <= 1.0 in 16.16)"""
    for i in range(world.rm.cfg.TRIG_N):
        v = world.rm._finesin_idx(i) & 0xFFFFFFFF
        s = v - (1 << 32) if v >> 31 else v
        w10 = (10 * v) & 0xFFFFFFFF
        assert (w10 - (1 << 32) if w10 >> 31 else w10) == 10 * s


def test_fxrnd_is_the_two_sites():
    """fxrnd's row for every stream state = the fireball hit's damage and the tics roll of the SAME draw"""
    f = site_formulas(lambda s: 0)
    vals = PC.fxrnd_values()
    for st in range(1 << R.STATE_BITS):
        v, nxt = R.p_random(st)
        row = vals[nxt]
        assert row & 0xFF == f["fireball_hit"][1](v) == (v % 8 + 1) * 3
        assert row >> 8 == f["tics_roll"][1](v) == v & 3


def test_pjst_is_p_setmobjstate():
    vals = PC.pjst_values()
    for s in PC.pool_states():
        nxt = gd.STATES[s].next
        if nxt == gd.S_NULL:
            assert vals[gd.STATE_INDEX[s]] == 0
        else:
            assert vals[gd.STATE_INDEX[s]] == gd.STATE_INDEX[nxt] | gd.STATES[nxt].tics << 8
    assert set(PC.pool_states()) >= {FIREBALL_INFO.spawnstate, FIREBALL_INFO.deathstate, "S_BLOOD1", "S_BLOOD2",
                                     "S_BLOOD3"}
    PC.check_model_rules()


def _uncovered(rows, lists, r):
    """(cell, line) pairs some box of half-width r centred in the cell can reach (no bbox reject) but the cell's
    list leaves out -- the nearest-point argument of the module docstring"""
    bad = []
    for li, row in enumerate(rows):
        minx, maxx, miny, maxy = (v << 16 for v in row[4:8])
        for cx in range((minx - r) // S - 1, (maxx + r) // S + 2):
            xa, xb = cx * S, cx * S + S - 1
            px = min(max(xa, minx), xb)             # the cell's x nearest to [minx, maxx]
            if not (minx - r < px < maxx + r):
                continue
            for cy in range((miny - r) // S - 1, (maxy + r) // S + 2):
                ya, yb = cy * S, cy * S + S - 1
                py = min(max(ya, miny), yb)
                if not (miny - r < py < maxy + r):
                    continue
                if li not in lists.get((cx, cy), ()):
                    bad.append(((cx, cy), li))
    return bad


def test_the_missile_cells_cover_every_reachable_line(world):
    rows, _doors = PC.missile_rows(world)
    lists = PC.missile_cell_lists(rows)
    assert not _uncovered(rows, lists, FIREBALL_R << 16)


def test_control_lists_without_the_margin_leave_lines_out(world):
    rows, _doors = PC.missile_rows(world)
    bad = _uncovered(rows, cell_lists(rows, 0, corner=False), FIREBALL_R << 16)
    assert len(bad) > 100, len(bad)


def test_the_missile_rows_are_the_models_rules(world):
    """per line, at every state of its dynamic sector (the model's heights_now), the row's verdict for a box that
    straddles it = missile_lines_block's rule: one-sided, or the opening under FIREBALL_H"""
    from doomfj.collision import FLAG_BLOCKING, FLAG_ONE_SIDED
    from doomfj.combat import FIREBALL_H
    rows, doors = PC.missile_rows(world)
    w, ws = world, world.ws
    nd = len(w.door_order)
    for k in range(10):
        for d, si in enumerate(w.door_order):
            ws.d_state[d] = min(k, w.door_nstates[si] - 1)
        for j, si in enumerate(w.lift_order):
            ws.l_state[j] = min(k, len(w.lift_stops[si]) - 1)
        ws.f_switch = k & 1
        w._door_phase_scene()
        for li, ld in enumerate(w.lds):
            if ld.back == -1:
                want = True
            else:
                (ff, fc), (bf, bc) = (w._sector_hts(w.sds[ld.front].sector), w._sector_hts(w.sds[ld.back].sector))
                want = min(fc, bc) - max(ff, bf) < FIREBALL_H
            got = bool(rows[li][9] & (FLAG_ONE_SIDED | FLAG_BLOCKING))
            for slot, p in doors.get(li, ()):
                st = ws.f_switch if isinstance(slot, str) else ws.d_state[slot]
                assert slot == "fswitch" or 0 <= slot < nd
                got = got or st < p
            assert got == want, (li, k)
    w.reset(w.ws.skill)
