"""R1's FAIL-before block, produced the only way it can be produced honestly AFTER the fact.

R1 wants the new tests failing before the change and passing after. When the change and the tests
landed in the same commit, "before" is not a state the repo still has -- so this reconstructs it:
each entry MUTATES REAL SOURCE back toward the bug the test exists to catch, runs the test, and
requires it to FAIL; then restores the file and requires it to PASS. A test that passes under its
own mutation is not evidence of anything, and this says so instead of printing a green line.

This is R9's negative-control pattern applied to the test suite rather than to a tool: the output
below is only worth quoting because every FAIL is a real regression the file caught.

    python scratchpad/cr/r1_evidence.py            # the FAIL-before / PASS-after pair
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (file, what to break, what to break it to, which test must then fail, why it is the real bug)
CASES = [
    ("src/doomfj/doorcode.py",
     'f"    wflip lnrow + {li * LINE_REST_LEN + FLAGS_REST_BYTE}*dw + w, "',
     'f"    wflip lnrow + {li * LINE_REST_LEN + FLAGS_REST_BYTE + 1}*dw + w, "',
     "tests/host/test_doorcode.py::test_the_wflip_targets_the_flags_byte_the_walk_reads",
     "the unblock lands one byte on, in `opentop` -- a door that opens by corrupting its height"),
    ("src/doomfj/collision.py",
     "            _sv = secs_open if is_door else secs",
     "            _sv = secs",
     "tests/host/test_doorcode.py::test_a_door_line_bakes_its_opening_at_the_OPEN_height",
     "a door line takes its opening from the SHUT map -- clearing the bit admits you into no gap"),
    ("src/doomfj/build.py",
     'DOOR_PERSIST = ("dstate", "ddir", "dsub", "dwait")',
     'DOOR_PERSIST = ("ddir", "dsub", "dwait")',
     "tests/host/test_doorcode.py::test_the_declared_cells_are_exactly_the_ones_the_reset_persists",
     "`dstate` does not survive the M1 reset -- every door re-shuts on every frame"),
    ("src/doomfj/wireformat.py",
     "KEY_USE = 1 << 4",
     "KEY_USE = 1 << 3",
     "tests/host/test_doorcode.py::test_use_is_the_first_bit_of_the_second_nibble",
     "use collides with turn-right: pressing use turns the player"),
    ("src/doomfj/doors.py",
     "    if used and dr != OPENING:",
     "    if used and dr == CLOSING:",
     "tests/host/test_doors_runtime.py::test_a_press_on_a_fully_open_door_restarts_the_wait",
     "a press only reverses a CLOSING door -- pressing use on an open one no longer holds it"),
    ("src/doomfj/doors.py",
     "            if state >= nstates - 1:",
     "            if state > nstates - 1:",
     "tests/host/test_doors_runtime.py::test_it_waits_open_then_closes_by_itself",
     "the door runs one state PAST its last and never latches open -- an off-by-one at the stop"),
    ("src/doomfj/wall_renderer.py",
     "def emit_wall_renderer(",
     "def emit_wall_renderer(",                         # unmutated: the control for this harness
     "tests/host/test_doors_runtime.py",
     "CONTROL -- nothing is broken, so this suite must PASS here and prove the runner works"),
]


def run(test):
    r = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "--no-header", "-x"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-1] if r.stdout.strip() else "<none>"
    return r.returncode, tail


def main():
    ok = True
    print("R1 FAIL-BEFORE -- each line mutates REAL source back to the bug and requires a FAIL")
    print("")
    for path, old, new, test, why in CASES:
        p = ROOT / path
        src = p.read_text(encoding="utf-8")
        control = old == new
        if not control:
            if src.count(old) != 1:
                print("  !! ANCHOR %s x%d in %s -- cannot mutate" % (old[:40], src.count(old), path))
                ok = False
                continue
            p.write_text(src.replace(old, new), encoding="utf-8")
        try:
            rc, tail = run(test)
        finally:
            p.write_text(src, encoding="utf-8")
        want_fail = not control
        good = (rc != 0) if want_fail else (rc == 0)
        ok &= good
        print("  %-4s %s" % ("FAIL" if rc else "PASS", test.split("::")[-1][:66]))
        print("       %s" % why)
        print("       %s%s" % (tail[:88], "" if good else "   !! NOT THE EXPECTED OUTCOME"))
    print("")
    print("R1 PASS-AFTER -- the tree as committed")
    rc, tail = run("tests/host/test_doorcode.py")
    ok &= rc == 0
    print("  %-4s tests/host/test_doorcode.py   %s" % ("PASS" if not rc else "FAIL", tail[:60]))
    print("")
    print("R1 EVIDENCE: %s" % ("COMPLETE -- every test failed on its own bug and passes without it"
                               if ok else "!! INCOMPLETE -- see the marked line"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
