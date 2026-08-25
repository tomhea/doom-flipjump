"""M12rr — the SHARED runtime wall-renderer emitter. Extracted from the M12nn capstone test so the SHIPPED
`build_doom` binary and the byte-exact golden test emit the *same* renderer (R6 single-source) — every
space optimization (M12oo pass-2 trampoline, M12pp/qq xor_by + xor-involution walk) is baked into this one
emitter, so build_doom inherits them for free.

`emit_wall_renderer(wad, mapname, cfg)` returns the renderer `main` fj text; assemble it with the fixed
include set [fj_consts, fixed_point, present, projection, frame_render, <main>]. The viewpoint is read from
stdin at runtime (`vx vy va`, signed decimal) so ONE assembled binary renders any E1M1 viewpoint — exactly
the two-pass runtime renderer (B'): a runtime BSP-walk pass 1 fills the per-column param arrays, then the
unrolled pass 2 rasters them through the shared-compare trampoline.
"""
from __future__ import annotations

from pathlib import Path

from doomfj.lut_generator import (
    generate_dispatch_table_fj,
    generate_xtoviewangle_lut_fj, generate_finetangent_lut_fj, generate_trig_idioms_fj,
    generate_tantoangle_lut_fj, generate_viewangletox_lut_fj, generate_slopediv_recip_lut_fj,
    generate_slopediv_recip8_lut_fj,
    generate_yslope_lut_fj, generate_zlight_lut_fj, generate_distscale_lut_fj,
    generate_emit_dispatch_table_fj, generate_yslope_packed_lut_fj, generate_zlight_packed_lut_fj,
)
from doomfj.reference_model import (ANG90, ANGLE_TURN, FORWARD_MOVE, MAX_STEP,
                                    ML_BLOCKING, PLAYER_HEIGHT, PLAYER_RADIUS,
                                    spawn_state)
from doomfj.mapcompiler import build_blockmap
from doomfj.wireformat import (MAGIC as WIRE_MAGIC, STATE_CMD as WIRE_STATE_CMD,
                               THING_CMD as WIRE_THING_CMD,
                               KEY_FORWARD_MASK, KEY_BACK_MASK,
                               KEY_TURN_LEFT_MASK, KEY_TURN_RIGHT_MASK)
from doomfj.mapcompiler import (bake_bsp, _bsp_as_code, _bsp_descend_code, _bytes_stream,
                                NF_SUBSECTOR, seg_affine_coeffs, bbox_gate_boxes,
                                thing_live_subsectors,
                                assert_thing_live_survives_prune)
from doomfj.reference_model import (ReferenceModel, WALL_BG, WPX_RUN_CAP, STEP_FACE_BASE,
                                    SPRITE_HD_H, SPRITE_RUN_CAP_HD,
                                    DEG_SOFT_SCENERY, DEG_MINH2_SCENERY, DEG_SOFT_MON,
                                    DEG_MINH2_MON, DEG_SPRB_MINH, DEG_SLIVER_W,
                                    DEG_STACK_SCALE, DEG_PNEAR, DEG_DDA_FACES,
                                    DEG_LIP_SCALE, DEG_SPR_LOWRES_H, DEG_SPR_LOWRES_CAP,
                                    DEG_SPR_NEAR_TZ,
                                    DEG_SPR_MID_CAP,
                                    STEP_SEG_BUDGET, SPRITE_HEIGHT_BUCKETS, THING_BUDGET,
                                    MONSTER_BUDGET, MONSTER_TYPES, MIN_SPRITE_H,
                                    MIN_SPRITE_H_MONSTER, VANISHABLE_TYPES,
                                    SPRITE_MINZ, sprite_bucket, sprite_bucket_height,
                                    COLORMAP_LIGHTS, LIGHT_SHIFT, SLOPERANGE, build_scene)
from doomfj.texturecompiler import (compile_colormap, compile_palette, composite_texture,
                                    texture_texels, _texel_table, downscale_canvas,
                                    colormap_values, _index_nibbles, generate_colormap_packed_table_fj)
from doomfj.lut_generator import generate_bands_walk_fj, generate_w1r_walls_fj
from doomfj.tables import (sine_table, tantoangle_table, slopediv_recip8_table,
                           slopediv_recip_table, viewangletox_table, xtoviewangle_table)
from doomfj.config import PNEAR_SEG_BUDGET


NLJ = chr(10)   # newline constant for generated .fj text


def _pfx(mapname: str) -> str:
    """The BSP-as-code label prefix for a map (lowercased, flipjump-legal)."""
    return mapname.lower().replace("-", "_")


# ⚠ CR-2026-08 (TS-3/ST-7) — the sprite registers a BAKED thing's `hex.xor_by` block writes, in
# emission order with their declared widths. `sim.thing_pass` must clear every one of them at least
# this wide, because `hex.xor_by` is self-restoring ONLY from a zero register and the runtime
# `thing_load` leaves them holding the last thing. That correspondence spans two languages with no
# compiler between them; it shipped wrong once (25 px at (1869,479), 29 px at spawn). Both the
# emitter (which asserts it built from this) and `test_the_runtime_pass_clears_every_register_the_
# baked_block_xors` (which reads it) key off this tuple, so the lists cannot drift apart again.
# `sp_tzmax2` is present only when `deg`, `sp_base2` only when `DEG_SPR_NEAR_TZ`.
THING_XORBY_FIELDS = (("sp_x", 8), ("sp_y", 8), ("sp_z", 8), ("sp_left", 8), ("sp_w", 8),
                      ("sp_hh", 8), ("sp_tzmax", 8), ("sp_tzmax2", 8), ("sp_mon", 2),
                      ("sp_base", 4), ("sp_base2", 4), ("sp_dw", 2), ("sp_lt", 2))


def _seg_xorby_block(label, fields):
    """The shared per-seg constant block `label` (emitted ONCE, fcall'd twice per visible seg — SET then CLEAR). M12pp:
    replaces the per-seg baked `hex.set` (each pays an @-dispatch to zero a reg it overwrites) with `hex.xor_by`
    (no @), kept correct by xor-INVOLUTION self-zeroing. `fields` = list of (regname, width, value) PURE
    compile-time constants. Correct ONLY on a zero register, so the zero-init seg regs self-restore each call."""
    lines = [f"  {label}:"]
    for reg, wdt, val in fields:
        lines.append(f"    hex.xor_by {wdt}, {reg}, {val}")
    lines.append("    stl.fret xb_ret")
    return lines


def _seg_xorby_use(label, clear=True):
    """The SET / USE / CLEAR fcall sequence at the call site. `clear=False` drops the involution CLEAR (a TDD
    FAIL stub: seg regs accumulate across segs -> wrong values for every seg after the first)."""
    seq = [f"    stl.fcall {label}, xb_ret",      # SET  (0 -> vals)
           "    stl.fcall seg_pass1_leaf, seg_ret"]      # USE  (the leaf READS the seg regs)
    if clear:
        seq.append(f"    stl.fcall {label}, xb_ret")   # CLEAR (vals -> 0, the xor involution)
    return seq


_ABLATE_MODES = frozenset({"planes", "pass2", "pass1", "segstub", "xrstub", "wedgestub",
                           "tsprobe", "tsmark", "pnearprune", "pnearcol", "pnearwalk", "tsfull",
                           "emitnopair", "emitnowalk", "atantwice",
                           "slopetwice", "tabletwice", "noflush", "colstub",
                           "noprescan", "noproj", "projtwice", "scaletwice", "skyall",
                           "sprnoemit", "thingtwice"})

DW_BITS = 64                   # `dw` in address units at w=32 (2w), for baked dw-offsets
TS_ECAP = 24                   # M13-2S rung 3b: buffered REGIONS per column per side,
                               # 5 bytes each ([kind][arg:2][y1][yend]). Measured worst
                               # over 30 E1M1 viewpoints: 14 top / 10 bottom.
# CR-2026-08: flush_frame's ditto byte count is `5*entries` computed in a 2-NIBBLE register
# (stream_render.fj `hex.mul_const 2, cn, tn, 5`), which wraps silently past 255 -- so the
# cap must keep 5*(TS_ECAP+1) inside one byte. Raising TS_ECAP past 50 needs that register
# widened first.
assert 5 * (TS_ECAP + 1) <= 255, "TS_ECAP overflows flush_frame's 2-nibble ditto byte count"
MAX_BANDS = 64                    # M13pS2c: band-list slots/column/region. Bound: a monotone half-window's
                                  # zidx walk gives <=32 distinct zrow runs (zlight[lvl][zidx] is monotone in
                                  # zidx with values in [0,31]); a horizon-STRADDLING window (negative-viewz
                                  # areas) is built as TWO half-window walks appended -> <=64 entries.
BAND_STRIDE = MAX_BANDS * 3        # packed bytes per column per region (run-length, base, zrow each entry)


def _int_part_lines(dst, src, neg, pos):
    """M14-b: the walk's INTEGER map coord out of a 16.16 position -- `dst[0:4] = src[4:8]`, then
    sign-extend nibbles 4..9 so the 10-nibble two's complement the BSP side test reads is exactly
    what `hex.input_dec_int 10` used to produce for the same coordinate. It is an arithmetic shift,
    so it floors; the decimal wire's integer coordinate meant the same thing."""
    return [f"hex.zero 10, {dst}", f"hex.mov 4, {dst}, {src} + 4*dw",
            f"hex.sign 4, {dst}, {neg}, {pos}",
            f"{neg}:", f"hex.set 6, {dst} + 4*dw, 0xFFFFFF", f";{pos}", f"{pos}:"]


def _player_sim_lines(collide: bool = False) -> list:
    """M14-c — ONE TIC OF THE PLAYER SIM, in fj. The exact mirror of
    `ReferenceModel.step_sim`: turn first, then a collision-free move along the NEW angle.

        angle += ANGLE_TURN on turn_left, -= ANGLE_TURN on turn_right   (mod 2**32)
        move   = +FORWARD_MOVE on forward, -FORWARD_MOVE on back        (both -> 0, so no move)
        x += FixedMul(move, cos(angle));  y += FixedMul(move, sin(angle))

    Two things are worth stating because they are where a mirror would drift:
      * the angle is modular, so `-= ANGLE_TURN` is emitted as `+= (2**32 - ANGLE_TURN)` -- one
        primitive, and bit-identical to the oracle's `& 0xFFFFFFFF` subtract;
      * `fixed_mul_lo` is the cheap form of `fixed_mul`, documented bit-identical, and the operands
        are in the oracle's order (move first, trig second).

    The key byte's bits are tested with `hex.if_flags`, whose mask is a set of NIBBLE VALUES: bit 0
    set is the 8 odd nibbles (0xAAAA), bit 1 is 0xCCCC, bit 2 is 0xF0F0, bit 3 is 0xFF00. Only the
    LOW nibble is read, so only key bits 0..3 exist.
    """
    turn = ANGLE_TURN & 0xFFFFFFFF
    fwd = FORWARD_MOVE & 0xFFFFFFFF
    return [
        f"hex.if_flags pkeys, {KEY_TURN_LEFT_MASK:#06x}, simtl_no, simtl_yes",
        "simtl_yes:", f"hex.add_constant 8, viewangle, {turn:#x}",
        "simtl_no:",
        f"hex.if_flags pkeys, {KEY_TURN_RIGHT_MASK:#06x}, simtr_no, simtr_yes",
        "simtr_yes:", f"hex.add_constant 8, viewangle, {-ANGLE_TURN & 0xFFFFFFFF:#x}",
        "simtr_no:",
        "hex.zero 8, pmove",
        f"hex.if_flags pkeys, {KEY_FORWARD_MASK:#06x}, simfw_no, simfw_yes",
        "simfw_yes:", f"hex.add_constant 8, pmove, {fwd:#x}",
        "simfw_no:",
        f"hex.if_flags pkeys, {KEY_BACK_MASK:#06x}, simbk_no, simbk_yes",
        "simbk_yes:", f"hex.add_constant 8, pmove, {-FORWARD_MOVE & 0xFFFFFFFF:#x}",
        "simbk_no:",
        "hex.if0 8, pmove, simmv_done",          # neither key, or both: the oracle does not move
        # the finesine index is the BAM's top 12 bits (angle_shift = 32 - log2(TRIG_N) = 20 = 5
        # nibbles), exactly `read_sin`'s `(angle >> angle_shift) & (TRIG_N - 1)`
        "hex.mov 8, pangt, viewangle", "hex.shr_hex 8, 5, pangt", "hex.mov 3, pangi, pangt",
        "finesine.read_cos pmvc, pangi",
        "finesine.read_sin pmvs, pangi",
        "hex.fixed_mul_lo 8, 4, pmvdx, pmove, pmvc",
        "hex.fixed_mul_lo 8, 4, pmvdy, pmove, pmvs",
        # M14-d: with collision on the move is a REQUEST -- `move_with_collision_lines` decides
        # where it actually lands. Without it the delta is applied straight, as M14-c shipped.
        *(["hex.mov 8, cm_dx, pmvdx", "hex.mov 8, cm_dy, pmvdy", ";simcollide"] if collide else
          ["hex.add 8, viewx, pmvdx", "hex.add 8, viewy, pmvdy"]),
        "simmv_done:",
    ]


def _state_wire_lines(state_wire: str, *, sim: bool = False, collide: bool = False) -> list:
    """The fj that reads one frame's world state (and, on the bin wire, echoes it back).

    Lives at module level so `tests/fj/test_state_wire.py` can assemble THE SAME TEXT in a
    seconds-long program instead of debugging it inside a 20-minute renderer build.

    "dec" is the historical wire: three decimals, position in whole map units.
    "bin" is M14's (doomfj.wireformat): a MAGIC byte, 16.16 x/y, a BAM angle and a key byte, with
    vx/vy derived from the position rather than the other way round. At an integer viewpoint both
    leave viewx/viewy/vx/vy holding identical bits -- which is what makes a bin frame byte-identical
    to a dec frame, and is what `scratchpad/m14_gate.py` gates."""
    if state_wire != "bin":
        assert not sim, "the player sim needs the bin wire (there is no key byte on the dec wire)"
        assert not collide, "collision rides the player sim, which needs the bin wire"
        return ["hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",
                "hex.input_dec_uint 8, viewangle, bad",
                "hex.mov 8, viewx, vx", "hex.shl_hex 8, 4, viewx",
                "hex.mov 8, viewy, vy", "hex.shl_hex 8, 4, viewy"]
    # MAGIC first: a junk feed must still reach `bad:` and halt, or the R0 build gate (which feeds
    # one junk byte) would block reading the other 13 bytes and die on EOF instead of gating.
    return [
        "hex.input 1, wmagic",
        f"hex.if_flags wmagic + dw, 1<<0x{WIRE_MAGIC >> 4:X}, bad, wmagic_lo",
        "wmagic_lo:", f"hex.if_flags wmagic, 1<<0x{WIRE_MAGIC & 0xF:X}, bad, wmagic_ok",
        "wmagic_ok:",
        "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 4, viewangle",
        "hex.input 1, pkeys",
        # M14-c: the tic runs BEFORE anything is derived from the state and before the echo, so the
        # frame is rendered from the state the host will be handed back -- DOOM's P_Ticker then
        # R_RenderPlayerView, and the reason one run really is one tic.
        *(_player_sim_lines(collide) if sim else []),
        *_int_part_lines("vx", "viewx", "vxsx", "vxdone"),
        *_int_part_lines("vy", "viewy", "vysx", "vydone"),
        # ... and the state goes straight back out, so the host can relay it into the next frame
        # without recomputing anything: one command byte + three 4-byte words, ahead of the frame's
        # own records (the device reads it as an ordinary present command).
        f"stl.output_char {WIRE_STATE_CMD}",
        "stream.emit_bytes4 viewx", "stream.emit_bytes4 viewy", "stream.emit_bytes4 viewangle",
    ]


# M5 — how many `kb.poll` expansions one standalone frame runs. Each is its own expansion (a
# backward jump would re-enter dirtied cells; see src/fj/input.fj), a poll with no event costs a
# single input hex, and the device never EOFs on an idle poll — so this is a cheap upper bound on
# "key transitions in one frame", not a budget that can bind. A human cannot produce 8 transitions
# in a 200 ms frame; if one ever did, the extras are read on the NEXT frame, in order.
STANDALONE_POLLS = 8

# M5 — the standalone tier's own globals, in ONE place (R6): the emitter declares them and
# scratchpad/m5_setfile.py re-attaches them to the restore set at exactly these widths, so a vec
# widened here without re-running that fails the build instead of leaving half a register
# unrestored. `kbstat`/`kbcode` are ordinary write-before-read scratch; the four flags are the
# PERSISTED held-key state (build.STANDALONE_PERSIST).
STANDALONE_SCRATCH_DECLS = [
    "kbstat: hex.vec 1", "kbcode: hex.vec 2",
    "kb_f: hex.vec 1", "kb_b: hex.vec 1", "kb_l: hex.vec 1", "kb_r: hex.vec 1",
]


def _standalone_input_lines(collide: bool = False, polls: int = STANDALONE_POLLS) -> list:
    """M5 — the standalone tier's frame prologue, in place of `_state_wire_lines`.

    The hosted tier is handed the player's whole world state every frame and echoes the new one
    back. A standalone `.fjm` has neither side of that: it KEEPS `viewx`/`viewy`/`viewangle` across
    the M1 reset (they are excluded from the restore set — see `build_wall_renderer`) and learns
    what the player did from the keyboard device.

    ⚠ THE TIC IS THE SAME CODE. `_player_sim_lines` is spliced in unchanged, so the standalone
    binary's simulation is the one `scratchpad/m14_gate.py` certified byte-exact; only where
    `pkeys` comes from differs. The four `kb.*` flags are edge-driven and persistent ("this key is
    held"), and `pkeys` is rebuilt from them every frame — so `pkeys` itself is ordinary
    restore-set scratch, and only the four flags need to survive the reset.
    """
    return [
        f"rep({polls}, i) kb.poll kbstat, kbcode, kb_f, kb_b, kb_l, kb_r, bad",
        # the held flags -> the key byte the sim reads, in wireformat.py's bit order. `xor_by` on a
        # cell just zeroed IS a set, and is the cheapest primitive that does it.
        "hex.zero 2, pkeys",
        "hex.if0 1, kb_f, sa_nf", "hex.xor_by pkeys, 0x1", "sa_nf:",
        "hex.if0 1, kb_b, sa_nb", "hex.xor_by pkeys, 0x2", "sa_nb:",
        "hex.if0 1, kb_l, sa_nl", "hex.xor_by pkeys, 0x4", "sa_nl:",
        "hex.if0 1, kb_r, sa_nr", "hex.xor_by pkeys, 0x8", "sa_nr:",
        *_player_sim_lines(collide),
        *_int_part_lines("vx", "viewx", "vxsx", "vxdone"),
        *_int_part_lines("vy", "viewy", "vysx", "vydone"),
        # ... and NO echo. There is no host to relay the state, which is the whole point.
    ]


def _moving_thing_tables(rm, cmap, lds, sds, secs, map_wad, mapname, sprite_wad,
                         spr_base, spr_ldbase, spr_dw, spr_cls, *, deg: bool, spr_cache: dict,
                         keep=None):
    """M14-e — everything the runtime thing table needs, baked ONCE by thing index.

    The static path bakes one xor-involution block per (subsector, thing), which is only possible
    because a static thing's leaf is known at emit time. Here the leaf is a runtime answer, so the
    same constants bake by INDEX (`doomfj.things.thing_rows`) and the two fields that are properties
    of WHERE the thing stands -- `sp_z` and `sp_lt` -- come from two small per-subsector tables plus
    an add. See `doomfj.things` for the split and for the proof that it reproduces the baked
    constants exactly at every thing's spawn position.

    Returns `(tables, ptloc, decls, nthings, nss)` -- the baked point-location walk is CODE and is
    kept out of the data block for the same reason M14-d's seed descent is: it lives beside the BSP
    walk it mirrors, not inside the region `;__hot_end` jumps over.
    """
    from doomfj.collision import generate_point_location_fj, point_location_decls
    from doomfj.lut_generator import generate_packed_lut_fj
    from doomfj.things import (THING_ROW_COLD_BYTES, THING_ROW_COLD_LEN, THING_ROW_HOT_BYTES,
                               THING_ROW_HOT_LEN, cold_row, hot_row, reachable_lightnums,
                               sprite_light_table, subsector_tables, thing_rows)
    allt = map_wad.things(mapname)
    rows, idx = thing_rows(rm, allt, sprite_wad, spr_base, spr_ldbase, spr_dw, MONSTER_TYPES,
                           MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, DEG_MINH2_SCENERY, DEG_MINH2_MON,
                           deg=deg, spr_near=bool(DEG_SPR_NEAR_TZ), cache=spr_cache, keep=keep)
    things = [allt[i] for i in idx]
    ssflr, sslgt_raw = subsector_tables(rm, cmap, lds, sds, secs)
    lns = reachable_lightnums(rm, secs)
    lnpos = {ln: k for k, ln in enumerate(lns)}
    # a seg-less leaf has no sector and gets 0 -- nothing can bind to it (point location only ever
    # returns a leaf with geometry), so which row it names never matters
    sslgt = [lnpos.get(ln, 0) for ln in sslgt_raw]
    sprlt = sprite_light_table(spr_cls, rows, lns)
    nt, nss = len(rows), len(cmap.subsectors)

    def _pack(vals, widths):
        out = shift = 0
        for v, nb in zip(vals, widths):
            out |= (v & ((1 << 8 * nb) - 1)) << shift
            shift += 8 * nb
        return out

    # ⚠ the position array is a hex.vec (one NIBBLE per slot), NOT a packed table (one BYTE per
    # slot): the wire writes it with `hex.input 8` and sim reads it with ptr_index + read_hex 16.
    # Emitting it as a packed LUT would put the strides a factor of 2 apart -- see handoff-m14 5.
    thpos = ["thpos_rt:"] + [f"    hex.vec 16, {(((t.y << 16) & 0xFFFFFFFF) << 32) | ((t.x << 16) & 0xFFFFFFFF)}"
                             for t in things]
    text = "\n".join([
        # M14-perf: HOT (everything a reject can reach) and COLD (what only a drawn sprite needs).
        # See doomfj.things -- 94.1% of loads are rejected, and read_table_packed is linear in the
        # row width, so the cold half is now read only by the 5.9% that survive.
        generate_packed_lut_fj("throw", [_pack(hot_row(r), THING_ROW_HOT_BYTES) for r in rows],
                               THING_ROW_HOT_LEN),
        generate_packed_lut_fj("throwc", [_pack(cold_row(r), THING_ROW_COLD_BYTES) for r in rows],
                               THING_ROW_COLD_LEN),
        "\n".join(thpos),
        # ⚠ ssflr / sslgt / ltbase are NOT emitted any more: every one of them was indexed by the
        # SUBSECTOR, so the emitter knows the answer and `subsector_action` bakes it into the leaf.
        generate_packed_lut_fj("sprlt", sprlt, 1),
    ])
    # 0xFF is the empty/end sentinel of both linked-list arrays, so 251 things fit a byte index
    assert nt < 0xFF, f"{mapname} has {nt} drawable things; the byte linked list tops out at 254"
    decls = ["cur_ss: hex.vec w/4", "tp_ret: ;0",
             # the leaf's baked floor height and sprlt row base (see subsector_action)
             "ss_flr: hex.vec 4", "ss_ltb: hex.vec 4",
             # ⚠ a bare hex.vec is ZERO-filled, and one run is one frame -- fj self-modifies, so
             # the host reloads the pristine image every frame. That makes 0 a free-to-restore
             # EMPTY sentinel, which is why bind_things has no clear loop and why the lists hold
             # t+1 rather than t. Deleted ~1.65M ops/frame.
             *point_location_decls()]
    # lightnum -> the row base into `sprlt`, for the leaf to bake, and (M5) each runtime thing's
    # SPAWN leaf. The hosted tier is fed that binding every frame; a standalone build has no host,
    # nothing moves things (that is C4), so the same values bake and `bind_things` takes its
    # `clean` path for every thing and never runs point location.
    return (text, generate_point_location_fj(cmap), decls, nt, nss,
            {ln: k * nt for k, ln in enumerate(lns)},
            [rm.point_in_subsector(cmap, t.x, t.y) for t in things])


