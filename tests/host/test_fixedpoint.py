"""Unit tests for the host fixed-point mirror (src/doomfj/fixedpoint.py).

These anchor the mirror to hand-computed Q-format values (the same ground truth PR #1's
.out files used). The fj<->host PARITY is checked separately in tests/fj/test_fixed_point.py;
together they prove the fj macros are correct (unit: host==truth, parity: fj==host)."""
import pytest

from doomfj.fixedpoint import fixed_mul, fixed_div, mul_const, encode_fixed_point

# (a, b, n, f) -> expected raw n-nibble result (16.16 is n=8,f=4; 8.8 is n=4,f=2)
MUL_CASES = [
    (0x00018000, 0x00020000, 8, 4, 0x00030000),  # 1.5 * 2.0 = 3.0
    (0xFFFE8000, 0x00020000, 8, 4, 0xFFFD0000),  # -1.5 * 2.0 = -3.0
    (0xFFFE8000, 0xFFFE0000, 8, 4, 0x00030000),  # -1.5 * -2.0 = 3.0
    (0x40000000, 0x00040000, 8, 4, 0x00000000),  # 16384 * 4 -> wraps mod 2^32
    (0x00008000, 0x00008000, 8, 4, 0x00004000),  # 0.5 * 0.5 = 0.25
    (0x0280,     0xFE00,     4, 2, 0xFB00),      # 8.8: 2.5 * -2.0 = -5.0
    (0xFFFF8000, 0xFFFF8000, 8, 4, 0x00004000),  # -0.5 * -0.5 = 0.25
]

DIV_CASES = [
    (0x00030000, 0x00020000, 8, 4, 0x00018000),  # 3.0 / 2.0 = 1.5
    (0xFFFD0000, 0x00020000, 8, 4, 0xFFFE8000),  # -3.0 / 2.0 = -1.5
    (0xFFFF0000, 0x00030000, 8, 4, 0xFFFFAAAB),  # -1.0 / 3.0 -> trunc toward zero
    (0x00010000, 0x00030000, 8, 4, 0x00005555),  # 1.0 / 3.0
    (0xFB00,     0x0280,     4, 2, 0xFE00),      # 8.8: -5.0 / 2.5 = -2.0
    (0x00030000, 0xFFFE0000, 8, 4, 0xFFFE8000),  # 3.0 / -2.0 = -1.5
    (0xFFFD0000, 0xFFFE0000, 8, 4, 0x00018000),  # -3.0 / -2.0 = 1.5
]

MUL_CONST_CASES = [
    (0x00001234, 320, 8, 0x0016C100),   # DOOM screen-stride constant
    (0x12345678, 1,   8, 0x12345678),
    (0xFFFFFFFF, 5,   8, 0xFFFFFFFB),   # wraps mod 2^32
    (0xABCD0123, 0,   8, 0x00000000),
]


@pytest.mark.parametrize("a,b,n,f,want", MUL_CASES)
def test_fixed_mul(a, b, n, f, want):
    assert fixed_mul(a, b, n, f) == want


@pytest.mark.parametrize("a,b,n,f,want", DIV_CASES)
def test_fixed_div(a, b, n, f, want):
    assert fixed_div(a, b, n, f) == want


def test_fixed_div_by_zero_returns_none():
    assert fixed_div(0x00030000, 0x00000000, 8, 4) is None


@pytest.mark.parametrize("src,c,n,want", MUL_CONST_CASES)
def test_mul_const(src, c, n, want):
    assert mul_const(src, c, n) == want


# encode_fixed_point: real value -> raw two's-complement fixed-point word (lifted from PR #1, M4)
def test_encode_positive():
    assert encode_fixed_point(1.0, fraction_bits=16, total_bits=32) == 0x10000
    assert encode_fixed_point(1.5, fraction_bits=16, total_bits=32) == 0x18000


def test_encode_negative_is_twos_complement():
    assert encode_fixed_point(-1.0, fraction_bits=16, total_bits=32) == 0xFFFF0000
    assert encode_fixed_point(-0.5, fraction_bits=16, total_bits=32) == 0xFFFF8000


def test_encode_8_8():
    assert encode_fixed_point(2.5, fraction_bits=8, total_bits=16) == 0x0280
    assert encode_fixed_point(-2.5, fraction_bits=8, total_bits=16) == 0xFD80


def test_encode_rounds_to_nearest():
    assert encode_fixed_point(0.3, fraction_bits=16, total_bits=32) == round(0.3 * (1 << 16))


def test_encode_out_of_range_raises():
    with pytest.raises(ValueError):
        encode_fixed_point(40000.0, fraction_bits=16, total_bits=32)
    with pytest.raises(ValueError):
        encode_fixed_point(-40000.0, fraction_bits=16, total_bits=32)
