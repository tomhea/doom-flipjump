"""M7 P8a package V (docs/gp-final-plan.md 3.1 row V, 5) -- the gates' and v7's tools, on the host, before the packages
whose behaviour they test (A, K, I, C) are merged.

  * EVERY game-tier gate's world render passes the dying view's sink (`view_drop=`, or `**view_drop_kw(...)`): a
    static scan of the gates' render calls (rule 5: a gate that forgets it draws a dead frame from the standing eye
    and parts from a binary that sinks -- found by a build otherwise), with an R9 mutant of p2a_gate.picture and of
    m2_std_gate's mirror that must be refused;
  * the cells: `MonsterPhase.p8a_state` (P6+P7's `p_tnh` -- #123 F1 -- and section 4.1's p_vd, the knock cells,
    bar_src) are exactly the probe's cells at the binary's modes (names, counts, nibble widths; `mon_target` 2
    nibbles under infighting), each an OPTIONAL_GROUP, each in gatestate.STATE_NAMES;
  * the knock's plumbing, against a STAND-IN package K (the smallest P_XYMovement this test writes, monkeypatched):
    `MonsterPhase.move` runs the player's knock move after the walk exactly once (also when K runs it inside the
    walk), dead or alive, and reports where the walk landed; KnockTap's refusals; B0's injection -- the knock
    momentum with the pose that lands the binary's WALK on the model's walk -- reproduces the model's landing, and
    without the momentum it parts (R9);
  * p8a_lib: a scenario's status (N/A at modes without its rule, AWAITS a package not in the tree), and every control
    either refuses as Awaits or patches and restores what it patched;
  * scenarios_v2: the set's modes ride `use_sight_rule` (a set without them is "full" / "full": v6 replays as
    recorded), and O-V1's two criteria appear only at a model with the rule and FAIL their mutants.
"""
import ast
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GP = ROOT / "scratchpad" / "gp"
if str(GP) not in sys.path:
    sys.path.insert(0, str(GP))

# the game-tier gates whose WORLD renders must carry the sink: file -> the render calls expected (a scan that finds
# fewer calls than this is vacuous). Not scanned: b0.py (the static B0 of blocked27: no monsters, no death),
# probe.py's selftest renders (the pristine level start), census_lib (the drawn-population census: no run of a set dies)
GATE_RENDERS = {
    "scratchpad/gp/p2a_gate.py": 2,
    "scratchpad/gp/hurt_gate.py": 1,
    "scratchpad/gp/b0_scenarios.py": 4,
    "scratchpad/m2_std_gate.py": 4,
    "scratchpad/m3_gate.py": 2,
}
NA = "view_drop: N/A"


def render_calls(src: str) -> list:
    """[(line, has_view_drop, exempt)] of every world render call in a module: `X.render_wall_frame(...)`, and
    `<orc>.render(...)` on the gates' oracle (`orc`, `self.orc`, `run.orc`)"""
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        f = node.func
        if f.attr == "render_wall_frame" or (f.attr == "render" and ast.unparse(f.value) in ("orc", "self.orc",
                                                                                              "run.orc")):
            kw = any(k.arg == "view_drop" or (k.arg is None and "view_drop" in ast.unparse(k.value))
                     for k in node.keywords)
            text = "\n".join(lines[node.lineno - 2:node.end_lineno])
            out.append((node.lineno, kw, NA in text))
    return out


def refused(src: str) -> list:
    return [line for line, kw, na in render_calls(src) if not kw and not na]


def test_every_game_tier_gate_render_passes_view_drop():
    for path, n in GATE_RENDERS.items():
        src = (ROOT / path).read_text(encoding="utf-8")
        calls = render_calls(src)
        assert len(calls) >= n, "%s: %d render calls found, %d expected -- the scan is vacuous" % (path, len(calls), n)
        assert not refused(src), (path, refused(src))
        assert any(kw for _l, kw, _na in calls), path


