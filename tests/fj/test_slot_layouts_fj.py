"""M7 P1.4 (PR #93's review, R6 / R9) -- the two slot layouts, EXECUTED.

A column's fragments live in `spslot`, a thing's constants in `gpslot`. frame.thing_record_body writes
both; frame.lines_spr_seed / lines_spr_step / lines_spr_load read a column's fragments, and
stream.frag_derive a thing's constants. wall_renderer states the layouts once: SPR_SLOT_STRIDE,
SPR_FRAG_FIELDS, SPR_SLOT_B_BYTE, SPR_THING_SLOT_BYTES, SPR_THING_SLOT_FIELDS, SPR_THING_Y0_BIAS.
This RUNS the shipped fj and holds every byte and every register to them -- nothing is modelled:

  write  The record's code from its slot allocation (`hex.inc 2, gps_nslot`) to the end of its
         column loop, transplanted VERBATIM from frame.thing_record_body into a harness macro with
         the emitter's own parameter values, records THINGS: columns across the 16, 64 and
         1,024-index bounds up to 159, slot ids 1..255 across 16, fragments A and B, a column whose
         both slots are spent, columns a wall hides, a fully transparent block, block indices past
         one byte, y0 below and above zero. Then EVERY byte of sprflag, spslot and gpslot must be
         the constants' layout of what was recorded: the bytes the layout names hold the fields and
         every other byte is still zero.
  read   From memory laid out by the constants, the real seed (and step) and load give each
         column's fragments, and the real derive each thing's y0 and light row.

Each side is held to the constants ON ITS OWN, so a change made alike on both sides that the
constants do not describe fails too.

What it does NOT cover: the shipped binary's ADDRESSES -- the harness lays drawn, pclm, sfflag,
sprflag, sfslot, spslot and gpslot out in the real hot block's order, so the narrow arms meet the
same neighbours, but at other addresses; the shipped binary's gates (m2_std_gate and m3_gate byte-
and state-exact, b0 pixel-exact) are the check at its addresses. Nor what the record computes
BEFORE the slot allocation (which things, their y0, rows and blocks): that is the column check's
(scratchpad/gp/probes/sprite/ship_check.py), against the oracle.

R9: every mutant in MUTANTS -- one real edit of the fj text each, of every kind PR #93's review
rounds found: an offset, a stride, a bias, a field order, a dropped increment, an inserted pointer
step, an operand width, an index bound, a prearmed write, a narrow-arm read, a register written
through `r + dw`, the slot offset, the branch between slot A and slot B -- must make it fail.
"""
import re
import subprocess
import sys
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj

ROOT = Path(__file__).resolve().parents[2]
FJ_NAMES = ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
            "plane_bands.fj", "stream_render.fj")
CFG = Config()
VIEW_W = CFG.VIEW_W
STRIDE, B_BYTE = wr.SPR_SLOT_STRIDE, wr.SPR_SLOT_B_BYTE
SLOT_BYTES, BIAS, NSLOTS = wr.SPR_THING_SLOT_BYTES, wr.SPR_THING_Y0_BIAS, wr.SPR_THING_SLOTS
# the record's parameters as the emitter passes them (wall_renderer._thing_leaf_body)
REC_PARAMS = {"viewwc": CFG.VIEW_W, "buckets": wr.SPRITE_HEIGHT_BUCKETS, "slotstride": wr.SPR_SLOT_STRIDE,
              "deg": 1, "spn": 1 if wr.DEG_SPR_NEAR_TZ else 0,
              "nld": wr._spr_nlow(CFG) if wr.DEG_SPR_NEAR_TZ else 1}

# (slot id, y0, light row, block, first column, last column), recorded in this order: a later
# record into a column that holds A takes B; a third finds both slots spent
THINGS = [(1, -200, 3, 0x0102, 0, 1),
          (15, 0, 30, 0x0201, 15, 17),
          (16, 150, 31, 0x0003, 62, 66),
          (255, -32000, 17, 0x01FF, 158, 159),
          (17, 7, 5, 0x0100, 0, 0),              # column 0 again: fragment B
          (40, -1, 9, 0x0004, 15, 16),           # columns 15 and 16 again: B
          (41, 100, 2, 0x0005, 0, 0),            # column 0 a third time: both slots spent
          (42, 33, 4, 0x0006, 10, 14),           # 12..14 are hidden by a wall
          (43, 55, 6, 0x0007, 100, 101)]         # a fully transparent block: no fragment
