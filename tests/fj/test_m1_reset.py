"""M1 -- `m1.zerobyte`, the byte clear the self-reset prologue is built on.

This drives the SHIPPED macro out of `src/fj/m1_reset.fj`. `scratchpad/m1_zbyte.py` is a probe and
embeds its own copy of the macro text, so it proves nothing about the file the build assembles;
this includes the real file.

WHY A BYTE CLEAR EXISTS AT ALL. In an ARRAY a byte written through `hex.write_byte` is ONE cell (8
bits at dbit..dbit+7), so a nibble op on it does not clear it, it CORRUPTS it -- measured
0xA5 -> 0x22A5. `hex.zero` cannot reach the high nibble; `hex.exact_xor` takes arbitrary bit
addresses and can.

THE CONTROLS, and what each would let through if it were dropped:
  * `test_preload_actually_plants_bytes` -- without it, every other test here passes on cells that
    were never non-zero. This is not hypothetical: an earlier cost measurement in this session was
    vacuous for exactly that reason, because `hex.xor_by` silently CLAMPS to a nibble.
  * `test_clears_every_value_0_to_255` -- a clear tested on small values only passes while the high
    nibble survives, which is the `hex.zero` bug this macro exists to avoid.
  * `test_neighbours_untouched` -- the stride is ONE cell, so a clear one bit too wide lands in the
    next entry and is invisible to a test that only reads the cells it cleared.
  * `test_second_call_on_the_same_cell_still_works` -- the macro re-points
    `hex.pointers.ret_after_read_byte` and must put it back. If it did not, the FIRST call would
    still pass and every later one would run off. The reset issues 1,002 of these in a row.
"""
import sys
import tempfile
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.fjm_run import IOReadOnEOF
from flipjump.utils.functions import load_debugging_labels

from doomfj.fastrun import FjmRunner, _fjcore
from doomfj.harness import W

M1_FJ = Path("src/fj/m1_reset.fj")
VAL_SHIFT = (W + W.bit_length()) - W


def run_clear(n, values, clear=True, repeats=1):
    """Plant `values` as raw BYTES, optionally clear, return the read-back cell values.

    The pre-load is a raw `wflip` of the cell's jump word, NOT `hex.xor_by` -- xor_by clamps to a
    nibble and would plant only the low half.
    """
    lines = ["stl.startup_and_init_all"]
    lines += ["wflip arr + %d*dw + w, %d*dw" % (i, v) for i, v in enumerate(values) if v]
    if clear:
        for _ in range(repeats):
            lines.append("rep(%d, i) m1.zerobyte arr + i*dw" % n)
    lines += ["stl.loop", "arr: hex.vec %d" % (n + 2)]

    tmp = Path(tempfile.mkdtemp(prefix="m1zb_"))
    src = tmp / "p.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    fj.assemble([M1_FJ.resolve(), src.resolve()], out, memory_width=W, print_time=False,
                debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)
    base = min(v for k, v in labels.items() if k == "arr" or k.endswith(":arr")) // W

    r = FjmRunner(out, flat_max_words=1 << 24)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, ln in r._segments:
        core.add_segment(s, ln)
    for st, vals in r._runs:
        core.set_words(st, vals)
    core.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)
    return [core.get_word(base + 2 * i + 1) >> VAL_SHIFT for i in range(n + 2)]


# The two cells past the end are planted with NON-ZERO bytes on purpose -- see
# test_neighbours_untouched.
GUARD = [0xC3, 0x5A]


@pytest.fixture(scope="module")
def all256():
    return run_clear(256, list(range(256)) + GUARD)


def test_preload_actually_plants_bytes():
    """CONTROL. With the clear removed the cells must read back the planted BYTES, high nibble and
    all. If this fails, nothing else in this file means anything."""
    vals = [(i * 4 + 1) & 0xFF for i in range(64)]
    got = run_clear(64, vals, clear=False)
    assert got[:64] == vals
    assert max(vals) > 0x0F, "the pre-load must exercise the HIGH nibble to be a control at all"


def test_clears_every_value_0_to_255(all256):
    nonzero = [(i, v) for i, v in enumerate(all256[:256]) if v != 0]
    assert not nonzero, "cells left non-zero: %s" % nonzero[:8]


