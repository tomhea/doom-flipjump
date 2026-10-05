"""M7 P5 (doomfj.hurtcode): the hurt code's D4 tables against the model's own rules, at every index they can be read
at -- `mbul` over all 256 stream states x every distance 0..2100 against combat._mon_hitscan's hit test, `dpsav`
against combat.damage_player's armor save, `palidx` against DOOM's ST_doPaletteStuff, `trclaw` / `sgbite` against
combat.Sites. Each comparison has a negative control (R9): a broken fold must part.

And the OFF emissions (the decide mode's md_attack, the weapon, the slot tic, the thing test) carry no P5 text."""
import pytest

from doomfj import combat as C
from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import monsterdecide as MD
from doomfj import weaponcode as WC
from doomfj.reference_model import ReferenceModel

DISTS = range(0, 2101)


@pytest.fixture(scope="module")
def model():
    rm = ReferenceModel()
    return rm, C.Sites(rm), C.half_width_table(rm.sine)


def _fj_hit(row: int, d: int) -> bool:
    """md_bul's compare, literally: mt_d's nibbles 1-3 against the row's nibbles 1-3 (nibble 3 never written: 0)"""
    assert row < 0x1000
    return (d >> 4) & 0xFFF < (row >> 4) & 0xFFF


def _model_hit(hwt, spread: int, d: int) -> bool:
    """combat._mon_hitscan's test for a seen player"""
    return d < C.MISSILERANGE_U and abs(spread) <= hwt[d >> C.HWT_SHIFT]


def _mbul_bad(values, sites, hwt):
    bad = []
    for n, row in enumerate(values):
        spread, dmg = sites.mon_bullet[1][n]
        if row & 0xF != dmg:
            bad.append((n, "dmg", row & 0xF, dmg))
        for d in DISTS:
            if _fj_hit(row, d) != _model_hit(hwt, spread, d):
                bad.append((n, d))
                break
    return bad


def test_hwt_is_monotone_and_covers_the_range(model):
    _rm, _s, hwt = model
    H.check_hwt(hwt)
    assert max(hwt) == C.SUBRANDOM_MAX and min(hwt) > 0


def test_check_hwt_rejects_a_widening_table(model):
    _rm, _s, hwt = model
    bent = list(hwt)
    bent[40] = bent[39] + 1
    with pytest.raises(AssertionError):
        H.check_hwt(bent)


def test_mbul_is_the_hitscan_at_every_state_and_distance(model):
    _rm, sites, hwt = model
    vals = H.mbul_values(hwt)
    assert len(vals) == 256 and max(vals) <= 0x80F
    assert _mbul_bad(vals, sites, hwt) == []
    # the outcomes spread: short reaches (wide spreads hit only up close), the full 2048 (narrow ones), many between
    reach = {H.bullet_fields(v)[0] for v in vals}
    assert min(reach) <= 64 and 2048 in reach and len(reach) > 20


@pytest.mark.parametrize("fold", ["L+16", "strict", "dmg"])
def test_control_a_broken_mbul_parts(model, fold):
    _rm, sites, hwt = model
    f = {"L+16": lambda s, dmg: (H.bullet_reach(hwt, s) + 16) | dmg,
         "strict": lambda s, dmg: (16 * sum(1 for v in hwt if v > abs(s))) | dmg,
         "dmg": lambda s, dmg: H.bullet_reach(hwt, s) | (dmg % 15 + 1)}[fold]
    assert _mbul_bad(H.mbul_values(hwt, fold=f), sites, hwt), fold


def _saved_model(at, armor, dmg):
    """combat.damage_player's armor block on a scratch state: (armor after, armortype after, damage after)"""
    saved = dmg // 3 if at == 1 else dmg // 2
    if armor <= saved:
        saved, at = armor, 0
    return armor - saved, at, dmg - saved


def _saved_fj(table, at, armor, dmg):
    """dp_go's armor block on the table"""
    sv = table[at << 8 | dmg]
    if armor <= sv:
        sv, at = armor, 0
    return armor - sv, at, dmg - sv


