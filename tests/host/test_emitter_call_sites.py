"""Every TRACKED caller of the emitter must pass keywords the emitter actually has.

WHY THIS EXISTS. Retiring a flag deletes a parameter, and the callers that still pass it do not
fail at import, at lint, or in any suite -- they fail the first time somebody runs them, which for
a scratchpad harness can be months later. That is not hypothetical: the previous retirement left
`scratchpad/bench.py` (the repo's ops harness), `scratchpad/opprof.py`, `scratchpad/m14_price_stack.py`
and the `cr/` hash tools all passing `over_align` / `floor_mode` / `wall_mode` / `raster_mode` /
`plane_near` to a signature that no longer had them. Every one of them would have raised TypeError
on the next invocation, and nothing in the repo noticed for a whole PR.

`pyflakes` cannot see this -- a wrong keyword is a runtime error, not an undefined name -- and
nothing else is fast enough to call the emitter (~600 s per config, because the banks scale with
the ASSET wad). So this reads the CALL SITES instead of running them.

WHAT IT DOES NOT COVER, said plainly: a call that splats `**kwargs` hides its keys from any static
reader, so those calls are counted and reported but not checked. Untracked scratchpad files are
skipped on purpose -- there are hundreds of dead experiments there, and `git ls-files` is the
repo's own answer to which of them are maintained.
"""
import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from doomfj.build import build_wall_renderer
from doomfj.wall_renderer import emit_wall_renderer

ROOT = Path(__file__).resolve().parents[2]
WATCHED = {"emit_wall_renderer": emit_wall_renderer, "build_wall_renderer": build_wall_renderer}


def _accepted(fn):
    return set(inspect.signature(fn).parameters)


def bad_keywords(source: str, where: str):
    """`[(where, callee, keyword)]` for every keyword the callee does not accept.

    Returns splat counts too, because a `**kwargs` call is invisible here and saying so is part of
    the result rather than a footnote nobody reads."""
    out, splats = [], 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        fn = WATCHED.get(name)
        if fn is None:
            continue
        accepted = _accepted(fn)
        for kw in node.keywords:
            if kw.arg is None:
                splats += 1
                continue
            if kw.arg not in accepted:
                out.append((where, name, kw.arg))
    return out, splats


def _tracked_python_files():
    listing = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True)
    assert listing.returncode == 0, listing.stderr
    return [ROOT / line for line in listing.stdout.split() if line.endswith(".py")]


def test_every_tracked_caller_passes_keywords_the_emitter_has():
    files = _tracked_python_files()
    assert len(files) > 50, f"the file listing looks wrong ({len(files)} files) -- vacuous run"
    bad, splats, seen = [], 0, 0
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found, n = bad_keywords(source, str(path.relative_to(ROOT)).replace("\\", "/"))
        bad += found
        splats += n
        seen += 1
    print(f"scanned {seen} tracked files; {splats} splat call(s) not statically checkable")
    assert not bad, "callers pass keywords the emitter does not have:\n" + "\n".join(
        f"  {w}: {callee}({kw}=...)" for w, callee, kw in bad
    )


def test_the_scan_rejects_a_keyword_that_does_not_exist():
    """R9: the negative control. Without it this test passes just as well when `bad_keywords`
    silently matches nothing -- which is exactly how it would fail, since a scan that finds no
    call sites reports no problems."""
    bad, _ = bad_keywords(
        "emit_wall_renderer(wad, 'E1M1', cfg, __not_a_real_flag__=True)", "<synthetic>"
    )
    assert bad == [("<synthetic>", "emit_wall_renderer", "__not_a_real_flag__")]


def test_the_scan_accepts_a_keyword_that_does_exist():
    """... and the other half of the control: it must not reject a REAL keyword, or the test above
    would pass for a scan that rejects everything."""
    bad, _ = bad_keywords("emit_wall_renderer(wad, 'E1M1', cfg, things=True)", "<synthetic>")
    assert bad == []


def test_the_scan_actually_finds_the_repo_call_sites():
    """Vacuity control: the sum above means nothing unless the walker really reaches call sites in
    real files. `src/doomfj/build.py` calls the emitter; if the scan cannot see that one, it can
    see none of them."""
    source = (ROOT / "src/doomfj/build.py").read_text(encoding="utf-8")
    calls = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) in WATCHED
    ]
    assert calls, "the walker found no emitter call in build.py -- it is not looking where it thinks"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
