"""PR #93, review round 2 (R9): which of the slot-layout mutants a VERSION of the layout test tells
apart.

    python scratchpad/gp/p14_layout_gap.py <tree>

The mutants are THIS checkout's `LAYOUT_MUTANTS` (tests/host/test_sprite_column.py), each a single
real edit of the fj text; they are applied to <tree>'s fj text and judged by <tree>'s own
`fj_layouts` / `stated_layouts`. A version that names no key for a mutant is blind to it -- round 2
found the first version blind to a dropped increment, an inserted pointer step and a slot offset
never added. Run it on a tree of the old version (git archive e8c22c3) and on this checkout.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]


def test_module(tree, name):
    sys.path.insert(0, str(tree / "src"))
    spec = importlib.util.spec_from_file_location(name, tree / "tests" / "host" / "test_sprite_column.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(tree):
    mutants = test_module(HERE, "layout_test_here").LAYOUT_MUTANTS
    judge = test_module(tree, "layout_test_there")
    texts = [(tree / "src" / "fj" / f).read_text(encoding="utf-8")
             for f in ("frame_render.fj", "stream_render.fj")]
    want = judge.stated_layouts()
    blind = 0
    for label, side, old, new, _keys in mutants:
        t = list(texts)
        if t[side].count(old) != 1:
            print("%-46s  SITE NOT IN THIS TREE'S TEXT" % label)
            continue
        t[side] = t[side].replace(old, new)
        got = judge.fj_layouts(*t)
        named = [k for k in want if got[k] != want[k]]
        blind += not named
        print("%-46s  %s" % (label, ", ".join(named) if named else "NOTHING -- blind"))
    print("%d of %d mutants told apart by %s's layout test" % (len(mutants) - blind, len(mutants), tree))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
