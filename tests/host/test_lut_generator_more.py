"""Host-side coverage for the parts of `doomfj.lut_generator` that only an ASSEMBLING run touched.

`tests/host/test_lut_generator.py` checks the data-table fallback and a handful of structural
substrings; `tests/host/test_dispatch_tables.py` decodes the per-entry VALUE tables. Everything
below was, until now, proven by nothing cheaper than a 10-45 minute build (`tests/fj/*`, or the
~20-minute `deg_gate`). Each test here encodes an INDEPENDENT truth about the emitted text -- a
stride agreeing with the thing it strides over, a bit order that decodes back to its byte, a
compare chain simulated against the oracle's own predicate -- never a restatement of the emitter.

What breaks in the shipped program if these stop holding:

* `_per_entry_emit_table` -- `HSTRIDE` is written once (9) and the handler body is written
  separately. Drift either way and every dispatch past entry 0 lands MID-handler: `byte.emit` /
  `cm.emit` are how every framebuffer byte leaves the program, so the present path emits garbage.
  Same argument for `_per_entry_table`'s wide-result `hstride = result_nibbles + 1`.
* the emit handler's bit order -- `stl.output_bit (v >> bit) & 1`, lsb-first. Reverse it and every
  byte the program emits comes out bit-reversed.
* `_cmp3_tree` -- the band walk's ENTIRE comparison semantics (skip / emit / emit-and-stop /
  clamp). An inverted arm or an off-by-one draws bands one row early or late, or never terminates.
* `_raw_byte_out` -- the only byte in the band walk that is not a compile-time constant (the
  clamped pair's `vq_hi`). Wrong at the window edge, in every colour that clamps.
* `_byte2bits_loader` -- it loads `vq_lo`/`vq_hi`. A wrong bit->address map means every band
  comparison that frame is against garbage, plus a dispatch op left dirty.
* `generate_bands_walk_fj`'s `pad` -- derived from the LIST COUNT only. `config.BAND_NIBBLES`
  states this as the reason M4's nine-level build can raise the index width for free; coupling the
  two would multiply the switch by 16 and blow the size half of the M6 target (<= 35% of 2^27).
* `generate_w1r_walls_fj` -- the fj wall texture must replay `ReferenceModel.W1R_PATTERNS` /
  `w1r_tier` run for run (R6). Its `cargs` pruning builds the def's parameter list and the call
  site's argument list in two places from one dict -- the fan-out shape CLAUDE.md rule 5 warns
  about, and an arity slip there is an ASSEMBLE-time failure, i.e. one that costs a full build.
* the packed/nibble LUT twins (`zlight`, `yslope`, `slopediv_recip8`) -- two emitters flattening
  the same oracle table independently, or one wired to the wrong `tables.py` function.

R9: the two simulators here (`_run_raw`, `_run_cmp`) and the W1R colour replay each carry a
negative control that mutates real emitted text and requires the check to reject it.
"""
import re

import pytest

from doomfj.config import Config
from doomfj.lut_generator import (
    generate_bands_walk_fj,
    generate_dispatch_table_fj,
    generate_emit_dispatch_table_fj,
    generate_offset_deposit_table_fj,
    generate_packed_lut_fj,
    generate_slopediv_recip8_lut_fj,
    generate_slopediv_recip_lut_fj,
    generate_w1r_walls_fj,
    generate_yslope_lut_fj,
    generate_yslope_packed_lut_fj,
    generate_zlight_lut_fj,
    generate_zlight_packed_lut_fj,
)
from doomfj.reference_model import ReferenceModel as RM
from doomfj.tables import (slopediv_recip8_table, slopediv_recip_table, yslope_table,
                           zlight_table)

NL = chr(10)

# ---------------------------------------------------------------------------
# shared decoders (deliberately independent of the emitters they read)
# ---------------------------------------------------------------------------

_LABEL = re.compile(r"^\s*(\w+):\s*$")
_PACKED = re.compile(r"^\s*;(0x[0-9a-f]+) \* dw\s*$")
_PACKED_DEC = re.compile(r"^;(\d+) \* dw$")
_SWITCH = re.compile(r"^\s*;handlers \+ (\d+)\*(\d+)\*dw\s*$")
_CLEANJ = re.compile(r"^\s*;clean \+ (\d+)\*dw\s*$")
_OUTBIT = re.compile(r"^\s*stl\.output_bit ([01])\s*$")
_RESFLIP = re.compile(r"^\s*wflip \.res\+(\d+)\*dw\+w, (0x[0-9a-fA-F]+)\*dw\s*$")


def _vec_entries(text, nibbles):
    """Decode a `generate_lut_fj` table: one `hex.vec <nibbles>, 0x..` per entry."""
    rx = re.compile(r"^\s*hex\.vec %d, (0x[0-9a-fA-F]+)\s*$" % nibbles)
    return [int(m.group(1), 0) for m in map(rx.match, text.split(NL)) if m]


def _packed_entries(text, nbytes):
    """Decode a packed-byte table: nbytes little-endian `;0x.. * dw` lines per entry."""
    raw = [int(m.group(1), 0) for m in map(_PACKED.match, text.split(NL)) if m]
    assert len(raw) % nbytes == 0, "packed table is not a whole number of entries"
    return [sum(raw[i + k] << (8 * k) for k in range(nbytes))
            for i in range(0, len(raw), nbytes)]


def _split_handlers(text, terminator):
    """Split a `handlers:`..`clean:` block into per-entry op lists.

    Returns [(entry_index_the_handler_cleans_with, ops_including_the_terminator), ...].
    """
    out, cur, seen = [], [], False
    for line in text.split(NL):
        s = line.strip()
        if s == "handlers:":
            seen = True
            continue
        if not seen:
            continue
        if s == "clean:":
            break
        m = terminator.match(line)
        cur.append(line)
        if m:
            out.append((int(m.group(1)), cur))
            cur = []
    assert not cur, "a handler ran off the end of the block"
    return out


