"""M7 P1.4 (PR #93's review, R6 / R9) -- the two slot layouts, EXECUTED.

A column's fragments live in `spslot`, a thing's constants in `gpslot`. frame.thing_record_body writes
both; frame.lines_spr_seed / lines_spr_step / lines_spr_load read a column's fragments, and
stream.frag_derive a thing's constants. wall_renderer states the layouts once: SPR_SLOT_STRIDE,
SPR_FRAG_FIELDS, SPR_SLOT_B_BYTE, SPR_THING_SLOT_BYTES, SPR_THING_SLOT_FIELDS, SPR_THING_Y0_BIAS.
This RUNS the shipped fj and holds every byte and every register to them -- nothing is modelled:

  write  The record's code from its slot allocation (`hex.inc 2, gps_nslot`) to the end of its
         column loop, transplanted VERBATIM from frame.thing_record_body into a harness macro, gets
         its parameters from the def's own parameter list zipped with the emitter's own
         `frame.thing_record_body ...` arguments -- wall_renderer's f-string, evaluated from its
         source for both record bodies (mt 1 and 0), `deg_flag` its bare literal; the other locals
         the f-string names are placeholders, varied, that the transplanted range must not depend
         on (`record_binding` refuses anything else). It records THINGS -- columns across the 16, 64
         and 1,024-index bounds up to 159, a first column below 0 and a last above 159 (both
         clamps), slot ids 1..255 across 16, fragments A and B, B refused by `ballow`, both slots
         spent, columns a wall hides, a fully transparent block, a texture step that moves the
         column and its clamp, both block strides (`hdfl`), y0 either side of zero -- and the
         operand ranges the shipped sprites reach: a last texture column past 16 (the shipped bank
         goes to 62), u past 15, u * BUCKETS and u * NLD past 255, a block past 0x1000. Then EVERY byte
         of the hot block -- pclm through the cell after drawn, 6,785 of them -- must be the
         constants' layout of what was recorded: the bytes the layout names hold the fields, drawn
         its walls, and every other byte is still zero.
  read   From memory laid out by the constants, the real seed (and step) and load give each
         column's fragments, and the real derive each thing's y0 and light row.

Each side is held to the constants ON ITS OWN, so a change made alike on both sides that the
constants do not describe fails too. The expected bytes come from the constants and THINGS alone.

The harness lays its hot block out as the build does: `pad 16384` (the block starts an arm5 window,
16,384 ops, and all of it fits in that one window), then pclm, sfflag, sprflag, sfslot, spslot,
gpslot and drawn in the real order, drawn followed by a zero cell as the build's `wrej: hex.vec 1`
follows it (a column past the right edge reads that cell as its wall) -- the real block holds more
arrays between gpslot and drawn, so the offsets inside the window differ.

What it does NOT cover:
  * the shipped binary's addresses: only the window the narrow arms need is the build's;
  * what the record computes BEFORE its slot allocation -- which things it accepts, their y0, light
    rows and blocks. The column check (scratchpad/gp/probes/sprite/ship_check.py) does not run it
    either: it feeds the oracle's values to this same code. The shipped binary's gates hold it,
    against the oracle, on the frames they play (m2_std_gate and m3_gate byte- and state-exact,
    b0_scenarios pixel-exact).

R9: every mutant in MUTANTS -- one real edit of the fj text, or of the emitter's call, each: every
kind PR #93's review rounds found, the reviewer's own edits among them as posted -- must make its
side fail; a mutant that does not assemble is an error, never a catch. And every edit in NEUTRAL
moves no byte (unreachable filler deleted) and must still pass: the harness does not fail on where
the code happens to land.
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
EMITTER = "wall_renderer.py"
CFG = Config()
VIEW_W = CFG.VIEW_W
STRIDE, B_BYTE = wr.SPR_SLOT_STRIDE, wr.SPR_SLOT_B_BYTE
SLOT_BYTES, BIAS, NSLOTS = wr.SPR_THING_SLOT_BYTES, wr.SPR_THING_Y0_BIAS, wr.SPR_THING_SLOTS
BUCKETS, NLD = wr.SPRITE_HEIGHT_BUCKETS, wr._spr_nlow(CFG)       # the block strides, hdfl 1 / 0
ARM5_WINDOW = 16384                                              # ops: 16^5 bits of 2 * W-bit ops

# (slot id, y0, light row, block base, first column, last column, texture step (16.16), hdfl,
#  ballow, sp_dw), recorded in this order: a later record into a column that holds A takes B
#  (if ballow lets it), a third finds both slots spent
THINGS = [(1, -200, 3, 0x0102, 0, 1, 0, 1, 1, 1),
          (15, 0, 30, 0x0201, 15, 17, 0, 1, 1, 1),
          (16, 150, 31, 0x0003, 62, 66, 0, 1, 1, 1),
          (255, -32000, 17, 0x01FF, 158, 159, 0, 1, 1, 1),
          (17, 7, 5, 0x0100, 0, 0, 0, 1, 1, 1),                   # column 0 again: B
          (40, -1, 9, 0x0004, 15, 16, 0, 1, 1, 1),                # columns 15, 16 again: B
          (41, 100, 2, 0x0005, 0, 0, 0, 1, 1, 1),                 # column 0 a third time: both spent
          (42, 33, 4, 0x0006, 10, 14, 0, 1, 1, 1),                # 12..14 hidden by a wall
          (43, 55, 6, 0x0007, 100, 101, 0, 1, 1, 1),              # a fully transparent block
          (44, 12, 7, 0x0008, 17, 17, 0, 1, 0, 1),                # column 17 holds A, ballow 0: no B
          (45, -5, 8, 0x0009, -3, 2, 0, 1, 1, 1),                 # a first column below 0
          (46, 20, 10, 0x0010, 157, 170, 0, 1, 1, 1),             # a last column above 159
          (47, 60, 11, 0x0020, 30, 37, 0x8000, 1, 1, 3),          # half a texel a column, clamped at 2
          (48, 61, 12, 0x0030, 40, 45, 0x10000, 0, 1, 9),         # hdfl 0: the nld stride
          (49, 62, 13, 0x0040, -2, 3, 0x10000, 1, 1, 8),          # below 0 WITH a step: u starts at 2
          # the shipped operand ranges (review round 5): E1M1's sprites reach 62 texture columns and
          # its bank 22,837 blocks, so u, u * BUCKETS, u * NLD and the block index leave the widths
          # where a narrowed op is still exact
          (50, 70, 14, 0x0040, 110, 126, 0x40000, 1, 1, 63),      # u 0..64 by 4, clamped at 62; u*32 to 1,984
          (51, 71, 15, 0x0030, 130, 139, 0x50000, 0, 1, 45),      # hdfl 0: u 0..45 by 5, clamped at 44; u*9 to 396
          (52, 72, 16, 0x1007, 140, 141, 0, 1, 1, 1)]             # a block past 0x1000 whose low three
                                                                  # nibbles name the transparent 0x0007
HIDDEN = {12, 13, 14}
TRANSPARENT = {0x0007}


def _columns(x1, x2, istep, hdfl, sp_dw, base):
    """the record's column walk for one thing, from THINGS alone: (column, block) per column"""
    dw_max = (sp_dw - 1) & 0xFF
    frac = ((-x1) * istep) & 0xFFFFFFFF if x1 < 0 else 0
    for x in range(max(x1, 0), min(x2, VIEW_W - 1) + 1):
        u = min((frac >> 16) & 0xFF, dw_max)
        yield x, (u * (BUCKETS if hdfl else NLD) + base) & 0xFFFF
        frac = (frac + istep) & 0xFFFFFFFF


