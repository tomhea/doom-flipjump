"""Every gate that EMITS must ask the oracle for the picture the emitter actually makes.

WHY THIS EXISTS. Retiring `sky`/`steps`/`stack_steps`/`bbox_cull`/`deg` did not only delete emitter
parameters -- all five DEFAULTED TO FALSE, so an emitter call that OMITTED them changed meaning.
Eleven E1M1 gates emitted without them and compared against a `render_wall_frame` call that also
omitted them: consistent before, mismatched after, and only one of the eleven was a pytest test.
`deg_gate` -- the one CLAUDE.md calls "the real proof" -- was among the ten that no suite runs.

So this reads the call sites of every file that does BOTH, and requires the two sides to agree
about the five features the emitter no longer lets anyone turn off.

What it does NOT check: the values, only the presence. A file that passes `sky=False` on a map
that has sky would satisfy this and still be wrong. It is a tripwire for the omission, which is the
failure that actually happened, not a proof of agreement.
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# the five the emitter now always does. `sky` is per-map, so a gate on a sky-less fixture is
# allowed to say `sky=False` -- what it may not do is stay silent.
FORCED = ("sky", "near_steps", "stack_steps", "bbox_cull", "degrade")
EMITTERS = ("emit_wall_renderer", "build_wall_renderer")


def _name(node):
    return getattr(node.func, "id", None) or getattr(node.func, "attr", None)


def out_of_step(source: str):
    """`[(lineno, [missing...])]` for each oracle call in a file that also emits."""
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    if not any(_name(n) in EMITTERS for n in calls):
        return []
    out = []
    for n in calls:
        if _name(n) != "render_wall_frame":
            continue
        have = {kw.arg for kw in n.keywords if kw.arg}
        missing = [k for k in FORCED if k not in have]
        if missing:
            out.append((n.lineno, missing))
    return out


def test_every_gate_asks_the_oracle_for_what_it_emits():
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    assert len(files) > 50, f"the listing looks wrong ({len(files)}) -- vacuous run"
    bad, seen = [], 0
    for rel in files:
        try:
            source = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            found = out_of_step(source)
        except SyntaxError:
            continue
        seen += 1
        bad += [(rel, line, miss) for line, miss in found]
    print(f"scanned {seen} tracked files")
    assert not bad, "gates whose oracle call omits what the emitter always does:\n" + "\n".join(
        f"  {rel}:{line} missing {', '.join(miss)}" for rel, line, miss in bad
    )


def test_the_scan_catches_an_omission():
    """R9: without this the test above passes just as well when `out_of_step` matches nothing."""
    src = ("emit_wall_renderer(w, 'E1M1', c)\n"
           "rm.render_wall_frame(s, scene, wall_mode='W1R')\n")
    assert out_of_step(src) == [(2, list(FORCED))]


def test_a_file_that_only_uses_the_oracle_is_not_judged():
    """The other half: the oracle's own tests compare against tiers on purpose, and a file that
    never emits has no emitter to be out of step WITH."""
    assert out_of_step("rm.render_wall_frame(s, scene, wall_mode='W1R')\n") == []
