"""M7 P8a package 0 (docs/gp-final-plan.md 3.0) -- THE INTERFACE COMMIT, on the host:

  * the modes: world.PLAYER_MODES + "final", MONSTER_MODES + "push", "final" -- each a superset of "full" (every
    pre-P8a one-rule helper and emitter mode tuple names it beside "full"), and the three new ONE-rule helpers
    (`player_sinks`, `knockback_on`, `infighting_on`) as section 3.0 states them;
  * the schema: section 4.1's fields, phase "P8a", declared exactly when their rule is on -- so a "full" World's
    schema, and every digest v6 recorded, is untouched -- and written by nobody yet: a "final" run equals a "full" run
    on every pre-P8a cell, tic for tic, with the new cells at 0;
  * the damage signatures (`damage_monster(m, dmg, source, inflictor, ev)`, `damage_player(dmg, source, inflictor,
    ev)`, `damage_barrel(b, dmg, source, ev)`): a STATIC check that every caller in src/, scratchpad/gp and tests/
    passes the new arity -- calls, lambdas and wrappers patched in their place -- and `_thrust` reached only when
    knockback_on, BEFORE the armor and the health;
  * `World.drop_pos` (the corpse's position for now) is the one reader of a drop's position; `gamedata.FRICTION` /
    `STOPSPEED`;
  * the fj hooks: each emitted only behind its rule (off: the text is P7's to the byte), and placed where section 3.0
    says -- the kb_go calls, every site's inflictor, the splice points.
Each check carries a control that must FAIL it (docs/cr-rules.md R9)."""
import ast
import inspect
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import world as W

ROOT = Path(__file__).resolve().parents[2]


# ---- the modes and their one-rule helpers -------------------------------------------------------------------------
def test_the_new_modes_follow_full():
    assert W.PLAYER_MODES == ("walk", "fire", "shoot", "hit", "fx", "full", "final")
    assert W.MONSTER_MODES == ("idle", "wake", "chase", "decide", "full", "push", "final")
    assert W.P8A_PLAYER_MODES == ("final",) and W.P8A_MONSTER_MODES == ("push", "final")


def test_every_pre_p8a_rule_treats_the_new_modes_as_full():
    """a P8a mode is "full" and more: every helper and emitter tuple that names "full" names them too"""
    from doomfj import damagecode, hurtcode, lootcode, monstercode, noisecode, restartcode
    from doomfj.barrelcode import barrels_on
    for f in (W.player_resolves, W.player_hears, W.player_bleeds, W.player_loots, W.player_mortal, barrels_on,
              hurtcode.hurt_on, lootcode.loot_on, restartcode.mortal, damagecode.damage_on, damagecode.fx_on):
        assert f("final") == f("full") is True, f.__name__
    assert "final" in noisecode.NOISE_PLAYER_MODES
    for m in W.P8A_MONSTER_MODES:
        assert W.monster_attacks_land(m) and m in monstercode.DEPTH_MODES, m
    assert [m for m in W.MONSTER_MODES if W.monster_attacks_land(m)] == ["full", "push", "final"]


def test_the_p8a_helpers_are_one_rule_each():
    pairs = [(p, m) for p in W.PLAYER_MODES for m in W.MONSTER_MODES]
    assert [p for p in W.PLAYER_MODES if W.player_sinks(p)] == ["final"]
    assert [m for m in W.MONSTER_MODES if W.infighting_on(m)] == ["final"]
    assert [(p, m) for p, m in pairs if W.knockback_on(p, m)] == [("final", "push"), ("final", "final")]
    # the fallback: "push" knocks without fighting
    assert W.knockback_on("final", "push") and not W.infighting_on("push")
    with pytest.raises(AssertionError):
        W.player_sinks("loot")


def test_a_p8a_monster_mode_needs_the_final_player():
    with pytest.raises(AssertionError, match="needs the player mode"):
        W.World(monsters="push", player="full")


