"""M8 C8 part 2 -- THE LOST SOUL in fj: `doomfj.lostsoul`'s rules (its docstring is the convention list; this module
copies it). Emitted only on a map with a soul (`soul_on`), in the game tier's "final" modes (the charge flies on the
knock cells and the fight's target load) -- a map without one has not one line of it, so E1M1 and E1M2 are unchanged.

THE CELLS (persisted, `map_persist`; restarted per skill, `restart_lines`), one row per soul in `soul_slots` order:

    sk_fly   1 x nsoul   MF_SKULLFLY          sk_z     8 x nsoul   z, 16.16
    sk_inf   1 x nsoul   MF_INFLOAT           sk_momz  8 x nsoul   momz, 16.16
    sk_ceil  4 x nsoul   ceilingz, map units

THE PIECES (each a leaf, `stl.fcall`; the slot code is monstercode's, which calls them for a soul slot):
  * `sks<k>` (XY, P_XYMovement): the momentum not 0 or flying -> the stop (fly and momentum 0: fly 0, momz 0, the
    spawn state due: `sk_lk`) or the knock window loaded (knockcode's kb_* / monstermove's mm_*: radius 16, its own
    MF_SOLID and MF_SHOOTABLE cleared around the move so neither the thing test nor the slam scan meets itself) and
    `sk_mmove` (kb_who 2: knockcode's kb_xy with the soul's try `sk_try` and its friction rule -- none while flying
    or airborne), the window back;
  * `sk_try` (frets kb_tyret): the integer part unchanged -> the fraction only; flying -> `sk_slam` (the scan, the
    model's `slam_thing` order) and a hit -> `sk_hitgo` (one P_Random on the soul's stream, the claw's table
    `trclaw`: ((v % 8) + 1) * 3; the monster or the barrel through damagecode's dm_go in its MONSTER mode, the player
    through dp_go; the soul the inflictor and the source) and the charge's end; not flying -> mm_things; then the seed,
    the monster cells and `sk_hts` (the opening holds its height, ceilz - z, floorz - z: 16.16); accepted -> the WR
    lifts at radius 16, the move, floorz, ceilingz, the relink;
  * `skz<k>` / `sk_zm` (P_ZMovement): z != floorz << 16 or momz != 0 -> z += momz, the float toward the target
    (mt_load: its 16.16 position, `mt_tz` its z -- the player's by kb_pz), the floor (the bounce), the ceiling;
  * `sk_charge` (A_SkullAttack's effect): ia_leaf's angle from the soul's whole units to mt_tq, momentum = 20 x
    finesine (projcode's `_times20`), dist = (P_AproxDistance >> 16) / 20 (at least 1), momz = (tz + 28 << 16 - z) /
    dist, C's division;
  * `sk_hts`: P_TryMove's height rules on (cp_ok, cp_floor, cp_ceil) for z `sl_z` and height `sl_h` -> mv_ok and
    `sk_fok` (FLOATOK: the position passed and the opening holds it) -- monstermove's mm_move reads both for a soul
    (P_Move's float branch).
"""
from __future__ import annotations

from typing import List, Sequence

from doomfj import gamedata as gd
from doomfj.lostsoul import (CORPSE_H, SKULLSPEED, SOUL_H, SOUL_HALF, TARGET_HALF, is_soul_type)

M32 = 0xFFFFFFFF
PERSIST = ("sk_fly", "sk_inf", "sk_z", "sk_momz", "sk_ceil")
NIB = {"sk_fly": 1, "sk_inf": 1, "sk_z": 8, "sk_momz": 8, "sk_ceil": 4}
MODEL_FIELD = {"sk_fly": "sk_fly", "sk_inf": "sk_inf", "sk_z": "sk_z", "sk_momz": "sk_momz", "sk_ceil": "sk_ceil"}
SOUL_R = 16
FLOAT16 = gd.FLOATSPEED                      # 4 << 16
STEP16 = gd.MAX_STEP_UP                      # 24 << 16
assert SKULLSPEED == 20 << 16 and SOUL_HALF == TARGET_HALF == 28


def soul_on(w) -> bool:
    return bool(getattr(w, "soul_slots", None))


def map_souls(map_wad, mapname: str) -> bool:
    return any(is_soul_type(t.type) for t in map_wad.things(mapname))


def map_persist(map_wad, mapname: str) -> tuple:
    """the map-dependent persisted names (build._map_persist): the soul cells on a map with a lost soul"""
    return PERSIST if map_souls(map_wad, mapname) else ()


def _vec(name: str, nib: int, vals) -> str:
    return "%s: hex.vec %d, %d" % (name, nib * max(1, len(vals)),
                                   sum((v & (16 ** nib - 1)) << (4 * nib * i) for i, v in enumerate(vals)))


def cell_decls(w, skill: int) -> List[str]:
    """the soul cells at `skill`'s level start"""
    snap = w.level_start(skill)
    return [_vec(c, NIB[c], [getattr(snap, MODEL_FIELD[c])[k] for k in range(len(w.soul_slots))]) for c in PERSIST]


def restart_lines(w, skill: int) -> List[str]:
    """NEW GAME / the restart at `skill`: every soul cell at its level start"""
    snap = w.level_start(skill)
    out = []
    for c in PERSIST:
        n = len(w.soul_slots)
        v = sum((getattr(snap, MODEL_FIELD[c])[k] & (16 ** NIB[c] - 1)) << (4 * NIB[c] * k) for k in range(n))
        out.append("    hex.set %d, %s, %d" % (NIB[c] * n, c, v))
    return out


