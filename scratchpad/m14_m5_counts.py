"""M5 — ORACLE-SIDE COUNTING. The §2 open counts, with no build at all.

`docs/handoff-perf.md` §2 lists four "how many per frame" questions that were previously answered
with residuals. §3's M5 says to answer them in Python across the sweep's own 260 viewpoints, and
§7b step 4 puts that before any lever is proposed. This is that.

WHAT IT COUNTS, and why each one prices a specific lever:

  * leaves the walk can reach, and how many of them CARRY A THING (static, exact) -- lever 5a's
    ceiling. Every visited leaf with segs pays 3 `hex.set`s + an `fcall` + a `ptr_index`/`read_byte`
    head probe (wall_renderer.py subsector_action, sim.fj `thing_pass`), whether or not it has
    things. If almost every leaf has things, 5a is worthless.
  * things the walk ARRIVES at = the number of `sim.thing_load` calls (thing_pass loads BEFORE the
    per-thing budget/size rejects fire inside thing_leaf) -- the multiplier on §1.2's measured
    45,934 ops/call.
  * how many of those SURVIVE each reject -- lever 5c is worth exactly the reject rate, and §5c
    says in terms: if most survive, the lever does not exist.

⚠ HOW IT MEASURES, and the one thing to distrust. It does NOT re-implement the walk. It renders
through `ReferenceModel.render_wall_frame` itself and reads the counters the oracle already keeps
(`_thing_stats`), plus two WRAPPERS around `project_thing`/`sprite_art` installed from here. No
oracle file is edited (§12.5). The wrapper counts are therefore the oracle's own control flow.

⚠ WHAT IT CANNOT SEE. The oracle's thing pre-pass and fj's `thing_pass` stop on slightly different
things: fj's leaf body is skipped wholesale by the `full` latch and its list walk stops on `tstop`,
where the oracle breaks on `n_wdrawn == W` and `continue`s past a spent budget. Both are pixel-
equivalent by construction, but the ARRIVAL count fj pays can be slightly lower than the oracle's.
So `th_arrived` here is an UPPER BOUND on fj's thing_load calls, and it is labelled that way.

    python scratchpad/m14_m5_counts.py [--stride N] [--csv out.csv]
"""
import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.reference_model import (MONSTER_BUDGET, THING_BUDGET,         # noqa: E402
                                    ReferenceModel, SimState, build_scene)
from doomfj.wad import WadFile                                            # noqa: E402
from nb_validate import _near_any_line, true_sector                       # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--step", type=int, default=256)
ap.add_argument("--angles", type=int, default=4)
ap.add_argument("--stride", type=int, default=1, help="render every Nth frame (1 = all 260)")
ap.add_argument("--vp", action="append", default=[],
                help="count THESE viewpoints (X,Y,ANG) instead of the grid -- for pairing a count "
                     "with an opprof.py profile of the same frame")
ap.add_argument("--csv", default=None)
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
cmap = scene.cmap

# the gate's / sweep's RENDER_KW, verbatim -- a different tier counts a different program
RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)

# ── the STATIC structure: lever 5a's ceiling ───────────────────────────────────────────────────
DRAWABLE = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
occupied = {rm.point_in_subsector(cmap, t.x, t.y) for t in DRAWABLE}
with_segs = [i for i, ss in enumerate(cmap.subsectors) if ss.numsegs]
occ_segs = [i for i in with_segs if i in occupied]
print("=== STATIC (exact, spawn positions) ===")
print(f"subsectors                    : {len(cmap.subsectors)}")
print(f"  ... with segs (walk emits a body for these) : {len(with_segs)}")
print(f"  ... carrying >=1 drawable thing             : {len(occ_segs)}")
print(f"  ... EMPTY of things                         : {len(with_segs) - len(occ_segs)} "
      f"({100 * (len(with_segs) - len(occ_segs)) / len(with_segs):.1f}% of bodied leaves)")
print(f"drawable things               : {len(DRAWABLE)}")
print(f"budgets                       : THING_BUDGET={THING_BUDGET} "
      f"MONSTER_BUDGET={MONSTER_BUDGET}")

# ── the grid: m14_sweep.py's, so the counts land on the frames the median is taken over ────────
verts = [(v.x, v.y) for v in mw.vertexes("E1M1")]
lds, sds = mw.linedefs("E1M1"), mw.sidedefs("E1M1")
xs, ys = [v[0] for v in verts], [v[1] for v in verts]
pts = []
for x in range(min(xs) + 13, max(xs), args.step):
    for y in range(min(ys) + 7, max(ys), args.step):
        if _near_any_line(verts, lds, x, y, 24.0):
            continue
        if true_sector(verts, lds, sds, x, y) == -1:
            continue
        pts.append((x, y))
frames = [(x, y, (k << 30) & 0xFFFFFFFF) for x, y in pts for k in range(args.angles)]
frames = frames[::args.stride]
if args.vp:
    frames = [tuple(int(v, 0) for v in s.split(",")) for s in args.vp]
print(f"\n{len(pts)} walkable points x {args.angles} angles -> rendering {len(frames)} frames "
      f"(stride {args.stride})", flush=True)

# ── the WRAPPERS: the oracle's own control flow, counted from outside it ───────────────────────
CNT = {"proj": 0, "proj_none": 0, "art": 0}
_real_project = ReferenceModel.project_thing
_real_art = ReferenceModel.sprite_art


def _project(self, *a, **k):
    CNT["proj"] += 1
    r = _real_project(self, *a, **k)
    if r is None:
        CNT["proj_none"] += 1
    return r


def _art(self, *a, **k):
    CNT["art"] += 1
    return _real_art(self, *a, **k)


ReferenceModel.project_thing = _project
ReferenceModel.sprite_art = _art