def test_neighbours_untouched(all256):
    """The two guard cells are PLANTED with non-zero bytes and must come back holding them.

    ⚠ CR round 3: this used to assert they were 0 -- but `values` was only 256 long, so the guard
    cells were never planted and were 0 going in. A spill that correctly byte-zeroed them left 0
    and the test passed. It could not fail for the bug it names. Planting them makes the assertion
    "unchanged", which a spill of either kind breaks."""
    assert all256[256:258] == GUARD, "the clear spilled past the array"


def test_second_call_on_the_same_cell_still_works():
    """R5. `m1.zerobyte` re-points a shared stl pointer and must restore it, so calling it twice
    over the same cells must behave exactly like calling it once."""
    vals = [(i * 7 + 3) & 0xFF for i in range(32)]
    once = run_clear(32, vals, repeats=1)
    twice = run_clear(32, vals, repeats=2)
    assert twice == once == [0] * 34


# ── m1.readbyte / m1.writebyte: the same round trip, minus the clear ─────────────────────────────
# Ported from scratchpad/ptr_price_list.py, where they were written to make the constant-address
# alternative MEASURABLE (628.0 -> 111.4 and 805.6 -> 110.3 ops). Once they live in src/ they need
# the same coverage m1.zerobyte has: every value, both nibbles, and neighbours untouched.

def run_rw(n, values, mode):
    """Plant `values` as raw BYTES, then read/rewrite them at CONSTANT addresses.

    ⚠ NO helper macro with an inline `hex.vec`. A `hex.vec` declared inside a macro body sits in the
    INSTRUCTION STREAM, and control falls straight into it after the last statement -- the data gets
    executed. That mistake cost a debugging round here and looked exactly like a broken primitive.
    Temporaries live after `stl.loop`, where nothing runs.
    """
    lines = ["stl.startup_and_init_all"]
    lines += ["wflip arr + %d*dw + w, %d*dw" % (i, v) for i, v in enumerate(values) if v]
    if mode == "read":
        lines.append("rep(%d, i) m1.readbyte tv + i*2*dw, arr + i*dw" % n)
        lines.append("rep(%d, i) m1.writebyte out + i*dw, tv + i*2*dw" % n)
    else:
        lines += ["hex.set 2, tv, 0x5A", "rep(%d, i) m1.writebyte arr + i*dw, tv" % n]
    lines += ["stl.loop", "tv: hex.vec %d" % (2 * n + 2), "arr: hex.vec %d" % (n + 2),
              "out: hex.vec %d" % (n + 2)]
    tmp = Path(tempfile.mkdtemp(prefix="m1rw_"))
    src = tmp / "p.fj"
    src.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    fj.assemble([M1_FJ.resolve(), src.resolve()], out, memory_width=W, print_time=False,
                debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)

    def base(name):
        return min(v for k, v in labels.items() if k == name or k.endswith(":" + name)) // W

    r = FjmRunner(out, flat_max_words=1 << 24)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for sg, ln in r._segments:
        core.add_segment(sg, ln)
    for st, vals in r._runs:
        core.set_words(st, vals)
    core.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)
    arr = [core.get_word(base("arr") + 2 * i + 1) >> VAL_SHIFT for i in range(n + 2)]
    got = ([core.get_word(base("out") + 2 * i + 1) >> VAL_SHIFT for i in range(n)]
           if mode == "read" else None)
    return arr, got


def test_readbyte_returns_every_value_and_does_not_disturb_the_cell():
    """Every value 0..255 read at a CONSTANT address and stored back through m1.writebyte.

    Catches the two failure modes that matter: losing the HIGH nibble (a read that only assembles
    4 of the 8 bits looks correct for every value below 0x10), and a read that corrupts its own
    source cell -- it flips bit dbit+8 and jumps INTO the cell, so it must undo both flips.
    """
    vals = list(range(256)) + GUARD
    arr, got = run_rw(256, vals, "read")
    assert got == list(range(256)), "misread: %s" % (
        [(i, g) for i, g in enumerate(got) if g != i][:6])
    assert arr[:256] == list(range(256)), "the READ modified its source cells"
    assert arr[256:258] == GUARD


def test_writebyte_stores_every_value_and_leaves_neighbours_alone():
    """The write twin of test_clears_every_value_0_to_255. 0x5A has popcount 4 and both nibbles
    non-zero, so a half-width write shows up immediately."""
    vals = list(range(256)) + GUARD
    arr, _ = run_rw(256, vals, "write")
    assert arr[:256] == [0x5A] * 256, "cells not written: %s" % (
        [(i, v) for i, v in enumerate(arr[:256]) if v != 0x5A][:6])
    assert arr[256:258] == GUARD, "the write spilled past the array"
