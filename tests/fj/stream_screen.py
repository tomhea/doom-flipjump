"""The HOSTED tiers' device: flipjump's own screen plus the host channel.

A hosted program (wall_renderer's `hosted*` tiers: what deg_gate, the M2 / M14 gates and the probes drive) reads its
world state from stdin and writes, on ONE output stream, both the screen's commands and the host channel's: the
round-tripped state (`doomfj.wireformat.STATE_CMD`, 0x80) and the thing bindings (`THING_CMD`, 0x81). The host
channel's opcodes sit outside the screen API's (flipjump `io_devices/README.md`), so `StreamScreen` is flipjump's
`InMemoryScreen` -- the API's own decoder, which refuses anything off it -- with those two commands taken out through
its subclass hook `_extension_command`, and an optional stdin feed.

There is no second decoder here any more: every picture a test or gate reads went through the real device.
"""
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IOReadOnEOF

# the state block and the bindings are decoded through the wire's SSOT -- the device must not open-code a byte order
# the emitter could change under it
from doomfj.wireformat import (STATE_CMD as CMD_STATE, STATE_BYTES, decode_state,
                               THING_CMD as CMD_THINGS, BINDING_OUT_BYTES, decode_bindings)


class StreamScreen(InMemoryScreen):
    def __init__(self, *, frames_dir=None, stdin: bytes = b"", n_things: int = 0):
        super().__init__(frames_dir=frames_dir)
        self._inp = stdin                          # optional stdin feed: the hosted program's world state
        self._in_byte = 0
        self._in_bits = 0
        # the round-tripped world state, as (x16, y16, angle); None until the program emits a STATE_CMD block
        self.state = None
        # the thing->subsector bindings coming back (the host relays them, so fj re-locates only what moved); the
        # block's length is n_things records
        self.bindings = None
        self._n_things = n_things

    @property
    def flush_count(self) -> int:
        """how many frames were presented (the name the gates have always read)"""
        return self.frame_count

    # ---------------------------------------------------------------- input stream (optional)

    def read_bit(self) -> bool:
        if self._in_bits == 0:
            if not self._inp:
                raise IOReadOnEOF("EOF on StreamScreen")
            self._in_byte, self._inp = self._inp[0], self._inp[1:]
            self._in_bits = 8
        bit = (self._in_byte & 1) == 1
        self._in_byte >>= 1
        self._in_bits -= 1
        return bit

    # ---------------------------------------------------------------- the host channel

    def _extension_command(self, opcode: int):
        """STATE_CMD and THING_CMD: collect their payload bytes, then decode them through doomfj.wireformat"""
        if opcode == CMD_STATE:
            length, decode, attr = STATE_BYTES, decode_state, "state"
        elif opcode == CMD_THINGS:
            length, decode, attr = BINDING_OUT_BYTES * self._n_things, decode_bindings, "bindings"
        else:
            return None                            # not ours: the device's own unknown-opcode error
        if length == 0:
            setattr(self, attr, decode(b""))
            return True
        payload = bytearray()

        def take(byte: int) -> bool:
            payload.append(byte)
            if len(payload) < length:
                return False
            setattr(self, attr, decode(bytes(payload)))
            return True
        return take
