"""M8 -- the switch textures (doomfj.switches: DOOM's P_ChangeSwitchTexture) in the MODEL and the oracle's picture.

The rule, the World's two steps (`switch_doors` in the door phase, `switch_uses` on a use press), the restart, the
gates' hooks (monsters.MonsterPhase.switch_doors / switch_uses / switch_kw and `view_drop_kw`), and the picture
(reference_model.wall_tone_names / render_wall_frame(switch_on=)). E1M1 is untouched: no SWITCH_TEX, no cell, no tone.
tests/fj/test_switch_tex_fj.py runs the fj against the same `switches` steps.
"""
import math

import pytest

from doomfj import switches as SW
from doomfj.config import GAME_CFG, Config, map_cfg
from doomfj.doors import CLOSING, IDLE, OPENING
from doomfj.reference_model import GAME_RENDER_KW, ReferenceModel, SimState, build_scene, wall_tone_names
from doomfj.wad import WadFile
from doomfj.world import World

E1M1 = "tests/fixtures/freedoom_e1m1.wad"
E1M2 = "tests/fixtures/freedoom_e1m2.wad"


@pytest.fixture(scope="module")
def m2():
    return WadFile.from_path(E1M2)


@pytest.fixture(scope="module")
def m1():
    return WadFile.from_path(E1M1)


def _world(mw, name="E1M2"):
    w = World(mw, name)
    w.ws.p_usedown = 0                     # the level start holds use (G_PlayerReborn): a press needs it released
    return w


def _at(w, line):
    """the player at the centre of switch `line`'s box (the line's midpoint)"""
    s = next(s for s in w.switches if s.line == line)
    x0, y0, x1, y1 = s.box
    w.ws.px, w.ws.py = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
    return s


def _press(w, line):
    _at(w, line)
    w.tic({"use": True})
    w.tic({})


def test_e1m1_has_no_switch_textures(m1):
    assert map_cfg(Config(), "E1M1").SWITCH_TEX == 0 and not SW.switches_on("E1M1")
    w = World(m1, "E1M1")
    assert w.switches == [] and not any(f.name.startswith("sw_") for f in w.schema)
    assert w.switch_on() == frozenset()
    lds, sds, secs = m1.linedefs("E1M1"), m1.sidedefs("E1M1"), m1.sectors("E1M1")
    assert wall_tone_names(lds, sds, secs) == wall_tone_names(lds, sds, secs, switch_tex=False)
    with pytest.raises(AssertionError):
        wall_tone_names(lds, sds, secs, pressed=frozenset({407}))


def test_e1m2_switch_cells(m2):
    assert SW.switches_on("E1M2")
    w = World(m2, "E1M2")
    assert [s.line for s in w.switch_cells] == [34, 93, 1284, 1544, 1854, 1904]
    assert w.switch_sr == [] and w.layout.nswitch == 6 and w.layout.nswsr == 0
    assert [f.name for f in w.schema if f.name.startswith("sw_")] == ["sw_on"]
    assert w.switch_on() == frozenset()


def test_tones_follow_the_shown_texture(m2):
    lds, sds, secs = m2.linedefs("E1M2"), m2.sidedefs("E1M2"), m2.sectors("E1M2")
    p10 = wall_tone_names(lds, sds, secs)
    base = wall_tone_names(lds, sds, secs, switch_tex=True)
    # the level start: only the SW2 switch (1544, SW2CMT) wears the used tone
    assert {i: t for i, t in base.items() if p10.get(i) != t} == {1544: "#SWITCHON"}
    lines = [s.line for s in SW.map_switches(secs, lds, sds, m2.vertexes("E1M2"))]
    used = wall_tone_names(lds, sds, secs, switch_tex=True, pressed=frozenset(lines))
    assert {i: t for i, t in used.items() if base.get(i) != t} == {
        34: "#SWITCHON", 93: "#SWITCHON", 737: "#SWITCHON", 1284: "#SWITCHON", 1544: "#SWITCH",
        1854: "#SWITCHON", 1904: "#SWITCHON"}
    assert used[735] == used[1884] == "#SWITCH", "a switch line no use changes keeps its tone"


