"""P12 -- proj.wxr_axis_add, wall_x_range_m's affine back-face sum without the multiply for an AXIS coefficient: RUN in
fj, acc + fixed_mul(v, k) (mod 2^32) against the oracle's fixed_mul over k = 0, +1.0, -1.0 (the fast path) and
general unit-normal components (the multiply), v = view coordinates with and without a fraction, both signs, the
32-bit extremes. The NEGATIVE CONTROL runs a mutant whose -1.0 arm ADDS instead of subtracting: it must fail."""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul
from doomfj.harness import W
from doomfj.wall_renderer import hoisted_scratch_fj

PROJECTION_FJ = Path("src/fj/projection.fj")
FRAME_RENDER_FJ = Path("src/fj/frame_render.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
M = 0xFFFFFFFF

KS = [0, 0x10000, 0xFFFF0000,                      # the fast path: 0, +1.0, -1.0
      0xB505, (-0xB505) & M, 0x8000, (-0x8000) & M,  # general unit-normal components
      0xFFFF, (-0xFFFF) & M, 0x1, (-0x1) & M, 0x10, 0x100, 0x1000]
VS = [0, 0x10000, (-416 << 16) & M, (1056 << 16) | 0x8000, ((-3072 << 16) - 0x4321) & M, 0x7FFFFFFF, 0x80000000,
      0x12345678, 0xFFFFFFFF]
ACCS = [0, 0x3A5C0000, 0xFFFFFFFF]


def _cases():
    out = []
    for i, k in enumerate(KS):
        for j, v in enumerate(VS):
            out.append((ACCS[(i + j) % len(ACCS)], v, k))
    return out


def _run(tmp_path, src):
    p_src = tmp_path / "projection.fj"
    p_src.write_text(src, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    body, data, expected = [], [], b""
    for n, (acc, v, k) in enumerate(_cases()):
        body += [f"hex.mov 8, acc, acc{n}", f"proj.wxr_axis_add acc, v{n}, k{n}",
                 "hex.print_as_digit 8, acc, 0", "stl.output 10"]
        data += [f"acc{n}: hex.vec 8, {acc}", f"v{n}: hex.vec 8, {v}", f"k{n}: hex.vec 8, {k}"]
        expected += f"{(acc + fixed_mul(v, k, 8, 4)) & M:08x}\n".encode()
    data += ["acc: hex.vec 8"]
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n" + hoisted_scratch_fj()
    p = tmp_path / "axis.fj"
    p.write_text(prog, encoding="utf-8")
    return fj.assemble_and_run_test_output(
        [consts.resolve(), FIXED_POINT_FJ.resolve(), p_src.resolve(), FRAME_RENDER_FJ.resolve(), p.resolve()],
        b"", expected, memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)


def test_axis_add_is_fixed_mul(tmp_path):
    assert len(_cases()) == len(KS) * len(VS) >= 100
    assert _run(tmp_path, PROJECTION_FJ.read_text(encoding="utf-8")), "wxr_axis_add != acc + fixed_mul(v, k)"


def test_axis_add_negative_control(tmp_path):
    """the -1.0 arm mutated to ADD: the same harness must reject it (else it proves nothing about that arm)"""
    src = PROJECTION_FJ.read_text(encoding="utf-8")
    old = "      neg:\n        hex.sub 8, acc, v\n"
    assert src.count(old) == 1
    assert not _run(tmp_path, src.replace(old, "      neg:\n        hex.add 8, acc, v\n"))
