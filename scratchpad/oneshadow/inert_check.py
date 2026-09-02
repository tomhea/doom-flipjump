"""Prove the PTR_CELL_BITS refactor is INERT at its default, and that it really is a knob.

Two claims, and the second is what makes the first mean anything:

  1. at PTR_CELL_BITS=8 the assembled bytes are IDENTICAL to the stl before the refactor. A generalised
     table that quietly emits something else at the default would be a silent regression for every
     program that never touches the knob.
  2. at PTR_CELL_BITS=12 and 16 the bytes DIFFER -- otherwise claim 1 could be true simply because the
     constant reaches nothing.

Each assembly runs in a child process, so the parser's stl-prefix cache cannot carry one stl into
another. The stl files are swapped on disk and restored in a finally, with .orig backups the next
run heals from.
"""

import subprocess
import sys
from pathlib import Path

WORKTREE = Path("C:/Users/tomhe/Documents/flipjump-wide")
STL = WORKTREE / "flipjump" / "stl"
NL = chr(10)
TIMEOUT = 300

TOUCHED = [
    STL / "runlib.fj",
    STL / "hex" / "pointers" / "basic_pointers.fj",
    STL / "hex" / "pointers" / "xor_from_pointer.fj",
    STL / "hex" / "pointers" / "xor_to_pointer.fj",
    STL / "hex" / "pointers" / "write_pointers.fj",
]
PROGRAMS = [
    WORKTREE / "programs/hexlib_tests/basics2/pointer_setters.fj",
    WORKTREE / "programs/concept_checks/hex_ptr.fj",
    WORKTREE / "programs/hexlib_tests/basics2/nth_pointers.fj",
]
BASE_REV = "39601e9"      # the commit before the PTR_CELL_BITS refactor


def assemble(program, *defines, width=64):
    """assemble in a CHILD process; return the .fjm bytes, or None."""
    import tempfile
    out = Path(tempfile.mkdtemp()) / "o.fjm"
    # `python -m flipjump` does not work (the package has no __main__); run the CLI entry point
    # directly instead, with cwd=WORKTREE so the worktree copy is the one imported.
    driver = ("import sys; from flipjump import assemble_run_according_to_cmd_line_args as go; go(cmd_line_args=sys.argv[1:])")
    args = [sys.executable, "-c", driver, "--asm", "-o", str(out), "-w", str(width)]
    for d in defines:
        args += ["-D", d]
    args.append(str(program))
    try:
        r = subprocess.run(args, cwd=str(WORKTREE), capture_output=True, timeout=TIMEOUT, text=True)
    except subprocess.TimeoutExpired:
        return None, "<TIMED OUT>"
    if r.returncode != 0 or not out.exists():
        tail = (r.stdout + r.stderr).strip().splitlines()
        return None, (tail[-1] if tail else "no output")
    return out.read_bytes(), "ok"


def git_show(rev, path):
    rel = path.relative_to(WORKTREE).as_posix()
    r = subprocess.run(["git", "show", f"{rev}:{rel}"], cwd=str(WORKTREE),
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git show {rev}:{rel} failed: {r.stderr.strip()}")
    return r.stdout


def restore_from_backups():
    healed = []
    for f in TOUCHED:
        bak = f.with_suffix(f.suffix + ".orig")
        if bak.exists():
            f.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8", newline="")
            bak.unlink()
            healed.append(f.name)
    return healed


def main():
    healed = restore_from_backups()
    if healed:
        print("HEALED a previous interrupted run: restored " + ", ".join(healed) + NL)
    originals = {f: f.read_text(encoding="utf-8") for f in TOUCHED}
    for f, text in originals.items():
        f.with_suffix(f.suffix + ".orig").write_text(text, encoding="utf-8", newline="")

    problems = []
    try:
        print("A. the refactored stl, at the default PTR_CELL_BITS=8, and at 12 / 16")
        now, wide12, wide16 = {}, {}, {}
        for prog in PROGRAMS:
            now[prog], m = assemble(prog)
            wide12[prog], m12 = assemble(prog, "hex.pointers.PTR_CELL_BITS = 12")
            wide16[prog], m16 = assemble(prog, "hex.pointers.PTR_CELL_BITS = 16")
            print("   %-20s default:%-6s  12:%-6s  16:%s" % (prog.name, m, m12, m16))

        print(NL + "B. the stl as of " + BASE_REV + " (before the refactor)")
        for f in TOUCHED:
            f.write_text(git_show(BASE_REV, f), encoding="utf-8", newline="")
        before = {}
        for prog in PROGRAMS:
            before[prog], m = assemble(prog)
            print("   %-20s %s" % (prog.name, m))
    finally:
        for f, text in originals.items():
            f.write_text(text, encoding="utf-8", newline="")
            f.with_suffix(f.suffix + ".orig").unlink(missing_ok=True)
        print(NL + "restored: " + ", ".join(f.name for f in TOUCHED))

    print()
    print("%-22s %-14s %-14s %s" % ("program", "inert at 8?", "12 differs?", "16 differs?"))
    for prog in PROGRAMS:
        a, b = now[prog], before[prog]
        inert = a is not None and b is not None and a == b
        d12 = wide12[prog] is not None and wide12[prog] != a
        d16 = wide16[prog] is not None and wide16[prog] != a
        print("%-22s %-14s %-14s %s" % (prog.name, "IDENTICAL" if inert else "DIFFERS",
                                        "yes" if d12 else "NO", "yes" if d16 else "NO"))
        if not inert:
            problems.append(prog.name + ": not inert at PTR_CELL_BITS=8")
        if not (d12 and d16):
            problems.append(prog.name + ": the knob reaches nothing -- inertness proves nothing")
    print()
    if problems:
        print("FAILED:")
        for p in problems:
            print("    " + p)
        return 1
    print("PASSED -- byte-identical at the default, and the knob demonstrably moves the binary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
