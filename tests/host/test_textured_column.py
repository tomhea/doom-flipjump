"""M11b (F5) — one textured wall column: the texture-v DDA. For each screen row the renderer steps
frac += step (8.8), samples the texture column at v = (frac>>8) & (texheight-1) via the M8 dispatch
table, applies the colormap at the column light, and emits the lit palette byte. The fj per-pixel
pipeline must reproduce the H5 oracle's column byte-for-byte (D12). The runtime framebuffer deposit /
present of these pixels is the M11c D2 structure decision; M11b proves the per-pixel render math + cost.
"""
from pathlib import Path

import pytest

from doomfj.build import build_textured_column
from doomfj.reference_model import ReferenceModel
from doomfj.texturecompiler import composite_texture, downscale_canvas, texture_texels
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
TEX, TEXH, TEXCOL, LIGHT, COUNT, STEP = "MC5", 64, 5, 20, 50, 327  # 64x64 (pow2 h); step 327 = 8.8


def _mc5_texels(wad):
    d = {x.name: x for x in wad.texture_defs()}[TEX]
    return texture_texels(downscale_canvas(composite_texture(wad, d), 2))


# ── oracle (H5) ─────────────────────────────────────────────────────────────

def test_oracle_textured_column():
    wad = WadFile.from_path(E1M1)
    seq = ReferenceModel().render_textured_column(
        _mc5_texels(wad), TEXH, TEXCOL, wad.colormap(), LIGHT, count=COUNT, frac0=0, step=STEP)
    assert len(seq) == COUNT
    assert list(seq[:6]) == [127, 6, 127, 8, 8, 127]   # hand-checked vs the integer pipeline


# ── fj per-pixel pipeline vs oracle (D12) ───────────────────────────────────

def test_fj_textured_column_bit_exact(tmp_path):
    """The fj DDA+sample+colormap column (captured as text) equals the oracle's lit sequence
    byte-for-byte, runs flat, and reports a positive per-pixel op cost."""
    wad = WadFile.from_path(E1M1)
    m = build_textured_column(E1M1, TEX, texcol=TEXCOL, light=LIGHT, count=COUNT, step=STEP,
                              out_fjm=tmp_path / "col.fjm", generated_dir=tmp_path / "gen")
    assert m["storage_mode"] == "flat"
    assert m["per_pixel_ops"] > 0

    seq = ReferenceModel().render_textured_column(
        _mc5_texels(wad), TEXH, TEXCOL, wad.colormap(), LIGHT, count=COUNT, frac0=0, step=STEP)
    expected = b"".join(b"%02x\n" % b for b in seq)
    assert m["output"] == expected
