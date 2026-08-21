"""M1d — simulate the INTERNAL FRAME LOOP in Python, before writing a line of fj.

THE DESIGN QUESTION THIS ANSWERS. `docs/handoff-complete-game.md` treats the 9-op wall and the
self-reset as one task. They are — but not the way the ~2,500-cell framing implied:

  * the 9-op death is `word 1`, op 0's jump field. It only matters because the HOST relaunches the
    program from address 0. **An internal loop re-enters at `__hot_end`, so op 0 never runs again
    and words 0/1 stop mattering at all.**
  * `stl.startup_and_init_all` has nothing to re-run: it emits the six truth tables as DATA and
    jumps over them (runlib.fj). Measured: the whole table span 1,060..17,322 comes back clean
    after a frame. So re-entering below it is faithful, not a shortcut.

So the loop is: restore the set, then `;__hot_end`. This script runs exactly that against the real
84.8M-word image using `core.run(..., start_ip=__hot_end)`, and asks the only question that
matters for a GAME:

    does frame N+1, run on a RESTORED image with a DIFFERENT input, produce the same pixels as
    that input rendered on a PRISTINE image?

That is strictly stronger than the `m1c_restore_set.py` test, which re-ran the SAME input and
compared to frame 1. Same input cannot catch a stale cell that only some other viewpoint reads.

⚠ NEGATIVE CONTROLS (R9):
  1. NO-RESTORE: the same sequence with the restore SKIPPED must FAIL. If it passed, the restore
     would be proving nothing -- and this is a real risk, because most scratch is overwritten
     before it is read.
  2. REFERENCE IS INDEPENDENT: frame N+1's pixels are compared against a pristine core running
     that input from address 0 -- never against frame N.
  3. VACUITY: every frame must run > 1e6 ops, and consecutive inputs must produce DIFFERENT
     pictures (otherwise "the pixels match" is free).
  4. CHAINS, not pairs: `--frames N` runs a whole sequence on ONE core, so an error that needs two
     or three frames to show up has somewhere to accumulate.

    python scratchpad/m1d_loop.py <fjm> --set full
    python scratchpad/m1d_loop.py <fjm> --set declared     # only fj-ADDRESSABLE labels
    python scratchpad/m1d_loop.py <fjm> --set none         # CONTROL: must fail
"""
import argparse
import bisect
import gzip
import io
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm", nargs="?", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--restore-set", default="scratchpad/_m1c_restore_set_nolut.json.gz")
ap.add_argument("--gen", default="scratchpad/fjmcache/_rssgen")
ap.add_argument("--set", default="full", choices=("full", "declared", "none"))
ap.add_argument("--frames", type=int, default=6, help="length of each chain")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--drop", default="", help="comma-separated labels to REMOVE from the set -- used "
                                           "to search for the MINIMAL set the loop needs")
ap.add_argument("--sweep", action="store_true",
                help="chain the 260 SWEEP viewpoints instead of the hand-picked chains -- the "
                     "strongest cheap validation of a candidate set, since the sweep grid is what "
                     "the repo's metric is defined over and no set was built from it")
ap.add_argument("--step", type=int, default=256)
ap.add_argument("--angles", type=int, default=4)
ap.add_argument("--drop-below", type=int, default=0,
                help="drop every word below this WORD address. The stl region below code_start is "
                     "CODE, not data cells: `to_flip` and `to_flip_var` are a consistent PAIR that "
                     "set_flip_pointer xors against, so restoring one without the other is worse "
                     "than restoring neither.")
args = ap.parse_args()

BANKS_STATE_ENDS_AT = "thvis"

