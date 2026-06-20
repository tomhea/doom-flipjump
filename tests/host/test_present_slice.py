"""M11a (F4 + F7-present) — the renderer's first golden frame. The fj program builds a packed-byte
framebuffer (D3), fills one fixed-address column, and presents it over the screen device (0x03); a
headless InMemoryScreen captures the frame. It must be bit-exact vs the H5 oracle's solid-column
frame (D12), and the device's per-frame sha256 must match the oracle's.
"""
from pathlib import Path

import pytest

from doomfj.build import build_present_slice
from doomfj.config import Config, FLAT_MAX_WORDS
from doomfj.reference_model import ReferenceModel, screen_frame_hash
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
COL_X, COLOR = 80, 96


def _palette_rgb(wad):
    return bytes(v for rgb in wad.playpal(0) for v in rgb)


# ── oracle: the solid-column frame (H5) ─────────────────────────────────────

def test_oracle_render_solid_column():
    """A framebuffer cleared to bg=0 with column COL_X filled with COLOR (row-major W*H indices)."""
    cfg = Config()
    frame = ReferenceModel().render_solid_column(COL_X, COLOR)
    assert len(frame) == cfg.FB_SIZE == 16000
    assert all(frame[y * cfg.W + x] == (COLOR if x == COL_X else 0)
               for y in range(cfg.H) for x in range(cfg.W))


def test_screen_frame_hash_formula():
    """The golden hash matches the device's: sha256(pixel_indices + palette_rgb_bytes)."""
    import hashlib
    frame = b"\x00\x05\x07"
    pal = b"\x10\x20\x30"
    assert screen_frame_hash(frame, pal) == hashlib.sha256(frame + pal).hexdigest()


# ── the fj present slice vs the oracle (the golden frame, D12) ───────────────

def test_present_slice_bit_exact_vs_oracle(tmp_path):
    """The fj-rendered frame (captured headless) equals the oracle's frame byte-for-byte, runs flat,
    and the device's per-frame sha256 matches the oracle hash over (indices + palette)."""
    wad = WadFile.from_path(E1M1)
    m = build_present_slice(E1M1, col_x=COL_X, color=COLOR,
                            out_fjm=tmp_path / "slice.fjm", generated_dir=tmp_path / "gen")
    assert m["storage_mode"] == "flat"
    assert m["span_words"] < FLAT_MAX_WORDS

    oracle_frame = ReferenceModel().render_solid_column(COL_X, COLOR)
    assert bytes(m["pixel_indices"]) == oracle_frame                      # bit-exact (D12)
    assert m["frame_hash"] == screen_frame_hash(oracle_frame, _palette_rgb(wad))
