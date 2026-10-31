"""M8 C8 part 2 (the lost soul): `scripts/level_survey.py`'s `Survey.monster_extensions` -- the rows the soul earned.

Three traps the soul found, each a survey row: (1) a new monster's states take THING-DOMAIN indices borrowed from
weapon-only states (gamedata.EXT_ALIAS_CODES, check_thing_aliases) -- a later monster can run out of them; (2) damagecode's pain classes are one
nibble of dmrnd -- at most 4 painchances on a map; (3) a soul beside a teleport line -- since M8 soultele both mirrors
teleport a soul (EV_Teleport's z, momz, ceilingz), so the row is OK; what it still refuses is a monster radius the fj's
teleport tests do not know (teleportcode: 16 / 20 / 30; a Baron's 24 beside a teleport line).

R9: each row is shown OK on E1M1 + three souls, then each CONTROL shrinks the bound (or adds the teleport) and the row
must turn OVER / REFUSED -- a survey that checks nothing cannot pass.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src")]

from doomfj import gamedata as gd                                    # noqa: E402
from doomfj.wad import Thing, WadFile                                # noqa: E402
from doomfj.world import World                                       # noqa: E402

SOULS = [(-250, 240, 180), (-200, 300, 180), (-300, 200, 180)]


def _survey_module():
    spec = importlib.util.spec_from_file_location("level_survey_soul", ROOT / "scripts" / "level_survey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ls():
    return _survey_module()


@pytest.fixture(scope="module")
def world():
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    base = mw.things
    mw.things = lambda name, base=base: base(name) + [Thing(x, y, a, 3006, 7) for x, y, a in SOULS]
    return mw, World(mw, "E1M1", monsters="idle")


def _rows(ls, mw, w):
    s = ls.Survey(mw, "E1M1", mw)
    s.monster_extensions(w)
    return {r[1].split(" (")[0]: r for r in s.rows}


def test_the_soul_map_surveys_its_rows_ok(ls, world):
    rows = _rows(ls, *world)
    assert rows["extension states' borrowed thing indices"][0] == "OK"
    assert rows["extension states' borrowed thing indices"][2] == str(len(gd.EXT_STATE_NAMES)) == "43"   # Baron 27 + 16
    assert rows["monster pain classes"][0] == "OK"
    assert rows["lost souls"][:3] == ("OK", "lost souls (MT_SKULL: doomfj.lostsoul, soulcode)", "3")
    assert rows["lost souls beside teleport lines"][0] == "OK"
    assert not any(r[0] in ("REFUSED", "ERROR", "OVER") for r in rows.values())


def test_e1m1_has_no_soul_row(ls):
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    rows = _rows(ls, mw, World(mw, "E1M1", monsters="idle"))
    assert "lost souls" not in rows and rows["extension states' borrowed thing indices"][0] == "OK"


def test_control_a_borrowed_index_on_a_thing_state(ls, world, monkeypatch):
    """the soul's run one on (31 .. 39): S_BLOOD1's index -- the row turns REFUSED"""
    monkeypatch.setattr(ls.gd, "EXT_ALIAS_CODES", tuple(range(3, 30)) + tuple(range(31, 40)) + tuple(range(212, 219)))
    assert _rows(ls, *world)["extension states' borrowed thing indices"][0] == "REFUSED"


def test_control_a_fifth_pain_class(ls, world, monkeypatch):
    from doomfj import damagecode
    real = damagecode.pain_classes
    monkeypatch.setattr(damagecode, "pain_classes", lambda p: list(real(p)) + [None] * (5 - len(real(p))))
    assert _rows(ls, *world)["monster pain classes"][0] == "OVER"


def test_a_teleport_beside_the_souls_is_ok(ls, world, monkeypatch):
    """M8 soultele: the pair is wired in both mirrors (tests/fj/test_soul_teleport_fj)"""
    mw, w = world
    monkeypatch.setattr(w, "teleports", ("a teleport line",), raising=False)
    assert _rows(ls, mw, w)["lost souls beside teleport lines"][0] == "OK"


def test_control_a_radius_24_beside_a_teleport_is_refused(ls, world, monkeypatch):
    mw, w = world
    monkeypatch.setattr(w, "teleports", ("a teleport line",), raising=False)
    r = list(w.mon_radius)
    r[0] = 24
    monkeypatch.setattr(w, "mon_radius", r)
    row = _rows(ls, mw, w)["lost souls beside teleport lines"]
    assert row[0] == "REFUSED" and "24" in row[4], row


def test_control_a_soul_of_radius_20_is_refused(ls, world, monkeypatch):
    mw, w = world
    r = list(w.mon_radius)
    r[w.soul_slots[0]] = 20
    monkeypatch.setattr(w, "mon_radius", r)
    assert _rows(ls, mw, w)["lost souls: soulcode.check_model_rules"][0] == "REFUSED"