def emit_wall_renderer(map_wad, mapname, cfg, *, asset_wad=None, over_align=False,
                       ablate: frozenset = frozenset(), floor_mode: str = "textured",
                       wall_mode: str = "textured", raster_mode: str = "framebuffer",
                       plane_near: bool = False, two_sided: bool = False,
                       wall_noise: bool = False, sky: bool = False, steps: bool = False,
                       things: bool = False, sprite_wad=None,
                       bbox_cull: bool = False, stack_steps: bool = False,
                       deg: bool = False, state_wire: str = "dec",
                       player_sim: bool = False, collide: bool = False,
                       moving_things: bool = False, standalone: bool = False,
                       return_parts: bool = False):
    """Emit the full runtime wall+floor/ceiling renderer for `mapname` as the fj `main` text (everything after
    the fixed includes). Uses the optimized SHARED macros (pixel_tramp/compare_y wall trampoline, the
    xor_by-involution walk, and the M13c3 plane_tramp visplane raster), so this is the single source both
    `build_doom` and the golden test render through. The viewpoint `(vx,vy,va)` is read from stdin (signed
    decimal) at runtime. Geometry comes from `map_wad`; textures/colormap/palette/flats from `asset_wad`
    (defaults to `map_wad` — E1M1 is self-contained; the square-room test passes a separate asset wad).
    `over_align` pads dispatch tables to a 2^n boundary (test layout); pass False for the production
    (build_doom) layout.

    `ablate` (M13p0, measurement-only — NEVER set for build_doom/the golden tests) drops components so
    `scripts/measure_frame.py` can isolate their ops/frame cost by delta:
      - "planes"  — drop the floor/ceiling visplane pass (pass 2b) from the mainline.
      - "pass2"   — drop the wall raster (pass 2a, the per-column trampoline) from the mainline.
      - "pass1"   — skip the BSP-walk jump entirely (pass-1 never runs; col arrays stay zero-init),
                    isolating init/input-parse/present residue. Valid ONLY combined with "planes"+"pass2"
                    (ablating pass1 alone leaves pass2/planes rendering garbage zero-filled columns).
      - "segstub" — the per-seg leaf `stl.fret`s immediately (no full-flag check, no wall_x_range) =
                    the bare walk skeleton (node side tests + subsector dispatch + the SET/CLEAR xorby
                    call overhead), isolating the walk from every per-seg cost.
      - "xrstub"  — the per-seg leaf keeps the `full`-flag pre-check but replaces `wall_x_range` with an
                    immediate cull-fail (no atans, no cull math) = walk + per-seg entry overhead only.
    "segstub"/"xrstub" are mutually exclusive and independent of "planes"/"pass2"/"pass1".

    `floor_mode` (M13p1): "textured" (default, M13b/M13d2 perspective u,v floors) or "flat" (M13a/M13p1
    flat-colored floors — no per-span DDA seed, no per-pixel sample; `seg_ceilbase`/`seg_floorbase` bake
    the flat's 2-nibble BASE palette index instead of a 5-nibble combined-table slice offset, and the
    combined flat texel table is not emitted at all).

    `wall_mode` "WPX" (M13-WPX, the lines-mode SHIPPING tier) is different in kind: the wall texels
    never enter the combined table at all (it stays at the W1 tier — see `tex_mode`). Instead
    `_lines_wall_pix_bank` bakes a per-(texture,light) × per-exact-height RUN-LIST bank, giving one
    texture texel per screen pixel down each column for one add per colour run at runtime.

    `wall_mode` (M13p4a): "textured" (default, the real per-seg wall texture) or "W1"/"W2" — every wall
    texture is reduced to a tiny synthetic canvas (`ReferenceModel._tiny_wall_canvas`, the SAME helper
    the oracle uses, R6) before it enters the combined table: W1 = 1×1 (the mode texel), W2 = 1×16 (a
    vertical band strip). `column_render_params`/pass-2/`leaf_body_w` are UNCHANGED — they just sample a
    much smaller table (793,344 texels → tens-to-low-hundreds).

    `plane_near` (M13-2S rung 3a, lines mode only): attribute each column's floor/ceiling surface to
    the nearest MARKING seg -- two-sided included -- instead of to the one-sided wall that claims the
    column. That claiming wall is generally in another room, which is the owner's "the close floor in
    the middle is gray, yet the sides are yellow" bug (docs/handoff-m13-2s.md §2). Marking = DOOM's
    R_StoreWallRange markfloor/markceiling test: the two sides differ in the band-bank key
    (height, light, flat). It CHANGES rendered output, so it is opt-in: without it every tier renders
    byte-identically to before (the `pnear` compile-time flag emits none of the added ops and the bank
    keeps the old shared-key layout; the only residue is +4.7k ops/frame of address-layout tax from
    the added per-column arrays, measured on E1M1 spawn: 23,204,595 -> 23,209,289).

    `raster_mode` (M13pS2): "framebuffer" (default, the UNCHANGED pass-1/pass-2/plane-pass pipeline
    above) or "stream" — THE COLUMN-STREAM COMPOSITE. Pass-1 builds each claimed column's ceiling/
    floor packed-byte BAND LISTS (`plane.build_bands`, `src/fj/plane_bands.fj`) and bakes the W1
    wall's fully-constant lit BYTE (`seg_lit`, computed here at Python emit time from the real
    colormap — no runtime lookup needed), storing them in `col_ceil_bands`/`col_ceil_n`/
    `col_floor_bands`/`col_floor_n`/`col_lit`; then, instead of any framebuffer raster, the frame is
    EMITTED as the device run-stream (`present.begin_frame_stream` + an unrolled
    `rep(VIEW_W,x) stream.emit_column ...` — `src/fj/stream_render.fj`, which the assemble include
    list must therefore contain in this mode), decoded by `StreamScreen`. The framebuffer, the pass-2
    wall trampoline, and ALL plane-pass machinery (`render_planes_spans`/`draw_span*`/`clear_planes`)
    are NOT EMITTED in this mode; the `cm`-label table is the EMIT dispatch table (`cm.emit`, run
    colours) plus the `byte.emit` identity table, replacing `compile_colormap`'s `cm.apply` table
    (same label — they cannot coexist, and nothing calls `cm.apply` here). Requires `wall_mode="W1"`
    and `floor_mode="flat"` (the only combination pS2 targets — W2's per-band wall lighting and
    textured floors are out of scope). ⚠ every column must be CLAIMED by pass-1 (a closed level
    always does) — an unclaimed column would emit 0 of its VIEW_H rows and stall the device's
    pixel count."""
    assert ablate <= _ABLATE_MODES, f"unknown ablate mode(s): {ablate - _ABLATE_MODES}"
    assert not ({"segstub", "xrstub"} <= ablate), "segstub and xrstub are mutually exclusive"
    assert floor_mode in ("textured", "flat", "FT1"), f"unknown floor_mode: {floor_mode!r}"
    assert wall_mode in ("textured", "W1", "W2", "W2S", "WPX", "W1R"), \
        f"unknown wall_mode: {wall_mode!r}"
    # M13-WPX carries its real texels in its OWN per-height bank, so the shared combined table
    # (and `seg_lit`) stays at the W1 tier -- one mode texel per texture, not the 793k-texel one.
    # M13-W1R keeps its OWN tex_mode: same 1x1 canvas shape, but the BRIGHT-HALF mode texel
    # (`_w1r_texel`) so the colormap has headroom to randomize in dark sectors.
    tex_mode = "W1" if wall_mode == "WPX" else wall_mode
    assert raster_mode in ("framebuffer", "stream", "spans", "raster", "proj", "lines"), \
        f"unknown raster_mode: {raster_mode!r}"
    # M13-spanfill: "spans" shares the ENTIRE stream pipeline (pass-1 band lists + col_struct + the
    # planesproto band buffers) and differs ONLY in the final present_tail: instead of the 0x09
    # planes protocol (device does the per-column clip), it emits explicit fillCol spans over the 0x0A
    # dumb-screen protocol (fj does the clip, device just fills). `stream` gates the shared pipeline.
    stream = raster_mode in ("stream", "spans")
    # M13-raster: the DEVICE RASTERIZER. fj stays the brain (walk/occlusion/projection-setup); the
    # device does the per-column wall DDA + first-wins fill + distance-light shade from compact
    # per-seg/per-visplane records emitted INLINE during the walk (no col_struct/band-list buffering
    # at all -- see frame.seg_pass1_leaf_body_raster). Shares the "no framebuffer/pass2/planes,
    # cvp_ids/fvp_ids, until-full abort" plumbing with stream/spans (the `stream or raster` checks
    # below) but has its OWN present_tail/decls/leaf-body.
    raster = raster_mode == "raster"
    # M13-proj (Path B LAB MODE, NOT a shipped default): the device holds the whole static per-seg
    # geometry table (0x0E) and does the vertex->column projection itself; fj keeps the walk + the
    # wedge and back-face culls and emits a 2-byte compact seg id per survivor. Built behind this
    # flag per the bake-off precedent ("keep building ladder infra behind mode flags; only the final
    # default-flip needs the owner's pick") -- flipping any default remains the owner's call.
    projm = raster_mode == "proj"
    # M13-lines: the DUMB-DEVICE mode (owner ruling 2026-07-27: the device may only print explicit
    # lines/pixels). fj does EVERYTHING -- projection, per-column clip, occlusion, band boundaries,
    # colormap -- and emits raw fillCol [x][y1][y2][colour] records (the 0x0A spans protocol)
    # inline at column-claim time. No col_struct, no present-tail pass.
    lines = raster_mode == "lines"
    assert not plane_near or lines, "plane_near is a lines-mode tier (M13-2S rung 3a)"
    # M13-2S rung 3b: the TWO-SIDED renderer -- DOOM's R_RenderSegLoop window per column, upper
    # and lower wall runs, and one plane region per bounding SEG. It supersedes plane_near (whose
    # attribution it includes) and targets ReferenceModel.render_frame_2s.
    assert not two_sided or lines, "two_sided is a lines-mode tier (M13-2S rung 3b)"
    assert not (two_sided and plane_near), "two_sided already includes plane_near's attribution"
    plane_near = plane_near or two_sided
    # ablate "pnearcol" prices the emit half alone (per-column attribution OFF, the two-sided claim
    # walk still emitted); "pnearwalk" prices the walk alone (claim sites dropped, per-column ON).
    # Both render wrong on purpose -- measurement only.
    pnear_flag = 1 if (plane_near and "pnearcol" not in ablate) else 0
    # M13-EMIT rung 1 (measurement only): 1 = walk the baked band lists but emit no pairs (prices the
    # two byte.emit dispatches), 2 = skip the band walks entirely (prices the whole per-pair path:
    # two hex.read_byte_and_inc pointer reads + the loop + the dispatches). Renders wrong on purpose.
    eabl_flag = 2 if "emitnowalk" in ablate else (1 if "emitnopair" in ablate else 0)
    # M13-EMIT rung 3 (measurement only): run each seg's two vertex atans TWICE, the second time
    # into a dead register. Everything downstream stays bit-identical (the frames must still come
    # out byte-exact), so the delta IS the frame's point_to_angle cost.
    atan_dbl = 1 if "atantwice" in ablate else 0
    # ... and the same trick INSIDE point_to_angle_m, to split the atan into its two halves: the
    # slope divide vs the packed tantoangle LUT read (4 pointer byte-reads).
    slope_dbl = 1 if "slopetwice" in ablate else 0
    table_dbl = 1 if "tabletwice" in ablate else 0
    w2s_flag = 1 if wall_mode == "W2S" else 0   # M13-W2S tier select for the lines leaf
    wpx_flag = 1 if wall_mode == "WPX" else 0   # M13-WPX (1x1 vertical) tier select
    w1r_flag = 1 if wall_mode == "W1R" else 0   # M13-W1R (randomized runs) tier select
    deg_flag = 1 if deg else 0                  # 25M-CAP: load-adaptive degradation package
    if stream or raster or projm or lines:
        assert wall_mode in ("W1", "W2S", "WPX", "W1R") and floor_mode in ("flat", "FT1"), \
            "the run-stream modes support wall_mode='W1'/'W2S'/'WPX'/'W1R' + floor_mode='flat'/'FT1'"
        assert wall_mode == "W1" or lines, f"wall_mode={wall_mode!r} is a lines-mode tier"
        assert floor_mode != "FT1" or lines, "floor_mode='FT1' is a lines-mode tier"
    # M14-b: the state wire. "dec" is the historical three-decimals-on-stdin viewpoint; "bin" is the
    # M14 round-trip format (doomfj.wireformat) -- 16.16 position + BAM + key byte in, state back
    # out ahead of the frame. The echo goes out through `stream.emit_bytes4`, i.e. `byte.emit`,
    # which only the run-stream modes bake a table for.
    assert state_wire in ("dec", "bin"), f"state_wire={state_wire!r} is not 'dec' or 'bin'"
    assert state_wire == "dec" or (stream or raster or projm or lines), \
        "state_wire='bin' needs a run-stream mode (byte.emit's table is not baked for framebuffer)"
    # M14-e: the runtime thing table. Positions arrive on the wire after the player's state, so it
    # needs the binary wire; and there is nothing to re-bind unless sprites are being emitted.
    assert not moving_things or (things and lines), \
        "moving_things=True is the runtime thing table -- it needs things=True on the lines tier"
    assert not moving_things or state_wire == "bin", \
        "moving_things=True reads the position array off the binary wire (see wireformat.encode_things)"
    # M5 -- the STANDALONE tier: no host, so no wire in either direction. It keeps the view state
    # across the M1 reset and reads the keyboard device instead, which means the player sim is not
    # optional here: without it nothing would ever move and the keys would go nowhere.
    assert not standalone or player_sim, (
        "standalone=True needs player_sim=True -- the keyboard drives the sim, and nothing else "
        "moves the player")
    assert not standalone or state_wire == "bin", (
        "standalone=True shares the bin tier's registers (pkeys, the 16.16 view state); "
        "state_wire='dec' has neither")
    assert not standalone or lines, (
        "standalone=True presents 0x0B column run-lists, which is the lines tier")
    # the player start, which only the standalone tier bakes (see the view-state declaration)
    _spawn = spawn_state(map_wad, mapname) if standalone else None
    # `sim.thing_load` externs the full sprite register set, and an extern that has no global is an
    # assembler error -- so the two OPTIONAL registers must be present. Both are in the certified
    # tier; this refuses at emit time rather than 25 minutes into an assemble.
    assert not moving_things or (deg and DEG_SPR_NEAR_TZ), (
        "moving_things=True needs deg=True and DEG_SPR_NEAR_TZ: sim.thing_load loads sp_tzmax2 and "
        "sp_base2, which are only declared under those two flags")
    # M13-W1R rides V1's per-column grain group (`gnrow` via the wnoise lookup) and V1's ditto
    # comparison of it -- without the grain the pattern key does not exist at runtime.
    assert not w1r_flag or wall_noise, "wall_mode='W1R' requires wall_noise=True (V1's gnrow)"
    assert not (w1r_flag and two_sided), "wall_mode='W1R' is not wired into the two_sided leaf"
    # CR-2026-08: emit_region has NO rep(w2s) windowed wall emitter (stream_render.fj, the
    # 'KNOWN GAP' note): a sprite-fragmented column in a W2S build would emit no wall piece
    # and let the floor pairs paint the wall rows. Refuse the combination at build time.
    assert not (wall_mode == "W2S" and things), \
        "wall_mode='W2S' has no windowed wall emitter for sprite-fragmented columns (things=True)"
    # V5: stacked boundary pieces + per-boundary plane regions ride the V3 slot machinery and
    # the pnear pid bank -- both must be on.
    stack_flag = 1 if stack_steps else 0
    assert not stack_flag or (lines and steps and plane_near and not two_sided), \
        "stack_steps requires the lines tier with steps + plane_near (and not two_sided)"
    # V5 slot layout: 4-byte pieces [y1][y2][cls][bpid] at u1@0, u2@4, l1@8, l2@12 -- all four
    # fit the EXISTING 16-byte stride, so the whole-nibble shift stays.
    asset_wad = asset_wad or map_wad
    rm = ReferenceModel(cfg)                                  # REAL textures (no _wall_texture override)
    cmap = bake_bsp(map_wad, mapname)
    verts = cmap.vertexes
    lds = map_wad.linedefs(mapname); sds = map_wad.sidedefs(mapname); secs = map_wad.sectors(mapname)
    scene = build_scene(map_wad, asset_wad, mapname)
    colormap = scene.asset_wad.colormap()
    proj = cfg.PROJECTION << 16
    defs = {d.name.upper(): d for d in asset_wad.texture_defs("TEXTURE1")}

    def _ts_draws_wall_early(seg) -> bool:
        """_seg_draws_wall, needed by the texture/WPX bakes that run before it is defined."""
        ld_ = lds[seg.linedef]
        if ld_.back == -1:
            return False
        fs_ = secs[sds[ld_.front if seg.side == 0 else ld_.back].sector]
        bs_ = secs[sds[ld_.back if seg.side == 0 else ld_.front].sector]
        return fs_.ceil_h > bs_.ceil_h or bs_.floor_h > fs_.floor_h

    # the combined dispatch table over every distinct wall texture the one-sided segs use (downscaled to match
    # the oracle's _wall_texture), plus the 1x1 WALL_BG sentinel; per-seg texinfo precomputed via the oracle rule.
    cache = {}
    seg_texinfo = {}                                         # si -> (texbase, texheight, texwidth)
    names = set()
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back != -1 and not ("tsfull" in ablate and secs and _ts_draws_wall_early(seg)):
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        if rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=tex_mode) is not None:
            names.add(sd.middle.upper())
    combined, info = [], {}
    for nm in sorted(names) + [None]:
        key = nm if nm else "__WALLBG__"
        if nm is None:
            # W1R's canvas is TWO texels (t1 + the 2C alt), so the texture-less sentinel
            # matches its stride -- both texels the flat shade.
            th, tw, texels = (2, 1, [WALL_BG, WALL_BG]) if tex_mode == "W1R" else (1, 1, [WALL_BG])
        else:
            c = downscale_canvas(composite_texture(asset_wad, defs[nm]), rm.downscale)
            th, tw, texels = len(c), len(c[0]), texture_texels(c)
            if tex_mode != "textured":                         # M13p4a: shrink to the tiny synthetic canvas
                texels, th, tw = rm._tiny_wall_canvas(
                    texels, th, tex_mode,
                    pal=asset_wad.playpal() if tex_mode == "W1R" else None)
        while len(combined) % th != 0:                        # align the slice to its texheight (the OR-trick)
            combined.append(0)
        info[key] = (len(combined), th, tw)
        combined += texels
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back != -1 and not ("tsfull" in ablate and _ts_draws_wall_early(seg)):
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        t = rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=tex_mode)
        seg_texinfo[si] = info[sd.middle.upper()] if t is not None else info["__WALLBG__"]

    tex = _texel_table("tex", combined, "per_entry", over_align=over_align)

    # M13-proj: compact one-sided-seg ids (walk-independent, seg-index order) for the 2-byte wire
    # records + the device-resident geometry table (30 B/row packed bytes via _bytes_stream --
    # stream_screen.PROJ_ROW_BYTES must match this layout).
    proj_sid = {}
    proj_geom_txt = ""
    if projm:
        for si, seg in enumerate(cmap.segs):
            if lds[seg.linedef].back == -1:
                proj_sid[si] = len(proj_sid)

    # M13d2 — the combined FLAT texel table over every distinct ceil/floor flat the one-sided seg sectors use
    # (64x64 RAW, NO downscale; the `&63` wraps). Each flat gets a SLICE offset; the textured span pass samples
    # `flat[slice_offset + (v&63)*64 + (u&63)]`. Missing flats (e.g. the sky placeholder before M16) become a
    # uniform WALL_BG tile via _flat_texels — identical to the oracle. Per-seg bakes the ceil/floor slice offset.
    # M13p1: floor_mode="flat" bakes the flat's 2-nibble BASE palette index instead (M13a tier, `_flat_base`)
    # and skips the combined flat table entirely (not sampled by draw_span_flat).
    flat_texcache: dict = {}
    flat_basecache: dict = {}
    flat_slice: dict = {}
    flat_table = ""
    if floor_mode == "textured":
        flat_names = set()
        for si, seg in enumerate(cmap.segs):
            ld = lds[seg.linedef]
            if ld.back != -1:
                continue
            fsec = rm._seg_sector(lds, sds, secs, seg)
            flat_names.add(fsec.ceil_tex.upper()); flat_names.add(fsec.floor_tex.upper())
        flat_combined = []
        for nm in sorted(flat_names):
            flat_slice[nm] = len(flat_combined)
            flat_combined += list(rm._flat_texels(asset_wad, nm, flat_texcache))
        flat_table = _texel_table("flat", flat_combined, "per_entry", over_align=over_align)

    def _flatval(name: str) -> int:
        return (flat_slice[name.upper()] if floor_mode == "textured"
                else rm._flat_base(asset_wad, name, flat_basecache))
    # M13-proj: the device-resident geometry rows (needs _flatval, hence built here)
    if projm:
            rows = []
            for si in proj_sid:
                seg = cmap.segs[si]
                v1x, v1y = verts[seg.v1]
                v2x, v2y = verts[seg.v2]
                sa, sb, sc = seg_affine_coeffs(seg, verts)
                gsec = rm._seg_sector(lds, sds, secs, seg)
                gtb = seg_texinfo[si][0]
                rows.append((v1x & 0xFFFF, v1y & 0xFFFF, v2x & 0xFFFF, v2y & 0xFFFF, seg.angle,
                             sa, sb, sc, gsec.ceil_h & 0xFFFF, gsec.floor_h & 0xFFFF,
                             gsec.light & 0xFF,
                             colormap[max(0, min(COLORMAP_LIGHTS - 1, gsec.light >> LIGHT_SHIFT))][combined[gtb]],
                             _flatval(gsec.ceil_tex), _flatval(gsec.floor_tex)))
            proj_geom_txt = _bytes_stream("seg_geom", rows, (2, 2, 2, 2, 2, 4, 4, 4, 2, 2, 1, 1, 1, 1))

    if stream or lines:
        # M13pS2: nothing calls `cm.apply` in stream mode -- the `cm` label carries the EMIT dispatch
        # table instead (`cm.emit`, band-run colours; same flattened light<<8|colour values), plus the
        # `byte.emit` identity table (run counts + the baked col_lit wall bytes). Same label as
        # compile_colormap's table, so the two are mutually exclusive per program.
        cmv = colormap_values(asset_wad, lights=COLORMAP_LIGHTS)
        cm = "\n".join([
            generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
            generate_emit_dispatch_table_fj("cm", cmv, index_nibbles=_index_nibbles(len(cmv)),
                                            over_align=True),
        ])
    elif raster or projm:
        # M13-raster/proj: nothing calls cm.emit OR cm.apply -- the device does its OWN colormap
        # lookup from the raw packed colormap table (present.load_raster_tables); only byte.emit
        # (runtime-byte emit: record fields / header bytes / seg ids) is needed.
        cm = generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)
    else:
        cm = compile_colormap("cm", asset_wad, lights=COLORMAP_LIGHTS, over_align=over_align)
    palette = compile_palette("palette", asset_wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    # M13-ATANDISP (lines mode): the SAME tantoangle values as a D4 per-entry dispatch table, so
    # point_to_angle_m can trade its ~289@ packed read (4x read_byte_and_inc + a mul_const, per the
    # stl's documented complexities) for a ~20@ lookup. Byte-exact by construction: same values.
    # M13-2S rung 3b: entry index -> byte offset (5 bytes per region entry), by dispatch. The
    # multiply it replaces is 9 shifts of w/4 and the append path runs ~1,600 times a frame.
    entoff = (generate_dispatch_table_fj("entoff", [5 * i * DW_BITS for i in range(TS_ECAP + 2)],
                                         index_nibbles=2, result_nibbles=8) if two_sided else "")
    ttang = (generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE),
                                        index_nibbles=3, result_nibbles=8) if lines else "")
    sdrecip = (generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(),
                                          index_nibbles=3, result_nibbles=6) if lines else "")
    # M13-SRDISP: the SAME lever, FOURTH application. `proj.scale_recip_div` opens with a
    # `read_table_packed 3` of `slopediv_recip` (~247@), and it runs twice per pass-2 seg, twice
    # per step-face seg and once per projected thing.
    srdisp = (generate_dispatch_table_fj("srdisp", slopediv_recip_table(),
                                         index_nibbles=3, result_nibbles=6) if lines else "")
    # M13-XTADISP: the SAME lever, third application. `proj.wall_scale_setup` runs once per
    # in-frustum seg (169 at E1M1 spawn, 202 at the worst sweep viewpoint) and opens by reading
    # xtoviewangle at x1 AND at x2 -- two ~289@ packed reads = ~15.6k ops per seg, ~2.6M/3.2M a
    # frame spent reading a 161-entry table. As a dispatch table each read is ~20@. Only 161
    # entries, so this costs ~1/25 the program size of the tantoangle conversion.
    xtadisp = (generate_dispatch_table_fj("xtadisp", xtoviewangle_table(cfg.VIEW_W, cfg.TRIG_N),
                                          index_nibbles=2, result_nibbles=8) if lines else "")
    # M13-VTXDISP: the SAME lever, fifth application -- and the largest one left. `proj.angle_to_x`
    # opens with a `hex.read_table_packed 4` of `viewangletox` and runs TWICE per in-frustum seg
    # inside `wall_x_range_m`. MEASURED on the macro itself with only the `disp` flag changed, both
    # arms vacuity-checked (scratchpad/ca2_price.py): 8,827.7 -> 1,809.5 ops/call, 7,018.2 saved.
    # 2,048 entries at 8 nibbles -> ~41k words, against an 85.5M-word span.
    # ⚠ An earlier version of that probe compared the WHOLE macro against a BARE `vtxdisp.lookup`
    # and reported 8,404.7 -- it was crediting the change with angle_to_x's prologue, which the
    # change keeps. Measure a rep-gated macro by flipping its flag, never against its inner call.
    # ⚠ AND 7,018.2 IS STILL ONLY AN ISOLATED-PROBE PRICE: at one profiled shipped-tier frame it
    # predicts 3,017,826 ops of saving (430 calls) where the WHOLE frame saved 2,564,285. The
    # round-2 RESULT is measured (-1,121,842 shipped median, 260/260 byte-exact); its ATTRIBUTION
    # to these four changes is NOT. Do not estimate from it -- see docs/handoff-constaddr.md §13.8.
    # Values are the SAME `tables.viewangletox_table` the packed LUT bakes (R6 SSOT), masked to
    # 32 bits exactly as `generate_viewangletox_lut_fj` does (the columns are signed sentinels).
    vtxdisp = (generate_dispatch_table_fj(
        "vtxdisp", [v & 0xFFFFFFFF for v in viewangletox_table(cfg.VIEW_W, cfg.TRIG_N)],
        index_nibbles=3, result_nibbles=8) if lines else "")

    # M13-SINADISP: `proj.scale_from_global_angle` computes its DENOMINATOR sine from
    # anglea = ANG90 + (visangle - viewangle). Every caller builds visangle as
    # `viewangle + xtoviewangle[col]`, so viewangle cancels EXACTLY (mod 2^32) and anglea is a
    # function of the screen column alone. The whole prologue + read_sin therefore bakes into a
    # 161-entry dispatch indexed by the column -- the same domain and index width `xtadisp`
    # already uses, so a column valid for one is valid for the other by construction.
    # Values come from the same `tables.sine_table` / `tables.xtoviewangle_table` the fj path
    # reads (R6 SSOT), with the shift written as the config-derived ANGLE_SHIFT, not a literal.
    _ang_shift = 32 - (cfg.TRIG_N.bit_length() - 1)          # = 20 for TRIG_N=4096
    _sine = sine_table(cfg.TRIG_N, 16, 32)
    sinadisp = (generate_dispatch_table_fj(
        "sinadisp",
        [_sine[((a + (1 << 30)) >> _ang_shift) & (cfg.TRIG_N - 1)] & 0xFFFFFFFF
         for a in xtoviewangle_table(cfg.VIEW_W, cfg.TRIG_N)],
        index_nibbles=2, result_nibbles=8) if lines else "")
    # V2: the SKY bank. A sky column has no perspective and no distance lighting, so it is just a
    # band list -- which makes "sky" nothing more than a per-column CHOICE OF CEILING BAND LIST, and
    # needs no new emit path at all. One list per sky texture column, in the same
    # [y2_cumulative][colour] form the plane bands already use, plus a compile-time per-column
    # offset table; the frame supplies `skybase` and the existing prefix walk does the rest.
    skybands, skyoff = _lines_sky_bank(rm, asset_wad, cfg) if (lines and sky) else ("", "")
    skypid = ""                     # filled below, once the pid map exists
    # V3: the step-face shade bank + the (light, wall-units) class each face-carrying boundary bakes.
    stepcol, step_cls = (_lines_step_bank(rm, asset_wad, cfg, cmap, lds, sds, secs,
                                          w1r=bool(w1r_flag), sky=sky)
                         if (lines and steps) else ("", {}))
    # V4: the sprite run-list bank + the shade-row bank, and the per-type block bases the things bake.
    _do_things = lines and things
    assert not (things and sprite_wad is None), "things=True needs sprite_wad (see _lines_sprite_bank)"
    sprbank, spr_base, spr_dw, spr_ldbase = (_lines_sprite_bank(rm, sprite_wad, cfg, map_wad, mapname)
                                 if _do_things else ("", {}, {}, {}))
    sprlight, spr_cls = (_lines_sprite_light(rm, cfg, sprite_wad, map_wad, mapname,
                                             cmap, lds, sds, secs, moving_things=moving_things)
                         if _do_things else ("", {}))
    # h -> [bucket_height:2][bucket:2], the one runtime step of the height quantisation
    sprbkt = (generate_dispatch_table_fj(
        "sprbkt", [0] + [sprite_bucket(h, cfg.VIEW_H) | (sprite_bucket_height(
            sprite_bucket(h, cfg.VIEW_H), cfg.VIEW_H) << 8) for h in range(1, cfg.VIEW_H + 1)],
        index_nibbles=2, result_nibbles=4) if _do_things else "")
    spr_cache: dict = {}
    # M14.5 — THE SPLIT. `things_by_ss` is what the leaf BAKES; `_mt_keep` is what the runtime
    # table carries. On a static build everything bakes, exactly as before. On a moving build the
    # SSOT (`baked_thing_mask`) decides, and the two sets are disjoint and cover the drawable set --
    # asserted below, because a thing in NEITHER is invisible with no other symptom (M14-a's
    # failure mode), and a thing in BOTH is drawn twice.
    things_by_ss: dict = {}
    _all_by_ss: dict = {}
    _mt_keep = None
    if _do_things:
        from doomfj.things import baked_thing_mask, drawable_things, vanishable_slots
        _drawable, _draw_idx = drawable_things(rm, map_wad.things(mapname), sprite_wad, spr_cache)
        _baked = (baked_thing_mask(rm, cmap, _drawable, MONSTER_TYPES) if moving_things
                  else (True,) * len(_drawable))
        _mt_keep = {i for i, b in zip(_draw_idx, _baked) if not b}
        # M14.5 §3.3: the baked things that can VANISH get a 1-nibble flag at a fixed address.
        # Static builds have no wire to carry it, so they keep none -- and stay byte-identical.
        _vis_slots = (vanishable_slots(_drawable, _baked, VANISHABLE_TYPES) if moving_things
                      else {})
        for _di, (_t, _b) in enumerate(zip(_drawable, _baked)):
            _ss0 = rm.point_in_subsector(cmap, _t.x, _t.y)
            _all_by_ss.setdefault(_ss0, []).append(_t)
            if _b:
                things_by_ss.setdefault(_ss0, []).append((_di, _t))
        # THE CONTROL (handoff-m14_5.md §7b.1): baked ∪ runtime == drawable, exactly, no overlap.
        _nb = sum(len(v) for v in things_by_ss.values())
        assert _nb + len(_mt_keep) == len(_drawable) and _nb == sum(_baked), (
            f"M14.5 split lost or duplicated things: {_nb} baked + {len(_mt_keep)} runtime != "
            f"{len(_drawable)} drawable")
        # ... and every leaf is HOMOGENEOUS at spawn, which is what keeps the per-leaf visit order
        # wad order in both mirrors (§4b). A mixed leaf here means the rule was edited without its
        # oracle half, and the gate would find it as a mysterious pixel diff 25 minutes later.
        assert not moving_things or not [s for s, v in _all_by_ss.items()
                                         if 0 < len(things_by_ss.get(s, ())) < len(v)], (
            "M14.5: a leaf holds BOTH baked and runtime things at spawn -- see baked_thing_mask")
    # M14-a — THE PRUNE, settled. Everything that decides whether a leaf/subtree may be dropped now
    # asks `thing_live_subsectors` ("could a thing EVER be here?") instead of `things_by_ss` ("is a
    # thing standing here right now?"). The second answer stops being true the moment the sim moves
    # anything, and it fails SILENTLY -- see the SSOT's docstring. `_do_things` keeps a things=False
    # build bit-identical: with no sprites emitted there is nothing to lose by pruning.
    # ...gated by `_do_things` for the PRUNE, but not for the bbox gate: like the old code, the
    # wedge boxes are inflated whether or not sprites are emitted, because the oracle's half is
    # computed the same way in both cases and the two sets must agree to the node.
    _thing_live_gate = thing_live_subsectors(cmap, lds, sds, secs)
    _thing_live = _thing_live_gate if _do_things else frozenset()
    # THE LOUD FAILURE (handoff-m14.md section 3: "a silent vanish is unacceptable; a hard failure
    # is fine"). Anything the predicate calls uninhabitable must be provably unreachable, so a thing
    # already standing in one means the predicate is wrong -- refuse to emit rather than ship a
    # renderer that can drop it.
    _stranded = sorted(set(_all_by_ss) - _thing_live) if _do_things else []
    assert not _stranded, (
        f"thing_live_subsectors says subsectors {_stranded} are uninhabitable, yet {mapname} spawns "
        f"drawable things in them: {[(t.type, t.x, t.y) for s in _stranded for t in _all_by_ss[s]]}. "
        "The prune would drop those leaves and the sprites would vanish with no other symptom.")
    # M14-e: the runtime half of the same data, baked by INDEX rather than by (subsector, thing).
    _mt_tables, _mt_ptloc, _mt_decls, _MT_NT, _MT_NSS, _MT_LTB, _MT_BINDS = (
        _moving_thing_tables(rm, cmap, lds, sds, secs, map_wad, mapname, sprite_wad,
                             spr_base, spr_ldbase, spr_dw, spr_cls, deg=deg, spr_cache=spr_cache,
                             keep=_mt_keep)
        if moving_things else ("", "", [], 0, 0, {}, []))
    # M14.5: one byte-wide slot per vanishable baked thing, filled from the wire before the walk.
    # ⚠ ZERO-init would mean "hidden", so the host sends the whole block every frame -- it is the
    # host that owns what has been picked up, and fj has no state between frames.
    _MT_NVIS = len(_vis_slots) if _do_things else 0
    if _MT_NVIS:
        # M5: standalone has no host to say what has been picked up, and nothing picks anything up
        # yet (that is C1), so every slot bakes VISIBLE. Zero would mean "hidden" -- the reason the
        # hosted tier has to send the whole block every frame.
        _mt_decls = list(_mt_decls) + (
            ["thvis:"] + ["    hex.vec 2, 1"] * _MT_NVIS if standalone else
            [f"thvis: hex.vec {2 * _MT_NVIS}"])
    _MT_NTH = _index_nibbles(max(1, _MT_NT))          # the row index's width, as check_line's is
    _MT_NSSN = _index_nibbles(max(1, _MT_NSS))
    _MT_NLTI = _index_nibbles(max(1, len(_MT_LTB) * _MT_NT)) if moving_things else 1
    # M14.5: the baked call sites' own copy of the record body (`mt`=0). On a static build there is
    # only one body and it keeps its name, so that renderer is emission-identical to before.
    _baked_leaf = "thing_leaf_b" if moving_things else "thing_leaf"
    _emit_baked_leaf = bool(moving_things and things_by_ss)

    def _thing_leaf_body(label, mt):
        """One instantiation of frame.thing_record_body. `mt` picks where the COLD half of the
        thing's row comes from: 1 = the runtime table (read after every reject), 0 = the leaf's
        xor_by block, where the rep expands to nothing and the table names are never referenced."""
        return [f"{label}:",
                f"frame.thing_record_body {THING_BUDGET}, {MONSTER_BUDGET}, {SPRITE_MINZ}, "
                f"{proj}, {cfg.CENTERX}, "
                f"{cfg.CENTERY}, {cfg.VIEW_W}, {cfg.VIEW_H}, {cfg.TEXTURE_DOWNSCALE}, "
                f"{SPR_BLOCK_STRIDE.bit_length() - 1}, "
                f"{SPRITE_HEIGHT_BUCKETS}, {SPR_SLOT_STRIDE}, "
                f"{1 if 'thingtwice' in ablate else 0}, {deg_flag}, {DEG_SOFT_SCENERY}, "
                f"{DEG_SOFT_MON}, {DEG_SPRB_MINH}, {1 if DEG_SPR_NEAR_TZ else 0}, "
                f"{DEG_SPR_LOWRES_H}, {_spr_nlow(cfg) if DEG_SPR_NEAR_TZ else 1}, "
                f"{DEG_SPR_NEAR_TZ * 0x10000}, "
                f"{mt}, "
                f"{'throwc' if mt else '0'}, {_MT_NTH}, "
                f"{'sprlt' if mt else '0'}, {_MT_NLTI}"]
    # V1: the pseudo-random wall grain, baked straight from the oracle so the two cannot drift (R6).
    # The hash is xors and shifts of the column index, so it evaluates entirely at COMPILE time and
    # the runtime cost is one ~20@ lookup per column -- no table read, no arithmetic, no per-run state.
    # W1R-ANCHOR: the pattern key is (x + wnoff) with wnoff in [0, 640), so the W1R tables
    # cover the whole shifted domain (the hash is pure, so this is just more baked entries).
    _wn_dom = cfg.VIEW_W + 1 + (640 if w1r_flag else 0)
    _wn_idx = 3 if w1r_flag else 2
    wnoise = (generate_dispatch_table_fj(
        "wnoise", [rm.wall_noise(x) for x in range(_wn_dom)],
        index_nibbles=_wn_idx, result_nibbles=2) if lines and wall_noise else "")
    # M13-W1R: the randomized-wall walkers, baked from the oracle's own pattern tables (R6).
    w1rpat = (generate_w1r_walls_fj(rm.W1R_TIER_BOUNDS, rm.W1R_PATTERNS)
              if lines and w1r_flag else "")
    # W1R-LOD: the fine (2-px) and coarse (8-px) column-group hashes, dispatch tables like
    # wnoise's -- far tiers mix wnoise2 into their pattern pick, the near tier uses wnoise3.
    wnoise2 = (generate_dispatch_table_fj(
        "wnoise2", [rm.wall_noise2(x) for x in range(_wn_dom)],
        index_nibbles=_wn_idx, result_nibbles=2) if lines and w1r_flag else "")
    wnoise3 = (generate_dispatch_table_fj(
        "wnoise3", [rm.wall_noise3(x) for x in range(_wn_dom)],
        index_nibbles=_wn_idx, result_nibbles=2) if lines and w1r_flag else "")
    slopediv_recip = generate_slopediv_recip_lut_fj("slopediv_recip")   # perf #13
    slopediv_recip8 = generate_slopediv_recip8_lut_fj("slopediv_recip8")  # M13-coarseslope
    # M13-SINPERENTRY: `per_result_nibble` runs EIGHT dispatches per lookup (one per result
    # nibble); `per_entry` runs ONE. MEASURED on the real idiom (scratchpad/ca2_price.py, both
    # arms vacuity-checked): 983.2 -> 452.6 ops/call, i.e. 530.6 saved. read_sin+read_cos run 769
    # times at the sweep-median frame (scratchpad/ca2_callcount.py). The generator docstring
    # chose per_result_nibble for span on a "trig is ~160x/frame" estimate that is 4.8x low; the
    # span it buys is 65,536 -> 81,920 words, 0.02% of an 85.5M-word image.
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16, mode="per_entry")
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def lrow(light):
        return max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

    def wlit(light, texel, flat_wall=False):
        """The baked constant wall byte (`seg_lit`). W1R bakes it BRIGHTER by
        `W1R_BASE_BRIGHTEN` rows so the randomized run rows can move the tone BOTH ways
        around the W1 tone -- mirrors the oracle's W1R branch (`blr`) exactly (R6).
        W1R-FLAT walls (texture-less only since CR-2026-08; sky walls now pattern) keep the
        plain UNbrightened W1 tone."""
        row = lrow(light)
        if wall_mode == "W1R" and not flat_wall:
            row = max(0, row - rm.W1R_BASE_BRIGHTEN)
        return colormap[row][texel]

    # W1R-FLAT: the combined-table bases whose walls stay FLAT under W1R -- texture-less
    # (the WALL_BG sentinel) only. SKY-textured walls USED to be here too; owner 2026-08-09:
    # they read as blank white slabs, so they now take the standard masonry pattern (mirrors
    # the oracle's W1R-FLAT branch, R6).
    w1r_flat_tb = {info["__WALLBG__"][0]} if w1r_flag else set()

    # M13-bakedbands (the 12M campaign's LUT play): in lines mode EVERY POSSIBLE band list is
    # baked at compile time -- one list per (viewz class) x (height, light, flat-base) key, with
    # the FINAL palette colour folded in (colormap[zrow][base]) and CUMULATIVE absolute y2 per
    # entry -- so the runtime build machinery (build_bands, recip32, built-flags, planeheight)
    # vanishes entirely. Adjacent zrows sharing a final colour merge, so baked lists are also
    # SHORTER than the runtime-built ones (identical pixels). Layout: vpbank +
    # class_idx*(nkeys*130*dw) + key_idx*130*dw; each list = [nA][(y2,colour)xnA] at +0 and the
    # desc half at +65*dw, mirroring the old half-buffer layout.
    # M13-2S rung 3a: does this seg MARK its front sector's planes? One-sided always does; a
    # two-sided one only when its two sides differ in a band-bank key (height, light, flat) --
    # DOOM's R_StoreWallRange markfloor/markceiling test. Equal on both sides => attributing the
    # plane to either sector renders identically, so skipping it is free of error BY CONSTRUCTION.
    def _seg_marks(seg) -> bool:
        ld_ = lds[seg.linedef]
        if ld_.back == -1:
            return True
        fs_ = secs[sds[ld_.front if seg.side == 0 else ld_.back].sector]
        bs_ = secs[sds[ld_.back if seg.side == 0 else ld_.front].sector]
        return ((fs_.ceil_h, fs_.light & 0xFF, fs_.ceil_tex.upper())
                != (bs_.ceil_h, bs_.light & 0xFF, bs_.ceil_tex.upper())
                or (fs_.floor_h, fs_.light & 0xFF, fs_.floor_tex.upper())
                != (bs_.floor_h, bs_.light & 0xFF, bs_.floor_tex.upper()))

    def _seg_draws_wall(seg) -> bool:
        """M13-2S rung 3b (ablate "tsfull", measurement only): would this two-sided seg draw an
        upper or a lower wall run? (front ceiling above back ceiling / back floor above front
        floor). "tsfull" routes exactly these through the ONE-SIDED emission path -- full projection,
        scale setup, per-column params, WPX emit -- to price rung 3b's walk+emit BEFORE building it
        (R23/R32: the coarse-cull pre-pass was built before being priced and cost +24.7M). It emits
        FULL-HEIGHT walls instead of upper/lower slices, so it over-emits pixels and does NOT include
        rung 3b's per-column pair BUFFERING: read it as the projection/emit floor, not a bound."""
        ld_ = lds[seg.linedef]
        if ld_.back == -1:
            return False
        fs_ = secs[sds[ld_.front if seg.side == 0 else ld_.back].sector]
        bs_ = secs[sds[ld_.back if seg.side == 0 else ld_.front].sector]
        return fs_.ceil_h > bs_.ceil_h or bs_.floor_h > fs_.floor_h

    def _seg_as_solid(seg) -> bool:
        """Does this seg go down the one-sided (wall-emitting) path?"""
        return lds[seg.linedef].back == -1 or ("tsfull" in ablate and _seg_draws_wall(seg))

    def _seg_as_piece(seg) -> bool:
        """CR-2026-08 (the node-gate fix): is this a PIECE-CARRYING marking seg (um/lm nonzero)?
        Piece segs must keep running after claim-completion until the face budget is spent, so a
        gated subtree containing one needs the compound skip test, not plain tsstop."""
        ld_ = lds[seg.linedef]
        if ld_.back == -1 or not _seg_marks(seg):
            return False
        fs_ = secs[sds[ld_.front if seg.side == 0 else ld_.back].sector]
        bs_ = secs[sds[ld_.back if seg.side == 0 else ld_.front].sector]
        um_, lm_ = rm.v5_side_modes(fs_, bs_, sky)
        return bool(um_ or lm_)

    def _seg_in_walk(seg) -> bool:
        """Does the emitted walk do per-seg work for this seg? (the prune predicate's unit)

        ablate "pnearprune" (measurement only): keep the PRE-rung-3a one-sided prune rule while
        still emitting the two-sided claim sites, to price what the wider prune costs. Renders
        wrong (claims inside pruned subtrees are lost) -- never ship it."""
        if "pnearprune" in ablate:
            return lds[seg.linedef].back == -1
        return (_seg_as_solid(seg) or (plane_near and _seg_marks(seg))
                or lds[seg.linedef].back == -1)

    lines_key_ids: dict = {}
    lines_vz_classes: dict = {}
    lines_pid: dict = {}                       # M13-2S rung 3a: (ceil key, floor key) -> pid (1-based)
    lines_bank_keys: list = []                 # the bank's key order (a LIST: pid pairs repeat keys)

    def _plane_keys(sec):
        return ((sec.ceil_h, sec.light & 0xFF, _flatval(sec.ceil_tex), sec.ceil_tex.upper()),
                (sec.floor_h, sec.light & 0xFF, _flatval(sec.floor_tex), sec.floor_tex.upper()))

    if lines:
        for _ss in cmap.subsectors:
            _sec = rm._seg_sector(lds, sds, secs, cmap.segs[_ss.firstseg])
            lines_vz_classes.setdefault(rm.view_z(_sec.floor_h), len(lines_vz_classes))
        for _seg in cmap.segs:
            # M13-2S rung 3a: a marking two-sided seg attributes ITS front sector's planes, so that
            # sector's two band lists must be in the bank too (E1M1: 159 -> 227 distinct keys).
            if not _seg_in_walk(_seg):
                continue
            _ck, _fk = _plane_keys(rm._seg_sector(lds, sds, secs, _seg))
            lines_key_ids.setdefault(_ck, len(lines_key_ids))
            lines_key_ids.setdefault(_fk, len(lines_key_ids))
            if (_ck, _fk) not in lines_pid:
                lines_pid[(_ck, _fk)] = len(lines_pid) + 1     # 1-based: 0 == "not attributed yet"
            # V5: a stacked piece's REGION shows its boundary's BACK sector, so back pairs need
            # pids (and band lists) too. Registered for every two-sided walk seg -- a superset
            # of the face-carrying ones, a few extra keys at most.
            if stack_flag and lds[_seg.linedef].back != -1:
                _bsec5 = secs[sds[lds[_seg.linedef].back if _seg.side == 0
                               else lds[_seg.linedef].front].sector]
                _bck, _bfk = _plane_keys(_bsec5)
                lines_key_ids.setdefault(_bck, len(lines_key_ids))
                lines_key_ids.setdefault(_bfk, len(lines_key_ids))
                if (_bck, _bfk) not in lines_pid:
                    lines_pid[(_bck, _bfk)] = len(lines_pid) + 1
        # M13-2S rung 3a — the bank LAYOUT. With per-column attribution the emit half has to recover
        # a column's two band lists from ONE byte, so `plane_near` lays the bank out per SECTOR PLANE
        # PAIR (pid): pid p's ceiling list is slot 2(p-1), its floor list 2(p-1)+1, hence
        #   ceil = vzbank + (p-1)*4*half_slots*dw   and   floor = ceil + 2*half_slots*dw
        # -- one mul_const plus adds. The alternative (per-column address cells read back with
        # hex.ptr_index + hex.read_hex 8) measured ~780 dispatches per column, +5M/frame. Keys stop
        # being shared between pids, so the bank grows (E1M1 1.42M -> 1.91M words); without
        # plane_near the layout is EXACTLY the old shared-key one.
        lines_bank_keys = ([k for pair in lines_pid for k in pair] if plane_near
                           else list(lines_key_ids))
        # CR-2026-08: a pid must fit ONE BYTE everywhere it flows (the per-column pclm store is
        # `hex.write_byte pptr, seg_pid`, and skypid dispatches on 2 nibbles). E1M1-lite bakes
        # ~230 pairs; a denser map would silently alias pids without this.
        assert len(lines_pid) <= 255, f"lines_pid needs one byte, got {len(lines_pid)} pids"
        # ... and which PIDs are sky at all. A pid is (ceiling key, floor key) and the ceiling key
        # carries the flat NAME, so sky-ness is decided entirely at compile time: one dispatch per
        # column tells the emit loop whether to take the sky list or the plane list. pids are 1-based
        # (0 = "not attributed yet"), so slot 0 is a non-sky filler.
        skypid = (generate_dispatch_table_fj(
        "skypid",
        [0] + [1 if ck[3] == "F_SKY1" else 0 for (ck, _fk) in lines_pid],
        index_nibbles=2, result_nibbles=2) if (lines and sky and plane_near) else "")
    n_bank_keys = max(1, len(lines_bank_keys))

    # M13-15M BANDS-AS-CODE: the shipping-tier emit path — every band half-list baked as raw-op
    # CODE (see lut_generator.generate_bands_walk_fj; ~40-70 executed ops per emitted pair vs
    # ~2,600 for the data walk). Ablate builds and the two_sided lab keep the data bank.
    ascode = 1 if (lines and not two_sided and not ablate) else 0
    bands_code, sky_base_id = "", 0
    if ascode:
        _main_lists = _band_pair_lists(rm, cfg, asset_wad, lines_vz_classes, lines_bank_keys,
                                       floor_mode == "FT1")
        _sky_lists = _sky_pair_lists(rm, asset_wad, cfg) if sky else []
        sky_base_id = len(_main_lists)
        bands_code = generate_bands_walk_fj(_main_lists + _sky_lists)
        skybands = ""                          # the sky DATA bank dies with the plane bank

    # M13-prune (lines): count one-sided segs below every subtree; zero => the subtree can be
    # skipped by the main walk entirely (byte-exact -- it would emit nothing and touch nothing).
    # M13-2S rung 3a: two counts now -- `_walk_below` (segs the walk does ANY work for, the compile-
    # time prune) and `_solid_below` (one-sided segs only: zero => the subtree can only ATTRIBUTE
    # planes, so it is dead once `tsstop` and gets the runtime tsstop gate instead).
    lines_walk_below: dict = {}
    lines_solid_below: dict = {}
    lines_piece_below: dict = {}
    if lines:
        # V4: a THING-carrying leaf counts as live for BOTH subtree predicates. The walk prune drops
        # the node at COMPILE time; the `tsstop` plane gate skips it at RUNTIME once attribution is
        # finished. Either one silently loses every sprite in an open, purely two-sided area -- at
        # the tree viewpoint, most of them. So `live` forces the leaf's count to 1 regardless of the
        # predicate: it is not "this leaf has a seg of that kind", it is "do not drop this leaf".
        #
        # ⚠ CR-2026-08 (WR-1) — WHICH live set, and why it is NOT the same one for both users.
        # M14-a widened the prune's set from "a thing stands here" to `thing_live_subsectors` ("a
        # thing could EVER be here"), which is right: the sim moves things, and the narrow answer
        # stops being true the moment it does. But that set is 657 of E1M1's 682 leaves, so feeding
        # it to the PLANE-GATE counts made `lines_solid_below` non-zero almost everywhere and
        # `_lines_plane_gate` returned mode 0 for EVERY node -- MEASURED 128 gated nodes -> 0 on
        # stock E1M1, 65 -> 0 on lite. The runtime tsstop gate simply stopped existing, and no gate
        # could see it: the gate only ever skipped provably-dead work, so losing it is byte-exact
        # and pure cost.
        # The fix is to ask each user its own question. The prune is a COMPILE-time drop and must
        # survive anything the sim can do, so it keeps the wide set. The plane gate is a RUNTIME
        # skip re-decided every frame, so it only has to cover where things can be IN THIS BUILD --
        # and when `moving_things` is off nothing moves, so spawn occupancy is exact.
        # Both are emitter-only: the oracle models the bbox gate (which keeps `_thing_live`
        # unchanged) but not this runtime skip, so narrowing it moves no pixel and needs no oracle
        # half -- it must still be gated, because it changes the emitted program.
        _live_planes = _thing_live if moving_things else (
            frozenset(_all_by_ss) if _do_things else frozenset())

        def _cnt(child, pred, memo, live):
            if child & NF_SUBSECTOR:
                _si0 = child & (NF_SUBSECTOR - 1)
                _ss = cmap.subsectors[_si0]
                if _si0 in live:
                    return 1
                return sum(1 for _si in range(_ss.firstseg, _ss.firstseg + _ss.numsegs)
                           if pred(cmap.segs[_si]))
            _n = cmap.nodes[child]
            tot = _cnt(_n.left, pred, memo, live) + _cnt(_n.right, pred, memo, live)
            memo[child] = tot
            return tot
        import sys as _sys
        _old_rl = _sys.getrecursionlimit()
        _sys.setrecursionlimit(20000)
        _cnt(cmap.root, _seg_in_walk, lines_walk_below, _thing_live)
        _cnt(cmap.root, _seg_as_solid, lines_solid_below, _live_planes)
        # ⚠ WR-14: the piece count decides the gate's FLAVOUR (mode 2's compound test), not whether
        # a node is gated at all -- and a live leaf has already forced `lines_solid_below` non-zero,
        # which returns mode 0 before the flavour is asked. So the live override is dead here, and
        # passing it only inflated the count into the costlier mode for nodes that reach it another
        # way. This one asks the predicate and nothing else.
        _cnt(cmap.root, _seg_as_piece, lines_piece_below, frozenset())
        _sys.setrecursionlimit(_old_rl)

    def _lines_prune(child):
        if child & NF_SUBSECTOR:
            _si0 = child & (NF_SUBSECTOR - 1)
            # V4: a subsector whose segs are ALL pruned can still hold THINGS, and the oracle
            # projects them the moment the walk arrives there. Pruning it made fj miss every
            # sprite in an open, purely two-sided area -- at the tree viewpoint, most of them.
            # M14-a: keep the leaf whenever a thing could EVER stand in it, not merely when one
            # stands in it at emit time.
            if _si0 in _thing_live:
                return False
            _ss = cmap.subsectors[_si0]
            return not any(_seg_in_walk(cmap.segs[_si])
                           for _si in range(_ss.firstseg, _ss.firstseg + _ss.numsegs))
        return lines_walk_below.get(child, 1) == 0

    def _lines_plane_gate(node_i):
        """Node blocks whose subtree holds no one-sided seg: skippable at runtime. Returns the
        gate MODE: 0 = no gate; 1 = plain tsstop (subtree is light-only -- dead at
        claim-completion); 2 = the compound test tsbstop|(tsstop&fbspent) (CR-2026-08: the
        subtree holds PIECE-carrying marking segs, which the oracle keeps scanning after
        claim-completion until the face budget is spent -- the old plain-tsstop gate dropped
        their riser/lip pieces, the (1210,1187)/(1698,892) divergence class at node level)."""
        if lines_solid_below.get(node_i, 1) != 0:
            return 0
        return 2 if (steps and lines_piece_below.get(node_i, 0)) else 1

    if lines and _do_things:
        # M14-a: the guard runs on the SAME two callables `_bsp_as_code` is about to be handed, so
        # it checks what is really emitted rather than a restatement of it. It is O(tree) at emit.
        # ⚠ CR-2026-08 (WR-1): the runtime gate is checked against `_live_planes`, the set that
        # build can actually put a thing in -- see the note at `_cnt`. On a moving build the two
        # arguments are the same object and this is the M14-a guard unchanged.
        assert_thing_live_survives_prune(
            cmap, thing_live=_thing_live, prune=_lines_prune,
            plane_gate=_lines_plane_gate if plane_near else None,
            plane_live=_live_planes, where=f"{mapname}: ")

    def _lines_descend_leaf(s):
        # the descend pre-walk's landing action: bake this subsector's viewz + band-bank pointer
        _sec = rm._seg_sector(lds, sds, secs, cmap.segs[cmap.subsectors[s].firstseg])
        _vz = rm.view_z(_sec.floor_h)
        if ascode:
            return [f"    hex.set 8, viewz, {_vz & 0xFFFFFFFF}",
                    f"    hex.set w/4, vzcbase, {lines_vz_classes[_vz] * n_bank_keys * 2}"]
        return [f"    hex.set 8, viewz, {_vz & 0xFFFFFFFF}",
                f"    hex.set w/4, vzbank, vpbank + "
                f"{lines_vz_classes[_vz] * n_bank_keys * 130}*dw"]

    # M13-W2S: the per-seg wall colour strips (only when the lines mode asks for the W2S tier)
    lines_wstrip_off, lines_wstrip_txt = {}, ""
    if lines and wall_mode == "W2S":
        lines_wstrip_off, lines_wstrip_txt = _lines_wall_strips(
            rm, asset_wad, cmap, lds, sds, secs, wall_mode, colormap, lrow)
    elif lines and wall_mode == "WPX":
        lines_wstrip_off, lines_wstrip_txt = _lines_wall_pix_bank(
            rm, asset_wad, cmap, lds, sds, secs, colormap, verts, cfg.VIEW_H,
            solid=_ts_draws_wall_early if "tsfull" in ablate else None,
            two_sided=_seg_marks if two_sided else None)

    _cid = [0]
    xorby_blocks = {}                                        # M12pp: seg{si}_xorby blocks, emitted once each
    # M13pS2-crush2b: per-seg VISPLANE ids -- segs sharing (plane height, light, flat base) share ONE
    # full-range band list per frame (built on first claim, sliced per column at emit). Keyed on the
    # BAKED triple (planeheight derives from height+runtime viewz identically for equal heights).
    cvp_ids: dict = {}
    fvp_ids: dict = {}

    def subsector_action(s):
        ss = cmap.subsectors[s]
        cid = _cid[0]; _cid[0] += 1
        psec = rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
        viewz_val = rm.view_z(psec.floor_h)
        if lines:
            # M13-prune: viewz/vzbank are set by the descend pre-walk, so leaves carry ONLY the
            # per-seg emission (and empty leaves nothing at all).
            out = []
            # V4 THINGS: this subsector's things, projected the moment the walk ARRIVES here --
            # before its own segs, so a thing standing in a room is in front of that room's walls.
            # Front-to-back arrival order is the whole occlusion test (see frame.thing_record_body).
            # `tstop` gates the xorby block, exactly as `tsstop` does for the two-sided claim: both
            # of the oracle's stop conditions (the budget spent, every column claimed) are monotone,
            # so once the leaf sets it no later thing can matter and none pays its SET+CLEAR.
            if _do_things and ss.numsegs:
                # M14.5: BAKED FIRST, THEN THE RUNTIME LIST -- the order both mirrors keep (§4b).
                # A static build has no runtime half and this is the whole thing pre-pass, exactly
                # as before; a moving build bakes only the things whose leaf no monster shares, so
                # at spawn a leaf runs one branch or the other and the order is wad order either way.
                for _ti, (_di, _t) in enumerate(things_by_ss.get(s, ())):
                    _art = rm.sprite_art(sprite_wad, _t.type, spr_cache)
                    _tsec = _thing_sector(rm, cmap, lds, sds, secs, _t)
                    _tag = f"{s}_{_ti}"
                    _tfields = [
                        ("sp_x", 8, (_t.x << 16) & 0xFFFFFFFF),
                        ("sp_y", 8, (_t.y << 16) & 0xFFFFFFFF),
                        ("sp_z", 8, ((_tsec.floor_h + _art[6]) << 16) & 0xFFFFFFFF),
                        ("sp_left", 8, (_art[5] << 16) & 0xFFFFFFFF),
                        ("sp_w", 8, (_art[3] << 16) & 0xFFFFFFFF),
                        ("sp_hh", 8, (_art[4] << 16) & 0xFFFFFFFF),
                        # The EXACT min-SIZE reject: past this depth the sprite projects to
                        # fewer than its category's minimum rows, so the projection stops before
                        # its two lateral multiplies and its reciprocal. ⚠ NOT the analytic
                        # wph*PROJECTION//min_h -- the block-FP reciprocal moves the true boundary
                        # by up to a map unit, so `sprite_tz_min_size` scans for it (R6: the oracle
                        # rejects the identical set at its `h < min_h` test).
                        ("sp_tzmax", 8, rm.sprite_tz_min_size(
                            _art[4], MIN_SPRITE_H_MONSTER if _t.type in MONSTER_TYPES
                            else MIN_SPRITE_H) & 0xFFFFFFFF),
                        # 25M-CAP: the RAISED bar's bound, scanned the same way; picked at
                        # runtime by degfl once the SOFT count fills (graduated acceptance)
                        *([("sp_tzmax2", 8, rm.sprite_tz_min_size(
                            _art[4], DEG_MINH2_MON if _t.type in MONSTER_TYPES
                            else DEG_MINH2_SCENERY) & 0xFFFFFFFF)] if deg else []),
                        # which budget this thing spends -- baked, because the category is a
                        # property of the thing type and never changes at runtime
                        ("sp_mon", 2, 1 if _t.type in MONSTER_TYPES else 0),
                        ("sp_base", 4, spr_base[_t.type]),
                        # SPR-NEAR: the packed coarse-region base -- read only for SHORT
                        # buckets of FAR things (the thfar flag project_thing sets)
                        *([("sp_base2", 4, spr_ldbase[_t.type])] if DEG_SPR_NEAR_TZ else []),
                        ("sp_dw", 2, spr_dw[_t.type]),
                        ("sp_lt", 2, spr_cls[(rm.wall_lightnum(_tsec.light, 0), max(1, _art[4]))])]
                    # ⚠ CR-2026-08 (TS-3/ST-7) — THE SCHEMA CHECK. These registers must each be
                    # cleared by `sim.thing_pass` on a hybrid build (xor_by self-restores only from
                    # zero), and the test that ties the two lists together used to hand-copy THIS
                    # list -- so a field added here was invisible to it. Now the schema is one
                    # constant, the emitter asserts it built from that schema, and the test reads
                    # the same constant: a new field cannot be added without both noticing.
                    assert [(n, w) for n, w, _v in _tfields] == [
                        p for p in THING_XORBY_FIELDS
                        if p[0] not in ("sp_tzmax2", "sp_base2")
                        or (p[0] == "sp_tzmax2" and deg)
                        or (p[0] == "sp_base2" and DEG_SPR_NEAR_TZ)], (
                        "the thing xor_by block no longer matches THING_XORBY_FIELDS -- update the "
                        "schema (and sim.thing_pass's clears) together")
                    xorby_blocks[f"T{_tag}"] = _seg_xorby_block(f"thing{_tag}_consts", _tfields)
                    out += [
                        # M14.5 §3.3: read-many, write-rarely, and the index is a COMPILE-TIME
                        # constant here -- so this is a fixed-address 1-nibble test, not a pointer
                        # build. A picked-up medikit costs exactly this test and skips its
                        # projection; a thing that cannot vanish emits nothing at all.
                        *([f"    hex.if0 1, thvis + {_vis_slots[_di]}*2*dw, "
                           f"ss{cid}_thing{_ti}_skip"] if _di in _vis_slots else []),
                        f"    hex.if0 1, tstop, ss{cid}_thing{_ti}_do",
                        f"    ;ss{cid}_thing{_ti}_skip",
                        f"  ss{cid}_thing{_ti}_do:"] + [
                            f"    stl.fcall thing{_tag}_consts, xb_ret",
                            f"    stl.fcall {_baked_leaf}, thing_ret",
                            f"    stl.fcall thing{_tag}_consts, xb_ret",
                            f"  ss{cid}_thing{_ti}_skip:"]
            if _do_things and ss.numsegs and moving_things:
                # M14-e: the leaf no longer knows which things are its own -- `bind_things` decided
                # that this frame from the wire's positions. Two lines, and the shared `thing_pass`
                # walks this leaf's list; `tstop` is re-tested per thing inside it, exactly as the
                # baked call sites gate themselves individually below.
                # ⚠ the leaf's FLOOR and LIGHT-ROW BASE go with it, as baked constants. Both are
                # properties of this subsector and fixed at level load, so reading them from tables
                # inside thing_load meant three `read_table_packed`s PER THING for values constant
                # across the whole leaf -- 23,569 of thing_load's measured 69,503 ops.
                out += [f"    hex.set w/4, cur_ss, {s}",
                        f"    hex.set 4, ss_flr, {psec.floor_h & 0xFFFF}",
                        f"    hex.set 4, ss_ltb, {_MT_LTB[rm.wall_lightnum(psec.light, 0)]}",
                        "    stl.fcall thing_pass_leaf, tp_ret"]
            for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
                seg = cmap.segs[si]
                ld = lds[seg.linedef]
                if ld.back != -1 and two_sided and not _seg_marks(seg):
                    continue                     # the compile-time cull (DOOM's R_AddLine reject)
                if ld.back != -1 and not _seg_as_solid(seg) and not two_sided:
                    # M13-2S probe (ablate "tsprobe"): walk the DRAWABLE two-sided segs through the
                    # cheap cull only -- GEOM block + pass 1, no emit. This prices the one thing that
                    # decides whether any two-sided emit design can fit the ops ceiling: what it
                    # costs merely to VISIT 1284 segs instead of 432. A two-sided seg whose sectors
                    # share BOTH ceiling and floor can never draw (773 of E1M1's 1482) and is
                    # excluded, exactly as the real implementation will exclude it via a baked flag.
                    # M13-2S rung 3a (ablate "tsmark"): the same probe, but with the cull the PLANE
                    # attribution actually needs. "Can never draw a WALL" (tsprobe) is too strong for
                    # planes: it drops the boundary between two sectors of equal heights but
                    # different flats/lights, which is precisely where the near floor changes
                    # surface -- measured at spawn, tsprobe's cull left 3 flats claiming the near
                    # floor, this one leaves exactly 1. It is DOOM's R_AddLine/R_StoreWallRange
                    # markfloor/markceiling test: skip only when BOTH band-bank keys
                    # (height, light, flat) are equal on the two sides, in which case attributing
                    # the plane to the back sector renders identically anyway.
                    if plane_near:
                        # M13-2S rung 3a — THE REAL THING (not a probe): a marking two-sided seg
                        # attributes the near floor/ceiling surface of the columns it covers. Guarded
                        # by `tsstop` BEFORE the xorby block, so once attribution can no longer
                        # change anything (every column attributed, or the per-frame seg BUDGET spent)
                        # each remaining two-sided seg costs one 1-nibble test -- 1386 of E1M1 spawn's
                        # 1445 land there, and visiting them all costs +11.9M, over the ceiling.
                        # Writes only the attribution state -- never drawn/n_drawn/full.
                        if not _seg_marks(seg) or "pnearwalk" in ablate:
                            continue                     # the compile-time cull (see _seg_marks)
                        _v1x, _v1y = verts[seg.v1]
                        _v2x, _v2y = verts[seg.v2]
                        _sa, _sb, _sc = seg_affine_coeffs(seg, verts)
                        xorby_blocks[si] = _seg_xorby_block(f"seg{si}_attrib_consts", [
                            ("seg_v1x", 8, (_v1x << 16) & 0xFFFFFFFF),
                            ("seg_v1y", 8, (_v1y << 16) & 0xFFFFFFFF),
                            ("seg_v2x", 8, (_v2x << 16) & 0xFFFFFFFF),
                            ("seg_v2y", 8, (_v2y << 16) & 0xFFFFFFFF),
                            ("seg_a", 8, _sa), ("seg_b", 8, _sb), ("seg_c", 8, _sc),
                            ("seg_pid", 2,
                             lines_pid[_plane_keys(rm._seg_sector(lds, sds, secs, seg))])])
                        # V3: a SECOND block, emitted only for boundaries that actually carry a step
                        # face (709 of E1M1's marking two-sided segs). `seg_fmask` is 0 for the rest,
                        # which is what the leaf tests -- so a face-less boundary pays one 2-nibble
                        # if0 and nothing else, and never pays this block's SET+CLEAR at all.
                        _fsec = rm._seg_sector(lds, sds, secs, seg)
                        _bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
                        # V5-DROP: per-side piece MODES (0 none / 1 riser / 2 lip) from the
                        # SSOT -- drop-offs and level flat/light changes now carry a 1-row lip
                        # piece so the far surface's region paints beyond the edge
                        _um, _lm = rm.v5_side_modes(_fsec, _bsec, sky)
                        _tsq = [f"    stl.fcall seg{si}_attrib_consts, xb_ret"]
                        _tsu = [f"    stl.fcall seg{si}_attrib_consts, xb_ret"]
                        if steps and (_um or _lm):
                            _ln = rm.wall_lightnum(_fsec.light, 0)
                            xorby_blocks[si] = xorby_blocks[si] + _seg_xorby_block(f"seg{si}_face_consts", [
                                ("seg_segangle", 8, seg.angle),
                                ("seg_fmask", 2, _um | (_lm << 4)),
                                ("seg_uh1", 4, _fsec.ceil_h & 0xFFFF),
                                ("seg_uh2", 4, _bsec.ceil_h & 0xFFFF),
                                ("seg_lh1", 4, _bsec.floor_h & 0xFFFF),
                                ("seg_lh2", 4, _fsec.floor_h & 0xFFFF),
                                ("seg_ucls", 2, step_cls.get(
                                    (_ln, max(1, _fsec.ceil_h - _bsec.ceil_h)), 0) if _um else 0),
                                ("seg_lcls", 2, step_cls.get(
                                    (_ln, max(1, _bsec.floor_h - _fsec.floor_h)), 0) if _lm else 0),
                                # V5: the boundary's BACK pair id -- the plane region behind a
                                # stored piece re-derives its band lists from this (lines_pid_ids)
                                *([("seg_bpid", 2, lines_pid[_plane_keys(_bsec)])]
                                  if stack_flag else [])])
                            _tsq.append(f"    stl.fcall seg{si}_face_consts, xb_ret")
                            _tsu.append(f"    stl.fcall seg{si}_face_consts, xb_ret")
                        # V5-DROP-P2: LIGHT-ONLY marking segs (no pieces possible) stop at
                        # claim-completion via tsstop; piece-carrying segs call unconditionally
                        # and stop on the leaf's wall-drawn `full` entry test instead.
                        # ... piece segs still respect the BUDGET latch (tsbstop), and (SMUDGE
                        # FIX part 2) the IDLE stop: claim-complete (tsstop) AND face budget
                        # spent (fbspent) means the seg provably writes nothing -- skip it.
                        # Mirrors the oracle's piece-seg idle stop exactly.
                        if not (_um or _lm):
                            out += [f"    hex.if0 1, tsstop, ss{cid}_seg{si}_mark",
                                    f"    ;ss{cid}_seg{si}_marked"]
                        else:
                            out += [f"    hex.if1 1, tsbstop, ss{cid}_seg{si}_marked",
                                    f"    hex.if0 1, tsstop, ss{cid}_seg{si}_mark",
                                    f"    hex.if0 1, fbspent, ss{cid}_seg{si}_mark",
                                    f"    ;ss{cid}_seg{si}_marked"]
                        out += [f"  ss{cid}_seg{si}_mark:",
                                *_tsq,
                                "    stl.fcall seg_pass1_ts_leaf, seg_ret",
                                *_tsu,
                                f"  ss{cid}_seg{si}_marked:"]
                        continue
                    if not (ablate & {"tsprobe", "tsmark"}):
                        continue
                    _fs = secs[sds[ld.front if seg.side == 0 else ld.back].sector]
                    _bs = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
                    if "tsmark" in ablate:
                        if ((_fs.ceil_h, _fs.light & 0xFF, _fs.ceil_tex.upper())
                                == (_bs.ceil_h, _bs.light & 0xFF, _bs.ceil_tex.upper())
                                and (_fs.floor_h, _fs.light & 0xFF, _fs.floor_tex.upper())
                                == (_bs.floor_h, _bs.light & 0xFF, _bs.floor_tex.upper())):
                            continue
                    elif not (_fs.ceil_h > _bs.ceil_h or _bs.floor_h > _fs.floor_h):
                        continue
                    _v1x, _v1y = verts[seg.v1]
                    _v2x, _v2y = verts[seg.v2]
                    _sa, _sb, _sc = seg_affine_coeffs(seg, verts)
                    xorby_blocks[si] = _seg_xorby_block(f"seg{si}_geom_consts", [
                        ("seg_v1x", 8, (_v1x << 16) & 0xFFFFFFFF),
                        ("seg_v1y", 8, (_v1y << 16) & 0xFFFFFFFF),
                        ("seg_v2x", 8, (_v2x << 16) & 0xFFFFFFFF),
                        ("seg_v2y", 8, (_v2y << 16) & 0xFFFFFFFF),
                        ("seg_a", 8, _sa), ("seg_b", 8, _sb), ("seg_c", 8, _sc)])
                    out += [f"    stl.fcall seg{si}_geom_consts, xb_ret",
                            "    stl.fcall seg_pass1_leaf, seg_ret",
                            f"    stl.fcall seg{si}_geom_consts, xb_ret"]
                    continue
                v1x, v1y = verts[seg.v1]
                v2x, v2y = verts[seg.v2]
                ssec = rm._seg_sector(lds, sds, secs, seg)
                tb, th, tw = seg_texinfo.get(si, (0, 1, 1))
                sa, sb, sc = seg_affine_coeffs(seg, verts)
                # the band-bank key carries the flat NAME too, so M13-FT1 can sample its texels
                ckey = (ssec.ceil_h, ssec.light & 0xFF, _flatval(ssec.ceil_tex),
                        ssec.ceil_tex.upper())
                fkey = (ssec.floor_h, ssec.light & 0xFF, _flatval(ssec.floor_tex),
                        ssec.floor_tex.upper())
                # M13-splitxb: GEOM block (part 1's cull inputs) vs REST block (part 2 only) --
                # 375 of 432 walked segs stop in part 1, never paying the rest block's SET+CLEAR.
                gfields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                           ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                           ("seg_a", 8, sa), ("seg_b", 8, sb), ("seg_c", 8, sc)]
                if two_sided:
                    # M13-2S rung 3b: the seg's own geometry PLUS its back sector's two heights and
                    # its upper/lower WPX blocks. seg_flags nibble 0 = two-sided, 1 = has upper,
                    # 2 = has lower -- all compile-time facts, so the leaf's branches are 1-nibble
                    # tests on baked constants. A one-sided seg bakes zeros for the back fields, and
                    # xor_by of 0 emits nothing, so it costs what it did before.
                    _mid, _up, _lo = lines_wstrip_off[si]
                    _bs = (secs[sds[ld.back if seg.side == 0 else ld.front].sector]
                           if ld.back != -1 else ssec)
                    _two = 1 if ld.back != -1 else 0
                    _hasu = 1 if (_two and ssec.ceil_h > _bs.ceil_h) else 0
                    _hasl = 1 if (_two and _bs.floor_h > ssec.floor_h) else 0
                    rfields = [("seg_segangle", 8, seg.angle),
                               ("seg_wstrip", 4, _mid),          # WPX bank BLOCK INDICES: a
                               ("seg_wsupper", 4, _up),          # buffered region entry carries
                               ("seg_wslower", 4, _lo),          # the index in two bytes
                               ("seg_flags", 3, _two | (_hasu << 4) | (_hasl << 8)),
                               ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                               ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                               ("bceilfix", 8, (_bs.ceil_h << 16) & 0xFFFFFFFF),
                               ("bfloorfix", 8, (_bs.floor_h << 16) & 0xFFFFFFFF),
                               # CR-2026-08: width 2, matching the `seg_pid: hex.vec 2` decl --
                               # a 4-nibble bake would address the neighbouring declaration
                               # (pids are byte-sized by the assert at the registry).
                               ("seg_pid", 2, lines_pid[_plane_keys(ssec)])]
                    xorby_blocks[si] = (_seg_xorby_block(f"seg{si}_geom_consts", gfields)
                                        + _seg_xorby_block(f"seg{si}_render_consts", rfields))
                    out += [f"    stl.fcall seg{si}_geom_consts, xb_ret",
                            "    stl.fcall seg_pass1_leaf, seg_ret",
                            f"    hex.if0 1, proceed, ss{cid}_seg{si}_unseen",
                            f"    stl.fcall seg{si}_render_consts, xb_ret",
                            "    stl.fcall seg_pass2_leaf, seg_ret2",
                            f"    stl.fcall seg{si}_render_consts, xb_ret",
                            f"  ss{cid}_seg{si}_unseen:",
                            f"    stl.fcall seg{si}_geom_consts, xb_ret"]
                    continue
                rfields = [("seg_segangle", 8, seg.angle),
                           *([("seg_wstrip", "w/4", f"{lines_wstrip_off[si]}*dw")]
                             if wall_mode in ("W2S", "WPX") else []),
                           ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                           ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                           ("seg_lit", 2, wlit(ssec.light, combined[tb],
                                               flat_wall=tb in w1r_flat_tb)),
                           # W1R-2C: the SECOND colour byte -- the canvas's second texel
                           # (combined[tb+1] at the 2-texel W1R tier) through the same bake.
                           # W1R-FLAT: the per-seg stay-flat flag (texture-less only;
                           # sky walls pattern like any other since CR-2026-08).
                           *([("seg_lit2", 2, wlit(ssec.light, combined[tb + 1],
                                                   flat_wall=tb in w1r_flat_tb)),
                              ("seg_w1rf", 1, 1 if tb in w1r_flat_tb else 0)]
                             if w1r_flag else []),
                           # 25M-CAP SLIVER: the UNbrightened flat tone. seg_lit carries the
                           # W1R_BASE_BRIGHTEN headroom (R44) so the pattern can darken from it;
                           # a sliver drawn flat must use the true W1-tone the oracle draws.
                           *([("seg_litf", 2, wlit(ssec.light, combined[tb], flat_wall=True))]
                             if (w1r_flag and deg) else []),
                           # M13-2S rung 3a: the emit half derives both list addresses from the
                           # column's plane-pair id, so ONE 2-nibble bake replaces the two offsets
                           # (and the same byte is what this seg writes when it claims a column).
                           *([("seg_pid", 2, lines_pid[(ckey, fkey)])] if plane_near else
                             [("seg_cvpidx", "w/4", lines_key_ids[ckey] * 2 if ascode
                               else f"{lines_key_ids[ckey] * 130}*dw"),
                              ("seg_fvpidx", "w/4", lines_key_ids[fkey] * 2 if ascode
                               else f"{lines_key_ids[fkey] * 130}*dw")])]
                xorby_blocks[si] = (_seg_xorby_block(f"seg{si}_geom_consts", gfields)
                                    + _seg_xorby_block(f"seg{si}_render_consts", rfields))
                # ss{cid}_seg{si}_unseen: keyed by the per-EMISSION counter (cid): _bsp_as_code emits each
                # leaf's action once per parent branch, so seg-index labels would collide (R6m).
                out += [f"    stl.fcall seg{si}_geom_consts, xb_ret",
                        "    stl.fcall seg_pass1_leaf, seg_ret",
                        f"    hex.if0 1, proceed, ss{cid}_seg{si}_unseen",
                        f"    stl.fcall seg{si}_render_consts, xb_ret",
                        "    stl.fcall seg_pass2_leaf, seg_ret2",
                        f"    stl.fcall seg{si}_render_consts, xb_ret",
                        f"  ss{cid}_seg{si}_unseen:",
                        f"    stl.fcall seg{si}_geom_consts, xb_ret"]
            if out:
                out = ([f"    hex.if0 1, full, ss{cid}_visit", f"    ;ss{cid}_occluded", f"  ss{cid}_visit:"]
                       + out + [f"  ss{cid}_occluded:"])
            return out
        # player-subsector setup (runs only at the FIRST subsector visited = order[0] = the player's): set the
        # runtime viewz (player sector floor + VIEWHEIGHT) that every seg's worldtop + ceil/floor planeheight use.
        out = [
            f"    hex.if0 1, vz_set, e1pset{cid}",
            f"    ;e1psegs{cid}",
            f"  e1pset{cid}:",
            f"    hex.set 8, viewz, {viewz_val & 0xFFFFFFFF}",
            f"    hex.set 8, viewzw, {(viewz_val >> 16) & 0xFFFFFFFF}",
            # M13-proj: the device's positional framing expects viewz right after the 8-byte header,
            # before any seg id -- the first visited subsector's block runs before its segs emit.
            *(["    stream.emit_bytes4 viewz"] if projm else []),
            # M13-bakedbands: aim the frame's band-list bank at this subsector's viewz class
            *(([f"    hex.set w/4, vzcbase, {lines_vz_classes[viewz_val] * n_bank_keys * 2}"]
               if ascode else
               [f"    hex.set w/4, vzbank, vpbank + "
                f"{lines_vz_classes[viewz_val] * n_bank_keys * 130}*dw"]) if lines else []),
            "    hex.set 1, vz_set, 1",
            f"  e1psegs{cid}:",
        ]
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = cmap.segs[si]
            ld = lds[seg.linedef]
            if ld.back != -1:
                continue
            v1x, v1y = verts[seg.v1]
            v2x, v2y = verts[seg.v2]
            sd = sds[ld.front if seg.side == 0 else ld.back]
            texoff = (seg.offset + sd.x_off) << 16
            ssec = rm._seg_sector(lds, sds, secs, seg)
            tb, th, tw = seg_texinfo[si]
            sa, sb, sc = seg_affine_coeffs(seg, verts)   # perf #9: baked affine rw_distance coeffs (SSOT)
            if projm:
                # M13-proj: the leaf only needs the wedge + back-face inputs and the wire id --
                # everything else lives in the device-resident geometry table.
                fields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                          ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                          ("seg_a", 8, sa), ("seg_b", 8, sb), ("seg_c", 8, sc),
                          ("seg_sid", 4, proj_sid[si])]
                xorby_blocks[si] = _seg_xorby_block(f"seg{si}_consts", fields)
                out += _seg_xorby_use(f"seg{si}_consts")
                continue
            fields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                      ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                      ("seg_segangle", 8, seg.angle), ("seg_a", 8, sa), ("seg_b", 8, sb), ("seg_c", 8, sc),
                      ("seg_texoff", 8, texoff & 0xFFFFFFFF),
                      ("seg_texbase", 5, tb), ("seg_texheight", 4, th), ("seg_tw", 8, tw),
                      ("seg_hm", 3, th - 1), ("seg_light", 2, lrow(ssec.light)),
                      ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                      ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                      ("seg_ceil", 8, ssec.ceil_h & 0xFFFFFFFF),   # M12pp: worldtop = seg_ceil - viewzw in-leaf
                      ("seg_floor", 8, ssec.floor_h & 0xFFFFFFFF),  # M13c3: floor planeheight = |floor_h<<16 - viewz|
                      ("seg_plight", 2, ssec.light & 0xFF),         # RAW sector light (zlight does >>4)
                      ("seg_ceilbase", 5, _flatval(ssec.ceil_tex)),   # M13d2 slice offset / M13p1 base index
                      ("seg_floorbase", 5, _flatval(ssec.floor_tex))]
            if stream or raster:
                # M13pS2c: the W1 wall's lit colour is fully constant (one texel, one light row) --
                # bake the FINAL palette byte at Python emit time (no runtime colormap lookup at all).
                # (Lines mode never reaches this half of the action -- it returned above -- so the
                # old `or lines` term here and the _LINES_DEAD_FIELDS filter below it were dead;
                # removed in the CR-2026-08 refactor on the same unreachability proof as the arm.)
                fields.append(("seg_lit", 2, wlit(ssec.light, combined[tb],
                                                  flat_wall=tb in w1r_flat_tb)))
                if w1r_flag:
                    fields.append(("seg_lit2", 2, wlit(ssec.light, combined[tb + 1],
                                                       flat_wall=tb in w1r_flat_tb)))
                    fields.append(("seg_w1rf", 1, 1 if tb in w1r_flat_tb else 0))
                # M13pS2-crush2b: the seg's ceiling/floor visplane indices (shared band lists in
                # stream mode; shared device-side row->colour arrays in raster mode).
                ckey = (ssec.ceil_h, ssec.light & 0xFF, _flatval(ssec.ceil_tex),
                        ssec.ceil_tex.upper())
                fkey = (ssec.floor_h, ssec.light & 0xFF, _flatval(ssec.floor_tex),
                        ssec.floor_tex.upper())
                fields.append(("seg_cvpidx", 8, cvp_ids.setdefault(ckey, len(cvp_ids))))
                fields.append(("seg_fvpidx", 8, fvp_ids.setdefault(fkey, len(fvp_ids))))
            xorby_blocks[si] = _seg_xorby_block(f"seg{si}_consts", fields)
            out += _seg_xorby_use(f"seg{si}_consts")
        if stream or raster or lines:
            # M13pG1: skip the whole action (incl. every seg's xorby SET/CLEAR pair) once the screen
            # is full -- the leaf would fret per seg anyway, but the involution flips aren't free.
            out = ([f"    hex.if0 1, full, ss{cid}_visit", f"    ;ss{cid}_occluded", f"  ss{cid}_visit:"]
                   + out + [f"  ss{cid}_occluded:"])
        return out

    # M13-15M: the BBOX WEDGE CULL. Gate boxes come from the SSOT (bbox_gate_boxes); the gate
    # decides which marking segs spend PNEAR budget, so both sides must agree on the gated set to
    # the node -- the oracle's half (reference_model.render_wall_frame) computes the SAME set.
    # M14-a: that set was "subtrees holding a thing AT SPAWN", which inflates exactly the boxes the
    # spawn layout happens to need. A thing that walks into an un-inflated subtree loses its
    # off-wedge columns silently, so the inflation now follows `thing_live_subsectors` -- every
    # subtree a thing could ever enter.
    bbox_gate: dict = {}
    if lines and bbox_cull:
        bbox_gate = bbox_gate_boxes(cmap, thing_subsectors=_thing_live_gate)

    def _bbox_gate_lines(i, ret_reg):
        box = bbox_gate.get(i)
        if box is None:
            return None
        _t, _b, _l, _r = box
        M32 = 0xFFFFFFFF
        stage = [f"    hex.xor_by 8, bbcl, {(_l << 16) & M32}",
                 f"    hex.xor_by 8, bbcb, {(_b << 16) & M32}",
                 f"    hex.xor_by 8, bbcr, {(_r << 16) & M32}",
                 f"    hex.xor_by 8, bbct, {(_t << 16) & M32}"]
        return (stage + ["    stl.fcall bbgate_leaf, bbtret"] + stage
                + [f"    hex.if0 1, bbvis, bbmiss{i}",
                   f"    ;bbgo{i}",
                   f"  bbmiss{i}:",
                   f"    stl.fret {ret_reg}",
                   f"  bbgo{i}:"])

    bsp = _bsp_as_code(_pfx(mapname), cmap, done_label="bsp_done", subsector_action=subsector_action,
                       full_abort_label="full" if (stream or raster or lines) else None,   # M13pG1
                       # inline_side=True measured +0.42M on E1M1 (code bloat beats the
                       # fcall savings -- the layout tax again); kept available, OFF.
                       prune=_lines_prune if lines else None, inline_side=False,
                       plane_gate=_lines_plane_gate if (lines and plane_near) else None,
                       plane_gate_label="tsstop",
                       extra_gate=_bbox_gate_lines if bbox_gate else None)
    if lines:
        bsp += _bsp_descend_code(_pfx(mapname), cmap, _lines_descend_leaf, done_label="dsc_done")
    xorby = [ln for blk in xorby_blocks.values() for ln in blk]   # the shared per-seg xorby blocks (once)

    if collide:
        assert player_sim and lines, "collide=True rides player_sim on the lines tier"
        # local import: doomfj.collision needs wall_renderer's _int_part_lines, so importing it at
        # module level would close a cycle (the seg_affine_coeffs precedent in mapcompiler)
        from doomfj.collision import (block_tables, blockmap_grid, collision_tables_fj,
                                      move_with_collision_lines, COLLISION_STATE_DECLS)
        _cgrid = build_blockmap(cmap, lds)
        _bx0, _by0, _nbx, _nby = blockmap_grid(_cgrid)
        _cblocks, _cflat = block_tables(_cgrid)
        _collide_block = ([";simcollide_skip", "simcollide:"]
                          + move_with_collision_lines(
                              _cgrid, _pfx(mapname), radius=PLAYER_RADIUS,
                              height=PLAYER_HEIGHT >> 16, maxstep=MAX_STEP >> 16,
                              n_bk=_index_nibbles(len(_cblocks)),
                              n_bl=_index_nibbles(max(1, len(_cflat))),
                              n_ln=_index_nibbles(len(lds)))
                          + ["    ;simmv_done", "simcollide_skip:"])
        _collide_tables = collision_tables_fj(cmap, lds, secs, sds, ML_BLOCKING, _cgrid)
        _collide_decls = list(COLLISION_STATE_DECLS)
        # the SEED descent: the same point-location query the eye's pre-walk runs, at a CANDIDATE
        # position, tagged so it gets its own labels while sharing the partition blocks
        _collide_descend = _bsp_descend_code(
            _pfx(mapname), cmap,
            lambda s: [f"    hex.set 8, cp_seedf, "
                       f"{rm._seg_sector(lds, sds, secs, cmap.segs[cmap.subsectors[s].firstseg]).floor_h & 0xFFFFFFFF}",
                       f"    hex.set 8, cp_seedc, "
                       f"{rm._seg_sector(lds, sds, secs, cmap.segs[cmap.subsectors[s].firstseg]).ceil_h & 0xFFFFFFFF}"],
            done_label="cs_seeded", tag="cs") + "\ncs_seeded:\n    stl.fret cs_ret\n"
    else:
        _collide_block = _collide_decls = []
        _collide_tables = _collide_descend = ""

    pass1 = [
        *(_standalone_input_lines(collide) if standalone else
          _state_wire_lines(state_wire, sim=player_sim, collide=collide)),
        *_collide_block,
        # M14-e: the thing positions follow the player's state on the wire, then every leaf's list
        # is rebuilt from them. `hex.input n` counts BYTES, so one call takes a whole 16.16 pair
        # into 16 nibbles at a COMPILE-TIME offset -- no per-byte writes, ~148k ops for all 251.
        # This has to precede the walk: `subsector_action` reads the lists the bind writes.
        *([f"sim.bind_things thpos_rt, thss_rt, {_MT_NT}"] if (moving_things and standalone) else
          [f"rep({_MT_NT}, i) hex.input 8, thpos_rt + i*16*dw",
           # M14-e perf: last frame's thing->subsector bindings. Re-locating all of them every frame
           # cost 27.2M ops -- 73% of what M14-e added -- and it was only necessary because fj has
           # no state between frames. The binding is world state like the position, so it
           # round-trips, and `bind_things` locates ONLY what the host marked dirty. 2 bytes in
           # (the value's 4 nibbles), 4 bytes out (emit_bytes4 is the emitter this protocol has).
           f"rep({_MT_NT}, i) hex.input 2, thss_rt + i*16*dw",
           f"sim.bind_things thpos_rt, thss_rt, {_MT_NT}",
           f"stl.output_char {WIRE_THING_CMD}",
           f"rep({_MT_NT}, i) stream.emit_bytes4 thss_rt + i*16*dw"] if moving_things else []),
        # M14.5: ... and the baked things' visibility, last on the wire. IN only: the host decides
        # what has been picked up, fj only reads it, at a fixed address per call site (section 3.3).
        *([f"rep({_MT_NVIS}, i) hex.input 1, thvis + i*2*dw"]
          if (_MT_NVIS and not standalone) else []),
        # CR-2026-08 (PJ-2): the M13-absmul per-frame |viewx|/|viewy| + sign flags are GONE, and
        # with them 12 fj statements and 4 labels per frame. The abs form multiplied the magnitude
        # and negated the product, which truncates toward ZERO where the oracle's fixed_mul floors
        # -- equal only when the product's low 16 bits are zero, i.e. only at a whole map unit. M14
        # made the view position fractional and the two mirrors silently stopped agreeing (MEASURED:
        # scratchpad/_pj2_probe.py, 5 of 10 cases off by +1 ULP). The per-seg affine cull now
        # multiplies the SIGNED coord, with the sparse baked coefficient as the SECOND operand so
        # the ROW RULE still applies (that swap is bit-identical -- probe control 6).
        "hex.zero 2, n_drawn", "hex.zero 1, full",   # M13opt-P1: reset the drawn-column counter + full flag per frame
        # W1R-ANCHOR: wnoff = viewangle * 640 columns-per-turn >> 32 = (va*5) >> 25
        # exactly -- once per frame, ~2k ops. Widened cells keep the 34-bit step exact.
        *(["hex.zero 10, wnt", "hex.mov 8, wnt, viewangle",
           "hex.zero 10, wnt2", "hex.mov 8, wnt2, viewangle",
           "hex.shl_bit 10, wnt", "hex.shl_bit 10, wnt",
           "hex.add 10, wnt, wnt2",
           "hex.shr_hex 10, 6, wnt", "hex.shr_bit 10, wnt",
           "hex.zero 4, wnoff", "hex.mov 4, wnoff, wnt"] if (lines and w1r_flag) else []),
    ]
    if stream or raster:
        # M13pS2-crush2b: per-frame reset of the visplane built-flags (compile-time-unrolled zeroing)
        pass1 += [f"rep({max(1, len(cvp_ids))}, v) hex.zero 1, vpc_flags + v*dw",
                  f"rep({max(1, len(fvp_ids))}, v) hex.zero 1, vpf_flags + v*dw"]
    # M13-bakedbands: lines mode has NO per-frame band state to reset (the lists are static data)
    if raster:
        # M13-wedge: the per-frame half-plane descriptors for the conservative FOV pre-cull (the
        # outward-rounded 45-degree wedge that strictly contains the FOV). Once per frame; the
        # per-seg test that uses them is multiply-free.
        pass1.append("proj.wedge_setup wqa, wna, wqb, wnb, wex, wey, weyx, wexy, viewangle, viewx, viewy")
        pass1.append("present.begin_frame_raster")   # M13-raster: starts the per-frame record stream;
                                                       # the walk below emits vp/seg records INLINE
    if projm:
        # M13-proj: same per-frame wedge descriptors, then the 0x0F frame + the positional 8-byte
        # header (viewx/viewy as signed 16-bit map units -- exactly the parsed vx/vy low bytes --
        # then the 4-byte viewangle); viewz follows from the player-subsector block inside the walk.
        pass1.append("proj.wedge_setup wqa, wna, wqb, wnb, wex, wey, weyx, wexy, viewangle, viewx, viewy")
        pass1 += ["present.begin_frame_proj",
                  "byte.emit vx", "byte.emit vx + 2*dw",
                  "byte.emit vy", "byte.emit vy + 2*dw",
                  "stream.emit_bytes4 viewangle"]
    if lines:
        # M13-lines: wedge descriptors, the descend pre-walk (viewz + band bank), then the 0x0B
        # frame opens BEFORE the walk -- the leaf emits records inline at column-claim time.
        pass1.append("proj.wedge_setup wqa, wna, wqb, wnb, wex, wey, weyx, wexy, viewangle, viewx, viewy")
        pass1 += [f";{_pfx(mapname)}_dsc_walk", "dsc_done:"]
        if wall_mode == "W2S":
            pass1.append("hex.set w/4, wstripbase, wstrips")
        elif wall_mode == "WPX":
            pass1.append("hex.set w/4, wstripbase, wpxstrips")
        pass1.append("present.begin_frame_collines")
    if "pass1" in ablate:                              # M13p0: skip the walk entirely (residue-only measurement)
        pass1.append("bsp_done:")
    else:
        pass1 += [f";{_pfx(mapname)}_bspcode_walk", "bsp_done:"]
    pass2 = []                                            # pass 2a: walls (M12oo shared-compare trampoline)
    if "pass2" not in ablate and not (stream or raster or projm or lines):   # M13p0 ablate / M13pS2: stream/raster have NO fb raster
        for x in range(cfg.VIEW_W):
            pass2.append(f"frame.load_col_mtw col_top + {8 * x}*dw, col_bottom + {8 * x}*dw, col_base + {8 * x}*dw, "
                         f"col_light + {8 * x}*dw, col_step + {8 * x}*dw, col_frac0 + {8 * x}*dw, "
                         f"col_heightmask + {8 * x}*dw")
            for y in range(cfg.H):                                # M12oo: the shared-compare trampoline (y runtime)
                pass2.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")
    # pass 2b: floor/ceiling visplanes (M13d2) — the per-frame clear_planes seeds + the runtime per-ROW
    # R_MakeSpans textured span pass (replaces the M13c3 per-column plane_tramp unroll).
    plane_pass = []
    if two_sided and "noflush" not in ablate:
        # M13-2S rung 3b: the record assembler. One unrolled pass over the columns AFTER the walk --
        # the walk cannot emit any more, because a column's pairs arrive from both ends.
        plane_pass = [f"stream.flush_frame {cfg.VIEW_W}, {TS_ECAP}, colst, colbuf"]
    if "planes" not in ablate and not (stream or raster or projm or lines):   # M13pS2/raster: planes render via bands/device instead
        plane_pass = ["stl.fcall clear_leaf, clear_ret",
                      f"frame.render_planes_spans {cfg.VIEW_W}, {cfg.VIEW_H}"]

    yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
    zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)
    distscale = generate_distscale_lut_fj("distscale", cfg.VIEW_W, cfg.TRIG_N)

    # M13pS2: the stream present -- the frame leaves the program AS the emitted run bytes (device
    # DMA decode); one unrolled emit_column per screen column, every col_* read at a compile-time
    # address. Replaces update_screen_reg + the whole fb/pass-2/plane-pass raster.
    # M13-planesproto: the frame leaves as SHARED per-visplane band lists (each entry's colour
    # cm.emit-mapped ONCE) + one 5-byte record per column -- the device does the per-column
    # prefix/suffix clipping that stream.emit_column paid ~15M fj ops/frame for.
    # col_struct's per-column stride is 11 dw: offset 0 = drawn (packed byte, not read here),
    # 1-10 = cexcl/fstart/lit/cvp/fvp each a 2-nibble-vec pair -- the emit reads each pair's LOW-nibble
    # address (idx/idx+1*dw are its two nibbles).
    _cell = lambda x: (f"col_struct + {11 * x + 1}*dw, col_struct + {11 * x + 3}*dw, "
                       f"col_struct + {11 * x + 5}*dw, col_struct + {11 * x + 7}*dw, col_struct + {11 * x + 9}*dw")
    if raster_mode == "stream":
        present_tail = ["present.begin_frame_planes",
                        f"stl.output_char {max(1, len(cvp_ids))}",
                        f"stream.emit_vp_bank vpc_bufs, {max(1, len(cvp_ids))}, {BAND_STRIDE}",
                        f"stl.output_char {max(1, len(fvp_ids))}",
                        f"stream.emit_vp_bank vpf_bufs, {max(1, len(fvp_ids))}, {BAND_STRIDE}",
                        *(f"stream.emit_column_rec {_cell(x)}" for x in range(cfg.VIEW_W))]
    elif raster_mode == "spans":
        # M13-spanfill: the DUMB-screen present -- fj does the per-column clip itself and emits explicit
        # fillCol [x][y1][y2][colour] records over 0x0A; the device just fills straight vertical strips.
        # Terminated by ONE 0xFF-x sentinel record (VIEW_W=160 < 0xFF, so x is never 0xFF for real).
        present_tail = ["present.begin_frame_spans",
                        *(f"stream.emit_column_spans {x}, {_cell(x)}, vpc_bufs, vpf_bufs, "
                          f"{BAND_STRIDE}" for x in range(cfg.VIEW_W)),
                        "stl.output_char 0xFF"]
    elif raster:
        # M13-raster: the per-seg/per-visplane records were ALREADY emitted inline during the walk
        # (present.begin_frame_raster was prepended to pass1, before the walk jump); present_tail here
        # is JUST the frame terminator (a seg record's own x1 is always < RASTER_TAG_FLOOR_VP=0xFD, so
        # 0xFF can never collide with real data).
        present_tail = ["stl.output_char 0xFF"]
    elif projm:
        # M13-proj: seg ids were emitted inline during the walk; the terminator is [0xFF][0xFF]
        # (a compact id's hi byte is never 0xFF).
        present_tail = ["stl.output_char 0xFF", "stl.output_char 0xFF"]
    elif lines:
        # M13-lines: fillCol records were emitted inline during the walk; one 0xFF x-sentinel
        # ends the frame (x is never 0xFF for real: VIEW_W = 160).
        present_tail = ["stl.output_char 0xFF"]
    else:
        present_tail = ["present.update_screen_reg framebuffer"]
    fb_leaves = [] if (stream or raster or projm or lines) else [          # the fb-raster shared leaves -- stream/raster emit none
        "pixel_leaf:", "frame.leaf_body_w",
        "compare_y:", "frame.compare_y_body",             # M12oo shared pass-2 clip (emitted once)
        "span_leaf:",
        (f"plane.draw_span framebuffer, {cfg.VIEW_W}" if floor_mode == "textured"      # M13d2 textured u,v span
         else f"plane.draw_span_flat framebuffer, {cfg.VIEW_W}"),                      # M13p1 flat-colored span
        "clear_leaf:", f"plane.clear_planes {cfg.CENTERX << 16}, {ANG90}",  # M13d2 per-frame R_ClearPlanes seeds
    ]
    # M13-hotdata (stream only, R20): pointer-deref/dispatch wflip cost scales with the ADDRESS's
    # set bits, so the hot pointer-walked data (per-visplane band buffers, the packed LUTs, the
    # cm/byte EMIT tables) moves from the ~20M-word program tail to just after startup, behind a
    # jump guard (the static tables' own `;end` headers only matter on fall-through, which the
    # guard prevents). Measured: 78.54M -> 76.39M ops/frame, frame byte-identical.
    if stream:
        hotdata = ([";__hot_end"]
                  + _stream_mode_decls(cfg, max(1, len(cvp_ids)), max(1, len(fvp_ids)))
                  + [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle,
                     tex, cm, "__hot_end:"])
    elif raster:
        hotdata = ([";__hot_end"]
                  + _raster_mode_decls(cfg, asset_wad, max(1, len(cvp_ids)), max(1, len(fvp_ids)))
                  + [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle,
                     tex, cm, "__hot_end:"])
    elif projm:
        hotdata = ([";__hot_end"]
                  + _proj_mode_decls(cfg, asset_wad, proj_geom_txt)
                  + [cm, "__hot_end:"])
    elif lines:
        # M-CONSTADDR C7 (R20): the six most pointer-hammered arrays were sitting in the ~34M-word
        # BANKS tail while `drawn`, walked in lockstep with three of them, was already hot. R20:
        # pointer-deref/dispatch wflip cost scales with the ADDRESS's set bits -- the measured
        # hotdata move was 78.54M -> 76.39M ops, frame byte-identical. Nothing here explained the
        # split; the arrays simply post-dated that pass.
        #
        # ⚠ ORDER IS LOAD-BEARING. `selfreset.byte_arrays` derives each byte array's reachable size
        # from the distance to the NEXT LABEL, so every one of these must keep its follower:
        # pclm->sfflag and sfflag->sprflag at VIEW_W cells, sshead->thnext at 2*nss. Reorder them
        # and the build asserts (which is the guard working, but you will have to read this comment
        # to know why).
        _hot_arrays = ([f"pclm:{NLJ}" + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W)),
                        f"sfflag:{NLJ}" + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W)),
                        f"sprflag:{NLJ}" + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W))]
                       + ([f"sshead: hex.vec {2 * _MT_NSS}",
                           f"thnext: hex.vec {2 * _MT_NT}"]
                          # M5: the hosted tier is fed last frame's binding; standalone bakes the
                          # SPAWN one, so bind_things finds every thing clean and still builds the
                          # per-leaf lists it is really there for.
                          + ([NLJ.join(["thss_rt:"]
                                       + [f"    hex.vec 16, {ss}" for ss in _MT_BINDS])]
                             if standalone else [f"thss_rt: hex.vec {16 * _MT_NT}"])
                          if moving_things else []))
        hotdata = ([";__hot_end"] + _hot_arrays
                  + _lines_mode_decls(cfg, rm, asset_wad, lines_vz_classes, lines_bank_keys,
                                      wall_mode in ("W2S", "WPX"))
                  + [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle,
                     tex, cm, ttang, sdrecip, srdisp, xtadisp, vtxdisp, sinadisp, wnoise, wnoise2, wnoise3, w1rpat, skybands, skyoff, skypid,
                     entoff, _collide_tables]
                  # ⚠ appended only when the flag is ON. An unconditional "" still costs a newline,
                  # which changes the shipped text and so its emit hash -- caught by
                  # scratchpad/cr/emit_hash_vs_head.py, which is exactly what that control is for.
                  + ([_mt_tables] if moving_things else []) + ["__hot_end:"])
    else:
        hotdata = []
    # M13-raster: the walk EMITS records inline (present.begin_frame_raster is prepended to pass1,
    # before the walk jump), so present.set_palette + the NEW load_raster_tables address handoff MUST
    # run before pass1 -- otherwise their command bytes would land INSIDE the interleaved raster
    # stream and corrupt it (every other mode buffers-then-emits in present_tail, safely after
    # set_palette). All other modes keep set_palette in its original post-pass1 position.
    if raster:
        yslope_packed_addr, zlight_packed_addr, colormap_packed_addr = (
            "yslope_packed", "zlight_packed", "colormap_packed")
        prelude = ["present.set_palette palette",
                  f"present.load_raster_tables {yslope_packed_addr}, {zlight_packed_addr}, {colormap_packed_addr}"]
        postlude_palette = []
    elif projm:
        # M13-proj: same inline-emission constraint as raster -- palette + BOTH DMA handoffs must
        # precede pass1's begin_frame_proj.
        prelude = ["present.set_palette palette",
                  "present.load_raster_tables yslope_packed, zlight_packed, colormap_packed",
                  f"present.load_proj_tables seg_geom, {len(proj_sid)}"]
        postlude_palette = []
    elif lines:
        # M13-lines: inline emission during the walk => palette must precede pass1.
        prelude = ["present.set_palette palette"]
        postlude_palette = []
    else:
        prelude = []
        postlude_palette = ["present.set_palette palette"]
    # ── PARTITIONED EMISSION ────────────────────────────────────────────────────────────
    # The emitted program is built as ORDERED, NAMED PARTS instead of one 107M-char blob, so
    # the huge generated regions (LUT/dispatch tables, per-seg constant blocks, the BSP walk,
    # the baked banks) assemble as their OWN FILES and the file holding the actual program
    # stays small and readable. ⚠ ORDER IS LOAD-BEARING and the parts are NOT reordered:
    # concatenating them in this order reproduces the previous single-file text BYTE FOR
    # BYTE (asserted by scratchpad/cr/emit_hash.py), so the assembled binary is unchanged.
    # A consequence of not reordering: a few small declarations that sit after the first
    # big array in the original order ride along in the "banks" part rather than "state".
    _parts = [
      ("entry", [
        "// == GENERATED PROGRAM: label vocabulary ==================================",
        "//   ss<c>_visit / _occluded        a subsector's per-seg block; _occluded = the screen",
        "//                                  was already full when the walk reached it",
        "//   ss<c>_seg<s>_mark / _marked    a MARKING (two-sided) seg: attribution + step faces",
        "//   ss<c>_seg<s>_unseen            pass 1 said this one-sided seg is not visible,",
        "//                                  so pass 2 is skipped",
        "//   ss<c>_thing<t>_do / _skip      a sprite, gated by the per-frame thing budget",
        "//   seg<s>_geom_consts             pass-1 constants (vertices + affine coeffs)",
        "//   seg<s>_render_consts           pass-2 constants (angle, heights, light)",
        "//   seg<s>_attrib_consts           a marking seg's plane-attribution constants",
        "//   seg<s>_face_consts             its step-face (riser/lip) constants",
        "//   thing<ss>_<t>_consts           a sprite's constants. ⚠ <ss> is the SUBSECTOR index,",
        "//                                  NOT the <c> above: <c> counts EMISSIONS (a leaf is emitted",
        "//                                  once per parent branch) while this block is deduped per",
        "//                                  subsector, so the two numbers differ.",
        "//     ^ every *_consts block is fcall'd TWICE -- SET then CLEAR. It is built from",
        "//       hex.xor_by, and xor is an involution (x^v^v = x), so the second call restores",
        "//       the registers to zero for the next seg. Deleting the CLEAR corrupts every",
        "//       seg after the first.",
        "//   <map>_bspcode_node<n>          one BSP node: the baked partition line's side test",
        "//     ..._open                     not occluded -> do the test",
        "//     ..._far                      the far child (the near child is visited first)",
        "//     ..._partition                its partition constants (SET/CLEAR, same involution)",
        "//     ..._ret                      its fcall return register",
        "//     ..._planes_live / _planes_dead   runtime skip for a subtree that can no longer",
        "//                                      contribute plane attribution or pieces",
        "//   <map>_dsc_node<n>              the descend-only pre-walk that locates the eye",
        "//   vpb_*                          the baked visplane band-list walker (generated by",
        "//                                  lut_generator; ~1.2M labels, machine-read only)",
        "// =========================================================================",
        "stl.startup_and_init_all",
        *hotdata[:1],                                  # the `;__hot_end` jump over the tables
      ]),
      ("tables", [
        *hotdata[1:],                                  # shared decls + trig/reciprocal LUTs + dispatch tables
      ]),
      ("main", [
          # M5: standalone is run by the plain `fj` CLI, whose stock InMemoryScreen wants the
          # 8-byte init. `flush_mode` governs only the 0x07 pixel-stream mode, which the 0x0B
          # frames this tier presents do not use, so dropping it costs the picture nothing.
          "present.init_screen" if standalone else
          ("present.init_screen_stream 0" if (stream or raster or projm or lines) else "present.init_screen"),
          *prelude,
          *pass1, *pass2, *plane_pass,
          *postlude_palette, *present_tail, "stl.loop",
          "bad: stl.loop",
          *fb_leaves,
          *((["seg_pass1_leaf:", "stl.fret seg_ret"]
             + (["seg_pass2_leaf:", "stl.fret seg_ret2"] if lines else [])) if "segstub" in ablate else
            # M13-wedge attribution: segstub + the wedge test only. (segstub - wedgestub)/segs gives the
            # test's true in-context unit cost; both walk the WHOLE tree (`full` is never set).
            (["seg_pass1_leaf:",
              "proj.wedge_reject wrej, seg_v1x, seg_v1y, seg_v2x, seg_v2y, wqa, wna, wqb, wnb, wex, wey, weyx, wexy",
              "stl.fret seg_ret"]
             + (["seg_pass2_leaf:", "stl.fret seg_ret2"] if lines else [])) if "wedgestub" in ablate else
            (["seg_pass1_leaf:", "hex.if0 1, full, xrs_work", "stl.fret seg_ret",
              "xrs_work:", "hex.zero 1, visible", "stl.fret seg_ret"]
             # lines mode fcalls a pass-2 leaf too, so the stub ladder has to define one (it is never
             # reached: part 1 always leaves `proceed` = 0 here).
             + (["seg_pass2_leaf:", "stl.fret seg_ret2"] if lines else [])) if "xrstub" in ablate else
            ["seg_pass1_leaf:", f"frame.seg_pass1_leaf_body_raster {proj}"]
            if raster else
            ["seg_pass1_leaf:", "frame.seg_pass1_leaf_body_proj"]
            if projm else
            ["seg_pass1_leaf:", f"frame.seg_pass1_leaf_body_lines {atan_dbl}, {slope_dbl}, {table_dbl}, "
             f"{1 if 'noprescan' in ablate else 0}",
             *(["expand_leaf:",
                f"stream.entry_expand_body {cfg.CENTERY}, {LINES_HALF_SLOTS}, "
                f"{2 * WPX_RUN_CAP}, {(cfg.VIEW_H + 1) * 2 * WPX_RUN_CAP}"] if two_sided else []),
             # CR-2026-08: the deg attribution budget must provably never bind (a binding budget
             # = the smudged-column bug) -- n_ts counts a subset of the map's segs, so total segs
             # below the baked cap is the sufficient condition. 4095 is also the 3-nibble
             # counter's max, enforced together here.
             *([_assert_pnear_unbound(deg, len(cmap.segs)), "seg_pass1_ts_leaf:",
                f"frame.seg_pass1_leaf_body_ts {DEG_PNEAR if deg else PNEAR_SEG_BUDGET}, {atan_dbl}, {slope_dbl}, "
                f"{table_dbl}, {1 if steps else 0}, {STEP_SEG_BUDGET}, {cfg.CENTERY * 0x10000}, "
                f"{cfg.VIEW_H - 1}, {proj}, {STEP_SLOT_STRIDE}, {stack_flag}, {deg_flag}, "
                f"{DEG_STACK_SCALE}, {1 if DEG_DDA_FACES else 0}, {DEG_LIP_SCALE}"] if plane_near else []),
             # CR-2026-08: project_thing's istep/downscale is a compile-time SHIFT by
             # log2(ds) (`rep(#ds - 1, ...)`), exact only for power-of-two downscales.
             *([_assert_pow2_ds(cfg.TEXTURE_DOWNSCALE),
                # M14.5: up to TWO bodies. `mt` is a COMPILE-TIME rep, so a build that has both
                # baked call sites and a runtime list cannot share one -- the baked one must not
                # read a cold row it has no index into, and the runtime one must. Same macro, same
                # arguments but `mt`; the duplicate is program TEXT, not per-frame ops.
                *_thing_leaf_body("thing_leaf", 1 if moving_things else 0),
                *(_thing_leaf_body(_baked_leaf, 0) if _emit_baked_leaf else [])]
               if _do_things else []),
             # M14-e: the ONE thing walk every leaf calls, in place of its baked per-thing blocks
             *(["thing_pass_leaf:",
                f"sim.thing_pass throw, {_MT_NTH}, thpos_rt",
                "stl.fret tp_ret"] if moving_things else []),
             "seg_pass2_leaf:",
             (f"frame.seg_pass2_leaf_body_2s {cfg.CENTERY}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}, "
              f"{LINES_HALF_SLOTS}, {TS_ECAP}, {1 if 'colstub' in ablate else 0}") if two_sided else
             (f"frame.seg_pass2_leaf_body_lines {cfg.CENTERY}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}, "
              f"{LINES_HALF_SLOTS}, {w2s_flag}, {wpx_flag}, {w1r_flag}, {2 * WPX_RUN_CAP}, {pnear_flag}, "
              f"{eabl_flag}, {1 if 'noproj' in ablate else 0}, "
              f"{1 if 'projtwice' in ablate else 0}, {1 if 'scaletwice' in ablate else 0}, "
              f"{1 if wall_noise else 0}, {1 if sky else 0}, {2 * LINES_HALF_SLOTS}, "
              f"{1 if 'skyall' in ablate else 0}, {1 if steps else 0}, "
              f"{1 if _do_things else 0}, {SPR_BLOCK_STRIDE.bit_length() - 1}, "
              f"{0 if 'sprnoemit' in ablate else 1}, {ascode}, {sky_base_id}, {stack_flag}, "
              f"{deg_flag}, {DEG_SLIVER_W}")]
            if lines else
            ["seg_pass1_leaf:",
             f"frame.seg_pass1_leaf_body_stream {cfg.CENTERY}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}, {BAND_STRIDE}"]
            if stream else
            ["seg_pass1_leaf:",
             f"frame.seg_pass1_leaf_body_mtlwp {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}"]),
          # the stub ablations replace the lines leaves wholesale, so the two-sided claim leaf the
          # plane_near call sites jump to has to be stubbed alongside them (measurement only).
          *(["seg_pass1_ts_leaf:", "stl.fret seg_ret"]
            if (plane_near and (ablate & {"segstub", "xrstub", "wedgestub"})) else []),
          # M13-15M: the bbox wedge gate's shared test leaf -- corners staged per node via xor_by
          *(["bbgate_leaf:",
             "proj.wedge_bbox bbvis, bbcl, bbcb, bbcr, bbct, wqa, wna, wqb, wnb, "
             "wex, wey, weyx, wexy",
             "stl.fret bbtret"] if bbox_gate else []),
      ]),
      ("segconsts", [
          *xorby,                                           # M12pp: the shared per-seg xorby blocks (fcall'd SET/CLEAR)
      ]),
      ("walk", [
          bsp,
          _collide_descend,          # M14-d: the candidate-position point location
          # M14-e: the per-thing point location, baked as code -- conditional for the same reason
          # the tables above are: an unconditional "" is still a newline the shipped text lacks
          *([_mt_ptloc] if moving_things else []),
      ]),
      ("state", [
          *([] if (stream or raster or projm or lines) else [f"framebuffer: hex.vec {2 * cfg.FB_SIZE}"]),   # no fb in stream/raster/proj mode
          "vx: hex.vec 10", "vy: hex.vec 10",
          # M5: the standalone tier BAKES the player start into the view state, because nothing
          # else ever writes it: there is no wire, the sim only ever adds a delta to it, and the
          # M1 reset is told to leave it alone (build.STANDALONE_PERSIST). So this declaration IS
          # the initial condition of the game, and every later frame is the sim's own doing.
          *([f"viewx: hex.vec 8, {_spawn.x & 0xFFFFFFFF}",
             f"viewy: hex.vec 8, {_spawn.y & 0xFFFFFFFF}",
             f"viewangle: hex.vec 8, {_spawn.angle & 0xFFFFFFFF}"] if standalone else
            ["viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8"]),
          *_collide_decls,                                  # M14-d collision state
          *HOISTED_SCRATCH_DECLS,                           # M1-HOIST: ex-@-local storage
          # M14-b: the binary state wire's magic byte + the frame's key byte (both 1 byte = 2
          # nibbles). M5: standalone has no wire and so no magic byte, but it still builds `pkeys`.
          *(["pkeys: hex.vec 2"] if standalone else
            (["wmagic: hex.vec 2", "pkeys: hex.vec 2"] if state_wire == "bin" else [])),
          # M5: the keyboard poll's scratch, and the four PERSISTENT held-key flags. The flags are
          # the only cells besides the view state that the M1 reset must leave alone.
          *(STANDALONE_SCRATCH_DECLS if standalone else []),
          # M14-c: the player tic's scratch -- the signed 16.16 move magnitude, the
          # finesine index it is projected through, and the two 16.16 deltas
          *(["pmove: hex.vec 8", "pangt: hex.vec 8", "pangi: hex.vec 3",
             "pmvc: hex.vec 8", "pmvs: hex.vec 8",
             "pmvdx: hex.vec 8", "pmvdy: hex.vec 8"] if player_sim else []),
          # the shared affine-distance output of wall_x_range (consumed by wall_setup_sgn as
          # rw_distance-pre-abs). ⚠ CR-2026-08 (PJ-2) removed viewxa/viewxs/viewya/viewys from
          # here; `sgn_aff` is NOT dead with them -- it is the OUTPUT, read at 10 call sites.
          "sgn_aff: hex.vec 8",
          "viewz: hex.vec 8", "viewzw: hex.vec 8", "vz_set: hex.vec 1",
          "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
          "seg_segangle: hex.vec 8", "seg_a: hex.vec 8", "seg_b: hex.vec 8", "seg_c: hex.vec 8",  # perf #9
          "seg_texoff: hex.vec 8",
          "seg_texbase: hex.vec 5", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
          "seg_light: hex.vec 2", "xb_ret: ;0",             # M12pp: xorby block fcall/fret return register
          *(["bbcl: hex.vec 8", "bbcb: hex.vec 8", "bbcr: hex.vec 8", "bbct: hex.vec 8",
             "bbvis: hex.vec 1", "bbtret: ;0"] if bbox_gate else []),   # M13-15M bbox wedge gate
          "ceilfix: hex.vec 8", "floorfix: hex.vec 8",
          "seg_ceil: hex.vec 8", "worldtop: hex.vec 8",     # M12pp: seg_ceil baked (pure); worldtop leaf-computed
          "seg_floor: hex.vec 8", "seg_plight: hex.vec 2",  # M13d2 plane bakes (pure floor_h + raw light + flat slices)
          "seg_ceilbase: hex.vec 5", "seg_floorbase: hex.vec 5",   # 5-nib flat slice offsets
          "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
          "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
          "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
          "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 5",
          "seg_ret: ;0",
          "top: hex.vec 8", "bottom: hex.vec 8",
          "y: hex.vec 2", "ret_reg: ;0",                    # M12oo trampoline: runtime row counter + shared return reg
          "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 5", "cmidx: hex.vec 4",
          "lit: hex.vec 2", "base_reg: hex.vec 5", "step: hex.vec 4",
          "heightmask: hex.vec 3", "pixel_ret: ;0",
          # M13d2 pass-2b textured-plane registers (render_planes_spans sets these per span; draw_span reads them)
          "planeheight: hex.vec 8", "light: hex.vec 2", "flatbase: hex.vec 5",
          "basexscale: hex.vec 8", "baseyscale: hex.vec 8",   # per-frame R_ClearPlanes seeds (clear_leaf)
          "span_ret: ;0", "clear_ret: ;0",
          # M13opt2 span-scan state + classify scratch (globals shared by render_planes_spans + plane_col)
          "inspan: hex.vec 1", "spanR: hex.vec 2", "spanph: hex.vec 8", "spanfb: hex.vec 5",
          "spanlt: hex.vec 2", "spanx1: hex.vec 2", "cR: hex.vec 2", "cph: hex.vec 8", "cfb: hex.vec 5",
          "clt: hex.vec 2", "cexcl: hex.vec 2", "fstart: hex.vec 2",
          f"col_top: rep({cfg.VIEW_W}, i) hex.vec 8, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          f"col_base: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          f"col_light: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          # M13c3 per-column plane param arrays (8-nibble stride, written by store_col_field/8)
          f"col_cexcl: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_fstart: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          f"col_ceil_ph: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_floor_ph: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          f"col_plight: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_ceilbase: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          f"col_floorbase: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
          # M13-raster/lines declare their OWN packed-byte `drawn` (stride 1, in their hotdata decls)
          # -- this shared nibble-vec (stride 4) declaration is for fb-mode/stream-mode only.
          *([] if (raster or lines) else [f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0"]),
          # M13opt-P1 byte-exact early-out: count claimed columns; `full` short-circuits later (occluded) segs.
          "n_drawn: hex.vec 2", "full: hex.vec 1", f"vieww: hex.vec 2, {cfg.VIEW_W}",
          # M13-2S rung 3a: the per-column PLANE ATTRIBUTION state -- ONE byte per column holding the
          # claiming seg's plane-pair id (0 = not attributed yet), a stride-1 packed-byte array walked
          # in lockstep with `drawn`. `tsstop` = attribution can no longer change (every column done,
          # or the seg budget spent) -- the early-out that makes
          # the extra two-sided walk affordable.
          # M13-2S rung 3b: per column [chi][flo][tcnt][bcnt] (the window's exclusive-end row bounds
          # and the bytes used in its two pair buffers), plus the buffers themselves -- tcap bytes of
          # TOP pairs then bcap of BOTTOM blocks. A column can never hold more than VIEW_H pairs in
          # total (each pair advances the fill cursor by >= 1 row), so 2*VIEW_H bytes per side plus a
          # length trailer per block is a hard bound, not a guess.
      ]),
      ("banks", [
          *([f"colst:{NLJ}" + NLJ.join(NLJ.join([";0x0 * dw", f";{cfg.VIEW_H:#x} * dw",
                                                 ";0x0 * dw", ";0x0 * dw"])
                                       for _ in range(cfg.VIEW_W)),
             f"colbuf:{NLJ}" + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W * 10 * TS_ECAP)),
             "cstp: hex.vec w/4", "cbfp: hex.vec w/4", "tptr: hex.vec w/4", "bptr: hex.vec w/4",
             "chi: hex.vec 2", "flo: hex.vec 2", "tcnt: hex.vec 2", "bcnt: hex.vec 2",
             "bcnt0: hex.vec 2", "seg_flags: hex.vec 3",
             "bceilfix: hex.vec 8", "bfloorfix: hex.vec 8",
             "seg_wsupper: hex.vec 4", "seg_wslower: hex.vec 4",
             "eptr: hex.vec w/4", "exp_ret: ;0",
             "cbufa: hex.vec w/4", "cbufd: hex.vec w/4",
             "fbufa: hex.vec w/4", "fbufd: hex.vec w/4"] if two_sided else []),
          *([             "pbase: hex.vec w/4", "pptr: hex.vec w/4", "pval8: hex.vec 2",
             # n_tsv is 3 nibbles: the deg attribution budget is DEG_PNEAR=4095 (its max), with
             # never-binds ENFORCED by _assert_pnear_unbound -- see seg_pass1_leaf_body_ts
             "n_claimed: hex.vec 2", "n_tsv: hex.vec 3", "tsstop: hex.vec 1",
             "tsbstop: hex.vec 1",              # V5-DROP-P2b: the budget-only latch
             # SMUDGE FIX part 2: the faces-spent latch. Declared under `lines` (NOT lines+steps,
             # CR-2026-08: the piece-seg call sites reference it in every plane_near build) --
             # a steps=0 build leaves it permanently 0, which matches the oracle: with
             # near_steps off, n_face never fills so the idle stop never fires.
             "fbspent: hex.vec 1",
             "viewh_stub: hex.vec 2, 100",
             "cpid: hex.vec 2",
             # the UNATTRIBUTED-COLUMN WINDOW: every column < pmin or > pmax is attributed already
             "pmin: hex.vec 2, 0", f"pmax: hex.vec 2, {cfg.VIEW_W - 1}"] if lines else []),
          # V3 step faces: the per-column WRITE-ONCE slots. `sfflag[x]` is one byte (nibble 0 = an
          # upper face is stored, nibble 1 = a lower one) so a column with no face costs ONE read on
          # the emit path; `sfslot[x]` holds [uy1][uy2][ucls][ly1][ly2][lcls] at a power-of-16 stride
          # so its byte offset is a whole-nibble shift. `n_face` is the per-frame SEG budget counter
          # (STEP_SEG_BUDGET) -- separate from n_tsv, because it must count only the boundaries that
          # actually pay a wall_scale_setup_m.
          *([             f"sfslot:{NLJ}" + NLJ.join(";0 * dw"
                                        for _ in range(cfg.VIEW_W * STEP_SLOT_STRIDE)),
             "n_face: hex.vec 2", "seg_fmask: hex.vec 2",
             "seg_uh1: hex.vec 4", "seg_uh2: hex.vec 4",
             "seg_lh1: hex.vec 4", "seg_lh2: hex.vec 4",
             "seg_ucls: hex.vec 2", "seg_lcls: hex.vec 2",
             "seg_bpid: hex.vec 2",                # V5: the boundary's baked BACK pair id
             stepcol] if (lines and steps) else []),
          # V4 THINGS: the per-column write-once SPRITE FRAGMENT. `sprflag[x]` is one byte (nonzero =
          # this column carries one) so a column without a sprite costs ONE read on the emit path;
          # `spslot[x]` holds [sy1][sy2p1][y0+128][blk_lo][blk_hi][shade row] at a power-of-16 stride.
          # `y0` is BIASED by 128 because a near sprite's top sits above row 0 and the slot is bytes;
          # h <= VIEW_H bounds it to +-99. `n_thing`/`tstop` are the budget and its monotone early-out.
          *([             f"spslot:{NLJ}" + NLJ.join(";0 * dw"
                                        for _ in range(cfg.VIEW_W * SPR_SLOT_STRIDE)),
             "n_thing: hex.vec 2", "n_mon: hex.vec 2", "tstop: hex.vec 1", "thing_ret: ;0",
             "sp_x: hex.vec 8", "sp_y: hex.vec 8", "sp_z: hex.vec 8",
             "sp_left: hex.vec 8", "sp_w: hex.vec 8", "sp_hh: hex.vec 8",
             "sp_base: hex.vec 4", "sp_dw: hex.vec 2", "sp_lt: hex.vec 2",
             "sp_tzmax: hex.vec 8", "sp_mon: hex.vec 2",
             # M14-perf: the thing INDEX the hot load ran on, so the deferred cold load can read
             # its row after the reject. Declared unconditionally (it costs w/4 nibbles) because
             # `frame.thing_load_cold` externs it, and an extern with no global is an assembler
             # error even on the static path where the macro is never instantiated.
             "sp_ti: hex.vec w/4",
             "sp_tzmax2: hex.vec 8",             # 25M-CAP: the raised min-size depth bound
             "sp_base2: hex.vec 4",              # OPTION B: the low-res LD region base
             "n_hd: hex.vec 2", "hdfl: hex.vec 1",      # ... its budget counter + per-thing flag
             "degfl: hex.vec 1", "ballow: hex.vec 1",   # ... and the per-thing runtime flags
             "thfar: hex.vec 1",                 # SPR-NEAR: beyond the detail radius?
             *_mt_decls,                         # M14-e: the runtime table's state + point location
             sprbkt, sprlight, sprbank] if _do_things else []),
          *([_lines_bake_bank(rm, cfg, asset_wad, lines_vz_classes, lines_bank_keys,
                              floor_mode == "FT1")] if (lines and not ascode) else []),
          *([bands_code] if ascode else []),
          *([lines_wstrip_txt] if lines_wstrip_txt else []),
          *([] if (stream or raster or projm or lines) else      # M13-hotdata: in stream/raster/proj mode these sit up front
            [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle, tex, cm]),
          palette,
          yslope, zlight, distscale, flat_table,        # M13d2 textured-floor LUTs + combined flat table
      ]),
    ]
    _texts = [(n, chr(10).join(g)) for n, g in _parts if g]
    main = chr(10).join(t for _, t in _texts)
    return (_texts if return_parts else main)


