"""M13pS1/pS2-crush2b -- the one-column stream-emitter prototype: a SYNTHETIC column through the
REAL `stream.emit_column` body (src/fj/stream_render.fj -- the crush2b PREFIX/SUFFIX clip over
shared FULL-RANGE band lists), decoded by the real device (StreamScreen) and checked byte-exact
against an independently Python-computed column. The ceiling list carries a below-cexcl filler band
(prefix-clipped away) and the floor list an above-fstart filler band (suffix-skipped) -- proving the
clip logic, not just the happy path.
"""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.harness import W as MEM_WIDTH
from doomfj.lut_generator import generate_emit_dispatch_table_fj
from doomfj.texturecompiler import _index_nibbles, colormap_values
from doomfj.wad import WadFile
from tests.fj.stream_screen import StreamScreen

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
PRESENT_FJ = Path("src/fj/present.fj")
STREAM_RENDER_FJ = Path("src/fj/stream_render.fj")

ASSET = "tests/fixtures/freedoom_assets.wad"

# the synthetic column: 3 ceiling bands (2 rows each) + 1 wall run (8 rows) + 3 floor bands (2 rows
# each) -- 7 runs total, at the low end of the pS spec's "~5-12 runs" per-column estimate.
CEIL_BANDS = [(2, 0, 10), (2, 1, 20), (2, 2, 30)]      # (rows, light, colour)
WALL_ROWS = 8
WALL_LIGHT, WALL_COLOUR = 5, 100
FLOOR_BANDS = [(2, 10, 5), (2, 11, 6), (2, 12, 7)]
HEIGHT = sum(r for r, _, _ in CEIL_BANDS) + WALL_ROWS + sum(r for r, _, _ in FLOOR_BANDS)


def _cidx(light, colour):
    return light * 256 + colour


def _expected_column(wad: WadFile):
    cm = wad.colormap()
    out = []
    for rows, light, colour in CEIL_BANDS:
        out += [cm[light][colour]] * rows
    out += [cm[WALL_LIGHT][WALL_COLOUR]] * WALL_ROWS
    for rows, light, colour in FLOOR_BANDS:
        out += [cm[light][colour]] * rows
    return out


def _band_list_fj(label, bands):
    """A crush2b FULL-RANGE visplane buffer: slot 0 = the entry count n (one packed byte), then 3
    PACKED bytes per entry (count, cidx-low, cidx-high), read by stream.emit_prefix/emit_suffix via
    hex.read_byte_and_inc -- NOT hex.vec register form (packed bytes are ONE dw apart, one full
    byte's data bits per op, the `;value*dw` idiom)."""
    lines = [f"{label}:", f"  ;{len(bands)} * dw"]
    for rows, light, colour in bands:
        cidx = _cidx(light, colour)
        lines.append(f"  ;{rows} * dw")
        lines.append(f"  ;{cidx & 0xFF} * dw")
        lines.append(f"  ;{(cidx >> 8) & 0xFF} * dw")
    return "\n".join(lines)


def _emit_data_fj(wad: WadFile):
    cexcl = sum(r for r, _, _ in CEIL_BANDS)
    fstart = cexcl + WALL_ROWS
    wall_lit = wad.colormap()[WALL_LIGHT][WALL_COLOUR]   # the FINAL lit byte, baked host-side (pS2c:
    # FULL-RANGE lists (each sums to HEIGHT): the ceiling list gains a filler band BELOW cexcl (the
    # prefix clip must drop it) and the floor list a filler band ABOVE fstart (the suffix must skip
    # it) -- so the test proves the clip logic, not just the happy path.
    ceil_full = CEIL_BANDS + [(HEIGHT - cexcl, 31, 99)]
    floor_full = [(fstart, 30, 77)] + FLOOR_BANDS
    return "\n".join([                                   # col_lit -- the wall run is byte.emit, no cm lookup)
        _band_list_fj("ceil_bands", ceil_full),
        _band_list_fj("floor_bands", floor_full),
        f"cexcl: hex.vec 2, {cexcl}",
        f"fstart: hex.vec 2, {fstart}",
        f"wall_lit: hex.vec 2, {wall_lit}",
        "cbuf_cell: hex.vec 8, ceil_bands",
        "fbuf_cell: hex.vec 8, floor_bands",
    ])


def _assemble_and_run_one_column(tmp_path, wad: WadFile):
    cfg = Config(W=1, H=HEIGHT)
    values = colormap_values(wad, lights=32)
    idx_n = _index_nibbles(len(values))
    assert idx_n == 4, f"prototype assumes a 4-nibble cm index (got {idx_n}) -- widen colors_arr"
    byte_table = generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)
    cm_table = generate_emit_dispatch_table_fj("cm", values, index_nibbles=idx_n, over_align=True)
    main = "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen_stream 0",
        "present.begin_frame_stream",
        "stream.emit_column cbuf_cell, cexcl, fstart, wall_lit, fbuf_cell",
        "stl.loop",
        _emit_data_fj(wad),
        byte_table,
        cm_table,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "onecol.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "onecol.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 STREAM_RENDER_FJ.resolve(), p.resolve()],
                out, memory_width=MEM_WIDTH, print_time=False)
    screen = StreamScreen()
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False)
    return screen, term


def test_one_column_byte_exact_vs_python_computed_column(tmp_path):
    wad = WadFile.from_path(ASSET)
    screen, _term = _assemble_and_run_one_column(tmp_path, wad)
    assert screen.pixel_indices == _expected_column(wad)
    assert screen.flush_count == 1
    assert screen.frame_count == 1
