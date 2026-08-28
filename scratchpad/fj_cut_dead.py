"""Delete the fj macros `fj_deadmacros.py` finds unreachable.

A FlipJump `def` costs nothing in the emitted program unless it is expanded, so this changes no
binary -- `emit_baseline --check` cannot even see it. The proof that a LIVE macro was not taken is
that the fj suite still ASSEMBLES: `tests/fj` builds ~200 real programs through these includes, and
an expansion of a missing macro is a hard assembler error.

    python scratchpad/fj_cut_dead.py --dry
    python scratchpad/fj_cut_dead.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scratchpad"))

from fj_deadmacros import defs_by_file, main as analyse   # noqa: E402

DRY = "--dry" in sys.argv


def dead_set():
    """re-run the analyser's own closure, and take its verdict"""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        analyse()
    names = set()
    for line in buf.getvalue().splitlines():
        m = re.match(r"\s{7}([A-Za-z_]\w*)\s+\d+ lines", line)
        if m:
            names.add(m.group(1))
    return names, buf.getvalue()


def main():
    per_file = defs_by_file()
    # the analyser prints only the top 8 per file, so recompute the full set from its closure
    import fj_deadmacros as A
    all_defs = {}
    for f, d in per_file.items():
        for name, span in d.items():
            all_defs.setdefault(name, []).append((f, span))
    roots = set()
    for p in sorted((ROOT / "src/doomfj").glob("*.py")):
        txt = re.sub(r"#.*", "", p.read_text(encoding="utf-8"))
        for tok in re.findall(r"[A-Za-z_][\w.]*", txt):
            roots.add(tok.split(".")[-1])
    live = {n for n in all_defs if n in roots}
    changed = True
    while changed:
        changed = False
        for name in list(live):
            for f, (a, b) in all_defs.get(name, []):
                body = A.COMMENT_RE.sub("", "\n".join(
                    f.read_text(encoding="utf-8").splitlines()[a:b + 1]))
                for leaf in A.CALL_RE.findall(body):
                    if leaf != name and leaf in all_defs and leaf not in live:
                        live.add(leaf)
                        changed = True
    dead = sorted(set(all_defs) - live)

    total = 0
    for f, defs in per_file.items():
        drop = [(a, b, n) for n, (a, b) in defs.items() if n in dead]
        if not drop:
            continue
        lines = f.read_text(encoding="utf-8").splitlines(keepends=True)
        for a, b, _n in sorted(drop, reverse=True):       # bottom-up, so indices stay valid
            del lines[a:b + 1]
        total += sum(b - a + 1 for a, b, _ in drop)
        print("  %-20s -%3d macros, -%4d lines" % (f.name, len(drop),
                                                   sum(b - a + 1 for a, b, _ in drop)))
        if not DRY:
            f.write_text("".join(lines), encoding="utf-8")
    print("%s %d dead macros, %d lines" % ("WOULD REMOVE" if DRY else "REMOVED", len(dead), total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
