"""M8 C9: the exits a map adds, in the model (doomfj.doors' EXIT_SPECIALS / SECRET_EXIT_SPECIALS / WALK_EXIT_SPECIALS,
combat._use_lines, combat._walkover), on Freedoom's E1M3 (the S1 secret exit 51, line 993, beside its S1 exit 11) and
E1M8 (the W1 exit 52: eight lines round the boss pad, fused to four segments):

- E1M3: a use PRESS in 51's box ends the level AND sets g_secretexit (LEVEL COMPLETE shows SECRET EXIT); 11's ends it
  without; the restart forgets both; the next tic is frozen;
- E1M8: the player WALKING across the pad's side -- either way -- ends the level in the walk's own tic (the monsters'
  world does not run that tic, as on the press frame); a MONSTER crossing does not (52 is the player's only);
- the LEVEL COMPLETE picture of a gate (wall_renderer.menu_screen_pixels) takes the secret flag as a third stats field;
- E1M1, E1M2: no secret field, no W1 exit -- their schema and their exits unchanged.
CONTROLS (R9): the W1 exit tested one way only misses the back crossing; a secret flag that the plain exit sets parts.
"""
from pathlib import Path

import pytest

from doomfj import doors as D
from doomfj import gamedata as gd
from doomfj.wad import WadFile
from doomfj.world import KEYS, TicEvents, World
from tests.fixtures.map_variants import episode_wad

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
FIX = ROOT / "tests" / "fixtures"
needs_art = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")


@pytest.fixture(scope="module")
def art():
    return WadFile.from_path(str(ART))


def _keys(**on):
    k = dict.fromkeys(KEYS, False)
    k.update(on)
    return k


def test_e1m1_and_e1m2_are_unchanged():
    for m, wad in (("E1M1", "freedoom_e1m1.wad"), ("E1M2", "freedoom_e1m2.wad")):
        mw = WadFile.from_path(FIX / wad)
        w = World(mw, m)
        assert w.exit_walk == [] and w.layout.secexit == 0 and "g_secretexit" not in [f.name for f in w.schema]
        assert w.exit_secret == [0] and len(w.exit_boxes) == 1 and D.exit_walk_triggers(w.lds, w.cmap.vertexes) == []


# ---- E1M3: the secret exit --------------------------------------------------------------------------------------------
@needs_art
@pytest.mark.parametrize("line,secret", [(993, 1), (1367, 0)])
def test_a_press_in_an_exit_box_ends_the_level(art, line, secret):
    w = World(episode_wad(art, "E1M3"), "E1M3", player="final", monsters="final")
    ws = w.ws
    assert w.exit_box_lines == [993, 1367] and w.exit_secret == [1, 0]
    x0, y0, x1, y1 = w.exit_boxes[w.exit_box_lines.index(line)]
    ws.px, ws.py = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
    ws.p_usedown = 0
    ev = w.tic(_keys(use=True))
    assert ev.level_done and ws.g_leveldone == 1 and ws.g_secretexit == secret
    assert w.tic(_keys(forward=True)).frozen
    w._restart(TicEvents(0))
    assert (ws.g_leveldone, ws.g_secretexit) == (0, 0)


@needs_art
def test_control_a_secret_flag_the_plain_exit_sets_parts(art, monkeypatch):
    """R9: every exit box read as secret -- the plain exit's test above parts"""
    w = World(episode_wad(art, "E1M3"), "E1M3", player="final", monsters="final")
    w.exit_secret = [1, 1]
    ws = w.ws
    x0, y0, x1, y1 = w.exit_boxes[1]
    ws.px, ws.py = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
    ws.p_usedown = 0
    w.tic(_keys(use=True))
    assert ws.g_secretexit == 1                     # the (1367, 0) case's assertion fails under it


