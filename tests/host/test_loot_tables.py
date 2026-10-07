"""M7 P6 + P7, package B (doomfj.lootcode): every table the player's loot code reads, value-checked on EVERY entry
against the model's own rules, and the pickup grid's exactness proof.

  * `amcap` -- combat.max_ammo for every (backpack, ammo), and 0 in the unused rows;
  * `nkleaf` -- combat.SECTOR_HURT of every leaf's sector (P_PlayerInSpecialSector), E1M1: the three special-7 sectors;
  * `bk10` -- A_Punch's berserk x10 for every melee damage the punch rolls (combat.Sites.punch) and every index;
  * `bonpal` / the berserk red / the palette steps (hurtcode.loot_palette) -- combat.palette_index over every strength;
  * the pickup GRID -- for every cell and every item, listed iff the item's open touch box meets the CLOSED cell at
    16.16 (re-derived here by interval arithmetic, not by the function under test), and complete at sampled points
    (every overlapping item is in the point's cell list); R9: a grid with one entry dropped is caught by the same
    checks;
  * the pickups' presence slots, their per-skill level start, the droppers, the loot cells' level start.
"""
import random

import pytest

from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import lootcode as L
from doomfj.collision import CELL_SHIFT, cell_of
from doomfj.combat import ITEM_RADIUS, PLAYER_R, SECTOR_HURT, Sites, palette_index
from doomfj.world import World


@pytest.fixture(scope="module")
def world():
    return World(skill=gd.SK_HARD)


def test_amcap_is_max_ammo_on_every_entry(world):
    vals = L.amcap_values()
    assert len(vals) == 32
    ws = world.ws
    keep = ws.p_backpack
    try:
        for i, v in enumerate(vals):
            bp, a = i >> 4, i & 15
            if a >= gd.NUMAMMO:
                assert v == 0, i
                continue
            ws.p_backpack = bp
            assert v == world.max_ammo(a), (i, v)
    finally:
        ws.p_backpack = keep


def test_nkleaf_is_the_sectors_damage_on_every_leaf(world):
    vals = L.nkleaf_values(world)
    assert len(vals) == len(world.cmap.subsectors)
    for leaf, v in enumerate(vals):
        assert v == SECTOR_HURT.get(world.secs[world.leaf_sector[leaf]].special, 0), leaf
    hurt = sorted({world.leaf_sector[s] for s, v in enumerate(vals) if v})
    assert hurt == [23, 38, 173] and {v for v in vals if v} == {5}, (hurt, set(vals))


def test_bk10_is_the_berserk_punch_on_every_entry(world):
    vals = L.bk10_values()
    assert len(vals) == 256
    for v, x in enumerate(vals):
        assert x == (v * 10 if v * 10 < 256 else 0), v
    # every damage A_Punch rolls (combat.Sites.punch) x10 fits a byte, and is the model's `damage *= 10`
    rolled = {d for d, _col in Sites(world.rm).punch[1]}
    assert rolled == set(range(2, 21, 2))
    assert all(vals[d] == d * 10 <= 200 for d in rolled)


def test_bonpal_and_the_loot_palette_are_st_dopalettestuff():
    from types import SimpleNamespace as NS
    vals = H.bonpal_values()
    assert len(vals) == 256
    for bc, v in enumerate(vals):
        assert v == palette_index(NS(p_damagecount=0, p_strength=0, p_bonuscount=bc)), bc
    bad = [(dc, st, bc) for st in range(0x10000) for dc in (0, 1, 8, 9, 17, 100) for bc in (0, 1, 8, 9, 255)
           if H.loot_palette(dc, st, bc) != palette_index(NS(p_damagecount=dc, p_strength=st, p_bonuscount=bc))]
    assert not bad, bad[:5]


def test_the_loot_palette_control_is_caught():
    """R9: the same comparison refuses a berserk red without its fade (always 3 while strength runs)"""
    from types import SimpleNamespace as NS
    def broken(dc, st, bc):
        red = max(H.red_palette(dc), 3 if st else 0)
        return red if red else H.bonus_palette(bc)
    assert any(broken(0, st, 0) != palette_index(NS(p_damagecount=0, p_strength=st, p_bonuscount=0))
               for st in range(0x10000))


# ---- the grid -------------------------------------------------------------------------------------------------------
S = 1 << CELL_SHIFT
BD = (ITEM_RADIUS + PLAYER_R) << 16


def _meets(t, cx, cy) -> bool:
    """the item's OPEN box (x - 36, x + 36) at 16.16 meets the CLOSED cell [c*S, c*S + S - 1] on both axes"""
    def axis(c16, c):
        lo, hi = c * S, c * S + S - 1
        return hi > c16 - BD and lo < c16 + BD
    return axis(t.x << 16, cx) and axis(t.y << 16, cy)


