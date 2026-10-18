"""M8 C5 / C9 / C10: the survey's rows for the monster-only teleports (126, 125), the exits (51, 52) and a map with no
barrel -- each read from the model's own functions (scripts/level_survey.py), each with a negative control (R9) that
moves the model and must move the row.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")


def _survey_module():
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts" / "level_survey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ls():
    return _survey_module()


@pytest.fixture(scope="module")
def wad(ls):
    return ls.WadFile.from_path(str(ASSET))


def _rows(ls, wad, m):
    return ls.Survey(wad, m, wad).run().rows


def _row(rows, check):
    got = [r for r in rows if r[1].startswith(check)]
    assert len(got) <= 1, got
    return got[0] if got else None


# ---- C5: the monster-only teleports -----------------------------------------------------------------------------------
@pytest.mark.parametrize("m,special", [("E1M4", 126), ("E1M5", 126), ("E1M6", 126), ("E1M7", 125)])
def test_the_monster_teleports_are_supported(ls, wad, m, special):
    rows = _rows(ls, wad, m)
    r = _row(rows, "line special %d " % special)
    assert r[0] == "OK" and "monsters only" in r[4], r
    assert _row(rows, "teleport lines baked")[0] == "OK"
    assert _row(rows, "teleport lines (teleport.teleporters") is None          # the guard adds a row only on refusal


def test_e1m5s_hard_only_destination_is_named(ls, wad):
    rows = _rows(ls, wad, "E1M5")
    assert _row(rows, "teleport destinations some skill lacks")[2] == "[(633, 4)]"
    assert _row(rows, "teleport lines baked")[2] == "0 / 1 / 0"
    assert _row(_rows(ls, wad, "E1M7"), "teleport lines baked")[2] == "3 / 4 / 4"


def test_control_a_player_line_some_skill_lacks_is_refused(ls, wad, monkeypatch):
    """R9: E1M5's 126 read as a PLAYER line (MONSTER_ONLY_SPECIALS emptied) -- its hard-only destination is refused"""
    from doomfj import teleport
    monkeypatch.setattr(teleport, "MONSTER_ONLY_SPECIALS", frozenset())
    r = _row(_rows(ls, wad, "E1M5"), "teleport lines (teleport.teleporters")
    assert r is not None and r[0] == "REFUSED" and "every single-player skill" in r[4], r
