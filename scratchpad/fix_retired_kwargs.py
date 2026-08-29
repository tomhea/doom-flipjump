"""Strip RETIRED emitter keywords from call sites -- but only where the value was the shipped one.

The M2 retirement deleted eight emitter parameters and left 32 tracked callers passing them,
including `scripts/walk_e1m1.py` and `scratchpad/deg_gate.py`. Every one of them raises TypeError
on its next run. This repairs the mechanical majority and REFUSES the rest.

The distinction is the whole point. `wall_mode="W1R"` was the shipped value, so deleting the
keyword changes nothing and the script keeps measuring what it measured. `wall_mode="W1"` selected
a renderer that no longer exists, so deleting the keyword silently RETARGETS the script at a
different picture -- which is how a stale gate comes back to life asserting the wrong thing. Those
are printed, never edited.

    python scratchpad/fix_retired_kwargs.py --dry     # what it would do
    python scratchpad/fix_retired_kwargs.py           # do it
"""
import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# retired keyword -> the ONE value that used to be live. A call passing anything else is retargeted
# by removal, so it is reported instead.
SHIPPED = {
    "over_align": False,
    "floor_mode": "FT1",
    "wall_mode": "W1R",
    "raster_mode": "lines",
    "plane_near": True,
    "wall_noise": True,
    "state_wire": "bin",
    "two_sided": False,
    "sky": True,
    "steps": True,
    "stack_steps": True,
    "bbox_cull": True,
    "deg": True,
}
CALLEES = {"emit_wall_renderer", "build_wall_renderer"}


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return _NOT_LITERAL


_NOT_LITERAL = object()


def plan(source: str):
    """`(strippable, refused)` -- lists of `(lineno, col, kwarg, value)` for one file."""
    strippable, refused = [], []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in CALLEES:
            continue
        for kw in node.keywords:
            if kw.arg not in SHIPPED:
                continue
            value = _literal(kw.value)
            entry = (kw.value.lineno, kw.value.col_offset, kw.arg, value)
            if value is _NOT_LITERAL or value != SHIPPED[kw.arg]:
                refused.append(entry)
            else:
                strippable.append(entry)
    return strippable, refused


def strip(source: str, strippable) -> str:
    """Remove `name=value,` occurrences, one keyword at a time, re-parsing after each so the
    positions stay true. Textual because ast.unparse would reformat the whole file."""
    for _lineno, _col, kwarg, _value in strippable:
        pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(kwarg) + r"\s*=\s*[^,()]+,\s*")
        new = pat.sub("", source, count=1)
        if new == source:                      # the last keyword in a call has no trailing comma
            pat2 = re.compile(r",\s*(?<![A-Za-z0-9_])" + re.escape(kwarg) + r"\s*=\s*[^,()]+")
            new = pat2.sub("", source, count=1)
        source = new
    return source


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("files", nargs="*", help="default: every tracked .py")
    args = ap.parse_args()

    files = args.files or [
        f for f in subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                                  capture_output=True, text=True).stdout.split()
        if f.endswith(".py")
    ]
    fixed = refused_total = 0
    for rel in files:
        path = ROOT / rel
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            strippable, refused = plan(source)
        except SyntaxError:
            continue
        if not strippable and not refused:
            continue
        print("%-40s strip %d  refuse %d" % (rel, len(strippable), len(refused)))
        for _l, _c, kwarg, value in refused:
            print("      REFUSED  %s=%r -- not the shipped value; removing it would RETARGET this "
                  "script" % (kwarg, value))
        refused_total += len(refused)
        if strippable and not args.dry:
            out = strip(source, strippable)
            ast.parse(out)                      # never write a file this tool cannot parse
            path.write_text(out, encoding="utf-8")
            fixed += 1
    print("")
    print("%d file(s) %s, %d keyword(s) refused"
          % (fixed, "would be rewritten" if args.dry else "rewritten", refused_total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
