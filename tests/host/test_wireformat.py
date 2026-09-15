"""M14 -- THE STATE WIRE's host half, pinned without assembling anything.

`doomfj/wireformat.py` is the SINGLE definition of the bytes that cross stdin/stdout every frame:
the player state in, the state and the thing bindings back out, plus the key byte, the thing
positions and the visibility flags. Every one of those is a pure function of ints and bytes, yet
until now the only thing that exercised them was `tests/fj/test_state_wire.py`, which proves them
by BUILDING a program and running 200 tics. A byte-order slip therefore cost a full build to see,
and `scratchpad/m5_gate.py` would only report it as "frame 0 differs" with the fj side blameless.

What this file pins, and what breaks in the shipped program if it stops holding:

* THE DECODER IS THE ENCODER'S INVERSE over the whole unsigned domain -- not at three chosen
  values. A swapped '<III' order or an offset slip renders the frame from someone else's position.
* THE SIGNEDNESS CONVENTION: x/y sign-extend at 2**31, the angle does NOT. This is exactly the
  divergence `SimState.__post_init__` records -- a state built from `spawn_state` (-27262976) and
  the mathematically equal masked state (0xFE600000) rendered different frames, 14,845 of 16,000
  pixels wrong. Sign-extending the angle too (which looks like harmless symmetry) hands
  `read_cos`/`read_sin` a negative index and turns the view.
* THE MIRROR COMPOSITION the host relay performs every frame: SimState -> encode_feed ->
  decode_state -> SimState is the identity. `scripts/walk_e1m1.py` feeds st[0], st[1], st[2]
  straight back into `encode_feed`; nothing host-side pinned that round trip.
* THE LOUD FAILURES: a mis-sized state payload, a misaligned binding block and a misaligned thing
  block all raise. Silent truncation of a desynced block is the failure mode that keeps running
  with a plausible-looking wrong position and reports nothing.
* THE KEY BYTE in both directions and in both spellings -- `walk_e1m1.py` hands `encode_feed` an
  int, the gates and `reference_model` speak the dict. If the two branches diverge the host and
  the oracle press different keys on the same frame.
* THE FOUR MOVEMENT MASKS, each re-derived from its OWN KEY_* bit. Binding one to the wrong nibble
  index is a one-token edit with no host-side symptom: the program would TURN where the oracle
  WALKS, and only a built renderer under a hosted gate would say so.
* THE DELIBERATE 2-in / 4-out ASYMMETRY of the binding block, which only a comment defends today,
  and BINDING_DIRTY's sentinel-ness: a spuriously dirty binding leaves the PIXELS correct and
  silently restores the 27.2M ops/frame that M14-e removed -- a perf regression with byte-exact
  output, the one class of defect `deg_gate`'s op-count check exists for.
* THAT THE TWO COMMAND-BYTE REGISTRIES DO NOT COLLIDE. STATE_CMD/THING_CMD live here; the
  present-protocol CMD_* live in `tests/fj/stream_screen.py` with no cross-check. If a future
  present command takes 0x10, StreamScreen mis-frames the stream and every frame decodes as
  garbage. The other registry is read out of its file with `ast` rather than re-typed here, so the
  two cannot be pinned to stale copies of each other.

R9 -- these can fail. Written on 2026-09-11 against 26 in-memory mutants of `wireformat.py` (the
module source was mutated and exec'd under a shimmed `sys.modules` entry; `src/` was not touched):
swapped struct orders on all four blocks, both dropped sign extensions, a sign-extended angle, each
removed length check, a dropped MAGIC, a stale FEED_BYTES, both binding strides, `BINDING_DIRTY`
moved, a key name typo, two names sharing a bit, a wrong nibble index for KEY_BACK_MASK, and a
colliding STATE_CMD. 25 of 26 were rejected. The one survivor -- `(vx & 0xFFFF) << 16` in
`encode_feed_mapunits` -- is an EQUIVALENT mutant, not a gap: two's complement makes it produce the
identical 32 bits for every signed 16-bit map unit (checked exhaustively). A truncating 16-bit
intermediate, the other spelling of that defect, IS rejected.

Deliberately NOT here (all need an assembled image, and `tests/fj/test_state_wire.py` owns them):
that a wrong MAGIC lands the program on `bad:`, that `hex.if_flags` interprets a nibble-value mask
the way the comment says, that FEED_BYTES is what the program actually consumes, and cumulative
multi-frame fidelity.
"""
import ast
import random
import struct
from pathlib import Path

