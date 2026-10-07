"""M7 P6 + P7, package B (docs/gp-p67-interface.md section 4.2) -- THE PLAYER'S SIDE in fj: pickups and every give
routine, the player blocked by things, nukage, berserk and bonus, and the dead player's guards. The model it mirrors
is `combat.CombatMixin` in the "full" player mode: `_player_phase`, `_death_think`, `_special_sector`,
`_player_move`, `_solid_thing_at`, `_touch_specials`, `_touch`, `_give_*`, `max_ammo`.

THE PICKUPS (`pk_go`, `stl.fcall pk_go, pk_ret`, at every TRIED candidate of the move: `cpx` / `cpy` 16.16, `cm_hf`
the floor at the tic-start position -- `collision.move_with_collision_lines(pickup=)`):
  * a dead player touches nothing (`p_dead`, read LIVE: a nukage death earlier in the same tic stops the touching,
    as `_touch_specials`' `player_alive` does; `p_hp <= 0` <=> `p_dead` on every reachable state, hurtcode);
  * a JUMP TREE on the candidate's 32-unit PICKUP CELL (`pickup_cell_lists`: exactly the items whose open box
    (x - 36, x + 36) x (y - 36, y + 36), 16.16, meets the closed cell -- `collision.thing_cell_lists`' interval rule,
    the host proof in tests/host/test_loot_tables.py) lands on the cell's list of item stubs, in PICKUP INDEX order;
  * item stub `pk<i>` (fcall'd, `pk_iret`): present (its `thvis` slot != 0) -> `pk_box` (ONE shared leaf: the
    item's x, y, z from the D4 table `pkxyz` by `pk_i`; the box, strict, 16.16; the reach `-8 <= item_z - cm_hf <=
    56`; `item_z` = the model's own `pickup_z`, baked: no pickup stands in a door or mover sector, asserted) -> `stl.fcall
    give_<type>, gv_ret` -> `gv_ok` ? (`pk_bonus`: `p_bc` = min(bc + 6, 255); the thvis slot 0; a RUNTIME pickup also
    unlinked from its leaf list);
  * then the DROPS, when `dr_live` != 0: each dropper k (the monster slots whose `dropper` is not None, in slot
    order) with `mdrop[k]` == 1 -> `pk_drop` (its monster's `thpos_rt` / `thss_rt` row read through a pointer: the
    16.16 position, and the floor of the corpse's leaf by `ms_seed_leaf` -> `cp_seedf`, mover-aware as the model's
    `_floor_at` reads `secs_c`; then `pk_box`'s test) -> `give_<type>d` (the dropped variants: half a clip, one clip with a shotgun) -> taken: bc,
    then package C's `drop_take<k>` (barrelcode.drop_lines: `mdrop[k]` = 2, `dr_live` - 1, row nt + 10 + k unlinked
    and cleared -- the drop's cells are C's: its `drop_link<k>` sets them, its `drop_take<k>` undoes them).

THE GIVES (`give_<type>`, fcall'd, `gv_ret`, -> `gv_ok`), `_touch`'s cases with DOOM's caps; `ga<a>` is P_GiveAmmo for
ammo a with `ga_n` rounds (the cap from ONE D4 table `amcap`[backpack << 4 | a], no runtime multiply; refused AT the
cap; from empty, the auto-switch -- E1M1 can own neither the chaingun, the plasma rifle nor the launcher, asserted,
so only the clip's "fist -> pistol" and the shells' "fist or pistol, shotgun owned -> shotgun" are emitted).

THE BLOCKING (`_solid_thing_at`): the monsters by `pb_mon` (`stl.fcall pb_mon, pb_ret` -> `pb_hit`; per slot
`mon_solid`, then |x - cpx| < (r + 16) << 16 on both axes, 16.16, strict) -- `collision.move_with_collision_lines
(block=)` refuses the candidate after its pickups, before its P_TryMove, the model's order; the static blockers
(barrels by `bar_solid`, decorations by `mc_don`) in the PLAYER's collision cells (`player_cell_things`), tested by
`THING_TEST16` (16.16, strict) in place of the monsters' whole-unit `sim.thing_test`.

NUKAGE (`nk_go`, alive only, before the weapon keys): `lvtime & 31 == 0` -> `ptloc_walk` at the player's whole-unit
position -> `nkleaf`[leaf] (the sector's SECTOR_HURT damage, 0 none) -> `ms_seed_leaf` (the sector's floor now) and
`sim.check_cells` at (viewx, viewy) (the box's floorz) -> equal -> `dp_dmg` = the damage, `dp_go`.

THE TIC (P7-a): `latch` (`p_dd0` = `p_dead`, at the world tic's start, after the restart block); `pre` (before the
weapon: nukage when alive); the weapon tic; then the damagecount fade -- hurtcode's `tic` when alive, and when dead at
the tic's start package D's `dt_turn` in its place (hurtcode.turn_lines: P_DeathThink's turn to the killer, and the
fade it allows: `tic_lines`); `post` (before the move): dead ->
the death think's tail (use HELD -> `g_rs` = 1) and a jump past the whole move (turning included: the turn block
`simth_*` and `p_tnh` are left as they were, as the model's dead branch returns before `_player_move`); alive ->
`p_str` + 1 (saturating at 0xFFFF, only when running) and `p_bc` - 1 (to 0). Every dead-player guard reads `p_dd0`,
the TIC-START state: `doorcode.door_tic_lines(dead=)` (the use press, the closing door's player contact), `use_guard`
around the use lines (the exit, the SR lifts, the floor switch -- `pusedn` untouched, as `_death_think` leaves
p_usedown), `weaponcode.weapon_lines(loot=True)`'s key skip.

THE PALETTE (berserk and bonus) and the berserk fist are hurtcode's / weaponcode's `loot=True` emissions.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence

from doomfj import gamedata as gd
from doomfj.lut_generator import generate_dispatch_table_fj

M32 = 0xFFFFFFFF
# the player modes whose player LOOTS (world.PLAYER_MODES): P6 + P7 ship as "full"
LOOT_PLAYER_MODES = ("full", "final")      # M7 P8a: "final" is "full" and more
# (cell, schema field, nibbles, ammo index or None): the persisted loot cells (section 4.5)
CELLS = (("p_bc", "p_bonuscount", 2, None), ("p_str", "p_strength", 4, None), ("p_bp", "p_backpack", 1, None),
         ("am_misl", "p_ammo", 3, gd.AM_MISL), ("am_cell", "p_ammo", 3, gd.AM_CELL))
PERSIST = tuple(c for c, _f, _n, _a in CELLS)
# every ammo cell by AM_* (am_clip / am_shell are weaponcode's)
AMMO_CELL = {gd.AM_CLIP: "am_clip", gd.AM_SHELL: "am_shell", gd.AM_CELL: "am_cell", gd.AM_MISL: "am_misl"}
BONUS_CAP = 255                       # p_bonuscount saturates (combat's docstring)
STRENGTH_CAP = 0xFFFF
PK_RADIUS = 20 + 16                   # combat.ITEM_RADIUS + PLAYER_R: the touch box's half-width
REACH_UP, REACH_DOWN = 56, 8          # combat.REACH_UP / REACH_DOWN
# the dropped variants' give routines (DROP_ITEM's types, `dropped=True`)
DROPPED = {2007: "give_2007d", 2001: "give_2001d"}
WEAPON_OWN = {gd.WP_FIST: 0, gd.WP_PISTOL: 1, gd.WP_SHOTGUN: 2, gd.WP_CHAINSAW: 3}   # weaponcode.OWN


def loot_on(player_mode: str) -> bool:
    return player_mode in LOOT_PLAYER_MODES


def _check_rules() -> None:
    """the constants above are the model's (assert, don't trust)"""
    from doomfj import combat as C
    from doomfj import weaponcode as WC
    assert PK_RADIUS == C.ITEM_RADIUS + C.PLAYER_R, (C.ITEM_RADIUS, C.PLAYER_R)
    assert (REACH_UP, REACH_DOWN) == (C.REACH_UP, C.REACH_DOWN)
    assert WEAPON_OWN == WC.OWN, WC.OWN
    assert {v: k for k, v in AMMO_CELL.items()}["am_clip"] == gd.AM_CLIP and WC.AMMO_CELL == {
        gd.AM_CLIP: "am_clip", gd.AM_SHELL: "am_shell"}
    assert set(C.DROP_ITEM.values()) == set(DROPPED)
    assert gd.BONUSADD == 6 and gd.MAXHEALTH == 100 and C.MAX_HEALTH_BONUS == 200 == C.MAX_ARMOR_BONUS
    # every cap fits the 3-nibble ammo cells, and a give never overflows one: cap + the largest give < 4096
    assert max(gd.MAXAMMO) * 2 + 5 * max(gd.CLIPAMMO) < 16 ** 3


# ---- the tables -------------------------------------------------------------------------------------------------
def amcap_values() -> List[int]:
    """`amcap`, indexed backpack << 4 | ammo: max_ammo (MAXAMMO, doubled by the backpack)"""
    out = [0] * 32
    for bp in (0, 1):
        for a in range(gd.NUMAMMO):
            out[bp << 4 | a] = gd.MAXAMMO[a] * (2 if bp else 1)
    return out


def nkleaf_values(w) -> List[int]:
    """`nkleaf`, by leaf: P_PlayerInSpecialSector's damage for the leaf's sector (combat.SECTOR_HURT), 0 none"""
    from doomfj.combat import SECTOR_HURT
    return [SECTOR_HURT.get(w.secs[w.leaf_sector[s]].special, 0) for s in range(len(w.cmap.subsectors))]


def bk10_values() -> List[int]:
    """`bk10`: the berserk fist's damage x10 (A_Punch's `damage *= 10`), by the melee damage; 0 past one byte"""
    return [v * 10 if v * 10 < 256 else 0 for v in range(256)]


def tables_fj(w) -> List[str]:
    """every D4 table the loot code reads: amcap, nkleaf, pkxyz (bk10 is weaponcode's, bonpal hurtcode's)"""
    nk = nkleaf_values(w)
    assert max(nk) < 256
    return [generate_dispatch_table_fj("amcap", amcap_values(), index_nibbles=2, result_nibbles=3),
            generate_dispatch_table_fj("nkleaf", nk, index_nibbles=3, result_nibbles=2),
            pickup_table_fj(w)]


# ---- which cell each pickup lives in ---------------------------------------------------------------------------
def pickup_cell_lists(w) -> Dict[tuple, tuple]:
    """`{(cx, cy): (pickup index, ...)}` -- the 32-unit cells (collision.CELL_SHIFT) a candidate centred anywhere in
    which can overlap pickup i's touch box: `collision.thing_cell_lists`' exact open-interval rule with the player's
    radius and the item's 20, ascending (the model's touch order)"""
    from doomfj.collision import thing_cell_lists
    from doomfj.combat import ITEM_RADIUS, PLAYER_R
    return thing_cell_lists([(t.x, t.y, ITEM_RADIUS) for t in w.pickup_things], PLAYER_R << 16)


def pickup_slots(w, rm, map_wad, mapname: str, sprite_wad) -> dict:
    """where each pickup's presence lives, the emitter's own split (`things.drawable_things` / `baked_thing_mask` /
    `vanishable_slots`): {"slot": [thvis slot per pickup], "rt": [runtime thing or None], "leaf": [its spawn leaf or
    None], "nvis": the baked vis slots, "nextra": the runtime pickups' extra slots}. A BAKED pickup's slot is its
    vis slot; the k-th RUNTIME pickup (pickup order) gets slot nvis + k, so the probe reads "taken" for every pickup
    from `thvis` alike (section 4.5)."""
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import MONSTER_TYPES, VANISHABLE_TYPES
    from doomfj.things import baked_thing_mask, drawable_things, vanishable_slots
    drawable, draw_idx = drawable_things(rm, map_wad.things(mapname), sprite_wad, {})
    cmap = bake_bsp(map_wad, mapname)
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    vis = vanishable_slots(drawable, baked, VANISHABLE_TYPES)
    keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
    key = {(t.type, t.x, t.y, t.angle, t.flags): i for i, t in enumerate(drawable)}
    slot, rt, leaf, extra = [], [], [], 0
    for t in w.pickup_things:
        di = key[(t.type, t.x, t.y, t.angle, t.flags)]
        if di in vis:
            slot.append(vis[di])
            rt.append(None)
            leaf.append(None)
        else:
            assert not baked[di], "pickup %s is baked but cannot vanish" % ((t.type, t.x, t.y),)
            slot.append(len(vis) + extra)
            rt.append(keep.index(draw_idx[di]))
            leaf.append(rm.point_in_subsector(cmap, t.x, t.y))
            extra += 1
    return {"slot": slot, "rt": rt, "leaf": leaf, "nvis": len(vis), "nextra": extra}


def extra_vis(w, slots: dict, skill: int) -> List[int]:
    """the runtime pickups' extra `thvis` slots at `skill`'s level start (1 present, 0 not on this skill), slot
    order -- the boot block and each skill's restart half set them as they set the vis slots"""
    bit = gd.skill_bit(skill)
    out = [0] * slots["nextra"]
    for i, t in enumerate(w.pickup_things):
        if slots["rt"][i] is not None:
            out[slots["slot"][i] - slots["nvis"]] = 1 if t.flags & bit else 0
    return out


def droppers(w) -> List[int]:
    """the monster slots that drop something when killed, in slot order: dropper k is slot droppers(w)[k]"""
    return [m for m, d in enumerate(w.dropper) if d is not None]


# ---- the cells --------------------------------------------------------------------------------------------------
def level_start(w) -> Dict[str, int]:
    """the loot cells' level-start values from a World (the player's start does not depend on the skill)"""
    from doomfj.monstercode import cell_nibbles
    ws = w.ws
    out = {}
    for cell, field, nib, a in CELLS:
        assert cell_nibbles(w.schema, field) >= (nib if a is None else 3), (field, nib)
        v = getattr(ws, field) if a is None else ws.p_ammo[a]
        out[cell] = v & (16 ** nib - 1)
    return out


def loot_decls(start: Dict[str, int]) -> List[str]:
    """the persisted cells (at `start`), the latch, the interfaces and the scratch"""
    return ([f"{cell}: hex.vec {nib}, {start[cell]}" for cell, _f, nib, _a in CELLS]
            + ["p_dd0: hex.vec 1",                                          # the TIC-START p_dead (P7-a)
               "gv_ok: hex.vec 1", "gv_ret: hex.vec w/4", "gv_c: hex.vec 3",
               "ga_ret: hex.vec w/4", "ga_n: hex.vec 3", "ga_z: hex.vec 1", "amc_i: hex.vec 2", "amc_c: hex.vec 3",
               "pk_ret: hex.vec w/4", "pk_iret: hex.vec w/4", "pk_bret: hex.vec w/4", "pk_dret: hex.vec w/4",
               "pk_nret: hex.vec w/4", "pk_d: hex.vec 8", "pk_bd: hex.vec 8, %d" % (PK_RADIUS << 16),
               "pk_cup: hex.vec 8, %d" % REACH_UP, "pk_cdn: hex.vec 8, %d" % (-REACH_DOWN & M32),
               "pk_i: hex.vec 2", "pk_r: hex.vec 12", "pk_tx: hex.vec 8", "pk_ty: hex.vec 8", "pk_tz: hex.vec 8",
               "pk_in: hex.vec 1", "pk_t: hex.vec 2", "pk_off: hex.vec w/4", "pk_base: hex.vec w/4",
               "pk_ptr: hex.vec w/4", "pk_pos: hex.vec 16",
               "pb_ret: hex.vec w/4", "pb_tret: hex.vec w/4", "pb_hit: hex.vec 1", "pb_c: hex.vec 8",
               "pb_tx: hex.vec 8", "pb_ty: hex.vec 8",
               "pb_bd20: hex.vec 8, %d" % ((20 + 16) << 16), "pb_bd30: hex.vec 8, %d" % ((30 + 16) << 16),
               "pbt_a: hex.vec 8", "pbt_b: hex.vec 8",
               "nk_ret: hex.vec w/4", "nk_dmg: hex.vec 2"])


def restart_lines(start: Dict[str, int]) -> List[str]:
    """NEW GAME / the restart: every persisted loot cell back to its level start"""
    return [f"hex.set {nib}, {cell}, {start[cell]}" for cell, _f, nib, _a in CELLS]


# ---- small fj helpers ---------------------------------------------------------------------------------------------
def _bonus_lines(p: str) -> List[str]:
    """P_TouchSpecialThing's `bonuscount += BONUSADD`, saturating at 255 (bc > 249 -> 255)"""
    return [f"    hex.set 2, gv_c, {BONUS_CAP - gd.BONUSADD}",
            f"    hex.cmp 2, p_bc, gv_c, {p}ba, {p}ba, {p}bs",
            f"  {p}bs:", f"    hex.set 2, p_bc, {BONUS_CAP}", f"    ;{p}be",
            f"  {p}ba:", f"    hex.add_constant 2, p_bc, {gd.BONUSADD}",
            f"  {p}be:"]


def _if_ready(p: str, weapons, yes: str, no: str) -> List[str]:
    """jump to `yes` when wp_rdy is one of `weapons`, else `no`"""
    mask = sum(1 << w for w in weapons)
    return [f"    hex.if_flags wp_rdy, {mask:#06x}, {no}, {yes}"]


# ---- the give routines ------------------------------------------------------------------------------------------
def give_ammo_lines(a: int) -> List[str]:
    """`ga<a>` (stl.fcall ga<a>, ga_ret): P_GiveAmmo for ammo a with `ga_n` rounds already scaled (num * clipammo,
    or half a clip) -> `gv_ok` 1 taken, 0 refused (at the cap). From empty, DOOM's auto-switch."""
    cell = AMMO_CELL[a]
    p = f"ga{a}"
    out = [f"{p}:",
           f"    hex.set 1, amc_i, {a}", "    hex.mov 1, amc_i + dw, p_bp",
           "    amcap.lookup amc_c, amc_i",
           f"    hex.cmp 3, {cell}, amc_c, {p}_go, {p}_no, {p}_go",
           f"  {p}_no:", "    hex.zero 1, gv_ok", "    stl.fret ga_ret",
           f"  {p}_go:", "    hex.set 1, gv_ok, 1",
           "    hex.zero 1, ga_z", f"    hex.if0 3, {cell}, {p}_z0", f"    ;{p}_add",
           f"  {p}_z0:", "    hex.set 1, ga_z, 1",
           f"  {p}_add:",
           f"    hex.add 3, {cell}, ga_n",
           f"    hex.cmp 3, {cell}, amc_c, {p}_cp, {p}_cp, {p}_cap",
           f"  {p}_cap:", f"    hex.mov 3, {cell}, amc_c",
           f"  {p}_cp:",
           "    hex.if0 1, ga_z, %s_out" % p]
    # "We were down to zero, so select a new weapon." (the weapons E1M1 cannot own are asserted away)
    if a == gd.AM_CLIP:              # fist -> the chaingun if owned (never on E1M1), else the pistol
        out += _if_ready(p + "c", (gd.WP_FIST,), f"{p}_sw", f"{p}_out")
        out += [f"  {p}_sw:", f"    hex.set 1, wp_pend, {gd.WP_PISTOL}"]
    elif a == gd.AM_SHELL:           # fist or pistol, the shotgun owned -> the shotgun
        out += _if_ready(p + "s", (gd.WP_FIST, gd.WP_PISTOL), f"{p}_sw", f"{p}_out")
        out += [f"  {p}_sw:", f"    hex.if0 1, wp_own + {WEAPON_OWN[gd.WP_SHOTGUN]}*dw, {p}_out",
                f"    hex.set 1, wp_pend, {gd.WP_SHOTGUN}"]
    # AM_CELL (the plasma rifle) and AM_MISL (the launcher): never owned on E1M1 -- no switch
    out += [f"  {p}_out:", "    stl.fret ga_ret"]
    return out


def _ga_call(a: int, n: int) -> List[str]:
    return [f"    hex.set 3, ga_n, {n}", f"    stl.fcall ga{a}, ga_ret"]


def _give_body(p: str, n: int, done: str, refused: Optional[str]) -> List[str]:
    """P_GiveBody(n): health >= 100 -> refused (to `refused`, or on to `done` when the caller ignores it); else
    health = min(health + n, 100) and on to `done` (gv_ok untouched)"""
    return [f"    hex.set 3, gv_c, {gd.MAXHEALTH}",
            f"    hex.cmp 3, p_hp, gv_c, {p}gb, {refused or done}, {refused or done}",
            f"  {p}gb:", f"    hex.add_constant 3, p_hp, {n}",
            f"    hex.cmp 3, p_hp, gv_c, {done}, {done}, {p}gc",
            f"  {p}gc:", f"    hex.mov 3, p_hp, gv_c", f"    ;{done}"]


def give_lines(kind: int, dropped: bool = False) -> List[str]:
    """`give_<kind>` (`give_<kind>d` for a dropped one): combat._touch's case for `kind` after the reach test ->
    `gv_ok`. Leaves through `stl.fret gv_ret` on every path."""
    p = "give_%d%s" % (kind, "d" if dropped else "")
    ok, no = f"{p}_ok", f"{p}_no"
    out = [f"{p}:"]
    if kind in (2018, 2019):                                          # ARM1 / ARM2: P_GiveArmor
        at = 1 if kind == 2018 else 2
        out += [f"    hex.set 2, gv_c, {at * 100}",
                f"    hex.cmp 2, p_ar, gv_c, {p}_t, {no}, {no}",
                f"  {p}_t:", f"    hex.set 1, p_at, {at}", f"    hex.set 2, p_ar, {at * 100}", f"    ;{ok}"]
    elif kind == 2014:                                                # BON1: health + 1, cap 200
        out += ["    hex.inc 3, p_hp", "    hex.set 3, gv_c, 200",
                f"    hex.cmp 3, p_hp, gv_c, {ok}, {ok}, {p}_c", f"  {p}_c:", "    hex.mov 3, p_hp, gv_c", f"    ;{ok}"]
    elif kind == 2015:                                                # BON2: armor + 1, cap 200; green if none
        out += ["    hex.inc 2, p_ar", "    hex.set 2, gv_c, 200",
                f"    hex.cmp 2, p_ar, gv_c, {p}_t, {p}_t, {p}_c", f"  {p}_c:", "    hex.mov 2, p_ar, gv_c",
                f"  {p}_t:", f"    hex.if0 1, p_at, {p}_g", f"    ;{ok}", f"  {p}_g:", "    hex.set 1, p_at, 1",
                f"    ;{ok}"]
    elif kind == 5:                                                   # BKEY: P_GiveCard SETS the flash
        out += [f"    hex.if1 1, pcard, {ok}", f"    hex.set 2, p_bc, {gd.BONUSADD}", "    hex.set 1, pcard, 1",
                f"    ;{ok}"]
    elif kind in (2011, 2012):                                        # STIM / MEDI: P_GiveBody
        out += _give_body(p, 10 if kind == 2011 else 25, ok, no)
    elif kind == 2023:                                                # PSTR: P_GiveBody(100), strength, the fist
        out += _give_body(p, 100, f"{p}_s", None)
        out += [f"  {p}_s:", "    hex.set 4, p_str, 1"]
        out += _if_ready(p + "f", (gd.WP_FIST,), ok, f"{p}_f")
        out += [f"  {p}_f:", f"    hex.set 1, wp_pend, {gd.WP_FIST}", f"    ;{ok}"]
    elif kind == 8:                                                   # BPAK: the caps doubled, a clip of each
        out += ["    hex.set 1, p_bp, 1"]
        for a in range(gd.NUMAMMO):
            out += _ga_call(a, gd.CLIPAMMO[a])
        out += [f"    ;{ok}"]
    elif kind == 2005:                                                # CSAW: P_GiveWeapon, no ammo
        own = f"wp_own + {WEAPON_OWN[gd.WP_CHAINSAW]}*dw"
        out += [f"    hex.if1 1, {own}, {no}", f"    hex.set 1, {own}, 1",
                f"    hex.set 1, wp_pend, {gd.WP_CHAINSAW}", f"    ;{ok}"]
    elif kind == 2001:                                                # SHOT: P_GiveWeapon (2 clips, 1 dropped)
        own = f"wp_own + {WEAPON_OWN[gd.WP_SHOTGUN]}*dw"
        out += _ga_call(gd.AM_SHELL, gd.CLIPAMMO[gd.AM_SHELL] * (1 if dropped else 2))
        out += [f"    hex.if0 1, {own}, {p}_new", "    stl.fret gv_ret",       # owned: taken iff ammo was given
                f"  {p}_new:", f"    hex.set 1, {own}, 1", f"    hex.set 1, wp_pend, {gd.WP_SHOTGUN}", f"    ;{ok}"]
    else:                                                             # the ammo: P_GiveAmmo
        a, num = {2007: (gd.AM_CLIP, 1), 2048: (gd.AM_CLIP, 5), 2010: (gd.AM_MISL, 1), 2046: (gd.AM_MISL, 5),
                  2047: (gd.AM_CELL, 1), 17: (gd.AM_CELL, 5), 2008: (gd.AM_SHELL, 1),
                  2049: (gd.AM_SHELL, 5)}[kind]
        if dropped:
            assert kind == 2007
            num = 0
        out += _ga_call(a, num * gd.CLIPAMMO[a] if num else gd.CLIPAMMO[a] // 2)
        out += ["    stl.fret gv_ret"]
    out += [f"  {no}:", "    hex.zero 1, gv_ok", "    stl.fret gv_ret",
            f"  {ok}:", "    hex.set 1, gv_ok, 1", "    stl.fret gv_ret"]
    return out


def give_kinds(w) -> List[tuple]:
    """the give routines a World needs: (kind, dropped) for every pickup type on the map, then the drops'"""
    from doomfj.combat import DROP_ITEM
    kinds = sorted({t.type for t in w.pickup_things})
    out = [(k, False) for k in kinds]
    out += sorted({(DROP_ITEM[gd.DROPS[gd.MONSTER_DOOMEDNUMS[w.mon_things[m].type]]], True) for m in droppers(w)})
    return out


# ---- the pickups ---------------------------------------------------------------------------------------------------
def _tree(L: str, reg_x: str, reg_y: str, lists: Dict[tuple, str], none: str) -> tuple:
    """`(lines, root)`: collision.collision_cells_fj's cell tree (jump16 on nibbles 7, 6, 5 of x, then of y; both
    16-unit halves of a 32-unit cell land on the same label), for `lists` = {(cx, cy): label}"""
    from doomfj.collision import _HALVES
    nodes: dict = {}

    def node(reg, nib, targets):
        if all(t == none for t in targets):
            return none
        key = (reg, nib, targets)
        if key not in nodes:
            nodes[key] = f"{L}_n{len(nodes)}"
        return nodes[key]

    def tree(reg, leaf_of):
        def sub(keys, depth, prefix):
            if depth == 3:
                return leaf_of.get(prefix, none)
            shift = 4 * (2 - depth)
            targets = []
            for d in range(16):
                p = (prefix << 4) | d
                below = [k for k in keys if k >> shift == p]
                targets.append(sub(below, depth + 1, p) if below else none)
            return node(reg, 7 - depth, tuple(targets))
        return sub(sorted(leaf_of), 0, 0)

    def halves(c):
        return [((c * _HALVES) + h) & 0xFFF for h in range(_HALVES)]

    by_col: dict = {}
    for (cx, cy), lab in lists.items():
        by_col.setdefault(cx, {})[cy] = lab
    x_leaf = {}
    for cx in sorted(by_col):
        col = tree(reg_y, {p: lab for cy, lab in by_col[cx].items() for p in halves(cy)})
        x_leaf.update({p: col for p in halves(cx)})
    root = tree(reg_x, x_leaf)
    out = []
    for (reg, nib, targets), lab in nodes.items():
        out += [f"{lab}:", f"    sim.jump16 {reg} + {nib}*dw, " + ", ".join(targets)]
    return out, root


def _default_rt_unlink(t: int, leaf: int) -> List[str]:
    """package C's `rt_unlink` (section 4.3): unlink runtime thing `t` from leaf `leaf`'s list -- the interface
    proposed here (`rtu_t` / `rtu_leaf` w/4 wide, sim.leaf_unlink's index width); the integrator passes C's own"""
    return [f"    hex.set w/4, rtu_t, {t}", f"    hex.set w/4, rtu_leaf, {leaf}", "    stl.fcall rt_unlink, rtu_ret"]


def _default_drop_take(k: int) -> List[str]:
    """package C's `drop_take<k>` (barrelcode.drop_lines): mdrop[k] = 2, dr_live - 1, and drop k's row nt + 10 + k out
    of its leaf list and cleared -- the hook owns every drop cell (its `drop_link<k>` set them)"""
    return [f"    stl.fcall drop_take{k}, drt_ret"]


def pkxyz_values(w) -> List[int]:
    """`pkxyz`, by pickup index: the item's x | y << 16 | z << 32, each 16 bits two's complement (whole map units;
    z the model's `pickup_z`, the floor it stands on)"""
    out = []
    for t, z in zip(w.pickup_things, w.pickup_z):
        out.append((t.x & 0xFFFF) | (t.y & 0xFFFF) << 16 | (z & 0xFFFF) << 32)
    assert len(out) < 256
    return out


def pickup_table_fj(w) -> str:
    return generate_dispatch_table_fj("pkxyz", pkxyz_values(w), index_nibbles=2, result_nibbles=12)


def _box_leaf() -> List[str]:
    """`pk_box` (item `pk_i`: its x, y, z from `pkxyz`) / `pk_boxz` (the caller set `pk_tx` / `pk_ty` 16.16 and
    `pk_tz` map units): `pk_in` = the candidate's box overlaps (|t - c| < 36 << 16 on both axes, strict) and the
    reach holds (`-8 <= pk_tz - cm_hf <= 56`). Both return through `pk_bret`."""
    return ["pk_box:",
            "    pkxyz.lookup pk_r, pk_i",
            "    hex.zero 4, pk_tx", "    hex.mov 4, pk_tx + 4*dw, pk_r",
            "    hex.zero 4, pk_ty", "    hex.mov 4, pk_ty + 4*dw, pk_r + 4*dw",
            "    hex.zero 8, pk_tz", "    hex.mov 4, pk_tz, pk_r + 8*dw", "    hex.sign_extend 8, 4, pk_tz",
            "pk_boxz:",
            "    hex.zero 1, pk_in",
            "    hex.mov 8, pk_d, pk_tx", "    hex.sub 8, pk_d, cpx", "    hex.abs 8, pk_d",
            "    hex.scmp 8, pk_d, pk_bd, pkb_y, pkb_out, pkb_out",
            "  pkb_y:",
            "    hex.mov 8, pk_d, pk_ty", "    hex.sub 8, pk_d, cpy", "    hex.abs 8, pk_d",
            "    hex.scmp 8, pk_d, pk_bd, pkb_r, pkb_out, pkb_out",
            "  pkb_r:",                                                   # delta = item_z - z in [-8, 56]
            "    hex.mov 8, pk_d, pk_tz", "    hex.sub 8, pk_d, cm_hf",
            "    hex.scmp 8, pk_d, pk_cup, pkb_u, pkb_u, pkb_out",
            "  pkb_u:",
            "    hex.scmp 8, pk_d, pk_cdn, pkb_out, pkb_in, pkb_in",
            "  pkb_in:", "    hex.set 1, pk_in, 1",
            "  pkb_out:", "    stl.fret pk_bret"]


def _drop_leaf() -> List[str]:
    """`pk_drop` (stl.fcall pk_drop, pk_dret): the drop of runtime row `pk_t` (its monster's thpos_rt / thss_rt row):
    its 16.16 position, its leaf's floor now (`ms_seed_leaf`: mover-aware, the model's `_floor_at`), then `pk_boxz`
    (sim.thing_pos_read's row read)"""
    return ["pk_drop:",
            "    hex.zero w/4, pk_off", "    hex.mov 2, pk_off, pk_t", "    hex.shl_hex w/4, 1, pk_off",   # 16 a row
            "    hex.set w/4, pk_base, thpos_rt", "    hex.ptr_index pk_ptr, pk_base, pk_off",
            "    hex.read_hex 16, pk_pos, pk_ptr",
            "    hex.mov 8, pk_tx, pk_pos", "    hex.mov 8, pk_ty, pk_pos + 8*dw",
            "    hex.set w/4, pk_base, thss_rt", "    hex.ptr_index pk_ptr, pk_base, pk_off",
            "    hex.zero w/4, ptss", "    hex.read_hex 3, ptss, pk_ptr",
            "    stl.fcall ms_seed_leaf, ms_seed_ret",
            "    hex.mov 8, pk_tz, cp_seedf",
            "    stl.fcall pk_boxz, pk_bret",
            "    stl.fret pk_dret"]


def pickup_lines(w, slots: dict, mon_rt: Sequence[int], *, rt_unlink: Callable = _default_rt_unlink,
                 drop_take: Callable = _default_drop_take, lists=None) -> List[str]:
    """`pk_go` (stl.fcall pk_go, pk_ret): `combat._touch_specials` at the candidate (`cpx`, `cpy`) with the floor
    `cm_hf` (the module docstring). `slots`: `pickup_slots`; `mon_rt[m]`: monster slot m's runtime thing (its
    thpos_rt / thss_rt row). `lists` overrides the cell lists (the host control's mutated grid). Jumps over itself.
    SIZE: every test lives in ONE shared leaf (`pk_box` / `pk_boxz`, `pk_drop`, `pk_bonus`) and an item's stub only
    names its item (`pk_i`, the `pkxyz` row) -- one inline 16.16 compare is ~3K words, and 95 items x 6 of them
    were 2M (MEASURED)."""
    from doomfj.combat import DROP_ITEM
    _check_rules()
    lists = pickup_cell_lists(w) if lists is None else lists
    for i, t in enumerate(w.pickup_things):          # the item's z is static: no pickup in a door or a mover
        sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, t.x, t.y)]
        assert sec not in w.door_order and sec not in w.mover_order, (i, t.type, sec)
    assert all(-0x8000 <= v < 0x8000 for t, z in zip(w.pickup_things, w.pickup_z) for v in (t.x, t.y, z))
    stubs = {key: f"pk_c{k}" for k, key in enumerate(sorted(set(lists.values())))}
    tree, root = _tree("pk", "cpx", "cpy", {c: stubs[key] for c, key in lists.items()}, "pk_drops")
    out = ["// M7 P6 (doomfj.lootcode): the pickups at a tried candidate -- %d cells, %d lists"
           % (len(lists), len(stubs)), ";pk_end",
           "pk_go:",
           "    hex.if1 1, p_dead, pk_out",                            # "dead thing touching"
           f"    ;{root}"]
    out += tree
    for key, lab in stubs.items():
        out += [f"{lab}:"] + [f"    stl.fcall pk{i}, pk_iret" for i in key] + ["    ;pk_drops"]
    # ---- every item's stub ----
    for i, t in enumerate(w.pickup_things):
        p = f"pk{i}"
        vis = f"thvis + {slots['slot'][i]}*2*dw"
        out += [f"{p}:", f"    hex.if0 1, {vis}, {p}_n",
                f"    hex.set 2, pk_i, {i}", "    stl.fcall pk_box, pk_bret", f"    hex.if0 1, pk_in, {p}_n",
                f"    stl.fcall give_{t.type}, gv_ret", f"    hex.if0 1, gv_ok, {p}_n",
                "    stl.fcall pk_bonus, pk_nret",
                f"    hex.zero 2, {vis}"]
        if slots["rt"][i] is not None:
            out += rt_unlink(slots["rt"][i], slots["leaf"][i])
        out += [f"  {p}_n:", "    stl.fret pk_iret"]
    # ---- the drops, in slot order ----
    out += ["pk_drops:", "    hex.if0 2, dr_live, pk_out"]
    for k, m in enumerate(droppers(w)):
        p = f"pkd{k}"
        kind = DROP_ITEM[gd.DROPS[gd.MONSTER_DOOMEDNUMS[w.mon_things[m].type]]]
        out += [f"    hex.if_flags mdrop + {k}*dw, {1 << 1:#06x}, {p}_n, {p}_t", f"  {p}_t:",
                f"    hex.set 2, pk_t, {mon_rt[m]}", "    stl.fcall pk_drop, pk_dret", f"    hex.if0 1, pk_in, {p}_n",
                f"    stl.fcall {DROPPED[kind]}, gv_ret", f"    hex.if0 1, gv_ok, {p}_n",
                "    stl.fcall pk_bonus, pk_nret"]
        out += drop_take(k)                          # mdrop[k] = 2, dr_live - 1, the row unlinked (package C's)
        out += [f"  {p}_n:"]
    out += ["pk_out:", "    stl.fret pk_ret"]
    # ---- the shared leaves and the give routines ----
    out += _box_leaf() + _drop_leaf()
    out += ["pk_bonus:"] + _bonus_lines("pkb") + ["    stl.fret pk_nret"]
    for kind, dropped in give_kinds(w):
        out += give_lines(kind, dropped)
    for a in range(gd.NUMAMMO):
        out += give_ammo_lines(a)
    out += ["pk_end:"]
    return out


