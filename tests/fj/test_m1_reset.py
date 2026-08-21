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


@pytest.fixture(scope="module")
def all256():
    return run_clear(256, list(range(256)))


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
    assert all256[256] == 0 and all256[257] == 0, "the clear spilled past the array"


def test_second_call_on_the_same_cell_still_works():
    """R5. `m1.zerobyte` re-points a shared stl pointer and must restore it, so calling it twice
    over the same cells must behave exactly like calling it once."""
    vals = [(i * 7 + 3) & 0xFF for i in range(32)]
    once = run_clear(32, vals, repeats=1)
    twice = run_clear(32, vals, repeats=2)
    assert twice == once == [0] * 34
