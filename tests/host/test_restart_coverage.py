"""M7 P7 -- the restart's wiring, on the host (docs/gp-p67-interface.md 4.4; the VALUES half -- every persisted cell
back to the model's level start, run in fj -- is tests/fj/test_restart_fj.py).

  * P7's cells (`g_skill`, `g_rs`, `lvtime`; doomfj.restartcode) persist (build.GAME_PERSIST in persist_labels), are
    declared ONCE, with the standalone globals the restore set re-attaches, at the plan's widths;
  * NEW GAME and the restart on use after death run ONE sequence (`restartcode.call_lines`) into the same fcall'd
    routines -- and a menu that inlined its own copy of a skill's block is told apart;
  * nothing in the composed restart writes a DEVICE SHADOW (`pal_cur`, `hud_s`, `hud_full`) -- with the P5 line that
    did as the control;
  * the frame order: the restart on use at the world frame's start, before the frozen-level guard and the door tic;
    `lvtime` +1 inside the frozen-level guard, after the effects;
  * the P6 INTEGRATION HOOKS: while packages B / C have not landed, none of their names persist; once a module of
    theirs exists, its PERSIST must be wired into persist_labels (this test fails until it is), and the level-start
    transcription of section 4.5 must equal package A's units.
"""
import importlib.util
import inspect
import re

import pytest

from doomfj import build as B
from doomfj import gamedata as gd
from doomfj import restartcode as RC
from doomfj import wall_renderer as WR
from doomfj import world as W
from doomfj.selfreset import decl_words

SPAWN = type("Spawn", (), {"x": 1 << 16, "y": 2 << 16, "angle": 0})()


def _restart(**kw):
    return WR.restart_lines(SPAWN, 1, [0, 1], [5, 6], 2,
                            [([1, 0], [0, 0], [1]), ([0, 2], [0, 0], [0]), ([1, 2], [0, 0], [1])], **kw)


def _persist():
    return B.persist_labels(standalone=True, doors=True, moving_things=WR.TIERS["game"]["moving_things"])


# ---- the cells ---------------------------------------------------------------------------------------------------
def test_p7s_cells_persist_and_are_declared_once_at_the_plans_widths():
    assert B.GAME_PERSIST == RC.PERSIST == ("lvtime", "g_rs", "g_skill")
    assert set(RC.PERSIST) <= set(_persist())
    assert not set(RC.PERSIST) & set(B.persist_labels(standalone=False, doors=True, moving_things=True))
    widths = {}
    for d in WR.STANDALONE_SCRATCH_DECLS:
        name, words = decl_words(d)
        assert name not in widths, "declared twice: %s" % name
        widths[name] = words // 2
    assert {n: widths[n] for n in RC.PERSIST} == {"lvtime": 4, "g_rs": 1, "g_skill": 1}
    assert RC.P6_NIBBLES["lvtime"] == 4 and RC.P6_NIBBLES["g_rs"] == 1
    # g_skill boots at the boot skill (the image is that skill's level start)
    assert "g_skill: hex.vec 1, %d" % WR.SKILLS.index(WR.BOOT_SKILL) in WR.MENU_STATE_DECLS
    # ... and the game screen's list does not declare them a second time (m5_setfile adds both lists)
    from doomfj.wad import WadFile
    gs = {decl_words(d)[0] for d in B.game_screen_persisted_decls(WadFile.from_path("tests/fixtures/freedoom_e1m1.wad"))}
    assert not gs & set(RC.PERSIST)


def test_the_restart_zeroes_p7s_cells_and_keeps_the_skill():
    common, skills = _restart()
    assert "    hex.zero 4, lvtime" in common and "    hex.zero 1, g_rs" in common
    assert not any("g_skill" in ln for ln in common + [ln for s in skills for ln in s])
    assert common[0] == "restart_common:" and common[-1] == "    stl.fret rs_ret"


