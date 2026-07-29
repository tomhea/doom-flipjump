"""M13-lines — the DUMB-DEVICE renderer (owner ruling 2026-07-27: the device may only print what
it is told — explicit lines/rectangles/pixels; no projection, no DDA, no shading, no resident
geometry). fj does EVERYTHING: BSP walk, wedge + back-face culls, per-seg projection, per-column
top/bottom + clipping, occlusion (claim-time, front-to-back), distance-light band boundaries and
colormap lookups. The device receives the 0x0B packed column-run frame: per column [x] +
[y2][colour] pairs filling rows top-down (plus the 0xFE "ditto" = copy column x-1, the
owner-approved rectangle-widening), 0xFF ends a column / the frame.

Byte-exact vs the same W1/flat oracle as the stream/spans/raster gates."""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer

from tests.fj.stream_screen import StreamScreen

SRC = [Path("src/fj") / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
        "plane_bands.fj", "stream_render.fj")]
ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"

RENDER_FLAT_WORDS = 1 << 26


def _assemble_lines(tmp_path, map_wad, mapname, cfg, asset_wad=None,
                    wall_mode="W1", floor_mode="flat"):
    main = emit_wall_renderer(map_wad, mapname, cfg, asset_wad=asset_wad, over_align=False,
                              floor_mode=floor_mode, wall_mode=wall_mode, raster_mode="lines")
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "lines.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "lines.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()],
                out, memory_width=W, print_time=False)
    return out


def _run_lines(out, vx, vy, va):
    screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_WORDS)
    assert str(term.storage_mode) == "flat", f"R4: storage_mode {term.storage_mode!r} != flat"
    return screen, term


def test_square_lines_frame_byte_exact_vs_oracle(tmp_path):
    """The square room: the 5 stream-gate viewpoints (incl. the (24,24) negative-viewz straddle
    viewpoint, which exercises BOTH lazy half-window band builds), each decoded frame byte-exact
    vs the W1/flat oracle."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45), (24, 24, A45)]
    out = _assemble_lines(tmp_path, mw, "MAP01", cfg, asset_wad=aw)
    for vx, vy, va in VIEWPOINTS:
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                    floor_texturing=False, wall_mode="W1")
        screen, _term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want), \
            f"lines @ ({vx},{vy},{va:#x}) != oracle W1/flat frame"
        assert screen.frame_count == 1 and screen.flush_count == 1


def test_e1m1_lines_frame_byte_exact_vs_oracle(tmp_path):
    """The full E1M1 frame over 4 viewpoints, byte-exact vs the W1/flat oracle. Reports the spawn
    ops/frame (the <30M dumb-device campaign metric)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1_WAD)
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    for t in mw.things("E1M1"):
        if (t.x, t.y) != (spx, spy):
            VIEWPOINTS.append((t.x, t.y, sp.angle))
        if len(VIEWPOINTS) >= 4:
            break
    out = _assemble_lines(tmp_path, mw, "E1M1", cfg)
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    floor_texturing=False, wall_mode="W1")
        screen, term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want), \
            f"lines @ ({vx},{vy},{va:#x}) != oracle E1M1 W1/flat frame"
        if k == 0:
            print(f"[lines] E1M1 spawn frame = {term.op_counter:,} ops")


def test_fjm_runner_matches_flipjump_run(tmp_path):
    """`doomfj.fastrun.FjmRunner` (the walker's engine: load the .fjm ONCE, run it per frame) must
    produce EXACTLY what `flipjump.run` produces — same pixels, same op count, across repeated runs.

    The repetition is the real assertion: FlipJump programs self-modify (`wflip`, and this
    renderer's whole `xor_by` machinery), so the runner has to restore a pristine memory image
    before each run. A regression there does not crash, it silently renders a different frame —
    measured, a second run on a reused image halts after 9 ops."""
    from doomfj.fastrun import FjmRunner
    cfg = Config()
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    VIEWPOINTS = [(spx, spy, sp.angle), (24, 24, 0x20000000), (200, 128, 0), (24, 24, 0x20000000)]
    out = _assemble_lines(tmp_path, mw, "MAP01", cfg, asset_wad=aw,
                          wall_mode="WPX", floor_mode="FT1")
    want = [(bytes(s.pixel_indices), t.op_counter)
            for s, t in (_run_lines(out, *vp) for vp in VIEWPOINTS)]
    runner = FjmRunner(out, flat_max_words=RENDER_FLAT_WORDS)
    for vp, (want_px, want_ops) in zip(VIEWPOINTS, want):
        screen = StreamScreen(stdin=f"{vp[0]}\n{vp[1]}\n{vp[2]}\n".encode())
        ops = runner.run(screen)
        assert ops == want_ops, f"FjmRunner op count {ops:,} != {want_ops:,} @ {vp}"
        assert bytes(screen.pixel_indices) == want_px, f"FjmRunner pixels differ @ {vp}"


