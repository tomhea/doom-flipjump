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
    assert ("OK", "drawable things, every skill") in got                 # 305 >= 256, capped 255 a frame (F1.4; C11)
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


def _ids_row(rows):
    return next(r for r in rows if r[1].startswith("runtime ids: things + pools + drops"))


def test_runtime_ids_are_capped_at_the_maps_list_width(ls, wad, monkeypatch):
    """M8 F1.5 (docs/f1-runtime-ids.md): E1M5's 370 runtime ids (things + pools + drops) are OVER its default 8-bit
    lists (254) and the INFO row asks for 12; with MAP_CONFIG's LIST_ID_BITS 12 the same count is OK against 4,094.
    The CONTROL is the pair: a survey that ignored the map's width would report the same row both times."""
    import doomfj.config as config
    # wave 1 gave E1M5 its 12-bit lists: the 8-bit form is E1M5 without LIST_ID_BITS
    monkeypatch.setitem(config.MAP_CONFIG, "E1M5", {k: v for k, v in config.MAP_CONFIG["E1M5"].items() if k != "LIST_ID_BITS"})
    rows = _rows(ls, wad, "E1M5")
    r = _ids_row(rows)
    assert (r[0], r[2], r[3]) == ("OVER", "370", "<= 254"), r
    info = next(x for x in rows if x[1].startswith("list id bits needed"))
    assert info[2] == "12" and "set LIST_ID_BITS 12" in info[4], info
    monkeypatch.setitem(config.MAP_CONFIG, "E1M5", dict(config.MAP_CONFIG["E1M5"], LIST_ID_BITS=12))
    rows = _rows(ls, wad, "E1M5")
    r = _ids_row(rows)
    assert (r[0], r[2], r[3]) == ("OK", "370", "<= 4094"), r
    info = next(x for x in rows if x[1].startswith("list id bits needed"))
    assert info[2] == "12" and info[4] == "MAP_CONFIG has 12", info
    assert not any(x[0] in BAD and ("runtime" in x[1] or "list id" in x[1]) for x in rows)


