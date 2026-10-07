"""M7 P6 (doomfj.barrelcode, docs/gp-p67-interface.md 4.3): the barrels' TABLES and static facts against the model.

  * `barnext` against `combat._barrels_phase` / `_barrel_set_state` stepped from every barrel state;
  * the static CHAIN (`chain_pairs`) against `combat._radius_attack`'s third loop, and its emit-time assert -- R9: a
    sight segment laid across a pair, and a barrel moved by 200 units, must change the verdict;
  * the blast's LOS lists (`monstersight.spot_lists` at `blast_margin`) hold every segment a blast's trace can meet --
    R9: the lists without the margin miss some; `segments_touch` is symmetric in its first two points (the fj puts the
    barrel first, the model the target);
  * `_bounds` at the blast's margin holds and a far wider one is refused;
  * the gib profiles (damagecode `full`): the rules hold at DM_MAX_FULL, and the "no gib" rule refuses it (control);
  * the puffs (projcode `puffs`): S_PUFF1..4 in the pool, `pjst` steps them to S_NULL;
  * the barrels' level start is the same on every skill; `barrel_parts` emits every stub its callers name.
"""
import random

import pytest

from doomfj import barrelcode as BC
from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import monstersight as MS
from doomfj import projcode as PC
from doomfj.combat import BOMB_DAMAGE, PLAYER_R
from doomfj.world import TicEvents, World, segments_touch


@pytest.fixture(scope="module")
def world():
    return World(monsters="full", sight_rule="seen", player="full")


def test_barnext_steps_as_the_model(world):
    w = world
    vals = BC.barnext_values()
    blasts = []
    saved = w._radius_attack
    w._radius_attack = lambda b, ev: blasts.append(b)
    try:
        for s in BC.barrel_states():
            ws0 = w.ws.copy()
            w.ws.bar_state[3], w.ws.bar_tics[3], w.ws.bar_solid[3] = gd.STATE_INDEX[s], 1, 1
            blasts.clear()
            w._barrels_phase(TicEvents(0))
            row = vals[gd.STATE_INDEX[s]]
            st, ti, fl = row & 0xFF, row >> 8 & 15, row >> 12
            assert (st, ti) == (w.ws.bar_state[3], w.ws.bar_tics[3]), s
            assert bool(fl & BC.FL_EXPLODE) == (blasts == [3]), (s, fl, blasts)
            assert bool(fl & BC.FL_REMOVE) == (w.ws.bar_state[3] == 0 == w.ws.bar_solid[3]), s
            w.ws = ws0
    finally:
        w._radius_attack = saved
    assert sum(1 for v in vals if v >> 12 & BC.FL_EXPLODE) == 1 and sum(1 for v in vals if v >> 12 & BC.FL_REMOVE) == 1


def _model_chain(w, b):
    """the model's `_radius_attack(b)` third loop: [(c, damage)] with the player dead and no monster"""
    out = []
    ws0 = w.ws.copy()
    w.ws.p_dead = 1
    for m in range(w.layout.nmon):
        w.ws.mon_active[m] = 0
    saved = w.damage_barrel
    w.damage_barrel = lambda c, dmg, ev: out.append((c, dmg))
    try:
        w._radius_attack(b, TicEvents(0))
    finally:
        w.damage_barrel = saved
        w.ws = ws0
    return out


def test_the_static_chain_is_the_models(world):
    chains = BC.chain_pairs(world)
    assert sum(len(v) for v in chains.values()) == 96, "the plan's MEASURED 96 in-range pairs"
    for b in range(len(world.barrel_things)):
        assert chains[b] == _model_chain(world, b), b


def test_control_a_blocked_pair_is_refused(world, monkeypatch):
    t14, t15 = world.barrel_things[14], world.barrel_things[15]
    mx, my = (t14.x + t15.x) // 2, (t14.y + t15.y) // 2
    segs = MS.sight_segments(world)
    wall = dict(a=(mx - 40, my), b=(mx + 40, my), box=(mx - 40, mx + 40, my, my), dyn=None)
    monkeypatch.setattr(MS, "sight_segments", lambda w: segs + [wall])
    with pytest.raises(AssertionError):
        BC.chain_pairs(world)


def test_control_a_moved_barrel_changes_the_chain(world, monkeypatch):
    import dataclasses
    before = BC.chain_pairs(world)
    things = list(world.barrel_things)
    things[17] = dataclasses.replace(things[17], x=things[17].x + 200)
    monkeypatch.setattr(world, "barrel_things", things)
    assert BC.chain_pairs(world) != before


def test_segments_touch_is_symmetric():
    rnd = random.Random(7)
    for _ in range(20000):
        p = (rnd.randint(-50, 50) << 16 | rnd.choice((0, rnd.randrange(1 << 16))), rnd.randint(-50, 50) << 16)
        q = (rnd.randint(-50, 50) << 16, rnd.randint(-50, 50) << 16 | rnd.choice((0, rnd.randrange(1 << 16))))
        a = (rnd.randint(-50, 50) << 16, rnd.randint(-50, 50) << 16)
        b = rnd.choice(((rnd.randint(-50, 50) << 16, rnd.randint(-50, 50) << 16), (a[0], a[1] + (5 << 16)), q))
        assert segments_touch(p, q, a, b) == segments_touch(q, p, a, b), (p, q, a, b)


