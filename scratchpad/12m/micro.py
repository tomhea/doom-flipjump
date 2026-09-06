"""MICRO-PRICE a macro variant -- exactly, in seconds, before spending a 12-minute build.

Two numbers, and the campaign needs both:

  EXECUTED ops per call   the frame cost. Measured as a SLOPE: assemble the body inside a loop
                          run `lo` times and again `hi` times, and divide the op-count difference
                          by (hi - lo). The loop harness itself cancels exactly, so this is the
                          body's own cost with no harness overhead in it.
  SPACE ops               the emitted size, which is what a layout-freeze filler must replace.
                          Read from the resolved label table as (mend - mstart) / 2w.

and, when two variants are given, whether they compute the SAME VALUE -- printed digits from the
real interpreter, not an argument.

    python scratchpad/12m/micro.py --selftest
    (as a library)  from micro import price, compare

CONTROLS (R9)
  * --selftest re-derives two numbers that were measured independently and written into
    FINDINGS section A (hex.mov 8 = 514 and hex.mov 5 = 320 ops of SPACE). A pricing tool that
    cannot reproduce the price list is not evidence.
  * It also prices a body that is literally nothing and requires 0 executed ops and 0 space --
    the slope method's own zero.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

import flipjump as fj                                                    # noqa: E402
import flipjump.assembler.assembler as _asm                              # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO              # noqa: E402
from doomfj.harness import W                                             # noqa: E402

DEFAULT_FILES = [ROOT / "src/fj/fixed_point.fj"]


def _assemble(text, tmp, name, files):
    """Assemble `text`, returning (fjm_path, labels dict) -- the label table via the same
    labels_resolve hook popcount_census uses, so `mstart`/`mend` come back resolved."""
    src = tmp / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    grabbed = {}
    orig = _asm.labels_resolve

    def spy(ops, labels, memory_width, fjm_writer, **kw):
        grabbed.update({k: v for k, v in labels.items() if ":" not in k})
        return orig(ops, labels, memory_width, fjm_writer, **kw)

    _asm.labels_resolve = spy
    try:
        fj.assemble([Path(f).resolve() for f in files] + [src], out,
                    memory_width=W, print_time=False)
    finally:
        _asm.labels_resolve = orig
    return out, grabbed


def _program(prelude, body, data, n):
    return "\n".join([
        prelude,
        "stl.startup_and_init_all",
        "hex.set 8, _mcnt, 0",
        "hex.set 8, _mlim, %d" % n,
        "_mloop:",
        "  hex.cmp 8, _mcnt, _mlim, _mbody, _mdone, _mdone",
        "_mbody:",
        "mstart:",
        *["  " + line for line in body],
        "mend:",
        "  hex.inc 8, _mcnt",
        "  ;_mloop",
        "_mdone:",
        "stl.loop",
        "_mcnt: hex.vec 8",
        "_mlim: hex.vec 8",
        *data,
    ])


_HARNESS = {}


def _slope(body, data, prelude, lo, hi, files, tmp):
    outs = []
    for tag, n in (("lo", lo), ("hi", hi)):
        out, labels = _assemble(_program(prelude, list(body), list(data), n), tmp, "m_" + tag, files)
        ops = fj.run(out, print_time=False, print_termination=False).op_counter
        outs.append((ops, labels))
    return (outs[1][0] - outs[0][0]) / (hi - lo), outs[0][1]


def price(body, data=(), prelude="", lo=50, hi=130, files=None, tmp=None):
    """-> (executed ops per call, emitted ops of space). Both exact.

    The loop harness (a hex.cmp 8 on the counter, a hex.inc 8, a jump) costs ~299 ops per
    iteration and is NOT constant -- the counter's own value drives the cmp -- so it is measured
    with an EMPTY body over the SAME lo..hi counter range and subtracted. Cancelling it against
    identical counter values, rather than against a constant, is what makes the difference exact."""
    files = list(DEFAULT_FILES if files is None else files)
    tmp = tmp or Path(tempfile.mkdtemp())
    key = (lo, hi, prelude, tuple(data), tuple(str(f) for f in files))
    if key not in _HARNESS:
        _HARNESS[key] = _slope([], data, prelude, lo, hi, files, tmp)[0]
    raw, labels = _slope(body, data, prelude, lo, hi, files, tmp)
    space = (labels["mend"] - labels["mstart"]) // (2 * W)
    return raw - _HARNESS[key], space


def show(body, data=(), prelude="", label="", **kw):
    ex, sp = price(body, data, prelude, **kw)
    print("  %-46s %10.1f executed/call   %8d ops of space" % (label or body[0][:46], ex, sp))
    return ex, sp


def compare(variants, data=(), prelude="", printer=None, quiet=False, **kw):
    """variants: [(name, body_lines), ...]. Prices each; if `printer` is given (a list of
    fj print statements) also runs each variant and returns its printed digits, so the two can
    be shown to compute the SAME VALUE rather than argued to."""
    rows = []
    for name, body in variants:
        ex, sp = price(body, data, prelude, **kw)
        digits = None
        if printer:
            tmp = Path(tempfile.mkdtemp())
            text = "\n".join([prelude, "stl.startup_and_init_all", *body, *printer, "stl.loop",
                              *list(data)])
            out, _ = _assemble(text, tmp, "v", list(DEFAULT_FILES if kw.get("files") is None
                                                   else kw["files"]))
            io = FixedIO(b"")
            fj.run(out, io_device=io, print_time=False, print_termination=False)
            digits = io.get_output(allow_incomplete_output=True).decode()
        rows.append((name, ex, sp, digits))
    base = rows[0]
    if quiet:
        return rows
    print("  %-22s %12s %12s %12s %12s" % ("variant", "exec/call", "d exec", "space", "d space"))
    for name, ex, sp, digits in rows:
        print("  %-22s %12.1f %12.1f %12d %12d   %s"
              % (name, ex, ex - base[1], sp, sp - base[2], digits or ""))
    if printer and len({r[3] for r in rows}) > 1:
        print("  !! THE VARIANTS DISAGREE ON THE VALUE -- this is not an optimisation")
    return rows


def selftest():
    tmp = Path(tempfile.mkdtemp())
    data = ["a8: hex.vec 8, 0x12345678", "b8: hex.vec 8"]
    ok = True
    e0, s0 = price([], data, tmp=tmp)
    print("control 0 (an empty body): %.1f executed, %d space  %s"
          % (e0, s0, "ok" if (e0 == 0 and s0 == 0) else "FAIL"))
    ok &= e0 == 0 and s0 == 0
    e8, s8 = price(["hex.mov 8, b8, a8"], data, tmp=tmp)
    e5, s5 = price(["hex.mov 5, b8, a8"], data, tmp=tmp)
    # FINDINGS section A gives hex.mov 8 = 514 ops of space, measured independently. This tool
    # must reproduce it, and must show the per-nibble slope is exactly 64 ops.
    print("control 1 (space of hex.mov 8): %d   FINDINGS says 514  %s"
          % (s8, "ok" if s8 == 514 else "FAIL"))
    print("control 2 (space slope per nibble): (%d-%d)/3 = %.1f, expect 64.0  %s"
          % (s8, s5, (s8 - s5) / 3.0, "ok" if s8 - s5 == 192 else "FAIL"))
    print("          (FINDINGS' 320 for mov 5 is 64*5; the true figure is 64n+2 = %d -- the"
          % s5)
    print("           2-op constant was dropped from that row, not from the mov-8 row.)")
    print("control 3 (executed cost falls with width): mov 8 = %.1f, mov 5 = %.1f  %s"
          % (e8, e5, "ok" if e8 > e5 > 0 else "FAIL"))
    ok &= s8 == 514 and s8 - s5 == 192 and e8 > e5 > 0
    print("micro selftest: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit("use --selftest, or import price/compare/show")
