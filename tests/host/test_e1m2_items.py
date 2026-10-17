"""M8 F4 / F7 (E1M2's items): the host side of the new gives' card cells, the KEYS area's yellow and red icons and the
exit frame's bar -- the rules that keep E1M1 unchanged and the ones the fj harnesses (tests/fj/test_give_cards_fj.py,
test_hud_keys_fj.py, test_exit_bar_fj.py) lean on. Each rule has a negative control (R9).
"""
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import hud, hudcode
from doomfj import lootcode as L
from doomfj import wall_renderer as WR
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
E1M1 = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"
E1M2 = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
needs_art = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")
needs_e1m2 = pytest.mark.skipif(not E1M2.exists(), reason="needs tests/fixtures/freedoom_e1m2.wad")
CARDS = ("yellow", "red")


@pytest.fixture(scope="module")
def colours():
    art = WadFile.from_path(str(ART))
    return hud.bar_colours(bytes(b for rgb in art.playpal(0) for b in rgb))


def _wad(path):
    return WadFile.from_path(str(path))


# ---- the card cells ----------------------------------------------------------------------------------------------
@needs_e1m2
def test_the_card_cells_follow_the_maps_cards():
    """ONE rule (lootcode.map_cards): E1M1 holds only the blue card -- nothing new is declared, persisted, restarted or
    drawn; E1M2 holds both new cards"""
    m1, m2 = _wad(E1M1), _wad(E1M2)
    assert L.map_cards(m1.things("E1M1")) == () and L.map_persist(m1, "E1M1") == () and L.hud_cards(m1, "E1M1") == ()
    assert L.map_cards(m2.things("E1M2")) == (6, 13)
    assert L.map_persist(m2, "E1M2") == ("pcard_y", "pcard_r") and L.hud_cards(m2, "E1M2") == CARDS
    from doomfj.world import World
    w1, w2 = World(m1, "E1M1", monsters="idle"), World(m2, "E1M2", monsters="idle")
    assert L.card_cells(w1) == () and L.card_decls(w1) == [] and L.card_restart_lines(w1) == []
    assert L.card_decls(w2) == ["pcard_y: hex.vec 1, 0", "pcard_r: hex.vec 1, 0"]
    assert L.card_restart_lines(w2) == ["    hex.zero 1, pcard_y", "    hex.zero 1, pcard_r"]


def test_control_a_multiplayer_card_is_not_the_maps():
    """a card only deathmatch / co-op spawns (MTF_NOTSINGLE, 16) is no single-player card: no cell (E1M1's own
    soulsphere is such a thing); the same card in single player is"""
    class T:
        def __init__(self, ty, flags):
            self.type, self.flags, self.x, self.y = ty, flags, 0, 0
    assert L.map_cards([T(6, 7 | 16), T(13, 7 | 16)]) == ()
    assert L.map_cards([T(13, 7), T(6, 1)]) == (6, 13)


@needs_e1m2
def test_the_card_cells_persist_on_e1m2_only():
    from doomfj.build import _map_persist
    assert _map_persist(_wad(E1M1), "E1M1", True) == ()
    assert set(_map_persist(_wad(E1M2), "E1M2", True)) >= {"pcard_y", "pcard_r"}
    assert _map_persist(_wad(E1M2), "E1M2", False) == ()


def test_the_give_routines_match_the_models_constants():
    from doomfj import combat as C
    L._check_rules()
    assert (L.SOUL_HEALTH, L.MAX_SOUL) == (C.SOUL_HEALTH, C.MAX_SOUL)
    assert {6, 13, 2013, 2026} <= C.GETTABLE
    text = "\n".join(L.give_lines(13))
    assert "hex.if1 1, pcard_r, give_13_ok" in text and "hex.set 1, pcard_r, 1" in text and "pcard_y" not in text
    assert L.give_lines(5)[1] == "    hex.if1 1, pcard, give_5_ok"          # the blue card's text is E1M1's


