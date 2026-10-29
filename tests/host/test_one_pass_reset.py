"""THE ONE-PASS RESET (selfreset.emit_reset_part_by_label) on synthetic program parts.

The reset names its cells by LABEL, reads each registered cell's extent and value off its own declaration, declares
the cell ZERO and sets it at boot and after every frame. These tests hold the generator to that on every kind of
declaration the program uses (a one-line hex.vec with and without a value, a bit.vec, raw `;v * dw` cells, rows of
hex.vec, a byte array) and hold its REFUSALS: a registered name with no declaration, a name declared twice, a raw
cell that is not a nibble (a LUT is never registered), a byte array whose extent disagrees with the geometry, and
a value that does not fit its cells. Every rewrite keeps every line where it was.

The one-time equivalence with the two-pass reset on the real program is scratchpad/onepass_check.py (it needs a
two-pass build's generated parts and label table).
"""
from pathlib import Path

import pytest

from doomfj import selfreset
from doomfj.harness import W

ENTRY = "stl.startup_and_init_all\n;__hot_end\n"
MAIN = "frame:\n    present.end_frame\nstl.loop\nbad: stl.loop\n"
STATE = "\n".join([
    "ws_c1: hex.vec 1, 1",
    "ws_cang: hex.vec 8, 0x3FFFFFFF",
    "p2_basep: hex.vec w/4",
    "vq_hi: bit.vec 8",
    "drawn:",
    ";0 * dw",
    ";0 * dw",
    ";3 * dw",
    "thpos_rt:",
    "    hex.vec 4, 0x1234",
    "    hex.vec 4, 0",
    "pclm:",
    ";0 * dw",
    ";0 * dw",
    "viewx: hex.vec 8, 4267704320",
    "lut_x: hex.vec 2, 200",
    "",
])
VIEW_W, NSS = 2, 3


def _parts(tmp_path: Path, state: str = STATE):
    (tmp_path / "e1m1_00_entry.fj").write_text(ENTRY, encoding="utf-8")
    (tmp_path / "e1m1_02_main.fj").write_text(MAIN, encoding="utf-8")
    (tmp_path / "e1m1_05_state.fj").write_text(state, encoding="utf-8")
    return sorted(tmp_path.glob("e1m1_0*.fj"))


NAMES = {"ws_c1", "ws_cang", "p2_basep", "vq_hi", "drawn", "thpos_rt", "pclm", "viewx"}


def _emit(tmp_path, names=NAMES, persist=("viewx",), state=STATE):
    files = _parts(tmp_path, state)
    return selfreset.emit_reset_part_by_label(tmp_path, files, names, VIEW_W, NSS, "e1m1", persist=persist)


