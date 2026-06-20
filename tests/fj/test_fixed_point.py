"""fj<->host parity for src/fj/fixed_point.fj (F2).

For each op a single fj program runs all cases and prints the results; the expected bytes are
computed by the host mirror (src/doomfj/fixedpoint.py). Byte-exact equality proves the kept PR #1
macros match the host math bit-for-bit (M2 exit / R6). read_table is covered every-entry +
call-twice (R5 #8)."""
from pathlib import Path

import flipjump as fj

from doomfj.fixedpoint import fixed_mul, fixed_div, mul_const
from doomfj.harness import W

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")


def _run(tmp_path, name, body, data, expected: bytes):
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != host mirror"


# (n, f, a, b) — boundary / signed / overflow / fractional, both 16.16 and 8.8
MUL_CASES = [
    (8, 4, 0x00018000, 0x00020000),
    (8, 4, 0xFFFE8000, 0x00020000),
    (8, 4, 0xFFFE8000, 0xFFFE0000),
    (8, 4, 0x40000000, 0x00040000),
    (8, 4, 0x00008000, 0x00008000),
    (4, 2, 0x0280, 0xFE00),
]

DIV_CASES = [
    (8, 4, 0x00030000, 0x00020000),
    (8, 4, 0xFFFD0000, 0x00020000),
    (8, 4, 0xFFFF0000, 0x00030000),
    (8, 4, 0x00010000, 0x00030000),
    (4, 2, 0xFB00, 0x0280),
    (8, 4, 0x00030000, 0xFFFE0000),
    (8, 4, 0xFFFD0000, 0xFFFE0000),
]

MUL_CONST_CASES = [(8, 0x00001234, 320), (8, 0x12345678, 1), (8, 0xFFFFFFFF, 5), (8, 0xABCD0123, 0)]


def test_fixed_mul_parity(tmp_path):
    body, data = [], []
    for i, (n, f, a, b) in enumerate(MUL_CASES):
        body += [f"hex.fixed_mul {n}, {f}, r{n}, a{i}, b{i}",
                 f"hex.print_as_digit {n}, r{n}, 0", "stl.output '\\n'"]
        data += [f"a{i}: hex.vec {n}, {hex(a)}", f"b{i}: hex.vec {n}, {hex(b)}"]
    for n in sorted({n for n, *_ in MUL_CASES}):
        data.append(f"r{n}: hex.vec {n}")
    expected = "".join(f"{fixed_mul(a, b, n, f):0{n}x}\n" for n, f, a, b in MUL_CASES).encode()
    _run(tmp_path, "fixed_mul", body, data, expected)


def test_fixed_mul_aliasing(tmp_path):
    # dst aliases a (in place), and b aliases a (square)
    body = ["hex.fixed_mul 8, 4, m, m, mb", "hex.print_as_digit 8, m, 0", "stl.output '\\n'",
            "hex.fixed_mul 8, 4, r, sq, sq", "hex.print_as_digit 8, r, 0", "stl.output '\\n'"]
    data = ["m: hex.vec 8, 0x00018000", "mb: hex.vec 8, 0x00020000",
            "sq: hex.vec 8, 0xFFFF8000", "r: hex.vec 8"]
    expected = (f"{fixed_mul(0x00018000, 0x00020000, 8, 4):08x}\n"
                f"{fixed_mul(0xFFFF8000, 0xFFFF8000, 8, 4):08x}\n").encode()
    _run(tmp_path, "fixed_mul_alias", body, data, expected)


def test_fixed_div_parity_and_div0(tmp_path):
    body, data = [], []
    for i, (n, f, a, b) in enumerate(DIV_CASES):
        body += [f"hex.fixed_div {n}, {f}, r{n}, a{i}, b{i}, baddiv0",
                 f"hex.print_as_digit {n}, r{n}, 0", "stl.output '\\n'"]
        data += [f"a{i}: hex.vec {n}, {hex(a)}", f"b{i}: hex.vec {n}, {hex(b)}"]
    # div-by-zero must take the div0 label; baddiv0 (the success-path error label) must never fire
    body += ['hex.fixed_div 8, 4, r8, az, zero8, gooddiv0',
             'baddiv0:', 'stl.output "BAD\\n"', 'stl.loop',
             'gooddiv0:', 'stl.output "DIV0\\n"', 'stl.loop']
    data += ["az: hex.vec 8, 0x00030000", "zero8: hex.vec 8, 0"]
    for n in sorted({n for n, *_ in DIV_CASES}):
        data.append(f"r{n}: hex.vec {n}")
    expected = ("".join(f"{fixed_div(a, b, n, f):0{n}x}\n" for n, f, a, b in DIV_CASES) + "DIV0\n").encode()
    _run(tmp_path, "fixed_div", body, data, expected)


def test_mul_const_parity(tmp_path):
    body, data = [], []
    for i, (n, src, c) in enumerate(MUL_CONST_CASES):
        body += [f"hex.mul_const {n}, r{n}, x{i}, {c}",
                 f"hex.print_as_digit {n}, r{n}, 0", "stl.output '\\n'"]
        data.append(f"x{i}: hex.vec {n}, {hex(src)}")
    for n in sorted({n for n, *_ in MUL_CONST_CASES}):
        data.append(f"r{n}: hex.vec {n}")
    expected = "".join(f"{mul_const(src, c, n):0{n}x}\n" for n, src, c in MUL_CONST_CASES).encode()
    _run(tmp_path, "mul_const", body, data, expected)


def test_read_table_every_entry_call_twice(tmp_path):
    # hand-built 4-entry hex[:8] table; read EVERY entry, TWICE (R5 #8: catches result-reg /
    # in-table-jumper cleanup bugs). idx is a 2-nibble index.
    entries = [0x11111111, 0x22222222, 0xABCDEF01, 0xFFFFFFFF]
    body, data = [], []
    for k in range(len(entries)):
        for _ in range(2):  # call twice per entry
            body += [f"hex.read_table 8, d, tbl, 2, i{k}", "hex.print_as_digit 8, d, 0", "stl.output '\\n'"]
        data.append(f"i{k}: hex.vec 2, {k}")
    data += ["d: hex.vec 8", "tbl:"] + [f"    hex.vec 8, {hex(v)}" for v in entries]
    expected = "".join(f"{v:08x}\n{v:08x}\n" for v in entries).encode()
    _run(tmp_path, "read_table", body, data, expected)
