"""gen_dryrun.py -- M8 (docs/episode-plan.md 4, step 3): run every per-level scenario GENERATOR on a map that is not
built yet, host-side, no binary -- so a generator's map-hardwired assumption is found here, in minutes, and not in the
level's gate run.

    python scratchpad/gp/gen_dryrun.py --maps E1M3 E1M4 E1M5 E1M8 E1M9          # the matrix (one subprocess a cell)
    python scratchpad/gp/gen_dryrun.py --maps E1M5 --gens roles tours            # some generators
    python scratchpad/gp/gen_dryrun.py --one E1M3 --standin unknown-things -- scratchpad/gp/gate_targets.py ...

THE GENERATORS (docs/level-pipeline.md 4), each run as the level pipeline runs it:
  roles        gp/gate_targets.py --map M --out <draft>            the gate roles (p2a / fight / die scenarios placed)
  checkpoints  gp/scenarios_map.py --map M --suggest-checkpoints   the combat set's checkpoints
  plan         gp/scenarios_map.py --map M --plan                  the combat set itself (B0's input)
  tours        12m/gamespeed.py --map M --validate                 the ten gamespeed tours, stepped on the whole game

A map whose model refuses it (a missing feature: a thing type, a line special, runtime ids past 254 ...) is retried
with the named DRY-RUN STAND-INS below -- model-side substitutes that exist ONLY to get the generator past a missing
feature so the generator's OWN code is exercised. A run that needed any stand-in is NOT clean: its output goes to the
scratch directory, never to scenarios/<map>/ (and is never a scenario set). A clean run writes its drafts as
scenarios/<map>/*.draft.json -- DRAFTS: the owner approves a frozen set per level; nothing here freezes one.

Each failure is CLASSIFIED: FEATURE (the model refuses the map: the feature cluster that lifts it is named) or TOOL
(the generator itself breaks: a hard-wired map assumption to fix here).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


# ================================================================================================
# dry-run stand-ins (model side; each names the feature cluster that removes it, docs/episode-plan.md 2)
# ================================================================================================
def _unknown_things():
    """C6 / C7 / C8: a thing type missing from gamedata.THING_TYPES (the plasma rifle, the invisibility, decorations,
    the Baron, the lost soul ...) is DROPPED from the map's things -- the generator sees the rest of the map"""
    from doomfj import gamedata as gd
    from doomfj.wad import WadFile
    orig = WadFile.things
    if getattr(orig, "_dryrun_unknown", False):
        return

    def things(self, mapname):
        return [t for t in orig(self, mapname) if t.type in gd.THING_TYPES or t.type in gd.NOT_THINGS]
    things._dryrun_unknown = True
    WadFile.things = things


def _undrawn_pickups():
    """C6: a pickup type with no sprite (reference_model.THING_SPRITE: E1M8's cell pack 17) is DROPPED -- it is no
    drawable, and every gate's views (monsters.MonsterViews: pickups by drawable index) KeyError on it"""
    from doomfj import gamedata as gd
    from doomfj.reference_model import THING_SPRITE
    from doomfj.wad import WadFile
    orig = WadFile.things

    def things(self, mapname):
        return [t for t in orig(self, mapname) if not (t.type in gd.THING_TYPES and t.type not in gd.MONSTER_DOOMEDNUMS
                                                      and gd.THING_TYPES[t.type].flags & gd.MF_SPECIAL
                                                      and t.type not in THING_SPRITE)]
    WadFile.things = things


def _door_first_kind():
    """C3: a door two lines ask two MOTIONS of (E1M9's 135: a DR door its D1 open-stay line also opens) takes its first
    line's kind (doors.door_kinds' manual > walk-over > switch order), the motion check skipped"""
    import sys as _sys
    from doomfj import doors as D

    def door_kinds(secs, lds, sds):
        doors = D.door_sectors(secs, lds, sds)
        lines_of = D._door_lines_of(secs, lds, sds)
        out = {}
        for si in sorted(doors):
            src = lines_of[si]
            for k in ("manual", "walk", "switch"):
                if src.get(k):
                    out[si] = sorted(src[k])[0]
                    break
        return out
    D.door_kinds = door_kinds
    for name in ("doomfj.world", "doomfj.wall_renderer"):
        if name in _sys.modules:
            _sys.modules[name].door_kinds = door_kinds


STANDINS = {"unknown-things": _unknown_things, "undrawn-pickups": _undrawn_pickups,
            "door-first-kind": _door_first_kind}

