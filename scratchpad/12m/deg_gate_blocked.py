"""Run the REAL `scratchpad/deg_gate.py` with BLOCKING on -- 4 viewpoints, byte-exact or not.

FINDINGS BG: blocking is correct on four toy programs with eight controls, and the shipped game
built from it presents 0 frames in 124 ops. Every cause found so far lived in something the toys do
not contain, so the next probe has to be a REAL program -- but the game tier costs ~1,780s a cycle
and tells you only "0 frames".

The visual tier costs less and says much more: deg_gate asserts four viewpoints BYTE-EXACT against
the oracle and prints their op counts. If blocking passes here, the renderer is fine and the fault
is in game-only code -- the menu, the keyboard, the simulation or the M1 self-reset. If it fails,
the failure is in the renderer and comes with pixel counts instead of a dead binary.

    python scratchpad/12m/deg_gate_blocked.py                 # blocking on
    python scratchpad/12m/deg_gate_blocked.py --selftest      # the R9 control: seconds, no build
    python scratchpad/12m/deg_gate_blocked.py --selftest-gate # the R9 control that costs a build

Not a copy of the gate: it hands deg_gate's own `run()` a pool factory (`run(table_pool=...)`, flipjump's
`assemble(table_pool=)`), so whatever deg_gate checks, this checks. Nothing is patched (flipjump 1.6.0's API):
`--no-pin`, which swapped the assembler's pin resolver, went with the patch. The exit status and both --selftest arms
live in `deg_gate_driver.py`; the checks below `_driver_controls` are this driver's own. The cheap arm does NOT cover
the E1M1 program: it runs a 10-line pointer fixture, which like deg_gate's own visual tier has no self-reset, so the
control shows the factory taking its no-self-reset branch -- and a second control hands it a program that does
declare the arrays, where it names their cells instead.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import deg_gate_driver as driver                                        # noqa: E402
from flipjump.assembler.inner_classes.table_pool import BlockPool                     # noqa: E402
from doomfj.config import Config                                        # noqa: E402
from doomfj.harness import W                                            # noqa: E402
from doomfj.selfreset import BYTE_ARRAY_NAMES, check_pin_all_but, declared_names, pin_all_but_cells   # noqa: E402

DRIVER = "deg_gate_blocked"


def make_pool_factory(a):
    """-> (the pool factory deg_gate's run() takes, the list every pool it builds is appended to, the cell lists).

    One factory, because --selftest hands the SAME factory to a stub gate that assembles through it -- so the control
    drives this body, not a copy of it.

    THE CELLS LEFT UNPINNED. On the GAME tier they are the M1 reset's BYTE cells -- `m1.zerobyte` jumps THROUGH one, so
    a pinned base sends it elsewhere -- named exactly as the shipped build names them (selfreset.pin_all_but_cells,
    over their reachable cells). deg_gate builds the VISUAL tier, which has no self-reset and therefore none of those
    arrays, while the renderer still reads cells through `hex.pointers` (every `hex.read_byte` expands the raw
    reader). So there no cell is named (`pin_all_but=[]`: every word may be pinned), and this driver says so. What
    stands in its place is the driver's own output: four viewpoints compared BYTE-EXACT against the oracle, which is
    the check a named set would only be approximating. That argument holds HERE and nowhere else -- a shipped build
    gets no such comparison, which is why it names its byte AND pointer cells.
    """
    pools, cell_lists = [], []

    def table_pool(files):
        declared = declared_names(files, BYTE_ARRAY_NAMES)
        cells = pin_all_but_cells(declared, Config().VIEW_W, a.subsectors, pointer_cells=False)
        if cells:
            print("  pin_all_but: the byte cells %s" % cells, flush=True)
        else:
            print("  pin_all_but: no self-reset in this program (no %s), so no cell to name -- "
                  "the gate's four byte-exact viewpoints are the check" % ", ".join(BYTE_ARRAY_NAMES), flush=True)
        pool = BlockPool(W, a.pool_base, pool_end=None if a.span_bits is None else a.pool_base + a.span_bits,
                         pin_all_but=cells)          # one pass: sized from its own expansion
        pools.append(pool)
        cell_lists.append(cells)
        return pool

    return table_pool, pools, cell_lists


def run(a):
    print("BLOCKING ON: pool base %s" % hex(a.pool_base), flush=True)
    table_pool, pools, cell_lists = make_pool_factory(a)
    labels = {}
    status = driver.run_gate(table_pool, labels_out=labels)
    if not pools:
        print("*** VACUOUS: the gate never assembled through the pool factory, so no pool was ever built",
              flush=True)
        return status or 2
    # the byte cells named before the assembly agree with the labels it produced (byte_arrays' geometry check)
    check_pin_all_but(cell_lists[-1], labels, Config().VIEW_W, a.subsectors)
    last = pools[-1]
    print("blocked: %s tables in %s groups; declined %s; ungrouped %s; pin conflicts %s; %s words pinned"
          % (format(last.allocated, ","), format(len(last.groups), ","),
             format(last.declined, ","), format(last.ungrouped, ","),
             format(last.report.pin_conflicts, ","), format(len(last.report.pinned), ",")), flush=True)
    return driver.verdict(status, last)


def _driver_controls(a, check, tmp, src):
    """The R9 checks only THIS driver can make: the shared arm's fixture is nobody's program, and
    the fresh pool per assembly and the cell list are this driver's machinery."""
    from pathlib import Path as _P
    import flipjump as fj

    def call(factory, name):
        """the factory, used the way deg_gate uses it; the deepest cause comes back if it raises"""
        try:
            fj.assemble([src], tmp / (name + ".fjm"), memory_width=W, show_progress=False,
                        table_pool=factory([src]))
            return "assembled"
        except BaseException as e:
            cause, depth = e, 0
            while (cause.__cause__ or cause.__context__) is not None and depth < 6:
                cause, depth = (cause.__cause__ or cause.__context__), depth + 1
            return "%s: %s" % (type(cause).__name__, cause)

    fresh, pools, _cells = make_pool_factory(a)
    causes, text = driver.capture(lambda: [call(fresh, "blk1"), call(fresh, "blk2")])
    check(len(pools) == 2 and pools[0] is not pools[1],
          "two assembles, two (one-pass) pools: a pool lays out one assembly",
          "%d pools" % len(pools))
    check(all(c == "assembled" for c in causes) and text.count("no self-reset in this program") == 2,
          "the factory names no cell without a self-reset",
          "%s; %d pin_all_but lines" % (causes[0], text.count("pin_all_but:")))

    # ... and the OTHER branch, which is the one a game-tier program takes: a program that declares the reset's byte
    # arrays gets their reachable cells named. Driven through the real factory, on declarations written here.
    nss, view_w = 3, Config().VIEW_W
    state = _P(tmp) / "state.fj"
    state.write_text("sshead: hex.vec %d\npclm: hex.vec %d\nsfflag: hex.vec %d\n" % (2 * nss, view_w, view_w),
                     encoding="utf-8")
    import argparse as _ap
    factory, built, lists = make_pool_factory(_ap.Namespace(**dict(vars(a), subsectors=nss)))
    _pool, why = driver.capture(lambda: factory([state]))
    check(lists == [[("sshead", nss), ("pclm", view_w), ("sfflag", view_w)]] and "the byte cells" in why,
          "... and it NAMES the byte cells when the program HAS a self-reset",
          (why.strip().splitlines() or ["(silent)"])[-1][:70])
    check(built[-1].pin_all_but == tuple(lists[-1]), "... and the pool it builds leaves exactly those unpinned",
          "pin_all_but=%r" % (built[-1].pin_all_but,))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--subsectors", type=int, default=682,
                    help="E1M1's subsector count, for the byte-array cells (as the shipped build derives it)")
    ap.add_argument("--selftest", action="store_true",
                    help="R9 negative control, seconds and NO build: mutate the pool's raw-cell list on a 10-line fj "
                         "program that reads a cell through hex.pointers, and this driver's own plumbing, and "
                         "require each mutation to break something. It controls the DEFAULT configuration, so "
                         "the tuning flags above are not applied to it (and it says which it "
                         "dropped). See deg_gate_driver.py for what it misses.")
    ap.add_argument("--selftest-gate", action="store_true",
                    help="R9 negative control that COSTS A BUILD (one E1M1 assemble, four runs): "
                         "the real gate under the real pool, against an oracle corrupted by one "
                         "byte -- all four viewpoints must report px DIFFER. Rule 1 applies.")
    a = ap.parse_args()

    if a.selftest:
        # the DEFAULTS, never `a`: the control's subject is this driver's default configuration, so
        # its verdict cannot depend on what else is on the command line (driver.control_args).
        ctl = driver.control_args(ap, a)
        table_pool, pools, _cells = make_pool_factory(ctl)
        return driver.cheap_selftest(
            DRIVER, table_pool, body_ran=lambda: len(pools),
            extra=lambda check, tmp, src: _driver_controls(ctl, check, tmp, src))
    if a.selftest_gate:
        return driver.gate_selftest(DRIVER, lambda: run(a))
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