rows = []
for i, (x, y, va) in enumerate(frames):
    CNT["proj"] = CNT["proj_none"] = CNT["art"] = 0
    rm.render_wall_frame(SimState(x << 16, y << 16, va, "E1M1"), scene, **RENDER_KW)
    st = rm._thing_stats
    arrived = st["th_arrived"]
    projected = CNT["proj"]
    accepted = projected - CNT["proj_none"]
    rows.append((x, y, va, st["ss_arrived"], arrived, CNT["art"], projected,
                 CNT["proj_none"], accepted, st["th_claim_stopped"]))
    if (i + 1) % 20 == 0:
        print(f"  ...{i+1}/{len(frames)}", flush=True)

ReferenceModel.project_thing = _real_project
ReferenceModel.sprite_art = _real_art


# ── LEAVES VISITED BEFORE `full` — the last §2 count, and lever 5a's multiplier ────────────────
# Every leaf the walk enters while `full` is clear runs the thing pre-pass preamble (3 hex.set +
# fcall + ptr_index + read_byte) even when it holds nothing; once `full` latches, the leaf body is
# skipped wholesale by `hex.if0 1, full` (wall_renderer.py subsector_action). `full` is MONOTONE,
# so the not-full leaves are a PREFIX of the BSP walk order -- which makes this exact rather than
# modelled: the oracle's claim-stop count says how many THING-CARRYING leaves fell in the suffix,
# and the prefix boundary is bracketed by the walk positions of the surrounding thing-carrying
# leaves. Reported as a bracket [lo, hi] because `full` may latch anywhere between them.
print("\n=== LEAVES ENTERED BEFORE `full` (exact bracket) ===")
brackets = []
for _i, ((x, y, va), r) in enumerate(zip(frames, rows)):
    order = rm.bsp_render_order(cmap, x, y)
    carr = [i for i, ss in enumerate(order) if ss in occupied and cmap.subsectors[ss].numsegs]
    n_not_full = len(carr) - r[9]                      # thing-carrying leaves in the prefix
    lo = carr[n_not_full - 1] + 1 if n_not_full else 0     # just past the last not-full one
    hi = carr[n_not_full] if n_not_full < len(carr) else len(order)
    brackets.append((lo, hi, len(order)))
    # the CSV carries it per frame: a two-predictor fit (calls AND leaves) is the only way to
    # split thing_pass's per-leaf preamble from its per-thing loop step, and two hand-picked
    # viewpoints cannot do it -- 463/183 vs 439/176 are near-parallel equations.
    rows[_i] = r + (lo, hi)
_lo = sorted(b[0] for b in brackets)
_hi = sorted(b[1] for b in brackets)
print(f"leaves in the walk order            : {brackets[0][2]}")
print(f"entered before `full`   LOW  bound  : min {_lo[0]:4d}  MEDIAN {_lo[len(_lo)//2]:4d}  "
      f"max {_lo[-1]:4d}")
print(f"                        HIGH bound  : min {_hi[0]:4d}  MEDIAN {_hi[len(_hi)//2]:4d}  "
      f"max {_hi[-1]:4d}")
print("  ... of which carry NO thing (the leaves lever 5a would skip): "
      f"MEDIAN {_lo[len(_lo)//2] - (len(occ_segs) - sorted(r[9] for r in rows)[len(rows)//2]):d} "
      "(low bound minus the not-full thing-carrying leaves)")


def stat(col, name):
    v = sorted(r[col] for r in rows)
    print(f"{name:44s} min {v[0]:5d}  MEDIAN {v[len(v)//2]:5d}  mean {statistics.mean(v):8.1f}  "
          f"max {v[-1]:5d}")


print(f"\n=== PER FRAME over {len(rows)} frames ===")
stat(3, "leaves WITH THINGS the walk arrived at")
stat(4, "things ARRIVED at (oracle loop entries)")
stat(9, "... of those, the CLAIM-STOP break (leaf full)")
stat(6, "... reached project_thing  == fj thing_load calls")
stat(7, "... project_thing REJECTED (size/behind)")
stat(8, "... ACCEPTED (drew a sprite)")

# ⚠ arrived - projected is the CLAIM-STOP break, not a budget: THING_BUDGET/MONSTER_BUDGET are
# both 255 against 251 drawable things, so neither can ever bind on this map. The first cut in the
# ladder is `n_wdrawn == W` (fj: the leaf's `full` gate), and the oracle counts the thing that
# TRIGGERED the break as arrived while fj skips that leaf's body entirely -- which is why
# `projected` and not `arrived` is the honest count of fj's thing_load calls.
tot_arr = sum(r[4] for r in rows)
tot_pr = sum(r[6] for r in rows)
tot_acc = sum(r[8] for r in rows)
print("\n=== THE SURVIVOR RATE (lever 5c is worth exactly this) ===")
print(f"arrived {tot_arr:,} -> claim-stopped {tot_arr - tot_pr:,} "
      f"({100 * (tot_arr - tot_pr) / max(1, tot_arr):.1f}%; budgets are 255 and cannot bind)")
print(f"        -> LOADED+projected {tot_pr:,} -> size/behind-rejected {tot_pr - tot_acc:,} "
      f"({100 * (tot_pr - tot_acc) / max(1, tot_pr):.1f}% of loaded)")
print(f"        -> ACCEPTED {tot_acc:,} = {100 * tot_acc / max(1, tot_pr):.1f}% of loaded")

if args.csv:
    out = ROOT / args.csv
    out.write_text("x,y,va,ss_arrived,th_arrived,art_calls,projected,proj_none,accepted,"
                   "claim_stopped,leaves_lo,leaves_hi\n"
                   + "\n".join(",".join(str(c) for c in r) for r in rows) + "\n")
    print(f"wrote {out}")
