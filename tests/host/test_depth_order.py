"""M7 P3.3 (host): the oracle's D3 d -- `render_wall_frame(rt_depth_order=)` draws a leaf's runtime things nearest
first. On v5's R0-aftermath frame 96 (the census's worst: two monsters of one leaf overlapping on screen) the order
changes the picture, the aprox-distance key and the true view depth agree there, and GAME_RENDER_KW carries the
rule the fj implements."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scratchpad" / "gp"), str(ROOT / "scratchpad" / "12m")]


@pytest.fixture(scope="module")
def frame96():
    import scenarios_v2 as S
    doc = json.loads((ROOT / "scratchpad/gp/scenarios/combat_scenarios_v5.json").read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    run = next(r for r in doc["runs"] if r["name"] == "R0-aftermath")
    w = S.start_world(run["setup"])
    for s in run["keys"][:97]:
        w.tic(S.str_to_keys(s))
    return w


def _render(w, depth):
    from doomfj.reference_model import SimState
    hook = w.seen_hook
    ws, n = w.ws, w.layout.nmon
    pos = [(t.x, t.y) for t in hook.drawable]
    hidden = set()
    for m in range(n):
        pos[hook.views.mdi[m]] = (ws.mon_x[m], ws.mon_y[m])
        if not ws.mon_active[m]:
            hidden.add(hook.views.mdi[m])
    views = [None] * hook.views.n
    for m, v in hook._mviews(w).items():
        views[hook.views.mdi[m]] = v
    kw = dict(hook.kw, rt_depth_order=depth)
    return w.rm.render_wall_frame(SimState(ws.px, ws.py, ws.pangle, w.mapname), hook._scene(w), sprite_wad=hook.art,
                                  thing_positions=pos, thing_hidden=hidden, thing_views=views, **kw)


def test_depth_order_changes_the_overlap(frame96):
    listed, aprox, tz = (_render(frame96, d) for d in (False, "aprox", "tz"))
    assert listed != aprox, "depth order changed nothing on the census's worst frame (the control)"
    assert aprox == tz, "the aprox-distance key and the view depth disagree on the frame they were chosen by"


def test_the_game_render_setting_is_the_fj_rule():
    from doomfj.reference_model import GAME_RENDER_KW, HOSTED_RENDER_KW
    assert GAME_RENDER_KW.get("rt_depth_order") == "aprox"
    assert not HOSTED_RENDER_KW.get("rt_depth_order"), "the hosted tiers' fj walks index order"


def test_a_mode_that_cannot_emit_the_walk_is_refused():
    """B1 of the pre-review: the game tier's depth rule with a monster mode that emits no depth walk RAISES (it
    used to emit sim.thing_pass silently); the chase/decide modes take it, and an explicit False turns it off."""
    from doomfj import monstercode as MC
    for mode in ("idle", "wake"):
        with pytest.raises(AssertionError, match="cannot emit the depth walk"):
            MC.depth_walk(mode)
        assert MC.depth_walk(mode, False) is False
    assert all(MC.depth_walk(m) is True for m in MC.DEPTH_MODES)
    with pytest.raises(AssertionError, match="P_AproxDistance only"):
        MC.depth_walk("decide", "tz")


def test_a_misspelt_depth_order_fails(frame96):
    """F6 of the pre-review: render_wall_frame takes False/None/"aprox"/"tz"; anything else used to fall through
    to the aprox key"""
    with pytest.raises(AssertionError, match="rt_depth_order"):
        _render(frame96, "aprx")


def test_the_oracle_key_is_the_shared_aprox_distance():
    """F4 of the pre-review: one P_AproxDistance -- world's name is fixedpoint's function, and the oracle's depth
    key is it on the view position's signed integer part"""
    from doomfj import fixedpoint, world
    from doomfj.reference_model import aprox_depth_key
    assert world.aprox_distance is fixedpoint.aprox_distance
    assert aprox_depth_key((-3 << 16 | 0x8000) & 0xFFFFFFFF, 5 << 16, 7, -20) == fixedpoint.aprox_distance(10, -25)
    assert fixedpoint.aprox_distance(-10, 4) == 10 + 4 - 2
