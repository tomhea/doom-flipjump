"""M8 (docs/level-pipeline.md 2): `scripts/level_survey.py` -- the map survey quoted as the plan for E1M2..E1M9.

R9: a tool used as evidence ships its negative control. The shipped map E1M1 must survey CLEAN (no REFUSED / OVER /
ERROR / WRONG / MISSING row); E1M2 must show the blockers it is known to have (measured 2026-10-16); and the CONTROL
removes a thing type E1M1 uses from the model's own table, which the survey must report as a refusal -- so a survey
that checks nothing cannot pass.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")

BAD = ("REFUSED", "OVER", "ERROR", "WRONG", "MISSING")


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


def test_the_shipped_map_surveys_clean(ls, wad):
    bad = [r for r in _rows(ls, wad, "E1M1") if r[0] in BAD]
    assert bad == []


def test_e1m2_shows_its_known_blockers(ls, wad):
    rows = _rows(ls, wad, "E1M2")
    got = {(r[0], r[1].split(" (")[0]) for r in rows}
    # M8 F1.1 (docs/f1-big-map-widths.md 2-4): aim_sid's width, three-digit counts and the far LOS's 128 pieces made
    # these OK on E1M2 (they were OVER / REFUSED before it)
    assert ("OK", "monsters + barrels -> aim_sid") in got                # 138 <= 255, aim_sid 8 bits
    assert not any("check_world" in r[1] for r in rows)                  # the guard adds a row only when it refuses
    assert ("OK", "map extent, far LOS") in got                          # 4,952 <= 128 * 127
    assert ("OVER", "drawable things, every skill") in got               # 305 >= 256 (F1.4's slot cap)
    assert ("OK", "solid decorations some skill lacks") in got     # M8 F1.2: mc_don at NEW GAME
    assert ("INFO", "line special 48 scrolling wall") in got             # a decided simplification
    assert ("OK", "line special 97 WR teleport") in got                 # M8 L4: doomfj.teleport
    # M8 L2: the yellow / red doors (27 / 28) and every other E1M2 door special are implemented (doomfj.doors)
    assert not any(r[0] in ("WRONG", "MISSING") and "door" in r[1] for r in rows)
    assert ("OK", "line special 27 DR yellow door") in got and ("OK", "line special 109 W1 blaze open stay") in got


def test_control_a_thing_type_removed_from_the_model_is_refused(ls, wad, monkeypatch):
    """E1M1's imps (3001) dropped from gamedata.THING_TYPES: World refuses the map and the survey says so"""
    types = dict(ls.gd.THING_TYPES)
    del types[3001]
    monkeypatch.setattr(ls.gd, "THING_TYPES", types)
    rows = _rows(ls, wad, "E1M1")
    assert any(r[0] == "REFUSED" and r[1] == "World(strict=True) builds" and "3001" in r[4] for r in rows)
    assert any(r[0] == "MISSING" and r[1] == "thing type 3001" for r in rows)


C7 = (22, 30, 31, 32, 36, 42, 44, 45, 46, 53, 55, 56, 57, 59, 62, 63)      # M8 C7: the decorations E1M5..E1M9 add


def test_c7_the_decorations_survey_drawn_and_e1m9_hangs_its_bodies_from_still_sectors(ls, wad):
    """M8 C7: no C7 type is MISSING on the maps that have them; each is drawn (OK, not the WARN of an undrawn type);
    E1M9's 16 hanging bodies (4 of them type 60) stand in sectors that never move"""
    for m in ("E1M5", "E1M7", "E1M8", "E1M9"):
        rows = _rows(ls, wad, m)
        assert not any(r[1] == "thing type %d" % ty for r in rows for ty in C7), m
        for ty in C7:
            mine = [r for r in rows if r[1].startswith("thing %d " % ty)]
            assert all(r[0] == "OK" for r in mine), (m, mine)
    rows = _rows(ls, wad, "E1M9")
    assert ("OK", "hanging things on still sectors", "16") in {r[:3] for r in rows}


def test_c7_control_a_hanging_body_on_a_door_is_refused(ls, wad, monkeypatch):
    """the gore room of E1M9 (sector 250) made a door sector: the survey refuses its hanging bodies, as the emitter"""
    from doomfj import doors
    real = doors.door_states
    monkeypatch.setattr(doors, "door_states", lambda secs, lds, sds, *a, **k: {**real(secs, lds, sds, *a, **k),
                                                                             250: [0, 64]})
    rows = _rows(ls, wad, "E1M9")
    assert any(r[0] == "REFUSED" and r[1] == "hanging things on a moving sector" and r[2] == "14" for r in rows)


def test_c7_an_undrawn_decoration_is_reported(ls, wad):
    """E1M1's corpses, its hanging body 60 and its impaled body 26 (MF_SOLID: an invisible blocker) have no picture in
    reference_model.THING_SPRITE: the survey says so (WARN), so a new map's undrawn types are seen"""
    rows = _rows(ls, wad, "E1M1")
    warn = {r[1].split()[1] for r in rows if r[0] == "WARN" and r[4].startswith("NOT DRAWN")}
    assert {"26", "60", "15", "18"} <= warn
    assert any(r[1].startswith("thing 26 ") and "BLOCKER" in r[4] for r in rows)
