"""M7 P5 (docs/gp-p5-interface.md): the fj of the FIREBALL pool and the BLOOD pool -- the model's
`combat._spawn_fireball`, `_projectiles_phase`, `_missile_try`, `missile_lines_block`, `_explode`, `_spawn_fx_at_target`
(blood), `_spawn_fx` and `_fx_phase`, over `world.FIREBALL_POOL` and `world.FX_POOL` slots.

THE INTERFACE (the callers are agent B's monster attack and damagecode's dm_leaf; the coordinator places the phases):

    pj_spawn / pj_sret     stl.fcall pj_spawn, pj_sret -- args mm_x, mm_y (4 nibbles each, the shooter's INTEGER map
                           position: the move context's cells, which md_attack's slot code already sets)
    pj_phase / pj_pret     stl.fcall pj_phase, pj_pret -- once per tic, after the monster tic (the model: monsters,
                           then projectiles); skipped while `lvdone` (the frozen world)
    fx_spawn / fx_sret     stl.fcall fx_spawn, fx_sret -- args fxs_x, fxs_y (4 nibbles, the TARGET's integer
                           position), fxs_dmg (2): P_SpawnBlood 10 units in front of the target toward the player
    fx_phase / fx_pret     stl.fcall fx_phase, fx_pret -- once per tic, after pj_phase (the model: ... barrels, fx)
    dp_go / dp_ret         (agent B, hurtcode) called by a fireball that reaches the player, with dp_dmg (2 nibbles)

THE CELLS (slot-major, one field after another; `world.build_schema`'s proj_* / fx_* fields):

    pj_act  1 nibble x 8     proj_active            fx_act  1 x 2    fx_active
    pj_x    8 x 8  (16.16)   proj_x                 fx_x    8 x 2    fx_x  (16.16, the fraction always 0)
    pj_y    8 x 8            proj_y                 fx_y    8 x 2    fx_y
    pj_mx   8 x 8            proj_momx              fx_st   2 x 2    fx_state (gamedata.STATE_INDEX)
    pj_my   8 x 8            proj_momy              fx_ti   1 x 2    fx_tics
    pj_st   2 x 8            proj_state             rng_fx  2        the effects stream (rng.STREAM_FX's seed)
    pj_ti   1 x 8            proj_tics
Fireball slot s is runtime thing `nt + s`, blood slot s is `nt + FIREBALL_POOL + s`: their `thpos_rt` row holds the
WHOLE-UNIT position -- the 16.16 position with the fraction cleared (x in nibbles 0-7, y in 8-15, as
`things.thing_pos_value`; M7 P5 integration, `_copy_out`) -- and their `thss_rt` row the leaf (3
nibbles) -- the model's derived proj_leaf / fx_leaf; a free slot's rows are 0. The leaf lists hold them as runtime
things (`sim.leaf_link`), so a leaf's list is ascending: monsters, then fireballs, then blood (the model's mobiles).
`proj_src` is not held: only the model's event log reads it.

THE CODE (no per-slot logic -- P3.2b's first build overflowed the table pool with unrolled per-slot code): ONE window
(`pw_*`) both pools share; a slot's stub copies in, calls the shared leaf, copies out.
  * `pj_spawn`: the lowest free slot (8 unrolled tests; full -> fizzle, no draw), whose stub runs `pj_spawn_leaf`:
    the angle by proj.point_to_angle from (mm_x << 16, mm_y << 16) to (viewx, viewy) -- R_PointToAngle2 as the
    model's, NOT the rotation leaf's viewer-to-thing angle flipped (that differs by one BAM on the axes); the
    momentum from finesine at idx = angle >> 20 times 10 (`fireball_momentum_table` is FixedMul(10 << 16, ...),
    exactly 10 * finesine: tests/host/test_projcode.py), S_TBALL1 with tics 4 - (P_Random & 3) on rng_fx, the
    position x + (momx >> 1) (arithmetic), its leaf by ptloc_walk on the integer position, the link, then pj_try at
    the spawn position -- a failure explodes it.
  * `pj_try` (P_TryMove for a missile): the living player's box first (|px - nx| < 22 << 16 on both axes, strict:
    FIREBALL_R + PLAYER_R) -> the impact: one rng_fx draw (`fxrnd`: (v % 8 + 1) * 3), dp_go, refused; else the
    MISSILE CELLS -- sim.check_cells at radius 6 << 16 on the third cell set (tag "mc6", `missile_cells_fj`), cp_ok.
  * `pj_leaf` (per tic, a live slot): momentum -> nx = x + mx, pj_try; refused -> `pj_explode` (momentum 0,
    S_TBALLX1, tics 6 - (P_Random & 3)); accepted -> the position, ptloc, the relink when the leaf changed; then
    `pool_tic`: tics - 1, at 0 the next state from `pjst`, S_NULL -> unlink and the slot freed.
  * `fx_spawn`: the lowest free slot of 2 (full -> skipped, no draw); `fx_spawn_leaf`: the octant of (player -
    target) by the decide leaves' `mm_octant` (world.octant_of), the position target + FX_STEP[octant], S_BLOOD1 with
    8 - (P_Random & 3), then S_BLOOD2 (damage 9..12) or S_BLOOD3 (damage < 9) -- a P_SetMobjState that resets the
    tics just rolled -- the leaf, the link. `fx_phase`: `pool_tic` per live slot.
  * shared by both pools (`pool_tic_lines`): `pw_locate` (ptloc_walk), `pw_link` / `pw_unlink` (ONE expansion each of
    sim.leaf_link / leaf_unlink, ~45-50K words apiece) and `pool_tic`; a fireball slot's copy-out `pj_out<s>` serves
    its spawn stub and its phase stub.
What the emit-time asserts hold (`check_model_rules`): no `max(1, tics - roll)` clamp binds (every rolled state
lasts >= 4 tics), no pool state is forever or zero-tic, S_NULL is index 0, and the missile cells' rules
(`missile_rows`): a lift line never shuts a missile; a door's or the floor switch's line is shut exactly below a
pass state; no line touches two dynamic sectors.
"""
from typing import Dict, List, Tuple

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.lut_generator import generate_dispatch_table_fj

