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
