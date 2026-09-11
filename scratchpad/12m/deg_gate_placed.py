"""Run the REAL `scratchpad/deg_gate.py` with the assembler's table-placement pass on.

Not a copy of the gate -- a wrapper that patches `flipjump.assemble` and then executes the gate
itself. CLAUDE.md rule 3: "a fast pre-gate is for saving 20 minutes, never for replacing the gate",
and a duplicated gate is a pre-gate that looks like the gate. Whatever deg_gate checks, this
checks, because it IS deg_gate.

    python scratchpad/12m/deg_gate_placed.py --off                      # baseline, for the deltas
    python scratchpad/12m/deg_gate_placed.py --top 8192 --run-ops 16

WHAT THE VERDICT MEANS HERE. deg_gate asserts 4 viewpoints byte-exact and prints their op counts.
Byte-exactness is the correctness proof. The op counts are EXPECTED to change -- that is the whole
point of the pass -- which is the one case where CLAUDE.md's "an op-count change with byte-exact
pixels means you changed structure" is the intended result rather than a bug to chase.
"""
import argparse
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                   # noqa: E402
from flipjump.assembler.preprocessor import TablePool                   # noqa: E402
from doomfj.harness import W                                            # noqa: E402

# The macros the profile named as owning the hot tables (FINDINGS BD): eleven of them hold 86.4%
# of every exact_xor call. Matched by NAME, because an exact label path embeds src/fj line numbers
# and goes stale silently the moment those files are edited.
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--off", action="store_true", help="run the gate unmodified (the baseline)")
    ap.add_argument("--top", type=int, default=8192)
    ap.add_argument("--run-ops", type=int, default=16)
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=1 << 27)
    a = ap.parse_args()

    pool = None
    if not a.off:
        pool = TablePool(W, a.pool_base, run_ops=a.run_ops, capacity=a.top,
                         span_bits=a.span_bits,
                         wants=lambda macro_name, prefix: any(o in prefix for o in HOT_OWNERS))
        real_assemble = fj.assemble

        def assemble_with_pool(*args, **kwargs):
            kwargs["table_pool"] = pool
            return real_assemble(*args, **kwargs)

        fj.assemble = assemble_with_pool
        print("PLACEMENT ON: base %s, span %s, run_ops %d, cap %s"
              % (hex(a.pool_base), hex(a.span_bits), a.run_ops, format(a.top, ",")), flush=True)
    else:
        print("PLACEMENT OFF (baseline)", flush=True)

    try:
        runpy.run_path(str(ROOT / "scratchpad" / "deg_gate.py"), run_name="__main__")
    except SystemExit as exit_code:
        status = exit_code.code or 0
    else:
        status = 0
    if pool is not None:
        print("relocated: %s tables into %s runs; declined %s"
              % (format(pool.allocated, ","), format(len(pool.run_starts), ","),
                 format(pool.declined, ",")), flush=True)
        if pool.allocated == 0:
            print("*** NOTHING RELOCATED -- the owner names matched no call site", flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