M32 = 0xFFFFFFFF


def _pool_sizes() -> Tuple[int, int]:
    from doomfj.world import FIREBALL_POOL, FX_POOL
    return FIREBALL_POOL, FX_POOL


def _info():
    from doomfj.combat import FIREBALL_INFO
    return FIREBALL_INFO


def _sidx(name: str) -> int:
    return gd.STATE_INDEX[name]


def _tics(name: str) -> int:
    return gd.STATES[name].tics


# ---- the state chains each pool walks -------------------------------------------------------------------------
def chain(start: str) -> List[str]:
    out, s = [], start
    while s != gd.S_NULL and s not in out:
        out.append(s)
        s = gd.STATES[s].next
    return out


def pool_states() -> List[str]:
    """every state a fireball or a blood splat can be in: the fireball's flight loop and death, the three blood
    states (combat._spawn_fx's S_BLOOD1 and the two it may jump to)"""
    info = _info()
    out = []
    for s in chain(info.spawnstate) + chain(info.deathstate) + chain("S_BLOOD1"):
        if s not in out:
            out.append(s)
    return out


def pjst_values() -> List[int]:
    """`pjst[state]`: P_SetMobjState's step in one lookup -- the next state's index (nibbles 0-1) and ITS tics
    (nibble 2); S_NULL reads 0 (the slot is freed)"""
    vals = [0] * (max(_sidx(s) for s in pool_states()) + 1)
    for s in pool_states():
        nxt = gd.STATES[s].next
        vals[_sidx(s)] = 0 if nxt == gd.S_NULL else _sidx(nxt) | (_tics(nxt) << 8)
    return vals


def fxrnd_row(v: int) -> int:
    """the effects stream's two call sites folded (combat.site_formulas, one source): nibbles 0-1 the fireball's
    impact damage ((v % 8 + 1) * damage), nibble 2 `v & 3` (every `tics -= P_Random() & 3`)"""
    from doomfj.combat import site_formulas
    f = site_formulas(lambda s: 0)
    k1, hit = f["fireball_hit"]
    k2, tics = f["tics_roll"]
    assert k1 == k2 == 1
    return hit(v) | (tics(v) << 8)


def fxrnd_values() -> List[int]:
    return R.outcome_table(fxrnd_row)


def momentum_values(rm) -> List[Tuple[int, int]]:
    """what the fj computes for fine angle i: (10 * finecos[i], 10 * finesine[i]) as signed 32-bit -- equal to
    `combat.fireball_momentum_table` (FixedMul(speed, ...) with speed = 10 << 16) on all TRIG_N entries
    (tests/host/test_projcode.py)"""
    def s32(v):
        v &= M32
        return v - (1 << 32) if v >> 31 else v
    sp = _info().speed >> 16
    assert _info().speed == sp << 16
    return [(s32(sp * s32(rm._finecos_idx(i))), s32(sp * s32(rm._finesin_idx(i)))) for i in range(rm.cfg.TRIG_N)]


def check_model_rules() -> None:
    from doomfj.combat import FX_STEP
    info = _info()
    assert _sidx(gd.S_NULL) == 0, "pool_tic reads the next state 0 as S_NULL"
    for s in pool_states():
        assert 0 < _tics(s) < 15 and _sidx(s) < 256, (s, _tics(s))
        assert gd.STATES[s].action is None, (s, gd.STATES[s].action)      # no action runs in a pool state
    for s in (info.spawnstate, info.deathstate, "S_BLOOD1"):               # max(1, tics - (P_Random() & 3))
        assert _tics(s) - 3 >= 1, (s, "the clamp would bind")
    assert info.speed >> 16 == 10 and info.speed & 0xFFFF == 0, "momentum = 10 * finesine: the x10 is shifts"
    assert all(abs(dx) < 16 and abs(dy) < 16 for dx, dy in FX_STEP)


