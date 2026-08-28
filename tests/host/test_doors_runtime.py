"""M2-R3/R4 — the runtime door's state model, trigger and state machine.

`tests/host/test_doors.py` covers the R2 geometry (which sectors are doors, where they stop). This
covers what R3/R4 added on top: the STATE INDEX both mirrors address a door by, the box that
decides a door was used, and the tic machine that walks the index. The fj side is a
transliteration of `door_tic`, so every rule pinned here is a rule the emitted program obeys.
"""
import pytest

from doomfj.doors import (CLOSING, DEFAULT_QUANT, IDLE, MAX_STATES, OPENING, SHUT, SPEED, WAIT,
                          door_states, door_tic, heights_for_states, in_use_box, initial_states,
                          open_enough, pass_state, use_boxes_xy)
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

E1M1 = "tests/fixtures/freedoom_e1m1.wad"


@pytest.fixture(scope="module")
def m():
    w = WadFile.from_path(E1M1)
    return (w.sectors("E1M1"), w.linedefs("E1M1"), w.sidedefs("E1M1"),
            bake_bsp(w, "E1M1").vertexes)


# ── the state table ────────────────────────────────────────────────────────────────────────────

def test_state_zero_is_shut_and_the_last_is_open(m):
    """The two ends are load-bearing everywhere else: state 0 must be the map as stored (so a
    doors=True build renders the stock picture until something writes a nibble) and the last state
    must be fully open (so `pass_state` and the tic machine have a real terminal)."""
    secs, lds, sds, _v = m
    tbl = door_states(secs, lds, sds)
    assert len(tbl) == 13
    for si, st in tbl.items():
        assert st[0] == secs[si].floor_h
        assert st == sorted(st) and len(set(st)) == len(st)


def test_the_state_index_fits_the_fj_nibble(m):
    """fj dispatches these with a ONE-NIBBLE switch. A door with more stops than that cannot be
    addressed, and the failure has to be at emit time -- a silent truncation would render state 17
    as state 1, which looks like a door that opens part-way and stops."""
    secs, lds, sds, _v = m
    assert max(len(v) for v in door_states(secs, lds, sds).values()) <= MAX_STATES
    with pytest.raises(AssertionError, match="past the"):
        door_states(secs, lds, sds, quant=1)      # 1-unit steps: hundreds of stops


def test_heights_for_states_is_the_same_override_the_emitter_takes(m):
    secs, lds, sds, _v = m
    tbl = door_states(secs, lds, sds)
    shut = heights_for_states(secs, lds, sds, {})
    assert all(c == secs[si].floor_h for si, (_f, c) in shut.items())
    opn = heights_for_states(secs, lds, sds, {si: len(v) - 1 for si, v in tbl.items()})
    assert all(c == tbl[si][-1] for si, (_f, c) in opn.items())


def test_an_out_of_range_state_is_refused_not_clamped(m):
    """Clamping would render a picture neither mirror asked for. The two sides enumerate states
    independently, so a disagreement about how many there are must be loud."""
    secs, lds, sds, _v = m
    si = sorted(door_states(secs, lds, sds))[0]
    with pytest.raises(AssertionError, match="out of range"):
        heights_for_states(secs, lds, sds, {si: 99})


def test_pass_state_is_the_first_state_you_fit_through(m):
    """The runtime collision test is `state >= pass_state`, so this number IS the door's
    passability. It must agree with the height rule it stands in for, at every state."""
    secs, lds, sds, _v = m
    for si, st in door_states(secs, lds, sds).items():
        k = pass_state(secs, lds, sds, si)
        for j in range(len(st)):
            assert open_enough(secs, lds, sds, si, j) == (j >= k), (si, j, k)


# ── the trigger box ────────────────────────────────────────────────────────────────────────────

def test_every_door_has_a_use_box_containing_its_own_lines(m):
    secs, lds, sds, verts = m
    boxes = use_boxes_xy(secs, lds, sds, verts)
    assert set(boxes) == set(door_states(secs, lds, sds))
    for si, (x0, y0, x1, y1) in boxes.items():
        assert x0 < x1 and y0 < y1


def test_the_use_box_is_inflated_by_the_use_range(m):
    """The box is the door's lines grown by USE_RANGE. Growing by 0 must give a strictly smaller
    box -- otherwise the inflation is not happening and the player has to stand ON the line."""
    secs, lds, sds, verts = m
    si = sorted(door_states(secs, lds, sds))[0]
    tight = use_boxes_xy(secs, lds, sds, verts, rng=0)[si]
    wide = use_boxes_xy(secs, lds, sds, verts, rng=64)[si]
    assert wide[0] == tight[0] - 64 and wide[2] == tight[2] + 64
    assert wide[1] == tight[1] - 64 and wide[3] == tight[3] + 64