# ---------------------------------------------------------------------------
# generate_emit_dispatch_table_fj -- the byte-OUTPUT dispatch (byte.emit / cm.emit)
# ---------------------------------------------------------------------------

class TestEmitDispatchTable:
    def test_switch_stride_equals_the_emitted_handler_length(self):
        """HSTRIDE and the handler body are written in two different places. If they disagree,
        entry d>0 lands mid-handler and emits a spliced byte. So: read the stride OFF the switch
        and the length OFF the handlers, and require the two numbers to be the same."""
        src = generate_emit_dispatch_table_fj("e", [0xA5, 0x01, 0xFF], index_nibbles=1)
        strides = [(int(m.group(1)), int(m.group(2)))
                   for m in map(_SWITCH.match, src.split(NL)) if m]
        assert strides, "no switch entries found -- the parse is wrong, not the emitter"
        assert [d for d, _ in strides] == list(range(len(strides))), \
            "entry d must jump to slot d, not a neighbour's"
        assert len({s for _, s in strides}) == 1, "the switch uses more than one stride"
        stride = strides[0][1]

        handlers = _split_handlers(src, _CLEANJ)
        assert [d for d, _ in handlers] == list(range(len(handlers))), \
            "handler d must clean with ITS OWN index"
        lens = {len(ops) for _, ops in handlers}
        assert len(lens) == 1, "handlers are not all the same length: %s" % sorted(lens)
        assert lens.pop() == stride, (
            "the switch strides by %d but a handler is a different number of ops" % stride)

    def test_handler_bits_decode_lsb_first_back_to_the_value(self):
        """Every framebuffer byte leaves the program through these 8 `stl.output_bit` ops, so the
        bit order IS the encoding. Decode lsb-first and require the original byte; msb-first (or
        an off-by-one shift) cannot also satisfy this for 0x01 / 0x80."""
        values = [0xA5, 0x01, 0x80, 0x00, 0xFF]
        src = generate_emit_dispatch_table_fj("e", values, index_nibbles=1)
        got = []
        for _, ops in _split_handlers(src, _CLEANJ):
            bits = [int(m.group(1)) for m in map(_OUTBIT.match, ops) if m]
            assert len(bits) == 8, "a handler does not emit exactly 8 bits"
            got.append(sum(b << i for i, b in enumerate(bits)))
        assert got[:len(values)] == list(values)
        assert all(v == 0x00 for v in got[len(values):]), "padding entries must emit 0x00"
        assert got[1] == 0x01 and got[2] == 0x80, "the asymmetric pair pins the direction"

    def test_identity_byte_table_is_the_identity(self):
        """The shipped `byte` table is `values=range(256)` -- the run-count emitter. If the
        handler for entry d emitted anything but d, every run length in the picture is wrong."""
        src = generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)
        for d, ops in _split_handlers(src, _CLEANJ):
            bits = [int(m.group(1)) for m in map(_OUTBIT.match, ops) if m]
            assert sum(b << i for i, b in enumerate(bits)) == d, "byte table entry %d" % d


class TestPerEntryValueTableStride:
    """The same stride invariant for the wide-result VALUE tables (`hstride = result_nibbles+1`).
    `test_dispatch_tables.decode_per_entry` reads the handler lines but never checks that the
    switch agrees with them, so a stride bug passes it."""

    @pytest.mark.parametrize("result_nibbles", [2, 3, 6, 8])
    def test_switch_stride_equals_handler_length(self, result_nibbles):
        mask = (1 << (4 * result_nibbles)) - 1
        vals = [(0x123456789ABCDEF0 >> (4 * i)) & mask for i in range(5)]
        src = generate_dispatch_table_fj("v", vals, index_nibbles=1,
                                         result_nibbles=result_nibbles)
        strides = [(int(m.group(1)), int(m.group(2)))
                   for m in map(_SWITCH.match, src.split(NL)) if m]
        assert strides, "wide-result mode must emit a handler-jump switch"
        assert [d for d, _ in strides] == list(range(len(strides)))
        assert len({s for _, s in strides}) == 1
        handlers = _split_handlers(src, _CLEANJ)
        assert [d for d, _ in handlers] == list(range(len(handlers)))
        lens = {len(ops) for _, ops in handlers}
        assert len(lens) == 1, "handlers differ in length: %s" % sorted(lens)
        assert lens.pop() == strides[0][1]
        # ... and the ops really are one flip per result nibble, so the stride is not agreeing by
        # accident with a body that lost a flip and gained something else.
        for d, ops in handlers:
            ps = [int(m.group(1)) for m in map(_RESFLIP.match, ops) if m]
            assert ps == list(range(result_nibbles)), "entry %d flips nibbles %s" % (d, ps)


