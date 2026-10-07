"""M7 P8a package D (docs/gp-final-plan.md 1.4): the follow-up issues' emit-time asserts and one-definition constants,
each with a negative control (R9) -- a mutated input the assert must refuse.

  * #119 item 4: aimcode.check_minz_first -- aim_record's UNSIGNED depth compare is exact only after project_thing's
    signed MINZ reject; a projection.fj whose aim hook runs before that reject is refused;
  * #119 item 7: aimcode.check_box_widths -- every box the aim leaf records is >= 1 column (an empty box would wrap its
    column count); a barrel aimed out to MISSILERANGE (0.78 of a column) is refused;
  * #123 item 4: wall_renderer.assert_exit_frame_bar -- no hurt sector and no health / armor pickup within one frame's
    reach of the exit box (hp_bar sits inside the lvdone guard); an exit box moved onto a stimpack, or onto the
    nukage, is refused;
  * #123 R5a: lootcode.nukage_lines' unsigned floor compare reads equality only (its lt and gt arms are one label);
  * #121 item 12: projcode.check_model_rules ties pw_ang + 5*dw to the model's angle shift (a 8192-entry finesine
    is refused);
  * #121 item 11 / #119 item 6: hurtcode's damagecount cap and palette ranges ARE combat's, the aim window's width IS
    world.AIM_COLUMNS everywhere, the game screen's sizes ARE config.GAME_CFG's -- no module restates them;
  * #121 F5: p31_parts names an unsupported mode pair; F7: World.reset on a copy leaves the original's state alone.
"""
import copy
import re
from pathlib import Path

import pytest

from doomfj import aimcode as AC

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
MAPWAD = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"
needs_art = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")


@pytest.fixture(scope="module")
def rm():
    from doomfj.config import GAME_CFG
    from doomfj.reference_model import ReferenceModel
    return ReferenceModel(GAME_CFG)


@pytest.fixture(scope="module")
def mapwad():
    from doomfj.wad import WadFile
    return WadFile.from_path(str(MAPWAD))


# ---- #119 item 4 ------------------------------------------------------------------------------------------------
def test_minz_reject_precedes_the_aim_hook():
    AC.check_minz_first()


def test_control_an_aim_hook_before_the_minz_reject_is_refused():
    text = (ROOT / "src" / "fj" / "projection.fj").read_text(encoding="utf-8")
    hook = next(ln for ln in text.splitlines(keepends=True) if ln.lstrip().startswith("rep(aim, k) .aim_hook"))
    minz = "        hex.set 8, pth_czlim, minz\n"
    assert text.count(hook) == 1 and text.count(minz) == 1
    bad = text.replace(hook, "").replace(minz, hook + minz)                   # the hook moved before the reject
    with pytest.raises(AssertionError, match="MINZ reject BEFORE the aim hook"):
        AC.check_minz_first(bad)
    with pytest.raises(AssertionError, match="no longer compares MINZ"):
        AC.check_minz_first(text.replace(minz, "        hex.set 8, pth_czlim, neartz\n"))


# ---- #119 item 7 ------------------------------------------------------------------------------------------------
@needs_art
def test_every_aimed_box_is_at_least_one_column(rm):
    from doomfj.wad import WadFile
    wph = AC.barrel_standing_wph(rm, WadFile.from_path(str(ART)))
    out = AC.check_box_widths(rm, wph)
    assert set(out) == {0, 1, AC.RC_BARREL}
    assert all(cols >= 1 for _r, _tz, _xs, cols in out.values()), out
    # the monsters' bound is MISSILERANGE itself; the barrel's is its own min-size depth, nearer
    assert out[0][1] == out[1][1] == AC.MAXTZ and out[AC.RC_BARREL][1] < AC.MAXTZ


