"""M7 P4.2a: the shot's folded outcome table `wpo` (`weaponcode.shot_values`) against `combat.Sites`.

One row per stream index (the state after the shot's FIRST draw) carries the gun damage, the melee damage and the
column for the pistol's accurate shot (1 draw), P_GunShot (3), A_Punch (3) and A_Saw (3). `verify_shot_table`
compares every field with the model's own tables at all 256 indices; the negative controls build wrong folds and
require it to reject each (R9)."""
from doomfj import combat as C
from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj import weaponcode as WC


def test_the_fold_is_the_models_sites_at_every_index():
    values = WC.shot_values()
    assert len(values) == 256
    assert WC.verify_shot_table(values) == []
    lo, centre, hi = WC.shot_window()
    assert (hi - lo + 1, centre - lo) == (WC.AIM_N, 8)
    fields = [WC.shot_fields(v) for v in values]
    assert {g for _m, g, _c in fields} == {5, 10, 15}
    assert {m for m, _g, _c in fields} == set(range(2, 21, 2))
    assert {c for _m, _g, c in fields} <= set(range(WC.AIM_N))
    assert max(values) < 1 << (4 * WC.SHOT_ROW_NIBBLES)


def test_the_row_read_is_the_models_roll_from_every_state():
    """the leaf reads the row at state + 1 and leaves the stream at state + 3 (+1 for the accurate shot): the
    model's `_roll` (p_random_outcome_k / p_random_outcome) from every state"""
    _rm, sites = WC._default_sites()
    lo, _c, _h = WC.shot_window()
    values = WC.shot_values()
    for s in range(256):
        melee, gun, col = WC.shot_fields(values[(s + 1) & 255])
        assert C.p_random_outcome_k(s, sites.gunshot[1], 3) == ((gun, lo + col), (s + 3) & 255)
        assert C.p_random_outcome_k(s, sites.saw[1], 3) == ((melee, lo + col), (s + 3) & 255)
        assert R.p_random_outcome(s, sites.pistol_acc[1]) == (gun, (s + 1) & 255)


def test_the_check_rejects_a_wrong_fold():
    """R9: each wrong fold is rejected -- indexed by the PRE-increment state, the column one off, the spread's
    subtraction reversed, the gun damage on the melee formula, and one row's melee damage flipped"""
    rm, sites = WC._default_sites()
    lo, _c, _h = WC.shot_window()
    good = WC.shot_values()
    col = sites.col
    wrong = {
        "pre_increment": good[1:] + good[:1],
        "col_plus1": WC.shot_values(fold=lambda a, b, c: WC.shot_row((a % 10 + 1) << 1, 5 * (a % 3 + 1),
                                                                     min(col(b - c) - lo + 1, WC.AIM_N - 1))),
        "spread_reversed": WC.shot_values(fold=lambda a, b, c: WC.shot_row((a % 10 + 1) << 1, 5 * (a % 3 + 1),
                                                                           col(c - b) - lo)),
        "gun_as_melee": WC.shot_values(fold=lambda a, b, c: WC.shot_row((a % 10 + 1) << 1, (a % 3 + 1) * 2,
                                                                        col(b - c) - lo)),
        "one_row": good[:77] + [good[77] ^ 2] + good[78:],
    }
    for name, values in wrong.items():
        assert values != good, name
        assert WC.verify_shot_table(values), "the wrong fold %s passed" % name


def test_shoot_off_emits_no_shot():
    states, frames = WC.weapon_states(), WC.overlay_frames()
    fire = "\n".join(WC.weapon_lines(states, frames))
    assert fire == "\n".join(WC.weapon_lines(states, frames, shoot=False))
    for label in ("sh_", "shc_", "dm_", "wpo", "aim_sid"):
        assert label not in fire, label
    shoot = "\n".join(WC.weapon_lines(states, frames, shoot=True))
    for label in ("sh_rd3:", "sh_gun:", "wpo.lookup sh_row, rng_pl", "stl.fcall dm_go, dm_ret", "aim_sid"):
        assert label in shoot, label
    melee_states = [s for s in WC.psprite_states() if gd.STATES[s].action in ("A_Punch", "A_Saw")]
    assert len(melee_states) == 3                               # S_PUNCH3, S_SAW1, S_SAW2
    assert shoot.count("stl.fcall dm_go, dm_ret") == 1 + len(melee_states)        # sh_gun + one per melee state
    assert {d.partition(":")[0] for d in WC.shot_decls()} == {"sh_row", "sh_ret", "dm_id", "dm_dmg", "dm_melee",
                                                              "dm_reach"}
