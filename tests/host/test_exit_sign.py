"""P11 (a) -- THE EXIT SIGN (doomfj.exitsign): a virtual decoration hung over the exit switch's alcove.

  * the PICTURE: centred on its thing, its lower edge `LIFT` above the alcove's ceiling; rim, plate and red letters
    only -- and the red, read back at the font's scale, spells the word (decoded from the pixels, not compared with
    the grid that built them);
  * the THING: appended LAST to E1M1's things (every wad index unchanged), only where the exit line is the one it was
    placed against (a wad whose line 407 differs gets none, another map none);
  * the WORLD ignores it (gamedata.NOT_THINGS) -- not solid, not a pickup -- yet it is the last DRAWABLE thing, drawn
    in the actor class (DRAW_ACTOR_TYPES) and never a monster (MONSTER_TYPES: never seen, never aimed);
  * the MODEL draws it: from the exit room, past the monster standing before the alcove, the sign's red reaches the
    picture where it projects and hiding it takes that away; and R9 for the actor class -- drawn as SCENERY (the
    B-gate) the same view loses the sign's columns behind the monster.
"""
from pathlib import Path

import pytest

from doomfj import exitsign as ES
from doomfj import gamedata as gd
from doomfj import reference_model as RMOD
from doomfj.config import GAME_CFG
from doomfj.reference_model import (DRAW_ACTOR_TYPES, GAME_RENDER_KW, MONSTER_TYPES, ReferenceModel, SimState,
                                    build_scene)
from doomfj.things import drawable_things
from doomfj.wad import Thing, WadFile, _records

ROOT = Path(__file__).resolve().parents[2]
MAP = "E1M1"


@pytest.fixture(scope="module")
def mw():
    return WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))


@pytest.fixture(scope="module")
def art():
    return WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))


def test_the_picture_is_centred_hung_and_spells_the_word():
    p = ES.exit_sign_picture()
    grid = [[None] * p.width for _ in range(p.height)]
    for x, col in enumerate(p.columns):
        assert [y for y, _v in col] == list(range(p.height)), "every column is opaque top to bottom"
        for y, v in col:
            grid[y][x] = v
    *_, floor, opening_top = ES.EXIT_SIGNS[MAP]
    assert p.leftoffset == p.width // 2
    assert floor + p.topoffset - p.height == opening_top + ES.LIFT, "the lower edge LIFT above the alcove's ceiling"
    assert {v for row in grid for v in row} == {ES.RED, ES.PLATE, ES.RIM}
    assert all(v == ES.RIM for v in grid[0] + grid[-1] + [r[0] for r in grid] + [r[-1] for r in grid])
    # the red, read back at the font's scale: every SCALE x SCALE block is all red or all not
    o, s = 1 + ES.PAD, ES.SCALE
    rows = []
    for gy in range(7):
        line = ""
        for gx in range((p.width - 2 * o) // s):
            block = {grid[o + gy * s + dy][o + gx * s + dx] == ES.RED for dy in range(s) for dx in range(s)}
            assert len(block) == 1, (gy, gx)
            line += "#" if block.pop() else "."
        rows.append(line)
    want = [".".join(ES.FONT[c][gy] for c in ES.WORD) for gy in range(7)]
    assert rows == want


def test_the_sign_is_appended_last_and_moves_no_wad_index(mw):
    raw = [Thing(*r) for r in _records(mw._map_lump(MAP, "THINGS").data, "<5h")]
    things = mw.things(MAP)
    assert things[:-1] == raw
    assert things[-1] == Thing(-380, 1296, 0, gd.EXIT_SIGN_TYPE, 7)


class _Moved:
    """a wad whose exit line is NOT the one the sign was placed against"""

    def __init__(self, wad, special=None, v1=None):
        self.wad, self.special, self.v1 = wad, special, v1

    def linedefs(self, m):
        lds = list(self.wad.linedefs(m))
        ld = lds[407]
        from dataclasses import replace
        lds[407] = replace(ld, special=self.special if self.special is not None else ld.special,
                           v1=self.v1 if self.v1 is not None else ld.v1)
        return lds

    def vertexes(self, m):
        return self.wad.vertexes(m)


def test_the_sign_is_bound_to_the_exit_line(mw):
    assert ES.virtual_things(mw, MAP) == [Thing(-380, 1296, 0, gd.EXIT_SIGN_TYPE, 7)]
    assert ES.virtual_things(_Moved(mw, special=0), MAP) == []
    assert ES.virtual_things(_Moved(mw, v1=mw.linedefs(MAP)[407].v2), MAP) == []
    assert ES.virtual_things(mw, "E1M2") == []


def test_the_world_ignores_it_and_the_renderers_draw_it(mw, art):
    from doomfj.world import World
    assert gd.EXIT_SIGN_TYPE in gd.NOT_THINGS
    tt = gd.THING_TYPES[gd.EXIT_SIGN_TYPE]
    assert not tt.solid and not tt.flags & gd.MF_SPECIAL
    assert all(t.type != gd.EXIT_SIGN_TYPE for t in World(mw, MAP).things)
    drawable = drawable_things(ReferenceModel(GAME_CFG), mw.things(MAP), art)[0]
    assert drawable[-1].type == gd.EXIT_SIGN_TYPE
    assert gd.EXIT_SIGN_TYPE in DRAW_ACTOR_TYPES and gd.EXIT_SIGN_TYPE not in MONSTER_TYPES


VIEW = (-200, 1296, 0x80000000)          # the exit room, facing west at the alcove, the room's monster before it


def _render(mw, art):
    rm = ReferenceModel(GAME_CFG)
    x, y, a = VIEW
    return rm.render_wall_frame(SimState(x << 16, y << 16, a, MAP), build_scene(mw, mw, MAP),
                                **{**GAME_RENDER_KW, "sprite_wad": art})


def _without_sign(mw, art, monkeypatch):
    """the same view with no sign at its SOURCE (a runtime thing cannot be hidden by thing_hidden: the model refuses
    a set that is not a skill's absent set, as fj can drop a runtime thing only that way)"""
    with monkeypatch.context() as m:
        m.setattr(ES, "EXIT_SIGNS", {})
        assert all(t.type != gd.EXIT_SIGN_TYPE for t in mw.things(MAP))
        return _render(mw, art)


def test_the_model_draws_the_sign_past_the_monster(mw, art, monkeypatch):
    with_sign, without = _render(mw, art), _without_sign(mw, art, monkeypatch)
    pal = art.playpal()
    diff = [i for i, (a, b) in enumerate(zip(with_sign, without)) if a != b]
    assert len(diff) > 300, len(diff)
    red = [i for i in diff if pal[with_sign[i]][0] > 2 * max(pal[with_sign[i]][1], pal[with_sign[i]][2], 20)]
    assert len(red) > 60, len(red)
    rows = {i // GAME_CFG.VIEW_W for i in diff}
    assert max(rows) < GAME_CFG.VIEW_H // 2, "the sign hangs above the view's middle"


def test_control_drawn_as_scenery_the_monster_cuts_it(mw, art, monkeypatch):
    """R9 for the actor class: the same view with the sign drawn as scenery (the B-gate) loses columns"""
    full = _render(mw, art)
    hid = _without_sign(mw, art, monkeypatch)
    n_full = sum(1 for a, b in zip(full, hid) if a != b)
    monkeypatch.setattr(RMOD, "DRAW_ACTOR_TYPES", MONSTER_TYPES)
    scenery = _render(mw, art)
    n_scenery = sum(1 for a, b in zip(scenery, hid) if a != b)
    assert n_scenery < n_full, (n_scenery, n_full)