# ── M1-HOIST: macro `@`-local STORAGE, promoted to named globals ─────────────────────────────────
# An `@`-local has no name outside its macro: it is one cell PER EXPANSION, so the assembler names
# it by the expansion path (`f<file>:l<line>:macro(arity)---local`). The M1 restore set is keyed on
# those, and they break on any line or arity drift -- 313 of 344 keys needed re-keying for LINE
# NUMBERS ALONE (2026-08-25). Promoting the storage to a global gives it a PERMANENT name, so the
# set stops naming anything positional.
#
# COSTS NOTHING. An `@`-local is already a baked constant address; a global is the same address with
# a name, so the emitted op is identical. `deg_gate` certifies exactly that -- byte-exact pixels AND
# op counts identical to the digit.
#
# ⚠ ONLY SOUND BECAUSE EVERY MACRO HERE IS INSTANTIATED ONCE. With one expansion, one cell either
# way. A macro with N live expansions would need a compile-time index (`base + i*dw`) instead of a
# shared cell; scratchpad/m1_hoist.py refuses those unless the caller has checked they may share.
#
# Generated by: python scratchpad/m1_hoist.py --file F --macro M --prefix P
HOISTED_SCRATCH_DECLS = [
    # ROUND 1: single-instantiation macros (exact by construction)
    "p2_cVH: hex.vec 8",
    "p2_cbufa: hex.vec w/4",
    "p2_cbufd: hex.vec w/4",
    "p2_cexcl: hex.vec 8",
    "p2_cw16: hex.vec 2, 16",
    "p2_dbot: hex.vec 8",
    "p2_dcexcl: hex.vec 2",
    "p2_dfstart: hex.vec 2",
    "p2_dgn: hex.vec 2",
    "p2_dgn2: hex.vec 2",
    "p2_dgn3: hex.vec 2",
    "p2_dl1bp: hex.vec 2",
    "p2_dl1cls: hex.vec 2",
    "p2_dl1y1: hex.vec 2",
    "p2_dl1y2: hex.vec 2",
    "p2_dl2bp: hex.vec 2",
    "p2_dl2cls: hex.vec 2",
    "p2_dl2y1: hex.vec 2",
    "p2_dl2y2: hex.vec 2",
    "p2_dlcnt: hex.vec 2",
    "p2_dlcol: hex.vec 2",
    "p2_dly1: hex.vec 2",
    "p2_dly2: hex.vec 2",
    "p2_dpid: hex.vec 2",
    "p2_dsblk: hex.vec 4",
    "p2_dsblkb: hex.vec 4",
    "p2_dscale: hex.vec 8",
    "p2_dsoff: hex.vec 2",
    "p2_dsstep: hex.vec 8",
    "p2_dssy1: hex.vec 2",
    "p2_dssy1b: hex.vec 2",
    "p2_dssy2: hex.vec 2",
    "p2_dssy2b: hex.vec 2",
    "p2_dsy0b: hex.vec 4",
    "p2_dsy0bb: hex.vec 4",
    "p2_dtop: hex.vec 8",
    "p2_du1bp: hex.vec 2",
    "p2_du1cls: hex.vec 2",
    "p2_du1y1: hex.vec 2",
    "p2_du1y2: hex.vec 2",
    "p2_du2bp: hex.vec 2",
    "p2_du2cls: hex.vec 2",
    "p2_du2y1: hex.vec 2",
    "p2_du2y2: hex.vec 2",
    "p2_ducnt: hex.vec 2",
    "p2_ducol: hex.vec 2",
    "p2_duy1: hex.vec 2",
    "p2_duy2: hex.vec 2",
    "p2_dvalid: hex.vec 1",
    "p2_face_flags: hex.vec 2",
    "p2_fbufa: hex.vec w/4",
    "p2_fbufd: hex.vec w/4",
    "p2_fstart: hex.vec 8",
    "p2_gnrow: hex.vec 2",
    "p2_issky: hex.vec 2",
    "p2_lcol: hex.vec 2",
    "p2_lfl: hex.vec 1",
    "p2_ly1: hex.vec 2",
    "p2_ly2p1: hex.vec 2",
    "p2_one: hex.vec 2",
    "p2_sblk: hex.vec 4",
    "p2_sblkb: hex.vec 4",
    "p2_skb: hex.vec 2",
    "p2_sliver_cap: hex.vec 2",
    "p2_sliver_w: hex.vec 2",
    "p2_slr: hex.vec 2",
    "p2_slrb: hex.vec 2",
    "p2_soff: hex.vec 2",
    "p2_sprfl: hex.vec 2",
    "p2_ssy1: hex.vec 2",
    "p2_ssy1b: hex.vec 2",
    "p2_ssy2: hex.vec 2",
    "p2_ssy2b: hex.vec 2",
    "p2_sy0b: hex.vec 4",
    "p2_sy0bb: hex.vec 4",
    "p2_ucol: hex.vec 2",
    "p2_ufl: hex.vec 1",
    "p2_uy1: hex.vec 2",
    "p2_uy2p1: hex.vec 2",
    "p2_wlen: hex.vec 2",
    "p2_wtc8: hex.vec 8",
    "p2_wtf8: hex.vec 8",
    "p2_xkey: hex.vec 4",
    "tsf_col_x: hex.vec 8",
    "tsf_cviewh1: hex.vec 8",
    "tsf_drawn_b: hex.vec w/4",
    "tsf_drawn_p: hex.vec w/4",
    "tsf_drawn_v: hex.vec 2",
    "tsf_face_cap: hex.vec 2",
    "tsf_face_dist: hex.vec 8",
    "tsf_face_norm: hex.vec 8",
    "tsf_face_scale: hex.vec 8",
    "tsf_face_scalestep: hex.vec 8",
    "tsf_fmode: hex.vec 1",
    "tsf_frac_l1: hex.vec 8",
    "tsf_frac_l2: hex.vec 8",
    "tsf_frac_u1: hex.vec 8",
    "tsf_frac_u2: hex.vec 8",
    "tsf_out_y1: hex.vec 8",
    "tsf_out_y2: hex.vec 8",
    "tsf_row_a: hex.vec 8",
    "tsf_row_b: hex.vec 8",
    "tsf_sfflag_b: hex.vec w/4",
    "tsf_sfflag_p: hex.vec w/4",
    "tsf_sfflag_v: hex.vec 2",
    "tsf_sfslot_b: hex.vec w/4",
    "tsf_sfslot_p: hex.vec w/4",
    "tsf_slot_idx: hex.vec w/4",
    "tsf_step_l1: hex.vec 8",
    "tsf_step_l2: hex.vec 8",
    "tsf_step_u1: hex.vec 8",
    "tsf_step_u2: hex.vec 8",
    "tsf_wtl1: hex.vec 8",
    "tsf_wtl2: hex.vec 8",
    "tsf_wtu1: hex.vec 8",
    "tsf_wtu2: hex.vec 8",
    "ecl_ccy: hex.vec 2",
    "ecl_cmidx: hex.vec 4",
    "ecl_colr: hex.vec 2",
    "ecl_ctake: hex.vec 2",
    "ecl_ent_i: hex.vec 2",
    "ecl_full_hi: hex.vec 2",
    "ecl_full_lo: hex.vec 2",
    "ecl_n_ent: hex.vec 2",
    "ecl_ptr: hex.vec w/4",
    "ecl_spr_bot: hex.vec 2",
    "ecl_spr_top: hex.vec 2",
    "ecl_whi: hex.vec 2",
    "ecl_win_end: hex.vec 2",
    "ecl_win_hi: hex.vec 2",
    "ecl_win_lo: hex.vec 2",
    "ecl_wlen: hex.vec 2",
    "ecl_wlo: hex.vec 2",
    "ecl_y2r: hex.vec 2",
    "ws_angt: hex.vec 8",
    "ws_c1: hex.vec 1, 1",
    "ws_c2: hex.vec 1, 2",
    "ws_c4: hex.vec 1, 4",
    "ws_c6: hex.vec 1, 6",
    "ws_cang45: hex.vec 8, 0x20000000",
    "ws_cang90m1: hex.vec 8, 0x3FFFFFFF",
    "ws_mdir: hex.vec 1",
    "ws_nout: hex.vec 1",
    "ws_qout: hex.vec 1",
    "pos_dxv: hex.vec 10",
    "pos_dxv_mag: hex.vec 8",
    "pos_dyv: hex.vec 10",
    "pos_dyv_mag: hex.vec 8",
    "pos_p1: hex.vec 8",
    "pos_p2: hex.vec 8",
    "pos_signA: hex.vec 1",
    "pos_signB: hex.vec 1",
    "pos_sign_dxv: hex.vec 1",
    "pos_sign_dyv: hex.vec 1",
    "cpm_c_centeryfix: hex.vec 8",
    "cpm_c_viewh1: hex.vec 8",
    "cpm_consts_set: hex.vec 1",
    "cpm_prod: hex.vec 8",

    # ROUND 2 (under bisection): multi-instantiation macros sharing one cell each
    "trb_blk: hex.vec w/4",
    "trb_blk_const: hex.vec w/4",
    "trb_blk_ofs: hex.vec w/4",
    "trb_bucket: hex.vec 4",
    "trb_bucket_h: hex.vec 8",
    "trb_cbound: hex.vec 8",
    "trb_climit: hex.vec 2",
    "trb_col_x: hex.vec 8",
    "trb_drawn_b: hex.vec w/4",
    "trb_drawn_p: hex.vec w/4",
    "trb_drawn_v: hex.vec 2",
    "trb_dthp: hex.vec 8",
    "trb_dtis: hex.vec 8",
    "trb_dtx1: hex.vec 8",
    "trb_dtx2: hex.vec 8",
    "trb_dtyt: hex.vec 8",
    "trb_dvis: hex.vec 1",
    "trb_dw_max: hex.vec 2",
    "trb_frac_u: hex.vec 8",
    "trb_negx1: hex.vec 8",
    "trb_run_last: hex.vec 2",
    "trb_run_r0: hex.vec 2",
    "trb_run_w8: hex.vec 8",
    "trb_shade_row: hex.vec 2",
    "trb_slot_flag: hex.vec 2",
    "trb_slot_ofs: hex.vec w/4",
    "trb_sprflag_b: hex.vec w/4",
    "trb_sprflag_p: hex.vec w/4",
    "trb_sprflag_v: hex.vec 2",
    "trb_sy1: hex.vec 8",
    "trb_sy2: hex.vec 8",
    "trb_tab_idx: hex.vec w/4",
    "trb_tbl_b: hex.vec w/4",
    "trb_tbl_p: hex.vec w/4",
    "trb_thpx: hex.vec 8",
    "trb_tistep: hex.vec 8",
    "trb_tx1: hex.vec 8",
    "trb_tx2: hex.vec 8",
    "trb_tytop: hex.vec 8",
    "trb_u: hex.vec 8",
    "trb_vis: hex.vec 1",
    "trb_y0: hex.vec 8",
    "trb_y0_biased: hex.vec 8",
    "trb_y_base: hex.vec 8",
    "wxr_adup: hex.vec 8",
    "wxr_ang1: hex.vec 8",
    "wxr_ang2: hex.vec 8",
    "wxr_c2clip: hex.vec 8, 0x40000000",
    "wxr_cclip: hex.vec 8, 0x20000000",
    "wxr_cnegclip: hex.vec 8, 0xE0000000",
    "wxr_diff: hex.vec 8",
    "wxr_sgn_b: hex.vec 8",
    "wxr_span: hex.vec 8",
    "wxr_tspan: hex.vec 8",
    "wxr_tx1: hex.vec 8",
    "wxr_tx2: hex.vec 8",
    "pth_ang: hex.vec 8",
    "pth_c_centerxfix: hex.vec 8",
    "pth_c_centeryfix: hex.vec 8",
    "pth_c_viewh: hex.vec 8",
    "pth_c_vieww: hex.vec 8",
    "pth_cproj: hex.vec 8",
    "pth_czlim: hex.vec 8",
    "pth_gxt: hex.vec 8",
    "pth_gyt: hex.vec 8",
    "pth_gzt: hex.vec 8",
    "pth_one16: hex.vec 8",
    "pth_sin_idx: hex.vec 3",
    "pth_tmp: hex.vec 8",
    "pth_tr_x: hex.vec 8",
    "pth_tr_y: hex.vec 8",
    "pth_trig_cached: hex.vec 1",
    "pth_tx: hex.vec 8",
    "pth_tx_abs: hex.vec 8",
    "pth_tx_left: hex.vec 8",
    "pth_tx_right: hex.vec 8",
    "pth_tz: hex.vec 8",
    "pth_tz_lim: hex.vec 8",
    "pth_vcos: hex.vec 8",
    "pth_vsin: hex.vec 8",
    "pth_xscale: hex.vec 8",
    "ssc_ceil_end: hex.vec 2",
    "ssc_rcbufa: hex.vec w/4",
    "ssc_rcbufd: hex.vec w/4",
    "ssc_rfbufa: hex.vec w/4",
    "ssc_rfbufd: hex.vec w/4",
    "ssc_rlo2: hex.vec 2",
    "ssc_ucnt2: hex.vec 1",
    "ssc_win_end: hex.vec 2",
    "ssc_win_lo: hex.vec 2",
    "ssc_zero_row: hex.vec 2",
    "ssf_cviewh: hex.vec 2",
    "ssf_floor_end: hex.vec 2",
    "ssf_floor_lo: hex.vec 2",
    "ssf_fstart2: hex.vec 2",
    "ssf_lcnt2: hex.vec 1",
    "ssf_rcbufa: hex.vec w/4",
    "ssf_rcbufd: hex.vec w/4",
    "ssf_rfbufa: hex.vec w/4",
    "ssf_rfbufd: hex.vec w/4",
    "ssf_win_end: hex.vec 2",
    "ssf_win_lo: hex.vec 2",
    "wss_scale2: hex.vec 8",
    "wss_visang1: hex.vec 8",
    "wss_visang2: hex.vec 8",
    "sst_diff: hex.vec 8",
    "sst_quot: hex.vec 8",
    "sst_rem: hex.vec 8",
    "sst_span: hex.vec 8",
    "srw_ptr: hex.vec w/4",
    "srw_rel: hex.vec 2",
    "srw_rel_w: hex.vec 4",
    "srw_sbase: hex.vec w/4",
    "srw_sidx: hex.vec w/4",
    "srw_smidx: hex.vec 4",
    "srw_tex: hex.vec 2",
    "srw_whi4: hex.vec 4",
    "srw_wlo4: hex.vec 4",
    "srw_y0: hex.vec 4",
    "srw_yabs: hex.vec 4",
    "srn_cvh: hex.vec 4",
    "srn_ptr: hex.vec w/4",
    "srn_rel: hex.vec 2",
    "srn_rel_w: hex.vec 4",
    "srn_sbase: hex.vec w/4",
    "srn_sidx: hex.vec w/4",
    "srn_smidx: hex.vec 4",
    "srn_tex: hex.vec 2",
    "srn_y0: hex.vec 4",
    "srn_yabs: hex.vec 4",
    "srd_csh10: hex.vec 2, 10",
    "srd_csh5: hex.vec 2, 5",
    "srd_csh6: hex.vec 2, 6",
    "srd_csh8: hex.vec 2, 8",
    "srd_den_norm: hex.vec 8",
    "srd_num_wide: hex.vec 14",
    "srd_prod: hex.vec 14",
    "srd_recip: hex.vec 6",
    "srd_recip_wide: hex.vec 14",
    "srd_shift_nibs: hex.vec 2",
    "sga_anglea: hex.vec 8",
    "sga_angleb: hex.vec 8",
    "sga_cang90: hex.vec 8, 0x40000000",
    "sga_csmax: hex.vec 8, 0x400000",
    "sga_csmin: hex.vec 8, 0x100",
    "sga_den: hex.vec 8",
    "sga_num: hex.vec 8",
    "sga_qneg: hex.vec 1",
    "sga_sin_idx: hex.vec 3",
    "sga_sinv: hex.vec 8",
    # ── proj.point_to_angle (x4 expansions) ──────────────────────────────────────────────
    # CR 2026-08-25: this macro was believed unhoistable. It was not -- m1_hoist.py appended
    # declarations it declined to hoist AFTER the body, and point_to_angle's last body line is
    # its terminal label `done:`, so data words landed in the fall-through EXIT. The six-run
    # bisect measured the TOOL. Fixed there; these are the registers it always could have taken.
    "pta_c1: hex.vec 1, 1",
    "pta_c2: hex.vec 1, 2",
    "pta_c4: hex.vec 1, 4",
    "pta_c6: hex.vec 1, 6",
    "pta_den: hex.vec 8",
    "pta_dx: hex.vec 8",
    "pta_dy: hex.vec 8",
    "pta_num: hex.vec 8",
    "pta_oct_idx: hex.vec 1",
    "pta_slope_idx: hex.vec 3",
    "pta_tan_base: hex.vec 8",
]