def test_dpsav_is_damage_players_save():
    t = H.dpsav_values()
    assert len(t) == 3 << 8 and max(t) < 256
    for at in (1, 2):
        for dmg in range(H.DP_MAX + 1):
            for armor in range(201):
                assert _saved_fj(t, at, armor, dmg) == _saved_model(at, armor, dmg), (at, armor, dmg)


def test_control_a_swapped_save_parts():
    t = [(i & 0xFF) // 2 if i >> 8 == 1 else (i & 0xFF) // 3 if i >> 8 == 2 else 0 for i in range(3 << 8)]
    assert any(_saved_fj(t, at, 200, dmg) != _saved_model(at, 200, dmg) for at in (1, 2) for dmg in range(3, 40))


def _doom_palette(dc):
    """st_stuff.c ST_doPaletteStuff, red only"""
    if dc:
        p = (dc + 7) >> 3
        if p >= H.NUMREDPALS:
            p = H.NUMREDPALS - 1
        return p + H.STARTREDPALS
    return 0


def test_palidx_is_doom_red_palette():
    t = H.palidx_values()
    assert [t[dc] for dc in range(256)] == [_doom_palette(dc) for dc in range(256)]
    # damage reaches every red palette but STARTREDPALS itself: (dc + 7) >> 3 >= 1 for dc >= 1 (DOOM's own quirk)
    assert {t[dc] for dc in range(H.DC_CAP + 1)} == set(range(H.NPALETTES)) - {H.STARTREDPALS}
    pi = getattr(C, "palette_index", None)                    # agent A's model function, when it has landed
    if pi is not None:
        class _WS:
            pass
        for dc in range(H.DC_CAP + 1):
            ws = _WS()
            ws.p_damagecount, ws.p_bonuscount, ws.p_strength = dc, 0, 0
            assert pi(ws) == t[dc], dc


def test_control_dc_shift_parts():
    assert any((0 if not dc else 1 + min(7, dc >> 3)) != _doom_palette(dc) for dc in range(101))


@pytest.mark.parametrize("label,site", sorted(H.ATTACK_TABLES.items()))
def test_one_draw_tables_are_the_sites(model, label, site):
    _rm, sites, _h = model
    assert H.one_draw_values(site) == list(getattr(sites, site)[1])
    assert getattr(sites, site)[0] == 1


def test_tables_emit(model):
    _rm, _s, hwt = model
    text = "\n".join(H.tables_fj(hwt))
    for lab in ("mbul", "trclaw", "sgbite", "dpsav", "palidx"):
        assert "ns %s {" % lab in text, lab


def test_the_off_emissions_carry_no_p5_text():
    """full / hurt off: none of the P5 labels or cells appears (the text-hash proof is in the commit message)"""
    p5 = ("dp_go", "p_dead", "p_hp", "mbul", "trclaw", "sgbite", "pj_spawn", "md_bul", "md_hs")
    off = "\n".join(MD.decide_leaves(True) + MD.attack_leaf_lines()
                    + WC.weapon_lines(WC.weapon_states(), WC.overlay_frames(), True, True))
    assert not [w for w in p5 if w in off]
    on = "\n".join(MD.attack_leaf_lines(full=True))
    assert all(w in on for w in ("dp_go", "p_dead", "mbul", "trclaw", "sgbite", "pj_spawn"))
    assert MD.decide_leaves(True, full=False) == MD.decide_leaves(True)


def test_the_kill_drops_every_ready_weapon():
    """dp_go's kill names each E1M1 weapon's downstate: an A_Lower state of one tic"""
    text = "\n".join(H.dp_lines())
    states = WC.weapon_states()
    for w in WC.WEAPONS:
        down = gd.WEAPONINFO[w].downstate
        assert "dpk_w%d:" % w in text
        assert "hex.set 2, wp_st, %d" % states.index(down) in text
