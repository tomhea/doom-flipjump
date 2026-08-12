"""M14-0 spike, part 2 of 2: per-primitive I/O cost, measured by a k-sweep in a SMALL program.

For each candidate wire primitive the same body is emitted k = 1, 17, 33 times and the op counter
differenced, so `stl.startup_and_init_all` and the table inits cancel and what is left is the
MARGINAL cost of one more call.

⚠ SCALE CAVEAT. `@` (the wflip cost of a label) grows with the set bits of the label's ADDRESS, so a
small program understates every number here. `m14_0_insitu_digits.py` measures ONE of these
primitives (a decimal digit) inside a real ~12MB binary; the ratio of that to the small-program
digit measured here is the scale factor printed at the end, and it is what the other rows must be
multiplied by before they are compared against a ~23-45M op frame.

NEGATIVE CONTROLS (R9), all three must hold or the row is reported FAIL:
 1. LINEARITY -- the marginal cost from k=1->17 and from k=17->33 must agree within 10%. A body that
    did not actually repeat (e.g. a macro the assembler folded) breaks this. The residual drift
    inside that band is REPORTED, not hidden: it is `@` growing as the program grows, the same
    effect the scale caveat is about, and it runs 4-6% over a 32x body -- which is why the band is
    10% and not 2%.
 2. INPUT DRAINED -- every fed byte must have been consumed. A primitive that silently read nothing
    would otherwise look gloriously cheap.
 3. OUTPUT EXACT -- output primitives must have emitted exactly the expected bytes.

Usage:  python scratchpad/m14_0_wire_cost.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj

KS = (1, 17, 33)
EMIT_TABLE = generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)


def variants(k: int):
    """name -> (body lines, data lines, stdin bytes, expected output bytes, units per call)."""
    v = {}
    # ---- decimal input, the format the program uses today -------------------------------------
    v["dec_uint8  '1869'      (4 digits)"] = (
        ["hex.input_dec_uint 8, r8, bad"] * k, ["r8: hex.vec 8"], b"1869\n" * k, b"", 1)
    v["dec_uint8  '0000001869'(10 digits)"] = (
        ["hex.input_dec_uint 8, r8, bad"] * k, ["r8: hex.vec 8"], b"0000001869\n" * k, b"", 1)
    v["dec_int10  '1869'      (4 digits)"] = (
        ["hex.input_dec_int 10, r10, bad"] * k, ["r10: hex.vec 10"], b"1869\n" * k, b"", 1)
    v["dec_int10  '0000001869'(10 digits)"] = (
        ["hex.input_dec_int 10, r10, bad"] * k, ["r10: hex.vec 10"], b"0000001869\n" * k, b"", 1)
    # ---- raw binary input ----------------------------------------------------------------------
    v["bin_in 1 byte  (hex.input 1)"] = (
        ["hex.input 1, b2"] * k, ["b2: hex.vec 2"], b"\x5a" * k, b"", 1)
    v["bin_in 4 bytes (hex.input 4)"] = (
        ["hex.input 4, b8"] * k, ["b8: hex.vec 8"], b"\x5a\x1c\x03\xff" * k, b"", 4)
    # ---- output ---------------------------------------------------------------------------------
    v["out const byte (stl.output_char)"] = (
        ["stl.output_char 0x5a"] * k, [], b"", b"\x5a" * k, 1)
    v["out runtime byte (byte.emit)"] = (
        ["byte.emit v2"] * k, ["v2: hex.vec 2, 0x5a", EMIT_TABLE], b"", b"\x5a" * k, 1)
    v["out decimal (hex.print_dec_uint 8)"] = (
        ["hex.print_dec_uint 8, pv"] * k, ["pv: hex.vec 8, 1869"], b"", b"1869" * k, 1)
    return v


def run_one(tmp: Path, name: str, body, data, stdin: bytes, expect_out: bytes):
    prog = ("stl.startup_and_init_all\n" + "\n".join(body)
            + "\nstl.loop\nbad:\nstl.loop\n" + "\n".join(data) + "\n")
    src = tmp / (name + ".fj")
    src.write_text(prog, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(stdin)
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = io.get_output(allow_incomplete_output=True)
    return term.op_counter, len(io.remaining_input), got


def main():
    tmp = Path(tempfile.mkdtemp(prefix="m14_0_"))
    names = list(variants(1))
    rows = {}
    for i, name in enumerate(names):
        ops, drained, outs = {}, [], []
        for k in KS:
            body, data, stdin, expect, _units = variants(k)[name]
            o, left, got = run_one(tmp, f"v{i}_k{k}", body, data, stdin, expect)
            ops[k] = o
            drained.append(left == 0)
            outs.append(got == expect)
        units = variants(1)[name][4]
        m_lo = (ops[17] - ops[1]) / (16 * units)          # marginal cost per UNIT, low half
        m_hi = (ops[33] - ops[17]) / (16 * units)         # ... and high half
        drift = (m_hi - m_lo) / max(m_hi, m_lo, 1)
        linear = abs(drift) <= 0.10
        rows[name] = (m_hi, linear, all(drained), all(outs))
        flags = (f"drift {drift:+.1%}" if linear else "!!NONLINEAR") \
                + ("" if all(drained) else " !!INPUT-LEFT") \
                + ("" if all(outs) else " !!OUTPUT-WRONG")
        print(f"{name:38s} {m_hi:9,.1f} ops/unit   k1={ops[1]:,} k17={ops[17]:,} k33={ops[33]:,}"
              f"   [{flags}]", flush=True)

    # the scale factor: this program's decimal digit vs the same digit inside a real ~12MB binary
    d4 = rows["dec_int10  '1869'      (4 digits)"][0]
    d10 = rows["dec_int10  '0000001869'(10 digits)"][0]
    per_digit_small = (d10 - d4) / 6
    print(f"\nper decimal DIGIT here (dec_int10): {per_digit_small:,.0f} ops")
    print("per decimal DIGIT in a 12MB binary (m14_0_insitu_digits.py): 2,079 / 2,395 (n=10)")
    print(f"=> SCALE FACTOR small -> in-situ: x{2079 / per_digit_small:.2f} .. x{2395 / per_digit_small:.2f}")

    ok = all(lin and dr and ou for _m, lin, dr, ou in rows.values())
    print("\nPASS" if ok else "\nFAIL -- a control tripped; the numbers above are not trustworthy")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
