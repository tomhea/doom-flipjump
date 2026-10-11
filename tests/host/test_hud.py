"""M7 P4.0 -- the status bar and weapon generator (`doomfj.hud`) and the game tier's screen rule (docs/gp-combat.md
section 2). `tests/fj/test_hud_fj.py` runs the emitted fj against these pictures; this holds the pictures' own
properties and the one config rule.
"""
from pathlib import Path

import pytest

from doomfj import hud, hudcode
from doomfj.config import GAME_CFG, Config
from doomfj.wad import WadFile
from doomfj.wall_renderer import TIERS, tier_cfg

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def art():
    return WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))


@pytest.fixture(scope="module")
def colours(art):
    return hud.bar_colours(bytes(b for rgb in art.playpal(0) for b in rgb))


def test_only_the_game_tier_has_the_bar():
    assert tier_cfg(None, "game").VIEW_H == hud.VIEW_ROWS == 84 and tier_cfg(None, "game").CENTERY == 42
    assert tier_cfg(Config(), "game").VIEW_H == 84            # whatever the caller passed: no 100-row game binary
    for tier in TIERS:
        if tier != "game":
            assert tier_cfg(None, tier).VIEW_H == 100, tier
    assert GAME_CFG.H == 100 and GAME_CFG.W == GAME_CFG.VIEW_W == 160


def test_the_slots_own_disjoint_columns_inside_the_bar():
    owner = {}
    for name, x0, w, variants in hud.bar_slots():
        assert 0 <= x0 and x0 + w <= 160 and len(set(variants)) == len(variants)
        for x in range(x0, x0 + w):
            assert x not in owner, "column %d is in slots %s and %s" % (x, owner[x], name)
            owner[x] = name


@pytest.mark.parametrize("vals", [hudcode.LEVEL_START,
                                  dict(ammo=8, health=57, armor=25, owned=(True, True, False, True, False, False),
                                       blue=True),
                                  dict(ammo=None, health=0, armor=200, owned=(False, False, True, False, True, False),
                                       blue=False),
                                  dict(ammo=123, health=100, armor=7, owned=(True,) * 6, blue=True)])
def test_a_slot_column_is_the_full_bar_column(colours, vals):
    """the fj side redraws ONE slot's columns from its own variant: that must be what the whole bar shows there"""
    full = hud.bar_pixels(colours, **vals)
    sv = hud.slot_values(**vals)
    owner = {x: n for n, x0, w, _v in hud.bar_slots() for x in range(x0, x0 + w)}
    for x in range(160):
        assert hud.bar_column(colours, x, sv.get(owner.get(x))) == [full[y][x] for y in range(hud.BAR_ROWS)], x


def test_the_digit_fields():
    assert hud.digits(50) == (None, 5, 0) and hud.digits(0) == (None, None, 0) and hud.digits(100) == (1, 0, 0)
    assert hud.digits(None) == (None, None, None) and hud.digits(-5) == (None, None, 0)
    assert hud.digits(1234) == (9, 9, 9)


def test_a_changed_value_changes_only_its_slot(colours):
    a = hud.bar_pixels(colours, **hudcode.LEVEL_START)
    b = hud.bar_pixels(colours, **dict(hudcode.LEVEL_START, health=57))
    cols = {x for y in range(hud.BAR_ROWS) for x in range(160) if a[y][x] != b[y][x]}
    health = {x for n, x0, w, _v in hud.bar_slots() if n.startswith("health") for x in range(x0, x0 + w)}
    assert cols and cols <= health


def test_the_pistol_sits_on_the_bar(art):
    """DOOM's R_DrawPSprite at half scale: the ready pistol is centred near column 80 and reaches the view's last
    row; every run lies in the view and runs never overlap"""
    ov = hud.psprite_columns(art.get_data("PISGA0"))
    xs = sorted(ov)
    assert xs == list(range(xs[0], xs[-1] + 1)) and abs((xs[0] + xs[-1]) / 2 - 80) <= 3
    assert max(r[1] for v in ov.values() for r in v) == hud.VIEW_ROWS
    for runs in ov.values():
        assert all(0 <= y0 < y1 <= hud.VIEW_ROWS for y0, y1, _t in runs)
        assert all(a[1] <= b[0] for a, b in zip(runs, runs[1:]))


def test_the_control_a_shifted_psprite_differs(art):
    """R9: one native unit of sx moves the overlay -- the geometry is not insensitive to its own inputs"""
    assert hud.psprite_columns(art.get_data("PISGA0"), sx=3) != hud.psprite_columns(art.get_data("PISGA0"))


