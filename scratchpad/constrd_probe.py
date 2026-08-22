"""Prove and price the CONST-ADDRESS READ dispatch (lut_generator.generate_const_read_dispatch_fj).

Correctness first: plant all 256 byte values, read every index through the dispatch, require the
exact value back AND the source cell untouched (the handler flips dbit+8 and jumps INTO the cell,
so it must undo both flips).

Then price it against what it replaces -- `hex.set w/4` + `hex.ptr_index` + `hex.read_byte` -- from
a DIFFERENCE of two program sizes, so fixed startup cannot be smuggled into the per-call figure.

CONTROLS (R9):
  * every one of the 256 values, both nibbles;
  * the source array must be UNCHANGED afterwards;
  * a negative control that breaks the handler (drops the undo-flip) and REQUIRES rejection;
  * cost from a difference, never a single run.

    python scratchpad/constrd_probe.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.utils.functions import load_debugging_labels                # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.lut_generator import generate_const_read_dispatch_fj          # noqa: E402

VAL = (W + W.bit_length()) - W
N = 256
PLANT = [(i * 167 + 13) & 0xFF for i in range(N)]        # 167 is odd -> a permutation of 0..255


def build(nread, break_handler=False, dispatch=True):
    tbl = generate_const_read_dispatch_fj("crd", "arr", N, index_nibbles=2)
    if break_handler:
        tbl = tbl.replace("        arr + 0*dw+dbit+8; clean + 0*dw",
                          "        ; clean + 0*dw", 1)        # drop index 0's undo flip
    lines = [tbl, "stl.startup_and_init_all"]
    lines += ["wflip arr + %d*dw + w, %d*dw" % (i, v) for i, v in enumerate(PLANT) if v]
    for i in range(nread):
        d = i % N
        if dispatch:
            lines += ["hex.set 2, idx, %d" % d, "crd.read_to out + %d*2*dw, idx" % d]
        else:
            lines += ["hex.set 2, idx, %d" % d,
                      "hex.set w/4, abase, arr",
                      "hex.ptr_index aptr, abase, idx",
                      "hex.read_byte out + %d*2*dw, aptr" % d]
    lines += ["stl.loop", "idx: hex.vec 2", "abase: hex.vec w/4", "aptr: hex.vec w/4",
              "arr: hex.vec %d" % (N + 2), "out: hex.vec %d" % (2 * N + 4)]
    d = Path(tempfile.mkdtemp(prefix="crd_"))
    src = d / "p.fj"
    src.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    fjm, dbg = d / "p.fjm", d / "p.fjd"
    fj.assemble([src.resolve()], fjm, memory_width=W, print_time=False, debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)

    def base(nm):
        return min(v for k, v in labels.items() if k == nm or k.endswith(":" + nm)) // W

    r = FjmRunner(fjm, flat_max_words=1 << 26)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s_, ln in r._segments:
        core.add_segment(s_, ln)
    for st, v in r._runs:
        core.set_words(st, v)
    _c, ops, _e, _l, _p = core.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)
    got = []
    for i in range(N):
        lo = core.get_word(base("out") + 4 * i + 1) >> VAL
        hi = core.get_word(base("out") + 4 * i + 3) >> VAL
        got.append((hi << 4) | lo)
    arr = [core.get_word(base("arr") + 2 * i + 1) >> VAL for i in range(N)]
    return ops, got, arr


ok = True
print("CORRECTNESS -- all %d values through the dispatch" % N)
_ops, got, arr = build(N)
bad = [(i, g, PLANT[i]) for i, g in enumerate(got) if g != PLANT[i]]
print("  values read back wrong : %d  %s" % (len(bad), "ok" if not bad else str(bad[:5])))
ok &= not bad
dirty = [(i, a, PLANT[i]) for i, a in enumerate(arr) if a != PLANT[i]]
print("  source cells disturbed : %d  %s" % (len(dirty), "ok" if not dirty else str(dirty[:5])))
ok &= not dirty

print("")
print("NEGATIVE CONTROL -- break one handler's undo-flip; the checker MUST reject")
try:
    _o, g2, a2 = build(N, break_handler=True)
    caught = g2 != PLANT or a2 != PLANT
except Exception as e:
    caught = True
    print("  (the broken build did not even run: %s)" % str(e)[:60])
print("  broken handler rejected: %s" % ("ok" if caught else "!! ACCEPTED -- the check is vacuous"))
ok &= caught

print("")
print("COST -- from a DIFFERENCE of two sizes")
for name, disp in (("crd.read_to (dispatch)", True), ("set+ptr_index+read_byte", False)):
    o1, _g, _a = build(64, dispatch=disp)
    o2, _g, _a = build(192, dispatch=disp)
    per = (o2 - o1) / 128.0
    print("  %-24s n=64 %10s   n=192 %10s   -> %7.1f ops/call"
          % (name, format(o1, ","), format(o2, ","), per))
print("")
print("constrd_probe: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
