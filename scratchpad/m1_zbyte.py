"""M1 -- a BYTE clear with NO pointer arithmetic, for a cell at a CONSTANT address.

THE IDEA (owner's). `hex.zero_ptr` costs 943 ops/cell and almost all of it is
`set_flip_and_jump_pointers` -- copying an 8-nibble ADDRESS into `to_flip`/`to_jump` so the machine
can reach a cell it only knows at runtime. But the reset knows every address at EMIT time. Nothing
has to be computed: the address is baked straight into the ops.

The stl already contains the only hard part -- `read_ptr_byte_table`, a 256-entry table at op 256
that decomposes a byte. `read_byte_from_inners_ptrs` drives it through the pointer registers; with a
constant address it can be driven directly:

    hex.zero 2, read_byte                  # the register the table xors into
    wflip ret_after_read_byte+w, back      # where the table should return
    C+dbit+8 ; C                           # set bit dbit+8, then JUMP INTO THE CELL:
                                           #   its jump word is now (v+256)*dw = table entry v,
                                           #   which xors v's bits into read_byte and returns
  back:
    wflip ret_after_read_byte+w, back      # undo the return address
    C+dbit+8 ;                             # undo the marker bit
    hex.exact_xor C+dbit+3..0, read_byte      # C ^= v  -> low nibble cleared
    hex.exact_xor C+dbit+7..4, read_byte+dw   # C ^= v  -> high nibble cleared

`hex.exact_xor` takes ARBITRARY BIT ADDRESSES for its four flip targets, so it can reach the HIGH
nibble of a byte cell -- exactly what `hex.zero` cannot do, and why a nibble op corrupts a byte
cell (M1a / R57).

NEGATIVE CONTROLS (R9):
  1. CORRECTNESS ACROSS THE WHOLE RANGE: every value 0..255 is planted and must come back 0. A
     clear tested only on small values would pass while the high nibble silently survived -- the
     exact failure mode `hex.zero` has.
  2. THE PRE-LOAD IS CHECKED: a run with the clear removed must read back the planted bytes. An
     earlier cost measurement in this session was vacuous because `hex.xor_by` clamps to a nibble
     and the byte was never planted at all.
  3. NEIGHBOURS UNTOUCHED: the cells past the end must stay 0 -- a 1-cell stride means a clear one
     bit too wide lands in the next entry.
  4. COST FROM A DIFFERENCE of two sizes, so fixed startup cannot be smuggled into per-cell.

    python scratchpad/m1_zbyte.py
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

MACRO = [
    "ns m1 {",
    "    // zero the BYTE cell at the CONSTANT address `c` -- no pointer, no address arithmetic.",
    "    def zbyte c @ back < hex.pointers.read_byte, hex.pointers.ret_after_read_byte {",
    "        hex.zero 2, hex.pointers.read_byte",
    "        wflip hex.pointers.ret_after_read_byte+w, back",
    "        c+dbit+8; c",
    "      back:",
    "        wflip hex.pointers.ret_after_read_byte+w, back",
    "        c+dbit+8;",
    "        hex.exact_xor c+dbit+3, c+dbit+2, c+dbit+1, c+dbit+0, hex.pointers.read_byte",
    "        hex.exact_xor c+dbit+7, c+dbit+6, c+dbit+5, c+dbit+4, hex.pointers.read_byte+dw",
    "    }",
    "}",
]


def build_run(n, values, clear=True):
    lines = list(MACRO) + ["stl.startup_and_init_all"]
    for i, v in enumerate(values):
        if v:
            lines.append("wflip arr + %d*dw + w, %d*dw" % (i, v))
    if clear:
        lines.append("rep(%d, i) m1.zbyte arr + i*dw" % n)
    lines += ["stl.loop", "arr: hex.vec %d" % (n + 2)]
    tmp = Path(tempfile.mkdtemp(prefix="zbyte_"))
    src = tmp / "p.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False, debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)
    base = min(v for k, v in labels.items() if k == "arr" or k.endswith(":arr")) // W
    r = FjmRunner(out, flat_max_words=1 << 24)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, ln in r._segments:
        core.add_segment(s, ln)
    for st, vals in r._runs:
        core.set_words(st, vals)
    _c, ops, _e, _l, _p = core.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)
    got = [core.get_word(base + 2 * i + 1) >> VAL for i in range(n + 2)]
    return ops, got


ok = True
N = 64
VALUES = [(i * 4 + 1) & 0xFF for i in range(N)]

print("CONTROL 2 -- the pre-load must actually plant BYTES (clear removed):")
_ops, got = build_run(N, VALUES, clear=False)
planted = got[:N] == VALUES
print("  planted %s... -> read back %s...  %s"
      % (VALUES[:6], got[:6], "ok" if planted else "!! THE PRE-LOAD IS VACUOUS"))
ok &= planted

print("")
print("CONTROL 1 -- every value 0..255 must clear to 0:")
_ops2, got2 = build_run(256, list(range(256)))
bad = [(i, v) for i, v in enumerate(got2[:256]) if v != 0]
print("  256 cells planted with 0..255, cleared -> %d not zero  %s"
      % (len(bad), "ok" if not bad else "!! " + str(bad[:6])))
ok &= not bad

print("")
print("CONTROL 3 -- the two cells past the end must be untouched:")
tail_ok = got2[256] == 0 and got2[257] == 0
print("  arr[256]=%#x arr[257]=%#x  %s" % (got2[256], got2[257], "ok" if tail_ok else "!! SPILLED"))
ok &= tail_ok

print("")
print("CONTROL 4 -- cost from a DIFFERENCE of two sizes:")
o1, _g = build_run(64, [(i * 4 + 1) & 0xFF for i in range(64)])
o2, _g = build_run(192, [(i * 4 + 1) & 0xFF for i in range(192)])
per = (o2 - o1) / (192 - 64)
print("  n=64 %s ops   n=192 %s ops   -> %.1f ops/cell" % (format(o1, ","), format(o2, ","), per))
print("")
print("  hex.zero_ptr (pointer path)       943.0 ops/cell   [measured earlier]")
print("  m1.zbyte     (constant address)  %6.1f ops/cell   -> %.1fx cheaper" % (per, 943 / per))
print("")
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
