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


def profile(mapname: str | None = None) -> MapProfile:
    m = (mapname or ACTIVE).upper()
    lo = m.lower()
    e1 = m == "E1M1"
    return MapProfile(map=m, wad="tests/fixtures/freedoom_%s.wad" % lo, prefix="doom_%s" % lo,
                      census="scratchpad/12m/_census_game%s.json.gz" % ("" if e1 else "_" + lo),
                      baseline="shipped" if e1 else "shipped_" + lo, scenarios="scenarios/%s" % lo)


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


def scenario_dir(mapname: str | None = None):
    """the map's tracked scenario directory (gate roles, gamespeed's records), absolute"""
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / profile(mapname).scenarios