# ---- the blocking ------------------------------------------------------------------------------------------------
def pb_mon_lines(w, mon_rt: Sequence[int]) -> List[str]:
    """`pb_mon` (stl.fcall pb_mon, pb_ret -> `pb_hit`): `_solid_thing_at`'s monster half -- the first slot with
    `mon_solid` whose box overlaps the candidate's, |mon_x << 16 - cpx| < (r + 16) << 16 on both axes (strict,
    16.16). A slot copies its whole-unit position (thpos_rt's integer halves: a monster stands on whole units, its
    fraction 0) into `pb_tx` / `pb_ty` (whose fractions stay 0) and calls the shared test of its radius. Jumps over
    itself."""
    out = ["// M7 P6 (doomfj.lootcode): the player blocked by a solid monster", ";pb_end",
           "pb_mon:", "    hex.zero 1, pb_hit"]
    for m in range(w.layout.nmon):
        r = w.mon_radius[m]
        assert r in (20, 30), r
        n = f"pb{m}_n"
        t = mon_rt[m]
        out += [f"    hex.if0 1, mon_solid + {m}*dw, {n}",
                f"    hex.mov 4, pb_tx + 4*dw, thpos_rt + {16 * t + 4}*dw",
                f"    hex.mov 4, pb_ty + 4*dw, thpos_rt + {16 * t + 12}*dw",
                f"    stl.fcall pb_t{r}, pb_tret", "    hex.if1 1, pb_hit, pb_out",
                f"  {n}:"]
    out += ["  pb_out:", "    stl.fret pb_ret"]
    for r in (20, 30):
        out += [f"pb_t{r}:",
                "    hex.mov 8, pb_c, pb_tx", "    hex.sub 8, pb_c, cpx", "    hex.abs 8, pb_c",
                f"    hex.scmp 8, pb_c, pb_bd{r}, pbt{r}_y, pbt{r}_n, pbt{r}_n",
                f"  pbt{r}_y:",
                "    hex.mov 8, pb_c, pb_ty", "    hex.sub 8, pb_c, cpy", "    hex.abs 8, pb_c",
                f"    hex.scmp 8, pb_c, pb_bd{r}, pbt{r}_h, pbt{r}_n, pbt{r}_n",
                f"  pbt{r}_h:", "    hex.set 1, pb_hit, 1",
                f"  pbt{r}_n:", "    stl.fret pb_tret"]
    out += ["pb_end:"]
    return out


