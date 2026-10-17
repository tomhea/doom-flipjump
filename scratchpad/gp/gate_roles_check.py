"""gate_roles_check.py -- M8: E1M1's gate scenarios are UNCHANGED by the gate roles (gate_roles.py), proven by
fingerprint against the gates at a git ref. Oracle only: no binary, no build.

    python scratchpad/gp/gate_roles_check.py [--ref a6b5e63] [--gates p2a fight die hurt]
    python scratchpad/gp/gate_roles_check.py --selftest       # + R9: the fingerprint must SEE a moved role

WHAT IS COMPARED. Each gate's scenario list, built the way its `main` builds it (`p2a_gate.scenarios`,
`fight_gate.scenario_list`, `die_gate.scenario_list`, `hurt_gate.scenario_list`, on E1M1 at the game tier's modes),
is reduced to a FINGERPRINT: every name, key list, control, pose and candidate (pose, setup, late setups), every
number -- and every FUNCTION (a claim, a setup, a late setup) as its RESOLVED BYTECODE: the instruction stream with
each load of a constant, a closure cell, a default argument or a module global replaced by its VALUE when that value
is a number, string or tuple of them, jump targets as instruction indices, and its closure and defaults fingerprinted
the same way (a primitive in the closure is in the tokens). So a claim that read the literal 84 and one that reads a role resolved to 84 fingerprint the same,
and one that reads 85 does not. Objects (the oracle, a world) fingerprint as their type.

The ref's gate files are extracted (`git show`) into a temporary directory placed FIRST on the child's sys.path; the
rest of the tree is the current one, so only the gates' own text differs between the two children.

THE CONTROL (R9, `--selftest`): the current gates with GATE_ROLES_OVERRIDE moving one role each (the reversal door,
the barrel F8a blocks, the first pickup walk, the floor switch's pillar height, the nukage sector, the
chain's pose filter, the court's facing) must part from
the ref on EXACTLY the scenarios that role places -- a fingerprint blind to a role's value would pass anything.
"""
from __future__ import annotations

import argparse
import dis
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GATES = {"p2a": "p2a_gate.py", "fight": "fight_gate.py", "die": "die_gate.py", "hurt": "hurt_gate.py"}
DEFAULT_REF = "a6b5e63"          # the tree before the roles (m8-e1m2-gates' base)
PRIM = (int, float, str, bool, type(None))
_GLOBAL_PRIMS: set = set()

# R9: each override moves ONE role; the scenarios it must move (name prefixes) per gate
CONTROLS = (
    ({"reversal_door": 34}, {"p2a": ("S13",), "die": ("D2", "D3d")}),
    ({"block_barrel": 12}, {"fight": ("F8a",)}),
    ({"pickup_walks": [[-160, 128, 0x40000000], [32, 1440, 0x80000000], [174, 898, 0xE0000000]]},
     {"fight": ("F1 ",)}),
    ({"floor_switch": {"box": 0, "sector": 129, "lowered": 137}}, {"p2a": ("S11",)}),
    ({"nukage_sector": 59}, {"fight": ("F9",), "die": ("D6",)}),
    ({"chain": {"x": 2512, "west_of": None}}, {"fight": ("F7", "S2", "S4")}),
    ({"court": {"points": [[1424, 732], [1424, 760], [1400, 732]], "angle": 0}}, {"fight": ("S3",)}),
)


# ================================================================================================
# the fingerprint
# ================================================================================================
def _prim(v) -> bool:
    return isinstance(v, PRIM) or (isinstance(v, tuple) and all(_prim(x) for x in v))


