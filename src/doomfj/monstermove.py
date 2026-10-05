"""M7 P3.2b "chase" (docs/gp-monsters.md 8.4): the fj a monster's move needs besides its collision cells
(`collision.monster_cells_fj`) -- each piece a generator the emitter calls and a tests/fj harness runs alone.

Piece 2, THE SEED: P_CheckPosition starts its opening from the sector under the candidate position -- the model's
`secs_c[leaf_sector[leaf]]` (every door at its OPEN height, each mover at its present state). The fj finds the leaf
with the baked point location every thing already uses (`ptloc_walk`, on the integer position in ptx / pty) and
jumps on it (`ptss`, three nibbles) to that leaf's stub, which sets `cp_seedf` / `cp_seedc` -- or, in a mover's
leaf, jumps on the mover's state cell to that state's heights. The leaf itself stays in `ptss` for the relink.
"""
from doomfj.mapcompiler import seg_sector

M32 = 0xFFFFFFFF


def leaf_sector_index(cmap, lds, sds, s: int) -> int:
    """the sector subsector `s` lies in -- its first seg's (the model's `leaf_sector`, the emitter's `_leaf_mover`)"""
    seg = cmap.segs[cmap.subsectors[s].firstseg]
    ld = lds[seg.linedef]
    return sds[ld.front if seg.side == 0 else ld.back].sector


def monster_seed_fj(cmap, lds, sds, secs_open, msecs: dict, mcell: dict, *, label: str = "ms_seed") -> list:
    """`<label>_leaf`: from `ptss` (the leaf `ptloc_walk` found) to `cp_seedf` / `cp_seedc`, returning through
    `<label>_ret`. `secs_open`: the map with every door open (the player's seeds' `_dsecs_open`); `msecs` /
    `mcell`: each mover's per-state sector lists and state cell (the emitter's `_msecs` / `_mcell`)."""
    n = len(cmap.subsectors)
    assert all(ss.numsegs for ss in cmap.subsectors), "a seg-less leaf has no sector to seed from"
    assert n <= 16 ** 3, "the leaf jump reads three nibbles of ptss"
    L = label
    out = [f"{L}_leaf:"]

    def jump(prefix: int, depth: int) -> list:
        """sim.jump16 on ptss nibble 2 - depth, into the sixteen next levels (or the leaves' stubs)"""
        nib = 2 - depth
        targets = []
        for d in range(16):
            p = (prefix << 4) | d
            lo = p << (4 * nib)
            targets.append((f"{L}_j{depth + 1}_{p:x}" if depth < 2 else f"{L}_s{p}") if lo < n else f"{L}_none")
        return [f"    sim.jump16 ptss + {nib}*dw, " + ", ".join(targets)]

    out += jump(0, 0)
    for depth in (1, 2):
        for p in range(16 ** depth):
            if p << (4 * (3 - depth)) < n:
                out += [f"  {L}_j{depth}_{p:x}:"] + jump(p, depth)

    def heights(sec) -> list:
        return [f"    hex.set 8, cp_seedf, {sec.floor_h & M32}", f"    hex.set 8, cp_seedc, {sec.ceil_h & M32}"]

    for s in range(n):
        si = leaf_sector_index(cmap, lds, sds, s)
        seg = cmap.segs[cmap.subsectors[s].firstseg]
        out.append(f"  {L}_s{s}:")
        if si in msecs:                                       # a mover's leaf: its state's heights
            labs = [f"{L}_s{s}_m{k}" for k in range(len(msecs[si]))]
            out.append(f"    sim.jump16 {mcell[si]}, " + ", ".join(labs + [labs[-1]] * (16 - len(labs))))
            for k, sv in enumerate(msecs[si]):
                out += [f"  {labs[k]}:", *heights(seg_sector(lds, sds, sv, seg)), f"    stl.fret {L}_ret"]
        else:
            out += heights(seg_sector(lds, sds, secs_open, seg)) + [f"    stl.fret {L}_ret"]
    out += [f"  {L}_none:", f"    stl.fret {L}_ret"]
    return out