def test_control_a_barrel_box_at_missilerange_is_refused(rm):
    """a barrel tall enough (80 units: 3 rows out to ~2133) to be kept to MISSILERANGE: r_eff 10 there is 0.78 of a
    column -- the wrap #119 names"""
    with pytest.raises(AssertionError, match="narrower than one column"):
        AC.check_box_widths(rm, barrel_wph=80)


def test_the_aim_leaf_text_is_unchanged_by_the_asserts():
    """the asserts add no text: the leaf's lines are a pure function of (centerx, barrels) as before"""
    a, b = AC.leaf_lines(80, barrels=True), AC.leaf_lines(80, barrels=True)
    assert a == b and a[1] == "hex.cmp 8, pth_tz, ar_maxtz, ar_in, ar_in, ar_out"


# ---- #123 item 4 ------------------------------------------------------------------------------------------------
def test_the_exit_frame_cannot_move_the_bar(mapwad):
    from doomfj import wall_renderer as WR
    from doomfj.doors import exit_boxes
    boxes = exit_boxes(mapwad.linedefs("E1M1"), mapwad.vertexes("E1M1"))
    m = WR.assert_exit_frame_bar(mapwad, "E1M1", boxes)
    assert m["hurt"] > 0 and m["pickup"] > 0, m


def test_control_an_exit_box_by_a_stimpack_or_on_the_nukage_is_refused(mapwad):
    from doomfj import wall_renderer as WR
    stim = next(t for t in mapwad.things("E1M1") if t.type == 2011 and t.x < 0)     # far from every hurt sector
    with pytest.raises(AssertionError, match="health / armor pickup"):
        WR.assert_exit_frame_bar(mapwad, "E1M1", [(stim.x + 100, stim.y - 10, stim.x + 200, stim.y + 10)])
    # sector 173 (E1M1's nukage, 5/frame) spans x 1248..1968, y 640..1344 (its lines' extent)
    with pytest.raises(AssertionError, match="meets damaging sector"):
        WR.assert_exit_frame_bar(mapwad, "E1M1", [(1500, 900, 1600, 1000)])


# ---- #123 R5a ---------------------------------------------------------------------------------------------------
def test_nukage_floor_compare_reads_equality_only():
    src = (ROOT / "src" / "doomfj" / "lootcode.py").read_text(encoding="utf-8")
    m = re.search(r'_nk_lt, _nk_eq, _nk_gt = "(\w+)", "(\w+)", "(\w+)"', src)
    assert m and m.group(1) == m.group(3) != m.group(2), "nukage's hex.cmp must take its lt and gt arms alike"
    assert '"    hex.cmp 8, cp_floor, cp_seedf, %s, %s, %s" % (_nk_lt, _nk_eq, _nk_gt)' in src


# ---- #121 item 12 -----------------------------------------------------------------------------------------------
def test_the_fireball_fine_angle_is_the_models(monkeypatch):
    from doomfj import projcode as PC
    from doomfj.config import Config
    PC.check_model_rules()
    PC.check_model_rules(puffs=True)
    import doomfj.config as cfgmod
    monkeypatch.setattr(cfgmod, "GAME_CFG", Config(VIEW_ROWS=84, TRIG_N=8192))       # angle >> 19: refused
    with pytest.raises(AssertionError, match="angle >> 20"):
        PC.check_model_rules()


# ---- #121 item 11, #119 item 6 ----------------------------------------------------------------------------------
def test_hurtcode_restates_no_model_constant():
    from doomfj import combat as C
    from doomfj import hurtcode as H
    for name in ("DC_CAP", "STARTREDPALS", "NUMREDPALS", "STARTBONUSPALS", "NUMBONUSPALS"):
        assert getattr(H, name) is getattr(C, name), name
    src = (ROOT / "src" / "doomfj" / "hurtcode.py").read_text(encoding="utf-8")
    assert not re.search(r"^(DC_CAP|STARTREDPALS|STARTBONUSPALS)\b.*=", src, re.M), "hurtcode re-declares a combat rule"
    csrc = (ROOT / "src" / "doomfj" / "combat.py").read_text(encoding="utf-8")
    assert "min(DC_CAP, ws.p_damagecount + dmg)" in csrc and "min(100, ws.p_damagecount" not in csrc