class TestIndexWidthAndEmptyValues:
    """Build-time refusals. An index too narrow for the padded table silently drops the high bits
    of `idx` at RUNTIME, returning a different entry's value; an empty table dispatches over
    nothing. `collision.py` guards its caller with `list(flat) or [0]` precisely because the
    refusal exists -- if it stopped firing, the next caller that forgets the guard would get a
    silently malformed table instead of a build failure."""

    @pytest.mark.parametrize("gen", ["value", "emit"])
    def test_index_too_narrow_is_refused_at_the_boundary(self, gen):
        # 17 values -> pad 32 -> needs 5 index bits: 2 nibbles are enough, 1 is not.
        vals = list(range(17))
        make = ((lambda n: generate_dispatch_table_fj("t", vals, index_nibbles=n,
                                                      result_nibbles=2))
                if gen == "value" else
                (lambda n: generate_emit_dispatch_table_fj("t", vals, index_nibbles=n)))
        assert "pad 32" in make(2), "the boundary case must be the padded size we think it is"
        with pytest.raises(ValueError) as e:
            make(1)
        assert "index_nibbles" in str(e.value) and "t" in str(e.value)

    @pytest.mark.parametrize("gen", ["value", "emit"])
    def test_empty_values_refused_naming_the_label(self, gen):
        with pytest.raises(ValueError) as e:
            if gen == "value":
                generate_dispatch_table_fj("lnbox", [], index_nibbles=1, result_nibbles=2)
            else:
                generate_emit_dispatch_table_fj("lnbox", [], index_nibbles=1)
        assert "lnbox" in str(e.value)


# ---------------------------------------------------------------------------
# the bands walk: a tiny interpreter for the raw-op subset its handlers use
# ---------------------------------------------------------------------------

_BITIF = re.compile(r"^\s*bit\.if (\w+) \+ (\d+)\*dw, (\w+), (\w+)\s*$")
_JUMP = re.compile(r"^\s*;(\w+)\s*$")
_OUTCHAR = re.compile(r"^\s*stl\.output_char (\d+)\s*$")


def _labels(lines):
    out = {}
    for i, line in enumerate(lines):
        m = _LABEL.match(line)
        if m:
            out.setdefault(m.group(1), i)
    return out


def _run_raw(lines, labels, start, bits, terminals, limit=400):
    """Interpret the bands walk's raw-op handler subset: `bit.if` (the FIRST target is the
    bit==0 one), `;label`, bare labels, `stl.output_bit`, `stl.output_char`, `stl.fret`.
    `bits` maps a bit.vec cell name to its runtime byte.

    Returns (where_it_stopped, outputs, labels_visited)."""
    i, outs, seen = start, [], []
    for _ in range(limit):
        if i >= len(lines):
            return ("FELL-OFF-THE-END", outs, seen)
        line = lines[i]
        m = _LABEL.match(line)
        if m:
            seen.append(m.group(1))
            if m.group(1) in terminals:
                return (m.group(1), outs, seen)
            i += 1
            continue
        m = _BITIF.match(line)
        if m:
            cell, b, t0, t1 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
            assert cell in bits, "bit.if reads %s, which the test did not bind" % cell
            tgt = t1 if (bits[cell] >> b) & 1 else t0
            if tgt in terminals:
                return (tgt, outs, seen)
            assert tgt in labels, "bit.if jumps to unknown label %s" % tgt
            i = labels[tgt]
            continue
        m = _JUMP.match(line)
        if m:
            tgt = m.group(1)
            if tgt in terminals:
                return (tgt, outs, seen)
            assert tgt in labels, "jump to unknown label %s" % tgt
            i = labels[tgt]
            continue
        m = _OUTBIT.match(line)
        if m:
            outs.append(("bit", int(m.group(1))))
            i += 1
            continue
        m = _OUTCHAR.match(line)
        if m:
            outs.append(("char", int(m.group(1))))
            i += 1
            continue
        if line.strip().startswith("stl.fret"):
            return ("FRET", outs, seen)
        return ("UNKNOWN-OP:" + line.strip(), outs, seen)
    return ("NO-TERMINATION", outs, seen)


# Lists chosen so the pair blocks cover both ends of the byte and a mid value, and so two are
# bit-identical (the shared-body path) -- the same discipline tests/fj/test_bands_walk.py uses.
_LISTS = [
    [(5, 0x11), (127, 0x22), (200, 0xAA)],
    [(5, 0x11), (127, 0x22), (200, 0xAA)],
    [(1, 0x01), (255, 0xFE)],
    [(128, 0x80)],
]
_PAIRS = sorted({p for lst in _LISTS for p in lst})


@pytest.fixture(scope="module")
def bands():
    text = generate_bands_walk_fj(_LISTS, index_nibbles=4)
    lines = text.split(NL)
    return lines, _labels(lines)


