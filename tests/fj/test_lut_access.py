"""M6 (F3) — fj-side LUT-access idioms reading the M5-generated dispatch tables, assembled + run.

read_sin / read_cos share one finesine table (#9): cos = sin((idx + count/4) mod count). Byte-exact
vs tables.py (R6 SSOT) on boundary AND wrap indices, call-twice (#8). Reciprocal is read via the
generic dispatch `.lookup`. Expected values come from tables.py — the same source the emitter used."""
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.tables import reciprocal_table, sine_table
from doomfj.lut_generator import generate_dispatch_table_fj, generate_trig_idioms_fj

N = 256            # 16^2 — small power-of-16 trig table for a fast run (real game N=4096)
FRAC = 16
RES_N = 8          # 32-bit entries
SINE = sine_table(N, FRAC, 4 * RES_N)
# boundary + wrap indices (cos adds N/4=64: 192->0, 255->63 wrap)
IDXS = [0, 1, 64, 127, 128, 191, 192, 255]


def _run(tmp_path, name, body, tables, expected: bytes):
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(tables) + "\n")
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [p.resolve()], b"", expected, memory_width=W,
        warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != expected"


def test_read_sin_byte_exact(tmp_path):
    body, data = [], []
    for k, idx in enumerate(IDXS):
        for _ in range(2):  # call twice (#8)
            body += [f"fs.read_sin r, a{k}", f"hex.print_as_digit {RES_N}, r, 0", "stl.output 10"]
        data.append(f"a{k}: hex.vec 2, {idx}")
    data.append(f"r: hex.vec {RES_N}")
    expected = "".join(f"{SINE[idx]:0{RES_N}x}\n{SINE[idx]:0{RES_N}x}\n" for idx in IDXS).encode()
    _run(tmp_path, "read_sin", body, data + [generate_trig_idioms_fj("fs", N, FRAC)], expected)


def test_read_cos_byte_exact_with_wrap(tmp_path):
    body, data = [], []
    for k, idx in enumerate(IDXS):
        for _ in range(2):  # call twice (#8) — also catches the ctmp scratch not being re-zeroed
            body += [f"fs.read_cos r, a{k}", f"hex.print_as_digit {RES_N}, r, 0", "stl.output 10"]
        data.append(f"a{k}: hex.vec 2, {idx}")
    data.append(f"r: hex.vec {RES_N}")
    expected = "".join(f"{SINE[(idx + N // 4) % N]:0{RES_N}x}\n{SINE[(idx + N // 4) % N]:0{RES_N}x}\n"
                       for idx in IDXS).encode()
    _run(tmp_path, "read_cos", body, data + [generate_trig_idioms_fj("fs", N, FRAC)], expected)


def test_read_reciprocal_byte_exact(tmp_path):
    # the reciprocal table read via the generic dispatch `.lookup` (read_reciprocal/read_scale idiom)
    count = 16
    recip = reciprocal_table(count, FRAC, 4 * RES_N)
    body, data = [], []
    for k in range(count):
        for _ in range(2):
            body += [f"rc.lookup r, a{k}", f"hex.print_as_digit {RES_N}, r, 0", "stl.output 10"]
        data.append(f"a{k}: hex.vec 1, {k}")
    data.append(f"r: hex.vec {RES_N}")
    expected = "".join(f"{v:0{RES_N}x}\n{v:0{RES_N}x}\n" for v in recip).encode()
    table = generate_dispatch_table_fj("rc", recip, index_nibbles=1, result_nibbles=RES_N,
                                       mode="per_result_nibble")
    _run(tmp_path, "read_reciprocal", body, data + [table], expected)
