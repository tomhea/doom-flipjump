"""Shared machinery for the deg_gate wrapper (`deg_gate_blocked.py`) -- and the negative controls (R9) its verdict
needs before anyone cites it. (There were two wrappers: deg_gate_placed.py relocated the tables of chosen owner macros
through the pool's macro filter, which flipjump 1.6.0 removed -- the stl now declares the tables that move -- so it
was deleted.)

`deg_gate_blocked.py` is not a copy of the gate: it hands `scratchpad/deg_gate.py`'s own `run()` a table pool factory
(`run(table_pool=...)`, which passes the pool to `flipjump.assemble(table_pool=)`) and the gate does the rest, so
whatever the gate checks, the driver checks. NOTHING IS PATCHED (flipjump 1.6.0's API, 2026-10-31): this used to
install the driver's closure AS `flipjump.assemble` and swap the assembler's `resolve_pinned` for `--no-pin`; the
pool now goes in by argument, and `--no-pin` went with the patch (flipjump has no switch that blocks without
pinning). 35b2fbb ("4/4 byte-exact") and e79d15f cite this driver.

    python scratchpad/12m/deg_gate_blocked.py --selftest        # CHEAP: seconds, no E1M1 build
    python scratchpad/12m/deg_gate_blocked.py --selftest-gate   # EXPENSIVE: one E1M1 assemble

WHAT THE CHEAP ARM CONTROLS -- and what it only BORROWS. Its fixture half (the first five checks)
is a port of flipjump's own unit test, `tests/unit/test_table_pool.py` (a pinned word read through a pointer):
same POINTER_PROGRAM, same inline / relocated / counting / unexcluded / excluded sequence, now on BlockPool's
`pin_all_but`. Those control the ASSEMBLER's pin machinery, not this file; they are here so the checks that
follow stand on a fixture known to still read a cell raw.

What this file's OWN checks control is the plumbing, and each is defeated by a mutation: `run_gate` hands the gate
the driver's pool factory, and a gate that assembles reaches its BODY; a gate's FAIL survives; flipjump's `assemble`
is left as it was; `verdict` refuses a vacuous run (no table moved, or tables moved and no word pinned) and only
WARNS for an explicitly restricted one; and each of `--selftest-gate`'s four checks MISSes ALONE on one of seven
stub gates -- every shape carries the NUMBER of checks it must defeat (0, 1, 1, 1, 1, 2, 4), because the shapes are
not all single-check and the table is what says which is which. The driver adds checks on the pool IT builds
(`cheap_selftest(extra=...)`), because this fixture is not its program. The cheap arm is run on the driver's DEFAULT
configuration whatever else is on the command line (`control_args`): a control whose verdict moves with a tuning
flag is a control that can say NO for a reason of its own making.

WHAT THE CHEAP ARM DOES NOT COVER: the E1M1 program. The fixture has no byte arrays, so the driver's cell list
cannot name a real cell, no part of the real program is assembled, and the stub gates compare no pixels. Only the
expensive arm and the gate itself touch those. CLAUDE.md rule 3: a fast pre-gate is for saving 20 minutes, never for
replacing the gate.
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                   # noqa: E402
from flipjump import FixedIO                                            # noqa: E402
from flipjump.assembler.inner_classes.table_pool import BlockPool                     # noqa: E402
from flipjump.utils.exceptions import FlipJumpException                 # noqa: E402
from doomfj.harness import W                                            # noqa: E402

DEG_GATE = ROOT / "scratchpad" / "deg_gate.py"


def run_gate(table_pool, *, gate=DEG_GATE, labels_out=None):
    """Load the gate module and call its `run(table_pool=..., labels_out=...)`; return its status.

    The gate itself runs, so it cannot fall behind the gate the way a copy would. `table_pool(files) -> BlockPool`
    is the driver's factory (None: the gate unpooled)."""
    spec = importlib.util.spec_from_file_location("deg_gate_run", gate)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        status = module.run(table_pool=table_pool, labels_out=labels_out)
    except SystemExit as exit_code:
        status = exit_code.code
    return status or 0


