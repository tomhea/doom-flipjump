"""Run the REAL `scratchpad/deg_gate.py` with the assembler's table-placement pass on.

Not a copy of the gate -- a wrapper that patches `flipjump.assemble` and then executes the gate
itself. CLAUDE.md rule 3: "a fast pre-gate is for saving 20 minutes, never for replacing the gate",
and a duplicated gate is a pre-gate that looks like the gate. Whatever deg_gate checks, this
checks, because it IS deg_gate.

    python scratchpad/12m/deg_gate_placed.py --off                      # baseline, for the deltas
    python scratchpad/12m/deg_gate_placed.py --top 8192 --run-ops 16
    python scratchpad/12m/deg_gate_placed.py --selftest                 # R9 control: 1.6s, no build
    python scratchpad/12m/deg_gate_placed.py --selftest-gate            # R9 control: one assemble

WHAT THE VERDICT MEANS HERE. deg_gate asserts 4 viewpoints byte-exact and prints their op counts.
Byte-exactness is the correctness proof. The op counts are EXPECTED to change -- that is the whole
point of the pass -- which is the one case where CLAUDE.md's "an op-count change with byte-exact
pixels means you changed structure" is the intended result rather than a bug to chase. A run that
relocated NOTHING is no longer a pass: it assembled the stock program, so the gate's verdict says
nothing about the pass (deg_gate_driver.verdict).

The patch, the exit status and both --selftest arms live in `deg_gate_driver.py`, shared with
deg_gate_blocked.py so the two cannot drift; the checks in `_driver_controls` below are this
driver's own, because the shared arm's fixture expands none of the macros HOT_OWNERS names. The
cheap arm does NOT cover the E1M1 program: it runs a 10-line pointer fixture, and no pixel is
compared anywhere in it.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import deg_gate_driver as driver                                        # noqa: E402
import flipjump as fj                                                   # noqa: E402
from flipjump.assembler.preprocessor import TablePool                   # noqa: E402
from doomfj.harness import W                                            # noqa: E402

DRIVER = "deg_gate_placed"

# The macros the profile named as owning the hot tables (FINDINGS BD): the TEN below own the top
# 16,384 tables, 86.4% of every exact_xor call. (BD's own prose says "eleven own the top 16,384
# (86.4%)" and then names these ten -- scratchpad/12m/FINDINGS.md, "Where the hot tables are". The
# names are the part a tuple can copy; the count is BD's to correct.) Matched by NAME, because an
# exact label path embeds src/fj line numbers and goes stale silently the moment those are edited.
HOT_OWNERS = (
    "frame.seg_pass1_leaf_body_lines",
    "frame.seg_pass2_leaf_body_lines",
    "frame.seg_pass1_leaf_body_ts",
    "proj.point_on_side_leaf",
    "frame.thing_record_body",
    "proj.wedge_bbox",
    "sim.thing_pass",
    "sim.check_position",
    "sim.try_move",
    "sim.bind_things",
)


def build_pool(a, force=False):
    """The pool this driver installs, or None for the --off baseline.

    --selftest passes force: the control needs a pass to control, and the baseline has none. The
    `wants` lambda reads HOT_OWNERS at CALL time, which is what lets _driver_controls point it at a
    macro the fixture does expand and see this same code relocate.
    """
    if a.off and not force:
        return None
    return TablePool(W, a.pool_base, run_ops=a.run_ops, capacity=a.top,
                     span_bits=a.span_bits,
                     wants=lambda macro_name, prefix: any(o in prefix for o in HOT_OWNERS))


def make_assemble(pool):
    """-> (the `flipjump.assemble` replacement, the list every call appends to).

    --selftest installs the SAME closure the gate runs under, and one of its stub gates CALLS
    fj.assemble through it, so the control drives this body rather than a copy of it -- on the
    fixture, not on E1M1. The list is that proof: it grows only when the body runs.
    """
    real_assemble = fj.assemble
    calls = []

    def assemble_with_pool(*args, **kwargs):
        calls.append(pool)
        kwargs["table_pool"] = pool
        return real_assemble(*args, **kwargs)

    return assemble_with_pool, calls


def run(a):
    pool = build_pool(a)
    if pool is None:
        print("PLACEMENT OFF (baseline)", flush=True)
    else:
        print("PLACEMENT ON: base %s, span %s, run_ops %d, cap %s"
              % (hex(a.pool_base), hex(a.span_bits), a.run_ops, format(a.top, ",")), flush=True)
    assemble_with_pool, calls = (None, None) if pool is None else make_assemble(pool)
    status = driver.run_gate(assemble_with_pool)
    if pool is not None:
        # The call list is KEPT, as deg_gate_blocked.py keeps its pools: "the gate never assembled"
        # and "the pool was offered nothing it wanted" are different failures, and a driver that
        # threw the list away could only report the second -- verdict is then free to say what it
        # can establish from the pool's own state and nothing more.
        if not calls:
            print("*** VACUOUS: the gate never called fj.assemble, so the pool was never installed",
                  flush=True)
            return status or 2
        # "relocated nothing" is driver.verdict's to report -- it is the same condition, and two
        # messages for one condition read as two problems.
        print("relocated: %s tables into %s runs; declined %s"
              % (format(pool.allocated, ","), format(len(pool.run_starts), ","),
                 format(pool.declined, ",")), flush=True)
    return driver.verdict(status, pool)


def _driver_controls(a, check, tmp, src):
    """The R9 checks only THIS driver can make. The shared arm controls the assembler's pin
    machinery and the wrapper's plumbing; HOT_OWNERS, --top and --run-ops are this pool's own, and
    a fixture that expands none of the hot macros cannot control any of them by accident."""
    global HOT_OWNERS
    pool = build_pool(a, force=True)
    hot, cold = "x.proj.point_on_side_leaf.y", "x.hex.tables.y"
    check(pool.wants(None, hot) and not pool.wants(None, cold),
          "HOT_OWNERS decides which CALL SITES this pool relocates",
          "%s %s, %s %s" % (hot, pool.wants(None, hot), cold, pool.wants(None, cold)))
    check(build_pool(argparse.Namespace(**dict(vars(a), off=True))) is None,
          "--off builds no pool at all (nothing for verdict to call vacuous)")

    off_out, off_ops, _ = driver.build_and_run(src, tmp, "hot", None,
                                               assemble=make_assemble(pool)[0])
    check(pool.allocated == 0 and off_out == driver.FIXTURE_OUTPUT,
          "... and the fixture expands NONE of them, so this pool moves nothing here",
          "%d tables, %r in %d ops" % (pool.allocated, off_out, off_ops))

    saved = HOT_OWNERS
    try:
        HOT_OWNERS = ("hex.",)          # a prefix the fixture does expand, everything else equal
        wide = build_pool(a, force=True)
        wide_out, wide_ops, _ = driver.build_and_run(src, tmp, "wide", None,
                                                     assemble=make_assemble(wide)[0])
        capped = build_pool(argparse.Namespace(**dict(vars(a), top=1)), force=True)
        cap_out, cap_ops, _ = driver.build_and_run(src, tmp, "capped", None,
                                                   assemble=make_assemble(capped)[0])
    finally:
        HOT_OWNERS = saved
    check(wide.allocated > 0 and wide_out == off_out and wide_ops < off_ops,
          "MUTANT: point HOT_OWNERS at one it DOES expand -> tables move, output does not",
          "%d tables, %r, %d -> %d ops" % (wide.allocated, wide_out, off_ops, wide_ops))
    check(capped.allocated == 1 and cap_out == off_out and cap_ops > wide_ops,
          "--top is the cap on that: 1 table, not %d" % wide.allocated,
          "%d tables, %r in %d ops" % (capped.allocated, cap_out, cap_ops))
    check(pool.run_bits == a.run_ops * 2 * W, "--run-ops is the run length the pool hands out",
          "run_bits=%d for run_ops=%d at w=%d" % (pool.run_bits, a.run_ops, W))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--off", action="store_true", help="run the gate unmodified (the baseline)")
    ap.add_argument("--top", type=int, default=8192)
    ap.add_argument("--run-ops", type=int, default=16)
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=1 << 27)
    ap.add_argument("--selftest", action="store_true",
                    help="R9 negative control, 1.6s measured and NO build: mutate the table "
                         "pool, the assembler's pin exclusion and this driver's own knobs on a "
                         "10-line fj program, and require each mutation to break something. It "
                         "controls the DEFAULT configuration, so the tuning flags above are not "
                         "applied to it (and it says which it dropped). See deg_gate_driver.py "
                         "for what it misses.")
    ap.add_argument("--selftest-gate", action="store_true",
                    help="R9 negative control that COSTS A BUILD (one E1M1 assemble, four runs): "
                         "the real gate under the real pool, against an oracle corrupted by one "
                         "byte -- all four viewpoints must report px DIFFER. Rule 1 applies.")
    a = ap.parse_args()

    if a.selftest:
        # the DEFAULTS, never `a`: the control's subject is this driver's default configuration, so
        # its verdict cannot depend on what else is on the command line (driver.control_args).
        ctl = driver.control_args(ap, a)
        assemble_with_pool, calls = make_assemble(build_pool(ctl, force=True))
        return driver.cheap_selftest(
            DRIVER, assemble_with_pool, body_ran=lambda: len(calls),
            extra=lambda check, tmp, src: _driver_controls(ctl, check, tmp, src))
    if a.selftest_gate:
        return driver.gate_selftest(DRIVER, lambda: run(a))
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
