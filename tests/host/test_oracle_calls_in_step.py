"""Every gate that EMITS must ask the oracle for the picture the emitter actually makes.

WHY THIS EXISTS. Retiring `sky`/`steps`/`stack_steps`/`bbox_cull`/`deg` did not only delete emitter
parameters -- all five DEFAULTED TO FALSE, so an emitter call that OMITTED them changed meaning.
Eleven E1M1 gates emitted without them and compared against a `render_wall_frame` call that also
omitted them: consistent before, mismatched after, and only one of the eleven was a pytest test.
`deg_gate` -- the one CLAUDE.md calls "the real proof" -- was among the ten that no suite runs.

So this reads the call sites of every file that does BOTH, and requires the two sides to agree
about the five features the emitter no longer lets anyone turn off.

PR #87 WIDENED IT: gates that drive a PREBUILT binary (m2_std_gate, m3_gate, m1/m5 gates, the M2
R3/R4 gates, m2_pass_probe) never emit, so they were never scanned -- and five of them lacked `sky`.
A tracked scratchpad file that RUNS a binary (FjmRunner / _fjcore / GameBinary), or any file under
scratchpad/gp/, is now judged too; oracle-only experiments (door_gate, the DEG knob probes) compare
oracle pictures with each other and are not. A `**splat` counts as asking for everything only when
it IS the shared set, `reference_model.GAME_RENDER_KW`: that name, its import alias,
`<mod>.GAME_RENDER_KW`, or a name the file binds ONLY by single-target `X = <shared>` statements
and never mutates. Any other binding of the name -- a tuple or chained target, a for, comprehension,
with, walrus or except target, a parameter, an import, a def or class, a match capture, `del X` --
disqualifies it, and so does a mutation (`del X[k]`, `X[k] = v`, `X |= ...`, `X.update/pop/...`),
directly or through a bare alias `Y = X`. A `dict(<shared>, ...)` that switches a forced key off is
not shared (PR #88 rounds 2-4).

What it does NOT check:
- the values, only the presence. A file that passes `sky=False` on a map that has sky would
  satisfy this and still be wrong. It is a tripwire for the omission, which is the failure that
  actually happened, not a proof of agreement;
- objects, only names: `**other.RENDER_KW` matches a class attribute of the same name, any
  module's `GAME_RENDER_KW` counts as the shared set, and scopes are not tracked (a binding anywhere
  in the file counts against the name, which only errs toward flagging);
- a mutation through a call or a container that receives the dict (`tweak(render_kw)`,
  `[render_kw][0].pop("sky")`), or a dynamic binding (`globals()`, `setattr`, `exec`).
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# the five the emitter now always does. `sky` is per-map, so a gate on a sky-less fixture is
# allowed to say `sky=False` -- what it may not do is stay silent.
FORCED = ("sky", "near_steps", "stack_steps", "bbox_cull", "degrade")
EMITTERS = ("emit_wall_renderer", "build_wall_renderer")
SHARED = "GAME_RENDER_KW"          # reference_model's one game-tier keyword set


BINARY_RUNNERS = ("FjmRunner", "_fjcore", "GameBinary")
# historical measurement scripts that ran a binary against the oracle's PRE-retirement flag sets
# (M14/V4-era). Older handoffs quote their results as the history of those tiers (handoff-perf); they
# are not re-run and are not gates today. A new gate is caught by BINARY_RUNNERS; only these named
# files are excused.
HISTORICAL = frozenset({"scratchpad/chk_refactor.py", "scratchpad/m14_baseline_id.py",
                        "scratchpad/m14_vp_ops.py", "scratchpad/v4_col.py"})
# a control tool that renders deliberate VARIANTS of the shared set (sky off, bbox_cull off) through
# a parameter -- judging it would demand it stop being a control
CONTROL_TOOLS = frozenset({"scratchpad/gp/census_control.py"})


def is_gate(rel: str, source: str) -> bool:
    """a tracked tool that compares a built binary against the oracle, without emitting"""
    return rel.startswith("scratchpad/") and rel not in HISTORICAL | CONTROL_TOOLS and (
        rel.startswith("scratchpad/gp/") or any(r in source for r in BINARY_RUNNERS))


def _name(node):
    return getattr(node.func, "id", None) or getattr(node.func, "attr", None)


def _is_shared(e, names) -> bool:
    """Is expression `e` the shared set: GAME_RENDER_KW (or its import alias), `<mod>.GAME_RENDER_KW`,
    a name/attribute this file bound to it, or `dict(<shared>, ...)` that sets no forced key to a
    constant False? (PR #87 round 2: merely NAMING the set somewhere in the file no longer counts.)"""
    if isinstance(e, ast.Name):
        return e.id in names
    if isinstance(e, ast.Attribute):
        return e.attr in names
    if isinstance(e, ast.Call) and getattr(e.func, "id", None) == "dict" and e.args:
        weakened = any(kw.arg in FORCED and isinstance(kw.value, ast.Constant) and not kw.value.value
                       for kw in e.keywords)
        return _is_shared(e.args[0], names) and not weakened
    return False


MUTATORS = ("update", "pop", "popitem", "setdefault", "clear", "__setitem__", "__delitem__")


def _bound(t):
    return getattr(t, "id", None) or getattr(t, "attr", None)


def _bindings(tree):
    """(assigns, rebound, mutated) for the whole file, by name.
    assigns -- name -> the values of its single-target `X = v` (or `X: T = v`) statements, the only
      bindings that can make a name shared;
    rebound -- every name bound ANY other way (PR #88 round 4: tuple unpacking, a loop or a
      comprehension escaped the round-3 rule, which looked only at `X = ...`);
    mutated -- every name whose dict is changed in place, closed over bare aliases `Y = X` both ways
      (they name one dict)."""
    assigns, rebound, mutated, aliases, sole = {}, set(), set(), [], set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and \
                isinstance(n.targets[0], (ast.Name, ast.Attribute)):
            t, v = n.targets[0], n.value
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, (ast.Name, ast.Attribute)):
            t, v = n.target, n.value              # `X: T` without a value binds nothing
        else:
            continue
        sole.add(id(t))
        if v is not None:
            assigns.setdefault(_bound(t), []).append(v)
            if isinstance(v, (ast.Name, ast.Attribute)):
                aliases.append({_bound(t), _bound(v)})
    for n in ast.walk(tree):
        if isinstance(n, (ast.Name, ast.Attribute)) and isinstance(n.ctx, (ast.Store, ast.Del)) \
                and id(n) not in sole:
            rebound.add(_bound(n))
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, (ast.Store, ast.Del)):
            mutated.add(_bound(n.value))
        elif isinstance(n, ast.arg):
            rebound.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            rebound |= {(a.asname or a.name).split(".")[0] for a in n.names if a.name != SHARED}
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            rebound.add(n.name)
        elif type(n).__name__ in ("MatchAs", "MatchStar") and n.name:
            rebound.add(n.name)
        elif type(n).__name__ == "MatchMapping" and n.rest:
            rebound.add(n.rest)
        if isinstance(n, ast.AugAssign):
            t = n.target
            mutated.add(_bound(t.value) if isinstance(t, ast.Subscript) else _bound(t))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUTATORS:
            mutated.add(_bound(n.func.value))
    grown = True
    while grown:
        grown = False
        for group in aliases:
            if group & mutated and not group <= mutated:
                mutated |= group
                grown = True
    return assigns, rebound, mutated