def block_lines(tag: str, nxt: str) -> List[str]:
    """`collision.move_with_collision_lines(block=)`: a solid monster refuses the candidate (on to `nxt`)"""
    return ["    stl.fcall pb_mon, pb_ret", f"    hex.if1 1, pb_hit, {nxt}"]


def pickup_call(tag: str) -> List[str]:
    """`collision.move_with_collision_lines(pickup=)`"""
    return ["    stl.fcall pk_go, pk_ret"]


# the static blockers' 16.16 test (collision_cells_fj(thing_test=)): the thing's box (ca_tx, ca_ty whole units,
# ca_tr its radius) against the candidate's -- |tx << 16 - cpx| < (tr << 16) + cprad on both axes, strict; a hit
# clears cp_ok. `sim.thing_test` compares the whole-unit parts, exact for a monster on whole units only.
THING_TEST16 = ["    hex.zero 4, pbt_a", "    hex.mov 4, pbt_a + 4*dw, ca_tx", "    hex.sub 8, pbt_a, cpx",
                "    hex.abs 8, pbt_a",
                "    hex.zero 4, pbt_b", "    hex.mov 4, pbt_b + 4*dw, ca_tr", "    hex.add 8, pbt_b, cprad",
                "    hex.scmp 8, pbt_a, pbt_b, ptt_y, ptt_n, ptt_n",
                "  ptt_y:",
                "    hex.zero 4, pbt_a", "    hex.mov 4, pbt_a + 4*dw, ca_ty", "    hex.sub 8, pbt_a, cpy",
                "    hex.abs 8, pbt_a",
                "    hex.scmp 8, pbt_a, pbt_b, ptt_hit, ptt_n, ptt_n",
                "  ptt_hit:", "    hex.zero 1, cp_ok",
                "  ptt_n:"]


