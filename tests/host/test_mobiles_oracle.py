"""M7 P5 (host): the ORACLE's mobiles -- `render_wall_frame(mobiles=[(x, y, lump)])` (docs/gp-p5-interface.md): the
fireballs and the blood drawn as runtime things of their leaf after the WAD's, scenery class, the base minimum height,
standing MISSILE_Z = 32 above the leaf's floor, never seen and never aimed.

  (a) no mobiles is the old picture: `mobiles=[]`, `None` and no keyword render the same bytes, and so does a mobile
      out of view (behind the player); the full v5 proof is scratchpad/gp/p5_mobiles_identity.py (60 frames against
      the UNMODIFIED oracle from git);
  (b) an imp's fireball in flight, in front of the player, DRAWS: the picture with `MonsterPhase.mobiles()` differs,
      while the seen set and the aim window do not move (a mobile is never seen, never aimed);
  (c) R9: the same fireball at the floor (MISSILE_Z 0) draws a different picture -- the height is what (b) drew;
  (d) every state a mobile can be in has its `...0` lump in the art (`monsters.mobile_lump`).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src")]
ART = ROOT / "assets/freedoom1.wad"
pytestmark = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad (the sprite art)")

IMP, POSE = 3, (848, 864, 0x40000000)           # an imp, and the player 192 units south of it, facing it


@pytest.fixture(scope="module")
def scene():
    """(phase, its MonsterViews, render(**kw): the game view) with the imp's fireball in flight and in view"""
    from doomfj import gamedata as gd
    from doomfj.config import GAME_CFG
    from doomfj.monsters import MonsterPhase, MonsterViews
    from doomfj.reference_model import GAME_RENDER_KW, ReferenceModel, SimState, build_scene
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(ART))
    ph = MonsterPhase(mode="full", player="fx")
    w, ws = ph.world, ph.world.ws
    ws.px, ws.py, ws.pangle = POSE[0] << 16, POSE[1] << 16, POSE[2]
    ws.mon_target[IMP] = 1
    ws.mon_state[IMP], ws.mon_tics[IMP] = gd.STATE_INDEX["S_TROO_ATK2"], 1
    for _ in range(6):                           # the spawn, then a few tics of flight toward the player
        ph.tic()
    assert any(ws.proj_active), "the imp fired"
    rm = ReferenceModel(GAME_CFG)
    mv = MonsterViews(rm, w.mw, w.mapname, art, w)
    sc = build_scene(w.mw, w.mw, w.mapname)
    st = SimState(ws.px, ws.py, ws.pangle, w.mapname)

    def render(**kw):
        return bytes(rm.render_wall_frame(st, sc, sprite_wad=art, thing_views=mv(ph, ws.px, ws.py),
                                          thing_positions=mv.positions(ph), **dict(GAME_RENDER_KW, **kw)))
    return ph, mv, render


def test_no_mobiles_is_the_old_picture(scene):
    ph, _mv, render = scene
    base = render()
    assert render(mobiles=[]) == base and render(mobiles=None) == base
    # a fireball 64 units BEHIND the player draws nothing
    x, y = POSE[0], POSE[1] - 64
    assert render(mobiles=[(x, y, "BAL1A0")]) == base


def test_a_fireball_in_view_draws_and_is_never_seen_or_aimed(scene):
    ph, mv, render = scene
    mob = ph.mobiles()
    assert mob and all(lump.startswith("BAL1") for _x, _y, lump in mob), mob
    s0, s1, a0, a1 = set(), set(), [0] * 17, [0] * 17
    at = mv.aim_things(ph)
    base = render(seen_out=s0, aim_things=at, aim_out=a0)
    drawn = render(mobiles=mob, seen_out=s1, aim_things=at, aim_out=a1)
    assert drawn != base, "the fireball in front of the player drew nothing"
    assert sum(p != q for p, q in zip(drawn, base)) >= 10
    assert (s0, a0) == (s1, a1), "a mobile moved the seen set or the aim window"


def test_the_control_a_fireball_on_the_floor_draws_elsewhere(scene, monkeypatch):
    """R9: MISSILE_Z is what puts the fireball 32 units up -- at 0 the same mobile paints other pixels"""
    from doomfj import reference_model as RM
    ph, _mv, render = scene
    mob = ph.mobiles()
    up = render(mobiles=mob)
    monkeypatch.setattr(RM, "MISSILE_Z", 0)
    assert render(mobiles=mob) != up


