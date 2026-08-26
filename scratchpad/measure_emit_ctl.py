"""What does `<label>.emit idx` REALLY cost? measure_emit.py's loop overhead was never subtracted.

Its per-iteration body is `hex.cmp 8 + <the call> + hex.inc 8 + jump`, and the two-count delta only
removes the fixed SETUP -- so the 283.6 / 329.5 ops/call in docs/m13p-procedural-plan.md include an
8-nibble compare and an 8-nibble increment on every iteration. This adds the control that was
missing: the SAME loop with the call removed. The difference is the call.

    python scratchpad/measure_emit_ctl.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.lut_generator import generate_emit_dispatch_table_fj          # noqa: E402
from doomfj.texturecompiler import colormap_values, _index_nibbles        # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO               # noqa: E402

FIXED_POINT_FJ = (ROOT / "src/fj/fixed_point.fj").resolve()


def run_ops(table_text, call_lines, idx_width, n, tmp, tag):
    main = "\n".join([
        "stl.startup_and_init_all",
        f"hex.set {idx_width}, idx, 0", "hex.set 8, cnt, 0", f"hex.set 8, lim, {n}",
        "loop:", "hex.cmp 8, cnt, lim, body, done, done",
        "body:", *call_lines, "hex.inc 8, cnt", ";loop",
        "done:", "stl.loop",
        f"idx: hex.vec {idx_width}", "cnt: hex.vec 8", "lim: hex.vec 8",
        table_text,
    ])
    p = tmp / ("%s.fj" % tag); p.write_text(main, encoding="utf-8")
    out = tmp / ("%s.fjm" % tag)
    fj.assemble([FIXED_POINT_FJ, p], out, memory_width=W, print_time=False)
    term = fj.run(out, io_device=FixedIO(b""), print_time=False, print_termination=False)
    return term.op_counter


def per_iter(table_text, call_lines, idx_width, tmp, tag, lo=100, hi=300):
    a = run_ops(table_text, call_lines, idx_width, lo, tmp, tag + "a")
    b = run_ops(table_text, call_lines, idx_width, hi, tmp, tag + "b")
    return (b - a) / (hi - lo)


tmp = Path(tempfile.mkdtemp())
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cmv = colormap_values(art, lights=32)
tables = {
    "byte.emit (256 entries, 2-nibble index)":
        (generate_emit_dispatch_table_fj("bytetbl", list(range(256)), index_nibbles=2),
         "bytetbl.emit idx", 2),
    "cm.emit (%d entries, %d-nibble index)" % (len(cmv), _index_nibbles(len(cmv))):
        (generate_emit_dispatch_table_fj("cmtbl", cmv, index_nibbles=_index_nibbles(len(cmv)),
                                         over_align=True),
         "cmtbl.emit idx", _index_nibbles(len(cmv))),
}

print("%-46s %10s %10s %10s" % ("", "with call", "loop only", "THE CALL"))
for name, (text, call, width) in tables.items():
    tag = name.split(".")[0]
    withc = per_iter(text, [call], width, tmp, tag + "w")
    # THE CONTROL: identical program, identical table, loop body minus the call.
    without = per_iter(text, [], width, tmp, tag + "n")
    print("%-46s %10.1f %10.1f %10.1f" % (name, withc, without, withc - without))

print("")
print("  the 'loop only' column is `hex.cmp 8` + `hex.inc 8` + the jump -- pure harness.")
print("  docs/m13p-procedural-plan.md quotes the 'with call' column as the per-call cost.")
