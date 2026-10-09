"""M7 P8a I (docs/gp-final-plan.md 1.2.3, O-B2 TAKEN): the FAR LOS's covering, on the host -- `monstersight.far_pieces`
(the cells `sl_far` visits, its arithmetic in Python) and the NEAR cell lists (grown by NEAR_MARGIN) hold every sight
segment a monster -> monster trace can touch, at ANY range: testing the whole trace against the union of the visited
cells' lists IS `World.los_points`, on random pairs across E1M1 with every door, lift and the switch in random states.
R9: lists without their margin, and a walk that visits only the first piece's cell, each part from the model.
(tests/fj/test_far_los_fj.py runs the real fj text.)"""
import random

import pytest

from doomfj import monstersight as MS
from doomfj.world import World, segments_touch

N = 3000


@pytest.fixture(scope="module")
def world():
    return World(monsters="final", player="final", sight_rule="seen")


def _set_states(w, rng):
    for d, si in enumerate(w.door_order):
        w.ws.d_state[d] = rng.choice((0, 0, w.door_nstates[si] - 1, rng.randrange(w.door_nstates[si])))
    for k, si in enumerate(w.lift_order):
        w.ws.l_state[k] = rng.randrange(len(w.lift_stops[si]))
    w.ws.f_switch = rng.randrange(2)
    w._mh_last = None
    w._door_phase_scene()


def _blocks(w, s, p16, q16, box=None) -> bool:
    """one sight segment against the whole trace: sl_seg's box reject (on `box`, a run's; else the trace's), the
    dynamic state, the touch of the WHOLE trace"""
    x0, x1 = sorted((p16[0], q16[0]))
    y0, y1 = sorted((p16[1], q16[1]))
    if box is not None:
        x0, x1, y0, y1 = box
    if s["box"][1] << 16 < x0 or s["box"][0] << 16 > x1 or s["box"][3] << 16 < y0 or s["box"][2] << 16 > y1:
        return False
    if s["dyn"]:
        cell, _n, shut = s["dyn"]
        st = (w.ws.f_switch if cell == "fswitch" else
              w.ws.d_state[int(cell.split("+")[1].split("*")[0])] if cell.startswith("dstate") else
              w.ws.l_state[int(cell.split("+")[1].split("*")[0])])
        if st not in shut:
            return False
    a, b = (s["a"][0] << 16, s["a"][1] << 16), (s["b"][0] << 16, s["b"][1] << 16)
    return segments_touch(p16, q16, a, b)


def _far(w, segs, lists, p, q16, first_only=False) -> bool:
    """True when the trace is CLEAR, by the far walk's rule"""
    runs = MS.far_runs(p, q16)
    if first_only:
        runs = runs[:1]
    p16 = (p[0] << 16, p[1] << 16)
    for c, box in runs:
        for k in lists.get(c, ()):
            if _blocks(w, segs[k], p16, q16, box):
                return False
    return True


def _pairs(w):
    rng = random.Random(0x8A1)
    vs = w.cmap.vertexes
    x0, x1 = min(v[0] for v in vs), max(v[0] for v in vs)
    y0, y1 = min(v[1] for v in vs), max(v[1] for v in vs)
    segs = MS.sight_segments(w)
    out = []
    while len(out) < N:
        r = rng.random()
        if r < 0.5:                                    # anywhere in the map's box: long traces, every range
            p = (rng.randint(x0, x1), rng.randint(y0, y1))
            q = (rng.randint(x0, x1), rng.randint(y0, y1))
        else:                                          # across a segment's neighbourhood, at a random range
            s = segs[rng.randrange(len(segs))]
            t = rng.random()
            cx = int(s["a"][0] + t * (s["b"][0] - s["a"][0]))
            cy = int(s["a"][1] + t * (s["b"][1] - s["a"][1]))
            k = rng.choice((60, 200, 600, 1500))
            p = (cx + rng.randint(-k, k), cy + rng.randint(-k, k))
            q = (cx + rng.randint(-k, k), cy + rng.randint(-k, k))
            if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and x0 <= q[0] <= x1 and y0 <= q[1] <= y1):
                continue
        out.append((p, (q[0] << 16, q[1] << 16), rng.randrange(1 << 30)))
    return out


def test_far_pieces_stay_short(world):
    """every piece is at most PIECE units per axis and there are at most FAR_PIECES; the map fits"""
    m = MS.far_margin(world)
    assert m <= MS.FAR_PIECES * MS.PIECE
    rng = random.Random(1)
    for _ in range(500):
        p = (rng.randint(-704, 3248), rng.randint(-1064, 2336))
        q16 = (rng.randint(-704, 3248) << 16 | rng.randrange(1 << 16), rng.randint(-1064, 2336) << 16)
        runs = MS.far_runs(p, q16)
        assert runs[0][0] == (MS.cell_of(p[0]), MS.cell_of(p[1]))
        assert len(runs) <= MS.FAR_PIECES and len({c for c, _b in runs}) == len(runs), "a cell walked twice"
        x0, x1 = sorted((p[0] << 16, q16[0]))
        y0, y1 = sorted((p[1] << 16, q16[1]))
        assert all(x0 <= b[0] <= b[1] <= x1 and y0 <= b[2] <= b[3] <= y1 for _c, b in runs), "a box outside the trace's"


def test_the_union_of_the_cells_lists_is_the_los(world):
    w = world
    segs = MS.sight_segments(w)
    lists = MS.cell_lists(segs, MS.map_cells(w))
    pairs = _pairs(w)
    blocked = far_beyond = 0
    for p, q16, seed in pairs:
        _set_states(w, random.Random(seed))
        want = w.los_points((p[0] << 16, p[1] << 16), q16)
        assert _far(w, segs, lists, p, q16) == want, (p, q16)
        blocked += not want
        far_beyond += max(abs((q16[0] >> 16) - p[0]), abs((q16[1] >> 16) - p[1])) > MS.NEAR_UNITS
    assert N // 10 <= blocked <= N - N // 10, blocked          # both verdicts in volume
    assert far_beyond >= N // 2, far_beyond


@pytest.mark.parametrize("mut", ["margin", "first_piece", "runbox"])
def test_control_a_broken_covering_is_caught(world, mut):
    w = world
    segs = MS.sight_segments(w)
    saved = MS.NEAR_MARGIN
    if mut == "margin":
        MS.NEAR_MARGIN = 0
    try:
        lists = MS.cell_lists(segs, MS.map_cells(w))
    finally:
        MS.NEAR_MARGIN = saved
    bad = 0
    for p, q16, seed in _pairs(w):
        _set_states(w, random.Random(seed))
        if mut == "runbox":                            # each run's box without its + 1: a floor that loses a point
            saved_runs = MS.far_runs
            MS.far_runs = lambda a, b: [(c, (x0, max(x0, x1 - (1 << 16)), y0, max(y0, y1 - (1 << 16))))
                                        for c, (x0, x1, y0, y1) in saved_runs(a, b)]
        try:
            v = _far(w, segs, lists, p, q16, first_only=(mut == "first_piece"))
        finally:
            if mut == "runbox":
                MS.far_runs = saved_runs
        bad += v != w.los_points((p[0] << 16, p[1] << 16), q16)
    assert bad, "%s: the covering control parts nothing" % mut
