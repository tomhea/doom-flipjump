"""Frame-cost bench: build ANY tier/knob/ablate combination, cache it, report ops at 4 viewpoints.

    python scratchpad/bench.py                          # the shipping tier, byte-exact gate
    python scratchpad/bench.py --ablate xrstub          # price everything below wall_x_range
    python scratchpad/bench.py --knob PNEAR_SEG_BUDGET=32 --knob STEP_SEG_BUDGET=8
    python scratchpad/bench.py --off steps --off things # a tier without V3 / V4

!! TWO traps this harness exists to avoid:
  * `wall_renderer` does `from doomfj.reference_model import THING_BUDGET, ...`, so its names are
    BOUND AT IMPORT. Patching only `reference_model.X` moves the oracle and leaves the emitter on
    the old value -- a "byte-exact" run that proves nothing. `_set_knob` writes BOTH modules (and
    `config` for the ones that live there).
  * the binary cache is keyed on a hash of the SOURCES, so a knob patched in memory would collide
    with a differently-knobbed build. The knobs are folded into the key.

An ablated build renders a deliberately WRONG frame, so byte-exactness is only asserted when the
ablate set is empty -- prices, not pictures.
"""
import argparse
import hashlib
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import flipjump as fj                                                     # noqa: E402
import doomfj.config as CFGM                                              # noqa: E402
import doomfj.reference_model as RM                                       # noqa: E402
import doomfj.wall_renderer as WR                                         # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state  # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
ap = argparse.ArgumentParser()
ap.add_argument("--ablate", action="append", default=[])
ap.add_argument("--knob", action="append", default=[], metavar="NAME=VALUE")
ap.add_argument("--off", action="append", default=[],
                choices=["grain", "sky", "steps", "things", "plane_near", "bboxcull"])
ap.add_argument("--res", default="", metavar="WxH",
                help="render at a different resolution. Config is fully W/H-derived, so the "
                     "oracle follows and byte-exactness still holds.")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--map", default="E1M1")
ap.add_argument("--asset", default="")
ap.add_argument("--vp", action="append", default=[], metavar="X,Y,ANG")
ap.add_argument("--tag", default="")
args = ap.parse_args()


def _set_knob(name, value):
    """Write the knob everywhere it is BOUND, not just where it is defined (see the module note)."""
    hit = []
    for mod in (RM, WR, CFGM):
        if hasattr(mod, name):
            setattr(mod, name, value)
            hit.append(mod.__name__.split('.')[-1])
    assert hit, f"unknown knob {name}"
    return hit


KNOBS = {}
for kv in args.knob:
    k, v = kv.split("=", 1)
    KNOBS[k] = int(v)
    print(f"  knob {k} = {v}  (patched in {', '.join(_set_knob(k, int(v)))})")

cfg = Config(**(dict(zip(("W", "H"), map(int, args.res.split("x")))) if args.res else {}))
if args.res:
    print(f"  resolution {cfg.VIEW_W}x{cfg.VIEW_H}  downscale {cfg.TEXTURE_DOWNSCALE}"
          f"  col_bits {cfg.COL_BITS}  ({cfg.VIEW_W * cfg.VIEW_H:,} px)")
mw = WadFile.from_path(args.wad)
art = WadFile.from_path('assets/freedoom1.wad')
aw = WadFile.from_path(args.asset) if args.asset else mw
rm = ReferenceModel(cfg)
scene = build_scene(mw, aw, args.map)
sp = spawn_state(mw, args.map)
VPS = ([(_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle, "spawn")]
       + [tuple(int(v) for v in q.split(",")) + (f"vp{i}",) for i, q in enumerate(args.vp)]
       if args.vp or args.map != "E1M1" else
       [(_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle, "spawn"),
        (1400, 1200, 0, "courtyard"), (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")])
ABL = frozenset(args.ablate)
FLAGS = dict(floor_mode="FT1", wall_mode="WPX", raster_mode="lines",
             plane_near="plane_near" not in args.off,
             wall_noise="grain" not in args.off, sky="sky" not in args.off,
             steps="steps" not in args.off, things="things" not in args.off,
             bbox_cull="bboxcull" not in args.off)


def build():
    key = hashlib.sha256()
    for p in SRC + [ROOT / "src/doomfj/wall_renderer.py", ROOT / "src/doomfj/reference_model.py",
                    ROOT / "src/doomfj/config.py"]:
        key.update(p.read_bytes())
    key.update(repr(sorted(FLAGS.items())).encode())
    key.update(repr(sorted(ABL)).encode())
    key.update(repr(sorted(KNOBS.items())).encode())
    key.update(args.res.encode())
    key.update((args.wad + args.map + args.asset).encode())
    key.update(Path(args.wad).read_bytes())   # ... the wad CONTENT: a regenerated arena.wad
                                              # at the same path must not hit the old binary      # ... or a knobbed build collides
    tag = key.hexdigest()[:16]
    cache = ROOT / "scratchpad" / "fjmcache"
    cache.mkdir(exist_ok=True)
    fjm = cache / f"b_{tag}.fjm"
    if fjm.exists():
        print(f"cache HIT {fjm.name}", flush=True)
        return fjm
    t0 = time.time()
    main = WR.emit_wall_renderer(mw, args.map, cfg, asset_wad=aw, over_align=False,
                                 sprite_wad=art if FLAGS["things"] else None, ablate=ABL, **FLAGS)
    print(f"emitted {len(main):,} chars ({time.time() - t0:.0f}s)", flush=True)
    consts = cfg.emit_fj_consts(cache / "fj_consts.fj")
    mp = cache / f"b_{tag}.fj"
    mp.write_text(main, encoding="utf-8")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], mp.resolve()],
                fjm, memory_width=W, print_time=False)
    mp.unlink()
    print(f"assembled ({time.time() - t0:.0f}s) -> {fjm.name}", flush=True)
    return fjm


WANT = None
if not ABL:                                    # an ablated frame is deliberately wrong: price only
    WANT = [bytes(rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level=args.map),
                                       scene, wall_mode="WPX", floor_mode_ft1=True,
                                       plane_near=FLAGS["plane_near"],
                                       wall_noise=FLAGS["wall_noise"], sky=FLAGS["sky"],
                                       near_steps=FLAGS["steps"], things=FLAGS["things"],
                                       sprite_wad=art, bbox_cull=FLAGS["bbox_cull"]))
            for vx, vy, va, _ in VPS]

label = args.tag or (" ".join(f"-{o}" for o in args.off) + " " +
                     " ".join(f"{k}={v}" for k, v in KNOBS.items()) +
                     (" ablate:" + ",".join(sorted(ABL)) if ABL else "")).strip() or "shipping tier"
r = FjmRunner(build())
print(f"\n### {label}")
tot = 0
for i, (vx, vy, va, tag) in enumerate(VPS):
    scr = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
    ops = r.run(scr)
    tot = max(tot, ops)
    ok = "" if WANT is None else ("  BYTE-EXACT" if bytes(scr.pixel_indices) == WANT[i]
                                  else "  !! DIFFERS")
    print(f"{tag:10s} {ops:12,}{'   UNDER 15M' if ops < 15_000_000 else ''}{ok}", flush=True)
print(f"{'WORST':10s} {tot:12,}")
