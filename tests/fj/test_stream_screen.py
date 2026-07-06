"""M13pS0 — pure-Python (no fj assembly) tests for StreamScreen: feed a synthetic byte stream directly
via write_bit and assert the decoded pixel grid + flush behavior. Fast (no assemble/run), the first
gate on the device mechanics before any fj program touches them."""
import struct

import pytest

from tests.fj.stream_screen import StreamScreen


def _feed(screen: StreamScreen, data: bytes) -> None:
    for byte in data:
        for i in range(8):
            screen.write_bit((byte >> i) & 1 == 1)


def _init_stream_bytes(width, height, bpp, ncolors, flush_mode) -> bytes:
    return (bytes([0x01]) + struct.pack("<H", width) + struct.pack("<H", height)
            + bytes([bpp]) + struct.pack("<H", ncolors) + bytes([flush_mode]))


def test_init_screen_stream_reads_the_extra_flush_mode_byte():
    screen = StreamScreen()
    _feed(screen, _init_stream_bytes(2, 3, 8, 16, 1))
    assert (screen.width, screen.height, screen.bpp, screen.palette_size) == (2, 3, 8, 16)
    assert screen.flush_mode == 1


def test_begin_frame_stream_requires_prior_init():
    screen = StreamScreen()
    with pytest.raises(Exception):
        _feed(screen, bytes([0x07]))


# a 2x3 screen (width=2, height=3, 6 pixels): column-major runs
#   column 0: one run of 3 pixels, color 5           -> rows 0,1,2 = 5
#   column 1: a split run: 1 pixel color 7, 2 pixels color 9  -> row0=7, rows1-2=9
# row-major pixel_indices = [row0: col0,col1; row1: col0,col1; row2: col0,col1]
#                          = [5,7, 5,9, 5,9]
STREAM_RUNS = bytes([3, 5, 1, 7, 2, 9])
EXPECTED_GRID = [5, 7, 5, 9, 5, 9]


def test_column_major_run_stream_flush_per_frame():
    """flush_mode=0 (the shipped default): the device presents exactly ONCE, after the whole stream."""
    screen = StreamScreen()
    _feed(screen, _init_stream_bytes(2, 3, 8, 16, 0))
    _feed(screen, bytes([0x07]))
    _feed(screen, STREAM_RUNS)
    assert screen.pixel_indices == EXPECTED_GRID
    assert screen.flush_count == 1
    assert screen.frame_count == 1


def test_column_major_run_stream_flush_per_column():
    """flush_mode=1: the device presents once per completed column (2 columns -> 2 flushes)."""
    screen = StreamScreen()
    _feed(screen, _init_stream_bytes(2, 3, 8, 16, 1))
    _feed(screen, bytes([0x07]))
    _feed(screen, STREAM_RUNS)
    assert screen.pixel_indices == EXPECTED_GRID
    assert screen.flush_count == 2
    assert screen.frame_count == 2


def test_stream_reverts_to_normal_command_parsing_after_the_frame_fills():
    """After exactly width*height pixels stream in, the next bytes are parsed as a NORMAL command
    (e.g. another begin_frame_stream for a second frame), not more stream bytes."""
    screen = StreamScreen()
    _feed(screen, _init_stream_bytes(2, 3, 8, 16, 0))
    _feed(screen, bytes([0x07]))
    _feed(screen, STREAM_RUNS)
    assert screen.flush_count == 1
    # a second frame, same content
    _feed(screen, bytes([0x07]))
    _feed(screen, STREAM_RUNS)
    assert screen.pixel_indices == EXPECTED_GRID
    assert screen.flush_count == 2
    assert screen.frame_count == 2


def test_stdin_feed_still_works_alongside_the_stream_decode():
    """StreamScreen also supports the stdin-feed convention (mirrors _ScreenWithInput) -- read_bit
    drains an independent input buffer, unaffected by the output-stream decode above."""
    screen = StreamScreen(stdin=b"\x2a")
    assert screen.read_bit() is False   # 0x2a = 0b00101010, lsb-first -> 0,1,0,1,0,1,0,0
    assert screen.read_bit() is True


# ── the fj-level integration test: emit the SAME 2x3 grid via the real macros + emit table ─────