# ---- the schema --------------------------------------------------------------------------------------------------
P8A_FIELDS = {   # section 4.1: name -> (bits, signed, count key, rule)
    "p_vdrop": (6, False, None, "sinks"), "p_momx": (32, True, None, "knock"), "p_momy": (32, True, None, "knock"),
    "mon_momx": (32, True, "nmon", "knock"), "mon_momy": (32, True, "nmon", "knock"),
    "mon_fx": (16, False, "nmon", "knock"), "mon_fy": (16, False, "nmon", "knock"),
    "drop_x": (16, True, "nmon", "knock"), "drop_y": (16, True, "nmon", "knock"),
    "proj_z": (16, True, "pool", "knock"), "bar_src": (6, False, "nbarrel", "fight"),
}


@pytest.fixture(scope="module")
def worlds():
    return {(p, m): W.World(skill=gd.SK_HARD, monsters=m, player=p, monster_tics=1)
            for p, m in (("full", "full"), ("final", "full"), ("final", "push"), ("final", "final"))}


def test_the_full_schema_is_untouched(worlds):
    """the "full" World's schema IS build_schema's with no P8a keyword -- v6's digests hash exactly these fields"""
    w = worlds[("full", "full")]
    assert w.schema == W.build_schema(w.layout)
    assert not [f.name for f in w.schema if f.phase == "P8a"]
    mt = next(f for f in w.schema if f.name == "mon_target")
    assert mt.bits == 1


@pytest.mark.parametrize("pair", [("final", "full"), ("final", "push"), ("final", "final")])
def test_each_rule_adds_its_cells(worlds, pair):
    w = worlds[pair]
    on = W.p8a_schema(*pair)
    lay = w.layout
    count = {None: 1, "nmon": lay.nmon, "pool": W.FIREBALL_POOL, "nbarrel": lay.nbarrel}
    got = {f.name: f for f in w.schema if f.phase == "P8a"}
    want = {n for n, (_b, _s, _c, rule) in P8A_FIELDS.items() if on[rule]} | ({"mon_target"} if on["fight"] else set())
    assert set(got) == want, (pair, sorted(got))
    for n, f in got.items():
        if n == "mon_target":
            assert (f.bits, f.signed, f.count) == (W._index_bits(lay.nmon + 2), False, lay.nmon)
            assert 2 + lay.nmon - 1 <= f.hi
            continue
        bits, signed, ck, _rule = P8A_FIELDS[n]
        assert (f.bits, f.signed, f.count) == (bits, signed, count[ck]), n
    assert 35 <= (got["p_vdrop"].hi if "p_vdrop" in got else 35)
    # the old fields keep their order: the P8a schema is the full one with fields inserted
    base = [f.name for f in worlds[("full", "full")].schema]
    assert [f.name for f in w.schema if f.name in base] == base


