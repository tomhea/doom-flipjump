"""`wall_renderer`'s PURE HELPERS -- the parts of the emitter that can be proved in milliseconds.

Roughly 700 of this module's statements are `emit_wall_renderer` and the closures it reaches; they
need a compiled map, a colormap and a scene, and several return multi-megabyte baked text whose
only meaning is the address layout of an assembled image. Those are the build gates' job. What is
left is a ring of small, pure, text-producing helpers -- and they had no host coverage at all,
which matters because each of them fails in a way that costs a WHOLE BUILD to discover:

  * `window_chrome_fj` (brand new, zero tests anywhere) -- an fj parse error in the icon macro, or
    a missing-lump crash in the prelude. The first version of it DID die at generated line 371,074
    after a 34-minute assembly because N `stl.output_char`s were joined onto one line.
  * `write_program_files` -- "ORDER IS THE CONTRACT". fj top-level labels are global, so a
    reordered, renamed or dropped part assembles into a program whose every baked address is wrong.
  * `_ABLATE_MODES` -- a declared mode with no consumer is a measurement tier that silently renders
    the FULL program and lies about the price, the exact pattern the "tsprobe"/"tsmark" retirement
    removed.
  * `TIERS` -- `emit_wall_renderer` asserts menu=>standalone and standalone=>player_sim, but only
    AFTER the emit has begun, so an impossible row is found minutes in instead of in one second.
  * `_seg_xorby_block` / `_seg_xorby_use` -- the xor involution. A CLEAR that is not
    character-identical to its SET leaves the per-seg registers dirty and every seg after the first
    bakes onto non-zero registers.
  * `_int_part_lines` -- expanded six-plus times per program with different tags; a hardcoded label
    is a duplicate global definition, i.e. an assemble failure.
  * `_player_sim_lines` / `_standalone_input_lines` / `_state_wire_lines` -- the fj half of a
    two-language mirror against `doomfj.wireformat` and `reference_model.step_sim`. A swapped key
    mask or a sign flip shows up only as a cumulative trajectory drift in `scratchpad/m5_gate.py`.
  * `_menu_lines`, `_band_pair_lists`, `hoisted_scratch_decls`, `map_has_sky`, `_spr_nlow`, `_pfx`
    -- bank-order, label-uniqueness and label-alphabet invariants, all of them one-second checks
    standing in for half-hour builds.

NOTHING HERE ASSEMBLES ANYTHING. The whole file is host-side text and arithmetic.
"""
import ast
import inspect
import re
import struct
from pathlib import Path

import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj import wall_renderer as WR
from doomfj import wireformat as WF
from doomfj.config import Config
from doomfj.menu import palette_colours, stream as menu_stream
from doomfj.reference_model import (ANGLE_TURN, FORWARD_MOVE, ReferenceModel,
                                    DEG_SPR_LOWRES_H, SPRITE_HEIGHT_BUCKETS,
                                    sprite_bucket_height)
from doomfj.wad import WadFile
from doomfj.wall_renderer import (DEFAULT_MENU, DEFAULT_MENU_SELECTED, MAX_BANDS,
                                  STANDALONE_POLLS, STANDALONE_SCRATCH_DECLS, TIERS,
                                  WINDOW_ICON_ART, WINDOW_ICON_INDEX,
                                  WINDOW_ICON_SIZE, WINDOW_TITLE,
                                  _ABLATE_MODES, _band_pair_lists, _int_part_lines,
                                  _lines_mode_decls, _menu_lines, _pfx, _player_sim_lines,
                                  _seg_xorby_block, _seg_xorby_use, _spr_nlow,
                                  _standalone_input_lines, _state_wire_lines,
                                  hoisted_scratch_decls, map_has_sky, tier_flags,
                                  window_chrome_fj, write_program_files)

FIX = Path("tests/fixtures")
ASSETS = FIX / "freedoom_assets.wad"
PRESENT_FJ = Path("src/fj/present.fj")


# -- window chrome: the baked DOOM wordmark ---------------------------------------------------
#
# The icon used to be decoded from a WAD lump and centred at emit time, and this section tested
# that decoding. It is now GENERATED from `WINDOW_ICON_ART`, a 32x32 ASCII picture in the emitter,
# so there is no lump, no centring and no wad -- which is why every tier gets an icon now,
# including `render`, which passes no sprite wad and used to ship title-only.


def _icon_indices(macro_lines):
    return [int(m.group(1)) for m in
            (re.match(r"\s*stl\.output_char (\d+)$", ln) for ln in macro_lines) if m]


def _feed_device(payload):
    """The device the standalone binary presents to, fed the same bytes present.fj emits."""
    screen = InMemoryScreen()
    for data in (bytes([0x01, 160 & 0xFF, 160 >> 8, 100 & 0xFF, 100 >> 8, 8, 0, 1]), payload):
        for byte in data:
            for i in range(8):
                screen.write_bit(bool((byte >> i) & 1))
    return screen


def test_the_icon_art_is_exactly_one_square_of_pixels():
    """A row that lost or gained a character shifts every pixel after it and the art shears. The
    emitter asserts this at import; the test is here so the failure names itself."""
    assert len(WINDOW_ICON_ART) == WINDOW_ICON_SIZE ** 2
    assert set(WINDOW_ICON_ART) <= {".", "#"}, sorted(set(WINDOW_ICON_ART) - {".", "#"})