def monster_seed_decls(label: str = "ms_seed") -> list:
    return [f"{label}_ret: hex.vec w/4"]


# ================================================================================================================
# Pieces 4-6: THE MOVE (world._a_chase's move half, _p_move, try_move_monster, _move_monster, _new_chase_dir)
#
# The slot code (unrolled per monster, monstercode) copies its monster into the CONTEXT cells below, calls the
# shared leaves, and copies back. The leaves never see a slot index: the other monsters' boxes are tested
# unrolled over every slot with compile-time addresses, and the mover is excluded by its slot clearing its own
# `mon_active` (M7 P4.2a: `mon_solid`) around the call.
# ================================================================================================================

P32B_CONTEXT = [
    "mm_x: hex.vec 4", "mm_y: hex.vec 4",          # the mover's integer position (int16)
    "mm_nx: hex.vec 4", "mm_ny: hex.vec 4",        # the candidate
    "mm_z: hex.vec 8",                             # its floorz, sign-extended to try_move_mon's width
    "mm_r: hex.vec 2", "mm_r30: hex.vec 1",        # its radius; 1 when it is 30
    "mm_spd: hex.vec 1",                           # 1 when its speed is 10 (else 8)
    "mm_dir: hex.vec 1", "mm_rng: hex.vec 2", "mm_mc: hex.vec 2",   # movedir, P_Random state, movecount (2's c.)
    "mm_tw: hex.vec w/4", "mm_leafw: hex.vec w/4",  # its runtime thing and leaf (the relink's operands)
    "mm_sec: hex.vec 2",                           # its sector (the REJECT row; P_ChangeSector)
    "mm_ok: hex.vec 1", "mm_blk: hex.vec 1",
    "mm_ox16: hex.vec 8", "mm_oy16: hex.vec 8",    # the position before the step, 16.16 (the crossings, boxes)
    "mm_bd20: hex.vec 4", "mm_bd30: hex.vec 4", "mm_bdp: hex.vec 8",   # r + 20, r + 30; (r + 16) << 16
    "mm_rr: hex.vec 4",                            # an mrnd row
    "mm_dx: hex.vec 4", "mm_dy: hex.vec 4", "mm_adx: hex.vec 4", "mm_ady: hex.vec 4",
    "mm_d1: hex.vec 1", "mm_d2: hex.vec 1", "mm_ta: hex.vec 1", "mm_od: hex.vec 1",   # NewChaseDir's
    "mm_wd: hex.vec 1", "mm_wres: hex.vec 1", "mm_tried: hex.vec 8", "mm_ntr: hex.vec 1",
    "mm_c: hex.vec 8",                             # a constant operand
    "mm_ret: hex.vec w/4", "mm_tret: hex.vec w/4", "mm_wret: hex.vec w/4", "mm_nret: hex.vec w/4",
    "mm_cret: hex.vec w/4",
]

# DOOM's direction numbering (world.step_delta): E, NE, N, NW, W, SW, S, SE, NODIR
NODIR = 8


def _add_const(n: int, cell: str, v: int) -> list:
    v &= 16 ** n - 1
    return ["    hex.add_constant %d, %s, %d" % (n, cell, v)] if v else []