def hoisted_scratch_fj() -> str:
    """HOISTED_SCRATCH_DECLS as fj text, for any program that expands these macros STANDALONE.

    The macros now name these registers in their `<` lists, so a program that expands one but
    does not emit the `state` part fails to assemble ("Can't evaluate label pos_dxv"). The
    shipped build gets them via the state part; tests get them from here, so there is ONE
    source (R6) and a new hoist cannot leave the tests behind.
    """
    return NLJ.join(HOISTED_SCRATCH_DECLS) + NLJ


def write_program_files(parts, outdir, mapname: str = "e1m1") -> list:
    """Write the emitted parts as SEPARATE .fj files and return them in ASSEMBLE ORDER.

    The generated program is ~4.76M lines, of which the actual program is ~58. Splitting it
    keeps the huge machine-written regions (LUT/dispatch tables, per-seg constant blocks, the
    BSP walk, the baked banks) out of the file a human opens to read the program.

    ⚠ ORDER IS THE CONTRACT. fj top-level labels are global, so N files assembled in this order
    are exactly equivalent to their concatenation -- which is byte-identical to the previous
    single file. Do NOT sort or reorder these paths: the parts are emitted in address order and
    the program's baked address constants depend on it.
    """
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, (name, text) in enumerate(parts):
        p = out / ("%s_%02d_%s.fj" % (mapname.lower(), i, name))
        p.write_text(text, encoding="utf-8")
        paths.append(p)
    return paths