# ------------------------------------------------------------------------------------- the image
r = FjmRunner(Path(args.fjm))
assert r.native, "needs the native engine"
sa, sn = [], []
with gzip.open(args.labels, "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            sa.append(int(v))
            sn.append(a)
order = sorted(range(len(sa)), key=lambda i: sa[i])
sa = [sa[i] for i in order]
sn = [sn[i] for i in order]
BITS = {}
for n, b in zip(sn, sa):
    BITS.setdefault(n, b)
HOT = BITS["__hot_end"]
print(f"{Path(args.fjm).name}: __hot_end at bit {HOT:,} (word {HOT//W:,})")

saw = [b // W for b in sa]


def extent_words(name):
    b = BITS[name] // W
    i = bisect.bisect_right(saw, b)
    return b, (saw[i] if i < len(saw) else b + 2)


def fresh():
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        core.add_segment(s, n)
    for st, vals in r._runs:
        core.set_words(st, vals)
    return core


PRISTINE = fresh()

# ------------------------------------------------------------------------------- the restore set
GEN = Path(args.gen)


def top_labels(path, stop_after=None):
    out = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Za-z_]\w*):", line)
            if m:
                out.append(m.group(1))
                if stop_after and m.group(1) == stop_after:
                    break
    return out


if args.set == "none":
    WORDS = []
elif args.set == "declared":
    # ONLY labels a fj prologue can actually name: emitter-declared top-level state.
    names = (set(top_labels(GEN / "e1m1_01_tables.fj"))
             | set(top_labels(GEN / "e1m1_05_state.fj"))
             | set(top_labels(GEN / "e1m1_06_banks.fj", stop_after=BANKS_STATE_ENDS_AT)))
    READONLY = {"stepcol", "lnrow", "finetangent", "slopediv_recip8", "slopediv_recip",
                "tantoangle", "viewangletox", "bklin"}
    names -= READONLY
    ws = set()
    for n in names:
        if n in BITS:
            a, b = extent_words(n)
            ws.update(range(a, b))
    WORDS = sorted(ws)
    print(f"set=declared: {len(names)} fj-addressable labels -> {len(WORDS):,} words")
else:
    runs = json.load(gzip.open(args.restore_set, "rt", encoding="utf-8"))["runs"]
    WORDS = sorted(x for a, b in runs for x in range(a, b))
    print(f"set=full: {len(WORDS):,} words from {args.restore_set}")
    if args.drop:
        for nm in args.drop.split(","):
            nm = nm.strip()
            if not nm:
                continue
            assert nm in BITS, f"--drop {nm}: no such label"
            a, b = extent_words(nm)
            before = len(WORDS)
            WORDS = [x for x in WORDS if not (a <= x < b)]
            print(f"  --drop {nm}: [{a:,},{b:,}) removed {before-len(WORDS):,} words")
        print(f"  set is now {len(WORDS):,} words")
    if args.drop_below:
        before = len(WORDS)
        WORDS = [x for x in WORDS if x >= args.drop_below]
        print(f"  --drop-below {args.drop_below:,}: removed {before-len(WORDS):,} words "
              f"-> {len(WORDS):,}")


def coalesce(ws):
    out, s, p = [], ws[0], ws[0]
    for c in ws[1:]:
        if c != p + 1:
            out.append((s, p + 1))
            s = c
        p = c
    out.append((s, p + 1))
    return out


PATCH = ([(a, [PRISTINE.get_word(x) for x in range(a, b)]) for a, b in coalesce(WORDS)]
         if WORDS else [])
print(f"restore patch: {len(PATCH):,} runs, {sum(len(v) for _a, v in PATCH):,} words")

# -------------------------------------------------------------------------------------- the feed
w = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
NVIS = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
BINDS = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])


def feed(vx, vy, va, keys=0, dx=0, dy=0):
    return (encode_feed(vx, vy, va, keys)
            + encode_things([((t.x + dx) << 16, (t.y + dy) << 16) for t in RT])
            + BINDS + encode_visibility([1] * NVIS))


