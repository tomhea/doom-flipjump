"""M11c (F5 / D2b — R1 gate / D2 bake-off) — the full-unroll renderer + the hex.vec2 framebuffer.

`rep(VIEW_W, x) frame.column ... rep(count, row) frame.pixel ...` renders every pixel at a COMPILE-TIME
address, each pixel running the M11b DDA pipeline (texture-v sample + per-column colormap apply) and
writing the lit byte DIRECTLY into its register-form (`hex.vec 2`) framebuffer cell — no deposit (the
hex.vec2 simplification, §2.1). The frame is presented over the 0x06 device (fj 1.5.1) and captured
headless; it must be bit-exact vs the H5 oracle (D12). The bake-off (ops/frame + assemble + .fjm size at
full WIDTH scale) is measured by scripts/m11c_evidence.py; these committed tests prove correctness on a
fast reduced-width slice and that the build runs flat.
"""
from pathlib import Path

import pytest

from doomfj.build import build_unroll_frame
from doomfj.config import Config, FLAT_MAX_WORDS
from doomfj.reference_model import ReferenceModel, screen_frame_hash
from doomfj.texturecompiler import composite_texture, downscale_canvas, texture_texels
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
TEX = "MC5"                              # 128x128, downscaled 2x -> 64x64 (pow2 height)
DOWNSCALE = 2
LIGHT, STEP, FRAC0 = 20, 327, 0          # constant column light + 8.8 DDA step
WIDTH, COUNT = 16, 50                    # committed slice: 16 cols x 50 rows (full bake-off is 160x100)


def _mc5_dims(wad):
    """Derive texheight/texwidth from the WAD at the shared downscale (R6) — the build derives the same,
    so the oracle samples the identical texture geometry."""
    d = {x.name: x for x in wad.texture_defs()}[TEX]
    return d.height // DOWNSCALE, d.width // DOWNSCALE


def _mc5_texels(wad):
    d = {x.name: x for x in wad.texture_defs()}[TEX]
    return texture_texels(downscale_canvas(composite_texture(wad, d), DOWNSCALE))


def _palette_rgb(wad):
    return bytes(v for rgb in wad.playpal(0) for v in rgb)


def _oracle_frame(wad):
    texh, texw = _mc5_dims(wad)
    return ReferenceModel().render_unroll_frame(
        _mc5_texels(wad), texh, texw, wad.colormap(), LIGHT,
        width=WIDTH, count=COUNT, frac0=FRAC0, step=STEP)


# ── oracle (H5): the synthetic full-unroll frame ─────────────────────────────

def test_oracle_unroll_frame_composition():
    """The frame is row-major W*H: column x is the texture-v DDA over texcol = x % TEXW, the rendered
    region is [row<COUNT][x<WIDTH], everything else is zero (the register framebuffer's zero-init)."""
    cfg = Config()
    wad = WadFile.from_path(E1M1)
    frame = _oracle_frame(wad)
    assert len(frame) == cfg.FB_SIZE

    texh, texw = _mc5_dims(wad)
    rm = ReferenceModel()
    for x in range(WIDTH):
        col = rm.render_textured_column(_mc5_texels(wad), texh, x % texw, wad.colormap(), LIGHT,
                                        count=COUNT, frac0=FRAC0, step=STEP)
        for row in range(COUNT):
            assert frame[row * cfg.W + x] == col[row]      # placed row-major at (x, row)

    # outside the rendered region: zero (unwritten framebuffer cells)
    assert frame[COUNT * cfg.W] == 0                        # first row below the slice
    assert frame[WIDTH] == 0                                # first column right of the slice
    # column 0 (texcol 0) first pixels are hand-anchored vs M11b's MC5 column-0 DDA
    assert frame[0 * cfg.W + 0] != 0                        # spawn pixel is a real lit texel


# ── the fj full-unroll frame vs the oracle (the golden frame, D12) ───────────

def test_unroll_frame_bit_exact_vs_oracle(tmp_path):
    """The fj-rendered hex.vec2 frame (captured headless over the 0x06 device) equals the oracle's frame
    byte-for-byte, runs flat under the span limit, reports a positive op cost, and the device's per-frame
    sha256 matches the oracle hash over (indices + palette)."""
    wad = WadFile.from_path(E1M1)
    m = build_unroll_frame(E1M1, TEX, light=LIGHT, width=WIDTH, count=COUNT, step=STEP, frac0=FRAC0,
                           out_fjm=tmp_path / "frame.fjm", generated_dir=tmp_path / "gen")
    assert m["storage_mode"] == "flat"
    assert m["span_words"] < FLAT_MAX_WORDS
    assert m["op_counter"] > 0 and m["per_pixel_ops"] > 0
    assert m["assemble_seconds"] >= 0.0 and m["fjm_bytes"] > 0

    oracle_frame = _oracle_frame(wad)
    assert bytes(m["pixel_indices"]) == oracle_frame                       # bit-exact (D12)
    assert m["frame_hash"] == screen_frame_hash(oracle_frame, _palette_rgb(wad))
