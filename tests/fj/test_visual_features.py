"""V1-V4 — the four VISUAL FEATURES, byte-exact against the oracle at four viewpoints.

V1 pseudo-random wall grain, V2 sky, V3 step faces, V4 thing sprites. Each is a keyword flag on
`emit_wall_renderer` (default False), so `tests/fj/test_lines_render.py` — which passes none of them
— is the regression net for the UNGATED build and this file is the net for the gated one. Both
matter: a gated feature can break the ungated build (an unused label is a hard assembler error), and
an ungated refactor can silently stop a gated feature from running (V4 lost every sprite in E1M1's
courtyard to a BSP prune that did not know about things).

⚠ SLOW. The sprite bank makes this a ~42M-character program and the assemble is ~7 minutes, so the
whole module is one test with one binary shared across the four viewpoints. Run it explicitly:

    python -m pytest tests/fj/test_visual_features.py -q

⚠ Sprite art comes from `assets/freedoom1.wad`. The cut-down fixture wad carries no sprite lumps at
all (223 lumps, no S_START), so V4 takes a separate `sprite_wad`; geometry, flats and colormap still
come from the fixture, so nothing but the sprites moves. The test SKIPS if that wad is absent.
"""
from pathlib import Path

import pytest

import flipjump as fj

from doomfj.config import Config
from doomfj.fastrun import FjmRunner
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer

from tests.fj.stream_screen import StreamScreen

SRC = [Path("src/fj") / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
        "plane_bands.fj", "stream_render.fj")]
E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"
SPRITE_WAD = "assets/freedoom1.wad"

# The four viewpoints are chosen so every branch of every feature fires at least once:
#   spawn      -- indoors, no sky, V3 lower faces only, no visible things
#   courtyard  -- outdoors: 139 sky columns, and the V3 seg budget actually binds
#   tree       -- a big near billboard plus 60+ competing things: the THING_BUDGET frame
#   worst      -- the heaviest frame of the sweep, and the only one with V3 UPPER faces
VIEWPOINTS = [(None, None, None, "spawn"), (1400, 1200, 0, "courtyard"),
              (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")]


@pytest.mark.skipif(not Path(SPRITE_WAD).exists(),
                    reason=f"{SPRITE_WAD} absent -- V4 needs a wad with sprite lumps")
def test_visual_features_byte_exact_vs_oracle(tmp_path):
    """One binary with all four features on, gated at four viewpoints. ~7 min to assemble."""
    cfg = Config()
    mw = WadFile.from_path(E1M1_WAD)
    art = WadFile.from_path(SPRITE_WAD)
    rm = ReferenceModel(cfg)
    scene = build_scene(mw, mw, "E1M1")

    sp = spawn_state(mw, "E1M1")
    vps = [(_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle, "spawn")
           if tag == "spawn" else (vx, vy, va, tag) for vx, vy, va, tag in VIEWPOINTS]

    main = emit_wall_renderer(mw, "E1M1", cfg, asset_wad=mw, over_align=False, floor_mode="FT1",
                              wall_mode="WPX", raster_mode="lines", plane_near=True,
                              wall_noise=True, sky=True, steps=True, things=True, sprite_wad=art)
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "vis.fj"
    p.write_text(main, encoding="utf-8")
    fjm = tmp_path / "vis.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()],
                fjm, memory_width=W, print_time=False)
    runner = FjmRunner(fjm)

    for vx, vy, va, tag in vps:
        want = bytes(rm.render_wall_frame(
            SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene,
            wall_mode="WPX", floor_mode_ft1=True, plane_near=True,
            wall_noise=True, sky=True, near_steps=True, things=True, sprite_wad=art))
        screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
        runner.run(screen)
        got = bytes(screen.pixel_indices)
        if got != want:
            bad = [i for i in range(len(got)) if got[i] != want[i]]
            cols = sorted({i % cfg.VIEW_W for i in bad})
            pytest.fail(f"{tag} ({vx},{vy},{va}): {len(bad)} pixels differ in {len(cols)} columns, "
                        f"first at (col {bad[0] % cfg.VIEW_W}, row {bad[0] // cfg.VIEW_W}); "
                        f"columns {cols[:12]}")
