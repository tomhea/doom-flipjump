"""M8 L4 -- THE TELEPORTERS in fj (line special 97, WR teleport): the model's `combat._teleport_player`,
`world._teleport_monster` and the player's reactiontime, on the rules of `doomfj.teleport` (one definition: the
destinations, the front side, the stomp, every constant). E1M1 has no teleport line, so nothing here is emitted there.

THE PIECES (each spliced by the emitter where the model runs the rule):
  * `reaction_lines()` -- right before `wall_renderer._player_sim_lines` (alive only: the dead player's tic jumps past
    it to `simmv_done`, `lootcode.post_lines`): p_rct != 0 -> p_rct -= 1 and on to `simmv_done` (no turn, no walk:
    P_PlayerThink's `if (reactiontime) reactiontime--; else P_MovePlayer`); combat._player_move's first lines.
  * `player_lines(tels, prefix=)` -- LAST in the walk's `after_accept` (collision.move_with_collision_lines: the move
    (cm_ox, cm_oy) -> (viewx, viewy)), after the walk-over doors and the WR lifts; `knock_ctx=True` is the knock
    move's copy (knockcode.ptry_lines' after_accept), which also restarts the knock loop from the destination
    (kb_px / kb_py) with its momentum stopped (kb_vx / kb_vy 0: combat._xy_move).
  * `monster_lines(tels, prefix=, knock_ctx=)` -- the monsters' accepted move, after their WR lifts and before the
    position is taken: monstermove.move_leaf_lines (P_Move: mm_ox16 / mm_oy16 -> cpx / cpy) and knockcode.mtry_lines
    (a knock step); a fire overwrites the candidate's mm_nx / mm_ny, its floor cp_floor and its leaf ptss -- the
    lines after take the destination as the move (the position, floorz, the relink, the sector) -- and leaves the
    facing in `tp_fa` with `tp_hit` 1 for the slot's write-back.
  * `slot_back_lines(m, ...)` -- per slot, after its move (monstercode.p32b_move_lines) or its knock move (the stub
    kbs<m>): tp_hit -> the facing, and on the walk the knock momentum and the position's fraction 0, tp_hit 0.
  * `stomp_leaf_lines(slots)` -- `tp_stomp` (stl.fcall tp_stomp, tp_sret): PIT_StompThing at (tp_dx, tp_dy) for
    radius tp_r over every SHOOTABLE monster's box (mon_shootable: active, alive) in slot order and, with tp_pl 1 (a
    MONSTER teleporting), the living player's: a monster's teleport is REFUSED by the first (tp_blk 1); the PLAYER's
    (tp_pl 0) TELEFRAGS each (`tp_frag`: damagecode's dm_go in its TELEFRAG mode, kb_tf 1 for the thrust) and is never
    refused -- combat._teleport_player's `stomp_victims` loop. The mover's own slot is not skipped:
    teleport.check_one_per_move proves it is never near a destination. The barrels: none can be (asserted at emit
    time, `check_barrels`).
  * `decls()`, `level_start_lines()` (the restart block's), PERSIST, `map_persist`: the persisted `p_rct` (0 at the
    level start and the restart) and the scratch.
  * M8 THE TELEPORT FOG (`_fog_lines`, in every fire branch after its stomp -- a teleport that happened): projcode's
    `tf_spawn` twice, at the mover's whole-unit position after its move (the regs' new x / y, nibbles 4-7) and at the
    destination's fog (Teleporter.fog) -- combat._teleport_fogs. In a monster's branch before ptss is set: the
    spawn's point location writes ptss.

The fire of one teleporter is ONE move's: the tests run in line order and the first front crossing decides -- a
refused (stomped) monster teleport ends the tests too (the model's `break`).

THE REGISTERS a telefrag's dm_go touches inside the move it runs in: dm_leaf's window (dm_*), the thrust's (kb_tx ..
kb_rr, kb_vx / kb_vy -- the victim's momentum through kbt<m> / kb_gm), drop_link's (dr_*, pw_t / pw_leaf), st_kill.
In the walk's after_accept none is live; in the knock move's (kb_ptry) kb_vx / kb_vy are, and the fire zeroes them
after the stomp (the teleport stops the momentum), kb_px / kb_py set from the destination; kb_xm / kb_ym (the move
left), kb_who, kb_dead and kb_ht are not touched.
"""
from __future__ import annotations

