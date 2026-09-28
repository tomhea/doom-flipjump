"""M7 P2a.2 -- the exit switch's rule in ONE place (docs/gp-exit.md): `doomfj.doors.exit_boxes` is the
model's box, the model ends the level exactly on a use PRESS inside it (the edges, both axes), the
LEVEL COMPLETE screen's transitions (`menu_step`), and NEW GAME's reset of the two new cells."""
import pytest

from doomfj import doors as D
from doomfj import gamedata as gd
from doomfj import world as W
from doomfj.menu import LEVEL_DONE_SCR, menu_step
from doomfj.wad import WadFile

FIX = "tests/fixtures/freedoom_e1m1.wad"


@pytest.fixture(scope="module")
def world():
    return W.World(skill=gd.SK_HARD, strict=True)


def test_the_exit_box_is_linedef_407_inflated(world):
    mw = WadFile.from_path(FIX)
    lds, verts = mw.linedefs("E1M1"), mw.vertexes("E1M1")
    assert [k for k, ld in enumerate(lds) if ld.special in D.EXIT_SPECIALS] == [407]
    ld = lds[407]
    xs, ys = (verts[ld.v1].x, verts[ld.v2].x), (verts[ld.v1].y, verts[ld.v2].y)
    want = (min(xs) - D.USE_RANGE, min(ys) - D.USE_RANGE, max(xs) + D.USE_RANGE, max(ys) + D.USE_RANGE)
    assert D.exit_boxes(lds, verts) == [want] == world.exit_boxes


def test_the_model_exits_exactly_on_a_press_in_the_box(world):
    """edge probes: the model's P_UseLines against `in_use_box_fixed`, a fresh press each; and a
    held use never exits"""
    (x0, y0, x1, y1), = world.exit_boxes
    cx, cy = (x0 + x1) // 2 << 16, (y0 + y1) // 2 << 16
    pts = [(cx, cy)]
    for e in (x0 << 16, x1 << 16):
        pts += [(e + d, cy) for d in (-1, 0, 1)]
    for e in (y0 << 16, y1 << 16):
        pts += [(cx, e + d) for d in (-1, 0, 1)]
    start = world.ws.copy()
    hits = 0
    for x, y in pts:
        for held in (0, 1):
            world.ws = start.copy()
            world.teleport_player(x, y)
            world.ws.p_usedown = held
            ev = world.tic({"use": True})
            want = not held and D.in_use_box_fixed(world.exit_boxes[0], x, y)
            assert ev.level_done == want and world.ws.g_leveldone == int(want), (x - cx, y - cy, held)
            hits += want
    world.ws = start
    assert 0 < hits < len(pts)


def test_the_level_complete_screen_leads_to_the_main_menu():
    for ev in ({"enter"}, {"esc"}, {"esc", "enter"}):
        assert menu_step(1, LEVEL_DONE_SCR, 2, ev) == (1, 0, 2, None)
    for ev in (set(), {"up"}, {"dn"}):
        assert menu_step(1, LEVEL_DONE_SCR, 1, ev) == (1, LEVEL_DONE_SCR, 1, None)


def test_new_game_resets_the_exits_cells():
    from doomfj.wall_renderer import restart_lines
    spawn = type("S", (), {"x": 0, "y": 0, "angle": 0})()
    common, _skills = restart_lines(spawn, 1, [], [], 1, [([0], [], [])] * 3)
    assert "    hex.zero 1, lvdone" in common and "    hex.set 1, pusedn, 1" in common


def test_the_exits_cells_persist():
    from doomfj.build import STANDALONE_PERSIST
    from doomfj.wall_renderer import MENU_STATE_DECLS
    assert {"lvdone", "pusedn"} <= set(STANDALONE_PERSIST)
    assert "lvdone: hex.vec 1, 0" in MENU_STATE_DECLS and "pusedn: hex.vec 1, 1" in MENU_STATE_DECLS