SCRATCH = ["sk_lk: hex.vec 1", "sk_lr: hex.vec 1", "sk_fok: hex.vec 1", "sk_hit: hex.vec 1", "sk_hj: hex.vec 2",
           "sw_fly: hex.vec 1", "sw_z: hex.vec 8", "sw_mz: hex.vec 8", "sw_c: hex.vec 8", "sw_rng: hex.vec 2",
           "sw_me: hex.vec 2", "sw_id: hex.vec 2", "sw_sh: hex.vec 1",
           "sl_z: hex.vec 8", "sl_h: hex.vec 8", "sk_t: hex.vec 8", "sk_c: hex.vec 8", "sk_a: hex.vec 4",
           "sk_dx: hex.vec 8", "sk_dy: hex.vec 8", "sk_d: hex.vec 8", "sk_d3: hex.vec 8",
           "sk_b32: hex.vec 4, 32", "sk_b36: hex.vec 4, 36", "sk_b46: hex.vec 4, 46", "sk_b26: hex.vec 4, 26",
           "sk_bp: hex.vec 8, %d" % ((SOUL_R + 16) << 16),
           "sz_z: hex.vec 8", "sz_mz: hex.vec 8", "sz_c: hex.vec 8", "sz_f: hex.vec 8", "sz_fly: hex.vec 1",
           "sz_inf: hex.vec 1", "sz_live: hex.vec 1", "sz_tg: hex.vec 2", "sz_x: hex.vec 8", "sz_y: hex.vec 8",
           "sz_h: hex.vec 8", "sz_t: hex.vec 8", "sz_tz: hex.vec 8",
           "sc_z: hex.vec 8", "sc_mx: hex.vec 8", "sc_my: hex.vec 8", "sc_mz: hex.vec 8", "sc_idx: hex.vec 3",
           "sc_dn: hex.vec 4", "sc_q: hex.vec 4", "sc_r: hex.vec 2", "sc_20: hex.vec 2, 20", "sc_a: hex.vec 8",
           "sc_r8: hex.vec 4", "sc_neg: hex.vec 1", "sc_was: hex.vec 1", "mt_tz: hex.vec 8",
           # monstermove's context for a soul (mm_move's float, mm_decide's range): flag, z, floating, ceiling
           "mm_sk: hex.vec 1", "mm_skz: hex.vec 8", "mm_ski: hex.vec 1", "mm_skc: hex.vec 4", "mm_r16: hex.vec 1",
           "mm_bd16: hex.vec 4",
           # the render's leaf floor swap (select_lines / leaf_restore_lines)
           "sf_d: hex.vec 1", "sf_sv: hex.vec 4",
           "pb_bd16: hex.vec 8, %d" % ((SOUL_R + 16) << 16),     # lootcode.pb_mon_lines' radius-16 bound
           "sks_ret: hex.vec w/4", "skz_ret: hex.vec w/4", "sk_slret: hex.vec w/4", "sk_hret: hex.vec w/4",
           "sk_htret: hex.vec w/4", "sk_zret: hex.vec w/4", "sk_apret: hex.vec w/4", "sk_cret: hex.vec w/4"]


# ---- small helpers -------------------------------------------------------------------------------------------------
# M8 C2 (docs/c2-slot-ids.md): the scratch registers holding a slot id or a code -- `sn` nibbles each (`scratch`)
SLOT_REGS = ("sk_hj", "sw_me", "sw_id", "sz_tg")


def scratch(sn: int = 2) -> List[str]:
    """SCRATCH at M8 C2's slot-id width `sn` (world.slot_nibbles): sk_hj (a slot or barrel index), sw_me / sw_id (the
    soul's code and id) and sz_tg (its target's code) three nibbles past 254 slots"""
    out = []
    for d in SCRATCH:
        name, _, rest = d.partition(": hex.vec ")
        if name in SLOT_REGS:
            assert rest == "2", d
            d = "%s: hex.vec %d" % (name, sn)
        out.append(d)
    return out


def _sn(w) -> int:
    from doomfj.world import slot_nibbles
    return slot_nibbles(w.layout)


def _hi16(dst: str, src4: str) -> List[str]:
    """dst[:8] = src4[:4] << 16 (a 16.16 from whole map units)"""
    return ["    hex.zero 4, %s" % dst, "    hex.mov 4, %s + 4*dw, %s" % (dst, src4)]


def _slot_cells(w, m: int) -> dict:
    from doomfj.monstercode import cell_nibbles
    from doomfj.sectorcode import msec_cell
    k = w.soul_of[m]
    sch = w.schema
    return {"k": k, "fly": "sk_fly + %d*dw" % k, "inf": "sk_inf + %d*dw" % k, "z": "sk_z + %d*dw" % (8 * k),
            "mz": "sk_momz + %d*dw" % (8 * k), "c": "sk_ceil + %d*dw" % (4 * k),
            "mx": "mkx + %d*dw" % (8 * m), "my": "mky + %d*dw" % (8 * m),
            "fx": "mfx + %d*dw" % (4 * m), "fy": "mfy + %d*dw" % (4 * m),
            "fz": "mon_floorz + %d*dw" % (4 * m), "sh": "mon_shootable + %d*dw" % m,
            "so": "mon_solid + %d*dw" % m, "rng": "mon_rng + %d*dw" % (2 * m),
            "tg": "mon_target + %d*dw" % (cell_nibbles(sch, "mon_target") * m),
            "sec": msec_cell(m, w.sec_nibbles)}


# ---- the XY move: the slot stub, sk_mmove, sk_try --------------------------------------------------------------------
def xy_stub_lines(w, m: int, rt: int, tele: bool = False) -> List[str]:
    """`sks<k>` (stl.fcall sks<k>, sks_ret) for soul slot m (runtime thing rt): P_XYMovement's half of the thinker.
    M8 soultele (`tele`, a map with a teleport line): after the move a teleport's facing (teleportcode.slot_back_lines:
    tp_hit) and the z back (sw_z: sk_try's fire set it to the destination floor)"""
    from doomfj.teleportcode import slot_back_lines
    c = _slot_cells(w, m)
    k, L = c["k"], "sks%d" % c["k"]
    nib = w.sec_nibbles
    X, Y = "thpos_rt + %d*dw" % (16 * rt + 4), "thpos_rt + %d*dw" % (16 * rt + 12)
    return ["%s:" % L,
            "    hex.zero 1, sk_lk",
            "    hex.if1 8, %s, %s_go" % (c["mx"], L), "    hex.if1 8, %s, %s_go" % (c["my"], L),
            "    hex.if0 1, %s, %s_o" % (c["fly"], L),
            "  %s_go:" % L,
            "    hex.if1 8, %s, %s_mv" % (c["mx"], L), "    hex.if1 8, %s, %s_mv" % (c["my"], L),
            # flying and still: "the skull slammed into something" -- fly 0, momz 0, the spawn state
            "    hex.zero 1, %s" % c["fly"], "    hex.zero 8, %s" % c["mz"], "    hex.set 1, sk_lk, 1",
            "    ;%s_o" % L,
            "  %s_mv:" % L,
            "    hex.mov 8, kb_vx, %s" % c["mx"], "    hex.mov 8, kb_vy, %s" % c["my"],
            "    hex.mov 4, kb_px, %s" % c["fx"], "    hex.mov 4, kb_px + 4*dw, %s" % X,
            "    hex.mov 4, kb_py, %s" % c["fy"], "    hex.mov 4, kb_py + 4*dw, %s" % Y,
            "    hex.mov 4, mm_x, %s" % X, "    hex.mov 4, mm_y, %s" % Y,
            "    hex.mov 4, mm_z, %s" % c["fz"], "    hex.sign_extend 8, 4, mm_z",
            "    hex.set 2, mm_r, %d" % SOUL_R, "    hex.zero 1, mm_r30", "    hex.set 1, mm_r16, 1",
            "    hex.set w/4, mm_tw, %d" % rt,
            "    hex.zero w/4, mm_leafw", "    hex.mov 3, mm_leafw, thss_rt + %d*dw" % (16 * rt),
            "    hex.mov %d, mm_sec, %s" % (nib, c["sec"]),
            "    hex.mov 1, kb_dead, %s" % c["sh"], "    hex.xor_by kb_dead, 1",            # a corpse
            "    hex.mov 1, sw_fly, %s" % c["fly"], "    hex.mov 8, sw_z, %s" % c["z"],
            "    hex.mov 8, sw_mz, %s" % c["mz"],
            "    hex.mov 4, sw_c, %s" % c["c"], "    hex.sign_extend 8, 4, sw_c",
            "    hex.mov 2, sw_rng, %s" % c["rng"],
            "    hex.set %d, sw_me, %d" % (_sn(w), m + 2), "    hex.set %d, sw_id, %d" % (_sn(w), m + 1),
            # itself out of the thing test and the slam scan: MF_SOLID and MF_SHOOTABLE cleared around the move
            "    hex.mov 1, kb_sv, %s" % c["so"], "    hex.zero 1, %s" % c["so"],
            "    hex.mov 1, sw_sh, %s" % c["sh"], "    hex.zero 1, %s" % c["sh"],
            "    stl.fcall sk_mmove, kb_mret",
            *(slot_back_lines(m, facing="mon_facing + %d*dw" % m, knock=True, walk=False, tag="tpsb")
              + ["    hex.mov 8, %s, sw_z" % c["z"]] if tele else []),           # M8 soultele: EV_Teleport's
            "    hex.mov 1, %s, kb_sv" % c["so"], "    hex.mov 1, %s, sw_sh" % c["sh"],
            "    hex.mov 8, %s, kb_vx" % c["mx"], "    hex.mov 8, %s, kb_vy" % c["my"],
            "    hex.mov 4, %s, kb_px" % c["fx"], "    hex.mov 4, %s, kb_py" % c["fy"],
            "    hex.mov 4, %s, mm_x" % X, "    hex.mov 4, %s, mm_y" % Y,
            "    hex.mov 4, %s, mm_z" % c["fz"],
            "    hex.mov 3, thss_rt + %d*dw, mm_leafw" % (16 * rt),
            "    hex.mov %d, %s, mm_sec" % (nib, c["sec"]),
            "    hex.mov 1, %s, sw_fly" % c["fly"], "    hex.mov 8, %s, sw_mz" % c["mz"],
            "    hex.mov 4, %s, sw_c" % c["c"], "    hex.mov 2, %s, sw_rng" % c["rng"],
            "  %s_o:" % L,
            "    stl.fret sks_ret"]