def test_the_icon_needs_no_wad_at_all():
    """THE POINT OF BAKING IT. `window_chrome_fj` takes no arguments: the `render` tier resolves
    `sprite_wad=None` and used to get a title and no icon, and the cut-down test fixtures have no
    sprites at all. A generated icon cannot be missing."""
    macro, calls = window_chrome_fj()
    assert macro and calls
    assert calls[0].startswith("present.set_window_title")
    assert "doom_window_icon" in calls


def test_every_icon_pixel_gets_its_own_line():
    """⚠ fj HAS NO STATEMENT SEPARATOR. N `stl.output_char`s joined by spaces is a parse error --
    which is how the first version of this died, at generated line 371,074, after a 34-minute
    assembly. One statement per line, 1,024 of them, no exceptions."""
    macro, _calls = window_chrome_fj()
    emitted = [ln for ln in macro if "stl.output_char" in ln]
    assert len(emitted) == WINDOW_ICON_SIZE ** 2
    assert all(ln.count("stl.output_char") == 1 for ln in emitted)


def test_the_emitted_pixels_are_the_art():
    """Re-derive the pixel stream from the ASCII independently and require the emitter to agree.
    A transposed loop, an off-by-one row slice or a swapped ink/space mapping fails here."""
    macro, _calls = window_chrome_fj()
    want = [WINDOW_ICON_INDEX if c == "#" else 0 for c in WINDOW_ICON_ART]
    assert _icon_indices(macro) == want


def test_the_icon_uses_only_transparent_and_one_ink_colour():
    """The reference is a single flat colour over 666 of its 707 ink pixels; the icon mirrors that.
    Index 0 is the device's transparency key, so ink must never be 0 or the letters vanish."""
    macro, _calls = window_chrome_fj()
    assert set(_icon_indices(macro)) == {0, WINDOW_ICON_INDEX}
    assert WINDOW_ICON_INDEX != 0


def test_the_macro_the_prelude_calls_is_the_macro_the_block_defines():
    """A call to a macro that was never defined is an assemble failure 30 minutes in."""
    macro, calls = window_chrome_fj()
    defined = [ln for ln in macro if ln.startswith("def ")]
    assert len(defined) == 1, defined
    name = defined[0].split()[1].rstrip(" {")
    assert name in calls, (name, calls)


def test_the_title_packing_is_what_present_fj_unpacks():
    """Round-trip through the REAL device. `present.set_window_title` emits
    `rep(len, i) stl.output_char (text >> (8*i)) & 0xff`, so the packed integer is
    least-significant BYTE first and `len` is the utf-8 byte count -- two independent numbers that
    nothing else pins together."""
    _macro, calls = window_chrome_fj()
    call = next(c for c in calls if c.startswith("present.set_window_title"))
    big, n = call.split(None, 1)[1].split(",")
    big, n = int(big, 16), int(n)
    assert n == len(WINDOW_TITLE.encode("utf-8"))
    assert bytes((big >> (8 * i)) & 0xFF for i in range(n)).decode("utf-8") == WINDOW_TITLE


def test_the_device_reads_the_emitted_indices_as_the_icon():
    """End to end through the real InMemoryScreen: the 0x13 command, the two size bytes, then the
    pixels. If the header and the payload ever disagree the device desynchronises and every later
    command is garbage."""
    macro, _calls = window_chrome_fj()
    n = WINDOW_ICON_SIZE
    screen = _feed_device(bytes([0x13, n, n]) + bytes(_icon_indices(macro)))
    assert screen.window_icon is not None
    w, h, idx = screen.window_icon
    assert (w, h) == (n, n)
    assert idx == [WINDOW_ICON_INDEX if c == "#" else 0 for c in WINDOW_ICON_ART]


def test_the_present_macros_the_chrome_calls_exist_with_that_arity():
    """The emitter writes fj text; nothing type-checks it until the assembler does, 30 minutes in."""
    src = PRESENT_FJ.read_text(encoding="utf-8")
    for name, arity in (("set_window_title", 2), ("set_window_icon_header", 2)):
        m = re.search(r"def\s+%s\s+([^{]*)\{" % name, src)
        assert m, "present.fj no longer defines %s" % name
        assert len([a for a in m.group(1).split(",") if a.strip()]) == arity


# -- THE BUG THIS SECTION EXISTS TO PREVENT ---------------------------------------------------
#
# The chrome was emitted into the PRELUDE, and the prelude is not boot-only: the M1 self-reset
# jumps to `__hot_end`, which sits immediately BEFORE it, so the prelude runs on EVERY FRAME. The
# title and 1,024 icon pixels were re-sent 35 times a second -- MEASURED at 8,440 ops and 0.57 ms
# per frame for a window decoration that cannot change. The docstring meanwhile claimed "Boot-only
# ... ZERO ops on the frame metric".
#
# Checked statically, against the emitter's source: building the parts for real costs a full emit.