# ---- one sequence ------------------------------------------------------------------------------------------------
def test_new_game_and_the_restart_on_use_run_one_sequence():
    n = len(WR.SKILLS)
    ng, tic = RC.new_game_lines(n), RC.tic_lines(n)
    seq = lambda lines, pfx: [ln.replace(pfx, "@") for ln in lines]          # noqa: E731
    assert seq(ng[1:], "mn_r") == seq(RC.call_lines("mn_r", n), "mn_r")
    assert seq(tic[1:-1], "rs_d") == seq(RC.call_lines("rs_d", n), "rs_d") == seq(ng[1:], "mn_r")
    assert ng[0] == "hex.mov 1, g_skill, menu_sel" and tic[0] == "hex.if0 1, g_rs, rs_live" and tic[-1] == "rs_live:"
    # the menu runs exactly NEW GAME's lines, and the routines are placed once, by the menu block
    menu = WR.menu_state_lines(_restart())
    k = menu.index("mn_start:")
    assert menu[k + 1:k + 1 + len(ng)] == ng
    routines = RC.routine_lines(_restart())
    assert [ln for ln in routines if ln.endswith(":") and not ln.startswith(" ")] == [
        "restart_common:", "rs_skill0:", "rs_skill1:", "rs_skill2:"]
    assert sum(ln.strip() == "stl.fret rs_ret" for ln in routines) == 4


def test_a_menu_with_its_own_copy_of_a_skill_block_is_told_apart():
    """R9 for the test above: the P1.5 shape -- NEW GAME inlining skill k's lines after its own dispatch -- is not
    the shared sequence"""
    common, skills = _restart()
    old = ["stl.fcall restart_common, rs_ret", *WR._skill_dispatch("mn_r"),
           "mn_r0:", *skills[0], ";mn_started", "mn_r1:", *skills[1], ";mn_started", "mn_r2:", *skills[2]]
    assert old[:1] == RC.call_lines("mn_r", 3)[:1] and old != RC.call_lines("mn_r", 3)
    assert not any(ln.startswith("stl.fcall rs_skill") for ln in old)


def test_the_restart_routines_are_placed_where_nothing_falls_in():
    from doomfj.config import Config
    from doomfj.wad import WadFile
    lines = WR._menu_lines(Config(), WadFile.from_path("tests/fixtures/freedoom_assets.wad"), WR.DEFAULT_MENU,
                           WR.DEFAULT_MENU_SELECTED, restart=_restart())
    k = lines.index("restart_common:")
    assert lines[k - 1] == ";frame_end"
    assert lines[k:-1] == RC.routine_lines(_restart()) and lines[-1] == "do_world:"


# ---- the device shadows ------------------------------------------------------------------------------------------
_WRITES = re.compile(r"^\s*hex\.(set|zero|mov|xor_by|inc|dec)\s+[^,]+,\s*(\w+)")


def _shadow_writes(lines):
    return sorted({m.group(2) for ln in lines for m in [_WRITES.match(ln)] if m and m.group(2) in RC.DEVICE_SHADOWS})


def test_the_composed_restart_writes_no_device_shadow():
    from doomfj import hud, hudcode, hurtcode
    from doomfj.world import World
    w = World()
    common, skills = WR.compose_restart(
        SPAWN, 1, [0, 1], [5, 6], 2, [([1, 0], [0, 0], [1])] * 3, nwalk=1, nlift=0, monsters=None,
        hud_restart=hudcode.hud_restart_lines(hudcode.slot_codes(hud.slot_values(**hudcode.LEVEL_START))),
        wpn_restart=(), aim=True, hrt_restart=hurtcode.restart_lines(hurtcode.level_start(w)), proj_restart=(),
        nmobile=0)
    lines = common + [ln for s in skills for ln in s]
    assert any("p_hp" in ln for ln in lines) and any("hud_v" in ln for ln in lines)     # the parts are in it
    assert _shadow_writes(lines) == []
    # R9: the P5 restart's own last line, restoring the palette shadow, is seen by the same check
    assert _shadow_writes(lines + ["hex.set 1, pal_cur, 0"]) == ["pal_cur"]
    assert _shadow_writes(["    hex.zero 2, hud_s"]) == ["hud_s"]


# ---- the frame order ---------------------------------------------------------------------------------------------
def test_the_restart_on_use_runs_at_the_world_frames_start():
    tic = RC.tic_lines(3)
    lines = WR._standalone_input_lines(menu=["MENU"], door_lines=["DOORS"], exit_boxes_=[(0, 0, 1, 1)],
                                       weapon=["WEAPON"], monster_tic=["MONSTERS"], restart_tic=tic)
    at = {k: lines.index(v) for k, v in (("menu", "MENU"), ("restart", tic[0]), ("frozen", "hex.if0 1, lvdone, lv_live"),
                                          ("doors", "DOORS"), ("weapon", "WEAPON"))}
    assert at["menu"] < at["restart"] < at["frozen"] < at["doors"] < at["weapon"], at
    assert lines[at["restart"]:at["restart"] + len(tic)] == tic
    # a tier that cannot die emits none of it
    assert not any("g_rs" in ln for ln in WR._standalone_input_lines(menu=["MENU"]))