def things_leaf_lines(slots, solid: str = "mon_active", hurt: bool = False) -> list:
    """`mm_things`: mm_blk = 1 when a SOLID thing's box overlaps the candidate (world._thing_blocker's monsters and
    player; the static blockers are in the cells). `slots`: [(runtime thing, radius)] per monster slot. `solid`: the
    per-slot flag a monster blocks by -- M7 P4.2a: `mon_solid`, MF_SOLID, which A_Fall clears (a corpse stops
    blocking); `mon_active` before monsters die, where the two are equal. The mover's own flag is clear during the
    call (monstercode.p32b_move_lines, the same `solid`). The player is tested at 16.16: |px - (nx << 16)| <
    (r + 16) << 16. `hurt` (M7 P5, doomfj.hurtcode): a dead player (`p_dead`) is not MF_SOLID and blocks nothing;
    off, the player is always alive and the text is P4's to the byte."""
    out = ["mm_things:",
           "    hex.zero 1, mm_blk",
           "    hex.zero 2, mm_bd20 + 2*dw", "    hex.mov 2, mm_bd20, mm_r", "    hex.mov 4, mm_bd30, mm_bd20",
           *_add_const(4, "mm_bd20", 20), *_add_const(4, "mm_bd30", 30)]
    for j, (t, rad) in enumerate(slots):
        bd = "mm_bd%d" % rad
        assert rad in (20, 30), rad
        nj = "mm_th%d_n" % j
        out += ["    hex.if0 1, %s + %d*dw, %s" % (solid, j, nj),
                "    hex.mov 4, ct_a, thpos_rt + %d*dw" % (16 * t + 4),
                "    hex.sub 4, ct_a, mm_nx", "    hex.abs 4, ct_a",
                "    hex.scmp 4, ct_a, %s, mm_th%d_y, %s, %s" % (bd, j, nj, nj),
                "  mm_th%d_y:" % j,
                "    hex.mov 4, ct_a, thpos_rt + %d*dw" % (16 * t + 12),
                "    hex.sub 4, ct_a, mm_ny", "    hex.abs 4, ct_a",
                "    hex.scmp 4, ct_a, %s, mm_hit, %s, %s" % (bd, nj, nj),
                "  %s:" % nj]
    # the player, 16.16: cpx / cpy already hold the candidate << 16 (the caller sets them first)
    out += (["    hex.if1 1, p_dead, mm_things_out"] if hurt else [])
    out += ["    hex.zero 8, mm_bdp", "    hex.mov 2, mm_bdp + 4*dw, mm_r", *_add_const(4, "mm_bdp + 4*dw", 16)]
    for ax, reg, c in (("x", "viewx", "cpx"), ("y", "viewy", "cpy")):
        out += ["    hex.mov 8, mm_c, %s" % reg, "    hex.sub 8, mm_c, %s" % c, "    hex.abs 8, mm_c",
                "    hex.scmp 8, mm_c, mm_bdp, mm_pl%s, mm_things_out, mm_things_out" % ax, "  mm_pl%s:" % ax]
    out += ["  mm_hit:", "    hex.set 1, mm_blk, 1", "  mm_things_out:", "    stl.fret mm_tret"]
    return out


