"""M7 P1.4 -- the v2 sprite column's invariants that hold without the renderer (docs/gp-sprite-column.md).

The column itself -- record -> load -> emit against the oracle, one fragment and two -- is checked
in fj by scratchpad/gp/probes/sprite/ship_check.py, with four mutants; the narrow reads themselves
run in tests/fj/test_narrow_reads_fj.py. What is pinned here:

  * the bank's 3-nibble reads (frame.read3_and_inc) are exact only on a bank that starts on a whole
    block, 64 ops = 16^3 bits. The emitter opens the bank with a `pad` of the block stride, and
    this assembles that construction and reads the label back; the build refuses a table where
    the label is off a block (build.sprbank_misalignment). Each has its control (R9): the same
    program without the pad lands off a block, and the build check rejects an off-block label.
  * a fragment names its thing by a ONE-BYTE slot id, so the emitter refuses a map with more
    drawable things than ids (wall_renderer.check_slot_ids) -- with the boundary on both sides.
  * a slot is SPR_THING_SLOT_BYTES bytes, and both fj sides scale a slot id by shifting -- the
    record's write and the derive's read -- so the shift count is held to the constant (R6).
  * the two slot layouts -- a fragment's bytes and fragment B's offset in `spslot`, a thing's
    bytes and the y0 bias in `gpslot` -- are literals in three fj macros. Each field's BYTE OFFSET
    is worked out from the fj ops (every read, write and pointer step through the layout's
    pointer) and held to wall_renderer's one statement of the layout (R6); a mutant of each kind
    -- a moved offset, a swapped field, a dropped increment, an inserted step -- must be told
    apart (R9).
  * the per-thing slot table is declared in the hot-data block at its full size, and the two
    FRAME-STATE registers the emit's slot cache depends on are among the hoisted globals the
    restore sets must carry (tests/host/test_restore_set_shipped.py holds them to that).
"""
import re
from pathlib import Path

import pytest

from doomfj import selfreset
from doomfj.build import sprbank_misalignment
from doomfj.config import Config
from doomfj.harness import W
from doomfj.wall_renderer import (SPR_BLOCK_STRIDE, SPR_FRAG_FIELDS, SPR_SLOT_B_BYTE,
                                  SPR_SLOT_STRIDE, SPR_THING_SLOT_BYTES, SPR_THING_SLOT_FIELDS,
                                  SPR_THING_SLOTS, SPR_THING_Y0_BIAS, check_slot_ids,
                                  hoisted_scratch_decls, sprite_bank_header)

BLOCK_BITS = SPR_BLOCK_STRIDE * 2 * W
FJ = Path(__file__).resolve().parents[2] / "src" / "fj"


def test_a_bank_block_is_three_whole_nibbles_of_address():
    """frame.blk_addr places a block index at nibble 3, and frame.arm3 re-arms nibbles 0-2 only"""
    assert SPR_BLOCK_STRIDE == 64
    assert BLOCK_BITS == 16 ** 3