import pytest

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, spawn_state
from doomfj.wad import WadFile
from doomfj.wireformat import (BINDING_DIRTY, BINDING_IN_BYTES, BINDING_OUT_BYTES, FEED_BYTES,
                               KEY_BACK, KEY_BACK_MASK, KEY_FORWARD, KEY_FORWARD_MASK, KEY_NAMES,
                               KEY_TURN_LEFT, KEY_TURN_LEFT_MASK, KEY_TURN_RIGHT,
                               KEY_TURN_RIGHT_MASK, MAGIC, STATE_BYTES, STATE_CMD, THING_CMD,
                               VIS_IN_BYTES, decode_bindings, decode_state, decode_things,
                               encode_bindings, encode_feed, encode_feed_mapunits, encode_things,
                               encode_visibility, keys_byte, keys_dict)

ROOT = Path(__file__).resolve().parents[2]
E1M1 = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"

# The state block as it comes back out of the program: everything after the STATE_CMD byte.
def _state_payload(feed: bytes) -> bytes:
    return feed[1:1 + STATE_BYTES]


def _payloads():
    """Every 12-byte payload worth trying: the two saturated ones, each byte position alone (which
    is what catches an offset slip), and a deterministic random sample of the rest."""
    rnd = random.Random(20260911)
    yield b"\x00" * STATE_BYTES
    yield b"\xff" * STATE_BYTES
    for i in range(STATE_BYTES):
        yield bytes(0xA5 if j == i else 0 for j in range(STATE_BYTES))
        yield bytes(0x00 if j == i else 0xFF for j in range(STATE_BYTES))
    for _ in range(200):
        yield bytes(rnd.randrange(256) for _ in range(STATE_BYTES))


# -- the state block: encoder and decoder are one function and its inverse -----------------------

def test_decode_state_is_the_exact_inverse_of_encode_feed():
    """The property that no chosen-value test finds: over the FULL unsigned domain, re-encoding a
    decoded payload reproduces it byte for byte. Swapping the '<III' order, or reading x/y/angle at
    the wrong offsets, survives a test that only checks the player start (whose y happens to be a
    round number) but not this one."""
    for p in _payloads():
        assert _state_payload(encode_feed(*decode_state(p))) == p, p.hex()


def test_x_and_y_are_sign_extended_but_the_angle_is_not():
    """THE convention, both halves of it. x/y are SIGNED 16.16 because the projection reads them
    raw (see SimState.__post_init__ -- the masked/signed pair rendered 14,845 wrong pixels). The
    angle is an unsigned 32-bit BAM: sign-extending it too, which looks like symmetry, hands
    read_cos/read_sin a negative index."""
    x, y, ang = decode_state(struct.pack("<III", 0x80000000, 0x80000000, 0xFFFFFFFF))
    assert x == -(1 << 31) and y == -(1 << 31)
    assert ang == 0xFFFFFFFF, "the angle must stay an unsigned BAM, never -1"
    # ...and one below the boundary is still positive, i.e. the extension is at 2**31 and not at
    # some other bit.
    x, y, ang = decode_state(struct.pack("<III", 0x7FFFFFFF, 0x7FFFFFFF, 0x80000000))
    assert x == 0x7FFFFFFF and y == 0x7FFFFFFF
    assert ang == 0x80000000
    # every decoded angle is in range, and every decoded coordinate is a signed 32-bit value
    for p in _payloads():
        dx, dy, da = decode_state(p)
        assert 0 <= da < (1 << 32)
        assert -(1 << 31) <= dx < (1 << 31) and -(1 << 31) <= dy < (1 << 31)