# ---- the missile cells -----------------------------------------------------------------------------------------
def missile_rows(w) -> Tuple[list, Dict[int, tuple]]:
    """`(rows, doors)` for `collision.collision_cells_fj` -- `combat.missile_lines_block` as a cell set:
      * `line_rows` with ML_BLOCKING ignored (it does not stop missiles), the openings ZEROED (only cp_ok is read,
        and a zero constant is no xor);
      * a static two-sided line whose opening (min ceil - max floor) is under FIREBALL_H blocks always
        (FLAG_BLOCKING);
      * a line on a door or on the floor switch: shut exactly at the states below its pass state -- the first state
        whose opening (`monstersight.closed_states`' heights, the model's `heights_now`) is >= FIREBALL_H; `doors`
        maps it to ((door slot or the switch's cell, pass state),);
      * a lift's line never shuts a missile (asserted)."""
    from doomfj.collision import FLAG_BLOCKING, line_rows
    from doomfj.combat import FIREBALL_H
    from doomfj.monstersight import closed_states
    rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, 0)
    dyn = set(w.door_order) | set(w.lift_order) | set(w.switch)
    out, doors = [], {}
    for li, (row, ld) in enumerate(zip(rows, w.lds)):
        flags = row[9]
        if ld.back != -1:
            fs, bs = w.sds[ld.front].sector, w.sds[ld.back].sector
            sides = [s for s in (fs, bs) if s in dyn]
            assert len(sides) <= 1, "line %d touches two dynamic sectors" % li
            if not sides:
                if (min(w.secs[fs].ceil_h, w.secs[bs].ceil_h) - max(w.secs[fs].floor_h, w.secs[bs].floor_h)
                        < FIREBALL_H):
                    flags |= FLAG_BLOCKING
            else:
                s = sides[0]
                o = bs if s == fs else fs
                cell, n, hts = closed_states(w, s)
                shut = []
                for k in range(n):
                    f1, c1 = hts[k].get(s, (w.secs[s].floor_h, w.secs[s].ceil_h))
                    f2, c2 = hts[k].get(o, (w.secs[o].floor_h, w.secs[o].ceil_h))
                    shut.append(min(c1, c2) - max(f1, f2) < FIREBALL_H)
                if s in w.lift_order:
                    assert not any(shut), "lift line %d shuts a missile at a state: it needs a per-state block" % li
                elif any(shut):
                    p = shut.index(False) if False in shut else n
                    assert shut == [True] * p + [False] * (n - p), (li, shut, "not shut exactly below a pass state")
                    slot = w.door_order.index(s) if s in w.door_order else cell
                    doors[li] = ((slot, p),)
        out.append(tuple(row[:9]) + (flags, 0, 0))
    return out, doors


def missile_cell_lists(rows) -> dict:
    """the missile cells' lists: `collision.cell_lists`' exact interval rule at the fireball's radius (narrower than
    a cell, so without its corner assert: tests/host/test_projcode.py proves the coverage instead)"""
    from doomfj.collision import cell_lists
    from doomfj.combat import FIREBALL_R
    return cell_lists(rows, FIREBALL_R << 16, corner=False)


def missile_cells_fj(w, pfx: str = "e1m1", lists=None, doors=None) -> Tuple[str, str]:
    """`(fj text, root label)`: the third cell set, labels `{pfx}_mc6*`, entered by `sim.check_cells <root>` with
    cprad = FIREBALL_R << 16 (`pj_try`). `lists` / `doors` override the built ones (the harnesses' controls)."""
    from doomfj.collision import collision_cells_fj
    rows, dr = missile_rows(w)
    return collision_cells_fj(pfx, rows, missile_cell_lists(rows) if lists is None else lists,
                              doors=dr if doors is None else doors, tag="mc6")


# ---- the decls -------------------------------------------------------------------------------------------------
PJ_FIELDS = (("pj_act", 1), ("pj_x", 8), ("pj_y", 8), ("pj_mx", 8), ("pj_my", 8), ("pj_st", 2), ("pj_ti", 1),
             ("pj_src", 2))     # M7 P7: the shooter, 1 + its monster slot (0 free): the impact's attacker
FX_FIELDS = (("fx_act", 1), ("fx_x", 8), ("fx_y", 8), ("fx_st", 2), ("fx_ti", 1))
# the model's field each cell mirrors (agent A's gate state reads the same pairs)
MODEL_FIELD = {"pj_act": "proj_active", "pj_x": "proj_x", "pj_y": "proj_y", "pj_mx": "proj_momx",
               "pj_my": "proj_momy", "pj_st": "proj_state", "pj_ti": "proj_tics", "fx_act": "fx_active",
               "fx_x": "fx_x", "fx_y": "fx_y", "fx_st": "fx_state", "fx_ti": "fx_tics"}