HIDDEN = {12, 13, 14}
TRANSPARENT = {0x0007}
NBLOCKS = max(t[3] for t in THINGS) + 1
# each block's header: r0, last_rel (0 = fully transparent), the rest zero
HEADER = {b: (5 + b % 7, 0 if b in TRANSPARENT else 9 + b % 5) for b in range(NBLOCKS)}
# the read side's columns: (seed column, steps) -- empty, A, A+B, across the index bounds
LOADS = [(0, 0), (1, 0), (2, 0), (10, 0), (12, 0), (15, 0), (16, 0), (17, 0), (62, 0), (63, 1),
         (64, 0), (158, 0), (159, 0), (100, 0), (13, 3)]
DERIVE_BLOCK = 0x0102


def expected_memory():
    """sprflag, spslot and gpslot after THINGS are recorded -- the constants' layout"""
    sprflag, spslot, gpslot = [0] * VIEW_W, [0] * (VIEW_W * STRIDE), [0] * (NSLOTS * SLOT_BYTES)
    for sid, y0, light, blk, x1, x2 in THINGS:
        yb = (y0 + BIAS) & 0xFFFF
        fields = {"y0 lo": yb & 0xFF, "y0 hi": yb >> 8, "light row": light}
        for i, f in enumerate(wr.SPR_THING_SLOT_FIELDS):
            gpslot[sid * SLOT_BYTES + i] = fields[f]
        if blk in TRANSPARENT:
            continue
        frag = {"slot id": sid, "block lo": blk & 0xFF, "block hi": blk >> 8}
        for x in range(x1, x2 + 1):
            if x in HIDDEN or sprflag[x] == 2:
                continue
            base = x * STRIDE + (0 if sprflag[x] == 0 else B_BYTE)
            for i, f in enumerate(wr.SPR_FRAG_FIELDS):
                spslot[base + i] = frag[f]
            sprflag[x] += 1
    return sprflag, spslot, gpslot


def expected_reads():
    """what the read side must give: per LOADS column (sprfl, s, sblk lo, hi, sb, sblkb lo, hi),
    then per thing (y0 lo, y0 hi, light row)"""
    sprflag, spslot, _ = expected_memory()
    out = []
    for x0, k in LOADS:
        x = x0 + k
        a = {f: spslot[x * STRIDE + i] for i, f in enumerate(wr.SPR_FRAG_FIELDS)}
        b = {f: spslot[x * STRIDE + B_BYTE + i] for i, f in enumerate(wr.SPR_FRAG_FIELDS)}
        n = sprflag[x]
        frag_a = [a["slot id"], a["block lo"], a["block hi"]] if n >= 1 else [0, 0, 0]
        frag_b = [b["slot id"], b["block lo"], b["block hi"]] if n == 2 else [0, 0, 0]
        out += [n] + frag_a + frag_b
    for sid, y0, light, *_ in THINGS:
        out += [y0 & 0xFF, (y0 >> 8) & 0xFF, light]
    return out


def _code(text):
    return "\n".join(line.split("//")[0] for line in text.splitlines())


GLOBALS = ({d.split(":")[0].strip() for d in wr.hoisted_scratch_decls(CFG)}
           | {"drawn", "pclm", "sfflag", "sprflag", "sfslot", "spslot", "gpslot", "sprbank", "sp_dw",
              "ballow", "hdfl"})


def transplant(frame_text):
    """the record's code from the slot allocation to the end of its column loop, VERBATIM, as a
    harness macro -- and the call that gives it the emitter's parameter values"""
    body = frame_text[frame_text.index("    def thing_record_body"):]
    code = body[body.index("        hex.inc 2, gps_nslot"):body.index("      set_tstop:")]
    labels = re.findall(r"^\s*(\w+):\s*(?://.*)?$", code, re.M)
    words = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", _code(code)))
    params = [p for p in REC_PARAMS if p in words]
    macro = ("ns frame {\n    def lay_rec %s @ %s < %s {\n%s      ret:\n    }\n}\n"
             % (", ".join(params), ", ".join(labels + ["ret"]), ", ".join(sorted(words & GLOBALS)), code))
    return macro, "frame.lay_rec " + ", ".join(str(REC_PARAMS[p]) for p in params)


