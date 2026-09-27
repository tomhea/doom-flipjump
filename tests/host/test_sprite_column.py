"""M7 P1.4 -- the v2 sprite column's invariants that hold without the renderer (docs/gp-sprite-column.md).

The column itself is checked in fj by tests/fj/test_sprite_bank_fj.py since M7 P1.6: the derive and
both run walkers over native lists (the window walker above and below a near fragment), and the
record's tier / slot / min_b section transplanted from the shipped source, each with mutants. P1.4's
record -> load -> emit check, scratchpad/gp/probes/sprite/ship_check.py, is SUPERSEDED (it builds
P1.4's blocks and no longer assembles); the load and the whole A+B composition are left to the
byte-exact gates. What is pinned here:

  * the bank's 3-nibble reads (frame.read3_and_inc) are exact only on a bank that starts on a whole
    block, 64 ops = 16^3 bits. The emitter opens the bank with a `pad` of the block stride, and
    this assembles that construction and reads the label back; the build refuses a table where
    the label is off a block (build.sprbank_misalignment). Each has its control (R9): the same
    program without the pad lands off a block, and the build check rejects an off-block label.
  * a fragment names its thing by a ONE-BYTE slot id, so the emitter refuses a map with more
    drawable things than ids (wall_renderer.check_slot_ids) -- with the boundary on both sides.
  * the per-thing slot table is declared in the hot-data block at its full size, and the two
    FRAME-STATE registers the emit's slot cache depends on are among the hoisted globals the
    restore sets must carry (tests/host/test_restore_set_shipped.py holds them to that).
"""
import pytest

from doomfj import selfreset
from doomfj.build import sprbank_misalignment
from doomfj.config import Config
from doomfj.harness import W
from doomfj.wall_renderer import (SPR_BLOCK_STRIDE, SPR_THING_SLOT_BYTES, SPR_THING_SLOTS,
                                  check_slot_ids, hoisted_scratch_decls, sprite_bank_header)

BLOCK_BITS = SPR_BLOCK_STRIDE * 2 * W


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