def _raster_mode_decls(cfg, asset_wad, nvpc: int, nvpf: int) -> list[str]:
    """M13-raster: the raster_mode="raster" per-frame scratch + the THREE static tables the DEVICE
    DMA-reads once via `present.load_raster_tables` (yslope_packed/zlight_packed/colormap_packed --
    all raw PACKED BYTE, 1 dw-slot/entry, exactly what `InMemoryScreen._read_packed_bytes` expects;
    NOT the nibble-vec forms `generate_yslope_lut_fj`/`generate_zlight_lut_fj` emit for fb/stream mode's
    OWN in-fj read_table use). No band buffers, no col_struct -- build_bands and the whole per-column
    param/store machinery are GONE from fj; `drawn` is a lone packed byte per column (colstruct-style,
    stride 1) used only for the walk's until-full abort + the occlusion pre-scan, never emitted (so it
    stays packed-byte, unlike col_struct's emit'd fields which had to be nibble-vec, R21)."""
    return [
        "seg_lit: hex.vec 2",                          # the W1 wall's fully-baked constant lit byte
        "seg_cvpidx: hex.vec 8", "seg_fvpidx: hex.vec 8",   # the seg's visplane indices (baked)
        # M13-wedge: the conservative FOV pre-cull's per-frame half-plane descriptors + per-seg verdict
        "wrej: hex.vec 1", "wqa: hex.vec 1", "wna: hex.vec 1", "wqb: hex.vec 1", "wnb: hex.vec 1",
        "wex: hex.vec 8", "wey: hex.vec 8", "weyx: hex.vec 8", "wexy: hex.vec 8",
        "drawn:\n" + "\n".join(";0 * dw" for _ in range(cfg.VIEW_W)),
        f"vpc_flags: rep({nvpc}, i) hex.vec 1, 0", f"vpf_flags: rep({nvpf}, i) hex.vec 1, 0",
        generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H),
        generate_zlight_packed_lut_fj("zlight_packed", cfg.VIEW_W, COLORMAP_LIGHTS),
        generate_colormap_packed_table_fj("colormap_packed", asset_wad, lights=COLORMAP_LIGHTS),
    ]


