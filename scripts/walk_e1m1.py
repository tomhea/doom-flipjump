"""walk_e1m1 -- the closest thing to PLAYING the game today: a pygame window you walk around in,
where EVERY FRAME IS RENDERED BY THE REAL FLIPJUMP PROGRAM (the shipping raster_mode="lines"
renderer, assembled once at startup). There is no fj-side input/simulation yet (that's M14) --
this host loop feeds the viewpoint to the .fjm via stdin and re-runs it per move, so movement,
collision and turning are host-side stand-ins while the RENDERING is 100% the real thing.

Controls:  W/S or Up/Down = forward/back    A/D = strafe    Left/Right = turn
           Q or Esc = quit                  P = save a screenshot PNG next to this script

Frame rate = however fast the Python fj interpreter chews ~18-20M ops (tens of seconds/frame on
CPython -- a slideshow, but a REAL one). Run:
    python scripts/walk_e1m1.py                 # E1M1, subsample x2 (fastest)
    python scripts/walk_e1m1.py --subsample 1   # full resolution
    python scripts/walk_e1m1.py --wad tests/fixtures/square_room.wad --map MAP01 \\
           --asset tests/fixtures/freedoom_assets.wad
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
from doomfj.harness import W
from doomfj.reference_model import spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from tests.fj.stream_screen import StreamScreen

SRC = [ROOT / "src/fj" / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
        "plane_bands.fj", "stream_render.fj")]
ANG_STEP = 0x08000000          # 11.25 degrees per turn
MOVE_STEP = 24                 # map units per step
SCALE = 4                      # window upscale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default=None)
    ap.add_argument("--subsample", type=int, default=2, choices=[1, 2])
    args = ap.parse_args()

    cfg = Config()
    mw = WadFile.from_path(str(ROOT / args.wad))
    aw = WadFile.from_path(str(ROOT / args.asset)) if args.asset else mw

    print(f"assembling the fj renderer ({args.map}, lines mode, subsample={args.subsample}) ...")
    t0 = time.perf_counter()
    main_txt = emit_wall_renderer(mw, args.map, cfg, asset_wad=aw, over_align=False,
                                  floor_mode="flat", wall_mode="W1", raster_mode="lines",
                                  lines_subsample=args.subsample)
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    (tmp / "m.fj").write_text(main_txt, encoding="utf-8")
    fjm = tmp / "m.fjm"
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
                fjm, memory_width=W, print_time=False)
    print(f"assembled in {time.perf_counter() - t0:.0f}s -- opening the window")

    pal = aw.playpal()
    sp = spawn_state(mw, args.map)
    px = _signed(sp.x, 32) >> 16
    py = _signed(sp.y, 32) >> 16
    ang = sp.angle

    import pygame
    pygame.init()
    win = pygame.display.set_mode((cfg.VIEW_W * SCALE, cfg.VIEW_H * SCALE))
    pygame.display.set_caption("doom-flipjump  --  every frame rendered by FlipJump")
    surf = pygame.Surface((cfg.VIEW_W, cfg.VIEW_H))

    def render():
        t = time.perf_counter()
        screen = StreamScreen(stdin=f"{px}\n{py}\n{ang}\n".encode())
        term = fj.run(fjm, io_device=screen, print_time=False, print_termination=False,
                      flat_max_words=1 << 26)
        pix = screen.pixel_indices
        for y in range(cfg.VIEW_H):
            for x in range(cfg.VIEW_W):
                surf.set_at((x, y), pal[pix[y * cfg.VIEW_W + x]])
        pygame.transform.scale(surf, win.get_size(), win)
        pygame.display.flip()
        dt = time.perf_counter() - t
        pygame.display.set_caption(
            f"doom-flipjump  ({px},{py}) ang={ang:#010x}  "
            f"{term.op_counter:,} fj ops in {dt:.1f}s")
        return term.op_counter, dt

    import math
    ops, dt = render()
    print(f"first frame: {ops:,} fj ops in {dt:.1f}s -- W/S move, A/D strafe, arrows turn, Q quits")
    running = True
    while running:
        moved = False
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                k = ev.key
                fx = math.cos(ang / 2**32 * 2 * math.pi)
                fy = math.sin(ang / 2**32 * 2 * math.pi)
                if k in (pygame.K_q, pygame.K_ESCAPE):
                    running = False
                elif k in (pygame.K_w, pygame.K_UP):
                    px += round(fx * MOVE_STEP); py += round(fy * MOVE_STEP); moved = True
                elif k in (pygame.K_s, pygame.K_DOWN):
                    px -= round(fx * MOVE_STEP); py -= round(fy * MOVE_STEP); moved = True
                elif k == pygame.K_a:
                    px -= round(fy * MOVE_STEP); py += round(fx * MOVE_STEP); moved = True
                elif k == pygame.K_d:
                    px += round(fy * MOVE_STEP); py -= round(fx * MOVE_STEP); moved = True
                elif k == pygame.K_LEFT:
                    ang = (ang + ANG_STEP) & 0xFFFFFFFF; moved = True
                elif k == pygame.K_RIGHT:
                    ang = (ang - ANG_STEP) & 0xFFFFFFFF; moved = True
                elif k == pygame.K_p:
                    pygame.image.save(win, str(ROOT / "scripts" / "walk_screenshot.png"))
                    print("screenshot saved to scripts/walk_screenshot.png")
        if moved and running:
            try:
                render()
            except Exception as e:                       # a viewpoint outside the map can crash the
                print(f"render failed at ({px},{py}): {e}")   # renderer -- step back and carry on
        pygame.time.wait(20)
    pygame.quit()


if __name__ == "__main__":
    main()