def test_the_control_a_render_without_view_drop_is_refused():
    """R9: p2a_gate.picture (every hurt / fight / die frame) and m2_std_gate's mirror frame with the keyword dropped"""
    for path, old in (("scratchpad/gp/p2a_gate.py", "                      view_drop=fr.get(\"vdrop\", 0))"),
                      ("scratchpad/m2_std_gate.py", "                                          **view_drop_kw(mph),")):
        src = (ROOT / path).read_text(encoding="utf-8")
        assert src.count(old) == 1, path
        new = ")" if path.endswith("p2a_gate.py") else ""
        mutated = src.replace(old, "                      " + new if new else "")
        assert refused(mutated), path


def test_view_drop_kw_and_the_phase():
    from doomfj.monsters import MonsterPhase, view_drop_kw
    ph = MonsterPhase(mode="final", player="final")
    assert ph.view_drop() == 0 and view_drop_kw(ph) == {} and view_drop_kw(None) == {}
    ph.world.ws.p_vdrop = 17
    assert ph.view_drop() == 17 and view_drop_kw(ph) == {"view_drop": 17}
    full = MonsterPhase(mode="full", player="full")
    assert full.view_drop() == 0, "a mode that does not sink draws today's picture"


# ---- the cells -------------------------------------------------------------------------------------------------
def _probe():
    import probe as P
    return P


@pytest.mark.parametrize("modes", [("full", "full"), ("final", "push"), ("final", "final")])
def test_p8a_state_is_the_probes_cells(modes):
    from doomfj.monsters import MonsterPhase
    P = _probe()
    ph = MonsterPhase(mode=modes[1], player=modes[0])
    n = ph.world.layout.nmon
    cells = P.game_cells(13, 2, 2, n, 0, 0, modes=modes)
    st = ph.p8a_state()
    want = {"p_tnh"} | ({"p_vd"} if modes[0] == "final" else set()) \
        | ({"p_kmx", "p_kmy", "mkx", "mky", "mfx", "mfy", "kb_live", "pj_z"} if modes[1] in ("push", "final") else set()) \
        | ({"bar_src"} if modes[1] == "final" else set())
    assert set(st) == want, sorted(set(st) ^ want)
    # make every value as wide as its field can be, then each must fit its cell
    ws = ph.world.ws
    for f in ph.world.schema:
        if f.phase == "P8a" and f.name not in ("drop_x", "drop_y"):
            arr = getattr(ws, f.name)
            top = (1 << (f.bits - 1)) - 1 if f.signed else (1 << f.bits) - 1
            if f.array:
                for i in range(len(arr)):
                    arr[i] = -top - 1 if f.signed else top
            else:
                setattr(ws, f.name, -top - 1 if f.signed else top)
    for k, v in ph.p8a_state().items():
        c = cells[k]
        vals = v if isinstance(v, tuple) else (v,)
        assert len(vals) == c.count, (k, len(vals), c.count)
        assert all(0 <= x < 16 ** c.n for x in vals), (k, c.n, max(vals))
    tw = cells["mon_target"].n
    assert tw == (2 if modes[1] == "final" else 1)
    assert max(ph.state()["mon_target"]) < 16 ** tw
    import gatestate
    assert want <= set(gatestate.STATE_NAMES)
    for name in want:                                     # each an OPTIONAL_GROUP's (a binary without the rule)
        assert any(name in g for g in P.OPTIONAL_GROUPS), name


def test_the_p8a_groups_come_whole():
    P = _probe()
    assert frozenset({"p_kmx", "p_kmy", "mkx", "mky", "mfx", "mfy", "kb_live", "pj_z"}) in P.OPTIONAL_GROUPS
    for one in ("p_tnh", "p_vd", "bar_src"):
        assert frozenset({one}) in P.OPTIONAL_GROUPS, one


# ---- a stand-in package K: the smallest P_XYMovement for the player and the monsters ---------------------------
def real_k() -> bool:
    """package K is in the tree: the player's knock move is CombatMixin's own"""
    from doomfj import combat as C
    return "_player_knock_move" in vars(C.CombatMixin)


def real_a() -> bool:
    """package A is in the tree: a death think sinks the view"""
    from doomfj.world import KEYS, TicEvents, World
    w = World(player="final", monsters="full")
    w.damage_player(w.ws.p_health + 30, ("gate", 0), None, TicEvents(0))
    w._death_think({k: False for k in KEYS}, TicEvents(0))
    return w.ws.p_vdrop == 1


