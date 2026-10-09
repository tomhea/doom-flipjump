"""M7 P8a A -- THE DYING VIEW SINKS, in the model and the oracle (docs/gp-final-plan.md 1.1; O-A1 taken: S0).

P_DeathThink (p_user.c), after P_MovePsprites: `if (viewheight > 6*FRACUNIT) viewheight -= FRACUNIT; if (viewheight <
6*FRACUNIT) viewheight = 6*FRACUNIT;` then P_CalcHeight (viewz = z + viewheight), then the turn to the attacker. The
model keeps it as `p_vdrop` = 41 - viewheight: 0 at the level start, +1 each death-think tic, capped at 35
(VIEW_DROP_MAX), 0 again at the restart -- in the "final" player mode alone (world.player_sinks); "full" has no such
field and its dead view never moves.

The oracle (`render_wall_frame(view_drop=d)`) splits its eye in two: the GEOMETRY (wall spans, step faces, sprites)
projects from the sunk eye view_z(floor) - (d << 16); the plane SHADING (the FT1 band walk's ph = |plane_h - viewz|)
keeps the standing eye -- the band lists the fj bakes per eye class, which its landing keeps. Checked here by
recording the eye each half receives (the picture itself is the fj harness's: tests/fj/test_dead_eye_render_fj.py).

Each claim has a control that must fail it (docs/cr-rules.md R9)."""
import pytest

from doomfj import gamedata as gd
from doomfj import world as W
from doomfj.reference_model import DEAD_VIEWHEIGHT, VIEW_DROP_MAX, VIEWHEIGHT

NOKEYS = dict.fromkeys(W.KEYS, False)


def _dead(player="final", monsters="final"):
    w = W.World(skill=gd.SK_HARD, player=player, monsters=monsters)
    w.ws.p_dead, w.ws.p_health = 1, 0
    return w


def _sink_run(w, tics, keys=NOKEYS):
    out = []
    for _ in range(tics):
        w.tic(keys)
        out.append(w.ws.p_vdrop)
    return out


def test_the_numbers_are_dooms():
    assert (VIEWHEIGHT, DEAD_VIEWHEIGHT, VIEW_DROP_MAX) == (41, 6, 35)
    assert gd.VIEWHEIGHT == VIEWHEIGHT << 16


def test_the_view_sinks_35_steps_then_rests():
    w = _dead()
    assert w.ws.p_vdrop == 0
    got = _sink_run(w, 45)
    assert got == list(range(1, 36)) + [35] * 10, got
    # R9: a sink that stops one short (viewheight 7) or one late (5), or never starts, is not this run
    assert got != list(range(1, 35)) + [34] * 11
    assert got != list(range(1, 37)) + [36] * 9


def test_the_cap_holds_from_any_depth():
    """P_DeathThink's two lines from any viewheight: one unit down, never below 6 (the cap holds a poked 35)"""
    for start in (0, 1, 17, 34, 35):
        w = _dead()
        w.ws.p_vdrop = start
        w._death_think(NOKEYS, W.TicEvents(0))
        assert w.ws.p_vdrop == min(start + 1, VIEW_DROP_MAX), start


def test_only_the_dead_sink():
    w = W.World(skill=gd.SK_HARD, player="final", monsters="final")
    for t in range(60):
        w.tic({"forward": t % 9 < 5, "fire": t % 3 == 0, "turn_left": t % 7 == 0})
        assert w.ws.p_vdrop == 0 or w.ws.p_dead, t


def test_full_has_no_sink():
    """the "full" model (v6's) has no p_vdrop field and its death think is P7's to the tic"""
    w = _dead("full", "full")
    assert "p_vdrop" not in {f.name for f in w.schema}
    w2 = _dead("final", "full")
    for _ in range(40):
        w.tic(NOKEYS)
        w2.tic(NOKEYS)
        a = {f.name: getattr(w.ws, f.name) for f in w.schema if not f.array}
        b = {f.name: getattr(w2.ws, f.name) for f in w.schema if not f.array}
        assert a == b
    assert w2.ws.p_vdrop == VIEW_DROP_MAX


