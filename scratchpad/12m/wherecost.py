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
  C5 EVERY REGION IS A DIFFERENT RUN -- and since the spin makes every region's PLAY leg the
     IDENTICAL 102 keys, the script signature now collapses to the travel leg. Two routes ending
     in the same cell have DIFFERENT scripts and would sail through a script-identity test while
     pricing the same spot twice. THE POSITION ASSERT IS THE LOAD-BEARING ONE NOW; the script test
     has become near-vacuous and therefore looks deletable. It is not -- it still catches a
     travel-leg collision.
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
TRAVEL_CAP = 260           # frames allowed to reach a region
SPIN = 102                 # frames for one full turn. ANGLE_TURN is 41,943,040 BAM, so a circle is
                           # 2**32/ANGLE_TURN = 102.40 frames: 102 sweeps 358.6 degrees (MEASURED),
                           # which covers every heading once and repeats none. 103 would wrap past
                           # the start and double-count the first heading.
PLAY = SPIN                # the play leg is one full turn; the alias keeps older callers working


def _spin(rm, scene, st, n):
    """`n` frames of pure rotation: sweep every sightline from this spot.

    ⚠ THIS REPLACED A WANDER, AND THE WANDER WAS SAMPLING THE CHEAPEST EIGHTH OF EVERY REGION.
    The old policy walked forward and turned only when the geometry refused, so it HUGGED WALLS --
    and a wall in your face is a short sightline and a cheap frame. MEASURED: for each region, ask
    where its 100 wander frames sit inside that same spot's distribution over headings. The mean
    quantile was **0.130**. Fair sampling would be 0.500. The wander was not sampling the region;
    it was sampling the region's cheapest eighth, a hundred times.

    Two independent confirmations that this is a real bias and not an artefact of the model:
      * the success metric's own ten scripts are STEERED ROUTES, not wall-hugging wanders, and on
        the SAME binary they price 16,629,651 mean / 21,862,375 p80 -- against the wander regions'
        10,790,667. Two instruments, one binary, 35% apart, and the cheaper one is the one whose
        policy hugs walls. That comparison needs no proxy at all.
      * heading turned out to matter as much as position: within-region spread over headings runs
        1.43x to 10.05x, against the 5.81x spread BETWEEN regions the instrument exists to measure.
        And heading was being chosen by index parity.

    A spin prices a STANDING player, and that is a real limitation: it cannot see the sprite-work
    ramp as a thing approaches, door-animation frames, or the visplane turnover as you cross a
    sector boundary. It also weights all 360 degrees equally where a real player's headings are
    not uniform. So the truth for "what does a player average here" sits between the wander's 0.13
    quantile and the spin's 0.50 -- which is why the spin lands just ABOVE the traversal metric
    rather than at half of it. That is the sanity check that matters: a regional instrument
    disagreeing with the success metric by 2x was describing its own policy, not the level.

    The fix for the POSITION dimension is more regions, not a walk rule inside one region -- any
    walk rule must decide when to turn, and that free parameter is what ended up dominating the
    number."""
    keys = []
    while len(keys) < n:
        kd = {"turn_left": True}      # direction is now irrelevant: MEASURED spin-mean left vs
        st = rm.step_sim(st, kd, scene=scene)   # right differs by -0.17%, +0.13%, -0.02%, against
        keys.append(kd)                          # the wander's 76%
    return st, keys


def _local_play(rm, scene, st, n, variant):
    """The original wander, kept ONLY as the low bracket -- it hugs walls and prices a region's
    cheap headings. Never the default again; `--play wander` reproduces the old numbers."""
    keys = []
    turn = "turn_left" if variant % 2 else "turn_right"
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