def _cells(values):
    return [";%d * dw" % v for v in values]


def hot_block(mem):
    """the real hot block's arrays in its order (wall_renderer: pclm, sfflag, sprflag, sfslot,
    spslot, gpslot), `drawn` just before them as the column check lays it"""
    sprflag, spslot, gpslot = mem
    return (["drawn:"] + _cells(1 if x in HIDDEN else 0 for x in range(VIEW_W))
            + ["pclm:"] + _cells([0] * (VIEW_W * CFG.PID_BYTES))
            + ["sfflag:"] + _cells([0] * VIEW_W)
            + ["sprflag:"] + _cells(sprflag)
            + ["sfslot:"] + _cells([0] * (VIEW_W * 16 ** CFG.SLOT_SHIFT))
            + ["spslot:"] + _cells(spslot)
            + ["gpslot:"] + _cells(gpslot))


def bank():
    blocks = []
    for b in range(NBLOCKS):
        r0, last = HEADER[b]
        blocks += _cells([r0, last] + [0] * (wr.SPR_BLOCK_STRIDE - 2))
    return wr.sprite_bank_header() + blocks


def emit(reg, nbytes):
    return ["    byte.emit %s" % (reg if i == 0 else "%s + %d*dw" % (reg, 2 * i)) for i in range(nbytes)]


DUMP = """def lay_dump arr, n @ loop, done < lay_p, lay_n, lay_v {
    hex.set w/4, lay_p, arr
    hex.set 4, lay_n, n
  loop:
    hex.read_byte_and_inc lay_v, lay_p
    byte.emit lay_v
    hex.dec 4, lay_n
    hex.if0 4, lay_n, done
    ;loop
  done:
}
"""
REGS = ["lay_p: hex.vec w/4", "lay_n: hex.vec 4", "lay_v: hex.vec 2", "lay_x: hex.vec 8",
        "lay_arm: hex.vec 2", "sp_dw: hex.vec 2", "ballow: hex.vec 1", "hdfl: hex.vec 1",
        "ld_sprfl: hex.vec 2", "ld_s: hex.vec 2", "ld_sblk: hex.vec 4", "ld_sb: hex.vec 2",
        "ld_sblkb: hex.vec 4", "dv_s: hex.vec 2", "dv_sblk: hex.vec 4", "dv_ybase: hex.vec 4",
        "dv_top: hex.vec 4", "dv_sy1: hex.vec 4", "dv_sy2: hex.vec 4", "dv_smidx: hex.vec 4",
        "dv_ptr: hex.vec w/4"]


def write_program(frame_text):
    macro, call = transplant(frame_text)
    main = ["stl.startup_and_init_all", generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
            "    hex.set 2, sp_dw, 1", "    hex.set 1, ballow, 1", "    hex.set 1, hdfl, 1"]
    for sid, y0, light, blk, x1, x2 in THINGS:
        main += ["    hex.set 2, gps_nslot, %d" % (sid - 1),       # the record takes the next slot id
                 "    hex.set 8, trb_y0, %d" % (y0 & 0xFFFFFFFF),
                 "    hex.set 2, trb_shade_row, %d" % light,
                 "    hex.set 8, trb_tx1, %d" % x1, "    hex.set 8, trb_tx2, %d" % x2,
                 "    hex.set 8, trb_tistep, 0",
                 "    hex.set w/4, trb_blk_const, %d" % blk,
                 "    " + call]
    main += ["    lay_dump sprflag, %d" % VIEW_W, "    lay_dump spslot, %d" % (VIEW_W * STRIDE),
             "    lay_dump gpslot, %d" % (NSLOTS * SLOT_BYTES), "    stl.loop"]
    zero = ([0] * VIEW_W, [0] * (VIEW_W * STRIDE), [0] * (NSLOTS * SLOT_BYTES))
    return "\n".join([macro, DUMP] + main + REGS + [wr.hoisted_scratch_fj(CFG)] + hot_block(zero) + bank()) + "\n"


