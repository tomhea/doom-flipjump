"""What a HOLE in the restore set actually does -- measured, in a bounded subprocess.

`m1c_restore_set.py`'s ablation reports "N words still differ". That undersells it. Restore
everything EXCEPT one label and run the next frame: for most labels you get a different op count,
but for `sshead` you get a program that DOES NOT TERMINATE -- because `sshead` is the head array of
a linked list, a stale head makes `bind_things` prepend onto a list that is already non-empty, and
`thing_pass` then walks a chain that can close on itself.

That is almost certainly what commit 3046a40 hit when it restored the two low words and reported
"STILL RUNNING AFTER 560s". It was not a slow frame. It was a cycle.

⚠ This runs ONE case per invocation and is meant to be launched under an external timeout, because
the failing case is by definition unbounded and `_fjcore.Memory.run` takes no op cap:

    timeout 90 python scratchpad/m1c_hole.py --drop none      # the CONTROL: must finish fast
    timeout 90 python scratchpad/m1c_hole.py --drop sshead    # expected: killed by the timeout
    timeout 90 python scratchpad/m1c_hole.py --drop spslot    # expected: finishes, ops differ

⚠ NEGATIVE CONTROL (R9): `--drop none` is the same code path with nothing removed. If it did not
finish fast, a timeout on the `sshead` run would prove nothing about `sshead`.
"""
import argparse
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
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
ap.add_argument("--fjm", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--set", default="scratchpad/_m1c_restore_set.json.gz")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--drop", default="none", help="label to punch out of the restore set, or 'none'")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
args = ap.parse_args()
W = 32

w = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bk = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
nv = len(vanishable_slots(dr, bk, VANISHABLE_TYPES))
rt = [t for t, b in zip(dr, bk) if not b]
TAIL = (encode_things([(t.x << 16, t.y << 16) for t in rt])
        + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in rt])
        + encode_visibility([1] * nv))
sp = spawn_state(w, "E1M1")
FEED = encode_feed(664 << 16, 291 << 16, 0x18000000, 0) + TAIL

r = FjmRunner(Path(args.fjm))
assert r.native


def fresh():
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        c.add_segment(s, n)
    for s, v in r._runs:
        c.set_words(s, v)
    return c


PRIST = fresh()
runs = json.load(gzip.open(args.set, "rt", encoding="utf-8"))["runs"]
words = sorted(x for a, b in runs for x in range(a, b))

if args.drop != "none":
    import bisect
    sa, sn = [], []
    with gzip.open(args.labels, "rt", encoding="utf-8") as f:
        for line in f:
            a, t, v = line.rstrip("\n").partition("\t")
            if t:
                sa.append(int(v) // W)
                sn.append(a)
    o = sorted(range(len(sa)), key=lambda i: sa[i])
    sa = [sa[i] for i in o]
    sn = [sn[i] for i in o]
    i = next(k for k, n in enumerate(sn) if n == args.drop)
    a = sa[i]
    j = bisect.bisect_right(sa, a)
    b = sa[j] if j < len(sa) else a + 2
    before = len(words)
    words = [x for x in words if not (a <= x < b)]
    print(f"punched out {args.drop}: [{a:,},{b:,}) = {before-len(words):,} words "
          f"({len(words):,} left)", flush=True)


def coalesce(ws):
    out, s, p = [], ws[0], ws[0]
    for c in ws[1:]:
        if c != p + 1:
            out.append((s, p + 1))
            s = c
        p = c
    out.append((s, p + 1))
    return out


PATCH = [(a, [PRIST.get_word(x) for x in range(a, b)]) for a, b in coalesce(words)]

core = fresh()
scr = StreamScreen(stdin=FEED, n_things=len(rt))
scr.attach_memory(NativeDeviceMemory(core, r.width))
t0 = time.perf_counter()
_c, ops1, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
print(f"frame 1: {ops1:,} ops in {time.perf_counter()-t0:.2f}s", flush=True)

for a, vals in PATCH:
    core.set_words(a, vals)
print(f"restored {len(PATCH):,} runs; now running frame 2 "
      f"({'FULL set -- this is the CONTROL' if args.drop == 'none' else 'set MINUS ' + args.drop})",
      flush=True)

scr2 = StreamScreen(stdin=FEED, n_things=len(rt))
scr2.attach_memory(NativeDeviceMemory(core, r.width))
t0 = time.perf_counter()
_c, ops2, _e, _l, _p = core.run(scr2.read_bit, scr2.write_bit, IOReadOnEOF, last_ops_length=0)
dt = time.perf_counter() - t0
same_px = bytes(scr2.pixel_indices) == bytes(scr.pixel_indices)
print(f"frame 2: {ops2:,} ops in {dt:.2f}s   ops {'==' if ops2 == ops1 else '!='} frame 1, "
      f"pixels {'match' if same_px else 'DIFFER'}", flush=True)
print("VERDICT: " + ("clean re-run" if (ops2 == ops1 and same_px)
                     else f"DIVERGED ({ops2-ops1:+,} ops)"))
