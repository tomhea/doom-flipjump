"""M8 C11 -- the MIXED door, the model half (the fj half: tests/fj/test_door_stay_switch_fj.py).

E1M9's door 135 is a DR door (line 650, special 1) that an S1 103 switch (line 887) opens to STAY: `door_kinds` refused
it ("door 135 is asked two motions: ['plain', 'stay']"), the survey's "section doors/movers" with it. Now a switch may
ask the open-stay form of the door's own motion; such a press (`stay_switch_boxes`) runs door_tic's `stay_used`:
OPENING with wait = STAY_MARK, the top then sets no wait.

What must NOT move: every other map's switch boxes and door kinds (no mixed door before E1M9), and door_tic itself on
every state a door can reach without `stay_used` -- its OPENING wait is always 0 there, so the top's new rule
(`0 if wait else top_wait`) is the old one. The World (`_doors_phase`) mirrors DoorPhase on E1M9's door 135.

R9: the pre-C11 door_tic (verbatim below) differs from the new one on a mixed press; the World with its stay switches
dropped parts from DoorPhase.
"""
from pathlib import Path

import pytest

from doomfj import doors as D
from doomfj import gamedata as gd
from doomfj.doors import CLOSING, IDLE, OPENING, SPEED, STAY_MARK, WAIT, door_tic
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not FULL.exists(), reason="the full episode wad is not present")
MAPS = ["E1M%d" % i for i in range(1, 10) if i != 8]


def old_door_tic(st, nstates, used, stride=1, stay=False, wait_frames=WAIT, blocked=False, pass_at=0):
    """doors.door_tic before M8 C11, verbatim"""
    state, dr, sub, wait = st
    top_wait = 0 if stay else wait_frames
    if used and dr != OPENING:
        if stay and state == nstates - 1:
            return st
        dr, sub, wait = OPENING, SPEED, 0
        if state == nstates - 1:
            dr, wait = IDLE, top_wait
    if dr == OPENING:
        sub -= 1
        if sub == 0:
            sub = SPEED
            state += stride
            if state >= nstates - 1:
                state, dr, wait = nstates - 1, IDLE, top_wait
    elif dr == CLOSING:
        sub -= 1
        if sub == 0:
            sub = SPEED
            if blocked and state >= pass_at > state - stride:
                return (state, OPENING, sub, wait)
            state -= stride
            if state <= 0:
                state, dr = 0, IDLE
    elif wait:
        wait -= 1
        if wait == 0:
            dr, sub = CLOSING, SPEED
    return (state, dr, sub, wait)


@pytest.fixture(scope="module")
def wad():
    return WadFile.from_path(str(FULL))


def _geo(wad, m):
    return wad.sectors(m), wad.linedefs(m), wad.sidedefs(m), wad.vertexes(m)


@pytest.mark.parametrize("m", MAPS)
def test_only_e1m9_has_a_mixed_door(wad, m):
    secs, lds, sds, v = _geo(wad, m)
    mixed = D.stay_switch_boxes(secs, lds, sds, v)
    assert mixed == ({135: [(128, 3456, 320, 3584)]} if m == "E1M9" else {})
    if m == "E1M9":
        assert D.door_kinds(secs, lds, sds)[135] == "plain"
    else:
        # the switch boxes as they were: every switch door trigger's box under every door it names
        old = {}
        for box, targets, _once in D.switch_door_triggers(secs, lds, sds, v):
            for si in targets:
                old.setdefault(si, []).append(box)
        assert D.switch_boxes(secs, lds, sds, v) == old


@pytest.mark.parametrize("nstates, stride, stay, wait_frames", [(9, 1, False, WAIT), (9, 1, True, WAIT),
                                                                (13, 4, False, WAIT), (5, 1, False, 3)])