def move_leaf_lines(*, root: str, lift_trigs, door_boxes, dropmax: int, stepup: int, height: int) -> list:
    """`mm_move`: P_Move for the context's monster (world._p_move): no direction -> mm_ok 0; else one step
    (step_delta: `speed` on an axis, 6 / 7 on both for a diagonal), P_TryMove (the things, then the seed at the
    candidate and the monster cells), and
      * accepted: the WR lifts the step crosses (`lift_trigs`: [(lift slot, axis, coord, lo, hi)], tested for the
        monster's radius), the new position, floorz = the opening's floor, and a changed leaf relinked (sshead /
        thnext, thss_rt) with its new sector -> mm_ok 1;
      * refused: the first monster door (`door_boxes`: [(door slot, (x0, y0, x1, y1))], ascending sector) whose use
        box holds the monster's CURRENT position and that a press would move (closing, or idle and shut) gets
        `dreq`, and movedir = NODIR -> mm_ok 1 (the move counts as made); else mm_ok 0."""
    from doomfj.doorcode import _box_test, _crossed_lines
    from doomfj.world import DIAG_STEP
    out = ["mm_move:",
           "    hex.zero 1, mm_ok",
           "    hex.if_flags mm_dir, %d, mm_mv_go, mm_mv_out" % (1 << NODIR),
           "  mm_mv_go:",
           "    hex.mov 4, mm_nx, mm_x", "    hex.mov 4, mm_ny, mm_y",
           "    sim.jump16 mm_dir, " + ", ".join(["mm_st%d" % d for d in range(8)] + ["mm_mv_out"] * 8)]
    for d in range(8):
        out.append("  mm_st%d:" % d)
        out.append("    hex.if1 1, mm_spd, mm_st%df" % d)
        for spd, lab in ((8, None), (10, "mm_st%df" % d)):
            if lab:
                out.append("  %s:" % lab)
            s, g = spd, DIAG_STEP[spd]
            dx, dy = ((s, 0), (g, g), (0, s), (-g, g), (-s, 0), (-g, -g), (0, -s), (g, -g))[d]
            out += _add_const(4, "mm_nx", dx) + _add_const(4, "mm_ny", dy) + ["    ;mm_stepped"]
    out += ["  mm_stepped:",
            # the candidate, 16.16, where the player's box test and the cells read it
            "    hex.zero 4, cpx", "    hex.mov 4, cpx + 4*dw, mm_nx",
            "    hex.zero 4, cpy", "    hex.mov 4, cpy + 4*dw, mm_ny",
            "    stl.fcall mm_things, mm_tret",
            "    hex.if1 1, mm_blk, mm_refused",
            # the seed: the leaf under the candidate and its heights
            "    hex.zero 10, ptx", "    hex.mov 4, ptx, mm_nx", "    hex.sign_extend 10, 4, ptx",
            "    hex.zero 10, pty", "    hex.mov 4, pty, mm_ny", "    hex.sign_extend 10, 4, pty",
            "    stl.fcall ptloc_walk, ptloc_ret",
            "    stl.fcall ms_seed_leaf, ms_seed_ret",
            "    hex.zero 8, cprad", "    hex.mov 2, cprad + 4*dw, mm_r",
            "    sim.try_move_mon %s, %d, %d, mm_z, %d" % (root, height, stepup, dropmax),
            "    hex.if0 1, mv_ok, mm_refused",
            # ---- accepted: the WR lifts the step crosses (old: mm_ox16 / mm_oy16; new: cpx / cpy) ----------
            "    hex.zero 4, mm_ox16", "    hex.mov 4, mm_ox16 + 4*dw, mm_x",
            "    hex.zero 4, mm_oy16", "    hex.mov 4, mm_oy16 + 4*dw, mm_y",
            "    hex.if1 1, mm_r30, mm_lw30"]
    for rad in (20, 30):
        if rad == 30:
            out.append("  mm_lw30:")
        for k, (slot, axis, coord, lo, hi) in enumerate(lift_trigs):
            out += _crossed_lines("mm_lw%d_%d" % (rad, k), axis, coord, lo, hi, rad,
                                  ["    hex.set 1, lreq + %d*dw, 1" % slot],
                                  regs=("mm_ox16", "mm_oy16", "cpx", "cpy"))
        out.append("    ;mm_lwdone")
    out += ["  mm_lwdone:",
            "    hex.mov 4, mm_x, mm_nx", "    hex.mov 4, mm_y, mm_ny",
            "    hex.mov 8, mm_z, cp_floor",
            # a new leaf: out of the old list, into the new one, and the new sector
            "    hex.zero w/4, mm_c", "    hex.mov 3, mm_c, ptss",
            "    hex.cmp 3, mm_c, mm_leafw, mm_relink, mm_same, mm_relink",
            "  mm_relink:",
            "    sim.leaf_unlink mm_tw, mm_leafw",
            "    hex.zero w/4, mm_leafw", "    hex.mov 3, mm_leafw, ptss",
            "    sim.leaf_link mm_tw, mm_leafw",
            "    lfsec.lookup mm_sec, mm_leafw",
            "  mm_same:",
            "    hex.set 1, mm_ok, 1",
            "    ;mm_mv_out",
            # ---- refused: a monster door's use box --------------------------------------------------------
            "  mm_refused:",
            "    hex.zero 4, mm_ox16", "    hex.mov 4, mm_ox16 + 4*dw, mm_x",
            "    hex.zero 4, mm_oy16", "    hex.mov 4, mm_oy16 + 4*dw, mm_y"]
    for k, (slot, box) in enumerate(door_boxes):
        nxt = "mm_db%d_n" % k
        out += _box_test("mb%d" % k, box, "mm_db%d_in" % k, nxt, regs=("mm_ox16", "mm_oy16"))
        out += ["  mm_db%d_in:" % k,
                # closing (2) -> press; idle (0) and shut (state 0) -> press; else not this door
                "    hex.if_flags ddir + %d*dw, %d, mm_db%d_i, mm_db%d_p" % (slot, 1 << 2, k, k),
                "  mm_db%d_i:" % k,
                "    hex.if_flags ddir + %d*dw, %d, %s, mm_db%d_s" % (slot, 1 << 0, nxt, k),
                "  mm_db%d_s:" % k,
                "    hex.if0 1, dstate + %d*dw, mm_db%d_p" % (slot, k),
                "    ;%s" % nxt,
                "  mm_db%d_p:" % k,
                "    hex.set 1, dreq + %d*dw, 1" % slot,
                "    hex.set 1, mm_dir, %d" % NODIR,
                "    hex.set 1, mm_ok, 1",
                "    ;mm_mv_out",
                "  %s:" % nxt]
    out += ["  mm_mv_out:", "    stl.fret mm_ret"]
    return out


