"""Delete the branches a pinned constant can never take -- the FIRST retirement's leftovers.

That round replaced `wall_mode`/`floor_mode`/`raster_mode`/`plane_near`/`wall_noise` with locals
pinned to their one live value, and stopped there. The `if` arms guarding the other value stayed:
48 sites, ~660 lines of Python that cannot execute, including one 283-line block.

⚠ THIS SAVES NO BINARY. An unemitted branch never cost span, ops or assemble time -- the binaries
were byte-identical across that whole retirement. It is source bloat, which is what the owner's
ruling is about.

⚠ AND THE HAZARD IS EXACTLY THE ONE THAT BIT BATCH 1a: dedent a block only when the WHOLE
condition is constant. Here each is checked against a table of what the constant IS, the dead
`else` is deleted, and the file is re-parsed after every single edit -- bottom-up, so earlier line
numbers stay valid.

    python scratchpad/fold_constants.py --dry
"""
import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/doomfj/wall_renderer.py"
# the pinned locals and the value they hold, read off the source they are pinned in
TRUE_NAMES = {"lines", "plane_near", "wall_noise"}
EQUALS = {"floor_mode": "FT1", "wall_mode": "W1R"}


def classify(test):
    """True (take the body), False (take the else), or None (not a constant condition)."""
    if isinstance(test, ast.Name) and test.id in TRUE_NAMES:
        return True
    if (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
            and test.left.id in EQUALS and len(test.ops) == 1
            and isinstance(test.comparators[0], (ast.Constant, ast.Tuple))):
        want = EQUALS[test.left.id]
        rhs = test.comparators[0]
        if isinstance(test.ops[0], ast.Eq) and isinstance(rhs, ast.Constant):
            return rhs.value == want
        if isinstance(test.ops[0], ast.NotEq) and isinstance(rhs, ast.Constant):
            return rhs.value != want
        if isinstance(test.ops[0], ast.In) and isinstance(rhs, ast.Tuple):
            return want in [e.value for e in rhs.elts if isinstance(e, ast.Constant)]
        if isinstance(test.ops[0], ast.NotIn) and isinstance(rhs, ast.Tuple):
            return want not in [e.value for e in rhs.elts if isinstance(e, ast.Constant)]
    return None


def one_expr_pass(lines):
    """Fold the LAST constant `A if CONST else B` in the file (a ternary, not a statement)."""
    tree = ast.parse("".join(lines))
    found = None
    for n in ast.walk(tree):
        if isinstance(n, ast.IfExp) and classify(n.test) is not None:
            if found is None or (n.lineno, n.col_offset) > (found.lineno, found.col_offset):
                found = n
    if found is None:
        return False
    keep = found.body if classify(found.test) else found.orelse
    text = "".join(lines)
    offs = [0]
    for l in lines:
        offs.append(offs[-1] + len(l))
    def pos(node, end=False):
        ln = node.end_lineno if end else node.lineno
        col = node.end_col_offset if end else node.col_offset
        return offs[ln - 1] + col
    text = text[:pos(found)] + text[pos(keep):pos(keep, True)] + text[pos(found, True):]
    lines[:] = text.splitlines(keepends=True)
    return True


def one_pass(lines):
    """Fold the LAST constant `if` in the file. Returns True if it changed anything."""
    tree = ast.parse("".join(lines))
    found = None
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and classify(n.test) is not None:
            if found is None or n.lineno > found.lineno:
                found = n
    if found is None:
        return False
    keep = found.body if classify(found.test) else found.orelse
    if not keep:                                    # `if CONST:` with no else and a False test
        del lines[found.lineno - 1:found.end_lineno]
        return True
    # the surviving arm, dedented by exactly one level
    start = keep[0].lineno - 1
    end = keep[-1].end_lineno
    body = [(l[4:] if l.startswith(" " * 4) else l) for l in lines[start:end]]
    lines[found.lineno - 1:found.end_lineno] = body
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    lines = TARGET.read_text(encoding="utf-8").splitlines(keepends=True)
    before = len(lines)
    n = 0
    while one_pass(lines) or one_expr_pass(lines):
        ast.parse("".join(lines))                   # never leave the file unparseable
        n += 1
        if n > 400:
            raise SystemExit("runaway")
    print("folded %d constant branch(es); %d -> %d lines" % (n, before, len(lines)))
    if not args.dry:
        TARGET.write_text("".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
