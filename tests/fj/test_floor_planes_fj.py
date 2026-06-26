"""M13d2 (F5) — the fj FLOOR/CEILING (visplane) TEXTURED raster wired into the SHARED `emit_wall_renderer`,
byte-exact vs the host oracle `render_wall_frame()` (the textured DEFAULT, R_DrawPlanes). Pass 1 stores the
per-column plane params (ceiling region `cexcl`, floor region `fstart`, the ceil/floor planeheights, the RAW
sector light, and the ceil/floor flat SLICE offset) via `seg_pass1_leaf_body_mtlwp`; the per-frame
`plane.clear_planes` seeds basexscale/baseyscale, and the runtime per-ROW `frame.render_planes_spans`
(R_MakeSpans) groups same-visplane columns into spans rasterized by `plane.draw_span` (the 2-coord u,v DDA
sampling the combined FLAT texel table, distance-lit) — replacing the M13c3 per-column flat-colored
`plane_tramp`.

The square room (one real STEP4 wall texture -> a tiny combined table -> a fast assemble) runs through the
EXACT shared emitter `build_doom` ships (R6), byte-exact vs the oracle over several runtime viewpoints, the
spawn frame matching the published textured golden. The full E1M1 frame is the heavy multi-sector capstone.
"""
from pathlib import Path

import flipjump as fj
from flipjump.fjm.fjm_reader import Reader

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import (ReferenceModel, SimState, build_scene, spawn_state, frame_hash)
from doomfj.wall_renderer import emit_wall_renderer
from doomfj.wad import WadFile

from tests.fj.test_wall_render import _ScreenWithInput   # the stdin-fed InMemoryScreen

PRESENT_FJ = Path("src/fj/present.fj")
FRAME_FJ = Path("src/fj/frame_render.fj")
PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
PLANE_FJ = Path("src/fj/plane_render.fj")
ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"

# the M13b textured square-room golden (tests/host/test_floor_planes.py::test_square_textured_floor_golden_hash)
SQUARE_TEX_GOLDEN = "00de1aaadf358eae11ddbf75fd54e44c04549942cb8a6322ea35d856eb973a12"
# the M13b textured E1M1 spawn golden (tests/host/test_floor_planes.py::test_e1m1_textured_floor_golden_hash)
E1M1_TEX_GOLDEN = "db5d3da80a52c3ea78a8f599d121aaeb450bdfb84ca96b4656f0c267302ef0b2"


def test_square_textured_planes_byte_exact_vs_oracle(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")

    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = [
        (spx, spy, sp.angle),     # spawn (the golden viewpoint FIRST): head-on N wall, floor band below
        (spx, spy, A45),          # rotated 45 deg: a different wall set, ceiling + floor bands both visible
        (200, 128, 0),            # off-centre, close wall (large scale, uneven split)
        (128, 128, A45),          # centre, angled: two walls, even split
    ]

    # the SHARED emitter build_doom ships (R6); geometry from the square-room wad, assets from the asset wad.
    main = emit_wall_renderer(mw, "MAP01", cfg, asset_wad=aw, over_align=False)
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "squareflat.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "squareflat.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), PLANE_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene)   # textured DEFAULT
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"M13d2 @ ({vx},{vy},{va}) != oracle textured planes"
        if k == 0:                                            # the spawn frame must hash to the textured golden
            assert frame_hash(got) == SQUARE_TEX_GOLDEN, f"M13d2 spawn hash {frame_hash(got)} != golden"


def test_e1m1_textured_planes_full_frame_byte_exact_and_golden(tmp_path):
    """M13d2 — THE FULL E1M1 TEXTURED floor/ceiling frame through the SHARED emit_wall_renderer (the same
    emitter build_doom ships, R6), byte-exact vs the host oracle render_wall_frame() (textured DEFAULT) and
    matching the published M13b E1M1 spawn golden db5d3da8. The MULTI-SECTOR capstone the single-sector square
    room cannot give: across E1M1's 575 one-sided segs the per-seg ceil/floor heights, flats (the 37-slice
    combined flat table -> 5-nibble slice offsets), and RAW sector light all VARY; the per-column plane params
    are baked per seg via the xor_by involution + stored per claimed column, then the runtime per-ROW span pass
    (R_MakeSpans) groups same-visplane columns and the u,v DDA samples each flat. One assemble (the 198k-texel
    wall table + the 151k-texel flat table dominate; R4-gated flat under 2**26), several stdin viewpoints (spawn
    + a rotation + two other-sector positions) each byte-exact, the spawn frame hashing to the textured golden,
    and the spawn-frame ops/frame reported (the FIRST fps data point: fps ~= 280M fj/s / ops_per_frame)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1_WAD)
    scene = build_scene(mw, mw, "E1M1")

    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    things = mw.things("E1M1")
    VIEWPOINTS = [(spx, spy, sp.angle),                       # the golden viewpoint FIRST
                  (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    seen = {(spx, spy)}
    for t in things:                                          # other sectors -> player viewz/light vary
        if (t.x, t.y) not in seen:
            seen.add((t.x, t.y)); VIEWPOINTS.append((t.x, t.y, sp.angle))
        if len(VIEWPOINTS) >= 4:
            break

    main = emit_wall_renderer(mw, "E1M1", cfg, over_align=False)   # PRODUCTION layout (build_doom ships this)
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "e1m1flat.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "e1m1flat.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), PLANE_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    # R4: the WHOLE runtime renderer (combined wall + flat tables + framebuffer + LUTs + the 16K-pixel wall
    # pass-2 unroll + the runtime span pass + the 681-node walk) must run flat under the raised 2**26.
    RENDER_FLAT_WORDS = 1 << 26
    span = max(s.segment_start + s.segment_length for s in Reader(out).memory_segments)
    assert span < RENDER_FLAT_WORDS, f"R4: span {span} >= {RENDER_FLAT_WORDS}"
    assert 20_000_000 < span < 40_000_000, f"R4 sanity: span {span} (textured: wall+flat tables)"

    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene)   # textured DEFAULT
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        term = fj.run(out, io_device=screen, print_time=False, print_termination=False,
                      flat_max_words=RENDER_FLAT_WORDS)
        assert str(term.storage_mode) == "flat", f"R4: storage_mode {term.storage_mode!r} not flat @ {span} words"
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"M13d2 @ ({vx},{vy},{va}) != oracle textured planes"
        if k == 0:                                            # the spawn viewpoint must hash to the textured golden
            assert frame_hash(got) == E1M1_TEX_GOLDEN, f"M13d2 spawn hash {frame_hash(got)} != golden"
            ops = term.op_counter                             # FIRST fps data point (DESIGN §1: fps ~ 280M/ops)
            print(f"\nM13d2 E1M1 spawn frame: {ops:,} ops/frame  ~= {280_000_000 / ops:.2f} fps "
                  f"(span {span:,} words)")
            # MEASURED BASELINE (M13d2): ~1.165e9 ops/frame ~= 0.24 fps at 280M fj/s -- ~83x over the DESIGN
            # ~14M/20fps estimate. NOT @-at-scale (@~25-30); a per-pixel hot-path cost (~13.4k ops/pixel, the
            # nibble-op dispatch count -- table size is irrelevant). The PERF-REDUCTION PHASE addresses this;
            # see the handoff. Loose bound = a regression backstop, not the target.
            assert 0 < ops < 2_000_000_000, f"ops/frame {ops}"