def test_the_wire_round_trips_through_the_oracle_state_class():
    """The composition the host relay performs EVERY FRAME -- scripts/walk_e1m1.py feeds st[0],
    st[1], st[2] straight back into encode_feed -- and nothing host-side pinned it: it was only
    proven inside the 200-tic fj test. Any drift between the wire's signedness and SimState's
    normalisation shows up here instead of as a parted trajectory in m5_gate."""
    w = WadFile.from_path(str(E1M1))
    states = [
        spawn_state(w, "E1M1"),                                  # the real E1M1 player start
        SimState(0, 0, 0, "E1M1"),
        SimState(-1, -1, 0xFFFFFFFF, "E1M1"),
        SimState(-(1 << 31), (1 << 31) - 1, 0x40000000, "E1M1"),  # the 16.16 extremes
        SimState(0x7FFFFFFF, -(1 << 31), 0xC0000000, "E1M1"),
    ]
    for s in states:
        back = SimState(*decode_state(_state_payload(encode_feed(s.x, s.y, s.angle))), level=s.level)
        assert back == s, f"{s} did not survive the wire"


def test_a_mis_sized_state_payload_raises():
    """The raise is what makes a present-protocol desync LOUD. A decoder that accepted a short or
    over-long block would hand the host a plausible-looking position and the frame would render
    from the wrong place with no error anywhere."""
    for n in (0, STATE_BYTES - 1, STATE_BYTES + 1):
        with pytest.raises(ValueError):
            decode_state(b"\x00" * n)
    decode_state(b"\x00" * STATE_BYTES)          # ...and the right size still decodes


# -- the feed: shape, magic, and totality --------------------------------------------------------

def test_the_feed_has_the_declared_shape_magic_and_key_byte():
    """FEED_BYTES is the module's DECLARED wire width and the program reads a fixed number of bytes:
    a field added to the encoder without updating it makes the program block on stdin. MAGIC is the
    single guard between a malformed feed and a blank frame that still passes a byte-exactness gate
    (see tests/host/test_no_decimal_wire.py)."""
    assert FEED_BYTES == 1 + STATE_BYTES + 1
    for keys in (0, 0xFF, KEY_FORWARD, {"forward": True, "turn_left": True}, {}, keys_dict(0x1F)):
        feed = encode_feed(-27262976, 16777216, 0x20000000, keys)
        assert len(feed) == FEED_BYTES
        assert feed[0] == MAGIC
        assert feed[-1] == keys_byte(keys)


def test_the_encoder_is_total_over_negative_and_over_wide_values():
    """Negative coordinates are the NORMAL case -- the E1M1 player start is negative in x -- so this
    path runs every frame. struct.pack('<I', negative) RAISES, so dropping the '& 0xFFFFFFFF' is not
    a wrong pixel but a crash partway through a walk. The angle wrap mirrors step_sim's own."""
    feed = encode_feed(-1, -(1 << 31), 0)
    assert decode_state(_state_payload(feed)) == (-1, -(1 << 31), 0)
    for a in (0, 1, 0xFFFFFFFF):
        assert encode_feed(-5, 7, a) == encode_feed(-5, 7, a + (1 << 32)), "angle must wrap mod 2**32"
        assert encode_feed(-5, 7, a) == encode_feed(-5, 7, a - (1 << 32))


def test_mapunits_is_a_SIGNED_shift_of_the_same_encoder():
    """Every deg_gate viewpoint, scripts/measure_frame.py and every hosted gate enters the wire
    through this helper. An unsigned or truncating shift ((vx & 0xFFFF) << 16, or a 16-bit
    intermediate) would mirror a negative viewpoint to a positive position -- and because BOTH
    mirrors would then be compared at the moved point, a gate could keep passing while measuring
    somewhere else entirely.

    The round trip is asserted over the SIGNED 16-BIT map-unit domain, which is the whole of it: a
    wad coordinate is a signed 16-bit int, and vx << 16 only fits the 16.16 wire for |vx| < 2**15.
    Outside that the encoder is still total (it masks, it does not raise) but the value is no longer
    representable -- that is 16.16, not a defect, so it is not asserted."""
    for vx, vy in ((0, 0), (1, -1), (-1056, 3616), (-32768, 32767), (32767, -32768)):
        assert encode_feed_mapunits(vx, vy, 0x30000000) == encode_feed(vx << 16, vy << 16, 0x30000000)
        x, y, _a = decode_state(_state_payload(encode_feed_mapunits(vx, vy, 0)))
        assert (x, y) == (vx << 16, vy << 16), f"map unit ({vx},{vy}) landed at ({x},{y})"
    # Note what this can and cannot see: a masking slip like `(vx & 0xFFFF) << 16` is INVISIBLE on
    # the wire (it produces the same 32 bits for every 16-bit map unit), so the property that has
    # teeth is the DECODED signed value above -- a 16-bit intermediate zeroes it, and an unsigned
    # widening lands it at +4294901760 instead of -65536.


