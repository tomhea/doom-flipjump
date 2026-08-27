"""Gap #5 -- re-measure `cm.apply` + `xor_zero` with the body-removed control.

`docs/m13p-procedural-plan.md` claims `cm.emit` is "2.07x cheaper than the OLD cm.apply(399) +
xor_zero(284) = 683 combo". Those figures came from the same harness whose per-iteration overhead
was never subtracted -- the one that reported `byte.emit` at 283.6 when the call is 47.1
(scratchpad/measure_emit_ctl.py, commit f93e9cb). So the comparison it supports is unverified in
BOTH terms, and the ratio could move either way.

Same technique as measure_emit_ctl.py: a two-count delta for the fixed startup, PLUS the control
the original lacked -- the identical loop with the call removed.

    python scratchpad/measure_apply_ctl.py
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.lut_generator import generate_emit_dispatch_table_fj          # noqa: E402
from doomfj.texturecompiler import colormap_values, compile_colormap, _index_nibbles  # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO               # noqa: E402

FIXED_POINT_FJ = (ROOT / "src/fj/fixed_point.fj").resolve()
tmp = Path(tempfile.mkdtemp())


def run_ops(table_text, call_lines, decls, idx_width, n, tag):
    main = "\n".join([
        "stl.startup_and_init_all",
        "hex.set %d, idx, 0" % idx_width, "hex.set 8, cnt, 0", "hex.set 8, lim, %d" % n,
        "loop:", "hex.cmp 8, cnt, lim, body, done, done",
        "body:", *call_lines, "hex.inc 8, cnt", ";loop",
        "done:", "stl.loop",
        "idx: hex.vec %d" % idx_width, "cnt: hex.vec 8", "lim: hex.vec 8", *decls,
        table_text,
    ])
    p = tmp / ("%s.fj" % tag); p.write_text(main, encoding="utf-8")
    out = tmp / ("%s.fjm" % tag)
    fj.assemble([FIXED_POINT_FJ, p], out, memory_width=W, print_time=False)
    term = fj.run(out, io_device=FixedIO(b""), print_time=False, print_termination=False)
    return term.op_counter


def per_iter(table_text, call_lines, decls, idx_width, tag, lo=100, hi=300):
    a = run_ops(table_text, call_lines, decls, idx_width, lo, tag + "a")
    b = run_ops(table_text, call_lines, decls, idx_width, hi, tag + "b")
    return (b - a) / (hi - lo)


art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cmv = colormap_values(art, lights=32)
idx_n = _index_nibbles(len(cmv))
apply_tbl = compile_colormap("cmt", art, lights=32)
emit_tbl = generate_emit_dispatch_table_fj("cme", cmv, index_nibbles=idx_n, over_align=True)

print("colormap: %d entries, %d-nibble index" % (len(cmv), idx_n))
print("")
print("%-44s %10s %10s %10s" % ("", "with call", "loop only", "THE CALL"))

cases = [
    ("cm.apply dst, idx",           apply_tbl, ["cmt.apply dst, idx"], ["dst: hex.vec 2"], "ap"),
    ("cm.apply + hex.xor_zero 2",   apply_tbl, ["cmt.apply dst, idx", "hex.xor_zero 2, res, dst"],
                                    ["dst: hex.vec 2", "res: hex.vec 2"], "apz"),
    ("cm.emit idx",                 emit_tbl,  ["cme.emit idx"], [], "em"),
]
results = {}
for name, tbl, calls, decls, tag in cases:
    t = time.perf_counter()
    withc = per_iter(tbl, calls, decls, idx_n, tag + "w")
    without = per_iter(tbl, [], decls, idx_n, tag + "n")
    results[name] = withc - without
    print("%-44s %10.1f %10.1f %10.1f   (%.0f s)"
          % (name, withc, without, withc - without, time.perf_counter() - t))

combo = results["cm.apply + hex.xor_zero 2"]
emit = results["cm.emit idx"]
print("")
print("  the doc says: cm.apply(399) + xor_zero(284) = 683, and cm.emit is 2.07x cheaper.")
print("  MEASURED here, harness removed: combo %.1f, emit %.1f -> emit is %.2fx %s"
      % (combo, emit, (combo / emit) if emit else 0,
         "cheaper" if combo > emit else "MORE EXPENSIVE"))