from typing import List, Sequence

from doomfj.teleport import REACTION_TICS, check_one_per_move

M32 = 0xFFFFFFFF
REACTION_NIBBLES = 2                    # p_rct: 0..18
PERSIST = ("p_rct",)


def decls() -> List[str]:
    """the persisted `p_rct` (0 at boot: the level start) and the scratch"""
    return [f"p_rct: hex.vec {REACTION_NIBBLES}, 0",
            "tp_c: hex.vec 8", "tp_dx: hex.vec 4", "tp_dy: hex.vec 4", "tp_r: hex.vec 2", "tp_pl: hex.vec 1",
            "tp_blk: hex.vec 1", "tp_hit: hex.vec 1", "tp_fa: hex.vec 1", "tp_a: hex.vec 4", "tp_b20: hex.vec 4",
            "tp_b30: hex.vec 4", "tp_e: hex.vec 8", "tp_g: hex.vec 8", "tp_bp: hex.vec 8", "tp_sret: hex.vec w/4",
            "tp_fret: hex.vec w/4", "kb_tf: hex.vec 1"]          # M8: the telefrag's return, its thrust flag


def map_persist(map_wad, mapname: str) -> tuple:
    """the map-dependent persisted names (build._map_persist, the game tier's): `p_rct` on a map with a WR teleport --
    the reset leaves it to NEW GAME / the restart, like mc_don -- nothing on E1M1 (its image stays byte-identical)"""
    from doomfj.teleport import teleporters
    return PERSIST if teleporters(map_wad, mapname) else ()


def level_start_lines() -> List[str]:
    """NEW GAME / the restart: no reactiontime (the level start's, every skill)"""
    return [f"    hex.zero {REACTION_NIBBLES}, p_rct"]


def reaction_lines(skip: str = "simmv_done") -> List[str]:
    """P_PlayerThink's reactiontime: counting -> one less, and no P_MovePlayer (on to `skip`, past the turn and the
    walk)"""
    return [f"hex.if0 {REACTION_NIBBLES}, p_rct, tp_rgo",
            f"hex.dec {REACTION_NIBBLES}, p_rct",
            f";{skip}",
            "tp_rgo:"]


def _scmp(reg: str, val: int, lt: str, eq: str, gt: str) -> List[str]:
    return [f"    hex.set 8, tp_c, {val & M32:#x}", f"    hex.scmp 8, {reg}, tp_c, {lt}, {eq}, {gt}"]


def cross_front_lines(p: str, tel, radius: int, regs: Sequence[str], fire: str) -> List[str]:
    """`teleport.crossed_front` in fj on the move regs = (old x, old y, new x, new y), 16.16: the old centre on the
    FRONT side (`c <= coord` when front_le, else `c > coord`), the new one on the other, the new centre strictly
    inside the extent inflated by `radius` -> on to `fire`; else on to `<p>_no` (the next test)"""
    ox, oy, nx, ny = regs
    a_old, a_new, o_new = (oy, ny, nx) if tel.axis == "y" else (ox, nx, ny)
    L = tel.coord << 16
    no, x = f"{p}_no", f"{p}_x"
    if tel.front_le:                    # old <= L, new > L
        out = _scmp(a_old, L, f"{p}_o", f"{p}_o", no) + [f"  {p}_o:"] + _scmp(a_new, L, no, no, x)
    else:                               # old > L, new <= L
        out = _scmp(a_old, L, no, no, f"{p}_o") + [f"  {p}_o:"] + _scmp(a_new, L, x, x, no)
    out += [f"  {x}:"]
    out += _scmp(o_new, (tel.lo - radius) << 16, no, no, f"{p}_x1")
    out += [f"  {p}_x1:"]
    out += _scmp(o_new, (tel.hi + radius) << 16, fire, no, no)
    out += [f"  {no}:"]
    return out


