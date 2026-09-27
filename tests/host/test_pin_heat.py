"""Pin protection (M7 P1.1, docs/gp-pin-protection.md): the shipped build's heat list still fits the
program.

The shipped binary is built with `build_blocked.py --pin-heat scratchpad/12m/heat_blocked27.json.gz`
(docs/ship-gate.md section 1b): flipjump's BlockPool places the list's hot groups first, pins them,
and gives their hottest tables the cheapest indices. The list names groups and table sites by
their macro-expansion paths, so a program change can leave it stale: a hot group can vanish, or
start sharing its key with another group, and a build would then protect nothing for it -- quietly,
since the pool only reports it. This checks the list against the TRACKED counts cache through
flipjump's own BlockPool, with the ship gate's knobs: every hot group matched exactly once, placed,
and pinned.
"""
import gzip
import json
import re
from pathlib import Path

from flipjump.assembler.preprocessor import BlockPool

ROOT = Path(__file__).resolve().parents[2]
HEAT = ROOT / "scratchpad" / "12m" / "heat_blocked27.json.gz"
COUNTS = ROOT / "scratchpad" / "12m" / "_counts_game.json.gz"
# docs/ship-gate.md section 1b's knobs (the ones that enter placement)
KNOBS = dict(span_bits=0x9FFFFFE0, spread=2, spread_min_count=256, max_slot_ops=512, width_buckets=True)
POOL_BASE = 0x60000000


def _pool(heat):
    with gzip.open(COUNTS, "rt", encoding="utf-8") as fh:
        c = json.load(fh)
    hist = {g: {int(w): n for w, n in h.items()} for g, h in c["width_hist"].items()}
    return BlockPool(32, POOL_BASE, counts=c["counts"], widths={g: int(w) for g, w in c["widths"].items()},
                     alias=c.get("alias") or {}, width_hist=hist, heat=heat, **KNOBS)


def test_the_shipped_heat_list_fits_the_program():
    with gzip.open(HEAT, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    heat = {g: [tuple(s) for s in sites] for g, sites in doc["groups"].items()}
    assert len(heat) == 20 and all(heat.values()), "20 hot groups, each with its hot sites"
    pool = _pool(heat)
    report = pool.heat_report()
    assert report["hot_groups"] == 20, report                    # none missing, none ambiguous
    assert report["hot_groups_missing"] == report["hot_groups_ambiguous"] == 0, report
    assert set(pool.hot_sites) <= set(pool.groups)             # placed (a lost hot group raises)
    first = sorted(pool.groups[g][0] for g in pool.hot_sites)
    rest = min(b for g, (b, _e) in pool.groups.items() if g not in pool.hot_sites)
    assert max(first) < rest, "the hot groups are placed first"


def test_the_ship_gate_builds_with_the_heat_list():
    text = (ROOT / "docs" / "ship-gate.md").read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.startswith("python scratchpad/12m/build_labeled.py")]
    assert lines and all(re.search(r"--pin-heat scratchpad/12m/heat_blocked27\.json\.gz\b", l)
                         for l in lines), lines