# what persists across frames (the M1 reset must not restore it): the pools and the stream
PERSIST = tuple(f for f, _ in PJ_FIELDS + FX_FIELDS) + ("rng_fx",)
ARG_DECLS = ["fxs_x: hex.vec 4", "fxs_y: hex.vec 4", "fxs_dmg: hex.vec 2"]
WINDOW_DECLS = ["pw_act: hex.vec 1", "pw_x: hex.vec 8", "pw_y: hex.vec 8", "pw_mx: hex.vec 8", "pw_my: hex.vec 8",
                "pw_st: hex.vec 2", "pw_ti: hex.vec 1", "pw_t: hex.vec w/4", "pw_leaf: hex.vec w/4",
                "pw_nx: hex.vec 8", "pw_ny: hex.vec 8", "pw_ok: hex.vec 1", "pw_ang: hex.vec 8", "pw_idx: hex.vec 3",
                "pw_c: hex.vec 8", "pw_rr: hex.vec 3", "pw_src: hex.vec 2"]
RET_DECLS = ["pj_sret: hex.vec w/4", "pj_slret: hex.vec w/4", "pj_tret: hex.vec w/4", "pj_eret: hex.vec w/4",
             "pj_oret: hex.vec w/4", "pw_lkret: hex.vec w/4", "pw_ulret: hex.vec w/4", "pw_loret: hex.vec w/4",
             "pj_lret: hex.vec w/4", "pt_ret: hex.vec w/4", "pj_pret: hex.vec w/4", "fx_sret: hex.vec w/4",
             "fx_lret: hex.vec w/4", "fx_pret: hex.vec w/4"]


def pool_decls(pool: int = None, fxn: int = None, values: dict = None) -> List[str]:
    """the pools' cells (`values`: field -> per-slot ints, zero by default -- an empty pool at level start), rng_fx
    at its level-start seed, the arguments, the window, the return registers and the box constant"""
    P, Q = _pool_sizes()
    pool = P if pool is None else pool
    fxn = Q if fxn is None else fxn
    from doomfj.combat import FIREBALL_R, PLAYER_R
    out = []
    for fields, n in ((PJ_FIELDS, pool), (FX_FIELDS, fxn)):
        for name, nib in fields:
            vals = (values or {}).get(name, [0] * n)
            assert len(vals) == n, (name, vals)
            out.append("%s: hex.vec %d, %d" % (name, nib * n, sum((v & (16 ** nib - 1)) << (4 * nib * s)
                                                                  for s, v in enumerate(vals))))
    out.append("rng_fx: hex.vec 2, %d" % (values or {}).get("rng_fx", R.stream_seed(R.STREAM_FX)))
    out.append("pj_bd: hex.vec 8, %d" % ((FIREBALL_R + PLAYER_R) << 16))       # combat._missile_try's box
    return out + ARG_DECLS + WINDOW_DECLS + RET_DECLS


# ---- the code --------------------------------------------------------------------------------------------------
def _ptloc_window() -> List[str]:
    """ptss = the leaf under the window's integer position (world._leaf16: the 16.16 position floored) -- the body of
    the shared leaf `pw_locate` (pool_tic_lines)"""
    return ["    hex.zero 10, ptx", "    hex.mov 4, ptx, pw_x + 4*dw", "    hex.sign_extend 10, 4, ptx",
            "    hex.zero 10, pty", "    hex.mov 4, pty, pw_y + 4*dw", "    hex.sign_extend 10, 4, pty",
            "    stl.fcall ptloc_walk, ptloc_ret"]


def _times10(cell: str) -> List[str]:
    """cell[:8] *= 10 (mod 2^32): 2v + 8v"""
    return ["    hex.shl_bit 8, %s" % cell, "    hex.mov 8, pw_c, %s" % cell,
            "    hex.shl_bit 8, pw_c", "    hex.shl_bit 8, pw_c", "    hex.add 8, %s, pw_c" % cell]


def _half_step(pos: str, mom: str, tag: str) -> List[str]:
    """pos += mom >> 1, arithmetic (the model's Python shift of a signed momentum)"""
    return ["    hex.mov 8, pw_c, %s" % mom, "    hex.shr_bit 8, pw_c",
            "    hex.if_flags %s + 7*dw, 0xFF00, %s_p, %s_n" % (mom, tag, tag),
            "  %s_n:" % tag, "    hex.xor_by pw_c + 7*dw, 8",
            "  %s_p:" % tag, "    hex.add 8, %s, pw_c" % pos]


def _roll() -> List[str]:
    """one P_Random on the effects stream: pw_rr = fxrnd's row at the post-increment state"""
    return ["    hex.inc 2, rng_fx", "    fxrnd.lookup pw_rr, rng_fx"]