def test_every_mobile_state_has_its_lump():
    from doomfj import gamedata as gd
    from doomfj.config import GAME_CFG
    from doomfj.monsters import mobile_lump
    from doomfj.reference_model import ReferenceModel
    from doomfj.wad import WadFile
    art, rm, cache = WadFile.from_path(str(ART)), ReferenceModel(GAME_CFG), {}
    seen = set()
    for first in ("S_TBALL1", "S_TBALLX1", "S_BLOOD1", "S_PUFF1"):
        s = first
        while s != gd.S_NULL and s not in seen:
            seen.add(s)
            lump = mobile_lump(s)
            assert lump.endswith("0") and rm.art_of_lump(art, lump, cache) is not None, (s, lump)
            s = gd.STATES[s].next
    assert {"S_TBALL1", "S_TBALL2", "S_TBALLX3", "S_BLOOD3"} <= seen


# ---- M7 P6 (docs/gp-p67-interface.md 4.1, 5): the drops at z 0, the barrels by state, what the game removed
def _open_view():
    from doomfj.config import GAME_CFG
    from doomfj.reference_model import GAME_RENDER_KW, ReferenceModel, SimState, build_scene
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(ART))
    rm = ReferenceModel(GAME_CFG)
    from doomfj.world import World
    w = World(monsters="idle")
    sc = build_scene(w.mw, w.mw, w.mapname)

    def render(x, y, a, **kw):
        return bytes(rm.render_wall_frame(SimState(x << 16, y << 16, a, w.mapname), sc, sprite_wad=art,
                                          **dict(GAME_RENDER_KW, **kw)))
    return w, rm, art, render


def test_a_drop_stands_on_the_floor():
    """a 4-tuple mobile's z: a drop (z 0) draws, and draws other pixels than the same lump at MISSILE_Z (R9: the
    height is what the 4th element moves); a 3-tuple is P5's MISSILE_Z exactly"""
    _w, _rm, _art, render = _open_view()
    x, y = -416, 256
    base = render(x, y, 0)
    on_floor = render(x, y, 0, mobiles=[(x + 96, y, "SHOTA0", 0)])
    up = render(x, y, 0, mobiles=[(x + 96, y, "SHOTA0")])
    assert on_floor != base and up != base and on_floor != up
    assert render(x, y, 0, mobiles=[(x + 96, y, "SHOTA0", 32)]) == up


def test_barrel_views_and_removed_are_opt_in():
    """`barrel_views` / `thing_removed` absent, None or empty draw today's picture; a barrel in S_BEXP draws its
    BEXP frame (a different picture), a barrel removed is not drawn; naming a non-vanishable thing is refused"""
    from doomfj.monsters import MonsterViews
    w, rm, art, render = _open_view()
    mv = MonsterViews(rm, w.mw, w.mapname, art, w)
    import math
    found = None                                  # a barrel in view: removing it changes the picture
    for b, t in enumerate(w.barrel_things):
        for k in range(8):
            x, y = round(t.x + 96 * math.cos(k * math.pi / 4)), round(t.y + 96 * math.sin(k * math.pi / 4))
            if not w.rm.check_position(w.scene_c, x << 16, y << 16)[0]:
                continue
            a = ((k * 0x20000000) + 0x80000000) & 0xFFFFFFFF
            if render(x, y, a, thing_removed=[mv.bdi[b]]) != render(x, y, a):
                found = (b, x, y, a)
                break
        if found:
            break
    assert found, "no barrel in view from 96 units"
    b, x, y, a = found
    base = render(x, y, a)
    assert render(x, y, a, barrel_views=None, thing_removed=None) == base
    assert render(x, y, a, barrel_views={}, thing_removed=[]) == base
    assert render(x, y, a, barrel_views={mv.bdi[b]: "BAR1A0"}) == base       # S_BAR1's frame is the type's art
    assert render(x, y, a, barrel_views={mv.bdi[b]: "BEXPB0"}) != base
    assert render(x, y, a, thing_removed=[mv.bdi[b]]) != base
    decor = next(di for di, t in enumerate(mv.drawable) if t.type == 2028)
    with pytest.raises(AssertionError):
        render(x, y, a, thing_removed=[decor])
    # a RUNTIME pickup may be removed (it is not a skill's absent set): the oracle accepts and hides it
    rt_pick = next(di for di in mv.rt_pickups)
    render(x, y, a, thing_removed=[rt_pick])