def mmove_lines(sn: int = 2) -> List[str]:
    """`sk_mmove` (stl.fcall sk_mmove, kb_mret): knockcode's kb_xy for a soul -- kb_who 2, its height (a corpse 14).
    M8 C2: kb_live is `sn` nibbles"""
    return ["sk_mmove:",
            "    hex.set 1, kb_who, 2",
            "    hex.set 8, kb_ht, %d" % SOUL_H,
            "    hex.if0 1, kb_dead, skm_a", "    hex.set 8, kb_ht, %d" % CORPSE_H,
            "  skm_a:",
            "    stl.fcall kb_xy, kb_xyret",
            "    hex.if1 8, kb_vx, skm_lv", "    hex.if1 8, kb_vy, skm_lv",
            "    hex.dec %d, kb_live" % sn,                                    # it stopped
            "  skm_lv:",
            "    stl.fret kb_mret"]


def xy_friction_lines() -> List[str]:
    """knockcode.xy_lines' soul gate, before its corpse rule: a soul (kb_who 2) flying or airborne keeps its momentum
    (P_XYMovement's `MF_SKULLFLY` and `z > floorz` returns)"""
    return ["    hex.if_flags kb_who, %d, kq_nsk, kq_skf" % (1 << 2),
            "  kq_skf:",
            "    hex.if1 1, sw_fly, kq_xout",
            *_hi16("kb_t", "mm_z"),
            "    hex.scmp 8, sw_z, kb_t, kq_nsk, kq_nsk, kq_xout",
            "  kq_nsk:"]


def try_dispatch_lines() -> List[str]:
    """knockcode.xy_lines' `kb_try` on a map with souls: kb_who 2 -> sk_try"""
    return ["kb_try:",
            "    hex.if_flags kb_who, %d, kq_tw, sk_try" % (1 << 2),
            "  kq_tw:",
            "    hex.if1 1, kb_who, kb_mtry",
            "    ;kb_ptry"]