def test_the_window_chrome_is_emitted_before_the_resets_landing_point():
    """The chrome belongs in the ENTRY part, ahead of the `;__hot_end` jump. Anything after that
    label is re-entered by the reset once per frame."""
    src = inspect.getsource(WR.emit_wall_renderer)
    entry = src[src.index('("entry", ['):]
    entry = entry[:entry.index('("tables", [')]
    assert "*_chrome_calls," in entry, (
        "the window chrome is no longer emitted into the entry part -- if it moved to the prelude "
        "it now costs 8,440 ops on EVERY frame, which is the bug this test exists for")
    assert "*hotdata[:1]," in entry
    assert entry.index("*_chrome_calls,") < entry.index("*hotdata[:1],"), (
        "the chrome is emitted AFTER the `;__hot_end` jump, so it never runs at boot")


def test_the_prelude_does_not_carry_the_chrome():
    """The other half of the same property, stated where a reader of the prelude would look."""
    src = inspect.getsource(WR.emit_wall_renderer)
    line = next(ln for ln in src.split("\n") if ln.strip().startswith("prelude = "))
    assert "_chrome_calls" not in line, (
        "the chrome is back in the per-frame prelude: " + line.strip())


# -- the ablate registry ---------------------------------------------------------------------------

def _ablate_modes_used(source: str) -> set:
    """Every string literal the emitter tests against the name `ablate` -- `"x" in ablate`,
    `"x" not in ablate`, and `ablate & {...}`."""
    used = set()

    class _Scan(ast.NodeVisitor):
        def visit_Compare(self, node):
            for op, cmp in zip(node.ops, node.comparators):
                if (isinstance(op, (ast.In, ast.NotIn)) and isinstance(cmp, ast.Name)
                        and cmp.id == "ablate" and isinstance(node.left, ast.Constant)
                        and isinstance(node.left.value, str)):
                    used.add(node.left.value)
            self.generic_visit(node)

        def visit_BinOp(self, node):
            if isinstance(node.op, ast.BitAnd):
                for a, b in ((node.left, node.right), (node.right, node.left)):
                    if isinstance(a, ast.Name) and a.id == "ablate":
                        for elt in getattr(b, "elts", []):
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                used.add(elt.value)
            self.generic_visit(node)

    _Scan().visit(ast.parse(source))
    return used


# This test found four DECLARED modes with no Python consumer -- `colstub`, `noflush`, `pass2`,
# `planes` -- and listed them so a NEW orphan would fail rather than quietly join them. All four
# were then RETIRED (2026-09-11): `planes` and `pass2` were the dangerous pair, advertised in
# `emit_wall_renderer`'s docstring as working knobs while `assert ablate <= _ABLATE_MODES` accepted
# them and nothing read them, so `ablate={"planes"}` rendered the FULL program and priced the
# visplane pass at zero. Same failure shape as the "tsprobe"/"tsmark" arm retired the same day.
#
# The allowlist is now EMPTY, and keeping it empty is the point: a mode may not be declared without
# an arm that reads it. If you are adding one, add its `in ablate` consumer in the same commit.
KNOWN_ORPHAN_ABLATE_MODES = frozenset()


def test_no_ablate_mode_is_used_without_being_declared():
    """The clean direction today: an arm whose name is missing from the registry is rejected by
    `assert ablate <= _ABLATE_MODES` -- i.e. the measurement run dies AFTER the setup, not before
    it."""
    assert _ablate_modes_used(inspect.getsource(WR)) - set(_ABLATE_MODES) == set()


def test_the_set_of_ablate_modes_with_no_consumer_has_not_grown():
    """A declared mode with no `in ablate` arm renders the FULL program while claiming to ablate."""
    orphans = set(_ABLATE_MODES) - _ablate_modes_used(inspect.getsource(WR))
    assert orphans == set(KNOWN_ORPHAN_ABLATE_MODES), (
        "ablate modes with no consumer changed: %r. A new one is a tier that silently lies; a "
        "retired one should come off KNOWN_ORPHAN_ABLATE_MODES." % sorted(orphans))


def test_the_ablate_scanner_can_fail():
    """R9 negative control -- a checker quoted as evidence must reject real defects. The scanner is
    shown sources that DO use a mode and sources that only look like they do."""
    assert _ablate_modes_used("if 'segstub' in ablate: pass") == {"segstub"}
    assert _ablate_modes_used("if 'segstub' not in ablate: pass") == {"segstub"}
    assert _ablate_modes_used("x = ablate & {'pass1', 'noproj'}") == {"pass1", "noproj"}
    assert _ablate_modes_used("if 'segstub' in other: pass") == set()
    assert _ablate_modes_used("segstub = 1") == set()


# -- the tier registry -----------------------------------------------------------------------------

def test_every_tier_row_satisfies_the_emitters_own_preconditions():
    """`emit_wall_renderer` asserts `not standalone or player_sim` and `not menu or standalone`,
    but only after the emit has started -- so a new TIERS row that can never build is discovered
    minutes into a run instead of here, in a millisecond."""
    for tier in sorted(TIERS):
        flags = tier_flags(tier)
        assert not flags["menu"] or flags["standalone"], (
            "%s: menu=True is a standalone-tier frame producer" % tier)
        assert not flags["standalone"] or flags["player_sim"], (
            "%s: a standalone binary has no host to move the player" % tier)