NBLOCKS = 1 + max(b for t in THINGS for _, b in _columns(t[4], t[5], t[6], t[7], t[9], t[3]))
# each block's header: r0, last_rel (0 = fully transparent), the rest zero
HEADER = {b: (5 + b % 7, 0 if b in TRANSPARENT else 9 + b % 5) for b in range(NBLOCKS)}
# the read side's columns: (seed column, steps) -- empty, A, A+B, across the index bounds
LOADS = [(0, 0), (1, 0), (2, 0), (3, 0), (10, 0), (12, 0), (15, 0), (16, 0), (17, 0), (31, 0),
         (36, 1), (44, 0), (62, 0), (63, 1), (64, 0), (157, 0), (158, 0), (159, 0), (100, 0), (13, 3),
         (110, 0), (118, 5), (126, 0), (135, 0), (140, 0), (141, 0)]
DERIVE_BLOCK = 0x0102


def expected_memory():
    """sprflag, spslot and gpslot after THINGS are recorded -- the constants' layout"""
    sprflag, spslot, gpslot = [0] * VIEW_W, [0] * (VIEW_W * STRIDE), [0] * (NSLOTS * SLOT_BYTES)
    for sid, y0, light, base, x1, x2, istep, hdfl, ballow, sp_dw in THINGS:
        yb = (y0 + BIAS) & 0xFFFF
        fields = {"y0 lo": yb & 0xFF, "y0 hi": yb >> 8, "light row": light}
        for i, f in enumerate(wr.SPR_THING_SLOT_FIELDS):
            gpslot[sid * SLOT_BYTES + i] = fields[f]
        for x, blk in _columns(x1, x2, istep, hdfl, sp_dw, base):
            n = sprflag[x]
            if x in HIDDEN or n == 2 or (n == 1 and not ballow) or HEADER[blk][1] == 0:
                continue
            frag = {"slot id": sid, "block lo": blk & 0xFF, "block hi": blk >> 8}
            for i, f in enumerate(wr.SPR_FRAG_FIELDS):
                spslot[x * STRIDE + (B_BYTE if n else 0) + i] = frag[f]
            sprflag[x] = n + 1
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