def test_the_level_time_ticks_inside_the_frozen_guard():
    lines = WR.p5_tic_lines({"bar": ["BAR"]})
    g, t, bar = lines.index("hex.if1 1, lvdone, p5_bar_skip"), lines.index("hex.inc 4, lvtime"), lines.index("BAR")
    assert lines.index("stl.fcall fx_phase, fx_pret") < g < t < bar < lines.index("p5_bar_skip:")


def test_the_emitter_composes_and_wires_the_restart():
    """the emission plan read off emit_wall_renderer's source (as test_p5_splice does): ONE composition, and the
    restart on use wired behind the mortal player modes"""
    src = inspect.getsource(WR.emit_wall_renderer)
    assert src.count("compose_restart(") == 1 and "restart_lines(" not in src
    assert "restart_tic=(_restartcode.tic_lines(len(SKILLS))" in src
    assert "_restartcode.mortal(PLAYER_MODE)" in src
    assert RC.mortal("full") and not RC.mortal("fx") and not RC.mortal("loot")


# ---- the P6 cells' level start, and the hooks --------------------------------------------------------------------
def test_the_p6_level_start_splits_by_skill():
    from doomfj.world import World
    w = World()
    common, per = RC.level_start_lines(w, WR.SKILLS, list(RC.P6_NIBBLES))
    assert len(per) == 3
    text = "\n".join(common)
    assert "hex.zero 25, mdrop" in text and "hex.zero 4, lvtime" in text
    assert "hex.set 2, bar_hp + 0*dw, 20" in text and "hex.set 2, rng_wd + 0*dw, %d" % w.level_start(gd.SK_HARD).rng_world in text
    # every barrel's phase roll is a line (22 barrels, on every skill)
    assert sum(ln.startswith("    hex.set 1, bar_ti + ") for ln in common) == w.layout.nbarrel == 22
    # R9: a value that differs by skill goes into the skills' blocks, one line each
    class Fake:
        layout, dropper = w.layout, w.dropper

        def level_start(self, sk):
            ws = w.level_start(sk).copy()
            ws.p_strength = sk
            return ws
    c2, p2 = RC.level_start_lines(Fake(), WR.SKILLS, ["p_str", "p_bc"])
    assert c2 == ["    hex.zero 2, p_bc"]
    assert p2 == [["    hex.set 4, p_str + 0*dw, %d" % sk] for sk in WR.SKILLS]


P6_MODULES = {"lootcode": ("p_bc", "p_str", "p_bp", "am_misl", "am_cell"), "barrelcode": RC.P6_BARREL}


@pytest.mark.parametrize("module", sorted(P6_MODULES))
def test_every_p6_module_persist_is_wired(module):
    """INTEGRATION HOOK (build.LOOT_PERSIST / BARREL_PERSIST): absent, none of the module's names persist yet (the
    branch is consistent); present, every name of its PERSIST persists and the game screen declares it for the
    re-key -- this FAILS until the integrator fills the hooks"""
    persist = set(_persist())
    if importlib.util.find_spec("doomfj." + module) is None:
        assert not persist & set(P6_MODULES[module]), "persisting %s's cells without the module" % module
        return
    mod = importlib.import_module("doomfj." + module)
    names = set(getattr(mod, "PERSIST", ()))
    assert names, "doomfj.%s has no PERSIST tuple" % module
    assert names <= persist, "HOOK: %s's %s are not in build.persist_labels" % (module, sorted(names - persist))
    from doomfj.wad import WadFile
    gs = {decl_words(d)[0] for d in B.game_screen_persisted_decls(WadFile.from_path("tests/fixtures/freedoom_e1m1.wad"))}
    assert names <= gs, "HOOK: %s's %s are not in build.game_screen_persisted_decls" % (module, sorted(names - gs))


# ---- M7 P8a: the final rung's persist hooks (docs/gp-final-plan.md 3.0 / 4.1) ----------------------------------------
# hook -> (the ONE rule its cells are emitted behind, at (player mode, monster mode); section 4.1's cells for it)
P8A_HOOKS = {
    "VIEW_PERSIST": (lambda pm, mm: W.player_sinks(pm), ("p_vd",)),
    "KNOCK_PERSIST": (lambda pm, mm: W.knockback_on(pm, mm),
                      ("p_kmx", "p_kmy", "mkx", "mky", "mfx", "mfy", "kb_live", "pj_z")),
    "FIGHT_PERSIST": (lambda pm, mm: W.infighting_on(mm), ("bar_src",)),   # mon_tgt: MONSTER_PERSIST's mon_target
}


