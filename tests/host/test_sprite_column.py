"""M7 P1.4 -- the v2 sprite column's invariants that hold without the renderer (docs/gp-sprite-column.md).

The column itself is checked in fj by tests/fj/test_sprite_bank_fj.py since M7 P1.6: the derive and
both run walkers over native lists (the window walker above and below a near fragment), and the
record's tier / slot / min_b section transplanted from the shipped source, each with mutants; the
narrow reads themselves run in tests/fj/test_narrow_reads_fj.py. P1.4's record -> load -> emit
check, scratchpad/gp/probes/sprite/ship_check.py, is SUPERSEDED (it builds P1.4's blocks and no
longer assembles); the load and the whole A+B composition are left to the byte-exact gates. What is
pinned here:

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
    bytes and the y0 bias in `gpslot` -- are literals in three fj macros. This file PINS them in
    the fj TEXT: each offset, the skip to B, both biases and each side's field order are held to
    wall_renderer's one statement of them (R6), with a mutant of each (R9). It is a text pin, not a
    model of the fj: whether every field lands on the byte the constants name is RUN, on both
    sides, by tests/fj/test_slot_layouts_fj.py -- PR #93's review found that an order-only text
    check cannot see a dropped increment, an inserted step, a width, an arm or a branch.
  * the two FRAME-STATE registers the emit's slot cache depends on are among the hoisted globals
    the restore sets must carry (tests/host/test_restore_set_shipped.py holds them to that).
"""
import re
from pathlib import Path

import pytest

