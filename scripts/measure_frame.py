"""M13p0 — measure E1M1 (or square-room) spawn ops/frame through the SHARED emitter, with component
ablation (see doomfj.wall_renderer.emit_wall_renderer's `ablate` kwarg for the full mode list).

Usage:
    python scripts/measure_frame.py                          # full frame (sanity: should be ~462.7M for E1M1)
    python scripts/measure_frame.py --ablate planes
    python scripts/measure_frame.py --ablate planes,pass2,pass1
    python scripts/measure_frame.py --ablate segstub
    python scripts/measure_frame.py --wad tests/fixtures/square_room.wad --map MAP01 --asset tests/fixtures/freedoom_assets.wad

E1M1 assemble is ~605s (> the Bash tool's 600s timeout) -- run this via run_in_background with NO
shell `timeout` wrapper; the harness notifies on completion.
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.harness import W, FJM_LZMA_FAST
from doomfj.reference_model import spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.test_wall_render import _ScreenWithInput
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj")]
# M13pS2: raster_mode="stream" additionally needs the band-list kernel + the run emitter, and the
# frame decodes through StreamScreen (the run-stream device) instead of the framebuffer screen.
STREAM_SRC = [ROOT / "src/fj" / f for f in ("plane_bands.fj", "stream_render.fj")]

# R4/DESIGN §1.2: the renderer's span (~20-24M words) exceeds doomfj.config.FLAT_MAX_WORDS (2**23 default)
# -- every fj.run of this program (build_wall_renderer, the E1M1 capstone test) raises the limit to 2**26.
# BUG FOUND (2026-07-04): the first version of this script omitted this, so fj.run silently fell back to a
# non-flat storage mode with a DIFFERENT op cost (453.2M measured vs the true 462.7M baseline) -- always
# pass this explicitly; never trust a measurement that didn't.
RENDER_FLAT_WORDS = 1 << 26


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablate", default="", help="comma list: planes,pass2,pass1,segstub,xrstub")
    ap.add_argument("--floor-mode", default="textured", choices=["textured", "flat", "FT1"])
    ap.add_argument("--wall-mode", default="textured", choices=["textured", "W1", "W2", "W2S", "WPX"])
    ap.add_argument("--raster-mode", default="framebuffer",
                    choices=["framebuffer", "stream", "spans", "raster", "proj", "lines"])
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default=None, help="asset wad (defaults to --wad)")
    ap.add_argument("--vx", type=int, default=None)
    ap.add_argument("--vy", type=int, default=None)
    ap.add_argument("--va", type=int, default=None, help="viewangle (defaults to the spawn angle)")
    args = ap.parse_args()
    ablate = frozenset(x for x in args.ablate.split(",") if x)

    cfg = Config()
    mw = WadFile.from_path(str(ROOT / args.wad))
    aw = WadFile.from_path(str(ROOT / args.asset)) if args.asset else mw
    main_txt = emit_wall_renderer(mw, args.map, cfg, asset_wad=aw, over_align=False, ablate=ablate,
                                  floor_mode=args.floor_mode, wall_mode=args.wall_mode,
                                  raster_mode=args.raster_mode)

    src = SRC + (STREAM_SRC if args.raster_mode in ("stream", "spans", "raster", "proj", "lines") else [])
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    (tmp / "m.fj").write_text(main_txt, encoding="utf-8")
    t0 = time.perf_counter()
    fj.assemble([consts.resolve(), *[p.resolve() for p in src], (tmp / "m.fj").resolve()],
                tmp / "m.fjm", memory_width=W, print_time=False, lzma_fast=FJM_LZMA_FAST)
    assemble_seconds = round(time.perf_counter() - t0, 1)

    sp = spawn_state(mw, args.map)
    vx = args.vx if args.vx is not None else _signed(sp.x, 32) >> 16
    vy = args.vy if args.vy is not None else _signed(sp.y, 32) >> 16
    va = args.va if args.va is not None else sp.angle
    stdin = f"{vx}\n{vy}\n{va}\n".encode()
    screen = (StreamScreen(stdin=stdin) if args.raster_mode in ("stream", "spans", "raster", "proj", "lines")
             else _ScreenWithInput(stdin))
    term = fj.run(tmp / "m.fjm", io_device=screen, print_time=False, print_termination=False,
                  flat_max_words=RENDER_FLAT_WORDS)
    assert str(term.storage_mode) == "flat", (
        f"R4: storage_mode {term.storage_mode!r} != flat -- ops/frame is NOT comparable to the baseline")

    label = ",".join(sorted(ablate)) or "none"
    print(f"map={args.map} floor_mode={args.floor_mode} wall_mode={args.wall_mode} "
          f"raster_mode={args.raster_mode} viewpoint=({vx},{vy},{va}) ablate={label} "
          f"storage_mode={term.storage_mode} ops/frame={term.op_counter:,} "
          f"assemble_seconds={assemble_seconds}")


if __name__ == "__main__":
    main()