def _install_k(monkeypatch, inside_walk: bool = False):
    """CombatMixin._player_knock_move / World._monster_knock_move (DOOM's shape: no halving, a refused step zeroes, else
    friction 29/32 and the STOPSPEED stop) and their calls in the model's tic: after the walk, dead or alive -- or,
    `inside_walk`, at the end of `_player_move` (and after the death think).
    Once package K is merged (its `_player_knock_move` is the class's own) the REAL K is used: only `inside_walk`'s
    extra call is patched in -- a stand-in on top of K would knock twice in the model's tic"""
    from doomfj import combat as C
    from doomfj import gamedata as gd
    from doomfj import world as W
    if real_k():
        if inside_walk:
            orig_pm, orig_dt = C.CombatMixin._player_move, C.CombatMixin._death_think

            def pm_(self, keys, ev):
                orig_pm(self, keys, ev)
                if self._p_knock:
                    self._player_knock_move(ev)

            def dt_(self, keys, ev):
                orig_dt(self, keys, ev)
                if self._p_knock:
                    self._player_knock_move(ev)
            monkeypatch.setattr(C.CombatMixin, "_player_move", pm_)
            monkeypatch.setattr(C.CombatMixin, "_death_think", dt_)
        return

    def friction(v):
        return (v * 29) // 32

    def pkm(self, ev):
        ws = self.ws
        if not (ws.p_momx or ws.p_momy):
            return
        nx, ny = ws.px + ws.p_momx, ws.py + ws.p_momy
        if self.rm.try_move(self.scene_c, ws.px, ws.py, nx, ny):
            ws.px, ws.py = nx, ny
            if all(abs(v) < gd.STOPSPEED for v in (ws.p_momx, ws.p_momy)):
                ws.p_momx = ws.p_momy = 0
            else:
                ws.p_momx, ws.p_momy = friction(ws.p_momx), friction(ws.p_momy)
        else:
            ws.p_momx = ws.p_momy = 0

    def mkm(self, m, ev):
        return None
    monkeypatch.setattr(C.CombatMixin, "_player_knock_move", pkm, raising=False)
    monkeypatch.setattr(W.World, "_monster_knock_move", mkm, raising=False)
    if inside_walk:
        orig_pm, orig_dt = C.CombatMixin._player_move, C.CombatMixin._death_think

        def pm(self, keys, ev):
            orig_pm(self, keys, ev)
            if self._p_knock:
                self._player_knock_move(ev)

        def dt(self, keys, ev):
            orig_dt(self, keys, ev)
            if self._p_knock:
                self._player_knock_move(ev)
        monkeypatch.setattr(C.CombatMixin, "_player_move", pm)
        monkeypatch.setattr(C.CombatMixin, "_death_think", dt)
    else:
        orig = C.CombatMixin._player_phase

        def phase(self, keys, ev):
            orig(self, keys, ev)
            if self._p_knock:
                self._player_knock_move(ev)
        monkeypatch.setattr(C.CombatMixin, "_player_phase", phase)


def _push(ws, mx=6 << 16, my=0):
    ws.p_momx, ws.p_momy = mx, my


@pytest.mark.parametrize("inside_walk", [False, True])
def test_the_phase_knocks_once_after_the_walk(monkeypatch, inside_walk):
    _install_k(monkeypatch, inside_walk)
    from doomfj.monsters import MonsterPhase
    ph = MonsterPhase(mode="final", player="final")
    ws = ph.world.ws
    x0, y0, a0 = ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, ws.pangle
    _push(ws)
    ph.weapon({}, x0, y0, a0)
    x, y, _a = ph.move({}, x0, y0, a0)
    assert ph.walk_end == (x0, y0), "the walk (no key) landed where the frame began"
    assert (x - x0) & 0xFFFFFFFF == 6 << 16 and y == y0, "pushed 6 units east, ONCE"
    assert ws.p_momx == (6 << 16) * 29 // 32 and ph.last_knock is not None
    # the walk forward, then the knock: the walk's landing is reported, the pose is past it
    ph.weapon({"forward": True}, x, y, a0)
    x2, y2, _ = ph.move({"forward": True}, x, y, a0)
    assert ph.walk_end is not None and ph.walk_end != (x, y) and (x2, y2) != ph.walk_end


