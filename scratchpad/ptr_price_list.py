"""A MEASURED ops/call price list for every POINTER primitive the program uses,
plus the CONSTANT-ADDRESS alternative where one exists or can be written.

WHY. M1 replaced `hex.zero_ptr` (clears a byte cell at a RUNTIME address) with `m1.zerobyte`
(clears a byte cell at a CONSTANT address). Almost the whole bill of the pointer form is
`set_flip_and_jump_pointers` -- copying an 8-nibble address into the stl's to_flip/to_jump
registers so the machine can reach a cell it only knows at runtime. When the address is known at
EMIT time none of that has to happen: the address is baked straight into the ops. This script
prices that trade for EVERY pointer primitive, so an optimisation search has real numbers.

METHOD (and why it is not a single run).
  * Every cost is a DIFFERENCE of two program sizes: the same program is emitted with n1 and n2
    repetitions of the body under test and nothing else changes, so startup, the byte PLANTS, the
    pointer setup and the tail cannot be smuggled into the per-call figure.
  * Four sizes are built per primitive (32/96/160/224 reps) and the three consecutive slopes are
    reported as min..max. A primitive whose slopes disagree is DATA-DEPENDENT, not noisy -- the fj
    interpreter is deterministic, so re-running a fixed program cannot produce a spread.
  * The body is UNROLLED rather than run in a runtime loop, because the constant-address variants
    need a DIFFERENT constant per repetition -- a runtime loop cannot express them. Unrolling
    isolates the body strictly better than a loop (no counter/compare in the delta at all).

CONTROLS (R9). A number without a control is worthless here.
  V. VACUITY -- after every measured run the memory is read back and the primitive must have DONE
     what it claims: reads leave the last byte in the destination register, writes leave 0x5a in
     exactly the cells they should and leave the next planted cell untouched, clears leave 0, and
     every pointer op leaves its register at the arithmetically expected address. Programs whose
     body was REMOVED are also run and must show the un-acted-on state -- that is what proves the
     plant is real. (An earlier measurement in this repo was vacuous because `hex.xor_by` CLAMPS to
     a nibble, so the byte under test was never planted at all. The plants here are raw `wflip`s.)
  N. NEGATIVE CONTROL -- `--selftest` mutates the constant-address macros (drops the high-nibble
     exact_xor from the write; drops the jump INTO the cell from the read) and REQUIRES the
     checkers to reject them. A checker that cannot fail is not evidence.

DOMAIN FACT the harness depends on: in an ARRAY a byte is ONE cell holding all 8 bits at
dbit..dbit+7; in a REGISTER (hex.read_byte's dst) it is TWO cells. A nibble op on an array byte
cell CORRUPTS it. So array cells are planted and read back as whole 8-bit words, and only register
bytes are treated as two nibbles.

    python scratchpad/ptr_price_list.py             # the price list + the saving upper bound
    python scratchpad/ptr_price_list.py --selftest  # the R9 negative control
    python scratchpad/ptr_price_list.py --addrtest  # is the pointer price ADDRESS-dependent?
    python scratchpad/ptr_price_list.py --record    # decompose the 5-byte-record composite

CAVEAT the harness itself measured: a pointer primitive's price is CONTEXT-dependent, because
`set_flip_and_jump_pointers` and `ptr_inc` both do per-nibble work on the concrete address.
--addrtest moves the array and sees +0/-4.0% on read_byte_and_inc; --record finds the marginal
read inside a 5-byte record is 906 ops against 781 walking a long table. So read the pointer
column as +/-15%, and the const-address column (which touches no address at all) as +/-5%.
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

DW = 2 * W                       # bits per fj op / per hex cell
VAL = W.bit_length()             # a hex cell's word holds value*DW; DW == 1<<VAL
NCELL = 240                      # planted byte cells in the array
SIZES = (32, 96, 160, 224)       # rep counts; consecutive pairs give the slope spread


# ---------------------------------------------------------------------------------------------
# The constant-address macros. `zerobyte` is src/fj/m1_reset.fj verbatim; `readbyte`/`writebyte`
# are the same technique extended to the other two byte operations. They do NOT exist in src/ --
# they are written here so the alternative can be MEASURED rather than guessed.
# ---------------------------------------------------------------------------------------------
def macros(break_write=False, break_read=False):
    lo = "        hex.exact_xor c+dbit+3, c+dbit+2, c+dbit+1, c+dbit+0, hex.pointers.read_byte"
    hi = "        hex.exact_xor c+dbit+7, c+dbit+6, c+dbit+5, c+dbit+4, hex.pointers.read_byte+dw"
    # the byte-table round trip: aim the stl's 256-entry read_ptr_byte_table (pinned at op 256) at
    # our own return label, mark the cell with bit dbit+8 so its jump word becomes (v+256)*dw ==
    # table entry v, jump into it, then undo both flips.
    trip = [
        "        hex.zero 2, hex.pointers.read_byte",
        "        wflip hex.pointers.ret_after_read_byte+w, back",
        "        c+dbit+8;" if break_read else "        c+dbit+8; c",
        "      back:",
        "        wflip hex.pointers.ret_after_read_byte+w, back",
        "        c+dbit+8;",
    ]
    hdr = "@ back < hex.pointers.read_byte, hex.pointers.ret_after_read_byte {"
    out = [
        "ns m1 {",
        # clear the byte cell at CONSTANT address c   (src/fj/m1_reset.fj)
        "    def zerobyte c " + hdr, *trip, lo, hi, "    }",
        # read the byte at CONSTANT address c, leaving it in hex.pointers.read_byte (no copy)
        "    def readbyte_reg c " + hdr, *trip, "    }",
        # read the byte at CONSTANT address c into the hex[:2] register dst
        "    def readbyte dst, c " + hdr, *trip,
        "        hex.mov 2, dst, hex.pointers.read_byte", "    }",
        # store the hex[:2] register src into the byte cell at CONSTANT address c:
        # read v, make read_byte = v^src, xor that onto c  ->  c = v ^ v ^ src = src
        "    def writebyte c, src " + hdr, *trip,
        "        hex.xor 2, hex.pointers.read_byte, src", lo,
    ]
    if not break_write:
        out.append(hi)
    out += ["    }", "}"]
    return out


# ---------------------------------------------------------------------------------------------
# program construction + run
# ---------------------------------------------------------------------------------------------
PLANT = [(i * 167 + 13) & 0xFF for i in range(NCELL)]     # 167 is odd -> a permutation of 0..255
FIXV = 0x5A                                               # popcount 4 == the mean over 0..255

DATA = [
    "arr: hex.vec %d" % (NCELL + 4),        # the byte ARRAY: 1 cell per byte
    "fxa: hex.vec 1",                       # a single fixed byte cell (planted with FIXV)
    "fxg: hex.vec 1",                       # its guard
    "gp:  hex.vec 8", "gp2: hex.vec 8", "pfx: hex.vec 8", "dstp: hex.vec 8",
    "idxv: hex.vec 8", "dstb: hex.vec 2", "srcb: hex.vec 2",
]
SETUP = [
    "hex.set 8, gp, arr", "hex.set 8, gp2, arr", "hex.set 8, pfx, fxa",
    "hex.set 8, idxv, 3", "hex.set 2, srcb, 0x%x" % FIXV,
]


def build_and_run(body_lines, mac, pad_cells=0):
    lines = list(mac) + ["stl.startup_and_init_all"]
    for i, v in enumerate(PLANT):                       # raw wflip: no nibble clamping (see header)
        if v:
            lines.append("wflip arr + %d*dw + w, %d*dw" % (i, v))
    lines.append("wflip fxa + w, %d*dw" % FIXV)
    tail = (["padx: hex.vec %d" % pad_cells] if pad_cells else []) + DATA
    lines += SETUP + list(body_lines) + ["stl.loop"] + tail
    tmp = Path(tempfile.mkdtemp(prefix="ptrprice_"))
    src = tmp / "p.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out, dbg = tmp / "p.fjm", tmp / "p.fjd"
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False, debugging_file_path=dbg)
    labels = load_debugging_labels(dbg)

    def addr(name):
        return min(v for k, v in labels.items() if k == name or k.endswith(":" + name))

    r = FjmRunner(out, flat_max_words=1 << 24)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, ln in r._segments:
        core.add_segment(s, ln)
    for st, vals in r._runs:
        core.set_words(st, vals)
    _c, ops, _e, _l, _p = core.run(lambda: 0, lambda _b: None, IOReadOnEOF, last_ops_length=0)

    def cell(name, i=0):                                 # the raw value of one hex / byte cell
        return core.get_word(addr(name) // W + 2 * i + 1) >> VAL

    def reg(name, n):                                    # an n-cell hex register, low nibble first
        return sum(cell(name, i) << (4 * i) for i in range(n))

    return ops, cell, reg, addr


# ---------------------------------------------------------------------------------------------
# checks: each returns (ok, text). `n` is the rep count that was actually run.
# ---------------------------------------------------------------------------------------------
def chk_read(n, cell, reg, addr):
    want, got = PLANT[n - 1], reg("dstb", 2)
    return got == want, "dstb=%#04x want arr[%d]=%#04x" % (got, n - 1, want)


def chk_read_fixed(n, cell, reg, addr):
    got = reg("dstb", 2)
    return got == FIXV, "dstb=%#04x want fxa=%#04x" % (got, FIXV)


def chk_read_reg(n, cell, reg, addr):
    want, got = PLANT[n - 1], reg("hex.pointers.read_byte", 2)
    return got == want, "read_byte=%#04x want arr[%d]=%#04x" % (got, n - 1, want)


def chk_write_walk(n, cell, reg, addr):
    bad = [i for i in range(n) if cell("arr", i) != FIXV]
    tail = cell("arr", n)
    return (not bad) and tail == PLANT[n], \
        "arr[0..%d)==%#04x (%d wrong); arr[%d]=%#04x want planted %#04x" % (
            n, FIXV, len(bad), n, tail, PLANT[n])


def chk_write_fixed(n, cell, reg, addr):
    return cell("fxa") == FIXV and cell("fxg") == 0, \
        "fxa=%#04x want %#04x; guard fxg=%#04x want 0" % (cell("fxa"), FIXV, cell("fxg"))


def chk_zero_walk(n, cell, reg, addr):
    bad = [i for i in range(n) if cell("arr", i) != 0]
    tail = cell("arr", n)
    return (not bad) and tail == PLANT[n], \
        "arr[0..%d)==0 (%d wrong); arr[%d]=%#04x want planted %#04x" % (
            n, len(bad), n, tail, PLANT[n])


def _ptr_chk(name, step):
    def f(n, cell, reg, addr):
        want = (addr("arr") + n * step * DW) & 0xFFFFFFFF
        got = reg(name, 8)
        return got == want, "%s=%#x want arr%+d*dw=%#x" % (name, got, n * step, want)
    return f


def chk_index(n, cell, reg, addr):
    want = (addr("arr") + 3 * DW) & 0xFFFFFFFF
    got = reg("dstp", 8)
    return got == want, "dstp=%#x want arr+3*dw=%#x" % (got, want)


def chk_dstp(val):
    def f(n, cell, reg, addr):
        got = reg("dstp", 8)
        return got == val, "dstp=%#x want %#x" % (got, val)
    return f


def chk_dstb(val):
    def f(n, cell, reg, addr):
        got = reg("dstb", 2)
        return got == val, "dstb=%#x want %#x" % (got, val)
    return f


def chk_rec(n, cell, reg, addr):
    """the 5-byte record read: the register must hold the LAST byte of the record."""
    want, got = PLANT[4], reg("dstb", 2)
    return got == want, "dstb=%#04x want arr[4]=%#04x" % (got, want)


def chk_xor(name, ncells, val):
    def f(n, cell, reg, addr):
        want = 0 if n % 2 == 0 else val
        got = reg(name, ncells)
        return got == want, "%s=%#x after %d xors, want %#x" % (name, got, n, want)
    return f


# ---------------------------------------------------------------------------------------------
# the test table:  (label, body(i) -> lines, check_after_run, check_with_body_REMOVED)
# ---------------------------------------------------------------------------------------------
A = "arr + %d*dw"


def tests():
    return [
        # ---- POINTER primitives (address known only at RUNTIME) ---------------------------
        ("hex.read_byte_and_inc dst,ptr",
         lambda i: ["hex.read_byte_and_inc dstb, gp"], chk_read, chk_dstb(0)),
        ("hex.read_byte dst,ptr",
         lambda i: ["hex.read_byte dstb, pfx"], chk_read_fixed, chk_dstb(0)),
        ("hex.write_byte_and_inc ptr,src",
         lambda i: ["hex.write_byte_and_inc gp2, srcb"], chk_write_walk, None),
        ("hex.write_byte ptr,src",
         lambda i: ["hex.write_byte pfx, srcb"], chk_write_fixed, None),
        ("hex.zero_ptr ptr + hex.ptr_inc",
         lambda i: ["hex.zero_ptr gp", "hex.ptr_inc gp"], chk_zero_walk, None),
        ("hex.ptr_inc ptr",
         lambda i: ["hex.ptr_inc gp"], _ptr_chk("gp", 1), _ptr_chk("gp", 0)),
        ("hex.ptr_add ptr,1",
         lambda i: ["hex.ptr_add gp, 1"], _ptr_chk("gp", 1), _ptr_chk("gp", 0)),
        ("hex.ptr_add ptr,11",
         lambda i: ["hex.ptr_add gp, 11"], _ptr_chk("gp", 11), _ptr_chk("gp", 0)),
        ("hex.ptr_sub ptr,1",
         lambda i: ["hex.ptr_sub gp, 1"], _ptr_chk("gp", -1), _ptr_chk("gp", 0)),
        ("hex.ptr_index dst,ptr,idx",
         lambda i: ["hex.ptr_index dstp, gp, idxv"], chk_index, chk_dstp(0)),
        # ---- CONSTANT-ADDRESS twins --------------------------------------------------------
        ("m1.zerobyte c",
         lambda i: ["m1.zerobyte " + A % i], chk_zero_walk, None),
        ("m1.readbyte_reg c",
         lambda i: ["m1.readbyte_reg " + A % i], chk_read_reg, None),
        ("m1.readbyte dst,c",
         lambda i: ["m1.readbyte dstb, " + A % i], chk_read, chk_dstb(0)),
        ("m1.writebyte c,src",
         lambda i: ["m1.writebyte %s, srcb" % (A % i)], chk_write_walk, None),
        # ---- the constant-address ops already in the stl, for scale ------------------------
        ("hex.zero 2 (const addr)",
         lambda i: ["hex.zero 2, dstb"], chk_dstb(0), None),
        ("hex.zero 8 (const addr)",
         lambda i: ["hex.zero 8, dstp"], chk_dstp(0), None),
        ("hex.set 2 (const addr)",
         lambda i: ["hex.set 2, dstb, 0x%x" % FIXV], chk_dstb(FIXV), chk_dstb(0)),
        ("hex.set 8 (const addr)",
         lambda i: ["hex.set 8, dstp, 0x12345678"], chk_dstp(0x12345678), chk_dstp(0)),
        ("hex.xor_by 2 (const addr)",
         lambda i: ["hex.xor_by 2, dstb, 0x%x" % FIXV], chk_xor("dstb", 2, FIXV), chk_dstb(0)),
        ("hex.xor_by 8 (const addr)",
         lambda i: ["hex.xor_by 8, dstp, 0x12345678"],
         chk_xor("dstp", 8, 0x12345678), chk_dstp(0)),
        # ---- a REALISTIC composite: read a 5-byte record out of a table, both ways ---------
        ("RECORD ptr: set + 5x read&inc",
         lambda i: ["hex.set 8, gp, arr"]
                   + ["hex.read_byte_and_inc dstb, gp"] * 5,
         chk_rec, chk_dstb(0)),
        ("RECORD const: 5x m1.readbyte",
         lambda i: ["m1.readbyte dstb, " + A % j for j in range(5)],
         chk_rec, chk_dstb(0)),
    ]


def measure(body, check, mac):
    """Cost is ALWAYS a difference of two sizes; four sizes give three independent slopes."""
    ops, ok, note = {}, True, "-"
    for n in SIZES:
        lines = []
        for i in range(n):
            lines += body(i)
        o, cell, reg, addr = build_and_run(lines, mac)
        ops[n] = o
        if n == SIZES[-1] and check is not None:
            ok, note = check(n, cell, reg, addr)
    slopes = [(ops[b] - ops[a]) / (b - a) for a, b in zip(SIZES, SIZES[1:])]
    return slopes, ok, note, ops


def main():
    mac = macros()
    print("harness: W=%d  dw=%d  %d planted byte cells  rep sizes=%s" % (W, DW, NCELL, list(SIZES)))
    win = PLANT[SIZES[0]:SIZES[-1]]
    print("plant (i*167+13)&0xff -- mean popcount over the measured window = %.2f "
          "(mean over all of 0..255 = 4.00)" % (sum(bin(v).count("1") for v in win) / len(win)))
    print("cost = (ops(n2)-ops(n1))/(n2-n1) over consecutive sizes; min..max is the DATA spread.")
    print("")
    print("%-32s %9s %9s %9s   %-7s %s"
          % ("primitive", "ops/call", "min", "max", "vacuity", "evidence"))
    print("-" * 130)
    res, allok = {}, True
    for label, body, check, _rm in tests():
        slopes, ok, note, _ops = measure(body, check, mac)
        mid = sum(slopes) / len(slopes)
        res[label] = (mid, min(slopes), max(slopes), ok)
        allok &= ok
        print("%-32s %9.1f %9.1f %9.1f   %-7s %s"
              % (label, mid, min(slopes), max(slopes), "OK" if ok else "FAIL", note))

    # zero_ptr is measured together with the ptr_inc that walks it; subtract the measured inc.
    zp = res["hex.zero_ptr ptr + hex.ptr_inc"][0] - res["hex.ptr_inc ptr"][0]
    print("")
    print("derived: hex.zero_ptr alone = %.1f - %.1f = %.1f ops/call"
          % (res["hex.zero_ptr ptr + hex.ptr_inc"][0], res["hex.ptr_inc ptr"][0], zp))
    res["hex.zero_ptr ptr"] = (zp, zp, zp, True)

    # ---- where the pointer money actually goes ------------------------------------------------
    print("")
    print("DERIVED (all from the measured numbers above)")
    print("  the ADDRESS-PLUMBING tax on a byte read  = read_byte %.1f - m1.readbyte %.1f = %.1f"
          % (res["hex.read_byte dst,ptr"][0], res["m1.readbyte dst,c"][0],
             res["hex.read_byte dst,ptr"][0] - res["m1.readbyte dst,c"][0]))
    print("  the ADDRESS-PLUMBING tax on a byte write = write_byte %.1f - m1.writebyte %.1f = %.1f"
          % (res["hex.write_byte ptr,src"][0], res["m1.writebyte c,src"][0],
             res["hex.write_byte ptr,src"][0] - res["m1.writebyte c,src"][0]))
    print("  cross-check: read_byte_and_inc %.1f - ptr_inc %.1f = %.1f vs read_byte measured %.1f"
          % (res["hex.read_byte_and_inc dst,ptr"][0], res["hex.ptr_inc ptr"][0],
             res["hex.read_byte_and_inc dst,ptr"][0] - res["hex.ptr_inc ptr"][0],
             res["hex.read_byte dst,ptr"][0]))
    print("  the 5-byte RECORD read: pointer %.1f -> const %.1f  (%.2fx, %.1f ops saved)"
          % (res["RECORD ptr: set + 5x read&inc"][0], res["RECORD const: 5x m1.readbyte"][0],
             res["RECORD ptr: set + 5x read&inc"][0] / res["RECORD const: 5x m1.readbyte"][0],
             res["RECORD ptr: set + 5x read&inc"][0] - res["RECORD const: 5x m1.readbyte"][0]))

    print("")
    print("CONTROL V2 -- with the BODY REMOVED the plant+setup alone must NOT produce the result")
    for label, body, check, rm in tests():
        if rm is None:
            continue
        _o, cell, reg, addr = build_and_run([], mac)
        ok, note = rm(SIZES[-1], cell, reg, addr)
        allok &= ok
        print("   %-32s %-7s %s" % (label, "OK" if ok else "FAIL", note))

    _o, cell, reg, addr = build_and_run([], mac)
    plant_ok = all(cell("arr", i) == PLANT[i] for i in range(NCELL)) and cell("fxa") == FIXV
    allok &= plant_ok
    print("   %-32s %-7s arr[0:6]=%s want %s, fxa=%#04x"
          % ("the PLANT is real (raw wflip)", "OK" if plant_ok else "FAIL",
             [cell("arr", i) for i in range(6)], PLANT[:6], cell("fxa")))

    # ---- the saving table -------------------------------------------------------------------
    sites = [
        ("hex.read_byte_and_inc dst,ptr", 88, "m1.readbyte dst,c"),
        ("hex.ptr_index dst,ptr,idx", 44, None),
        ("hex.ptr_add ptr,1", 43, "ELIMINATED"),
        ("hex.write_byte_and_inc ptr,src", 35, "m1.writebyte c,src"),
        ("hex.read_byte dst,ptr", 32, "m1.readbyte dst,c"),
        ("hex.write_byte ptr,src", 14, "m1.writebyte c,src"),
        ("hex.ptr_sub ptr,1", 12, "ELIMINATED"),
        ("hex.zero_ptr ptr", 2, "m1.zerobyte c"),
    ]
    print("")
    print("UPPER BOUND on the saving if EVERY call site could be const-addressed")
    print("(it cannot -- many addresses are genuinely runtime; this is a ceiling, not a forecast)")
    print("%-32s %6s %9s %9s %11s %14s"
          % ("primitive", "sites", "ops/call", "alt", "saved/call", "UPPER BOUND"))
    print("-" * 90)
    tot = 0.0
    for k, nsite, alt in sites:
        cost = res[k][0]
        if alt is None:
            print("%-32s %6d %9.1f %9s %11s %14s" % (k, nsite, cost, "n/a", "n/a", "n/a"))
            continue
        acost = 0.0 if alt == "ELIMINATED" else res[alt][0]
        sav = cost - acost
        tot += sav * nsite
        print("%-32s %6d %9.1f %9.1f %11.1f %14s"
              % (k, nsite, cost, acost, sav, format(int(sav * nsite), ",")))
    print("%-32s %6s %9s %9s %11s %14s"
          % ("TOTAL (one pass over all sites)", "", "", "", "", format(int(tot), ",")))
    print("")
    print("ALL CONTROLS PASS" if allok
          else "!! A CONTROL FAILED -- the numbers above are NOT evidence")
    return res, allok


def selftest():
    """R9 negative control: mutate the const-address macros; the checkers MUST reject them."""
    print("NEGATIVE CONTROL -- a checker that cannot fail is not evidence.")
    ok = True
    wb = ["m1.writebyte arr + %d*dw, srcb" % i for i in range(16)]
    rb = ["m1.readbyte dstb, arr + %d*dw" % i for i in range(16)]

    _o, cell, reg, addr = build_and_run(wb, macros(break_write=True))
    good, note = chk_write_walk(16, cell, reg, addr)
    print("  writebyte, HIGH-nibble exact_xor REMOVED -> %s   %s"
          % ("PASSED (BAD!)" if good else "rejected (good)", note))
    ok &= not good

    _o, cell, reg, addr = build_and_run(rb, macros(break_read=True))
    good, note = chk_read(16, cell, reg, addr)
    print("  readbyte, jump INTO the cell REMOVED     -> %s   %s"
          % ("PASSED (BAD!)" if good else "rejected (good)", note))
    ok &= not good

    _o, cell, reg, addr = build_and_run(wb, macros())
    good, note = chk_write_walk(16, cell, reg, addr)
    print("  the UNMUTATED writebyte                  -> %s   %s"
          % ("passed (good)" if good else "REJECTED (BAD!)", note))
    ok &= good
    _o, cell, reg, addr = build_and_run(rb, macros())
    good, note = chk_read(16, cell, reg, addr)
    print("  the UNMUTATED readbyte                   -> %s   %s"
          % ("passed (good)" if good else "REJECTED (BAD!)", note))
    ok &= good

    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return ok


def addrtest():
    """Is the pointer price ADDRESS-dependent?  set_flip_and_jump_pointers xors the 8 nibbles of
    the address, so a cell at a different address should cost a different amount. Shift the array
    by inserting dead cells in front of it and re-price the SAME primitive."""
    print("ADDRESS-DEPENDENCE -- the same primitive, the same data, a different array ADDRESS.")
    print("%12s %12s %10s   %s" % ("pad cells", "arr address", "ops/call", "vacuity"))
    mac = macros()
    base = None
    for pad in (0, 4001, 40001, 400001):
        ops = {}
        for n in (32, 160):
            lines = ["hex.read_byte_and_inc dstb, gp"] * n
            o, cell, reg, addr = build_and_run(lines, mac, pad_cells=pad)
            ops[n] = o
            a = addr("arr")
        per = (ops[160] - ops[32]) / (160 - 32)
        ok, note = chk_read(160, cell, reg, addr)
        base = per if base is None else base
        print("%12d %12s %10.1f   %-6s %s  (%+.1f%% vs pad=0)"
              % (pad, hex(a), per, "OK" if ok else "FAIL", note, 100.0 * (per - base) / base))
    return True


def recordtest():
    """Decompose the 5-byte-record read: is the composite really set8 + 5*read_byte_and_inc?
    Vary K (reads per record) and take the slope in K as well as the slope in reps."""
    print("RECORD DECOMPOSITION -- cost of `hex.set 8, gp, arr` + K x read_byte_and_inc")
    mac = macros()
    per = {}
    for K in (0, 1, 3, 5):
        ops = {}
        for n in (32, 160):
            body = ["hex.set 8, gp, arr"] + ["hex.read_byte_and_inc dstb, gp"] * K
            o, cell, reg, addr = build_and_run(body * n, mac)
            ops[n] = o
        per[K] = (ops[160] - ops[32]) / (160 - 32)
        if K == 0:
            want = addr("arr") & 0xFFFFFFFF
            ok, note = reg("gp", 8) == want, "gp=%#x want arr=%#x" % (reg("gp", 8), want)
        else:
            ok = reg("dstb", 2) == PLANT[K - 1]
            note = "dstb=%#04x want arr[%d]=%#04x" % (reg("dstb", 2), K - 1, PLANT[K - 1])
        print("   K=%d  %9.1f ops/record   %-6s %s" % (K, per[K], "OK" if ok else "FAIL", note))
    m = (per[5] - per[1]) / 4.0
    print("   hex.set 8 alone (K=0)                = %.1f ops" % per[0])
    print("   marginal read (slope in K)           = (%.1f - %.1f)/4 = %.1f ops"
          % (per[5], per[1], m))
    print("   1st read after the set (K=1 - K=0)   = %.1f - %.1f = %.1f"
          % (per[1], per[0], per[1] - per[0]))
    return True


if __name__ == "__main__":
    if "--record" in sys.argv:
        sys.exit(0 if recordtest() else 1)
    if "--addrtest" in sys.argv:
        sys.exit(0 if addrtest() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    _r, _ok = main()
    sys.exit(0 if _ok else 1)
