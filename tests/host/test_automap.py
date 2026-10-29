"""M8 -- THE MAP PAGE's host side (doomfj.automap; the owner, 2026-10-18): the switch, the scale and the bands, the two
mirrors of the baked page, the dot's arithmetic against a plain floor-division reference, DOOM's line rules, the
menu's rules with the MAP item and the key M, the help's M, and a map without the page untouched. tests/fj/
test_automap_fj.py RUNS the emitted fj against the same oracle.

The owner, 2026-10-18 ("Add it to e1m1 too"): E1M1 has the page too, at 40 units a pixel -- not a power of two, so its
dot divides by a fixed-point RECIPROCAL: `test_the_reciprocal_is_exact_over_the_whole_extent` holds it to floor
division for every whole-unit offset the map has, with a reciprocal one too small as its control. E1M2's page and dot
(32 units, a shift) are frozen to m8p-final's text (`test_e1m2_is_m8p_finals_page`)."""
import hashlib
import random

import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj import automap as A
from doomfj.config import Config, map_cfg
from doomfj.menu import (HELP_GAME_SCR, HELP_MENU_SCR, MAIN_EXIT_SCR, MAIN_HELP_SCR, MAIN_MAP_SCR, MAIN_RESUME_SCR,
                         MAP_GAME_SCR, MAP_MENU_SCR, MAP_KEY, MENU_KEYS, help_key_names, help_keycodes, help_pixels,
                         menu_keys, menu_step, palette_colours, pixels, program_cells)
from doomfj.wad import Linedef, Sector, Sidedef, WadFile
from doomfj import wall_renderer as WR

M32 = 0xFFFFFFFF
ASSETS = "tests/fixtures/freedoom_assets.wad"


def _palette():
    return bytes(b for rgb in WadFile.from_path(ASSETS).playpal(0) for b in rgb)


@pytest.fixture(scope="module")
def e1m2():
    return A.pages_for(WadFile.from_path("tests/fixtures/freedoom_e1m2.wad"), "E1M2", _palette())


@pytest.fixture(scope="module")
def e1m1():
    return A.pages_for(WadFile.from_path("tests/fixtures/freedoom_e1m1.wad"), "E1M1", _palette())


def test_the_switch_is_per_map():
    """E1M1's and E1M2's MAP_CONFIG turn the page on; the default Config (a map not listed) leaves it off. E1M1's
    entry is AUTOMAP and (#149) DOOR_NEIGHBOURS "legacy", host-side only: every other field is the default it had with
    no entry, and its fj constants are the default's"""
    from dataclasses import fields
    from doomfj.config import MAP_CONFIG
    assert map_cfg(Config(), "E1M2").AUTOMAP == 1 and A.has_page("E1M2")
    assert map_cfg(Config(), "E1M1").AUTOMAP == 1 and A.has_page("E1M1")
    assert MAP_CONFIG["E1M1"] == {"AUTOMAP": 1, "DOOR_NEIGHBOURS": "legacy"}
    assert Config().AUTOMAP == 0 and not A.has_page("E1M6")   # a map MAP_CONFIG gives no page (wave 1 has one)
    e1, base = map_cfg(Config(), "E1M1"), Config()
    assert [f.name for f in fields(Config) if getattr(e1, f.name) != getattr(base, f.name)] == ["AUTOMAP",
                                                                                                "DOOR_NEIGHBOURS"]
    assert e1.constants() == base.constants()


def test_build_takes_the_screen_size_from_its_caller(e1m1):
    """#149 (R6): `build` has no 160 x 100 of its own -- width and height are required, and `pages_for` passes the
    config's W x H. CONTROL: a different screen size gives a different page (the arguments are used)"""
    import inspect
    params = inspect.signature(A.build).parameters
    assert all(params[k].default is inspect.Parameter.empty for k in ("width", "height"))
    c = map_cfg(Config(), "E1M1")
    assert (e1m1.width, e1m1.height) == (c.W, c.H)
    mw = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
    assert A.build(mw, "E1M1", _palette(), c.W, c.H) == e1m1
    assert A.build(mw, "E1M1", _palette(), c.W + 64, c.H) != e1m1
    with pytest.raises(TypeError):
        A.build(mw, "E1M1", _palette())