def try_lines(mon_root: str, lift_trigs=(), teleport: Sequence[str] = ()) -> List[str]:
    """`sk_try` (via kb_try; frets kb_tyret): the soul's P_TryMove of an XY step at (kb_cx, kb_cy). M8 soultele
    (`teleport`: teleportcode.monster_lines(knock_ctx=True, soul="knock")): the WR teleports after the lifts, as
    knockcode.mtry_lines -- a fire makes the destination the move and the candidate, its floor and ceiling the soul's
    (cp_floor, cp_ceil), z = the floor << 16 and momz 0 (sw_z, sw_mz), the momentum stopped"""
    from doomfj.doorcode import _crossed_lines
    out = ["sk_try:",
           "    hex.set 1, kb_ok, 1",
           "    hex.cmp 4, kb_cx + 4*dw, mm_x, skt_t, skt_sx, skt_t",
           "  skt_sx:",
           "    hex.cmp 4, kb_cy + 4*dw, mm_y, skt_t, skt_fr, skt_t",            # the same whole units: untested
           "  skt_t:",
           "    hex.mov 4, mm_nx, kb_cx + 4*dw", "    hex.mov 4, mm_ny, kb_cy + 4*dw",
           "    hex.zero 4, cpx", "    hex.mov 4, cpx + 4*dw, mm_nx",
           "    hex.zero 4, cpy", "    hex.mov 4, cpy + 4*dw, mm_ny",
           "    hex.if0 1, sw_fly, skt_nf",
           "    stl.fcall sk_slam, sk_slret",                                   # PIT_CheckThing's skull slam
           "    hex.if0 1, sk_hit, skt_l",
           "    stl.fcall sk_hitgo, sk_hret",
           "    hex.zero 1, sw_fly", "    hex.zero 8, sw_mz", "    hex.set 1, sk_lk, 1",
           "    ;skt_no",
           "  skt_nf:",                                                          # not flying: a solid thing refuses
           "    stl.fcall mm_things, mm_tret",
           "    hex.if1 1, mm_blk, skt_no",
           "  skt_l:",
           "    hex.zero 10, ptx", "    hex.mov 4, ptx, mm_nx", "    hex.sign_extend 10, 4, ptx",
           "    hex.zero 10, pty", "    hex.mov 4, pty, mm_ny", "    hex.sign_extend 10, 4, pty",
           "    stl.fcall ptloc_walk, ptloc_ret",
           "    stl.fcall ms_seed_leaf, ms_seed_ret",
           "    hex.zero 8, cprad", "    hex.mov 2, cprad + 4*dw, mm_r",
           "    hex.mov 8, cp_drop, cp_seedf",
           "    sim.check_cells %s" % mon_root,
           "    hex.mov 8, sl_z, sw_z", "    hex.mov 8, sl_h, kb_ht",
           "    stl.fcall sk_hts, sk_htret",
           "    hex.if0 1, mv_ok, skt_no",
           # ---- accepted: the WR lifts crossed (radius 16), the move, the floor, the ceiling, the leaf
           "    hex.zero 4, mm_ox16", "    hex.mov 4, mm_ox16 + 4*dw, mm_x",
           "    hex.zero 4, mm_oy16", "    hex.mov 4, mm_oy16 + 4*dw, mm_y"]
    for j, (slot, axis, coord, lo, hi) in enumerate(lift_trigs):
        out += _crossed_lines("sktl%d" % j, axis, coord, lo, hi, SOUL_R,
                              ["    hex.set 1, lreq + %d*dw, 1" % slot], regs=("mm_ox16", "mm_oy16", "cpx", "cpy"))
    out += list(teleport)                                                     # M8 soultele: EV_Teleport
    out += ["    hex.mov 4, mm_x, mm_nx", "    hex.mov 4, mm_y, mm_ny",
            "    hex.mov 8, mm_z, cp_floor",
            "    hex.mov 8, sw_c, cp_ceil",
            "    hex.zero w/4, kb_lf", "    hex.mov 3, kb_lf, ptss",
            "    hex.cmp 3, kb_lf, mm_leafw, skt_rl, skt_fr, skt_rl",
            "  skt_rl:",                                                          # a new leaf: out, in, its sector
            "    hex.mov w/4, pw_t, mm_tw", "    hex.mov w/4, pw_leaf, mm_leafw",
            "    stl.fcall pw_unlink, pw_ulret",
            "    hex.mov w/4, mm_leafw, kb_lf",
            "    hex.mov w/4, pw_t, mm_tw", "    hex.mov w/4, pw_leaf, mm_leafw",
            "    stl.fcall pw_link, pw_lkret",
            "    lfsec.lookup mm_sec, mm_leafw",
            "  skt_fr:",                                                          # the position, its fraction too
            "    hex.mov 8, kb_px, kb_cx", "    hex.mov 8, kb_py, kb_cy",
            "    stl.fret kb_tyret",
            "  skt_no:",
            "    hex.zero 1, kb_ok",
            "    stl.fret kb_tyret"]
    return out


def hts_lines() -> List[str]:
    """`sk_hts` (stl.fcall sk_hts, sk_htret): P_TryMove's heights for a soul (lostsoul.soul_lines_try) -- in cp_ok,
    cp_floor, cp_ceil (map units), sl_z (16.16), sl_h (map units); out mv_ok, sk_fok"""
    return ["sk_hts:",
            "    hex.zero 1, mv_ok", "    hex.zero 1, sk_fok",
            "    hex.if0 1, cp_ok, skh_o",
            "    hex.mov 8, sk_t, cp_ceil", "    hex.sub 8, sk_t, cp_floor",          # the opening holds it
            "    hex.scmp 8, sk_t, sl_h, skh_o, skh_1, skh_1",
            "  skh_1:",
            "    hex.set 1, sk_fok, 1",
            *_hi16("sk_t", "cp_ceil"), "    hex.sub 8, sk_t, sl_z",              # ceilz - z < height: lower itself
            *_hi16("sk_c", "sl_h"),
            "    hex.scmp 8, sk_t, sk_c, skh_o, skh_2, skh_2",
            "  skh_2:",
            *_hi16("sk_t", "cp_floor"), "    hex.sub 8, sk_t, sl_z",             # floorz - z > 24: too big a step
            "    hex.set 8, sk_c, %d" % STEP16,
            "    hex.scmp 8, sk_t, sk_c, skh_ok, skh_ok, skh_o",
            "  skh_ok:",
            "    hex.set 1, mv_ok, 1",
            "  skh_o:",
            "    stl.fret sk_htret"]


def _box(tag: str, x, y, bd: str, hit: List[str]) -> List[str]:
    """|x - mm_nx| < bd and |y - mm_ny| < bd (whole units, signed, strict) -> `hit` lines, else on to <tag>_n.
    `x` / `y`: a 4-nibble cell, or an int (a constant position)"""
    out = []
    for ax, v, cand in (("x", x, "mm_nx"), ("y", y, "mm_ny")):
        if isinstance(v, int):
            out += ["    hex.mov 4, sk_a, %s" % cand, "    hex.sub_constant 4, sk_a, %d" % (v & 0xFFFF)]
        else:
            out += ["    hex.mov 4, sk_a, %s" % v, "    hex.sub 4, sk_a, %s" % cand]
        out += ["    hex.abs 4, sk_a",
                "    hex.scmp 4, sk_a, %s, %s_%s, %s_n, %s_n" % (bd, tag, ax, tag, tag), "  %s_%s:" % (tag, ax)]
    return out + hit + ["  %s_n:" % tag]