def _proj_mode_decls(cfg, asset_wad, seg_geom_txt: str) -> list[str]:
    """M13-proj (Path B lab mode): the per-frame scratch + the DEVICE-resident tables -- the same
    three packed shade tables as raster mode (0x0C) plus the static per-seg geometry table (0x0E,
    30 B/row via mapcompiler._bytes_stream; stream_screen.PROJ_ROW_BYTES matches). No drawn[], no
    vp flags, no col_struct: fj emits only 2-byte seg ids."""
    return [
        "seg_sid: hex.vec 4",                          # the seg's compact wire id (baked per seg)
        # the wedge pre-cull's per-frame half-plane descriptors + per-seg verdict (shared w/ raster)
        "wrej: hex.vec 1", "wqa: hex.vec 1", "wna: hex.vec 1", "wqb: hex.vec 1", "wnb: hex.vec 1",
        "wex: hex.vec 8", "wey: hex.vec 8", "weyx: hex.vec 8", "wexy: hex.vec 8",
        seg_geom_txt,
        generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H),
        generate_zlight_packed_lut_fj("zlight_packed", cfg.VIEW_W, COLORMAP_LIGHTS),
        generate_colormap_packed_table_fj("colormap_packed", asset_wad, lights=COLORMAP_LIGHTS),
    ]


