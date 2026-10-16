"""P13 -- `byte.emit` through two 16-entry nibble dispatches (lut_generator.generate_emit_byte_by_nibbles_fj): RUN in fj,
every byte value 0..255 emitted from a 2-nibble register must leave the program as exactly that byte, lsb first, as
the 256-entry EMIT table (generate_emit_dispatch_table_fj("byte", range(256), index_nibbles=2)) did. Both tables run
on the same register values and their outputs are compared to bytes(range(256)) and to each other.
CONTROL (R9): the pair with its nibbles emitted high first must NOT produce the bytes."""
import flipjump as fj

from doomfj.harness import W
from doomfj.lut_generator import generate_emit_byte_by_nibbles_fj, generate_emit_dispatch_table_fj


def _program(table: str) -> str:
    body = ["stl.startup_and_init_all"]
    for v in range(256):
        body += [f"hex.set 2, reg, {v}", "byte.emit reg"]
    return "\n".join(body + ["stl.loop", "reg: hex.vec 2", table]) + "\n"


def _run(tmp_path, name, table) -> bool:
    p = tmp_path / f"{name}.fj"
    p.write_text(_program(table), encoding="utf-8")
    return fj.assemble_and_run_test_output([p.resolve()], b"", bytes(range(256)), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_nibble_pair_emits_every_byte(tmp_path):
    assert _run(tmp_path, "nib", generate_emit_byte_by_nibbles_fj("byte"))


def test_the_256_entry_table_emits_the_same(tmp_path):
    assert _run(tmp_path, "wide", generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2))


def test_control_high_nibble_first_is_caught(tmp_path):
    t = generate_emit_byte_by_nibbles_fj("byte")
    good = "        bnib.emit idx\n        bnib.emit idx + dw\n"
    assert t.count(good) == 1
    assert not _run(tmp_path, "swapped", t.replace(good, "        bnib.emit idx + dw\n        bnib.emit idx\n"))