def _stomp_call(tel, radius_lines: List[str], player: int, end: str) -> List[str]:
    """the stomp at `tel`'s destination: a monster's (`player` 1: the living player tested too) refused on a hit; the
    player's (0) telefrags and goes on"""
    dx, dy = tel.dest
    return [f"    hex.set 4, tp_dx, {dx & 0xFFFF:#x}", f"    hex.set 4, tp_dy, {dy & 0xFFFF:#x}",
            *radius_lines, f"    hex.set 1, tp_pl, {player}",
            "    stl.fcall tp_stomp, tp_sret",
            *([f"    hex.if1 1, tp_blk, {end}"] if player else [])]


def _fog_lines(x_cell: str, y_cell: str, tel) -> List[str]:
    """M8: EV_Teleport's two fogs -- at (x_cell, y_cell) (4-nibble whole units), then at tel.fog"""
    from doomfj.projcode import FX_KINDS
    fx, fy = tel.fog
    return [f"    hex.mov 4, fxs_x, {x_cell}", f"    hex.mov 4, fxs_y, {y_cell}",
            f"    hex.set 1, fxs_kind, {FX_KINDS['fog']}",
            "    stl.fcall tf_spawn, fx_sret",
            f"    hex.set 4, fxs_x, {fx & 0xFFFF:#x}", f"    hex.set 4, fxs_y, {fy & 0xFFFF:#x}",
            "    stl.fcall tf_spawn, fx_sret"]


def player_lines(tels, *, prefix: str, knock_cells: bool, knock_ctx: bool = False,
                 regs=("cm_ox", "cm_oy", "viewx", "viewy")) -> List[str]:
    """combat._teleport_player after an accepted move (regs, 16.16): the first teleporter crossed from its front --
    TELEFRAGGING every shootable monster at its destination (tp_stomp with tp_pl 0: the player himself untested) --
    puts the player there: viewx / viewy, viewangle, p_rct = 18, and (`knock_cells`: knockback is on) his knock
    momentum 0. `knock_ctx`: the knock move's copy -- the loop's position (kb_px, kb_py) is the destination and its
    momentum (kb_vx, kb_vy) 0 (after the stomp: a telefrag's thrust runs through kb_vx / kb_vy)"""
    from doomfj.combat import PLAYER_R
    check_one_per_move(tels)
    end = f"{prefix}_end"
    out = [f"  // M8 L4: the WR teleports (doomfj.teleport, combat._teleport_player) -- {prefix}"]
    for k, tel in enumerate(tels):
        out += cross_front_lines(f"{prefix}{k}", tel, PLAYER_R, regs, f"{prefix}_f{k}")
    out += [f"    ;{end}"]
    for k, tel in enumerate(tels):
        X, Y = (tel.dest[0] << 16) & M32, (tel.dest[1] << 16) & M32
        out += [f"  {prefix}_f{k}:",
                *_stomp_call(tel, [f"    hex.set 2, tp_r, {PLAYER_R}"], 0, end),
                *_fog_lines(f"{regs[2]} + 4*dw", f"{regs[3]} + 4*dw", tel),       # M8: the fogs
                f"    hex.set 8, viewx, {X:#x}", f"    hex.set 8, viewy, {Y:#x}",
                f"    hex.set 8, viewangle, {tel.angle & M32:#x}",
                f"    hex.set {REACTION_NIBBLES}, p_rct, {REACTION_TICS}",
                *(["    hex.zero 8, p_kmx", "    hex.zero 8, p_kmy"] if knock_cells else []),
                *([f"    hex.set 8, kb_px, {X:#x}", f"    hex.set 8, kb_py, {Y:#x}",
                   "    hex.zero 8, kb_vx", "    hex.zero 8, kb_vy"] if knock_ctx else []),
                f"    ;{end}"]
    out += [f"  {end}:"]
    return out