def _code_tokens(code, env: dict, depth: int) -> list:
    skip = {"COPY_FREE_VARS", "RESUME", "MAKE_CELL", "NOP", "CACHE", "PRECALL"}
    ins = [i for i in dis.get_instructions(code) if i.opname not in skip]
    # a nested function's closure tuple (LOAD_CLOSURE ..., BUILD_TUPLE n before MAKE_FUNCTION with flag 8) is HOW a
    # value reaches it, not what it computes: dropped, with the flag (the nested code resolves the names itself)
    drop = set()
    for k, i in enumerate(ins):
        if i.opname == "MAKE_FUNCTION" and i.arg & 8:
            j = k - 2                              # ... BUILD_TUPLE, LOAD_CONST <code>, MAKE_FUNCTION
            if j >= 0 and ins[j].opname == "BUILD_TUPLE":
                drop.add(j)
                drop.update(range(j - ins[j].arg, j))
    ins = [i for k, i in enumerate(ins) if k not in drop]
    idx = {i.offset: k for k, i in enumerate(ins)}
    jumps = set(dis.hasjrel) | set(dis.hasjabs)
    out = []
    for i in ins:
        if i.opcode in jumps:
            out.append((i.opname, idx.get(i.argval, -1)))
            continue
        if i.opname.startswith("LOAD_") and i.opname not in ("LOAD_ATTR", "LOAD_METHOD"):
            name = i.argval
            if i.opname == "LOAD_CONST":
                v = i.argval
                if hasattr(v, "co_code"):          # a nested genexpr / lambda: its free names are this code's
                    inner = {k: env[k] for k in v.co_freevars if k in env}
                    inner.update({k: env[k] for k in v.co_names if k in env and k in _GLOBAL_PRIMS})
                    out.append(("CODE", _code_tokens(v, inner, depth + 1)))
                    continue
                if _prim(v):
                    out.append(("V", v))
                    continue
            elif isinstance(name, str) and name in env:
                v = env[name]
                if _prim(v):
                    out.append(("V", v))
                    continue
            out.append(("LOAD", name if isinstance(name, str) else repr(name)))
            continue
        if i.opname == "MAKE_FUNCTION":
            out.append((i.opname, i.arg & ~8))
            continue
        out.append((i.opname, i.argval if _prim(i.argval) else type(i.argval).__name__))
    return out


