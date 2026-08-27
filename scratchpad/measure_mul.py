"""Compare, per the user's question: general hex.mul 7 (runtime a*b) vs hex.mul_const 7 (a*CONST, the
multiplicand baked) for realistic partition-delta constants, plus a dispatch-table lookup baseline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flipjump as fj
from doomfj.harness import W

FIXED = Path("src/fj/fixed_point.fj").resolve()


def run_ops(body_lines, n, tmp, data=()):
    main = "\n".join([
        "stl.startup_and_init_all",
        "hex.set 8, cnt, 0", f"hex.set 8, lim, {n}",
        "mloop:", "  hex.cmp 8, cnt, lim, mbody, mdone, mdone",
        "mbody:", *["  " + l for l in body_lines],
        "  hex.inc 8, cnt", "  ;mloop", "mdone:", "stl.loop",
        "cnt: hex.vec 8", "lim: hex.vec 8",
        "prod: hex.vec 8", "dvx: hex.vec 2, 17", "ai: hex.vec 4, 896",
        *data,
    ])
    p = tmp / "m.fj"; p.write_text(main, encoding="utf-8")
    out = tmp / "m.fjm"
    fj.assemble([FIXED, p], out, memory_width=W, print_time=False)
    return fj.run(out, print_time=False, print_termination=False).op_counter


def per_call(body, tmp, data=(), lo=200, hi=600):
    return (run_ops(body, hi, tmp, data) - run_ops(body, lo, tmp, data)) / (hi - lo)


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    print("general mul (runtime a*dvx):")
    print(f"  hex.mul 7,  prod, ai, dvx      : {per_call(['hex.mul 7, prod, ai, dvx'], tmp):8.0f}")
    print(f"  hex.mul 5,  prod, ai, dvx      : {per_call(['hex.mul 5, prod, ai, dvx'], tmp):8.0f}")
    print("mul_const (dvx * CONST, CONST baked = the partition delta a_i):")
    for c in (896, 1216, 833, 512, 64, 120):
        ops = per_call([f'hex.mul_const 5, prod, dvx, {c}'], tmp)
        sb = bin(c).count('1')
        print(f"  hex.mul_const 5, prod, dvx, {c:5d}  : {ops:8.0f}   ({sb} set bits)")
    print("references:")
    print(f"  hex.add 7, prod, ai            : {per_call(['hex.add 7, prod, ai'], tmp):8.0f}")
    print(f"  hex.shl_bit 7, prod            : {per_call(['hex.shl_bit 7, prod'], tmp):8.0f}")


if __name__ == "__main__":
    main()
