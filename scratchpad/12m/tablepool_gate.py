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
from flipjump.assembler.preprocessor import BlockPool                        # noqa: E402
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
    # BLOCKING (BlockPool) -- two passes, because a block's size must be known before its base is
    # chosen and a group's tables are scattered through the program.
    print("")
    print("  %-36s %-10s %-9s %-7s %s" % ("program / blocking", "output", "ops", "groups", "verdict"))
    for name, source in PROGRAMS.items():
        ref_out, ref_ops, _ = build_and_run(source, None)
        counting = BlockPool(W, POOL_BASE)
        build_and_run(source, counting)                       # counts only; relocates nothing
        placing = BlockPool(W, POOL_BASE, counts=counting.counts, widths=counting.widths)
        got, ops, _ = build_and_run(source, placing)
        ok = got == ref_out
        if not ok:
            failures.append("%s [blocked]" % name)
        print("  %-36s %-10r %-9d %-7d %s%s"
              % (name[:36], got, ops, len(placing.groups),
                 "SAME" if ok else "*** DIFFERENT ***",
                 "" if not ok else "  %+.2f%% ops" % (100.0 * (ops - ref_ops) / ref_ops)))

    # THE DECLINE CONTROL. A group that cannot place every table must be UN-PINNED, or its inline
    # tables become unreachable: pinning makes every writer of that word flip `V ^ base`, which is
    # only right if the table being armed is in the block. The first game-tier block build hit this
    # and presented 0 FRAMES IN 124 OPS -- while the M1 reset check and the rows above all passed.
    # A tiny span forces declines, so this row exercises the path on purpose.
    print("")
    print("  %-36s %-10s %-9s %-7s %s" % ("program / blocking, span forced tiny",
                                          "output", "ops", "declined", "verdict"))
    for name, source in PROGRAMS.items():
        ref_out, ref_ops, _ = build_and_run(source, None)
        counting = BlockPool(W, POOL_BASE, span_bits=1 << 16)
        build_and_run(source, counting)
        placing = BlockPool(W, POOL_BASE, counts=counting.counts, widths=counting.widths,
                            span_bits=1 << 16)
        got, ops, _ = build_and_run(source, placing)
        ok = got == ref_out
        if not ok:
            failures.append("%s [blocked, declines]" % name)
        print("  %-36s %-10r %-9d %-7d %s%s"
              % (name[:36], got, ops, placing.declined,
                 "SAME" if ok else "*** DIFFERENT ***",
                 "" if not placing.declined else "  (%d group(s) un-pinned)" % len(placing.broken_groups)))

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

    # C5 -- THE UN-PIN IS LOAD-BEARING. Put the broken groups back into pinned_words and a
    # decline-forced build must produce the WRONG answer. Without this, C4's decline row could be
    # green for some unrelated reason.
    decl_src = PROGRAMS["hex.cmp/shift/mul"]
    decl_ref, _, _ = build_and_run(decl_src, None)

    def forced(_span=None):
        # UNDERSIZED COUNTS, not a small span. A span-exhausted group is declined BEFORE it is
        # created, so it was never pinned and the old code was already safe for it. The dangerous
        # decline is `index >= slots`: a group that WAS created and pinned and then overflows --
        # which is exactly what the game tier does, where pass 2 sees the M1 reset part's extra
        # tables (175,533 blocked in pass 1, 177,293 in pass 2).
        counting = BlockPool(W, POOL_BASE)
        build_and_run(decl_src, counting)
        starved = {g: 1 for g in counting.counts}
        placing = BlockPool(W, POOL_BASE, counts=starved, widths=counting.widths)
        return placing, build_and_run(decl_src, placing)

    placing, (fixed_out, _, _) = forced()
    check("C5 with declines, the un-pinned build is correct", fixed_out == decl_ref,
          "%d declined, %d group(s) un-pinned" % (placing.declined, len(placing.broken_groups)))
    # PINNING A DECLINED GROUP ANYWAY IS ALSO CORRECT, and asserting otherwise was a false control
    # this selftest carried until it failed. A consistent base CANCELS:
    # `(B + digit) ^ (switch ^ B)` is `switch + digit` wherever the table sits. So the un-pin is a
    # safety margin, not a fix -- and it is NOT what made the broken game build fail.
    #
    # ALIASING is the case that genuinely breaks, because two DIFFERENT bases do not cancel.
    from flipjump.assembler.assembler import resolve_pinned                  # noqa: E402

    class FakeExpr:
        def __init__(self, value):
            self.value = value

        def exact_eval(self, _labels):
            return self.value

    same_a, same_b = FakeExpr(4096), FakeExpr(4096)
    pinned, conflicts = resolve_pinned({same_a: 0x1000, same_b: 0x2000}, {})
    check("C6 two expressions on ONE address with DIFFERENT bases are un-pinned",
          4096 not in pinned and conflicts == 1, "pinned=%s conflicts=%d" % (pinned, conflicts))
    pinned2, conflicts2 = resolve_pinned({same_a: 0x1000, same_b: 0x1000}, {})
    check("C6 ...but the SAME base on one address is kept (not a conflict)",
          pinned2.get(4096) == 0x1000 and conflicts2 == 0, str(pinned2))
    pinned3, _ = resolve_pinned({FakeExpr(4096): 0x1000, FakeExpr(8192): 0x2000}, {})
    check("C6 ...and distinct addresses are both kept", len(pinned3) == 2, str(pinned3))

    # C8 -- THE RUNTIME'S WORDS ARE NOT THE PROGRAM'S. `stl.IO` is at bit address 64 and
    # `bit.output` dispatches through it, so it looks like an ordinary hex source to the grouper.
    # Baking a base into it corrupts the program's second op -- the blocked game build jumped
    # `ip 64 -> POOL -> ip 64` and presented 0 frames in 116 ops.
    io_pinned, _ = resolve_pinned({FakeExpr(96): 0x70000000, FakeExpr(1 << 20): 0x70001000}, {})
    check("C8 stl.IO's word (64+w) is NOT pinned", 96 not in io_pinned, str(io_pinned))
    check("C8 ...while a normal variable's word still is", (1 << 20) in io_pinned)

    # C7 -- THE VALUE-FLIP DISCRIMINATOR IS LOAD-BEARING. Not every wflip on a pinned word installs
    # a jump target: `hex.set`/`xor_by` wflip the same word to toggle the hex's VALUE bits, and
    # XORing base into those destroys the base. Rewrite ALL of them and the program must break.
    from flipjump.assembler import assembler as asmmod                       # noqa: E402

    blk_src = PROGRAMS["hex.xor"]
    blk_ref, _, _ = build_and_run(blk_src, None)

    def blocked_run():
        counting = BlockPool(W, POOL_BASE)
        build_and_run(blk_src, counting)
        placing = BlockPool(W, POOL_BASE, counts=counting.counts, widths=counting.widths)
        return placing, build_and_run(blk_src, placing)

    placing, (good_out, good_ops, _) = blocked_run()
    check("C7 blocking is correct and cheaper", good_out == blk_ref and good_ops < 1685,
          "%d pinned groups, %d ops" % (len(placing.pinned_words()), good_ops))

    real_insert = asmmod.BinaryData.insert_wflip_ops

    def rewrite_everything(self, word_address, flip_value, return_address):
        """XOR the base into EVERY wflip on a pinned word -- no magnitude test. Then call the real
        method with pinning switched off, so the rewrite happens exactly once."""
        saved = self.pinned
        if saved:
            base = saved.get(word_address)
            if base:
                flip_value ^= base
        self.pinned = None
        try:
            return real_insert(self, word_address, flip_value, return_address)
        finally:
            self.pinned = saved

    asmmod.BinaryData.insert_wflip_ops = rewrite_everything
    try:
        _, (bad_out, _, _) = blocked_run()
    except Exception as exc:                                                # noqa: BLE001
        bad_out = "raised: %s" % type(exc).__name__
    finally:
        asmmod.BinaryData.insert_wflip_ops = real_insert
    check("C7 ...rewriting EVERY wflip on a pinned word breaks it", bad_out != blk_ref,
          "all-rewritten=%r vs %r" % (bad_out, blk_ref))
    _, (restored_out, _, _) = blocked_run()
    check("C7 ...and the discriminator was restored", restored_out == blk_ref)

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