# ---- the KEYS area -----------------------------------------------------------------------------------------------
def test_e1m1_slots_are_unchanged_by_the_new_icons():
    """the new slots come AFTER every E1M1 slot, and only with `cards`"""
    assert hud.bar_slots(()) == hud.bar_slots()
    assert hud.bar_slots(CARDS)[:len(hud.bar_slots())] == hud.bar_slots()
    assert [n for n, *_r in hud.bar_slots(CARDS)[len(hud.bar_slots()):]] == ["card_y", "card_r"]
    assert [n for n, *_r in hud.bar_slots(("red",))[len(hud.bar_slots()):]] == ["card_r"]
    with pytest.raises(AssertionError):
        hud.bar_slots(("green",))


def test_the_icons_own_disjoint_columns_inside_keys():
    owner = {}
    for name, x0, w, _v in hud.bar_slots(CARDS):
        for x in range(x0, x0 + w):
            assert x not in owner, "column %d is in slots %s and %s" % (x, owner[x], name)
            owner[x] = name
    _n, k0, k1 = next(p for p in hud.PANELS if p[0] == "KEYS")
    for _slot, _card, (x0, y0, w, h) in hud.KEY_ICONS:
        assert k0 < x0 and x0 + w <= k1 + 1 and y0 + h <= hud.LABEL_Y, (x0, y0, w, h)


@needs_art
@pytest.mark.parametrize("cards", [(False, False, False), (True, True, False), (False, True, True), (True, False, True),
                                   (True, True, True)])
def test_a_key_slot_column_is_the_full_bar_column(colours, cards):
    """the fj redraws ONE slot's columns from its variant: that must be what the whole bar shows there"""
    blue, yellow, red = cards
    vals = dict(hudcode.LEVEL_START, blue=blue, yellow=yellow, red=red)
    full = hud.bar_pixels(colours, **vals)
    sv = hud.slot_values(**vals, cards=CARDS)
    owner = {x: n for n, x0, w, _v in hud.bar_slots(CARDS) for x in range(x0, x0 + w)}
    for x in range(160):
        assert hud.bar_column(colours, x, sv.get(owner.get(x)), cards=CARDS) == [full[y][x]
                                                                              for y in range(hud.BAR_ROWS)], x


@needs_art
def test_each_icon_is_drawn_in_its_own_colour_and_place(colours):
    base = hud.bar_pixels(colours, **hudcode.LEVEL_START)
    for slot, card, (x0, y0, w, h) in hud.KEY_ICONS:
        px = hud.bar_pixels(colours, **dict(hudcode.LEVEL_START, **{card: True}))
        diff = {(x, y) for y in range(hud.BAR_ROWS) for x in range(160) if px[y][x] != base[y][x]}
        assert diff == {(x, y) for y in range(y0, y0 + h) for x in range(x0, x0 + w)
                        if not (y in (y0, y0 + h - 1) and x in (x0, x0 + w - 1))}, card
        assert {px[y][x] for x, y in diff} == {colours[hud.KEY_COLOUR[card]]}
    assert len({colours["card"], colours["ycard"], colours["rcard"], colours["bg"]}) == 4


@needs_art
def test_control_the_icon_slot_reads_its_own_card(colours):
    """R9 for the column rule above: the yellow slot's column drawn from the RED card's value is not the bar's"""
    vals = dict(hudcode.LEVEL_START, yellow=True, red=False)
    full = hud.bar_pixels(colours, **vals)
    x0 = dict((s, b[0]) for s, _c, b in hud.KEY_ICONS)["card_y"]
    assert hud.bar_column(colours, x0 + 1, False, cards=CARDS) != [full[y][x0 + 1] for y in range(hud.BAR_ROWS)]


@needs_art
def test_the_tail_text_is_e1m1s_without_cards(colours):
    art = WadFile.from_path(str(ART))
    overlay = hud.psprite_columns(art.get_data(hudcode.READY_WEAPON))
    row = art.colormap()[0]
    a = hudcode.hud_tail_lines(colours, overlay, row, view_rows=84)
    assert hudcode.hud_tail_lines(colours, overlay, row, view_rows=84, cards=()) == a
    b = hudcode.hud_tail_lines(colours, overlay, row, view_rows=84, cards=CARDS)
    assert b != a and any("pcard_y" in ln for ln in b) and any("pcard_r" in ln for ln in b)
    assert not any("pcard_y" in ln or "pcard_r" in ln for ln in a)