def slam_lines(w, slot_rt: Sequence[int], *, pick_slots=None, drop_rt=None, var=()) -> List[str]:
    """`sk_slam` (stl.fcall sk_slam, sk_slret): lostsoul.slam_thing at (mm_nx, mm_ny) -- sk_hit 0 none, 1 a monster,
    2 the player, 3 a barrel, 4 a thing that takes no damage; sk_hj its index. The mover's own flags are clear.
    `pick_slots`: lootcode.pickup_slots' (the thvis slot of each pickup); `drop_rt[k]`: dropper k's row; `var`: the
    skill-dependent solid decorations (monstermove.static_blockers' -- their mc_don flags)"""
    from doomfj.combat import BARREL_R, ITEM_RADIUS
    from doomfj.barrelcode import droppers
    bd = {16: "sk_b32", 20: "sk_b36", 30: "sk_b46"}
    assert BARREL_R + SOUL_R == 26 and ITEM_RADIUS + SOUL_R == 36
    sn = _sn(w)                                         # M8 C2: sk_hj's width
    out = ["sk_slam:", "    hex.zero 1, sk_hit", "    hex.zero %d, sk_hj" % sn]

    def hit(kind, idx):
        return ["    hex.set 1, sk_hit, %d" % kind, "    hex.set %d, sk_hj, %d" % (sn, idx), "    ;sk_sl_o"]
    for j in range(w.layout.nmon):
        t, r = slot_rt[j], w.mon_radius[j]
        tag = "skm%d" % j
        out += ["    hex.if1 1, mon_solid + %d*dw, %s_t" % (j, tag), "    hex.if0 1, mon_shootable + %d*dw, %s_n" % (j, tag),
                "  %s_t:" % tag]
        out += _box(tag, "thpos_rt + %d*dw" % (16 * t + 4), "thpos_rt + %d*dw" % (16 * t + 12), bd[r], hit(1, j))
    # the player, alive, 16.16 (cpx / cpy hold the candidate << 16)
    out += ["    hex.if1 1, p_dead, skp_n", "    hex.sign 3, p_hp, skp_n, skp_a", "  skp_a:", "    hex.if0 3, p_hp, skp_n"]
    for ax, reg, c in (("x", "viewx", "cpx"), ("y", "viewy", "cpy")):
        out += ["    hex.mov 8, sk_t, %s" % reg, "    hex.sub 8, sk_t, %s" % c, "    hex.abs 8, sk_t",
                "    hex.scmp 8, sk_t, sk_bp, skp_%s, skp_n, skp_n" % ax, "  skp_%s:" % ax]
    out += hit(2, 0) + ["  skp_n:"]
    for b, t in enumerate(w.barrel_things):
        tag = "skb%d" % b
        out += ["    hex.if0 1, bar_solid + %d*dw, %s_n" % (b, tag)]
        out += _box(tag, t.x, t.y, "sk_b26", hit(3, b))
    for i, t in enumerate(w.decor_solid):
        tag = "skd%d" % i
        r = gd.THING_TYPES[t.type].radius + SOUL_R
        if i in var:
            out += ["    hex.if0 1, mc_don + %d*dw, %s_n" % (list(var).index(i), tag)]
        out += ["    hex.set 4, sk_d3, %d" % r]
        out += _box(tag, t.x, t.y, "sk_d3", hit(4, i))
    for i, t in enumerate(w.pickup_things):
        tag = "skq%d" % i
        out += ["    hex.if0 1, thvis + %d*2*dw, %s_n" % (pick_slots["slot"][i], tag)]
        if gd.THING_TYPES[t.type].radius + SOUL_R == 36:
            bdr = "sk_b36"
        else:
            out += ["    hex.set 4, sk_d3, %d" % (gd.THING_TYPES[t.type].radius + SOUL_R)]
            bdr = "sk_d3"
        out += _box(tag, t.x, t.y, bdr, hit(4, i))
    for k, m in enumerate(droppers(w) if drop_rt is not None else ()):
        tag = "skr%d" % k
        d = drop_rt[k]
        out += ["    hex.if_flags mdrop + %d*dw, %d, %s_n, %s_t" % (k, 1 << 1, tag, tag), "  %s_t:" % tag]
        out += _box(tag, "thpos_rt + %d*dw" % (16 * d + 4), "thpos_rt + %d*dw" % (16 * d + 12), "sk_b36", hit(4, k))
    return out + ["  sk_sl_o:", "    stl.fret sk_slret"]


def hitgo_lines(nmon: int, knock: bool = True, sn: int = 2) -> List[str]:
    """`sk_hitgo` (stl.fcall sk_hitgo, sk_hret): the slam -- P_Random on the soul's stream (sw_rng), the claw's table
    (`trclaw`: ((v % 8) + 1) * 3), and P_DamageMobj(the thing, the soul, the soul): a monster or a barrel through
    dm_go in its MONSTER mode (no reach, no blood; dm_src the soul's code), the player through dp_go. M8 C2: `sn`
    (world.slot_nibbles) -- the ids and codes"""
    from doomfj.damagecode import MONSTER
    from doomfj.knockcode import inflictor_lines
    kb = inflictor_lines("mm_x", "mm_y", z="sw_z + 4*dw") if knock else []
    return ["sk_hitgo:",
            "    hex.inc 2, sw_rng", "    trclaw.lookup dp_dmg, sw_rng",
            "    hex.switch sk_hit, skg_o, skg_mon, skg_pl, skg_bar, %s" % ", ".join(["skg_o"] * 12),
            "  skg_mon:",
            "    hex.mov 2, dm_dmg, dp_dmg", "    hex.set 1, dm_melee, %d" % MONSTER,
            "    hex.mov %d, dm_src, sw_me" % sn,
            "    hex.mov %d, dm_id, sk_hj" % sn, "    hex.inc %d, dm_id" % sn,         # dm_go's id: 1 + the slot
            *kb,
            "    stl.fcall dm_go, dm_ret",
            "    ;skg_o",
            "  skg_bar:",
            "    hex.mov 2, dm_dmg, dp_dmg", "    hex.set 1, dm_melee, %d" % MONSTER,
            "    hex.mov %d, dm_src, sw_me" % sn,
            "    hex.set %d, dm_id, %d" % (sn, 1 + nmon), "    hex.add %d, dm_id, sk_hj" % sn,  # 1 + nmon + the barrel
            "    stl.fcall dm_go, dm_ret",
            "    ;skg_o",
            "  skg_pl:",
            "    hex.mov %d, dp_src, sw_id" % sn,                                        # the attacker: 1 + the slot
            *kb,
            "    stl.fcall dp_go, dp_ret",
            "  skg_o:",
            "    stl.fret sk_hret"]


# ---- P_ZMovement ---------------------------------------------------------------------------------------------------
def z_stub_lines(w, m: int, rt: int) -> List[str]:
    """`skz<k>` (stl.fcall skz<k>, skz_ret): z != floorz << 16 or momz != 0 -> its window, `sk_zm`, back"""
    c = _slot_cells(w, m)
    L = "skz%d" % c["k"]
    return ["%s:" % L,
            "    hex.if1 8, %s, %s_go" % (c["mz"], L),
            *_hi16("sz_f", c["fz"]),
            "    hex.cmp 8, %s, sz_f, %s_go, %s_o, %s_go" % (c["z"], L, L, L),
            "  %s_go:" % L,
            "    hex.mov 8, sz_z, %s" % c["z"], "    hex.mov 8, sz_mz, %s" % c["mz"],
            *_hi16("sz_c", c["c"]), *_hi16("sz_f", c["fz"]),
            "    hex.mov 1, sz_fly, %s" % c["fly"], "    hex.mov 1, sz_inf, %s" % c["inf"],
            "    hex.mov 1, sz_live, %s" % c["sh"], "    hex.mov %d, sz_tg, %s" % (_sn(w), c["tg"]),
            "    hex.mov 4, sz_x, %s" % c["fx"], "    hex.mov 4, sz_x + 4*dw, thpos_rt + %d*dw" % (16 * rt + 4),
            "    hex.mov 4, sz_y, %s" % c["fy"], "    hex.mov 4, sz_y + 4*dw, thpos_rt + %d*dw" % (16 * rt + 12),
            "    stl.fcall sk_zm, sk_zret",
            "    hex.mov 8, %s, sz_z" % c["z"], "    hex.mov 8, %s, sz_mz" % c["mz"],
            "  %s_o:" % L,
            "    stl.fret skz_ret"]