def shared_names(tree) -> set:
    """The names this file binds ONLY to the shared set: the import (and its alias), then -- to a
    fixed point -- each name whose every binding is a single-target assignment of a shared value and
    which the file never mutates (PR #88 rounds 3-4)."""
    assigns, rebound, mutated = _bindings(tree)
    out = rebound | mutated
    roots = {SHARED} | {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                        for a in n.names if a.name == SHARED}
    names = {r for r in roots if r not in out and all(_is_shared(v, roots) for v in assigns.get(r, []))}
    grown = True
    while grown:
        grown = False
        for name, vals in assigns.items():
            if name in names or name in out:
                continue
            if all(_is_shared(v, names) for v in vals):
                names.add(name)
                grown = True
    return names


def out_of_step(source: str, *, gate: bool = False):
    """`[(lineno, [missing...])]` for each oracle call in a file that also emits (or is a gate)."""
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    if not gate and not any(_name(n) in EMITTERS for n in calls):
        return []
    names = shared_names(tree)
    out = []
    for n in calls:
        if _name(n) != "render_wall_frame":
            continue
        if any(kw.arg is None and _is_shared(kw.value, names) for kw in n.keywords):
            continue                    # **the shared set, or a name bound to it in this file
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
            found = out_of_step(source, gate=is_gate(rel, source))
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


def test_a_gate_that_only_drives_a_binary_is_judged():
    """PR #87: the widening's own control -- a gate-named file is scanned although it never emits,
    and a missing `sky` is caught; the same call through the shared set passes."""
    call = ("rm.render_wall_frame(s, scene, wall_mode='W1R', near_steps=True, stack_steps=True, "
            "bbox_cull=True, degrade=True)\n")
    assert out_of_step(call, gate=True) == [(1, ["sky"])]
    assert is_gate("scratchpad/m2_std_gate.py", "from doomfj.fastrun import FjmRunner")
    assert is_gate("scratchpad/gp/census_lib.py", "")
    assert not is_gate("scratchpad/door_gate.py", "rm.render_wall_frame(s, sc, **RENDER_KW)")
    assert not is_gate("tests/host/test_render_features.py", "FjmRunner")
    shared = ("from doomfj.reference_model import GAME_RENDER_KW\n"
              "rm.render_wall_frame(s, scene, sprite_wad=art, **GAME_RENDER_KW)\n")
    assert out_of_step(shared, gate=True) == [], "a splat of the shared set asks for all of it"
    assert out_of_step("rm.render_wall_frame(s, scene, **other_kw)\n", gate=True) == \
        [(1, list(FORCED))], "a splat of anything else is judged like an omission"