def _copy_out(prefix: str, s: int, t: int, fields) -> List[str]:
    """the window into slot s of pool `prefix` and into runtime thing t's thpos_rt / thss_rt rows. The row holds the
    WHOLE-UNIT position (docs/gp-p5-interface.md, THE MOBILE ROWS: the 16.16 position with its fraction CLEARED --
    the floor, as the model's `MonsterViews.rt_state` and the oracle's mobiles at `x >> 16`): the renderer projects a
    mobile from its row, so a row that kept pw_x's fraction would draw a different picture. M7 P5 integration: the
    fraction nibbles are written 0 and only the integer half (nibbles 4-7) is copied."""
    out = ["    hex.mov %d, %s + %d*dw, pw_%s" % (nib, name, nib * s, name[3:]) for name, nib in fields]
    return out + ["    hex.zero 4, thpos_rt + %d*dw" % (16 * t),
                  "    hex.mov 4, thpos_rt + %d*dw, pw_x + 4*dw" % (16 * t + 4),
                  "    hex.zero 4, thpos_rt + %d*dw" % (16 * t + 8),
                  "    hex.mov 4, thpos_rt + %d*dw, pw_y + 4*dw" % (16 * t + 12),
                  "    hex.mov 3, thss_rt + %d*dw, pw_leaf" % (16 * t)]


