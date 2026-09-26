"""The model's geometric aim (`combat.CombatMixin.aim_geometric`) -- the aim the frozen combat set
was planned and replayed with: the NEAREST target covering the column wins, and a target behind a
wall is not hit. PR #87 review, finding 1: flipping the depth comparison or deleting the sight
check used to pass every gameplay test.

Every other monster is made unshootable and every barrel dead, so only the placed targets can
answer; each test has a control showing its target IS aimable when nothing is in the way.
"""
from doomfj import gamedata as gd
from doomfj import world as W

# (view angle in BAM, unit step in map units) for the four axes
AXES = ((0x00000000, (1, 0)), (0x40000000, (0, 1)), (0x80000000, (-1, 0)), (0xC0000000, (0, -1)))


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _world():
    w = W.World(skill=gd.SK_HARD)
    ws = w.ws
    for m in range(w.layout.nmon):
        ws.mon_shootable[m] = 0
    for b in range(len(w.barrel_things)):
        ws.bar_health[b] = 0
    return w


def _clear_run(w, step):
    """map units from the player to the first line that blocks 2D sight along `step`"""
    px, py = w.ws.px, w.ws.py
    for d in range(8, 2040, 4):
        if not w.los_points((px, py), (px + ((step[0] * d) << 16), py + ((step[1] * d) << 16))):
            return d
    return 2040


def _place(w, m, step, d):
    ws = w.ws
    w.teleport_monster(m, (s32(ws.px) >> 16) + step[0] * d, (s32(ws.py) >> 16) + step[1] * d)
    ws.mon_shootable[m] = 1


def _live_monsters(w, n):
    out = [m for m in range(w.layout.nmon) if w.ws.mon_active[m] and w.ws.mon_health[m] > 0]
    assert len(out) >= n
    return out[:n]


def _axis(w, want):
    """the first axis whose clear run satisfies `want(d)`"""
    for angle, step in AXES:
        d = _clear_run(w, step)
        if want(d):
            w.ws.pangle = angle
            return step, d
    raise AssertionError("no axis from the spawn fits this test")


def test_the_nearer_of_two_targets_in_a_column_wins():
    # the pair is placed BOTH ways -- the nearer in the higher slot, then in the lower -- so neither
    # "the first target in slot order wins" nor "the last one wins" passes (PR #88 round 3)
    lo, hi = _live_monsters(_world(), 2)
    for near, far in ((hi, lo), (lo, hi)):
        w = _world()
        step, _d = _axis(w, lambda d: d > 240)
        _place(w, near, step, 80)
        _place(w, far, step, 200)
        col = w.aim_centre
        assert W.World.aim_geometric(w, col) == ("mon", near), (near, far)
        w.ws.mon_shootable[near] = 0            # control: without the nearer, the farther answers
        assert W.World.aim_geometric(w, col) == ("mon", far), (near, far)


def test_a_target_behind_a_wall_is_not_hit():
    w = _world()
    step, d = _axis(w, lambda d: 120 <= d < 1500)
    (c,) = _live_monsters(w, 1)
    _place(w, c, step, d + 48)                  # beyond the first sight-blocking line
    col = w.aim_centre
    assert W.World.aim_geometric(w, col) is None
    _place(w, c, step, d - 40)                  # control: in front of it, the same target is hit
    assert W.World.aim_geometric(w, col) == ("mon", c)
