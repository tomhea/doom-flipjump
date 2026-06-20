"""Pure LUT value-function tests (src/doomfj/tables.py).

Anchored to hand-computed / DOOM-convention sample values (sin/recip), and to math.sin parity.
These value fns are the single source shared by the emitter (H2/H4, M5) and the oracle (H5, M9)."""
import math

from doomfj.tables import sine_table, reciprocal_table


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
