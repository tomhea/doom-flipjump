"""A0.2 / PJ-1 — does `wedge_bbox_plane` disagree with `bbox_wedge_miss` at a FRACTIONAL view
position, and does the proposed fix close it?

THE CLAIM (scratchpad/cr2/findings/fj-projection.md, PJ-1): `wedge_setup` builds the eye terms at
full 16.16 width (`weyx = viewy - viewx`), and `wedge_bbox_plane` then reads only their HIGH
4-nibble slice -- i.e. floor((viewy-viewx)/2^16). The oracle computes floor(viewy) - floor(viewx).
Those differ by 1 exactly when the fractions borrow (q=1, fy<fx) or carry (q=3, fx+fy>=1). Every
gate in the repo sits at a whole map unit, where fx=fy=0 and the two are identical -- so the gates
cannot see it. M14 made the player fractional.

⚠ THE COMMENT ON THE MACRO STATES THE DEAD PREMISE AS PROVEN ("corners are integer map units <<16,
so low halves are zero"), which is why this is settled by a probe and not by reading.

WHAT THIS RUNS. `wedge_setup` at a fractional viewx/viewy, then `wedge_bbox_plane` for all 8
half-planes against a DEGENERATE (point) box placed so the true Q is exactly -1, 0 or +1 -- the
only places a +-1 error can change the verdict. Each plane is evaluated TWICE per case:

  * "fj"      -- weyx/wexy straight from `wedge_setup`: floor AFTER combining. This is what ships,
                 and after the PJ-1 fix it is what the ORACLE now does too, so it must AGREE.
  * "peraxis" -- weyx/wexy rebuilt in the probe as floor(viewy)-floor(viewx). This was the ORACLE's
                 old rule. It must still DIVERGE, or this probe has lost its teeth.

⚠ THE ROLES SWAPPED WHEN THE FIX LANDED. Before it, "fj" diverged and "peraxis" agreed; the fix
moved the ORACLE (mapcompiler.bbox_wedge_miss) onto fj's rule rather than the reverse, because only
floor-after-combining is CONSERVATIVE -- its error vs the exact eye is frac(E) in [0,1) for all four
q, so a cull always implies the point is truly outside. Per-axis flooring gives q=3 an error of
fx+fy in [0,2), which can cull a box that is genuinely INSIDE. That inversion is the regression
test: if a later change puts the oracle back on the per-axis rule, control 3 fails.

R9 / TWO-SIDED CONTROLS, because a probe that only ever prints "differs" proves nothing:
  1. the INTEGER cases (fx=fy=0) must AGREE in both modes -- if they disagree, the probe is wrong,
     not the macro;
  2. the planes q=0 and q=2 must AGREE in every case -- they read wex/wey, whose high slice is
     floor() already, so a probe that flags those is over-reporting;
  3. the SHIPPED fj rule must agree with the oracle EVERYWHERE -- this is the fix;
  4. the per-axis rule must still DIVERGE somewhere, or the probe cannot see the bug class at all
     and its verdict means nothing.

    python scratchpad/_pj1_probe.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.mapcompiler import bbox_wedge_miss                            # noqa: E402

M32 = (1 << 32) - 1

# (label, viewx, viewy) in 16.16. `frac` notes are in units of 1/65536.
CASES = [
    # fx  fy      -> which planes the finding predicts diverge
    ("integer      ", (100 << 16),            (200 << 16)),             # none (the control)
    ("fy<fx        ", (100 << 16) | 0x8000,   (200 << 16) | 0x1000),    # q=1 (borrow)
    ("fx+fy>=1     ", (100 << 16) | 0x9000,   (200 << 16) | 0x9000),    # q=3 (carry)
    ("both         ", (100 << 16) | 0xC000,   (200 << 16) | 0x5000),    # q=1 and q=3
    ("neg vx, carry", (-50 << 16) + 0x4000,   (300 << 16) | 0xC000),    # q=3 only (fy>fx)
]
TARGETS = (-1, 0, 1)          # the true (raw) Q values where a +-1 error can flip the verdict


def corner(m, vx, vy, target):
    """A point box whose maximizing corner makes the RAW Q of plane m equal `target`.

    Degenerate (left==right, top==bottom) so the corner is the same one on both sides no matter
    which selection rule is applied -- this probes the ARITHMETIC, not the corner choice."""
    q = m & 3
    dx, dy = (0, target) if q in (0, 1) else (target, 0)
    return vx + dx, vy + dy      # integer map units


def build_program():
    body, data = [], []
    data.append("qa: hex.vec 1")
    data.append("na: hex.vec 1")
    data.append("qb: hex.vec 1")
    data.append("nb: hex.vec 1")
    for r in ("wex", "wey", "weyx", "wexy", "weyx2", "wexy2"):
        data.append(f"{r}: hex.vec 8")
    data.append("res: hex.vec 1")
    for v in range(4):
        data.append(f"cq{v}: hex.vec 1, {v}")
    data.append("cn0: hex.vec 1, 0")
    data.append("cn1: hex.vec 1, 1")

    for ci, (_name, vx, vy) in enumerate(CASES):
        data.append(f"vx{ci}: hex.vec 8, {vx & M32}")
        data.append(f"vy{ci}: hex.vec 8, {vy & M32}")
        data.append(f"va{ci}: hex.vec 8, 0")
        body.append(f"proj.wedge_setup qa, na, qb, nb, wex, wey, weyx, wexy, "
                    f"va{ci}, vx{ci}, vy{ci}")
        # THE FIX, in fj: the eye terms built from the INTEGER slices instead of sliced afterwards.
        body += [f"hex.zero 8, weyx2",
                 f"hex.mov 4, weyx2 + 4*dw, vy{ci} + 4*dw",
                 f"hex.sub 4, weyx2 + 4*dw, vx{ci} + 4*dw",
                 f"hex.zero 8, wexy2",
                 f"hex.mov 4, wexy2 + 4*dw, vx{ci} + 4*dw",
                 f"hex.add 4, wexy2 + 4*dw, vy{ci} + 4*dw"]
        for m in range(8):
            qv, nv = m & 3, 1 if 2 <= m <= 5 else 0
            for ti, t in enumerate(TARGETS):
                cx, cy = corner(m, vx >> 16, vy >> 16, t)
                bx, by = (cx << 16) & M32, (cy << 16) & M32
                for mode, (yx, xy) in (("a", ("weyx", "wexy")), ("f", ("weyx2", "wexy2"))):
                    tag = f"{ci}_{m}_{ti}{mode}"
                    data += [f"bl{tag}: hex.vec 8, {bx}", f"br{tag}: hex.vec 8, {bx}",
                             f"bt{tag}: hex.vec 8, {by}", f"bb{tag}: hex.vec 8, {by}"]
                    body += [f"proj.wedge_bbox_plane cq{qv}, cn{nv}, bl{tag}, bb{tag}, br{tag}, "
                             f"bt{tag}, wex, wey, {yx}, {xy}, in{tag}, out{tag}",
                             f"in{tag}:", f"hex.set 1, res, 1", f";pr{tag}",
                             f"out{tag}:", f"hex.set 1, res, 0",
                             f"pr{tag}:", f"hex.print_as_digit 1, res, 0"]
    return body, data


def main():
    body, data = build_program()
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
            + "\n".join(data) + "\n")
    tmp = Path(tempfile.mkdtemp())
    p = tmp / "pj1.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp / "pj1.fjm"
    fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(),
                 (ROOT / "src/fj/projection.fj").resolve(), p.resolve()],
                out, memory_width=W, warning_as_errors=True, print_time=False)
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    raw = io.get_output().decode("ascii", "replace")
    got = "".join(c for c in raw if c in "01")
    print(f"fj emitted {len(got)} verdicts\n")

    exp_len = len(CASES) * 8 * len(TARGETS) * 2
    if len(got) != exp_len:
        print(f"!! expected {exp_len} verdicts, got {len(got)} -- PROBE BROKEN")
        print(repr(raw[:400]))
        return 1

    k = 0
    stats = {"a": [0, 0], "f": [0, 0]}          # [agree, differ]
    intctl = {"a": [0, 0], "f": [0, 0]}
    q02 = {"a": [0, 0], "f": [0, 0]}
    print(f"{'case':<14} {'m':>2} {'q':>1} {'n':>1} {'Qtrue':>5}  oracle    fj  peraxis")
    for ci, (name, vx, vy) in enumerate(CASES):
        ovx, ovy = vx >> 16, vy >> 16           # arithmetic shift = floor, as the oracle does
        for m in range(8):
            for ti, t in enumerate(TARGETS):
                cx, cy = corner(m, ovx, ovy, t)
                box = (cy, cy, cx, cx)          # (top, bottom, left, right)
                o_in = not bbox_wedge_miss(m, box, ovx, ovy, vx, vy)
                v = {}
                for mode in ("a", "f"):
                    v[mode] = got[k] == "1"
                    k += 1
                    ok = v[mode] == o_in
                    stats[mode][0 if ok else 1] += 1
                    if ci == 0:
                        intctl[mode][0 if ok else 1] += 1
                    if (m & 3) in (0, 2):
                        q02[mode][0 if ok else 1] += 1
                flag = "" if v["a"] == o_in else "   <-- !! SHIPPED fj DIVERGES"
                if v["f"] != o_in:
                    flag += "   <-- per-axis diverges (expected)"
                print(f"{name:<14} {m:>2} {m & 3:>1} {1 if 2 <= m <= 5 else 0:>1} {t:>5}  "
                      f"{'in ' if o_in else 'out':>6}  "
                      f"{'in ' if v['a'] else 'out':>4}  {'in ' if v['f'] else 'out':>5}{flag}")

    print(f"\nfj (shipped, floor-after-combining): {stats['a'][0]} agree, {stats['a'][1]} DIFFER")
    print(f"per-axis (the oracle's OLD rule)  : {stats['f'][0]} agree, {stats['f'][1]} DIFFER")
    print("\nCONTROLS (R9, two-sided):")
    c1 = intctl["a"][1] == 0 and intctl["f"][1] == 0
    c2 = q02["a"][1] == 0 and q02["f"][1] == 0
    c3 = stats["a"][1] == 0
    c4 = stats["f"][1] > 0
    print(f"  1. integer cases agree in both modes ........ {'ok' if c1 else 'FAIL'} "
          f"(fj {intctl['a'][1]} differ, per-axis {intctl['f'][1]})")
    print(f"  2. q=0 / q=2 planes agree everywhere ........ {'ok' if c2 else 'FAIL'} "
          f"(fj {q02['a'][1]} differ, per-axis {q02['f'][1]})")
    print(f"  3. SHIPPED fj agrees with the oracle ........ "
          f"{'ok -- PJ-1 FIXED' if c3 else 'FAIL -- STILL BROKEN'}")
    print(f"  4. the per-axis rule still diverges ......... "
          f"{'ok -- the probe can still see the bug class' if c4 else 'FAIL -- probe has no teeth'}")
    good = c1 and c2
    print(f"\nprobe {'VALID' if good else 'INVALID -- do not quote it'}; "
          f"PJ-1 {'FIXED' if (good and c3 and c4) else 'NOT FIXED'}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
