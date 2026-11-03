"""M8 C6 (doomfj.powers): the timed powers' MODEL rules and the one rule for which maps carry them -- each with its
control (R9):

  * `map_powers` per map (E1M1, E1M2: none; E1M3 the invisibility; E1M4 the suit; E1M6 / E1M7 / E1M9 both) -- the
    control: a multiplayer-only suit is not the map's;
  * the schema: E1M1's and E1M2's Worlds have no power field (their digests and programs are untouched), E1M3's has
    `p_invis` (control: its field list differs from a power-less one by exactly that);
  * `combat.palette_index` IS ST_doPaletteStuff with `powers[pw_ironfeet]` -- held to a line-by-line transcription of
    the C over a grid (control: a transcription without the `& 8` flicker disagrees);
  * the countdown runs a player tic while alive and stops while dead (P_DeathThink returns before it);
  * the monsters' aim at an invisible player: A_FaceTarget draws two on the shooter's stream and the hitscan's
    bullets take the turn -- over every stream state the hits of an invisible player differ from a visible one's, and
    the stream advances by 2 more (control: with the power off, nothing differs);
  * the survey: the three pickups' rows are OK on every map that holds them; a gettable kind with no sprite is
    reported (the trap: an item taken but never drawn).
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from doomfj import gamedata as gd
from doomfj import powers as P

ROOT = Path(__file__).resolve().parents[2]
FULL = ROOT / "assets" / "freedoom1.wad"
needs_wad = pytest.mark.skipif(not FULL.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")


@pytest.fixture(scope="module")
def wad():
    from doomfj.wad import WadFile
    return WadFile.from_path(str(FULL))


@needs_wad
def test_map_powers_per_map(wad):
    want = {"E1M1": (), "E1M2": (), "E1M3": (2024,), "E1M4": (2025,), "E1M5": (), "E1M6": (2024, 2025),
            "E1M7": (2024, 2025), "E1M8": (), "E1M9": (2024, 2025)}
    assert {m: P.map_powers(wad.things(m)) for m in want} == want


def test_control_a_multiplayer_suit_is_not_the_maps():
    from doomfj.wad import Thing
    assert P.map_powers([Thing(0, 0, 0, 2025, 7 | 16)]) == ()          # MTF_NOTSINGLE
    assert P.map_powers([Thing(0, 0, 0, 2025, 7)]) == (2025,)


def test_the_fixture_worlds_have_no_power_field():
    from doomfj.wad import WadFile
    from doomfj.world import World
    for m, f in (("E1M1", "freedoom_e1m1.wad"), ("E1M2", "freedoom_e1m2.wad")):
        w = World(WadFile.from_path(str(ROOT / "tests" / "fixtures" / f)), m, monsters="idle", player="fire")
        assert w.powers == () and not {"p_invis", "p_ironfeet"} & {x.name for x in w.schema}, m


@needs_wad
def test_control_a_power_map_has_its_field(wad):
    from doomfj.world import World, build_schema
    import dataclasses
    w = World(wad, "E1M3", monsters="idle", player="fire")
    names = [x.name for x in w.schema]
    bare = [x.name for x in build_schema(dataclasses.replace(w.layout, powers=()))]
    assert [n for n in names if n not in bare] == ["p_invis"]


def st_do_palette_stuff(dc, bc, strength, ironfeet, flicker=True):
    """st_stuff.c ST_doPaletteStuff, line by line (single player)"""
    cnt = dc
    if strength:
        bzc = 12 - (strength >> 6)
        if bzc > cnt:
            cnt = bzc
    if cnt:
        palette = (cnt + 7) >> 3
        if palette >= 8:
            palette = 7
        palette += 1
    elif bc:
        palette = (bc + 7) >> 3
        if palette >= 4:
            palette = 3
        palette += 9
    elif ironfeet > 4 * 32 or (flicker and ironfeet & 8):
        palette = 13
    else:
        palette = 0
    return palette


GRID = [(dc, bc, st, rf) for dc in (0, 1, 50) for bc in (0, 6, 40) for st in (0, 1, 700, 5000)
        for rf in (0, 1, 7, 8, 9, 15, 16, 24, 127, 128, 129, 130, 2100)]


def _ws(dc, bc, st, rf):
    return SimpleNamespace(p_damagecount=dc, p_bonuscount=bc, p_strength=st, p_ironfeet=rf)


def test_palette_index_is_st_do_palette_stuff_with_the_suit():
    from doomfj.combat import palette_index
    bad = [g for g in GRID if palette_index(_ws(*g)) != st_do_palette_stuff(*g)]
    assert bad == []
    assert {palette_index(_ws(*g)) for g in GRID} >= {0, 13}


def test_control_the_flicker_matters():
    from doomfj.combat import palette_index
    assert any(palette_index(_ws(*g)) != st_do_palette_stuff(*g, flicker=False) for g in GRID)


def test_a_world_without_the_suit_has_no_radiation():
    from doomfj.combat import palette_index
    assert palette_index(SimpleNamespace(p_damagecount=0, p_bonuscount=0, p_strength=0)) == 0


@needs_wad
def test_the_countdown_runs_alive_and_stops_dead(wad):
    from doomfj.world import World
    w = World(wad, "E1M4", monsters="idle", player="final")
    w.ws.p_ironfeet = 100
    for _ in range(3):
        w.tic({})
    assert w.ws.p_ironfeet == 97
    w.ws.p_dead, w.ws.p_health = 1, 0
    for _ in range(3):
        w.tic({})
    assert w.ws.p_ironfeet == 97


@needs_wad
def test_an_invisible_player_turns_the_hitscan(wad, monkeypatch):
    """A_PosAttack from a possessed in sight: over every stream state, the invisible player's outcome (hits and the
    stream) differs from the visible one's on some states, and the stream advances 2 more; with p_invis 0 (control)
    the two runs agree everywhere"""
    from doomfj.world import TicEvents, World
    w = World(wad, "E1M3", monsters="final", player="final")
    m = next(i for i, t in enumerate(w.mon_things) if t.type == 3004)
    monkeypatch.setattr(w, "attack_sight", lambda world, mm: True)
    ws = w.ws
    ws.mon_x[m], ws.mon_y[m] = (ws.px >> 16) + 200, ws.py >> 16

    def run(state, inv):
        ws.mon_target[m], ws.mon_rng[m], ws.p_invis = 1, state, inv
        ws.p_health, ws.p_armor, ws.p_dead = 100, 0, 0
        ev = TicEvents(tic=0)
        w._monster_attack(m, "A_PosAttack", ev)
        return [s[3] for s in ev.mon_shots], ws.mon_rng[m]

    differ = 0
    for s in range(256):
        a, b = run(s, 0), run(s, 2100)
        assert (b[1] - a[1]) % 256 == 2
        differ += a[0] != b[0]
        assert run(s, 0) == a
    assert differ > 10, differ


@needs_wad
def test_the_survey_reports_the_three_pickups_ok(wad):
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts" / "level_survey.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    for m, kinds in (("E1M3", (2024, 2046)), ("E1M4", (2025, 2046))):
        rows = ls.Survey(wad, m, wad).run().rows
        for k in kinds:
            row = next(r for r in rows if r[1].startswith("thing %d " % k))
            assert row[0] == "OK", row
        assert not any(r[0] != "OK" and "pickup sprite" in r[1] for r in rows), m


@needs_wad
def test_control_a_pickup_without_a_sprite_is_reported(wad, monkeypatch):
    spec = importlib.util.spec_from_file_location("level_survey", ROOT / "scripts" / "level_survey.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    from doomfj import reference_model as RM
    monkeypatch.setattr(RM, "THING_SPRITE", {k: v for k, v in RM.THING_SPRITE.items() if k != 2046})
    rows = ls.Survey(wad, "E1M3", wad).run().rows
    assert any(r[0] == "MISSING" and r[1].startswith("pickup sprite") and "2046" in str(r[2]) for r in rows), \
        [r for r in rows if "sprite" in r[1]]