# -- write_program_files: ORDER IS THE CONTRACT ----------------------------------------------------

SHIPPED_PARTS = ["entry", "tables", "main", "segconsts", "walk", "state", "banks"]


def test_the_written_files_are_the_parts_in_emit_order(tmp_path):
    """fj top-level labels are global, so N files assembled in this order are exactly their
    concatenation. Sorting, globbing or dropping one assembles a program whose every baked address
    constant is wrong -- and it still assembles, which is why this has to be checked here.

    Read back in TEXT mode deliberately: `write_text` translates newlines, so the files on this box
    are CRLF and the equivalence that matters is the character content plus the order."""
    parts = [(name, "// part %s\n;%s_label\n" % (name, name)) for name in SHIPPED_PARTS]
    paths = write_program_files(parts, tmp_path / "generated", "E1M1")
    assert [p.name for p in paths] == ["e1m1_%02d_%s.fj" % (i, n)
                                       for i, (n, _) in enumerate(parts)]
    assert "".join(p.read_text(encoding="utf-8") for p in paths) == "".join(t for _, t in parts)


def test_a_lexicographic_sort_of_the_directory_reproduces_the_emit_order(tmp_path):
    """Several scratchpad tools glob the generated dir. The zero-padded NN is what makes that
    survivable -- an unpadded index puts part 10 between 1 and 2."""
    parts = [(name, "") for name in SHIPPED_PARTS]
    paths = write_program_files(parts, tmp_path / "generated", "E1M1")
    assert sorted(p.name for p in paths) == [p.name for p in paths]
    assert all(re.fullmatch(r"e1m1_\d\d_[a-z0-9_]+\.fj", p.name) for p in paths)


def test_a_missing_output_directory_is_created(tmp_path):
    outdir = tmp_path / "no" / "such" / "generated"
    assert not outdir.exists()
    paths = write_program_files([("entry", "x")], outdir)
    assert paths and paths[0].parent == outdir


def test_non_ascii_in_a_part_round_trips(tmp_path):
    """The emitter's own comments carry warning glyphs. Dropping `encoding="utf-8"` from
    `write_text` either raises UnicodeEncodeError mid-build or writes mojibake into the generated
    program -- on this cp1255 Windows box only, so a Linux CI would never see it."""
    # The glyphs are built with chr() and the comparison is on BYTES, so a FAILURE here prints an
    # ASCII repr: this console is cp1255, and a non-ASCII failure message would replace the
    # diagnosis with a UnicodeEncodeError from pytest's own reporter. No newline in the text --
    # `write_text` is TEXT mode, so on Windows it would translate one to CRLF and that would be
    # this test failing about line endings instead of about the encoding.
    text = "// %s ORDER IS THE CONTRACT %s do not sort" % (chr(0x26A0), chr(0x2014))
    paths = write_program_files([("entry", text)], tmp_path / "g")
    assert paths[0].read_bytes() == text.encode("utf-8")


# -- the xor involution ----------------------------------------------------------------------------

def test_the_clear_fcall_is_character_identical_to_the_set_fcall():
    """The involution IS the same block called twice. A CLEAR that names a different block (or a
    dropped one) leaves the per-seg registers dirty, so every seg after the first bakes onto
    non-zero registers -- the failure `_seg_xorby_use`'s own docstring describes."""
    seq = _seg_xorby_use("ss7_seg3_xb")
    assert seq[0] == seq[-1], "SET and CLEAR are not the same fcall: %r" % seq
    assert seq[1].strip().startswith("stl.fcall seg_pass1_leaf"), seq


def test_dropping_the_clear_leaves_exactly_the_set_use_prefix():
    """`clear=False` is the TDD FAIL stub, so it must differ from the real sequence by the CLEAR
    and by nothing else."""
    full, stub = _seg_xorby_use("blk", True), _seg_xorby_use("blk", False)
    assert full[:len(stub)] == stub
    assert len(full) == len(stub) + 1


def test_the_xorby_block_writes_its_fields_in_order_and_returns_through_its_argument():
    """M2-R3: a per-door-state block is reached through its door's SWITCH and must return to the
    switch's register. A hardcoded `xb_ret` returns through the wrong one in any doors build -- a
    control-flow break that only an assembled runtime-door gate would show."""
    fields = [("sp_x", 8, 0x1234), ("sp_mon", 2, 1), ("sp_lt", 2, 7)]
    block = _seg_xorby_block("d3s2_xb", fields, ret="d3_switch_ret")
    assert block[0].strip() == "d3s2_xb:"
    assert [ln.strip() for ln in block[1:-1]] == [
        "hex.xor_by %d, %s, %d" % (w, r, v) for r, w, v in fields]
    assert block[-1].strip() == "stl.fret d3_switch_ret"
    assert "xb_ret" not in block[-1], "the ret register is hardcoded, not the argument"
    assert _seg_xorby_block("x", fields)[-1].strip() == "stl.fret xb_ret"   # default still works


# -- _int_part_lines: no hardcoded labels ----------------------------------------------------------

def _labels_defined(lines):
    return {ln.strip()[:-1] for ln in lines if re.fullmatch(r"\s*[A-Za-z_][A-Za-z0-9_]*:", ln)}