# -- the key byte: both directions, both spellings -----------------------------------------------

def test_keys_round_trip_over_all_256_byte_values():
    """The docstring's claim, as a sweep: bits 5..7 do not exist on EITHER side, so a malformed byte
    reads the same in both mirrors. Two names sharing a bit, or a name added at a bit the fj side
    does not test, stops this being the identity on the low five bits -- and a keypress is then
    silently dropped or duplicated. test_doorcode pins keys_dict at KEY_USE and 0xFF only."""
    defined = KEY_FORWARD | KEY_BACK | KEY_TURN_LEFT | KEY_TURN_RIGHT | max(KEY_NAMES.values())
    assert defined == 0x1F
    assert len(set(KEY_NAMES.values())) == len(KEY_NAMES), "two key names share a bit"
    for b in range(256):
        assert keys_byte(keys_dict(b)) == b & 0x1F, f"byte {b:#04x} did not round trip"
        assert keys_dict(b) == keys_dict(b & 0x1F), f"byte {b:#04x} reads a bit above 4"
        assert set(keys_dict(b)) == set(KEY_NAMES)


def test_the_int_branch_and_the_dict_branch_agree():
    """Both branches are LIVE: scripts/walk_e1m1.py hands encode_feed an int, while the fj gates and
    reference_model speak the dict. If they diverge the host and the oracle press different keys on
    the same frame -- a trajectory split only the cumulative m5_gate would catch, and only after it
    has already gone wrong on frame 0."""
    for b in range(256):
        assert keys_byte(b) & 0x1F == keys_byte(keys_dict(b))
        # ...and the two spellings produce the same wire byte through the encoder itself
        assert encode_feed(0, 0, 0, b)[-1] & 0x1F == encode_feed(0, 0, 0, keys_dict(b))[-1]
    assert keys_byte(0x1FF) == 0xFF, "an int key must be masked to one byte"
    assert keys_byte({}) == 0, "a dict with no names pressed is no keys"
    assert keys_byte({"strafe_left": True, "fire": True}) == 0, "an unknown name must contribute nothing"


def test_each_movement_mask_is_derived_from_its_OWN_key_bit():
    """`hex.if_flags`' mask is a set of NIBBLE VALUES, not a bit mask: mask bit v is set iff nibble
    value v takes the flag-set branch. Re-derive each published mask from its own KEY_* constant --
    NOT via _NIBBLE_MASK, which is what the implementation already does, so a mask bound to the
    wrong nibble index (KEY_BACK_MASK = _NIBBLE_MASK[2]) would still pass. That edit makes the
    program TURN where the oracle WALKS, with no host-side symptom at all; test_doorcode pins
    KEY_USE_MASK, and these four were completely unpinned."""
    pairs = ((KEY_FORWARD, KEY_FORWARD_MASK, "forward"), (KEY_BACK, KEY_BACK_MASK, "back"),
             (KEY_TURN_LEFT, KEY_TURN_LEFT_MASK, "turn_left"),
             (KEY_TURN_RIGHT, KEY_TURN_RIGHT_MASK, "turn_right"))
    for bit, mask, name in pairs:
        k = bit.bit_length() - 1                      # the key's bit index, from the constant itself
        assert bit == 1 << k and KEY_NAMES[name] == bit
        want = sum(1 << v for v in range(16) if v & (1 << (k % 4)))
        assert mask == want, f"{name}: mask {mask:#06x} is not bit {k % 4} of the nibble"
        # wall_renderer formats these as '{:#06x}' into hex.if_flags, so a wider value would emit a
        # mask no 16-value nibble test can mean.
        assert 0 <= mask <= 0xFFFF and f"{mask:#06x}" == f"{mask:#06x}"
    assert len({m for _b, m, _n in pairs}) == 4, "two movement keys share a nibble mask"


