"""Shared machinery for the two deg_gate wrappers -- and the negative controls (R9) their verdicts
need before anyone cites them.

`deg_gate_blocked.py` and `deg_gate_placed.py` are not copies of the gate: each installs a table
pool into `flipjump.assemble` and then EXECUTES `scratchpad/deg_gate.py`, so whatever the gate
checks, the driver checks. That claim rests entirely on the patch-and-restore below, which is why
it lives here ONCE instead of twice -- the two drivers cannot drift apart on the part that makes
their verdict mean anything. 35b2fbb ("4/4 byte-exact") and e79d15f cite these drivers; neither
driver had, until now, a control showing it can still say FAIL.

    python scratchpad/12m/deg_gate_blocked.py --selftest        # CHEAP: 2.1s, no E1M1 build
    python scratchpad/12m/deg_gate_blocked.py --selftest-gate   # EXPENSIVE: one E1M1 assemble

WHAT THE CHEAP ARM CONTROLS -- and what it only BORROWS. Its fixture half (the first five checks)
is a port of flipjump-151's own unit test, `tests/unit/test_table_pool.py`
::test_a_pinned_word_read_through_a_pointer_needs_the_callers_exclusion: same POINTER_PROGRAM, same
inline / relocated / counting / refused / excluded sequence, same assertions, credited line by line
below. Those control the ASSEMBLER's pin machinery, not this file; they are here so the checks that
follow stand on a fixture known to still read a cell raw.

What this file's OWN checks control is the plumbing, and each is defeated by a mutation:
`run_gate` installs the driver's closure, and a gate that calls `fj.assemble` reaches its BODY; a
gate's FAIL survives; the stock assembler and the real `resolve_pinned` come back; `--no-pin`
suppresses a pin the real resolver would have granted; `verdict` refuses a vacuous run and only
WARNS for an explicitly restricted one; and each of `--selftest-gate`'s four checks MISSes ALONE on
one of seven stub gates -- every shape carries the NUMBER of checks it must defeat (0, 1, 1, 1, 1,
2, 4), because the shapes are not all single-check and the table is what says which is which. Each
driver adds checks on the pool IT builds (`cheap_selftest(extra=...)`), because this fixture is
neither driver's program. The cheap arm is run on the driver's DEFAULT configuration whatever else
is on the command line (`control_args`): a control whose verdict moves with a tuning flag is a
control that can say NO for a reason of its own making.

WHAT NEITHER CHEAP ARM COVERS: the E1M1 program. The fixture has no byte arrays, so
`_byte_cell_exclusion` cannot name a real cell -- blocked's own control shows the assembler CALLING
it and the call failing on the fixture's label table -- no part of the real program is assembled,
and the stub gates compare no pixels. Only the expensive arm and the gate itself touch those.
CLAUDE.md rule 3: a fast pre-gate is for saving 20 minutes, never for replacing the gate.
"""
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                   # noqa: E402
from flipjump import FixedIO                                            # noqa: E402
from flipjump.assembler import assembler as asmmod                      # noqa: E402
from flipjump.assembler.preprocessor import BlockPool, TablePool        # noqa: E402
from flipjump.utils.exceptions import FlipJumpException                 # noqa: E402
from doomfj.harness import W                                            # noqa: E402

DEG_GATE = ROOT / "scratchpad" / "deg_gate.py"