def read_program():
    main = ["stl.startup_and_init_all", generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)]
    for x0, k in LOADS:
        main += ["    hex.set 8, lay_x, %d" % x0, "    frame.lines_spr_seed lay_x"]
        main += ["    frame.lines_spr_step"] * k
        main += ["    hex.read_byte lay_arm, p2_spfp",             # a hot-block arm, as the leaf's reads leave it
                 "    hex.set 1, p2_sdirty, 1",                    # an empty column zeroes the outputs
                 "    hex.set 2, ld_s, 0xAA", "    hex.set 4, ld_sblk, 0xAAAA",
                 "    hex.set 2, ld_sb, 0xAA", "    hex.set 4, ld_sblkb, 0xAAAA",
                 "    frame.lines_spr_load ld_sprfl, ld_s, ld_sblk, ld_sb, ld_sblkb"]
        main += emit("ld_sprfl", 1) + emit("ld_s", 1) + emit("ld_sblk", 2) + emit("ld_sb", 1) + emit("ld_sblkb", 2)
    for sid, *_ in THINGS:
        main += ["    hex.set 2, gps_cur_s, 0",                   # a new thing: the derive fetches its slot
                 "    hex.set 2, dv_s, %d" % sid, "    hex.set 4, dv_sblk, %d" % DERIVE_BLOCK,
                 "    stream.frag_derive dv_s, dv_sblk, dv_ybase, dv_top, dv_sy1, dv_sy2, dv_smidx, dv_ptr"]
        main += emit("gps_y0", 2) + emit("gps_lr", 1)
    main.append("    stl.loop")
    return "\n".join([DUMP] + main + REGS + [wr.hoisted_scratch_fj(CFG)] + hot_block(expected_memory()) + bank()) + "\n"


RUNNER = r"""
import sys
import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
io = FixedIO(b"")
term = fj.run(sys.argv[1], io_device=io, print_time=False, print_termination=False)
print(str(term.termination_cause))
print(io.get_output(allow_incomplete_output=True).hex())
"""