def test_the_corpse_slides(monkeypatch):
    _install_k(monkeypatch)
    from doomfj.monsters import MonsterPhase
    from doomfj.world import TicEvents
    ph = MonsterPhase(mode="final", player="final")
    ws = ph.world.ws
    ph.world.damage_player(ws.p_health + 30, ("gate", 0), None, TicEvents(0))
    x0, y0, a0 = ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, ws.pangle
    _push(ws, 0, 5 << 16)
    ph.weapon({}, x0, y0, a0, dead=1)
    x, y, _a = ph.move({"forward": True}, x0, y0, a0, dead=1)
    assert x == x0 and (y - y0) & 0xFFFFFFFF == 5 << 16, "dead: no walk, the knock still moves the corpse"


def test_without_knockback_the_move_is_unchanged(monkeypatch):
    _install_k(monkeypatch)
    from doomfj.monsters import MonsterPhase
    ph = MonsterPhase(mode="full", player="full")
    ws = ph.world.ws
    assert not ph.tap.ok and ph.tap.records == []
    x0, y0, a0 = ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, ws.pangle
    ph.weapon({}, x0, y0, a0)
    assert ph.move({}, x0, y0, a0) == (x0, y0, a0) and ph.walk_end is None


def test_the_tap_names_a_wall_refusal(monkeypatch):
    _install_k(monkeypatch)
    from doomfj.monsters import MonsterPhase
    ph = MonsterPhase(mode="final", player="final")
    ws = ph.world.ws
    x0, y0, a0 = ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, ws.pangle
    # push the player hard toward every direction until a wall refuses one
    found = False
    for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
        ws.px, ws.py = ph.world.ws.px, ph.world.ws.py
        _push(ws, dx * (29 << 16), dy * (29 << 16))
        k = len(ph.tap.records)
        for _ in range(40):
            ph.weapon({}, ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, a0)
            ph.move({}, ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, a0)
            if ws.p_momx == ws.p_momy == 0:
                break
        if ph.tap.wall_refusals(ph.tap.since(k)):
            found = True
            break
    assert found, "no wall refused a 29-unit push in any direction from the spawn"
    # R9: friction alone (a small push decaying to the STOPSPEED stop) is NOT a refusal
    ws.px, ws.py = x0, y0
    _push(ws, 0x1800, 0)
    k = len(ph.tap.records)
    for _ in range(8):                                    # 0x1800 * (29/32)^k falls under STOPSPEED at k = 5
        ph.weapon({}, ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, a0)
        ph.move({}, ws.px & 0xFFFFFFFF, ws.py & 0xFFFFFFFF, a0)
    assert ws.p_momx == 0 and not ph.tap.refusals(ph.tap.since(k))


def test_b0_injection_lands_the_walk_and_the_knock(monkeypatch):
    """B0's contract for one frame under knockback: the binary (its mirror: BinaryMirror.step with a phase) given the
    pose `b0_injection` makes from the WALK's landing and the frozen model's knock momentum lands on the model's
    pose. R9: the same frame without the momentum parts"""
    _install_k(monkeypatch)
    import scenarios_v2 as S
    from doomfj.monsters import KnockTap, MonsterPhase
    saved = (S.SIGHT_RULE, S.MONSTER_TICS, S.PLAYER_MODE, S.MONSTER_MODE)
    try:
        S.use_sight_rule({"sight_rule": "seen", "monster_tics": 2, "player_mode": "final", "monster_mode": "final"})
        w = S.new_world()
        tap = KnockTap(w)
        assert tap.ok
        _push(w.ws, 3 << 16, -(2 << 16))
        ws = w.ws
        pre, pre_doors, pre_movers = (ws.px, ws.py, ws.pangle), S.door_tuples(w), S.mover_state(w)
        knock = (ws.p_momx, ws.p_momy)
        kd = {"forward": True, "turn_left": True}
        k0 = len(tap.records)
        w.tic(kd)
        post = (ws.px, ws.py, ws.pangle)
        land = S.walk_landing(tap, k0, post)
        assert land[:2] != post[:2], "the knock moved the player past the walk's landing"
        inj, bk = S.b0_injection(w.rm, pre, land, kd)

        def binary(with_knock):
            ph = MonsterPhase(w.mw, w.mapname, w.ws.skill, rm=w.rm, mode="final", player="final")
            if with_knock:
                ph.world.ws.p_momx, ph.world.ws.p_momy = knock
            return S.BinaryMirror(S.new_world()).step(inj, bk, pre_doors, pre_movers, mph=ph)[0]
        assert binary(True) == (post[0], post[1], post[2] & 0xFFFFFFFF)    # plan_run's comparison
        assert binary(False)[:2] != (post[0], post[1]), "R9: without the momentum it parts"
    finally:
        S.SIGHT_RULE, S.MONSTER_TICS, S.PLAYER_MODE, S.MONSTER_MODE = saved