def pj_lines(*, nt: int, root: str, pool: int = None, exit_guard: bool = True) -> List[str]:
    """pj_spawn (+ its slot stubs), pj_spawn_leaf, pj_try, pj_explode, pj_leaf, pj_phase (+ its stubs); pool_tic is
    `pool_tic_lines`'.
    `nt`: the runtime things before the pools (fireball slot s is thing nt + s); `root`: the missile cells' entry
    (`missile_cells_fj`); `pool`: FIREBALL_POOL (the harness's control builds another)"""
    P, _Q = _pool_sizes()
    pool = P if pool is None else pool
    from doomfj.combat import FIREBALL_R
    info = _info()
    sp, dth = info.spawnstate, info.deathstate
    out = ["pj_spawn:"]
    out += ["    hex.if0 1, pj_act + %d*dw, pj_sp%d" % (s, s) for s in range(pool)]
    out += ["    stl.fret pj_sret"]                                       # full: the attack fizzles, no draw
    for s in range(pool):
        out += ["  pj_sp%d:" % s, "    hex.set w/4, pw_t, %d" % (nt + s), "    stl.fcall pj_spawn_leaf, pj_slret",
                "    stl.fcall pj_out%d, pj_oret" % s, "    stl.fret pj_sret"]
    for s in range(pool):                                                # the window into slot s (spawn and phase)
        out += ["pj_out%d:" % s] + _copy_out("pj", s, nt + s, PJ_FIELDS) + ["    stl.fret pj_oret"]
    out += ["pj_spawn_leaf:",
            # the shooter's position, 16.16, and R_PointToAngle2 from it to the player
            "    hex.zero 4, pw_x", "    hex.mov 4, pw_x + 4*dw, mm_x",
            "    hex.zero 4, pw_y", "    hex.mov 4, pw_y + 4*dw, mm_y",
            "    proj.point_to_angle pw_ang, pw_x, pw_y, viewx, viewy, 1",
            "    hex.mov 3, pw_idx, pw_ang + 5*dw",                          # the fine angle: angle >> 20
            "    finesine.read_cos pw_mx, pw_idx", *_times10("pw_mx"),
            "    finesine.read_sin pw_my, pw_idx", *_times10("pw_my"),
            "    hex.set 1, pw_act, 1",
            "    hex.mov 2, pw_src, md_src",                                 # M7 P7: the shooter (md_attack's)
            "    hex.set 2, pw_st, %d" % _sidx(sp), "    hex.set 1, pw_ti, %d" % _tics(sp),
            *_roll(), "    hex.sub 1, pw_ti, pw_rr + 2*dw",               # tics -= P_Random() & 3 (no clamp)
            *_half_step("pw_x", "pw_mx", "pj_hx"), *_half_step("pw_y", "pw_my", "pj_hy"),
            "    stl.fcall pw_locate, pw_loret",
            "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, ptss",
            "    stl.fcall pw_link, pw_lkret",
            "    hex.mov 8, pw_nx, pw_x", "    hex.mov 8, pw_ny, pw_y",
            "    stl.fcall pj_try, pj_tret",                                 # P_CheckMissileSpawn
            "    hex.if1 1, pw_ok, pj_sl_out",
            "    stl.fcall pj_explode, pj_eret",
            "  pj_sl_out:",
            "    stl.fret pj_slret",
            # ---- P_TryMove for a missile at (pw_nx, pw_ny): pw_ok ------------------------------------------------
            "pj_try:",
            "    hex.zero 1, pw_ok",
            "    hex.if1 1, p_dead, pj_tl",                                  # the player alive: not dead ...
            "    hex.sign 3, p_hp, pj_tl, pj_ta",                            # ... and health > 0
            "  pj_ta:",
            "    hex.if0 3, p_hp, pj_tl",
            "    hex.mov 8, pw_c, viewx", "    hex.sub 8, pw_c, pw_nx", "    hex.abs 8, pw_c",
            "    hex.scmp 8, pw_c, pj_bd, pj_tb, pj_tl, pj_tl",
            "  pj_tb:",
            "    hex.mov 8, pw_c, viewy", "    hex.sub 8, pw_c, pw_ny", "    hex.abs 8, pw_c",
            "    hex.scmp 8, pw_c, pj_bd, pj_hit, pj_tl, pj_tl",
            "  pj_hit:",                                                     # the impact: damage, refused
            *_roll(),
            "    hex.mov 2, dp_dmg, pw_rr",
            "    hex.mov 2, dp_src, pw_src",                                 # M7 P7: the attacker is the shooter
            "    stl.fcall dp_go, dp_ret",
            "    stl.fret pj_tret",
            "  pj_tl:",                                                      # the lines: the missile cells
            "    hex.mov 8, cpx, pw_nx", "    hex.mov 8, cpy, pw_ny",
            "    hex.set 8, cprad, %d" % (FIREBALL_R << 16),
            "    sim.check_cells %s" % root,
            "    hex.mov 1, pw_ok, cp_ok",
            "    stl.fret pj_tret",
            # ---- P_ExplodeMissile ----------------------------------------------------------------------------
            "pj_explode:",
            "    hex.zero 8, pw_mx", "    hex.zero 8, pw_my",
            "    hex.set 2, pw_st, %d" % _sidx(dth), "    hex.set 1, pw_ti, %d" % _tics(dth),
            "    hex.inc 2, rng_fx", "    fxrnd.lookup pw_rr, rng_fx", "    hex.sub 1, pw_ti, pw_rr + 2*dw",
            "    stl.fret pj_eret",
            # ---- P_MobjThinker for a live fireball -----------------------------------------------------------
            "pj_leaf:",
            "    hex.if1 8, pw_mx, pj_mv",
            "    hex.if0 8, pw_my, pj_lt",
            "  pj_mv:",
            "    hex.mov 8, pw_nx, pw_x", "    hex.add 8, pw_nx, pw_mx",
            "    hex.mov 8, pw_ny, pw_y", "    hex.add 8, pw_ny, pw_my",
            "    stl.fcall pj_try, pj_tret",
            "    hex.if1 1, pw_ok, pj_ok",
            "    stl.fcall pj_explode, pj_eret",
            "    ;pj_lt",
            "  pj_ok:",
            "    hex.mov 8, pw_x, pw_nx", "    hex.mov 8, pw_y, pw_ny",
            "    stl.fcall pw_locate, pw_loret",
            "    hex.cmp 3, ptss, pw_leaf, pj_rl, pj_lt, pj_rl",
            "  pj_rl:",                                                      # a new leaf: the relink
            "    stl.fcall pw_unlink, pw_ulret",
            "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, ptss",
            "    stl.fcall pw_link, pw_lkret",
            "  pj_lt:",
            "    stl.fcall pool_tic, pt_ret",
            "    stl.fret pj_lret",
            "pj_phase:"]
    if exit_guard:
        out.append("    hex.if1 1, lvdone, pj_ph_out")                      # a finished level: the world is frozen
    for s in range(pool):
        t = nt + s
        out += ["    hex.if0 1, pj_act + %d*dw, pj_ph%d_n" % (s, s),
                "    hex.set 1, pw_act, 1",
                *["    hex.mov %d, pw_%s, %s + %d*dw" % (nib, name[3:], name, nib * s) for name, nib in PJ_FIELDS[1:]],
                "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, thss_rt + %d*dw" % (16 * t),
                "    hex.set w/4, pw_t, %d" % t,
                "    stl.fcall pj_leaf, pj_lret",
                "    stl.fcall pj_out%d, pj_oret" % s,
                "  pj_ph%d_n:" % s]
    out += ["  pj_ph_out:", "    stl.fret pj_pret"]
    return out


