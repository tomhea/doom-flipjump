"""Host mirror of src/fj/fixed_point.fj — host math == fj math, bit-for-bit (D12/R6).

Values are raw unsigned n-nibble integers (n nibbles = 4n bits). The signed Q-format
interpretation is two's-complement over those 4n bits. These functions reproduce exactly what
the fj macros compute (verified byte-exact in tests/fj/test_fixed_point.py), so the host
emitter/oracle and the fj program cannot drift.
"""
from __future__ import annotations


def _wrap(x: int, nbits: int) -> int:
    """Reduce to an unsigned nbits-wide two's-complement value."""
    return x & ((1 << nbits) - 1)


def _signed(raw: int, nbits: int) -> int:
    """Signed interpretation of an nbits-wide two's-complement value."""
    raw = _wrap(raw, nbits)
    return raw - (1 << nbits) if raw & (1 << (nbits - 1)) else raw


def fixed_mul(a: int, b: int, n: int, f: int) -> int:
    """dst[:n] = (a[:n] * b[:n]) >> 4f  (signed Q-format multiply, wraps mod 2^4n).

    The product is formed at 2n-nibble width (no intermediate overflow), then the n-nibble
    result is the logical extract starting at fraction-nibble f. @Assumes 0 < f <= n."""
    bits = 4 * n
    product = _wrap(_signed(a, bits) * _signed(b, bits), 8 * n)  # 2n-nibble two's complement
    return _wrap(product >> (4 * f), bits)


def fixed_div(a: int, b: int, n: int, f: int):
    """dst[:n] = (a[:n] << 4f) / b[:n]  (signed divide, truncated toward zero).

    Returns None for b == 0 (the macro's div0 path). @Assumes 0 < f <= n."""
    bits = 4 * n
    if _wrap(b, bits) == 0:
        return None
    sa, sb = _signed(a, bits), _signed(b, bits)
    dividend = sa << (4 * f)
    q = abs(dividend) // abs(sb)
    if (dividend < 0) != (sb < 0):
        q = -q
    return _wrap(q, bits)


def mul_const(src: int, c: int, n: int) -> int:
    """dst[:n] = src[:n] * c  (c a compile-time constant; wraps mod 2^4n)."""
    bits = 4 * n
    return _wrap(_wrap(src, bits) * c, bits)
