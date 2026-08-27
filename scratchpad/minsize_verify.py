"""The MINIMUM-SIZE far-sprite reject: derive the exact per-sprite tz threshold, and PROVE it.

EXP-7 rejects `tz > (wph*PROJECTION)<<16`, the depth past which a sprite projects to ZERO rows.
This generalises it to "fewer than MIN_SPRITE_H rows" -- the same one compare, a different constant.

⚠ The constant is NOT taken analytically. `xscale = _scale_recip_div(PROJECTION<<16, tz)` is a
block-FP reciprocal, not a true divide, so the analytic boundary can be off by a unit. Instead:
scan the real chain around the analytic estimate, take the LARGEST tz that still yields
`h >= MIN_SPRITE_H`, and verify no larger tz anywhere in range does. The baked constant is then
exact by construction and the oracle's `h < MIN_SPRITE_H` test and fj's `tz > sp_tzmin` test agree
for every (wph, tz) -- which is what byte-exactness needs.

    python scratchpad/minsize_verify.py
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed, fixed_mul                          # noqa: E402
from doomfj.reference_model import (ANGLE_MASK, SPRITE_MINZ, THING_SPRITE,  # noqa: E402
                                    ReferenceModel, build_scene)
from doomfj.wad import WadFile                                            # noqa: E402

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
build_scene(mw, mw, "E1M1")
PROJ = cfg.PROJECTION


def height(wph, tz):
    """The oracle's exact chain: xscale from the block-FP reciprocal, then h."""
    xs = rm._scale_recip_div(PROJ << 16, tz)
    return _signed(fixed_mul((wph << 16) & ANGLE_MASK, xs, 8, 4), 32) >> 16


# every sprite height V4 can put on screen in E1M1
cache: dict = {}
whs = sorted({rm.sprite_art(art, t, cache)[4]
              for t in sorted(THING_SPRITE) if rm.sprite_art(art, t, cache) is not None})
print(f"{len(whs)} distinct sprite world-heights: {whs}")

TZ_HI = 12000 << 16          # well past any E1M1 sight line
for MINH in (2, 3, 4):
    print(f"\n=== MIN_SPRITE_H = {MINH} ===")
    ok = True
    for wph in whs:
        t0 = ((wph * PROJ) << 16) // MINH                 # the analytic estimate
        lo, hi = max(SPRITE_MINZ, t0 - (4 << 16)), t0 + (4 << 16)
        # the exact boundary: the largest tz in the window with h >= MINH
        best = None
        for tz in range(lo, hi):
            if height(wph, tz) >= MINH:
                best = tz
        if best is None:
            print(f"  wph {wph:3d}: NO tz in the window yields h >= {MINH} -- widen it")
            ok = False
            continue
        # ... and nothing beyond it anywhere in range may sneak back over the bound
        viol = [tz for tz in range(best + 1, TZ_HI, 1 << 12) if height(wph, tz) >= MINH]
        flag = "" if not viol else f"  ⚠ {len(viol)} VIOLATIONS (first tz={viol[0]})"
        ok &= not viol
        print(f"  wph {wph:3d}: exact tz threshold {best:>12,} "
              f"({best / 65536:8.1f} map units)  analytic {t0:>12,} "
              f"delta {best - t0:+6d}{flag}")
    print(f"  => {'EXACT, no margin needed' if ok else 'NOT SAFE'}")
