import math
from pathlib import Path

from doomfj.config import Config

DEFAULT = Config()  # 160x100, the primary target (DESIGN §1)


def _parse_fj_consts(text: str) -> dict[str, int]:
    """Parse `NAME = INT` lines from a generated fj_consts.fj, ignoring // comments and blanks."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if not line:
            continue
        name, _, val = line.partition("=")
        out[name.strip()] = int(val.strip())
    return out


def test_derived_constants_160x100():
    c = DEFAULT
    assert (c.W, c.H) == (160, 100)
    assert c.NCOLORS == 256
    assert c.COL_BITS == 8       # ceil(log2 160) — screen column x width (§1.1.4), not a fixed 8
    assert c.ROW_BITS == 7       # ceil(log2 100)
    assert c.FB_SIZE == 16000    # W*H packed bytes (§1.2)
    assert c.PALETTE_SIZE == 768  # 256*3
    assert (c.VIEW_W, c.VIEW_H) == (160, 100)


def test_resolution_parametricity_320x200():
    """The §1 2-const invariant: change ONLY W/H and everything resolution-derived tracks —
    nothing silently keeps the 160x100 value or a width that assumes W/H <= 256."""
    c = Config(W=320, H=200)
    assert c.COL_BITS == 9       # ceil(log2 320) — NOT a fixed 8
    assert c.ROW_BITS == 8       # ceil(log2 200)
    assert c.FB_SIZE == 64000    # 320*200
    assert (c.VIEW_W, c.VIEW_H) == (320, 200)
    # the derived values genuinely differ from the default resolution
    assert c.FB_SIZE != DEFAULT.FB_SIZE
    assert c.COL_BITS != DEFAULT.COL_BITS


def test_col_bits_is_ceil_log2_w():
    for w in (160, 256, 320, 512):
        assert Config(W=w, H=100).COL_BITS == math.ceil(math.log2(w))


def test_fj_consts_roundtrip(tmp_path):
    p = DEFAULT.emit_fj_consts(tmp_path / "fj_consts.fj")
    parsed = _parse_fj_consts(Path(p).read_text())
    assert parsed == DEFAULT.constants()


def test_emit_has_no_hardcoded_resolution_literal(tmp_path):
    """The generated file for a non-default resolution must not leak the default W/H/FB. The resolution
    *variables* must scale; check them by name — a blanket "no 160/100" is a false positive now that
    derived constants legitimately alias defaults (e.g. CENTERX = VIEW_W//2 = 160 at W=320)."""
    p = Config(W=320, H=200).emit_fj_consts(tmp_path / "fj_consts.fj")
    text = p.read_text()
    assert "320" in text and "200" in text
    for leaked in ("W = 160\n", "H = 100\n", "VIEW_W = 160\n", "VIEW_H = 100\n", "FB_SIZE = 16000\n"):
        assert leaked not in text, leaked