def _walk(rm, scene, st, n, goal, boxes, in_box):
    """`n` frames of a player GOING SOMEWHERE from here -- steered, not wandering, not spinning.

    THIS IS THE POLICY THAT MATCHES PLAY, and the other two bracket it rather than replace it:

      * `_local_play` (the wander) walked forward and turned only when refused, so it hugged walls.
        A wall in your face is a short sightline and a cheap frame. MEASURED on the binary:
        10,790,667 mean over 16 regions.
      * `_spin` sweeps every heading equally. That makes a region's number a property of the PLACE
        instead of the policy -- spread across regions fell from 5.81x to 2.55x -- but a player
        does not stand and pirouette. MEASURED: 13,130,226 mean over the same 16 regions.
      * WALKING costs more than either, because it is the only one where new geometry keeps
        ENTERING the frame: you cross sector boundaries and the visplane set turns over, things
        come into sprite range, doors animate. The success metric's own steered routes measure
        16,629,651 mean / 21,862,375 p80 on this binary -- but all ten start at the baked player
        start and together cover ~1.6% of the level, so they describe the spawn's neighbourhood.

    So: take the metric's own walking policy and run it from SIXTEEN places spread across the map
    instead of one. That is what a player does, measured where a player goes.

    ⚠ A PROXY PREDICTED THE SPIN WOULD COST ~20M AND THE BINARY SAID 13.1M -- wrong by 53%. Which
    is why this policy's number is measured on the binary and nothing here is inferred from a model.
    """
    st2, keys = GS._steer(rm, scene, st, GS._waypoints(rm, scene, st, goal) or [], n, boxes, in_box)
    # a leg that ends early must not leave the player standing: a stationary frame is a cheap frame
    # counted as play, which is the failure mode of every generation of this harness so far.
    while len(keys) < n:
        kd = {"forward": True}
        nxt = rm.step_sim(st2, kd, scene=scene)
        if abs(nxt.x - st2.x) + abs(nxt.y - st2.y) >= UNIT:
            st2 = nxt
        else:
            kd = {"turn_left": True}
            st2 = rm.step_sim(st2, kd, scene=scene)
        keys.append(kd)
    return st2, keys[:n]


