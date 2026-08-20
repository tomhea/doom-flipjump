"""M10 (R0 gate) — the E1M1 integration: the committed full-E1M1 fixture, the shared 2x D5 downscale
lever (bit-exact, imported by BOTH the texture compiler and the oracle — R6/D12), and the unified-build
flat/span guard (R4). The full 1.41M-texel measurement is recorded in DESIGN §1.2/§1.3 + versions/;
these tests assert correctness on a fast subset.
"""
from pathlib import Path

import pytest

from doomfj import reference_model, texturecompiler
from doomfj.build import build_doom, build_wall_renderer
from doomfj.config import Config, FLAT_MAX_WORDS, RENDER_FLAT_MAX_WORDS
from doomfj.texturecompiler import (
    downscale_canvas, composite_texture, texture_texels, compile_texture, compile_flat,
)
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
SPRITE_WAD = Path("assets/freedoom1.wad")     # V4 art: the cut-down fixture has no sprite lumps
# ⚠ B0 -- MEASURED 2026-08-19, and the provisional band was wrong in the informative direction.
# The shipped tier (sim + collide + the full fixture) is 84,823,030 words, NOT the ~68.2M carried
# over from the M14 gate's lighter binary. headroom=1.582 against 2**27; against the old 2**26 it
# would have been 1.26x OVER, so the limit raise was required, not cosmetic.
#   R4 shipped-tier metrics: tier=lines/W1R/FT1+plane_near span=84,823,030 words
#   limit=134,217,728 headroom=1.582 fjm=23,432,034 bytes assemble=8054.988s
# ⚠ THAT 8,054 s FIGURE IS HISTORY. The assembler was rebuilt 2026-08-20 (flipjump-151 06385ad +
# 108e391) and the SAME program now assembles in 559 s -- 9m19s, measured, decompressing to a
# byte-identical 314,505,544-byte program image. The old note here said "every gate on this tier is
# a two-hour commitment" and priced three levels in one image at 4-5 hours; both are now wrong by
# an order of magnitude (three levels projects to ~30 min). See docs/handoff-complete-game.md.
SPAN_LO, SPAN_HI = 70_000_000, 100_000_000    # bracketing the MEASURED 84.82M, not a guess:
                                              # 51.21M words (CR-2026-08 recalibration -- the old
                                              # 9-18M band predated V4-HD full-res sprite buckets,
                                              # V5 stacked pieces/regions and SPR-NEAR's dual bank;
                                              # this hour-long gate had not run since). The hard
                                              # ceiling stays the separate span < RENDER_FLAT_MAX_WORDS
                                              # HI at 62M leaves real headroom warning-room below it.


# ── the downscale factor is config-derived (R6) ─────────────────────────────

def test_texture_downscale_is_config_derived():
    """D5 factor = NATIVE_W // W: 2x at the 160 build, 1x (none) at native 320 (where the flat limit is
    raised instead). Never a literal — switch resolution and it follows."""
    assert Config().TEXTURE_DOWNSCALE == 2
    assert Config(W=320).TEXTURE_DOWNSCALE == 1
    assert Config(W=160).NATIVE_W == 320


# ── the shared downscale function (subsample, bit-exact) ────────────────────

def test_downscale_identity():
    grid = [[1, 2, 3], [4, 5, 6]]
    out = downscale_canvas(grid, 1)
    assert out == grid and out is not grid          # a copy, equal

def test_downscale_2x_subsample():
    """out[r][c] = in[r*2][c*2] — top-left of each 2x2 block (palette indices are categorical, so we
    subsample, never average)."""
    grid = [[10 * r + c for c in range(4)] for r in range(4)]
    assert downscale_canvas(grid, 2) == [[0, 2], [20, 22]]

def test_downscale_dims():
    grid = [[0] * 128 for _ in range(64)]   # 64 rows x 128 cols
    out = downscale_canvas(grid, 2)
    assert len(out) == 32 and len(out[0]) == 64

