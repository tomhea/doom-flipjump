"""A0.2 / PJ-2 — is the M13-absmul identity ("multiply |viewx|, negate the product") still
bit-identical to the oracle now that the view position has a fraction?

THE CLAIM (scratchpad/cr2/findings/fj-projection.md, PJ-2): fj computes
`sgn = -(fixed_mul_lo(a, |viewx|))` while the oracle computes `fixed_mul(a, viewx, 8, 4)` on the
SIGNED value. With P = a*|viewx|:

    fj     = -floor(P / 2^16)          (negate AFTER truncating)
    oracle = -ceil (P / 2^16)          (truncate the already-negated 2^64 product)

equal iff P mod 2^16 == 0. The macro's own comment states the premise as PROVEN --

    "viewx/viewy are always map<<16, so the product's low 4 nibbles are zero ... (verified over
     401 viewpoints x 575 segs)"

-- and M14's player sim moves in 16.16, so `viewx = m<<16` is false from the player's second step.

⚠ R17 CAVEAT, taken from the finding and made into a control here: at a HALF-unit offset the
divergence only appears for segs whose coefficient `a` is ODD (P mod 2^16 = (a mod 2)*2^15). A
half-unit-only fixture is therefore partly vacuous -- so this probe runs BOTH parities at a half
unit AND a fraction (0x5555) that diverges for either.

TWO-SIDED CONTROLS (R9):
  1. integer viewx must AGREE in both forms -- the premise's valid domain. If it disagrees the
     probe is wrong, not the macro.
  2. POSITIVE viewx must agree in both forms -- no negation is involved, so a divergence there
     would mean the probe is measuring something else.
  3. even `a` at exactly a half unit must AGREE -- the vacuity the finding warns about, asserted
     rather than assumed.
  4. the SIGNED form (the proposed fix) must agree EVERYWHERE.
  5. the shipped abs/negate form must actually DIVERGE somewhere, or PJ-2 is refuted.

    python scratchpad/_pj2_probe.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from doomfj.fixedpoint import fixed_mul                                   # noqa: E402
from doomfj.harness import W                                              # noqa: E402

M32 = (1 << 32) - 1

# (label, a, viewx) -- `a` is a baked seg affine coefficient (a small signed integer), `viewx` a
# 16.16 position. The parity of `a` and the fraction of `viewx` are the two axes that matter.
def C(name, a, xi, frac):
    return (name, a, ((xi << 16) + frac) & M32)


CASES = [
    C("a odd  vx>0 int   ",  7,  100, 0x0000),      # control: integer, positive
    C("a odd  vx<0 int   ",  7, -100, 0x0000),      # control: integer, negative -> the premise
    C("a even vx<0 int   ",  8, -100, 0x0000),      # control
    C("a even vx<0 half  ",  8, -100, 0x8000),      # R17: must AGREE (P mod 2^16 == 0)
    C("a odd  vx<0 half  ",  7, -100, 0x8000),      # R17: must DIVERGE
    C("a odd  vx<0 0x5555",  7, -100, 0x5555),      # diverges for either parity
    C("a even vx<0 0x5555",  8, -100, 0x5555),      # diverges for either parity
    C("a odd  vx>0 0x5555",  7,  100, 0x5555),      # positive: no negation -> must agree
    C("a neg  vx<0 0x5555", -13, -100, 0x5555),     # negative coefficient too
    C("a neg  vx<0 half  ", -13, -100, 0x8000),     # odd |a| at a half unit
]


def main():
    body, data = [], []
    data.append("r1: hex.vec 8")
    data.append("r2: hex.vec 8")
    data.append("r3: hex.vec 8")
    for i, (_n, a, vx) in enumerate(CASES):
        vs = vx - (1 << 32) if vx & (1 << 31) else vx        # signed viewx
        vxa = abs(vs) & M32                                   # |viewx|, as fj's viewxa register
        data += [f"a{i}: hex.vec 8, {a & M32}",
                 f"vx{i}: hex.vec 8, {vx}",
                 f"vxa{i}: hex.vec 8, {vxa}"]
        # FORM 1 -- what ships: multiply the ABS, then negate iff viewx was negative. The sign flag
        # is a per-frame constant, so branching on it here is exactly what `viewxs` does at runtime.
        body.append(f"hex.fixed_mul_lo 8, 4, r1, a{i}, vxa{i}")
        if vs < 0:
            body.append("hex.neg 8, r1")
        # FORM 2 -- the proposed fix: multiply the SIGNED value, as the oracle does.
        body.append(f"hex.fixed_mul_lo 8, 4, r2, a{i}, vx{i}")
        # FORM 3 -- the fix AS IT WILL SHIP: same signed multiply, operands SWAPPED so the sparse
        # baked constant `a` is the SECOND operand (the ROW RULE -- cost is one schoolbook row per
        # nonzero nibble of the second operand). The row rule asserts this swap is bit-identical.
        # ⚠ THAT ASSERTION IS EXACTLY THE KIND THIS REPO HAS BEEN WRONG ABOUT, so it is MEASURED
        # here rather than assumed: control 6 requires form 3 == form 2 on every case.
        body.append(f"hex.fixed_mul_lo 8, 4, r3, vx{i}, a{i}")
        body += ["hex.print_as_digit 8, r1, 0", "stl.output 32",
                 "hex.print_as_digit 8, r2, 0", "stl.output 32",
                 "hex.print_as_digit 8, r3, 0", "stl.output 10"]

    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
            + "\n".join(data) + "\n")
    tmp = Path(tempfile.mkdtemp())
    p = tmp / "pj2.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp / "pj2.fjm"
    fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), p.resolve()],
                out, memory_width=W, warning_as_errors=True, print_time=False)
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    lines = [ln for ln in io.get_output().decode("ascii", "replace").split("\n") if ln.strip()]
    if len(lines) != len(CASES):
        print(f"!! expected {len(CASES)} lines, got {len(lines)} -- PROBE BROKEN")
        print(lines[:4])
        return 1

    print(f"{'case':<20} {'oracle':>10} {'abs/neg':>10} {'signed':>10} {'swapped':>10}   verdict")
    nd_abs = nd_sgn = nd_swp = 0
    ctl_int = ctl_pos = ctl_evenhalf = 0
    for (name, a, vx), ln in zip(CASES, lines):
        f1, f2, f3 = (int(t, 16) for t in ln.split())
        want = fixed_mul(a & M32, vx, 8, 4)
        d1, d2, d3 = f1 != want, f2 != want, f3 != f2
        nd_abs += d1
        nd_sgn += d2
        nd_swp += d3
        if "int " in name:
            ctl_int += d1 or d2
        if "vx>0" in name:
            ctl_pos += d1 or d2
        if "a even" in name and "half" in name:
            ctl_evenhalf += d1 or d2
        v = ("ABS/NEG DIFFERS (off by %+d)" % (f1 - want) if d1 else "agree")
        if d2:
            v += "  !! SIGNED DIFFERS TOO"
        if d3:
            v += "  !! OPERAND SWAP NOT BIT-IDENTICAL"
        print(f"{name:<20} {want:>10x} {f1:>10x} {f2:>10x} {f3:>10x}   {v}")

    print(f"\nabs/neg (shipped): {len(CASES)-nd_abs} agree, {nd_abs} DIFFER")
    print(f"signed  (the fix): {len(CASES)-nd_sgn} agree, {nd_sgn} DIFFER")
    print("\nCONTROLS (R9, two-sided):")
    print(f"  1. integer viewx agrees ..................... {'ok' if not ctl_int else 'FAIL'}")
    print(f"  2. positive viewx agrees .................... {'ok' if not ctl_pos else 'FAIL'}")
    print(f"  3. even `a` at a half unit agrees (R17) ..... "
          f"{'ok' if not ctl_evenhalf else 'FAIL'}")
    print(f"  4. the SIGNED form agrees everywhere ........ {'ok' if not nd_sgn else 'FAIL'}")
    print(f"  5. the shipped form diverges somewhere ...... "
          f"{'ok -- PJ-2 CONFIRMED' if nd_abs else 'no divergence -- PJ-2 REFUTED'}")
    print(f"  6. ROW-RULE operand swap is bit-identical ... "
          f"{'ok' if not nd_swp else 'FAIL -- DO NOT SWAP'}")
    good = not (ctl_int or ctl_pos or ctl_evenhalf or nd_sgn or nd_swp)
    print(f"\nprobe {'VALID' if good else 'INVALID -- do not quote it'}; "
          f"PJ-2 {'CONFIRMED' if (good and nd_abs) else ('REFUTED' if good else 'UNSETTLED')}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