def test_e1m2_scale_and_bands(e1m2):
    """32 units a pixel (the finest scale, UNITS_MIN: a power of two, so the dot shifts), two overlapping bands of
    98 rows over the map's 155, switched at the middle of their overlap"""
    p = e1m2
    assert (p.units, p.shift, p.wpx, p.hpx, p.nbands, p.tops, p.thresholds) == (32, 5, 93, 155, 2, (0, 57), (77,))
    assert p.units == A.UNITS_MIN
    assert A.window(p) == (5, 1)
    assert {"wall", "step", "blue", "yellow", "red", "exit"} == p.kinds


def test_e1m1_scale(e1m1):
    """40 units a pixel: 32 would be 124 px wide, over the area; 99 x 86 px, ONE page (centred in its rows); not a
    power of two, so the dot multiplies by the reciprocal of 40"""
    p = e1m1
    area = p.panel_x - A.PANEL_GAP - A.MARGIN_X
    assert (p.maxx - p.minx) // 32 + 1 > area >= p.wpx
    assert (p.units, p.shift, p.wpx, p.hpx, p.nbands, p.thresholds) == (40, None, 99, 86, 1, ())
    assert A.recip_of(p) == (5, 26215)
    assert {"wall", "step", "blue", "exit"} == p.kinds


# frozen at m8p-final (925af820): E1M2's page -- the dot's fj, the band streams, the cold block, the decls;
# RE-FROZEN at the screen API change (io-api, 2026-10-23): the bands are draw_collines frames (COPY, END closing every
# column, END_CMD + present) and the dot's KEEP is the API's 0xFE; the decls are m8p-final's. The PIXELS are
# unchanged: test_each_band_stream_paints_its_picture decodes them through the device against the oracle
E1M2_FROZEN = {"fj": "284edf9fc4ae9dbb7cc2fcd95ab4a5d13376562d6ae2c310b5afde314a6aa869",
               "streams": "5a3d268dcafd5282c9cd06a1f7315b1550ed54c7ceb5e24d1ab519bfe19e0336",
               "decls": "909a7e89612060258d9148bdaabc96ec92373984f0fba09072095c30267d7289"}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_e1m2_is_m8p_finals_page(e1m2):
    """the steps-of-8 scale rule and the reciprocal leave E1M2 (32 units: the shift) as m8p-final emitted it -- the
    dot's fj, both bands' streams and the page's decls, hash for hash"""
    assert _sha("\n".join(A.fj_lines(e1m2))) == E1M2_FROZEN["fj"]
    assert _sha("\n".join(A.band_stream(e1m2, k).hex() for k in range(e1m2.nbands))) == E1M2_FROZEN["streams"]
    assert _sha("\n".join(A.decls(e1m2))) == E1M2_FROZEN["decls"]


