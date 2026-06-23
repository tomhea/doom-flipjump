"""M12k (F7) — isolated unit tests for the present-layer macros (src/fj/present.fj). Each macro emits a
byte-exact command stream on the output channel (the screen-device protocol), so we drive the macro and
compare the captured output to the bytes hand-derived from the protocol + the config SSOT (W/H/BPP/
NCOLORS from fj_consts). These macros are PURE EMIT (no precondition/@Assumes), so per the test mandate
there is no should-fail case — only sanity (byte-exact) + the address-byte-order edge case."""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.harness import W

PRESENT_FJ = Path("src/fj/present.fj")


def _run(tmp_path, name, body, expected: bytes):
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [consts.resolve(), PRESENT_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: present output != protocol bytes"


def test_init_screen_command_bytes(tmp_path):
    """init_screen: [0x01][W:2 LE][H:2 LE][BPP:1][NCOLORS:2 LE] from the config SSOT."""
    c = Config()
    expected = bytes([0x01, c.W & 0xFF, (c.W >> 8) & 0xFF, c.H & 0xFF, (c.H >> 8) & 0xFF,
                      c.BPP, c.NCOLORS & 0xFF, (c.NCOLORS >> 8) & 0xFF])
    _run(tmp_path, "init_screen", ["present.init_screen"], expected)


def test_emit_addr_is_little_endian_w_over_8_bytes(tmp_path):
    """emit_addr writes the low w/8 bytes of the address, little-endian (incl. zero bytes). w=32 ⇒ 4
    bytes; the edge case is the byte ORDER (LE) and that zero high bytes are still emitted."""
    addr = 0x12345678
    expected = bytes([(addr >> (8 * i)) & 0xFF for i in range(W // 8)])      # 78 56 34 12
    _run(tmp_path, "emit_addr", [f"present.emit_addr {addr}"], expected)


def test_emit_addr_emits_zero_high_bytes(tmp_path):
    """A small address still emits all w/8 bytes (the device reads a fixed-width address)."""
    expected = bytes([0x05, 0x00, 0x00, 0x00])
    _run(tmp_path, "emit_addr_small", ["present.emit_addr 5"], expected)


def test_set_palette_command(tmp_path):
    """set_palette: [0x02][addr: w/8 LE]."""
    addr = 0x0000ABCD
    expected = bytes([0x02]) + bytes([(addr >> (8 * i)) & 0xFF for i in range(W // 8)])
    _run(tmp_path, "set_palette", [f"present.set_palette {addr}"], expected)


def test_update_screen_command(tmp_path):
    """update_screen (memory-hook present): [0x03][addr: w/8 LE]."""
    addr = 0x00ABCDEF
    expected = bytes([0x03]) + bytes([(addr >> (8 * i)) & 0xFF for i in range(W // 8)])
    _run(tmp_path, "update_screen", [f"present.update_screen {addr}"], expected)


def test_update_screen_reg_command(tmp_path):
    """update_screen_reg (0x06, hex.vec2 register form, fj 1.5.1): [0x06][addr: w/8 LE]."""
    addr = 0x00000040
    expected = bytes([0x06]) + bytes([(addr >> (8 * i)) & 0xFF for i in range(W // 8)])
    _run(tmp_path, "update_screen_reg", [f"present.update_screen_reg {addr}"], expected)


def test_full_present_sequence(tmp_path):
    """The real per-frame command order: init then set_palette then update_screen — concatenated."""
    c = Config()
    pal, fbuf = 0x100, 0x200
    expected = (bytes([0x01, c.W & 0xFF, (c.W >> 8) & 0xFF, c.H & 0xFF, (c.H >> 8) & 0xFF,
                       c.BPP, c.NCOLORS & 0xFF, (c.NCOLORS >> 8) & 0xFF])
                + bytes([0x02]) + bytes([(pal >> (8 * i)) & 0xFF for i in range(W // 8)])
                + bytes([0x03]) + bytes([(fbuf >> (8 * i)) & 0xFF for i in range(W // 8)]))
    _run(tmp_path, "present_seq",
         ["present.init_screen", f"present.set_palette {pal}", f"present.update_screen {fbuf}"], expected)