# a refusal's text -> (the feature cluster that lifts it, the stand-in that gets past it)
FEATURE_REFUSALS = (
    (r"thing types missing from gamedata\.THING_TYPES", "C6/C7/C8 (pickups / decorations / monsters)",
     "unknown-things"),
    (r"KeyError: \(\d+, -?\d+, -?\d+, \d+, \d+\).*monsters\.py", "C6 (a pickup with no sprite: THING_SPRITE)",
     "undrawn-pickups"),
    (r"door \d+ is asked two motions", "C3 (a door two lines move two ways)", "door-first-kind"),
    (r"door switch tag \d+ opens a door that closes", "C3 (an S1 switch opening a door that closes again)", None),
    (r"M8 L4: line \d+'s destination .* is within line \d+'s reach", "C5 (teleports: a destination inside another "
     "teleport line's reach)", None),
    (r"suggest: no monster of \w+ lies in a region", "C8 (its monsters: E1M8's four are Barons, 3003)", None),
    (r"leaf lists store mobile index \+ 1 in a byte", "C1/C2 (runtime ids past 254: the byte leaf lists)", None),
)


def classify(text: str):
    """-> (kind, detail, stand-in or None) for a failed run's output"""
    err = last_error(text)
    for pat, cluster, standin in FEATURE_REFUSALS:
        if re.search(pat, err):
            return "FEATURE", "%s -- %s" % (cluster, err), standin
    return "TOOL", err, None