class TestCmp3Tree:
    """`_cmp3_tree` is the band walk's entire comparison semantics, and the only thing that would
    catch an inverted arm today is deg_gate or an assembling tests/fj run. Simulate the emitted
    MSB-first `bit.if` chain for EVERY runtime value 0..255 against the baked constant."""

    @pytest.mark.parametrize("y2,colour", _PAIRS)
    def test_vq_lo_tree_is_a_true_three_way_compare(self, bands, y2, colour):
        lines, labels = bands
        t = "vpb_pb_%d_%d" % (y2, colour)
        assert t in labels, "no pair block for (%d, %d)" % (y2, colour)
        terms = {t + "_in", t + "_ct"}
        for v in range(256):
            where, _, seen = _run_raw(lines, labels, labels[t] + 1, {"vq_lo": v}, terms)
            # contract: vq_lo < y2 -> process the pair (_in); vq_lo >= y2 -> skip it (_ct)
            want = t + "_in" if v < y2 else t + "_ct"
            assert where == want, "vq_lo=%d vs y2=%d landed on %s" % (v, y2, where)
            assert len(seen) == len(set(seen)), "the chain revisited a label (vq_lo=%d)" % v

    @pytest.mark.parametrize("y2,colour", _PAIRS)
    def test_vq_hi_tree_splits_clamp_stop_and_continue(self, bands, y2, colour):
        lines, labels = bands
        t = "vpb_pb_%d_%d" % (y2, colour)
        start = labels[t + "_in"] + 1
        terms = {t + "_cl", t + "_ls", t + "_em"}
        for v in range(256):
            where, _, seen = _run_raw(lines, labels, start, {"vq_hi": v}, terms)
            # contract (tests/fj/test_bands_walk.py header): y2 > vq_hi -> CLAMP, y2 == vq_hi ->
            # emit and stop, y2 < vq_hi -> emit and continue.
            want = t + "_cl" if v < y2 else (t + "_ls" if v == y2 else t + "_em")
            assert where == want, "vq_hi=%d vs y2=%d landed on %s" % (v, y2, where)
            assert len(seen) == len(set(seen)), "the chain revisited a label (vq_hi=%d)" % v

    def test_the_simulator_rejects_an_inverted_arm(self, bands):
        """NEGATIVE CONTROL (R9): swap the two targets of one `bit.if` in one pair block and the
        sweep above must stop agreeing. A simulator that echoed the emitter would not notice.

        "The swapped chain disagrees" is on its own too weak to be a control: a BROKEN
        `_cmp3_tree` disagrees too, so the assertion stays green exactly when its subject is
        wrecked. (Measured: emitting both arms of a set bit to the same label -- which destroys
        every compare in the band walk -- left the old single assertion passing.) Sweeping the
        UNSWAPPED block as well and requiring it clean makes the swap, and only the swap, the
        thing this test varies.
        """
        lines, _ = bands
        t = "vpb_pb_128_128"
        terms = {t + "_in", t + "_ct"}

        def disagreements(src):
            lb = _labels(src)
            return [v for v in range(256)
                    if _run_raw(src, lb, lb[t] + 1, {"vq_lo": v}, terms)[0]
                    != (t + "_in" if v < 128 else t + "_ct")]

        i = next(n for n, s in enumerate(lines)
                 if s.strip().startswith("bit.if") and (t + "_lo_b") in s)
        m = _BITIF.match(lines[i])
        broken = list(lines)
        broken[i] = "    bit.if %s + %s*dw, %s, %s" % (m.group(1), m.group(2),
                                                       m.group(4), m.group(3))
        clean = disagreements(lines)
        assert not clean, (
            "the UNSWAPPED block already disagrees at vq_lo=%s -- the emitted compare is broken, "
            "so this control would pass for the wrong reason" % clean[:8])
        assert disagreements(broken), (
            "the compare simulator is vacuous -- an inverted arm changed nothing")


class TestRawByteOut:
    """`_raw_byte_out` emits the CLAMPED pair's `vq_hi` -- the one byte in the band walk that is
    not a compile-time constant. Wrong bit order or a dropped bit is a wrong clamp row on every
    clamped band, at the window edge, in every colour that reaches the shared M4 tail."""

    @pytest.mark.parametrize("colour", sorted({c for _, c in _PAIRS}))
    def test_clamp_tail_emits_vq_hi_lsb_first_then_the_colour(self, bands, colour):
        lines, labels = bands
        tail = "vpb_cl_%d" % colour
        assert tail in labels, "no shared clamp tail for colour %d" % colour
        tag = "vpb_clt%d" % colour
        for v in (0x00, 0x01, 0x80, 0xA5, 0x5A, 0xFF, 0x7F, 99):
            where, outs, seen = _run_raw(lines, labels, labels[tail] + 1,
                                         {"vq_hi": v}, set(), limit=800)
            assert where == "FRET", "the clamp tail must end in the shared fret, got %s" % where
            bits = [b for kind, b in outs if kind == "bit"]
            assert len(bits) == 8, "clamp tail emitted %d bits, not 8" % len(bits)
            assert sum(b << i for i, b in enumerate(bits)) == v, "bit order is not lsb-first"
            chars = [c for kind, c in outs if kind == "char"]
            assert chars == [colour], "the clamp tail must follow the byte with its colour"
            # every arm must reconverge on the shared per-bit label, once and in order
            ns = [s for s in seen if s.startswith(tag + "_n")]
            assert ns == ["%s_n%d" % (tag, b) for b in range(8)], \
                "arms skipped or duplicated a bit: %s" % ns

    def test_dropping_a_bit_is_visible(self, bands):
        """NEGATIVE CONTROL (R9): delete the `stl.output_bit` on a TAKEN arm of a clamp tail and
        the round-trip must fail. Proves the decode reads the emitted ops, not the test's input."""
        lines, labels = bands
        tail = "vpb_cl_17"
        # 0xA5 has bit 0 set, so the `_o0` arm is the one that actually runs.
        i = labels["vpb_clt17_o0"] + 1
        assert _OUTBIT.match(lines[i]), "expected an output_bit right after the taken arm"
        broken = lines[:i] + lines[i + 1:]
        blabels = _labels(broken)
        _, outs, _ = _run_raw(broken, blabels, blabels[tail] + 1,
                              {"vq_hi": 0xA5}, set(), limit=800)
        bits = [b for kind, b in outs if kind == "bit"]
        assert (len(bits), sum(b << k for k, b in enumerate(bits))) != (8, 0xA5), (
            "the raw-byte decode is vacuous -- a dropped output_bit changed nothing")
        # ... and the trace must be SHORTER BY EXACTLY ONE. "it no longer decodes to 0xA5" is
        # satisfied by almost any wreckage of `_raw_byte_out`, so on its own it lets the control
        # pass while its subject is broken: dropping the z-arm's `;{tag}_n{b}` jump makes every
        # CLEAR bit fall through and emit twice (12 bits for 0xA5), and the assertion above
        # stayed green. One deleted op = exactly one missing bit is the property that says each
        # arm of the chain contributes one, and only one, emitted bit.
        assert len(bits) == 7, (
            "deleting one TAKEN output_bit left %d bits, not 7 -- the clamp tail's arms are no "
            "longer one emitted bit each" % len(bits))