def _grid_errors(world, lists):
    errs = []
    items = world.pickup_things
    cells = set(lists)
    for t_i, t in enumerate(items):           # every cell any item can reach: a margin of 3 cells
        for cx in range(((t.x << 16) - BD) // S - 2, ((t.x << 16) + BD) // S + 3):
            for cy in range(((t.y << 16) - BD) // S - 2, ((t.y << 16) + BD) // S + 3):
                cells.add((cx, cy))
    for c in cells:
        want = tuple(i for i, t in enumerate(items) if _meets(t, *c))
        if lists.get(c, ()) != want:
            errs.append((c, lists.get(c, ()), want))
    rnd = random.Random(7)
    for _ in range(4000):                     # completeness at points: every overlapping item is listed, in order
        t = rnd.choice(items)
        x16 = (t.x << 16) + rnd.randint(-BD - 3, BD + 3)
        y16 = (t.y << 16) + rnd.randint(-BD - 3, BD + 3)
        hit = tuple(i for i, u in enumerate(items) if abs((u.x << 16) - x16) < BD and abs((u.y << 16) - y16) < BD)
        got = lists.get((cell_of(x16), cell_of(y16)), ())
        if not set(hit) <= set(got) or list(got) != sorted(got):
            errs.append(((x16, y16), got, hit))
    return errs


def test_the_pickup_grid_is_exact(world):
    lists = L.pickup_cell_lists(world)
    assert not _grid_errors(world, lists)
    assert max(len(v) for v in lists.values()) >= 2, "no cell holds two items: the order is untested"


def test_a_grid_missing_one_entry_is_caught(world):
    lists = dict(L.pickup_cell_lists(world))
    c = next(c for c, v in sorted(lists.items()) if len(v) >= 2)
    lists[c] = lists[c][1:]
    assert _grid_errors(world, lists)


# ---- presence, droppers, cells ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def slots(world):
    from pathlib import Path
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(Path(__file__).resolve().parents[2] / "assets" / "freedoom1.wad"))
    return L.pickup_slots(world, world.rm, world.mw, "E1M1", art)


def test_every_pickup_has_its_own_slot(world, slots):
    s = slots["slot"]
    assert len(s) == len(world.pickup_things) == 95
    assert len(set(s)) == len(s)
    assert slots["nextra"] == sum(r is not None for r in slots["rt"]) == 10
    assert all((r is None) == (v < slots["nvis"]) for r, v in zip(slots["rt"], s))
    assert sorted(v for v in s if v >= slots["nvis"]) == list(range(slots["nvis"], slots["nvis"] + 10))
    assert all(lf == world.rm.point_in_subsector(world.cmap, t.x, t.y)
               for t, r, lf in zip(world.pickup_things, slots["rt"], slots["leaf"]) if r is not None)


def test_the_extra_slots_start_as_the_models_pickup_taken(world, slots):
    for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD):
        ws = world.level_start(sk)
        vis = L.extra_vis(world, slots, sk)
        for i, r in enumerate(slots["rt"]):
            if r is not None:
                assert vis[slots["slot"][i] - slots["nvis"]] == 1 - ws.pickup_taken[i], (sk, i)


def test_the_droppers_and_the_gives(world):
    d = L.droppers(world)
    assert len(d) == 25 and d == sorted(d)
    assert all(world.dropper[m] in (2007, 2001) for m in d)
    kinds = L.give_kinds(world)
    assert {k for k, dr in kinds if not dr} == {t.type for t in world.pickup_things}
    assert {k for k, dr in kinds if dr} == {2007, 2001}
    from doomfj.combat import GETTABLE
    assert {k for k, _ in kinds} <= GETTABLE


def test_the_loot_cells_start_at_the_level_start(world):
    st = L.level_start(world)
    ws = world.level_start(gd.SK_HARD)
    assert st == {"p_bc": ws.p_bonuscount, "p_str": ws.p_strength, "p_bp": ws.p_backpack,
                  "am_misl": ws.p_ammo[gd.AM_MISL], "am_cell": ws.p_ammo[gd.AM_CELL]} == dict.fromkeys(st, 0)
    assert L.restart_lines(st) == ["hex.set 2, p_bc, 0", "hex.set 4, p_str, 0", "hex.set 1, p_bp, 0",
                                   "hex.set 3, am_misl, 0", "hex.set 3, am_cell, 0"]


def test_the_off_switches_leave_the_p5_text(world):
    """loot off: no lootcode label leaks into the weapon, palette, door or move text"""
    from doomfj import weaponcode as WC
    from doomfj.collision import move_with_collision_lines
    st, fr = WC.weapon_states(), WC.overlay_frames()
    text = "\n".join(WC.weapon_lines(st, fr, True, True, True) + H.pal_lines()
                     + move_with_collision_lines("R", "e1m1", radius=16 << 16, height=56, maxstep=24))
    for word in ("p_dd0", "p_str", "bk10", "bonpal", "pb_mon", "pk_go", "playpal9", "cma_go", "cmc_sx"):
        assert word not in text, word


def test_pkxyz_is_every_pickups_place_on_every_entry(world):
    """`pkxyz` (pk_box's item row): x, y and the model's pickup_z, each 16-bit two's complement, decoded back"""
    def s16(v):
        return v - 0x10000 if v & 0x8000 else v
    vals = L.pkxyz_values(world)
    assert len(vals) == len(world.pickup_things) == 95
    for i, (v, t, z) in enumerate(zip(vals, world.pickup_things, world.pickup_z)):
        assert (s16(v & 0xFFFF), s16(v >> 16 & 0xFFFF), s16(v >> 32 & 0xFFFF)) == (t.x, t.y, z), i
        assert v >> 48 == 0
    assert any(t.x < 0 for t in world.pickup_things) and any(z < 0 for z in world.pickup_z)   # the sign is exercised
