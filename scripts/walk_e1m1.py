"""walk_e1m1 -- the closest thing to PLAYING the game today: a pygame window you walk around in,
where EVERY FRAME IS RENDERED BY THE REAL FLIPJUMP PROGRAM (the shipping raster_mode="lines"
renderer, assembled once at startup).

⚠ B0 (2026-08-18) -- THE SIM NOW RUNS IN FLIPJUMP. This docstring used to say "there is no fj-side
input/simulation yet (that's M14)", and that was true for months AFTER M14 and M14.5 shipped: both
were built, gated byte-exact and completely unreachable from anything a human runs, because
`sim.fj` was in no entry point's source list. The host now sends a KEY BITMASK and reads the
player's new position back OUT of the frame; it does not move, turn or collide the player at all.
Pass `--no-sim` for the old host-driven path (kept only as an A/B, not as a fallback).

⚠ NO STRAFE WITH THE SIM. `sim.fj`'s key set is forward/back/turn_left/turn_right -- there is no
strafe in the mirror, so A/D turn instead. Adding strafe is a SIM FEATURE (both mirrors, gated),
not wiring, and doing it host-side would put simulation back in the host, which is the one thing
B0 exists to remove.

Controls:  W/S or Up/Down = forward/back    A/D = turn      Left/Right = turn
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
from doomfj.mapcompiler import bake_bsp
from doomfj.things import baked_thing_mask, vanishable_slots
from doomfj.wireformat import (encode_bindings, encode_feed, encode_things,
                               encode_visibility)
from doomfj.fixedpoint import _signed
from doomfj.harness import W, FJM_LZMA_FAST
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,
                                    ReferenceModel, spawn_state)
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from tests.fj.stream_screen import StreamScreen

_SRC_NAMES = ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj",
              "plane_render.fj", "plane_bands.fj", "stream_render.fj")
# B0: `sim.fj` LAST, exactly as m14_gate.py orders it -- fj top-level labels are global, so the
# ordered file list is equivalent to its concatenation and the order is load-bearing (R54).
SRC = [ROOT / "src/fj" / f for f in _SRC_NAMES]
SRC_SIM = [ROOT / "src/fj" / f for f in _SRC_NAMES + ("sim.fj",)]
ANG_STEP = 0x08000000          # 11.25 degrees per turn
MOVE_STEP = 24                 # map units per step
SCALE = 4                      # window upscale


def main():
    ap = argparse.ArgumentParser()
    # THE PLAYABLE DEFAULT IS E1M1-LITE (owner 2026-08-01: "use the e1m1... you may modify your
    # level a bit... keep it good and fun"). Same layout, rooms and monsters as E1M1 -- built by
    # src/doomfj/mapsimplify.py + the new node builder (segs 2057->1378, nodes 681->470, decor
    # thinned spatially so every landmark survives; every monster/weapon/key kept). Measured
    # BYTE-EXACT at six walkable gates: spawn 16.1M ops/frame (stock: 27.7M), worst gate 34.9M
    # (stock: 39.1M+). The pure-arena and stock maps stay one flag away:
    #     --wad tests/fixtures/arena.wad         --map MAP01  (16-wall ring, 11.6-13.6M)
    #     --wad assets/freedoom1.wad             --map E2M8   (542-seg arena, 19.9-24.6M)
    #     --wad tests/fixtures/freedoom_e1m1.wad --map E1M1   (stock, canonical for goldens)
    ap.add_argument("--wad", default="tests/fixtures/e1m1_lite.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default=None)
    # W1R is the default (owner 2026-08-02: "make nicer walls... keep the speed up to 16M"):
    # W1's flat-lit wall split into pseudo-random vertical runs keyed on the V1 grain group +
    # a height tier (near brighter / far darker), certified median 14.91M / mean 15.22M over
    # the 260-frame walkable sweep -- +0.46M at the median over plain W1 (14.45M). W1 stays a
    # flag away, as does the true-texel look: --wall-mode WPX (+2-6M/frame).
    ap.add_argument("--wall-mode", default="W1R", choices=["W1", "W2S", "WPX", "W1R"])
    ap.add_argument("--floor-mode", default="FT1", choices=["flat", "FT1"])
    ap.add_argument("--two-sided", action="store_true",
                    help="M13-2S rung 3b: draw the TWO-SIDED walls too (step faces, ledge fronts,"
                         " door frames) and give every plane region its own bounding seg's sector."
                         " Byte-exact vs the 2S oracle but ~6x slower than the shipped tier"
                         " (131M vs 21.7M ops/frame at spawn) -- for looking at, not for playing.")
    ap.add_argument("--no-plane-near", action="store_true",
                    help="turn OFF M13-2S rung 3a (attribute each column's floor/ceiling to the"
                         " nearest MARKING seg instead of to the wall that claims the column) --"
                         " i.e. go back to the pre-rung-3a look, for comparison")
    # ── the four VISUAL FEATURES (V1-V4). ON by default: they are what the renderer looks like
    # now, and every one is byte-exact against the oracle. Each costs ops, so each has an off
    # switch -- docs/opt-experiments.md has what they are worth.
    ap.add_argument("--no-grain", action="store_true",
                    help="V1 OFF: no pseudo-random wall texture grain")
    ap.add_argument("--no-sky", action="store_true",
                    help="V2 OFF: sky-flat ceilings go back to a plain plane")
    ap.add_argument("--no-steps", action="store_true",
                    help="V3 OFF: no step faces (stair risers, ledge fronts, door lintels)")
    ap.add_argument("--no-stack", action="store_true",
                    help="V5 OFF: back to ONE boundary piece per column and no per-boundary"
                         " floor/ceiling regions (stairs collapse to a single riser again)")
    ap.add_argument("--no-things", action="store_true",
                    help="V4 OFF: no thing sprites")
    ap.add_argument("--no-deg", action="store_true",
                    help="25M-CAP OFF: disable the load-adaptive degradation package (graduated"
                         " far-thing acceptance, behind-sprite B-gate, sliver-flat walls, far"
                         " stacked-piece gate, marking budget 96). Light frames render the same"
                         " either way; degradation only sheds far detail on already-heavy frames.")
    ap.add_argument("--sprites", default="assets/freedoom1.wad", metavar="WAD",
                    help="wad to take SPRITE art from. The cut-down test fixture has no sprite"
                         " lumps at all, so things need a full wad here; if it is missing, V4"
                         " turns itself off with a warning rather than failing to build.")
    ap.add_argument("--no-sim", action="store_true",
                    help="B0 A/B ONLY: drive movement from the HOST again (no sim.fj, decimal "
                         "wire). The default runs the player sim, collision and the runtime thing "
                         "table INSIDE the fj program and reads the new position out of the frame.")
    ap.add_argument("--frames", type=int, default=0, metavar="N",
                    help="render N frames HEADLESSLY (no window) and report timings, then exit"
                         " -- use this to check the fj side independently of pygame")
    ap.add_argument("--fjm", default=None, metavar="PATH",
                    help="play a PREBUILT .fjm instead of assembling one -- e.g. the M1 "
                         "self-resetting binary from build.build_wall_renderer(self_reset=True)")
    ap.add_argument("--loop", action="store_true",
                    help="M1: the program RESETS ITSELF and loops, so the host never reloads the "
                         "image. Needs a self-reset binary (--fjm). The control flow inverts: ONE "
                         "core.run drives the whole session and the device services it -- read_bit "
                         "builds the next tic from the state the frame just echoed. Without this "
                         "the walker reloads the whole image between tics, which is the ~52ms "
                         "floor M1 exists to remove.")
    args = ap.parse_args()

    cfg = Config()
    mw = WadFile.from_path(str(ROOT / args.wad))
    # A geometry-only PWAD (the arena) carries no COLORMAP/textures/flats, so fall back to the
    # IWAD for art. A self-contained map wad (the E1M1 fixture) keeps using itself, so its
    # byte-exact goldens are untouched.
    if args.asset:
        aw_path = ROOT / args.asset
        aw = WadFile.from_path(str(aw_path))
    elif "COLORMAP" in mw.names():
        aw_path = None                     # the map wad itself -- already in the cache key
        aw = mw
    else:
        aw_path = ROOT / "assets/freedoom1.wad"
        aw = WadFile.from_path(str(aw_path))
        print(f"  ({args.wad} is geometry-only -- taking art from assets/freedoom1.wad)")

    # V1-V4 ride on the rung-3a (plane_near) lines tier; the rung-3b two-sided tier is a different
    # emit path that none of them was written against, so they are off there.
    feats = not args.two_sided
    # M13-W1R rides V1's per-column grain group; without the grain its pattern key does not
    # exist at runtime, so W1R forces V1 on rather than failing the emit assert.
    if args.wall_mode == "W1R" and (args.no_grain or not feats):
        print("  !! --wall-mode W1R needs V1's grain group -- keeping grain ON")
        args.no_grain = False
        assert feats, "--wall-mode W1R is not wired into the two_sided tier"
    spr_path = ROOT / args.sprites
    want_things = feats and not args.no_things
    if want_things and not spr_path.exists():
        print(f"  !! {args.sprites} not found -- V4 things OFF"
              " (the cut-down fixture wad has no sprite lumps)")
        want_things = False
    spr = WadFile.from_path(str(spr_path)) if want_things else None
    on = [n for n, f in (("grain", feats and not args.no_grain),
                         ("sky", feats and not args.no_sky),
                         ("steps", feats and not args.no_steps),
                         ("things", want_things)) if f]

    # B0: the sim is the DEFAULT path now. It needs the runtime thing table (moving_things), so
    # it also needs things; --no-things therefore implies --no-sim rather than silently building a
    # sim binary whose wire carries a thing block the program never reads.
    sim = not args.no_sim and want_things
    if not args.no_sim and not want_things:
        print("  --no-things forces --no-sim (the sim path carries a runtime thing block)",
              flush=True)

    # The fjm CACHE (same shape as bench.py's): the emit is ~7 and the assemble ~16 of the ~23
    # build minutes, and BOTH are a pure function of (sources, flags, wad bytes) -- so a hash of
    # exactly those names the binary, and a second launch of the same config opens in seconds
    # instead of regenerating and reassembling a ~104M-character program every time.
    import hashlib
    key = hashlib.sha256()
    # CR-2026-08: the key hashes EVERY build input -- the fj sources, all emit-shaping python
    # modules (not just wall_renderer: the LUT/map/texture compilers shape the emitted text
    # too), the flag tuple, and the BYTES of all three wads (map, asset art, sprites). A
    # missing input here = a stale binary served after that input changes.
    for p in SRC + [ROOT / "src/doomfj" / f for f in
                    ("wall_renderer.py", "reference_model.py", "config.py", "lut_generator.py",
                     "mapcompiler.py", "texturecompiler.py", "tables.py", "wad.py", "build.py",
                     # fixedpoint encodes every baked constant; harness owns W (the assemble
                     # memory_width) -- hashing an importer does NOT capture its imports
                     "fixedpoint.py", "harness.py")]:
        key.update(p.read_bytes())
    # ⚠ B0: `sim` is IN THE KEY. It changes the binary AND the wire format, so a cached
    # no-sim binary served to the sim path would be fed a wire it cannot parse and would halt
    # after ~200 ops -- the exact failure dirty_census documents for the decimal feed.
    key.update(repr((args.wall_mode, args.floor_mode, args.two_sided, args.no_plane_near,
                     args.no_grain, args.no_sky, args.no_steps, args.no_stack, want_things,
                     args.no_deg, args.map, sim)).encode())
    key.update((ROOT / args.wad).read_bytes())
    if aw_path is not None:
        key.update(aw_path.read_bytes())
    if want_things:
        key.update(spr_path.read_bytes())
    cache = ROOT / "scratchpad" / "fjmcache"
    cache.mkdir(parents=True, exist_ok=True)
    fjm = cache / f"w_{key.hexdigest()[:16]}.fjm"
    if args.fjm:                       # a prebuilt binary (M1: the self-resetting one)
        fjm = Path(args.fjm) if Path(args.fjm).is_absolute() else ROOT / args.fjm
        assert fjm.exists(), f"--fjm {fjm} does not exist"
        print(f"using prebuilt {fjm.name} ({fjm.stat().st_size:,} bytes)", flush=True)
    t0 = time.perf_counter()
    if fjm.exists():
        print(f"cache HIT {fjm.name} -- skipping the ~15 min build", flush=True)
    else:
        print(f"assembling the fj renderer ({args.map}, lines mode, "
              f"{args.wall_mode}+{args.floor_mode}"
              f"{'+two_sided' if args.two_sided else '' if args.no_plane_near else '+plane_near'}"
              f"{'+' + '+'.join(on) if on else ''}) ...")
        if want_things:
            print("  (the sprite bank makes this a ~104M-character program: expect ~7 min to"
                  " emit + ~9 min to assemble; the result is CACHED for later launches)",
                  flush=True)
        main_txt = emit_wall_renderer(mw, args.map, cfg, asset_wad=aw, over_align=False,
                                      floor_mode=args.floor_mode, wall_mode=args.wall_mode,
                                      raster_mode="lines", two_sided=args.two_sided,
                                      plane_near=(not args.no_plane_near) and not args.two_sided,
                                      wall_noise=feats and not args.no_grain,
                                      sky=feats and not args.no_sky,
                                      steps=feats and not args.no_steps,
                                      things=want_things, sprite_wad=spr,
                                      bbox_cull=True,   # M13-15M: the wedge subtree cull ships
                                      # V5: stacked boundary pieces + true regions
                                      stack_steps=(feats and not args.no_steps
                                                   and not args.no_stack),
                                      # 25M-CAP + OPT-A: certified median 16.51M / mean 17.34M /
                                      # worst 41.9M, byte-exact (b_8db722bbd480cd52)
                                      deg=feats and not args.no_deg,
                                      # B0: the sim, the collision and the runtime thing table --
                                      # built and gated since M14/M14.5, wired in here for the
                                      # first time. `collide=True` is what makes walls solid
                                      # without the host testing a single linedef.
                                      **(dict(state_wire="bin", player_sim=True, collide=True,
                                              moving_things=True) if sim else {}))
        print(f"emitted {len(main_txt):,} chars in {time.perf_counter() - t0:.0f}s", flush=True)
        tmp = Path(tempfile.mkdtemp())
        consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
        (tmp / "m.fj").write_text(main_txt, encoding="utf-8")
        fj.assemble([consts.resolve(), *[p.resolve() for p in (SRC_SIM if sim else SRC)],
                     (tmp / "m.fj").resolve()], fjm, memory_width=W, print_time=False,
                    lzma_fast=FJM_LZMA_FAST)
        print(f"built in {time.perf_counter() - t0:.0f}s (cached as {fjm.name})", flush=True)
    print("loading the program", flush=True)
    runner = FjmRunner(fjm)          # parse + memory-image prep ONCE, not once per frame
    print("engine: " + ("native (C)" if runner.native else
                        "pure-python FALLBACK -- ~14x slower"), flush=True)

    pal = aw.playpal()
    sp = spawn_state(mw, args.map)
    px = _signed(sp.x, 32) >> 16
    py = _signed(sp.y, 32) >> 16
    ang = sp.angle
    # B0 -- the state the PROGRAM owns. With the sim on, the host holds the player's 16.16
    # position only to hand it back next tic; it never changes it. `st` is replaced wholesale by
    # what the frame echoes out, which is the whole point of B0.
    st = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
    THINGS, NTH, binds = b"", 0, None
    if sim:
        # the runtime thing block, built exactly as m14_gate/m14_sweep build it -- same SSOT
        # (baked_thing_mask / vanishable_slots), so the walker cannot drift from the gates.
        _rm = ReferenceModel(cfg)
        _cmap = bake_bsp(mw, args.map)
        _drawable = [th for th in mw.things(args.map)
                     if _rm.sprite_art(spr, th.type, {}) is not None]
        _baked = baked_thing_mask(_rm, _cmap, _drawable, MONSTER_TYPES)
        _nvis = len(vanishable_slots(_drawable, _baked, VANISHABLE_TYPES))
        _rt = [th for th, b in zip(_drawable, _baked) if not b]
        NTH = len(_rt)
        _POS = encode_things([(th.x << 16, th.y << 16) for th in _rt])
        # nothing moves things yet (that is C4), so the bindings are the spawn ones and stay warm
        binds = [_rm.point_in_subsector(_cmap, th.x, th.y) for th in _rt]
        _VIS = encode_visibility([1] * _nvis)
        THINGS = (_POS, _VIS)
        print(f"  sim ON: {len(_drawable)} drawable = {sum(_baked)} baked + {NTH} runtime, "
              f"{_nvis} visibility flags", flush=True)

    def wire(keys):
        """The frame's stdin. ⚠ BINARY when the sim is on -- a decimal feed halts a state_wire=bin
        program after ~200 ops rather than failing loudly."""
        if not sim:
            nl = chr(10)          # the three-decimal wire, one value per line
            return (str(px) + nl + str(py) + nl + str(ang) + nl).encode()
        return encode_feed(st[0], st[1], st[2], keys) + THINGS[0] + encode_bindings(binds) + THINGS[1]

    def render_headless(keys):
        """`render()` without the window -- same wire, same state adoption, no pygame."""
        nonlocal st, px, py, ang, binds
        screen = StreamScreen(stdin=wire(keys), n_things=NTH)
        ops = runner.run(screen)
        if sim:
            st = screen.state
            px, py = st[0] >> 16, st[1] >> 16
            ang = st[2]
            if screen.bindings:
                binds = list(screen.bindings)
        return ops

    if args.frames:                      # headless: fj only, no pygame, no window
        # B0: with the sim on this is a real headless PLAY loop -- turn_left every tic, and
        # the position/angle that come back are the PROGRAM's. It is also the cheapest
        # end-to-end check that the wire, the sim and the state echo all work (R2 evidence).
        for i in range(args.frames):
            t = time.perf_counter()
            # turn for the first half, then walk: a turn-only script would prove the sim
            # runs but never that MOVEMENT or COLLISION do, which is the half B0 wires in.
            ops = render_headless((0b0100 if i < args.frames // 2 else 0b0001) if sim else 0)
            if not sim:
                ang = (ang + ANG_STEP) & 0xFFFFFFFF
            dt = time.perf_counter() - t
            pos = (f"  -> ({st[0] / 65536:.3f},{st[1] / 65536:.3f}) ang={st[2]:#010x}"
                   if sim else "")
            print(f"  frame {i + 1}: {ops:,} fj ops in {dt * 1000:.0f}ms "
                  f"({1 / dt:.1f} fps){pos}", flush=True)
        return

    # PYGAME-CE ONLY. Go through flipjump's guard rather than `import pygame` directly: upstream
    # pygame and pygame-ce install under the SAME module name, so the wrong one is silent -- this
    # script would import it and run. `_import_pygame` requires `pygame.IS_CE` and names the fix.
    from flipjump.interpreter.io_devices.pygame_window import _import_pygame
    pygame = _import_pygame()
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
    # the 256-entry RGB palette, handed to SDL ONCE per surface. The old path built a 48,000-byte
    # RGB buffer in python every frame (`b"".join(map(pal3.__getitem__, indices))`, 0.52 ms);
    # `frombuffer(..., "P")` hands SDL the 16,000 raw indices and lets it expand them -- 0.04 ms,
    # MEASURED at this resolution. Same pixels, 13x less python per frame.
    pal_rgb = [tuple(pal[i]) for i in range(256)]

    def render(keys=0):
        """One TIC. ⚠ B0: with the sim on this both renders AND advances the world -- the
        program turns, moves and collides the player, then echoes the new state, which we
        simply adopt. The host does not compute a position. `nonlocal` is doing real work
        here: `st` is the program's output, not the host's variable."""
        nonlocal st, px, py, ang, binds
        t = time.perf_counter()
        screen = StreamScreen(stdin=wire(keys), n_things=NTH)
        ops = runner.run(screen)
        if sim:
            st = screen.state                   # <- the new position, FROM THE FRAME
            px, py = st[0] >> 16, st[1] >> 16   # display only; never fed back as truth
            ang = st[2]
            if screen.bindings:
                binds = list(screen.bindings)   # the relay, exactly as m14_gate does it
        frame = pygame.image.frombuffer(bytes(screen.pixel_indices),
                                        (cfg.VIEW_W, cfg.VIEW_H), "P")
        frame.set_palette(pal_rgb)
        # .convert(win): frombuffer hands back an 8-bit paletted surface, and scaling INTO the
        # 32-bit display surface needs a matching format
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
    if sim:
        # ── B0: THE HOST DOES NO SIMULATION. ────────────────────────────────────────────────
        # Every key becomes a BIT in the wire's key byte and nothing else. There is no host-side
        # position update, no host-side turn and no host-side collision left in this loop -- the
        # program moves the player, walks him into walls and hands back where he ended up.
        # Held keys, not KEYDOWN events: a tic is what the sim consumes, so sampling the keyboard
        # state each pass gives continuous movement while a key is down, which is what a game does.
        # ⚠ NO STRAFE: sim.fj has forward/back/turn_left/turn_right only, so A/D turn.
        F, B, L, R = 0b0001, 0b0010, 0b0100, 0b1000

        if args.loop:
            # ── M1: ONE RUN, THE PROGRAM LOOPS. ─────────────────────────────────────────────
            # The control flow inverts. Instead of the host calling the program once per tic and
            # reloading the whole image in between, the program runs continuously and the DEVICE
            # services it: read_bit builds the next tic's wire out of the state the frame just
            # echoed, and _present blits. That is what an interactive host actually is, and it is
            # only possible because the program restores itself.
            from doomfj.fastrun import _fjcore
            from flipjump.utils.exceptions import IOReadOnEOF as _EOF

            class _LoopDevice(StreamScreen):
                def __init__(self, **kw):
                    super().__init__(stdin=b"", n_things=NTH, **kw)
                    self.stop = False
                    self.tics = 0
                    self.t0 = time.perf_counter()
                    self._inp = wire(0)          # the first tic, from the spawn state

                def _poll(self):
                    for ev in pygame.event.get():
                        if ev.type == pygame.QUIT:
                            self.stop = True
                        elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_p:
                            pygame.image.save(win, str(ROOT / "scripts" / "walk_screenshot.png"))
                            print("screenshot saved to scripts/walk_screenshot.png")
                    kp = pygame.key.get_pressed()
                    if kp[pygame.K_q] or kp[pygame.K_ESCAPE]:
                        self.stop = True
                    k = 0
                    if kp[pygame.K_w] or kp[pygame.K_UP]:
                        k |= F
                    if kp[pygame.K_s] or kp[pygame.K_DOWN]:
                        k |= B
                    if kp[pygame.K_LEFT] or kp[pygame.K_a]:
                        k |= L
                    if kp[pygame.K_RIGHT] or kp[pygame.K_d]:
                        k |= R
                    return k

                def read_bit(self):
                    if self._in_bits == 0 and not self._inp:
                        if self.stop:
                            raise _EOF("walker: quit")
                        self._inp = wire(self._poll())
                    return super().read_bit()

                def _present(self):
                    nonlocal st, px, py, ang, binds
                    super()._present()
                    if self.state:
                        st = self.state
                        px, py = st[0] >> 16, st[1] >> 16
                        ang = st[2]
                    if self.bindings:
                        binds = list(self.bindings)
                    surf = pygame.image.frombuffer(bytes(self.pixel_indices),
                                                   (cfg.VIEW_W, cfg.VIEW_H), "P")
                    surf.set_palette(pal_rgb)
                    pygame.transform.scale(surf.convert(win), win.get_size(), win)
                    pygame.display.flip()
                    self.tics += 1
                    el = time.perf_counter() - self.t0
                    pygame.display.set_caption(
                        f"doom-flipjump [M1 LOOP]  ({px},{py}) ang={ang:#010x}  "
                        f"tic {self.tics}  {self.tics / el:.1f} fps")

            core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
            for _s, _n in runner._segments:
                core.add_segment(_s, _n)
            for _st, _v in runner._runs:
                core.set_words(_st, _v)
            dev = _LoopDevice()
            dev.attach_memory(NativeDeviceMemory(core, runner.width))
            print("M1 LOOP: one run, the program self-resets between tics "
                  "-- W/S move, A/D or arrows turn, P screenshot, Q quits", flush=True)
            try:
                _c, ops, _e, _l, _pp = core.run(dev.read_bit, dev.write_bit, _EOF,
                                                last_ops_length=0)
            except Exception as exc:
                print(f"  run ended: {exc}", flush=True)
                ops = 0
            el = time.perf_counter() - dev.t0
            print(f"  {dev.tics} tics in {el:.1f}s ({dev.tics / max(el, 1e-9):.2f} fps), "
                  f"{ops:,} fj ops in ONE run", flush=True)
            pygame.quit()
            return

        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_p:
                    pygame.image.save(win, str(ROOT / "scripts" / "walk_screenshot.png"))
                    print("screenshot saved to scripts/walk_screenshot.png")
            kp = pygame.key.get_pressed()
            if kp[pygame.K_q] or kp[pygame.K_ESCAPE]:
                running = False
                continue
            keys = 0
            if kp[pygame.K_w] or kp[pygame.K_UP]:
                keys |= F
            if kp[pygame.K_s] or kp[pygame.K_DOWN]:
                keys |= B
            if kp[pygame.K_LEFT] or kp[pygame.K_a]:
                keys |= L
            if kp[pygame.K_RIGHT] or kp[pygame.K_d]:
                keys |= R
            if keys:
                render(keys)          # one tic: the program simulates AND draws
            else:
                pygame.time.wait(20)
    else:
        import math          # the legacy HOST-SIDE path (--no-sim), kept only as an A/B
        while running:
            moved = False
            # the last good viewpoint, snapshotted BEFORE the handlers apply this tick's move --
            # snapshotting after them would 'restore' the exact position that just failed
            ppx, ppy, pang = px, py, ang
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
                    px, py, ang = ppx, ppy, pang
            pygame.time.wait(20)
    pygame.quit()


if __name__ == "__main__":
    main()