def regions(wad=GS.DEFAULT_WAD, mapname=GS.DEFAULT_MAP, n=8, play="walk"):
    """`n` regions that are genuinely `n` DIFFERENT runs.

    ⚠ TWO FAULTS MADE 16 REGIONS INTO 12, AND BOTH WERE MINE. The destinations were fine --
    farthest-point sampling gave 16 distinct points, verified. What collapsed them:

      1. THE TRAVEL CAP. Seven runs hit TRAVEL_CAP and never arrived. Regions aiming at
         (1928,1160) and (1944,568) -- a thousand units apart -- both ran out of frames at
         (1666,931); three more aiming at (-24,2216), (-360,1288) and (328,1624) all stopped at
         (144,1321). A cap truncates different journeys at the same point on a shared corridor.
      2. INDEX PARITY IN THE PLAY POLICY. Two runs stranded in the same spot with the same index
         parity turned the same way and emitted byte-identical keys.

    Duplicates are not free: they weight whichever end of the distribution they land on, and these
    landed on both ends. Deduplicating moved the mean 12,492,543 -> 12,848,952 (2.8%).

    THE FIX IS TO DEDUPE ON WHERE THE RUN ENDS, not on where it was aimed -- robust whatever the
    cap is, where raising the cap would only push the collision further out. A destination whose
    travel lands somewhere already priced is skipped and the next one tried, and the scripts are
    asserted pairwise distinct before anything is measured."""
    # spares, because rejected destinations have to be replaced
    if GS.TOUR_TARGETS < n * 3:
        GS.TOUR_TARGETS = n * 3
        GS._TOUR.clear()                     # the plan is cached; force it to rebuild with spares
    rm, _scene, sp = GS._oracle(wad, mapname)
    open_scene, targets, boxes, in_box = GS._tour_plan(wad, mapname)
    sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16

    out, seen_pos, seen_sig, skipped = [], set(), set(), []
    for goal in targets:
        if len(out) >= n:
            break
        wps = GS._waypoints(rm, open_scene, sp, goal)
        st, travel = (sp, []) if not wps else GS._steer(
            rm, open_scene, sp, wps, TRAVEL_CAP, boxes, in_box)
        x, y = _signed(st.x, 32) >> 16, _signed(st.y, 32) >> 16
        if (x, y) in seen_pos:
            skipped.append("(%d,%d) already priced -- travel capped short of %s" % (x, y, goal))
            continue
        if play == "spin":
            _st2, keys = _spin(rm, open_scene, st, SPIN)
        elif play == "wander":
            _st2, keys = _local_play(rm, open_scene, st, PLAY, len(out))
        else:
            # walk on TOWARD somewhere else -- a player passing through, not arriving and stopping
            onward = targets[(targets.index(goal) + len(targets) // 2) % len(targets)]
            _st2, keys = _walk(rm, open_scene, st, PLAY, onward, boxes, in_box)
        play_keys = keys
        sig = repr(travel) + "|" + repr(play_keys)
        if sig in seen_sig:
            skipped.append("(%d,%d) identical script to an earlier region" % (x, y))
            continue
        seen_pos.add((x, y))
        seen_sig.add(sig)
        dist = int(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5)
        out.append(("region %d (%d,%d) %d from spawn" % (len(out), x, y, dist),
                    travel, play_keys, dist))

    # C5: the guarantee, checked rather than hoped for
    sigs = {repr(t) + "|" + repr(p) for _l, t, p, _d in out}
    assert len(sigs) == len(out), (
        "only %d of %d regions are distinct runs -- a duplicate is one sample counted twice"
        % (len(sigs), len(out)))
    ends = {l.split("(")[1].split(")")[0] for l, _t, _p, _d in out}
    assert len(ends) == len(out), "two regions are priced at the same position"
    if len(out) < n:
        print("  NOTE: %d of %d regions available; %d destination(s) rejected as duplicates:"
              % (len(out), n, len(skipped)), flush=True)
        for sk in skipped[:6]:
            print("        %s" % sk, flush=True)
    return out


def _ops(fjm, per_frame):
    full = [{} for _ in range(gate.MENU_FRAMES)] + list(per_frame)
    frames, ops = gate.run_fj(fjm, GS.events_for(full), len(full))
    assert len(frames) == len(full), (
        "C2 short run: %d of %d frames presented" % (len(frames), len(full)))
    return ops


def sweep(fjm, n=8, play="walk"):
    rows = []
    # ⚠ flush, and SAY WHAT THE SILENCE IS. `regions()` plans first -- a breadth-first search per
    # candidate destination, and with spares for rejected duplicates that is up to 3n searches over
    # 12,576 cells. Several quiet minutes before the first region prices is normal; a tool that
    # does not say so is indistinguishable from a hung one.
    print("pricing %d regions on %s -- play=%s, two runs each (travel, travel+play)"
          % (n, fjm, play), flush=True)
    print("  planning routes (a BFS per candidate destination) -- no output until region 0 prices",
          flush=True)
    for label, travel, play_keys, dist in regions(n=n, play=play):
        both = list(travel) + list(play_keys)
        assert both[:len(travel)] == list(travel), "C1 run B is not a prefix-extension of run A"
        a = _ops(fjm, travel)
        b = _ops(fjm, both)
        assert b > a, "C4 travel+play cost no more than travel alone"
        per = (b - a) / float(len(play_keys))
        rows.append((label, dist, len(travel), per))
        # ⚠ flush=True IS NOT DECORATION. Python buffers stdout when it is redirected to a file,
        # so a 40-minute sweep printed NOTHING until it exited -- indistinguishable from a hang,
        # and it prompted exactly that question. A long tool must report progress as it makes it.
        print("  %-44s travel %3d frames   %s ops/frame"
              % (label, len(travel), format(int(per), ",")), flush=True)
    print("")
    vals = sorted(r[3] for r in rows)
    lo, hi = vals[0], vals[-1]
    mean = sum(vals) / len(vals)
    # ⚠ THE ROLL-UP WAS QUIETLY THE WRONG STATISTIC. This printed a MEAN over regions and that mean
    # is what became "13.3M". The success criterion is the 80th-PERCENTILE run's average, so the
    # level-wide analogue is the 80th-percentile REGION, not the average one. Both are printed now;
    # the percentile uses the same floor-index convention gamespeed does, so the two cannot drift.
    p80 = vals[int(0.8 * (len(vals) - 1))]
    print("CHEAPEST region  : %s ops/frame" % format(int(lo), ","))
    print("DEAREST  region  : %s ops/frame" % format(int(hi), ","))
    print("SPREAD           : %.2fx  (a single-region number can be this far from another)"
          % (hi / lo if lo else 0))
    print("MEAN over regions: %s ops/frame" % format(int(mean), ","))
    print("80th-PCT region  : %s ops/frame   <- the analogue of the success metric"
          % format(int(p80), ","))
    print("BINDING (mean+p80)/2: %s ops/frame" % format(int((mean + p80) / 2), ","))
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
    sigs = {repr(t) + "|" + repr(p) for _l, t, p, _d in rs}
    check("C5 every region is a DIFFERENT run", len(sigs) == len(rs),
          "%d distinct of %d" % (len(sigs), len(rs)))
    ends = {l.split("(")[1].split(")")[0] for l, _t, _p, _d in rs}
    check("C5 ...and no two are priced at the same position", len(ends) == len(rs),
          "%d positions of %d" % (len(ends), len(rs)))
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
    ap.add_argument("--play", choices=("walk", "spin", "wander"), default="walk",
                    help="walk = a player going somewhere (what play costs); spin = every heading from a standstill (an upper bound on a STANDING player); wander = the retired wall-hugging policy, kept to reproduce old numbers")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else (sweep(a.fjm, a.regions, a.play) and 0))