def block_arrays(mem):
    """the hot block's arrays in the build's order, with the contents `mem` gives sprflag, spslot and
    gpslot: [(label, cells)]"""
    sprflag, spslot, gpslot = mem
    return [("pclm", [0] * (VIEW_W * CFG.PID_BYTES)), ("sfflag", [0] * VIEW_W), ("sprflag", list(sprflag)),
            ("sfslot", [0] * (VIEW_W * 16 ** CFG.SLOT_SHIFT)), ("spslot", list(spslot)),
            ("gpslot", list(gpslot)), ("drawn", [1 if x in HIDDEN else 0 for x in range(VIEW_W)]),
            ("lay_wrej", [0])]


def expected_block():
    """every byte of the hot block after THINGS are recorded, and where each one is"""
    where, values = [], []
    for label, cells in block_arrays(expected_memory()):
        where += [(label, i) for i in range(len(cells))]
        values += cells
    return where, values


def _code(text):
    return "\n".join(line.split("//")[0] for line in text.splitlines())


GLOBALS = ({d.split(":")[0].strip() for d in wr.hoisted_scratch_decls(CFG)}
           | {"drawn", "pclm", "sfflag", "sprflag", "sfslot", "spslot", "gpslot", "sprbank", "sp_dw",
              "ballow", "hdfl"})


class BindingRefused(Exception):
    """the emitter's call does not give the transplanted range ONE set of values"""


# the locals the emitter's f-string names that the test does not reproduce: placeholders, each
# evaluated at two values -- the transplanted range's arguments must not move with them
PLACEHOLDERS = [dict(proj=0x11111, _MT_NTH=1, _MT_NLTI=1, ablate=frozenset()),
                dict(proj=0x2222222, _MT_NTH=3, _MT_NLTI=5, ablate=frozenset({"thingtwice"}))]