def test_b0_model_frames_carry_the_knock():
    import scenarios_v2 as S
    spec = importlib.util.spec_from_file_location("gp_b0_scenarios_v", GP / "b0_scenarios.py")
    b0s = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = b0s
    spec.loader.exec_module(b0s)
    src = Path(b0s.__file__).read_text(encoding="utf-8")
    assert '"knock": pre_knock' in src and '"p_kmx": fr["knock"][0] & M32' in src
    assert "mph.world.ws.p_momx, mph.world.ws.p_momy = fr[\"knock\"]" in src
    assert S.walk_landing(None, 0, (1, 2, 3)) == (1, 2, 3)


# ---- p8a_lib ---------------------------------------------------------------------------------------------------
def test_status_na_and_awaits():
    import p8a_lib as P8
    sc = {"rule": "knock", "pkg": ("K",)}
    assert P8.status(sc, "full", "full").startswith("n/a")
    st = P8.status(sc, "final", "final")
    assert st == "run" if P8.packages()["K"][0] else st.startswith("awaits package K")
    assert P8.status({"pkg": ()}, "full", "full") == "run"
    assert P8.rules("final", "push") == {"sink", "knock", "p8a"} and P8.rules("full", "full") == frozenset()
    assert P8.status({"rule": "p8a", "pkg": ("C",)}, "full", "full").startswith("n/a"), "blocked51's gate: no C rows"


def test_every_control_patches_and_restores_or_awaits():
    import p8a_lib as P8
    from doomfj import combat as C
    from doomfj import gamedata as gd
    from doomfj import world as W
    import probe as P

    def snap():
        return (dict(vars(C.CombatMixin)), dict(vars(W.World)), gd.FRICTION, gd.STOPSPEED,
                dict(P.Oracle.RENDER_KW))
    before = snap()
    for name in P8.CONTROLS:
        try:
            with P8.control(name):
                pass
        except P8.Awaits:
            pass
        assert snap() == before, name


def test_a_control_breaks_its_rule_on_a_stand_in(monkeypatch):
    """R9 of the controls themselves: on a stand-in package A (the death think sinks one unit), `no_sink` keeps the
    view standing and `sink_fast` sinks two"""
    from doomfj import combat as C
    import p8a_lib as P8
    if not real_a():                                      # package A merged: its real death think
        orig = C.CombatMixin._death_think

        def dt(self, keys, ev):
            orig(self, keys, ev)
            self.ws.p_vdrop = min(35, self.ws.p_vdrop + 1)
        monkeypatch.setattr(C.CombatMixin, "_death_think", dt)
    from doomfj.world import KEYS, TicEvents, World
    for ctl, want in ((None, 1), ("no_sink", 0), ("sink_fast", 2)):
        w = World(player="final", monsters="full")
        w.damage_player(w.ws.p_health + 30, ("gate", 0), None, TicEvents(0))
        if ctl is None:
            w._death_think({k: False for k in KEYS}, TicEvents(0))
        else:
            with P8.control(ctl):
                w._death_think({k: False for k in KEYS}, TicEvents(0))
        assert w.ws.p_vdrop == want, ctl