def test_the_shared_set_turns_on_every_forced_feature():
    """PR #87 round 2: deleting `sky` or `bbox_cull` from GAME_RENDER_KW used to pass the whole suite."""
    from doomfj.reference_model import GAME_RENDER_KW
    assert all(GAME_RENDER_KW.get(k) is True for k in FORCED), GAME_RENDER_KW
    assert GAME_RENDER_KW.get("things") is True and GAME_RENDER_KW.get("wall_mode") == "W1R"


def test_a_splat_counts_only_when_it_is_the_shared_set():
    """The round-2 controls: an import of the set does not excuse a splat of something else."""
    own = ("from doomfj.reference_model import GAME_RENDER_KW\n"
           "render_kw = dict(wall_mode='W1R', near_steps=True, stack_steps=True, bbox_cull=True, "
           "degrade=True)\n"
           "rm.render_wall_frame(s, scene, **render_kw)\n")
    assert out_of_step(own, gate=True) == [(3, list(FORCED))], "m5 variant: own dict without sky"
    other = ("from doomfj.reference_model import GAME_RENDER_KW\n"
             "rm.render_wall_frame(s, scene, **OLD_KW)\n")
    assert out_of_step(other, gate=True) == [(2, list(FORCED))], "m1 variant: an unrelated splat"
    weak = ("from doomfj.reference_model import GAME_RENDER_KW\n"
            "kw = dict(GAME_RENDER_KW, sky=False)\n"
            "rm.render_wall_frame(s, scene, **kw)\n")
    assert out_of_step(weak, gate=True) == [(3, list(FORCED))], "a forced key switched off"
    alias = ("from doomfj.reference_model import GAME_RENDER_KW as _G\n"
             "class O:\n"
             "    RENDER_KW = dict(_G)\n"
             "    def f(self):\n"
             "        return rm.render_wall_frame(s, scene, **self.RENDER_KW)\n")
    assert out_of_step(alias, gate=True) == [], "an alias bound through a class attribute"


def test_a_rebound_or_mutated_name_is_not_the_shared_set():
    """PR #88 rounds 3-4: the reviews' escapes on m5_gate -- rebinding the name to a dict without
    sky, `del render_kw["sky"]`, then tuple unpacking, a loop, a comprehension, a walrus, `with`, a
    parameter -- plus the other mutations and binding forms, each judged like an omission."""
    head = ("from doomfj.reference_model import GAME_RENDER_KW\n"
            "render_kw = dict(GAME_RENDER_KW, sprite_wad=art)\n")
    call = "rm.render_wall_frame(s, scene, **render_kw)\n"
    for extra in ("render_kw = dict(wall_mode='W1R', near_steps=True, stack_steps=True, "
                  "bbox_cull=True, degrade=True)\n",
                  "del render_kw['sky']\n",
                  "render_kw['sky'] = False\n",
                  "render_kw.update(sky=False)\n",
                  "render_kw.pop('sky')\n",
                  "render_kw |= {'sky': False}\n",
                  # round 4: every other way to bind the name, and a mutation through an alias
                  "render_kw, _ = dict(wall_mode='W1R'), 0\n",
                  "for render_kw in (dict(wall_mode='W1R'),): pass\n",
                  "(render_kw := dict(wall_mode='W1R'))\n",
                  "with open(p) as render_kw: pass\n",
                  "from old_gate import OLD_KW as render_kw\n",
                  # a chained target: two names for one dict, so a mutation through `other` would
                  # reach it -- only a single target can make a name shared
                  "render_kw = other = dict(GAME_RENDER_KW)\n",
                  "k2 = render_kw; del k2['sky']\n"):     # through a bare alias: one dict
        src = head + extra + call
        assert out_of_step(src, gate=True) == [(4, list(FORCED))], extra
    for body, line in (("out = [rm.render_wall_frame(s, scene, **render_kw) for render_kw in VARIANTS]\n", 3),
                       ("def frame(render_kw):\n    return rm.render_wall_frame(s, scene, **render_kw)\n", 4),
                       ("frame = lambda render_kw: rm.render_wall_frame(s, scene, **render_kw)\n", 3)):
        assert out_of_step(head + body, gate=True) == [(line, list(FORCED))], body
    assert out_of_step(head + call, gate=True) == [], "the untouched binding still passes"
    alias = head + "k2 = render_kw\nrm.render_wall_frame(s, scene, **k2)\n"
    assert out_of_step(alias, gate=True) == [], "a bare alias of the shared set, never mutated"

