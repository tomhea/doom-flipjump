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
    from doomfj.reference_model import GAME_RENDER_KW
    assert GAME_RENDER_KW.get("rt_depth_order") == "aprox"
