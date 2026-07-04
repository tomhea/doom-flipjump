"""M13pS2c -- the LS2 band-list machinery: standalone kernel tests, de-risked BEFORE any wiring
(mirrors the projection-kernel precedent, R9). Each piece is tested in isolation against the
already-validated host algorithm (ReferenceModel._recip_div32 / _zidx_band_walk, R15) before the
per-column pass-1 wiring lands. Follows the fj<->host parity pattern from test_fixed_point.py:
one program computes every case, printed as fixed-width hex, byte-compared vs the host mirror."""
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.lut_generator import (
    generate_slopediv_recip_lut_fj, generate_yslope_lut_fj, generate_zlight_lut_fj,
)
from doomfj.reference_model import COLORMAP_LIGHTS, ReferenceModel
from doomfj.config import Config

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
PROJECTION_FJ = Path("src/fj/projection.fj")
PLANE_BANDS_FJ = Path("src/fj/plane_bands.fj")

# every REAL planeheight the E1M1 spawn frame's render loop actually computes (R15's validated set)
REAL_E1M1_PLANEHEIGHTS = [
    458752, 589824, 983040, 1048576, 1507328, 1638400, 2162688, 2555904, 2686976, 3211264,
    3342336, 4259840, 4653056, 5177344, 5701632, 6225920, 6750208, 6881280, 8847360, 8978432,
    9371648, 9895936, 10682368, 10944512, 11075584, 11468800, 11599872, 11993088, 12517376,
    12648448, 13172736, 14090240, 14614528, 16711680, 17235968, 17760256, 19333120, 21954560,
    23527424, 26804224, 32440320,
]


def _run(tmp_path, name, body, data, expected: bytes):
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), PROJECTION_FJ.resolve(), PLANE_BANDS_FJ.resolve(), p.resolve()],
        b"", expected, memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != host mirror"


def test_recip32_matches_recip_div32_for_every_real_e1m1_planeheight(tmp_path):
    body, data, expected = [], [], []
    for i, ph in enumerate(REAL_E1M1_PLANEHEIGHTS):
        data.append(f"ph{i}: hex.vec 8, {hex(ph)}")
        body += [f"hex.mov 8, bb_recip_ph, ph{i}", "stl.fcall recip32_leaf, plane_recip_ret",
                 "hex.print_as_digit 8, bb_recip_out, 0", "stl.output '\\n'"]
        expected.append(f"{ReferenceModel._recip_div32(ph):08x}\n")
    data += ["bb_recip_ph: hex.vec 8", "bb_recip_out: hex.vec 8", "plane_recip_ret: ;0",
             "recip32_leaf: plane.recip32", generate_slopediv_recip_lut_fj("slopediv_recip")]
    _run(tmp_path, "recip32", body, data, "".join(expected).encode())


# ── build_bands: the full per-column band-list construction (seed + threshold walk + packed writes) ──

MAX_BANDS = 50


def _expected_bands(rm, ph, light, base, y0, count, ascending):
    """The SAME grouping the fj kernel performs, built from the already-validated
    ReferenceModel._zidx_band_walk (R15): rows in EMISSION order (always ascending y — `ascending`
    only affects which DIRECTION zidx moves, not the row iteration order)."""
    rows = list(range(y0, y0 + count))
    zidxs = rm._zidx_band_walk(ph, rows)
    lvl = min(15, light >> 4)
    bands = []
    for z in zidxs:
        zrow = rm.zlight[lvl][z]
        if bands and bands[-1][1] == zrow:
            bands[-1] = (bands[-1][0] + 1, zrow)
        else:
            bands.append((1, zrow))
    return [(c, base, zrow) for c, zrow in bands]