class TestByte2BitsLoader:
    """`vql_load` / `vqh_load` put the frame's window bytes into `vq_lo` / `vq_hi`. A wrong
    bit->address map means EVERY band comparison that frame is against garbage; an entry that
    cleaned with someone else's index leaves the shared dispatch op dirty."""

    @pytest.mark.parametrize("tag,target", [("vql", "vq_lo"), ("vqh", "vq_hi")])
    def test_each_handler_flips_exactly_the_set_bits_of_its_index(self, bands, tag, target):
        lines, labels = bands
        flip = re.compile(r"^\s*%s \+ (\d+)\*dw \+ dbit;\s*$" % target)
        clean = re.compile(r"^\s*;%s_clean__ \+ (\d+)\*dw\s*$" % tag)
        for v in range(256):
            i = labels["%s_h%d" % (tag, v)] + 1
            got, cleaned = [], None
            while cleaned is None:
                m = clean.match(lines[i])
                if m:
                    cleaned = int(m.group(1))
                    break
                m = flip.match(lines[i])
                assert m, "unexpected op in %s_h%d: %r" % (tag, v, lines[i])
                got.append(int(m.group(1)))
                i += 1
            assert got == [b for b in range(8) if (v >> b) & 1], \
                "%s_h%d flips bits %s" % (tag, v, got)
            assert cleaned == v, "%s_h%d cleans with index %d, not its own" % (tag, v, cleaned)

    @pytest.mark.parametrize("tag", ["vql", "vqh"])
    def test_switch_has_256_entries_each_pointing_at_its_own_handler(self, bands, tag):
        lines, labels = bands
        head = labels["%s_switch__" % tag]
        rx = re.compile(r"^\s*;%s_h(\d+)\s*$" % tag)
        got = []
        i = head + 1
        while i < len(lines):
            m = rx.match(lines[i])
            if not m:
                break
            got.append(int(m.group(1)))
            i += 1
        assert got == list(range(256)), "%s switch is %d entries" % (tag, len(got))
        assert lines[head - 1].strip() == "pad 256"


class TestBandsWalkPadIsIndependentOfIndexWidth:
    """`config.BAND_NIBBLES` states this as the reason M4's nine-level build can raise the index
    width for free -- the table is sized by the LIST COUNT. Coupling the two would multiply the
    switch by 16 and blow the size half of the M6 target (<= 35% of 2^27 words)."""

    def test_only_the_rep_line_changes_between_4_and_5_nibbles(self):
        a = generate_bands_walk_fj(_LISTS, index_nibbles=4).split(NL)
        b = generate_bands_walk_fj(_LISTS, index_nibbles=5).split(NL)
        assert len(a) == len(b), "raising the index width changed the emission LENGTH"
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        assert len(diff) == 1, "expected exactly one differing line, got %d" % len(diff)
        assert a[diff[0]].strip() == "rep(4, i) hex.xor vpb_dsp + 4*i, idx + i*dw"
        assert b[diff[0]].strip() == "rep(5, i) hex.xor vpb_dsp + 4*i, idx + i*dw"

    def test_more_lists_than_the_index_can_address_is_refused(self):
        """Boundary: pad == 16**index_nibbles passes, one list more raises. Silently unreachable
        band ids would be missing floors/ceilings in whole regions of a level with no build
        error -- and the nine-level build is exactly the case that crosses 4 nibbles."""
        ok = generate_bands_walk_fj([[(1, 2)]] * 16, index_nibbles=1)
        assert "pad 16" in ok
        with pytest.raises(ValueError) as e:
            generate_bands_walk_fj([[(1, 2)]] * 17, index_nibbles=1)
        assert "wider index" in str(e.value)


# ---------------------------------------------------------------------------
# generate_w1r_walls_fj -- the randomized wall walkers (R6 mirror of the oracle)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def w1r():
    return generate_w1r_walls_fj(RM.W1R_TIER_BOUNDS, RM.W1R_PATTERNS).split(NL)


def _body_lines(lines, name):
    """The lines of one `def <name> ...` body, header and closing brace included."""
    i = next(n for n, s in enumerate(lines) if s.strip().startswith("def %s " % name))
    j = next(n for n in range(i + 1, len(lines)) if lines[n].strip() == "}")
    return lines[i:j + 1]


def _replay_runs(body, cycles=1):
    """Replay a W1R body's colour state machine and run list: one (len, row, colour) triple per
    run per cycle, in emission order, carrying the colour ACROSS the `;entry` wrap."""
    colour, pend, out = None, None, []
    for _ in range(cycles):
        for line in body:
            s = line.strip()
            if s.startswith("hex.mov 2, cmidx, "):
                colour = s.rsplit(", ", 1)[1]
            elif s.startswith("hex.add_constant 2, ycur, "):
                pend = (int(s.rsplit(", ", 1)[1]), colour)
            elif s.startswith("hex.set 2, cmidx + 2*dw, ") and pend is not None:
                out.append((pend[0], int(s.rsplit(", ", 1)[1]), pend[1]))
                pend = None                 # the l{k} arm repeats the same row; ignore it
    assert pend is None, "a run was started and never given a colormap row"
    return out


_BODIES = [(t, v, win) for t in range(4) for v in range(4) for win in (False, True)]