def record_bindings(frame_text, emitter_text):
    """every binding of thing_record_body's parameters the emitter's text can give: the def's own
    parameter list (frame_render.fj) zipped with the emitter's own argument list --
    wall_renderer's `frame.thing_record_body ...` f-string, evaluated from its source with its
    module constants, `deg_flag` as its one bare literal, for BOTH record bodies (mt 1, the runtime
    table; mt 0, the baked leaf -- `_thing_leaf_body` instantiates both in the game tier) and at
    each PLACEHOLDERS value. Anything else is refused: this reads the emitter, it does not model it."""
    m = re.search(r"^    def thing_record_body (.*?)^\s*@", frame_text, re.M | re.S)
    params = [p.strip() for p in m.group(1).replace("\\", " ").split(",")]
    a = emitter_text.index('f"frame.thing_record_body ')
    call_src = emitter_text[a:emitter_text.index("]", a)]
    deg = re.findall(r"^\s*deg_flag = ([^#\n]*?)\s*(?:#.*)?$", emitter_text, re.M)
    if len(deg) != 1 or not deg[0].isdigit():
        raise BindingRefused("deg_flag is not one bare literal: %r" % deg)
    if emitter_text.count("_thing_leaf_body(") < 2:
        raise BindingRefused("the emitter's record bodies are not the two this binds")
    out = []
    for mt in (1, 0):
        for ph in PLACEHOLDERS:
            ns = dict(vars(wr), cfg=CFG, deg_flag=int(deg[0]), mt=mt, **ph)
            call = eval("(" + call_src + ")", ns)               # the emitter's own text, nothing else
            args = [x.strip() for x in call[len("frame.thing_record_body "):].split(",")]
            if len(args) != len(params):
                raise BindingRefused("%d arguments for %d parameters" % (len(args), len(params)))
            out.append(dict(zip(params, args)))
    return out


def transplant(frame_text, emitter_text):
    """the record's code from the slot allocation to the end of its column loop, VERBATIM, as a
    harness macro -- and the call that binds its parameters as the shipped build does"""
    body = frame_text[frame_text.index("    def thing_record_body"):]
    code = body[body.index("        hex.inc 2, gps_nslot"):body.index("      set_tstop:")]
    labels = re.findall(r"^\s*(\w+):\s*(?://.*)?$", code, re.M)
    words = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", _code(code)))
    bindings = record_bindings(frame_text, emitter_text)
    params = [p for p in bindings[0] if p in words]
    for p in params:
        seen = {b[p] for b in bindings}
        if len(seen) != 1:
            raise BindingRefused("the record bodies or a placeholder bind %s to %s" % (p, sorted(seen)))
    bound = bindings[0]
    macro = ("ns frame {\n    def lay_rec %s @ %s < %s {\n%s      ret:\n    }\n}\n"
             % (", ".join(params), ", ".join(labels + ["ret"]), ", ".join(sorted(words & GLOBALS)), code))
    return macro, "frame.lay_rec " + ", ".join(bound[p] for p in params)


def _cells(values):
    return [";%d * dw" % v for v in values]


def hot_block(mem):
    """laid out as the build lays its hot block (wall_renderer: `pad 16384`, then pclm, sfflag,
    sprflag, sfslot, spslot, gpslot ... drawn, wrej)"""
    block = []
    for label, cells in block_arrays(mem):
        block += [label + ":"] + _cells(cells)
    assert sum(not c.endswith(":") for c in block) <= ARM5_WINDOW, "the block outgrew one arm5 window"
    return ["pad %d" % ARM5_WINDOW] + block


def bank():
    """the bank, NBLOCKS blocks of SPR_BLOCK_STRIDE cells: a used block's header, zeros elsewhere
    (runs of zero cells as `rep(n, i) stl.fj 0, 0`, the zero cell the layout freezes use)"""
    out, zeros = list(wr.sprite_bank_header()), 0
    used = {blk for t in THINGS for _, blk in _columns(t[4], t[5], t[6], t[7], t[9], t[3])} | {DERIVE_BLOCK}
    for b in range(NBLOCKS):
        if b not in used:
            zeros += wr.SPR_BLOCK_STRIDE
            continue
        if zeros:
            out.append("rep(%d, i) stl.fj 0, 0" % zeros)
        out += _cells(HEADER[b])
        zeros = wr.SPR_BLOCK_STRIDE - 2
    if zeros:
        out.append("rep(%d, i) stl.fj 0, 0" % zeros)
    return out


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
HEAD = ["stl.startup_and_init_all", generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)]


