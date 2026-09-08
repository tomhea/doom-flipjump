"""Run the REAL `scratchpad/deg_gate.py` with BLOCKING on -- 4 viewpoints, byte-exact or not.

FINDINGS BG: blocking is correct on four toy programs with eight controls, and the shipped game
built from it presents 0 frames in 124 ops. Every cause found so far lived in something the toys do
not contain, so the next probe has to be a REAL program -- but the game tier costs ~1,780s a cycle
and tells you only "0 frames".

The visual tier costs less and says much more: deg_gate asserts four viewpoints BYTE-EXACT against
the oracle and prints their op counts. If blocking passes here, the renderer is fine and the fault
is in game-only code -- the menu, the keyboard, the simulation or the M1 self-reset. If it fails,
the failure is in the renderer and comes with pixel counts instead of a dead binary.

    python scratchpad/12m/deg_gate_blocked.py            # blocking on
    python scratchpad/12m/deg_gate_blocked.py --no-pin   # relocation only, pinning suppressed

`--no-pin` is the bisect that matters: BlockPool does two separable things -- it MOVES tables into
per-source-word blocks, and it PINS those words so the arm flips an index. Placement (FINDINGS BE)
already showed moving tables is safe. If --no-pin passes and the default fails, the fault is in
pinning, which is a much smaller thing to search.

Not a copy of the gate -- it patches `flipjump.assemble` and executes deg_gate itself, so whatever
deg_gate checks, this checks.
"""
import argparse
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                   # noqa: E402
from flipjump.assembler import assembler as asmmod                      # noqa: E402
from flipjump.assembler.preprocessor import BlockPool                   # noqa: E402
from doomfj.harness import W                                            # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--no-pin", action="store_true",
                    help="relocate into blocks but do NOT pin the source words")
    a = ap.parse_args()

    print("BLOCKING ON: pool base %s, pinning %s"
          % (hex(a.pool_base), "OFF (relocation only)" if a.no_pin else "on"), flush=True)

    frozen = {}
    pools = []
    real_assemble = fj.assemble

    def assemble_blocked(*args, **kwargs):
        if not frozen:
            with tempfile.TemporaryDirectory() as td:
                counting = BlockPool(W, a.pool_base, span_bits=a.span_bits)
                probe = dict(kwargs)
                probe["table_pool"] = counting
                out_arg = list(args)
                if len(out_arg) > 1:
                    out_arg[1] = Path(td) / "count.fjm"
                else:
                    probe["output_fjm_path"] = Path(td) / "count.fjm"
                real_assemble(*out_arg, **probe)
                frozen["counts"] = counting.counts
                frozen["widths"] = counting.widths
                print("  counting pass: %s groups, %s tables"
                      % (format(len(counting.counts), ","),
                         format(sum(counting.counts.values()), ",")), flush=True)
        pool = BlockPool(W, a.pool_base, counts=frozen["counts"], widths=frozen["widths"],
                         span_bits=a.span_bits)
        pools.append(pool)
        kwargs["table_pool"] = pool
        return real_assemble(*args, **kwargs)

    fj.assemble = assemble_blocked
    real_resolve = asmmod.resolve_pinned
    if a.no_pin:
        asmmod.resolve_pinned = lambda exprs, labels, reserved_below=1024: ({}, 0)
    try:
        runpy.run_path(str(ROOT / "scratchpad" / "deg_gate.py"), run_name="__main__")
    except SystemExit as exit_code:
        status = exit_code.code or 0
    else:
        status = 0
    finally:
        fj.assemble = real_assemble
        asmmod.resolve_pinned = real_resolve

    if pools:
        last = pools[-1]
        print("blocked: %s tables in %s groups; declined %s; ungrouped %s; pin conflicts %s"
              % (format(last.allocated, ","), format(len(last.groups), ","),
                 format(last.declined, ","), format(last.ungrouped, ","),
                 format(getattr(last, "pin_conflicts", 0), ",")), flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
