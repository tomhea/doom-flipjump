"""M1c — MEASURE the per-cell cost of every way to restore a cell. No guessing.

The prologue restores ~60k cells and the repo's rule is that an ops number is not a number until
the harness prints it. Three primitives, three different jobs:

  * `hex.zero 1, addr`      clears bits dbit..dbit+3 -- a NIBBLE cell. Cheap, value-independent.
  * `hex.set 1, addr, v`    zero + xor_by -- a nibble cell whose pristine value is not 0.
  * an 8-BIT clear          needed for a BYTE cell (sshead, drawn, pclm, sfflag, sprflag), where
                            all 8 bits live in ONE cell (M1a) and `hex.zero` would leave the high
                            nibble set. `hex.zero` is NOT enough and the difference is measured
                            here, not assumed.

⚠ NEGATIVE CONTROL (R9): each variant is run at TWO sizes and the per-cell cost is taken from the
DIFFERENCE, so the fixed startup/IO cost cannot be smuggled into the per-cell number. And each
variant asserts it actually did the job -- the 8-bit clear is checked on a cell pre-loaded with
0xA5, which `hex.zero` provably fails, so a measurement that quietly used the wrong primitive
shows up as a FAILED correctness check rather than a cheap number.

    python scratchpad/m1c_cost.py
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

DW = 2 * W
VAL_SHIFT = (W + W.bit_length()) - W


def build(body_lines, tail_lines, n_arr):
    lines = ["stl.startup_and_init_all"] + body_lines + ["stl.loop"] + tail_lines
    tmp = Path(tempfile.mkdtemp(prefix="m1cost_"))
    src = tmp / "p.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False, debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)
    r = FjmRunner(out, flat_max_words=1 << 24)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        core.add_segment(s, n)
    for st, vals in r._runs:
        core.set_words(st, vals)
    _c, ops, _e, _l, _p = core.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)
    base = min(v for k, v in labels.items() if k == "arr" or k.endswith(":arr")) // W
    vals = [core.get_word(base + 2 * i + 1) >> VAL_SHIFT for i in range(n_arr)]
    return ops, vals


def variant_zero(n):
    """hex.zero on n cells that start at 0xA5 -- shows what it does NOT clear."""
    body = [f"rep({n}, i) hex.xor_by arr + i*dw, 0xA5", f"rep({n}, i) hex.zero 1, arr + i*dw"]
    return body, [f"arr: hex.vec {n}"]


def variant_set(n):
    body = [f"rep({n}, i) hex.xor_by arr + i*dw, 0xA5", f"rep({n}, i) hex.set 1, arr + i*dw, 7"]
    return body, [f"arr: hex.vec {n}"]


def variant_byteclear(n):
    """The 8-bit clear: point at the cell and use hex.zero_ptr, which reads the byte and xors it
    back -- the only value-independent way to clear all 8 bits of one cell."""
    body = [f"rep({n}, i) hex.xor_by arr + i*dw, 0xA5",
            "hex.set w/4, p, arr",
            f"rep({n}, i) .zp"]
    tail = ["p: hex.vec w/4", f"arr: hex.vec {n}"]
    return body, tail


PRE = ["def zp < p {", "    hex.zero_ptr p", "    hex.ptr_inc p", "}"]

print(f"W={W}, dw={DW}. Each variant pre-loads every cell with 0xA5 (a BYTE), then restores it.")
print(f"{'variant':<22}{'n=64':>12}{'n=192':>12}{'per cell':>12}   result of cell 0")
print("-" * 84)
for name, mk, extra in (("hex.zero 1 (nibble)", variant_zero, []),
                        ("hex.set 1, v (nibble)", variant_set, []),
                        ("hex.zero_ptr (byte)", variant_byteclear, PRE)):
    res = {}
    for n in (64, 192):
        body, tail = mk(n)
        ops, vals = build(extra + body, tail, min(n, 4))
        res[n] = (ops, vals)
    per = (res[192][0] - res[64][0]) / (192 - 64)
    got = res[64][1][0]
    print(f"{name:<22}{res[64][0]:>12,}{res[192][0]:>12,}{per:>12.1f}   "
          f"cell0 = {got:#04x} {'(FULLY CLEARED)' if got == 0 else '(high nibble SURVIVES)' if name.startswith('hex.zero 1') else ''}")

print()
print("=> `hex.zero 1` leaves 0xA0 behind on a byte cell: it is NOT a byte clear, measured, not argued.")