def test_the_aim_window_width_and_the_screen_have_one_definition(rm):
    from doomfj import hud, weaponcode
    from doomfj.combat import aim_window
    from doomfj.config import GAME_CFG
    from doomfj.world import AIM_COLUMNS
    lo, hi = aim_window(rm)
    assert (AC.FIRST, AC.NCOLS, weaponcode.AIM_N) == (lo, hi - lo + 1, AIM_COLUMNS) == (lo, AIM_COLUMNS, AIM_COLUMNS)
    assert (hud.SCREEN_W, hud.VIEW_ROWS, hud.BAR_ROWS) == (GAME_CFG.W, GAME_CFG.VIEW_ROWS, GAME_CFG.H - GAME_CFG.VIEW_ROWS)
    for f, pat in (("src/doomfj/aimcode.py", r"^FIRST, NCOLS = 72, 17"), ("src/doomfj/weaponcode.py", r"^AIM_N = 17"),
                   ("src/doomfj/hud.py", r"^VIEW_ROWS = 84"), ("src/doomfj/hud.py", r"\b160\b(?!x100)"),
                   ("src/doomfj/hudcode.py", r"range\(160\)"), ("src/doomfj/wall_renderer.py", r"2 \* 17\}, aim_sid"),
                   ("scratchpad/gp/probe.py", r'"aim_sid", "hex", 2, count=17')):
        text = (ROOT / f).read_text(encoding="utf-8")
        code = "\n".join(ln.split("#")[0] for ln in text.splitlines() if not ln.lstrip().startswith(("#", '"""')))
        assert not re.search(pat, code, re.M), (f, pat)


# ---- #121 F5 / F7 ------------------------------------------------------------------------------------------------
@needs_art
def test_f5_an_unsupported_mode_pair_is_refused_by_name(rm, mapwad):
    from doomfj import monstercode as MC
    from doomfj import wall_renderer as WR
    from doomfj.mapcompiler import bake_bsp
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(ART))
    cache = {}
    drawable, draw_idx = drawable_things(rm, mapwad.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mapwad, "E1M1"), drawable, WR.MONSTER_TYPES)
    rt = [mapwad.things("E1M1")[w] for w, b in zip(draw_idx, baked) if not b]
    patches = WR.anim_patches(art, WR.anim_frames(mapwad, "E1M1"))
    anim = {k: (0x100 + 64 * i, rm.art_of_lump(art, lump, cache)[2], mir)
            for i, (k, (lump, mir)) in enumerate(sorted(patches.items()))}
    with pytest.raises(AssertionError, match=r"UNSUPPORTED MODE PAIR \(monster mode 'full', player mode 'walk'\)"):
        MC.p31_parts(rm, mapwad, "E1M1", art, anim, rt, spr_near=True, boot_skill=WR.BOOT_SKILL, skills=WR.SKILLS,
                     cache=cache, mode="full", player="walk")


def test_f7_a_reset_copy_leaves_the_original_world_alone(mapwad):
    """wall_renderer resets a COPY of p31_parts' World (World.reset rebinds, never mutates, what it touches)"""
    from doomfj.world import World
    w = World(mapwad, "E1M1")
    w.ws.p_health = 7                                    # a state the parts were "built from"
    ws0, ev0 = w.ws, w.events
    c = copy.copy(w)
    c.reset(w.ws.skill)
    assert w.ws is ws0 and w.ws.p_health == 7 and w.events is ev0
    assert c.ws is not ws0 and c.ws.p_health == 100
    src = (ROOT / "src" / "doomfj" / "wall_renderer.py").read_text(encoding="utf-8")
    assert '_w5 = _copy.copy(_p31["world"])' in src and '_w5 = _p31["world"]\n' not in src