LINES_HALF_SLOTS = 1 + 2 * (MAX_BANDS // 2)   # per half-window list: [count] + <=32 x 2-byte pairs


def _band_pair_lists(rm, cfg, asset_wad, vz_classes: dict, key_ids, ft1: bool = False):
    """The SSOT pair-list producer both band representations bake from: for every (viewz class,
    bank key), the asc then desc half-window [absolute y2, final colour] lists — class-major,
    key, half order, which IS the vpb_walk id order (id = (class*nkeys + key)*2 + half)."""
    colormap = asset_wad.colormap()
    flatcache: dict = {}
    H, CY = cfg.VIEW_H, cfg.CENTERY
    lists = []
    for vz in vz_classes:
        from doomfj.fixedpoint import _signed as _sgn
        vzs = _sgn(vz, 32)
        for (h, light, base, flatname) in key_ids:
            ph = abs((h << 16) - vzs)
            lvl = max(0, min(15, light >> 4))
            # M13-FT1: the flat's DIAGONAL texels -- band ordinal j takes texel strip[j & 63]
            # instead of every band sharing the flat's single base texel. Costs ZERO runtime ops
            # (it only changes which byte is baked), and gives the floor real depth-varying texel
            # colour on top of the distance shading. Sampling by band ORDINAL (not world u,v) is
            # what keeps it free -- see docs/plan-w2-ft1.md for the honest scope statement.
            strip = None
            if ft1:
                tx = rm._flat_texels(asset_wad, flatname, flatcache)
                strip = [tx[(i * 64 + i) % len(tx)] for i in range(64)]
            for rows in (list(range(0, CY)), list(range(CY, H))):
                zidx = rm._zidx_band_walk(ph, rows)
                zrows = [rm.zlight[lvl][z] for z in zidx]
                pairs, ordinal, prev_z = [], 0, None
                for k, zr in enumerate(zrows):
                    y2 = rows[k] + 1
                    if prev_z is not None and zr != prev_z:
                        ordinal += 1
                    prev_z = zr
                    colr = (colormap[zr][strip[ordinal & 63]] if ft1 else colormap[zr][base])
                    if pairs and pairs[-1][1] == colr:
                        pairs[-1][0] = y2
                    else:
                        pairs.append([y2, colr])
                lists.append([tuple(pr) for pr in pairs])
    return lists


def _sky_pair_lists(rm, asset_wad, cfg):
    """The sky lists in vpb_walk id order (u-major, asc then desc), mirroring _lines_sky_bank's
    half() exactly — SKY_BANK_MUL*tw entries of u so skybase+skyoff never needs a mask."""
    tex = rm._wall_texture(asset_wad, "SKY1", {}, wall_mode="textured")
    if tex is None:
        return []
    _texels, _th, tw = tex
    H, CY = cfg.VIEW_H, cfg.CENTERY
    out = []

    def half(u, y0, y1):
        pairs, prev = [], None
        for y in range(y0, y1):
            c = rm.sky_texel_u(asset_wad, {}, u, y)
            if c != prev:
                if prev is not None:
                    pairs[-1][0] = y
                pairs.append([y1, c])
                prev = c
        return [tuple(pr) for pr in pairs]

    for u in range(SKY_BANK_MUL * tw):
        out.append(half(u, 0, CY))
        out.append(half(u, CY, H))
    return out


def _lines_bake_bank(rm, cfg, asset_wad, vz_classes: dict, key_ids: dict,
                     ft1: bool = False) -> str:
    """M13-bakedbands: the compile-time band-list bank. For every (viewz class, (h,light,base))
    pair, both half-window lists ([0,centery) asc + [centery,H) desc) with entries
    [y2_absolute:1B][final_colour:1B], grouped by FINAL colour (adjacent zrows sharing a colour
    merge -- identical pixels, fewer pairs). The lists come from `_band_pair_lists` -- the SAME
    SSOT walk the bands-as-code tier bakes from, itself mirroring the fj runtime build
    (rm._zidx_band_walk + zlight + colormap) -- so frames are byte-identical to the
    runtime-built ones. Layout: list (class,key) at (class*len(keys)+key)*130 dw; asc half at +0
    ([n][pairs]), desc half at +65 dw."""
    half = LINES_HALF_SLOTS
    out = [f"// M13-bakedbands: {len(vz_classes)} viewz classes x {len(key_ids)} keys, 130 dw/list",
           "vpbank:"]
    for pairs in _band_pair_lists(rm, cfg, asset_wad, vz_classes, key_ids, ft1):
        assert len(pairs) <= MAX_BANDS // 2, f"half list overflow: {len(pairs)}"
        cell = [len(pairs)] + [b for pr in pairs for b in pr]
        for b in cell:
            out.append(f";{b:#x} * dw")
        for _ in range(half - len(cell)):
            out.append(";0 * dw")
    return NLJ.join(out) + NLJ


def _lines_wall_strips(rm, asset_wad, cmap, lds, sds, secs, wall_mode, colormap, lrow):
    """M13-W2S: per-seg RUN-MERGED wall colour strips + their bank text.

    Each one-sided seg's 16-texel strip (the shared `_tiny_wall_canvas` reduction, R6) is
    colormapped at its sector's light level and then run-merged into entries
    `[cum_band:1][colour:1]` -- cum_band is the CUMULATIVE band index (1..16) at which the colour
    changes, so the emit computes `y2 = top + ((cum*h) >> 4)` with no divide. Segs whose strip is
    one flat colour (83 of 575 on E1M1) collapse to a single entry, i.e. exactly today's W1 cost.
    Returns (offsets_by_seg, bank_text); STRIDE dw per seg keeps the offsets baked constants."""
    STRIDE = 1 + 2 * 16                       # [n][ (cum,colour) x <=16 ]
    cache = {}
    off_by_seg, lines_out, k = {}, ["// M13-W2S: per-seg run-merged wall colour strips", "wstrips:"], 0
    for si, seg in enumerate(cmap.segs):
        if lds[seg.linedef].back != -1:
            continue
        sd = sds[lds[seg.linedef].front if seg.side == 0 else lds[seg.linedef].back]
        sec = rm._seg_sector(lds, sds, secs, seg)
        lr = lrow(sec.light)
        tex = rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=wall_mode)
        if tex is None:
            cols = [colormap[lr][WALL_BG]]
        else:
            texels, th, _tw = tex
            cols = [colormap[lr][texels[i]] for i in range(min(16, len(texels)))]
        runs = []
        for j, c in enumerate(cols):
            if runs and runs[-1][1] == c:
                runs[-1][0] = j + 1
            else:
                runs.append([j + 1, c])
        runs[-1][0] = 16                      # the last run always reaches the wall bottom
        off_by_seg[si] = k * STRIDE
        body = [len(runs)] + [b for r in runs for b in r]
        for b in body:
            lines_out.append(f";{b:#x} * dw")
        for _ in range(STRIDE - len(body)):
            lines_out.append(";0 * dw")
        k += 1
    return off_by_seg, NLJ.join(lines_out) + NLJ