def _rand_lines() -> list:
    """one P_Random on the mover's stream: mm_rr = mrnd's row at the post-increment state"""
    return ["    hex.inc 2, mm_rng", "    mrnd.lookup mm_rr, mm_rng"]


def ncd_leaf_lines(*, deadzone: int, max_tries: int) -> list:
    """`mm_ncd`: P_NewChaseDir (world._new_chase_dir) with the D5 cap -- DOOM's try order, a direction already
    tried skipped, at most `max_tries` distinct tries (then NODIR), each try `mm_walk` (P_TryWalk: P_Move, and on
    success movecount = P_Random & 15). The random calls in the model's order: one for the swap (always, after the
    diagonal), one for the sweep's direction (only when reached), one per successful walk."""
    from doomfj import gamedata as gd
    out = ["mm_ncd:",
           "    hex.zero 8, mm_tried", "    hex.zero 1, mm_ntr",
           "    hex.mov 1, mm_od, mm_dir",
           "    mopp.lookup mm_ta, mm_od",                      # turnaround = OPPOSITE[olddir] (NODIR -> NODIR)
           # dx, dy to the player: (px >> 16) - x, (py >> 16) - y
           "    hex.mov 4, mm_dx, viewx + 4*dw", "    hex.sub 4, mm_dx, mm_x",
           "    hex.mov 4, mm_dy, viewy + 4*dw", "    hex.sub 4, mm_dy, mm_y",
           "    hex.mov 4, mm_adx, mm_dx", "    hex.abs 4, mm_adx",
           "    hex.mov 4, mm_ady, mm_dy", "    hex.abs 4, mm_ady",
           # d1: E if dx > dz, W if dx < -dz, else NODIR; d2: S if dy < -dz, N if dy > dz
           "    hex.set 1, mm_d1, %d" % NODIR, "    hex.set 1, mm_d2, %d" % NODIR,
           "    hex.set 4, mm_c, %d" % deadzone,
           "    hex.cmp 4, mm_adx, mm_c, mm_n_d2, mm_n_d2, mm_n_d1",
           "  mm_n_d1:",
           "    hex.sign 4, mm_dx, mm_n_w, mm_n_e",
           "  mm_n_w:", "    hex.set 1, mm_d1, %d" % gd.DI_WEST, "    ;mm_n_d2",
           "  mm_n_e:", "    hex.set 1, mm_d1, %d" % gd.DI_EAST,
           "  mm_n_d2:",
           "    hex.cmp 4, mm_ady, mm_c, mm_n_dg, mm_n_dg, mm_n_d2s",
           "  mm_n_d2s:",
           "    hex.sign 4, mm_dy, mm_n_s, mm_n_n",
           "  mm_n_s:", "    hex.set 1, mm_d2, %d" % gd.DI_SOUTH, "    ;mm_n_dg",
           "  mm_n_n:", "    hex.set 1, mm_d2, %d" % gd.DI_NORTH,
           # the diagonal, when both axes pick a direction: DIAGS[((dy < 0) << 1) + (dx > 0)], unless the turnaround
           "  mm_n_dg:",
           "    hex.if_flags mm_d1, %d, mm_n_dg1, mm_n_swap" % (1 << NODIR),
           "  mm_n_dg1:",
           "    hex.if_flags mm_d2, %d, mm_n_dg2, mm_n_swap" % (1 << NODIR),
           "  mm_n_dg2:",
           "    hex.sign 4, mm_dy, mm_n_dgs, mm_n_dgn",
           "  mm_n_dgn:",                                   # dy >= 0: NW (dx <= 0) / NE (dx > 0)
           "    hex.set 1, mm_wd, %d" % gd.DIAGS[0],
           "    hex.sign 4, mm_dx, mm_n_dgt, mm_n_dgz1",
           "  mm_n_dgz1:",
           "    hex.if0 4, mm_dx, mm_n_dgt",
           "    hex.set 1, mm_wd, %d" % gd.DIAGS[1], "    ;mm_n_dgt",
           "  mm_n_dgs:",                                   # dy < 0: SW / SE
           "    hex.set 1, mm_wd, %d" % gd.DIAGS[2],
           "    hex.sign 4, mm_dx, mm_n_dgt, mm_n_dgz2",
           "  mm_n_dgz2:",
           "    hex.if0 4, mm_dx, mm_n_dgt",
           "    hex.set 1, mm_wd, %d" % gd.DIAGS[3],
           "  mm_n_dgt:",
           "    hex.cmp 1, mm_wd, mm_ta, mm_n_dgw, mm_n_swap, mm_n_dgw",
           "  mm_n_dgw:", *_walk("dg"),
           # the swap: P_Random > 200, or |dy| > |dx| (the random call comes first, always)
           "  mm_n_swap:", *_rand_lines(),
           "    hex.if_flags mm_rr + 2*dw, %d, mm_n_noswr, mm_n_sw" % 0b1010101010101010,   # bit 0: > 200
           "  mm_n_noswr:",
           "    hex.cmp 4, mm_ady, mm_adx, mm_n_ta, mm_n_ta, mm_n_sw",
           "  mm_n_sw:",
           "    hex.mov 1, mm_wd, mm_d1", "    hex.mov 1, mm_d1, mm_d2", "    hex.mov 1, mm_d2, mm_wd",
           "  mm_n_ta:",                                    # a turnaround choice becomes NODIR
           "    hex.cmp 1, mm_d1, mm_ta, mm_n_ta2, mm_n_ta1, mm_n_ta2",
           "  mm_n_ta1:", "    hex.set 1, mm_d1, %d" % NODIR,
           "  mm_n_ta2:",
           "    hex.cmp 1, mm_d2, mm_ta, mm_n_w1, mm_n_ta3, mm_n_w1",
           "  mm_n_ta3:", "    hex.set 1, mm_d2, %d" % NODIR,
           "  mm_n_w1:",
           "    hex.if_flags mm_d1, %d, mm_n_w1g, mm_n_w2" % (1 << NODIR),
           "  mm_n_w1g:", "    hex.mov 1, mm_wd, mm_d1", *_walk("w1"),
           "  mm_n_w2:",
           "    hex.if_flags mm_d2, %d, mm_n_w2g, mm_n_wo" % (1 << NODIR),
           "  mm_n_w2g:", "    hex.mov 1, mm_wd, mm_d2", *_walk("w2"),
           "  mm_n_wo:",                                    # the old direction
           "    hex.if_flags mm_od, %d, mm_n_wog, mm_n_sweep" % (1 << NODIR),
           "  mm_n_wog:", "    hex.mov 1, mm_wd, mm_od", *_walk("wo"),
           # the sweep: E..SE if P_Random is odd, else SE..E; the turnaround skipped
           "  mm_n_sweep:", *_rand_lines(),
           "    hex.if_flags mm_rr + 2*dw, %d, mm_n_dn, mm_n_up" % 0b1100110011001100]          # bit 1: odd
    for tag, order in (("up", range(8)), ("dn", range(7, -1, -1))):
        out.append("  mm_n_%s:" % tag)
        for tdir in order:
            lab = "mm_n_%s%d" % (tag, tdir)
            out += ["    hex.set 1, mm_wd, %d" % tdir,
                    "    hex.cmp 1, mm_wd, mm_ta, %sw, %s, %sw" % (lab, lab, lab),
                    "  %sw:" % lab, *_walk("%s%d" % (tag, tdir)), "  %s:" % lab]
        out.append("    ;mm_n_last")
    out += ["  mm_n_last:",                                 # the turnaround itself, last
            "    hex.if_flags mm_ta, %d, mm_n_lg, mm_n_fail" % (1 << NODIR),
            "  mm_n_lg:", "    hex.mov 1, mm_wd, mm_ta", *_walk("last"),
            "  mm_n_fail:",
            "    hex.set 1, mm_dir, %d" % NODIR,
            "  mm_n_done:",
            "    stl.fret mm_nret"]
    return out


