"""M4 — `doomfj.mapprefix`, which gives one map's generated labels a private namespace.

Three levels in one image is three emissions concatenated, and fj top-level labels are GLOBAL. The
module's own `selftest()` carries the R9 controls; this runs it, and adds the properties that only
make sense against real emitted text.
"""
from pathlib import Path

import pytest

from doomfj.mapprefix import FAMILIES, apply, count, selftest

GEN = Path("build/generated_std")


def test_the_module_selftest_passes(capsys):
    assert selftest() == 0
    out = capsys.readouterr().out
    assert "SELFTEST: PASS" in out
    assert out.count("ok") >= 6, out


def test_an_empty_prefix_is_the_identity_on_a_real_emission():
    """THE property that makes this opt-in: with no prefix the emitted text is untouched, so
    single-level builds stay byte-identical and every existing certification transfers."""
    files = sorted(GEN.glob("e1m1_0*.fj"))
    if not files:
        pytest.skip("no emitted program on disk (build/generated_std)")
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        assert apply(text, "") == text, f.name


def test_it_touches_the_parts_that_carry_map_geometry():
    """A prefixer that renamed nothing would pass the identity test above and be useless."""
    files = sorted(GEN.glob("e1m1_0*.fj"))
    if not files:
        pytest.skip("no emitted program on disk (build/generated_std)")
    per_file = {f.name: count(f.read_text(encoding="utf-8", errors="replace")) for f in files}
    assert sum(per_file.values()) > 10_000, per_file
    # the per-seg constants and the BSP-as-code walk are where map geometry lives
    assert per_file.get("e1m1_03_segconsts.fj", 0) > 0
    assert per_file.get("e1m1_04_walk.fj", 0) > 0


@pytest.mark.parametrize("name", ["ptloc_walk", "ptloc_ret", "seg_pid", "seg_ret", "vpb_t900",
                                  "seg_pass1_leaf", "bbgate_leaf", "e1m1_bspcode_node4"])
def test_shared_and_extern_names_are_never_renamed(name):
    """`src/fj/sim.fj` externs some of these BY NAME, and the bands bank is ID-indexed so several
    maps merge into it. Renaming any of them would break the program, not namespace it."""
    assert apply(name, "m2_") == name


@pytest.mark.parametrize("name", ["ss12_visit", "ss3_seg9_marked", "seg7_geom_consts",
                                  "seg120_face_consts", "ptloc_l17", "thing9_2_consts",
                                  "bbmiss4", "bbgo11"])
def test_every_family_is_actually_covered(name):
    assert apply(name, "m2_") == "m2_" + name


def test_the_family_list_is_not_secretly_empty():
    assert len(FAMILIES) == 5