def _lines_wall_pix_bank(rm, asset_wad, cmap, lds, sds, secs, colormap, verts, view_h,
                         cap: int = WPX_RUN_CAP, solid=None, two_sided=None):
    """M13-WPX: the fully-baked 1×1 wall bank + its per-seg block offsets.

    One BLOCK per distinct (wall texture, seg light level, sector wall span) — 575 E1M1 segs collapse
    to ~185 blocks, since those three determine every column the seg can ever draw. A block holds one
    run-list per possible wall height h (0..view_h) at a UNIFORM stride of `2*cap` words, so the
    fj emit indexes it with a single `mul_const` by the height: no offset table, no search.

    Each list is `[(rel, colour) × n][0][last_colour]` where `rel` is the run's end row measured
    from the wall's top. The final run always ends exactly at the wall bottom, which fj already
    holds, so its `rel` is never stored — which frees `rel == 0` to be the list TERMINATOR (every
    real run ends at row >= 1), so the fj loop needs no counter and no per-run compare. Baking per
    EXACT height is what makes this true 1×1: every boundary is pixel-exact, and a short wall's list
    is short (a 5px wall can hold at most 5 runs), so far geometry costs almost nothing.

    M13-2S rung 3b (`two_sided`): a marking two-sided seg gets TWO more blocks -- its UPPER
    (texture `sd.upper`, span front.ceil - back.ceil) and its LOWER (`sd.lower`, span
    back.floor - front.floor) -- keyed exactly like the middle one, so a step face and a wall of the
    same texture, light and span share a block. Returns `(offsets_by_seg, bank_text)` where each
    offset entry is `(middle, upper, lower)` when `two_sided` is given, else the bare middle offset.

    The run-lists come from `ReferenceModel.wpx_strip` — the same call the oracle paints from, so
    the two cannot drift (R6)."""
    STRIDE = 2 * cap                              # [n] + (cap-1) pairs + [last_colour]
    cache, blocks, off_by_seg = {}, {}, {}
    out = [f"// M13-WPX: 1x1 wall run-lists, per (texture,light) block x wall height "
           f"(stride {STRIDE} dw, run cap {cap})", "wpxstrips:"]

    def block_for(texname, lightnum, wall_units):
        """the bank offset of the block for this (texture, light, span), baking it on first use."""
        tex = rm._wall_texture(asset_wad, texname, cache, wall_mode="WPX")
        key = (texname.upper() if tex is not None else None, lightnum, wall_units)
        if key not in blocks:
            # M13-2S rung 3b buffers a block INDEX (one byte pair in a region entry); the
            # shipped tier bakes the dw OFFSET straight into the seg's register.
            blocks[key] = (len(blocks) if two_sided is not None
                           else len(blocks) * (view_h + 1) * STRIDE)
            texels, th, tw = tex if tex is not None else (None, 0, 0)
            for h in range(view_h + 1):
                lr = rm.wall_light_row(lightnum, max(1, h), max(1, wall_units))
                runs = rm.wpx_strip(texels, th, tw, colormap, lr, max(1, h), cap=cap)
                body = []
                for rel, c in runs[:-1]:
                    body += [rel, c]
                body += [0, runs[-1][1]]                  # rel==0 sentinel, then the last colour
                assert len(body) <= STRIDE, f"WPX list overflows its stride: {len(body)} > {STRIDE}"
                out.extend([f";{v:#x} * dw" for v in body] + [";0 * dw"] * (STRIDE - len(body)))
        return blocks[key]

    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        two = ld.back != -1
        if two and not ((solid is not None and solid(seg))
                        or (two_sided is not None and two_sided(seg))):
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        sec = rm._seg_sector(lds, sds, secs, seg)
        # M13-WPXLIGHT: the block key carries the seg's DOOM light level (sector level + FAKE
        # CONTRAST, both per-seg constants) and the wall's span in map units -- the span is what lets
        # each baked height h recover its own projection scale, and hence its scalelight row. So
        # distance lighting and fake contrast are pure BAKE: zero runtime ops.
        lightnum = rm.wall_lightnum(sec.light, rm.wall_fake_contrast(verts[seg.v1], verts[seg.v2]))
        mid = block_for(sd.middle, lightnum, sec.ceil_h - sec.floor_h)
        if two_sided is None:
            off_by_seg[si] = mid
            continue
        up = lo = mid
        if two:
            bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
            if sec.ceil_h > bsec.ceil_h:
                up = block_for(sd.upper, lightnum, sec.ceil_h - bsec.ceil_h)
            if bsec.floor_h > sec.floor_h:
                lo = block_for(sd.lower, lightnum, bsec.floor_h - sec.floor_h)
        off_by_seg[si] = (mid, up, lo)
    return off_by_seg, NLJ.join(out) + NLJ


def _lines_mode_decls(cfg, rm, asset_wad, vz_classes: dict, key_ids: dict,
                      w2s: bool = False) -> list[str]:
    """M13-lines decls, post-bakedbands: the baked bank + the frame's bank pointer. No
    build_bands, no recip32, no built-flags, no planeheight math, no yslope table -- the lists
    are static data. `drawn` stays the stride-1 packed byte; wedge registers shared-named with
    raster/proj."""
    return [
        "seg_lit: hex.vec 2",                          # the W1 wall's fully-baked constant lit byte
        "seg_lit2: hex.vec 2",                         # W1R-2C: ... and its SECOND colour byte
        "seg_w1rf: hex.vec 1",                         # W1R-FLAT: this wall stays one flat tone
        "w1rslv: hex.vec 1",                           # 25M-CAP: runtime sliver twin of seg_w1rf
        "wnoff: hex.vec 4",                            # W1R-ANCHOR: the per-frame column offset
        "wnt: hex.vec 10", "wnt2: hex.vec 10",         # ... and its widened scratch
        "seg_litf: hex.vec 2",                         # ... and the unbrightened sliver tone
        "gnrow2: hex.vec 2",                           # W1R-LOD: the fine 2-px group key
        "gnrow3: hex.vec 2",                           # ... and the coarse 8-px one
        # V5: the current column's stacked boundary pieces (GLOBALS so emit_region's windowed
        # splices reach them without threading 18 parameters through every signature)
        "ucnt: hex.vec 2", "u1y1: hex.vec 2", "u1y2: hex.vec 2", "u1cls: hex.vec 2",
        "u1bp: hex.vec 2", "u2y1: hex.vec 2", "u2y2: hex.vec 2", "u2cls: hex.vec 2",
        "u2bp: hex.vec 2",
        "lcnt: hex.vec 2", "l1y1: hex.vec 2", "l1y2: hex.vec 2", "l1cls: hex.vec 2",
        "l1bp: hex.vec 2", "l2y1: hex.vec 2", "l2y2: hex.vec 2", "l2cls: hex.vec 2",
        "l2bp: hex.vec 2",
        "seg_wstrip: hex.vec w/4", "wstripbase: hex.vec w/4",   # M13-W2S strip bank
        "seg_cvpidx: hex.vec w/4", "seg_fvpidx: hex.vec w/4",   # baked dw-offsets into the bank
        "seg_pid: hex.vec 2",                          # M13-2S rung 3a: baked plane-pair id (1-based)
        "vzbank: hex.vec w/4",                         # set per frame by the player-subsector block
        "vzcbase: hex.vec w/4",                        # M13-15M: the as-code per-frame class base ID
        # M13-splitxb: part-1/part-2 shared state + the rest-block gate
        "proceed: hex.vec 1", "dbase: hex.vec w/4", "dptr: hex.vec w/4", "dval8: hex.vec 2",
        "seg_ret2: ;0",
        "drawn:" + NLJ + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W)),
        "wrej: hex.vec 1", "wqa: hex.vec 1", "wna: hex.vec 1", "wqb: hex.vec 1", "wnb: hex.vec 1",
        "wex: hex.vec 8", "wey: hex.vec 8", "weyx: hex.vec 8", "wexy: hex.vec 8",
    ]

def _stream_mode_decls(cfg, nvpc: int, nvpf: int) -> list[str]:
    """M13pS2-crush2b: the raster_mode="stream" per-VISPLANE band storage + the shared band-building
    leaves' scratch registers. Each of the map's nvpc ceiling / nvpf floor visplanes gets ONE
    full-range packed-byte buffer (slot 0 = the entry count n, then up to MAX_BANDS 3-byte entries)
    built at most once per frame (`vpc_flags`/`vpf_flags`, reset in pass-1).

    M13-colstruct: each claimed column's fields (drawn flag, clipped cexcl/fstart rows, the baked W1
    lit byte, the ceiling/floor visplane indices) live PACKED in ONE combined struct `col_struct`
    (stride 11 dw/column) instead of 6 separate arrays (the shared `drawn` array + col_cexcl/
    col_fstart, still declared elsewhere for the fb-mode leaf, goes unused here). Layout: offset 0 =
    drawn, a single PACKED byte (1 dw slot) -- it's only ever read/written internally (read_byte/
    write_byte_and_inc), never emitted. Offsets 1-10 = cexcl,fstart,lit,cvp,fvp, each a 2-NIBBLE-VEC
    pair (2 dw slots: low nibble then high nibble) -- NOT a packed byte, because present_tail's
    `byte.emit`/`cm.emit` dispatch reads its cell as idx/idx+1*dw (two separate nibble dw-slots) by
    XORing those two ADDRESSES directly into the dispatch op; it never dereferences through a register,
    so the address it's given must actually hold nibble-vec data, matching the OLD col_cexcl-style
    hex.vec arrays' low 2 nibbles. One struct load lets the stream leaf walk all 6 fields with a single
    held pointer instead of a fresh ptr_index per field per column (ptr_index's cost scales with the
    address width, ptr_add's doesn't -- R20/fj-lessons). fvp's 0xFF sentinel (UNCLAIMED, both nibbles
    0xF) sits at offsets 9-10 of each column's slot."""
    vp_slots = 1 + 3 * MAX_BANDS
    vpc_zeros = "\n".join(";0 * dw" for _ in range(nvpc * vp_slots))
    vpf_zeros = "\n".join(";0 * dw" for _ in range(nvpf * vp_slots))
    # per-column init: [drawn=0 (packed byte), cexcl=00, fstart=00, lit=00, cvp=00, fvp=FF] as nibbles
    _COL_SLOT_NIBBLES = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0xF, 0xF]   # 1 packed byte + 5 nibble-vec pairs
    col_struct_zeros = "\n".join(
        f";{v:#x} * dw"
        for _ in range(cfg.VIEW_W) for v in _COL_SLOT_NIBBLES)
    return [
        "seg_lit: hex.vec 2",                          # M13pS2c: the W1 wall's fully-baked constant lit byte
        "seg_cvpidx: hex.vec 8", "seg_fvpidx: hex.vec 8",   # crush2b: the seg's visplane indices (baked)
        f"col_struct:\n{col_struct_zeros}",
        f"vpc_flags: rep({nvpc}, i) hex.vec 1, 0", f"vpf_flags: rep({nvpf}, i) hex.vec 1, 0",
        f"vpc_bufs:\n{vpc_zeros}", f"vpf_bufs:\n{vpf_zeros}",
        "bb_ph: hex.vec 8", "bb_light: hex.vec 2", "bb_base: hex.vec 2", "bb_y0: hex.vec 2",
        "bb_count: hex.vec 2", "bb_ascending: hex.vec 2", "bb_arr: hex.vec w/4", "bb_n: hex.vec 2",
        "bb_recip_ph: hex.vec 8", "bb_recip_out: hex.vec 8",   # plane.recip32's own I/O globals
        "plane_recip_ret: ;0", "plane_band_ret: ;0",
        "recip32_leaf: plane.recip32", "build_bands_leaf: plane.build_bands 1",
        # M13pS2-crush2a: build_bands walks yslope through ONE incrementing packed-byte pointer
        # (3 bytes/row) instead of a per-row read_table 8 -- the packed twin of the 8-nib table.
        generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H),
    ]


STEP_SLOT_STRIDE = 16      # V3: bytes per column in `sfslot` -- 6 used, rounded to a POWER OF 16 so
                           # the per-column byte offset is `x << 1 nibble`, not a mul_const (~72@).
STEP_COL_STRIDE = 256      # ... and bytes per light class in `stepcol`, same whole-nibble reason.


def _lines_step_bank(rm, asset_wad, cfg, cmap, lds, sds, secs, w1r=False, sky=False):
    """V3 — the step-face SHADE bank, plus the (lightnum, units) -> class map the segs bake.

    A step face is flat-shaded: one palette index for the whole run. But it still takes DOOM's
    scalelight row for its own on-screen height, exactly as a wall column does (near reads
    brighter), and that row is `wall_light_row(lightnum, h, units)` — a pure function of two
    COMPILE-TIME per-seg facts and the run's clipped height. So the whole thing bakes: one
    `STEP_COL_STRIDE`-byte row per class, indexed by h.

    ⚠ `STEP_FACE_BASE` (96), NOT `WALL_BG` (4). A palette INDEX carries no brightness ordering you
    can guess at — DOOM's ramp puts 4 near WHITE, and the first version of this blew every face out
    (the same bug as V1's confetti grain, twice).

    Values come from `ReferenceModel.wall_light_row`, so oracle and fj cannot drift (R6)."""
    colormap = asset_wad.colormap()
    cls_of: dict = {}
    for seg in cmap.segs:
        ld = lds[seg.linedef]
        if ld.back == -1:
            continue
        fsec = rm._seg_sector(lds, sds, secs, seg)
        bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
        ln = rm.wall_lightnum(fsec.light, 0)
        # V5-DROP: lips (mode 2) collapse to units=1; risers keep their true delta (R6:
        # exactly the keys the seg bakes below)
        um, lm = rm.v5_side_modes(fsec, bsec, sky)
        if um:
            cls_of.setdefault((ln, max(1, fsec.ceil_h - bsec.ceil_h)), len(cls_of))
        if lm:
            cls_of.setdefault((ln, max(1, bsec.floor_h - fsec.floor_h)), len(cls_of))
    assert len(cls_of) * STEP_COL_STRIDE <= 0x10000, f"step classes overflow the 4-nibble index: {len(cls_of)}"
    out = [f"// V3 step-face shades: {len(cls_of)} (light, wall-units) classes x "
           f"{STEP_COL_STRIDE} dw, indexed class<<8 | height", "stepcol:"]
    for (ln, units) in cls_of:                      # insertion order == class index
        row = [0] * STEP_COL_STRIDE
        for h in range(1, cfg.VIEW_H + 1):
            lr = rm.wall_light_row(ln, h, units)
            # M13-W1R-FACES: the W1R tier splits faces into randomized runs at emit time, so
            # the baked byte pre-brightens exactly like seg_lit (colormap headroom, R44) --
            # mirrors the oracle's `_face_paint` (R6).
            if w1r:
                lr = max(0, lr - rm.W1R_BASE_BRIGHTEN)
            row[h] = colormap[lr][STEP_FACE_BASE]
        out += [f";{v:#x} * dw" for v in row]
    return NLJ.join(out) + NLJ, cls_of


SPR_BLOCK_STRIDE = 64      # V4-HD: cap 24 needs 3+48 bytes -- was 32 at cap 12. Power of two so
                           # the record/emit shifts stay bit-shifts (blkshift derives from this).
                           # V4: dw per baked sprite-column block -- [n][ (rel,texel) x <=cap ] with
                           # SPRITE_RUN_CAP = 12 needs 25, and a POWER OF TWO stride turns the block
                           # index into a shl_bit instead of a mul_const.
SPR_SLOT_STRIDE = 16       # ... and bytes per column in `spslot` (7 used: y0 is TWO bytes,
                           #     bias 32768 -- the one-byte +128 bias wrapped for tall near
                           #     sprites, M13-15M), a power of 16 so the
                           # per-column byte offset is a whole-nibble shift.


def _lines_sprite_bank(rm, sprite_wad, cfg, map_wad, mapname):
    """V4 — the sprite bank: one RAW-texel run-list per (thing sprite, downscaled texture column,
    on-screen height BUCKET), plus the per-thing block bases.

    This is the WPX wall bank's shape, applied to billboards: a wall column bakes per (texture,
    light, exact height) because its content depends on nothing else, and a sprite column bakes per
    (sprite, u, height) for the same reason -- a billboard has no perspective within itself. The two
    differences are both forced by size: heights are BUCKETED (`SPRITE_HEIGHT_BUCKETS`) because the
    sprite key already carries a texture column, and texels are stored RAW with the light row
    applied at emit time through `cm.emit` (V1's grain mechanism), so one bank serves every light
    level instead of being multiplied by 16.

    A block is `[r0][last_rel][n][ (rel_end, texel) x n ]`. `r0` and `last_rel` sit in the HEADER so
    the RECORD half can bound the fragment's screen rows with two byte reads instead of pre-walking
    the run-list — the emit needs those bounds before it emits anything (it composes the column
    around them), and walking twice would double the only per-fragment loop there is.

    Returns `(bank_text, base_of_kind, dw_of_kind)` — the bank's fj text, each thing type's first
    block index, and its downscaled width (blocks for a type are laid out u-major, bucket-minor).
    Run-lists come from `ReferenceModel.sprite_strip`, so oracle and fj cannot drift (R6)."""
    cache: dict = {}
    kinds = sorted({t.type for t in map_wad.things(mapname)
                    if rm.sprite_art(sprite_wad, t.type, cache) is not None})
    out = ["// V4 sprite bank: [r0][last_rel][n][ (rel_end, RAW texel) x n ] per (sprite, column, "
           f"height bucket), stride {SPR_BLOCK_STRIDE} dw", "sprbank:"]
    base_of, dw_of, blk = {}, {}, 0
    for kind in kinds:
        art = rm.sprite_art(sprite_wad, kind, cache)
        cols, dh, dwid, fcols, fdh = art[0], art[1], art[2], art[7], art[8]
        base_of[kind], dw_of[kind] = blk, dwid
        for u in range(dwid):
            for b in range(SPRITE_HEIGHT_BUCKETS):
                hb_ = sprite_bucket_height(b, cfg.VIEW_H)
                # V4-HD: tall buckets bake from the FULL-RES column, deeper cap. SPR-NEAR: the
                # MAIN bank is always FULL detail -- the coarse variants live in the packed LD
                # region below and only FAR things pick them (R6 mirror of the record site).
                st = (rm.sprite_strip(fcols[u], fdh, hb_, cap=SPRITE_RUN_CAP_HD)
                      if hb_ >= SPRITE_HD_H else
                      rm.sprite_strip(cols[u], dh, hb_, cap=DEG_SPR_MID_CAP))
                body = [0, 0, 0] if st is None else (
                    [st[0], st[1][-1][0], len(st[1])] + [v for pr in st[1] for v in pr])
                assert len(body) < SPR_BLOCK_STRIDE, f"sprite block overflows: {len(body)}"   # STRICT: the
                # rel==0 sentinel in stream.sprite_runs needs at least one 0 cell after the body
                out += [f";{v:#x} * dw" for v in body]
                out += [";0 * dw"] * (SPR_BLOCK_STRIDE - len(body))
                blk += 1
    # SPR-NEAR (owner, 2026-08-05): the packed COARSE region -- the SHORT buckets baked at
    # DEG_SPR_LOWRES_CAP. Only things BEYOND the detail radius (thfar, set in project_thing)
    # index here: ld_base + u*n_ld + bucket (the low buckets are a prefix, so no offset).
    # Near things -- however short on screen -- keep the main bank's full detail.
    ld_base_of = {}
    if DEG_SPR_NEAR_TZ:
        n_ld = _spr_nlow(cfg)
        for kind in kinds:
            art = rm.sprite_art(sprite_wad, kind, cache)
            cols, dh, dwid = art[0], art[1], art[2]
            ld_base_of[kind] = blk
            for u in range(dwid):
                for b in range(n_ld):
                    st = rm.sprite_strip(cols[u], dh, sprite_bucket_height(b, cfg.VIEW_H),
                                         cap=DEG_SPR_LOWRES_CAP)
                    body = [0, 0, 0] if st is None else (
                        [st[0], st[1][-1][0], len(st[1])] + [v for pr in st[1] for v in pr])
                    assert len(body) < SPR_BLOCK_STRIDE, f"LD block overflows: {len(body)}"       # STRICT, as above
                    out += [f";{v:#x} * dw" for v in body]
                    out += [";0 * dw"] * (SPR_BLOCK_STRIDE - len(body))
                    blk += 1
    assert blk < 0x10000, f"sprite bank blocks overflow sp_base's 4 nibbles: {blk}"
    return NLJ.join(out) + NLJ, base_of, dw_of, ld_base_of


def _spr_nlow(cfg):
    """How many SHORT buckets (< DEG_SPR_LOWRES_H px) there are -- monotone, so a prefix."""
    return sum(1 for b in range(SPRITE_HEIGHT_BUCKETS)
               if sprite_bucket_height(b, cfg.VIEW_H) < DEG_SPR_LOWRES_H)


def _assert_pnear_unbound(deg: bool, total_segs: int) -> str:
    """The deg attribution budget's never-binds proof (see DEG_PNEAR): total segs strictly below
    the baked cap, and the cap inside the 3-nibble fj counter. Returns an empty emitted line."""
    if deg:
        assert total_segs < DEG_PNEAR <= 4095, (
            f"DEG_PNEAR={DEG_PNEAR} can bind (map has {total_segs} segs) or overflows the "
            "3-nibble n_tsv counter -- a binding attribution budget paints wrong columns")
    return ""


def _assert_pow2_ds(ds: int) -> str:
    """Guard project_thing's compile-time istep shift (`rep(#ds - 1, ...)` = /2^log2(ds)):
    exact only for power-of-two downscales. Returns an empty emitted line so the check can sit
    inline in the emit list right where the value is consumed."""
    assert ds >= 1 and (ds & (ds - 1)) == 0, (
        f"TEXTURE_DOWNSCALE={ds}: project_thing's istep shift needs a power of two")
    return ""


def _thing_sector(rm, cmap, lds, sds, secs, t):
    """The sector a thing stands in — its floor is the sprite's base and its light the sprite's."""
    ss = cmap.subsectors[rm.point_in_subsector(cmap, t.x, t.y)]
    return rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])


def _lines_sprite_light(rm, cfg, sprite_wad, map_wad, mapname, cmap, lds, sds, secs,
                        *, moving_things: bool = False):
    """V4 — the sprite SHADE-ROW bank + the (lightnum, sprite world height) class each thing bakes.

    A billboard takes DOOM's scalelight row for its own on-screen height, exactly as a wall column
    and a V3 step face do, so the row is a function of (sector light, sprite height, BUCKETED screen
    height) and bakes out. Rows, not colours: sprite texels stay RAW in `sprbank` and go through
    `cm.emit` at emit time (V1's grain mechanism), which is what keeps ONE bank serving all 16 light
    levels instead of being multiplied by them.

    M14-e `moving_things`: the classes above are the pairs that occur AT SPAWN, which is all a
    static thing can ever see. A thing that walks into a differently-lit sector needs a pair that
    was never baked, so the bank widens to the CROSS PRODUCT of the sprite heights with the
    lightnums a thing can actually stand in.

    ⚠ "can actually stand in" is the whole cost argument, and it is sound: a thing is always in some
    sector, so only the lightnums the map's SECTORS have are reachable. On E1M1 that is 10 of the 32
    COLORMAP_LIGHTS, so the bank goes 75 -> 210 classes (**2.8x**, ~193k -> ~540k chars) instead of
    the 672 (9x, ~1.73M) a naive all-lights widening would cost."""
    cache: dict = {}
    cls_of: dict = {}
    for t in map_wad.things(mapname):
        art = rm.sprite_art(sprite_wad, t.type, cache)
        if art is None:
            continue
        sec = _thing_sector(rm, cmap, lds, sds, secs, t)
        cls_of.setdefault((rm.wall_lightnum(sec.light, 0), max(1, art[4])), len(cls_of))
    if moving_things:
        # the spawn pairs keep their indices -- appending leaves every static thing's baked class
        # exactly where it was, so widening the bank cannot move a pixel by itself
        heights = sorted({h for (_ln, h) in cls_of})
        for ln in sorted({rm.wall_lightnum(s.light, 0) for s in secs}):
            for h in heights:
                cls_of.setdefault((ln, h), len(cls_of))
    assert len(cls_of) * STEP_COL_STRIDE <= 0x10000, f"sprite light classes overflow: {len(cls_of)}"
    out = [f"// V4 sprite shade rows: {len(cls_of)} (light, sprite-height) classes x "
           f"{STEP_COL_STRIDE} dw, indexed class<<8 | bucket height", "sprlight:"]
    for (ln, units) in cls_of:
        row = [0] * STEP_COL_STRIDE
        for h in range(1, cfg.VIEW_H + 1):
            row[h] = rm.wall_light_row(ln, h, units)
        out += [f";{v:#x} * dw" for v in row]
    return NLJ.join(out) + NLJ, cls_of


SKY_BANK_MUL = 3


def _lines_sky_bank(rm, asset_wad, cfg):
    """V2 — the SKY bank: one `[y2_cumulative][colour]` band list per sky texture column, plus the
    compile-time per-column offset table.

    Sky is the one surface with NO perspective and NO distance lighting, so a sky column depends on
    the texture column `u` ALONE. That makes it bakeable outright: 128 lists of ~9 runs, ~1,150 pairs
    of static data — nothing beside the 8.9M-character wall bank — and it slots into the ceiling
    prefix walk that already exists, so V2 adds no emit path.

    At runtime: `u = skybase + skyoff[x]`, then the ceiling list address is `skybands + u*stride`.
    `skybase` is the shifted viewangle taken as a full UNMASKED byte once per frame
    (`lines_sky_base`'s 2-nibble mov); the oracle's `sky_base` folds in the `& (tw-1)` the fj
    never pays — same column either way, since the bank wraps at tw.

    ⚠ The bank holds **SKY_BANK_MUL*tw** lists, entry `u` carrying sky column `u % tw`. `skyoff`
    stays in [0, tw-1] but the unmasked skybase byte spans [0, 255], so their sum reaches at most
    255 + tw-1 = SKY_BANK_MUL*tw - 2 (tw=128) and **the wrap needs no mask at all** — which
    matters because fj has no cheap AND: masking would cost a dispatch or a compare-and-subtract
    per column, while the extra copies cost only static text (~350k of the bank's ~530k
    characters, against the 8.9M-character wall bank). Trading a little baked data for an omitted
    runtime op is the same bargain the wall bank already makes.

    Values come from `ReferenceModel.sky_texel_u`, so oracle and fj cannot drift (R6)."""
    H = cfg.VIEW_H
    tex = rm._wall_texture(asset_wad, "SKY1", {}, wall_mode="textured")
    if tex is None:
        return "", ""
    _texels, _th, tw = tex
    CY = cfg.CENTERY
    stride = 2 * LINES_HALF_SLOTS             # one pid-shaped CEILING PAIR: [asc half][desc half]
    out = [f"// V2 sky bank: {SKY_BANK_MUL * tw} lists (tw={tw}, x{SKY_BANK_MUL} so the UNMASKED "
           f"skybase+skyoff needs no mask), each an [asc][desc] half pair of {LINES_HALF_SLOTS} dw",
           "skybands:"]

    def half(u, y0, y1):
        """One half-window band list in the PLANE format: [n] then n x [absolute y2][colour].

        The ceiling is TWO halves split at CENTERY -- emit_col_lines walks cbufa and then, when
        ctake > CENTERY, continues into cbufd via cdesc2. The plane bank splits there because the
        zlight ordinals restart per half-window; sky has no perspective and needs no split at all,
        but THE WALKER'S LAYOUT IS NOT OPTIONAL, so the sky lists are shaped to match."""
        body, prev = [], None
        for y in range(y0, y1):
            c = rm.sky_texel_u(asset_wad, {}, u, y)
            if c != prev:
                if prev is not None:
                    body[-2] = y
                body += [y1, c]
                prev = c
        body = [len(body) // 2] + body
        assert len(body) <= LINES_HALF_SLOTS, f"sky half overflows: {len(body)}"
        return body + [0] * (LINES_HALF_SLOTS - len(body))

    for u in range(SKY_BANK_MUL * tw):
        body = half(u, 0, CY) + half(u, CY, H)
        out.extend([f";{v:#x} * dw" for v in body] + [";0 * dw"] * (stride - len(body)))
    offs = generate_dispatch_table_fj(
        "skyoff", [rm.sky_col_off(x, tw) for x in range(cfg.VIEW_W + 1)],
        index_nibbles=2, result_nibbles=2)
    return "\n".join(out), offs