def run(tmp, name, program, texts=None, timeout=600):
    """assemble `program` against the fj sources -- `texts` replaces some ({file: text}) -- and run
    it in a subprocess with a timeout (fj.run has no op limit, and a broken layout may never end):
    the output bytes, or None if it did not end on its closing loop"""
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    files = []
    for f in FJ_NAMES:
        p = tmp / f
        p.write_text((texts or {}).get(f) or (ROOT / "src/fj" / f).read_text(encoding="utf-8"), encoding="utf-8")
        files.append(p.resolve())
    prog = tmp / (name + ".fj")
    prog.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *files, prog.resolve()], out, memory_width=W, print_time=False)
    try:
        r = subprocess.run([sys.executable, "-c", RUNNER, str(out)], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    cause, _, data = r.stdout.strip().partition("\n")
    return list(bytes.fromhex(data.strip())) if "loop" in cause.lower() else None


def fj_text(name):
    return (ROOT / "src/fj" / name).read_text(encoding="utf-8")


def flat(mem):
    return [v for part in mem for v in part]


def test_the_record_writes_every_byte_where_the_constants_say(tmp_path):
    got = run(tmp_path, "write", write_program(fj_text("frame_render.fj")))
    want = flat(expected_memory())
    assert got is not None, "the record's program did not end on its loop"
    names = ["sprflag"] * VIEW_W + ["spslot"] * (VIEW_W * STRIDE) + ["gpslot"] * (NSLOTS * SLOT_BYTES)
    offs = list(range(VIEW_W)) + list(range(VIEW_W * STRIDE)) + list(range(NSLOTS * SLOT_BYTES))
    bad = [(names[i], offs[i], g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert len(got) == len(want) and not bad, (len(got), len(want), bad[:10])
    # not vacuous: every kind of record happened
    sprflag = expected_memory()[0]
    assert sprflag[0] == 2 and sprflag[15] == 2 and sprflag[64] == 1 and sprflag[159] == 1
    assert all(sprflag[x] == 0 for x in HIDDEN | {100, 101})


def test_the_load_and_the_derive_read_every_field_where_the_constants_say(tmp_path):
    got = run(tmp_path, "read", read_program())
    want = expected_reads()
    assert got is not None, "the read side's program did not end on its loop"
    assert got == want, [(i, g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w][:10]


# (label, side, file, old, new): one real edit of the fj text each; `side` is the program it moves
_W = "\n        "
MUTANTS = [
    ("slot B's byte", "write", "frame_render.fj",
     "hex.set w/4, trb_slot_ofs, 8", "hex.set w/4, trb_slot_ofs, 9"),
    ("the record's bias", "write", "frame_render.fj",
     "hex.add_constant 8, gps_yb8, 32768", "hex.add_constant 8, gps_yb8, 32767"),
    ("the record's fragment order", "write", "frame_render.fj",
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw",
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk + 2*dw" + _W + "frame.write_byte5 trb_tbl_p, trb_blk"),
    ("the record's fragment: an increment dropped", "write", "frame_render.fj",
     "hex.write_byte_and_inc trb_tbl_p, gps_s_rec", "hex.write_byte trb_tbl_p, gps_s_rec"),
    ("the record's fragment: a step inserted", "write", "frame_render.fj",
     "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw", "hex.ptr_inc trb_tbl_p" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw"),
    ("the record's slot: an increment dropped", "write", "frame_render.fj",
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw", "hex.write_byte gps_ptr, gps_yb8 + 2*dw"),
    ("the record's slot: a step inserted", "write", "frame_render.fj",
     "hex.write_byte gps_ptr, trb_shade_row", "hex.ptr_inc gps_ptr" + _W + "hex.write_byte gps_ptr, trb_shade_row"),
    ("the record's slot: a prearmed write", "write", "frame_render.fj",
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw", "frame.write_byte_and_inc_prearmed gps_ptr, gps_yb8 + 2*dw"),
    ("the slot offset never added", "write", "frame_render.fj",
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.zero w/4, trb_slot_ofs"),
    ("the slot offset bumped", "write", "frame_render.fj",
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.inc 1, trb_slot_ofs" + _W + "hex.add w/4, trb_tab_idx, trb_slot_ofs"),
    ("slot A falls into slot B", "write", "frame_render.fj",
     "hex.set 2, trb_slot_flag, 1" + _W + ";slot_done", "hex.set 2, trb_slot_flag, 1"),
    ("the column index one nibble wide", "write", "frame_render.fj",
     "hex.mov 2, trb_tab_idx, trb_col_x", "hex.mov 1, trb_tab_idx, trb_col_x"),
    ("the column index shifted back", "write", "frame_render.fj",
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.shr_hex w/4, 1, trb_tab_idx" + _W + "hex.add w/4, trb_tab_idx, trb_slot_ofs"),
    ("the record's column stride", "write", "frame_render.fj",
     "rep(slotstride/16, k) hex.shl_hex w/4, 1, trb_tab_idx", "rep(slotstride/8, k) hex.shl_hex w/4, 1, trb_tab_idx"),
    ("the record's index bound", "write", "frame_render.fj",
     "frame.ptr_index6 trb_tbl_p, trb_tbl_b, trb_tab_idx" + _W + "// P2-5", "frame.ptr_index4 trb_tbl_p, trb_tbl_b, trb_tab_idx" + _W + "// P2-5"),
    ("the slot id one nibble wide", "write", "frame_render.fj",
     "hex.mov 2, gps_sidx, gps_s_rec", "hex.mov 1, gps_sidx, gps_s_rec"),
    ("the slot index written through r + dw", "write", "frame_render.fj",
     "hex.shl_bit w/4, gps_sidx" + _W + "hex.shl_bit w/4, gps_sidx", "hex.shl_bit w/4, gps_sidx" + _W + "hex.inc 1, gps_sidx + dw" + _W + "hex.shl_bit w/4, gps_sidx"),
    # the review's round-3 edits, exactly as posted
    ("r3: the record's first slot write prearmed", "write", "frame_render.fj",
     "hex.write_byte_and_inc gps_ptr, gps_yb8" + _W, "frame.write_byte_and_inc_prearmed gps_ptr, gps_yb8" + _W),
    ("r3: the slot index bumped through r + dw", "write", "frame_render.fj",
     "hex.set w/4, gps_sbase, gpslot" + _W + "frame.ptr_index gps_ptr", "hex.inc 1, gps_sidx + dw" + _W + "hex.set w/4, gps_sbase, gpslot" + _W + "frame.ptr_index gps_ptr"),
    ("r3: a one-nibble shift after the slot offset", "write", "frame_render.fj",
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.add w/4, trb_tab_idx, trb_slot_ofs" + _W + "hex.shr_hex 1, 1, trb_tab_idx"),
    ("r3: slot A's branch taken to slot B", "write", "frame_render.fj",
     "hex.if0 2, trb_sprflag_v, slot_a", "hex.if0 2, trb_sprflag_v, slot_b"),
    ("the load's skip to B", "read", "frame_render.fj",
     "hex.ptr_add spslot_p, 5", "hex.ptr_add spslot_p, 4"),
    ("the load: an increment dropped", "read", "frame_render.fj",
     "frame.read0_byte_and_inc sblk + 2*dw, spslot_p", "frame.read_byte5 sblk + 2*dw, spslot_p"),
    ("the load: a step inserted", "read", "frame_render.fj",
     "frame.read0_byte_and_inc sblkb, spslot_p", "hex.ptr_inc spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p"),
    ("the load: a narrow-arm read", "read", "frame_render.fj",
     "frame.read0_byte_and_inc s, spslot_p", "frame.read3_and_inc s, spslot_p"),
    ("the load's field order", "read", "frame_render.fj",
     "frame.read0_byte_and_inc sblkb, spslot_p" + _W + "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p",
     "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p"),
    ("the seed's column stride", "read", "frame_render.fj",
     "hex.shl_hex w/4, 1, sidx ", "hex.shl_hex w/4, 2, sidx "),
    ("the seed's index bound", "read", "frame_render.fj",
     "frame.ptr_index5 p2_sspp, bteam, sidx", "frame.ptr_index4 p2_sspp, bteam, sidx"),
    ("the seed's column one nibble wide", "read", "frame_render.fj",
     "hex.mov 2, sidx, x1" + _W + "hex.shl_hex w/4, 1, sidx ", "hex.mov 1, sidx, x1" + _W + "hex.shl_hex w/4, 1, sidx "),
    ("the step's column stride", "read", "frame_render.fj",
     "hex.ptr_add p2_sspp, 16", "hex.ptr_add p2_sspp, 8"),
    ("the derive's bias", "read", "stream_render.fj",
     "hex.sub_constant 4, gps_y0, 32768", "hex.sub_constant 4, gps_y0, 16384"),
    ("the derive: an increment dropped", "read", "stream_render.fj",
     "hex.read_byte_and_inc gps_y0 + 2*dw, ptr", "hex.read_byte gps_y0 + 2*dw, ptr"),
    ("the derive: a step inserted", "read", "stream_render.fj",
     "hex.read_byte gps_lr, ptr", "hex.ptr_inc ptr" + _W + "hex.read_byte gps_lr, ptr"),
    ("the derive's field order", "read", "stream_render.fj",
     "hex.read_byte_and_inc gps_y0, ptr" + _W + "hex.read_byte_and_inc gps_y0 + 2*dw, ptr",
     "hex.read_byte_and_inc gps_y0 + 2*dw, ptr" + _W + "hex.read_byte_and_inc gps_y0, ptr"),
    ("the derive's slot id one nibble wide", "read", "stream_render.fj",
     "hex.mov 2, gps_sidx, s", "hex.mov 1, gps_sidx, s"),
]


@pytest.mark.parametrize("label, side, name, old, new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_a_mutated_layout_fails(tmp_path, label, side, name, old, new):
    """R9: each mutant edits the real fj text once -- and the side it moves must no longer hold"""
    text = fj_text(name)
    assert text.count(old) == 1, "the mutant's site is not in %s: %r" % (name, old)
    texts = {name: text.replace(old, new)}
    if side == "write":
        got, want = run(tmp_path, "w", write_program(texts.get("frame_render.fj", fj_text("frame_render.fj"))), texts, 120), flat(expected_memory())
    else:
        got, want = run(tmp_path, "r", read_program(), texts, 120), expected_reads()
    assert got != want, "%s: the layout still holds -- the test has no teeth here" % label
