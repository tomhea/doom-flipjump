"""M13pS1 -- measure the REAL stream.emit_column body's per-run and per-column ops cost (the
two-count delta technique, mirroring measure_walk.py/measure_emit.py). Builds a program that loops
`reps` times over [present.begin_frame_stream + stream.emit_column] for a column with `n` ceiling
bands + `n` floor bands + 1 wall run (2n+1 runs total), and derives:
  - per-column cost at a fixed run-count (delta over reps, holding n fixed)
  - per-run marginal cost (two-point diff of per-column cost across two values of n)
Run: python scratchpad/measure_stream_column.py
"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flipjump as fj
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj
from doomfj.texturecompiler import _index_nibbles, colormap_values
from doomfj.wad import WadFile
from flipjump.interpreter.io_devices.FixedIO import FixedIO

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj").resolve()
PRESENT_FJ = Path("src/fj/present.fj").resolve()
STREAM_RENDER_FJ = Path("src/fj/stream_render.fj").resolve()
ASSET = "tests/fixtures/freedoom_assets.wad"


def _band_list(label, n, base_colour):
    # n bands, 2 rows each, as 3 PACKED bytes/entry (count, cidx-low, cidx-high) -- see
    # stream.emit_band_list. Row count / colour VALUE don't affect op cost (byte.emit/cm.emit cost
    # only depends on the dispatch, R12).
    lines = [f"{label}:"]
    for i in range(n):
        cidx = base_colour + i
        lines.append("  ;2 * dw")
        lines.append(f"  ;{cidx & 0xFF} * dw")
        lines.append(f"  ;{(cidx >> 8) & 0xFF} * dw")
    return "\n".join(lines)


def _data_fj(n, idx_n):
    return "\n".join([
        _band_list("ceil_bands", n, 0),
        _band_list("floor_bands", n, 100),
        "cexcl: hex.vec 2, 10", "fstart: hex.vec 2, 18",
        f"wall_cidx: hex.vec {idx_n}, 200",
        f"ceil_n: hex.vec 2, {n}", f"floor_n: hex.vec 2, {n}",
    ])


def run_ops(n, reps, byte_table, cm_table, idx_n, tmp):
    main = "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen_stream 0",
        "hex.set 8, cnt, 0", f"hex.set 8, lim, {reps}",
        "loop:", "hex.cmp 8, cnt, lim, body, done, done",
        "body:",
        "present.begin_frame_stream",
        "stream.emit_column ceil_bands, ceil_n, cexcl, fstart, wall_cidx, floor_bands, floor_n",
        "hex.inc 8, cnt", ";loop",
        "done:", "stl.loop",
        "cnt: hex.vec 8", "lim: hex.vec 8",
        _data_fj(n, idx_n),
        byte_table, cm_table,
    ])
    cfg = Config(W=1, H=18)
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    p = tmp / "m.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp / "m.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ, PRESENT_FJ, STREAM_RENDER_FJ, p],
                out, memory_width=W, print_time=False)
    term = fj.run(out, io_device=FixedIO(b""), print_time=False, print_termination=False)
    return term.op_counter


def per_column(n, byte_table, cm_table, idx_n, tmp, lo=50, hi=150):
    a = run_ops(n, lo, byte_table, cm_table, idx_n, tmp)
    b = run_ops(n, hi, byte_table, cm_table, idx_n, tmp)
    return (b - a) / (hi - lo)


def main():
    tmp = Path(tempfile.mkdtemp())
    wad = WadFile.from_path(ASSET)
    values = colormap_values(wad, lights=32)
    idx_n = _index_nibbles(len(values))
    byte_table = generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)
    cm_table = generate_emit_dispatch_table_fj("cm", values, index_nibbles=idx_n, over_align=True)

    points = {}
    for n in (1, 3, 5):
        runs = 2 * n + 1
        cost = per_column(n, byte_table, cm_table, idx_n, tmp)
        points[runs] = cost
        print(f"n={n} ceil+floor bands ({runs} runs/column): {cost:,.0f} ops/column "
              f"({cost / runs:,.0f} ops/run avg)")

    r_lo, r_hi = 3, 11
    per_run = (points[r_hi] - points[r_lo]) / (r_hi - r_lo)
    per_column_fixed = points[r_lo] - per_run * r_lo
    print(f"\nlinear fit (points at {r_lo} and {r_hi} runs):")
    print(f"  per-run marginal cost : {per_run:,.0f} ops/run")
    print(f"  per-column fixed part : {per_column_fixed:,.0f} ops/column (run-count-independent)")

    for lo_est, hi_est in ((5, 8), (8, 12)):
        est_runs = (lo_est + hi_est) / 2
        est_cost = per_column_fixed + per_run * est_runs
        print(f"  @ ~{lo_est}-{hi_est} runs/column: est {est_cost:,.0f} ops/column")

    E1M1_COLUMNS = 160
    for lo_est, hi_est in ((5, 8), (8, 12)):
        est_runs = (lo_est + hi_est) / 2
        est_ls1 = per_column_fixed * E1M1_COLUMNS + per_run * est_runs * E1M1_COLUMNS
        print(f"  LS1 estimate @ ~{lo_est}-{hi_est} runs x {E1M1_COLUMNS} columns: "
              f"{est_ls1 / 1e6:.2f}M ops/frame (ledger line LS1 <= 2.20M)")


if __name__ == "__main__":
    main()