def player_cell_things(w, lists: dict) -> tuple:
    """`(lists, things)` for the PLAYER's `collision.collision_cells_fj(lists, things=things,
    thing_test=THING_TEST16)`: the line lists (`cell_lists(rows, PLAYER_RADIUS)`) with every static blocker
    (`monstermove.static_blockers`: the barrels by `bar_solid`, the solid decorations by `mc_don`) entered -(k + 1)
    in the cells the player's box can meet it from. Asserts the player's start overlaps none (the invariant that
    keeps the cells' floor query at a position the player stands on a lines-only one, as the model's)."""
    from doomfj.collision import thing_cell_lists
    from doomfj.monstermove import static_blockers
    from doomfj.reference_model import PLAYER_RADIUS
    from doomfj.world import spawn_state
    things, _var = static_blockers(w)
    st = spawn_state(w.mw, w.mapname)
    for tx, ty, tr, _flag in things:
        bd = (tr << 16) + PLAYER_RADIUS
        assert not (abs((tx << 16) - st.x) < bd and abs((ty << 16) - st.y) < bd), (tx, ty)
    out = dict(lists)
    for c, ks in thing_cell_lists(things, PLAYER_RADIUS).items():
        out[c] = out.get(c, ()) + tuple(-k - 1 for k in ks)
    return out, things


