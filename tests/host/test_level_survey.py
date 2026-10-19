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


def test_a_pickup_without_a_sprite_is_missing(ls, wad, monkeypatch):
    """M8 (gates-ready): E1M8's cell pack (17) has a give but no sprite -- every gate's views KeyError on it; the survey
    names it. CONTROL: on E1M1, a pickup it uses (the clip, 2007) taken out of THING_SPRITE turns MISSING too"""
    rows = _rows(ls, wad, "E1M8")
    assert any(r[0] == "MISSING" and r[1].startswith("thing 17 ") and "sprite NO" in r[4] for r in rows), (
        [r for r in rows if r[1].startswith("thing 17")])
    import doomfj.reference_model as RM
    monkeypatch.setattr(RM, "THING_SPRITE", {k: v for k, v in RM.THING_SPRITE.items() if k != 2007})
    bad = [r for r in _rows(ls, wad, "E1M1") if r[0] == "MISSING"]
    assert any(r[1].startswith("thing 2007 ") and "sprite NO" in r[4] for r in bad), bad


def test_weapon_light_rows(ls, wad, monkeypatch):
    """M8 (gates-ready): the weapon is lit by ONE baked colormap row (hudcode); E1M9 has a sector dark enough for a
    second -- REFUSED by the survey (it refused every game-tier tool at hud.GameScreen). CONTROL: E1M1 is OK, and a
    sector of E1M1 darkened to E1M9's needs turns it REFUSED"""
    assert any(r[0] == "REFUSED" and r[1].startswith("weapon light") for r in _rows(ls, wad, "E1M9"))
    assert any(r[0] == "OK" and r[1].startswith("weapon light") for r in _rows(ls, wad, "E1M1"))
    from doomfj import hud
    orig = hud.psprite_light_row
    monkeypatch.setattr(hud, "psprite_light_row", lambda rm, light: orig(rm, light) + (light == 255))
    assert any(r[0] == "REFUSED" and r[1].startswith("weapon light") for r in _rows(ls, wad, "E1M1"))