def test_square_lines_wpx_ft1_byte_exact_vs_oracle(tmp_path):
    """The WPX+FT1 visual tier (owner call 2026-07-29: "can the walls get 1x1 pixel textures and
    still be <25M"). WPX = one texture texel per screen pixel down each wall column, run-merged and
    baked per EXACT wall height, so the fj emit is one add per colour run. Byte-exact vs the
    same-tier oracle on the 5 square viewpoints (which include the negative-viewz straddle)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45), (24, 24, A45)]
    out = _assemble_lines(tmp_path, mw, "MAP01", cfg, asset_wad=aw,
                          wall_mode="WPX", floor_mode="FT1")
    for vx, vy, va in VIEWPOINTS:
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                    floor_texturing=False, wall_mode="WPX", floor_mode_ft1=True)
        screen, _term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want), \
            f"lines WPX+FT1 @ ({vx},{vy},{va:#x}) != oracle"


def test_e1m1_lines_wpx_ft1_byte_exact_vs_oracle(tmp_path):
    """E1M1 spawn + rotation at the SHIPPING WPX+FT1 tier, byte-exact vs the oracle. Reports
    ops/frame against the owner's 25M ceiling (the W2S+FT1 tier below it measures 23.16M)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1_WAD)
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    out = _assemble_lines(tmp_path, mw, "E1M1", cfg, wall_mode="WPX", floor_mode="FT1")
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    floor_texturing=False, wall_mode="WPX", floor_mode_ft1=True)
        screen, term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want), \
            f"lines WPX+FT1 @ ({vx},{vy},{va:#x}) != E1M1 oracle"
        if k == 0:
            print(f"[lines WPX+FT1] E1M1 spawn frame = {term.op_counter:,} ops")
            assert term.op_counter < 25_000_000, "WPX+FT1 broke the 25M ceiling"


def test_square_lines_w2s_ft1_byte_exact_vs_oracle(tmp_path):
    """The W2S+FT1 visual tier (owner call 2026-07-29: the plain look should gain wall texture and
    floor variety while staying under 24M). W2S = the 16-texel wall strip stretched over each
    wall's span; FT1 = each distance band taking the flat's band-ordinal diagonal texel instead of
    one shared base colour. Byte-exact vs the same-tier oracle on the 5 square viewpoints."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    aw = WadFile.from_path(ASSET)
    scene = build_scene(mw, aw, "MAP01")
    sp = spawn_state(mw, "MAP01")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    A45 = 0x20000000
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, A45), (200, 128, 0), (128, 128, A45), (24, 24, A45)]
    out = _assemble_lines(tmp_path, mw, "MAP01", cfg, asset_wad=aw,
                          wall_mode="W2S", floor_mode="FT1")
    for vx, vy, va in VIEWPOINTS:
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                    floor_texturing=False, wall_mode="W2S", floor_mode_ft1=True)
        screen, _term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want),             f"lines W2S+FT1 @ ({vx},{vy},{va:#x}) != oracle"


def test_e1m1_lines_w2s_ft1_byte_exact_vs_oracle(tmp_path):
    """E1M1 spawn + rotation at the W2S+FT1 tier, byte-exact vs the oracle. Reports ops/frame
    (23.16M at the time of writing, against the 24M ceiling and the 20.64M W1/flat tier)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1_WAD)
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    out = _assemble_lines(tmp_path, mw, "E1M1", cfg, wall_mode="W2S", floor_mode="FT1")
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    floor_texturing=False, wall_mode="W2S", floor_mode_ft1=True)
        screen, term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want),             f"lines W2S+FT1 @ ({vx},{vy},{va:#x}) != E1M1 oracle"
        if k == 0:
            print(f"[lines W2S+FT1] E1M1 spawn frame = {term.op_counter:,} ops")
