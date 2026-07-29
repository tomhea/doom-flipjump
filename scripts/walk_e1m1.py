"""walk_e1m1 -- the closest thing to PLAYING the game today: a pygame window you walk around in,
where EVERY FRAME IS RENDERED BY THE REAL FLIPJUMP PROGRAM (the shipping raster_mode="lines"
renderer, assembled once at startup). There is no fj-side input/simulation yet (that's M14) --
this host loop feeds the viewpoint to the .fjm via stdin and re-runs it per move, so movement,
collision and turning are host-side stand-ins while the RENDERING is 100% the real thing.

Controls:  W/S or Up/Down = forward/back    A/D = strafe    Left/Right = turn
           Q or Esc = quit                  P = save a screenshot PNG next to this script

Frame rate: the fj program runs on the NATIVE (C) engine at ~220M ops/s, and `doomfj.fastrun`
loads the .fjm ONCE instead of once per frame (`flipjump.run` re-parses the file and rebuilds the
memory image on every call -- 96% of its wall time here), so an E1M1 frame costs ~0.19s instead of
~2.6s: walkable, not a slideshow. Run:
    python scripts/walk_e1m1.py
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
from doomfj.fastrun import FjmRunner
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
    ap.add_argument("--wall-mode", default="WPX", choices=["W1", "W2S", "WPX"])
    ap.add_argument("--floor-mode", default="FT1", choices=["flat", "FT1"])
    ap.add_argument("--frames", type=int, default=0, metavar="N",
                    help="render N frames HEADLESSLY (no window) and report timings, then exit"
                         " -- use this to check the fj side independently of pygame")
    args = ap.parse_args()

    cfg = Config()
    mw = WadFile.from_path(str(ROOT / args.wad))
    aw = WadFile.from_path(str(ROOT / args.asset)) if args.asset else mw

    print(f"assembling the fj renderer ({args.map}, lines mode, "
          f"{args.wall_mode}+{args.floor_mode}) ...")
    t0 = time.perf_counter()
    main_txt = emit_wall_renderer(mw, args.map, cfg, asset_wad=aw, over_align=False,
                                  floor_mode=args.floor_mode, wall_mode=args.wall_mode,
                                  raster_mode="lines")
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    (tmp / "m.fj").write_text(main_txt, encoding="utf-8")
    fjm = tmp / "m.fjm"
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], (tmp / "m.fj").resolve()],
                fjm, memory_width=W, print_time=False)
    print(f"assembled in {time.perf_counter() - t0:.0f}s -- loading the program", flush=True)
    runner = FjmRunner(fjm)          # parse + memory-image prep ONCE, not once per frame
    print("engine: " + ("native (C)" if runner.native else
                        "pure-python FALLBACK -- ~14x slower"), flush=True)

    pal = aw.playpal()
    sp = spawn_state(mw, args.map)
    px = _signed(sp.x, 32) >> 16
    py = _signed(sp.y, 32) >> 16
    ang = sp.angle

    if args.frames:                      # headless: fj only, no pygame, no window
        for i in range(args.frames):
            t = time.perf_counter()
            screen = StreamScreen(stdin=f"{px}\n{py}\n{ang}\n".encode())
            ops = runner.run(screen)
            dt = time.perf_counter() - t
            print(f"  frame {i + 1}: {ops:,} fj ops in {dt * 1000:.0f}ms ({1 / dt:.1f} fps)",
                  flush=True)
            ang = (ang + ANG_STEP) & 0xFFFFFFFF
        return

    import pygame
    # display.init(), NOT pygame.init(): the latter also spins up the AUDIO MIXER, which can block
    # for a long time (or forever) on a Windows box with a flaky/absent audio device -- and the
    # symptom is exactly "the pygame banner printed and then no window ever appeared". Nothing here
    # makes a sound, so there is no reason to touch the mixer at all.
    print("  pygame.display.init() ...", flush=True)
    pygame.display.init()
    win = pygame.display.set_mode((cfg.VIEW_W * SCALE, cfg.VIEW_H * SCALE))
    pygame.display.set_caption("doom-flipjump  --  rendering the first frame ...")
    # paint + pump BEFORE the first render, so the window is on screen immediately instead of
    # staying invisible (or "not responding") for however long that first frame takes
    win.fill((24, 24, 28))
    pygame.display.flip()
    pygame.event.pump()
    print(f"  window open ({pygame.display.get_driver()}) -- rendering the first frame", flush=True)
    # palette as 256 ready-made RGB triples: the blit is then one C-level map+join instead of
    # 16,000 per-pixel surf.set_at calls (which cost about as much as the fj run itself now)
    pal3 = [bytes(pal[i]) for i in range(256)]

    def render():
        t = time.perf_counter()
        screen = StreamScreen(stdin=f"{px}\n{py}\n{ang}\n".encode())
        ops = runner.run(screen)
        frame = pygame.image.frombuffer(b"".join(map(pal3.__getitem__, screen.pixel_indices)),
                                        (cfg.VIEW_W, cfg.VIEW_H), "RGB")
        # .convert(win): frombuffer hands back a 24-bit surface, and scaling INTO the 32-bit
        # display surface needs a matching format
        pygame.transform.scale(frame.convert(win), win.get_size(), win)
        pygame.display.flip()
        dt = time.perf_counter() - t
        pygame.display.set_caption(
            f"doom-flipjump  ({px},{py}) ang={ang:#010x}  "
            f"{ops:,} fj ops in {dt * 1000:.0f}ms ({1 / dt:.1f} fps)")
        return ops, dt

    import math
    ops, dt = render()
    print(f"first frame: {ops:,} fj ops in {dt * 1000:.0f}ms ({1 / dt:.1f} fps)"
          f" -- W/S move, A/D strafe, arrows turn, Q quits")
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