# ---- nukage -------------------------------------------------------------------------------------------------------
def nukage_lines(w, cell_root: str) -> List[str]:
    """`nk_go` (stl.fcall nk_go, nk_ret): `combat._special_sector` at the tic-start position. `cell_root`: the player's
    collision cell routine (`collision_cells_fj`'s root). Jumps over itself."""
    from doomfj.combat import HURT_PERIOD_MASK
    from doomfj.reference_model import PLAYER_RADIUS
    assert HURT_PERIOD_MASK == 0x1F
    # the use lines run BEFORE this in fj and after it in the model: a floor switch fired this tic must not move a
    # floor this query can read -- no mover line within the box's reach of any damaging sector (E1M1: none)
    hurt = [s for s, v in enumerate(nkleaf_values(w)) if v]
    hsec = {w.leaf_sector[s] for s in hurt}
    assert not hsec & set(w.mover_order), hsec
    V = w.cmap.vertexes

    def box(secset):
        xs, ys = [], []
        for ld in w.lds:
            ss = {w.sds[ld.front].sector} | ({w.sds[ld.back].sector} if 0 <= ld.back < len(w.sds) else set())
            if ss & secset:
                xs += [V[ld.v1][0], V[ld.v2][0]]
                ys += [V[ld.v1][1], V[ld.v2][1]]
        return min(xs), max(xs), min(ys), max(ys)
    hb = box(hsec) if hsec else None      # a map with no damaging floor (the one-room fixtures): nothing to keep apart
    # issue #123 R5a: cp_floor and cp_seedf are SIGNED floor heights and `hex.cmp` compares unsigned -- exact here
    # because only EQUALITY is read ("Falling, not all the way down yet?": floorz != the sector's floor -> no damage),
    # and equality is sign-agnostic. Asserted: the compare's lt and gt arms are the same label, so no order is ever taken
    _nk_lt, _nk_eq, _nk_gt = "nk_out", "nk_hit", "nk_out"
    assert _nk_lt == _nk_gt != _nk_eq, "nukage's unsigned floor compare may read equality only (issue #123 R5a)"
    for mv in (w.mover_order if hb else ()):
        mb = box({mv})
        r = (PLAYER_RADIUS >> 16) + 1
        assert mb[1] < hb[0] - r or mb[0] > hb[1] + r or mb[3] < hb[2] - r or mb[2] > hb[3] + r, (mv, mb, hb)
    return ["// M7 P6 (doomfj.lootcode): nukage -- P_PlayerInSpecialSector's damaging floors", ";nk_end",
            "nk_go:",
            "    hex.if0 1, lvtime, nk_a", "    ;nk_out",
            "  nk_a:",
            "    hex.if_flags lvtime + dw, 0xAAAA, nk_b, nk_out",       # leveltime & 31 == 0
            "  nk_b:",
            "    hex.zero 10, ptx", "    hex.mov 4, ptx, viewx + 4*dw", "    hex.sign_extend 10, 4, ptx",
            "    hex.zero 10, pty", "    hex.mov 4, pty, viewy + 4*dw", "    hex.sign_extend 10, 4, pty",
            "    stl.fcall ptloc_walk, ptloc_ret",
            "    nkleaf.lookup nk_dmg, ptss",
            "    hex.if0 2, nk_dmg, nk_out",
            "    stl.fcall ms_seed_leaf, ms_seed_ret",                     # the sector's floor now (cp_seedf)
            "    hex.mov 8, cpx, viewx", "    hex.mov 8, cpy, viewy",
            "    hex.set 8, cprad, %d" % PLAYER_RADIUS,
            "    sim.check_cells %s" % cell_root,                          # the box's floorz (cp_floor)
            "    hex.cmp 8, cp_floor, cp_seedf, %s, %s, %s" % (_nk_lt, _nk_eq, _nk_gt),   # "Falling, not all the way
            # down yet?" -- equality only (see the assert above)
            "  nk_hit:",
            "    hex.mov 2, dp_dmg, nk_dmg",
            "    stl.fcall dp_go, dp_ret",
            "  nk_out:",
            "    stl.fret nk_ret",
            "nk_end:"]