def test_every_kind_of_declaration_is_reset_from_its_own_value(tmp_path):
    part, nib, byte, plan = _emit(tmp_path)
    body = part.read_text(encoding="utf-8")
    assert "    hex.set 1, ws_c1, 1" in body
    assert "    hex.set 8, ws_cang, 0x3FFFFFFF" in body
    assert "    hex.zero %d, p2_basep" % (W // 4) in body                     # w/4 cells (W = the memory width)
    assert "    hex.zero 8, vq_hi" in body
    assert "    hex.set 1, drawn + 2*dw, 3" in body and "    hex.zero 1, drawn + 0*dw" in body
    assert "    hex.set 4, thpos_rt + 0*dw, 0x1234" in body and "    hex.zero 4, thpos_rt + 4*dw" in body
    assert "    rep(2, i) m1.zerobyte pclm + i*dw      // pclm" in body
    assert "viewx" not in body.split("m1_reset:")[1], "a PERSISTED label must not be reset"
    assert "lut_x" not in body, "an unregistered label (a LUT) is never reset"
    assert body.rstrip().endswith(";__hot_end")
    got = {(n, c): v for n, c, v in plan}
    assert got[("ws_cang", 0)] == 0xF and got[("ws_cang", 7)] == 0x3 and got[("ws_c1", 0)] == 1
    assert got[("thpos_rt", 1)] == 0x3 and got[("thpos_rt", 4)] == 0 and got[("drawn", 2)] == 3
    assert got[("pclm", 1)] == "byte" and byte == 2 and nib == 1 + 8 + W // 4 + 8 + 3 + 8


def test_the_registered_cells_are_declared_zero_and_no_line_moves(tmp_path):
    _emit(tmp_path)
    after = (tmp_path / "e1m1_05_state.fj").read_text(encoding="utf-8").split("\n")
    before = STATE.split("\n")
    assert len(after) == len(before)
    assert after[0] == "ws_c1: hex.vec 1" and after[1] == "ws_cang: hex.vec 8"
    assert after[7] == ";0 * dw" and after[9] == "    hex.vec 4" and after[10] == "    hex.vec 4, 0"
    assert after[14] == "viewx: hex.vec 8, 4267704320", "a persisted label keeps its declared value"
    assert after[15] == "lut_x: hex.vec 2, 200", "an unregistered label keeps its declared value"


def test_the_boot_and_the_frame_tail_both_enter_the_reset(tmp_path):
    _emit(tmp_path)
    assert (tmp_path / "e1m1_00_entry.fj").read_text(encoding="utf-8").split("\n")[1] == ";m1_reset"
    main = (tmp_path / "e1m1_02_main.fj").read_text(encoding="utf-8").split("\n")
    assert main[2] == ";m1_reset" and main[3] == "bad: stl.loop"


@pytest.mark.parametrize("why, names, state, match", [
    ("a registered name the program lost", NAMES | {"gone_reg"}, STATE, "no declaration"),
    ("a name declared twice", NAMES, STATE + "ws_c1: hex.vec 1\n", "declared twice"),
    ("a raw cell that is not a nibble (a LUT)", NAMES | {"lut_cells"}, STATE + "lut_cells:\n;200 * dw\n",
     "not a nibble"),
    ("a byte array the geometry disagrees with", NAMES, STATE.replace("pclm:\n;0 * dw\n", "pclm:\n"),
     "geometry says"),
    ("a value that does not fit its cells", NAMES | {"big"}, STATE + "big: hex.vec 1, 16\n", "does not fit"),
    # the CR of #129: cells that resume after a blank or a comment line are refused, not silently cut off
    ("cells resumed after a comment line", NAMES, STATE.replace(";0 * dw\n;0 * dw\n;3 * dw\n",
                                                                  ";0 * dw\n// a note\n;0 * dw\n;3 * dw\n"),
     "resume at line"),
    ("cells resumed after a blank line", NAMES, STATE.replace("    hex.vec 4, 0x1234\n", "    hex.vec 4, 0x1234\n\n"),
     "resume at line"),
])
def test_the_generator_refuses(tmp_path, why, names, state, match):
    with pytest.raises(AssertionError, match=match):
        _emit(tmp_path, names=names, state=state)


# ---- the pin veto (the CR of #129, BLOCKING) ---------------------------------------------------------------------------
_PTR_LOAD = __import__("re").compile(r"hex\.set\s+w/4\s*,\s*\w+\s*,\s*([A-Za-z_]\w*)")


def _pointer_loaded(names, texts):
    """the registered labels some source loads into a pointer register (`hex.set w/4, <ptr>, <label>`)"""
    return {m.group(1) for text in texts for m in _PTR_LOAD.finditer(text) if m.group(1) in names}


def test_every_pointer_read_registered_cell_is_vetoed():
    """the one-pass reset clears every registered cell in the counted assembly, so each cell the program reads RAW
    through a pointer must be in the pin veto (selfreset.POINTER_READ_CELLS / BYTE_ARRAY_NAMES): a pinned word holds
    base + value. Derived from the sources -- the fj and the emitters' text -- not listed by hand"""
    from doomfj.config import Config
    from doomfj.wall_renderer import tier_cfg
    root = Path(__file__).resolve().parents[2]
    names = selfreset.registered_reset_names(root / "src/doomfj/data/m5_restore_set.json.gz",
                                             tier_cfg(Config(), "game"), True)
    texts = [q.read_text(encoding="utf-8") for q in list((root / "src/fj").glob("*.fj"))
             + list((root / "src/doomfj").glob("*.py"))]
    loaded = _pointer_loaded(names, texts)
    veto = set(selfreset.POINTER_READ_CELLS) | set(selfreset.BYTE_ARRAY_NAMES)
    assert {"drawn", "sprflag", "thpos_rt"} <= loaded, sorted(loaded)        # the scan sees the real loads
    assert loaded <= veto, "pointer-read registered cells the pin veto misses: %s" % sorted(loaded - veto)
    # R9: a source that loads one more registered label into a pointer is caught
    extra = sorted(names - veto)[0]
    assert _pointer_loaded(names, texts + ["    hex.set w/4, some_p, %s" % extra]) - veto == {extra}



@pytest.mark.parametrize("persist, match", [(("viewx", "viewxx"), "registry does not hold"),
                                            (("viewx", "lut_x"), "registry does not hold")])
def test_a_persist_name_that_protects_nothing_is_refused(tmp_path, persist, match):
    """the two-pass reset's persist checks, ported (the CR of #129): a typo, or a label never registered, would leave
    the real state reset every frame"""
    with pytest.raises(AssertionError, match=match):
        _emit(tmp_path, persist=persist)


def test_a_registered_persist_name_the_program_does_not_declare_is_refused(tmp_path):
    with pytest.raises(AssertionError, match="does not declare"):
        _emit(tmp_path, names=NAMES | {"ghost"}, persist=("viewx", "ghost"))
