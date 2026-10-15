"""P12 (T5) -- proj.project_thing's TIGHT far bound (doomfj.things.tight_far_bound_ok): a body without the aim hook
rejects a thing at L-inf distance tz_map + (tz_map >> 1) + SPR_REACH before its two depth multiplies. That is exact
only if every position the WHOLE projection accepts lies inside it:
  * the constants it rests on bound what they claim -- TIGHT_K the block-FP reciprocal's worst half-screen /
    (xscale * tz) over every reciprocal bucket, TIGHT_TRIG_DEV the trig table's |cos^2 + sin^2 - 1|;
  * the ORACLE (ReferenceModel.project_thing, the fj's mirror) accepts nothing outside it, for every E1M1 sprite,
    over viewpoints sampled at the corner of the accepted region (depth near tzmax, lateral near the screen edge,
    every view angle, fractional positions);
  * NEGATIVE CONTROL: the same sampling against a bound of 1.25 x tzmax must find accepted positions outside it --
    the samples reach the region the bound has to cover, so the check above is not vacuous."""
import math
import random

import pytest

from doomfj.config import GAME_CFG, Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import (MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, SPRITE_MINZ, ReferenceModel)
from doomfj.things import TIGHT_K, TIGHT_TRIG_DEV, tight_far_bound_ok
from doomfj.wad import WadFile
from doomfj.wall_renderer import DRAW_ACTOR_TYPES

E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"
SPRITE_WAD = "assets/freedoom1.wad"


def _worst_k(rm, cfg):
    half = max(cfg.VIEW_W - cfg.CENTERX + 2.0 ** -16, cfg.CENTERX - 1)
    worst = 0.0
    for fsh in range(7, 14):
        for sden in range(0x100, 0x1000):
            hi = ((sden + 1) << (4 * (fsh - 6))) - 1
            if hi < SPRITE_MINZ or hi >= 1 << 31:
                continue
            xs = rm._scale_recip_div(cfg.PROJECTION << 16, hi)
            if xs:
                worst = max(worst, half * 2.0 ** 32 / (xs * hi))
    return worst


@pytest.mark.parametrize("cfg", [GAME_CFG, Config()], ids=["game", "default"])
def test_constants_bound_the_measured(cfg):
    rm = ReferenceModel(cfg)
    k = _worst_k(rm, cfg)
    assert 1.0 < k <= TIGHT_K, k
    n = cfg.TRIG_N
    dev = max(abs((_signed(rm.sine[i], 32) ** 2 + _signed(rm.sine[(i + n // 4) % n], 32) ** 2) / 2 ** 32 - 1)
              for i in range(n))
    assert dev <= TIGHT_TRIG_DEV, dev


def _sprites():
    rm = ReferenceModel(GAME_CFG)
    mw, sw = WadFile.from_path(E1M1_WAD), WadFile.from_path(SPRITE_WAD)
    cache, out = {}, {}
    for t in mw.things("E1M1"):
        art = rm.sprite_art(sw, t.type, cache)
        if art is not None and t.type not in out:
            mh = MIN_SPRITE_H_MONSTER if t.type in DRAW_ACTOR_TYPES else MIN_SPRITE_H
            out[t.type] = (art, mh, rm.sprite_tz_min_size(art[4], mh))
    return rm, out


def _outside(rm, sprites, bound, samples=400, seed=12):
    """accepted positions outside `bound(t)` (L-inf, the floor the fj compares), over corner-of-region samples"""
    rnd = random.Random(seed)
    bad, accepted = [], 0
    for kind, (art, mh, tzmax) in sorted(sprites.items()):
        T = tzmax / 65536
        w = max(art[5], art[3] - art[5], 0)
        for _ in range(samples):
            ang = rnd.randrange(1 << 32)
            th = ang / 2 ** 32 * 2 * math.pi
            tz = T * rnd.uniform(0.85, 1.0)
            tx = rnd.choice((-1, 1)) * (tz + w) * rnd.uniform(0.9, 1.03)
            # view space -> world: tr = tz * (cos, sin) + tx * (sin, -cos)  (the fj's tx = sin*trx - cos*try)
            trx = tz * math.cos(th) + tx * math.sin(th)
            tr_y = tz * math.sin(th) - tx * math.cos(th)
            vx = int(round(-trx * 65536)) + rnd.randrange(-3, 4)
            vy = int(round(-tr_y * 65536)) + rnd.randrange(-3, 4)
            res = rm.project_thing(vx & 0xFFFFFFFF, vy & 0xFFFFFFFF, ang, 41 << 16, 0, 0, 0, art, min_h=mh)
            if res is None:
                continue
            accepted += 1
            t = tzmax >> 16
            m = max(abs(((0 << 16) - vx) >> 16), abs(((0 << 16) - vy) >> 16))
            if m > bound(t, art):
                bad.append((kind, t, m, bound(t, art)))
    return bad, accepted


def test_oracle_accepts_nothing_outside_the_tight_bound():
    rm, sprites = _sprites()
    for _kind, (art, _mh, tzmax) in sprites.items():
        assert tight_far_bound_ok(tzmax, art[5], art[3], Config.SPR_REACH)
    bad, accepted = _outside(rm, sprites, lambda t, art: t + (t >> 1) + Config.SPR_REACH)
    assert accepted > 1000, accepted
    assert not bad, bad[:5]


def test_negative_control_a_too_tight_bound_is_caught():
    rm, sprites = _sprites()
    bad, accepted = _outside(rm, sprites, lambda t, art: t + (t >> 2))
    assert accepted > 1000 and len(bad) > 50, (accepted, len(bad))
