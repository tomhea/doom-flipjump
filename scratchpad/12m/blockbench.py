"""Does BLOCKING actually work? Measure the marginal cost of one `hex.xor`, stock vs blocked.

FINDINGS BD priced blocking at 13,864,136 ops/frame and BE showed BD's PLACEMENT projection missed
by 15x. So this validates blocking's MECHANISM against the interpreter before anyone builds it,
which is what should have happened to placement.

THE IDEA. `hex.exact_xor` arms a switch table by writing its ADDRESS into the hex variable's jump
word, costing `2 * popcount(address)` executed ops. A hex variable is a single op `;val*dw`, so
that word already holds the variable's VALUE, and `wflip src+w, switch` makes it `switch + digit`.

Blocking bakes a BASE into the variable instead -- `;(BASE + val*dw)` -- and puts every table that
this variable dispatches to in one aligned block at BASE. The arm then only has to flip the INDEX
within the block:

    wflip src+w, IDX*16*dw, src        <- popcount(IDX), not popcount(address)
  ret:
    wflip src+w, IDX*16*dw

BASE is 16-op aligned, so it has zeros where the value's nibble lives and the variable still reads
back correctly.

    python scratchpad/12m/blockbench.py
    python scratchpad/12m/blockbench.py --selftest

TWO ALIGNMENT RULES, both learned by breaking them:
  * THE BLOCK, NOT THE TABLE, SETS THE ALIGNMENT. `pad 16` aligns to ONE table, which leaves the
    index bits (10..13) free to be already-set in BASE -- and then the XOR SUBTRACTS instead of
    adding. Measured: BASE=556,032 has bit 10 set, so arming index 1 jumped to 555,328 instead of
    557,376. The block must be aligned to `block_tables * 16` ops.
  * THE BLOCK SIZE MUST BE A POWER OF TWO, for the same reason: `pad 144` for a 9-table block does
    not clear the index bits either.

CONTROLS (R9)
  C1 CORRECTNESS -- the blocked program must reach `stl.loop` (cause `looping`) and compute the
     same value as the stock one. A blocked program that dies early has a LOWER op count, so op
     count alone would read as a win.
  C2 THE MARGINAL COST MUST FALL -- and be measured as a SLOPE over K, not as one program's total,
     because the two programs differ in setup (stock must `hex.set` the source; blocked bakes it).
  C3 MISALIGNMENT IS CAUGHT -- a non-power-of-two block must break, proving the alignment rule is
     load-bearing rather than a precaution.
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                    # noqa: E402
from flipjump.interpreter.fjm_run import run as fjm_run                  # noqa: E402
from flipjump.interpreter.io_devices.IODevice import IODevice            # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                        # noqa: E402
from doomfj.harness import W                                             # noqa: E402
from doomfj.config import Config                                         # noqa: E402

NS = """
ns hexx {
    def hex_at BASE, val {
        ;(BASE + (val)*dw)
    }
    def xor_blk IDX, src, ret {
        wflip src+w, IDX*16*dw, src
      ret:
        wflip src+w, IDX*16*dw
    }
    def table_at tbl, d3, d2, d1, d0, ret {
          ;ret
        d0;ret
        d1;ret
        d1;tbl+1*dw
        d2;ret
        d2;tbl+1*dw
        d2;tbl+2*dw
        d2;tbl+3*dw
        d3;ret
        d3;tbl+1*dw
        d3;tbl+2*dw
        d3;tbl+3*dw
        d3;tbl+4*dw
        d3;tbl+5*dw
        d3;tbl+6*dw
        d3;tbl+7*dw
    }
}
"""


class Capture(IODevice):
    def __init__(self):
        self.bits = []
        self.out = bytearray()

    def read_bit(self):
        raise IOReadOnEOF("no input")

    def write_bit(self, b):
        self.bits.append(1 if b else 0)
        if len(self.bits) == 8:
            self.out.append(sum(v << i for i, v in enumerate(self.bits)))
            self.bits = []

    def attach_memory(self, m):
        pass

    def get_output(self, *a, **k):
        return bytes(self.out)


def stock_program(k, show=False):
    lines = ["stl.startup_and_init_all", "    hex.set 1, a, 0x3", "    hex.set 1, b, 0x5",
             "    rep(%d, i) hex.xor a, b" % k]
    if show:
        lines.append("    hex.print a")
    lines += ["    stl.loop", "a: hex.vec 1", "b: hex.vec 1"]
    return "\n".join(lines) + "\n"


def blocked_program(k, show=False, block=None):
    """block defaults to the next POWER OF TWO >= k -- see the alignment rules above"""
    if block is None:
        block = 1 << max(0, (k - 1).bit_length())
    lines = ["stl.startup_and_init_all", "    hex.set 1, a, 0x3"]
    for i in range(k):
        lines.append("    hexx.xor_blk %d, b, BACK%d" % (i, i))
    if show:
        lines.append("    hex.print a")
    lines += ["    stl.loop", "a: hex.vec 1", "pad %d" % (block * 16), "TBLBASE:"]
    for i in range(k):
        lines.append("    hexx.table_at TBLBASE+%d*16*dw, "
                     "a+dbit+3, a+dbit+2, a+dbit+1, a+dbit+0, BACK%d" % (i, i))
    # `b` goes AFTER the tables on purpose: `hex.print` emits the byte formed by two ADJACENT
    # nibbles, so a source variable sitting next to `a` changes the printed byte and reads as a
    # correctness failure that is really a layout difference.
    lines.append("b: hexx.hex_at TBLBASE, 0x5")
    return "\n".join(lines) + "\n"


def run(source):
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        consts = Config().emit_fj_consts(t / "fj_consts.fj")
        (t / "s.fj").write_text(NS + source, encoding="utf-8")
        out = t / "o.fjm"
        fj.assemble([consts.resolve(), (t / "s.fj").resolve()], out,
                    memory_width=W, print_time=False)
        cap = Capture()
        term = fjm_run(out, io_device=cap, print_time=False, flat_max_words=1 << 27)
        # str(): termination_cause is an ENUM. Comparing it to "looping" directly is vacuously
        # false, so `cause != "looping"` would pass whatever happened -- a control that fails open.
        return term.op_counter, str(term.termination_cause), bytes(cap.out)


def bench(ks):
    print("marginal cost of one hex.xor -- stock vs blocked")
    print("")
    print("  %-6s %-24s %-24s" % ("K", "stock", "blocked (block=2^n)"))
    rows = {}
    for k in ks:
        s_ops, s_cause, _ = run(stock_program(k))
        b_ops, b_cause, _ = run(blocked_program(k))
        rows[k] = (s_ops, b_ops, s_cause, b_cause)
        print("  %-6d %-8d %-15s %-8d %-15s" % (k, s_ops, s_cause, b_ops, b_cause))
    lo, hi = min(ks), max(ks)
    if lo != hi:
        span = hi - lo
        s_slope = (rows[hi][0] - rows[lo][0]) / span
        b_slope = (rows[hi][1] - rows[lo][1]) / span
        print("")
        print("  MARGINAL ops per xor (K=%d -> K=%d):" % (lo, hi))
        print("    stock   : %.2f ops/xor" % s_slope)
        print("    blocked : %.2f ops/xor  (%.1f%%)" % (b_slope, 100.0 * (b_slope - s_slope) / s_slope))
        print("")
        print("  In THIS program the stock table addresses are ~popcount 8. In the shipped game")
        print("  they are popcount 9.32 (FINDINGS BD), so stock's real per-call cost is higher")
        print("  than the slope above and blocking's advantage there is larger. That extrapolation")
        print("  is NOT measured here -- BD's arithmetic missed by 15x (BE).")
    return rows


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("blockbench selftest", flush=True)

    # C1 -- the blocked program must RUN, not just be cheap
    s_ops, s_cause, s_out = run(stock_program(1, show=True))
    b_ops, b_cause, b_out = run(blocked_program(1, show=True))
    check("C1 the blocked program reaches stl.loop", b_cause == "looping", b_cause)
    check("C1 ...and so does the stock one", s_cause == "looping", s_cause)
    check("C1 blocked computes 0x3 ^ 0x5 = 6", b_out and b_out[-1] & 0xF == 6, repr(b_out))

    # C2 -- the slope, not the total
    rows = {}
    for k in (1, 32):
        rows[k] = (run(stock_program(k))[0], run(blocked_program(k))[0])
    s_slope = (rows[32][0] - rows[1][0]) / 31.0
    b_slope = (rows[32][1] - rows[1][1]) / 31.0
    check("C2 blocked has a LOWER marginal cost per xor", b_slope < s_slope,
          "%.2f vs %.2f ops/xor" % (b_slope, s_slope))

    # C3 -- the alignment rule is load-bearing: a non-power-of-two block must break
    ops9, cause9, _ = run(blocked_program(9, block=9))
    check("C3 a NON-power-of-two block breaks (index bits not clear)", cause9 != "looping",
          "cause=%s" % cause9)
    ops16, cause16, _ = run(blocked_program(9, block=16))
    check("C3 ...and the power-of-two block for the same K works", cause16 == "looping",
          "cause=%s" % cause16)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, nargs="*", default=[1, 4, 16, 32])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    bench(a.k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