def _jump_targets(lines):
    return {ln.strip()[1:] for ln in lines if re.fullmatch(r"\s*;[A-Za-z_][A-Za-z0-9_]*", ln)}


def test_the_int_part_block_defines_only_the_labels_it_was_handed():
    """`doomfj.collision` expands this many times in ONE program with different tags. A label that
    is hardcoded instead of parameterised is a DUPLICATE global definition, i.e. an assemble
    failure several minutes into a build."""
    lines = _int_part_lines("vx", "viewx", "vxsx", "vxdone")
    assert _labels_defined(lines) == {"vxsx", "vxdone"}
    assert _jump_targets(lines) == {"vxdone"}


def test_two_expansions_share_no_label():
    a = _int_part_lines("vx", "viewx", "vxsx", "vxdone")
    b = _int_part_lines("vy", "viewy", "vysx", "vydone")
    assert _labels_defined(a) & _labels_defined(b) == set()


def test_nothing_in_the_block_is_named_that_was_not_passed_in():
    """Stronger than the two above, which only read DEFINITIONS: a tag hardcoded in an ARGUMENT
    (`hex.sign`'s branch targets, say) sends every expansion to the first one's label -- silently
    correct-looking text, wrong control flow. Fresh tags must leave no trace of the usual ones."""
    text = "\n".join(_int_part_lines("qdst", "qsrc", "qneg", "qpos"))
    for token in ("vx", "vy", "viewx", "viewy", "vxsx", "vxdone", "vysx", "vydone"):
        assert token not in text, "%r is hardcoded into the block: %r" % (token, text)


# -- the player sim: the fj half of a two-language mirror ------------------------------------------

def _sim_arms(lines):
    """(key mask) -> (register, added constant) for each `if_flags`-gated add_constant arm."""
    arms = {}
    for i, ln in enumerate(lines):
        m = re.fullmatch(r"hex\.if_flags pkeys, (0x[0-9a-f]+), (\w+), (\w+)", ln)
        if not m:
            continue
        mask, yes = int(m.group(1), 16), m.group(3)
        assert lines[i + 1] == yes + ":", "the `yes` label does not follow its branch: %r" % ln
        add = re.fullmatch(r"hex\.add_constant 8, (\w+), (0x[0-9a-f]+)", lines[i + 2])
        assert add, "arm %r does not add a constant: %r" % (yes, lines[i + 2])
        arms[mask] = (add.group(1), int(add.group(2), 16))
    return arms


def test_each_key_turns_and_moves_the_way_its_name_says():
    """A swapped mask (the left key turning right) or a sign flip on the modular subtract is
    invisible to everything cheap: today only an assembled m14/m5 gate catches it, as a cumulative
    trajectory drift. The negations are checked as a PAIR summing to 2**32, which is what makes
    `-= ANGLE_TURN` emitted as `+= (2**32 - ANGLE_TURN)` bit-identical to the oracle's
    `& 0xFFFFFFFF` subtract in `reference_model.step_sim`."""
    arms = _sim_arms(_player_sim_lines())
    assert set(arms) == {WF.KEY_TURN_LEFT_MASK, WF.KEY_TURN_RIGHT_MASK,
                         WF.KEY_FORWARD_MASK, WF.KEY_BACK_MASK}
    assert arms[WF.KEY_TURN_LEFT_MASK] == ("viewangle", ANGLE_TURN & 0xFFFFFFFF)
    assert arms[WF.KEY_FORWARD_MASK] == ("pmove", FORWARD_MOVE & 0xFFFFFFFF)
    for pos, neg in ((WF.KEY_TURN_LEFT_MASK, WF.KEY_TURN_RIGHT_MASK),
                     (WF.KEY_FORWARD_MASK, WF.KEY_BACK_MASK)):
        assert arms[pos][0] == arms[neg][0], "the two arms move different registers"
        assert arms[pos][1] + arms[neg][1] == 1 << 32, (
            "%#x and %#x are not modular negations" % (arms[pos][1], arms[neg][1]))


def test_the_move_is_applied_exactly_once_per_tic():
    """Both arms present means the player moves TWICE per tic -- and that still satisfies any check
    that merely looks for the collision handoff. `m5_gate` would show it only as a cumulative drift
    from frame 0."""
    direct = ["hex.add 8, viewx, pmvdx", "hex.add 8, viewy, pmvdy"]
    handoff = ["hex.mov 8, cm_dx, pmvdx", "hex.mov 8, cm_dy, pmvdy", ";simcollide"]
    with_col, without = _player_sim_lines(True), _player_sim_lines(False)
    assert all(ln in with_col for ln in handoff) and not any(ln in with_col for ln in direct)
    assert all(ln in without for ln in direct) and not any(ln in without for ln in handoff)


# -- the two frame prologues -----------------------------------------------------------------------

