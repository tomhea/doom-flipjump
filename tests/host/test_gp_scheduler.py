"""S3a: the K-slot scheduler -- never more than K heavy monster actions in a tic, deferral that is
deterministic, and deferred monsters served round robin (no starvation). Plan section 6.1, D5."""
import math

import pytest

from doomfj import gamedata as gd
from doomfj import world as W


def _all_awake(k, tics, policy=W.next_cursor):
    w = W.World(skill=gd.SK_HARD, k_heavy=k, cursor_policy=policy)
    w.wake_all()
    return w, [w.tic({}) for _ in range(tics)]


@pytest.mark.parametrize("k", [1, 3])
def test_never_more_than_k_heavy_acts_and_no_idle_slot_while_one_waits(k):
    w, evs = _all_awake(k, 120)
    assert all(len(ev.heavy) <= k for ev in evs)
    # work conserving: a monster waits only when all K slots were taken
    assert all(len(ev.heavy) == k for ev in evs if ev.deferred)
    assert sum(1 for ev in evs if ev.deferred) > 60          # the cap really bound (vacuity)
    assert not set(sum((ev.heavy for ev in evs), [])) & {m for m in range(w.layout.nmon)
                                                          if not w.ws.mon_active[m]}


def test_the_bound_holds_with_monsters_awake_by_play_too():
    """Not only the wake_all stress state: every door stands open and the player fires, so the
    shot carries through the level and monsters wake by SOUND (and some by sight) the way play
    wakes them -- more of them than K, so the cap has to bind."""
    w = W.World(skill=gd.SK_HARD)
    for d, si in enumerate(w.door_order):
        w.ws.d_state[d] = w.door_nstates[si] - 1
    w._door_phase_scene()
    keys = [{"fire": t % 7 == 0, "forward": t < 40, "turn_left": 40 <= t < 50} for t in range(200)]
    evs = w.run(keys)
    assert all(len(ev.heavy) <= W.K_HEAVY for ev in evs)
    wakes = [how for ev in evs for _m, how in ev.wakes]
    assert len(wakes) > 10 and "sound" in wakes
    assert sum(1 for ev in evs if ev.deferred) > 20


def test_deferral_is_deterministic():
    _w1, a = _all_awake(3, 100)
    _w2, b = _all_awake(3, 100)
    assert [(e.heavy, e.deferred) for e in a] == [(e.heavy, e.deferred) for e in b]
    assert _w1.digest() == _w2.digest()


def _longest_wait(evs, nmon):
    """The longest run of consecutive tics any monster spent deferred."""
    run, worst = [0] * nmon, 0
    for ev in evs:
        waiting = set(ev.deferred)
        for m in range(nmon):
            run[m] = run[m] + 1 if m in waiting else 0
            worst = max(worst, run[m])
    return worst


def test_deferred_monsters_are_served_round_robin():
    k = 3
    w, evs = _all_awake(k, 200)
    active = sum(w.ws.mon_active)
    bound = 2 * math.ceil(active / k)
    assert _longest_wait(evs, w.layout.nmon) <= bound
    served = {m for ev in evs for m in ev.heavy}
    assert served == {m for m in range(w.layout.nmon) if w.ws.mon_active[m]}


def test_the_fairness_check_catches_a_cursor_that_never_moves():
    """R9: plant a scheduler that always starts at slot 0 -- the high slots starve and the same
    check must say so."""
    k = 3
    w, evs = _all_awake(k, 200, policy=lambda cursor, first_deferred, n: 0)
    active = sum(w.ws.mon_active)
    assert _longest_wait(evs, w.layout.nmon) > 2 * math.ceil(active / k)


def test_cheap_actions_never_take_a_slot():
    """A_Look runs in the monster's own slot: with K = 0 the monsters that hear a shot still wake,
    and none of them ever takes a heavy action."""
    w = W.World(skill=gd.SK_HARD, k_heavy=0)
    evs = w.run([{"fire": True}] * 30)
    assert sum(len(ev.wakes) for ev in evs) > 0
    assert sum(len(ev.heavy) for ev in evs) == 0
    assert sum(len(ev.deferred) for ev in evs) > 0
