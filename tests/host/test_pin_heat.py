"""Pin protection (M7 P1.1, docs/gp-pin-protection.md): the shipped build's heat list still fits the
program.

The shipped binary is built with `build_blocked.py --pin-heat <list>` (docs/ship-gate.md section
1b): flipjump's BlockPool places the list's hot groups first and gives their hottest tables the
cheapest indices. The list names groups and table sites by their macro-expansion paths, so a program
change can leave it stale: a hot group can vanish, or start sharing its key with another group, and a
build would then protect nothing for it -- quietly, since the pool only reports it. This checks the
list against the TRACKED counts cache through flipjump's own BlockPool, with the placement knobs,
the heat list and the counts cache all READ FROM the recorded build command, so the command and this
test cannot drift apart: every hot group is matched exactly once, placed, and placed ahead of every
other group.

What it does NOT check is that the hot words stay PINNED in the built binary: that is settled while
the program assembles, and a counts cache cannot show it. `scratchpad/12m/pinreport.py` reads it off
a binary (the shipped one's report: docs/ship-evidence/blocked28_pinreport.log).

Each check has its control (R9): a heat key the program lacks is reported missing, and the same pool
built WITHOUT the list does not put those groups first.
"""
import gzip
import json
import re
from pathlib import Path

import pytest
from flipjump.assembler.preprocessor import BlockPool

from doomfj.harness import W

ROOT = Path(__file__).resolve().parents[2]


def _knobs(cmd):
    def val(flag, conv=str):
        found = re.findall(rf"{flag} (\S+)", cmd)
        assert len(found) == 1, f"{flag} appears {len(found)} times in the recorded command {cmd!r}"
        return conv(found[0])
    return dict(pool_base=val("--pool-base", lambda s: int(s, 0)),
                span_bits=val("--span-bits", lambda s: int(s, 0)),
                spread=val("--spread", int), spread_min_count=val("--spread-min-count", int),
                max_slot_ops=val("--max-slot-ops", int),
                width_buckets=bool(re.search(r"--width-buckets\b", cmd)),
                evict_by_value=bool(re.search(r"--evict-by-value\b", cmd)),
                heat=val("--pin-heat"), counts=val("--counts-cache"))


@pytest.fixture(scope="module")
def shipped():
    """docs/ship-gate.md 1b's game build line(s), which must agree on every knob read here"""
    text = (ROOT / "docs" / "ship-gate.md").read_text(encoding="utf-8")
    cmds = [line for line in text.splitlines()
            if line.startswith("python scratchpad/12m/build_labeled.py") and " game " in line]
    assert cmds, "docs/ship-gate.md 1b no longer records the build_labeled.py game command"
    knobs = [_knobs(c) for c in cmds]
    assert all(k == knobs[0] for k in knobs), f"the recorded build commands disagree: {knobs}"
    return knobs[0]


@pytest.fixture(scope="module")
def heat(shipped):
    with gzip.open(ROOT / shipped["heat"], "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    return {g: [tuple(s) for s in sites] for g, sites in doc["groups"].items()}


def _pool(k, heat):
    with gzip.open(ROOT / k["counts"], "rt", encoding="utf-8") as fh:
        c = json.load(fh)
    return BlockPool(W, k["pool_base"], counts=c["counts"],
                     widths={g: int(w) for g, w in c["widths"].items()},
                     width_hist={g: {int(w): int(n) for w, n in h.items()} for g, h in c["width_hist"].items()},
                     alias=c.get("alias") or {}, span_bits=k["span_bits"], spread=k["spread"],
                     spread_min_count=k["spread_min_count"], max_slot_ops=k["max_slot_ops"],
                     width_buckets=k["width_buckets"], evict_by_value=k["evict_by_value"],
                     **({"heat": heat} if heat is not None else {}))


def _placed_first(pool, groups):
    first = [pool.groups[g][0] for g in groups]
    rest = [b for g, (b, _e) in pool.groups.items() if g not in groups]
    return max(first) < min(rest)


def test_the_shipped_heat_list_fits_the_program(shipped, heat):
    assert heat and all(heat.values()), "a heat list, each group with its hot sites"
    pool = _pool(shipped, heat)
    report = pool.heat_report()
    assert report["hot_groups_missing"] == report["hot_groups_ambiguous"] == 0, report
    assert report["hot_groups"] == len(heat), report            # every listed group matched once
    assert set(pool.hot_sites) <= set(pool.groups)             # placed (a lost hot group raises)
    assert _placed_first(pool, set(pool.hot_sites)), "the hot groups are placed first"


def test_the_checks_can_fail(shipped, heat):
    """R9: a key the program lacks is reported, and without the list the same groups are NOT first"""
    stale = dict(heat)
    stale["no.such.group"] = next(iter(heat.values()))
    assert _pool(shipped, stale).heat_report()["hot_groups_missing"] == 1
    hot = set(_pool(shipped, heat).hot_sites)
    assert not _placed_first(_pool(shipped, None), hot), \
        "the hot groups come first even without the list -- the placement check proves nothing"


def test_poolmap_prices_the_shipped_heat_list(shipped):
    """poolmap.py's default knobs are ship-gate 1b's; its heat list must be the one 1b builds with"""
    src = (ROOT / "scratchpad" / "12m" / "poolmap.py").read_text(encoding="utf-8")
    m = re.search(r'SHIP_GATE = dict\([^)]*heat="([^"]+)"', src, re.S)
    assert m, "poolmap.py's SHIP_GATE no longer names the heat list"
    assert m.group(1) == shipped["heat"]
