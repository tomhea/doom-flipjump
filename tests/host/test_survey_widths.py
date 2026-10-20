"""M8 C11: the survey's width rows that the World's refusals used to hide or that went stale.

* "monster slots + barrels, every skill, from the WAD": the slot ids (dm_id, aim_sid, mon_target / bar_src, p_atk)
  are bytes in fj; the World row only runs when the World builds, and on E1M6 / E1M7 it refuses first (unknown
  thing types, byte thing lists) -- so the WAD's count is a row of its own. E1M7: 289 monsters of every skill (8 lost
  souls gamedata lacks among them) + 16 barrels = 305 > 254.
* "drawable things, every skill (1-byte fragment slot id)": since F1.4 a map with a per-frame SPR_SLOT_CAP is bounded
  by construction (wall_renderer.check_slot_ids, the emitter's own assert); the row read OVER on E1M2 regardless.

R9: the lost souls left out of DOOM_MONSTERS drop E1M7's count by 8 (the unknown monster types ARE counted); E1M7
without its SPR_SLOT_CAP reads OVER.
"""
import importlib.util
from pathlib import Path

import pytest

from doomfj import config as C
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FULL_WAD = ROOT / "assets/freedoom1.wad"
pytestmark = pytest.mark.skipif(not FULL_WAD.exists(), reason="the full episode wad is not present")
SLOTS = "monster slots + barrels, every skill, from the WAD"
DRAW = "drawable things, every skill (1-byte fragment slot id)"


@pytest.fixture(scope="module")
def ls():
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts/level_survey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wad():
    return WadFile.from_path(str(FULL_WAD))


def _rows(ls, wad, m, section, name):
    s = ls.Survey(wad, m, wad)
    getattr(s, section)()
    return [(r[0], r[2]) for r in s.rows if r[1].startswith(name)]


@pytest.mark.parametrize("m, want", [("E1M2", ("OK", "138")), ("E1M6", ("OVER", "301")), ("E1M7", ("OVER", "305"))])
def test_monster_slots_from_the_wad(ls, wad, m, want):
    assert _rows(ls, wad, m, "things", SLOTS) == [want]


def test_control_the_unknown_monsters_are_counted(ls, wad, monkeypatch):
    monkeypatch.setattr(ls, "DOOM_MONSTERS", ls.DOOM_MONSTERS - {3006})
    assert _rows(ls, wad, "E1M7", "things", SLOTS) == [("OVER", "297")]


def test_the_slot_cap_row_takes_the_maps_cap(ls, wad, monkeypatch):
    assert [st for st, _v in _rows(ls, wad, "E1M7", "render_caps", DRAW)] == ["OK"]
    monkeypatch.setitem(C.MAP_CONFIG, "E1M7", dict(C.MAP_CONFIG["E1M7"], SPR_SLOT_CAP=0))
    assert _rows(ls, wad, "E1M7", "render_caps", DRAW) == [("OVER", "614")]          # R9 (606 before C7 drew its decor)