def ap_lines() -> List[str]:
    """`sk_ap` (stl.fcall sk_ap, sk_apret): sk_d = P_AproxDistance(sk_dx, sk_dy), 8 nibbles (16.16)"""
    return ["sk_ap:",
            "    hex.abs 8, sk_dx", "    hex.abs 8, sk_dy",
            "    hex.cmp 8, sk_dx, sk_dy, ska_xl, ska_xg, ska_xg",
            "  ska_xl:", "    hex.mov 8, sk_d, sk_dx", "    ;ska_h",
            "  ska_xg:", "    hex.mov 8, sk_d, sk_dy",
            "  ska_h:",
            "    hex.shr_bit 8, sk_d",                                    # min >> 1
            "    hex.mov 8, sk_d3, sk_dx", "    hex.add 8, sk_d3, sk_dy", "    hex.sub 8, sk_d3, sk_d",
            "    hex.mov 8, sk_d, sk_d3",
            "    stl.fret sk_apret"]


def _target_z(dst: str, tag: str) -> List[str]:
    """dst[:8] = the loaded target's z, 16.16 (after mt_load): the player's check_position floorz (kb_pz), else mt_tz"""
    return ["    hex.if0 1, mt_pl, %s_m" % tag,
            "    stl.fcall kb_pz, kb_pzret", *_hi16(dst, "kb_pzv"), "    ;%s_d" % tag,
            "  %s_m:" % tag, "    hex.mov 8, %s, mt_tz" % dst,
            "  %s_d:" % tag]


def zm_lines(sn: int = 2) -> List[str]:
    """`sk_zm` (stl.fcall sk_zm, sk_zret): P_ZMovement on the z window (lostsoul._soul_z_move). M8 C2: sz_tg / mm_tg
    are `sn` nibbles"""
    return ["sk_zm:",
            "    hex.add 8, sz_z, sz_mz",
            "    hex.if0 1, sz_live, szm_fl", "    hex.if0 %d, sz_tg, szm_fl" % sn,
            "    hex.if1 1, sz_fly, szm_fl", "    hex.if1 1, sz_inf, szm_fl",
            # the float toward the target: dist (16.16 positions), delta = tz + 28 - z
            "    hex.mov %d, mm_tg, sz_tg" % sn, "    stl.fcall mt_load, mt_lret",
            *_target_z("sz_tz", "szt"),
            "    hex.add_constant 8, sz_tz, %d" % (SOUL_HALF << 16), "    hex.sub 8, sz_tz, sz_z",
            "    hex.mov 8, sk_dx, sz_x", "    hex.sub 8, sk_dx, mt_tqx",
            "    hex.mov 8, sk_dy, sz_y", "    hex.sub 8, sk_dy, mt_tqy",
            "    stl.fcall sk_ap, sk_apret",
            "    hex.mov 8, sz_t, sz_tz", "    hex.add 8, sz_t, sz_tz", "    hex.add 8, sz_t, sz_tz",   # 3 delta
            "    hex.sign 8, sz_tz, szm_dn, szm_dp",
            "  szm_dn:",                                                          # delta < 0: dist < -3 delta
            "    hex.neg 8, sz_t",
            "    hex.scmp 8, sk_d, sz_t, szm_down, szm_fl, szm_fl",
            "  szm_down:", "    hex.add_constant 8, sz_z, %d" % (-FLOAT16 & M32), "    ;szm_fl",
            "  szm_dp:",
            "    hex.if0 8, sz_tz, szm_fl",                                       # delta > 0: dist < 3 delta
            "    hex.scmp 8, sk_d, sz_t, szm_up, szm_fl, szm_fl",
            "  szm_up:", "    hex.add_constant 8, sz_z, %d" % FLOAT16,
            # the floor: the Ultimate bounce, then momz < 0 -> 0, z = floorz
            "  szm_fl:",
            "    hex.scmp 8, sz_z, sz_f, szm_hf, szm_hf, szm_ce",
            "  szm_hf:",
            "    hex.if0 1, sz_fly, szm_hf2", "    hex.neg 8, sz_mz",
            "  szm_hf2:",
            "    hex.sign 8, sz_mz, szm_hf3, szm_hf4",
            "  szm_hf3:", "    hex.zero 8, sz_mz",
            "  szm_hf4:", "    hex.mov 8, sz_z, sz_f",
            # the ceiling: z + height > ceilz
            "  szm_ce:",
            "    hex.set 8, sz_h, %d" % (SOUL_H << 16),
            "    hex.if1 1, sz_live, szm_ch", "    hex.set 8, sz_h, %d" % (CORPSE_H << 16),
            "  szm_ch:",
            "    hex.mov 8, sz_t, sz_z", "    hex.add 8, sz_t, sz_h",
            "    hex.scmp 8, sz_t, sz_c, szm_o, szm_o, szm_hc",
            "  szm_hc:",
            "    hex.sign 8, sz_mz, szm_hc2, szm_hc1",
            "  szm_hc1:", "    hex.zero 8, sz_mz",                              # momz > 0 (or 0): 0
            "  szm_hc2:",
            "    hex.mov 8, sz_z, sz_c", "    hex.sub 8, sz_z, sz_h",
            "    hex.if0 1, sz_fly, szm_o", "    hex.neg 8, sz_mz",
            "  szm_o:",
            "    stl.fret sk_zret"]