def run_gate(assemble_fn, *, no_pin=False, gate=DEG_GATE):
    """Install `assemble_fn` as `flipjump.assemble`, execute the gate, restore, return its status.

    The patch IS the wrapper: deg_gate.py itself runs, so it cannot fall behind the gate the way a
    copy would. `assemble_fn` is tagged, so a control can prove the closure the driver built -- and
    not the stock assembler -- is what the gate ran under; pass None to run the gate unpatched (the
    placement driver's --off baseline).
    """
    if assemble_fn is not None:
        assemble_fn._pooled = True
    real_assemble = fj.assemble
    real_resolve = asmmod.resolve_pinned
    if assemble_fn is not None:
        fj.assemble = assemble_fn
    if no_pin:
        # KEEP THE ASSEMBLER'S OWN SIGNATURE. `exclude=` has been passed since the pin_exclude hook
        # landed here in 9a4122c (the stub at 9a4122c^ has no such parameter), and a stub without it
        # raises TypeError instead of suppressing the pins. The parameter is the assembler's own:
        # flipjump 1.5.1, tomhea/flipjump#360, merged as dd7ad31 in the flipjump-151 checkout.
        asmmod.resolve_pinned = lambda exprs, labels, reserved_below=1024, exclude=None: ({}, 0)
    try:
        runpy.run_path(str(gate), run_name="__main__")
    except SystemExit as exit_code:
        status = exit_code.code or 0
    else:
        status = 0
    finally:
        fj.assemble = real_assemble
        asmmod.resolve_pinned = real_resolve
    return status


def verdict(status, pool, *, no_pin=False, restricted=False):
    """The driver's exit status: the gate's verdict, AND non-vacuity of the pass under test.

    A pool that relocated nothing assembled the STOCK program, so a green gate says nothing about
    blocking or placement -- and "4/4 byte-exact with blocking on" would be a false citation.
    deg_gate_placed.py used to print "*** NOTHING RELOCATED" and still exit 0; that is a FAILURE
    now. The gate's own non-zero status always wins, so this can only ever add a failure.

    `restricted` is for a run whose macro/owner names were narrowed ON PURPOSE (deg_gate_blocked's
    --macros / --owners, whose documented use is "does the fault live outside these names?"): an
    empty match is that experiment's ANSWER, so it warns loudly and keeps the gate's own status
    rather than turning a run that answered its question into exit 2.
    """
    if pool is None:                    # the --off baseline: no pass to be vacuous about
        return status
    if pool.allocated == 0:
        # STATE, not a diagnosis. A pool cannot tell afterwards WHY it holds nothing: `wants`
        # matching no call site and a capacity of 0 both reach here, and whether the gate called
        # fj.assemble at all is something only the driver's call list knows (both drivers keep one
        # and report that case themselves). `declined` is the part that IS knowable here -- 0 means
        # nothing was ever offered to `reserve`, non-zero means it was offered and refused.
        return _vacuous(status, restricted,
                        "the pool relocated NOTHING (0 allocated, %s declined) -- this run is the "
                        "stock program, whatever the gate said" % format(pool.declined, ","))
    if isinstance(pool, BlockPool) and not no_pin and not pool.pinned_words():
        return _vacuous(status, restricted,
                        "%s tables were blocked but NO word was pinned -- the arm still writes an "
                        "address, so this is placement, not blocking" % format(pool.allocated, ","))
    return status


def _vacuous(status, restricted, why):
    """The one place the vacuity message is printed, so a caller cannot print a second one."""
    if restricted:
        print("*** WARNING: %s\n    ... but this run was RESTRICTED on purpose, so an empty match "
              "is its answer, not a failure" % why, flush=True)
        return status
    print("*** VACUOUS: %s" % why, flush=True)
    return status or 2


class _Tee:
    """stdout that keeps a copy: a control has to require the words the gate PRINTS, not just the
    status it exits with -- a wrapper that runs a gate comparing nothing exits 0 quite happily.
    `mirror=False` swallows the copy instead, for the stub runs inside a control."""

    def __init__(self, mirror=True):
        self._real = sys.stdout
        self._mirror = mirror
        self._text = []
        sys.stdout = self

    def __getattr__(self, name):        # encoding / fileno / isatty, for whoever asks
        return getattr(self._real, name)

    def write(self, s):
        self._text.append(s)
        return self._real.write(s) if self._mirror else len(s)

    def flush(self):
        self._real.flush()

    def stop(self):
        sys.stdout = self._real
        return "".join(self._text)


