"""Pure LUT value-function tests (src/doomfj/tables.py).

Anchored to hand-computed / DOOM-convention sample values (sin/recip), and to math.sin parity.
These value fns are the single source shared by the emitter (H2/H4, M5) and the oracle (H5, M9)."""
import math

from doomfj.fixedpoint import _signed
from doomfj.tables import sine_table, reciprocal_table, finetangent_table


def test_sine_anchors_16_16():
    s = sine_table(4096, 16, 32)
    assert len(s) == 4096
    assert s[0] == 0x00000000      # sin(0) = 0
    assert s[1024] == 0x00010000   # sin(pi/2) = 1.0   (quarter circle, DOOM ANG90 convention)
    assert s[2048] == 0x00000000   # sin(pi) = 0
    assert s[3072] == 0xFFFF0000   # sin(3pi/2) = -1.0 (two's-complement)


def test_sine_matches_math_sin():
    s = sine_table(256, 16, 32)
    for k in range(256):
        want = round(math.sin(2 * math.pi * k / 256) * (1 << 16)) & 0xFFFFFFFF
        assert s[k] == want


def test_reciprocal_values_16_16():
    r = reciprocal_table(256, 16, 32)
    assert len(r) == 256
    assert r[0] == 0xFFFFFFFF             # i=0 clamped to max (DOOM convention)
    assert r[1] == 0x00010000             # 1/1 = 1.0
    assert r[2] == 0x00008000             # 1/2 = 0.5
    assert r[3] == round((1 << 16) / 3)   # 1/3
    assert r[4] == 0x00004000             # 1/4 = 0.25


def test_reciprocal_clamps_when_over_max():
    # 2^fraction_bits / 1 = 2^16 overflows an 8-bit entry -> clamp to max
    r = reciprocal_table(4, 16, 8)
    assert r[0] == 0xFF
    assert r[1] == 0xFF  # 65536 clamped to 0xFF


def test_finetangent_offset_and_anchors_16_16():
    """finetangent[i] = tan(angle_i - 90deg): 0 at ANG90 (head-on wall centre), ±1 at ±45deg from it."""
    N = 4096
    t = finetangent_table(N)
    assert len(t) == N
    assert _signed(t[N // 4], 32) == 0                       # ANG90 -> tan(0) = 0
    assert _signed(t[N * 3 // 8], 32) == 1 << 16             # ANG135 -> tan(45) = +1.0
    assert _signed(t[N // 8], 32) == -(1 << 16)             # ANG45 -> tan(-45) = -1.0


def test_finetangent_poles_clamped():
    """The poles (angle 0deg/180deg ⇒ tan(∓90deg) = ∓∞) clamp to the signed 32-bit range, no overflow."""
    N = 4096
    t = finetangent_table(N)
    assert _signed(t[0], 32) == -(1 << 31)                   # tan(-90) -> clamp low
    assert _signed(t[N // 2], 32) == (1 << 31) - 1           # tan(+90) -> clamp high
    assert all(-(1 << 31) <= _signed(v, 32) <= (1 << 31) - 1 for v in t)


def test_finetangent_matches_math_tan_every_entry():
    """R5: every entry equals the clamped 16.16 math.tan(angle-90deg) (the shared emitter+oracle source)."""
    N = 256
    t = finetangent_table(N)
    assert len(t) == N
    lo, hi = -(1 << 31), (1 << 31) - 1
    for i in range(N):
        want = max(lo, min(hi, round(math.tan(2 * math.pi * i / N - math.pi / 2) * (1 << 16)))) & 0xFFFFFFFF
        assert t[i] == want


def test_finetangent_deterministic():
    """Built twice (the emitter and the oracle each build it once) ⇒ byte-identical, so they can't drift."""
    assert finetangent_table(512) == finetangent_table(512)
