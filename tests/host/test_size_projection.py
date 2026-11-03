"""M8 size: the survey's size rows (scripts/level_survey.py `size_estimate`, `_span_estimate`) -- the binary's words by
emitted region, measured exactly on blocked63 (E1M1) and e1m2_r4 (E1M2), each region scaled by its own driver, under
the map's MAP_SIZE_CONFIG cuts (PTLOC_SHARED, VPB_DIRECT).

CALIBRATION: at the shipped knobs (spread 1, the pool from word 2^26) the estimate must give E1M2 r4's real span,
92.06% of 2^27 (ship-gate 5), within one point. R9: the same check on a model with one driver's words dropped (the band
bank, 14.4M of E1M2's words) must FAIL -- a calibration a broken model passes calibrates nothing. And the lesson the rows
exist for: E1M7's main stream (code + wflip chains) is past the shipped pool base, with or without the cuts, and
without the cuts no layout fits it.
"""
import dataclasses
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")
E1M2_R4_SPAN = 123_567_424          # words (fjmsize / poolmap on build/doom_e1m2_r4.fjm)


@pytest.fixture(scope="module")
def ls():
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts" / "level_survey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wad(ls):
    return ls.WadFile.from_path(str(ASSET))


def _shipped_span(sv):
    main, pool = sv.size_estimate()
    return (1 << 26) + 1.87 * pool, main


def _row(sv, prefix):
    hits = [r for r in sv.rows if r[1].startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


def test_the_estimate_gives_e1m2_r4s_span(ls, wad):
    span, main = _shipped_span(ls.Survey(wad, "E1M2", wad))
    assert abs(span - E1M2_R4_SPAN) / (1 << 27) < 0.01, span
    assert abs(main - 53_319_790) / 53_319_790 < 0.01, main          # the main stream below the pool (poolmap SPLIT)


def test_control_a_model_without_the_band_bank_fails_the_calibration(ls, wad, monkeypatch):
    sv = ls.Survey(wad, "E1M2", wad)
    monkeypatch.setitem(sv.SIZE_DRIVERS, "vpb", (0, 0, 0, 0))
    span, main = _shipped_span(sv)
    assert not abs(main - 53_319_790) / 53_319_790 < 0.01, "the calibration passed a model missing 14.4M words"


def test_e1m7_main_stream_is_past_the_shipped_pool_base_and_fits_only_with_the_cuts(ls, wad):
    from doomfj.config import Config, map_cfg
    sv = ls.Survey(wad, "E1M7", wad)
    sv._span_estimate()
    assert _row(sv, "main stream")[0] == "WARN"                        # > 2^26 words even with the cuts
    assert _row(sv, "address span")[4] != "none fits"
    main, pool = sv.size_estimate(dataclasses.replace(map_cfg(Config(), "E1M7"), PTLOC_SHARED=0, VPB_DIRECT=0))
    assert main * 1.01 + 1.11 * pool > (1 << 27), "without the cuts E1M7 fits nowhere (the control for the cuts)"
