"""M13-spanfill — the DUMB-screen fillCol span protocol (0x0A). raster_mode="spans" shares the entire
stream pipeline (pass-1 band lists + col_struct + planesproto band buffers) and differs ONLY in the
present_tail: fj does the per-column ceiling/wall/floor clip itself and emits explicit
[x][y1][y2][colour] fillCol records; the device (StreamScreen._decode_spans_frame) just fills straight
vertical strips. Pixels are IDENTICAL to the planesproto/oracle frame (no re-bless) — this test asserts
the decoded span frame is byte-exact vs the same W1/flat oracle the stream gates use."""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
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

RENDER_FLAT_WORDS = 1 << 26


def _assemble_spans(tmp_path, map_wad, mapname, cfg, asset_wad=None):
    main = emit_wall_renderer(map_wad, mapname, cfg, asset_wad=asset_wad, over_align=False,
                              floor_mode="flat", wall_mode="W1", raster_mode="spans")
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "spans.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "spans.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), PLANE_BANDS_FJ.resolve(),
                 PLANE_FJ.resolve(), STREAM_RENDER_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    return out


def _run_spans(out, vx, vy, va):
    screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_WORDS)
    assert str(term.storage_mode) == "flat", f"R4: storage_mode {term.storage_mode!r} != flat"
    return screen, term


def test_square_spans_frame_byte_exact_vs_oracle(tmp_path):
    """The square room: 5 viewpoints (same as the stream gate), each decoded fillCol span frame
    byte-exact vs the W1/flat oracle. Pixels are unchanged from planesproto -- pure emit-format change."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45), (24, 24, A45)]
    out = _assemble_spans(tmp_path, mw, "MAP01", cfg, asset_wad=aw)
    for vx, vy, va in VIEWPOINTS:
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                    floor_texturing=False, wall_mode="W1")
        screen, _term = _run_spans(out, vx, vy, va)
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"spans @ ({vx},{vy},{va:#x}) != oracle W1/flat frame"
        assert screen.frame_count == 1 and screen.flush_count == 1


def test_e1m1_spans_frame_byte_exact_vs_oracle(tmp_path):
    """The full E1M1 frame over 4 viewpoints: decoded fillCol span frame byte-exact vs the W1/flat
    oracle. Reports ops/frame at spawn."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1_WAD)
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    things = mw.things("E1M1")
    seen = {(spx, spy)}
    for t in things:
        if (t.x, t.y) not in seen:
            seen.add((t.x, t.y)); VIEWPOINTS.append((t.x, t.y, sp.angle))
        if len(VIEWPOINTS) >= 4:
            break
    out = _assemble_spans(tmp_path, mw, "E1M1", cfg)
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    floor_texturing=False, wall_mode="W1")
        screen, term = _run_spans(out, vx, vy, va)
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"spans @ ({vx},{vy},{va:#x}) != oracle E1M1 W1/flat frame"
        if k == 0:
            print(f"[spans] E1M1 spawn frame = {term.op_counter:,} ops")
