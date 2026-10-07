"""M7 P6 (host, docs/gp-p67-interface.md 4.1 and risk 8): every gate that drives a prebuilt GAME-tier binary steps the
player with the MODEL's move (`monsters.MonsterPhase.move`: pickups, blocking by things), never a bare
`ReferenceModel.step_sim` -- a gate that kept step_sim would show every pickup and every block as a mismatch, and cost
a build to find (rule 5, fan-out). Static, by the AST: each listed file's `step_sim` calls must sit in a function the
table below names, with its reason (a route PLANNER, or the frozen run's blocked27 expectation), and each mirror
function named must also call `.move(`.

R9: the scan is run on a mutated copy of p2a_gate.py whose mirror steps step_sim again, and must refuse it.

Not scanned, and why: scratchpad/m2_r4_gate.py drives the HOSTED tier (no things, no player modes);
scratchpad/gp/gatestate_check.py checks the state probe's mechanics on a pre-P1.5 binary (no monsters, no weapon).
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# file -> {function: reason} where a step_sim call is allowed; "+move" marks a function that must ALSO call .move(
ALLOWED = {
    "scratchpad/gp/p2a_gate.py": {},
    "scratchpad/gp/hurt_gate.py": {},
    "scratchpad/gp/fight_gate.py": {},
    "scratchpad/gp/die_gate.py": {},
    "scratchpad/gp/b0_scenarios.py": {},
    "scratchpad/m3_gate.py": {},
    "scratchpad/m2_std_gate.py": {"plan_walkable": "the route planner", "drive": "the route planner",
                                  "plan_to": "the route planner", "plan_route": "the route planner",
                                  "tic": "+move: the planner's step (mph None); the mirror passes mph"},
    "scratchpad/gp/scenarios_v2.py": {"step": "+move: model_frames' blocked27 expectation (mph None)"},
}
MIRRORS = {"scratchpad/gp/p2a_gate.py": "run", "scratchpad/m3_gate.py": "main", "scratchpad/m2_std_gate.py": "tic",
           "scratchpad/gp/scenarios_v2.py": "step"}


def scan(src: str):
    """-> ([(function, line)] of step_sim calls, {function: calls .move(}) of a module's source"""
    tree = ast.parse(src)
    calls, moves = [], {}

    def walk(node, fn):
        for ch in ast.iter_child_nodes(node):
            name = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(ch, ast.Call) and isinstance(ch.func, ast.Attribute):
                if ch.func.attr == "step_sim":
                    calls.append((fn, ch.lineno))
                if ch.func.attr == "move":
                    moves[fn] = True
            walk(ch, name)
    walk(tree, "<module>")
    return calls, moves


def refused(path: str, src: str) -> list:
    calls, moves = scan(src)
    bad = [(fn, line) for fn, line in calls if fn not in ALLOWED[path]]
    bad += [(fn, "no .move(") for fn, why in ALLOWED[path].items() if why.startswith("+move") and not moves.get(fn)]
    mirror = MIRRORS.get(path)
    if mirror and not moves.get(mirror):
        bad.append((mirror, "the mirror does not step the model's move"))
    return bad


def test_game_tier_gates_step_the_model():
    for path in ALLOWED:
        src = (ROOT / path).read_text(encoding="utf-8")
        assert not refused(path, src), (path, refused(path, src))


def test_the_control_a_mirror_back_on_step_sim_is_refused():
    path = "scratchpad/gp/p2a_gate.py"
    src = (ROOT / path).read_text(encoding="utf-8")
    old = "nx, ny, na = mph.move(kd, st.x, st.y, st.angle, dead=dead)"
    assert src.count(old) == 1
    mutated = src.replace(old, "new = sim.rm.step_sim(st, kd, scene=sim._scene(blocked, mp.heights(ms)))\n"
                               "                        nx, ny, na = new.x, new.y, new.angle")
    assert refused(path, mutated)


# ---- #119-1 (M7 P8a, package V): the gates flood the noise through THIS frame's doors -----------------------------
# In "full" (and P8a's modes after it) every game-tier mirror syncs the frame's doors and lifts into the world
# (`MonsterPhase.sync`) BEFORE the weapon (`MonsterPhase.weapon`): a shot's noise floods through the doors as they are
# this frame, as the binary's door tic runs before its weapon (#119-1, DONE in P6+P7). This holds the order so it stays.
def sync_before_weapon(src: str, fn: str):
    """(the first .sync( line, the first .weapon( line) inside function `fn` -- None where there is none"""
    tree = ast.parse(src)
    first = {"sync": None, "weapon": None}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn:
            for ch in ast.walk(node):
                if isinstance(ch, ast.Call) and isinstance(ch.func, ast.Attribute) and ch.func.attr in first:
                    k = ch.func.attr
                    first[k] = ch.lineno if first[k] is None else min(first[k], ch.lineno)
    return first["sync"], first["weapon"]


def test_the_mirrors_sync_the_doors_before_the_weapon():
    for path, fn in MIRRORS.items():
        s, w = sync_before_weapon((ROOT / path).read_text(encoding="utf-8"), fn)
        assert s is not None and w is not None and s < w, (path, fn, s, w)


def test_the_control_a_weapon_before_the_sync_is_refused():
    path = "scratchpad/gp/p2a_gate.py"
    src = (ROOT / path).read_text(encoding="utf-8")
    old = "                        mph.sync(ph[0], ms[0], ms[2])\n"
    assert src.count(old) == 1
    anchor = "                    if loots:\n                        nx, ny, na = mph.move("
    assert src.count(anchor) == 1
    mutated = src.replace(old, "").replace(anchor, anchor.replace(
        "if loots:\n", "if loots:\n                        mph.sync(ph[0], ms[0], ms[2])\n"), 1)
    s, w = sync_before_weapon(mutated, "run")
    assert not (s is not None and w is not None and s < w), (s, w)
