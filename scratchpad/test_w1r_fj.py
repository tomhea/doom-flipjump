"""M13-W1R unit test: the generated `w1rpat.walk`/`walk_win` vs `ReferenceModel.w1r_runs`.

Tiny standalone fj program (shared fcall'd leaves, real cm/byte emit tables) driven over a
tier/group/window battery; stdout bytes must equal the Python mirror exactly.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump
from doomfj.reference_model import ReferenceModel, COLORMAP_LIGHTS
from doomfj.lut_generator import generate_emit_dispatch_table_fj, generate_w1r_walls_fj
from doomfj.texturecompiler import colormap_values, _index_nibbles
from doomfj.wad import WadFile

aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
cmv = colormap_values(aw, lights=COLORMAP_LIGHTS)
colormap = aw.colormap()

CASES = [  # (ctake, fstart, x_column, wall_lit)  -- full-wall walk cases
    (10, 13, 0, 0x67),      # tier 0
    (10, 15, 4, 0x67),      # tier 0 boundary (wlen=5)
    (10, 16, 8, 0x67),      # tier 1 boundary (wlen=6)
    (20, 30, 0, 0x12), (20, 30, 4, 0x12), (20, 30, 8, 0x12), (20, 30, 12, 0x12),  # tier 1
    (5, 20, 12, 0x67),      # tier 1 (wlen=15)
    (5, 21, 0, 0x67),       # tier 2 boundary (wlen=16)
    (40, 65, 8, 0x30),      # tier 2
    (0, 39, 4, 0x30),       # tier 2 boundary (wlen=39)
    (0, 40, 4, 0x30),       # tier 3 boundary (wlen=40)
    (10, 80, 12, 0x67),     # tier 3, cycles
    (0, 100, 4, 0x12),      # tier 3, full column
]
WCASES = [  # (ctake, fstart, wlo, whi, x_column, wall_lit) -- windowed cases
    (0, 50, 10, 30, 0, 0x67),
    (0, 50, 45, 50, 4, 0x67),   # skip most runs, clamp at whi
    (0, 50, 20, 20, 8, 0x67),   # empty window -> nothing
    (0, 50, 0, 5, 12, 0x12),    # top window
    (30, 34, 31, 33, 0, 0x30),  # tier 0 window
    (10, 90, 11, 89, 8, 0x30),  # tall wall, near-full window
]


def mirror_walk(ctake, fstart, xcol, wl):
    wl2 = (wl + 0x30) & 0xFF                     # a distinct second colour per case
    out = bytearray()
    for rel, row, alt in ReferenceModel.w1r_runs(fstart - ctake, xcol):
        out += bytes([ctake + rel, colormap[row][wl2 if alt else wl]])
    return out


def mirror_win(ctake, fstart, wlo, whi, xcol, wl):
    out = bytearray()
    if wlo >= whi:
        return out
    wl2 = (wl + 0x30) & 0xFF
    for rel, row, alt in ReferenceModel.w1r_runs(fstart - ctake, xcol):
        y2 = ctake + rel
        c = colormap[row][wl2 if alt else wl]
        if y2 <= wlo:
            continue
        if y2 >= whi:
            out += bytes([whi, c])
            break
        out += bytes([y2, c])
    return out


def build_program():
    byte_tbl = generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)
    cm_tbl = generate_emit_dispatch_table_fj("cm", cmv, index_nibbles=_index_nibbles(len(cmv)),
                                             over_align=True)
    pat = generate_w1r_walls_fj(ReferenceModel.W1R_TIER_BOUNDS, ReferenceModel.W1R_PATTERNS)
    drive = []
    for (ct, fs, xc, wl) in CASES:
        drive += [f"hex.set 2, wlen_r, {fs - ct}", f"hex.set 2, ctake_r, {ct}",
                  f"hex.set 2, fstart_r, {fs}",
                  f"hex.set 2, gnrow_r, {ReferenceModel.wall_noise(xc)}",
                  f"hex.set 2, gnrow2, {ReferenceModel.wall_noise2(xc)}",
                  f"hex.set 2, gnrow3, {ReferenceModel.wall_noise3(xc)}",
                  f"hex.set 2, wlit_r, {wl}",
                  f"hex.set 2, wlit2_r, {(wl + 0x30) & 0xFF}",
                  "stl.fcall wleaf, wret",
                  "stl.output_char 0xFA", "stl.output_char 0xF5"]
    for (ct, fs, lo, hi, xc, wl) in WCASES:
        drive += [f"hex.set 2, ctake_r, {ct}", f"hex.set 2, fstart_r, {fs}",
                  f"hex.set 2, wlo_r, {lo}", f"hex.set 2, whi_r, {hi}",
                  f"hex.set 2, gnrow_r, {ReferenceModel.wall_noise(xc)}",
                  f"hex.set 2, gnrow2, {ReferenceModel.wall_noise2(xc)}",
                  f"hex.set 2, gnrow3, {ReferenceModel.wall_noise3(xc)}",
                  f"hex.set 2, wlit_r, {wl}",
                  f"hex.set 2, wlit2_r, {(wl + 0x30) & 0xFF}",
                  "stl.fcall wwleaf, wret",
                  "stl.output_char 0xFA", "stl.output_char 0xF5"]
    prog = "\n".join([
        "stl.startup_and_init_all",
        byte_tbl, cm_tbl, pat,
        *drive,
        "stl.loop",
        "wleaf:",
        "w1rpat.walk wlen_r, ctake_r, fstart_r, gnrow_r, wlit_r, wlit2_r, cmidx_r",
        "stl.fret wret",
        "wwleaf:",
        "w1rpat.walk_win ctake_r, fstart_r, wlo_r, whi_r, gnrow_r, wlit_r, wlit2_r, cmidx_r",
        "stl.fret wret",
        "wret: 0;0",
        "wlen_r: hex.vec 2", "ctake_r: hex.vec 2", "fstart_r: hex.vec 2",
        "wlo_r: hex.vec 2", "whi_r: hex.vec 2",
        "gnrow_r: hex.vec 2", "gnrow2: hex.vec 2", "gnrow3: hex.vec 2", "wlit_r: hex.vec 2", "wlit2_r: hex.vec 2", "cmidx_r: hex.vec 4",
        ""])
    return prog


def main():
    expected = bytearray()
    for (ct, fs, xc, wl) in CASES:
        expected += mirror_walk(ct, fs, xc, wl) + b"\xFA\xF5"
    for (ct, fs, lo, hi, xc, wl) in WCASES:
        expected += mirror_win(ct, fs, lo, hi, xc, wl) + b"\xFA\xF5"
    prog = build_program()
    fp = ROOT / "scratchpad" / "w1r_unit.fj"
    fp.write_text(prog, encoding="utf-8")
    ok = flipjump.assemble_and_run_test_output(
        [fp], b"", bytes(expected), warning_as_errors=True,
        should_raise_assertion_error=False)
    print("W1R fj unit:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