@pytest.mark.parametrize("hook", sorted(P8A_HOOKS))
def test_every_p8a_hook_is_wired(hook):
    """INTEGRATION HOOK (build.VIEW_PERSIST / KNOCK_PERSIST / FIGHT_PERSIST, P6's `test_every_p6_module_persist_is_wired`
    extended): a hook holds only its own package's cells of section 4.1, once each; it persists exactly while its ONE
    rule is on at the game tier's modes (the cells are emitted behind the same rule) -- and then it holds ALL of its
    section-4.1 cells, every one persists and the game screen declares it for the re-key. FAILS when integration
    turns a rule on before its package wired its cells"""
    rule, cells = P8A_HOOKS[hook]
    names = getattr(B, hook)
    assert set(names) <= set(cells), "%s holds cells that are not its package's: %s" % (hook, sorted(set(names) - set(cells)))
    assert len(set(names)) == len(names), names
    persist = _persist()
    if not rule(WR.PLAYER_MODE, WR.MONSTER_MODE):
        assert not set(names) & set(persist), "%s persists while its rule is off at %s / %s" % (
            hook, WR.PLAYER_MODE, WR.MONSTER_MODE)
        return
    assert set(names) == set(cells), "HOOK: %s lacks %s (section 4.1) while its rule is on" % (
        hook, sorted(set(cells) - set(names)))
    assert set(names) <= set(persist), "HOOK: %s's %s are not in build.persist_labels" % (hook, sorted(set(names) - set(persist)))
    from doomfj.wad import WadFile
    gs = {decl_words(d)[0] for d in B.game_screen_persisted_decls(WadFile.from_path("tests/fixtures/freedoom_e1m1.wad"))}
    assert set(names) <= gs, "HOOK: %s's %s are not in build.game_screen_persisted_decls" % (hook, sorted(set(names) - gs))


def test_p8a_persist_composes_by_the_rules(monkeypatch):
    """build.p8a_persist: each hook behind its rule -- nothing at any pre-P8a pair, the view alone with a "final" player
    beside a "full" monster mode, the knock with "push" (the fallback), all three at "final" / "final" -- and
    persist_labels / game_screen_persisted_decls carry it at the game tier's modes (R9: with the hooks filled by
    stand-ins, the "final" tier persists them and the shipped "full" one does not)"""
    monkeypatch.setattr(B, "VIEW_PERSIST", ("p_vd",))
    monkeypatch.setattr(B, "KNOCK_PERSIST", ("p_kmx",))
    monkeypatch.setattr(B, "FIGHT_PERSIST", ("bar_src",))
    assert B.p8a_persist("full", "full") == B.p8a_persist("fx", "full") == ()
    assert B.p8a_persist("final", "full") == ("p_vd",)
    assert B.p8a_persist("final", "push") == ("p_vd", "p_kmx")
    assert B.p8a_persist("final", "final") == ("p_vd", "p_kmx", "bar_src")
    shipped = _persist()
    assert not {"p_vd", "p_kmx", "bar_src"} & set(shipped)
    monkeypatch.setattr(WR, "PLAYER_MODE", "final")
    monkeypatch.setattr(WR, "MONSTER_MODE", "final")
    final = _persist()
    assert final == shipped + ("p_vd", "p_kmx", "bar_src")
    src = inspect.getsource(B.game_screen_persisted_decls)
    assert "p8a_persist()" in src and "p8a_persisted_decls(" in src


def test_the_p6_units_are_package_as():
    """INTEGRATION HOOK: section 4.5 names MonsterPhase.loot_state / barrel_state / game_state the ONE definition of
    the cells' units; restartcode.p6_cell_values transcribes the table. When A's land, the two must agree on every
    skill's level start."""
    from doomfj.monsters import MonsterPhase
    have = [f for f in ("loot_state", "barrel_state", "game_state") if hasattr(MonsterPhase, f)]
    if not have:
        pytest.skip("HOOK: package A's MonsterPhase.loot_state / barrel_state / game_state are not on this branch")
    for sk in WR.SKILLS:
        mp = MonsterPhase(None, "E1M1", sk, mode=WR.MONSTER_MODE, player="full")
        mine = RC.p6_cell_values(mp.world)
        for f in have:
            for k, v in getattr(mp, f)().items():
                if k in mine:
                    got = list(v) if isinstance(v, (list, tuple)) else [v]
                    assert got == mine[k], (f, k, got, mine[k])
