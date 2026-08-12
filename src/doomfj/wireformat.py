"""M14 — THE STATE WIRE, in one place.

The program is a pure function of stdin that renders one frame and halts; the loop is host-side
because fj self-modifies. M14 changes that function's signature from

    (vx, vy, viewangle) -> frame        to        (world state, input) -> frame, world state'

so simulation state has to ROUND-TRIP through stdin/stdout every frame, and the host becomes a
relay that holds the previous state rather than the thing that computes movement.

WHY BINARY (M14-0, measured -- see docs/handoff-m14.md section 2.1). A decimal number costs ~2,100
fj ops per DIGIT to read and ~12,900 to print; the same 32-bit value costs 295 to read and 216 to
write as raw bytes. Round-tripping the 212-thing table would be ~36M ops/frame as decimals -- more
than the entire 33.5-45.2M frame -- against ~542k as binary.

THE WIRE (little-endian throughout, the order `hex.input` reads and `stream.emit_bytes4` writes):

    in   [MAGIC:1][x:4][y:4][angle:4][keys:1]        = 14 bytes
    out  [STATE_CMD:1][x:4][y:4][angle:4]            = 13 bytes, before the frame's own records

`x`/`y` are 16.16 fixed point (the sim's native precision, and what `viewx`/`viewy` want anyway);
`angle` is a 32-bit BAM. MAGIC exists so a malformed feed still lands on the program's `bad:` halt:
the R0 build gate feeds one junk byte and must halt on it rather than block reading 13 more.

This module is the SINGLE definition of that layout. The emitter reads MAGIC/STATE_CMD from here,
the host encoder/decoder below is what every caller uses, and `StreamScreen` decodes STATE_CMD
through `decode_state`. Nothing else may open-code the byte order.
"""
from __future__ import annotations

import struct

MAGIC = 0xD0            # first byte of every state feed; anything else -> the program's `bad:` halt
STATE_CMD = 0x10        # the present-protocol command byte carrying the state block back out
STATE_BYTES = 12        # x, y, angle -- three little-endian 32-bit words
FEED_BYTES = 1 + STATE_BYTES + 1

# the key bits of the input byte (DOOM's ticcmd, reduced to what reference_model.step_sim reads)
KEY_FORWARD = 1 << 0
KEY_BACK = 1 << 1
KEY_TURN_LEFT = 1 << 2
KEY_TURN_RIGHT = 1 << 3
KEY_NAMES = {"forward": KEY_FORWARD, "back": KEY_BACK,
             "turn_left": KEY_TURN_LEFT, "turn_right": KEY_TURN_RIGHT}

# The fj side tests these bits with `hex.if_flags`, whose mask is a set of NIBBLE VALUES rather
# than a bit mask: mask bit v is set iff nibble value v should take the "flag set" branch. So
# "bit k of the nibble is set" is the mask below -- derived here, once, rather than written out as
# four magic constants in the emitter.
_NIBBLE_MASK = {k: sum(1 << v for v in range(16) if v & (1 << k)) for k in range(4)}
KEY_FORWARD_MASK = _NIBBLE_MASK[0]        # 0xAAAA
KEY_BACK_MASK = _NIBBLE_MASK[1]           # 0xCCCC
KEY_TURN_LEFT_MASK = _NIBBLE_MASK[2]      # 0xF0F0
KEY_TURN_RIGHT_MASK = _NIBBLE_MASK[3]     # 0xFF00


def keys_dict(byte: int) -> dict:
    """The wire's key byte as the dict `ReferenceModel.step_sim` reads. Only bits 0..3 exist -- the
    fj side reads the LOW NIBBLE only -- so anything above is dropped here too, deliberately, so the
    two mirrors agree on a malformed byte as well as a well-formed one."""
    return {name: bool(byte & bit) for name, bit in KEY_NAMES.items()}


def keys_byte(keys) -> int:
    """`{'forward': True, ...}` (the dict `step_sim` takes) or an int, as the wire's key byte."""
    if isinstance(keys, int):
        return keys & 0xFF
    return sum(bit for name, bit in KEY_NAMES.items() if keys.get(name))


def encode_feed(x16: int, y16: int, angle: int, keys=0) -> bytes:
    """The 14 bytes the program reads for one frame. `x16`/`y16` are 16.16 (signed or already
    masked); `angle` is a BAM."""
    return bytes([MAGIC]) + struct.pack(
        "<III", x16 & 0xFFFFFFFF, y16 & 0xFFFFFFFF, angle & 0xFFFFFFFF) + bytes([keys_byte(keys)])


def encode_feed_mapunits(vx: int, vy: int, angle: int, keys=0) -> bytes:
    """The same feed from INTEGER map units -- the (vx, vy, va) triple every existing gate and test
    speaks. `x16 = vx << 16` is exactly what the decimal wire's `hex.shl_hex 8, 4, viewx` produced,
    which is what makes a bin-wire frame byte-identical to a dec-wire one at the same viewpoint."""
    return encode_feed(vx << 16, vy << 16, angle, keys)


def decode_state(payload: bytes) -> tuple:
    """The 12-byte STATE_CMD payload -> (x16, y16, angle), x/y as SIGNED 16.16."""
    if len(payload) != STATE_BYTES:
        raise ValueError(f"state payload is {len(payload)} bytes, want {STATE_BYTES}")
    x, y, ang = struct.unpack("<III", payload)
    return (x - (1 << 32) if x >> 31 else x,
            y - (1 << 32) if y >> 31 else y,
            ang)
