"""WHICH fj MACROS ARE NOW UNREACHABLE, after the flag retirement removed their callers?

A FlipJump `def` costs nothing in the emitted program unless it is expanded, so a dead macro is
pure source weight -- but that also means the assembler will not tell you it is dead, and deleting
a LIVE one only shows up as a failed assembly minutes later. So this computes the reachable set
properly instead of grepping once:

  ROOTS   every macro name the Python emitter can emit (a literal `name` or `ns.name` anywhere in
          src/doomfj/*.py), plus the fj entry points the build always assembles.
  CLOSURE anything a reachable macro's body expands, transitively.
  DEAD    every `def` not in the closure.

⚠ THE ROOT SET IS THE RISK. A macro named through an f-string the scan cannot see would look dead.
So the roots are deliberately over-broad (any identifier-shaped token in any emitter string), and
the verdict is a CANDIDATE list to read, not a delete script.

    python scratchpad/fj_deadmacros.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FJ = ROOT / "src/fj"
PY = ROOT / "src/doomfj"

DEF_RE = re.compile(r"^\s*def\s+([A-Za-z_][\w]*)\s", re.M)
NS_RE = re.compile(r"^\s*ns\s+([A-Za-z_][\w]*)\s*\{", re.M)
# a macro CALL in fj: an indented bare name (possibly ns-qualified) at the start of a statement
# ⚠ A CALL IS NOT ALWAYS AT THE START OF A LINE. `rep(steps, k) .ts_step_faces a, b` calls a
# namespace-local macro MID-LINE with a leading dot, and the first version of this scan --
# which anchored on an indented leading name -- declared `ts_step_faces`, `lines_step_load`
# and `lines_spr_load` dead. All three are live and shipped. The detector now takes ANY
# occurrence of the name as a word in a comment-stripped body, which OVER-approximates
# liveness -- the right bias, because a live macro wrongly listed costs a failed assembly
# minutes later while a dead one left in place costs nothing.
CALL_RE = re.compile(r"[A-Za-z_][\w]*")
COMMENT_RE = re.compile(r"//.*")


def fj_files():
    return sorted(FJ.glob("*.fj"))


def defs_by_file():
    """{file: {macro name: (start, end) line indices}} -- a def's body runs to its closing brace."""
    out = {}
    for f in fj_files():
        text = f.read_text(encoding="utf-8")
        lines = text.splitlines()
        found = {}
        for m in DEF_RE.finditer(text):
            name = m.group(1)
            start = text[:m.start()].count("\n")
            depth, i = 0, start
            seen_open = False
            while i < len(lines):
                depth += lines[i].count("{") - lines[i].count("}")
                if "{" in lines[i]:
                    seen_open = True
                if seen_open and depth <= 0:
                    break
                i += 1
            found[name] = (start, i)
        out[f] = found
    return out


def main():
    per_file = defs_by_file()
    all_defs = {}
    for f, d in per_file.items():
        for name, span in d.items():
            all_defs.setdefault(name, []).append((f, span))

    # ---- roots: every identifier-shaped token the Python emitter mentions --------------------
    roots = set()
    for p in sorted(PY.glob("*.py")):
        txt = re.sub(r"#.*", "", p.read_text(encoding="utf-8"))
        for tok in re.findall(r"[A-Za-z_][\w.]*", txt):
            roots.add(tok.split(".")[-1])
    # ...plus anything an .fj file calls at top level (the includes' own entry points)
    live = {n for n in all_defs if n in roots}

    # ---- closure: what reachable bodies expand ------------------------------------------------
    changed = True
    while changed:
        changed = False
        for name in list(live):
            for f, (a, b) in all_defs.get(name, []):
                body = "\n".join(f.read_text(encoding="utf-8").splitlines()[a:b + 1])
                body = COMMENT_RE.sub("", body)          # a NAME IN A COMMENT IS NOT A CALL
                for leaf in CALL_RE.findall(body):
                    if leaf != name and leaf in all_defs and leaf not in live:
                        live.add(leaf)
                        changed = True

    dead = sorted(set(all_defs) - live)
    print("fj macros: %d defined, %d reachable, %d CANDIDATE-DEAD"
          % (len(all_defs), len(live), len(dead)))
    print("")
    by_file = {}
    for name in dead:
        for f, (a, b) in all_defs[name]:
            by_file.setdefault(f.name, []).append((name, b - a + 1))
    for fname in sorted(by_file):
        rows = sorted(by_file[fname], key=lambda r: -r[1])
        print("  %-20s %3d macros, %5d lines" % (fname, len(rows), sum(r[1] for r in rows)))
        for name, n in rows[:8]:
            print("       %-40s %4d lines" % (name, n))
        if len(rows) > 8:
            print("       ... and %d more" % (len(rows) - 8))
    return 0


if __name__ == "__main__":
    sys.exit(main())
