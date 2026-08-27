"""Sprite-visibility AUDIT (owner guarantee: "all sprites always shown when possible").

For every sweep frame: count things that project_thing ACCEPTS (projected on-screen and past the
min-size bar) and, via the renderer's `_thing_stats`, how many arrivals the monotone thing-stop
skipped (`th_claim_stopped` -- must be 0 on non-full frames after the full-latch fix); print the
worst offending frames. NOTE: it does NOT classify misses further (no SLOTS / MINSIZE / OTHER
breakdown -- the `miss_slots`/`miss_minsize`/`miss_other` counters are placeholders, never
incremented).

    python scratchpad/sprite_audit.py [--limit N]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
import doomfj.reference_model as RM
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

ap = argparse.ArgumentParser()
ap.add_argument("--csv", default="scratchpad/sweep_frames.csv")
ap.add_argument("--limit", type=int, default=0)
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
W = cfg.VIEW_W
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")

frames = []
with open(args.csv, encoding="utf-8") as f:
    next(f)
    for line in f:
        x, y, a, _o = line.strip().split(",")
        frames.append((int(x), int(y), int(a)))
if args.limit:
    frames = frames[:args.limit]

# tap the record pipeline: which things got AT LEAST one fragment recorded, and why others didn't
EV: dict = {}
_o_strip = ReferenceModel.sprite_strip
_o_proj = ReferenceModel.project_thing
_cur = {"t": None}


def _proj(self, *a):
    r = _o_proj(self, *a)
    EV.setdefault("proj", []).append((a[4], a[5], r is not None))   # tx_map, ty_map, accepted
    return r


def _strip(*a, **k):
    EV["strips"] = EV.get("strips", 0) + 1
    return _o_strip(*a, **k)


ReferenceModel.project_thing = _proj
ReferenceModel.sprite_strip = staticmethod(_strip)

tot = dict(frames=0, gt_visible=0, recorded=0, miss_slots=0, miss_minsize=0,
           miss_stopped=0, miss_other=0)
worst = []
for i, (vx, vy, va) in enumerate(frames):
    EV.clear()
    tout: list = []
    po: list = []
    rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene,
                         wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                         wall_noise=True, sky=True, near_steps=True, things=True,
                         sprite_wad=art, bbox_cull=True, stack_steps=True, degrade=True,
                         things_out=tout, planes_out=po)
    st = rm._thing_stats
    projs = EV.get("proj", [])
    accepted = sum(1 for _x, _y, ok in projs if ok)
    tot["frames"] += 1
    tot["gt_visible"] += accepted        # projected + accepted = should show somewhere
    tot["recorded"] += accepted          # every accepted thing enters the record loop
    tot["miss_stopped"] += st.get("th_claim_stopped", 0)
    if st.get("th_claim_stopped", 0):
        worst.append((st["th_claim_stopped"], vx, vy, va))
    if (i + 1) % 40 == 0:
        print(f"  ...{i+1}/{len(frames)}", flush=True)

print(f"\n{tot['frames']} frames: accepted things {tot['gt_visible']}, "
      f"monotone-stopped arrivals {tot['miss_stopped']}")
print("frames where the stop skipped things (should ALL be true-full frames):")
for n, vx, vy, va in sorted(worst, reverse=True)[:10]:
    print(f"  {n:4d} skipped @ ({vx},{vy},{va:#x})")
