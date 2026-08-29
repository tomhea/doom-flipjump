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


def _dict_literal_keys(node, tree):
    """The keys of a `**` argument when they can be known statically.

    Three shapes reach the emitter in this repo and all three were INVISIBLE to the first version
    of this scan, which counted every splat as uncheckable: `**dict(a=1)` inline, `**NAME` where
    NAME is assigned a dict literal in the same file, and `**(dict(...) if c else {})`. That gap
    hid five files that were broken at the head which added this guard -- including
    `scripts/walk_e1m1.py`, the entry point the same change claimed to have repaired. Returns None
    when the keys genuinely cannot be known."""
    if isinstance(node, ast.IfExp):                       # **(dict(...) if cond else {})
        keys = set()
        for branch in (node.body, node.orelse):
            got = _dict_literal_keys(branch, tree)
            if got is None:
                return None
            keys |= got
        return keys
    if isinstance(node, ast.Dict):                        # **{"a": 1}
        keys = set()
        for k, v in zip(node.keys, node.values):
            if k is None:                                 # **{**BAD} -- a nested splat
                got = _dict_literal_keys(v, tree)
                if got is None:
                    return None
                keys |= got
            elif isinstance(k, ast.Constant) and isinstance(k.value, str):
                keys.add(k.value)
            else:
                return None                               # a computed key
        return keys
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "dict":
        return {kw.arg for kw in node.keywords if kw.arg}
    if isinstance(node, ast.Name):                        # **FLAGS
        # ⚠ PARTIAL KNOWLEDGE IS NOT KNOWLEDGE. The first version returned whatever keys it could
        # see and reported 0 unresolvable splats, so `KW = {}` followed by `KW["sky"] = True`, or
        # `KW.update(...)`, or an augmented assign, all read as "fully checked, nothing wrong".
        # Any write to the name that this function cannot read makes the whole splat unknown.
        found = None
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == node.id for t in n.targets
            ):
                got = _dict_literal_keys(n.value, tree)
                if got is None:
                    return None
                found = got if found is None else found | got
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)                     and n.target.id == node.id:
                return None
            elif isinstance(n, ast.Assign) and any(
                isinstance(t, (ast.Subscript, ast.Attribute))
                and getattr(getattr(t, "value", None), "id", None) == node.id
                for t in n.targets
            ):
                return None                                # KW["sky"] = True
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)                     and getattr(n.func.value, "id", None) == node.id                     and n.func.attr in ("update", "setdefault", "pop", "__setitem__"):
                return None                                # KW.update(...)
        return found
    return None


def bad_keywords(source: str, where: str):
    """`[(where, callee, keyword)]` for every keyword the callee does not accept.

    Splats are resolved when their keys are statically knowable (see `_dict_literal_keys`); the
    count returned is of the ones that are NOT, because a gap in a guard belongs in its output
    rather than in a footnote nobody reads."""
    out, splats = [], 0
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        fn = WATCHED.get(name)
        if fn is None:
            continue
        accepted = _accepted(fn)
        for kw in node.keywords:
            if kw.arg is None:
                keys = _dict_literal_keys(kw.value, tree)
                if keys is None:
                    splats += 1
                    continue
                out += [(where, name, k) for k in sorted(keys) if k not in accepted]
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


def test_the_scan_sees_through_the_three_splat_shapes():
    """R9, and the control for the gap that hid five broken files. Each of these passes a retired
    keyword through a `**`; every one must be caught."""
    for src in (
        "emit_wall_renderer(w, 'E1M1', c, **dict(__gone__=True))",
        "FLAGS = dict(__gone__=True)" + chr(10) + "emit_wall_renderer(w, 'E1M1', c, **FLAGS)",
        "emit_wall_renderer(w, 'E1M1', c, **(dict(__gone__=True) if s else {}))",
        "emit_wall_renderer(w, 'E1M1', c, **{'__gone__': True})",
    ):
        bad, splats = bad_keywords(src, "<synthetic>")
        assert bad == [("<synthetic>", "emit_wall_renderer", "__gone__")], (src, bad)
        assert splats == 0, (src, splats)


def test_a_splat_it_cannot_resolve_is_still_counted():
    """... and the other half: an unresolvable splat must be REPORTED, not silently passed.

    Every shape here defeated the first version, which returned the keys it COULD see and called
    that a complete answer -- so a dict built by mutation reported "0 splats, nothing wrong" while
    checking nothing at all. Partial knowledge is not knowledge; these must all count as 1."""
    NL = chr(10)
    for src in (
        "emit_wall_renderer(w, 'E1M1', c, **f())",
        "emit_wall_renderer(w, 'E1M1', c, **{**BAD})",
        "KW = {}" + NL + "KW['sky'] = True" + NL + "emit_wall_renderer(w, 'E1M1', c, **KW)",
        "KW = {}" + NL + "KW.update(sky=True)" + NL + "emit_wall_renderer(w, 'E1M1', c, **KW)",
        "KW = dict(things=True)" + NL + "KW += o" + NL + "emit_wall_renderer(w, 'E1M1', c, **KW)",
        "emit_wall_renderer(w, 'E1M1', c, **{k: 1})",
    ):
        bad, splats = bad_keywords(src, "<synthetic>")
        assert splats == 1, (src, splats, bad)


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