# ---- the tic --------------------------------------------------------------------------------------------------------
def latch_lines() -> List[str]:
    """P7-a: the TIC-START death, read by every guard of the tic (at the world tic's start, after the restart)"""
    return ["hex.mov 1, p_dd0, p_dead"]


def pre_lines() -> List[str]:
    """before the weapon keys: nukage, alive only (the model's first line of the alive branch)"""
    return ["hex.if1 1, p_dd0, lt_pre_end", "stl.fcall nk_go, nk_ret", "lt_pre_end:"]


def post_lines(skip_move: str = "simmv_done") -> List[str]:
    """after the weapon tic and the damagecount fade (hurtcode's `tic`), before the move. Dead at the tic's start:
    `_death_think`'s use -> g_restart (use HELD: the key byte's use bit) and on past the move to `skip_move` (the
    label right after `wall_renderer._player_sim_lines`, turning included). Alive: the strength grows while it runs
    (saturating), the bonus count fades."""
    from doomfj.wireformat import KEY_USE_MASK
    return ["hex.if0 1, p_dd0, lt_alive",
            f"hex.if_flags pkeys + dw, {KEY_USE_MASK:#06x}, lt_dead_out, lt_rs",
            "lt_rs:", "hex.set 1, g_rs, 1",
            "lt_dead_out:", f";{skip_move}",
            "lt_alive:",
            "hex.if0 4, p_str, lt_str_end",
            "hex.inc 4, p_str",
            "hex.if0 4, p_str, lt_str_sat", ";lt_str_end",
            "lt_str_sat:", f"hex.set 4, p_str, {STRENGTH_CAP}",
            "lt_str_end:",
            "hex.if0 2, p_bc, lt_bc_end", "hex.dec 2, p_bc",
            "lt_bc_end:"]


