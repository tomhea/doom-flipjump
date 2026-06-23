"""M12m+ (F5) — the runtime projection kernels in FlipJump (src/fj/projection.fj), each byte-exact vs the
H5 oracle (reference_model). proj.slope_div is R_PointToAngle's SlopeDiv: the tantoangle index for a
slope num/den. Driven over a spread of 16.16 magnitudes (small den / normal / clamp / boundary) twice
each (R5 #8), compared to ReferenceModel._slope_div — so the fj angle math and the oracle agree (D12)."""
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.reference_model import ReferenceModel

PROJECTION_FJ = Path("src/fj/projection.fj")


def _run(tmp_path, name, body, data, expected: bytes):
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != oracle"


# (num, den) 16.16 magnitudes: den<512 sentinel; den==0; slope<1; slope==1 (ANG45 clamp); slope>1 clamp;
# den exactly 512; num==0; a mid value.
SLOPE_CASES = [
    (0x10000, 0x100),     # den 256 < 512 -> SLOPERANGE
    (0x50000, 0x0),       # den 0 < 512 -> SLOPERANGE (no divide-by-zero)
    (0x10000, 0x20000),   # slope 0.5 -> 1024
    (0x20000, 0x20000),   # slope 1.0 -> 2048 (ANG45, exactly at clamp)
    (0x30000, 0x10000),   # slope 3.0 -> clamp to 2048
    (0x10000, 0x200),     # den exactly 512 -> compute
    (0x8000,  0x40000),   # slope 0.125 -> 256
    (0x0,     0x10000),   # num 0 -> 0
]


def test_slope_div_byte_exact_vs_oracle(tmp_path):
    body, data = [], []
    for k, (num, den) in enumerate(SLOPE_CASES):
        for _ in range(2):   # call twice per case (R5 #8): catches scratch/result-reg cleanup bugs
            body += [f"proj.slope_div d, n{k}, m{k}", "hex.print_as_digit 3, d, 0", "stl.output 10"]
        data += [f"n{k}: hex.vec 8, {num}", f"m{k}: hex.vec 8, {den}"]
    data.append("d: hex.vec 3")
    expected = b"".join(f"{ReferenceModel._slope_div(num, den):03x}\n".encode() * 2
                        for num, den in SLOPE_CASES)
    _run(tmp_path, "slope_div", body, data, expected)
