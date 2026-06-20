"""M5 (S5.1/H2) — dispatch-CODE LUT emitter, assembled + run on the real flipjump engine.

Every generated table is exercised on EVERY entry AND call-twice-per-entry (#8 / R5) — this catches
result-register and in-table-jumper-cleanup bugs from the #5 construction (D4). Both emit modes
(per-entry default + per-result-nibble override, D4) and the D3 +4-offset packed-byte deposit are
covered. Expected bytes come from the host (the LUT values are the test's own source of truth)."""
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.lut_generator import (
    generate_dispatch_table_fj,
    generate_offset_deposit_table_fj,
)


def _run(tmp_path, name, body, tables, expected: bytes):
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
            + "\n".join(tables) + "\n")
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [p.resolve()], b"", expected, memory_width=W,
        warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != expected"


def _every_entry_twice_body(label, values, index_nibbles, result_nibbles):
    """body + data + expected for: read every entry twice, print result, compare to values."""
    body, data = [], []
    for k in range(len(values)):
        for _ in range(2):  # call twice per entry (#8)
            body += [f"{label}.lookup rdst, idx{k}",
                     f"hex.print_as_digit {result_nibbles}, rdst, 0", "stl.output 10"]
    for k in range(len(values)):
        data.append(f"idx{k}: hex.vec {index_nibbles}, {k}")
    data.append(f"rdst: hex.vec {result_nibbles}")
    expected = "".join(f"{v:0{result_nibbles}x}\n{v:0{result_nibbles}x}\n" for v in values).encode()
    return body, data, expected


def test_per_entry_single_nibble_every_entry_twice(tmp_path):
    label, values, idx_n, res_n = "t1", [(i * 7 + 3) & 0xF for i in range(16)], 1, 1
    body, data, expected = _every_entry_twice_body(label, values, idx_n, res_n)
    table = generate_dispatch_table_fj(label, values, index_nibbles=idx_n, result_nibbles=res_n,
                                       mode="per_entry")
    _run(tmp_path, label, body, data + [table], expected)


def test_per_entry_multi_nibble_every_entry_twice(tmp_path):
    # 8-nibble (32-bit) results incl. 0, all-ones, and signed-encoded values
    label = "t2"
    values = [0x00000000, 0xFFFFFFFF, 0x0000FFFF, 0xDEADBEEF, 0x12345678,
              0x80000000, 0x00000001, 0xA5A5A5A5, 0x0F0F0F0F, 0xCAFEF00D,
              0x11111111, 0x22222222, 0x7FFFFFFF, 0x00010000, 0xABCDEF01, 0x99999999]
    idx_n, res_n = 1, 8
    body, data, expected = _every_entry_twice_body(label, values, idx_n, res_n)
    table = generate_dispatch_table_fj(label, values, index_nibbles=idx_n, result_nibbles=res_n,
                                       mode="per_entry")
    _run(tmp_path, label, body, data + [table], expected)


def test_per_result_nibble_multi_nibble_every_entry_twice(tmp_path):
    label = "t3"
    values = [0x00000000, 0xFFFFFFFF, 0xDEADBEEF, 0x12345678, 0x80000000, 0x00000001,
              0xA5A5A5A5, 0xCAFEF00D, 0x7FFFFFFF, 0x00010000, 0xABCDEF01, 0x99999999,
              0x0F0F0F0F, 0xF0F0F0F0, 0x10000000, 0x00000010]
    idx_n, res_n = 1, 8
    body, data, expected = _every_entry_twice_body(label, values, idx_n, res_n)
    table = generate_dispatch_table_fj(label, values, index_nibbles=idx_n, result_nibbles=res_n,
                                       mode="per_result_nibble")
    _run(tmp_path, label, body, data + [table], expected)


def test_per_entry_multi_nibble_index_every_entry_twice(tmp_path):
    # count=17 -> pad 32 -> 2-nibble index (exercises the multi-nibble index XOR in lookup)
    label = "t4"
    values = [(i * 0x1111 + 0xABC) & 0xFFFFF for i in range(17)]  # 5-nibble results
    idx_n, res_n = 2, 5
    body, data, expected = _every_entry_twice_body(label, values, idx_n, res_n)
    table = generate_dispatch_table_fj(label, values, index_nibbles=idx_n, result_nibbles=res_n,
                                       mode="per_entry")
    _run(tmp_path, label, body, data + [table], expected)


def test_offset_deposit_byte_exact(tmp_path):
    # D3 +4-offset packed-byte deposit: deposit each byte (low nibble via stock dispatch, high via
    # the +4 table) into the kept-zero packed-byte acc, read it back (register form), call twice.
    label = "dep"
    test_bytes = [0x00, 0x01, 0x10, 0x0F, 0xF0, 0x5A, 0xA5, 0xFF, 0x80, 0x7F, 0x42, 0xC3]
    body, data = [], []
    for k, _v in enumerate(test_bytes):
        for _ in range(2):  # call twice per byte (#8)
            body += [f"hex.set 2, dval, {hex(_v)}",
                     f"{label}.deposit dval",
                     f"{label}.readback rbyte",
                     "hex.print_as_digit rbyte+1*dw, 0", "hex.print_as_digit rbyte+0*dw, 0",
                     "stl.output 10"]
    data += ["dval: hex.vec 2", "rbyte: hex.vec 2"]
    expected = "".join(f"{v:02x}\n{v:02x}\n" for v in test_bytes).encode()
    table = generate_offset_deposit_table_fj(label)
    _run(tmp_path, label, body, data + [table], expected)
