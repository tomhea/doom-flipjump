"""M7 P5 -- the coordinator's splice of the monsters' attacks into the game tier (docs/gp-p5-interface.md), checked
WITHOUT a game-tier emission (that emits the ~104M-char sprite bank): the mobiles' rows and row select from
monstercode.p31_parts at the game tier's own model modes (a stand-in anim index -- the real widths, a distinct bank
region per view), the emitter's emit-time asserts and label check with their controls, the restart's links, the
tic's order, and the emission PLAN read off emit_wall_renderer's source (as test_wall_renderer_helpers does for the
window chrome): the boot-only screen init, the palette before the record stream, the phases after the monsters."""
import inspect
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import wall_renderer as WR

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def p5():
    from doomfj.config import Config
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import ReferenceModel
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    rm = ReferenceModel(Config())
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mw, "E1M1"), drawable, WR.MONSTER_TYPES)
    keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
    rt = [mw.things("E1M1")[w] for w in keep]
    patches = WR.anim_patches(art, WR.anim_frames(mw, "E1M1"))
    anim = {k: (0x100 + 64 * i, rm.art_of_lump(art, lump, cache)[2], mir)
            for i, (k, (lump, mir)) in enumerate(sorted(patches.items()))}
    p31 = MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=WR.BOOT_SKILL, skills=WR.SKILLS,
                       cache=cache, mode=WR.MONSTER_MODE, player=WR.PLAYER_MODE)
    from doomfj.hurtcode import hurt_parts
    w = p31["world"]
    w.reset(WR.BOOT_SKILL)
    hrt = hurt_parts(w, sprite_wad=art, boot_wad=mw)
    return dict(rm=rm, art=art, mw=mw, rt=rt, anim=anim, p31=p31, hrt=hrt, cache=cache)


def test_the_game_tier_runs_p5s_modes():
    from doomfj.hurtcode import hurt_on
    from doomfj.damagecode import fx_on
    assert (WR.MONSTER_MODE, WR.PLAYER_MODE) == ("full", "fx")
    assert hurt_on(WR.PLAYER_MODE) and fx_on(WR.PLAYER_MODE)


def test_the_mobile_rows_follow_the_oracles_draw_rule(p5):
    """each pool state's row: its mobile_lump's art at rotation 0 (the bank region of `(sprite, letter, 0)`), top +
    MISSILE_Z, the BASE min height in both depth bounds, the LD region 2*dw on, not mirrored -- and (M7 P6+P7 E, the
    game picture's actors rule, GAME_RENDER_KW `exempt_actors`) an ACTOR: the monster class (sp_mon 1) at the MONSTER
    base bound; without the rule the scenery class at MIN_SPRITE_H"""
    from types import SimpleNamespace
    from doomfj import projcode as PC
    from doomfj.monsters import mobile_lump, mobile_rows
    from doomfj.reference_model import GAME_RENDER_KW, MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, MISSILE_Z
    p31, rm, art, anim, nt = p5["p31"], p5["rm"], p5["art"], p5["anim"], len(p5["rt"])
    actor = GAME_RENDER_KW["exempt_actors"]
    assert actor is True and MIN_SPRITE_H_MONSTER < MIN_SPRITE_H     # the rule moves the bound (a vacuity guard)
    assert p31["nmob"] == 10 == mobile_rows(SimpleNamespace(monsters=WR.MONSTER_MODE, player=WR.PLAYER_MODE))
    assert MISSILE_Z == 32                                   # a vacuity guard: the z the rows must carry is not 0
    seen_rows = set()
    for s in PC.pool_states():
        lump = mobile_lump(s)
        row = p31["mob_view"][gd.STATE_INDEX[s]]
        r = p31["view_rows"][row - nt]
        a = rm.art_of_lump(art, lump, p5["cache"])
        base, dw, mir = anim[(lump[:4], lump[4], 0)]
        tz = rm.sprite_tz_min_size(a[4], MIN_SPRITE_H_MONSTER if actor else MIN_SPRITE_H) & 0xFFFFFFFF
        assert r == (a[5], a[3], a[4], a[6] + MISSILE_Z, tz, tz, base, base + 2 * dw, int(actor), dw), (s, lump, r)
        assert not mir
        seen_rows.add(row)
    assert len(seen_rows) == 8 and min(seen_rows) == p31["mob_first"] and max(seen_rows) == p31["nrows"] - 1
    # every mobile row's height is in the light classes the emitter widens the bank with
    assert {max(1, p31["view_rows"][r - nt][2]) for r in seen_rows} <= set(p31["view_heights"])