def _walk(tag: str) -> list:
    """one P_TryWalk site in mm_ncd: mm_walk on mm_wd; success -> done, the cap -> NODIR (fail), else on"""
    return ["    stl.fcall mm_walk, mm_wret",
            "    sim.jump16 mm_wres, mm_nw_%s, mm_n_done, mm_n_fail, %s" % (tag, ", ".join(["mm_n_fail"] * 13)),
            "  mm_nw_%s:" % tag]


def walk_leaf_lines(*, max_tries: int) -> list:
    """`mm_walk`: one try of direction mm_wd -- 0: already tried (or the move failed), go on; 1: moved (movecount =
    P_Random & 15); 2: the cap (`max_tries` distinct directions tried already)."""
    out = ["mm_walk:",
           "    hex.zero 1, mm_wres",
           "    sim.jump16 mm_wd, " + ", ".join(["mm_wk%d" % d for d in range(8)] + ["mm_wk_out"] * 8)]
    for d in range(8):
        out += ["  mm_wk%d:" % d, "    hex.if1 1, mm_tried + %d*dw, mm_wk_out" % d,
                "    hex.set 1, mm_tried + %d*dw, 1" % d, "    ;mm_wk_new"]
    out += ["  mm_wk_new:",
            "    hex.if_flags mm_ntr, %d, mm_wk_try, mm_wk_cap" % (1 << max_tries),   # max_tries tried: the cap
            "  mm_wk_cap:",
            "    hex.set 1, mm_wres, 2", "    ;mm_wk_out",
            "  mm_wk_try:",
            "    hex.inc 1, mm_ntr",
            "    hex.mov 1, mm_dir, mm_wd",
            "    stl.fcall mm_move, mm_ret",
            "    hex.if0 1, mm_ok, mm_wk_out",
            *_rand_lines(),
            "    hex.zero 2, mm_mc", "    hex.mov 1, mm_mc, mm_rr + 3*dw",   # movecount = P_Random & 15
            "    hex.set 1, mm_wres, 1",
            "  mm_wk_out:",
            "    stl.fret mm_wret"]
    return out


