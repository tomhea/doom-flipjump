"""The palette tests' device (test_palette_fj, test_powers_fj): flipjump's own screen, fed stdin, that also counts the
`select_palette` commands the program sends between presents.

The screen decodes everything (it is the API's authority and refuses anything off it); the count comes from a tiny
parse of the same bytes, for exactly the commands these programs print: init_screen, define_palette, select_palette,
an EMPTY draw_collines (0x11, END_CMD) and present. Anything else is refused here too, so a program that prints more
than the test expects cannot slip past the count.
"""
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IOReadOnEOF

from doomfj import screenwire as SW


def boot_lines(palettes):
    """init_screen and the palettes into slots 0..n-1, as the game's boot sends them (wall_renderer's io_boot)"""
    out = ["present.init_screen"]
    for k, rgb in enumerate(palettes):
        out += SW.fj_lines(SW.define_palette(k, rgb))
    return out


class PalDev(InMemoryScreen):
    """per present: (select_palette commands since the previous present, the palette shown)"""

    def __init__(self, stdin: bytes):
        super().__init__()
        self._inp, self._in_byte, self._in_bits = stdin, 0, 0
        self.sent, self.frames = 0, []
        self._out_byte, self._out_bits = 0, 0
        self._cmd = bytearray()

    def read_bit(self) -> bool:
        if self._in_bits == 0:
            if not self._inp:
                raise IOReadOnEOF("EOF")
            self._in_byte, self._inp, self._in_bits = self._inp[0], self._inp[1:], 8
        bit = self._in_byte & 1
        self._in_byte >>= 1
        self._in_bits -= 1
        return bool(bit)

    # the engine hands the device whole bytes (write_byte) from a byte boundary, single bits otherwise: count both ways
    def write_bit(self, bit: bool) -> None:
        self._out_byte |= int(bit) << self._out_bits
        self._out_bits += 1
        if self._out_bits == 8:
            self._count(self._out_byte)
            self._out_byte, self._out_bits = 0, 0
        super().write_bit(bit)

    def write_byte(self, byte: int) -> None:
        if self._out_bits:
            for i in range(8):
                self.write_bit(bool((byte >> i) & 1))
            return
        self._count(byte)
        super().write_byte(byte)

    def _count(self, byte: int) -> None:
        cmd = self._cmd
        cmd.append(byte)
        op = cmd[0]
        if op == SW.OP_INIT_SCREEN:
            done = len(cmd) == 6
        elif op == SW.OP_DEFINE_PALETTE:
            done = len(cmd) >= 4 and len(cmd) == 4 + 3 * (cmd[3] - cmd[2] + 1)
        elif op == SW.OP_SELECT_PALETTE:
            done = len(cmd) == 2
            if done:
                self.sent += 1
        elif op == SW.OP_DRAW_COLLINES:
            assert len(cmd) == 1 or cmd[1] == SW.END_CMD, "the palette programs draw nothing: %r" % bytes(cmd)
            done = len(cmd) == 2
        elif op == SW.OP_PRESENT:
            done = True
        else:
            raise AssertionError("an opcode the palette programs never print: %#04x" % op)
        if done:
            self._cmd = bytearray()

    def _present(self):
        super()._present()
        self.frames.append((self.sent, tuple(tuple(c) for c in self.palette)))
        self.sent = 0