# ---- scenarios_v2: the set's modes; O-V1 ----------------------------------------------------------------------
def test_the_sets_modes_ride_use_sight_rule():
    import scenarios_v2 as S
    saved = (S.SIGHT_RULE, S.MONSTER_TICS, S.PLAYER_MODE, S.MONSTER_MODE)
    try:
        S.use_sight_rule({"sight_rule": "seen", "monster_tics": 2})
        assert (S.PLAYER_MODE, S.MONSTER_MODE) == ("full", "full"), "a set without modes (v1 .. v6) is full / full"
        w = S.new_world()
        assert (w.player, w.monsters) == ("full", "full")
        S.use_sight_rule({"sight_rule": "seen", "monster_tics": 2, "player_mode": "final", "monster_mode": "final"})
        w = S.new_world()
        assert (w.player, w.monsters) == ("final", "final") and w.monster_tics == 2
    finally:
        S.SIGHT_RULE, S.MONSTER_TICS, S.PLAYER_MODE, S.MONSTER_MODE = saved


def _metrics(fight, knock, model=True, infight=1, walls=1):
    base = {"name": "r", "census": False, "frames": 100, "dead": 0, "health": 50, "mkills": 9, "bkills": 0,
            "shotgun": 0, "totals": {"deaths": 0, "mon_shots": 1, "mon_melee": 1, "proj_spawns": 1, "pickups": 9,
                                     "level_done": 0},
            "doors_player": [1, 2, 3], "doors_monster": [], "move_key": 80, "strafe": 60, "moving": 80,
            "move_frames": 80, "dodges": 1, "threat_frames": 1, "cam_part": 0, "door_part": 0, "use_strafe": 0,
            "corpses_near_start": 0, "aftermath": False, "pops": [], "fight": fight, "knock": knock,
            "knock_model": model, "infight": infight, "knock_walls": walls, "knock_moves": 5}
    return [base]


def test_o_v1_criteria():
    import scenarios_v2 as S
    names = [n for n, _ok, _d in S.criteria(_metrics(False, False))]
    assert not any("infighting" in n or "knockback" in n for n in names), "v1 .. v6 validate as recorded"
    crit = {n.split()[1] if n.startswith(">=") else n: (ok, d) for n, ok, d in S.criteria(_metrics(True, True))}
    got = {n: ok for n, ok, _d in S.criteria(_metrics(True, True))}
    inf = next(n for n in got if "infighting" in n)
    kw = next(n for n in got if "knockback stopped by a wall" in n)
    assert got[inf] is True and got[kw] is True and crit
    bad = {n: ok for n, ok, _d in S.criteria(_metrics(True, True, infight=0, walls=0))}
    assert bad[inf] is False and bad[kw] is False, "R9: a set without them FAILS"
    na = {n: ok for n, ok, _d in S.criteria(_metrics(True, True, model=False, walls=0))}
    assert na[kw] is None, "no knock model (K not merged): n/a, not PASS"


def test_state_dump_applies_the_sets_model():
    src = (GP / "state_dump.py").read_text(encoding="utf-8")
    assert src.index("SV.use_sight_rule(doc)") < src.index("w0 = SV.new_world()")


def test_the_census_and_the_autopilot_read_the_drops_own_position():
    """the drop readers package 0 left (docs/gp-final-plan.md 3.0): census_lib's drop rows and the autopilot's drop
    goal read World.drop_pos, never the corpse's mon_x / mon_y"""
    cl = (GP / "census_lib.py").read_text(encoding="utf-8")
    seg = cl[cl.index("if ws.mon_drop[m] == 1:"):cl.index("for s in range(W.FIREBALL_POOL)")]
    assert "wd.drop_pos(m)" in seg and "PThing(self.syn_type(dl, \"drop\"), dx, dy)" in seg
    sv = (GP / "scenarios_v2.py").read_text(encoding="utf-8")
    assert 'yield ("drop", m), w.dropper[m], *w.drop_pos(m)' in sv
    assert 'if g[0] == "drop":\n            return w.drop_pos(g[1])' in sv


def _install_thrust(monkeypatch):
    """a stand-in `_thrust`: dmg * (FRACUNIT >> 3) * 100 // mass along +x (the angle is K's; the controls under test
    only scale, negate or drop what the thrust adds). Package K merged: its real `_thrust`"""
    from doomfj import combat as C
    if real_k():
        return

    def thrust(self, target, inflictor, source, dmg):
        if inflictor is None:
            return
        mass = 100 if target[0] == "player" else self.mon_info[target[1]].mass
        v = dmg * (1 << 13) * 100 // mass
        if target[0] == "player":
            self.ws.p_momx += v
        else:
            self.ws.mon_momx[target[1]] += v
    monkeypatch.setattr(C.CombatMixin, "_thrust", thrust)