def test_the_standalone_prologue_echoes_nothing():
    """THE defining difference between the two prologues, and nothing asserted it. An echo in the
    shipped binary injects the state record into the frame stream, which the present device reads
    as picture commands and paints as garbage.

    The hosted side is checked by OPERAND, not by count: the host relays these three words straight
    into the next frame's `hex.input 4, viewx/viewy/viewangle`, in that order, so echoing one
    register twice is a silent position/angle freeze the host cannot see. (MEASURED: with the
    assertion written as `sum(...) == 3`, echoing `viewx` where `viewangle` belongs passed.)"""
    standalone = _standalone_input_lines(collide=True)
    assert not any("stl.output_char" in ln for ln in standalone)
    assert not any("stream.emit_bytes4" in ln for ln in standalone)
    hosted = _state_wire_lines(sim=True, collide=True)
    assert any(ln.strip() == "stl.output_char %d" % WF.STATE_CMD for ln in hosted)
    assert [ln.split()[-1] for ln in hosted if "stream.emit_bytes4" in ln] == [
        "viewx", "viewy", "viewangle"], (
        "the host is relayed something other than x, y and angle, in that order: %r"
        % [ln for ln in hosted if "stream.emit_bytes4" in ln])


def test_pkeys_is_rebuilt_with_wireformats_own_bit_values():
    """M2-R4: the use key is `1 << 4`, i.e. bit 0 of the HIGH nibble, so it is xor'd into
    `pkeys + dw`. Landing it in the low nibble makes space do nothing (or a movement key open
    doors) -- a mirror drift against `doomfj.wireformat` that only a keyboard-driven build shows."""
    lines = _standalone_input_lines()
    built = {}
    for i, ln in enumerate(lines):
        m = re.fullmatch(r"hex\.if0 1, (kb_\w+), \w+", ln)
        if not m:
            continue
        xor = re.fullmatch(r"hex\.xor_by (pkeys(?: \+ dw)?), (0x[0-9a-f]+)", lines[i + 1])
        assert xor, "flag %s is tested but sets nothing: %r" % (m.group(1), lines[i + 1])
        built[m.group(1)] = (xor.group(1), int(xor.group(2), 16))
    assert built == {
        "kb_f": ("pkeys", WF.KEY_FORWARD),
        "kb_b": ("pkeys", WF.KEY_BACK),
        "kb_l": ("pkeys", WF.KEY_TURN_LEFT),
        "kb_r": ("pkeys", WF.KEY_TURN_RIGHT),
        "kb_u": ("pkeys + dw", WF.KEY_USE >> 4),
    }
    assert WF.KEY_USE == 1 << 4, "KEY_USE left the high nibble -- `pkeys + dw` is now wrong"


def test_every_poll_is_its_own_expansion():
    """A backward jump would re-enter dirtied cells (src/fj/input.fj), which is why the polls are a
    `rep`, and a count silently dropping to 1 loses key transitions inside a frame."""
    polls = [ln for ln in _standalone_input_lines() if "kb.poll" in ln]
    assert len(polls) == 1, "the polls are no longer one `rep` line: %r" % polls
    assert polls[0].startswith("rep(%d, i) kb.poll " % STANDALONE_POLLS), polls[0]
    assert _standalone_input_lines(polls=3)[0].startswith("rep(3, i) kb.poll ")


def test_the_magic_check_precedes_every_state_input():
    """A junk feed must reach `bad:` and halt. With the check AFTER the inputs it blocks reading the
    other bytes and dies on EOF instead -- which is exactly what the R0 build gate relies on."""
    lines = _state_wire_lines()
    first_wide_input = next(i for i, ln in enumerate(lines) if ln.startswith("hex.input 4,"))
    magic = [i for i, ln in enumerate(lines) if "wmagic" in ln]
    assert magic, "the MAGIC check vanished -- a junk feed is no longer rejected"
    assert max(magic) < first_wide_input
    assert sum("bad," in lines[i] for i in magic) == 2, (
        "both MAGIC nibbles must branch to `bad:`")


def test_the_frame_order_is_doors_then_sim_then_derive_then_echo():
    """Reordering the doors after the move changes which frame a door becomes walkable on, and the
    oracle mirror has to agree (CLAUDE.md rule 2). The derived integer coords must come after the
    move, or the BSP walk runs on last frame's position."""
    lines = _state_wire_lines(sim=True, collide=True, door_lines=["door_tic_marker"])
    where = {k: lines.index(v) for k, v in (
        ("doors", "door_tic_marker"),
        ("sim", "hex.zero 8, pmove"),
        ("derive", "hex.zero 10, vx"),
        ("echo", "stl.output_char %d" % WF.STATE_CMD))}
    assert where["doors"] < where["sim"] < where["derive"] < where["echo"], where


# -- the menu wrapper ------------------------------------------------------------------------------

def test_the_menu_omits_exactly_the_frame_end_byte():
    """The trap the docstring names: both producers fall into the SAME tail, whose last line is
    `stl.output_char 0xFF`. A second 0xFF presents an EMPTY frame, and jumping past the tail breaks
    `selfreset.emit_reset_part`'s assert -- a black-screen menu that costs a full game build to
    discover. `doomfj.menu` itself is well tested; this wrapper was not tested at all."""
    cfg = Config()
    asset_wad = WadFile.from_path(ASSETS)
    lines = _menu_lines(cfg, asset_wad, DEFAULT_MENU, DEFAULT_MENU_SELECTED)
    colours = palette_colours(bytes(b for rgb in asset_wad.playpal(0) for b in rgb))
    full = menu_stream(cfg.VIEW_W, cfg.VIEW_H, DEFAULT_MENU, DEFAULT_MENU_SELECTED, colours)
    assert full[-1] == 0xFF, "doomfj.menu.stream no longer ends with the frame-end marker"
    assert "\n".join(lines).count("stl.output_char") == len(full) - 1