def test_the_order_is_psprites_drop_turn(monkeypatch):
    """DOOM's order inside P_DeathThink: the psprites see the old viewheight, the turn the new one"""
    w = _dead()
    w.ws.p_attacker = 1
    seen = []
    orig_wt, orig_turn = w._weapon_tics, w._turn_to_attacker
    monkeypatch.setattr(w, "_weapon_tics", lambda k, ev: (seen.append(("psprites", w.ws.p_vdrop)), orig_wt(k, ev)))
    monkeypatch.setattr(w, "_turn_to_attacker", lambda ev: (seen.append(("turn", w.ws.p_vdrop)), orig_turn(ev)))
    w.ws.p_vdrop = 4
    w._death_think(NOKEYS, W.TicEvents(0))
    assert seen == [("psprites", 4), ("turn", 5)], seen


def test_the_restart_stands_the_eye_up():
    w = _dead()
    _sink_run(w, 20)
    assert w.ws.p_vdrop == 20
    w.tic(dict(NOKEYS, use=True))                 # use while dead asks for the restart (and this tic sinks one more)
    assert w.ws.g_restart and w.ws.p_vdrop == 21
    w.tic(NOKEYS)                                 # the restart block, then a living tic
    assert w.ws.p_vdrop == 0 and not w.ws.p_dead
    assert w.level_start(w.ws.skill).p_vdrop == 0
    # R9: the restart writes p_vdrop because it is a schema field (restart_fields); without it the eye would stay
    assert "p_vdrop" in w.restart_fields


def test_new_game_mid_sink():
    w = _dead()
    _sink_run(w, 9)
    w.new_game(gd.SK_EASY)
    w.tic(NOKEYS)
    assert w.ws.p_vdrop == 0 and w.ws.skill == gd.SK_EASY


# ---- the oracle's split -------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def scene():
    from doomfj.reference_model import build_scene
    from doomfj.wad import WadFile
    mw = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
    return build_scene(mw, mw, "E1M1")


KW = dict(floor_texturing=False, wall_mode="W1R", floor_mode_ft1=True, wall_noise=True, plane_near=True, sky=True,
          near_steps=True, stack_steps=True, bbox_cull=True, degrade=True)


def _record(monkeypatch, rm, scene, d):
    """render at view_drop d, recording the eye each half was given: the plane shading's (every ph the band walk
    keys on, and the viewz `_render_planes_flat` / `_flat_row_colours` take) and the geometry's (wall_screen_span)"""
    from doomfj.reference_model import ReferenceModel, SimState, spawn_state
    plane_vz, geo_vz = set(), set()
    o_planes, o_rows, o_span = rm._render_planes_flat, rm._flat_row_colours, rm.wall_screen_span
    monkeypatch.setattr(rm, "_render_planes_flat",
                        lambda fb, cm, aw, fc, vz, *a, **k: (plane_vz.add(vz), o_planes(fb, cm, aw, fc, vz, *a, **k))[1])
    monkeypatch.setattr(rm, "_flat_row_colours",
                        lambda cm, aw, fc, vz, *a, **k: (plane_vz.add(vz), o_rows(cm, aw, fc, vz, *a, **k))[1])
    monkeypatch.setattr(rm, "wall_screen_span",
                        lambda c, f, vz, s: (geo_vz.add(vz), o_span(c, f, vz, s))[1])
    sp = spawn_state(scene.map_wad, "E1M1")
    fb = rm.render_wall_frame(SimState(sp.x, sp.y, sp.angle, "E1M1"), scene, view_drop=d, **KW)
    return fb, plane_vz, geo_vz


def test_the_oracle_splits_the_eye(monkeypatch, scene):
    from doomfj.reference_model import ReferenceModel
    from doomfj.config import GAME_CFG
    rm = ReferenceModel(GAME_CFG)
    standing = rm.view_z(0)                        # the spawn's sector floor is 0 on E1M1
    fb0, p0, g0 = _record(monkeypatch, rm, scene, 0)
    assert p0 == {standing} and g0 == {standing}
    fb35, p35, g35 = _record(monkeypatch, rm, scene, 35)
    assert p35 == {standing}, "the planes' band lists must keep the STANDING eye (S0)"
    assert g35 == {standing - (35 << 16)}, "the geometry must take the SUNK eye"
    assert fb35 != fb0, "a sunk eye changes the picture"