def test_the_row_select_has_a_stub_for_every_mobile(p5):
    p31, nt = p5["p31"], len(p5["rt"])
    sel = "\n".join(p31["select"])
    for k in range(10):
        assert "  thsel_s%d:\n" % (nt + k) in sel
    assert "  thsel_s%d:" % (nt + 10) not in sel
    tail = sel[sel.index("  thsel_mob:"):]
    assert "hex.zero w/4, sp_sa" in tail and "hex.zero 2, sp_sid" in tail and "mobview.lookup sp_ti, ts_mob" in tail
    assert "ts_mob: hex.vec 2" in p31["decls"]


def test_the_pools_and_the_blood_ride_the_decide_mode(p5):
    p31, nt = p5["p31"], len(p5["rt"])
    assert p31["proj"]["nt"] == nt and p31["chase"]["hurt"] is True
    assert "    stl.fcall fx_spawn, fx_sret" in p31["decide_lines"]       # damagecode's dm_leaf bleeds (fx_on)
    lines = "\n".join(p31["proj"]["lines"])
    assert "thpos_rt + %d*dw" % (16 * nt + 4) in lines and "thpos_rt + %d*dw" % (16 * (nt + 9) + 4) in lines
    assert "thpos_rt + %d*dw" % (16 * (nt + 10) + 4) not in lines
    # the fireball rows carry the WHOLE-UNIT position (the fraction nibbles zeroed, the integer half copied)
    assert "    hex.zero 4, thpos_rt + %d*dw" % (16 * nt) in lines
    assert "    hex.mov 4, thpos_rt + %d*dw, pw_x + 4*dw" % (16 * nt + 4) in lines


def test_a_mode_pair_that_disagrees_is_refused(p5):
    with pytest.raises(AssertionError):
        MC.p31_parts(p5["rm"], p5["mw"], "E1M1", p5["art"], p5["anim"], p5["rt"], spr_near=True,
                     boot_skill=WR.BOOT_SKILL, skills=WR.SKILLS, cache=p5["cache"], mode="decide", player="fx")


def test_the_emit_time_asserts_pass_and_catch_a_moved_row(p5):
    p31, hrt = p5["p31"], p5["hrt"]
    WR._p5_model_asserts(p31, p31["proj"], hrt)
    bad = dict(p31, mob_view=dict(p31["mob_view"]))
    bad["mob_view"][gd.STATE_INDEX["S_TBALL1"]] = p31["mob_first"] - 1         # a monster view's row
    with pytest.raises(AssertionError):
        WR._p5_model_asserts(bad, p31["proj"], hrt)
    with pytest.raises(AssertionError):
        WR._p5_model_asserts(dict(p31, nmob=9), p31["proj"], hrt)


def test_the_label_check_catches_a_missing_label():
    texts = [("a", "\n".join("%s: hex.vec 1" % n for n in WR.P5_SHARED_LABELS)),
             ("b", "\n".join("ns %s {\n}" % n for n in WR.P5_SHARED_NS))]
    WR._p5_assert_labels(texts)
    with pytest.raises(AssertionError):
        WR._p5_assert_labels([("a", texts[0][1].replace("dp_go:", "dp_gone:")), texts[1]])
    with pytest.raises(AssertionError):
        WR._p5_assert_labels([texts[0], ("b", texts[1][1].replace("ns pjst {", "ns pjs {"))])


def test_new_game_unlinks_the_mobiles_too():
    from types import SimpleNamespace
    spawn = SimpleNamespace(x=0, y=0, angle=0)
    common, _ = WR.restart_lines(spawn, 1, [0, 1], [5, 6], 2, [([0, 0], [0, 0], [])] * 3, nmobile=10)
    assert "    rep(12, i) m1.zerobyte thnext + i*dw" in common
    common0, _ = WR.restart_lines(spawn, 1, [0, 1], [5, 6], 2, [([0, 0], [0, 0], [])] * 3)
    assert "    rep(2, i) m1.zerobyte thnext + i*dw" in common0