def test_door_tic_is_the_old_one_on_every_reachable_state(nstates, stride, stay, wait_frames):
    pass_at = nstates // 2
    seen, todo = set(), [(0, IDLE, 0, 0)]
    while todo:
        st = todo.pop()
        if st in seen:
            continue
        seen.add(st)
        for used in (False, True):
            for blocked in (False, True):
                kw = dict(stride=stride, stay=stay, wait_frames=wait_frames, blocked=blocked, pass_at=pass_at)
                new = door_tic(st, nstates, used, **kw)
                assert new == old_door_tic(st, nstates, used, **kw), (st, used, blocked)
                todo.append(new)
    assert all(w == 0 for (_s, dr, _u, w) in seen if dr == OPENING), "an OPENING door's wait is 0 before C11"
    assert len(seen) >= nstates


def test_the_stay_press():
    n = 9
    assert door_tic((0, IDLE, 0, 0), n, False, stay_used=True) == (1, OPENING, SPEED, STAY_MARK)   # one stop, marked
    st = (0, IDLE, 0, 0)
    for _ in range(n + 5):
        st = door_tic(st, n, False, stay_used=(st == (0, IDLE, 0, 0)))
    assert st == (n - 1, IDLE, SPEED, 0)                # at the top, no wait: it stays
    for _ in range(3 * WAIT):
        st = door_tic(st, n, False)
    assert st[:2] == (n - 1, IDLE) and st[3] == 0
    assert door_tic(st, n, False, stay_used=True) == st          # at the top: nothing
    st = door_tic(st, n, True)                                    # the DR at the top: a wait, then it closes
    assert st == (n - 1, IDLE, SPEED, WAIT - 1)               # (the wait already counting this tic)
    # R9: the pre-C11 machine has no stay press -- the same switch press leaves it shut
    assert old_door_tic((0, IDLE, 0, 0), n, False) == (0, IDLE, 0, 0)


def _world_e1m9(wad, monkeypatch):
    from doomfj.world import World
    unknown = {t.type for t in wad.things("E1M9")} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
    monkeypatch.setattr(gd, "NOT_THINGS", frozenset(gd.NOT_THINGS | unknown))   # C6 / C7's things left out
    return World(wad, "E1M9", strict=True)


def _drive(w, sched):
    from doomfj.world import TicEvents
    out = []
    for x16, y16, use in sched:
        w.ws.px, w.ws.py = x16, y16
        w._doors_phase({"use": use}, TicEvents(0))
        out.append(w.door_state(135))
    return out


def _sched(dp):
    def ctr(b):
        return ((b[0] + b[2]) // 2) << 16, ((b[1] + b[3]) // 2) << 16
    sw, dr = ctr(dp.stay_switches[135][0]), ctr(dp.boxes[135])
    away = (dr[0] + (400 << 16), dr[1] + (400 << 16))
    return ([(*sw, 1)] + [(*away, 0)] * (WAIT + 20) + [(*dr, 1)] + [(*away, 0)] * (WAIT + 20)
            + [(*sw, 1)] + [(*away, 0)] * 20)


def _phase(wad):
    from doomfj.mapcompiler import bake_bsp
    secs, lds, sds, v = _geo(wad, "E1M9")
    return D.DoorPhase(secs, lds, sds, v, D.use_boxes_xy(secs, lds, sds, bake_bsp(wad, "E1M9").vertexes))


def _expect(dp, sched):
    st, out = dp.initial(), []
    for x16, y16, use in sched:
        st = dp.tic(st, bool(use), x16, y16, has_blue=True, has_yellow=True, has_red=True)
        out.append(st[0][135])
    return out


def test_the_world_mirrors_doorphase_on_e1m9(wad, monkeypatch):
    dp = _phase(wad)
    sched = _sched(dp)
    w = _world_e1m9(wad, monkeypatch)
    assert w.door_stay_switches == dp.stay_switches
    want = _expect(dp, sched)
    assert _drive(w, sched) == want
    assert any(s[0] == dp.nstates[135] - 1 and s[3] == 0 for s in want[WAIT:WAIT + 20])     # held open past WAIT


def test_control_the_world_without_its_stay_switches_parts(wad, monkeypatch):
    dp = _phase(wad)
    sched = _sched(dp)
    w = _world_e1m9(wad, monkeypatch)
    w.door_stay_switches = {}
    assert _drive(w, sched) != _expect(dp, sched)
