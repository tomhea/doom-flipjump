"""M13pS2 -- THE COLUMN-STREAM COMPOSITE gates: the full raster_mode="stream" renderer (pass-1 builds
per-column band lists via plane.build_bands; the frame leaves the program as the device run-stream --
present.begin_frame_stream + one stream.emit_column per column; NO framebuffer, NO pass-2, NO plane
machinery), decoded by StreamScreen and compared byte-exact against the (band-walked, F4 re-blessed)
oracle `render_wall_frame(floor_texturing=False, wall_mode="W1")`.

Supersedes the pS2c-wiring band-list dump test (the producer plumbing is now exercised end-to-end:
band-list bytes ARE the frame) and the legacy framebuffer-flat gates in test_floor_planes_fj.py
(skipped there -- the walked oracle intentionally diverges from the legacy exact-per-row
draw_span_flat kernel by <=1-row band edges).

The corner viewpoint (24,24)@0x20000000 is load-bearing: at the square spawn every wall reaches the
screen top (cexcl=0 -> the ceiling build_bands call takes its empty early-exit), so spawn alone would
leave the CEILING band path vacuously untested (fj-lessons R17); the corner viewpoint has cexcl>0 AND
fstart<VIEW_H across the frame, so both band calls write and both windows emit.
"""
from pathlib import Path

import flipjump as fj
from flipjump.fjm.fjm_reader import Reader

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import (ReferenceModel, SimState, build_scene, spawn_state, frame_hash)
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer

from tests.fj.stream_screen import StreamScreen

PRESENT_FJ = Path("src/fj/present.fj")
FRAME_FJ = Path("src/fj/frame_render.fj")
PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
PLANE_BANDS_FJ = Path("src/fj/plane_bands.fj")
PLANE_FJ = Path("src/fj/plane_render.fj")
STREAM_RENDER_FJ = Path("src/fj/stream_render.fj")
ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"

# the W1-wall + flat-floor + band-walked-zidx spawn goldens (M13pS2 -- a NEW mode combination; the
# flat-floor F4 re-bless is folded in, see tests/host/test_floor_planes.py's e1m1 hash note)
SQUARE_STREAM_GOLDEN = "39e7d42eba95e1bb3587ae0b46f3281f791faeabb70edc0e74826b956c27d631"
E1M1_STREAM_GOLDEN = "229b80e123daa2e57a8e332e53fe6c11d3e7177fc96e347008f0b0dd54552b93"  # crush2b shared-walk floors


def _assemble_stream(tmp_path, map_wad, mapname, cfg, asset_wad=None):
    main = emit_wall_renderer(map_wad, mapname, cfg, asset_wad=asset_wad, over_align=False,
                              floor_mode="flat", wall_mode="W1", raster_mode="stream")
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "stream.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "stream.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), PLANE_BANDS_FJ.resolve(),
                 PLANE_FJ.resolve(), STREAM_RENDER_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    return out


RENDER_FLAT_WORDS = 1 << 26   # R4: measure in FLAT storage or the op count isn't baseline-comparable


def _run_stream(out, vx, vy, va):
    screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_WORDS)
    assert str(term.storage_mode) == "flat", f"R4: storage_mode {term.storage_mode!r} != flat"
    return screen, term


def test_square_stream_frame_byte_exact_vs_oracle(tmp_path):
    """ONE assemble, 5 stdin viewpoints (the 4 legacy flat-gate viewpoints + the non-vacuous-ceiling
    corner one), each decoded StreamScreen grid byte-exact vs the oracle; spawn matches the golden."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45),
                  (24, 24, A45)]                          # the cexcl>0 ceiling-exercising corner
    out = _assemble_stream(tmp_path, mw, "MAP01", cfg, asset_wad=aw)
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                    floor_texturing=False, wall_mode="W1")
        screen, _term = _run_stream(out, vx, vy, va)
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"stream @ ({vx},{vy},{va:#x}) != oracle W1/flat frame"
        assert screen.frame_count == 1 and screen.flush_count == 1
        if k == 0:
            assert frame_hash(got) == SQUARE_STREAM_GOLDEN, \
                f"stream spawn hash {frame_hash(got)} != golden"


def test_e1m1_stream_full_frame_byte_exact_and_golden(tmp_path):
    """THE pS2 CAPSTONE: the full E1M1 column-stream frame -- byte-exact vs the oracle over
    spawn + rotation + 2 other-viewpoint frames, spawn matching the stream golden. Reports
    ops/frame (the pS2 MEASURE gate: expect ~110-140M vs the 265.7M flat+W1 framebuffer state)
    and the span (no fb, no pass-2 unroll, no plane machinery -- expect a big drop from 20.1M)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1_WAD)
    scene = build_scene(mw, mw, "E1M1")

    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    things = mw.things("E1M1")
    VIEWPOINTS = [(spx, spy, sp.angle),
                  (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    seen = {(spx, spy)}
    for t in things:
        if (t.x, t.y) not in seen:
            seen.add((t.x, t.y)); VIEWPOINTS.append((t.x, t.y, sp.angle))
        if len(VIEWPOINTS) >= 4:
            break

    out = _assemble_stream(tmp_path, mw, "E1M1", cfg)
    span = max(s.segment_start + s.segment_length for s in Reader(out).memory_segments)
    print(f"[pS2] E1M1 stream span = {span:,} words")

    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    floor_texturing=False, wall_mode="W1")
        screen, term = _run_stream(out, vx, vy, va)
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"stream @ ({vx},{vy},{va:#x}) != oracle E1M1 W1/flat frame"
        if k == 0:
            assert frame_hash(got) == E1M1_STREAM_GOLDEN, \
                f"stream spawn hash {frame_hash(got)} != golden"
            print(f"[pS2] E1M1 stream spawn frame = {term.op_counter:,} ops")