class TestW1RBodiesReplayThePatterns:
    """R6: the fj wall texture and `ReferenceModel.w1r_runs` read the SAME tuples. A transposed
    tier/group index, a dropped run, or a windowed body diverging from its full-wall twin makes
    the two mirrors draw different walls -- today only deg_gate sees that."""

    @pytest.mark.parametrize("t,v,win", _BODIES)
    def test_run_lengths_and_rows_match_w1r_patterns(self, w1r, t, v, win):
        name = "%s%d_%d" % ("w" if win else "b", t, v)
        got = _replay_runs(_body_lines(w1r, name))
        want = [(ln, row) for ln, row, _ in RM.W1R_PATTERNS[t][v]]
        assert [(ln, row) for ln, row, _ in got] == want, "%s replays %s" % (name, got)

    @pytest.mark.parametrize("t,v,win", _BODIES)
    def test_every_run_gets_the_colour_its_alt_bit_names_across_the_wrap(self, w1r, t, v, win):
        """W1R-2C: the mov is emitted only where consecutive runs CHANGE colour, and the cycle
        relies on `entry:`'s unconditional mov to re-set run 0. Two cycles, with the colour
        carried over the wrap, is what makes the second cycle able to disagree."""
        name = "%s%d_%d" % ("w" if win else "b", t, v)
        pat = RM.W1R_PATTERNS[t][v]
        got = _replay_runs(_body_lines(w1r, name), cycles=2)
        want = ["wall_lit2" if alt else "wall_lit" for _, _, alt in pat] * 2
        assert [c for _, _, c in got] == want, "%s colours %s" % (name, [c for _, _, c in got])

    def test_dropping_the_entry_mov_breaks_the_wrap(self, w1r):
        """NEGATIVE CONTROL (R9) for the optimization the docstring calls out: without the
        unconditional `entry:` mov, the first run of each cycle inherits the PREVIOUS cycle's
        shade, so tall walls (which cycle) get a wrong band and short walls do not."""
        pat = RM.W1R_PATTERNS[1][3]
        assert pat[0][2] != pat[-1][2], "b1_3 must wrap across a colour change to be sensitive"
        body = _body_lines(w1r, "b1_3")
        i = next(n for n, s in enumerate(body) if s.strip().startswith("hex.mov 2, cmidx, "))
        broken = body[:i] + body[i + 1:]
        got = [c for _, _, c in _replay_runs(broken, cycles=2)]
        want = ["wall_lit2" if alt else "wall_lit" for _, _, alt in pat] * 2
        assert got != want, "the colour replay is vacuous -- a dropped mov changed nothing"


class TestW1RBodyArity:
    """The `cargs` pruning (a body only takes the colour params it references) builds the def's
    parameter list and the call site's argument list in two different places from one dict --
    CLAUDE.md rule 5's fan-out shape. A mismatch is an ASSEMBLE-time failure, i.e. one that
    currently costs a full 10-45 minute build to discover."""

    def test_all_32_defs_and_call_sites_agree_in_arity_and_names(self, w1r):
        defs, calls = {}, {}
        for line in w1r:
            m = re.match(r"^\s*def ([bw]\d_\d) (.*?) @", line)
            if m:
                defs[m.group(1)] = [p.strip() for p in m.group(2).split(",")]
            m = re.match(r"^\s*\.([bw]\d_\d) (.*)$", line)
            if m:
                calls[m.group(1)] = [p.strip() for p in m.group(2).split(",")]
        assert len(defs) == 32 and len(calls) == 32, \
            "expected 32 bodies and 32 call sites, got %d/%d" % (len(defs), len(calls))
        assert set(defs) == set(calls)
        for name in sorted(defs):
            assert defs[name] == calls[name], (
                "%s: def takes %s, the call site passes %s" % (name, defs[name], calls[name]))
            assert all(p for p in defs[name]), "%s has an EMPTY parameter slot" % name

    @pytest.mark.parametrize("t,v,win", _BODIES)
    def test_a_body_declares_exactly_the_colour_params_it_references(self, w1r, t, v, win):
        """An unused colour label is a werror; a referenced-but-undeclared one is an unknown
        label. Both only show up when the assembler runs."""
        name = "%s%d_%d" % ("w" if win else "b", t, v)
        body = _body_lines(w1r, name)
        params = [p.strip()
                  for p in re.match(r"^\s*def \S+ (.*?) @", body[0]).group(1).split(",")]
        used = {c for _, _, c in _replay_runs(body)}
        for lit in ("wall_lit", "wall_lit2"):
            assert (lit in params) == (lit in used), \
                "%s: %s declared=%s used=%s" % (name, lit, lit in params, lit in used)


_HEXCMP = re.compile(r"^\s*hex\.cmp \d+, (\w+), (\w+), (\w+), (\w+), (\w+)\s*$")
_CELL = re.compile(r"^\s*(\w+): hex\.vec \d+, (\d+)\s*$")
_TERMS = {"d%d_%d" % (t, v) for t in range(4) for v in range(4)}


def _run_cmp(lines, labels, start, values, terminals, limit=64):
    """Interpret the W1R selection tree: `hex.cmp n, a, b, lt, eq, gt` over named cells."""
    i = start
    for _ in range(limit):
        line = lines[i]
        m = _LABEL.match(line)
        if m:
            if m.group(1) in terminals:
                return m.group(1)
            i += 1
            continue
        m = _HEXCMP.match(line)
        assert m, "unexpected op in the selection tree: %r" % line
        a, b = values[m.group(1)], values[m.group(2)]
        tgt = m.group(3) if a < b else (m.group(4) if a == b else m.group(5))
        if tgt in terminals:
            return tgt
        i = labels[tgt]
    return "NO-TERMINATION"