def test_a_pickup_without_a_sprite_is_missing(ls, wad, monkeypatch):
    """M8 (gates-ready): E1M8's cell pack (17) has a give but no sprite -- every gate's views KeyError on it; the survey
    names it. CONTROL: on E1M1, a pickup it uses (the clip, 2007) taken out of THING_SPRITE turns MISSING too"""
    rows = _rows(ls, wad, "E1M8")                        # M8 C6 gave the cell pack its art (CELP): OK now
    assert any(r[0] == "OK" and r[1].startswith("thing 17 ") and "sprite yes" in r[4] for r in rows), (
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

def test_e1m8_surveys_its_barons_and_the_boss_trigger(ls, wad):
    """M8 C8: thing 3003 is a monster (no MISSING row), and the rows the Baron's fj bakes per map: A_BossDeath's floor
    group (tag 666, sector 3), the radius classes (24, 30), the one missile (MT_BRUISERSHOT), one height (64)"""
    rows = _rows(ls, wad, "E1M8")
    assert not any("3003" in r[1] and r[0] != "OK" for r in rows)
    assert ("OK", "thing 3003  (monster MT_BRUISER)", "4") in {r[:3] for r in rows}
    got = {r[1].split(" (")[0]: (r[0], r[2]) for r in rows}
    assert got["A_BossDeath"] == ("OK", "group 2, sectors [3]")
    assert got["monster radius classes"] == ("OK", "(24, 30)")
    assert got["one monster missile species"] == ("OK", "MT_BRUISERSHOT")
    assert got["one monster height"] == ("OK", "[64]")
    e1 = {r[1].split(" (")[0]: (r[0], r[2]) for r in _rows(ls, wad, "E1M1")}
    assert "A_BossDeath" not in e1 and e1["monster radius classes"] == ("OK", "(20, 30)")


def test_control_a_boss_tag_without_a_group_is_refused(ls, wad, monkeypatch):
    """R9: E1M8's boss rule moved to a tag no line names (667) -- the model refuses the map and the survey says so"""
    monkeypatch.setitem(ls.gd.BOSS_MAPS, "E1M8", ("MT_BRUISER", 667, "lowest"))
    rows = _rows(ls, wad, "E1M8")
    assert any(r[0] == "REFUSED" and "boss tag 667" in r[4] for r in rows), [r for r in rows if r[0] == "REFUSED"]


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


# ---- M8 C2 (docs/c2-slot-ids.md): the monster / barrel slot ids and the counters past a byte -------------------------
def _row(rows, prefix):
    return next(r for r in rows if r[1].startswith(prefix))


def test_the_slot_ids_are_capped_at_the_maps_slot_width(ls, wad, monkeypatch):
    """E1M6's 294 monster slots (3 lost souls among them) + 7 barrels: OK against MAP_CONFIG's SLOT_ID_BITS 12 (the
    World's row, the WAD's row, and the INFO row agree). The CONTROL is the pair: without its entry (the default 8
    bits) the same count is OVER on both rows and the INFO row asks for 12 -- a survey that ignored the map's width
    would report the same rows both times"""
    import doomfj.config as config
    rows = _rows(ls, wad, "E1M6")
    r = _row(rows, "monster slots + barrels (slot ids")
    assert (r[0], r[2], r[3]) == ("OK", "301", "<= 4093"), r
    r = _row(rows, "monster slots + barrels, every skill, from the WAD")
    assert (r[0], r[2], r[3]) == ("OK", "301", "<= 4093"), r
    assert _row(rows, "slot id bits needed")[2:] == ("12", "", "MAP_CONFIG has 12")
    assert _row(rows, "monsters + barrels -> aim_sid")[0] == "OK"
    assert _row(rows, "monsters on LEVEL COMPLETE")[:3] == ("OK", "monsters on LEVEL COMPLETE (st_kill: "
                                                            "statcode.count_nibbles / count_digits)", "294")
    assert not any(x[0] in BAD and any(k in x[1] for k in ("slot", "aim_sid", "LEVEL COMPLETE", "runtime"))
                   for x in rows), [x for x in rows if x[0] in BAD]
    monkeypatch.setitem(config.MAP_CONFIG, "E1M6", {k: v for k, v in config.MAP_CONFIG["E1M6"].items()
                                                    if k != "SLOT_ID_BITS"})
    rows = _rows(ls, wad, "E1M6")
    r = _row(rows, "monster slots + barrels (slot ids")
    assert (r[0], r[2], r[3]) == ("OVER", "301", "<= 254"), r
    r = _row(rows, "monster slots + barrels, every skill, from the WAD")
    assert (r[0], r[2], r[3]) == ("OVER", "301", "<= 254") and "SLOT_ID_BITS 12" in r[4], r
    info = _row(rows, "slot id bits needed")
    assert info[2] == "12" and "set SLOT_ID_BITS 12" in info[4], info


def test_the_slot_rows_survive_a_world_refused_for_another_reason(ls, wad, monkeypatch):
    """E1M7's filtered World refuses (a teleport destination on a mover): the WAD's slot row still reads 281 + 8 souls
    + 16 barrels against its 12 bits, and the runtime-ids row counts its droppers from the WAD's things
    (world.level_things). CONTROL: E1M7 without SLOT_ID_BITS -- the same row OVER"""
    import doomfj.config as config
    rows = _rows(ls, wad, "E1M7")
    assert any(r[0] == "REFUSED" and r[1].startswith("World(strict=True) without") for r in rows)
    r = _row(rows, "monster slots + barrels, every skill, from the WAD")
    assert (r[0], r[2]) == ("OK", "305"), r
    assert _row(rows, "runtime ids: things + pools + drops")[0] == "OK"
    monkeypatch.setitem(config.MAP_CONFIG, "E1M7", {k: v for k, v in config.MAP_CONFIG["E1M7"].items()
                                                    if k != "SLOT_ID_BITS"})
    assert _row(_rows(ls, wad, "E1M7"), "monster slots + barrels, every skill, from the WAD")[0] == "OVER"
