"""M8 C11 (E1M7): the deg attribution budget's width per map -- the model half (the fj half is
tests/fj/test_tsv_budget_fj.py).

E1M7 marks 4,183 two-sided segs, past the 3-nibble `n_tsv` counter's 4,095 (DEG_PNEAR). A map's counter is
`Config.TSV_NIBBLES` wide (MAP_CONFIG; E1M7 4) and the budget `Config.TSV_BUDGET` = 16^n - 1, shared by the emitter
(`n_tsv`'s declaration, the macro's budget, `_assert_pnear_unbound`) and the oracle (`render_wall_frame`'s default
`deg_mark`, read through `map_cfg(cfg, scene.mapname)` as SPR_SLOT_CAP is). E1M1 / E1M2 keep 3 nibbles: their
emitted text is unchanged.

R9: a budget that BINDS must change the oracle's picture (else the oracle is not reading the map's budget at all) --
E1M1 with TSV_NIBBLES 1 (budget 15) at the spawn differs; 4 and 2 (65,535 / 255: never reached there) are identical;
the emitter's never-binds assert refuses E1M7 at 3 nibbles and a budget that is not a whole counter's max.
"""
from pathlib import Path

import pytest

from doomfj import config as C
from doomfj.config import Config, map_cfg
from doomfj.reference_model import DEG_PNEAR, ReferenceModel, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import _assert_pnear_unbound

ROOT = Path(__file__).resolve().parents[2]
E1M1 = ROOT / "tests/fixtures/freedoom_e1m1.wad"
FULL_WAD = ROOT / "assets/freedoom1.wad"
RENDER = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True, near_steps=True,
              stack_steps=True, degrade=True)
E1M7_MARKING = 4183        # tests/host/test_marking_seg_bound.py EXPECT (every door state)


def test_the_default_is_deg_pnear():
    assert Config().TSV_NIBBLES == 3 and Config().TSV_BUDGET == DEG_PNEAR == 4095
    for m in ("E1M1", "E1M2"):
        assert map_cfg(Config(), m).TSV_NIBBLES == 3, m
    assert map_cfg(Config(), "E1M7").TSV_BUDGET == 0xFFFF


def test_the_never_binds_assert_takes_the_maps_budget():
    assert _assert_pnear_unbound(E1M7_MARKING, map_cfg(Config(), "E1M7").TSV_BUDGET) == ""
    assert _assert_pnear_unbound(4094) == "" and _assert_pnear_unbound(4094, 4095) == ""
    with pytest.raises(AssertionError, match="TSV_NIBBLES"):          # R9: E1M7 at E1M1's width
        _assert_pnear_unbound(E1M7_MARKING, Config().TSV_BUDGET)
    with pytest.raises(AssertionError, match="whole counter"):        # R9: 5000 is no counter's max
        _assert_pnear_unbound(10, 5000)


@pytest.fixture(scope="module")
def spawn():
    mw = WadFile.from_path(str(E1M1))
    return mw, build_scene(mw, mw, "E1M1"), spawn_state(mw, "E1M1")


def _frame(spawn, monkeypatch, nib):
    mw, scene, st = spawn
    if nib is not None:
        monkeypatch.setitem(C.MAP_CONFIG, "E1M1", dict(C.MAP_CONFIG.get("E1M1", {}), TSV_NIBBLES=nib))
    return ReferenceModel(Config()).render_wall_frame(st, scene, **RENDER)


def test_the_oracle_takes_the_maps_budget(spawn, monkeypatch):
    base = _frame(spawn, monkeypatch, None)
    assert _frame(spawn, monkeypatch, 4) == base and _frame(spawn, monkeypatch, 2) == base
    binding = _frame(spawn, monkeypatch, 1)
    assert binding != base, "R9: a 15-seg budget must bind at the spawn -- else the oracle ignores the map's width"
    assert sum(a != b for a, b in zip(binding, base)) > 1000


@pytest.mark.skipif(not FULL_WAD.exists(), reason="the full episode wad is not present")
def test_the_survey_row(monkeypatch):
    """level_survey's n_tsv row reads the map's width: E1M7 OK at 4 nibbles, OVER at E1M1's 3 (R9)"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts/level_survey.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)

    def row(over):
        if over is not None:
            monkeypatch.setitem(C.MAP_CONFIG, "E1M7", dict(C.MAP_CONFIG["E1M7"], TSV_NIBBLES=over))
        s = ls.Survey(WadFile.from_path(str(FULL_WAD)), "E1M7", WadFile.from_path(str(FULL_WAD)))
        from doomfj import wall_renderer as WR
        from doomfj.mapcompiler import bake_bsp
        s._marking(WR, bake_bsp(s.wad, "E1M7"))
        return [r for r in s.rows if "n_tsv" in r[1]]
    ok = row(None)
    assert [(r[0], r[2]) for r in ok] == [("OK", str(E1M7_MARKING))], ok
    bad = row(3)
    assert [(r[0], r[2]) for r in bad] == [("OVER", str(E1M7_MARKING))], bad
