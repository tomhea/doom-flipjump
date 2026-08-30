"""Rewrite every emitter call site from eight booleans to one tier name.

The mapping is not a guess: each call's flags are read out of the AST and matched against
`wall_renderer.TIERS`, so a call becomes the tier that means EXACTLY what it meant before. A
combination no tier covers is REFUSED and printed -- that is a missing row in the registry, and
inventing a near-enough tier is how a gate quietly starts certifying a different program.

    python scratchpad/to_tier.py --dry
"""
import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.wall_renderer import TIERS, TIER_FLAGS                        # noqa: E402

# the old names, and what they now fall out of
GONE = set(TIER_FLAGS) | {"menu_entries", "menu_selected", "door_quant", "restore_set",
                          "flat_max_words", "generated_dir", "self_reset"}
BY_FLAGS = {tuple(TIERS[t].get(f, False) for f in TIER_FLAGS): t for t in TIERS}


def tier_for(kwargs):
    return BY_FLAGS.get(tuple(bool(kwargs.get(f, False)) for f in TIER_FLAGS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    files = [f for f in subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                                       capture_output=True, text=True).stdout.split()]
    changed = refused = 0
    for rel in files:
        path = ROOT / rel
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        edits = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            if (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) not in (
                    "emit_wall_renderer", "build_wall_renderer"):
                continue
            if any(kw.arg == "tier" for kw in n.keywords):
                continue                       # already converted -- build.py's own inner call
            literal, unknown = {}, False
            for kw in n.keywords:
                if kw.arg in TIER_FLAGS:
                    try:
                        literal[kw.arg] = ast.literal_eval(kw.value)
                    except (ValueError, SyntaxError):
                        unknown = True
            if unknown:
                print("  REFUSED %s:%d -- a flag is an expression, not a literal; name the tier "
                      "by hand" % (rel, n.lineno))
                refused += 1
                continue
            tier = tier_for(literal)
            if tier is None:
                print("  REFUSED %s:%d -- %s matches no tier. Add a row to wall_renderer.TIERS"
                      % (rel, n.lineno, {k: v for k, v in literal.items() if v}))
                refused += 1
                continue
            edits.append((n.lineno, n.end_lineno, n.end_col_offset, tier))
        if not edits:
            continue
        lines = source.splitlines(keepends=True)
        for start, end, end_col, tier in sorted(edits, reverse=True):
            # ⚠ the tier goes at the END of the argument list. Putting it first turned every call
            # with a positional argument into a syntax error, which the parse check caught before
            # a single file was written.
            last = lines[end - 1]
            lines[end - 1] = last[:end_col - 1] + ', tier="%s"' % tier + last[end_col - 1:]
            chunk = "".join(lines[start - 1:end])
            for name in GONE:
                chunk = re.sub(r"(?<![A-Za-z0-9_])" + name + r"\s*=\s*[^,()]+(\([^()]*\))?,?\s*",
                               "", chunk)
            chunk = re.sub(r",\s*,", ",", chunk)
            chunk = re.sub(r"\(\s*,", "(", chunk)
            chunk = re.sub(r",\s*\)", ")", chunk)
            lines[start - 1:end] = [chunk]
        out = "".join(lines)
        try:
            ast.parse(out)
        except SyntaxError as e:
            print("  !! %s would not parse (%s) -- skipped, fix by hand" % (rel, e))
            continue
        print("  %-40s %d call(s) -> %s" % (rel, len(edits),
                                            ", ".join(sorted({t for *_r, t in edits}))))
        changed += 1
        if not args.dry:
            path.write_text(out, encoding="utf-8")
    print("")
    print("%d file(s) %s, %d call(s) refused"
          % (changed, "would change" if args.dry else "changed", refused))
    return 0


if __name__ == "__main__":
    sys.exit(main())
