"""M8 -- THE SCROLLING WALL (special 48; doomfj.scrollcode) on the host: E1M1 untouched, the model's half, the gates.

  * E1M1's emitted pieces at E1M1's arguments are the ones they were: the seg's pass-2 call is the one line, the wnoise
    tables keep 801 keys, no new cell is declared, no fj constant is added -- E1M1's Config takes no WALL_SCROLL and
    its WAD has no special-48 line (the full emission's hashes are the integrator's emit_baseline);
  * E1M2: the map's Config scrolls, its scrolling lines are 1254 and 1338;
  * the ONE place the value is made (World.wall_scroll: leveltime's low byte on a scrolling map, else 0), and the gates'
    keyword (monsters.view_drop_kw carries it; MonsterPhase.wall_scroll);
  * the oracle: the slide moves pixels on E1M2 and only through those two lines, by exactly the slide in the W1R key
    of the calls it moves; a slide of 256 is none; E1M1 and a map whose Config is off draw the old picture (R9);
  * EVERY game-tier gate's world render passes the slide (`wall_scroll=`, or `**view_drop_kw(...)`, which carries it):
    the static scan of tests/host/test_p8a_gates.py over the same files, with an R9 mutant of p2a_gate.picture.
The fj half (the emitted wrap and the widened tables, RUN against the model with R9 mutants) is
tests/fj/test_wall_scroll_fj.py."""
import ast
import dataclasses
import importlib.util
from pathlib import Path

import pytest