# ---- A_SkullAttack -------------------------------------------------------------------------------------------------
def charge_lines() -> List[str]:
    """`sk_charge` (stl.fcall sk_charge, sk_cret): the charge (lostsoul._a_skull_attack after A_FaceTarget) -- in
    mm_x / mm_y (the soul's whole units), mt_tq (mt_load ran), mt_pl / mt_tz, sc_z (its z); out sc_mx, sc_my, sc_mz"""
    from doomfj.projcode import _times20
    return ["sk_charge:",
            *_hi16("ia_x1", "mm_x"), *_hi16("ia_y1", "mm_y"),
            "    hex.mov 8, ia_x2, mt_tqx", "    hex.mov 8, ia_y2, mt_tqy",
            "    stl.fcall ia_leaf, ia_ret",
            "    hex.mov 3, sc_idx, ia_ang + 5*dw",                           # the fine angle: angle >> 20
            "    finesine.read_cos sc_mx, sc_idx", *[ln.replace("pw_c", "sc_a") for ln in _times20("sc_mx")],
            "    finesine.read_sin sc_my, sc_idx", *[ln.replace("pw_c", "sc_a") for ln in _times20("sc_my")],
            # dist = P_AproxDistance(dest - actor) / SKULLSPEED, at least 1
            "    hex.mov 8, sk_dx, ia_x2", "    hex.sub 8, sk_dx, ia_x1",
            "    hex.mov 8, sk_dy, ia_y2", "    hex.sub 8, sk_dy, ia_y1",
            "    stl.fcall sk_ap, sk_apret",
            "    hex.mov 4, sc_dn, sk_d + 4*dw",                               # >> 16, then / 20
            "    hex.div 4, 2, sc_q, sc_r, sc_dn, sc_20, skc_d0",
            "  skc_d0:",
            "    hex.if1 4, sc_q, skc_q",
            "    hex.set 4, sc_q, 1",
            "  skc_q:",
            # momz = (tz + 28 << 16 - z) / dist, truncated toward zero
            *_target_z("sc_a", "skct"),
            "    hex.add_constant 8, sc_a, %d" % (TARGET_HALF << 16), "    hex.sub 8, sc_a, sc_z",
            "    hex.zero 1, sc_neg",
            "    hex.sign 8, sc_a, skc_n, skc_p",
            "  skc_n:", "    hex.set 1, sc_neg, 1", "    hex.neg 8, sc_a",
            "  skc_p:",
            "    hex.div 8, 4, sc_mz, sc_r8, sc_a, sc_q, skc_d1",
            "  skc_d1:",
            "    hex.if0 1, sc_neg, skc_o", "    hex.neg 8, sc_mz",
            "  skc_o:",
            "    stl.fret sk_cret"]


def attack_slot_lines(w, m: int, rt: int, *, L: str, nxt: str, hear: bool) -> List[str]:
    """the slot's A_SkullAttack (its action label `<L>k_A_SkullAttack`): no target -> nothing; mt_load; A_FaceTarget
    (the ambush flag, mm_octant's facing); the charge (`sk_charge`): fly 1, the momentum (kb_live kept), momz"""
    from doomfj.monstercode import cell_nibbles
    c = _slot_cells(w, m)
    ntg = cell_nibbles(w.schema, "mon_target")
    FA = "mon_facing + %d*dw" % (cell_nibbles(w.schema, "mon_facing") * m)
    A = "%ssk" % L
    return ["  %sk_A_SkullAttack:" % L,
            "    hex.if0 %d, %s, %s" % (ntg, c["tg"], nxt),
            "    hex.mov %d, mm_tg, %s" % (ntg, c["tg"]), "    stl.fcall mt_load, mt_lret",
            *(["    hex.zero 1, mon_ambush + %d*dw" % m] if hear else []),
            "    hex.mov 4, mm_x, thpos_rt + %d*dw" % (16 * rt + 4),
            "    hex.mov 4, mm_y, thpos_rt + %d*dw" % (16 * rt + 12),
            "    stl.fcall mm_todist, mm_tdret", "    stl.fcall mm_octant, mm_ocret",
            "    hex.mov 1, %s, mm_fa" % FA,
            "    hex.mov 8, sc_z, %s" % c["z"],
            "    stl.fcall sk_charge, sk_cret",
            "    hex.set 1, %s, 1" % c["fly"],
            "    hex.zero 1, sc_was",
            "    hex.if1 8, %s, %s_w1" % (c["mx"], A), "    hex.if0 8, %s, %s_w0" % (c["my"], A),
            "  %s_w1:" % A, "    hex.set 1, sc_was, 1",
            "  %s_w0:" % A,
            "    hex.mov 8, %s, sc_mx" % c["mx"], "    hex.mov 8, %s, sc_my" % c["my"],
            "    hex.mov 8, %s, sc_mz" % c["mz"],
            "    hex.if1 8, sc_mx, %s_nz" % A, "    hex.if1 8, sc_my, %s_nz" % A,
            "    hex.if0 1, sc_was, %s" % nxt, "    hex.dec %d, kb_live" % _sn(w), "    ;%s" % nxt,
            "  %s_nz:" % A,
            "    hex.if1 1, sc_was, %s" % nxt, "    hex.inc %d, kb_live" % _sn(w), "    ;%s" % nxt]


# ---- the slot code's other soul lines (monstercode.p32a_slot) -------------------------------------------------------
def splice_lines(w, m: int, *, L: str, spawn: int, spawn_tics: int, ns: int, nt: int) -> List[str]:
    """the slot's thinker splice for a soul (in place of the knock splice): XY, then the spawn state its slam or stop
    set -- whose A_Look runs now (the look's exits return here, `sk_lr`) -- then P_ZMovement"""
    k = w.soul_of[m]
    ST, TI = "mon_state + %d*dw" % (ns * m), "mon_tics + %d*dw" % (nt * m)
    return ["    stl.fcall sks%d, sks_ret" % k,
            "    hex.if0 1, sk_lk, %sskz" % L,
            "    hex.set %d, %s, %d" % (ns, ST, spawn), "    hex.set %d, %s, %d" % (nt, TI, spawn_tics),
            "    hex.set 1, sk_lr, 1",
            "    ;%slook" % L,
            "  %slkret:" % L,
            "    hex.zero 1, sk_lr",
            "  %sskz:" % L,
            "    stl.fcall skz%d, skz_ret" % k]


def look_exit_lines(*, L: str, nxt: str) -> List[str]:
    """a soul slot's look exits through here: back to the splice after a slam's spawn state, else to the next slot"""
    return ["  %slkx:" % L, "    hex.if1 1, sk_lr, %slkret" % L, "    ;%s" % nxt]


def remove_lines(w, m: int, rt: int, *, L: str, nxt: str) -> List[str]:
    """P_RemoveMobj at the S_NULL its death states end in: inactive, out of its leaf list (kb_live less a sliding
    corpse) -- the state and the tics stay (the model's `_set_state` returns before writing them)"""
    c = _slot_cells(w, m)
    return ["  %srm:" % L,
            "    hex.zero 1, mon_active + %d*dw" % m,
            "    hex.set w/4, pw_t, %d" % rt, "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, thss_rt + %d*dw" % (16 * rt),
            "    stl.fcall pw_unlink, pw_ulret",
            "    hex.if1 8, %s, %srml" % (c["mx"], L), "    hex.if0 8, %s, %s" % (c["my"], nxt),
            "  %srml:" % L, "    hex.dec %d, kb_live" % _sn(w),
            "    ;%s" % nxt]


def change_sector_lines(w, m: int) -> List[str]:
    """P_ChangeSector (monstercode.p32b_change_sector_lines, mcf_hit): a soul ON its floor moves with the lift -- before
    mon_floorz takes mcf_val"""
    c = _slot_cells(w, m)
    tag = "mcsk%d" % m
    return [*_hi16("sk_t", c["fz"]),
            "    hex.cmp 8, %s, sk_t, %s, %s_on, %s" % (c["z"], tag, tag, tag),
            "  %s_on:" % tag, *_hi16(c["z"], "mcf_val"),
            "  %s:" % tag]


