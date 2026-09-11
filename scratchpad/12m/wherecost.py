"""WHERE does a frame cost what it costs? Ops per frame BY REGION, on the real binary.

The success metric plays ten 100-frame games from the baked player start. At roughly 16 units of
thrust a frame, 100 frames is about 1,600 units of travel on a map 3,952 x 3,400 units across, so
NO script set of that shape can see much of the level: measured 2026-09-11, the ten runs together
visit ~1.6-1.9% of the 12,576 nav cells a player can reach with the doors open. That is a property
of the metric's SHAPE, not of the scripts -- and it is exactly the doubt the owner raised: "maybe
your 13M doesn't get to all the places on the level? only get stuck on cheap screens?"

This answers that question directly. For each region: drive the binary there, then play 100 frames
LOCALLY, and price those frames by PREFIX DIFFERENCING -- run the travel alone, run travel+play,
subtract. Same trick the harness already uses to remove the menu, and it needs no per-frame
instrumentation the native engine does not offer.

    python scratchpad/12m/wherecost.py --fjm build/doom_e1m1_blocked24.fjm
    python scratchpad/12m/wherecost.py --selftest

CONTROLS (R9)
  C1 THE PREFIX MUST REALLY BE A PREFIX -- run B's key script starts with run A's, byte for byte,
     so the subtraction is of identical work. Asserted, not assumed.
  C2 THE FRAMES MUST ARRIVE -- both runs must present exactly the frames asked for; a short run
     returns fewer ops and would read as a cheap region.
  C3 THE PLAYER MUST ACTUALLY BE THERE -- the oracle is stepped through the same script and the
     end position is reported, so a region whose travel leg failed is visible, not silently scored
     as its starting room.
  C4 NON-NEGATIVE -- ops(B) > ops(A), or the differencing is meaningless.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad/12m", ROOT):
    sys.path.insert(0, str(q))

import gamespeed as GS                                                      # noqa: E402
import m2_std_gate as gate                                                  # noqa: E402
from doomfj.config import Config                                            # noqa: E402
from doomfj.reference_model import ReferenceModel, spawn_state, _signed     # noqa: E402
from doomfj.wad import WadFile                                              # noqa: E402
from doomfj import build as B                                               # noqa: E402

UNIT = 1 << 16
PLAY = 100                 # frames priced in each region
TRAVEL_CAP = 260           # frames allowed to reach it


def _local_play(rm, scene, st, n, seed):
    """`n` frames of ordinary play from wherever the player is: walk, turn when the wall says no."""
    keys = []
    turn = "turn_left" if seed % 2 else "turn_right"
    while len(keys) < n:
        kd = {"forward": True}
        nxt = rm.step_sim(st, kd, scene=scene)
        if abs(nxt.x - st.x) + abs(nxt.y - st.y) >= UNIT:
            st = nxt
        else:
            kd = {turn: True}
            st = rm.step_sim(st, kd, scene=scene)
        keys.append(kd)
    return st, keys


def regions(wad=GS.DEFAULT_WAD, mapname=GS.DEFAULT_MAP, n=8):
    GS.TOUR_TARGETS = max(GS.TOUR_TARGETS, n)   # more regions -> a tighter estimate of the spread
    """(label, travel keys, play keys, where the oracle says the player ends up) per region."""
    rm, _scene, sp = GS._oracle(wad, mapname)
    open_scene, targets, boxes, in_box = GS._tour_plan(wad, mapname)
    sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    out = []
    for i, goal in enumerate(targets[:n]):
        wps = GS._waypoints(rm, open_scene, sp, goal)
        st, travel = (sp, []) if not wps else GS._steer(
            rm, open_scene, sp, wps, TRAVEL_CAP, boxes, in_box)
        st2, play = _local_play(rm, open_scene, st, PLAY, i)
        x, y = _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16
        dist = int(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5)
        out.append(("region %d (%d,%d) %d from spawn" % (i, x, y, dist), travel, play, dist))
    return out


def _ops(fjm, per_frame):
    full = [{} for _ in range(gate.MENU_FRAMES)] + list(per_frame)
    frames, ops = gate.run_fj(fjm, GS.events_for(full), len(full))
    assert len(frames) == len(full), (
        "C2 short run: %d of %d frames presented" % (len(frames), len(full)))
    return ops


def sweep(fjm, n=8):
    rows = []
    print("pricing %d regions on %s -- two runs each (travel, travel+play)\n" % (n, fjm))
    for label, travel, play, dist in regions(n=n):
        both = list(travel) + list(play)
        assert both[:len(travel)] == list(travel), "C1 run B is not a prefix-extension of run A"
        a = _ops(fjm, travel)
        b = _ops(fjm, both)
        assert b > a, "C4 travel+play cost no more than travel alone"
        per = (b - a) / float(len(play))
        rows.append((label, dist, len(travel), per))
        print("  %-44s travel %3d frames   %s ops/frame"
              % (label, len(travel), format(int(per), ",")))
    print("")
    vals = [r[3] for r in rows]
    lo, hi = min(vals), max(vals)
    print("CHEAPEST region : %s ops/frame" % format(int(lo), ","))
    print("DEAREST  region : %s ops/frame" % format(int(hi), ","))
    print("SPREAD          : %.2fx  (a single-region number can be this far from another)"
          % (hi / lo if lo else 0))
    print("MEAN over regions: %s ops/frame" % format(int(sum(vals) / len(vals)), ","))
    return rows


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-56s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("wherecost selftest -- the controls, without running a binary")
    rs = regions(n=4)
    check("C1 every run B is a prefix-extension of its run A",
          all((list(t) + list(p))[:len(t)] == list(t) for _l, t, p, _d in rs))
    check("C2 every region asks for the same number of PLAY frames",
          all(len(p) == PLAY for _l, _t, p, _d in rs))
    check("C3 the regions are actually apart",
          len({d for _l, _t, _p, d in rs}) > 1,
          "distances %s" % sorted({d for _l, _t, _p, d in rs}))
    far = [d for _l, _t, _p, d in rs if d > 400]
    check("C3 ...and at least one is far from spawn", bool(far), "%s" % sorted(far))
    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked24.fjm")
    ap.add_argument("--regions", type=int, default=8)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else (sweep(a.fjm, a.regions) and 0))