def test_every_movement_key_is_live_in_the_oracle_and_use_is_not():
    """Cross-mirror liveness. A rename or typo in KEY_NAMES leaves the fj side emitting that key's
    hex.if_flags mask while the oracle's keys.get(name) reads a name nobody sets -- the key works in
    the program and is DEAD in the oracle, which is a byte-exactness failure costing a full build to
    see. 'use' is the doors mirror's key: doors.door_tic consumes it, step_sim must not."""
    rm = ReferenceModel(Config())
    st = SimState(-27262976, 16777216, 0x20000000, "E1M1")
    idle = rm.step_sim(st, keys_dict(0), scene=None)
    assert idle == st, "no key pressed must move nothing"
    for name, bit in KEY_NAMES.items():
        moved = rm.step_sim(st, keys_dict(bit), scene=None)
        if name == "use":
            assert moved == idle, "'use' is the doors key and must not reach step_sim"
        else:
            assert moved != idle, f"pressing '{name}' changed nothing in the oracle"


# -- the thing table: bindings, positions, visibility --------------------------------------------

def _widen(narrow: bytes) -> bytes:
    """What `stream.emit_bytes4` produces from the 2-byte values the program stores: the same
    little-endian value with two zero high bytes, because nothing ever writes them."""
    return b"".join(narrow[i:i + BINDING_IN_BYTES] + b"\x00" * (BINDING_OUT_BYTES - BINDING_IN_BYTES)
                    for i in range(0, len(narrow), BINDING_IN_BYTES))


def test_the_binding_round_trip_is_deliberately_asymmetric():
    """2 bytes IN (`hex.input 2` fills the 4 nibbles the value occupies), 4 bytes OUT
    (`stream.emit_bytes4` is the emitter this protocol has). A '<I' in the encoder or an '<H' in the
    decoder shifts the WHOLE binding table by one thing: every sprite then binds to another thing's
    subsector -- wrong depth, wrong clipping, wrong light. The asymmetry is exactly what a
    well-meaning 'make these symmetric' cleanup breaks, and only a comment defends it today."""
    assert (BINDING_IN_BYTES, BINDING_OUT_BYTES) == (2, 4)
    xs = [0, 1, 2, 255, 256, 0x1234, 0xFFFE, BINDING_DIRTY]
    narrow = encode_bindings(xs)
    assert len(narrow) == len(xs) * BINDING_IN_BYTES
    assert decode_bindings(_widen(narrow)) == [x & 0xFFFF for x in xs]
    # the decoder really does consume BINDING_OUT_BYTES per entry, not len//2
    assert len(decode_bindings(_widen(narrow))) == len(xs)
    # ...and it reads all FOUR bytes. On the real wire the high two are always zero (nothing writes
    # them), which is precisely why a '<H' decoder keeping the 4-byte stride is invisible against a
    # widened payload -- so pin the DECLARED width directly, which is the half a host test can see.
    assert decode_bindings(struct.pack("<I", 0x00010002)) == [0x00010002]
    assert encode_bindings([]) == b"" and decode_bindings(b"") == []


def test_binding_dirty_survives_encoding_as_an_unmistakable_sentinel():
    """BINDING_DIRTY means 're-locate this one'. The nasty part is that a spurious dirty binding
    leaves the PIXELS correct: it just makes fj re-locate the thing, silently restoring the 27.2M
    ops/frame M14-e removed. A perf regression with byte-exact output is precisely what deg_gate's
    op-count check exists for, and reaching it costs a full build."""
    assert encode_bindings([BINDING_DIRTY]) == b"\xff\xff"
    sentinel = encode_bindings([BINDING_DIRTY])
    assert all(encode_bindings([s]) != sentinel for s in range(0, 0xFFFF)), (
        "an ordinary subsector index encodes to the dirty sentinel")