from doomfj import selfreset
from doomfj.build import sprbank_misalignment
from doomfj.config import Config
from doomfj.harness import W
from doomfj.wall_renderer import (SPR_BLOCK_STRIDE, SPR_FRAG_BYTES, SPR_FRAG_FIELDS,
                                  SPR_SLOT_B_BYTE, SPR_THING_SLOT_BYTES, SPR_THING_SLOT_FIELDS,
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


# ---- the two slot layouts (R6): the fj literals, read off the three macros that hold them --------
# A TEXT pin: it sees the literals and the order of the ops, never where a byte lands -- that is
# tests/fj/test_slot_layouts_fj.py's, which runs the fj on both sides.

# what each fj register holds: the record's names and the reads' names for the same bytes (a
# two-byte value `v` is `v` low, `v + 2*dw` high)
REG_FIELD = {
    # frame.thing_record_body -- the writes
    "gps_s_rec": "slot id", "trb_blk": "block lo", "trb_blk + 2*dw": "block hi",
    "gps_yb8": "y0 lo", "gps_yb8 + 2*dw": "y0 hi", "trb_shade_row": "light row",
    "trb_bucket": "bucket",                                          # M7 P1.6: the rowmap's row
    # frame.lines_spr_load -- fragment A, then fragment B
    "s": "slot id", "sblk": "block lo", "sblk + 2*dw": "block hi",
    "sb": "slot id", "sblkb": "block lo", "sblkb + 2*dw": "block hi",
    # stream.frag_derive
    "gps_y0": "y0 lo", "gps_y0 + 2*dw": "y0 hi", "gps_lr": "light row", "gps_b": "bucket",
}


def macro(text, name):
    """a namespace macro's text, from its `def` to its closing brace"""
    m = re.search(r"^    def %s\b.*?^    \}\s*$" % name, text, re.M | re.S)
    assert m, "no macro %s" % name
    return m.group(0)


def fields(ops):
    return tuple(REG_FIELD.get(" ".join(op.split()), "?" + op) for op in ops)


def written(body, ptr):
    return fields(re.findall(r"^\s*(?:hex|frame)\.write_byte\w*\s+%s,\s*([^/\n]+?)\s*(?://.*)?$"
                             % ptr, body, re.M))


def read(body, ptr):
    return fields(re.findall(r"^\s*(?:hex|frame)\.read0?_byte\w*\s+([^,\n]+?),\s*%s\s*(?://.*)?$"
                             % ptr, body, re.M))


def one(pattern, body):
    found = re.findall(pattern, body, re.M)
    assert len(found) == 1, "%r: %d matches" % (pattern, len(found))
    return int(found[0])


def fj_layouts(frame_text, stream_text):
    """what the fj text says, key by key -- each key one literal site"""
    rec = macro(frame_text, "thing_record_body")
    load = macro(frame_text, "lines_spr_load")
    derive = macro(stream_text, "frag_derive")
    load_a, load_b = re.split(r"^\s*hex\.ptr_add spslot_p, \d+.*$", load, maxsplit=1, flags=re.M)
    fetch = derive[derive.index("fetch:"):derive.index("have:")]
    return {
        "the record's fragment": written(rec, "trb_tbl_p"),
        "fragment A's byte": one(r"^\s*slot_a:\s*\n\s*hex\.set w/4, trb_slot_ofs, (\d+)", rec),
        "fragment B's byte": one(r"^\s*slot_b:\s*\n\s*hex\.set w/4, trb_slot_ofs, (\d+)", rec),
        "the load's fragment A": read(load_a, "spslot_p"),
        "the load's skip to B": one(r"^\s*hex\.ptr_add spslot_p, (\d+)", load),
        "the load's fragment B": read(load_b, "spslot_p"),
        "the record's slot": written(rec, "gps_ptr"),
        "the record's bias": one(r"^\s*hex\.add_constant \d+, gps_yb8, (\d+)", rec),
        "the derive's slot": read(fetch, "ptr"),
        "the derive's bias": one(r"^\s*hex\.sub_constant \d+, gps_y0, (\d+)", derive),
    }


def stated_layouts():
    """the same keys, from wall_renderer's one statement of each layout"""
    return {
        "the record's fragment": SPR_FRAG_FIELDS,
        "fragment A's byte": 0,
        "fragment B's byte": SPR_SLOT_B_BYTE,
        "the load's fragment A": SPR_FRAG_FIELDS,
        "the load's skip to B": SPR_SLOT_B_BYTE - SPR_FRAG_BYTES,
        "the load's fragment B": SPR_FRAG_FIELDS,
        "the record's slot": SPR_THING_SLOT_FIELDS,
        "the record's bias": SPR_THING_Y0_BIAS,
        "the derive's slot": SPR_THING_SLOT_FIELDS,
        "the derive's bias": SPR_THING_Y0_BIAS,
    }


def fj_texts():
    return ((FJ / "frame_render.fj").read_text(encoding="utf-8"),
            (FJ / "stream_render.fj").read_text(encoding="utf-8"))


def test_the_slot_layouts_are_the_constants_on_every_fj_side():
    """R6: every literal of the two layouts in the fj text, on both sides, is wall_renderer's"""
    assert fj_layouts(*fj_texts()) == stated_layouts()


# one mutant per kind of literal, each a real edit of the real text (R9): a wrong offset, a wrong
# skip, a wrong bias on each side, and a field order swapped on each side of each layout
_W = "\n        "
LAYOUT_MUTANTS = [
    (0, "hex.set w/4, trb_slot_ofs, 0", "hex.set w/4, trb_slot_ofs, 1", "fragment A's byte"),
    (0, "hex.set w/4, trb_slot_ofs, 8", "hex.set w/4, trb_slot_ofs, 9", "fragment B's byte"),
    (0, "hex.ptr_add spslot_p, 5", "hex.ptr_add spslot_p, 4", "the load's skip to B"),
    (0, "frame.write_byte_and_inc5 trb_tbl_p, trb_blk" + _W + "frame.write_byte5 trb_tbl_p, trb_blk + 2*dw",
     "frame.write_byte_and_inc5 trb_tbl_p, trb_blk + 2*dw" + _W + "frame.write_byte5 trb_tbl_p, trb_blk",
     "the record's fragment"),
    (0, "frame.read0_byte_and_inc sblk, spslot_p" + _W + "frame.read0_byte_and_inc sblk + 2*dw, spslot_p",
     "frame.read0_byte_and_inc sblk + 2*dw, spslot_p" + _W + "frame.read0_byte_and_inc sblk, spslot_p",
     "the load's fragment A"),
    (0, "frame.read0_byte_and_inc sblkb, spslot_p" + _W + "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p",
     "frame.read0_byte_and_inc sblkb + 2*dw, spslot_p" + _W + "frame.read0_byte_and_inc sblkb, spslot_p",
     "the load's fragment B"),
    (0, "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw" + _W + "hex.write_byte_and_inc gps_ptr, trb_shade_row",
     "hex.write_byte_and_inc gps_ptr, trb_shade_row" + _W + "hex.write_byte_and_inc gps_ptr, gps_yb8 + 2*dw",
     "the record's slot"),
    (0, "hex.add_constant 8, gps_yb8, 32768", "hex.add_constant 8, gps_yb8, 32767", "the record's bias"),
    (1, "hex.read_byte_and_inc gps_y0, ptr" + _W + "hex.read_byte_and_inc gps_y0 + 2*dw, ptr",
     "hex.read_byte_and_inc gps_y0 + 2*dw, ptr" + _W + "hex.read_byte_and_inc gps_y0, ptr",
     "the derive's slot"),
    (1, "hex.sub_constant 4, gps_y0, 32768", "hex.sub_constant 4, gps_y0, 16384", "the derive's bias"),
]


def test_every_layout_literal_has_a_mutant():
    assert sorted(m[3] for m in LAYOUT_MUTANTS) == sorted(stated_layouts())


@pytest.mark.parametrize("side, old, new, key", LAYOUT_MUTANTS, ids=[m[3] for m in LAYOUT_MUTANTS])
def test_a_mutated_layout_literal_is_told_apart(side, old, new, key):
    """R9: each mutant edits the real fj text once, and the comparison must name the key it broke
    -- and only that key"""
    texts = list(fj_texts())
    assert texts[side].count(old) == 1, "the mutant's site is not in the fj text: %r" % old
    texts[side] = texts[side].replace(old, new)
    got, want = fj_layouts(*texts), stated_layouts()
    assert [k for k in want if got[k] != want[k]] == [key]
