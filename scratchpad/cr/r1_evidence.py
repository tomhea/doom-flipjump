"""R1's FAIL-before block, produced the only way it can be produced honestly AFTER the fact.

R1 wants the new tests failing before the change and passing after. When the change and the tests
landed in the same commit, "before" is not a state the repo still has -- so this reconstructs it:
each entry MUTATES REAL SOURCE back toward the bug the test exists to catch, runs the test, and
requires it to FAIL; then restores the file and requires it to PASS. A test that passes under its
own mutation is not evidence of anything, and this says so instead of printing a green line.

This is R9's negative-control pattern applied to the test suite rather than to a tool: the output
below is only worth quoting because every FAIL is a real regression the file caught.

⚠ **RUN IT ALONE. IT CORRUPTS THE WORKING TREE ON PURPOSE.** For a few hundred milliseconds at a
time `src/doomfj/wall_renderer.py` and `src/doomfj/build.py` hold a deliberate bug. Anything else
reading the tree in that window reads the mutation -- which is not hypothetical: launching this
beside `emit_baseline.py --check` made the arbiter report EMISSION MOVED on two configs, and cost
an hour proving the emitter was fine (it was; the same text hashes identically under two hash
seeds). CLAUDE.md's "one heavy job at a time" is about RAM; this is about correctness, and it
applies to cheap jobs too.

    python scratchpad/cr/r1_evidence.py            # the FAIL-before / PASS-after pair
"""
import os
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
    # the call-site guard, mutated back to the two shapes it was written to catch
    ("scripts/walk_e1m1.py",
     "            mw, args.map, cfg, asset_wad=aw, sprite_wad=spr,",
     "            mw, args.map, cfg, asset_wad=aw, sprite_wad=spr, **dict(state_wire=\"bin\"),",
     "tests/host/test_emitter_call_sites.py::"
     "test_every_tracked_caller_passes_keywords_the_emitter_has",
     "the entry point splats a retired keyword -- the shape that hid five broken files"),
    # PHASE 2's two real bugs, mutated back
    ("src/doomfj/build.py",
     "    limit = RENDER_FLAT_MAX_WORDS          # config.py's module constant, not a Config field",
     "    limit = cfg.RENDER_FLAT_MAX_WORDS",
     "tests/host/test_build_wall_renderer_setup.py::test_it_gets_past_its_own_first_lines",
     "the flat limit is read off `Config`, which has no such field -- every caller dies on setup "
     "and no gate notices, because none of them call the builder"),
    ("src/doomfj/wall_renderer.py",
     '    "hosted": dict(things=True, player_sim=True, collide=True, moving_things=True),',
     '    "hosted": dict(things=True, player_sim=True),',
     "tests/host/test_build_wall_renderer_setup.py::test_each_tier_means_exactly_what_it_says",
     "a tier quietly means something else -- the failure the whole registry exists to prevent"),
    ("scratchpad/ca2_sweep.py",
     "stdin=encode_feed_mapunits(vx, vy, va)",
     'stdin=("%d%s%d%s%d%s" % (vx, chr(10), vy, chr(10), va, chr(10))).encode()',
     "tests/host/test_no_decimal_wire.py::test_every_screen_is_fed_the_binary_wire",
     "the governing 260-frame sweep feeds the retired wire -- its byte-exactness control would "
     "then compare two blank `bad:` frames and pass"),
    ("scratchpad/deg_gate.py",
     "sprite_wad=art, degrade=True, sky=True, bbox_cull=True)",
     "sprite_wad=art, degrade=True, bbox_cull=True)",
     "tests/host/test_oracle_calls_in_step.py::test_every_gate_asks_the_oracle_for_what_it_emits",
     "deg_gate's oracle drops `sky` while its emitter renders it -- 4 viewpoints of mismatch"),
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


def _warn_if_not_alone() -> None:
    """Refuse to mutate the tree while another python could be reading it."""
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"],
                             capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return                                  # not Windows, or no tasklist: nothing to check
    others = [l for l in out.splitlines() if l.lower().startswith("python.exe")]
    if len(others) > 1 and not os.environ.get('R1_EVIDENCE_FORCE'):
        raise SystemExit(
            'REFUSING TO RUN: %d python processes are alive. This harness mutates real '
            'source and restores it; anything reading the tree meanwhile reads the bug. '
            'Wait for them, then re-run. (R1_EVIDENCE_FORCE=1 overrides -- do not quote '
            'the result if you do.)' % len(others))


def _drop_pyc(path: Path) -> None:
    """Delete the cached bytecode for a file this harness just restored.

    ⚠ WITHOUT THIS THE RESTORE DOES NOT TAKE. Python invalidates a .pyc by (source mtime in
    SECONDS, source size), and every mutation here is a same-length edit -- `1 << 4` -> `1 << 3`,
    `>=` -> `>` -- restored within the same second. Both fields match, so the interpreter keeps
    using bytecode compiled from the MUTATED source: `git status` is clean, the file on disk reads
    correctly, and `KEY_USE` is still 8. Every later process in that second inherits it.

    Found by this harness's own PASS-AFTER step, which is what that step is for.
    """
    cache = path.parent / "__pycache__"
    if cache.is_dir():
        for pyc in cache.glob(path.stem + ".*.pyc"):
            pyc.unlink()


NO_TESTS_RAN = 4          # pytest's exit code for "the nodeid matched nothing"


def run(test):
    """`(returncode, last line)`. ⚠ A nodeid that matches NOTHING exits 4, and the first version
    scored any non-zero as the required FAIL -- so when round 4 renamed a test, this harness
    reported its mutation as caught by a test that never ran, and the PR body quoted that line as
    evidence. `main()` treats 4 as an ERROR now, never as a pass."""
    r = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "--no-header", "-x"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-1] if r.stdout.strip() else "<none>"
    return r.returncode, tail


def main():
    # a crude interlock: if another python is running, it may be reading the tree we are about to
    # mutate. Refuse rather than produce a result nobody can trust.
    _warn_if_not_alone()
    ok = True
    print("R1 FAIL-BEFORE -- each line mutates REAL source back to the bug and requires a FAIL")
    print("")
    for path, old, new, test, why in CASES:
        p = ROOT / path
        # ⚠ newline="" both ways: `.gitattributes` pins eol=lf, and a text-mode
        # round trip on Windows rewrites every line, leaving nine tracked files
        # "modified" after a run that is supposed to restore the tree exactly.
        # (Path.read_text gained `newline` only in 3.13, hence the explicit open.)
        with p.open(encoding="utf-8", newline="") as fh:
            src = fh.read()
        control = old == new
        if not control:
            if src.count(old) != 1:
                print("  !! ANCHOR %s x%d in %s -- cannot mutate" % (old[:40], src.count(old), path))
                ok = False
                continue
            with p.open("w", encoding="utf-8", newline="") as fh:
                fh.write(src.replace(old, new))
        try:
            rc, tail = run(test)
        finally:
            with p.open("w", encoding="utf-8", newline="") as fh:
                fh.write(src)
            _drop_pyc(p)
        want_fail = not control
        if rc == NO_TESTS_RAN or "no tests ran" in tail:
            good, rc = False, rc          # a nodeid that matched nothing proves nothing
            tail = "!! NO TESTS RAN -- the nodeid matched nothing (renamed?): " + tail
        else:
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
