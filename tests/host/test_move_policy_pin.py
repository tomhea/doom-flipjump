"""Issue #123 item 5 (RECORDED, docs/gp-final-plan.md 1.4): the two move policies -- `ReferenceModel.move_with_collision`
(step_sim: the HOSTED tiers' walk, mirrored by their fj, which has no skip_still) and `combat._player_move` (the game
tier's model since a1da51a) -- differ ONLY by the still-candidate rule, and never in where the player ends up.

Both try the same three candidates (the full step, x only, y only), touching the pickups at each tried one and taking
the first `try_move` accepts. combat skips a candidate equal to the start comparing like with like (both signed);
move_with_collision compares the MASKED candidate with the SIGNED start, so at a negative coordinate the still
candidate is tried (and touched) instead of skipped. Changing it would move the hosted tiers' fj at the player start
(x = -416) and need a hosted rebuild no ship gate runs -- so it is pinned, not changed:

  (a) the real move_with_collision's tried sequence == the three-candidate loop with the MASKED rule, and the real
      _player_move's == the same loop with the SIGNED rule (the loop below is the one both implement; only the rule
      differs);
  (b) the final positions are equal on every case;
  (c) not vacuous: some case's two sequences differ (a still candidate at a negative coordinate, tried by the hosted
      policy only), and some still candidate at non-negative coordinates is skipped by both.
"""
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
M32 = 0xFFFFFFFF