def test_view_drop_zero_is_todays_picture(scene):
    from doomfj.reference_model import ReferenceModel, SimState, spawn_state
    from doomfj.config import GAME_CFG
    rm = ReferenceModel(GAME_CFG)
    sp = spawn_state(scene.map_wad, "E1M1")
    st = SimState(sp.x, sp.y, (sp.angle + 0x30000000) & 0xFFFFFFFF, "E1M1")
    assert rm.render_wall_frame(st, scene, **KW) == rm.render_wall_frame(st, scene, view_drop=0, **KW)


def test_view_drop_is_bounded(scene):
    from doomfj.reference_model import ReferenceModel, SimState, spawn_state
    from doomfj.config import GAME_CFG
    rm = ReferenceModel(GAME_CFG)
    sp = spawn_state(scene.map_wad, "E1M1")
    st = SimState(sp.x, sp.y, sp.angle, "E1M1")
    for bad in (-1, 36):
        with pytest.raises(AssertionError):
            rm.render_wall_frame(st, scene, view_drop=bad, **KW)
    with pytest.raises(AssertionError):            # the split is the FT1 tier's (its band lists)
        rm.render_wall_frame(st, scene, view_drop=3, floor_texturing=True)


# ---- the fj wiring, behind world.player_sinks (the text itself runs in tests/fj/test_view_drop_fj.py) ---------------
def test_the_fj_pieces_are_behind_the_rule():
    from doomfj import build as B
    from doomfj import hurtcode as HC
    from doomfj import restartcode as RC
    from doomfj import wall_renderer as WR
    rows = list(range(2, 55))
    off, on = HC.turn_lines(rows), HC.turn_lines(rows, sink=True)
    assert off == HC.turn_lines(rows, sink=False)
    assert "p_vd" not in "\n".join(off)
    # the drop is the leaf's FIRST work (after the psprites the caller ran, before the turn), and the rest is P7's
    assert on[0] == off[0] == "dt_turn:" and on[len(on) - len(off) + 1:] == off[1:]
    assert any("hex.inc 2, p_vd" in ln for ln in on[:len(on) - len(off) + 1])
    assert HC.sink_decls() == ["dt_vmx: hex.vec 2, %d" % VIEW_DROP_MAX]
    assert RC.VIEW_PERSIST == B.VIEW_PERSIST == ("p_vd",)
    assert RC.view_decls() == ["p_vd: hex.vec 2, 0"] and RC.view_restart_lines() == ["    hex.zero 2, p_vd"]
    assert B.p8a_persist("final", "full") == ("p_vd",) and B.p8a_persist("full", "full") == ()
    assert "p_vd: hex.vec 2, 0" in B.p8a_persisted_decls(None)
    drop = WR.landing_drop_lines()
    assert drop[0] == "hex.if0 2, p_vd, lnd_vd_end" and drop[-1] == "lnd_vd_end:"


def test_the_restart_composition_follows_the_world():
    """wall_renderer.p6_restart_parts (the ONE composition the emitter and tests/fj/test_restart_fj.py share) writes
    p_vd exactly when the World it is given sinks -- the World p31_parts builds at the game tier's PLAYER_MODE"""
    from doomfj import wall_renderer as WR
    for player, want in (("final", True), ("full", False)):
        w = W.World(skill=gd.SK_HARD, player=player, monsters="full")
        common, skills = WR.p6_restart_parts(w)
        assert ("    hex.zero 2, p_vd" in common) is want, player
        assert not any("p_vd" in ln for sk in skills for ln in sk)
    assert WR.p6_restart_parts(None) == ([], [[], [], []])


def test_the_split_flag_is_the_gates_control(monkeypatch, scene):
    """reference_model.VIEW_DROP_SPLIT (die_gate's `band_eye` control flips it): False hands the planes the SUNK eye
    too -- the picture S0 must part from -- and True (the default) is the split"""
    from doomfj import reference_model as RMOD
    from doomfj.config import GAME_CFG
    assert RMOD.VIEW_DROP_SPLIT is True
    rm = RMOD.ReferenceModel(GAME_CFG)
    standing = rm.view_z(0)
    fb, p, g = _record(monkeypatch, rm, scene, 17)
    p, g = set(p), set(g)                          # (the next _record wraps these recorders: snapshot them)
    monkeypatch.setattr(RMOD, "VIEW_DROP_SPLIT", False)
    fb_x, p_x, g_x = _record(monkeypatch, rm, scene, 17)
    assert p == {standing} and p_x == g_x == g == {standing - (17 << 16)}
    assert fb_x != fb