from doomfj import config as C
from doomfj import reference_model as R
from doomfj import scrollcode as SC
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
E1M1 = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"
E1M2 = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
needs_e1m2 = pytest.mark.skipif(not E1M2.exists(), reason="needs tests/fixtures/freedoom_e1m2.wad")
ANG90 = 0x40000000
VIEW = (700, -1392, ANG90 // 2)       # E1M2: line 1254 (COMPBLUE) at an angle, other walls beside it


# ---- E1M1 untouched ------------------------------------------------------------------------------------------------
def test_e1m1_pieces_are_unchanged():
    assert SC.pass2_lines(False) == ["    stl.fcall seg_pass2_leaf, seg_ret2"]      # the line the seg block had
    g = C.GAME_CFG
    assert SC.wnoise_domain(g.VIEW_W, True, False) == g.VIEW_W + 1 + 640 == 801     # the old `_wn_dom`
    assert SC.wnoise_domain(g.VIEW_W, False, False) == g.VIEW_W + 1
    assert not SC.scroll_on(g, "E1M1") and not SC.scroll_on(C.Config(), "E1M1")
    assert C.map_cfg(g, "E1M1") == g and C.Config().WALL_SCROLL == 0
    assert "WALL_SCROLL" not in C.Config().constants(), "an fj constant would change every map's fj_consts"
    w = WadFile.from_path(E1M1)
    assert SC.scroll_lines(w.linedefs("E1M1")) == frozenset()


def test_the_emitter_routes_the_seg_call_through_scrollcode():
    """the seg block's pass-2 call exists once, through pass2_lines, and the scroll's three emitter sites are gated
    on `_scroll_on` (off at E1M1's arguments: the test above) -- a second, ungated copy would emit on E1M1"""
    src = (ROOT / "src" / "doomfj" / "wall_renderer.py").read_text(encoding="utf-8")
    assert src.count("stl.fcall seg_pass2_leaf, seg_ret2") == 0, "the pass-2 call text lives in scrollcode alone"
    assert src.count("_scrollcode.pass2_lines(_scrollcode.seg_scrolls(seg, _scroll_lds))") == 1
    assert "_scroll_lds = _scrollcode.scroll_lines(lds) if _scroll_on else frozenset()" in src
    assert "_wn_dom = _scrollcode.wnoise_domain(cfg.VIEW_W, bool(w1r_flag), _scroll_on)" in src
    assert "*(_scrollcode.DECLS if _scroll_on else [])," in src
    assert "_scroll_on = bool(w1r_flag and lines and standalone and _scrollcode.scroll_on(cfg, mapname))" in src


# ---- E1M2 ----------------------------------------------------------------------------------------------------------
@needs_e1m2
def test_e1m2_scrolls_lines_1254_and_1338():
    w = WadFile.from_path(E1M2)
    assert SC.scroll_on(C.GAME_CFG, "E1M2") and SC.scroll_on(C.Config(), "E1M2")
    assert SC.scroll_lines(w.linedefs("E1M2")) == {1254, 1338}
    assert SC.wnoise_domain(C.GAME_CFG.VIEW_W, True, True) == 1056


@pytest.fixture(scope="module")
def phases():
    from doomfj import gamedata as gd
    from doomfj.monsters import MonsterPhase
    out = {"E1M1": MonsterPhase(WadFile.from_path(str(E1M1)), "E1M1", gd.SK_HARD, mode="final", player="final")}
    if E1M2.exists():
        out["E1M2"] = MonsterPhase(WadFile.from_path(str(E1M2)), "E1M2", gd.SK_HARD, mode="final", player="final")
    return out


@needs_e1m2
def test_the_one_value_and_the_gates_keyword(phases, monkeypatch):
    from doomfj.monsters import view_drop_kw
    ph = phases["E1M2"]
    ws = ph.world.ws
    for lt, want in ((0, 0), (1, 1), (0xFF, 0xFF), (0x100, 0), (0x12345, 0x45), (0xFFFFF, 0xFF)):
        ws.leveltime = lt
        assert ph.world.wall_scroll() == want == ph.wall_scroll() == SC.wall_scroll_of(lt)
        assert view_drop_kw(ph) == ({"wall_scroll": want} if want else {})
    e1 = phases["E1M1"]
    e1.world.ws.leveltime = 0x45
    assert e1.world.wall_scroll() == 0 and view_drop_kw(e1) == {}
    # R9: E1M2 with its Config off slides nothing (a fresh world: the answer is cached per world)
    monkeypatch.setitem(C.MAP_CONFIG, "E1M2", {k: v for k, v in C.MAP_CONFIG["E1M2"].items() if k != "WALL_SCROLL"})
    ph.world.__dict__.pop("_wall_scrolls", None)          # the answer is cached per world: ask again
    assert ph.world.wall_scroll() == 0 and view_drop_kw(ph) == {}
    ph.world.__dict__.pop("_wall_scrolls", None)          # ... and leave no answer cached under the patched Config


# ---- the oracle -----------------------------------------------------------------------------------------------------
KW = dict(R.GAME_RENDER_KW, things=False)


def _render(rm, w, mapname, view, **kw):
    sc = R.build_scene(w, w, mapname, {})
    return rm.render_wall_frame(R.SimState(view[0] << 16, view[1] << 16, view[2], mapname), sc, **KW, **kw)


@needs_e1m2
def test_the_oracle_slides_only_the_scrolling_lines(monkeypatch):
    w = WadFile.from_path(E1M2)
    rm = R.ReferenceModel(C.GAME_CFG)
    calls = {}
    orig = R.ReferenceModel.w1r_runs

    def rec(wlen, x):
        calls.setdefault("cur", []).append(x)
        return orig(wlen, x)
    monkeypatch.setattr(rm, "w1r_runs", rec)
    pics = {}
    for s in (0, 3, 256):
        calls["cur"] = []
        pics[s] = _render(rm, w, "E1M2", VIEW, wall_scroll=s)
        calls[s] = calls["cur"]
    assert sum(a != b for a, b in zip(pics[0], pics[3])) > 100, "the slide moves the wall's pixels"
    assert pics[256] == pics[0], "a slide of 256 is none (the low byte)"
    assert len(calls[3]) == len(calls[0])
    diffs = {b - a for a, b in zip(calls[0], calls[3])}
    assert diffs == {0, 3}, diffs                  # the slid calls move by exactly the slide, the rest not at all
    # R9: the same picture with the two lines' special gone -- nothing slides
    lds = [ld if i not in (1254, 1338) else dataclasses.replace(ld, special=0)
           for i, ld in enumerate(w.linedefs("E1M2"))]
    monkeypatch.setattr(w, "linedefs", lambda name, _l=lds: _l)
    assert _render(rm, w, "E1M2", VIEW, wall_scroll=3) == _render(rm, w, "E1M2", VIEW)


@needs_e1m2
def test_the_oracle_ignores_the_slide_off_a_scrolling_map(monkeypatch):
    """R9: E1M2 with its Config off, and E1M1, draw the old picture whatever slide is passed"""
    rm = R.ReferenceModel(C.GAME_CFG)
    w = WadFile.from_path(E1M2)
    monkeypatch.setitem(C.MAP_CONFIG, "E1M2", {k: v for k, v in C.MAP_CONFIG["E1M2"].items() if k != "WALL_SCROLL"})
    assert _render(rm, w, "E1M2", VIEW, wall_scroll=3) == _render(rm, w, "E1M2", VIEW)
    w1 = WadFile.from_path(E1M1)
    v1 = (1056, -3616, ANG90)
    assert _render(rm, w1, "E1M1", v1, wall_scroll=7) == _render(rm, w1, "E1M1", v1)


# ---- the gates ------------------------------------------------------------------------------------------------------
def _p8a():
    spec = importlib.util.spec_from_file_location("_p8a_gates", ROOT / "tests" / "host" / "test_p8a_gates.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NA = ("view_drop: N/A", "wall_scroll: N/A")


def render_calls(src: str) -> list:
    """[(line, passes the slide, exempt)] of every world render call (test_p8a_gates' set of calls): the keyword
    `wall_scroll`, or a `**` whose text names wall_scroll or view_drop_kw (which carries it)"""
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        f = node.func
        if f.attr == "render_wall_frame" or (f.attr == "render" and ast.unparse(f.value) in ("orc", "self.orc",
                                                                                              "run.orc")):
            kw = any(k.arg == "wall_scroll" or (k.arg is None and any(t in ast.unparse(k.value)
                                                                        for t in ("wall_scroll", "view_drop_kw")))
                     for k in node.keywords)
            text = "\n".join(lines[node.lineno - 2:node.end_lineno])
            out.append((node.lineno, kw, any(n in text for n in NA)))
    return out


def refused(src: str) -> list:
    return [line for line, kw, na in render_calls(src) if not kw and not na]


def test_every_game_tier_gate_render_passes_the_slide():
    gates = _p8a().GATE_RENDERS
    assert len(gates) >= 6
    for path, n in gates.items():
        src = (ROOT / path).read_text(encoding="utf-8")
        calls = render_calls(src)
        assert len(calls) >= n, "%s: %d render calls found, %d expected -- the scan is vacuous" % (path, len(calls), n)
        assert not refused(src), (path, refused(src))
        assert any(kw for _l, kw, _na in calls), path


def test_the_control_a_render_without_the_slide_is_refused():
    """R9: p2a_gate.picture (every hurt / fight / die frame) and sight's seen render with the keyword dropped"""
    for path, old, new in (("scratchpad/gp/p2a_gate.py", 'wall_scroll=fr.get("wscroll", 0))', '_ws=fr.get("wscroll", 0))'),
                           ("src/doomfj/sight.py", '{"wall_scroll": world.wall_scroll()} if world.wall_scroll() else {}',
                            "{}")):
        src = (ROOT / path).read_text(encoding="utf-8")
        assert src.count(old) == 1, path
        assert not refused(src), path
        assert refused(src.replace(old, new)), path
