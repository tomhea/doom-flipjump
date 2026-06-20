"""M8 (H4) — texture / colormap / palette compiler, host-side.

Composite + value correctness against the committed trimmed-Freedoom fixture (BSD, redistributable —
the full Freedoom WAD is gitignored, so tests read the committed fixture, never rebuild it). Byte-exact
fj reads (sample_texture / apply_colormap) live in tests/fj/test_texture_sample.py."""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj.harness import W
from doomfj.wad import WadFile, decode_picture
from doomfj.texturecompiler import (
    colormap_values,
    compile_colormap,
    compile_flat,
    compile_palette,
    compile_texture,
    composite_texture,
    texture_texels,
)

FIXTURE = Path("tests/fixtures/freedoom_assets.wad")


def _wad():
    return WadFile.from_path(FIXTURE)


def _defs(wad):
    return {d.name: d for d in wad.texture_defs()}


def test_fixture_has_expected_graphics_lumps():
    wad = _wad()
    names = wad.names()
    for lump in ("PLAYPAL", "COLORMAP", "PNAMES", "TEXTURE1"):
        assert lump in names
    assert set(_defs(wad)) == {"A-YELLOW", "STEP4"}
    assert len(wad.playpal()) == 256
    assert len(wad.colormap()) == 34


def test_composite_single_patch_matches_patch():
    wad = _wad()
    canvas = composite_texture(wad, _defs(wad)["A-YELLOW"])
    pic = decode_picture(wad.get_data("YELLOW"))
    # the single full-cover patch -> every opaque patch pixel appears at its texel
    for cx, col in enumerate(pic.columns):
        for (cy, value) in col:
            assert canvas[cy][cx] == value


def test_composite_two_patch_opaque():
    wad = _wad()
    canvas = composite_texture(wad, _defs(wad)["STEP4"])  # STEP06 stacked at y=0 and y=8
    assert len(canvas) == 16 and len(canvas[0]) == 32
    assert all(v is not None for row in canvas for v in row)  # fully opaque


def test_texture_texels_column_major():
    wad = _wad()
    canvas = composite_texture(wad, _defs(wad)["A-YELLOW"])
    texels = texture_texels(canvas)
    h, w = len(canvas), len(canvas[0])
    assert len(texels) == w * h
    # index = col*height + row
    assert texels[0] == canvas[0][0]
    assert texels[h] == canvas[0][1]      # start of column 1
    assert texels[2 * h + 3] == canvas[3][2]


def test_colormap_values_match_wad():
    wad = _wad()
    cm = wad.colormap()
    values = colormap_values(wad, lights=32)
    assert len(values) == 32 * 256
    for light in (0, 7, 15, 31):
        for colour in (0, 1, 100, 255):
            assert values[light * 256 + colour] == cm[light][colour]


def test_compile_palette_emits_rgb_device_data():
    wad = _wad()
    src = compile_palette("pal", wad)
    assert "pal:" in src
    assert src.count("* dw") == 256 * 3  # R,G,B per colour
    r, g, b = wad.playpal()[1]
    assert f";{hex(r)} * dw" in src and f";{hex(g)} * dw" in src


def test_compile_texture_emits_dispatch_and_sample():
    src = compile_texture("tex", _wad(), "A-YELLOW")
    assert "ns tex" in src and "def sample" in src and "def lookup" in src
    assert "hex.set" not in src  # D4 trap avoided (inherited from the M5 emitter)


def test_compile_flat_and_colormap_emit_idioms():
    wad = _wad()
    assert "def sample" in compile_flat("flt", wad, "CEIL1_2")
    assert "def apply" in compile_colormap("cm", wad, lights=2)


def test_compile_texture_unknown_rejected():
    with pytest.raises(KeyError):
        compile_texture("t", _wad(), "NOPE")


def test_compiled_graphics_assemble_flat(tmp_path):
    # R4: compiled texture + flat + colormap must assemble + run on the flat path (no paged fallback).
    # Uses the committed fixture so this runs in CI (the m8_evidence flat check needs dev Freedoom).
    wad = _wad()
    src = (compile_texture("tex", wad, "A-YELLOW") + "\n"
           + compile_flat("flt", wad, "CEIL1_2") + "\n"
           + compile_colormap("cm", wad, lights=2, over_align=False))
    prog = "stl.startup_and_init_all\nstl.loop\n" + src + "\n"
    p = tmp_path / "gfx.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp_path / "gfx.fjm"
    fj.assemble([p.resolve()], out, memory_width=W, print_time=False)
    term = fj.run(out, print_time=False, print_termination=False)
    assert str(term.storage_mode) == "flat"