def _keys(t):
    k = dict.fromkeys(W.KEYS, False)
    k["fire"] = t % 3 != 2
    k["forward"] = (t // 20) % 2 == 0
    k["left"] = (t // 7) % 5 == 0
    return k


def test_a_final_run_is_a_full_run_until_the_packages_land():
    """the model in "final" / "final" (and the fallback "final" / "push"), tic for tic against "full" / "full" on a
    fight from the level start: every pre-P8a cell equal, every new cell still 0 -- and the thrust hook reached
    (only) in the P8a pairs, once per landed hit on the player or a monster"""
    runs = {}
    for pair in (("full", "full"), ("final", "push"), ("final", "final")):
        w = W.World(skill=gd.SK_HARD, player=pair[0], monsters=pair[1])
        calls = []
        w._thrust = lambda target, inflictor, source, dmg, calls=calls: calls.append((target, inflictor, source, dmg))
        hist = []
        for t in range(160):
            w.tic(_keys(t))
            hist.append({f.name: (list(getattr(w.ws, f.name)) if f.array else getattr(w.ws, f.name))
                         for f in w.schema})
        runs[pair] = (hist, calls, w)
    base, base_calls, _w0 = runs[("full", "full")]
    assert not base_calls, "the thrust ran in the full model"
    assert any(h["p_health"] < 100 for h in base) and any(min(h["mon_health"]) <= 0 for h in base), (
        "the run must fight: the player hurt and a monster killed")
    for pair in (("final", "push"), ("final", "final")):
        hist, calls, w = runs[pair]
        new = [f.name for f in w.schema if f.phase == "P8a" and f.name != "mon_target"]
        for t, (a, b) in enumerate(zip(base, hist)):
            assert {k: v for k, v in b.items() if k in a} == a, (pair, t)
            assert all(not any(b[n]) if isinstance(b[n], list) else b[n] == 0 for n in new), (pair, t)
        assert calls and all(c[0][0] in ("player", "mon") and c[1] is not None and c[3] > 0 for c in calls), calls[:3]


def test_the_thrust_comes_first(worlds):
    """damage_player / damage_monster call `_thrust` after the dead / not-shootable return and before the armor and
    the health; a dead target thrusts nothing; no inflictor is passed on as None"""
    w = W.World(skill=gd.SK_HARD, player="final", monsters="final", monster_tics=1)
    seen = []
    w._thrust = lambda tg, inf, src, dmg: seen.append((tg, inf, src, dmg, w.ws.p_armor, w.ws.p_health,
                                                       list(w.ws.mon_health)))
    ws = w.ws
    ws.p_armor, ws.p_armortype = 50, 1
    w.damage_player(30, ("mon", 2), ("mon", 2), W.TicEvents(0))
    assert seen[-1][:6] == (("player", -1), ("mon", 2), ("mon", 2), 30, 50, 100)
    w.damage_player(10, ("sector", 0), None, W.TicEvents(0))
    assert seen[-1][1] is None
    m = next(i for i in range(w.layout.nmon) if ws.mon_active[i])
    hp = ws.mon_health[m]
    w.damage_monster(m, 5, ("player", -1), ("bar", 0), W.TicEvents(0))
    assert seen[-1][:4] == (("mon", m), ("bar", 0), ("player", -1), 5) and seen[-1][6][m] == hp
    n = len(seen)
    ws.p_dead = 1
    w.damage_player(10, ("mon", 1), ("mon", 1), W.TicEvents(0))
    ws.mon_shootable[m] = 0
    w.damage_monster(m, 5, ("player", -1), ("player", -1), W.TicEvents(0))
    assert len(seen) == n, "a dead or unshootable target thrusts"


def test_drop_pos_is_the_corpse_for_now():
    w = W.World(skill=gd.SK_HARD, monster_tics=1)
    m = next(i for i in range(w.layout.nmon) if w.dropper[i] is not None)
    w.teleport_monster(m, 123, -456)
    assert w.drop_pos(m) == (123, -456)
    # the readers go through it (src): the pickup's touch, the gates' mobiles, the drop rows
    import doomfj.combat as C
    import doomfj.monsters as M
    assert "self.drop_pos(m)" in inspect.getsource(C.CombatMixin._touch_specials)
    assert "drop_pos(m)" in inspect.getsource(M.MonsterPhase.mobiles)
    assert "drop_pos(m)" in inspect.getsource(M.MonsterViews.rt_state)


def test_friction_and_stopspeed_are_dooms():
    assert gd.FRICTION == 0xE800 and gd.STOPSPEED == 0x1000
    from doomfj.fixedpoint import fixed_mul
    for mom in (1, 7, 0x1000, 0x12345, 30 * gd.FRACUNIT):
        assert fixed_mul(mom, gd.FRICTION, 8, 4) == mom * 29 // 32, mom   # FixedMul by 29/32, floored


def test_the_hooks_are_declared_empty():
    from doomfj import combat as C
    from doomfj import knockcode as KC
    w = W.World(skill=gd.SK_HARD, monster_tics=1)
    assert C.CombatMixin._thrust(w, ("player", -1), ("mon", 0), ("mon", 0), 10) is None
    assert C.CombatMixin._xy_move(w, ("player", -1), W.TicEvents(0)) is None
    assert KC.PERSIST == () and KC.player_move_lines() == [] and KC.monster_slot_lines(3) == []
    assert KC.go_lines()[-2:] == ["kb_go:", "    stl.fret kb_ret"]
    from doomfj import wall_renderer as WR
    assert WR.landing_drop_lines() == []


# ---- the damage signatures: every caller (rule 5: src/, scratchpad/, tests/) -------------------------------------
ARITY = {"damage_monster": 5, "damage_player": 4, "damage_barrel": 4}   # without self
SCAN = [ROOT / "src", ROOT / "scratchpad" / "gp", ROOT / "tests"]


def _callers(roots=SCAN):
    """(path, line, name, n): every call `x.damage_*(...)` (positional count), every lambda assigned to `x.damage_*`
    and every function patched in (patch(CM, "damage_*", fn) / a def passed there) -- its parameter count without
    self"""
    out = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if path.name.startswith("_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            defs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ARITY:
                    out.append((path, node.lineno, node.func.attr, len(node.args) + len(node.keywords)))
                elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                    for t in node.targets:
                        if isinstance(t, ast.Attribute) and t.attr in ARITY:
                            out.append((path, node.lineno, t.attr, len(node.value.args.args)))
                elif (isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
                      and any(isinstance(t, ast.Attribute) and t.attr in ARITY for t in node.targets)):
                    t = next(t for t in node.targets if isinstance(t, ast.Attribute) and t.attr in ARITY)
                    f = defs.get(node.value.id)
                    if f is not None:
                        out.append((path, node.lineno, t.attr, len(f.args.args)))
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "patch"
                      and len(node.args) == 3 and isinstance(node.args[1], ast.Constant)
                      and node.args[1].value in ARITY and isinstance(node.args[2], ast.Name)):
                    f = defs.get(node.args[2].id)
                    if f is not None:                         # a method wrapper: self first
                        out.append((path, node.lineno, node.args[1].value, len(f.args.args) - 1))
    return out


def test_every_damage_caller_passes_the_inflictor():
    """docs/gp-final-plan.md 3.0: the signatures take the inflictor (damage_barrel: the source), and EVERY caller --
    the model, the gates, the tests; a call, a recording lambda, a patched wrapper -- has the new arity"""
    from doomfj.combat import CombatMixin as CM
    assert list(inspect.signature(CM.damage_monster).parameters) == ["self", "m", "dmg", "source", "inflictor", "ev"]
    assert list(inspect.signature(CM.damage_player).parameters) == ["self", "dmg", "source", "inflictor", "ev"]
    assert list(inspect.signature(CM.damage_barrel).parameters) == ["self", "b", "dmg", "source", "ev"]
    found = _callers()
    by = {n: [c for c in found if c[2] == n] for n in ARITY}
    assert len(by["damage_player"]) >= 20 and len(by["damage_monster"]) >= 8 and len(by["damage_barrel"]) >= 4, (
        {n: len(v) for n, v in by.items()})
    bad = [("%s:%d" % (p.relative_to(ROOT), ln), n, k) for p, ln, n, k in found if k != ARITY[n]]
    assert not bad, bad
    # the model names a real inflictor at every one of its sites (None only for sector damage)
    src = inspect.getsource(CM)
    # (M7 P8a I: a fireball's impact on the player AND on a thing; the blast's source is bar_src's, its inflictor the
    # barrel's on the player and on every monster)
    assert src.count('("proj", s)') == 2 and src.count('("bar", b), ev)') == 2
    assert 'self.damage_player(dmg, ("sector", sec), None, ev)' in src


def test_control_an_old_arity_caller_is_found(tmp_path):
    """R9: a file with an old-arity call, an old recording lambda and an old patched wrapper -- each is reported"""
    (tmp_path / "old.py").write_text(
        "w.damage_player(5, ('mon', 1), ev)\n"
        "w.damage_monster(m, 5, ('player', -1), ev)\n"
        "w.damage_barrel = lambda c, dmg, ev: None\n"
        "def no_armor(self, dmg, source, ev):\n    pass\n"
        "patch(CM, 'damage_player', no_armor)\n", encoding="utf-8")
    found = _callers([tmp_path])
    assert sorted((n, k) for _p, _l, n, k in found) == [("damage_barrel", 3), ("damage_monster", 4),
                                                        ("damage_player", 3), ("damage_player", 3)]
    assert all(k != ARITY[n] for _p, _l, n, k in found)


# ---- the fj hooks: behind their rule, in their place --------------------------------------------------------------
def _calls_before(lines, call):
    """the lines immediately before each `stl.fcall <call>`"""
    return [lines[i - 3:i] for i, ln in enumerate(lines) if ln.strip() == "stl.fcall %s" % call]


def test_off_the_hooks_emit_nothing():
    """knock False is P7's text: the default of every hooked emitter is the knock-free one"""
    from doomfj import hurtcode as H
    from doomfj import monsterdecide as MD
    assert H.dp_lines() == H.dp_lines(False) and "kb_" not in "\n".join(H.dp_lines())
    assert MD.attack_leaf_lines(True) == MD.attack_leaf_lines(True, False)
    assert "kb_" not in "\n".join(MD.decide_leaves(True, full=True))


def test_dp_go_thrusts_before_the_armor():
    from doomfj import hurtcode as H
    on = H.dp_lines(knock=True)
    i = on.index("    stl.fcall kb_go, kb_ret")
    assert on[i - 3:i] == ["    hex.if0 3, p_hp, dp_out", "    hex.zero 2, kb_tg", "    hex.mov 2, kb_dm, dp_dmg"]
    assert i < on.index("    hex.if0 1, p_at, dp_dc")
    assert on[-3:] == ["    hex.zero 2, dp_src", "    hex.zero 1, kb_on", "    stl.fret dp_ret"]
    off = H.dp_lines()
    assert [ln for ln in on if "kb_" not in ln] == off


def test_every_site_names_its_inflictor():
    """the blast (the barrel), the fireball's impact (the missile, unmoved), md_attack (the attacker), dm_leaf (the
    player for a shot) -- each right before its damage call, only with knock"""
    from doomfj import damagecode as DC
    from doomfj import monsterdecide as MD
    from doomfj import projcode as PC
    from doomfj import knockcode as KC
    md = MD.attack_leaf_lines(full=True, knock=True)
    pre = _calls_before(md, "dp_go, dp_ret")
    assert len(pre) == 3 and all(p == KC.inflictor_lines("mm_x", "mm_y") for p in pre)   # the claw, the bite, a bullet
    pj = PC.pj_lines(nt=40, root="e1m1_mc", knock=True)
    pre = _calls_before(pj, "dp_go, dp_ret")
    assert pre == [KC.inflictor_lines("pw_x + 4*dw", "pw_y + 4*dw")]
    assert "kb_" not in "\n".join(PC.pj_lines(nt=40, root="e1m1_mc"))
    w = W.World(skill=gd.SK_HARD, monster_tics=1)
    keys, of = DC.profiles(w, gib=True)
    leaf = DC.leaf_lines(keys, fx=True, full=True, knock=True)
    i = leaf.index("    stl.fcall kb_go, kb_ret")
    j = leaf.index("  dm_kbp:")
    assert leaf[j + 1:j + 4] == KC.inflictor_lines("viewx + 4*dw", "viewy + 4*dw") and j < i
    assert leaf.index("    hex.if0 3, dm_hp, dm_out") < j and i < leaf.index("    hex.sub_shifted 3, 2, dm_hp, dm_dmg, 0")
    assert leaf[-2:] == ["    hex.zero 1, kb_on", "    stl.fret dm_lret"]
    assert DC.leaf_lines(keys, fx=True, full=True) == [ln for ln in leaf if ln not in (
        "    hex.zero 1, kb_on",) and not ln.startswith(("  dm_kb", "    stl.fcall kb_go", "    hex.mov 2, kb_dm",
                                                       "    hex.set 1, kb_on", "    hex.mov 4, kb_i",
                                                       "    hex.if_flags dm_melee, 4, dm_kbp"))]
    go = DC.go_lines(w.schema, list(range(w.layout.nmon)), of, knock=True)
    for m in range(w.layout.nmon):
        k = go.index("  dmg%d:" % m)
        nxt = next(x for x in range(k, len(go)) if go[x] == "    stl.fcall dm_leaf, dm_lret")
        assert go[nxt - 1] == "    hex.set 2, kb_tg, %d" % (m + 1)


def test_the_blast_names_the_barrel():
    from doomfj import barrelcode as BC
    from doomfj import knockcode as KC
    w = W.World(skill=gd.SK_HARD, monster_tics=1)
    rt = list(range(w.layout.nmon))
    on = BC.blast_lines(w, slot_rt=rt, knock=True)
    calls = [i for i, ln in enumerate(on) if ln.strip().startswith("stl.fcall dp_go") or
             ln.strip().startswith("stl.fcall dmg")]
    assert len(calls) == 1 + w.layout.nmon
    assert all(on[i - 3:i] == KC.inflictor_lines("bl_px", "bl_py") for i in calls)
    assert [ln for ln in on if "kb_" not in ln] == BC.blast_lines(w, slot_rt=rt)


def test_the_splice_points_are_wired_behind_their_rules():
    """the emitter's plan, read off its source (as test_p5_splice does): kb_go and the decls behind `_KNOCK`, the
    player's knock move after simmv_done, the landing's drop after dsc_done behind `_SINK`, every switch from its
    ONE rule; p32a_slot's splice right after the "not active" skip"""
    from doomfj import monstercode as MC
    from doomfj import wall_renderer as WR
    src = inspect.getsource(WR.emit_wall_renderer)
    for needle in ('_SINK = bool(_LOOT and _W8.player_sinks(PLAYER_MODE))',
                   '_KNOCK = bool(_LOOT and _W8.knockback_on(PLAYER_MODE, MONSTER_MODE))',
                   '_FIGHT = bool(_LOOT and _W8.infighting_on(MONSTER_MODE))',
                   '+ (_knockcode.go_lines() if _KNOCK else [])',
                   '*(_knockcode.decls() if _KNOCK else [])',
                   'knock_move=_knockcode.player_move_lines() if _KNOCK else ()',
                   '"dsc_done:"]\n',
                   'if _SINK:\n        pass1 += landing_drop_lines()'):
        assert needle in src, needle
    assert src.index('"dsc_done:"]') < src.index("pass1 += landing_drop_lines()")
    lines = WR._standalone_input_lines(True, weapon_bar=["BAR"], knock_move=["KNOCK"])
    i = lines.index("simmv_done:")
    assert lines[i + 1:i + 3] == ["KNOCK", "BAR"]
    assert "KNOCK" not in WR._standalone_input_lines(True, weapon_bar=["BAR"])
    slot = dict(t=0, x=0, y=0, rj="rj0", see_idx=1, see_tics=1)
    w = W.World(skill=gd.SK_HARD, monster_tics=1)
    off = MC.p32a_slot(3, schema=w.schema, **slot)
    assert MC.p32a_slot(3, schema=w.schema, knock=True, **slot) == off     # the splice is empty until K
    from doomfj import knockcode as KC
    orig = KC.monster_slot_lines
    try:
        KC.monster_slot_lines = lambda m: ["    KNOCK %d" % m]
        on = MC.p32a_slot(3, schema=w.schema, knock=True, **slot)
    finally:
        KC.monster_slot_lines = orig
    k = on.index("    KNOCK 3")
    assert on[k - 1] == "    hex.if0 1, mon_active + 3*dw, mw3_next" and on[:k] + on[k + 1:] == off
