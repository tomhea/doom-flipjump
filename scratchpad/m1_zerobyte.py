"""M1c — a BYTE CLEAR WITH NO POINTER ARITHMETIC, for a cell at a CONSTANT address.

`hex.zero_ptr` costs 943 ops/cell and almost all of it is `set_flip_and_jump_pointers`: copying a
w/4 = 8-nibble address into `to_flip`/`to_jump` at runtime. **When the address is a compile-time
constant none of that is needed.** The stl's own byte read already works by flipping bit `dbit+8`
of the pointed cell and JUMPING INTO IT: the cell's jump word becomes `(v+256)*dw`, which lands at
`read_ptr_byte_table + v` (the table is pinned at op 256), and that entry xors `v`'s bits into
`hex.pointers.read_byte` and returns. With a baked address:

    * "flip bit dbit+8 of the cell"  is one op:  `C+dbit+8;`
    * "jump to the cell"             is one op:  `;C`
    * "xor the value back out"       is two `hex.exact_xor`s, whose d3..d0 are ARBITRARY BIT
      ADDRESSES -- so they can target C's own low and high nibble directly.

No pointer, no address copy, no loop counter. This measures what that actually costs.

⚠ NEGATIVE CONTROLS (R9):
  1. CORRECTNESS ON EVERY BYTE VALUE. The cells are pre-loaded with a raw `wflip C+w, v*dw` (NOT
     `hex.xor_by`, which CLAMPS to a nibble -- that clamp already made one cost measurement in this
     session vacuous), covering v = 0..255 including the values a nibble op corrupts. Every cell
     must read back 0.
  2. THE PRE-LOAD IS VERIFIED FIRST: a run with the clear omitted must read back the values that
     were written, or "cleared" means "never set".
  3. PER-CELL COST FROM A DIFFERENCE of two sizes, so fixed startup cannot be smuggled in.
  4. `hex.zero_ptr` is measured in the same program as the baseline, in-session.

    python scratchpad/m1_zerobyte.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.utils.functions import load_debugging_labels                # noqa: E402

from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402

VAL = (W + W.bit_length()) - W

# The macro under test. `C` is a compile-time constant address.
MACRO = [
    "ns m1 {",
    "    // the pointer-path baseline, for an in-session A/B in the SAME program",
    "    def zp < p {",
    "        hex.zero_ptr p",
    "        hex.ptr_inc p",
    "    }",
    "    // Clear all 8 bits of the byte cell at the CONSTANT address C, with no pointer.",
    "    //   1. zero the stl's 2-cell byte register",
    "    //   2. point the table's return at `back`",
    "    //   3. flip bit dbit+8 of C and jump INTO C: its jump word is now (v+256)*dw, which is",
    "    //      read_ptr_byte_table + v, and that entry xors v into read_byte and returns",
    "    //   4. flip the marker bit back, then xor read_byte's two nibbles onto C's own low and",
    "    //      high nibble -- hex.exact_xor takes arbitrary BIT addresses, so C is named directly",
    "    def zerobyte C @ back < hex.pointers.read_byte, hex.pointers.ret_after_read_byte {",
    "        hex.zero 2, hex.pointers.read_byte",
    "        wflip hex.pointers.ret_after_read_byte+w, back",
    "        C+dbit+8; C",
    "      back:",
    "        wflip hex.pointers.ret_after_read_byte+w, back",
    "        C+dbit+8;",
    "        hex.exact_xor C+dbit+3, C+dbit+2, C+dbit+1, C+dbit+0, hex.pointers.read_byte",
    "        hex.exact_xor C+dbit+7, C+dbit+6, C+dbit+5, C+dbit+4, hex.pointers.read_byte+dw",
    "    }",
    "}",
]


def build(body, n_arr, extra_tail=()):
    lines = MACRO + ["stl.startup_and_init_all"] + body + ["stl.loop",
                                                           "p: hex.vec w/4"] + list(extra_tail) + \
        [f"arr: hex.vec {n_arr + 2}"]
    tmp = Path(tempfile.mkdtemp(prefix="m1zb_"))
    src = tmp / "p.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False, debugging_file_path=dbg)
    L = load_debugging_labels(dbg)
    r = FjmRunner(out, flat_max_words=1 << 25)
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, k in r._segments:
        c.add_segment(s, k)
    for s, v in r._runs:
        c.set_words(s, v)
    _cc, ops, _e, _l, _p = c.run(lambda: 0, lambda b: None, IOReadOnEOF, last_ops_length=0)
    base = min(v for k, v in L.items() if k == "arr" or k.endswith(":arr")) // W
    vals = [c.get_word(base + 2 * i + 1) >> VAL for i in range(n_arr)]
    return ops, vals


def preload(n):
    """v = i*7+1 mod 256 -- covers small, >15, and low-nibble-zero values. RAW wflip, because
    hex.xor_by clamps to a nibble."""
    return [f"wflip arr + {i}*dw + w, {((i*7+1) & 0xFF)}*dw" for i in range(n)]


print("CONTROL 2 -- the pre-load must actually store bytes (no clear):")
ops, vals = build(preload(8), 8)
want = [((i * 7 + 1) & 0xFF) for i in range(8)]
print(f"  read back {[hex(v) for v in vals]}")
print(f"  wanted    {[hex(v) for v in want]}   "
      f"{'ok' if vals == want else '!! PRE-LOAD IS VACUOUS'}")
assert vals == want, "the pre-load did not store bytes; every number below would be meaningless"

print("\nCONTROL 1 -- every byte value 0..255 must clear to 0:")
N = 256
ops, vals = build(preload(N) + [f"rep({N}, i) m1.zerobyte arr + i*dw"], N)
nz = [(i, v) for i, v in enumerate(vals) if v]
print(f"  {N} cells, values (i*7+1)&0xFF; non-zero after the clear: {len(nz)}  "
      f"{'ok' if not nz else '!! ' + str(nz[:6])}")
assert not nz, "zerobyte does not clear every value"

print("\nCOST (per-cell, from the difference of two sizes):")
rows = []
for name, mk in (
    ("m1.zerobyte (no pointer)",
     lambda n: preload(n) + [f"rep({n}, i) m1.zerobyte arr + i*dw"]),
    ("hex.zero_ptr (baseline)",
     lambda n: preload(n) + ["hex.set w/4, p, arr",
                             f"rep({n}, i) m1.zp"]),
):
    tail = ()
    if "zero_ptr" in name:
        pass
    a_ops, _v = build(mk(64), 64, extra_tail=tail)
    b_ops, _v = build(mk(192), 192, extra_tail=tail)
    per = (b_ops - a_ops) / (192 - 64)
    rows.append((name, a_ops, b_ops, per))
    print(f"  {name:<28}{a_ops:>9,}{b_ops:>10,}{per:>10.1f} ops/cell")

fast, slow = rows[0][3], rows[1][3]
print(f"\n  => {slow/fast:.1f}x cheaper than the pointer path "
      f"({slow:.0f} -> {fast:.0f} ops/cell)")
print(f"  => 1,002 byte cells: {1002*slow:,.0f} -> {1002*fast:,.0f} ops")