def verdict(status, pool, *, restricted=False):
    """The driver's exit status: the gate's verdict, AND non-vacuity of the pass under test.

    A pool that relocated nothing assembled the STOCK program, so a green gate says nothing about
    blocking -- and "4/4 byte-exact with blocking on" would be a false citation. A pool that relocated tables but
    pinned no word (its final pin map, `pinned`) is placement, not blocking. The gate's own non-zero status
    always wins, so this can only ever add a failure.

    `restricted` is for a run narrowed ON PURPOSE (an empty match is that experiment's ANSWER): it warns loudly and
    keeps the gate's own status rather than turning a run that answered its question into exit 2.
    """
    if pool is None:                    # the --off baseline: no pass to be vacuous about
        return status
    if pool.allocated == 0:
        return _vacuous(status, restricted,
                        "the pool relocated NOTHING (0 allocated, %s declined) -- this run is the "
                        "stock program, whatever the gate said" % format(pool.declined, ","))
    if not pool.pinned:
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

# THE FIXTURE, verbatim from flipjump's tests/unit/test_table_pool.py::POINTER_PROGRAM. `hex.xor
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

# the stub gates take deg_gate's interface: run(table_pool=None, labels_out=None) -> status
_STUB_FAIL = """
def run(table_pool=None, labels_out=None):
    print("(stub gate) pool factory handed in: %s" % (table_pool is not None))
    print("(664,291,0x18000000): 1,234 ops  !! 7 px DIFFER")
    print("FAIL")
    return 1
"""
_STUB_PASS = """
def run(table_pool=None, labels_out=None):
    print("(stub gate) 4 viewpoints BYTE-EXACT")
    print("PASS")
    return 0
"""
# deg_gate's one call into the assembler, on the fixture instead of on E1M1: `@SRC@` and `@OUT@` are
# substituted with real paths when the stub is written. This is the stub that makes "--selftest
# hands the gate the same factory the gate runs under" a run rather than a sentence -- the factory is
# ENTERED here; whether the fixture then assembles is the driver's business, not the control's.
_STUB_ASSEMBLE = """
from pathlib import Path
import flipjump as fj
from doomfj.harness import W


def run(table_pool=None, labels_out=None):
    print("(stub gate) pool factory handed in: %s" % (table_pool is not None))
    files = [Path(@SRC@)]
    try:
        fj.assemble(files, Path(@OUT@), memory_width=W, show_progress=False,
                    table_pool=None if table_pool is None else table_pool(files))
        print("(stub gate) fj.assemble returned")
    except BaseException as e:
        cause, depth = e, 0
        while (cause.__cause__ or cause.__context__) is not None and depth < 6:
            cause, depth = (cause.__cause__ or cause.__context__), depth + 1
        print("(stub gate) fj.assemble raised %s (%s: %s)" % (type(e).__name__, type(cause).__name__, cause))
    return 0
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


def build_and_run(source, tmp, name, pool):
    """-> (output, ops, cause). A mutant that DIES is a rejection, not an error, so a broken run
    comes back as an output that is not the fixture's rather than as an exception."""
    out = tmp / (name + ".fjm")
    fj.assemble([source], out, memory_width=W, show_progress=False, table_pool=pool)
    io = FixedIO(b"")
    try:
        stats = fj.run(out, io_device=io, show_progress=False, print_termination=False)
    except FlipJumpException as e:
        return None, 0, type(e).__name__
    return io.get_output(allow_incomplete_output=True), stats.op_counter, str(stats.termination_cause)


def control_args(parser, a):
    """-> a PRISTINE namespace for --selftest, built from `parser`'s DEFAULTS rather than from `a`.

    The cheap arm is a negative control, so its subject must be the driver's default configuration:
    read the user's own namespace and the control's verdict depends on what else is on the command
    line. It did (`--span-bits 0x100` once printed a MISS that was an artefact of the flag). A tool whose whole job
    is to say whether a check has teeth may not have a mode in which it says NO for a reason of its own making. The
    tuning flags are therefore not applied to the control -- and it says so, rather than ignoring them quietly.
    """
    ctl = parser.parse_args([])
    ignored = sorted("--" + name.replace("_", "-") for name, default in vars(ctl).items()
                     if not name.startswith("selftest") and getattr(a, name) != default)
    if ignored:
        print("  --selftest controls the DEFAULT configuration, so %s %s not applied to it"
              % (", ".join(ignored), "is" if len(ignored) == 1 else "are"), flush=True)
    return ctl


