"""EVERY-ENTRY coverage for the dispatch tables the renderer emits (CR-2026-08, R5).

R5 wants every-entry and call-twice coverage for a live LUT. The fj kernel tests
(`tests/fj/test_projection_kernels.py`) give call-twice and byte-exactness at SAMPLED indices, but
they cannot drive 2,048 or 4,096 entries -- one lookup per entry is a program the size of the
renderer. What they leave uncovered is exactly what a sampled test cannot see: whether entry 1,731
of the emitted table carries the value the shared kernel says it should.

That is a property of the emitted TEXT, so it is checked here, on the host, for every entry: parse
the generated dispatch back into a value list and require it to equal the SSOT table. `ttang` and
`sdrecip` are the two tables C2 made live and that CR-2026-08 found had no test at all; `vtxdisp`
and `sinadisp` are the M13-VTXDISP / M13-SINADISP adds.

The decoder is deliberately independent of the generator: it reads the
`wflip .res+<p>*dw+w, <v>*dw` handler lines -- the emitted program's own encoding of the value --
rather than re-calling the code that produced them. `test_the_decoder_sees_a_mutated_table` is the
negative control: it flips one nibble of one entry and requires the decoder to notice (R9).
"""
import re

import pytest

from doomfj.config import Config
from doomfj.lut_generator import generate_dispatch_table_fj, generate_trig_idioms_fj
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import (sine_table, slopediv_recip8_table, tantoangle_table,
                           viewangletox_table, xtoviewangle_table)

_HANDLER = re.compile(r"^\s*wflip \.res\+(\d+)\*dw\+w, (0x[0-9a-fA-F]+|\d+)\*dw\s*$")
_CLEAN = re.compile(r"^\s*;clean \+ (\d+)\*dw\s*$")


def decode_per_entry(text, result_nibbles):
    """Reconstruct the value list from a per-entry dispatch table's emitted handler lines.

    Independent of the generator: it reads what the program will actually execute -- one
    `wflip .res+p*dw+w, v*dw` per result nibble, terminated by the jump to `clean + d*dw`.
    """
    values, cur = [], {}
    seen = False
    for line in text.split(chr(10)):
        if line.strip() == "handlers:":
            seen = True
            continue
        if not seen:
            continue
        m = _HANDLER.match(line)
        if m:
            cur[int(m.group(1))] = int(m.group(2), 0)
            continue
        m = _CLEAN.match(line)
        if m:
            assert int(m.group(1)) == len(values), (
                "handlers out of order at entry %d" % len(values))
            assert sorted(cur) == list(range(result_nibbles)), (
                "entry %d has nibbles %s, want 0..%d"
                % (len(values), sorted(cur), result_nibbles - 1))
            values.append(sum(cur[p] << (4 * p) for p in range(result_nibbles)))
            cur = {}
    assert not cur, "a handler ran off the end of the table"
    return values


def _first_diff(got, want):
    for i, (a, b) in enumerate(zip(got, want)):
        if a != b:
            return i
    return -1


def _cases():
    cfg = Config()
    return [
        ("ttang", 3, 8, [v & 0xFFFFFFFF for v in tantoangle_table(SLOPERANGE)]),
        ("sdrecip", 3, 6, [v & 0xFFFFFF for v in slopediv_recip8_table()]),
        ("xtadisp", 2, 8, [v & 0xFFFFFFFF for v in xtoviewangle_table(cfg.VIEW_W, cfg.TRIG_N)]),
        ("vtxdisp", 3, 8, [v & 0xFFFFFFFF for v in viewangletox_table(cfg.VIEW_W, cfg.TRIG_N)]),
    ]