def monster_lines(tels, *, prefix: str, knock_ctx: bool = False,
                  regs=("mm_ox16", "mm_oy16", "cpx", "cpy")) -> List[str]:
    """world._teleport_monster after a monster's accepted move (regs: the old whole units << 16, the candidate, 16.16;
    the radius by mm_r30): the first teleporter crossed from its front -- unless a shootable thing (another monster,
    the living player) stands at its destination -- makes the destination the move: mm_nx / mm_ny, cp_floor (its
    sector's floor), ptss (its leaf), and tp_fa / tp_hit for the slot's write-back. `knock_ctx` (knockcode.mtry_lines):
    the candidate kb_cx / kb_cy is the destination (kq_mfr copies it, fraction 0) and the momentum kb_vx / kb_vy 0"""
    check_one_per_move(tels)
    end = f"{prefix}_end"
    out = [f"  // M8 L4: the WR teleports, a monster's move (doomfj.teleport, world._teleport_monster) -- {prefix}",
           f"    hex.if1 1, mm_r30, {prefix}_r30"]
    for rad in (20, 30):
        if rad == 30:
            out += [f"  {prefix}_r30:"]
        for k, tel in enumerate(tels):
            out += cross_front_lines(f"{prefix}{rad}_{k}", tel, rad, regs, f"{prefix}_f{k}")
        out += [f"    ;{end}"]
    for k, tel in enumerate(tels):
        dx, dy = tel.dest
        assert 0 <= tel.dest_leaf < 16 ** 3, tel.dest_leaf
        out += [f"  {prefix}_f{k}:",
                *_stomp_call(tel, ["    hex.zero 2, tp_r", "    hex.mov 2, tp_r, mm_r"], 1, end),
                *_fog_lines(f"{regs[2]} + 4*dw", f"{regs[3]} + 4*dw", tel),       # M8: the fogs (before ptss)
                f"    hex.set 4, mm_nx, {dx & 0xFFFF:#x}", f"    hex.set 4, mm_ny, {dy & 0xFFFF:#x}",
                f"    hex.set 8, cp_floor, {tel.dest_floor & M32:#x}",
                "    hex.zero w/4, ptss", f"    hex.set 3, ptss, {tel.dest_leaf:#x}",
                f"    hex.set 1, tp_fa, {tel.facing}", "    hex.set 1, tp_hit, 1",
                *([f"    hex.set 8, kb_cx, {(dx << 16) & M32:#x}", f"    hex.set 8, kb_cy, {(dy << 16) & M32:#x}",
                   "    hex.zero 8, kb_vx", "    hex.zero 8, kb_vy"] if knock_ctx else []),
                f"    ;{end}"]
    out += [f"  {end}:"]
    return out


def slot_back_lines(m: int, *, facing: str, knock: bool, walk: bool, tag: str) -> List[str]:
    """slot m's write-back after its move (`walk`: monstercode.p32b_move_lines) or its knock move (the stub kbs<m>,
    which writes its momentum and fraction back itself): a teleport (tp_hit) -> the facing cell `facing` = tp_fa and,
    on the walk with knockback on, mkx / mky / mfx / mfy 0 (world._teleport_monster); tp_hit 0"""
    skip = f"{tag}{m}_n"
    return [f"    hex.if0 1, tp_hit, {skip}",
            "    hex.zero 1, tp_hit",
            f"    hex.mov 1, {facing}, tp_fa",
            *([f"    hex.zero 8, mkx + {8 * m}*dw", f"    hex.zero 8, mky + {8 * m}*dw",
               f"    hex.zero 4, mfx + {4 * m}*dw", f"    hex.zero 4, mfy + {4 * m}*dw"] if (knock and walk) else []),
            f"  {skip}:"]


