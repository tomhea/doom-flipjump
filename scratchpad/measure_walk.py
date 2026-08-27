"""Measure the per-node BSP side-test cost (the walk's hot math). Runs proj.point_on_side_leaf in a runtime
loop N times and N' times, subtracts op_counter -> ops per side test. Also measures a 10-nibble hex.mul alone
and the xor_by SET/CLEAR overhead, to attribute the cost."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flipjump as fj
from doomfj.config import Config
from doomfj.harness import W

PROJ = Path("src/fj/projection.fj").resolve()
FIXED = Path("src/fj/fixed_point.fj").resolve()


def run_ops(body_lines, n, tmp):
    """A program that runs `body` n times in a runtime loop; returns op_counter."""
    main = "\n".join([
        "stl.startup_and_init_all",
        "hex.set 10, vx, 0x123456789",
        "hex.set 10, vy, 0x0ABCDEF12",
        "hex.set 8, cnt, 0",
        f"hex.set 8, lim, {n}",
        "mloop:",
        "  hex.cmp 8, cnt, lim, mbody, mdone, mdone",
        "mbody:",
        *["  " + l for l in body_lines],
        "  hex.inc 8, cnt",
        "  ;mloop",
        "mdone:",
        "stl.loop",
        # the side-test leaf (called via fcall)
        "pos_leaf:",
        "proj.point_on_side_leaf side, vx, vy, cpx, cpy, cdx, cdy, pos_ret",
        "vx: hex.vec 10", "vy: hex.vec 10",
        "cpx: hex.vec 10, 0x111111111", "cpy: hex.vec 10, 0x222222222",
        "cdx: hex.vec 10, 0x000000040", "cdy: hex.vec 10, 0x0000A0000",
        "side: hex.vec 2", "pos_ret: ;0",
        "cnt: hex.vec 8", "lim: hex.vec 8",
        "prod: hex.vec 10", "ma: hex.vec 10, 0x123456789", "mb: hex.vec 10, 0x0ABCDEF12",
    ])
    p = tmp / "m.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp / "m.fjm"
    fj.assemble([FIXED, PROJ, p], out, memory_width=W, print_time=False)
    term = fj.run(out, print_time=False, print_termination=False)
    return term.op_counter


def per_call(body, tmp, lo=100, hi=300):
    a = run_ops(body, lo, tmp)
    b = run_ops(body, hi, tmp)
    return (b - a) / (hi - lo)


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    sidetest = ["stl.fcall pos_leaf, side_ret2"]   # one full side test (the leaf)
    # need a 2nd ret reg for the outer fcall
    # measure: side test (leaf), a lone 10-nibble mul, a 10-nibble sub
    side = per_call(["stl.fcall pos_leaf, pos_ret"], tmp)
    mul10 = per_call(["hex.mul 10, prod, ma, mb"], tmp)
    sub10 = per_call(["hex.sub 10, prod, ma"], tmp)
    mov10 = per_call(["hex.mov 10, prod, ma"], tmp)
    NODES = 681
    print(f"per side-test (point_on_side_leaf) : {side:9.0f} ops")
    print(f"  one hex.mul 10                   : {mul10:9.0f} ops")
    print(f"  one hex.sub 10                   : {sub10:9.0f} ops")
    print(f"  one hex.mov 10                   : {mov10:9.0f} ops")
    print(f"  (leaf has 2 mul + 2 sub + 2 mov + set + scmp)")
    print(f"\n{NODES} nodes x side-test          = {NODES*side/1e6:6.2f}M ops (just the side math)")


if __name__ == "__main__":
    main()