def test_the_knock_controls_break_their_rule_on_a_stand_in(monkeypatch):
    """R9 of the K controls: on a stand-in K, `no_thrust` adds nothing, `thrust_sign` pushes the other way, `mass`
    gives a demon (mass 400) a mass-100 push"""
    _install_k(monkeypatch)
    _install_thrust(monkeypatch)
    import p8a_lib as P8
    from doomfj.world import TicEvents, World

    def hit(ctl, kind):
        w = World(player="final", monsters="push")
        m = next(i for i in range(w.layout.nmon) if w.ws.mon_active[i] and w.mon_info[i].name == kind)
        if ctl is None:
            w.damage_monster(m, 16, ("player", -1), ("player", -1), TicEvents(0))
        else:
            with P8.control(ctl):
                w.damage_monster(m, 16, ("player", -1), ("player", -1), TicEvents(0))
        return w.ws.mon_momx[m], w.ws.mon_momy[m]
    base = hit(None, "MT_POSSESSED")
    import math
    mag = math.hypot(*base)
    assert abs(mag - (16 << 13)) < 64, base                 # |16 * FRACUNIT/8| along the inflictor -> target angle
    assert hit("no_thrust", "MT_POSSESSED") == (0, 0)
    assert hit("thrust_sign", "MT_POSSESSED") == (-base[0], -base[1])
    demon = hit(None, "MT_SERGEANT")
    assert abs(math.hypot(*demon) - (16 << 13) / 4) < 64, demon         # mass 400: a quarter
    assert hit("mass", "MT_SERGEANT") == (4 * demon[0], 4 * demon[1])


def test_the_fight_controls_break_their_rule_on_a_stand_in(monkeypatch):
    """R9 of the I controls: on a stand-in I (a monster hit by a monster targets it unless its threshold runs),
    `no_switch` keeps the old target and `threshold_ignored` switches through a running threshold"""
    from doomfj import combat as C
    from doomfj import world as W
    import p8a_lib as P8
    orig = C.CombatMixin.damage_monster

    def dm(self, m, dmg, source, inflictor, ev):
        orig(self, m, dmg, source, inflictor, ev)
        if source and source[0] == "mon" and not self.ws.mon_threshold[m]:
            self.ws.mon_target[m], self.ws.mon_threshold[m] = 2 + source[1], 100
    monkeypatch.setattr(C.CombatMixin, "damage_monster", dm)
    monkeypatch.setattr(W.World, "target_alive", lambda self, m: True, raising=False)
    from doomfj.world import TicEvents, World

    def hit(ctl, threshold=0):
        w = World(player="final", monsters="final")
        a, b = [i for i in range(w.layout.nmon) if w.ws.mon_active[i]][:2]
        w.ws.mon_health[a] = 500
        w.ws.mon_target[a], w.ws.mon_threshold[a] = 1, threshold
        if ctl is None:
            w.damage_monster(a, 1, ("mon", b), ("mon", b), TicEvents(0))
        else:
            with P8.control(ctl):
                w.damage_monster(a, 1, ("mon", b), ("mon", b), TicEvents(0))
        return w.ws.mon_target[a], b
    t, b = hit(None)
    assert t == 2 + b
    assert hit("no_switch")[0] == 1
    assert hit(None, threshold=50)[0] == 1 and hit("threshold_ignored", threshold=50)[0] == 2 + b


def test_the_census_draws_its_sets_mode():
    """census_lib imports beside package C's GAME_RENDER_KW keys (its frozen copy refused them: every --validate and
    --plan with the census raised) and draws D3 a / b exactly at a player mode with world.compositor_d3"""
    import census_lib as CL
    from doomfj import world as W
    assert CL.Census().d3_kw in ({}, {"rt_rank": False, "exempt_barrels": False})
    if hasattr(W, "compositor_d3"):
        assert CL.Census(player="final", monsters="final").d3_kw == {"rt_rank": True, "exempt_barrels": True}