def _label_after(tmp_path, n_ops, header):
    """assemble `n_ops` ops, then `header`, then one op; return the bank label's bit address"""
    src = tmp_path / "p.fj"
    src.write_text("\n".join(["stl.startup", ";skip", "rep(%d, i) stl.fj 0, 0" % n_ops,
                              *header, ";0 * dw", "skip:", "stl.loop"]) + "\n", encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    labels = selfreset.capture_labels([consts, src], tmp_path / "p.fjm")
    return int(labels["sprbank"])


@pytest.mark.parametrize("n_ops", [0, 1, 37, 63, 64, 1000])
def test_the_bank_header_puts_sprbank_on_a_block(tmp_path, n_ops):
    at = _label_after(tmp_path, n_ops, sprite_bank_header())
    assert at % BLOCK_BITS == 0, (n_ops, at)
    assert sprbank_misalignment({"sprbank": at}) is None


def test_without_the_pad_it_lands_off_a_block(tmp_path):
    """R9: the same program with the header's `pad` dropped is off a block -- so the passing test
    above is the pad's doing, and the build check says so"""
    header = [line for line in sprite_bank_header() if not line.startswith("pad ")]
    assert len(header) == len(sprite_bank_header()) - 1, "the header no longer carries a pad"
    at = _label_after(tmp_path, 37, header)
    assert at % BLOCK_BITS != 0
    assert sprbank_misalignment({"sprbank": at}) is not None


def test_the_build_check_reads_the_label_it_is_given():
    assert sprbank_misalignment({"sprbank": 7 * BLOCK_BITS}) is None
    assert "past a %d-bit block" % BLOCK_BITS in sprbank_misalignment({"sprbank": 7 * BLOCK_BITS + 64})
    assert sprbank_misalignment({"sprbank": 7 * BLOCK_BITS + BLOCK_BITS // 2}) is not None
    assert sprbank_misalignment({"pclm": 64}) is None, "no bank (the render tier): nothing to check"


def test_the_slot_id_is_one_byte_and_the_emitter_holds_the_map_to_it():
    assert SPR_THING_SLOTS == 256 and SPR_THING_SLOT_BYTES == 4
    check_slot_ids(255)                                  # ids 1..255: exactly fits
    with pytest.raises(AssertionError, match="one-byte slot id"):
        check_slot_ids(256)                              # R9: one more thing is refused


def test_the_slot_cache_state_is_hoisted_for_the_restore_sets():
    """gps_nslot (the next slot id) and gps_cur_s (whose constants the derive holds) must be 0 at
    every frame start. A stale gps_cur_s crashes nothing -- the next frame's slot 1 skips its fetch
    and draws the previous frame's thing-1 top row and light -- so they ride the reset, which
    test_restore_set_shipped.py requires of every hoisted global."""
    decls = dict(d.split(":", 1) for d in hoisted_scratch_decls())
    assert decls["gps_nslot"].strip() == "hex.vec 2"
    assert decls["gps_cur_s"].strip() == "hex.vec 2"
    retired = {"p2_ssy1", "p2_sy0b", "p2_slr", "p2_dssy1", "p2_dsy0b", "trb_run_r0", "trb_y_base",
               "trb_y0_biased", "srn_ptr", "srw_ptr"}
    assert not retired & set(decls), "a retired fragment register is still hoisted"


def test_the_slot_stride_is_the_shift_both_fj_sides_scale_by():
    """R6: `gpslot` holds SPR_THING_SLOT_BYTES bytes per thing (wall_renderer declares it so), and
    the record's write (frame_render.fj) and the derive's read (stream_render.fj) each turn a slot
    id into its byte offset with `hex.shl_bit w/4, gps_sidx` lines. Nothing else ties those shifts
    to the constant: each file must shift exactly log2(SPR_THING_SLOT_BYTES) times."""
    shifts = SPR_THING_SLOT_BYTES.bit_length() - 1
    assert 1 << shifts == SPR_THING_SLOT_BYTES, "a slot must be a power of two bytes"
    root = Path(__file__).resolve().parents[2] / "src" / "fj"
    for f in ("frame_render.fj", "stream_render.fj"):
        text = (root / f).read_text(encoding="utf-8")
        n = len(re.findall(r"^\s*hex\.shl_bit w/4, gps_sidx\b", text, re.M))
        assert n == shifts, "%s shifts gps_sidx %d times, the slot is %d bytes" % (
            f, n, SPR_THING_SLOT_BYTES)


# ---- the two slot layouts (R6): every field's byte, WORKED OUT from the fj ops ------------------------
#
# PR #93's review, round 2: comparing the ORDER of the reads and writes let a dropped `_and_inc`, an
# inserted pointer step, or a slot offset never added move a field with no key changing. So the bytes
# are computed: each macro's ops are walked in order, holding the registers that build an address as
# VALUES (linear in their sources: `spslot + 16 * trb_col_x + trb_slot_ofs`), and following the
# layout's pointer from every op that sets it -- each byte read or written through it lands at the
# address its op produced plus the steps since. Both sides' column strides are part of the address.

# what each fj register holds, per layout side (a two-byte value `v` is `v` low, `v + 2*dw` high)
FRAG_RECORD = {"gps_s_rec": "slot id", "trb_blk": "block lo", "trb_blk + 2*dw": "block hi"}
SLOT_RECORD = {"gps_yb8": "y0 lo", "gps_yb8 + 2*dw": "y0 hi", "trb_shade_row": "light row"}
FRAG_LOAD = {"s": ("A", "slot id"), "sblk": ("A", "block lo"), "sblk + 2*dw": ("A", "block hi"),
             "sb": ("B", "slot id"), "sblkb": ("B", "block lo"), "sblkb + 2*dw": ("B", "block hi")}
SLOT_DERIVE = {"gps_y0": "y0 lo", "gps_y0 + 2*dw": "y0 hi", "gps_lr": "light row"}

# thing_record_body's `slotstride` parameter: the emitter passes SPR_SLOT_STRIDE (its call to
# `frame.thing_record`); a `rep(...)` count is evaluated with it
PARAMS = {"slotstride": SPR_SLOT_STRIDE}
HIGH_ZERO = "high nibbles zeroed"       # `hex.zero w/4 - 2, r + 2*dw`, before a 2-nibble mov into r


def macro(text, name):
    """a namespace macro's text, from its `def` to its closing brace"""
    m = re.search(r"^    def %s\b.*?^    \}\s*$" % name, text, re.M | re.S)
    assert m, "no macro %s" % name
    return m.group(0)


def rep_count(expr):
    """a `rep` count: an integer, a PARAMS name, or one of them times / over another -- else None"""
    m = re.fullmatch(r"\s*(\w+)\s*(?:([*/])\s*(\w+))?\s*", expr)
    if not m:
        return None
    term = lambda t: None if t is None else int(t) if t.isdigit() else PARAMS.get(t)
    a, op, b = term(m.group(1)), m.group(2), term(m.group(3))
    if a is None or op and b is None:
        return None
    if not op:
        return a
    return a * b if op == "*" else a // b if b and a % b == 0 else None


def body_ops(body):
    """(times, op name, [operands]) after the macro's header, comments and a leading label stripped;
    a `rep(n, i) op` is its op with times = n (None when n is not evaluable)"""
    after = body[body.index("{") + 1:]
    for line in after.splitlines():
        code = re.sub(r"^\s*[\w.]+:\s*", "", line.split("//")[0]).strip()
        if not code or code.startswith(";"):
            continue
        times = 1
        m = re.fullmatch(r"rep\(([^,]+),\s*\w+\)\s*(.*)", code)
        if m:
            times, code = rep_count(m.group(1)), m.group(2)
        name, _, args = code.partition(" ")
        yield times, name, [" ".join(a.split()) for a in args.split(",")] if args.strip() else []


def _plus(a, b):
    if a is None or b is None or HIGH_ZERO in (a, b):
        return None
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return {k: v for k, v in out.items() if v}


def _times(a, n):
    return None if a is None or a == HIGH_ZERO else {k: v * n for k, v in a.items() if v * n}


def run(body, ptr, track=()):
    """Walk the macro's ops in order, holding `ptr` and each register in `track` as a VALUE --
    {symbol: coefficient}, '1' the constant, a register on entry itself -- and return (stretches,
    values at the end): each stretch of `ptr` from an op that sets it is (its address, [(byte
    offset from there, register)] for every byte read or written through it). An op this walk does
    not model leaves whatever it may write UNKNOWN (None) -- never silently right."""
    regs = set(track) | {ptr}
    env = {r: {r: 1} for r in regs}
    segs = []

    def val(x):
        if x in env:
            return None if env[x] == HIGH_ZERO else env[x]
        return ({"1": int(x)} if int(x) else {}) if x.isdigit() else {x: 1}

    def empty(r):
        return env[r] in ({}, HIGH_ZERO)

    def offset():
        base = segs[-1][0] if segs else None
        d = _plus(env[ptr], _times(base, -1)) if base is not None else None
        return None if d is None or set(d) - {"1"} else d.get("1", 0)

    for times, name, argv in body_ops(body):
        hit = {r for r in regs if r in argv or r + " + 2*dw" in argv}
        if not hit:
            continue
        if times is None:
            for r in hit:
                env[r] = None
            continue
        for _ in range(times):
            if "write" in name and argv[0] == ptr or "read" in name and argv[-1] == ptr:
                if not segs:
                    segs.append((env[ptr], []))
                segs[-1][1].append((offset(), argv[1] if "write" in name else argv[0]))
                if "_and_inc" in name:
                    env[ptr] = _plus(env[ptr], {"1": 1})
                continue
            w = argv[0] if argv else None
            dst = argv[1] if len(argv) > 1 else None
            if name.startswith("frame.ptr_index") and w in regs:
                env[w] = _plus(val(argv[1]), val(argv[2]))
            elif name == "frame.blk_addr" and w in regs:
                env[w] = None
            elif name in ("hex.ptr_add", "hex.ptr_sub") and w in regs and argv[1].isdigit():
                env[w] = _plus(env[w], {"1": int(argv[1]) * (1 if name.endswith("add") else -1)})
            elif name in ("hex.ptr_inc", "hex.ptr_dec") and w in regs:
                env[w] = _plus(env[w], {"1": 1 if name.endswith("inc") else -1})
            elif name == "hex.zero" and dst in regs:
                env[dst] = {} if w == "w/4" else None
            elif name == "hex.zero" and dst and dst.endswith(" + 2*dw") and dst[:-7] in regs:
                env[dst[:-7]] = HIGH_ZERO if w == "w/4 - 2" else None
            elif name in ("hex.set", "hex.mov") and dst in regs:
                env[dst] = val(argv[2]) if w == "w/4" or empty(dst) else None
            elif name == "hex.add" and dst in regs:
                env[dst] = _plus(env[dst], val(argv[2]))
            elif name == "hex.inc" and dst in regs:
                env[dst] = _plus(env[dst], {"1": 1})
            elif name == "hex.shl_bit" and dst in regs:
                env[dst] = _times(env[dst], 2)
            elif name == "hex.shl_hex" and len(argv) == 3 and argv[2] in regs and argv[1].isdigit():
                env[argv[2]] = _times(env[argv[2]], 16 ** int(argv[1]))
            else:                              # any other op that may write one of them
                for r in regs & set(argv[:2] + [a[:-7] for a in argv[:2] if a.endswith(" + 2*dw")]):
                    env[r] = None
                continue
            if w == ptr and (name.startswith("frame.ptr_index") or name == "frame.blk_addr") or \
                    dst == ptr and name in ("hex.set", "hex.mov"):
                segs.append((env[ptr], []))    # the pointer is SET: a new stretch from here
    return segs, env


def value(v):
    """a value as a comparable, printable tuple of (symbol, coefficient); unknown stays None"""
    return None if v is None or v == HIGH_ZERO else tuple(sorted(v.items()))


def by_offset(pairs):
    """(offset, field) pairs in byte order -- an unknown offset (None) last"""
    return tuple(sorted(pairs, key=lambda of: (of[0] is None, of[0] or 0, repr(of[1]))))


def stretch(body, ptr, fields, track=()):
    """the ONE stretch of `ptr` whose bytes are this layout's: (its address, its (offset, field)
    pairs; a register of no field shows as '?name'). Two stretches, or none, is itself a layout."""
    hits = [(a, acc) for a, acc in run(body, ptr, track)[0] if any(r in fields for _, r in acc)]
    if len(hits) != 1:
        return ("stretches", len(hits)), ("stretches", tuple(tuple(acc) for _, acc in hits))
    a, acc = hits[0]
    return value(a), by_offset((o, fields.get(r, "?" + r)) for o, r in acc)


def one_setting(body, ptr, track=()):
    """the address the macro's ONE setting of `ptr` gives it (none or two is itself a value)"""
    segs = run(body, ptr, track)[0]
    return value(segs[0][0]) if len(segs) == 1 else ("settings", len(segs))


def net_step(body, reg):
    """how far the macro moves `reg`, when that is a constant"""
    d = _plus(run(body, reg)[1][reg], {reg: -1})
    return None if d is None or set(d) - {"1"} else d.get("1", 0)


def one(pattern, body):
    found = re.findall(pattern, body, re.M)
    assert len(found) == 1, "%r: %d matches" % (pattern, len(found))
    return int(found[0])


def fj_layouts(frame_text, stream_text):
    """what the fj text says, key by key"""
    rec = macro(frame_text, "thing_record_body")
    load = macro(frame_text, "lines_spr_load")
    seed = macro(frame_text, "lines_spr_seed")
    step = macro(frame_text, "lines_spr_step")
    derive = macro(stream_text, "frag_derive")
    frag_at, frag = stretch(rec, "trb_tbl_p", FRAG_RECORD, ("trb_tab_idx", "trb_tbl_b"))
    load_at, loaded = stretch(load, "spslot_p", FRAG_LOAD)
    slot_at, slot = stretch(rec, "gps_ptr", SLOT_RECORD, ("gps_sidx", "gps_sbase"))
    dslot_at, dslot = stretch(derive, "ptr", SLOT_DERIVE, ("gps_sidx", "gps_sbase"))
    return {
        "the record's fragment address": frag_at,
        "the record's fragment": frag,
        "fragment A's byte": one(r"^\s*slot_a:\s*\n\s*hex\.set w/4, trb_slot_ofs, (\d+)", rec),
        "fragment B's byte": one(r"^\s*slot_b:\s*\n\s*hex\.set w/4, trb_slot_ofs, (\d+)", rec),
        "the load's column": one_setting(seed, "p2_sspp", ("sidx", "bteam")),
        "the load's column step": net_step(step, "p2_sspp"),
        "the load's address": load_at,
        "the load's fragments": loaded,
        "the record's slot address": slot_at,
        "the record's slot": slot,
        "the record's bias": one(r"^\s*hex\.add_constant \d+, gps_yb8, (\d+)", rec),
        "the derive's slot address": dslot_at,
        "the derive's slot": dslot,
        "the derive's bias": one(r"^\s*hex\.sub_constant \d+, gps_y0, (\d+)", derive),
    }


def at(first, fields, tag=None):
    """a layout's (offset, field) pairs from its first byte, in byte order"""
    return by_offset((first + i, f if tag is None else (tag, f)) for i, f in enumerate(fields))


def stated_layouts():
    """the same keys, from wall_renderer's one statement of each layout"""
    return {
        # a column's slot is SPR_SLOT_STRIDE bytes of `spslot`; fragment A at byte 0, B at SPR_SLOT_B_BYTE
        "the record's fragment address": value({"spslot": 1, "trb_col_x": SPR_SLOT_STRIDE, "trb_slot_ofs": 1}),
        "the record's fragment": at(0, SPR_FRAG_FIELDS),
        "fragment A's byte": 0,
        "fragment B's byte": SPR_SLOT_B_BYTE,
        "the load's column": value({"spslot": 1, "x1": SPR_SLOT_STRIDE}),
        "the load's column step": SPR_SLOT_STRIDE,
        "the load's address": value({"p2_sspp": 1}),
        "the load's fragments": by_offset(at(0, SPR_FRAG_FIELDS, "A") + at(SPR_SLOT_B_BYTE, SPR_FRAG_FIELDS, "B")),
        # a thing's slot is SPR_THING_SLOT_BYTES bytes of `gpslot`, found by its slot id
        "the record's slot address": value({"gpslot": 1, "gps_s_rec": SPR_THING_SLOT_BYTES}),
        "the record's slot": at(0, SPR_THING_SLOT_FIELDS),
        "the record's bias": SPR_THING_Y0_BIAS,
        "the derive's slot address": value({"gpslot": 1, "s": SPR_THING_SLOT_BYTES}),
        "the derive's slot": at(0, SPR_THING_SLOT_FIELDS),
        "the derive's bias": SPR_THING_Y0_BIAS,
    }


def fj_texts():
    return ((FJ / "frame_render.fj").read_text(encoding="utf-8"),
            (FJ / "stream_render.fj").read_text(encoding="utf-8"))


def test_the_slot_layouts_are_the_constants_on_every_fj_side():
    """R6: every field of the two layouts, on both sides, sits at the byte wall_renderer says"""
    got = fj_layouts(*fj_texts())
    assert got == stated_layouts()
    # the walk is not vacuous: B's fragment is found at byte 8 by COUNTING A's three reads and the
    # skip, and the record's column by evaluating its `rep(slotstride/16, k)` shift
    assert (SPR_SLOT_B_BYTE, ("B", "slot id")) in got["the load's fragments"]
    assert ("trb_col_x", SPR_SLOT_STRIDE) in got["the record's fragment address"]


# one mutant per way a layout can move, each a single real edit of the real text (R9), with the keys
# it must break -- and only those. PR #93's review round 2 found the first comparison blind to a
# dropped increment, an inserted pointer step and a slot offset never added: each has its mutant,
# the first two on each side of each layout.
_W = "\n        "
LAYOUT_MUTANTS = [
    # the literal offsets, strides and biases, one side at a time
    ("A's byte", 0, "hex.set w/4, trb_slot_ofs, 0", "hex.set w/4, trb_slot_ofs, 1", {"fragment A's byte"}),
    ("B's byte", 0, "hex.set w/4, trb_slot_ofs, 8", "hex.set w/4, trb_slot_ofs, 9", {"fragment B's byte"}),
    ("the load's skip", 0, "hex.ptr_add spslot_p, 5", "hex.ptr_add spslot_p, 4", {"the load's fragments"}),
    ("the record's bias", 0, "hex.add_constant 8, gps_yb8, 32768", "hex.add_constant 8, gps_yb8, 32767",
     {"the record's bias"}),
    ("the derive's bias", 1, "hex.sub_constant 4, gps_y0, 32768", "hex.sub_constant 4, gps_y0, 16384",
     {"the derive's bias"}),
    ("the record's column stride", 0, "rep(slotstride/16, k) hex.shl_hex w/4, 1, trb_tab_idx",
     "rep(slotstride/8, k) hex.shl_hex w/4, 1, trb_tab_idx", {"the record's fragment address"}),
    ("the load's column stride", 0, "hex.shl_hex w/4, 1, sidx ", "hex.shl_hex w/4, 2, sidx ",
     {"the load's column"}),
    ("the load's column step", 0, "hex.ptr_add p2_sspp, 16", "hex.ptr_add p2_sspp, 8", {"the load's column step"}),
    ("the load's pointer", 0, "hex.mov w/4, spslot_p, p2_sspp", "hex.mov w/4, spslot_p, p2_spfp",
     {"the load's address"}),
    ("the record's slot stride", 0, "hex.shl_bit w/4, gps_sidx" + _W + "hex.shl_bit w/4, gps_sidx",
     "hex.shl_bit w/4, gps_sidx", {"the record's slot address"}),
    ("the derive's slot stride", 1, "hex.shl_bit w/4, gps_sidx" + _W + "hex.shl_bit w/4, gps_sidx",
     "hex.shl_bit w/4, gps_sidx", {"the derive's slot address"}),
    # the review's third kind: B's offset never added -- B written over A at byte 0
    ("the slot offset never added", 0, "hex.add w/4, trb_tab_idx, trb_slot_ofs", "hex.zero w/4, trb_slot_ofs",
     {"the record's fragment address"}),
    # a field order swapped, on each side of each layout
    ("the record's fragment swapped", 0,
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw",
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk + 2*dw" + _W + "frame.write_byte5 trb_tbl_p, trb_blk",
     {"the record's fragment"}),
    ("the load's A swapped", 0,
     "frame.read0_byte_and_inc sblk, spslot_p" + _W + "frame.read0_byte_and_inc sblk + 2*dw, spslot_p",
     "frame.read0_byte_and_inc sblk + 2*dw, spslot_p" + _W + "frame.read0_byte_and_inc sblk, spslot_p",
     {"the load's fragments"}),
    ("the load's B swapped", 0,
     "frame.read0_byte_and_inc sblkb, spslot_p" + _W + "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p",
     "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p",
     {"the load's fragments"}),
    ("the record's slot swapped", 0,
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw" + _W + "hex.write_byte gps_ptr, trb_shade_row",
     "hex.write_byte_and_inc gps_ptr, trb_shade_row" + _W + "hex.write_byte gps_ptr, gps_yb8 + 2*dw",
     {"the record's slot"}),
    ("the derive's slot swapped", 1,
     "hex.read_byte_and_inc gps_y0, ptr" + _W + "hex.read_byte_and_inc gps_y0 + 2*dw, ptr",
     "hex.read_byte_and_inc gps_y0 + 2*dw, ptr" + _W + "hex.read_byte_and_inc gps_y0, ptr",
     {"the derive's slot"}),
    # a DROPPED increment, on each side of each layout (the review's four)
    ("the record's fragment: an increment dropped", 0,
     "hex.write_byte_and_inc trb_tbl_p, gps_s_rec", "hex.write_byte trb_tbl_p, gps_s_rec",
     {"the record's fragment"}),
    ("the load: an increment dropped", 0,
     "frame.read0_byte_and_inc sblk + 2*dw, spslot_p", "frame.read0_byte sblk + 2*dw, spslot_p",
     {"the load's fragments"}),
    ("the record's slot: an increment dropped", 0,
     "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw", "hex.write_byte gps_ptr, gps_yb8 + 2*dw",
     {"the record's slot"}),
    ("the derive: an increment dropped", 1,
     "hex.read_byte_and_inc gps_y0 + 2*dw, ptr", "hex.read_byte gps_y0 + 2*dw, ptr",
     {"the derive's slot"}),
    # an INSERTED pointer step, on each side of each layout (the review's three, and the record's slot)
    ("the record's fragment: a step inserted", 0,
     "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw", "hex.ptr_inc trb_tbl_p" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw",
     {"the record's fragment"}),
    ("the load: a step inserted", 0,
     "frame.read0_byte_and_inc sblkb, spslot_p", "hex.ptr_inc spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p",
     {"the load's fragments"}),
    ("the record's slot: a step inserted", 0,
     "hex.write_byte gps_ptr, trb_shade_row", "hex.ptr_inc gps_ptr" + _W + "hex.write_byte gps_ptr, trb_shade_row",
     {"the record's slot"}),
    ("the derive: a step inserted", 1,
     "hex.read_byte gps_lr, ptr", "hex.ptr_inc ptr" + _W + "hex.read_byte gps_lr, ptr",
     {"the derive's slot"}),
]


def test_every_layout_key_has_a_mutant_and_every_side_both_pointer_mutants():
    assert set().union(*(m[4] for m in LAYOUT_MUTANTS)) == set(stated_layouts())
    for side in ("the record's fragment", "the load", "the record's slot", "the derive"):
        for kind in ("an increment dropped", "a step inserted"):
            assert "%s: %s" % (side, kind) in {m[0] for m in LAYOUT_MUTANTS}, (side, kind)


@pytest.mark.parametrize("label, side, old, new, keys", LAYOUT_MUTANTS, ids=[m[0] for m in LAYOUT_MUTANTS])
def test_a_mutated_layout_is_told_apart(label, side, old, new, keys):
    """R9: each mutant edits the real fj text once, and the comparison must name exactly the keys
    it moves"""
    texts = list(fj_texts())
    assert texts[side].count(old) == 1, "the mutant's site is not in the fj text: %r" % old
    texts[side] = texts[side].replace(old, new)
    got, want = fj_layouts(*texts), stated_layouts()
    assert {k for k in want if got[k] != want[k]} == keys


def test_the_walk_leaves_what_it_does_not_model_unknown():
    """the walk never guesses: an op of a kind it does not model makes what it may write unknown,
    so a byte behind it cannot compare equal -- the pointer's offsets, and a register's value"""
    body = ("    def m p {\n        frame.ptr_index p, b, i\n        hex.write_byte_and_inc p, x\n"
            "        hex.add_constant 3, p, dw\n        hex.write_byte p, y\n"
            "        hex.set w/4, r, 16\n        hex.xor w/4, r, q\n    }\n")
    segs, env = run(body, "p", ("r",))
    assert segs == [({"b": 1, "i": 1}, [(0, "x"), (None, "y")])]
    assert env["r"] is None
    assert rep_count("slotstride/16") == 1 and rep_count("things*spremit") is None
