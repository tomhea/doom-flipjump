"""M7 P1.4 -- the sprite bank's NARROW reads, assembled and run.

`frame.blk_addr` places a block, the block's first byte is read on the FULL arm
(`hex.read_byte_and_inc`, as `stream.frag_derive` reads a block's header) and every later byte on the
3-nibble arm (`frame.read3_and_inc`). Two 64-op blocks of distinct bytes follow
`wall_renderer.sprite_bank_header()` -- the `pad` that puts `sprbank` on a 4096-bit block -- and all
128 bytes must come out as baked, through `byte.emit` (a dispatch through `hex.tables`, which leaves
the pointer arm alone, like the walkers' own emits).

R9: the same program with the header's `pad` dropped and the bank pushed off a block must read WRONG
-- so the passing test is the alignment's doing, which is exactly what a narrow read assumes and what
`build.sprbank_misalignment` checks in a build.
"""
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj

ROOT = Path(__file__).resolve().parents[2]
SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
CFG = Config()
STRIDE = wr.SPR_BLOCK_STRIDE
BLOCKS = [[(k * 97 + i * 13 + 5) & 0xFF for i in range(STRIDE)] for k in range(2)]


def _program(header, lead_ops=0):
    main = ["stl.startup_and_init_all",
            generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)]
    for k in range(len(BLOCKS)):
        main += ["    hex.set 4, t_blk, %d" % k,
                 "    frame.blk_addr t_ptr, t_blk, sprbank",
                 "    hex.read_byte_and_inc t_v, t_ptr",        # the block's first read: the full arm
                 "    byte.emit t_v"]
        main += ["    frame.read3_and_inc t_v, t_ptr", "    byte.emit t_v"] * (STRIDE - 1)
    main += ["    stl.loop",
             "t_blk: hex.vec 4", "t_ptr: hex.vec w/4", "t_v: hex.vec 2",
             wr.hoisted_scratch_fj(CFG)]
    if lead_ops:
        main.append("rep(%d, i) stl.fj 0, 0" % lead_ops)
    main += header
    for blk in BLOCKS:
        main += [";%#x * dw" % v for v in blk]
    return "\n".join(main) + "\n"


def _run(tmp, name, text):
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    p = tmp / (name + ".fj")
    p.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()], out,
                memory_width=W, print_time=False)
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    assert "loop" in str(term.termination_cause).lower(), term.termination_cause
    return list(io.get_output(allow_incomplete_output=True))


def test_every_byte_of_an_aligned_block_reads_back(tmp_path):
    got = _run(tmp_path, "aligned", _program(wr.sprite_bank_header()))
    want = [v for blk in BLOCKS for v in blk]
    bad = [(i // STRIDE, i % STRIDE, g, w) for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert len(got) == len(want) and not bad, (len(got), bad[:8])


def test_an_unaligned_bank_reads_wrong(tmp_path):
    header = [ln for ln in wr.sprite_bank_header() if not ln.startswith("pad ")]
    assert len(header) == len(wr.sprite_bank_header()) - 1, "the header no longer carries a pad"
    got = _run(tmp_path, "unaligned", _program(header, lead_ops=37))
    want = [v for blk in BLOCKS for v in blk]
    assert len(got) == len(want)
    assert got != want, "a bank off a 4096-bit block read back intact -- the check has no teeth"
