"""M13c3a (F5) — the fj FLOOR/CEILING (visplane) FLAT-COLORED raster wired into the SHARED
`emit_wall_renderer`, byte-exact vs the host oracle `render_wall_frame(floor_texturing=False)` (the M13a
flat tier). The two-band M9 background (`render_background_reg`) is replaced by a per-column visplane fill:
pass 1 stores the per-column plane params (ceiling region `cexcl`, floor region `fstart`, the ceil/floor
planeheights, the RAW sector light, and the ceil/floor flat base index) via the new
`seg_pass1_leaf_body_mtlwp`; a second unrolled pass-2 (`load_col_plane` + `plane_tramp` + the shared
`plane_compare_body` / `plane.draw_pixel` kernel) paints the floor/ceiling bands around each wall.

The square room (one real STEP4 wall texture -> a tiny combined table -> a fast assemble) lets this run
through the EXACT shared emitter `build_doom` ships (R6), byte-exact vs the oracle over several runtime
viewpoints, with the spawn frame matching the published flat-tier golden. E1M1 (the slow full-texture
assemble) is M13c3b.
"""
from pathlib import Path

import flipjump as fj

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

# the M13a flat-colored square-room golden (tests/host/test_floor_planes.py::test_square_flatcolored_floor_golden_hash)
SQUARE_FLAT_GOLDEN = "aeeb82a8bea795acf51edf4ff9150dab8f4bd15030f8e6008c6b00a1702d1463"


def test_square_flat_planes_byte_exact_vs_oracle(tmp_path):
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
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "MAP01"), scene, floor_texturing=False)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"M13c3a @ ({vx},{vy},{va}) != oracle flat planes"
        if k == 0:                                            # the spawn frame must hash to the flat golden
            assert frame_hash(got) == SQUARE_FLAT_GOLDEN, f"M13c3a spawn hash {frame_hash(got)} != golden"