def write_program(frame_text, emitter_text):
    macro, call = transplant(frame_text, emitter_text)
    main = list(HEAD)
    for sid, y0, light, base, x1, x2, istep, hdfl, ballow, sp_dw in THINGS:
        main += ["    hex.set 2, gps_nslot, %d" % (sid - 1),       # the record takes the next slot id
                 "    hex.set 8, trb_y0, %d" % (y0 & 0xFFFFFFFF), "    hex.set 2, trb_shade_row, %d" % light,
                 "    hex.set 8, trb_tx1, %d" % (x1 & 0xFFFFFFFF), "    hex.set 8, trb_tx2, %d" % (x2 & 0xFFFFFFFF),
                 "    hex.set 8, trb_tistep, %d" % istep, "    hex.set w/4, trb_blk_const, %d" % base,
                 "    hex.set 1, hdfl, %d" % hdfl, "    hex.set 1, ballow, %d" % ballow,
                 "    hex.set 2, sp_dw, %d" % sp_dw, "    " + call]
    main += ["    lay_dump pclm, %d" % len(expected_block()[1]), "    stl.loop"]
    zero = ([0] * VIEW_W, [0] * (VIEW_W * STRIDE), [0] * (NSLOTS * SLOT_BYTES))
    return "\n".join([macro, DUMP] + main + REGS + [wr.hoisted_scratch_fj(CFG)] + hot_block(zero) + bank()) + "\n"


def read_program():
    main = list(HEAD)
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


def source(name):
    return (ROOT / ("src/doomfj" if name == EMITTER else "src/fj") / name).read_text(encoding="utf-8")


def run(tmp, name, program, texts=None, timeout=600):
    """assemble `program` against the fj sources -- `texts` replaces some ({file: text}) -- and run
    it in a subprocess with a timeout (fj.run has no op limit, and a broken layout may never end):
    the output bytes, or None if it did not end on its closing loop"""
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    files = []
    for f in FJ_NAMES:
        p = tmp / f
        p.write_text((texts or {}).get(f) or source(f), encoding="utf-8")
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


def run_side(tmp, side, texts=None, timeout=600):
    """(got, want) for one side, the fj and the emitter's call as `texts` has them; a binding the
    emitter's text does not give in ONE way is `got` = the refusal, never a run"""
    texts = texts or {}
    if side == "write":
        try:
            prog = write_program(texts.get("frame_render.fj") or source("frame_render.fj"),
                                 texts.get(EMITTER) or source(EMITTER))
        except BindingRefused as e:
            return "binding refused: %s" % e, expected_block()[1]
        return run(tmp, "w", prog, texts, timeout), expected_block()[1]
    return run(tmp, "r", read_program(), texts, timeout), expected_reads()