@pytest.mark.parametrize("label,idx_n,res_n,want", _cases(), ids=[c[0] for c in _cases()])
def test_every_entry_carries_the_shared_kernel_value(label, idx_n, res_n, want):
    text = generate_dispatch_table_fj(label, want, index_nibbles=idx_n, result_nibbles=res_n)
    got = decode_per_entry(text, res_n)
    assert len(got) >= len(want), "%s: table shorter than the value list" % label
    d = _first_diff(got[:len(want)], want)
    assert d == -1, ("%s: entry %d is %#x, the shared kernel says %#x"
                     % (label, d, got[d], want[d]))
    assert len(got[:len(want)]) == len(want)
    assert all(v == 0 for v in got[len(want):]), "%s: pad entries are not zero" % label


def test_sinadisp_every_entry_is_the_sine_of_that_columns_angle():
    """M13-SINADISP's whole claim: entry `col` is sin(ANG90 + xtoviewangle[col]). Checked for every
    column against the shared sine table, with the shift derived from TRIG_N, never written as 20."""
    cfg = Config()
    xtov = xtoviewangle_table(cfg.VIEW_W, cfg.TRIG_N)
    sine = sine_table(cfg.TRIG_N, 16, 32)
    shift = 32 - (cfg.TRIG_N.bit_length() - 1)
    want = [sine[((a + (1 << 30)) >> shift) & (cfg.TRIG_N - 1)] & 0xFFFFFFFF for a in xtov]
    assert len(want) == cfg.VIEW_W + 1, "the sinadisp domain must be the column range"
    text = generate_dispatch_table_fj("sinadisp", want, index_nibbles=2, result_nibbles=8)
    got = decode_per_entry(text, 8)
    d = _first_diff(got[:len(want)], want)
    assert d == -1, "sinadisp: column %d is %#x, want %#x" % (d, got[d], want[d])
    assert all(v == 0 for v in got[len(want):])


def test_finesine_per_entry_carries_every_sine_value():
    """The shipped finesine mode (M13-SINPERENTRY). per_result_nibble emits eight 1-nibble tables
    and has no per-entry handler block, so only the mode that ships is decodable here -- which is
    the point: this test pins the mode, and would fail loudly if it were switched back."""
    cfg = Config()
    want = [v & 0xFFFFFFFF for v in sine_table(cfg.TRIG_N, 16, 32)]
    text = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16, mode="per_entry")
    got = decode_per_entry(text, 8)
    d = _first_diff(got[:len(want)], want)
    assert d == -1, "finesine: entry %d is %#x, want %#x" % (d, got[d], want[d])
    assert "def read_sin dst, idx" in text and "def read_cos dst, idx" in text


def test_the_decoder_sees_a_mutated_table():
    """NEGATIVE CONTROL (R9). Every assertion above is worth only what this proves: flip one nibble
    of one entry and the decoder must see it. A decoder that echoed its input would pass all of the
    tests above and none of this one."""
    cfg = Config()
    want = [v & 0xFFFFFFFF for v in viewangletox_table(cfg.VIEW_W, cfg.TRIG_N)]
    text = generate_dispatch_table_fj("vtxdisp", want, index_nibbles=3, result_nibbles=8)
    clean = decode_per_entry(text, 8)
    assert clean[:len(want)] == want, "the control's own baseline must be clean"

    lines = text.split(chr(10))
    hi = lines.index("      handlers:")
    entry, target = 0, None
    for i in range(hi + 1, len(lines)):
        if _CLEAN.match(lines[i]):
            entry += 1
            if entry > 100:
                break
            continue
        m = _HANDLER.match(lines[i])
        if entry == 100 and m and m.group(1) == "0":
            target = i
            break
    assert target is not None, "could not locate entry 100's nibble-0 handler"
    old = _HANDLER.match(lines[target]).group(2)
    new = hex((int(old, 0) + 1) % 16)
    lines[target] = lines[target].replace("%s*dw" % old, "%s*dw" % new)
    mutated = decode_per_entry(chr(10).join(lines), 8)
    assert mutated != clean, "the decoder did NOT see a changed entry -- it is vacuous"
    assert sum(1 for a, b in zip(mutated, clean) if a != b) == 1, "exactly one entry should differ"
    assert mutated[100] != clean[100], "the change should be at the entry that was mutated"
