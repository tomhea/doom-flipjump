"""M8 F1.3 item 5 (docs/f1-big-map-widths.md 5): a lift with more than 16 stops at the doors' quant takes the least
coarser quant of its own (`movers.lift_quant`), so its 4-bit state still holds it.

  * E1M1's lifts keep quant 16 and their stops exactly (a frozen literal: their binary is unchanged);
  * E1M3's lift 84 (19 stops at 16) and E1M4's lift 33 (17) fit in 16 at the LEAST quant that does;
  * CONTROL: forcing quant 16 on E1M3's lift 84 is refused by lift_states' assert, not wrapped.
"""
from pathlib import Path

import pytest

from doomfj import movers
from doomfj.doors import MAX_STATES, stops
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"


def _map(wad, m):
    return wad.sectors(m), wad.linedefs(m), wad.sidedefs(m)


def test_e1m1s_lifts_are_unchanged():
    w = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    secs, lds, sds = _map(w, "E1M1")
    for si, (low, high) in movers.lift_sectors(secs, lds, sds).items():
        assert movers.lift_quant(low, high) == 16
    ls = movers.lift_states(secs, lds, sds)
    assert ls == {si: stops(lo, hi, 16)[::-1] for si, (lo, hi) in movers.lift_sectors(secs, lds, sds).items()}
    assert {si: len(v) for si, v in ls.items()} == {98: 10, 103: 10}


def test_the_least_quant_that_fits():
    for low, high in ((0, 288), (-40, 256), (8, 240), (0, 64)):
        q = movers.lift_quant(low, high)
        assert len(stops(low, high, q)) <= MAX_STATES
        assert q == 16 or len(stops(low, high, q - 1)) > MAX_STATES, (low, high, q)


@pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad")
@pytest.mark.parametrize("m,si,q", [("E1M3", 84, 20), ("E1M4", 33, 18)])
def test_a_long_lift_takes_a_coarser_quant(m, si, q):
    w = WadFile.from_path(str(ASSET))
    secs, lds, sds = _map(w, m)
    low, high = movers.lift_sectors(secs, lds, sds)[si]
    assert len(stops(low, high, 16)) > MAX_STATES, "the lift fits at 16: the case is not exercised"
    assert movers.lift_quant(low, high) == q
    assert len(movers.lift_states(secs, lds, sds)[si]) <= MAX_STATES


@pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad")
def test_control_quant_16_on_a_long_lift_is_refused(monkeypatch):
    w = WadFile.from_path(str(ASSET))
    secs, lds, sds = _map(w, "E1M3")
    monkeypatch.setattr(movers, "lift_quant", lambda low, high, base=16: 16)
    with pytest.raises(AssertionError, match="stops at quant 16"):
        movers.lift_states(secs, lds, sds)
