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
    python scratchpad/12m/deg_gate_blocked.py --selftest      # the R9 control: 2.1s, no build
    python scratchpad/12m/deg_gate_blocked.py --selftest-gate # the R9 control that costs a build

`--no-pin` is the bisect that matters: BlockPool does two separable things -- it MOVES tables into
per-source-word blocks, and it PINS those words so the arm flips an index. Placement (FINDINGS BE)
already showed moving tables is safe. If --no-pin passes and the default fails, the fault is in
pinning, which is a much smaller thing to search.

Not a copy of the gate -- it patches `flipjump.assemble` and executes deg_gate itself, so whatever
deg_gate checks, this checks. The patch, the exit status and both --selftest arms live in
`deg_gate_driver.py`, shared with deg_gate_placed.py so the two cannot drift; the checks below
`_driver_controls` are this driver's own. The cheap arm does NOT cover the E1M1 program: it runs a
10-line pointer fixture, which like deg_gate's own visual tier has no self-reset, so the control
shows the assembler CALLING `_byte_cell_exclusion` and the exclusion taking its no-self-reset
branch -- and a second control hands it a label table that does carry the arrays, where it names
their cells instead.
"""
import argparse
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import deg_gate_driver as driver                                        # noqa: E402
import flipjump as fj                                                   # noqa: E402
from flipjump.assembler.preprocessor import BlockPool                   # noqa: E402
from doomfj.config import Config                                        # noqa: E402
from doomfj.harness import W                                            # noqa: E402
from doomfj.selfreset import BYTE_ARRAY_NAMES, byte_arrays              # noqa: E402

DRIVER = "deg_gate_blocked"


def make_assemble(a):
    """-> (the `flipjump.assemble` replacement, the list every pool it builds is appended to).

    One factory, because --selftest installs the SAME closure the gate runs under and one of its
    stub gates CALLS fj.assemble through it -- so the control drives this body, not a copy of it.
    On the fixture, not on E1M1: see the cheap arm's closing note.
    """
    _wants = None
    if a.macros:
        allow = frozenset(a.macros)
        _wants = lambda macro_name, prefix: macro_name.name in allow      # noqa: E731
        print("  macros allowed: %s" % ", ".join(sorted(allow)), flush=True)
    elif a.owners:
        names = tuple(a.owners)
        _wants = lambda macro_name, prefix: any(o in prefix for o in names)   # noqa: E731
        print("  restricted to: %s" % ", ".join(names), flush=True)

    frozen = {}
    pools = []
    real_assemble = fj.assemble
    excluded = {"words": None}

    def _byte_cell_exclusion(address, labels):
        """The words a pointer can reach, which the assembler is then free to pin around.

        On the GAME tier they are the M1 reset's BYTE cells -- `m1.zerobyte` jumps THROUGH one, so a
        pinned base sends it elsewhere -- derived from the label table exactly as
        `build_blocked.py --pin-state-cells` derives them.

        deg_gate builds the VISUAL tier, which has no self-reset and therefore none of those arrays,
        while the renderer still reads cells through `hex.pointers` (every `hex.read_byte` expands
        the raw reader), which is what makes 1.5.1 ask for this callable at all. So here there is no
        cell set to name, and this driver says so and names none. What stands in its place is the
        driver's own output: four viewpoints compared BYTE-EXACT against the oracle, which is the
        check a named set would only be approximating. That argument holds HERE and nowhere else --
        a shipped build gets no such comparison, which is why build_blocked.py names its cells.
        (The first version of this borrowed the game-tier set outright and asserted on `sshead`,
        63 minutes into a gate run.)
        """
        if excluded["words"] is None:
            bits = {k: int(v) for k, v in labels.items()}
            absent = sorted(n for n in BYTE_ARRAY_NAMES if n not in bits)
            if absent:
                excluded["words"] = set()
                print("  pin-exclude: no self-reset in this program (no %s), so no cell to name -- "
                      "the gate's four byte-exact viewpoints are the check" % ", ".join(absent),
                      flush=True)
            else:
                words_sorted = sorted(v // W for v in bits.values())
                out = set()
                for name, n in byte_arrays(bits, words_sorted, Config().VIEW_W, a.subsectors):
                    base = bits[name] // W
                    out.update(base + 2 * k + half for k in range(n) for half in (0, 1))
                excluded["words"] = out
                print("  pin-exclude: %s byte-cell words" % format(len(out), ","), flush=True)
        return (address // W) in excluded["words"]

    def assemble_blocked(*args, **kwargs):
        if not frozen:
            with tempfile.TemporaryDirectory() as td:
                counting = BlockPool(W, a.pool_base, span_bits=a.span_bits, wants=_wants)
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
                         span_bits=a.span_bits, wants=_wants)
        # A pinned word cannot be read raw, and the assembler (flipjump 1.5.1, tomhea/flipjump#360)
        # refuses to pin a program that reads through hex.pointers unless the caller names the
        # cells a pointer can reach. Here those are the byte arrays (`hex.read_byte` walks them),
        # the same exclusion build_blocked.py's --pin-state-cells uses; LUT cells are never armed.
        pool.pin_exclude = _byte_cell_exclusion
        pools.append(pool)
        kwargs["table_pool"] = pool
        return real_assemble(*args, **kwargs)

    # "restricted" is decided HERE, where the narrowing is decided, so run() cannot disagree with
    # it: --macros/--owners is an experiment that may legitimately match nothing, and driver.verdict
    # warns instead of failing for one (a `bool(a.macros or a.owners)` in run() would be a second
    # definition of the same condition, free to drift from this one).
    assemble_blocked._restricted = _wants is not None
    assemble_blocked._pin_exclude = _byte_cell_exclusion    # the controls drive the REAL one
    return assemble_blocked, pools


def run(a):
    print("BLOCKING ON: pool base %s, pinning %s"
          % (hex(a.pool_base), "OFF (relocation only)" if a.no_pin else "on"), flush=True)
    assemble_blocked, pools = make_assemble(a)
    status = driver.run_gate(assemble_blocked, no_pin=a.no_pin)
    if not pools:
        print("*** VACUOUS: the gate never called fj.assemble, so no pool was ever built",
              flush=True)
        return status or 2
    last = pools[-1]
    print("blocked: %s tables in %s groups; declined %s; ungrouped %s; pin conflicts %s"
          % (format(last.allocated, ","), format(len(last.groups), ","),
             format(last.declined, ","), format(last.ungrouped, ","),
             format(getattr(last, "pin_conflicts", 0), ",")), flush=True)
    return driver.verdict(status, last, no_pin=a.no_pin,
                          restricted=assemble_blocked._restricted)


def _reset_like_labels(nss, view_w):
    """A label table shaped like a SELF-RESETTING program's, and the byte-cell words in it.

    `byte_arrays` derives each array's reachable cells from the gap to the next label and refuses a
    table whose geometry disagrees with (nss, view_w) -- so this lays the three arrays out with
    exactly the declared cells it demands (sshead is over-allocated 2x, the per-column arrays 1:1)
    and a sentinel label closing the last one. Building it here rather than mocking `byte_arrays`
    keeps the control on the real derivation.
    """
    # (declared words, REACHABLE words): sshead declares 2 cells per reachable one, so its top half
    # is over-allocation the exclusion does not name -- which is the part of the derivation worth
    # controlling, and the reason this returns the two counts separately.
    sizes = [("sshead", 4 * nss, 2 * nss), ("pclm", 2 * view_w, 2 * view_w),
             ("sfflag", 2 * view_w, 2 * view_w)]
    bits, cells, word = {}, [], 1 << 12
    for name, declared, reachable in sizes:
        bits[name] = word * W
        cells.extend(range(word, word + reachable))
        word += declared
    bits["_end_of_the_byte_arrays"] = word * W
    return bits, cells


def _driver_controls(a, check, tmp, src):
    """The R9 checks only THIS driver can make: the shared arm's fixture is nobody's program, and
    the frozen counting pass, the pin exclusion and --macros/--owners are machinery
    deg_gate_placed.py does not have at all."""

    class _Macro:                       # `wants` reads .name; a MacroName is not constructible here
        def __init__(self, name):
            self.name = name

    def call(fn, name):
        """The closure, called the way deg_gate calls it. It may well RAISE -- the fixture is not
        the program the exclusion is written for -- so the deepest cause comes back instead."""
        try:
            fn([src], tmp / (name + ".fjm"), memory_width=W, print_time=False)
            return "assembled"
        except BaseException as e:
            cause, depth = e, 0
            while (cause.__cause__ or cause.__context__) is not None and depth < 6:
                cause, depth = (cause.__cause__ or cause.__context__), depth + 1
            return "%s: %s" % (type(cause).__name__, cause)

    fresh, pools = make_assemble(a)
    causes, text = driver.capture(lambda: [call(fresh, "blk1"), call(fresh, "blk2")])
    check(text.count("counting pass:") == 1 and len(pools) == 2,
          "two assembles, ONE counting pass: the counts are frozen",
          "%d counting-pass lines, %d pools" % (text.count("counting pass:"), len(pools)))
    check(all(c == "assembled" for c in causes) and text.count("pin-exclude: no self-reset") == 1,
          "the assembler CALLS this driver's pin exclusion, which names no cell without a self-reset",
          "%s; %d pin-exclude lines" % (causes[0], text.count("pin-exclude:")))

    # ... and the OTHER branch, which is the one a game-tier program takes: hand the exclusion a
    # label table that does carry the reset's byte arrays and it must name their cells instead of
    # excusing itself. Driven through the real closure's own exclusion, not a copy of it.
    nss, view_w = 3, Config().VIEW_W
    labels, cells = _reset_like_labels(nss, view_w)
    excl = make_assemble(argparse.Namespace(**dict(vars(a), subsectors=nss)))[0]._pin_exclude
    named, why = driver.capture(lambda: [excl(w * W, labels) for w in cells])
    check(all(named) and ("pin-exclude: %s byte-cell words" % format(len(cells), ",")) in why,
          "... and it NAMES the byte cells when the program HAS a self-reset",
          (why.strip().splitlines() or ["(silent)"])[-1][:70])
    outside, _ = driver.capture(lambda: excl((max(cells) + 4) * W, labels))
    check(not outside, "... and a word outside them is still pinnable", "excluded=%s" % outside)

    narrowed, _ = driver.capture(
        lambda: (make_assemble(argparse.Namespace(**dict(vars(a), macros=["hex.xor"]))),
                 make_assemble(argparse.Namespace(**dict(vars(a), macros=None,
                                                         owners=["hex.tables"])))))
    (by_macro, macro_pools), (by_owner, owner_pools) = narrowed
    driver.capture(lambda: (call(by_macro, "blk3"), call(by_owner, "blk4")))
    m, o = macro_pools[-1], owner_pools[-1]
    check(m.wants(_Macro("hex.xor"), "") and not m.wants(_Macro("hex.add"), ""),
          "--macros is what its pool relocates by NAME",
          "hex.xor %s, hex.add %s" % (m.wants(_Macro("hex.xor"), ""),
                                      m.wants(_Macro("hex.add"), "")))
    check(o.wants(_Macro("x"), "a.hex.tables.b") and not o.wants(_Macro("x"), "a.stl.loop.b"),
          "--owners is what its pool relocates by CALL SITE",
          "hex.tables %s, stl.loop %s" % (o.wants(_Macro("x"), "a.hex.tables.b"),
                                          o.wants(_Macro("x"), "a.stl.loop.b")))
    check(fresh._restricted is False and by_macro._restricted is True
          and by_owner._restricted is True,
          "... and either of them is what makes a run RESTRICTED for verdict",
          "plain %s, --macros %s, --owners %s" % (fresh._restricted, by_macro._restricted,
                                                  by_owner._restricted))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool-base", type=lambda s: int(s, 0), default=1 << 31)
    ap.add_argument("--span-bits", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--macros", nargs="*", default=None,
                    help="only block tables emitted by these MACROS. This is the declaration the "
                         "assembler cannot infer: FINDINGS BG showed 'a maximal run of a;b ops "
                         "after a pad' is unsound -- hex.pointers.xor_hex_to_flip_ptr's pad-4 block "
                         "is selected by ADDRESS-BIT FLIPS and contains a wflip, so the rule splits "
                         "it. Naming the macros whose tables are verified jump-only replaces the "
                         "guess with an opt-in. A run narrowed this way that matches nothing WARNS "
                         "rather than failing: an empty match is this experiment's answer.")
    ap.add_argument("--owners", nargs="*", default=None,
                    help="only block tables under these macro names. The PLACEMENT run that passes "
                         "this gate was restricted to six hot owners; BlockPool relocates "
                         "EVERYTHING, including hex.tables.*, hex.pointers.* and stl internals. "
                         "Restricting it the same way tests whether the unsafe tables are outside "
                         "them -- so, as with --macros, matching nothing is an answer and warns.")
    ap.add_argument("--subsectors", type=int, default=682,
                    help="E1M1's subsector count, for the byte-array exclusion (as build_blocked.py)")
    ap.add_argument("--no-pin", action="store_true",
                    help="relocate into blocks but do NOT pin the source words")
    ap.add_argument("--selftest", action="store_true",
                    help="R9 negative control, 2.1s measured and NO build: mutate the assembler's "
                         "pin exclusion on a 10-line fj program that reads a cell through "
                         "hex.pointers, and this driver's own plumbing, and require each "
                         "mutation to break something. It controls the DEFAULT configuration, so "
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
        assemble_blocked, pools = make_assemble(ctl)
        return driver.cheap_selftest(
            DRIVER, assemble_blocked, body_ran=lambda: len(pools),
            extra=lambda check, tmp, src: _driver_controls(ctl, check, tmp, src))
    if a.selftest_gate:
        return driver.gate_selftest(DRIVER, lambda: run(a))
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