def _missing(w, margin):
    """traces from each barrel to targets the blast can reach (Chebyshev < 128 + r, r up to the largest radius,
    a random 16.16 fraction): the segments whose box meets the trace's box but are not in the barrel's list"""
    segs = MS.sight_segments(w)
    spots = [(t.x, t.y) for t in w.barrel_things]
    lists = MS.spot_lists(segs, spots, margin)
    rmax = max([PLAYER_R] + list(w.mon_radius[:w.layout.nmon]))
    rnd = random.Random(0xB1A57)
    n = 0
    for b, (x, y) in enumerate(spots):
        have = set(lists[b])
        for _ in range(300):
            e = BOMB_DAMAGE + rmax
            qx = ((x + rnd.randint(-e, e - 1)) << 16) + rnd.randrange(1 << 16)
            qy = ((y + rnd.choice((rnd.randint(-e, e - 1), -e, e - 1))) << 16) + rnd.randrange(1 << 16)
            x0, x1 = sorted((x << 16, qx))
            y0, y1 = sorted((y << 16, qy))
            n += sum(1 for k, g in enumerate(segs) if k not in have and not (
                g["box"][1] << 16 < x0 or g["box"][0] << 16 > x1 or g["box"][3] << 16 < y0 or g["box"][2] << 16 > y1))
    return n


def test_the_blast_lists_hold_every_candidate(world):
    rmax = max([PLAYER_R] + list(world.mon_radius[:world.layout.nmon]))
    assert MS.blast_margin(rmax) == BOMB_DAMAGE + 30 + 1
    assert _missing(world, MS.blast_margin(rmax)) == 0
    assert _missing(world, 0) > 0, "the margin control finds nothing to miss"


def test_the_bounds_hold_at_the_blast_margin(world):
    segs = MS.sight_segments(world)
    MS._bounds(segs, MS.blast_margin(30))
    with pytest.raises(AssertionError):
        MS._bounds(segs, 1 << 18)


def test_the_gib_profiles_and_rules(world):
    DC.check_model_rules(world, max_dmg=DC.DM_MAX_FULL, gib=True)
    keys, of = DC.profiles(world, gib=True)
    assert len(of) == world.layout.nmon and len(keys) <= 16 and all(len(k) == 7 for k in keys)
    with pytest.raises(AssertionError):
        DC.check_model_rules(world, max_dmg=DC.DM_MAX_FULL)            # the "no gib" rule refuses 200
    # the gib bound: the zombieman, the sergeant and the imp gib; the demon and the spectre have no xdeath
    xd = {world.mon_things[m].type: world.mon_info[m].xdeathstate for m in range(world.layout.nmon)}
    assert sum(1 for v in xd.values() if v != gd.S_NULL) >= 3


def test_the_puffs_join_the_pool():
    assert PC.pool_states(puffs=True)[-4:] == ["S_PUFF1", "S_PUFF2", "S_PUFF3", "S_PUFF4"]
    assert "S_PUFF1" not in PC.pool_states()
    vals = PC.pjst_values(puffs=True)
    for s, nxt in (("S_PUFF1", "S_PUFF2"), ("S_PUFF2", "S_PUFF3"), ("S_PUFF3", "S_PUFF4")):
        assert vals[gd.STATE_INDEX[s]] == gd.STATE_INDEX[nxt] | gd.STATES[nxt].tics << 8
    assert vals[gd.STATE_INDEX["S_PUFF4"]] == 0
    PC.check_model_rules(puffs=True)
    # the pool table without puffs is unchanged (the "fx" tier's emission)
    old = PC.pjst_values()
    assert vals[:len(old)] == [v if gd.STATE_NAMES[i] not in ("S_PUFF1", "S_PUFF2", "S_PUFF3", "S_PUFF4") else vals[i]
                               for i, v in enumerate(old)]


def test_the_level_start_is_one_for_every_skill(world):
    v = [BC.level_start_values(world, sk) for sk in (1, 2, 3)]
    assert v[0] == v[1] == v[2]
    assert v[0]["bar_st"] == [gd.STATE_INDEX["S_BAR1"]] * len(world.barrel_things)
    assert v[0]["bar_hp"] == [gd.MOBJINFO["MT_BARREL"].spawnhealth] * len(world.barrel_things)
    BC.check_model_rules(world, (1, 2, 3))


def test_barrel_parts_emit_every_stub_its_callers_name(world):
    n = world.layout.nmon
    bp = BC.barrel_parts(world, nt=68, slot_rt=list(range(n)), boot_skill=3, skills=(1, 2, 3),
                         barrel_rt={15: 70, 0: 71})
    dp = DC.damage_parts(world, slot_rt=list(range(n)), boot_skill=3, fx=True, full=True, nbar=bp["nbar"],
                         drops=bp["drops"])
    text = "\n".join(bp["lines"] + dp["lines"])
    labels = {ln.strip()[:-1] for ln in text.split("\n") if ln.strip().endswith(":") and " " not in ln.strip()}
    assert all("dmb%d" % b in labels for b in range(bp["nbar"]))
    assert all("drop_link%d" % k in labels and "drop_take%d" % k in labels for k in range(bp["ndrop"]))
    assert all("bdm%d" % c in labels for c in range(bp["nbar"]))
    # damagecode jumps to every barrel id and calls drop_link for exactly the dropper slots
    assert text.count("stl.fcall drop_link") == bp["ndrop"] == 25
    assert bp["nbar"] == 22 and n + bp["nbar"] + 1 == 76
    assert len(bp["restart"]) == 3 and bp["drop_first"] == 78
    # the runtime barrels unlink at S_NULL, the baked ones do not
    assert text.count("stl.fcall pw_unlink, pw_ulret") == 2 + 1          # the runtime barrels, the shared take
