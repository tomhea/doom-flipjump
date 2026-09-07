"""THE GATE for the assembler's table-placement pass: does relocating a lookup table change what
the program does?

WHY THE PASS EXISTS. `hex.exact_xor`'s switch table is reached only by a jump, so it can live
anywhere -- but the two `wflip`s that arm and disarm it write the table's ADDRESS into a hex
variable's jump word, and the assembler emits one executed op per set bit. FINDINGS BD measured
that 61,617,683 of 78,675,599 ops in a shipped-game walk (78.32%) are wflips into such a word, at
a mean table popcount of 9.32. Moving tables to low-popcount addresses is therefore the single
largest lever in the program, and it changes no semantics.

    python scratchpad/12m/tablepool_gate.py
    python scratchpad/12m/tablepool_gate.py --selftest

THE ONE THING THAT CAN GO WRONG, and it is not hypothetical. "A table is reached only by jump" is
FALSE for some stl tables. `bit.exact_xor` is:

    pad 8
  base_jump_label:
    ;cleanup
    dst;              <- EMPTY jump target: "continue to the next address"
  cleanup:
    wflip src+w, base_jump_label

`dst;` falls THROUGH to `cleanup`. Inline that is the next op; relocated it is the next table's
slot. `preprocessor.relocatable_table_end` rejects exactly this shape by looking for `$` in a jump
expression, and C4 below is the negative control that proves the rejection is load-bearing: with
the guard forced to True, a `bit.exact_xor` program stops producing the right answer.

CONTROLS (R9)
  C1 INERT WHEN OFF -- with no pool, the .fjm is byte-identical to the unpatched assembler's.
     (Proved separately by sha256 against a `git stash` of the assembler; asserted here as the
     weaker "pool=None output equals the reference output".)
  C2 IDENTICAL WHEN ON -- every program must produce the same output at every run_ops.
  C3 IT ACTUALLY MOVED -- tables must land at the pool base, and the op count must FALL. A pass
     that relocates nothing would sail through C2.
  C4 THE GUARD IS LOAD-BEARING -- force `relocatable_table_end` to accept and a fall-through table
     must produce WRONG output. If it still passes, the guard is not what is keeping C2 green.
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                        # noqa: E402
from flipjump.assembler import preprocessor as pp                            # noqa: E402
from flipjump.interpreter.fjm_run import run as fjm_run                      # noqa: E402
from flipjump.interpreter.io_devices.IODevice import IODevice                # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                            # noqa: E402
from doomfj.harness import W                                                 # noqa: E402
from doomfj.config import Config                                             # noqa: E402

POOL_BASE = 1 << 31


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


# Programs chosen to reach different table shapes: hex 16-entry switches, the 2-op tables the
# pointer/compare macros use, bit-level tables (which must be REFUSED), and `hex.add`'s chains.
PROGRAMS = {
    "hex.xor": """
stl.startup_and_init_all
    hex.set 4, a, 0x1234
    hex.set 4, b, 0x5678
    rep(24, i) hex.xor 4, a, b
    hex.print_uint 4, a, 1, 1
    stl.loop
a: hex.vec 4
b: hex.vec 4
""",
    "hex.add/sub": """
stl.startup_and_init_all
    hex.set 4, a, 0x0FE1
    hex.set 4, b, 0x1234
    rep(12, i) hex.add 4, a, b
    rep(5, i) hex.sub 4, a, b
    hex.print_uint 4, a, 1, 1
    stl.loop
a: hex.vec 4
b: hex.vec 4
""",
    "hex.cmp/shift/mul": """
stl.startup_and_init_all
    hex.set 4, a, 0x00F5
    hex.set 4, b, 0x0031
    rep(6, i) hex.shl_bit 4, a
    rep(2, i) hex.shr_hex 4, a
    hex.mul 4, r, a, b
    hex.cmp 4, r, b, LT, EQ, GT
LT:
    hex.print_uint 4, r, 1, 1
    ;done
EQ:
    hex.print_uint 4, b, 1, 1
    ;done
GT:
    hex.print_uint 4, a, 1, 1
done:
    stl.loop
a: hex.vec 4
b: hex.vec 4
r: hex.vec 4
""",
    # THE ONE THAT MUST BE REFUSED: `bit.exact_xor`'s table ends in `dst;`, a fall-through.
    "bit.exact_xor (fall-through table)": """
stl.startup_and_init_all
    rep(16, i) bit.xor a+i*dw, b+i*dw
    bit.print 8, a
    stl.loop