def capture(fn):
    """-> (fn's return value, everything it printed). A control on a guard that PRINTS its reason
    has to read the reason: "exit 2" alone does not say which branch fired."""
    tee = _Tee(mirror=False)
    try:
        value = fn()
    finally:
        text = tee.stop()
    return value, text


# --- the cheap arm ---------------------------------------------------------------------------

POOL_BASE = 1 << 26     # above everything the fixture reaches, as in flipjump's own unit tests

# THE FIXTURE, verbatim from flipjump-151 tests/unit/test_table_pool.py::POINTER_PROGRAM. `hex.xor
# e, d` arms d's jump word, so BlockPool pins d; the pointer read then flips a bit of that word and
# jumps through it expecting `value*dw`, and a pinned word holds `base + value*dw` -- so it lands in
# the block instead of the pointer decoder. Prints 0xD ^ 6 = 'B'.
POINTER_SOURCE = """
stl.startup_and_init_all
    hex.set d, 6
    hex.xor e, d
    hex.set v, 0xD
    hex.xor_hex_from_ptr v, p
    hex.print_as_digit v, 1
    stl.loop
d: hex.hex
e: hex.hex
v: hex.hex
p: hex.vec w/4, d
"""
FIXTURE_OUTPUT = b"B"

_STUB_FAIL = """
import sys
import flipjump as fj
print("(stub gate) pooled assemble installed: %s" % getattr(fj.assemble, "_pooled", False))
print("(664,291,0x18000000): 1,234 ops  !! 7 px DIFFER")
print("FAIL")
sys.exit(1)
"""
_STUB_PASS = """
import sys
print("(stub gate) 4 viewpoints BYTE-EXACT")
print("PASS")
sys.exit(0)
"""
# deg_gate's one call into the assembler, on the fixture instead of on E1M1: `@SRC@` and `@OUT@` are
# substituted with real paths when the stub is written. This is the stub that makes "--selftest
# installs the same closure the gate runs under" a run rather than a sentence -- the closure is
# ENTERED here; whether the fixture then assembles is the driver's business, not the control's.
_STUB_ASSEMBLE = """
import sys
from pathlib import Path
import flipjump as fj
from doomfj.harness import W

print("(stub gate) pooled assemble installed: %s" % getattr(fj.assemble, "_pooled", False))
try:
    fj.assemble([Path(@SRC@)], Path(@OUT@), memory_width=W, print_time=False)
    print("(stub gate) fj.assemble returned")
except BaseException as e:
    cause, depth = e, 0
    while (cause.__cause__ or cause.__context__) is not None and depth < 6:
        cause, depth = (cause.__cause__ or cause.__context__), depth + 1
    print("(stub gate) fj.assemble raised %s (%s: %s)"
          % (type(e).__name__, type(cause).__name__, cause))
sys.exit(0)
"""
# ONE definition of the pin request, because the stub gate puts it to the PATCHED resolver and the
# control puts it to the real one: a control that built its own request could drift from the stub's
# and compare two different questions. 4096 is above resolve_pinned's RESERVED_BELOW (1024), so the
# real resolver pins it; 0x40 is the block base it is pinned to.
_PIN_REQUEST = """
class _Pin:
    def exact_eval(self, labels):
        return 4096


PIN_ARGS = ({_Pin(): 0x40}, {})
PIN_KW = {"exclude": lambda address, labels: False}
"""
_STUB_NO_PIN = _PIN_REQUEST + """
import sys
from flipjump.assembler import assembler as asmmod

print("(stub gate) resolve_pinned(1 pin request, exclude=...) -> %r"
      % (asmmod.resolve_pinned(*PIN_ARGS, **PIN_KW),))
sys.exit(0)
"""