def chase_leaf_lines() -> list:
    """`mm_chase`: the move half of A_Chase in the chase mode (world._a_chase after the turn): movecount =
    max(-1, movecount - 1); then if movecount < 0 or P_Move fails, P_NewChaseDir. movecount is 2 nibbles, two's
    complement (0xFF = -1, where it saturates)."""
    return ["mm_chase:",
            "    hex.set 2, mm_c, 0xFF",
            "    hex.cmp 2, mm_mc, mm_c, mm_ch_dec, mm_ch_ncd, mm_ch_dec",
            "  mm_ch_dec:",
            "    hex.dec 2, mm_mc",
            "    hex.cmp 2, mm_mc, mm_c, mm_ch_mv, mm_ch_ncd, mm_ch_mv",
            "  mm_ch_mv:",
            "    stl.fcall mm_move, mm_ret",
            "    hex.if1 1, mm_ok, mm_ch_out",
            "  mm_ch_ncd:",
            "    stl.fcall mm_ncd, mm_nret",
            "  mm_ch_out:",
            "    stl.fret mm_cret"]


# ================================================================================================================
# The constructions every user shares (the emitter, the harnesses)
# ================================================================================================================

def static_blockers(w) -> tuple:
    """`(things, var)` for `collision.monster_cells_fj(things=)` from a World: the barrels (presence `bar_solid`),
    then the solid decorations -- a presence flag `mc_don + i*dw` for each that some skill lacks; `var` lists those
    decorations' indices in `w.decor_solid` (the order of the `mc_don` flags)"""
    from doomfj import gamedata as gd
    br = gd.THING_TYPES[2035].radius
    things = [(t.x, t.y, br, "bar_solid + %d*dw" % b) for b, t in enumerate(w.barrel_things)]
    allsk = [gd.skill_bit(sk) for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)]
    var = [k for k, t in enumerate(w.decor_solid) if not all(t.flags & b for b in allsk)]
    things += [(t.x, t.y, gd.THING_TYPES[t.type].radius, ("mc_don + %d*dw" % var.index(k)) if k in var else None)
               for k, t in enumerate(w.decor_solid)]
    return things, var