def stomp_leaf_lines(slots: Sequence[tuple], *, hurt: bool = True, knock: bool = True, sn: int = 2) -> List[str]:
    """`tp_stomp`, jumping over itself: PIT_StompThing at the destination (tp_dx, tp_dy) for radius tp_r over each
    shootable monster's box (`slots`: [(runtime thing, radius)] per slot -- slot j is dm_go's id j + 1;
    mon_shootable) -- |thing - dest| < r + r', strict, whole units -- and, with tp_pl 1, the living player's (`hurt`:
    p_dead is not shootable), 16.16. tp_pl 1 (a monster teleporting): the first hit sets tp_blk 1 and returns. tp_pl 0
    (the player): each hit is a TELEFRAG -- `tp_frag` (dm_go, dm_melee TELEFRAG; `knock`: kb_tf 1 around it) -- and
    the loop goes on; tp_blk stays 0. M8 C2: `sn` (world.slot_nibbles) -- dm_id's width"""
    from doomfj.damagecode import TELEFRAG
    from doomfj.combat import PLAYER_R
    from doomfj.monstermove import _add_const
    out = [";tp_stomp_end", "tp_stomp:",
           "    hex.zero 1, tp_blk",
           "    hex.zero 4, tp_b20", "    hex.mov 2, tp_b20, tp_r", "    hex.mov 4, tp_b30, tp_b20",
           *_add_const(4, "tp_b20", 20), *_add_const(4, "tp_b30", 30)]
    for j, (t, rad) in enumerate(slots):
        assert rad in (20, 30), rad
        bd, nj = f"tp_b{rad}", f"tp_s{j}_n"
        out += [f"    hex.if0 1, mon_shootable + {j}*dw, {nj}",
                f"    hex.mov 4, tp_a, thpos_rt + {16 * t + 4}*dw",
                "    hex.sub 4, tp_a, tp_dx", "    hex.abs 4, tp_a",
                f"    hex.scmp 4, tp_a, {bd}, tp_s{j}_y, {nj}, {nj}",
                f"  tp_s{j}_y:",
                f"    hex.mov 4, tp_a, thpos_rt + {16 * t + 12}*dw",
                "    hex.sub 4, tp_a, tp_dy", "    hex.abs 4, tp_a",
                f"    hex.scmp 4, tp_a, {bd}, tp_s{j}_h, {nj}, {nj}",
                f"  tp_s{j}_h:",                                             # a hit: refused, or a telefrag
                "    hex.if1 1, tp_pl, tp_stk",
                f"    hex.set {sn}, dm_id, {j + 1}",
                "    stl.fcall tp_frag, tp_fret",
                f"  {nj}:"]
    out += ["    hex.if0 1, tp_pl, tp_out"]
    out += (["    hex.if1 1, p_dead, tp_out"] if hurt else [])
    out += ["    hex.zero 8, tp_bp", "    hex.mov 2, tp_bp + 4*dw, tp_r", *_add_const(4, "tp_bp + 4*dw", PLAYER_R)]
    for ax, reg, d in (("x", "viewx", "tp_dx"), ("y", "viewy", "tp_dy")):
        out += ["    hex.zero 4, tp_e", f"    hex.mov 4, tp_e + 4*dw, {d}",
                f"    hex.mov 8, tp_g, {reg}", "    hex.sub 8, tp_g, tp_e", "    hex.abs 8, tp_g",
                f"    hex.scmp 8, tp_g, tp_bp, tp_pl{ax}, tp_out, tp_out", f"  tp_pl{ax}:"]
    out += ["  tp_stk:", "    hex.set 1, tp_blk, 1",
            "  tp_out:", "    stl.fret tp_sret",
            # M8: the telefrag of slot dm_id - 1 -- P_DamageMobj(thing, player, player, 10000)
            "tp_frag:",
            f"    hex.set 1, dm_melee, {TELEFRAG}",
            *(["    hex.set 1, kb_tf, 1"] if knock else []),
            "    stl.fcall dm_go, dm_ret",
            *(["    hex.zero 1, kb_tf"] if knock else []),
            "    stl.fret tp_fret",
            "tp_stomp_end:"]
    return out


def check_barrels(w) -> None:
    """the fj's stomp tests no barrel: none stands within a blockdist (barrel radius + 30) of a destination"""
    from doomfj.combat import BARREL_R
    from doomfj.teleport import REACH_MAX
    for tel in w.teleports:
        for t in w.barrel_things:
            bd = BARREL_R + REACH_MAX
            assert not (abs(t.x - tel.dest[0]) < bd and abs(t.y - tel.dest[1]) < bd), (
                "M8 L4: a barrel at the teleport destination %r: tp_stomp tests none" % (tel.dest,))