def cheap_selftest(driver, table_pool, *, body_ran=None, extra=None):
    """The DEFAULT --selftest arm: mutate the pool's raw-cell list, this file's plumbing, the vacuity guard and the
    expensive arm's accounting, and require every mutation to be rejected.

    `table_pool` is the driver's factory; `body_ran()` -> how many pools it has built, so the stub gate that assembles
    can prove the factory was ENTERED. `extra(check, tmp, src)` contributes the driver's own checks.
    """
    tmp = Path(tempfile.mkdtemp(prefix="deg_gate_ctl_"))
    src = tmp / "pointer.fj"
    src.write_bytes(POINTER_SOURCE.encode("ascii"))
    print("%s --selftest: the cheap arm (tiny pointer fixture, NO E1M1 build)" % driver, flush=True)
    log = []

    def check(ok, label, detail=""):
        log.append(bool(ok))
        print("  %-4s %-58s %s" % ("ok" if ok else "MISS", label, detail), flush=True)

    # --- checks 1-5: flipjump's own test, ported. They control the ASSEMBLER, not this driver; they run here because
    # every later check needs a fixture that still reads a cell raw (a stale fixture is a FAILURE, never a SKIP).
    inline, inline_ops, cause = build_and_run(src, tmp, "inline", None)
    check(inline == FIXTURE_OUTPUT, "fixture: the inline build prints %r" % FIXTURE_OUTPUT,
          "got %r in %d ops (%s)" % (inline, inline_ops, cause))

    # every label of the program, each to the next: a pool told to leave all of them unpinned moves its tables and
    # pins nothing (the labels: what flipjump's assemble returns)
    every_cell = sorted(fj.assemble([src], tmp / "labels.fjm", memory_width=W, show_progress=False))
    relocated = BlockPool(W, POOL_BASE, pin_all_but=every_cell)          # tables move; every cell stays unpinned
    out, ops, cause = build_and_run(src, tmp, "relocated", relocated)
    check(out == inline and relocated.allocated > 0 and not relocated.pinned,
          "relocation alone leaves the output alone",
          "%d tables, %d pinned, %d -> %d ops" % (relocated.allocated, len(relocated.pinned), inline_ops, ops))

    counting = BlockPool(W, POOL_BASE)
    fj.assemble([src], tmp / "counting.fjm", memory_width=W, show_progress=False, table_pool=counting)
    check(counting.reads_words_raw, "fixture: it still reads a cell through hex.pointers",
          "reads_words_raw=%s, %d groups" % (counting.reads_words_raw, len(counting.counts)))

    # without pin_all_but the assembler does not know which cells are read raw: it pins NO word, for the pointer
    # runtime's sake, and the program is the same program, slower. The mutation is caught by that fallback.
    unexcluded = BlockPool(W, POOL_BASE)
    try:
        out, ops, cause = build_and_run(src, tmp, "unexcluded", unexcluded)
    except FlipJumpException as e:
        out, cause = None, "%s: %s" % (type(e).__name__, str(e)[:40])
    check(out == inline and list(unexcluded.unpins) == ["the pointer runtime"],
          "MUTANT: no raw-cell list at all -> no word is pinned (the pointer runtime)",
          "output %r, unpins %s" % (out, dict(unexcluded.unpins)))

    # d is the cell the pointer reads: one op
    pool = BlockPool(W, POOL_BASE, pin_all_but=[("d", 1)])
    out, ops, cause = build_and_run(src, tmp, "blocked", pool)
    check(out == inline and pool.pinned,
          "blocking with the pointed-to cell left unpinned: the same program",
          "%d pinned words, %d tables, %d ops" % (len(pool.pinned), pool.allocated, ops))

    # --- and one mutation flipjump's test does not make: a list that names the WRONG cells (none), which is the
    # failure mode the driver's cell list can actually have.
    try:
        out, ops, cause = build_and_run(src, tmp, "unprotected", BlockPool(W, POOL_BASE, pin_all_but=[]))
    except FlipJumpException as e:
        out, cause = None, type(e).__name__
    check(out != inline, "MUTANT: a list omitting the pointed-to cell -> not that program",
          "output %r (%s)" % (out, cause))

    # --- verdict: every branch of it
    inert = BlockPool(W, POOL_BASE, max_slot_ops=0, pin_all_but=[("d", 1)])   # relocates nothing: no slot fits
    build_and_run(src, tmp, "inert", inert)
    status, text = capture(lambda: verdict(0, inert))
    check(status != 0 and "VACUOUS" in text, "MUTANT: a pool that relocated nothing is not a PASS",
          "allocated=%d, exit %r" % (inert.allocated, status))
    status, text = capture(lambda: verdict(0, inert, restricted=True))
    check(status == 0 and "WARNING" in text, "... but a run RESTRICTED on purpose only warns",
          "exit %r, %r" % (status, text[4:36]))
    check(verdict(0, pool) == 0, "... while a pool that did relocate and pin passes",
          "allocated=%d, %d pinned" % (pool.allocated, len(pool.pinned)))
    check(verdict(1, pool) != 0, "... and the gate's own FAIL is never overridden by it")
    check(verdict(0, None) == 0, "... and --off, which has no pool at all, is not vacuous")
    # tables relocated, nothing pinned: placement wearing blocking's name -- a real pool, not a mutated one
    status, text = capture(lambda: verdict(0, relocated))
    check(status != 0 and "placement, not blocking" in text,
          "MUTANT: blocked tables but NO pinned word is not a PASS",
          "%d pinned, %d tables, exit %r" % (len(relocated.pinned), relocated.allocated, status))

    # --- run_gate: the factory goes in, the gate's status comes out, and flipjump is left alone
    stubs = {}
    for name, body in (("fail", _STUB_FAIL), ("pass", _STUB_PASS),
                       ("assemble", _STUB_ASSEMBLE.replace("@SRC@", repr(str(src)))
                                                  .replace("@OUT@", repr(str(tmp / "stub.fjm"))))):
        stubs[name] = tmp / ("stub_%s.py" % name)
        stubs[name].write_bytes(body.encode("ascii"))

    stock_assemble = fj.assemble
    status, text = capture(lambda: run_gate(table_pool, gate=stubs["fail"]))
    check(status == 1, "MUTANT: a gate that FAILs comes back as a non-zero driver status",
          "status=%r" % (status,))
    check("handed in: True" in text, "... and the gate was handed the DRIVER'S pool factory",
          text.strip().splitlines()[0] if text.strip() else "(the stub printed nothing)")
    check(fj.assemble is stock_assemble, "... and flipjump's assemble is untouched (nothing is patched)")
    check(capture(lambda: run_gate(table_pool, gate=stubs["pass"]))[0] == 0, "a gate that passes comes back as 0")

    before = None if body_ran is None else body_ran()
    status, text = capture(lambda: run_gate(table_pool, gate=stubs["assemble"]))
    said = [ln for ln in text.splitlines() if "fj.assemble" in ln]
    check(status == 0 and bool(said) and "handed in: True" in text,
          "a gate that assembles reaches the driver's pool factory",
          "handed in: %s; %s" % ("handed in: True" in text, said[-1][:44] if said else "the stub never got there"))
    if body_ran is not None:
        check(body_ran() > before, "... and the factory's BODY ran -- the pool this driver builds",
              "%r -> %r pools" % (before, body_ran()))

    # --- the EXPENSIVE arm's accounting, driven over stub gates so --selftest-gate's verdict is not
    # the one claim in this file that nothing controls. No build: the stubs print what deg_gate
    # prints, and every shape below carries the number of that arm's four checks it must defeat.
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
          "gates compare no pixels, and the cell list is exercised on declarations written for it here, not on a "
          "real self-reset. Use --selftest-gate, and the gate.", flush=True)
    return 1 if bad else 0