sp = spawn_state(w, "E1M1")
SPAWN = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
# Chains of DIFFERENT inputs -- viewpoint, keys and thing positions all move.
CHAINS = [
    [(664 << 16, 291 << 16, 0x18000000, 0, 0, 0), (700 << 16, 300 << 16, 0x20000000, 1, 0, 0),
     (1272 << 16, (-724) << 16, 0x40000000, 5, 16, 0), (1869 << 16, 479 << 16, 0x80000000, 0, 0, 0),
     (SPAWN[0], SPAWN[1], SPAWN[2], 4, -32, 48), (1000 << 16, 100 << 16, 0x20000000, 8, 0, 0)],
    [(2100 << 16, 800 << 16, 0xC0000000, 5, 16, -16), (1500 << 16, (-200) << 16, 0x60000000, 1, 0, 0),
     (SPAWN[0], SPAWN[1], SPAWN[2], 0, 64, 0), (664 << 16, 291 << 16, 0x18000000, 8, 0, 0),
     (1869 << 16, 479 << 16, 0x80000000, 1, -8, 8), (1272 << 16, (-724) << 16, 0x40000000, 4, 0, 0)],
]


if args.sweep:
    sys.path.insert(0, str(ROOT / "scratchpad"))
    from nb_validate import true_sector, _near_any_line          # noqa: E402
    _v = [(v.x, v.y) for v in w.vertexes("E1M1")]
    _l, _s = w.linedefs("E1M1"), w.sidedefs("E1M1")
    _xs = [p[0] for p in _v]
    _ys = [p[1] for p in _v]
    _pts = [(x, y)
            for x in range(min(_xs) + 13, max(_xs), args.step)
            for y in range(min(_ys) + 7, max(_ys), args.step)
            if not _near_any_line(_v, _l, x, y, 24.0) and true_sector(_v, _l, _s, x, y) != -1]
    CHAINS = [[(x << 16, y << 16, (a * (1 << 32) // args.angles) & 0xFFFFFFFF, 0, 0, 0)
               for x, y in _pts for a in range(args.angles)]]
    args.frames = len(CHAINS[0])
    print(f"--sweep: {len(_pts)} grid points x {args.angles} angles = {args.frames} frames "
          f"in ONE chain", flush=True)


def run(core, f, start_ip=0):
    scr = StreamScreen(stdin=f, n_things=len(RT))
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF,
                                   last_ops_length=0, start_ip=start_ip)
    return ops, bytes(scr.pixel_indices)


# reference pictures: each input rendered on its OWN pristine core, from address 0
print("\nrendering reference frames on pristine cores ...", flush=True)
REF = {}
t0 = time.perf_counter()
for chain in CHAINS:
    for c in chain:
        if c in REF:
            continue
        core = fresh()
        ops, px = run(core, feed(*c))
        assert ops > 1_000_000, f"CONTROL 3 (vacuity): {ops} ops"
        REF[c] = (ops, px)
        del core
print(f"  {len(REF)} references in {time.perf_counter()-t0:.0f}s", flush=True)
uniq = len({px for _o, px in REF.values()})
assert uniq >= 0.9 * len(REF), \
    f"CONTROL 3 (vacuity): only {uniq} distinct pictures among {len(REF)} inputs -- " \
    "matching pixels would be nearly free"
print(f"  all {uniq} reference pictures are distinct (so a match is not free)")

# ----------------------------------------------------------------------------------- the chains
print(f"\nCHAINS: frame 1 from address 0, then restore + re-enter at __hot_end, "
      f"{args.frames} frames each", flush=True)
ok = True
for ci, chain in enumerate(CHAINS):
    core = fresh()
    for k, c in enumerate(chain[:args.frames]):
        ops, px = run(core, feed(*c), start_ip=(0 if k == 0 else HOT))
        rops, rpx = REF[c]
        good = px == rpx
        ok &= good
        print(f"  chain {ci} frame {k}: {ops:,} ops (ref {rops:,}, "
              f"{'==' if ops == rops else f'{ops-rops:+,}'})  pixels "
              f"{'MATCH' if good else 'DIFFER (%d px)' % sum(1 for a, b in zip(px, rpx) if a != b)}"
              f"  {'ok' if good else 'FAIL'}", flush=True)
        if k + 1 < min(args.frames, len(chain)):
            for a, vals in PATCH:
                core.set_words(a, vals)
    del core

print("\n" + "=" * 96)
print(f"set={args.set}: {'PASS' if ok else 'FAIL'}")
if args.set == "none":
    print("  (CONTROL 1: this MUST fail. If it passes, the restore is proving nothing.)")
print("=" * 96)
sys.exit(0 if ok else 1)