def fp(obj, depth: int = 0):
    if depth > 12:
        return "<deep>"
    if _prim(obj) and not isinstance(obj, tuple):
        return obj
    if isinstance(obj, (list, tuple)):
        return [fp(x, depth + 1) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted((fp(x, depth + 1) for x in obj), key=repr)
    if isinstance(obj, dict):
        return {str(k): fp(v, depth + 1) for k, v in sorted(obj.items(), key=lambda kv: repr(kv[0]))}
    code = getattr(obj, "__code__", None)
    if code is not None:
        env = {}
        if obj.__closure__:
            for name, cell in zip(code.co_freevars, obj.__closure__):
                try:
                    env[name] = cell.cell_contents
                except ValueError:
                    env[name] = None
        if obj.__defaults__:
            names = code.co_varnames[:code.co_argcount]
            env.update(zip(names[len(names) - len(obj.__defaults__):], obj.__defaults__))
        g = getattr(obj, "__globals__", {})
        _GLOBAL_PRIMS.clear()
        for c in [code] + [k for k in code.co_consts if hasattr(k, "co_code")]:
            for name in c.co_names:
                if name in g and _prim(g[name]) and name not in env:
                    env[name] = g[name]
                    _GLOBAL_PRIMS.add(name)
        return {"fn": obj.__name__, "code": _code_tokens(code, env, depth),
                "env": {k: fp(v, depth + 1) for k, v in sorted(env.items())
                        if not _prim(v) and (callable(v) or isinstance(v, (list, dict, set, frozenset)))}}
    return "<%s>" % type(obj).__name__


def scenario_fps(scen: list) -> dict:
    """{scenario name: sha16 of its fingerprint} (names are unique within a gate)"""
    out = {}
    for sc in scen:
        if sc.get("na"):                     # M8: a scenario the map cannot host runs nothing (listed apart)
            out.setdefault("<N/A>", []).append(sc["name"])
            continue
        h = hashlib.sha256(json.dumps(fp(sc), sort_keys=True, default=repr).encode()).hexdigest()[:16]
        assert sc["name"] not in out, sc["name"]
        out[sc["name"]] = h
    return out


# ================================================================================================
# the child: build each gate's scenario list as its main does
# ================================================================================================
def dump(gates: list, out: Path) -> None:
    for q in (ROOT / "src", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
        if str(q) not in sys.path:
            sys.path.append(str(q))
    import onewalk
    import p2a_gate as G
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE, PLAYER_MODE
    res = {"files": {}}
    dsim = onewalk.DoorSim()
    card = dsim.dp.card_at
    for g in gates:
        mod = __import__(GATES[g][:-3])
        res["files"][g] = mod.__file__
        if g == "p2a":
            scen = G.scenarios(dsim, card)
        else:
            w0 = MonsterPhase(dsim.mw, dsim.mapname, BOOT_SKILL, rm=dsim.rm, mode=MONSTER_MODE, player=PLAYER_MODE)
            if g == "hurt":
                scen = mod.scenario_list(dsim, w0.world)
            else:
                scen = mod.scenario_list(dsim, w0.world, card)
        res[g] = scenario_fps(scen)
    out.write_text(json.dumps(res, indent=1), encoding="ascii")


def child(gates, out: Path, first=None, env_extra=None) -> dict:
    env = dict(os.environ, DOOMFJ_MAP="E1M1")
    env.pop("GATE_ROLES_OVERRIDE", None)
    env.pop("PYTHONPATH", None)
    env.update(env_extra or {})
    lines = ["import sys"]
    if first:
        lines.append("sys.path.insert(0, %r)" % str(first))
    lines += ["sys.path.append(%r)" % str(HERE), "import gate_roles_check as C",
              "from pathlib import Path", "C.dump(%r, Path(%r))" % (list(gates), str(out))]
    p = subprocess.run([sys.executable, "-c", "\n".join(lines)], cwd=str(ROOT), env=env, capture_output=True,
                       text=True)
    if p.returncode:
        raise SystemExit("child failed (%s):\n%s\n%s" % (first, p.stdout[-3000:], p.stderr[-6000:]))
    return json.loads(out.read_text(encoding="ascii"))


def extract(ref: str, tmp: Path) -> Path:
    d = tmp / "ref_gates"
    d.mkdir()
    for f in GATES.values():
        txt = subprocess.run(["git", "show", "%s:scratchpad/gp/%s" % (ref, f)], cwd=str(ROOT), capture_output=True,
                             check=True).stdout
        (d / f).write_bytes(txt)
    return d


def compare(a: dict, b: dict, gates) -> dict:
    """{gate: [names that differ or exist on one side only]}"""
    out = {}
    for g in gates:
        names = sorted(set(a[g]) | set(b[g]))
        out[g] = [n for n in names if n != "<N/A>" and a[g].get(n) != b[g].get(n)]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--gates", nargs="*", default=list(GATES))
    ap.add_argument("--selftest", action="store_true", help="also run the R9 controls")
    a = ap.parse_args(argv)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        refdir = extract(a.ref, tmp)
        old = child(a.gates, tmp / "old.json", first=refdir)
        assert all(Path(f).resolve().parent == refdir.resolve() for f in old["files"].values()), old["files"]
        new = child(a.gates, tmp / "new.json")
        assert all(Path(f).resolve().parent == HERE for f in new["files"].values()), new["files"]
        diff = compare(old, new, a.gates)
        ok = True
        for g in a.gates:
            nn = {k: v for k, v in new[g].items() if k != "<N/A>"}
            print("  %-5s %3d scenarios at %s, %3d now: %s%s" % (
                g, len(old[g]), a.ref, len(nn),
                "IDENTICAL fingerprints" if not diff[g] else "DIFFER: %s" % diff[g],
                "; N/A (not run): %s" % new[g]["<N/A>"] if "<N/A>" in new[g] else ""), flush=True)
            ok &= not diff[g]
        print("E1M1 SCENARIOS %s against %s (%d gates, %d scenarios compared)" % (
            "UNCHANGED" if ok else "CHANGED", a.ref, len(a.gates),
            sum(len([k for k in new[g] if k != "<N/A>"]) for g in a.gates)), flush=True)
        if a.selftest:
            for k, (ov, want) in enumerate(CONTROLS):
                gs = [g for g in a.gates if g in want]
                if not gs:
                    continue
                mut = child(gs, tmp / ("ctl%d.json" % k), env_extra={"GATE_ROLES_OVERRIDE": json.dumps(ov)})
                d = compare(old, mut, gs)
                good = all(d[g] and all(any(n.startswith(p) for p in want[g]) for n in d[g])
                           and all(any(n.startswith(p) for n in d[g]) for p in want[g]) for g in gs)
                ok &= good
                print("  CONTROL %-58s parts on %s -- %s" % (
                    json.dumps(ov)[:58], {g: d[g] for g in gs},
                    "PASS (exactly the scenarios it places)" if good else "FAIL"), flush=True)
    print("GATE ROLES CHECK %s (%.0f s)" % ("PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