def test_the_menu_branch_wraps_the_stream_in_the_documented_order():
    """`hex.if0 1, mode, do_world` / <the menu> / `;frame_end` / `do_world:` -- the persisted mode
    cell picks the producer, and the menu arm must jump INTO the shared tail, not past it."""
    lines = _menu_lines(Config(), WadFile.from_path(ASSETS), ["A", "B"], 0)
    assert lines[0] == "hex.if0 1, mode, do_world"
    assert lines[-2] == ";frame_end"
    assert lines[-1] == "do_world:"


# -- the band-list bank ----------------------------------------------------------------------------

@pytest.fixture(scope="module")
def bands():
    """Two viewz classes x two bank keys -- enough to pin the enumeration order, and it costs
    milliseconds because the walk is per-row, not per-pixel."""
    asset_wad = WadFile.from_path(ASSETS)
    flats = [n for n in ("CEIL1_2", "FLOOR4_8") if n in set(asset_wad.names())]
    assert len(flats) == 2, "the asset fixture lost a flat this test keys off: %r" % flats
    return (ReferenceModel(), Config(), asset_wad, {0: 0, (41 << 16): 1},
            [(0, 160, 4, flats[0]), (72, 128, 8, flats[1])])


@pytest.mark.parametrize("ft1", [False, True])
def test_the_lists_enumerate_class_major_then_key_then_half(bands, ft1):
    """The baked bank address is `(class*len(keys) + key)*130 dw` and the vpb_walk id is derived
    from this order, so a loop-order swap assembles perfectly and paints every floor and ceiling
    from another band's list."""
    rm, cfg, wad, vz_classes, key_ids = bands
    whole = _band_pair_lists(rm, cfg, wad, vz_classes, key_ids, ft1)
    assert len(whole) == len(vz_classes) * len(key_ids) * 2
    for c, vz in enumerate(vz_classes):
        for k, key in enumerate(key_ids):
            one = _band_pair_lists(rm, cfg, wad, {vz: 0}, [key], ft1)
            for half in (0, 1):
                assert whole[(c * len(key_ids) + k) * 2 + half] == one[half], (
                    "class %d key %d half %d is not where its id says" % (c, k, half))


def test_each_half_list_covers_its_half_window_exactly(bands):
    """A walk that stops short leaves rows unpainted in EVERY frame; a broken run-merge inflates
    every list toward the MAX_BANDS//2 overflow. `y2` is an absolute, exclusive row bound."""
    rm, cfg, wad, vz_classes, key_ids = bands
    lists = _band_pair_lists(rm, cfg, wad, vz_classes, key_ids, True)
    for i, pairs in enumerate(lists):
        end = cfg.CENTERY if i % 2 == 0 else cfg.VIEW_H
        assert pairs, "half list %d is empty -- those rows are never painted" % i
        ys = [p[0] for p in pairs]
        assert ys == sorted(set(ys)), "y2 is not strictly increasing in half list %d" % i
        assert ys[-1] == end, "half list %d ends at %d, not %d" % (i, ys[-1], end)
        colours = [p[1] for p in pairs]
        assert all(a != b for a, b in zip(colours, colours[1:])), (
            "adjacent entries repeat a colour -- the run merge is not merging")


def test_no_half_list_overflows_its_slots(bands):
    """`_lines_bake_bank` asserts this at emit time, so this is a two-second pre-check of a failure
    that otherwise costs a build -- and it is the arithmetic claim the MAX_BANDS comment makes
    (a monotone half-window walk gives at most 32 distinct zrow runs)."""
    rm, cfg, wad, vz_classes, key_ids = bands
    for ft1 in (False, True):
        for pairs in _band_pair_lists(rm, cfg, wad, vz_classes, key_ids, ft1):
            assert len(pairs) <= MAX_BANDS // 2, "%d entries overflows the bank slot" % len(pairs)


# -- the hoisted globals ---------------------------------------------------------------------------

def _decl_names(decls):
    """Every fj label a decl list defines. A decl entry may be MULTI-LINE (`drawn:` carries a
    `;0 * dw` body), so this reads lines, not list entries."""
    names = []
    for decl in decls:
        for line in decl.split("\n"):
            m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
            if m:
                names.append(m.group(1))
    return names


def _all_decl_names(cfg):
    # `_lines_mode_decls` reads only `cfg` today; its other four parameters are unread, which is why
    # None/{} suffices here. If that stops being true, this call is where it surfaces.
    return (_decl_names(hoisted_scratch_decls(cfg))
            + _decl_names(_lines_mode_decls(cfg, None, None, {}, {}))
            + _decl_names(STANDALONE_SCRATCH_DECLS))


def test_the_three_decl_producers_declare_no_label_twice():
    """Two producers declaring the same global is an fj redefinition -- or, worse, one register
    silently shared by two consumers. `test_restore_set_shipped`'s `_declared()` collapses the
    decls into a dict keyed by name, so a duplicate DISAPPEARS there by construction."""
    names = _all_decl_names(Config())
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, "declared more than once: %r" % dupes


