"""No tracked file may hand a screen a stdin built from newline-separated decimals.

WHY THIS EXISTS, and why grep was not enough. `state_wire="dec"` retired; the program has been
binary-only since. A decimal feed does not error -- the magic byte check fails, the program halts
at `bad:` after ~200 ops, and the screen shows a blank frame. That reads as a catastrophic render
bug, and CLAUDE.md documents two whole debugging cycles lost to exactly it.

Pattern-matching the f-string to find the stragglers failed TWICE in one review round. It missed
`scripts/measure_frame.py`, which EMITS AND ASSEMBLES and so printed ~209 halt-ops as `ops/frame=`,
a number that looks like a measurement. Then it missed six more that build the same bytes another
way -- `"%d%s%d%s" % (vx, chr(10), vy, chr(10))` in `scratchpad/ca2_sweep.py`, and a bytes literal
in `scratchpad/walker_perf.py`.

`ca2_sweep` is the GOVERNING 260-frame metric, and its own docstring says to point it at deg_gate's
binary -- which is binary-wire. Its declared R9 control, "byte-exactness over all 260 frames",
would have compared two blank `bad:` frames and passed.

This detects the BAD SHAPE rather than whitelisting good encoders. The whitelist version flagged
`StreamScreen(stdin=wire(keys))`, where `wire` is a local helper building the binary feed, and a
unit test of the screen itself -- and a guard that cries wolf gets an allowlist, which is where
this class of bug hides in the first place.
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCREENS = ("StreamScreen", "CountScreen", "DumpScreen", "Recording", "InMemoryScreen")
LF = chr(10)


def _has_newline(value):
    if isinstance(value, str):
        return LF in value
    if isinstance(value, bytes):
        return LF.encode() in value
    return False


def _decimal_shaped(node):
    """the three shapes this repo actually produced, all of them the retired wire"""
    for n in ast.walk(node):
        if isinstance(n, ast.JoinedStr):            # f"{x}<lf>{y}<lf>"
            if any(isinstance(v, ast.Constant) and _has_newline(v.value) for v in n.values):
                return True
        if (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod)
                and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str)
                and "%d" in n.left.value):           # "%d%s%d%s" % (...)
            return True
        if isinstance(n, ast.Constant) and _has_newline(n.value):
            text = n.value if isinstance(n.value, str) else n.value.decode("latin-1")
            if any(part.strip().lstrip("-").isdigit() for part in text.split(LF) if part.strip()):
                return True                          # a bytes literal of decimals
    return False


def decimal_feeds(source: str):
    """`[(lineno, screen)]` for every screen fed the retired wire's shape"""
    out = []
    for n in ast.walk(ast.parse(source)):
        if not isinstance(n, ast.Call):
            continue
        name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if name not in SCREENS:
            continue
        for kw in n.keywords:
            if kw.arg == "stdin" and _decimal_shaped(kw.value):
                out.append((n.lineno, name))
    return out


def test_no_tracked_file_feeds_the_retired_decimal_wire():
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    assert len(files) > 50, "the listing looks wrong (%d) -- vacuous run" % len(files)
    bad = []
    for rel in files:
        try:
            found = decimal_feeds((ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        bad += [(rel, line, screen) for line, screen in found]
    assert not bad, "screens fed the retired decimal wire:" + LF + LF.join(
        "  %s:%d %s(stdin=...)" % (rel, line, screen) for rel, line, screen in bad
    )


def test_the_scan_catches_every_shape_that_got_through_a_grep():
    """R9: the three real shapes, as literals. Without this the test above passes just as well
    when `_decimal_shaped` matches nothing."""
    for src in ('StreamScreen(stdin=f"{x}' + chr(92) + 'n{y}".encode())',
                'StreamScreen(stdin=("%d%s" % (vx, chr(10))).encode())',
                'StreamScreen(stdin=b"-435' + chr(92) + 'n223")'):
        assert decimal_feeds(src), src


def test_the_scan_leaves_the_binary_wire_and_its_helpers_alone():
    """... and the other half, including the two shapes a whitelist version wrongly flagged."""
    assert decimal_feeds("StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))") == []
    assert decimal_feeds("StreamScreen(stdin=encode_feed(x, y, a, 0) + blob_tail)") == []
    assert decimal_feeds("StreamScreen(stdin=wire(keys), n_things=3)") == []
    assert decimal_feeds('StreamScreen(stdin=b"' + chr(92) + 'x2a")') == []
