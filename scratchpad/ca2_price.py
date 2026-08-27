"""MEASURED ops/call for the dropped constant-address candidates, against the REAL macros.

Each arm is built from src/fj/projection.fj itself (not a re-implementation) plus the real
generated tables, so the price is the price the program pays. Every figure is a DIFFERENCE of two
program sizes at two rep counts, so startup, table init and the tail cannot enter the per-call
number.

ARMS
  A  proj.angle_to_x   -- as shipped (hex.read_table_packed 4 on viewangletox)
  B  proj.angle_to_x, disp=1 (the SAME macro, viewangletox as a per-entry DISPATCH)
  C  finesine.read_sin -- as shipped (mode=per_result_nibble, 8 dispatches)
  D  finesine.read_sin -- mode=per_entry (1 dispatch)

CONTROLS (R9)
  V. VACUITY, two-sided. After every run the destination register is read back and must hold the
     value the table says. A run whose destination is wrong is REPORTED AS VACUOUS and its price
     is not printed -- the C1 probe in this repo measured 0.0 ops/call for a KNOWN-GOOD idiom
     because its harness never executed the body and it never checked.
  N. --selftest corrupts the last rep index and REQUIRES every arm to report VACUOUS.
  S. Both arms of a comparison are fed the SAME index sequence, so the delta is the mechanism.

    python scratchpad/ca2_price.py [--selftest]
"""
import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.utils.functions import load_debugging_labels                # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.lut_generator import (generate_dispatch_table_fj,             # noqa: E402
                                  generate_trig_idioms_fj,
                                  generate_viewangletox_lut_fj)
from doomfj.tables import sine_table, viewangletox_table                  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--selftest", action="store_true")
ap.add_argument("--sizes", type=int, nargs=2, default=[24, 72])
args = ap.parse_args()

cfg = Config()
VAL = W.bit_length()
NL = chr(10)
SIZES = tuple(args.sizes)
VTX = [v & 0xFFFFFFFF for v in viewangletox_table(cfg.VIEW_W, cfg.TRIG_N)]
SINE = sine_table(cfg.TRIG_N, 16, 32)

# the index sequence both arms of every comparison see (spread over the whole index range)
IDX = [(i * 617 + 41) % 2048 for i in range(SIZES[1] + 4)]     # 617 is coprime with 2048