def test_every_e1m2_switch_latches_on_its_press_and_the_restart_clears(m2):
    w = _world(m2)
    seen = []
    for s in w.switch_cells:
        _press(w, s.line)
        seen.append(s.line)
        assert w.switch_on() == frozenset(seen), s
    assert list(w.ws.sw_on) == [1] * 6
    w.new_game()
    w.tic({})
    assert list(w.ws.sw_on) == [0] * 6 and w.switch_on() == frozenset()


def test_the_exit_swaps_with_the_level(m2):
    w = _world(m2)
    _at(w, 737)
    w.tic({"use": True})
    assert w.ws.g_leveldone and w.switch_on() == frozenset({737})
    assert w.switch_on(leveldone=0) == frozenset()


def test_a_held_use_or_a_dead_player_or_out_of_the_box(m2):
    w = _world(m2)
    s = _at(w, 34)
    w.ws.p_usedown = 1                     # use held since last tic: no press (P_UseLines' edge)
    w.tic({"use": True})
    assert w.switch_on() == frozenset()
    w = _world(m2)
    s = _at(w, 34)
    w.ws.px = (s.box[2] + 1) << 16         # one unit past the box
    w.tic({"use": True})
    assert w.switch_on() == frozenset()
    w = _world(m2)
    _at(w, 93)                             # a door switch takes the HELD use, alive only
    w.ws.p_dead = 1
    w.tic({"use": True})
    assert w.switch_on() == frozenset()


def test_a_door_switch_needs_a_door_at_rest(m2):
    """EV_DoDoor skips a door with a thinker: 1854's door 208 also opens by its own face (31)"""
    w = _world(m2)
    d = w.door_order.index(208)
    _at(w, 1854)
    w.ws.d_dir[d], w.ws.d_state[d] = OPENING, 2
    w.tic({"use": True})
    assert w.switch_on() == frozenset(), "a moving door: no swap"
    w.ws.d_dir[d], w.ws.d_state[d], w.ws.d_wait[d] = IDLE, w.door_nstates[208] - 1, 0
    w.tic({"use": True})
    assert w.switch_on() == frozenset({1854}), "a door at rest open: EV_DoDoor starts it, the line swaps"
    w = _world(m2)
    _at(w, 1854)
    w.ws.d_dir[d], w.ws.d_wait[d] = CLOSING, 0
    w.tic({"use": True})
    assert w.switch_on() == frozenset()


def test_a_floor_switch_needs_its_group_still(m2):
    w = _world(m2)
    s = _at(w, 1284)
    g = s.targets[0]
    w.ws.f_sub[g] = 1                      # the group moving (a W1 line of its tag, say)
    w.tic({"use": True})
    assert w.switch_on() == frozenset()


def test_sr_countdown_and_press():
    on, tm, sr = [0, 0, 0], [0, 0], [0, 2]
    SW.press(on, tm, sr, 2)
    SW.press(on, tm, sr, 1)
    assert on == [0, 1, 1] and tm == [0, SW.BUTTON_FRAMES]
    for _ in range(SW.BUTTON_FRAMES - 1):
        SW.countdown(on, tm, sr)
        SW.press(on, tm, sr, 2)            # pressed again while out: nothing (the timer is not restarted)
    assert on == [0, 1, 1] and tm == [0, 1]
    SW.countdown(on, tm, sr)
    assert on == [0, 1, 0] and tm == [0, 0], "BUTTONTIME later the SR line swaps back; the S1 one stays"