def last_error(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    tb = [i for i, ln in enumerate(lines) if ln.startswith("Traceback")]
    if not tb:
        # a plan whose criteria FAIL (exit 1, no traceback): the failing criteria, not the last line (the freeze
        # checks F1..F5 fail on every unfrozen plan by design)
        crit = [ln.strip() for ln in lines if " FAIL " in ln and not re.match(r"\s*F\d ", ln)]
        if crit:
            return ("criteria FAIL: " + " | ".join(sorted(set(crit)))[:600])
        return (lines[-1] if lines else "(no output)")[:300]
    tail = lines[tb[-1]:]
    where = [ln.strip() for ln in tail if ln.strip().startswith("File ")]
    return ("%s  [%s]" % (tail[-1], where[-1] if where else "?"))[:400]


# ================================================================================================
# the generators
# ================================================================================================
def gen_cmds(m: str, out: Path):
    """name -> (argv after the interpreter, the file it writes); `out` is where the run's outputs go"""
    lo = m.lower()
    cps = out / "checkpoints.draft.json"
    return {
        "roles": (["scratchpad/gp/gate_targets.py", "--map", m, "--out", str(out / "gates.draft.json")],
                  out / "gates.draft.json"),
        "checkpoints": (["scratchpad/gp/scenarios_map.py", "--map", m, "--suggest-checkpoints",
                         "--checkpoints", str(cps)], cps),
        "plan": (["scratchpad/gp/scenarios_map.py", "--map", m, "--plan", "--checkpoints", str(cps),
                  "--file", str(out / ("combat_scenarios_%s_v1.draft.json" % lo))],
                 out / ("combat_scenarios_%s_v1.draft.json" % lo)),
        "tours": (["scratchpad/12m/gamespeed.py", "--map", m, "--validate",
                   "--tours-out", str(out / "gamespeed_tours.draft.json")], out / "gamespeed_tours.draft.json"),
    }


def run_cell(m: str, gen: str, standins, out: Path, log: Path, timeout: int):
    argv, wrote = gen_cmds(m, out)[gen]
    cmd = [sys.executable, str(HERE / "gen_dryrun.py"), "--one", m]
    if standins:
        cmd += ["--standin"] + list(standins)
    cmd += ["--"] + argv
    t0 = time.time()
    env = dict(os.environ, DOOMFJ_MAP=m, PYTHONIOENCODING="ascii:backslashreplace")
    with open(log, "w", encoding="utf-8") as fh:              # streamed: a long run's progress is readable
        fh.write(" ".join(cmd) + "\n\n")
        fh.flush()
        try:
            rc = subprocess.run(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, timeout=timeout,
                                env=dict(env, PYTHONUNBUFFERED="1")).returncode
        except subprocess.TimeoutExpired:
            rc = -9
            fh.write("\nTIMEOUT after %d s\n" % timeout)
    text = log.read_text(encoding="utf-8", errors="replace")
    return rc, text, time.time() - t0, wrote


def _line(r):
    return "%-5s %-12s %-20s %-16s %5d s  %s" % (r["map"], r["gen"], r["result"], "+".join(r["standins"]) or "-",
                                                 r["s"], r["detail"][:220])


def matrix(maps, gens, scratch: Path, timeout: int, write_drafts: bool) -> list:
    rows = []
    for m in maps:
        todo = list(gens)
        for gen in list(todo):
            if gen not in todo:
                continue
            standins = []
            while True:
                clean = not standins
                out = (ROOT / "scenarios" / m.lower()) if (clean and write_drafts) else (scratch / m.lower())
                out.mkdir(parents=True, exist_ok=True)
                log = scratch / ("%s_%s%s.log" % (m.lower(), gen, "_" + "+".join(standins) if standins else ""))
                rc, text, secs, wrote = run_cell(m, gen, standins, out, log, timeout)
                if rc == 0:
                    rows.append({"map": m, "gen": gen, "result": "CLEAN" if clean else "PASS with stand-ins",
                                 "standins": list(standins), "detail": "wrote %s" % wrote, "s": round(secs),
                                 "log": str(log)})
                    break
                kind, detail, sin = classify(text)
                rows.append({"map": m, "gen": gen, "result": kind, "standins": list(standins), "detail": detail,
                             "s": round(secs), "log": str(log)})
                if kind == "FEATURE" and sin and sin not in standins:
                    print(_line(rows[-1]), flush=True)
                    standins.append(sin)
                    continue
                break
            print(_line(rows[-1]), flush=True)
            if gen == "checkpoints" and rows[-1]["result"] not in ("CLEAN", "PASS with stand-ins") and "plan" in todo:
                todo.remove("plan")                                      # the plan reads the checkpoints
                rows.append({"map": m, "gen": "plan", "result": "SKIPPED", "standins": [],
                             "detail": "no checkpoints", "s": 0, "log": ""})
                print(_line(rows[-1]), flush=True)
    return rows


def one(m: str, standins, argv) -> int:
    """the inner run: stand-ins applied, then the generator in THIS process"""
    os.environ["DOOMFJ_MAP"] = m
    for q in (ROOT / "src", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE, ROOT / "tests"):
        if str(q) not in sys.path:
            sys.path.insert(0, str(q))
    for s in [s for s in STANDINS if s in standins]:      # registry order, whatever order they were found in
        STANDINS[s]()
    if standins:
        print("DRY-RUN STAND-INS %s: this run is a TOOL check, not a scenario set" % standins, flush=True)
    import runpy
    script, *rest = argv
    sys.argv = [script] + rest
    sys.path.insert(0, str((ROOT / script).parent))
    try:
        runpy.run_path(str(ROOT / script), run_name="__main__")
    except SystemExit as e:
        if isinstance(e.code, str):
            print(e.code, flush=True)                      # a tool's refusal message is the cell's detail
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--maps", nargs="*", default=[])
    ap.add_argument("--gens", nargs="*", default=["roles", "checkpoints", "plan", "tours"])
    ap.add_argument("--scratch", default=str(ROOT / "scratchpad" / "gp" / "_dryrun"))
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--no-drafts", action="store_true", help="a clean run's outputs go to --scratch too")
    ap.add_argument("--json", help="write the matrix here")
    ap.add_argument("--one", help="(inner) run one generator on this map")
    ap.add_argument("--standin", nargs="*", default=[], choices=sorted(STANDINS))
    argv = sys.argv[1:]
    rest = []
    if "--" in argv:
        k = argv.index("--")
        argv, rest = argv[:k], argv[k + 1:]
    a = ap.parse_args(argv)
    if a.one:
        assert rest, "--one needs `-- SCRIPT ARGS`"
        return one(a.one.upper(), a.standin, rest)
    scratch = Path(a.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    rows = matrix([m.upper() for m in a.maps], list(a.gens), scratch, a.timeout, not a.no_drafts)
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1), encoding="ascii")
    final = {}
    for r in rows:
        final[(r["map"], r["gen"])] = r
    res = [r["result"] for r in final.values()]
    print("\n%d cells: %d CLEAN, %d PASS with stand-ins, %d FEATURE, %d TOOL, %d SKIPPED" % (
        len(res), res.count("CLEAN"), res.count("PASS with stand-ins"), res.count("FEATURE"), res.count("TOOL"),
        res.count("SKIPPED")))
    return 1 if "TOOL" in res else 0


if __name__ == "__main__":
    sys.exit(main())
