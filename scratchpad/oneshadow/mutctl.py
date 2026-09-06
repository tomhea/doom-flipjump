"""Negative control for the one-shadow pointer setters (R9).

The claim under test is that the four programs below actually WATCH the new code. So this file:

  1. runs them against the stl as it stands and requires every one to match the golden .out that
     the repo ships -- if the baseline does not pass, nothing below is evidence of anything;
  2. applies each mutation to the real stl source, one at a time, and requires the suite to
     REJECT it.

The mutations are the adjacent, easiest-to-make errors, and the reason this file exists is that
none of them crashes at compile time: an off-by-one in a k=3 walk silently drops a destination
and yields a WRONG DIGIT, and a half-maintained setter is a wild jump that the doom gates cannot
see, because doom calls neither one-sided setter. M6 and M7 matter most -- they are exactly the
"merge the shadow but keep the one-sided setters" mistake, which breaks stl.call and stl.return
for every program that is not doom.

M1 is why triple_exact_xor.fj exists: against the pointer programs alone that mutation SURVIVED,
because their source hexes are the nibbles of real addresses and never take the value 0xf.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fjrun import WORKTREE  # noqa: E402  (fjrun also guards which flipjump got imported)

NL = chr(10)

STL = WORKTREE / "flipjump" / "stl"
LOGICS = STL / "hex" / "logics.fj"
BASIC = STL / "hex" / "pointers" / "basic_pointers.fj"

PROGRAMS = [
    ("triple_exact_xor", "programs/hexlib_tests/basics1/triple_exact_xor.fj",
     "tests/inout/hexlib_tests/basics1/triple_exact_xor.out"),
    ("pointer_setters", "programs/hexlib_tests/basics2/pointer_setters.fj",
     "tests/inout/hexlib_tests/basics2/pointer_setters.out"),
    ("hex_ptr", "programs/concept_checks/hex_ptr.fj",
     "tests/inout/concept_checks/hex_ptr.out"),
    ("nth_pointers", "programs/hexlib_tests/basics2/nth_pointers.fj",
     "tests/inout/hexlib_tests/basics2/nth_pointers.out"),
]

ALIAS_JUMP = ("        def set_jump_pointer ptr {" + NL
              + "            .set_flip_and_jump_pointers ptr" + NL
              + "        }")
ALIAS_FLIP = ("        def set_flip_pointer ptr {" + NL
              + "            .set_flip_and_jump_pointers ptr" + NL
              + "        }")
ONE_SIDED_JUMP = ("        def set_jump_pointer ptr < .to_jump, .to_ptr_var {" + NL
                  + "            ..address_and_variable_xor w/4, .to_jump+w, .to_ptr_var, .to_ptr_var" + NL
                  + "            ..address_and_variable_xor w/4, .to_jump+w, .to_ptr_var, ptr" + NL
                  + "        }")
ONE_SIDED_FLIP = ("        def set_flip_pointer ptr < .to_flip, .to_ptr_var {" + NL
                  + "            ..address_and_variable_xor w/4, .to_flip, .to_ptr_var, .to_ptr_var" + NL
                  + "            ..address_and_variable_xor w/4, .to_flip, .to_ptr_var, ptr" + NL
                  + "        }")
CLEAR_PASS = ("            ..address_and_variable_triple_xor w/4, .to_flip, .to_jump+w,"
              " .to_ptr_var, .to_ptr_var" + NL)

# (name, file, scope, find, replace). `scope` names the macro the mutation belongs to, and the
# find/replace is applied ONLY inside it: several of these anchors also occur verbatim in
# double_exact_xor / quadrupled_exact_xor / address_and_variable_double_xor, and mutating one of
# THOSE would prove nothing about the macros added here.
MUTATIONS = [
    ("M1 triple_exact_xor: off-by-one in the first walk (only source 0xf reaches it)", LOGICS,
     "    def triple_exact_xor",
     "        q3;second_flip+15*dw    // 15", "        q3;second_flip+14*dw    // 15"),
    ("M2 triple_exact_xor: the second group bit 0 is never flipped", LOGICS,
     "    def triple_exact_xor",
     "        t0;third_flip+ 1*dw     //  1", "          ;third_flip+ 1*dw     //  1"),
    ("M3 triple_exact_xor: off-by-one chaining back to the first table", LOGICS,
     "    def triple_exact_xor",
     "        d3;first_flip+7*dw      // 15", "        d3;first_flip+6*dw      // 15"),
    ("M4 address_and_variable_triple_xor: address2 low bit aimed one bit high", LOGICS,
     "    def address_and_variable_triple_xor",
     "address2+4*i+1, address2+4*i+0,", "address2+4*i+1, address2+4*i+1,"),
    ("M5 address_and_variable_triple_xor: the shadow low bit aimed one bit high", LOGICS,
     "    def address_and_variable_triple_xor",
     "var+dbit+i*dw+1, var+dbit+i*dw+0,", "var+dbit+i*dw+1, var+dbit+i*dw+1,"),
    ("M6 set_jump_pointer kept one-sided (the stl.return wild jump)", BASIC,
     "        def set_jump_pointer", ALIAS_JUMP, ONE_SIDED_JUMP),
    ("M7 set_flip_pointer kept one-sided (the ptr_flip/ptr_wflip wild jump)", BASIC,
     "        def set_flip_pointer", ALIAS_FLIP, ONE_SIDED_FLIP),
    ("M8 set_flip_and_jump_pointers: the clearing pass dropped", BASIC,
     "        def set_flip_and_jump_pointers", CLEAR_PASS, ""),
]


def mutate(text, scope, find, repl):
    """apply find->repl inside the macro that `scope` opens. Returns (new_text_or_None, hits)."""
    lo = text.index(scope)
    nxt = text.find(NL + "    def ", lo + 1)
    if nxt < 0:
        nxt = text.find(NL + "        def ", lo + 1)
    hi = len(text) if nxt < 0 else nxt
    body = text[lo:hi]
    n = body.count(find)
    if n != 1:
        return None, n
    return text[:lo] + body.replace(find, repl, 1) + text[hi:], 1


FJRUN = str(Path(__file__).resolve().parent / "fjrun.py")
RUN_TIMEOUT = 60      # every one of these programs finishes in under a second when correct


def run_program(prog):
    """assemble+run in a CHILD process. A mutation can make a program loop for ever instead of
    crashing, so a timeout is a legitimate result -- and a FAILING one."""
    try:
        r = subprocess.run([sys.executable, FJRUN, str(WORKTREE / prog), "--raw"],
                           capture_output=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, b"<TIMED OUT: the program never terminated>"
    out = r.stdout
    return out.startswith(b"OK:"), out[3:]


def check_suite(early_exit):
    """run every program; return (all_ok, report_lines)."""
    lines, all_ok = [], True
    for name, prog, out in PROGRAMS:
        want = (WORKTREE / out).read_bytes()
        ok, got = run_program(prog)
        good = ok and got == want
        lines.append("      %-17s %s%s" % (name, "match" if good else "MISMATCH",
                                           "" if good else "  got=" + repr(got[:80])))
        if not good:
            all_ok = False
            if early_exit:
                break
    return all_ok, lines


def restore_from_backups():
    """if a previous run was killed mid-mutation, its .orig files are still on disk."""
    healed = []
    for f in (LOGICS, BASIC):
        bak = f.with_suffix(f.suffix + ".orig")
        if bak.exists():
            f.write_text(bak.read_text())
            bak.unlink()
            healed.append(f.name)
    return healed


def main():
    healed = restore_from_backups()
    if healed:
        print("HEALED a previous interrupted run: restored " + ", ".join(healed) + NL)
    originals = {f: f.read_text() for f in (LOGICS, BASIC)}
    for f, text in originals.items():
        f.with_suffix(f.suffix + ".orig").write_text(text)
    failures = []
    try:
        print("BASELINE (the stl as it stands) -- must PASS")
        ok, lines = check_suite(False)
        print(NL.join(lines))
        if not ok:
            print(NL + "BASELINE FAILED. Nothing below is evidence of anything.")
            return 2

        print(NL + "MUTATIONS -- each must be REJECTED")
        for name, path, scope, find, repl in MUTATIONS:
            text = originals[path]
            mutated, n = mutate(text, scope, find, repl)
            if mutated is None:
                failures.append(name + ": anchor found %d times in scope, expected 1" % n)
                print("  " + name + NL + "      ANCHOR NOT UNIQUE IN SCOPE (%d) -- not applied" % n)
                continue
            path.write_text(mutated)
            try:
                ok, lines = check_suite(True)
            finally:
                path.write_text(text)
            print("  " + name + NL + "      -> " + ("rejected" if not ok else "SURVIVED"))
            print(NL.join(lines))
            if ok:
                failures.append(name + ": SURVIVED")
    finally:
        for f, text in originals.items():
            f.write_text(text)
            f.with_suffix(f.suffix + ".orig").unlink(missing_ok=True)
        print(NL + "restored: " + ", ".join(f.name for f in originals))

    print()
    if failures:
        print("NEGATIVE CONTROL FAILED -- %d problem(s):" % len(failures))
        for f in failures:
            print("    " + f)
        return 1
    print("NEGATIVE CONTROL PASSED -- baseline matches, all %d mutations rejected."
          % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
