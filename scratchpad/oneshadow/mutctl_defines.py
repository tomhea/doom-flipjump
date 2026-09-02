"""Negative control for the -D override semantics (R9).

tests/unit/test_cli.py claims to pin the three rules of handoff section 3:
  3a  -D overrides a declaration the program makes
  3b  a namespaced constant is addressed as a.b.NAME, and the bare name does not reach it
  3c  -D of a constant nothing declares is a parse error, not a new definition

This file checks that the claim is worth something, by breaking each rule on purpose in the real
source and requiring the suite to REJECT it. None of these mutations crashes: every one of them
assembles a program and produces a WRONG BINARY or a SILENTLY ACCEPTED typo, which is exactly the
failure the tests exist to catch.

If a previous run was interrupted mid-mutation its .orig files are still on disk; this heals from
them on start, and every case runs in a child process with a wall-clock cap.
"""

import subprocess
import sys
from pathlib import Path

WORKTREE = Path("C:/Users/tomhe/Documents/flipjump-wide")
PARSER = WORKTREE / "flipjump" / "assembler" / "fj_parser.py"
CLI = WORKTREE / "flipjump" / "flipjump_cli.py"
NL = chr(10)
TIMEOUT = 180

SKIP_BRANCH = (
    "        if name in self.defines:" + NL
    + "            # -D wins. Behave exactly as if this line had never been written. The value is" + NL
    + "            # already in self.consts - the defines file put it there when it was read." + NL
    + "            self.used_defines.add(name)" + NL
    + "            return" + NL
)

UNUSED_CHECK = (
    "    for name in sorted(set(parser.defines) - parser.used_defines):" + NL
    + '        syntax_error(parser.defines_lineno[name], f\'override of non-defined constant "{name}".\')' + NL
)
BUILTIN_GUARD = "            if name in self.consts and name not in self.builtin_consts:"
NS_WRAP = "        *namespaces, base_name = name.split('.')"

# (name, file, find, replace, what it breaks)
MUTATIONS = [
    ("M1 3a: the override no longer suppresses the declaration", PARSER,
     SKIP_BRANCH, "", "the program keeps its own value, or hits Can-t-redeclare"),
    ("M2 3a: the defines file records the value but never publishes it", PARSER,
     "            # visible from here on, so a later define may use an earlier one and the" + NL
     + "            # overridden program still sees the value at every use site." + NL
     + "            self.consts[name] = Expr(self.defines[name])" + NL,
     "", "the overridden constant ends up undefined"),
    ("M3 3c: an unmatched override is no longer an error", PARSER,
     UNUSED_CHECK, "", "a misspelled -D looks exactly like a working one"),
    ("M4 3c: a define counts as satisfied the moment it is written", PARSER,
     "            self.defines_lineno[name] = p.lineno" + NL,
     "            self.defines_lineno[name] = p.lineno" + NL + "            self.used_defines.add(name)" + NL,
     "3c never fires: a define that meets no declaration is accepted"),
    ("M5 -D w: the builtin guard is dropped", PARSER,
     BUILTIN_GUARD, "            if name in self.consts:",
     "-D w=64 silently rewrites w in the const table"),
    ("M6 3b: the dotted name is no longer wrapped in its namespaces", CLI,
     NS_WRAP, "        namespaces, base_name = [], name",
     "a.b.NAME becomes a top-level name and misses the constant"),
]


def run_suite():
    """the -D tests, in a child process. A timeout is a legitimate, FAILING result."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/test_cli.py", "-q", "--no-header", "-x"],
            cwd=str(WORKTREE), capture_output=True, timeout=TIMEOUT, text=True)
    except subprocess.TimeoutExpired:
        return False, "<TIMED OUT>"
    tail = [ln for ln in r.stdout.splitlines() if "passed" in ln or "failed" in ln or "error" in ln]
    return r.returncode == 0, (tail[-1] if tail else r.stdout[-90:]).strip()


def restore_from_backups():
    healed = []
    for f in (PARSER, CLI):
        bak = f.with_suffix(f.suffix + ".orig")
        if bak.exists():
            f.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")
            bak.unlink()
            healed.append(f.name)
    return healed


def main():
    healed = restore_from_backups()
    if healed:
        print("HEALED a previous interrupted run: restored " + ", ".join(healed) + NL)
    originals = {f: f.read_text(encoding="utf-8") for f in (PARSER, CLI)}
    for f, text in originals.items():
        f.with_suffix(f.suffix + ".orig").write_text(text, encoding="utf-8")
    failures = []
    try:
        print("BASELINE -- must PASS")
        ok, line = run_suite()
        print("      " + line)
        if not ok:
            print(NL + "BASELINE FAILED. Nothing below is evidence of anything.")
            return 2

        print(NL + "MUTATIONS -- each must be REJECTED")
        for name, path, find, repl, breaks in MUTATIONS:
            text = originals[path]
            n = text.count(find)
            if n != 1:
                failures.append(name + ": anchor found %d times, expected 1" % n)
                print("  " + name + NL + "      ANCHOR NOT UNIQUE (%d) -- not applied" % n)
                continue
            path.write_text(text.replace(find, repl, 1), encoding="utf-8")
            try:
                ok, line = run_suite()
            finally:
                path.write_text(text, encoding="utf-8")
            print("  " + name + NL + "      breaks: " + breaks
                  + NL + "      -> " + ("rejected" if not ok else "SURVIVED") + "   " + line)
            if ok:
                failures.append(name + ": SURVIVED")
    finally:
        for f, text in originals.items():
            f.write_text(text, encoding="utf-8")
            f.with_suffix(f.suffix + ".orig").unlink(missing_ok=True)
        print(NL + "restored: " + ", ".join(f.name for f in originals))

    print()
    if failures:
        print("NEGATIVE CONTROL FAILED -- %d problem(s):" % len(failures))
        for f in failures:
            print("    " + f)
        return 1
    print("NEGATIVE CONTROL PASSED -- baseline passes, all %d mutations rejected." % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