a: bit.vec 16, 0x4A4B
b: bit.vec 16, 0x0102
""",
}


def build_and_run(source, pool):
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        consts = Config().emit_fj_consts(t / "fj_consts.fj")
        (t / "s.fj").write_text(source, encoding="utf-8")
        out = t / "o.fjm"
        fj.assemble([consts.resolve(), (t / "s.fj").resolve()], out,
                    memory_width=W, print_time=False, table_pool=pool)
        cap = Capture()
        term = fjm_run(out, io_device=cap, print_time=False, flat_max_words=1 << 27)
        return bytes(cap.out), term.op_counter, out.stat().st_size


def run_gate(run_ops_list):
    failures = []
    print("table-placement gate -- relocating a lookup table must not change the program")
    print("")
    print("  %-36s %-10s %-9s %-7s %s" % ("program / pool", "output", "ops", "reloc", "verdict"))
    for name, source in PROGRAMS.items():
        ref_out, ref_ops, _ = build_and_run(source, None)
        print("  %-36s %-10r %-9d %-7s %s" % (name + " [inline]", ref_out, ref_ops, "-", "reference"))
        for run_ops in run_ops_list:
            pool = pp.TablePool(W, POOL_BASE, run_ops=run_ops)
            got, ops, _ = build_and_run(source, pool)
            ok = got == ref_out
            if not ok:
                failures.append("%s @run_ops=%d" % (name, run_ops))
            print("  %-36s %-10r %-9d %-7d %s%s"
                  % ("    run_ops=%d" % run_ops, got, ops, pool.allocated,
                     "SAME" if ok else "*** DIFFERENT ***",
                     "" if not ok else "  %+.2f%% ops" % (100.0 * (ops - ref_ops) / ref_ops)))
    print("")
    print("GATE %s%s" % ("PASS" if not failures else "FAIL",
                         "" if not failures else ": " + ", ".join(failures)))
    return 1 if failures else 0


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("tablepool gate selftest", flush=True)
    src = PROGRAMS["hex.xor"]
    ref_out, ref_ops, ref_size = build_and_run(src, None)

    # C1 / C2
    pool = pp.TablePool(W, POOL_BASE, run_ops=16)
    got, ops, _ = build_and_run(src, pool)
    check("C1/C2 relocating hex.xor's tables leaves the output unchanged", got == ref_out,
          "%r vs %r" % (got, ref_out))

    # C3 -- it really moved, and it really got cheaper
    check("C3 tables were relocated", pool.allocated > 0, "%d relocated" % pool.allocated)
    check("C3 the op count FELL (a no-op pass would pass C2 too)", ops < ref_ops,
          "%d -> %d (%+.2f%%)" % (ref_ops, ops, 100.0 * (ops - ref_ops) / ref_ops))

    # C4 -- THE NEGATIVE CONTROL. Force the fall-through guard to accept everything; a
    # `bit.exact_xor` program must then break. If it does not, the guard is not load-bearing and
    # C2's green is coming from somewhere else.
    bit_src = PROGRAMS["bit.exact_xor (fall-through table)"]
    bit_ref, _, _ = build_and_run(bit_src, None)
    guarded, _, _ = build_and_run(bit_src, pp.TablePool(W, POOL_BASE, run_ops=16))
    check("C4 with the guard ON, the fall-through program is correct", guarded == bit_ref,
          "%r vs %r" % (guarded, bit_ref))
    real_guard = pp.relocatable_table_end
    pp.relocatable_table_end = lambda ops, i: (
        len(ops) - 1,
        sum(1 for o in ops[i + 1:] if isinstance(o, pp.FlipJump)),
    )
    try:
        broken, _, _ = build_and_run(bit_src, pp.TablePool(W, POOL_BASE, run_ops=16))
    except Exception as exc:                                                 # noqa: BLE001
        broken = "raised: %s" % type(exc).__name__
    finally:
        pp.relocatable_table_end = real_guard
    check("C4 with the guard FORCED to accept, it breaks (so the guard is load-bearing)",
          broken != bit_ref, "guardless=%r vs %r" % (broken, bit_ref))
    restored, _, _ = build_and_run(bit_src, pp.TablePool(W, POOL_BASE, run_ops=16))
    check("C4 ...and the guard was restored afterwards", restored == bit_ref)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-ops", type=int, nargs="*", default=[16, 64, 256, 4096])
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    return selftest() if a.selftest else run_gate(a.run_ops)


if __name__ == "__main__":
    sys.exit(main())