def test_in_use_box_is_inclusive_on_the_edge():
    box = (-10, -20, 30, 40)
    assert in_use_box(box, -10, -20) and in_use_box(box, 30, 40) and in_use_box(box, 0, 0)
    assert not in_use_box(box, -11, 0) and not in_use_box(box, 0, 41)


# ── the tic machine ────────────────────────────────────────────────────────────────────────────

N = 9                     # E1M1's widest door


def run(tics, used_at=(), n=N, st=None):
    """Drive one door for `tics` tics, pressing use at the listed tic numbers. Returns the state
    index after each tic -- the sequence a player actually sees."""
    st = st or (SHUT, IDLE, 0, 0)
    out = []
    for t in range(tics):
        st = door_tic(st, n, used=t in used_at)
        out.append(st[0])
    return out, st


def test_an_untouched_door_never_moves():
    """The most important property of the whole rung: with no press, every one of these tics has
    to leave the nibble at 0, because a door that drifts open on its own would move pixels in
    every gate that never touched it."""
    seq, st = run(500)
    assert set(seq) == {0} and st == (SHUT, IDLE, 0, 0)


def test_a_press_opens_the_door_one_step_every_SPEED_tics():
    seq, _st = run(SPEED * (N - 1), used_at=(0,))
    # The press tic is itself the first of the SPEED tics, so the first step lands ON tic SPEED-1,
    # not after it. (The `sub` counter is set to SPEED by the press and then decremented by the
    # same tic's OPENING branch -- one machine, one pass per tic.)
    assert seq[:SPEED - 1] == [0] * (SPEED - 1) and seq[SPEED - 1] == 1
    assert seq[-1] == N - 1                            # ...and it is fully open at the end
    steps = [i for i in range(1, len(seq)) if seq[i] != seq[i - 1]]
    assert all(b - a == SPEED for a, b in zip(steps, steps[1:]))


def test_it_waits_open_then_closes_by_itself():
    total = SPEED * (N - 1) + WAIT + SPEED * (N - 1) + 2
    seq, st = run(total, used_at=(0,))
    assert max(seq) == N - 1
    assert seq[-1] == SHUT and st[1] == IDLE
    # Fully open for the wait PLUS the SPEED tics the first downward step takes: `wait` running
    # out only sets CLOSING and reloads `sub`, and the height does not move until `sub` reaches 0.
    open_for = sum(1 for v in seq if v == N - 1)
    assert open_for == WAIT + SPEED


def test_a_press_while_closing_reverses_it():
    """DOOM reverses a closing door rather than letting it shut on you. The state index must go
    back UP from wherever it had got to, not restart from 0."""
    opened = SPEED * (N - 1)
    seq, _st = run(opened + WAIT + SPEED * 3, used_at=(0,))
    mid = seq[-1]
    assert 0 < mid < N - 1, "the door should be part-way shut here"
    more, st = run(SPEED * 2, used_at=(0,), st=_st)
    assert more[-1] > mid and st[1] in (OPENING, IDLE)


def test_a_press_on_a_fully_open_door_restarts_the_wait():
    opened = SPEED * (N - 1)
    seq, st = run(opened, used_at=(0,))
    assert seq[-1] == N - 1 and st[3] == WAIT
    _s2, st2 = run(WAIT // 2, st=st)
    assert st2[3] < WAIT
    _s3, st3 = run(1, used_at=(0,), st=st2)
    # Back to the top of the wait, less the press tic itself -- the point being that it went UP,
    # from half-elapsed to full, rather than continuing to run down.
    assert st3[3] > st2[3] and st3[3] == WAIT - 1, "using an open door must hold it open"


def test_a_shorter_door_terminates_on_its_own_last_state():
    """Doors have DIFFERENT numbers of stops (E1M1: 5, 6 and 9). A machine that assumed one length
    would drive the short ones past their table -- an out-of-range nibble, which the switch would
    dispatch into padding."""
    for n in (2, 5, 6, 9):
        seq, st = run(SPEED * n + 4, used_at=(0,), n=n)
        assert max(seq) == n - 1 and st[0] == n - 1
        assert all(0 <= v <= n - 1 for v in seq)


def test_initial_states_match_what_the_emitter_bakes(m):
    """`dstate: hex.vec <ndoors>, 0` is the emitted declaration, so the oracle has to start every
    door at exactly that -- shut, idle, no timers."""
    secs, lds, sds, _v = m
    init = initial_states(secs, lds, sds)
    assert set(init) == set(door_states(secs, lds, sds))
    assert set(init.values()) == {(SHUT, IDLE, 0, 0)}
