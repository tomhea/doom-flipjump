"""M13pS0 -- measure byte.emit/cm.emit per-call op cost (the two-count delta technique, mirroring
scratchpad/measure_walk.py). Run: python scratchpad/measure_emit.py"""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flipjump as fj
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj
from doomfj.texturecompiler import colormap_values, _index_nibbles
from doomfj.wad import WadFile
from flipjump.interpreter.io_devices.FixedIO import FixedIO

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj").resolve()


def run_ops(table_text, call_line, idx_width, n, tmp):
    main = "\n".join([
        "stl.startup_and_init_all",
        f"hex.set {idx_width}, idx, 0", "hex.set 8, cnt, 0", f"hex.set 8, lim, {n}",
        "loop:", "hex.cmp 8, cnt, lim, body, done, done",
        "body:", call_line, "hex.inc 8, cnt", ";loop",
        "done:", "stl.loop",
        f"idx: hex.vec {idx_width}", "cnt: hex.vec 8", "lim: hex.vec 8",
        table_text,
    ])
    p = tmp / "m.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp / "m.fjm"
    fj.assemble([FIXED_POINT_FJ, p], out, memory_width=W, print_time=False)
    term = fj.run(out, io_device=FixedIO(b""), print_time=False, print_termination=False)
    return term.op_counter


def per_call(table_text, call_line, idx_width, tmp, lo=100, hi=300):
    a = run_ops(table_text, call_line, idx_width, lo, tmp)
    b = run_ops(table_text, call_line, idx_width, hi, tmp)
    return (b - a) / (hi - lo)


def main():
    tmp = Path(tempfile.mkdtemp())

    byte_table = generate_emit_dispatch_table_fj("bytetbl", list(range(256)), index_nibbles=2)
    byte_ops = per_call(byte_table, "bytetbl.emit idx", 2, tmp)
    print(f"byte.emit (identity 256-table): {byte_ops:.1f} ops/call")

    wad = WadFile.from_path("tests/fixtures/freedoom_assets.wad")
    values = colormap_values(wad, lights=32)
    idx_n = _index_nibbles(len(values))
    cm_table = generate_emit_dispatch_table_fj("cmemit", values, index_nibbles=idx_n, over_align=True)
    cm_ops = per_call(cm_table, "cmemit.emit idx", idx_n, tmp)
    print(f"cm.emit (real {len(values)}-entry colormap): {cm_ops:.1f} ops/call")

    print(f"\nvs the OLD combo cm.apply(399)+xor_zero(284)=683: "
          f"cm.emit alone at {cm_ops:.1f} is {683 / cm_ops:.2f}x cheaper (no register write needed).")


if __name__ == "__main__":
    main()