def run(lines, want_name, want_nib, want_val):
    tmp = Path(tempfile.mkdtemp(prefix="ca2_"))
    src = tmp / "p.fj"
    src.write_text(NL.join(lines) + NL, encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    consts = tmp / "fj_consts.fj"
    cfg.emit_fj_consts(consts)
    files = [consts.resolve(),
             (ROOT / "src/fj/fixed_point.fj").resolve(),
             (ROOT / "src/fj/projection.fj").resolve(),
             src.resolve()]
    fj.assemble(files, out, memory_width=W, print_time=False, debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)

    def addr(n):
        return min(v for k, v in labels.items() if k == n or k.endswith(":" + n))

    r = FjmRunner(out, flat_max_words=1 << 25)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, ln in r._segments:
        core.add_segment(s, ln)
    for st, vals in r._runs:
        core.set_words(st, vals)
    cause, ops, err, _l, _p = core.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)
    got = sum((core.get_word(addr(want_name) // W + 2 * i + 1) >> VAL) << (4 * i)
              for i in range(want_nib))
    return ops, got == want_val, got, cause


def price(mk_lines, want_name, want_nib, want_of_last):
    res = []
    for n in SIZES:
        want = want_of_last(n)
        ops, ok, got, cause = run(mk_lines(n), want_name, want_nib, want)
        res.append((n, ops, ok, got, want, cause))
        print("      n=%-4d ops=%-12s %s=%#-12x want %#-12x term=%s  %s"
              % (n, format(ops, ","), want_name, got, want, cause,
                 "ok" if ok else "!! VACUOUS"), flush=True)
    per = (res[1][1] - res[0][1]) / (SIZES[1] - SIZES[0])
    return per, all(r[2] for r in res)


def _prog(tbl, body, vecs):
    """The REAL program order (src/doomfj/wall_renderer.py:1784-1788): `stl.startup_and_init_all`
    FIRST, then a jump OVER the generated tables, then the tables. Getting this backwards makes
    op 0 the first word of a data table -- the program halts in 2 ops and every arm reads 0."""
    return (["stl.startup_and_init_all", ";__tbl_end", tbl, "__tbl_end:"]
            + body + ["stl.loop"] + vecs)


def _angle_of(j):
    """the view-relative BAM whose angle_to_x index is j: idx = (angle + ANG90) >> 20."""
    return ((j << 20) - (1 << 30)) & 0xFFFFFFFF


def atx_expect(n):
    return VTX[IDX[n - 1]]


def lines_atx_table(n, bad=False):
    tbl = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    body = []
    for i in range(n):
        j = IDX[i] ^ (0x555 if (bad and i == n - 1) else 0)
        body += ["hex.set 8, angv, %s" % hex(_angle_of(j)), "proj.angle_to_x dstv, angv, 0"]
    return _prog(tbl, body, ["angv: hex.vec 8", "dstv: hex.vec 8"])


def lines_atx_disp(n, bad=False):
    """! ARM B IS THE REAL MACRO, disp=1 -- NOT a bare dispatch lookup.

    The first version of this probe measured `vtxdisp.lookup` ALONE against the whole of
    `proj.angle_to_x`, so A-B credited the change with angle_to_x's entire prologue (mov 8, add 8,
    shr_hex 8,5, mov 3, cmp 3) -- work the change KEEPS. It reported 8,404.7 ops/call saved where
    the 260-frame sweep then measured a whole-program delta smaller than that one call site should
    have produced. Both arms now run the same macro; only the `disp` flag differs, so A-B is the
    change and nothing else."""
    tbl = generate_dispatch_table_fj("vtxdisp", VTX, index_nibbles=3, result_nibbles=8)
    lut = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    body = []
    for i in range(n):
        j = IDX[i] ^ (0x555 if (bad and i == n - 1) else 0)
        body += ["hex.set 8, angv, %s" % hex(_angle_of(j)), "proj.angle_to_x dstv, angv, 1"]
    return _prog(tbl + NL + lut, body, ["angv: hex.vec 8", "dstv: hex.vec 8"])


def _sidx(i):
    return (IDX[i] * 2) % cfg.TRIG_N


def lines_sin(n, mode, bad=False):
    tbl = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16, mode=mode)
    body = []
    for i in range(n):
        j = _sidx(i) ^ (0x555 if (bad and i == n - 1) else 0)
        body += ["hex.set 3, sidx, %s" % hex(j), "finesine.read_sin sdst, sidx"]
    return _prog(tbl, body, ["sidx: hex.vec 3", "sdst: hex.vec 8"])


def sin_expect(n):
    return SINE[_sidx(n - 1)] & 0xFFFFFFFF


BAD = args.selftest
ARMS = [
    ("A  proj.angle_to_x (read_table_packed 4, as shipped)",
     lambda n: lines_atx_table(n, BAD), "dstv", 8, atx_expect),
    ("B  proj.angle_to_x, disp=1 (same macro, viewangletox as a DISPATCH)",
     lambda n: lines_atx_disp(n, BAD), "dstv", 8, atx_expect),
    ("C  finesine.read_sin (per_result_nibble, as shipped)",
     lambda n: lines_sin(n, "per_result_nibble", BAD), "sdst", 8, sin_expect),
    ("D  finesine.read_sin (per_entry)",
     lambda n: lines_sin(n, "per_entry", BAD), "sdst", 8, sin_expect),
]

print("harness: W=%d  sizes=%s  (price = (ops(n2)-ops(n1))/(n2-n1))" % (W, list(SIZES)))
print("NOTE: each rep is a hex.set of the index plus the lookup, IDENTICAL in both arms of a")
print("      pair, so the A-B and C-D deltas are the mechanism alone.")
if BAD:
    print("SELFTEST: the last rep index is corrupted -- every arm MUST report VACUOUS.")
print("")
out = []
for tag, mk, nm, nib, exp in ARMS:
    print("  %s" % tag, flush=True)
    per, vac = price(mk, nm, nib, exp)
    out.append((tag, per, vac))
    print("      -> %.1f ops/rep   %s" % (per, "OK" if vac else "!! VACUOUS"))
    print("", flush=True)

print("=" * 100)
for tag, per, vac in out:
    print("  %-56s %10.1f ops/rep   %s" % (tag[:56], per, "OK" if vac else "VACUOUS"))
print("")
anyvac = any(not v for _t, _p, v in out)
if BAD:
    print("SELFTEST: %s" % ("PASS (every arm rejected the corrupted index)"
                            if all(not v for _t, _p, v in out)
                            else "!! FAIL -- a corrupted index was ACCEPTED"))
    sys.exit(0 if all(not v for _t, _p, v in out) else 1)
if not anyvac:
    print("  A - B (angle_to_x  -> dispatch) : %10.1f ops saved per call" % (out[0][1] - out[1][1]))
    print("  C - D (read_sin per_entry)      : %10.1f ops saved per call" % (out[2][1] - out[3][1]))
print("")
print("ca2_price: %s" % ("FAIL (a vacuous arm)" if anyvac else "PASS"))
sys.exit(1 if anyvac else 0)