def _build_bands_program(cases):
    """cases: list of (ph, light, base, y0, count, ascending). Emits ONE program that runs
    build_bands for each case into its own MAX_BANDS*3-byte buffer, then prints bb_n followed by
    each written (count, base, zrow) triple, all as fixed 2-digit hex."""
    body, data = [], []
    for i, (ph, light, base, y0, count, ascending) in enumerate(cases):
        data += [
            f"ph{i}: hex.vec 8, {hex(ph)}", f"light{i}: hex.vec 2, {hex(light)}",
            f"base{i}: hex.vec 2, {hex(base)}", f"y0_{i}: hex.vec 2, {hex(y0)}",
            f"count{i}: hex.vec 2, {hex(count)}", f"asc{i}: hex.vec 2, {hex(ascending)}",
            f"arr{i}:", *[";0 * dw" for _ in range(MAX_BANDS * 3)],
        ]
        body += [
            f"hex.mov 8, bb_ph, ph{i}", f"hex.mov 2, bb_light, light{i}",
            f"hex.mov 2, bb_base, base{i}", f"hex.mov 2, bb_y0, y0_{i}",
            f"hex.mov 2, bb_count, count{i}", f"hex.mov 2, bb_ascending, asc{i}",
            f"hex.set w/4, bb_arr, arr{i}",
            "stl.fcall build_bands_leaf, plane_band_ret",
            "hex.print_as_digit 2, bb_n, 0", "stl.output ':'",
            f"hex.set w/4, dumpptr, arr{i}",
            "hex.zero 2, dumpi",
          f"dumploop{i}:",
            f"hex.cmp 2, dumpi, bb_n, dumpbody{i}, dumpdone{i}, dumpdone{i}",
          f"dumpbody{i}:",
            "hex.read_byte_and_inc dcnt, dumpptr", "hex.print_as_digit 2, dcnt, 0",
            "hex.read_byte_and_inc dbase, dumpptr", "hex.print_as_digit 2, dbase, 0",
            "hex.read_byte_and_inc dzrow, dumpptr", "hex.print_as_digit 2, dzrow, 0",
            "stl.output ','",
            "hex.inc 2, dumpi", f";dumploop{i}",
          f"dumpdone{i}:",
            "stl.output '\\n'",
        ]
    data += [
        "bb_ph: hex.vec 8", "bb_light: hex.vec 2", "bb_base: hex.vec 2", "bb_y0: hex.vec 2",
        "bb_count: hex.vec 2", "bb_ascending: hex.vec 2", "bb_arr: hex.vec w/4", "bb_n: hex.vec 2",
        "bb_recip_ph: hex.vec 8", "bb_recip_out: hex.vec 8",
        "plane_recip_ret: ;0", "plane_band_ret: ;0",
        "dumpptr: hex.vec w/4", "dumpi: hex.vec 2", "dcnt: hex.vec 2", "dbase: hex.vec 2",
        "dzrow: hex.vec 2",
        "recip32_leaf: plane.recip32", "build_bands_leaf: plane.build_bands",
        generate_slopediv_recip_lut_fj("slopediv_recip"),
        generate_yslope_lut_fj("yslope", Config().VIEW_W, Config().VIEW_H),
        generate_zlight_lut_fj("zlight", Config().VIEW_W, COLORMAP_LIGHTS),
    ]
    return body, data


def test_build_bands_matches_zidx_band_walk_for_real_ceiling_and_floor_windows(tmp_path):
    rm = ReferenceModel()
    cfg_centery = 50
    cases = []
    expected_lines = []
    for ph in REAL_E1M1_PLANEHEIGHTS[:12]:   # a representative slice keeps the program/assemble small
        for light in (16, 176, 255):
            base = 42
            # ceiling: y0=0, ascending=1; floor: y0=centery, ascending=0
            for y0, count, ascending in ((0, cfg_centery, 1), (cfg_centery, 100 - cfg_centery, 0)):
                cases.append((ph, light, base, y0, count, ascending))
                bands = _expected_bands(rm, ph, light, base, y0, count, ascending)
                line = f"{len(bands):02x}:" + "".join(f"{c:02x}{b:02x}{z:02x}," for c, b, z in bands) + "\n"
                expected_lines.append(line)
    body, data = _build_bands_program(cases)
    _run(tmp_path, "build_bands", body, data, "".join(expected_lines).encode())


def test_build_bands_ph_zero_case(tmp_path):
    rm = ReferenceModel()
    cases = [(0, 128, 7, 0, 50, 1), (0, 128, 7, 50, 50, 0)]
    expected_lines = []
    for ph, light, base, y0, count, ascending in cases:
        bands = _expected_bands(rm, ph, light, base, y0, count, ascending)
        line = f"{len(bands):02x}:" + "".join(f"{c:02x}{b:02x}{z:02x}," for c, b, z in bands) + "\n"
        expected_lines.append(line)
    body, data = _build_bands_program(cases)
    _run(tmp_path, "build_bands_ph0", body, data, "".join(expected_lines).encode())


def test_build_bands_empty_window(tmp_path):
    cases = [(6553600, 128, 7, 0, 0, 1)]
    expected_lines = ["00:\n"]
    body, data = _build_bands_program(cases)
    _run(tmp_path, "build_bands_empty", body, data, "".join(expected_lines).encode())
