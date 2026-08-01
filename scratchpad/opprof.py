"""RUNTIME op profiler: which MACROS actually burn the frame's fj ops.

Every number in this repo's optimisation history came from subtraction between whole-frame builds
(~20 minutes each) or, worse, from a model. This attributes ops DIRECTLY:

  * assemble with `debugging_file_path`, which saves every label's address;
  * run the interpreter's FEATURED loop (`profile=True`), whose `register_op_address(ip)` fires on
    every single op -- monkeypatched here into a histogram;
  * map each executed address back to the nearest label at or below it, and aggregate by the MACRO
    the label came from (flipjump label names carry their macro path).

⚠ The featured loop is the pure-Python one, ~200x slower than the native engine. Profile a SMALL
map, not E1M1: the square room's 4.7M ops are the renderer's level-independent floor, which is
exactly what "regardless of level size" means.

    python scratchpad/opprof.py                       # square room (fast)
    python scratchpad/opprof.py --wad ... --map ...   # anything else, if you have the patience
"""
import argparse
import bisect
import collections
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import flipjump as fj                                                     # noqa: E402
from flipjump.utils.classes import RunStatistics                          # noqa: E402
from flipjump.utils.functions import load_debugging_labels                # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.reference_model import spawn_state                            # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import emit_wall_renderer                       # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
ap = argparse.ArgumentParser()
ap.add_argument("--wad", default="tests/fixtures/square_room.wad")
ap.add_argument("--map", default="MAP01")
ap.add_argument("--asset", default="tests/fixtures/freedoom_assets.wad")
ap.add_argument("--sky", action="store_true", help="the fixture room has no sky flat")
ap.add_argument("--top", type=int, default=25)
args = ap.parse_args()

cfg = Config()
mw = WadFile.from_path(args.wad)
aw = WadFile.from_path(args.asset) if args.asset else mw
art = WadFile.from_path('assets/freedoom1.wad')
out = ROOT / "scratchpad" / "fjmcache"
out.mkdir(exist_ok=True)
fjm, dbg = out / "prof.fjm", out / "prof.dbg"

t0 = time.time()
main = emit_wall_renderer(mw, args.map, cfg, asset_wad=aw, over_align=False, floor_mode="FT1",
                          wall_mode="WPX", raster_mode="lines", plane_near=True, wall_noise=True,
                          sky=args.sky, steps=True, things=True, sprite_wad=art)
consts = cfg.emit_fj_consts(out / "fj_consts.fj")
mp = out / "prof.fj"
mp.write_text(main, encoding="utf-8")
fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], mp.resolve()], fjm,
            memory_width=W, print_time=False, debugging_file_path=dbg)
print(f"assembled + labelled in {time.time() - t0:.0f}s", flush=True)

labels = load_debugging_labels(dbg)            # {label_name: address}
addrs = sorted(set(labels.values()))
by_addr: dict = {}
for name, a in labels.items():                 # keep one representative name per address
    by_addr.setdefault(a, name)
print(f"{len(labels):,} labels over {len(addrs):,} distinct addresses", flush=True)

HIST: collections.Counter = collections.Counter()
WFLIP_BLAME: collections.Counter = collections.Counter()
_is_wflip = [by_addr[a].startswith(":wflips:") for a in addrs]
_bisect = bisect.bisect_right
_state = {"owner": -1}


def _profile_hook(self, ip):
    """Every op. A wflip AREA is where the flips physically happen, not who asked for them --
    so ops inside one are BLAMED on the last macro that was executing before we jumped in."""
    i = _bisect(addrs, ip) - 1
    if i >= 0 and _is_wflip[i]:
        WFLIP_BLAME[_state["owner"]] += 1
    else:
        _state["owner"] = i
        HIST[i] += 1


RunStatistics.register_op_address = _profile_hook

sp = spawn_state(mw, args.map)
vx, vy, va = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle
screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
print(f"running {args.map} @ ({vx},{vy}) under the PYTHON loop -- this is the slow part", flush=True)
t1 = time.time()
term = fj.run(fjm, io_device=screen, profile=True, print_time=False, print_termination=False,
              flat_max_words=1 << 26)
total = sum(HIST.values()) + sum(WFLIP_BLAME.values())
print(f"ran {total:,} ops in {time.time() - t1:.0f}s\n", flush=True)


def path_of(label: str):
    """flipjump labels carry the FULL macro call path, `---` separated, each component
    `file:line:macro.name(args)`. Return it as a list of bare macro names, outermost first."""
    if label.startswith(":wflips:"):
        return ["<wflip areas>"]
    outn = []
    for comp in label.split("---"):
        bits = comp.split(":")
        for b in reversed(bits):
            if "(" in b:
                outn.append(b.split("(")[0])
                break
            if "." in b and not b.startswith("l") and not b.startswith("f"):
                outn.append(b)
                break
    return outn or ["<unlabelled>"]


PATHS = {}
for i, n in HIST.items():
    a = addrs[i] if i >= 0 else -1
    PATHS.setdefault(a, [path_of(by_addr.get(a, "<pre>")), 0])
    PATHS[a][1] += n
BLAME = {}
for i, n in WFLIP_BLAME.items():
    a = addrs[i] if i >= 0 else -1
    BLAME.setdefault(a, [path_of(by_addr.get(a, "<pre>")), 0])
    BLAME[a][1] += n
wtot = sum(n for _p, n in BLAME.values())
print(f"wflip-area ops: {wtot:,} ({100*wtot/total:.1f}%) -- blamed on their CALLER below")


def report(title, keyfn, top, src=None):
    agg = collections.Counter()
    for pth, n in (src if src is not None else PATHS).values():
        k = keyfn(pth)
        if k is not None:
            agg[k] += n
    print(f"\n### {title}")
    print(f"{'macro':46s} {'ops':>13s} {'share':>7s}")
    print("-" * 69)
    for name, n in agg.most_common(top):
        print(f"{name:46s} {n:13,} {100 * n / total:6.2f}%")


report("BY OUTERMOST macro -- where the frame's ops go", lambda p: p[0], 12)
report("BY DEPTH-2 -- the renderer kernel actually doing the work",
       lambda p: " > ".join(p[:2]) if len(p) > 1 else p[0], args.top)
report("BY DEEPEST PRIMITIVE -- what to micro-optimise", lambda p: p[-1], 15)
report("WHO PAYS THE WFLIP COST (71% of the frame) -- outermost",
       lambda p: p[0], 10, BLAME)
report("WHO PAYS THE WFLIP COST -- by the primitive that issued it",
       lambda p: p[-1], 15, BLAME)


def caller_of_xor(pth):
    """The macro that CALLED the xor primitive -- i.e. what is actually generating them."""
    for i in range(len(pth) - 1, -1, -1):
        if "exact_xor" in pth[i]:
            return " > ".join(pth[max(0, i - 2):i + 1])
    return None


report("WHAT IS CALLING THE XORS (the real question)", caller_of_xor, 18, BLAME)


def zero_parent(pth):
    """Who asks for a ZERO? hex.zero/xor_zero live inside other ops -- name the op above them."""
    for i, c in enumerate(pth):
        if c in ("hex.zero", "hex.xor_zero"):
            return " > ".join(pth[max(0, i - 2):i + 1])
    return None


report("WHO IS ZEROING (~20% of the frame)", zero_parent, 18, BLAME)
print("-" * 69)
print(f"{'TOTAL':46s} {total:13,}")
