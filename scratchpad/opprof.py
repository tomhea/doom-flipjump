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

M14 MODE (`--m14`), added for the perf campaign because `docs/handoff-perf.md` section 0 depends on
it: emit EXACTLY what `m14_gate.py --things` emits (bin wire, `player_sim`, `moving_things`, W1R +
deg), and feed the same wire `m14_sweep.py` feeds -- state, the 251 spawn thing positions, and the
WARM bindings. The op total is then directly comparable to the sweep's per-frame numbers.

⚠ THE CONTROL that makes this worth anything: `--m14` byte-compares its own assembled binary
against `scratchpad/fjmcache/m14_bin_things.fjm` (the binary the sweep in section 1.1 measured) and
prints IDENTICAL / DIFFERS. `debugging_file_path` only writes a side file, so a profile of a binary
that is not byte-identical to the measured one is a profile of a different program -- and the tool
says so rather than letting the reader assume.

    python scratchpad/opprof.py --m14 --vp 664,291,0x18000000
"""
import argparse
import bisect
import collections
import hashlib
import sys
import tempfile
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
from doomfj.wall_renderer import emit_wall_renderer, write_program_files  # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed_mapunits,     # noqa: E402
                               encode_things, encode_visibility)
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj")]
SRC_M14 = SRC + [ROOT / "src/fj/sim.fj"]           # the sim wire lives in its own unit
ap = argparse.ArgumentParser()
ap.add_argument("--wad", default="tests/fixtures/square_room.wad")
ap.add_argument("--map", default="MAP01")
ap.add_argument("--asset", default="tests/fixtures/freedoom_assets.wad")
ap.add_argument("--top", type=int, default=25)
ap.add_argument("--vp", default="", metavar="X,Y,ANG",
                help="profile THIS viewpoint instead of spawn (profile the frame that hurts)")
ap.add_argument("--reuse", action="store_true",
                help="reuse scratchpad/fjmcache/prof.fjm+dbg from the previous run (same sources!)")
ap.add_argument("--m14", action="store_true",
                help="profile the M14 `--things` binary: bin wire + player_sim + moving_things, "
                     "fed the warm-binding wire m14_sweep.py feeds (see the module docstring)")
args = ap.parse_args()
if args.m14 and args.wad == ap.get_default("wad"):
    args.wad, args.map = "tests/fixtures/freedoom_e1m1.wad", "E1M1"

cfg = Config()
mw = WadFile.from_path(args.wad)
aw = WadFile.from_path(args.asset) if args.asset else mw
art = WadFile.from_path('assets/freedoom1.wad')
out = ROOT / "scratchpad" / "fjmcache"
out.mkdir(exist_ok=True)
tag = "prof_m14" if args.m14 else "prof"
fjm, dbg = out / f"{tag}.fjm", out / f"{tag}.dbg"

# ⚠ the M14 emit kwargs are m14_gate.py's, verbatim. If they drift, the profile stops describing
# the binary the sweep measured -- which is what the byte-compare below is there to catch.
M14_EMIT = dict(return_parts=True, things=True,
                player_sim=True, collide=False, moving_things=True)
# ⚠ CR-2026-08 (IN-3, A0.1): `bbox_cull=True` added to keep the "m14_gate.py's, verbatim" contract
# above true after A0.1 unified the four configurations. A profile of a different picture ranks the
# wrong macros -- and the ranking is what A2's whole batch order rests on.

t0 = time.time()
if args.reuse and fjm.exists() and dbg.exists():
    print(f"REUSING {fjm.name} + {dbg.name} (same-source assumption is YOURS to hold)", flush=True)
elif args.m14:
    print("emitting...", flush=True)
    parts = emit_wall_renderer(mw, args.map, cfg, sprite_wad=art, **M14_EMIT)
    tmp = Path(tempfile.mkdtemp())
    consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")
    prog = write_program_files(parts, tmp, "e1m1")            # ⚠ order is the contract
    print(f"emitted {sum(p.stat().st_size for p in prog):,} chars in "
          f"{time.time() - t0:.0f}s -> assembling (the ~25-minute part)", flush=True)
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC_M14], *[p.resolve() for p in prog]],
                fjm, memory_width=W, print_time=False, debugging_file_path=dbg)
    print(f"assembled + labelled in {time.time() - t0:.0f}s "
          f"({fjm.stat().st_size:,} bytes)", flush=True)
else:
    main = emit_wall_renderer(mw, args.map, cfg, asset_wad=aw, things=True, sprite_wad=art)
    consts = cfg.emit_fj_consts(out / "fj_consts.fj")
    mp = out / "prof.fj"
    mp.write_text(main, encoding="utf-8")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], mp.resolve()], fjm,
                memory_width=W, print_time=False, debugging_file_path=dbg)
    print(f"assembled + labelled in {time.time() - t0:.0f}s", flush=True)

if args.m14:
    # THE CONTROL (see docstring): is this the binary the section-1.1 sweep actually measured?
    ref = out / "m14_bin_things.fjm"
    if ref.exists():
        h1 = hashlib.sha256(fjm.read_bytes()).hexdigest()
        h2 = hashlib.sha256(ref.read_bytes()).hexdigest()
        verdict = ("IDENTICAL -- profiling the measured binary" if h1 == h2 else
                   "!! DIFFERS -- this profile is NOT of the swept binary")
        print(f"binary vs {ref.name}: {h1[:16]} vs {h2[:16]} -> {verdict}", flush=True)
    else:
        print(f"!! {ref.name} absent -- cannot confirm this is the swept binary", flush=True)

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

if args.vp:
    vx, vy, va = (int(v, 0) for v in args.vp.split(","))
else:
    sp = spawn_state(mw, args.map)
    vx, vy, va = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle

if args.m14:
    # THE WIRE, exactly as m14_sweep.py feeds it: keys=0, the spawn thing positions, and the WARM
    # bindings (the steady state the median is measured in). Feeding all-dirty here would profile a
    # cold level load, which is a different frame -- see m14_sweep.py's `--cold`.
    from doomfj.mapcompiler import bake_bsp                               # noqa: E402
    from doomfj.reference_model import ReferenceModel                     # noqa: E402
    _rm = ReferenceModel(cfg)
    _cmap = bake_bsp(mw, args.map)
    from doomfj.reference_model import MONSTER_TYPES, VANISHABLE_TYPES  # noqa: E402
    from doomfj.things import baked_thing_mask, vanishable_slots        # noqa: E402
    _draw = [t for t in mw.things(args.map) if _rm.sprite_art(art, t.type, {}) is not None]
    # M14.5: the wire carries the RUNTIME half only; the rest is baked into its leaf's code
    _bk = baked_thing_mask(_rm, _cmap, _draw, MONSTER_TYPES)
    _nvis = len(vanishable_slots(_draw, _bk, VANISHABLE_TYPES))
    _draw = [t for t, b in zip(_draw, _bk) if not b]
    feed = (encode_feed_mapunits(vx, vy, va, 0)
            + encode_things([(t.x << 16, t.y << 16) for t in _draw])
            + encode_bindings([_rm.point_in_subsector(_cmap, t.x, t.y) for t in _draw])
            + encode_visibility([1] * _nvis))
    screen = StreamScreen(stdin=feed, n_things=len(_draw))
    print(f"M14 wire: {len(_draw)} things, {len(feed)} bytes, WARM bindings, keys=0", flush=True)
else:
    screen = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
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

# ── the SUBSYSTEM roll-up: direct ops AND the wflip blame, summed ──────────────────────────────
# Every other table below is one or the other, which is why none of them adds up to the frame.
# `docs/handoff-perf.md` §0 asks for ops attributed to each subsystem with the arithmetic shown;
# an attribution that omits ~72% of the frame (the wflip areas) is not one. This table is the
# only one whose column sums to `total`, so it is the one an attribution may be built on.


def report_all(title, keyfn, top):
    agg = collections.Counter()
    for src in (PATHS, BLAME):
        for pth, n in src.values():
            k = keyfn(pth)
            if k is not None:
                agg[k] += n
    print(f"\n### {title}")
    print(f"{'subsystem':46s} {'ops':>13s} {'share':>7s}")
    print("-" * 69)
    acc = 0
    for name, n in agg.most_common(top):
        acc += n
        print(f"{name:46s} {n:13,} {100 * n / total:6.2f}%")
    print(f"{'... the rest':46s} {sum(agg.values()) - acc:13,}")
    print(f"{'SUM (must equal the frame)':46s} {sum(agg.values()):13,}  vs total {total:,}")


def m14_subsystem(pth):
    """M14's own macros all live in `sim.fj` and are named `sim.*`; everything else is the base
    renderer this milestone did not touch. The FIRST `sim.` component in the path is the caller
    that owns the work (`sim.thing_pass` owns the `sim.thing_load` inside it), so report the
    outermost one -- and separately, below, the deepest, to split the pass from the load."""
    for c in pth:
        if c.startswith("sim."):
            return c
    return "<base renderer -- not M14>"


def m14_deepest(pth):
    for c in reversed(pth):
        if c.startswith("sim."):
            return c
    return None


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


if args.m14:
    report_all("M14 vs THE BASE RENDERER -- direct ops + wflip blame, the only table that sums",
               m14_subsystem, 14)
    report_all("... and the same ops by the DEEPEST sim macro (splits pass from load)",
               lambda p: m14_deepest(p) or "<base renderer -- not M14>", 14)

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


def _scoped(scope):
    def key(p):
        if p and p[0] == scope and len(p) > 1:
            return " > ".join(p[1:3])
        return None
    return key


report("INSIDE seg_pass2_leaf_body_lines -- direct ops by sub-path",
       _scoped("frame.seg_pass2_leaf_body_lines"), 24)
report("INSIDE seg_pass2_leaf_body_lines -- wflip blame by sub-path",
       _scoped("frame.seg_pass2_leaf_body_lines"), 24, BLAME)
report("INSIDE seg_pass1_leaf_body_ts -- wflip blame by sub-path",
       _scoped("frame.seg_pass1_leaf_body_ts"), 16, BLAME)
