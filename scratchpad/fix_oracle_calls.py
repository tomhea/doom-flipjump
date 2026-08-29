"""Bring `render_wall_frame` calls back into step with an emitter that lost its flags.

Retiring `sky`/`steps`/`stack_steps`/`bbox_cull`/`deg` did not only delete emitter parameters -- it
changed what an emitter call with those arguments OMITTED now produces, because every one of them
defaulted to False. The oracle still has all five, still defaulting False. So every gate that
emitted without them and compared against an oracle without them was consistent before and is
INCONSISTENT now: the fj side renders sky, step faces, stacked pieces, the bbox cull and the
degradation package, and the oracle side does not.

That is a picture mismatch at every viewpoint, in eleven E1M1 gates, and no suite catches it --
they are scratchpad tools. `tests/fj/test_lines_render.py` was the one that DID fail, which is how
the class was found; this is the rest of it.

    python scratchpad/fix_oracle_calls.py --dry
"""
import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# what the emitter now always does. `sky` only where the MAP has one -- every file here is E1M1
# (19 F_SKY1 ceilings); a square-room fixture must stay False, which is why this is not a blanket
# rewrite of every render_wall_frame in the repo.
FORCED = ["sky", "near_steps", "stack_steps", "bbox_cull", "degrade"]
FILES = ["deg_gate", "deg_gate2", "m14_basegate", "m14_gate", "v4_check", "v4b_gate", "v5_gate",
         "v5spr_debug", "v5spr_debug2", "v5spr_gate", "w1r_faces_gate"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    total = 0
    for stem in FILES:
        path = ROOT / "scratchpad" / f"{stem}.py"
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        edits = []
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            if (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) != "render_wall_frame":
                continue
            have = {kw.arg for kw in n.keywords if kw.arg}
            missing = [k for k in FORCED if k not in have]
            if missing:
                edits.append((n.end_lineno, n.end_col_offset, missing))
        if not edits:
            continue
        lines = src.splitlines(keepends=True)
        for end_lineno, end_col, missing in sorted(edits, reverse=True):
            line = lines[end_lineno - 1]
            assert line[end_col - 1] == ")", (stem, end_lineno, repr(line[end_col - 5:end_col]))
            add = ", " + ", ".join(f"{k}=True" for k in missing)
            lines[end_lineno - 1] = line[:end_col - 1] + add + line[end_col - 1:]
        print("%-20s %d call(s): %s" % (stem, len(edits),
                                        ", ".join(sorted({k for _l, _c, m in edits for k in m}))))
        total += len(edits)
        if not args.dry:
            out = "".join(lines)
            ast.parse(out)
            path.write_text(out, encoding="utf-8")
    print("")
    print("%d oracle call(s) %s" % (total, "would be updated" if args.dry else "updated"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