# --- the expensive arm -----------------------------------------------------------------------

def gate_selftest(driver, run_driver, quiet=False):
    """OPT-IN, one E1M1 assemble: run the REAL gate, under the REAL pool, against an ORACLE
    CORRUPTED BY ONE BYTE -- and require FAIL. -> the NUMBER of its checks that MISSed, so the cheap
    arm can require WHICH one a stub defeats; any non-zero is a failed arm.

    The mutation is on the side the gate compares AGAINST (doom's own oracle, ReferenceModel.render_wall_frame,
    wrapped for the run and put back), so the fj program runs exactly as it does in the ordinary run: the arm costs
    one assemble, always terminates, and every one of the four viewpoints must come back `!! 1 px DIFFER`. That count
    is the teeth AND most of a positive arm at once -- a wrapper that swallowed the gate's status, or a gate that
    stopped comparing some viewpoint, exits 0 quite happily; and "exactly one pixel, four times" is the byte-exactness
    claim itself, minus the one byte this arm corrupted.

    THE REST OF THE POSITIVE ARM IS THE DRIVER'S ORDINARY RUN, not a second pass inside this one:
    `python scratchpad/12m/deg_gate_blocked.py` printing 4x BYTE-EXACT, PASS and its op counts is
    the verdict a commit message cites anyway.

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