def pool_tic_lines() -> List[str]:
    """the leaves both pools share: `pw_locate` (ptloc_walk on the window's integer position), `pw_link` /
    `pw_unlink` (the window's runtime thing into / out of the leaf pw_leaf), and `pool_tic` (stl.fcall pool_tic,
    pt_ret), the state tics on the window: tics - 1, at 0 the next state (`pjst`); S_NULL -> P_RemoveMobj:
    unlinked, the window zeroed (pw_act 0 tells the stub to free the slot)"""
    return ["pw_locate:", *_ptloc_window(), "    stl.fret pw_loret",
            # ONE expansion each of the relink macros (~50K words apiece: a copy per call site cost 0.25M words)
            "pw_link:", "    sim.leaf_link pw_t, pw_leaf", "    stl.fret pw_lkret",
            "pw_unlink:", "    sim.leaf_unlink pw_t, pw_leaf", "    stl.fret pw_ulret",
            "pool_tic:",
            "    hex.dec 1, pw_ti",
            "    hex.if1 1, pw_ti, pt_out",
            "    pjst.lookup pw_rr, pw_st",
            "    hex.if0 2, pw_rr, pt_free",
            "    hex.mov 2, pw_st, pw_rr", "    hex.mov 1, pw_ti, pw_rr + 2*dw",
            "    ;pt_out",
            "  pt_free:",                                                    # P_RemoveMobj
            "    stl.fcall pw_unlink, pw_ulret",
            "    hex.zero 1, pw_act", "    hex.zero 8, pw_x", "    hex.zero 8, pw_y", "    hex.zero 8, pw_mx",
            "    hex.zero 8, pw_my", "    hex.zero 2, pw_st", "    hex.zero w/4, pw_leaf",
            "    hex.zero 2, pw_src",                                        # M7 P7
            "  pt_out:",
            "    stl.fret pt_ret"]


def fx_lines(*, nt: int, fxn: int = None, exit_guard: bool = True) -> List[str]:
    """fx_spawn (+ its stubs), fx_spawn_leaf, fx_phase (+ its stubs); pool_tic is `pool_tic_lines`'. Blood slot s is
    thing nt + FIREBALL_POOL + s."""
    from doomfj.combat import FX_STEP
    P, Q = _pool_sizes()
    fxn = Q if fxn is None else fxn
    b1, b2, b3 = "S_BLOOD1", gd.STATES["S_BLOOD1"].next, gd.STATES[gd.STATES["S_BLOOD1"].next].next
    assert (b2, b3) == ("S_BLOOD2", "S_BLOOD3")
    out = ["fx_spawn:"]
    out += ["    hex.if0 1, fx_act + %d*dw, fx_sp%d" % (s, s) for s in range(fxn)]
    out += ["  fx_skip:", "    stl.fret fx_sret"]                        # full: skipped, no draw
    for s in range(fxn):
        t = nt + P + s
        out += ["  fx_sp%d:" % s, "    hex.set w/4, pw_t, %d" % t, "    stl.fcall fx_spawn_leaf, fx_lret"]
        out += _copy_out("fx", s, t, FX_FIELDS) + ["    stl.fret fx_sret"]
    dirs = [gd.DI_EAST, gd.DI_NORTHEAST, gd.DI_NORTH, gd.DI_NORTHWEST, gd.DI_WEST, gd.DI_SOUTHWEST, gd.DI_SOUTH,
            gd.DI_SOUTHEAST]
    assert sorted(dirs) == list(range(8))
    out += ["fx_spawn_leaf:",
            # the octant of (player - target), the integer offsets mm_octant reads (world.octant_of)
            "    hex.mov 4, mt_dx, viewx + 4*dw", "    hex.sub 4, mt_dx, fxs_x",
            "    hex.mov 4, mt_dy, viewy + 4*dw", "    hex.sub 4, mt_dy, fxs_y",
            "    hex.mov 4, mt_ax, mt_dx", "    hex.abs 4, mt_ax", "    hex.mov 4, mt_ay, mt_dy", "    hex.abs 4, mt_ay",
            "    stl.fcall mm_octant, mm_ocret",
            "    hex.zero 4, pw_x", "    hex.mov 4, pw_x + 4*dw, fxs_x",
            "    hex.zero 4, pw_y", "    hex.mov 4, pw_y + 4*dw, fxs_y",
            "    sim.jump16 mm_fa, " + ", ".join(["fx_o%d" % d for d in range(8)] + ["fx_on"] * 8)]
    for d in range(8):
        ox, oy = FX_STEP[d]
        out += ["  fx_o%d:" % d]
        out += ["    hex.add_constant 4, pw_x + 4*dw, %d" % (ox & 0xFFFF)] if ox else []
        out += ["    hex.add_constant 4, pw_y + 4*dw, %d" % (oy & 0xFFFF)] if oy else []
        out += ["    ;fx_on"]
    out += ["  fx_on:",
            "    hex.set 1, pw_act, 1",
            "    hex.set 2, pw_st, %d" % _sidx(b1), "    hex.set 1, pw_ti, %d" % _tics(b1),
            *_roll(), "    hex.sub 1, pw_ti, pw_rr + 2*dw",               # tics -= P_Random() & 3 (no clamp)
            # blood by damage: 9..12 -> S_BLOOD2, < 9 -> S_BLOOD3, each resetting the tics just rolled
            "    hex.set 2, pw_c, 9",
            "    hex.cmp 2, fxs_dmg, pw_c, fx_b3, fx_hi, fx_hi",
            "  fx_hi:",
            "    hex.set 2, pw_c, 12",
            "    hex.cmp 2, fxs_dmg, pw_c, fx_b2, fx_b2, fx_pos",
            "  fx_b2:",
            "    hex.set 2, pw_st, %d" % _sidx(b2), "    hex.set 1, pw_ti, %d" % _tics(b2), "    ;fx_pos",
            "  fx_b3:",
            "    hex.set 2, pw_st, %d" % _sidx(b3), "    hex.set 1, pw_ti, %d" % _tics(b3),
            "  fx_pos:",
            "    stl.fcall pw_locate, pw_loret",
            "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, ptss",
            "    stl.fcall pw_link, pw_lkret",
            "    stl.fret fx_lret",
            "fx_phase:"]
    if exit_guard:
        out.append("    hex.if1 1, lvdone, fx_ph_out")
    for s in range(fxn):
        t = nt + P + s
        out += ["    hex.if0 1, fx_act + %d*dw, fx_ph%d_n" % (s, s),
                "    hex.set 1, pw_act, 1",
                "    hex.mov 2, pw_st, fx_st + %d*dw" % (2 * s), "    hex.mov 1, pw_ti, fx_ti + %d*dw" % s,
                "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, thss_rt + %d*dw" % (16 * t),
                "    hex.set w/4, pw_t, %d" % t,
                "    stl.fcall pool_tic, pt_ret",
                "    hex.mov 2, fx_st + %d*dw, pw_st" % (2 * s), "    hex.mov 1, fx_ti + %d*dw, pw_ti" % s,
                "    hex.if1 1, pw_act, fx_ph%d_n" % s,
                "    hex.zero 1, fx_act + %d*dw" % s, "    hex.zero 8, fx_x + %d*dw" % (8 * s),
                "    hex.zero 8, fx_y + %d*dw" % (8 * s),
                "    hex.zero 16, thpos_rt + %d*dw" % (16 * t), "    hex.zero 3, thss_rt + %d*dw" % (16 * t),
                "  fx_ph%d_n:" % s]
    out += ["  fx_ph_out:", "    stl.fret fx_pret"]
    return out