def tic_lines(weapon_tic: Sequence[str], hurt_tic: Sequence[str], turn: bool = True) -> List[str]:
    """the player's tic between the use lines and the move, in the model's order (`_player_phase` / `_death_think`):
    `pre` (nukage, alive), the weapon tic (`weaponcode.weapon_lines(loot=True)`: its keys skipped on `p_dd0`, the
    psprites always), the damagecount fade -- hurtcode's `tic` alive; dead at the tic's start (`p_dd0`), `turn`:
    package D's `stl.fcall dt_turn, dt_tret` IN ITS PLACE (hurtcode.turn_lines: the turn to the killer, and the fade
    only once facing him or with no attacker) -- then `post` (the restart request and the jump past the move, or the
    strength and bonus tic)"""
    fade = list(hurt_tic)
    if turn:
        fade = (["hex.if0 1, p_dd0, lt_fade", "stl.fcall dt_turn, dt_tret", ";lt_fade_end", "lt_fade:"]
                + fade + ["lt_fade_end:"])
    return pre_lines() + list(weapon_tic) + fade + post_lines()


def use_guard() -> tuple:
    """(before, after) the use lines (wall_renderer.exit_lines with movercode's SR lifts and switch): a player dead
    at the tic's start uses nothing and leaves `pusedn` alone (`_death_think` never touches p_usedown)"""
    return ["hex.if1 1, p_dd0, lt_use_skip"], ["lt_use_skip:"]