def move_context_lines(w, m: int, back: bool) -> List[str]:
    """monstercode.p32b_move_lines on a map with souls: the soul context in (mm_sk, mm_skz, mm_ski, mm_skc, mm_r16) or
    back"""
    if m not in w.soul_of:
        return [] if back else ["    hex.zero 1, mm_sk", "    hex.zero 1, mm_r16"]
    c = _slot_cells(w, m)
    if back:
        return ["    hex.mov 8, %s, mm_skz" % c["z"], "    hex.mov 1, %s, mm_ski" % c["inf"],
                "    hex.mov 4, %s, mm_skc" % c["c"]]
    return ["    hex.set 1, mm_sk, 1", "    hex.set 1, mm_r16, 1",
            "    hex.mov 8, mm_skz, %s" % c["z"], "    hex.mov 1, mm_ski, %s" % c["inf"],
            "    hex.mov 4, mm_skc, %s" % c["c"]]


def move_try_lines(root: str) -> List[str]:
    """monstermove.move_leaf_lines on a map with souls: a soul's P_TryMove (the heights at its z: sk_hts) in place of
    sim.try_move_mon -- mv_ok and sk_fok (FLOATOK) for mm_refused"""
    return ["    hex.if0 1, mm_sk, mm_tmon",
            "    hex.mov 8, cp_drop, cp_seedf",
            "    sim.check_cells %s" % root,
            "    hex.mov 8, sl_z, mm_skz", "    hex.set 8, sl_h, %d" % SOUL_H,
            "    stl.fcall sk_hts, sk_htret",
            "    ;mm_tdone",
            "  mm_tmon:"]


def move_accept_lines() -> List[str]:
    """mm_move's accept for a soul: not floating, its ceiling the opening's (P_Move: `flags &= ~MF_INFLOAT`)"""
    return ["    hex.if0 1, mm_sk, mm_acc_n", "    hex.zero 1, mm_ski", "    hex.mov 4, mm_skc, cp_ceil",
            "  mm_acc_n:"]


def move_float_lines() -> List[str]:
    """mm_move's refusal for a soul with FLOATOK: P_Move's `must adjust height` -- z += 4 if z < tmfloorz else -4,
    floating, and the move counts as made"""
    return ["    hex.if0 1, mm_sk, mm_rfd", "    hex.if0 1, sk_fok, mm_rfd",
            *_hi16("sk_t", "cp_floor"),
            "    hex.scmp 8, mm_skz, sk_t, mm_fu, mm_fd, mm_fd",
            "  mm_fu:", "    hex.add_constant 8, mm_skz, %d" % FLOAT16, "    ;mm_fs",
            "  mm_fd:", "    hex.add_constant 8, mm_skz, %d" % (-FLOAT16 & M32),
            "  mm_fs:",
            "    hex.set 1, mm_ski, 1", "    hex.set 1, mm_ok, 1",
            "    ;mm_mv_out",
            "  mm_rfd:"]


def decide_range_lines() -> List[str]:
    """monsterdecide.decide_leaf_lines' roll for a soul (mm_sk): P_CheckMissileRange's `dist >>= 1` -- refuse exactly
    when v < 200 and d >= 2v + 194 (dist = (d - 64 - 128) >> 1, capped at 200; tests/host/test_lostsoul_model holds the
    identity on every d and v)"""
    from doomfj.world import MISSILE_BIAS, MISSILE_CAP, MISSILE_NOMELEE_BIAS
    b = MISSILE_BIAS + MISSILE_NOMELEE_BIAS
    return ["  mm_dc_sk:",
            "    hex.set 2, mo_c4, %d" % MISSILE_CAP,
            "    hex.cmp 2, mm_rr, mo_c4, mm_dc_sk1, mm_dc_yes, mm_dc_yes",
            "  mm_dc_sk1:",
            "    hex.zero 4, mo_t4", "    hex.mov 2, mo_t4, mm_rr", "    hex.shl_bit 4, mo_t4",
            "    hex.add_constant 4, mo_t4, %d" % (b + 2),
            "    hex.cmp 4, mt_d, mo_t4, mm_dc_yes, mm_dc_mv, mm_dc_mv"]


def select_lines(w, m: int) -> List[str]:
    """the row select's soul stub tail: the leaf's floor becomes the soul's z for its thing_load (the first soul of the
    leaf keeps the leaf's floor in sf_sv); `leaf_restore_lines` puts it back after"""
    k = w.soul_of[m]
    return ["    hex.if1 1, sf_d, thsk%d_k" % m,
            "    hex.mov 4, sf_sv, ss_flr", "    hex.set 1, sf_d, 1",
            "  thsk%d_k:" % m,
            "    hex.mov 4, ss_flr, sk_z + %d*dw" % (8 * k + 4)]


def leaf_restore_lines() -> List[str]:
    """thing_leaf's first lines on a map with souls: a soul's thing_load has read the swapped floor -- the leaf's back"""
    return ["    hex.if0 1, sf_d, thsk_r", "    hex.mov 4, ss_flr, sf_sv", "    hex.zero 1, sf_d", "  thsk_r:"]


def leaves(w, *, slot_rt, mon_root: str, lift_trigs=(), pick_slots=None, drop_rt=None, var=(),
           teleport: Sequence[str] = ()) -> List[str]:
    """every soul leaf, jumping over itself. M8 soultele: `teleport` -- sk_try's WR teleports
    (teleportcode.monster_lines(knock_ctx=True, soul="knock")); () on a map without one"""
    out = ["// M8 C8 (doomfj.soulcode): the lost souls' leaves", ";sk_end"]
    for k, m in enumerate(w.soul_slots):
        out += xy_stub_lines(w, m, slot_rt[m], tele=bool(teleport)) + z_stub_lines(w, m, slot_rt[m])
    sn = _sn(w)                                         # M8 C2: the slot ids' width
    out += (mmove_lines(sn) + try_lines(mon_root, lift_trigs, teleport) + hts_lines()
            + slam_lines(w, slot_rt, pick_slots=pick_slots, drop_rt=drop_rt, var=var)
            + hitgo_lines(w.layout.nmon, sn=sn)
            + ap_lines() + zm_lines(sn) + charge_lines())
    return out + ["sk_end:"]


def check_model_rules(w) -> None:
    """the emit-time asserts: the map's heights keep every 16.16 difference the leaves form in 32 bits; the soul is
    16 wide; MF_FLOAT and the charge's speed are the model's"""
    hs = [s.floor_h for s in w.secs] + [s.ceil_h for s in w.secs]
    assert max(abs(h) for h in hs) < 1 << 13, "a 16.16 height difference would overflow 32 bits"
    assert all(w.mon_radius[m] == SOUL_R for m in w.soul_slots)