def _stub_gate_run(lines, status):
    """A stand-in for a driver's whole ordinary run, printing what deg_gate prints at its
    viewpoints. The op counts are deliberately fake (1,234): a plausible one pasted here would be
    an invented occurrence of a number this repo cites for real."""

    def run_driver():
        for line in lines:
            print(line)
        print("FAIL" if status else "PASS")
        return status

    return run_driver


def build_and_run(source, tmp, name, pool, assemble=None):
    """-> (output, ops, cause). A mutant that DIES is a rejection, not an error, so a broken run
    comes back as an output that is not the fixture's rather than as an exception.

    `assemble` (a driver's own closure) is called the way deg_gate calls it, i.e. WITHOUT
    table_pool, so the closure is what chooses the pool.
    """
    out = tmp / (name + ".fjm")
    if assemble is None:
        fj.assemble([source], out, memory_width=W, print_time=False, table_pool=pool)
    else:
        assemble([source], out, memory_width=W, print_time=False)
    io = FixedIO(b"")
    try:
        stats = fj.run(out, io_device=io, print_time=False, print_termination=False)
    except FlipJumpException as e:
        return None, 0, type(e).__name__
    return io.get_output(allow_incomplete_output=True), stats.op_counter, str(stats.termination_cause)


def control_args(parser, a):
    """-> a PRISTINE namespace for --selftest, built from `parser`'s DEFAULTS rather than from `a`.

    The cheap arm is a negative control, so its subject must be the driver's default configuration:
    read the user's own namespace and the control's verdict depends on what else is on the command
    line. It did. `deg_gate_blocked.py --selftest --macros hex.xor` narrowed the very pool the
    pin-exclusion check assembles under -- the fixture then ASSEMBLED instead of reaching the
    exclusion -- and made the "plain" arm of the RESTRICTED check restricted, so the run printed two
    MISSes that were artefacts of the flag; `--span-bits 0x100` and `deg_gate_placed.py --selftest
    --top 1` printed one each. A tool whose whole job is to say whether a check has teeth may not
    have a mode in which it says NO for a reason of its own making. The tuning flags are therefore
    not applied to the control -- and it says so, rather than ignoring them quietly.
    """
    ctl = parser.parse_args([])
    ignored = sorted("--" + name.replace("_", "-") for name, default in vars(ctl).items()
                     if not name.startswith("selftest") and getattr(a, name) != default)
    if ignored:
        print("  --selftest controls the DEFAULT configuration, so %s %s not applied to it"
              % (", ".join(ignored), "is" if len(ignored) == 1 else "are"), flush=True)
    return ctl