def test_e1m1_lights_the_weapon_with_one_row():
    from doomfj.config import DEFAULT_MAP_WAD
    from doomfj.reference_model import ReferenceModel
    rm = ReferenceModel(GAME_CFG)
    mw = WadFile.from_path(DEFAULT_MAP_WAD)
    assert len({hud.psprite_light_row(rm, s.light) for s in mw.sectors("E1M1")}) == 1


# ---- P9 (the owner's play-test, 2026-10-10: "fix ARMS on the status bar to match DOOM") ------------------------------
def test_arms_are_dooms_six_digits_and_the_chainsaw_has_none():
    """DOOM's arms widget: digits 2..7, digit d lit when weaponowned[d - 1] -- the pistol, the shotgun, the chaingun, the
    launcher, the plasma rifle, the BFG. The fist and the chainsaw share slot 1: owning the chainsaw lights NOTHING
    (until P9 the bar lit a "4" for it); owning the launcher lights 5"""
    from doomfj import gamedata as gd
    assert hud.ARMS_DIGITS == (2, 3, 4, 5, 6, 7)
    assert [n for n, *_r in hud.bar_slots() if n.startswith("arms")] == ["arms%d" % d for d in range(2, 8)]
    owned = [0] * gd.NUMWEAPONS
    owned[gd.WP_FIST] = owned[gd.WP_PISTOL] = owned[gd.WP_CHAINSAW] = 1
    assert hud.arms_owned(owned) == (True, False, False, False, False, False)
    owned[gd.WP_MISSILE] = 1
    assert hud.arms_owned(owned) == (True, False, False, True, False, False)
    for w, d in ((gd.WP_PISTOL, 2), (gd.WP_SHOTGUN, 3), (gd.WP_CHAINGUN, 4), (gd.WP_MISSILE, 5), (gd.WP_PLASMA, 6),
                 (gd.WP_BFG, 7)):
        one = [0] * gd.NUMWEAPONS
        one[w] = 1
        assert hud.arms_owned(one) == tuple(x == d for x in hud.ARMS_DIGITS), (w, d)


def test_the_arms_digits_are_drawn_lit_and_dim_inside_their_panel(colours):
    """every digit 2..7 is drawn (the 3x5 font), in the owned colour when lit and the dim one when not, inside the ARMS
    panel and clear of its separators; ARMOR and KEYS keep their labels and the card inside their panels"""
    from doomfj.menu import _SMALL_GLYPHS
    _n, a0, a1 = next(p for p in hud.PANELS if p[0] == "ARMS")
    for owned in ((True, False, False, True, False, False), (False,) * 6, (True,) * 6):
        px = hud.bar_pixels(colours, **dict(hudcode.LEVEL_START, owned=owned))
        for i, d in enumerate(hud.ARMS_DIGITS):
            x0 = hud.ARMS_X0 + i * hud.ARMS_PITCH
            assert a0 < x0 and x0 + hud.ARMS_W <= a1
            want = {(x0 + c, hud.ARMS_Y + r) for r, row in enumerate(_SMALL_GLYPHS[str(d)].split("|"))
                    for c, ch in enumerate(row) if ch == "#"}
            ink = colours["owned" if owned[i] else "unowned"]
            got = {(x, y) for y in range(hud.BAR_ROWS) for x in range(x0, x0 + hud.ARMS_W) if px[y][x] == ink}
            assert got == want, (d, owned)
    _n, k0, k1 = next(p for p in hud.PANELS if p[0] == "KEYS")
    assert k0 < hud.CARD_BOX[0] and hud.CARD_BOX[0] + hud.CARD_BOX[2] <= k1


def test_control_the_arms_check_catches_the_old_chainsaw_digit(colours, monkeypatch):
    """R9: the pre-P9 bar -- three digits 2 3 4 with the CHAINSAW behind "4" -- fails the mapping check: owning the
    chainsaw would light a digit"""
    from doomfj import gamedata as gd
    owned = [0] * gd.NUMWEAPONS
    owned[gd.WP_PISTOL] = owned[gd.WP_CHAINSAW] = 1
    old = (bool(owned[gd.WP_PISTOL]), bool(owned[gd.WP_SHOTGUN]), bool(owned[gd.WP_CHAINSAW]))
    assert sum(old) == 2 != sum(hud.arms_owned(owned)) == 1
    monkeypatch.setattr(hud, "arms_owned", lambda o: old + (False,) * 3)
    with pytest.raises(AssertionError):
        test_arms_are_dooms_six_digits_and_the_chainsaw_has_none()