def decor_presence(w, var, skill: int) -> list:
    """the `mc_don` flags at `skill` -- which of the skill-dependent decorations stand"""
    from doomfj import gamedata as gd
    return [int(bool(w.decor_solid[k].flags & gd.skill_bit(skill))) for k in var]


def world_cell_inputs(w, door_quant: int) -> dict:
    """the keyword arguments of `collision.monster_cells_fj` (and `monster_seed_fj`'s `secs_open` / `msecs` /
    `mcell`) built from a World the way the emitter builds the player's -- for the harnesses"""
    from doomfj import gamedata as gd
    from doomfj.doors import pass_state
    from doomfj.movers import lift_states, switch_sectors
    from doomfj.reference_model import ML_BLOCKING, apply_sector_heights
    secs, lds, sds = w.secs, w.lds, w.sds
    doors = {}
    for d, si in enumerate(w.door_order):
        for li in w.door_lines.get(si, ()):
            doors.setdefault(li, []).append((d, pass_state(secs, lds, sds, si)))
    ls = lift_states(secs, lds, sds, door_quant)
    assert sorted(ls) == list(w.lift_order), (sorted(ls), w.lift_order)
    sw = switch_sectors(secs, lds, sds)
    msecs = {si: [apply_sector_heights(secs, {si: (h, secs[si].ceil_h)}) for h in st] for si, st in ls.items()}
    msecs.update({si: [secs, apply_sector_heights(secs, {si: (low, secs[si].ceil_h)})] for si, (low, _h) in sw.items()})
    mcell = {si: "lstate + %d*dw" % k for k, si in enumerate(sorted(ls))}
    mcell.update({si: "fswitch" for si in sw})
    return dict(secs_open=apply_sector_heights(secs, w.open_h),
                door_line_ids={li for v in w.door_lines.values() for li in v}, doors=doors, msecs=msecs,
                mcell=mcell, ml_blocking=ML_BLOCKING, ml_blockmonsters=gd.ML_BLOCKMONSTERS)
