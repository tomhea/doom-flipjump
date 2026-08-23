"""M1c step 0 — build a restore set that is DERIVED, and PROVE it in the harness before writing fj.

WHY NOT A LEARNED SET. `dirty_restore.py` learned RANGES from sampled frames and its own docstring
says that is unsound. M1a's measurements say exactly why a learned set must be short:

  * `write_byte` / `hex.input` XOR the DELTA, so a write of the value already there is INVISIBLE to
    every census -- MEASURED: `thpos_rt` shows 0 dirty words with the standard wire and 92 the
    moment things move;
  * `sshead` has 682 reachable cells and a frame writes at most 75, and WHICH 75 is runtime data.

THE CONSTRUCTION, in three parts. The first two are DERIVED; the third is belt and braces.

  A. DECLARED  -- every label the EMITTER declares as runtime state: all top-level labels of
     `e1m1_05_state.fj`, of `e1m1_01_tables.fj`, and of the state prefix of `e1m1_06_banks.fj`
     (which ends at `thvis`, after which the file is baked banks). It does not care whether a frame
     was ever observed writing them -- that is the entire point.
  B. MACRO-LOCAL VECTORS -- every label mangled `...---<local>` whose `<local>` is declared
     `hex.vec`/`bit.vec` somewhere. These are the stl/emitter scratch registers created INSIDE code;
     they appear in no declaration list and a frame that runs a code path no censused frame ran
     leaves that path's scratch dirty. Restoring ALL macro-locals is impossible (5,128,268 labels,
     47,145,920 words = 55% of the image, because label-to-label extents sweep up the code between
     jump targets); filtering to declared VECTORS collapses that to ~6.5k labels / ~66k words. It is
     small only because this repo puts every heavy body in a SHARED LEAF instantiated once.
  C. OBSERVED  -- the full extent of every label a censused frame dirtied. After A and B, only 9
     labels come from here alone.

Each label contributes its WHOLE extent `[label, next label)`, never just the cells seen dirty --
so a frame that writes a different cell of a known label is covered for free.

⚠ A restore is `set to the PRISTINE value`, never `set to 0`: 81,573 words of the set (22.4%) are
non-zero in the pristine image (`pmax = 159`, `col_top = 1`, `thpos_rt` = baked spawn positions,
and every read-only LUT). Zeroing `pmax` makes every seg find an empty window and kills plane
attribution for the whole frame, silently.

⚠ THE PARSER FOR (B) HAS BEEN WRONG THREE TIMES, each costing a holdout failure, so each shape is
now a NAMED ASSERTION: next-line declarations (`ba:` then `.vec n`, which is how the stl writes
them), GENERATED macros (`w1rpat.walk_win`'s `wl2`, written by lut_generator.py and present in no
.fj file), and `rep(...)` declarations (`col_top: rep(160, i) hex.vec 8, 1`).

⚠ NEGATIVE CONTROLS (R9) -- "the restore worked" is precisely the claim that must not be trusted:
  1. HOLDOUT: sufficiency is tested on frames the set was never built from -- other viewpoints,
     other key states, and a MOVED-things wire. Testing only the built-from frames is circular.
  2. ABLATION: the validation is re-run with one label's words REMOVED, and it MUST FAIL. Only
     labels that were actually observed dirty are ablated -- dropping a never-written label
     legitimately changes nothing, and counting that as "no teeth" would be the wrong test.
     ⚠ The ablation removes WORDS and re-coalesces. An earlier version filtered whole RUNS, and
     since runs coalesce across label boundaries it removed nothing and reported "no teeth" for
     five labels in a row. A control that cannot subtract cannot detect.
  3. VACUITY: every frame must run > 1e6 ops AND must dirty something before the restore.
  4. SUPERSET: the set must contain every measured dirty word (asserted).

The pass condition is the real M1 gate: after the restore, an EXACT walk of all 84.8M words against
the pristine image reports 0 differ, and re-running the same frame reproduces the op count AND the
pixels byte for byte.

    python scratchpad/m1c_restore_set.py <fjm>
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

from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.reference_model import spawn_state                            # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--dirty", default="scratchpad/_m1_dirty_grand.json.gz")
ap.add_argument("--gen", default="scratchpad/fjmcache/_rssgen")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--ablate", type=int, default=8)
ap.add_argument("--drop-luts", action="store_true",
                help="exclude the read-only LUTs. Restoring a region nothing writes is safe but is "
                     "pure cost; this measures whether they are really never written, and the "
                     "holdout is what decides -- do not drop them on the argument alone.")
ap.add_argument("--dump", default="scratchpad/_m1c_restore_set.json.gz")
args = ap.parse_args()

# The state prefix of the banks part ends at `thvis`; everything after is baked bank data.
BANKS_STATE_ENDS_AT = "thvis"
# Read-only LUTs that live in the tables part. Restoring them is SAFE (a restore writes the
# pristine value, so a read-only region is a no-op) but it is 224,766 words of pure cost, so they
# are reported separately rather than silently included.
READONLY_LUTS = {"stepcol", "lnrow", "finetangent", "slopediv_recip8", "slopediv_recip",
                 "tantoangle", "viewangletox", "bklin"}


# ---------------------------------------------------------------------------- the declared state
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


GEN = Path(args.gen)
DECLARED = set(top_labels(GEN / "e1m1_01_tables.fj")) \
    | set(top_labels(GEN / "e1m1_05_state.fj")) \
    | set(top_labels(GEN / "e1m1_06_banks.fj", stop_after=BANKS_STATE_ENDS_AT))
# CONTROL: `BANKS_STATE_ENDS_AT` is a hardcoded boundary in a file the emitter writes. If the
# emitter ever moves a state declaration past `thvis`, the prefix silently stops covering it and the
# restore set silently shrinks -- with no symptom until frame 2 runs a different program. So name
# the state labels that MUST be inside the prefix, and fail loudly if one is not.
for _n in ("sshead", "thnext", "thss_rt", "cur_ss", "thvis", "ptss"):
    assert _n in DECLARED, (f"CONTROL FAILED: {_n} is not in the declared-state prefix -- the "
                            f"emitter moved it past '{BANKS_STATE_ENDS_AT}' in e1m1_06_banks.fj")
print(f"DECLARED runtime-state labels (from the emitted parts): {len(DECLARED)}")

# ------------------------------------------------------------------------------------ the frames
def _things():
    from doomfj.config import Config
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel
    from doomfj.things import baked_thing_mask, vanishable_slots
    w = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(w, "E1M1")
    drawable = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    rt = [t for t, b in zip(drawable, baked) if not b]
    return rt, [rm.point_in_subsector(cmap, t.x, t.y) for t in rt], nvis


RT, BINDS, NVIS = _things()


def feed(vx, vy, va, keys=0, dx=0, dy=0):
    from doomfj.wireformat import (encode_bindings, encode_feed, encode_things,
                                   encode_visibility)
    return (encode_feed(vx, vy, va, keys)
            + encode_things([((t.x + dx) << 16, (t.y + dy) << 16) for t in RT])
            + encode_bindings(BINDS) + encode_visibility([1] * NVIS))


_sp = spawn_state(WadFile.from_path(str(ROOT / args.wad)), "E1M1")
SPAWN = (_signed(_sp.x, 32), _signed(_sp.y, 32), _sp.angle)
BUILT_FROM = [(664 << 16, 291 << 16, 0x18000000, 0), (664 << 16, 291 << 16, 0x18000000, 1),
              (1272 << 16, (-724) << 16, 0x40000000, 5), (SPAWN[0], SPAWN[1], SPAWN[2], 0)]
HOLDOUT = [(SPAWN[0], SPAWN[1], SPAWN[2], 4, 0, 0),          # turn left only
           (SPAWN[0], SPAWN[1], SPAWN[2], 8, 0, 0),          # turn right only
           (SPAWN[0], SPAWN[1], SPAWN[2], 0, 64, 0),         # THINGS MOVED -- the known leak
           (SPAWN[0], SPAWN[1], SPAWN[2], 1, -32, 48),       # moving AND things moved
           (1000 << 16, 100 << 16, 0x20000000, 0, 0, 0),     # viewpoints never censused
           (1500 << 16, (-200) << 16, 0x60000000, 1, 0, 0),
           (2100 << 16, 800 << 16, 0xC0000000, 5, 16, -16)]

# ------------------------------------------------------------------------------------- the image
r = FjmRunner(Path(args.fjm))
assert r.native, "needs the native engine"
TOTAL = sum(n for _s, n in r._segments)
print(f"{Path(args.fjm).name}: {TOTAL:,} words", flush=True)


def fresh():
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        core.add_segment(s, n)
    for st, vals in r._runs:
        core.set_words(st, vals)
    return core


PRISTINE = fresh()


def run(core, f):
    scr = StreamScreen(stdin=f, n_things=len(RT))
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    return ops, bytes(scr.pixel_indices)


def walk_count(core, limit=None):
    n = 0
    for s, ln in r._segments:
        for x in range(s, s + ln):
            if PRISTINE.get_word(x) != core.get_word(x):
                n += 1
                if limit and n >= limit:
                    return n
    return n


# ------------------------------------------------------------------------------- the restore set
print("building the restore set ...", flush=True)
grand = json.load(gzip.open(args.dirty, "rt", encoding="utf-8"))["grand"]
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
first_of = {}
for i, n in enumerate(sn):
    first_of.setdefault(n, i)


def extent(i):
    a = sa[i]
    j = bisect.bisect_right(sa, a)
    return a, (sa[j] if j < len(sa) else a + 2)


observed = {}
for wd in grand:
    i = bisect.bisect_right(sa, wd) - 1
    if i >= 0:
        observed[i] = observed.get(i, 0) + 1

# C. MACRO-LOCAL VECTORS -- the class that defeated the observed-only set. A macro's `@`-locals are
# invisible in any declaration list, and a frame that runs a code path no censused frame ran leaves
# that path's scratch dirty. But every one of them IS in the label table, mangled as
# `...---<local>`, and whether `<local>` is DATA is answerable from the fj sources: it is data iff
# some macro declares it `hex.vec`/`bit.vec`. Filtering on that turns an unusable 47,145,920-word
# "all macro-locals" (which sweeps up every jump target and the code between them) into ~40k words.
# It is small only because this repo puts every heavy body in a SHARED leaf instantiated ONCE.
def vec_names(path):
    """Names declared as a vec, whether the declaration is on the label's line or the NEXT one.

    ⚠ THE NEXT-LINE FORM IS NOT AN EDGE CASE -- it is how the stl writes it, e.g. `hex.scmp`:
          ba:
            .vec n
    A same-line-only regex misses `ba`/`bb` and every other stl scratch vector, which is exactly
    how an earlier version of this set left 185 words leaking out of `sim.check_line`.
    """
    out, pend = set(), []
    for line in io.open(path, encoding="utf-8", errors="replace"):
        s = line.split("//")[0].rstrip()
        if not s.strip():
            continue
        m = re.match(r"^\s*([A-Za-z_]\w*):\s*(.*)$", s)
        if m:
            pend.append(m.group(1))
            rest = m.group(2).strip()
            if not rest:
                continue
            s = rest
        # `x: hex.vec 8`, `x:` / `.vec n`, and `x: rep(160, i) hex.vec 8, 1` are all declarations.
        if re.match(r"^(?:rep\s*\([^)]*\)\s*)?(?:\.|hex\.|bit\.)?vec\b", s.strip()):
            out.update(pend)
        pend = []
    return out


VECNAMES = set()
_fjsrc = list((ROOT / "src/fj").glob("*.fj"))
_stl = Path(sys.modules["flipjump"].__file__).parent / "stl"
_fjsrc += list(_stl.rglob("*.fj"))
# ⚠ AND THE EMITTED PARTS. Some macros are GENERATED (`lut_generator.py` writes `w1rpat.walk_win`
# and its `wl2: hex.vec 2` straight into the program text), so they exist in no hand-written .fj
# file and a parser that reads only src/fj + the stl cannot see their locals. That gap left exactly
# two words -- `walk_win`'s `gxor` and `wl2` -- leaking on one holdout viewpoint.
_fjsrc += [GEN / f for f in ("e1m1_01_tables.fj", "e1m1_02_main.fj", "e1m1_03_segconsts.fj",
                             "e1m1_04_walk.fj", "e1m1_05_state.fj", "e1m1_06_banks.fj")]
for p in _fjsrc:
    if p.is_file():
        VECNAMES |= vec_names(p)
# CONTROL: every shape that has defeated a previous version of this parser is named here. A parser
# that silently stops seeing one of them would otherwise just quietly shrink the restore set.
for _n, _why in (("ba", "hex.scmp's NEXT-LINE `ba:` / `.vec n` (stl)"),
                 ("bb", "hex.scmp's NEXT-LINE `bb:` / `.vec n` (stl)"),
                 ("wl2", "w1rpat.walk_win's `wl2: hex.vec 2` -- a GENERATED macro, src/fj has it not"),
                 ("wide_a", "hex.fixed_mul_lo's scratch"),
                 ("col_top", "an emitter-declared per-column array")):
    assert _n in VECNAMES, f"CONTROL FAILED: the vec parser no longer sees {_n} -- {_why}"
print(f"  {len(_fjsrc)} fj sources -> {len(VECNAMES)} names ever declared as a vec")

MACROVEC_CAP = 256                 # a declared vec bigger than this is a mis-filter, not a vec
macrovec, skipped = {}, []
for i, n in enumerate(sn):
    if "---" not in n or n.rsplit("---", 1)[-1] not in VECNAMES:
        continue
    a, b = extent(i)
    if b - a > MACROVEC_CAP:
        skipped.append((b - a, n))
        continue
    macrovec[i] = b - a

regions = {}                       # name -> (a, b, source)
for i in observed:
    a, b = extent(i)
    regions[sn[i]] = (a, b, "observed")
for i in macrovec:
    a, b = extent(i)
    regions[sn[i]] = (a, b, "macrovec" if sn[i] not in regions else "both")
for n in DECLARED:
    i = first_of.get(n)
    if i is None:
        continue
    a, b = extent(i)
    regions[n] = (a, b, "declared" if n not in regions else "both")
regions["op0+stl.IO"] = (0, 4, "declared")
print(f"  macro-local declared-vec labels: {len(macrovec):,} "
      f"({sum(macrovec.values()):,} words); {len(skipped)} skipped as implausible")
for e, n in sorted(skipped, reverse=True)[:4]:
    print(f"     skipped {e:>9,} words: {n[:80]}")


if args.drop_luts:
    for n in list(regions):
        if n in READONLY_LUTS:
            del regions[n]
    print(f"  --drop-luts: removed {len(READONLY_LUTS)} read-only LUT labels from the set")
lut_words = sum(b - a for n, (a, b, _s) in regions.items() if n in READONLY_LUTS)
words = set()
for n, (a, b, _s) in regions.items():
    words.update(range(a, b))
words = sorted(words)
wset = set(words)
missing = [w for w in grand if w not in wset]
if missing and args.drop_luts:
    print(f"  !! --drop-luts removed {len(missing):,} words that a censused frame DID dirty -- "
          f"a 'read-only' LUT is written after all")
assert not missing, f"CONTROL 4 FAILED: not a superset -- {len(missing)} measured words absent"
nz = sum(1 for w in words if PRISTINE.get_word(w) != 0)
from collections import Counter                                           # noqa: E402
src_hist = Counter(s for _n, (_a, _b, s) in regions.items())
print(f"  {len(regions):,} labels by source: {dict(src_hist)}")
print(f"  -> {len(words):,} words ({100*len(words)/TOTAL:.5f}% of the image, "
      f"~{len(words)*8/1e6:.3f} MB)")
print(f"  superset of the {len(grand):,} measured dirty words: ok")
print(f"  NON-ZERO pristine values: {nz:,} ({100*nz/len(words):.1f}%) -- a memset(0) is WRONG")
print(f"  read-only LUT words still IN the set: {lut_words:,}"
      + ("  (--drop-luts removed them)" if args.drop_luts else "  -- droppable with --drop-luts"))


def coalesce(ws):
    out, s, p = [], ws[0], ws[0]
    for c in ws[1:]:
        if c != p + 1:
            out.append((s, p + 1))
            s = c
        p = c
    out.append((s, p + 1))
    return out


def patch_for(ws):
    return [(a, [PRISTINE.get_word(x) for x in range(a, b)]) for a, b in coalesce(ws)]


RUNS = coalesce(words)
PATCH = patch_for(words)
print(f"  as {len(RUNS):,} contiguous runs")
json.dump({"fjm": args.fjm, "words": len(words), "labels": len(regions), "nonzero": nz,
           "readonly_lut_words": lut_words, "runs": [[a, b] for a, b in RUNS]},
          gzip.open(args.dump, "wt", encoding="utf-8"))
print(f"  wrote {args.dump}")


def validate(patch, cases, label, quiet=False, rerun=True):
    """rerun=False skips the frame-2 re-run and judges on the walk alone.

    ⚠ THE ABLATION MUST PASS rerun=False, AND THIS IS NOT AN OPTIMISATION. A hole in a LINKED-LIST
    head does not merely change the op count: leave `sshead` unrestored and frame 2 does not
    terminate at all -- `bind_things` prepends onto a list that is already non-empty and
    `thing_pass` walks a chain that can close on itself. MEASURED: killed at 180 s against a 0.22 s
    clean re-run (`scratchpad/m1c_hole.py --drop sshead`, exit 124; the control exits 0).
    `_fjcore.Memory.run` takes no op cap, so a re-run inside the ablation loop is an unbounded hang.
    The walk alone is sufficient evidence for the ablation: `left > 0` already means insufficient.
    """
    ok = True
    for c in cases:
        vx, vy, va, keys = c[0], c[1], c[2], c[3]
        dx, dy = (c[4], c[5]) if len(c) > 4 else (0, 0)
        f = feed(vx, vy, va, keys, dx, dy)
        core = fresh()
        ops1, px1 = run(core, f)
        assert ops1 > 1_000_000, f"CONTROL 3 (vacuity): {ops1} ops -- wrong wire"
        assert walk_count(core, limit=1) > 0, "CONTROL 3 (vacuity): the frame dirtied nothing"
        for a, vals in patch:
            core.set_words(a, vals)
        left = walk_count(core, limit=None if not quiet else 500)
        if not rerun:                       # ablation: the walk alone decides (see the docstring)
            good = (left == 0)
            ops2, px2 = ops1, px1
        else:
            ops2, px2 = run(core, f)
            good = (left == 0) and (ops2 == ops1) and (px2 == px1)
        ok &= good
        if not quiet or not good:
            tail = (f"re-run {ops2:,} {'==' if ops2 == ops1 else '!='}, pixels "
                    f"{'match' if px2 == px1 else 'DIFFER'}" if rerun else
                    "re-run SKIPPED (would not terminate on a linked-list hole)")
            print(f"  {label} ({vx>>16},{vy>>16},{va:#x},k={keys},d=({dx},{dy})): {ops1:,} ops "
                  f"-> {left:,} differ after restore; {tail}  {'ok' if good else 'FAIL'}",
                  flush=True)
        del core
        if not good and quiet:
            return False
    return ok


t0 = time.perf_counter()
print("\nVALIDATION A -- frames the set was BUILT from (necessary, not sufficient):")
a_ok = validate(PATCH, BUILT_FROM, "built")
print("\nVALIDATION B -- HOLDOUT frames the set was NEVER built from (the real test):")
b_ok = validate(PATCH, HOLDOUT, "holdout")
print(f"\n({time.perf_counter()-t0:.0f}s so far)")

c_ok = True
if args.ablate:
    print("\nCONTROL 2 (ablation): removing ONE observed-dirty label's WORDS must make it FAIL.")
    cand = sorted(((extent(i)[1] - extent(i)[0], sn[i]) for i in observed), reverse=True)
    seen = set()
    picked = []
    for szn in cand:
        if szn[1] not in seen and szn[1] != "op0+stl.IO":
            seen.add(szn[1])
            picked.append(szn)
        if len(picked) >= args.ablate:
            break
    for sz, n in picked:
        a, b = regions[n][0], regions[n][1]
        sub = [x for x in words if not (a <= x < b)]
        failed = not validate(patch_for(sub), BUILT_FROM[:1] + HOLDOUT[2:3],
                              f"ablate<{n[:24]}>", quiet=True, rerun=False)
        print(f"  drop {n[:36]:<36} ({sz:>5,} w, set {len(sub):,}): "
              f"{'ok -- FAILED as required' if failed else '!! STILL PASSED -- no teeth'}",
              flush=True)
        c_ok &= failed

print("\n" + "=" * 100)
print(f"VALIDATION A (built-from) : {'PASS' if a_ok else 'FAIL'}")
print(f"VALIDATION B (holdout)    : {'PASS' if b_ok else 'FAIL'}")
print("CONTROL 2  (ablation)     : " + ("SKIPPED (--ablate 0)" if not args.ablate
      else ('PASS -- the test has teeth' if c_ok else 'FAIL -- no teeth')))
print(f"restore set: {len(words):,} words = {len(words)//2:,} hex cells, {len(RUNS):,} runs, "
      f"{nz:,} non-zero ({100*nz/len(words):.1f}%), {lut_words:,} read-only LUT")
print("=" * 100)
sys.exit(0 if (a_ok and b_ok and c_ok) else 1)