def test_thing_positions_round_trip_signed_in_both_directions():
    """The thing-table twin of the SimState bug: a sprite at -2**31 read as +2**31 projects from the
    opposite end of the map. The encode-after-decode direction additionally pins the 8-byte stride
    without asserting the magic 8 -- a stride slip renders every thing at its neighbour's position.
    Honest caveat: decode_things has no caller in src/, scripts/ or tests/ today (StreamScreen
    decodes bindings, not positions), so this pins a DECLARED inverse; the module's premise is that
    nothing else may open-code the byte order."""
    w = WadFile.from_path(str(E1M1))
    pos = [(0, 0), (-1, -1), (1, -1), (-(1 << 31), (1 << 31) - 1), ((1 << 31) - 1, -(1 << 31))]
    pos += [(t.x << 16, t.y << 16) for t in list(w.things("E1M1"))[:24]]
    assert decode_things(encode_things(pos)) == pos
    # and the other way round, from arbitrary wire bytes: an unsigned 0x80000000 decodes SIGNED
    assert decode_things(struct.pack("<II", 0x80000000, 0x7FFFFFFF)) == [(-(1 << 31), (1 << 31) - 1)]
    rnd = random.Random(20260911)
    payload = bytes(rnd.randrange(256) for _ in range(8 * 32))
    assert encode_things(decode_things(payload)) == payload
    assert len(encode_things(pos)) == len(pos) * 8
    assert encode_things([]) == b"" and decode_things(b"") == []


def test_a_misaligned_binding_or_thing_block_raises():
    """Silent truncation of a desynced command block is the quiet failure: the host keeps running
    with a short list, so the last things hold LAST frame's binding and drift out of the world with
    no error anywhere. Both raises are real defences, not unreachable glue."""
    for n in (1, BINDING_OUT_BYTES - 1, BINDING_OUT_BYTES + 1, 2 * BINDING_OUT_BYTES + 2):
        with pytest.raises(ValueError):
            decode_bindings(b"\x00" * n)
    for n in (1, 7, 9, 17):
        with pytest.raises(ValueError):
            decode_things(b"\x00" * n)


def test_visibility_is_one_byte_per_flag_in_slot_order():
    """One byte per slot in `vanishable_slots` order -- `hex.input 1` fills the two nibbles the byte
    occupies and the guard tests the low one. Any shape change (packing bits, or emitting 2 bytes to
    'match' the other blocks) shifts every slot, so the WRONG baked things vanish: picked-up items
    reappear and untouched ones disappear. Note scripts/walk_e1m1.py feeds [1] * n, so INTs must be
    accepted as well as bools."""
    assert VIS_IN_BYTES == 1
    flags = [True, False, 1, 0, 2, -1, None, "x"]
    out = encode_visibility(flags)
    assert len(out) == len(flags) * VIS_IN_BYTES
    assert out == bytes(1 if f else 0 for f in flags)
    assert encode_visibility([1] * 7) == b"\x01" * 7          # the live caller's spelling
    assert encode_visibility([]) == b""


# -- the two command-byte registries -------------------------------------------------------------

def _present_protocol_command_bytes():
    """The present-protocol command bytes, read out of tests/fj/stream_screen.py with `ast` rather
    than re-typed here -- a re-typed copy is how two registries in two files drift apart. That file
    imports `flipjump`, so it is PARSED, never imported."""
    src = (ROOT / "tests" / "fj" / "stream_screen.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    named, compared = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, int) and not isinstance(node.value.value, bool):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.startswith("CMD_"):
                    named[t.id] = node.value.value
        # the dispatch tests one command byte inline (CMD_INIT_SCREEN); catch it by shape
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) \
                and node.left.id == "command":
            for c in node.comparators:
                if isinstance(c, ast.Constant) and isinstance(c.value, int):
                    compared.add(c.value)
    return named, compared