def test_the_record_writes_every_byte_where_the_constants_say(tmp_path):
    got, want = run_side(tmp_path, "write")
    assert isinstance(got, list), got or "the record's program did not end on its loop"
    where = expected_block()[0]
    bad = [(where[i], g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert len(got) == len(want) and not bad, (len(got), len(want), bad[:10])
    # not vacuous: every kind of record happened (the expectation is what `got` just equalled)
    sprflag, spslot, _ = expected_memory()
    assert sprflag[0] == 2 and sprflag[15] == 2 and sprflag[64] == 1 and sprflag[159] == 2
    assert sprflag[17] == 1, "ballow 0 must leave column 17 at A only"
    assert all(sprflag[x] == 0 for x in HIDDEN | {100, 101})
    # half a texel a column: u moves every second column, so the block does at 32, 34, 36 (clamped)
    assert spslot[32 * STRIDE + 1] != spslot[30 * STRIDE + 1], "the texture step moved no block"
    assert spslot[44 * STRIDE + 1] != spslot[40 * STRIDE + 1], "the nld stride moved no block"
    # ... and the shipped ranges were reached: u*32 and u*9 past 255, a block past 0x1000
    blocks = [spslot[x * STRIDE + 1] | spslot[x * STRIDE + 2] << 8 for x in range(VIEW_W) if sprflag[x]]
    assert max(blocks) >= 0x1000 and any(b - 0x40 > 255 for b in blocks if 0x40 <= b < 0x1000)
    assert spslot[139 * STRIDE + 1] | spslot[139 * STRIDE + 2] << 8 == 0x30 + 44 * NLD


def test_the_load_and_the_derive_read_every_field_where_the_constants_say(tmp_path):
    got, want = run_side(tmp_path, "read")
    assert got is not None, "the read side's program did not end on its loop"
    assert got == want, [(i, g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w][:10]


# (label, side, file, old, new): one real edit each -- of the fj text, or of the emitter's call
_W = "\n        "
FR, SR = "frame_render.fj", "stream_render.fj"
MUTANTS = [
    ("slot B's byte", "write", FR, "hex.set w/4, trb_slot_ofs, 8", "hex.set w/4, trb_slot_ofs, 9"),
    ("the record's bias", "write", FR, "hex.add_constant 8, gps_yb8, 32768", "hex.add_constant 8, gps_yb8, 32767"),
    ("the record's fragment order", "write", FR,
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw",
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk + 2*dw" + _W + "frame.write_byte5 trb_tbl_p, trb_blk"),
    ("the record's fragment: an increment dropped", "write", FR,
     "hex.write_byte_and_inc trb_tbl_p, gps_s_rec", "hex.write_byte trb_tbl_p, gps_s_rec"),
    ("the record's fragment: a step inserted", "write", FR,
     "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw", "hex.ptr_inc trb_tbl_p" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw"),
    ("the record's slot: an increment dropped", "write", FR,
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw", "hex.write_byte gps_ptr, gps_yb8 + 2*dw"),
    ("the record's slot: a step inserted", "write", FR,
     "hex.write_byte gps_ptr, trb_shade_row", "hex.ptr_inc gps_ptr" + _W + "hex.write_byte gps_ptr, trb_shade_row"),
    ("the record's slot: a prearmed write", "write", FR,
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw", "frame.write_byte_and_inc_prearmed gps_ptr, gps_yb8 + 2*dw"),
    ("the slot offset never added", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.zero w/4, trb_slot_ofs"),
    ("the slot offset bumped", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.inc 1, trb_slot_ofs" + _W + "hex.add w/4, trb_tab_idx, trb_slot_ofs"),
    ("slot A falls into slot B", "write", FR, "hex.set 2, trb_slot_flag, 1" + _W + ";slot_done", "hex.set 2, trb_slot_flag, 1"),
    ("the column index one nibble wide", "write", FR, "hex.mov 2, trb_tab_idx, trb_col_x", "hex.mov 1, trb_tab_idx, trb_col_x"),
    ("the column index shifted back", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.shr_hex w/4, 1, trb_tab_idx" + _W + "hex.add w/4, trb_tab_idx, trb_slot_ofs"),
    ("the record's column stride", "write", FR,
     "rep(slotstride/16, k) hex.shl_hex w/4, 1, trb_tab_idx", "rep(slotstride/8, k) hex.shl_hex w/4, 1, trb_tab_idx"),
    ("the record's index bound", "write", FR,
     "frame.ptr_index6 trb_tbl_p, trb_tbl_b, trb_tab_idx" + _W + "// P2-5", "frame.ptr_index4 trb_tbl_p, trb_tbl_b, trb_tab_idx" + _W + "// P2-5"),
    ("the slot id one nibble wide", "write", FR, "hex.mov 2, gps_sidx, gps_s_rec", "hex.mov 1, gps_sidx, gps_s_rec"),
    ("the slot index written through r + dw", "write", FR,
     "hex.shl_bit w/4, gps_sidx" + _W + "hex.shl_bit w/4, gps_sidx", "hex.shl_bit w/4, gps_sidx" + _W + "hex.inc 1, gps_sidx + dw" + _W + "hex.shl_bit w/4, gps_sidx"),
    ("the nld stride one block long", "write", FR,
     "rep(spn, k) hex.mul_const w/4, trb_blk, trb_blk, nld", "rep(spn, k) hex.mul_const w/4, trb_blk, trb_blk, nld + 1"),
    # the review's round-3 edits, exactly as posted
    ("r3: the record's first slot write prearmed", "write", FR,
     "hex.write_byte_and_inc gps_ptr, gps_yb8" + _W, "frame.write_byte_and_inc_prearmed gps_ptr, gps_yb8" + _W),
    ("r3: the slot index bumped through r + dw", "write", FR,
     "hex.set w/4, gps_sbase, gpslot" + _W + "frame.ptr_index gps_ptr", "hex.inc 1, gps_sidx + dw" + _W + "hex.set w/4, gps_sbase, gpslot" + _W + "frame.ptr_index gps_ptr"),
    ("r3: a one-nibble shift after the slot offset", "write", FR,
     "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.add w/4, trb_tab_idx, trb_slot_ofs" + _W + "hex.shr_hex 1, 1, trb_tab_idx"),
    ("r3: slot A's branch taken to slot B", "write", FR, "hex.if0 2, trb_sprflag_v, slot_a", "hex.if0 2, trb_sprflag_v, slot_b"),
    ("r3: the record's column shift two nibbles wide", "write", FR,
     "rep(slotstride/16, k) hex.shl_hex w/4, 1, trb_tab_idx", "rep(slotstride/16, k) hex.shl_hex 2, 1, trb_tab_idx"),
    ("r3: the record's block-lo write prearmed", "write", FR,
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk" + _W, "frame.write_byte_and_inc_prearmed trb_tbl_p, trb_blk" + _W),
    ("r3: the seed's column shift two nibbles wide", "read", FR, "hex.shl_hex w/4, 1, sidx ", "hex.shl_hex 2, 1, sidx "),
    # the review's round-4 edits
    ("r4: B allowed whatever ballow says", "write", FR,
     "rep(deg, k) hex.if0 1, ballow, col_next", "rep(deg, k) hex.if0 1, ballow, slot_a"),
    ("r4: the right-edge clamp never fires", "write", FR,
     "hex.scmp 8, trb_tx2, trb_cbound, x2_done, x2_done, x2_clamp", "hex.scmp 8, trb_tx2, trb_cbound, x2_done, x2_done, x2_done"),
    ("r4: the clamp one column wide", "write", FR, "        hex.dec 8, trb_cbound" + "\n", ""),
    ("r4: the def's buckets and slotstride swapped", "write", FR,
     "viewwc, viewh, ds, buckets, slotstride, ttwice,", "viewwc, viewh, ds, slotstride, buckets, ttwice,"),
    ("r4: the emitter passes twice the slot stride", "write", EMITTER,
     "{SPRITE_HEIGHT_BUCKETS}, {SPR_SLOT_STRIDE}, ", "{SPRITE_HEIGHT_BUCKETS}, {2 * SPR_SLOT_STRIDE}, "),
    # the review's round-5 edits
    ("r5: deg_flag computed per tier", "write", EMITTER,
     "    deg_flag = 1 ", "    deg_flag = 1 if not standalone else 0 "),
    ("r5: the baked leaf's deg 0", "write", EMITTER, "{deg_flag}, {DEG_SOFT_SCENERY}", "{deg_flag if mt else 0}, {DEG_SOFT_SCENERY}"),
    ("r5: the buckets stride two nibbles wide", "write", FR,
     "        hex.mul_const w/4, trb_blk, trb_blk, buckets", "        hex.mul_const 2, trb_blk, trb_blk, buckets"),
    ("r5: the nld stride two nibbles wide", "write", FR,
     "rep(spn, k) hex.mul_const w/4, trb_blk, trb_blk, nld", "rep(spn, k) hex.mul_const 2, trb_blk, trb_blk, nld"),
    ("r5: the texture column one nibble wide", "write", FR,
     "hex.mov 2, trb_u, trb_frac_u + 4*dw", "hex.mov 1, trb_u, trb_frac_u + 4*dw"),
    ("r5: the last texture column one nibble wide", "write", FR,
     "hex.mov 2, trb_dw_max, sp_dw", "hex.mov 1, trb_dw_max, sp_dw"),
    ("r5: the texture column clamp one nibble wide", "write", FR,
     "hex.cmp 2, trb_u, trb_dw_max, col_check, col_check, u_clamp", "hex.cmp 1, trb_u, trb_dw_max, col_check, col_check, u_clamp"),
    ("r5: blk_addr places three nibbles", "write", FR,
     "hex.mov 4, gps_boff + 3*dw, blk", "hex.mov 3, gps_boff + 3*dw, blk"),
    # the read side
    ("the load's skip to B", "read", FR, "hex.ptr_add spslot_p, 5", "hex.ptr_add spslot_p, 4"),
    ("the load: an increment dropped", "read", FR,
     "frame.read0_byte_and_inc sblk + 2*dw, spslot_p", "frame.read_byte5 sblk + 2*dw, spslot_p"),
    ("the load: a step inserted", "read", FR,
     "frame.read0_byte_and_inc sblkb, spslot_p", "hex.ptr_inc spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p"),
    ("the load: a narrow-arm read", "read", FR, "frame.read0_byte_and_inc s, spslot_p", "frame.read3_and_inc s, spslot_p"),
    ("the load's field order", "read", FR,
     "frame.read0_byte_and_inc sblkb, spslot_p" + _W + "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p",
     "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p"),
    ("the seed's column stride", "read", FR, "hex.shl_hex w/4, 1, sidx ", "hex.shl_hex w/4, 2, sidx "),
    ("the seed's index bound", "read", FR, "frame.ptr_index5 p2_sspp, bteam, sidx", "frame.ptr_index4 p2_sspp, bteam, sidx"),
    ("the seed's column one nibble wide", "read", FR,
     "hex.mov 2, sidx, x1" + _W + "hex.shl_hex w/4, 1, sidx ", "hex.mov 1, sidx, x1" + _W + "hex.shl_hex w/4, 1, sidx "),
    ("the step's column stride", "read", FR, "hex.ptr_add p2_sspp, 16", "hex.ptr_add p2_sspp, 8"),
    ("the derive's bias", "read", SR, "hex.sub_constant 4, gps_y0, 32768", "hex.sub_constant 4, gps_y0, 16384"),
    ("the derive: an increment dropped", "read", SR, "hex.read_byte_and_inc gps_y0 + 2*dw, ptr", "hex.read_byte gps_y0 + 2*dw, ptr"),
    ("the derive: a step inserted", "read", SR, "hex.read_byte gps_lr, ptr", "hex.ptr_inc ptr" + _W + "hex.read_byte gps_lr, ptr"),
    ("the derive's field order", "read", SR,
     "hex.read_byte_and_inc gps_y0, ptr" + _W + "hex.read_byte_and_inc gps_y0 + 2*dw, ptr",
     "hex.read_byte_and_inc gps_y0 + 2*dw, ptr" + _W + "hex.read_byte_and_inc gps_y0, ptr"),
    ("the derive's slot id one nibble wide", "read", SR, "hex.mov 2, gps_sidx, s", "hex.mov 1, gps_sidx, s"),
]
# edits that move NO byte -- unreachable filler, each a layout freeze -- must still PASS: the harness
# anchors its hot block, so its verdict does not depend on where the code lands (review round 4)
NEUTRAL = [
    ("the record's layout freeze deleted", "write", FR, "        rep(703, i) stl.fj 0, 0\n", ""),
    ("the load's layout freeze deleted", "read", FR, "        rep(980, i) stl.fj 0, 0\n", ""),
]


def _mutate(name, old, new):
    text = source(name)
    assert text.count(old) == 1, "the edit's site is not in %s exactly once: %r" % (name, old)
    return {name: text.replace(old, new)}


@pytest.mark.parametrize("label, side, name, old, new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_a_mutated_layout_fails(tmp_path, label, side, name, old, new):
    """R9: each mutant edits the real text once -- and the side it moves must no longer hold"""
    got, want = run_side(tmp_path, side, _mutate(name, old, new), timeout=120)
    assert got != want, "%s: the layout still holds -- the test has no teeth here" % label


@pytest.mark.parametrize("label, side, name, old, new", NEUTRAL, ids=[m[0] for m in NEUTRAL])
def test_an_edit_that_moves_no_byte_still_passes(tmp_path, label, side, name, old, new):
    got, want = run_side(tmp_path, side, _mutate(name, old, new))
    assert got == want, "%s: the harness failed an edit that moves no byte" % label