def test_downscale_preserves_transparency():
    grid = [[None, 5], [7, None]]
    assert downscale_canvas(grid, 1) == [[None, 5], [7, None]]


# ── downscale threaded into the compilers (texel count drops by factor^2) ───

def test_compile_texture_downscaled_texel_count():
    wad = WadFile.from_path(E1M1)
    defs = {d.name: d for d in wad.texture_defs()}
    name = next(n for n, d in defs.items() if d.width % 2 == 0 and d.height % 2 == 0)
    full = texture_texels(composite_texture(wad, defs[name]))
    down = texture_texels(downscale_canvas(composite_texture(wad, defs[name]), 2))
    assert len(down) == len(full) // 4
    d = defs[name]
    assert len(down) == (d.width // 2) * (d.height // 2)

def test_compile_flat_downscaled_assembles():
    """compile_flat at downscale 2 emits a 32x32 (=1024 texel) table; here we just check the count via
    the public helper (assembly is covered by the flat-build test)."""
    wad = WadFile.from_path(E1M1)
    name = wad.lumps_between("F_START", "F_END")[0].name
    assert len(texturecompiler.flat_texels(wad, name, downscale=2)) == 32 * 32
    assert len(texturecompiler.flat_texels(wad, name, downscale=1)) == 64 * 64


# ── R6: the oracle and the compiler share the SAME downscale function ────────

def test_oracle_shares_downscale_lever():
    """D5/D12/R6: one bit-exact downscale, imported by both H4 (texturecompiler) and H5 (oracle)."""
    assert reference_model.downscale_canvas is texturecompiler.downscale_canvas
    assert reference_model.ReferenceModel().downscale == Config().TEXTURE_DOWNSCALE == 2


# ── the committed fixture is the full E1M1 ──────────────────────────────────

def test_fixture_is_full_e1m1():
    wad = WadFile.from_path(E1M1)
    assert "E1M1" in wad.names()
    assert len(wad.texture_defs("TEXTURE1")) == 114
    assert len(wad.lumps_between("F_START", "F_END")) == 43
    assert len(wad.lumps_between("P_START", "P_END")) == 163
    assert len(wad.things("E1M1")) > 0 and len(wad.linedefs("E1M1")) > 0
    assert len(wad.playpal(0)) == 256 and len(wad.colormap()) >= 32


# ── R4: the unified build is flat and under the span limit ──────────────────

def test_build_doom_subset_is_flat(tmp_path):
    """A small downscaled E1M1 build (a few textures/flats + the LUTs) must run on the flat path with
    span < the flat limit (R4 committed assemble-flat guard). The full-E1M1 span is in DESIGN §1.2."""
    wad = WadFile.from_path(E1M1)
    tex = [d.name for d in wad.texture_defs("TEXTURE1")][:2]
    flat = [wad.lumps_between("F_START", "F_END")[0].name]
    m = build_doom(E1M1, "E1M1", out_fjm=tmp_path / "doom.fjm", generated_dir=tmp_path / "gen",
                   texture_subset=tex, flat_subset=flat, lights=2)
    assert m["storage_mode"] == "flat", m
    assert m["span_words"] < FLAT_MAX_WORDS
    assert m["headroom"] > 1.0
    assert m["entry_counts"]["textures"] > 0


# ── M12rr: the SHIPPED runtime wall renderer (build_wall_renderer) is flat under the RAISED limit ──

@pytest.mark.slow          # Excluded by default via addopts; `-m slow` runs it. SOLO (CLAUDE.md #1).
                           # ⚠ COST UNMEASURED SINCE 2026-08-20. Last measured end-to-end at 29:43
                           # (emit + assemble). The assemble half got 3.1x faster that day
                           # (1,729 s -> 559 s on the same program), so expect roughly half -- but
                           # this test prints its own `assemble=` line, so read that, don't guess.
@pytest.mark.skipif(not SPRITE_WAD.exists(),
                    reason=f"{SPRITE_WAD} absent -- the shipped tier's V4 things need sprite lumps")
def test_build_wall_renderer_e1m1_flat(tmp_path):
    """M12rr/M13c3 (build_doom wiring) — the SHIPPED runtime wall+floor/ceiling renderer assembles flat and
    under the RAISED flat limit `config.RENDER_FLAT_MAX_WORDS` (R0/R4). build_wall_renderer emits via the SHARED
    doomfj.wall_renderer.emit_wall_renderer — the SAME optimized renderer (M12oo trampoline + M12pp/qq
    xor_by-involution walk + the M13c3 plane_tramp visplane raster) the byte-exact golden test renders through
    (R6) — so this gates the production build.

    The shipped defaults are now the LINES tier with all four visual features on (WPX walls + FT1 floors
    + plane_near + V1 grain / V2 sky / V3 step faces / V4 things), which is what walk_e1m1 shows and what
    tests/fj/test_visual_features.py proves byte-exact. The sprite bank dominates the span; the bound
    below is the sanity band around the measured figure, not a target. ⚠ SLOW: the V4 build is a
    ~42M-character program. (The assembler is LINEAR in program size -- measured exponent 1.12 --
    not "~cubic" as this repo long assumed; what made it slow was paging, now fixed.)"""
    m = build_wall_renderer(E1M1, "E1M1", out_fjm=tmp_path / "renderer.fjm",
                            generated_dir=tmp_path / "gen",
                            flat_max_words=RENDER_FLAT_MAX_WORDS)
    # G1/R2: this 30-minute run is the only place the shipped tier's span, .fjm size and assemble
    # time are measured. It used to assert them and print NOTHING, so a passing run left no number
    # for the perf ledger and the next session had to spend the 30 minutes again to learn one.
    print(f"\nR4 shipped-tier metrics: tier={m['tier']} span={m['span_words']:,} words "
          f"limit={RENDER_FLAT_MAX_WORDS:,} headroom={m['headroom']} "
          f"fjm={m['fjm_bytes']:,} bytes "
          f"assemble={m['assemble_seconds']}s", flush=True)
    assert m["storage_mode"] == "flat", m
    assert m["span_words"] < RENDER_FLAT_MAX_WORDS
    assert m["headroom"] > 1.0
    # CR-2026-08 (IN-3, A0.1) — this pair is the ONLY automated guard that the shipped picture is the
    # one the walker shows and `deg_gate` certifies. It asserted WPX and four features while build.py
    # had moved to W1R + stack_steps/bbox_cull/deg; a fan-out miss the 70-min runtime hid.
    assert m["features"] == {"wall_noise": True, "sky": True, "steps": True, "things": True,
                             "stack_steps": True, "bbox_cull": True, "deg": True,
                             # B0: the shipped artifact runs the sim, same as the walker
                             "player_sim": True, "collide": True, "moving_things": True,
                             "state_wire": "bin"}, m
    assert m["tier"] == "lines/W1R/FT1+plane_near", m
    assert SPAN_LO < m["span_words"] < SPAN_HI, m


def test_shipped_sprite_wad_resolution():
    """V4's art source resolves explicitly or RAISES — it never silently ships things=True with an
    empty sprite bank. The cut-down fixture has no S_START..S_END at all, which is the whole reason
    `sprite_wad` is a separate argument."""
    from doomfj.build import _resolve_sprite_wad

    fixture = WadFile.from_path(E1M1)
    assert "S_START" not in fixture.names()               # the premise
    with pytest.raises(ValueError, match="sprite"):
        _resolve_sprite_wad(fixture, "no/such/file.wad")  # absent default + a spriteless map wad
    with pytest.raises(ValueError, match="S_START"):
        _resolve_sprite_wad(fixture, fixture)             # explicitly handed a spriteless wad
    if SPRITE_WAD.exists():
        assert "S_START" in _resolve_sprite_wad(fixture, SPRITE_WAD).names()