def _signed(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


@pytest.fixture(scope="module")
def world():
    from doomfj.wad import WadFile
    from doomfj.world import World
    w = World(WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad")), "E1M1")
    w.player_blocking = False          # move_with_collision tests no things: compare the line policy alone
    return w


def _cases(w, n=1500, seed=0x123):
    """(x, y, angle, keys): points the player may stand on, many beside a wall (the refused steps), axis angles
    (a zero step component: a still candidate) and random ones"""
    rm, sc = w.rm, w.scene_c
    xs = [v[0] for v in w.cmap.vertexes]
    ys = [v[1] for v in w.cmap.vertexes]
    rnd = random.Random(seed)
    out = []
    keysets = [dict(forward=1), dict(back=1), dict(strafe_right=1), dict(strafe_left=1),
               dict(forward=1, strafe_left=1), dict(back=1, strafe_right=1)]
    while len(out) < n:
        x = rnd.randrange(min(xs), max(xs)) << 16 | rnd.randrange(1 << 16)
        y = rnd.randrange(min(ys), max(ys)) << 16 | rnd.randrange(1 << 16)
        if not rm.check_position(sc, x, y)[0]:
            continue
        ang = rnd.choice([0, 0x40000000, 0x80000000, 0xC0000000, rnd.randrange(1 << 32)])
        keys = {k: 0 for k in ("forward", "back", "strafe_left", "strafe_right", "turn_left", "turn_right")}
        keys.update(rnd.choice(keysets))
        out.append((x, y, ang, keys))
    return out


def _step(rm, x, y, ang, keys):
    """DOOM's P_MovePlayer step, as both policies compute it (FixedMul by the angle's cos / sin)"""
    from doomfj.fixedpoint import fixed_mul
    from doomfj.reference_model import FORWARD_MOVE, STRAFE_MOVE
    move = (FORWARD_MOVE if keys["forward"] else 0) - (FORWARD_MOVE if keys["back"] else 0)
    side = (STRAFE_MOVE if keys["strafe_right"] else 0) - (STRAFE_MOVE if keys["strafe_left"] else 0)
    dx = dy = 0
    if move:
        dx += fixed_mul(move & M32, rm.read_cos(ang), 8, 4)
        dy += fixed_mul(move & M32, rm.read_sin(ang), 8, 4)
    if side:
        dx += fixed_mul(side & M32, rm.read_sin(ang), 8, 4)
        dy -= fixed_mul(side & M32, rm.read_cos(ang), 8, 4)
    return dx, dy


def _loop(rm, sc, x, y, dx, dy, masked_rule):
    """THE three-candidate loop both policies implement -> (tried candidates, signed, in order; the end position).
    `masked_rule`: skip when the MASKED candidate equals the signed start (move_with_collision); else when the signed
    candidate does (combat)"""
    tried = []
    for cand in (((x + dx) & M32, (y + dy) & M32), ((x + dx) & M32, y), (x, (y + dy) & M32)):
        c = (_signed(cand[0]), _signed(cand[1]))
        if (cand if masked_rule else c) == (x, y):
            continue
        tried.append(c)
        if rm.try_move(sc, x, y, *c):
            return tried, c
    return tried, (x, y)


def test_the_policies_differ_only_by_the_still_candidate_rule(world):
    from doomfj.reference_model import SimState
    from doomfj.world import TicEvents
    w, rm, sc = world, world.rm, world.scene_c
    n_still_neg = n_still_pos = n_differ = n_refused = 0
    for x, y, ang, keys in _cases(w):
        sx, sy = _signed(x), _signed(y)
        dx, dy = _step(rm, sx, sy, ang, keys)
        # the hosted policy, through step_sim (the hosted tiers' own entry)
        th = []
        st = rm.step_sim(SimState(x, y, ang, "E1M1"), keys, scene=sc, touch=lambda cx, cy, _z: th.append((cx, cy)),
                         strafe=True)
        # the game tier's model
        tm = []
        w.ws.px, w.ws.py, w.ws.pangle, w.ws.p_turnheld = sx, sy, ang, 0
        w._touch_specials = lambda cx, cy, _z, _ev: tm.append((cx, cy))
        w._walkover = lambda *_a: None
        w._player_move(keys, TicEvents(0))
        want_h, end_h = _loop(rm, sc, sx, sy, dx, dy, masked_rule=True)
        want_m, end_m = _loop(rm, sc, sx, sy, dx, dy, masked_rule=False)
        assert th == want_h, ("move_with_collision is not the masked-rule loop", x, y, ang, keys, th, want_h)
        assert tm == want_m, ("_player_move is not the signed-rule loop", x, y, ang, keys, tm, want_m)
        assert (_signed(st.x), _signed(st.y)) == (w.ws.px, w.ws.py) == end_m, (x, y, ang, keys)
        still = (sx, sy) in {(_signed(sx + dx), sy), (sx, _signed(sy + dy))}
        n_refused += len(want_m) > 1 or end_m == (sx, sy)
        n_still_neg += still and (sx < 0 or sy < 0)
        n_still_pos += still and sx >= 0 and sy >= 0
        n_differ += th != tm
    print("cases with a refused step %d; a still candidate at a negative / non-negative coordinate %d / %d; tried "
          "sequences differ %d" % (n_refused, n_still_neg, n_still_pos, n_differ))
    assert n_differ > 0, "no case reached the still-candidate rule: the pin is vacuous"
    assert n_still_pos > 0 and n_refused > 0


def test_control_a_swapped_rule_is_caught(world):
    """R9: the pin's comparison can see the rule -- the hosted policy predicted with combat's rule must fail on some
    case (else (a) proves nothing about which rule each side runs)"""
    from doomfj.reference_model import SimState
    w, rm, sc = world, world.rm, world.scene_c
    for x, y, ang, keys in _cases(w):
        sx, sy = _signed(x), _signed(y)
        dx, dy = _step(rm, sx, sy, ang, keys)
        th = []
        rm.step_sim(SimState(x, y, ang, "E1M1"), keys, scene=sc, touch=lambda cx, cy, _z: th.append((cx, cy)),
                    strafe=True)
        if th != _loop(rm, sc, sx, sy, dx, dy, masked_rule=False)[0]:
            return
    pytest.fail("the hosted policy matched combat's rule on every case: the pin cannot tell the rules apart")
