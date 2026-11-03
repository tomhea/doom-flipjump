"""M8 C6 (the plasma rifle) in the survey (scripts/level_survey.py): the rifle's rows are cleared on E1M6 / E1M9 (the
model's give and the fj's), the cell pack 17 is drawn (E1M8's refused World thing), and the lesson the rifle earned --
THE STATE BYTE (`Survey._state_byte`) -- each with its negative control (R9). Light: the survey, no emission."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")


@pytest.fixture(scope="module")
def ls():
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts/level_survey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def wad(ls):
    return ls.WadFile.from_path(str(ASSET))


def _rows(ls, wad, m, run="things"):
    sv = ls.Survey(wad, m, wad)
    getattr(sv, run)()
    return sv.rows


def _one(rows, prefix):
    hits = [r for r in rows if r[1].startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


@pytest.mark.parametrize("m", ["E1M6", "E1M9"])
def test_the_rifle_is_no_longer_missing(ls, wad, m):
    rows = _rows(ls, wad, m)
    assert not any(r[1] == "thing type 2004" for r in rows)
    r = _one(rows, "thing 2004")
    assert r[0] == "OK" and "fj give yes" in r[4], r


def test_control_a_rifle_without_its_fj_give_is_missing(ls, wad, monkeypatch):
    """R9: the fj give gone -- the row is MISSING again"""
    from doomfj import lootcode
    real = lootcode.give_lines

    def gl(kind, *a, **k):
        if kind == 2004:
            raise KeyError(kind)
        return real(kind, *a, **k)
    monkeypatch.setattr(lootcode, "give_lines", gl)
    r = _one(_rows(ls, wad, "E1M9"), "thing 2004")
    assert r[0] == "MISSING" and "fj give NO" in r[4], r


def test_the_cell_pack_has_art_on_e1m8(ls, wad):
    sv = ls.Survey(wad, "E1M8", wad).run()
    r = _one(sv.rows, "World things with sprite art")
    assert r[0] == "OK", r


def test_the_plasma_sprites_are_in_a_rifle_map_s_bank_only(wad, monkeypatch):
    """G6: the anim bank carries MT_PLASMA's lumps (PLSSA0 / PLSSB0, PLSEA0 .. E0) exactly on a map with the rifle
    (combat.plasma_on: E1M6, E1M9) -- E1M1 .. E1M5, E1M7, E1M8 carry none of their words. R9: the rule forced on, E1M1
    carries them"""
    from doomfj import combat
    from doomfj import wall_renderer as WR

    def plasma_sprites(m):
        return {s for s in WR.anim_frames(wad, m) if s in ("PLSS", "PLSE")}
    for m in ("E1M1", "E1M2", "E1M3", "E1M5", "E1M7"):
        assert not plasma_sprites(m), m
    for m in ("E1M6", "E1M9"):
        assert plasma_sprites(m) == {"PLSS", "PLSE"}, m
    monkeypatch.setattr(combat, "plasma_on", lambda things: True)
    assert plasma_sprites("E1M1") == {"PLSS", "PLSE"}


def test_the_state_byte(ls, wad):
    """no map needs a new state any more: the Baron and the lost soul (M8 C8) have theirs in the thing domain
    (gamedata.EXT_ALIAS_CODES) -- before them E1M6 was OVER by 16 and E1M8 by 27 (this test's first form); the
    control below still counts the free indices"""
    for m, want in (("E1M1", ("OK", "0")), ("E1M9", ("OK", "0")), ("E1M6", ("OK", "0")), ("E1M8", ("OK", "0"))):
        r = _one(_rows(ls, wad, m, "_state_byte"), "the state byte")
        assert (r[0], r[2]) == want and "<= 14 free" in r[3], (m, r)


def test_control_the_state_byte_counts_its_free_indices(ls, wad, monkeypatch):
    """R9: with the plasma's ghosts handed back (19 more raise indices free) the lost soul fits -- the row reads the
    table, it does not print a constant; and a type gamedata already holds needs nothing"""
    from doomfj import gamedata as gd
    names = tuple(next((g for g, live in gd.STATE_GHOSTS.items() if live == n), n) for n in gd.STATE_NAMES)
    monkeypatch.setattr(gd, "STATE_NAMES", names)
    r = _one(_rows(ls, wad, "E1M6", "_state_byte"), "the state byte")
    assert r[0] == "OK" and "<= 29 free" in r[3], r
    monkeypatch.undo()
    monkeypatch.setitem(gd.THING_TYPES, 3006, gd.THING_TYPES[3001])
    r = _one(_rows(ls, wad, "E1M6", "_state_byte"), "the state byte")
    assert (r[0], r[2]) == ("OK", "0"), r