def test_the_gate_picture_takes_the_secret_flag():
    from doomfj.menu import LEVEL_DONE_SCREENS, level_done_pixels, stats_digits
    from doomfj.config import GAME_CFG
    from doomfj.wall_renderer import menu_screen_pixels
    colours = (0, 4, 176, 101)
    d = stats_digits(1, 2, 3, 4, 0, 5)
    scr = sorted(LEVEL_DONE_SCREENS)[0]
    plain = menu_screen_pixels(GAME_CFG, colours, scr, 0, 1, (2, d))
    assert plain == menu_screen_pixels(GAME_CFG, colours, scr, 0, 1, (2, d, 0))
    sec = menu_screen_pixels(GAME_CFG, colours, scr, 0, 1, (2, d, 1))
    assert sec != plain and sec == level_done_pixels(GAME_CFG.W, GAME_CFG.H, colours, 2, d, secret=True)


# ---- E1M8: the W1 exit -----------------------------------------------------------------------------------------------
@pytest.fixture
def e1m8(art):
    w = World(episode_wad(art, "E1M8"), "E1M8", player="final", monsters="final")
    ws = w.ws
    for k in range(w.layout.nmon):              # no monster in the way
        ws.mon_active[k] = ws.mon_shootable[k] = ws.mon_solid[k] = 0
    return w


def _walk_across(w, x, y, angle, frames=6):
    ws = w.ws
    ws.px, ws.py, ws.pangle = x << 16, y << 16, angle
    for f in range(frames):
        ev = w.tic(_keys(forward=True))
        if ev.level_done:
            return f, ev
    return None, None


@needs_art
@pytest.mark.parametrize("x,angle", [(1040, 0x80000000), (1010, 0)])
def test_walking_across_the_pad_ends_the_level_either_way(e1m8, x, angle):
    """x = 1024 is the pad's east side: walking west onto it from x 1040 and east off it from x 1010"""
    # y 270: the pad's east side runs y 256..384, and the SOLID torch (45, M8 C7) at (1056, 320) blocks y 288..352
    sk = e1m8.rm.check_position(e1m8.scene_c, x << 16, 270 << 16)
    if not sk[0]:
        pytest.skip("the pad's side is blocked here (%r)" % (sk,))
    f, ev = _walk_across(e1m8, x, 270, angle)
    assert f is not None and e1m8.ws.g_leveldone == 1
    assert e1m8.tic(_keys(forward=True)).frozen


@needs_art
def test_control_a_one_way_w1_exit_misses_the_back_crossing(e1m8, monkeypatch):
    """R9: the crossing read one way only (old centre on the low side) -- the walk east off the pad (x 1010 -> 1024+)
    does not end the level"""
    import doomfj.combat as CB
    real = CB.crossed
    monkeypatch.setattr(CB, "crossed", lambda trig, o, n, r: real(trig, o, n, r) and (
        trig not in e1m8.exit_walk or o[0 if trig[1] == "x" else 1] > (trig[2] << 16)))
    f, _ev = _walk_across(e1m8, 1010, 270, 0)                 # clear of the torch (above)
    assert f is None and e1m8.ws.g_leveldone == 0


@needs_art
def test_a_monster_never_fires_the_w1_exit(art):
    """E1M8's monsters are all Barons (not in the model yet), so on E1M3: a W1 exit segment laid across a monster's step
    -- the player's walk over it ends the level, the monster's does not"""
    w = World(episode_wad(art, "E1M3"), "E1M3", player="final", monsters="final")
    ws = w.ws
    m = next(k for k in range(w.layout.nmon) if ws.mon_active[k])
    x, y = ws.mon_x[m], ws.mon_y[m]
    w.exit_walk = [(0, "x", x + 5, y - 40, y + 40)]
    w._move_monster(m, x + 8, y, ws.mon_floorz[m], TicEvents(0))
    assert (ws.mon_x[m], ws.g_leveldone) == (x + 8, 0)
    w._walkover(x << 16, y << 16, (x + 8) << 16, y << 16, TicEvents(0))
    assert ws.g_leveldone == 1