def _tree_of(lines, sel):
    """The selection tree of ONE walker: (its lines, its label map, tree start, its BAKED cells).

    Scoped to the def, because `walk` and `walk_win` use the SAME macro-local label names (q1, r0,
    d0_0 ...): a whole-file label map would silently resolve walk_win's jumps into walk's tree, and
    the one-sided edit this test exists to catch would then be invisible.

    The `tb1/tb2/tb3` and `g4/g8/g12` constants are read OUT of the emitted `hex.vec n, k` cells,
    never assumed -- that is what makes a hardcoded tier bound visible.
    """
    body = _body_lines(lines, "walk" if sel == "wlen" else "walk_win")
    start = next(n for n, s in enumerate(body)
                 if s.strip().startswith("hex.cmp 2, %s, tb1," % sel))
    consts = {m.group(1): int(m.group(2)) for m in map(_CELL.match, body) if m}
    return body, _labels(body), start, consts


class TestW1RSelectionTree:
    """The tier/group tree must mirror `ReferenceModel.w1r_tier` and the oracle's `(key >> 2) & 3`
    group pick, with the W1R-LOD per-tier key (gxor for tiers 0-1, gnrow for 2, gnrow3 for 3).
    `walk` and `walk_win` build it twice from the same helper, so a one-sided edit is plausible."""

    @pytest.mark.parametrize("sel,bounds", [("wlen", RM.W1R_TIER_BOUNDS), ("wl2", (7, 21, 55)),
                                            ("wlen", (7, 21, 55)), ("wl2", RM.W1R_TIER_BOUNDS)])
    def test_tier_pick_mirrors_the_oracle_for_its_own_bounds(self, sel, bounds):
        """The bounds are the PARAMETER, not a baked literal: passing bounds other than the
        oracle's must move the boundary, which is what makes this able to fail (R9)."""
        lines, labels, start, consts = _tree_of(
            generate_w1r_walls_fj(bounds, RM.W1R_PATTERNS).split(NL), sel)
        b1, b2, b3 = bounds
        for wlen in range(1, 70):
            # the simulation runs on the BAKED constants; the expectation is the bounds we PASSED
            vals = dict(consts, gxor=0, gnrow=0, gnrow3=0)
            vals[sel] = wlen
            got = _run_cmp(lines, labels, start, vals, _TERMS)
            want = 0 if wlen < b1 else 1 if wlen < b2 else 2 if wlen < b3 else 3
            assert got.startswith("d%d_" % want), \
                "%s=%d picked %s, bounds %s" % (sel, wlen, got, bounds)
            if tuple(bounds) == tuple(RM.W1R_TIER_BOUNDS):
                assert want == RM.w1r_tier(wlen), \
                    "the emitted tree disagrees with ReferenceModel.w1r_tier at wlen=%d" % wlen

    @pytest.mark.parametrize("sel", ["wlen", "wl2"])
    def test_group_pick_reads_the_tiers_own_lod_key(self, w1r, sel):
        """Each tier's key is bound to a DIFFERENT value, so reading the wrong one lands on a
        different group -- a swapped LOD key stops texel width scaling with distance on the fj
        side only. Also pins the 3-cmp decode as the oracle's `(key >> 2) & 3`."""
        lines, labels, start, consts = _tree_of(w1r, sel)
        b1, b2, b3 = RM.W1R_TIER_BOUNDS
        wlen_of = {0: b1 - 1, 1: b1, 2: b2, 3: b3}
        key_of = {0: "gxor", 1: "gxor", 2: "gnrow", 3: "gnrow3"}
        for t in range(4):
            for n in range(16):
                decoy = (n + 8) % 16
                assert (decoy >> 2) & 3 != (n >> 2) & 3, "the decoy must pick another group"
                vals = dict(consts, gxor=decoy, gnrow=decoy, gnrow3=decoy)
                vals[key_of[t]] = n
                vals[sel] = wlen_of[t]
                got = _run_cmp(lines, labels, start, vals, _TERMS)
                assert got == "d%d_%d" % (t, (n >> 2) & 3), \
                    "tier %d, %s=%d picked %s" % (t, key_of[t], n, got)

    def test_the_shipped_call_bakes_the_oracles_bounds(self):
        """Feature wiring: the emitter is parameterized, so the thing that keeps the fj tier
        boundary equal to `w1r_tier` is the CALL passing the oracle's own tuple."""
        import inspect

        from doomfj import wall_renderer
        assert "generate_w1r_walls_fj(rm.W1R_TIER_BOUNDS, rm.W1R_PATTERNS)" \
            in inspect.getsource(wall_renderer)


# ---------------------------------------------------------------------------
# packed / nibble LUT twins -- two emitters flattening one oracle table
# ---------------------------------------------------------------------------