def test_the_state_wire_commands_do_not_collide_with_the_present_protocol():
    """The two registries live in different files with no collision check, and they share ONE
    numbering space on the output stream. If a present-protocol command ever takes 0x10 or 0x11,
    StreamScreen mis-frames the stream and every frame decodes as garbage -- discovered only by
    building. This also documents that wireformat.py owns 0x10/0x11."""
    named, compared = _present_protocol_command_bytes()
    # the scan must actually have found the registry, or this test proves nothing (R9)
    assert "CMD_BEGIN_FRAME_STREAM" in named and len(named) >= 8, sorted(named)
    assert compared, "no inline command-byte comparison found; the dispatch moved"
    others = set(named.values()) | compared
    assert STATE_CMD != THING_CMD
    for name, cmd in (("STATE_CMD", STATE_CMD), ("THING_CMD", THING_CMD)):
        assert cmd not in others, f"{name} = {cmd:#04x} collides with the present protocol"
        assert 0 <= cmd <= 0xFF, f"{name} is not one byte"


# -- the magic byte: the one constant a round-trip test is BLIND to ---------------------------
#
# Found by scratchpad/12m/mutcheck.py, not by review. Changing `MAGIC = 0xD0` to 0xD1 left every
# test in this file green: encode writes MAGIC and decode checks MAGIC, so the round-trip stays
# self-consistent at ANY value. A symbol agreeing with itself is exactly what a round-trip proves,
# and exactly what does not matter here -- MAGIC is an ABI constant shared with a program that was
# BUILT from some earlier value of it.


def test_the_wire_magic_byte_is_frozen():
    """MAGIC is a wire ABI constant, not an implementation detail: every `.fjm` ever built baked a
    comparison against the value it had at build time (wall_renderer._state_wire_lines emits two
    `hex.if_flags` nibble tests). A host that changes it talks to an older binary by sending a byte
    that program routes to `bad:`, so the program HALTS IMMEDIATELY and the failure looks like a
    crashed renderer rather than a version mismatch. Changing this deliberately means rebuilding
    every binary and updating this test in the same commit."""
    assert MAGIC == 0xD0


def test_the_magic_byte_cannot_be_mistaken_for_a_byte_the_gate_feeds():
    """The R0 build gate feeds one junk byte (`q`) and REQUIRES the program to reach `bad:` and
    halt, rather than block reading the other 13 bytes and die on EOF. That holds only while MAGIC
    is not that byte -- nor an ASCII decimal digit, which the historical "dec" wire's parser
    accepted as the start of a viewpoint."""
    assert MAGIC != ord("q")
    assert not (MAGIC < 128 and chr(MAGIC).isdigit())
    assert 0 <= MAGIC <= 0xFF


def test_the_emitted_program_tests_exactly_the_magic_byte_this_module_sends():
    """THE CROSS-MIRROR HALF -- what a symbol-vs-symbol test cannot give you.

    The program does not compare a byte to a constant; it branches on two NIBBLES, high then low
    (`hex.if_flags wmagic + dw, 1<<0xD` then `hex.if_flags wmagic, 1<<0x0`). Reconstruct the byte
    the emitted text actually accepts and require it to equal the byte this module actually sends.
    A swapped `>> 4` / `& 0xF`, or a nibble typed by hand, fails here and nowhere else."""
    import re

    from doomfj.wall_renderer import _state_wire_lines
    lines = _state_wire_lines()
    hi = lo = None
    for ln in lines:
        m = re.search(r"hex\.if_flags\s+wmagic\s*\+\s*dw\s*,\s*1<<0x([0-9A-Fa-f])", ln)
        if m:
            hi = int(m.group(1), 16)
        m = re.search(r"hex\.if_flags\s+wmagic\s*,\s*1<<0x([0-9A-Fa-f])", ln)
        if m:
            lo = int(m.group(1), 16)
    assert hi is not None and lo is not None, (
        "the emitted wire prologue no longer tests the magic byte as two nibbles:\n"
        + "\n".join(lines[:6]))
    assert (hi << 4) | lo == MAGIC, (
        "the emitted program accepts 0x%02X but this module sends 0x%02X"
        % ((hi << 4) | lo, MAGIC))
