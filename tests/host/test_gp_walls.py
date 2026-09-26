"""S3a: monsters cannot cross one-sided lines.

Every monster is woken and left to chase the player for a few hundred tics with no K cap, so they
press into walls from every side. After every tic, each monster that moved is checked two ways:
its centre's path must not touch a one-sided line, and its box must not straddle one. The negative
control runs the same fight with the line test switched off and requires the check to fire."""
import pytest

from doomfj import gamedata as gd
from doomfj import world as W


def _violations(w, tics):
    walls = [((ax, ay), (bx, by), (x0, x1, y0, y1))
             for (_li, x0, x1, y0, y1, ax, ay, bx, by, one, _f, _fs, _bs) in w._lines if one]
    ws, bad, moves = w.ws, [], 0
    for _ in range(tics):
        before = {m: (ws.mon_x[m], ws.mon_y[m]) for m in range(w.layout.nmon)}
        ev = w.tic({})
        moves += len(ev.moves)
        for m in set(ev.moves):
            p = (before[m][0] << 16, before[m][1] << 16)
            q = (ws.mon_x[m] << 16, ws.mon_y[m] << 16)
            r = w.mon_radius[m] << 16
            box = (q[1] + r, q[1] - r, q[0] - r, q[0] + r)          # top, bottom, left, right
            for a, b, (x0, x1, y0, y1) in walls:
                if W.segments_touch(p, q, a, b):
                    bad.append(("crossed", m, a, b))
                elif not (box[3] <= x0 or box[2] >= x1 or box[0] <= y0 or box[1] >= y1) \
                        and w.rm.box_on_line_side(box, *a, *b) == -1:
                    bad.append(("straddles", m, a, b))
    return bad, moves


def test_monsters_never_cross_or_straddle_a_one_sided_line():
    w = W.World(skill=gd.SK_HARD, k_heavy=53)
    w.wake_all()
    bad, moves = _violations(w, 250)
    assert not bad, bad[:5]
    assert moves > 500                                                   # vacuity: they moved
    assert sum(ev.blocked[W.V_WALL] for ev in w.events) > 100            # ... and hit walls


def test_the_check_fires_when_walls_are_switched_off(monkeypatch):
    """R9: with the line test answering "clear" everywhere, monsters walk through walls and the
    same check must catch it."""
    real = W.World.check_lines

    def no_walls(self, x16, y16, r16, *, monster):
        v, f, c, d = real(self, x16, y16, r16, monster=monster)
        return W.OK, f, c, d
    monkeypatch.setattr(W.World, "check_lines", no_walls)
    w = W.World(skill=gd.SK_HARD, k_heavy=53)
    w.wake_all()
    bad, _moves = _violations(w, 250)
    assert bad