def test_a_wider_pid_widens_registers_without_adding_or_losing_any():
    """`hoisted_scratch_decls` became a FUNCTION for this reason (the M4 PID_NIBBLES note), and
    every existing caller passes no cfg at all -- so the widening path is otherwise unexercised. A
    newly hoisted global hardcoded at the default pid width is invisible until a nine-level build,
    where a truncated pid indexes the wrong plane."""
    narrow, wide = Config(), Config(PID_NIBBLES=4)
    assert wide.PID_BYTES > narrow.PID_BYTES, "PID_NIBBLES=4 no longer widens PID_BYTES"
    assert _all_decl_names(wide) == _all_decl_names(narrow), (
        "widening the pid added or removed a label, not just its width")
    for producer in (hoisted_scratch_decls,
                     lambda c: _lines_mode_decls(c, None, None, {}, {})):
        thin, fat = producer(narrow), producer(wide)
        widened = {_decl_names([a])[0] for a, b in zip(thin, fat) if a != b}
        # The module's own naming: a register that HOLDS a pid is `*pid`, one that holds a baked
        # plane-pair pointer is `*bp`. `seg_cvpidx`/`seg_fvpidx` are bank offsets, not pids, which
        # is why the suffix has to be exact. Comparing SETS (not a count) is what makes a single
        # decl left at the default width fail here rather than hiding behind its four neighbours.
        by_name = {n for n in (_decl_names([d])[0] for d in thin if _decl_names([d]))
                   if n.endswith("bp") or n.endswith("pid")}
        assert widened == by_name, (
            "these registers name themselves pid-width but did not widen: %r"
            % sorted(by_name - widened))
        assert all(d.endswith("hex.vec %d" % (narrow.PID_BYTES * 2)) for d in thin
                   if _decl_names([d]) and _decl_names([d])[0] in widened), (
            "a decl widened for a reason other than the pid width")


# -- small pure predicates -------------------------------------------------------------------------

class _Sector:
    """Only the two flat names `map_has_sky` can legitimately look at."""

    def __init__(self, ceil_tex):
        self.ceil_tex, self.floor_tex = ceil_tex, "F_SKY1"


def test_sky_is_a_ceiling_flat_matched_case_insensitively():
    """The persisted_labels-shaped bug: `metrics["features"]["sky"]` claimed sky for a wad with
    none, because the answer was a SECOND EXPRESSION. A floor F_SKY1 is not a sky, and the emitter
    bakes or skips a ~3*tw-entry bank on this answer -- wasted span, or missing pixels."""
    assert map_has_sky([_Sector("CEIL3_5"), _Sector("f_sky1")])
    assert not map_has_sky([_Sector("CEIL3_5"), _Sector("FLOOR4_8")])
    assert not map_has_sky([])


@pytest.mark.parametrize("wad,mapname,expect", [
    ("freedoom_e1m1", "E1M1", True), ("e1m1_lite", "E1M1", True),
    ("square_room", "MAP01", False), ("test", "MAP01", False), ("arena", "MAP01", False)])
def test_sky_agrees_with_the_real_fixtures(wad, mapname, expect):
    assert map_has_sky(WadFile.from_path(FIX / (wad + ".wad")).sectors(mapname)) is expect


# The shipped VIEW_H is 100 and these are the plausible neighbours. MEASURED: the prefix claim
# does NOT hold for 32 <= VIEW_H <= 62 -- there the top buckets are unreachable, so
# `sprite_bucket_height` returns its `hi = 1` default and bucket 31 classifies as "short" while
# buckets 19..30 do not. Nothing builds at those heights, so this pins the range the repo uses
# rather than asserting a claim that is false off it.
@pytest.mark.parametrize("view_h", [63, 100, 120, 200, 240])
def test_the_short_sprite_buckets_really_are_a_prefix(view_h):
    """`_spr_nlow`'s docstring claims "monotone, so a prefix", and the emitter tests `b < nlow` on
    the strength of it. If `sprite_bucket_height` stops being monotone in the bucket index, that
    test misclassifies which sprites take the low-res path -- a pixel change with no assert
    anywhere."""
    cfg = Config(H=view_h)                      # VIEW_H is a property of H, not a field
    short = {b for b in range(SPRITE_HEIGHT_BUCKETS)
             if sprite_bucket_height(b, view_h) < DEG_SPR_LOWRES_H}
    assert short == set(range(_spr_nlow(cfg))), (
        "the short buckets are not a prefix at VIEW_H=%d: %r" % (view_h, sorted(short)))


@pytest.mark.parametrize("mapname", ["E1M%d" % i for i in range(1, 10)])
def test_every_map_prefix_is_a_legal_fj_label(mapname):
    """M4 puts nine maps in one image, so the BSP-as-code label prefixes multiply. An illegal one is
    an assemble failure minutes into a build."""
    assert re.fullmatch(r"[a-z][a-z0-9_]*", _pfx(mapname)), "%r is illegal" % _pfx(mapname)
    assert _pfx("E1-M1") == "e1_m1", "hyphens must map to underscores, not vanish"
    assert len({_pfx("E1M%d" % i) for i in range(1, 10)}) == 9, "two maps share a prefix"