def test_the_gates_hooks_are_the_worlds(m2):
    """MonsterPhase.switch_doors / switch_uses take a gate's door and mover states and step the World's cells"""
    from doomfj.monsters import MonsterPhase, view_drop_kw
    ph = MonsterPhase(m2, "E1M2", 3)
    w = ph.world
    s = next(s for s in w.switch_cells if s.line == 1854)
    x0, y0, x1, y1 = s.box
    x16, y16 = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
    doors = {si: (0, IDLE, 0, 0) for si in w.door_order}
    ph.switch_doors({**doors, 208: (1, OPENING, 1, 0)}, True, x16, y16)
    assert ph.switch_kw() == {}
    ph.switch_doors(doors, True, x16, y16)
    assert ph.switch_kw() == {"switch_on": frozenset({1854})} and view_drop_kw(ph) == {"switch_on": frozenset({1854})}
    s = next(s for s in w.switch_cells if s.line == 1904)
    x0, y0, x1, y1 = s.box
    x16, y16 = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
    ng = len(w.floor_groups)
    sw = [0] * (2 * ng)
    sw[ng + s.targets[0]] = 1
    ph.switch_uses((((0, IDLE, 0, 0),) * len(w.lift_order), frozenset(), tuple(sw)), x16, y16)
    assert ph.switch_kw()["switch_on"] == frozenset({1854})
    ph.switch_uses((((0, IDLE, 0, 0),) * len(w.lift_order), frozenset(), (0,) * (2 * ng)), x16, y16)
    assert ph.switch_kw()["switch_on"] == frozenset({1854, 1904})
    assert ph.switch_state() == {"swpr": (0, 0, 0, 0, 1, 1)}
    assert ph.switch_kw(leveldone=1)["switch_on"] == frozenset({1854, 1904, 737})


def test_the_picture_changes_only_where_the_switch_is(m2):
    rm = ReferenceModel(GAME_CFG)
    sc = build_scene(m2, m2, "E1M2")
    v = m2.vertexes("E1M2")
    ld = m2.linedefs("E1M2")[34]
    a, b = v[ld.v1], v[ld.v2]
    mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
    L = math.hypot(b.x - a.x, b.y - a.y)
    px, py = mx + 48 * (b.y - a.y) / L, my - 48 * (b.x - a.x) / L           # 48 units in front, facing it
    ang = int((math.atan2(my - py, mx - px) % (2 * math.pi)) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
    st = SimState(int(px) << 16, int(py) << 16, ang, "E1M2")
    kw = dict(GAME_RENDER_KW, things=False)
    own = bytes(rm.render_wall_frame(st, sc, **kw))
    used = bytes(rm.render_wall_frame(st, sc, switch_on=frozenset({34}), **kw))
    assert sum(x != y for x, y in zip(own, used)) > 1000
    assert bytes(rm.render_wall_frame(st, sc, switch_on=frozenset({1904}), **kw)) == own, "out of view: no change"
    with pytest.raises(AssertionError):
        rm.render_wall_frame(st, sc, switch_on=frozenset({34}), **dict(kw, wall_tones=False))


# ---- rule 5: every gate render that passes the sink by hand passes the switches too -------------------------------
SWITCH_NA = "switch_on: N/A"


def _hand_sink_calls(src: str) -> list:
    """[(line, has_switch_on, exempt)] of the gates' render calls that pass `view_drop=` BY HAND (test_p8a_gates'
    scan) -- a call through `**view_drop_kw(...)` gets the switches with the sink (monsters.view_drop_kw)"""
    import ast
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        f = node.func
        if not (f.attr == "render_wall_frame" or (f.attr == "render" and ast.unparse(f.value) in
                                                  ("orc", "self.orc", "run.orc"))):
            continue
        if not any(k.arg == "view_drop" for k in node.keywords):
            continue
        text = "\n".join(lines[node.lineno - 2:node.end_lineno])
        out.append((node.lineno, any(k.arg == "switch_on" for k in node.keywords), SWITCH_NA in text))
    return out


GATES = {"scratchpad/gp/p2a_gate.py": 2, "scratchpad/gp/hurt_gate.py": 1, "scratchpad/gp/b0_scenarios.py": 1}


def test_every_hand_sink_gate_render_passes_the_switches():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for path, n in GATES.items():
        calls = _hand_sink_calls((root / path).read_text(encoding="utf-8"))
        assert len(calls) >= n, (path, calls)
        assert all(sw or na for _l, sw, na in calls), (path, calls)
    # R9: p2a_gate.picture (every hurt / fight / die frame) without the keyword is refused
    src = (root / "scratchpad/gp/p2a_gate.py").read_text(encoding="utf-8")
    old = '                      switch_on=fr.get("switches"))'
    assert src.count(old) == 1
    bad = src.replace(old, "                      )")
    assert not all(sw or na for _l, sw, na in _hand_sink_calls(bad))
