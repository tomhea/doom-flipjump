"""M8 C6 (the gates' mirror on a map with the timed powers): `MonsterPhase.weapon` -- the gates' copy of the player
phase's counters (p2a_gate.Mirror, the playthrough gate) -- counts the powers down as `combat._player_phase` does
(`_power_tic`, after the strength, before the damage and bonus fades). E1M9's playthrough found the copy without it: a
suit taken on world frame 3236 stayed at 2100 in the mirror while the binary (and DOOM's P_PlayerThink) ticked it
to 2099 on the next frame."""
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import powers as P
from doomfj.monsters import MonsterPhase
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
WAD = ROOT / "assets" / "freedoom1.wad"
needs_wad = pytest.mark.skipif(not WAD.exists(), reason="needs assets/freedoom1.wad (E1M9: both powers)")
WANT = (P.TICS[P.INVIS_TYPE] - 1, P.TICS[P.SUIT_TYPE] - 1, gd.BONUSADD - 1)


def _phase():
    ph = MonsterPhase(WadFile.from_path(str(WAD)), "E1M9", gd.SK_EASY, mode="final", player="final")
    assert set(ph.world.powers) == {P.INVIS_TYPE, P.SUIT_TYPE}
    return ph


def _one_frame(ph):
    ws = ph.world.ws
    ws.p_invis, ws.p_ironfeet, ws.p_bonuscount = P.TICS[P.INVIS_TYPE], P.TICS[P.SUIT_TYPE], gd.BONUSADD
    ph.weapon({}, dead=0)
    return ws.p_invis, ws.p_ironfeet, ws.p_bonuscount


@needs_wad
def test_the_mirror_counts_the_powers_down():
    assert _one_frame(_phase()) == WANT


@needs_wad
def test_control_a_mirror_without_the_countdown_is_caught(monkeypatch):
    """R9: the mirror as it was (no `_power_tic`) must fail the assertion above"""
    ph = _phase()
    monkeypatch.setattr(type(ph.world), "_power_tic", lambda self: None)
    assert _one_frame(ph) != WANT
