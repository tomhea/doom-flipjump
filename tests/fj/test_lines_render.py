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
from doomfj.wireformat import encode_feed_mapunits

from tests.fj.stream_screen import StreamScreen

SRC = [Path("src/fj") / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
        "plane_bands.fj", "stream_render.fj")]
ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"

RENDER_FLAT_WORDS = 1 << 26


def _assemble_lines(tmp_path, map_wad, mapname, cfg, asset_wad=None):
    """The shipped tier: W1R walls, FT1 floors, the lines raster. Those were arguments while the
    ladder was being climbed (W1/flat -> WPX -> W1R -> W2S -> two-sided); they are the emitter's
    only behaviour now, so the rungs below W1R went with them."""
    main = emit_wall_renderer(map_wad, mapname, cfg, asset_wad=asset_wad, tier="render")
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "lines.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "lines.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()],
                out, memory_width=W, print_time=False)
    return out


def _run_lines(out, vx, vy, va):
    # ⚠ THE BINARY WIRE. Retiring `state_wire` removed the decimal feed, and a program
    # fed text now fails its MAGIC byte check and halts at `bad:` -- presenting NOTHING.
    # That reads as an all-zero frame vs the oracle's picture, i.e. exactly like a render
    # bug, which is how ~5 minutes went into looking at the renderer instead of the feed.
    screen = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_WORDS)
    assert str(term.storage_mode) == "flat", f"R4: storage_mode {term.storage_mode!r} != flat"
    return screen, term


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
    out = _assemble_lines(tmp_path, mw, "MAP01", cfg, asset_wad=aw)
    want = [(bytes(s.pixel_indices), t.op_counter)
            for s, t in (_run_lines(out, *vp) for vp in VIEWPOINTS)]
    runner = FjmRunner(out, flat_max_words=RENDER_FLAT_WORDS)
    for vp, (want_px, want_ops) in zip(VIEWPOINTS, want):
        screen = StreamScreen(stdin=encode_feed_mapunits(*vp))
        ops = runner.run(screen)
        assert ops == want_ops, f"FjmRunner op count {ops:,} != {want_ops:,} @ {vp}"
        assert bytes(screen.pixel_indices) == want_px, f"FjmRunner pixels differ @ {vp}"


def test_square_lines_w1r_ft1_byte_exact_vs_oracle(tmp_path):
    """M13-W1R — the RANDOMIZED W1 wall tier (owner ask 2026-08-02: per-pixel-looking texture
    inside the 15M budget): the wall keeps W1's one baked lit byte but is emitted as pseudo-random
    vertical runs re-shaded through the colormap, keyed on the V1 grain group (`wall_noise(x)`,
    already in the ditto signature) and a height tier (short = far = darker). Byte-exact vs the
    same-tier oracle on the 5 square viewpoints (incl. the negative-viewz straddle)."""
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
        # the emitter's tier, stated rather than inherited from five `False` defaults that no
        # longer exist on its side. `sky=False` because square_room.wad has NO F_SKY1 ceiling --
        # `map_has_sky` says so and the emitter skips the whole sky path for it. The other four are
        # unconditional now; on a one-sector room with no things they change nothing, which is why
        # this test kept passing while the E1M1 one did not.
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene,
                                    floor_texturing=False, wall_mode="W1R", floor_mode_ft1=True,
                                    wall_noise=True, plane_near=True, sky=False, near_steps=True,
                                    stack_steps=True, bbox_cull=True, degrade=True)
        screen, _term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want), \
            f"lines W1R+FT1 @ ({vx},{vy},{va:#x}) != oracle"


def test_e1m1_lines_w1r_ft1_byte_exact_vs_oracle(tmp_path):
    """E1M1 spawn + rotation at the W1R+FT1 tier, byte-exact vs the oracle."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1_WAD)
    scene = build_scene(mw, mw, "E1M1")
    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    VIEWPOINTS = [(spx, spy, sp.angle), (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    out = _assemble_lines(tmp_path, mw, "E1M1", cfg)
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        # ⚠ THE ORACLE HAS TO BE ASKED FOR THE PICTURE THE EMITTER NOW ALWAYS MAKES. sky, step
        # faces, stacked pieces, the bbox cull and the degradation package were emitter FLAGS that
        # defaulted to False, and this call inherited that default by omitting them. They are the
        # renderer now, so omitting them here asks the oracle for a tier that no longer exists --
        # which is a mismatch on E1M1 (19 sky ceilings) and invisible on the square room (none).
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                    floor_texturing=False, wall_mode="W1R", floor_mode_ft1=True,
                                    wall_noise=True, plane_near=True, sky=True, near_steps=True,
                                    stack_steps=True, bbox_cull=True, degrade=True)
        screen, term = _run_lines(out, vx, vy, va)
        assert bytes(screen.pixel_indices) == bytes(want), \
            f"lines W1R+FT1 @ ({vx},{vy},{va:#x}) != E1M1 oracle"
        if k == 0:
            print(f"[lines W1R+FT1] E1M1 spawn frame = {term.op_counter:,} ops")


