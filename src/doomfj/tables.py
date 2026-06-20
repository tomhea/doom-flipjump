"""G-a — pure LUT VALUE functions (sine, reciprocal, ...).

These return the raw encoded entry values (the LUT *contents*), and are the single source shared by
the emitter (H2/H4, M5/M8) and the reference oracle (H5, M9) so the two cannot drift (D12/R6). The
fj-text emission (`hex.vec` entries / packed-byte ops) is a separate concern — `lut_generator.py`
(M5, §3.4 fallback) and the dispatch-code emitter. (Value kernel lifted from PR #1, D15 keep — M4.)
"""
from __future__ import annotations
import math

from doomfj.fixedpoint import encode_fixed_point


def sine_table(count: int, fraction_bits: int, total_bits: int) -> list[int]:
    """sin(2*pi*k/count) for k in [0, count), as signed fixed-point words (two's-complement).
    count=4096 (16**3) is the design's trig table size (§1.2/§2.1)."""
    return [encode_fixed_point(math.sin(2 * math.pi * k / count), fraction_bits, total_bits)
            for k in range(count)]


def reciprocal_table(count: int, fraction_bits: int, total_bits: int) -> list[int]:
    """round(2^fraction_bits / i) for i in [0, count); entry 0 is clamped to the max entry value
    (DOOM convention), and every entry is clamped to the entry width. Replaces runtime divides."""
    max_value = (1 << total_bits) - 1
    table = [max_value]
    table += [min(round((1 << fraction_bits) / i), max_value) for i in range(1, count)]
    return table
