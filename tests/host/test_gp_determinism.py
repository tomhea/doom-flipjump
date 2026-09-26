"""S3a: the model is a pure function of (skill, key script) -- same inputs, same trajectory hash,
tic by tic; independent of Python's hash seed; and the hash can tell two different games apart."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import world as W

ROOT = Path(__file__).resolve().parents[2]

# a walk that turns, presses use, fires (noise) and stops: 160 tics of the parts S3a has
SCRIPT_SRC = """
def keys():
    out = []
    for t in range(160):
        k = {}
        if t < 60 or 80 <= t < 120:
            k["forward"] = True
        if 60 <= t < 70:
            k["turn_left"] = True
        if 120 <= t < 128:
            k["turn_right"] = True
        if t in (30, 31, 90):
            k["use"] = True
        if t % 25 == 5:
            k["fire"] = True
        out.append(k)
    return out
"""
_ns = {}
exec(SCRIPT_SRC, _ns)
KEYS = _ns["keys"]()


def _trajectory(skill=gd.SK_HARD, keys=KEYS, strict=False):
    w = W.World(skill=skill, strict=strict)
    return [(w.tic(k), w.digest())[1] for k in keys], w


def test_same_inputs_same_trajectory():
    a, wa = _trajectory()
    b, wb = _trajectory()
    assert a == b
    assert sum(len(ev.moves) for ev in wa.events) > 0            # something happened (vacuity)
    assert sum(len(ev.wakes) for ev in wa.events) > 0


def test_the_hash_tells_different_games_apart():
    """R9 for the hash: one changed key, or another skill, must change the trajectory."""
    base, _ = _trajectory()
    keys = [dict(k) for k in KEYS]
    keys[40]["turn_left"] = True
    changed, _ = _trajectory(keys=keys)
    assert changed[:40] == base[:40] and changed[-1] != base[-1]
    other, _ = _trajectory(skill=gd.SK_MEDIUM)
    assert other[0] != base[0]


def test_no_field_overflows_its_declared_width():
    """strict=True raises on any write outside a field's range, so a whole walk plus an all-awake
    fight proves the widths hold what the model writes."""
    _t, w = _trajectory(strict=True)
    w.wake_all()
    for _ in range(200):
        w.tic({})


RUNNER = SCRIPT_SRC + """
from doomfj import world as W, gamedata as gd
w = W.World(skill=gd.SK_HARD)
for k in keys():
    w.tic(k)
print(w.digest())
"""


def test_the_trajectory_does_not_depend_on_the_hash_seed():
    """Set or dict iteration order leaking into the game would show up as a different digest under
    another PYTHONHASHSEED."""
    got = set()
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, "-c", RUNNER], capture_output=True, text=True,
                           cwd=ROOT, env=env, timeout=300)
        assert r.returncode == 0, r.stderr[-2000:]
        got.add(r.stdout.strip())
    assert len(got) == 1
    here, _ = _trajectory()
    assert got == {here[-1]}