def cheap_selftest(driver, assemble_fn, *, body_ran=None, extra=None):
    """The DEFAULT --selftest arm: mutate the assembler's pin exclusion, this file's plumbing, the
    vacuity guard and the expensive arm's accounting, and require every mutation to be rejected.

    `body_ran()` -> how many times the driver's closure has run its BODY (not merely been called),
    so the stub gate that calls `fj.assemble` can prove the closure was ENTERED. `extra(check, tmp,
    src)` contributes the driver's own checks, on the pool only it builds.
    """
    tmp = Path(tempfile.mkdtemp(prefix="deg_gate_ctl_"))
    src = tmp / "pointer.fj"
    src.write_bytes(POINTER_SOURCE.encode("ascii"))
    print("%s --selftest: the cheap arm (tiny pointer fixture, NO E1M1 build)" % driver, flush=True)
    log = []

    def check(ok, label, detail=""):
        log.append(bool(ok))
        print("  %-4s %-58s %s" % ("ok" if ok else "MISS", label, detail), flush=True)

    # --- checks 1-5: flipjump-151's own test, ported. They control the ASSEMBLER, not this driver;
    # they run here because every later check needs a fixture that still reads a cell raw, and
    # alpha_check's lesson is that a stale fixture is a FAILURE, never a quiet SKIP.
    inline, inline_ops, cause = build_and_run(src, tmp, "inline", None)
    check(inline == FIXTURE_OUTPUT, "fixture: the inline build prints %r" % FIXTURE_OUTPUT,
          "got %r in %d ops (%s)" % (inline, inline_ops, cause))

    relocated = TablePool(W, POOL_BASE)
    out, ops, cause = build_and_run(src, tmp, "relocated", relocated)
    check(out == inline and relocated.allocated > 0, "relocation alone leaves the output alone",
          "%d tables, %d -> %d ops" % (relocated.allocated, inline_ops, ops))

    counting = BlockPool(W, POOL_BASE)
    fj.assemble([src], tmp / "counting.fjm", memory_width=W, print_time=False, table_pool=counting)
    check(counting.reads_words_raw, "fixture: it still reads a cell through hex.pointers",
          "reads_words_raw=%s, %d groups" % (counting.reads_words_raw, len(counting.counts)))

    def blocked(exclude):
        pool = BlockPool(W, POOL_BASE, counts=counting.counts, widths=counting.widths)
        pool.pin_exclude = exclude
        return pool

    try:
        build_and_run(src, tmp, "unexcluded", blocked(None))
        refused = ""
    except FlipJumpException as e:
        refused = str(e)
    check("pin_exclude" in refused, "MUTANT: no exclusion at all -> the assembler refuses",
          (refused[:56] + "...") if refused else "IT ASSEMBLED ANYWAY")

    # the veto sees the bit address of the cell's JUMP word, `d + w`
    pool = blocked(lambda address, labels: address == labels["d"] + W)
    out, ops, cause = build_and_run(src, tmp, "blocked", pool)
    check(out == inline and pool.pinned_words(),
          "blocking with the pointed-to cell excluded: the same program",
          "%d pinned words, %d tables, %d ops" % (len(pool.pinned_words()), pool.allocated, ops))

    # --- and one mutation of the fixture flipjump's test does not make: an exclusion that names the
    # WRONG cells, which is the failure mode `_byte_cell_exclusion` can actually have.
    try:
        out, ops, cause = build_and_run(src, tmp, "unprotected",
                                        blocked(lambda address, labels: False))
    except FlipJumpException as e:
        out, cause = None, type(e).__name__
    check(out != inline, "MUTANT: an exclusion omitting the pointed-to cell -> not that program",
          "output %r (%s)" % (out, cause))

    # --- verdict: every branch of it, the BlockPool half included
    inert = TablePool(W, POOL_BASE, wants=lambda macro_name, prefix: False)
    build_and_run(src, tmp, "inert", inert)
    status, text = capture(lambda: verdict(0, inert))
    check(status != 0 and "VACUOUS" in text, "MUTANT: a pool that relocated nothing is not a PASS",
          "allocated=%d, exit %r" % (inert.allocated, status))
    status, text = capture(lambda: verdict(0, inert, restricted=True))
    check(status == 0 and "WARNING" in text, "... but a run RESTRICTED on purpose only warns",
          "exit %r, %r" % (status, text[4:36]))
    check(verdict(0, relocated) == 0, "... while a pool that did relocate still passes",
          "allocated=%d" % relocated.allocated)
    check(verdict(1, relocated) != 0, "... and the gate's own FAIL is never overridden by it")
    check(verdict(0, None) == 0, "... and --off, which has no pool at all, is not vacuous")

    check(verdict(0, pool) == 0, "a BlockPool that pinned words is not vacuous either",
          "%d pinned, %d tables" % (len(pool.pinned_words()), pool.allocated))
    # the assembler's OWN "this group failed to place" state, applied to every group: pin_broken is
    # False by default, so a broken group is dropped from pinned_words() while its tables stay
    # allocated, and the arm writes a full address again. That is placement wearing blocking's name.
    pool.broken_groups = set(pool.groups)
    status, text = capture(lambda: verdict(0, pool))
    check(status != 0 and "placement, not blocking" in text,
          "MUTANT: blocked tables but NO pinned word is not a PASS",
          "%d pinned, %d tables, exit %r" % (len(pool.pinned_words()), pool.allocated, status))
    check(verdict(0, pool, no_pin=True) == 0, "... unless --no-pin asked for exactly that")

    # --- run_gate: the patch, the restore, and the closure's body
    stubs = {}
    for name, body in (("fail", _STUB_FAIL), ("pass", _STUB_PASS), ("nopin", _STUB_NO_PIN),
                       ("assemble", _STUB_ASSEMBLE.replace("@SRC@", repr(str(src)))
                                                  .replace("@OUT@", repr(str(tmp / "stub.fjm"))))):
        stubs[name] = tmp / ("stub_%s.py" % name)
        stubs[name].write_bytes(body.encode("ascii"))

    status, text = capture(lambda: run_gate(assemble_fn, gate=stubs["fail"]))
    check(status == 1, "MUTANT: a gate that FAILs comes back as a non-zero driver status",
          "status=%r" % (status,))
    check("installed: True" in text, "... and the gate ran under the DRIVER'S closure",
          text.strip().splitlines()[0] if text.strip() else "(the stub printed nothing)")
    check(fj.assemble is not assemble_fn, "... and the stock assembler is back afterwards")
    check(run_gate(assemble_fn, gate=stubs["pass"]) == 0, "a gate that passes comes back as 0")

    before = None if body_ran is None else body_ran()
    status, text = capture(lambda: run_gate(assemble_fn, gate=stubs["assemble"]))
    said = [ln for ln in text.splitlines() if "fj.assemble" in ln]
    # "installed: True" is what makes this the DRIVER'S closure rather than the stock assembler: a
    # run_gate that installs NOTHING runs this stub perfectly happily and it prints the very same
    # "fj.assemble raised ..." words out of the stock assembler, so a status and a line mentioning
    # fj.assemble cannot tell the two apart -- which is what this check is named for.
    check(status == 0 and bool(said) and "installed: True" in text,
          "a gate that CALLS fj.assemble reaches the driver's closure",
          "installed: %s; %s" % ("installed: True" in text,
                                 said[-1][:44] if said else "the stub never got there"))
    if body_ran is not None:
        check(body_ran() > before, "... and the closure's BODY ran -- the pool this driver builds",
              "%r -> %r body runs" % (before, body_ran()))

    # --- --no-pin: the stub must accept the assembler's call AND actually suppress the pin. The
    # real resolver answers ({}, 0) to an EMPTY request too, so a control that asked it nothing
    # passes with the stub uninstalled -- which is exactly what this check did until this round.
    namespace = {}
    exec(_PIN_REQUEST, namespace)       # the same text the stub gate runs, so neither can drift

    def no_pin_run():
        """A stub whose signature does not match the assembler's call raises straight out of
        run_gate -- and a control that DIES reports nothing: a traceback and 0 MISS, a rejection in
        the exit-status sense only. Catching it here is what lets the mismatch this check is named
        for (a stub without `exclude=`, the 9a4122c^ regression) print MISS like any other."""
        try:
            return run_gate(assemble_fn, no_pin=True, gate=stubs["nopin"]), ""
        except BaseException as e:
            return None, "%s: %s" % (type(e).__name__, e)

    (status, blew_up), text = capture(no_pin_run)
    real_pin = asmmod.resolve_pinned(*namespace["PIN_ARGS"], **namespace["PIN_KW"])
    check(status == 0 and not blew_up,
          "the --no-pin stub takes the assembler's call, signature and all",
          blew_up[:70] or (text.strip().splitlines()[-1][:70] if text.strip()
                           else "(the stub printed nothing)"))
    check("-> ({}, 0)" in text and bool(real_pin[0]),
          "... and SUPPRESSES a pin the real resolver grants", "real resolver: %r" % (real_pin,))
    check(asmmod.resolve_pinned.__name__ == "resolve_pinned", "... and the real pin resolver is back")

    # --- the EXPENSIVE arm's accounting, driven over stub gates so --selftest-gate's verdict is not
    # the one claim in this file that nothing controls. No build: the stubs print what deg_gate
    # prints, and every shape below carries the number of that arm's four checks it must defeat.
    # The middle four defeat ONE EACH -- one per check, so deleting any single check turns that
    # shape's required 1 into a 0 -- and the last two defeat several at once and are required to
    # MISS exactly as many. No shape "defeats exactly one check" as a general rule: the table says
    # which, and the run prints the count next to each.
    from doomfj.reference_model import ReferenceModel
    real_render = ReferenceModel.render_wall_frame
    ok_lines = ["(stub viewpoint %d): 1,234 ops  !! 1 px DIFFER" % vp for vp in range(4)]
    shapes = (
        ("--selftest-gate accepts 4x '!! 1 px DIFFER', exit 1", ok_lines, 1, 0),
        # one per check: status, the count of differing viewpoints, their SIZE, and BYTE-EXACT
        ("MUTANT: ... and rejects a run whose FAIL was swallowed (exit 0)", ok_lines, 0, 1),
        ("MUTANT: ... and rejects a FIFTH differing viewpoint",
         ok_lines + ["(stub viewpoint 4): 1,234 ops  !! 2 px DIFFER"], 1, 1),
        ("MUTANT: ... and rejects a FAIL of the WRONG SIZE (4x 7 px)",
         [ln.replace("1 px", "7 px") for ln in ok_lines], 1, 1),
        ("MUTANT: ... and rejects a run that says BYTE-EXACT as well",
         ok_lines + ["(stub viewpoint 4): 1,234 ops  BYTE-EXACT"], 1, 1),
        # and two that defeat several, which is why the required count is per shape, not "one"
        ("MUTANT: ... and rejects a run with a viewpoint never compared", ok_lines[:3], 1, 2),
        ("MUTANT: ... and rejects BYTE-EXACT, exit 0",
         [ln.replace("!! 1 px DIFFER", "BYTE-EXACT") for ln in ok_lines], 0, 4),
    )
    for label, lines, gate_status, want in shapes:
        bad = gate_selftest(driver, _stub_gate_run(lines, gate_status), quiet=True)
        check(bad == want, label, "%d of its 4 checks MISS (must be %d)" % (bad, want))
    check(ReferenceModel.render_wall_frame is real_render, "... and puts the real oracle back")

    shared = len(log)
    if extra is not None:
        extra(check, tmp, src)

    bad = len(log) - sum(log)
    print("selftest: %s" % ("all mutations rejected (%d checks: %d shared + %d %s)"
                            % (len(log), shared, len(log) - shared, driver) if not bad
                            else "!! %d CHECK(S) HAVE NO TEETH" % bad), flush=True)
    print("NOT COVERED by this arm: the E1M1 program itself. The fixture is 10 lines, the stub "
          "gates compare no pixels, and the exclusion's cell set is exercised on a label table "
          "built for it here, not on a real self-reset. Use --selftest-gate, and the gate.",
          flush=True)
    return 1 if bad else 0