# ---- the splice ------------------------------------------------------------------------------------------------------
def loot_parts(w, *, rm, map_wad, mapname: str, sprite_wad, mon_rt: Sequence[int], cell_root: str,
               rt_unlink: Callable = _default_rt_unlink, drop_take: Callable = _default_drop_take) -> dict:
    """everything package B adds to the game tier, for the World `w` (its level start; any skill):
      * `decls`: the persisted cells (p_bc, p_str, p_bp, am_misl, am_cell), p_dd0, the interfaces and scratch;
      * `tables`: amcap, nkleaf;
      * `leaves`: pk_go (the grid, the item stubs, the drops, the gives), pb_mon, nk_go -- each jumps over itself;
      * `latch`: the world tic's start, after the restart block, before the door tic (P7-a);
      * `pre`: right before the weapon tic (nukage, alive only);
      * `post`: after the weapon tic and hurtcode's `tic`, before `_player_sim_lines` (the death think or the
        strength / bonus tic; dead jumps to `simmv_done`);
      * `tic(weapon_tic, hurt_tic)`: `tic_lines` -- pre, the weapon, the fade or (dead) package D's `dt_turn`, post:
        what the emitter splices between the use lines and `_player_sim_lines`;
      * `use_guard`: (before, after) wrapped around `exit_lines(...)`;
      * `pickup` / `block`: `collision.move_with_collision_lines(pickup=, block=, skip_still=True)`;
      * `cells`: `player_cell_things` -- call it with the player's line lists, pass the result and THING_TEST16 to
        `collision_cells_fj(..., things=, thing_test=)`; its root is `cell_root` here;
      * `slots`: `pickup_slots`; `extra_vis[skill]`: the runtime pickups' extra thvis slots (appended after the vis
        slots in `thvis`, boot = hard's, and each skill's restart half);
      * `restart`: NEW GAME's / the restart's loot cell values; `persist`: the cells the M1 reset must leave alone.
    `mon_rt[m]`: monster slot m's runtime thing row (monsters.MonsterViews.rt)."""
    start = level_start(w)
    slots = pickup_slots(w, rm, map_wad, mapname, sprite_wad)
    leaves = (pickup_lines(w, slots, mon_rt, rt_unlink=rt_unlink, drop_take=drop_take)
              + pb_mon_lines(w, mon_rt) + nukage_lines(w, cell_root))
    return {"decls": loot_decls(start), "tables": tables_fj(w), "leaves": leaves,
            "latch": latch_lines(), "pre": pre_lines(), "post": post_lines(), "use_guard": use_guard(),
            "tic": tic_lines,
            "pickup": pickup_call, "block": block_lines, "cells": player_cell_things, "thing_test": THING_TEST16,
            "slots": slots,
            "extra_vis": {sk: extra_vis(w, slots, sk) for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)},
            "restart": restart_lines(start), "persist": PERSIST, "start": start}