class TestPackedAndNibbleTwinsAgree:
    def test_zlight_packed_and_nibble_carry_the_same_sequence(self):
        """The device DMA rasterizer reads the packed form; `hex.read_table` reads the nibble
        form. If they disagree, floors light differently depending on which path drew them."""
        cfg = Config()
        ncm = 32
        flat = [row for lvl in zlight_table(cfg.VIEW_W, ncm) for row in lvl]
        packed = _packed_entries(generate_zlight_packed_lut_fj("z", cfg.VIEW_W, ncm), 1)
        nibble = _vec_entries(generate_zlight_lut_fj("z", cfg.VIEW_W, ncm), 2)
        assert len(flat) > 0 and packed == nibble == flat
        assert all(0 <= v < ncm for v in packed), "a zlight entry is not a colormap row"

    def test_yslope_packed_round_trips_and_matches_the_nibble_form(self):
        """`plane.build_bands` walks this with ONE incrementing pointer (3x read_byte_and_inc per
        row), so a stride slip shifts every later row's distance -- floors wrong from that row
        down. This emitter hand-rolls its own encoding (decimal, no indent), so it can drift from
        the form the reader expects."""
        cfg = Config()
        want = yslope_table(cfg.VIEW_W, cfg.VIEW_H)
        text = generate_yslope_packed_lut_fj("yslp", cfg.VIEW_W, cfg.VIEW_H)
        raw = [int(m.group(1)) for m in map(_PACKED_DEC.match, text.split(NL)) if m]
        assert len(raw) == 3 * cfg.VIEW_H, "expected 3 bytes per row, got %d lines" % len(raw)
        got = [sum(raw[3 * y + k] << (8 * k) for k in range(3)) for y in range(cfg.VIEW_H)]
        assert got == want
        assert got == _vec_entries(generate_yslope_lut_fj("yslp", cfg.VIEW_W, cfg.VIEW_H), 8)
        assert len(set(got)) > 1, "a constant table would round-trip under any byte order"

    def test_slopediv_recip8_is_the_shifted_twin_not_a_copy_of_its_neighbour(self):
        """The classic copy-paste: the 8-twin emitter calling `slopediv_recip_table()`. The coarse
        `proj.slope_div` would then read reciprocals 8x too small -- a whole-picture defect from a
        one-word edit."""
        base = _packed_entries(generate_slopediv_recip_lut_fj("r"), 3)
        eight = _packed_entries(generate_slopediv_recip8_lut_fj("r8"), 3)
        assert base == slopediv_recip_table(), "the plain emitter drifted from its SSOT"
        assert eight == slopediv_recip8_table(), "the <<3 emitter drifted from its SSOT"
        assert eight == [v << 3 for v in base], "recip8 is not the <<3-prefolded twin"
        assert eight != base, "the two emitters returned the SAME table -- one is miswired"
        assert max(eight) < (1 << 24), "recip8 must still fit 3 packed bytes"


class TestGeneratePackedLutFj:
    """A truncated pack in `collision.py`'s lnbox/lnrow/bkoff/bklin tables is wrong blockmap line
    data -- the player walking into or through walls (the failure mode that WITHDREW a measured
    op-count in CLAUDE.md)."""

    def test_oversized_value_is_refused_naming_the_index(self):
        with pytest.raises(ValueError) as e:
            generate_packed_lut_fj("lnbox", [0, 1, 1 << 16], 2)
        assert "lnbox[2]" in str(e.value)

    @pytest.mark.parametrize("nbytes", [1, 2, 3, 4])
    def test_entries_are_nbytes_consecutive_little_endian_slots(self, nbytes):
        top = (1 << (8 * nbytes)) - 1
        vals = [0, 1, top, top // 3, 0x0102030405 & top]
        text = generate_packed_lut_fj("t", vals, nbytes)
        raw = [int(m.group(1), 0) for m in map(_PACKED.match, text.split(NL)) if m]
        assert len(raw) == nbytes * len(vals), "wrong number of byte slots"
        assert _packed_entries(text, nbytes) == vals
        # little-endian, said explicitly: slot 0 of entry 2 (all-ones) is its LOW byte
        assert raw[nbytes * 2] == top & 0xFF


class TestOffsetDepositTable:
    """A missing +4 offset lands both nibbles on the low one -- every pixel byte loses its high
    nibble. The existing host test asserts four substrings; nothing checked the identity map or
    the demux stride."""

    def test_both_nibble_switches_are_the_identity_map_at_their_own_offset(self):
        src = generate_offset_deposit_table_fj("dep").split(NL)
        rx = re.compile(r"^\s*stl\.wflip_macro (\.acc\+4\+w|\.acc\+w),\s+(0x[0-9a-f]+)\*dw, "
                        r"clean_(lo|hi)\+(\d+)\*dw\s*$")
        seen = {"lo": [], "hi": []}
        for line in src:
            m = rx.match(line)
            if m:
                seen[m.group(3)].append((m.group(1), int(m.group(2), 0), int(m.group(4))))
        for half, target in (("lo", ".acc+w"), ("hi", ".acc+4+w")):
            rows = seen[half]
            assert len(rows) == 16, "%s switch has %d entries" % (half, len(rows))
            assert all(t == target for t, _, _ in rows), \
                "%s switch does not flip into %s" % (half, target)
            assert [(v, d) for _, v, d in rows] == [(d, d) for d in range(16)], \
                "%s switch is not the identity nibble map" % half

    def test_demux_stride_matches_its_three_op_handlers(self):
        src = generate_offset_deposit_table_fj("dep").split(NL)
        sw = re.compile(r"^\s*;demux_handlers \+ (\d+)\*(\d+)\*dw\s*$")
        entries = [(int(m.group(1)), int(m.group(2))) for m in map(sw.match, src) if m]
        assert [v for v, _ in entries] == list(range(256))
        assert {s for _, s in entries} == {3}, "the demux switch stride is not 3"

        lo = re.compile(r"^\s*wflip \.reg\+0\*dw\+w, (0x[0-9a-f]+)\*dw\s*$")
        hi = re.compile(r"^\s*wflip \.reg\+1\*dw\+w, (0x[0-9a-f]+)\*dw\s*$")
        end = re.compile(r"^\s*;demux_clean \+ (\d+)\*dw\s*$")
        i = next(n for n, s in enumerate(src) if s.strip() == "demux_handlers:") + 1
        for v in range(256):
            ops = src[i:i + 3]
            i += 3
            a, b, c = lo.match(ops[0]), hi.match(ops[1]), end.match(ops[2])
            assert a and b and c, "demux handler %d is not 3 ops: %r" % (v, ops)
            assert int(a.group(1), 0) == (v & 0xF) and int(b.group(1), 0) == (v >> 4), \
                "demux handler %d sets the wrong nibbles" % v
            assert int(c.group(1)) == v, "demux handler %d cleans with %s" % (v, c.group(1))