# ---------------- M13-planesproto: the per-visplane frame command (0x09) ----------------
# a 2x6 screen (width=2, height=6). One ceiling vp list [(2, 0x11), (4, 0x22)] (sums to 6),
# one floor vp list [(3, 0x33), (3, 0x44)].
# col 0: cexcl=2, fstart=4, lit=0x55, cvp=0, fvp=0
#   ceiling prefix [0, min(2,4)=2): rows 0-1 = 0x11
#   wall [2,4): rows 2-3 = 0x55
#   floor suffix skipping 4 rows of [(3,0x33),(3,0x44)]: skip 3 (all of 0x33) + 1 of 0x44
#     -> rows 4-5 = 0x44
# col 1: unclaimed (fvp=0xFF) -> stays 0
PLANES_PAYLOAD = bytes([
    1,                     # n_cvps
    2, 2, 0x11, 4, 0x22,   # cvp0: 2 entries
    1,                     # n_fvps
    2, 3, 0x33, 3, 0x44,   # fvp0: 2 entries
    2, 4, 0x55, 0, 0,      # col 0 record: cexcl, fstart, lit, cvp, fvp
    0, 0, 0, 0, 0xFF,      # col 1 record: unclaimed
])
PLANES_EXPECTED = [0x11, 0, 0x11, 0, 0x55, 0, 0x55, 0, 0x44, 0, 0x44, 0]   # row-major 2x6


def test_planes_frame_decodes_columns_from_shared_vp_lists():
    screen = StreamScreen()
    _feed(screen, _init_stream_bytes(2, 6, 8, 16, 0))
    _feed(screen, bytes([0x09]))
    _feed(screen, PLANES_PAYLOAD)
    assert screen.pixel_indices == PLANES_EXPECTED
    assert screen.flush_count == 1 and screen.frame_count == 1


def test_planes_frame_ceiling_clips_at_fstart_and_empty_lists_are_fine():
    """cexcl > fstart -> the ceiling prefix stops at fstart (the min); n=0 vp lists parse."""
    screen = StreamScreen()
    _feed(screen, _init_stream_bytes(1, 6, 8, 16, 0))
    _feed(screen, bytes([0x09]))
    payload = bytes([
        2, 1, 6, 0x11, 0,        # cvp0 = [(6, 0x11)], cvp1 = [] (empty list parses)
        1, 1, 6, 0x22,           # fvp0 = [(6, 0x22)]
        5, 3, 0x77, 0, 0,        # cexcl=5 > fstart=3 -> ceiling rows 0-2, no wall, floor rows 3-5
    ])
    _feed(screen, payload)
    assert screen.pixel_indices == [0x11, 0x11, 0x11, 0x22, 0x22, 0x22]


def test_planes_frame_reverts_to_command_parsing():
    """After the payload completes, normal command decode resumes (a second 0x09 works)."""
    screen = StreamScreen()
    _feed(screen, _init_stream_bytes(1, 2, 8, 16, 0))
    for colour in (0x0A, 0x0B):
        _feed(screen, bytes([0x09]))
        _feed(screen, bytes([0, 1, 1, 2, colour, 0, 0, 0x00, 0, 0]))   # fstart=0 -> all-floor column
    assert screen.pixel_indices == [0x0B, 0x0B]
    assert screen.frame_count == 2


from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.harness import W as MEM_WIDTH
from doomfj.lut_generator import generate_emit_dispatch_table_fj

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
PRESENT_FJ = Path("src/fj/present.fj")


def _assemble_and_run_micro_column(tmp_path, flush_mode):
    """Emit the SAME 3-run 2x3 grid as STREAM_RUNS (count=3,color=5 / count=1,color=7 /
    count=2,color=9), but via the REAL present.fj macros + a real byte-identity emit table, then
    decode it with StreamScreen -- the end-to-end pS0 gate (fj emission -> device decode)."""
    cfg = Config(W=2, H=3)
    byte_table = generate_emit_dispatch_table_fj("bytetbl", list(range(256)), index_nibbles=2)
    main = "\n".join([
        "stl.startup_and_init_all",
        f"present.init_screen_stream {flush_mode}",
        "present.begin_frame_stream",
        "hex.set 2, v, 3", "bytetbl.emit v",   # count=3
        "hex.set 2, v, 5", "bytetbl.emit v",   # color=5
        "hex.set 2, v, 1", "bytetbl.emit v",   # count=1
        "hex.set 2, v, 7", "bytetbl.emit v",   # color=7
        "hex.set 2, v, 2", "bytetbl.emit v",   # count=2
        "hex.set 2, v, 9", "bytetbl.emit v",   # color=9
        "stl.loop",
        "v: hex.vec 2",
        byte_table,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "microcol.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "microcol.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(), p.resolve()],
                out, memory_width=MEM_WIDTH, print_time=False)
    screen = StreamScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    return screen


def test_fj_emits_a_known_3run_column_flush_per_frame(tmp_path):
    screen = _assemble_and_run_micro_column(tmp_path, flush_mode=0)
    assert screen.pixel_indices == EXPECTED_GRID
    assert screen.flush_count == 1


def test_fj_emits_a_known_3run_column_flush_per_column(tmp_path):
    screen = _assemble_and_run_micro_column(tmp_path, flush_mode=1)
    assert screen.pixel_indices == EXPECTED_GRID
    assert screen.flush_count == 2