def tables_fj() -> List[str]:
    return [generate_dispatch_table_fj("fxrnd", fxrnd_values(), index_nibbles=2, result_nibbles=3),
            generate_dispatch_table_fj("pjst", pjst_values(), index_nibbles=2, result_nibbles=3)]


def restart_lines(pool: int = None, fxn: int = None, *, nt: int) -> List[str]:
    """NEW GAME: empty pools, their runtime things' rows zero, rng_fx at its seed (the leaf lists are the
    coordinator's: a level start links no pool thing)"""
    P, Q = _pool_sizes()
    pool = P if pool is None else pool
    fxn = Q if fxn is None else fxn
    out = ["    hex.zero %d, %s" % (nib * n, name) for fields, n in ((PJ_FIELDS, pool), (FX_FIELDS, fxn))
           for name, nib in fields]
    out += ["    hex.zero %d, thpos_rt + %d*dw" % (16 * (pool + fxn), 16 * nt),
            "    hex.zero %d, thss_rt + %d*dw" % (16 * (pool + fxn), 16 * nt),
            "    hex.set 2, rng_fx, %d" % R.stream_seed(R.STREAM_FX)]
    return out


def proj_parts(w, *, nt: int, pfx: str = "e1m1", exit_guard: bool = True) -> dict:
    """everything P5's pools add, for the World `w`:
      * `decls`: pool_decls() (an empty pool, rng_fx at its seed);
      * `lines`: pj_* / pool_tic / fx_* -- leaves (each ends in a fret), placed where nothing falls in;
      * `cells`: the missile cell set's fj text (it jumps over itself) and `root`;
      * `tables`: fxrnd, pjst;
      * `restart`: NEW GAME's lines; `persist`: the labels that persist across frames.
    The callers' cells this text READS: mm_x / mm_y, viewx / viewy, p_hp / p_dead (hurtcode), lvdone, the collision
    state (cpx, cpy, cprad, cp_ok, ...), ptx / pty / ptss / ptloc_walk, the leaf lists (sshead, thnext, ll_*),
    thpos_rt / thss_rt (rows nt .. nt + 9), mt_dx / mt_dy / mt_ax / mt_ay and mm_octant / mm_fa (the decide
    leaves), finesine, the point_to_angle tables; and it CALLS dp_go (hurtcode)."""
    check_model_rules()
    cells, root = missile_cells_fj(w, pfx)
    return {"decls": pool_decls(), "lines": pj_lines(nt=nt, root=root, exit_guard=exit_guard) + pool_tic_lines()
            + fx_lines(nt=nt, exit_guard=exit_guard), "cells": cells, "root": root, "tables": tables_fj(),
            "restart": restart_lines(nt=nt), "persist": PERSIST}
