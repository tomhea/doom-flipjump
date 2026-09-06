"""`wall_renderer.marking_seg_count` -- the bound the deg attribution budget is proved against.

`_assert_pnear_unbound` used `len(cmap.segs)`, which is over-conservative by 2-3x: only MARKING
two-sided segs reach `seg_pass1_ts_leaf`, because it is called solely from `ss<c>_seg<s>_mark`
blocks and one-sided segs never emit one. Each seg belongs to exactly one subsector and the BSP
walk visits a subsector at most once per frame, so the marking count is a hard per-frame ceiling
on `n_tsv`.

That over-conservatism was not free: it rejected E1M6 (4,409 segs) from a nine-level image while
its real marking count is 2,550 -- 1,545 BELOW the 3-nibble counter's 4,095.

⚠ Tightening it moves NOT ONE BYTE of the emitted program: `_assert_pnear_unbound` returns "".
"""
from pathlib import Path

import pytest

from doomfj.doors import door_states, heights_for_states
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import apply_sector_heights
from doomfj.wad import WadFile
from doomfj.wall_renderer import DEG_PNEAR, marking_seg_count, seg_marks_in

FULL_WAD = Path("assets/freedoom1.wad")
E1 = ["E1M%d" % i for i in range(1, 10)]

# MEASURED 2026-08-31 over every door state of every map.
EXPECT = {"E1M1": 1445, "E1M2": 2242, "E1M3": 1300, "E1M4": 2036, "E1M5": 1251,
          "E1M6": 2550, "E1M7": 4183, "E1M8": 1284, "E1M9": 2051}


@pytest.fixture(scope="module")
def wad():
    if not FULL_WAD.exists():
        pytest.skip("the full episode wad is not present")
    return WadFile.from_path(str(FULL_WAD))


def _marks(wad, m):
    """The emitter's own `_seg_marks`: a seg marks if it marks in ANY door state."""
    lds, sds, secs = wad.linedefs(m), wad.sidedefs(m), wad.sectors(m)
    variants = [secs]
    for si, stops in door_states(secs, lds, sds).items():
        for k in range(len(stops)):
            variants.append(apply_sector_heights(
                secs, heights_for_states(secs, lds, sds, {si: k})))
    return lambda seg: any(seg_marks_in(lds, sds, seg, v) for v in variants)


@pytest.mark.parametrize("m", E1)
def test_marking_counts_are_what_the_bound_claims(wad, m):
    cmap = bake_bsp(wad, m)
    assert marking_seg_count(cmap, wad.linedefs(m), _marks(wad, m)) == EXPECT[m]


@pytest.mark.parametrize("m", E1)
def test_marking_is_never_more_than_the_total(wad, m):
    """The bound must be SOUND: a tighter number that could exceed the old one would be a
    regression dressed as an optimisation."""
    cmap = bake_bsp(wad, m)
    assert marking_seg_count(cmap, wad.linedefs(m), _marks(wad, m)) <= len(cmap.segs)


def test_one_sided_segs_never_count(wad):
    """WHY the bound is tighter: the ts leaf is reached only from a two-sided seg's `_mark` block.
    `seg_marks_in` returns True for a one-sided seg (it always marks its own planes), so the
    one-sided exclusion has to live in the COUNT, not in the predicate -- and if it moved into the
    predicate this test would catch it."""
    m = "E1M1"
    lds, sds, secs = wad.linedefs(m), wad.sidedefs(m), wad.sectors(m)
    one_sided = [s for s in bake_bsp(wad, m).segs if lds[s.linedef].back == -1]
    assert one_sided, "E1M1 has one-sided segs; if not, this test proves nothing"
    assert all(seg_marks_in(lds, sds, s, secs) for s in one_sided)


def test_the_tighter_bound_is_what_admits_e1m6(wad):
    """THE POINT OF THE CHANGE, stated as a control. Under the old `len(cmap.segs)` bound E1M6 and
    E1M7 are both rejected; under the real one only E1M7 is, and by 88."""
    got = {}
    for m in ("E1M6", "E1M7"):
        cmap = bake_bsp(wad, m)
        got[m] = (len(cmap.segs), marking_seg_count(cmap, wad.linedefs(m), _marks(wad, m)))
    assert got["E1M6"][0] >= DEG_PNEAR, "the OLD bound must reject E1M6, or nothing was fixed"
    assert got["E1M6"][1] < DEG_PNEAR, "the NEW bound must admit E1M6"
    assert got["E1M7"][0] >= DEG_PNEAR and got["E1M7"][1] >= DEG_PNEAR, (
        "E1M7 is over on both bounds -- if that ever stops being true, say so in the handoff")


def test_every_other_e1_map_fits_the_counter(wad):
    for m in E1:
        if m == "E1M7":
            continue
        cmap = bake_bsp(wad, m)
        n = marking_seg_count(cmap, wad.linedefs(m), _marks(wad, m))
        assert n < DEG_PNEAR <= 4095, (m, n)
