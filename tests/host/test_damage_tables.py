"""M7 P4.2a (doomfj.damagecode): the folded P_Random table `dmrnd` against the SLOW formulas -- successive
`rng.p_random` calls through `combat.site_formulas` -- and against the model's own outcome tables (`combat.Sites`),
over all 256 stream states; and the emit-time rules `damagecode.check_model_rules` holds.

R9: a table folded with `<=` for the pain roll, or `& 7` for the tics, must fail the same comparison; a damage that
could gib, and a death state that could clamp, must fail the rules.
"""
import dataclasses

import pytest

from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.combat import Sites, site_formulas
from doomfj.reference_model import ReferenceModel
from doomfj.world import World


@pytest.fixture(scope="module")
def world():
    return World(monsters="decide", sight_rule="seen", player="shoot")


def _mismatches(world, table):
    """indices where `table` (by POST-increment state) disagrees with the slow formulas or the model's tables"""
    keys, _of = DC.profiles(world)
    classes = DC.pain_classes(keys)
    slow = site_formulas(lambda s: 0)
    sites = Sites(ReferenceModel())
    bad = []
    for i in range(1 << R.STATE_BITS):
        v, post = R.p_random((i - 1) & R.STATE_MASK)
        assert post == i
        row = table[i]
        ok = (row & 15) == slow["tics_roll"][1](v) == sites.tics_roll[1][i]
        for c, pc in enumerate(classes):
            bit = row >> (4 + c) & 1
            ok &= bit == slow["pain_%d" % pc][1](v) == sites.pain[pc][1][i]
        ok &= row >> (4 + len(classes)) == 0
        if not ok:
            bad.append(i)
    return bad


def test_the_folded_table_equals_the_slow_formulas(world):
    keys, _of = DC.profiles(world)
    assert len(DC.pain_classes(keys)) >= 2, "E1M1's types have more than one painchance: the bits are all live"
    assert _mismatches(world, DC.dmrnd_values(DC.pain_classes(keys))) == []


def test_control_a_misfolded_table_is_caught(world):
    keys, _of = DC.profiles(world)
    classes = DC.pain_classes(keys)
    le = R.outcome_table(lambda v: (v & 3) | (sum(int(v <= pc) << c for c, pc in enumerate(classes)) << 4))
    seven = R.outcome_table(lambda v: (v & 7) | (DC.dmrnd_row(v, classes) & ~15))
    assert _mismatches(world, le), "a `<=` pain roll passed"
    assert _mismatches(world, seven), "a `& 7` tics roll passed"


def test_the_pain_masks_select_their_class():
    for c in range(4):
        m = DC.pain_mask(c)
        assert all((m >> n & 1) == (n >> c & 1) for n in range(16)), c


def test_the_model_rules_hold_on_e1m1(world):
    DC.check_model_rules(world)
    keys, of = DC.profiles(world)
    assert len(of) == world.layout.nmon and max(of) < len(keys) <= 16


def test_control_the_rules_refuse_a_gib_and_a_clamp(world, monkeypatch):
    small = min(world.mon_info[m].spawnhealth for m in range(world.layout.nmon))
    with pytest.raises(AssertionError):
        DC.check_model_rules(world, max_dmg=small + 2)          # the zombieman (20) could be gibbed by 22
    death = world.mon_info[0].deathstate
    st = gd.STATES[death]
    monkeypatch.setitem(gd.STATES, death, dataclasses.replace(st, tics=3))   # tics - (P_Random() & 3) could be 0
    with pytest.raises(AssertionError):
        DC.check_model_rules(world)