def test_the_reciprocal_is_exact_over_the_whole_extent(e1m1):
    """THE PROOF: (d * M) >> 4t == d // 40 for EVERY whole-unit offset d the map has (0 .. its extent, 3,952), and
    the dot through it equals floor division of the 16.16 position at every whole unit of the map's width and height
    (each with a fraction); R9: M one smaller, and the fraction one nibble shorter, are each wrong somewhere in it"""
    p = e1m1
    t, m = A.recip_of(p)
    dmax = A.extent(p)
    assert dmax == 3952
    assert all((d * m) >> (4 * t) == d // p.units for d in range(dmax + 1))
    assert any((d * (m - 1)) >> (4 * t) != d // p.units for d in range(dmax + 1))
    m_short = -(-(16 ** (t - 1)) // p.units)
    assert any((d * m_short) >> (4 * (t - 1)) != d // p.units for d in range(dmax + 1))
    rnd = random.Random(40)
    for x in range(p.minx, p.maxx + 1):
        vx = ((x << 16) + rnd.randrange(1 << 16)) & M32
        assert A.dot(p, vx, p.maxy << 16)[1] == _reference_dot(p, vx, p.maxy << 16)[1], x
    for y in range(p.miny, p.maxy + 1):
        vy = ((y << 16) + rnd.randrange(1 << 16)) & M32 if y < p.maxy else (y << 16) & M32
        vx = (p.minx << 16) & M32
        assert A.dot(p, vx, vy) == _reference_dot(p, vx, vy), y


def test_a_reciprocal_one_too_small_is_caught(e1m1, monkeypatch):
    """R9 for the dot: recip_of returning M - 1 moves some position's dot off the floor division"""
    t, m = A.recip_of(e1m1)
    monkeypatch.setattr(A, "recip_of", lambda p: (t, m - 1))
    assert any(A.dot(e1m1, vx, vy) != _reference_dot(e1m1, vx, vy)
               for vx, vy in [(((x << 16) & M32), (e1m1.maxy << 16) & M32) for x in range(e1m1.minx, e1m1.maxx)])


def _decode(stream, w, h):
    """the stream through the REAL screen device (tests/host/test_menu.py's way): exactly one frame, its pixels"""
    scr = InMemoryScreen()
    from doomfj import screenwire as SW
    for byte in SW.init_screen(w, h) + stream:
        for k in range(8):
            scr.write_bit(bool((byte >> k) & 1))
    assert scr.frame_count == 1
    return list(scr.pixel_indices)


@pytest.mark.parametrize("which", ["e1m1", "e1m2"])
def test_each_band_stream_paints_its_picture(which, request):
    """ONE GENERATOR, TWO MIRRORS: each band's frame, decoded by the REAL screen device, is its picture"""
    p = request.getfixturevalue(which)
    for k in range(p.nbands):
        assert _decode(A.band_stream(p, k), p.width, p.height) == A.band_pixels(p, k), k


def _reference_dot(p, viewx, viewy):
    """the dot by plain floor division of the SIGNED 16.16 position -- not the program's arithmetic"""
    sx = viewx - (1 << 32) if viewx & 0x80000000 else viewx
    sy = viewy - (1 << 32) if viewy & 0x80000000 else viewy
    col = p.x0 + (sx - (p.minx << 16)) // (p.units << 16)
    row = ((p.maxy << 16) - sy) // (p.units << 16)
    band = sum(row >= t for t in p.thresholds)
    return band, col - 1, row - p.tops[band] + A.MARGIN_Y - 1


def _random_poses(p, n=400, seed=7):
    rnd = random.Random(seed)
    return [(rnd.randrange(p.minx << 16, (p.maxx + 1) << 16) & M32, rnd.randrange(p.miny << 16, (p.maxy << 16) + 1) & M32)
            for _ in range(n)]


@pytest.mark.parametrize("which", ["e1m1", "e1m2"])
def test_the_dot_is_the_floor_division(which, request):
    """`dot`'s steps (the program's: E1M2's 32-bit sums and shifts, E1M1's reciprocal) equal a plain floor division
    at 400 positions"""
    p = request.getfixturevalue(which)
    for vx, vy in _random_poses(p):
        assert A.dot(p, vx, vy) == _reference_dot(p, vx, vy), (vx, vy)


def test_a_dot_a_pixel_off_is_caught(e1m2, monkeypatch):
    """R9 for the reference test above: x_const one pixel off disagrees with the floor division"""
    good = A.x_const(e1m2)
    monkeypatch.setattr(A, "x_const", lambda p: (good + (1 << A.shift_bits(p))) & M32)
    assert any(A.dot(e1m2, vx, vy) != _reference_dot(e1m2, vx, vy) for vx, vy in _random_poses(e1m2, 20))


def test_the_dot_is_drawn_where_dot_says(e1m2):
    vx, vy = 608 << 16, 48 << 16                                   # E1M2's player start
    band, col, top = A.dot(e1m2, vx, vy)
    pic, base = A.pixels(e1m2, vx, vy), A.band_pixels(e1m2, band)
    changed = {(i % e1m2.width, i // e1m2.width) for i in range(len(pic)) if pic[i] != base[i]}
    assert changed <= {(col + dx, top + dy) for dx in range(A.DOT) for dy in range(A.DOT)}
    assert all(pic[(top + dy) * e1m2.width + col + dx] == e1m2.inks["you"] for dx in range(3) for dy in range(3))


def test_every_reachable_row_keeps_the_dot_on_screen(e1m2):
    """`check` is what the emitter runs; a page whose bands cannot hold the dot is refused (R9: a threshold moved
    to the band's edge)"""
    A.check(e1m2)
    from dataclasses import replace
    bad = replace(e1m2, tops=(0, 40))                     # band 1 from row 40: its last rows fall off its bottom
    with pytest.raises(AssertionError):
        A.check(bad)


def test_doom_line_rules():
    """am_map.c's: ML_DONTDRAW hides, one-sided and SECRET are walls, a two-sided line only where a height changes,
    a locked door its key's colour, an exit green"""
    secs = [Sector(0, 128, "F", "C", 160, 0, 0), Sector(0, 128, "F", "C", 160, 0, 0), Sector(24, 128, "F", "C", 160, 0, 0)]
    sides = [Sidedef(0, 0, "-", "-", "-", 0), Sidedef(0, 0, "-", "-", "-", 1), Sidedef(0, 0, "-", "-", "-", 2)]

    def ld(flags=0, special=0, back=0xFFFF, front=0):
        return Linedef(0, 1, flags, special, 0, front, back)
    assert A.line_kind(ld(), sides, secs) == "wall"
    assert A.line_kind(ld(flags=A.ML_DONTDRAW), sides, secs) is None
    assert A.line_kind(ld(back=1), sides, secs) is None                      # same heights: not drawn
    assert A.line_kind(ld(back=2), sides, secs) == "step"                    # a floor change
    assert A.line_kind(ld(back=1, flags=A.ML_SECRET), sides, secs) == "wall"
    assert [A.line_kind(ld(special=s, back=1), sides, secs) for s in (26, 27, 28, 32, 33, 34)] == \
        ["blue", "yellow", "red", "blue", "red", "yellow"]
    assert A.line_kind(ld(special=11), sides, secs) == "exit"


def test_the_inks_come_from_the_palette():
    ink = A.map_inks(_palette())
    bg, text, hi, credit = palette_colours(_palette())
    assert (ink["background"], ink["wall"], ink["you"], ink["credit"]) == (bg, text, hi, credit)
    assert len({ink[k] for k in ("you", "red", "blue", "yellow", "exit", "wall", "step")}) == 7


# --------------------------------------------------------------------------------------------------------------------
# the menu's side
def test_the_main_menu_has_map_under_help_only_where_the_page_is():
    assert WR.menu_entries_for(WR.DEFAULT_MENU, False) == WR.DEFAULT_MENU
    assert WR.menu_entries_for(WR.DEFAULT_MENU, True) == ["DOOM ON FLIPJUMP", "", "NEW GAME", "HELP", "MAP", "EXIT"]


def test_menu_screen_pixels_with_the_page(e1m2):
    cfg = Config()
    colours = palette_colours(_palette())
    entries = WR.menu_entries_for(WR.DEFAULT_MENU, True)
    assert WR.menu_screen_pixels(cfg, colours, MAIN_MAP_SCR, 1, 0, automap=e1m2) == pixels(
        cfg.W, cfg.H, entries, entries.index("MAP"), colours)
    assert WR.menu_screen_pixels(cfg, colours, 0, 1, 0, automap=e1m2) == pixels(cfg.W, cfg.H, entries, 2, colours)
    assert WR.menu_screen_pixels(cfg, colours, HELP_GAME_SCR, 1, 1, automap=e1m2) == help_pixels(
        cfg.W, cfg.H, colours, automap=True)
    v = (608 << 16, 48 << 16)
    assert WR.menu_screen_pixels(cfg, colours, MAP_GAME_SCR, 1, 1, automap=e1m2, view=v) == A.pixels(e1m2, *v)
    for scr in (MAP_GAME_SCR, MAP_MENU_SCR, MAIN_MAP_SCR):           # no page, no picture
        with pytest.raises(ValueError):
            WR.menu_screen_pixels(cfg, colours, scr, 1, 1, view=v)


def test_the_help_lists_m_only_where_the_page_is():
    assert "M" not in help_key_names() and "M" in help_key_names(True)
    assert help_keycodes(True)["M"] == MAP_KEY == A.AUTOMAP_KEY == 0x6D and "M" not in help_keycodes()
    colours = palette_colours(_palette())
    assert help_pixels(160, 100, colours) != help_pixels(160, 100, colours, automap=True)
    assert menu_keys() == MENU_KEYS and menu_keys(True) == {**MENU_KEYS, 0x6D: "map"}


# (mode, scr, events, live) -> (mode, scr) with the page: every rule menu.menu_step adds for it
MAP_RULES = [
    ((0, 0, {"map"}, 1), (1, MAP_GAME_SCR)),                    # m in the world: the page
    ((0, 0, {"help", "map"}, 1), (1, HELP_GAME_SCR)),           # h is read first
    ((0, 0, {"esc", "map"}, 1), (1, MAIN_RESUME_SCR)),          # esc first
    ((1, MAP_GAME_SCR, {"map"}, 1), (0, 0)),                    # m closes the world's page to the world
    ((1, MAP_GAME_SCR, {"esc"}, 1), (0, 0)),                    # so does esc
    ((1, MAP_GAME_SCR, {"enter", "help", "up", "dn"}, 1), (1, MAP_GAME_SCR)),   # nothing else
    ((1, MAP_MENU_SCR, {"esc"}, 0), (1, MAIN_MAP_SCR)),         # the menu's page closes to MAP
    ((1, MAP_MENU_SCR, {"map"}, 1), (1, MAIN_MAP_SCR)),
    ((1, MAIN_MAP_SCR, {"enter"}, 0), (1, MAP_MENU_SCR)),
    ((1, MAIN_MAP_SCR, {"map"}, 0), (1, MAP_MENU_SCR)),
    ((1, MAIN_MAP_SCR, {"help"}, 0), (1, HELP_MENU_SCR)),
    ((1, MAIN_MAP_SCR, {"up"}, 0), (1, MAIN_HELP_SCR)),
    ((1, MAIN_MAP_SCR, {"dn"}, 0), (1, MAIN_EXIT_SCR)),
    ((1, MAIN_MAP_SCR, {"esc"}, 1), (0, 0)),                    # esc resumes a game in progress...
    ((1, MAIN_MAP_SCR, {"esc"}, 0), (1, MAIN_MAP_SCR)),         # ...and is no rule without one
    ((1, MAIN_HELP_SCR, {"dn"}, 0), (1, MAIN_MAP_SCR)),         # HELP's down reaches MAP
    ((1, MAIN_EXIT_SCR, {"up"}, 0), (1, MAIN_MAP_SCR)),         # EXIT's up reaches MAP
    ((1, 0, {"map"}, 0), (1, MAP_MENU_SCR)),                    # m on every main-menu item
    ((1, MAIN_HELP_SCR, {"map"}, 0), (1, MAP_MENU_SCR)),
    ((1, MAIN_EXIT_SCR, {"map"}, 0), (1, MAP_MENU_SCR)),
    ((1, MAIN_RESUME_SCR, {"map"}, 1), (1, MAP_MENU_SCR)),
    ((1, HELP_MENU_SCR, {"map"}, 0), (1, HELP_MENU_SCR)),       # the help ignores m
    ((1, 1, {"map"}, 0), (1, 1)),                               # so does the skill screen
]


@pytest.mark.parametrize("before, after", MAP_RULES)
def test_menu_step_with_the_page(before, after):
    mode, scr, ev, live = before
    assert menu_step(mode, scr, 1, ev, live, automap=True)[:2] == after


def test_without_the_page_m_is_no_rule_and_the_menu_is_e1m1s():
    """automap False (E1M1): "map" changes nothing anywhere, and HELP / EXIT step to each other as before"""
    for mode, scr, live in [(0, 0, 1), (1, 0, 0), (1, MAIN_HELP_SCR, 0), (1, MAIN_EXIT_SCR, 1), (1, MAIN_RESUME_SCR, 1)]:
        assert menu_step(mode, scr, 1, {"map"}, live) == menu_step(mode, scr, 1, set(), live)
    assert menu_step(1, MAIN_HELP_SCR, 1, {"dn"}, 0)[1] == MAIN_EXIT_SCR
    assert menu_step(1, MAIN_EXIT_SCR, 1, {"up"}, 0)[1] == MAIN_HELP_SCR


def test_program_cells():
    """the oracle's page states are the program's menu_scr 0 and amap 1 / 2 / 3; every other state is menu_scr"""
    assert [program_cells(s) for s in (MAP_GAME_SCR, MAP_MENU_SCR, MAIN_MAP_SCR, 0, MAIN_EXIT_SCR, 15)] == \
        [(0, 1), (0, 2), (0, 3), (0, 0), (MAIN_EXIT_SCR, 0), (15, 0)]


# --------------------------------------------------------------------------------------------------------------------
# E1M1 untouched: the page off emits nothing of it
SPAWN = type("Spawn", (), {"x": 1 << 16, "y": 2 << 16, "angle": 0})()


def test_the_page_off_emits_none_of_it():
    restart = WR.restart_lines(SPAWN, 0, [0], [5], 1, [([1], [0], [])] * len(WR.SKILLS))
    off = (WR._menu_lines(Config(), WadFile.from_path(ASSETS), list(WR.DEFAULT_MENU), WR.DEFAULT_MENU_SELECTED,
                          restart=restart)
           + WR.menu_state_lines(restart) + WR.standalone_key_lines() + list(WR.STANDALONE_SCRATCH_DECLS))
    text = "\n".join(off)
    for token in ("amap", "ev_map", "am_x", "mf_am", "mn_tomap", "kbm0", "menu_frame_map"):
        assert token not in text, token


def test_the_page_on_emits_it(e1m2):
    """the control for the test above: with the page, every one of those tokens is there"""
    restart = WR.restart_lines(SPAWN, 0, [0], [5], 1, [([1], [0], [])] * len(WR.SKILLS))
    on = (WR._menu_lines(Config(), WadFile.from_path(ASSETS), list(WR.DEFAULT_MENU), WR.DEFAULT_MENU_SELECTED,
                         restart=restart, automap=e1m2)
          + WR.standalone_key_lines(automap=True) + WR.AUTOMAP_STATE_DECLS + A.decls(e1m2))
    text = "\n".join(on)
    for token in ("amap", "ev_map", "am_x", "mf_am", "mn_tomap", "kbm0", "menu_frame_map"):
        assert token in text, token


def test_the_cold_block_goes_where_the_caller_puts_it(e1m2):
    """the emitter passes `cold` (the end of the last part): the page's producers leave the menu block -- one jump
    there -- and arrive in the caller's list whole"""
    restart = WR.restart_lines(SPAWN, 0, [0], [5], 1, [([1], [0], [])] * len(WR.SKILLS))
    args = (Config(), WadFile.from_path(ASSETS), list(WR.DEFAULT_MENU), WR.DEFAULT_MENU_SELECTED)
    inline = WR._menu_lines(*args, restart=restart, automap=e1m2)
    cold = []
    hot = WR._menu_lines(*args, restart=restart, automap=e1m2, cold=cold)
    assert cold and cold[0] == "mf_am:" and not any(ln in hot for ln in ("mf_am:", "mf_amap:"))
    assert sorted(hot + cold) == sorted(inline) and ";mf_am" in hot


def test_build_persists_amap_only_with_the_page():
    from doomfj.build import automap_persist
    assert automap_persist(map_cfg(Config(), "E1M2"), True) == ("amap",)
    assert automap_persist(map_cfg(Config(), "E1M2"), False) == () == automap_persist(Config(), True)