# --- the expensive arm -----------------------------------------------------------------------

def gate_selftest(driver, run_driver, quiet=False):
    """OPT-IN, one E1M1 assemble: run the REAL gate, under the REAL pool, against an ORACLE
    CORRUPTED BY ONE BYTE -- and require FAIL. -> the NUMBER of its checks that MISSed, so the cheap
    arm can require WHICH one a stub defeats; any non-zero is a failed arm.

    The mutation is on the side the gate compares AGAINST, so the fj program runs exactly as it
    does in the ordinary run: the arm costs one assemble, always terminates, and every one of the
    four viewpoints must come back `!! 1 px DIFFER`. That count is the teeth AND most of a positive
    arm at once -- a wrapper that swallowed the gate's status, or a gate that stopped comparing
    some viewpoint, exits 0 quite happily; and "exactly one pixel, four times" is the byte-exactness
    claim itself, minus the one byte this arm corrupted.

    UNRUN as of this commit (CLAUDE.md rule 1: another heavy job had the box): no --selftest-gate
    run has been made, so the REQUIRED lines below are this arm's requirement, not a report of what
    deg_gate printed. What HAS run is the accounting: the cheap arm drives these four checks over
    seven stub gates and requires each to MISS the number of checks its row names -- four of them
    defeat one check each, one per check, so no check here is load-bearing for nothing.

    THE REST OF THE POSITIVE ARM IS THE DRIVER'S ORDINARY RUN, not a second pass inside this one:
    `python scratchpad/12m/deg_gate_blocked.py` printing 4x BYTE-EXACT, PASS and its op counts is
    the verdict a commit message cites anyway, and re-running it here would double a build the
    citation has to show regardless.

    `quiet` runs it over a stub instead of a build, which is how the cheap arm controls the
    accounting below without paying for a gate.
    """
    from doomfj.reference_model import ReferenceModel
    real_render = ReferenceModel.render_wall_frame
    say = (lambda *a, **k: None) if quiet else print

    def corrupted(self, *args, **kwargs):
        frame = bytearray(bytes(real_render(self, *args, **kwargs)))
        frame[0] ^= 1                   # exactly one pixel, so the gate must say "1 px DIFFER"
        return bytes(frame)

    say("%s --selftest-gate: the REAL gate, oracle corrupted by one byte -- it must FAIL" % driver,
        flush=True)
    say("  MUTATED : doomfj.reference_model.ReferenceModel.render_wall_frame, wrapped so every "
        "frame it returns comes back", flush=True)
    say("            with byte 0 XOR 1 -- one pixel, at all four viewpoints. Nothing on the fj "
        "side is touched.", flush=True)
    say("  REQUIRED: the driver exits non-zero; 'px DIFFER' appears exactly 4 times; every one of "
        "them is '!! 1 px", flush=True)
    say("            DIFFER'; 'BYTE-EXACT' appears nowhere. Anything else and the gate is not "
        "comparing what it claims.", flush=True)
    say("  ---- the driver's own output, unedited, follows ----", flush=True)
    ReferenceModel.render_wall_frame = corrupted
    tee = _Tee(mirror=not quiet)
    try:
        status = run_driver()
    finally:
        text = tee.stop()
        ReferenceModel.render_wall_frame = real_render

    differ = text.count("px DIFFER")
    one_px = text.count("!! 1 px DIFFER")
    say("  ---- end of it: %d lines, %d 'px DIFFER' of which %d are 1 px, 'BYTE-EXACT' %s ----"
        % (len(text.splitlines()), differ, one_px,
           "PRESENT" if "BYTE-EXACT" in text else "absent"), flush=True)
    checks = [(status != 0, "the corrupted run exits non-zero", "status=%r" % (status,)),
              (differ == 4, "all four viewpoints report px DIFFER", "%d of 4" % differ),
              (one_px == 4, "each differs by EXACTLY the corrupted pixel", "%d of 4" % one_px),
              ("BYTE-EXACT" not in text, "and none of them reports BYTE-EXACT", "")]
    for ok, label, detail in checks:
        say("  %-4s %-58s %s" % ("ok" if ok else "MISS", label, detail), flush=True)
    bad = sum(1 for ok, _, _ in checks if not ok)
    say("selftest-gate: %s"
        % ("the gate still rejects a one-byte difference" if not bad else
           "!! %d of its 4 REQUIREMENTS NOT MET -- this arm did not see the gate reject the "
           "corrupted oracle" % bad), flush=True)
    say("oracle restored: %s" % (ReferenceModel.render_wall_frame is real_render), flush=True)
    return bad