def test_the_tic_after_the_monsters_runs_projectiles_then_blood_then_the_bar(p5):
    out = WR.p5_tic_lines(p5["hrt"])
    assert out[:3] == ["stl.fcall pj_phase, pj_pret", "stl.fcall fx_phase, fx_pret", "hex.if1 1, lvdone, p5_bar_skip"]
    assert out[3:-1] == list(p5["hrt"]["bar"]) and out[-1] == "p5_bar_skip:"


def test_the_persist_set_carries_p5s_cells():
    from doomfj.build import persist_labels
    from doomfj import hurtcode, projcode
    got = persist_labels(standalone=True, doors=True, moving_things=True)
    for n in hurtcode.PERSIST + projcode.PERSIST:
        assert n in got, n
    assert "pal_cur" in got and "rng_fx" in got and "p_hp" in got and "pj_act" in got and "fx_act" in got
    assert not set(hurtcode.PERSIST) & set(persist_labels(standalone=False, doors=True, moving_things=True))


# ---- the emission PLAN, read off the emitter's source (a game-tier emission is the heavy build) -----------------
def _src():
    return inspect.getsource(WR.emit_wall_renderer)


def test_the_screen_init_and_boot_palette_run_once_in_the_entry_part():
    src = _src()
    entry = src[src.index('("entry", ['):]
    entry = entry[:entry.index('("tables", [')]
    assert "*(_boot_screen if _boot_screen else [])," in entry
    assert entry.index("*(_boot_screen if _boot_screen else []),") < entry.index("*hotdata[:1],")
    main = src[src.index('("main", ['):]
    main = main[:main.index("*pass1,")]
    assert "*([] if _boot_screen else" in main and "*([] if _boot_screen else prelude)," in main
    # ... and only the game-screen tier (the bar, the palette) moves them: every other tier keeps its per-frame ones
    line = next(ln for ln in src.split("\n") if ln.strip().startswith("_boot_screen = "))
    nxt = src[src.index(line):].split("\n")[1]
    assert "if _hud else None" in line + nxt


def test_the_palette_goes_before_the_record_stream_and_the_phases_after_the_monsters():
    src = _src()
    i_eye = src.index('_wt_tic = list(_p31.get("tic_after_eye", ())) if _p31 else []')
    i_p5 = src.index("_wt_pools = p5_tic_lines(_hrt) if _hrt else []")
    # M7 P6+P7 E: the two composed into the monsters' world at the tempo (world_tic_lines; tests/fj/test_monster_tempo_fj)
    i_wt = src.index("pass1 += world_tic_lines(_wt_tic, _wt_pools, _WT_TICS if (_wt_tic and _hrt) else 1)")
    i_pal = src.index('pass1 += list(_hrt["palette"])')
    i_begin = src.index('pass1.append("present.begin_frame_collines")')
    assert i_eye < i_p5 < i_wt < i_pal < i_begin


def test_the_hurt_tic_menu_palette_restart_and_leaves_are_spliced():
    src = _src()
    assert 'weapon=((list(_wpn["tic"]) + (list(_hrt["tic"]) if _hrt else []))' in src
    assert 'list(_hrt["menu_palette"])' in src
    assert 'list(_hrt["restart"]) + list(_proj["restart"])' in src and "nmobile=_MT_NMOB" in src
    assert '(list(_hrt["leaves"]) + list(_proj["lines"]) + [_proj["cells"]])' in src
    i_leaves = src.index('(list(_hrt["leaves"]) + list(_proj["lines"]) + [_proj["cells"]])')
    assert src.index('["    ;mm_block_end", _mcells]') < i_leaves < src.index('["mm_block_end:"]) + BSn')
    assert "full=bool(_chase.get(\"hurt\"))" in src and "hurt=bool(_chase.get(\"hurt\"))" in src
    assert "hurt=_P5) if menu else None" in src and "_P5 = _P5 and _p31 is not None" in src
    assert "_p5_assert_labels(_texts)" in src and "_p5_model_asserts(_p31, _proj, _hrt)" in src