@needs_e1m2
def test_the_oracles_bar_shows_the_worlds_cards():
    """monsters.MonsterPhase.screen_kw passes the World's yellow and red cards to the picture (GameScreen.frame)"""
    from doomfj.monsters import MonsterPhase
    from doomfj.world import World
    w = World(_wad(E1M2), "E1M2", monsters="idle", player="final")
    ph = MonsterPhase.__new__(MonsterPhase)
    ph.world, ph.gd = w, gd
    v = ph.screen_kw()["values"]
    assert (v["yellow"], v["red"]) == (False, False)
    w.ws.p_cards[gd.IT_YELLOWCARD] = 1
    w.ws.p_cards[gd.IT_REDCARD] = 1
    v = ph.screen_kw()["values"]
    assert (v["yellow"], v["red"]) == (True, True)


# ---- the exit frame's bar (issue #123 item 4) ---------------------------------------------------------------------
def test_the_guarded_bar_text_is_e1m1s():
    """bar_always=False is blocked48's text; True moves the bar (and nothing else) after the guard"""
    hrt = {"bar": ["BAR1", "BAR2"]}
    a = WR.p5_tic_lines(hrt, barrels=True)
    assert a == WR.p5_tic_lines(hrt, barrels=True, bar_always=False)
    b = WR.p5_tic_lines(hrt, barrels=True, bar_always=True)
    assert sorted(a) == sorted(b) and b[-3:] == ["p5_bar_skip:", "BAR1", "BAR2"]
    assert a[-3:] == ["BAR1", "BAR2", "p5_bar_skip:"]


def test_e1m1_has_no_exit_frame_hazard_and_e1m2_has_one():
    """the emitter's choice (`exit_frame_bar_hazards`): E1M1 keeps the guarded bar; E1M2's health bonuses beside its
    exit switch put the bar after the guard"""
    from doomfj.doors import exit_boxes
    m1 = _wad(E1M1)
    h1 = WR.exit_frame_bar_hazards(m1, "E1M1", exit_boxes(m1.linedefs("E1M1"), m1.vertexes("E1M1")))
    assert h1["hazards"] == [] and h1["hurt"] > 0 and h1["pickup"] > 0
    if E1M2.exists():
        m2 = _wad(E1M2)
        h2 = WR.exit_frame_bar_hazards(m2, "E1M2", exit_boxes(m2.linedefs("E1M2"), m2.vertexes("E1M2")))
        assert h2["hazards"] and all("health / armor pickup" in s for s in h2["hazards"])


def test_control_a_hazard_is_reported_not_refused():
    """R9: the box moved onto a stimpack / the nukage is a hazard (the emitter then runs the bar after the guard); the
    old refusal survives only as assert_exit_frame_bar, which the emitter no longer calls"""
    m1 = _wad(E1M1)
    stim = next(t for t in m1.things("E1M1") if t.type == 2011 and t.x < 0)
    h = WR.exit_frame_bar_hazards(m1, "E1M1", [(stim.x + 100, stim.y - 10, stim.x + 200, stim.y + 10)])
    assert len(h["hazards"]) == 1 and "health / armor pickup" in h["hazards"][0]
    h = WR.exit_frame_bar_hazards(m1, "E1M1", [(1500, 900, 1600, 1000)])
    assert any("meets damaging sector" in s for s in h["hazards"])
    src = (ROOT / "src" / "doomfj" / "wall_renderer.py").read_text(encoding="utf-8")
    assert src.count("assert_exit_frame_bar(") == 1                   # its definition: no caller in the emitter


def test_the_stand_ins_are_retired():
    import importlib.util
    spec = importlib.util.spec_from_file_location("emit_check", ROOT / "scripts" / "emit_check.py")
    ec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ec)
    assert "gives" not in ec.STANDINS and "exit-bar-stale" not in ec.STANDINS
