"""M8 (docs/level-pipeline.md 3): ONE place that names a map's files, so every gate and measurement tool can run on any
E1 map from one switch.

The tools already take `wad` / `mapname` at the bottom (`probe.Oracle`, `onewalk.DoorSim`, gamespeed's tour planner);
what broke them off E1M1 was the DEFAULTS -- a gate that builds `Oracle()` or a `World()` with no map silently gets
E1M1. Their defaults now come from here, and here from the environment:

    DOOMFJ_MAP=E1M2 python scratchpad/gp/p2a_gate.py ...

`ACTIVE` is the map the process measures (E1M1 when unset, which is every tool's behaviour before M8). `profile(map)`
derives each per-map path by one rule, so two tools cannot disagree about where a map's census or baseline lives.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

ACTIVE = os.environ.get("DOOMFJ_MAP", "E1M1").upper()


@dataclass(frozen=True)
class MapProfile:
    map: str            # "E1M2"
    wad: str            # the map's fixture wad, repo-relative (tests/fixtures/make_e1m1_wad.py <map> writes it)
    prefix: str         # binaries: build/<prefix>_<name>.fjm
    census: str         # the one-pass build's census (--counts-cache): E1M1 keeps its historical name
    baseline: str       # msframe.py --against / --save-baseline
    scenarios: str      # the generated per-map scenario files (gate roles, gamespeed records, viewpoints)
    heat: str = ""      # M8 G13: the map's OWN pin-heat list (heatsites.py --map writes it; E1M1: ship-gate 1b's)
    hotwords: str = ""  # M8 G13: the map's own hot-word list (profx/hotwords.py --map; pinreport.py --map reads it)


def profile(mapname: str | None = None) -> MapProfile:
    m = (mapname or ACTIVE).upper()
    lo = m.lower()
    e1 = m == "E1M1"
    return MapProfile(map=m, wad="tests/fixtures/freedoom_%s.wad" % lo, prefix="doom_%s" % lo,
                      census="scratchpad/12m/_census_game%s.json.gz" % ("" if e1 else "_" + lo),
                      baseline="shipped" if e1 else "shipped_" + lo, scenarios="scenarios/%s" % lo,
                      heat="scratchpad/12m/heat_blocked27_p10.json.gz" if e1 else "scratchpad/12m/heat_%s.json.gz" % lo,
                      hotwords="scratchpad/12m/profx/hotwords_blocked27.json" if e1
                      else "scratchpad/12m/profx/hotwords_%s.json" % lo)


def heat_list(mapname: str | None = None, kind: str = "heat"):
    """M8 G13 (docs/level-pipeline.md 4): (repo-relative path, own) of the pin-heat list (`kind` "heat") or the hot
    words (`kind` "hotwords") a build / report on the map uses: the map's OWN when its profile has made one, else E1M1's
    -- whose keys are macro-expansion paths, map-free, which is how E1M2 shipped (`own` False says so; a tool prints
    it). Never another map's silently: E1M1's is the only fallback."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    own = getattr(profile(mapname), kind)
    if (root / own).exists():
        return own, True
    return getattr(profile("E1M1"), kind), False


def take_map_arg(argv=None, keep: bool = False) -> str:
    """M8: `--map E1Mn` (or `--map=E1Mn`) on a tool's command line selects the map exactly as DOOMFJ_MAP does -- it
    sets the environment (child processes inherit it) and `ACTIVE`. It must run BEFORE the tool imports `probe` or
    `gamespeed`, whose DEFAULT_WAD / DEFAULT_MAP are read at import: a map asked for after one of them was imported
    on another map is refused rather than half-applied. `keep` leaves the flag in `argv` (a tool whose own parser
    takes `--map`). -> the active map."""
    import sys
    global ACTIVE
    argv = sys.argv if argv is None else argv
    want = None
    for i, a in enumerate(list(argv)):
        if a == "--map" and i + 1 < len(argv):
            want, span = argv[i + 1], (i, i + 2)
            break
        if a.startswith("--map="):
            want, span = a.split("=", 1)[1], (i, i + 1)
            break
    if want is None:
        return ACTIVE
    want = want.upper()
    for name in ("probe", "gamespeed"):
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, "DEFAULT_MAP", want).upper() != want:
            raise SystemExit("--map %s: %s was imported on %s first -- pass the map before importing it (or set "
                             "DOOMFJ_MAP)" % (want, name, mod.DEFAULT_MAP))
    os.environ["DOOMFJ_MAP"] = want
    ACTIVE = want
    if not keep:
        del argv[span[0]:span[1]]
    return want


def check_checkout(tool_file) -> None:
    """M8 (the C3 agent's trap, 2026-10-19): the installed `doomfj` points at the MAIN repo, so a tool run in a worktree
    without PYTHONPATH=src imported the main repo's model and measured the wrong code. A tool calls this with its own
    `__file__`: its doomfj must be THIS checkout's src (the tool's checkout), else it refuses, naming both"""
    from pathlib import Path
    here = Path(__file__).resolve().parents[2]            # the checkout this doomfj comes from
    tool = Path(tool_file).resolve()
    root = next((p for p in tool.parents if (p / "src" / "doomfj").is_dir()), None)
    if root is not None and root != here:
        raise SystemExit("%s is %s's tool, but its doomfj is %s's (set PYTHONPATH=%s)"
                         % (tool.name, root, here, root / "src"))


def binary_map(fjm) -> str | None:
    """M8 (gates-ready): the map a binary's NAME says it is (build/doom_<map>_<x>.fjm: profile().prefix), or None for
    a name that names no map (the selftests' and older binaries: blocked62.fjm, padB.fjm ...)"""
    import re
    from pathlib import Path
    m = re.match(r"doom_(e\dm\d)_", Path(str(fjm)).name.lower())
    return m.group(1).upper() if m else None


def check_binary(fjm, mapname: str | None = None) -> None:
    """M8 (gates-ready): refuse a binary NAMED for another map than the one the tool measures (a gate run with
    --map E1M5 and E1M1's default binary measured E1M1 and called it E1M5's)"""
    want = (mapname or ACTIVE).upper()
    got = binary_map(fjm)
    if got is not None and got != want:
        raise SystemExit("%s is named for %s, but this run measures %s (--map / DOOMFJ_MAP)" % (fjm, got, want))


def scenario_dir(mapname: str | None = None):
    """the map's tracked scenario directory (gate roles, gamespeed's records), absolute"""
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / profile(mapname).scenarios
