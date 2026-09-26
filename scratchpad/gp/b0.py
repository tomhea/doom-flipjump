"""b0.py -- B0 BY INJECTION (docs/plan-gameplay.md sections 1 and 9; stream S2's second deliverable).

    python scratchpad/gp/b0.py --from-gamespeed 0 --every 5 --count 20      # 20 viewpoints of a run
    python scratchpad/gp/b0.py --scenarios scratchpad/gp/scenarios/v1.json  # the frozen set (S4)
    python scratchpad/gp/b0.py --selftest                                    # R9 controls

WHY INJECTION. B0 is blocked27's cost on the combat scenario set, and replaying the combat keys on
blocked27 would diverge at the first lift, key door or monster (plan section 1). So B0 drives the
binary through the scenario's per-frame POSES with scratchpad/gp/probe.py and measures what each
frame costs. Two modes, and they answer different questions:

  view  (the plan's B0) at each frame start: write the frame's pose (x, y, angle), every key up,
        and every door POSED still at the frame's state (dstate, IDLE, no timers -- door_tic leaves
        that unchanged). The tic moves nothing, so the frame draws exactly that pose. It is the
        cost of DRAWING the scenario on blocked27 -- with no player collision, because no key is
        held (the sim skips try_move when pmove is 0).
  tic   at each game frame start: write the PREVIOUS frame's pose and play the frame's keys as
        real key events (the gamespeed composition, menu and enter included). The frame runs the
        real movement and collision tic from that pose. On a trajectory blocked27 itself would
        take, every write is an identity write (probe control C1), so the run IS the real game --
        selftest control B2 requires the recorded gamespeed total to the op.

PER-FRAME OPS are the probe's readings: each within +/-2^18 of the truth (probe.py docstring and
control C4). The RUN AVERAGE is exact: (core.run's total - the exact startup) / frames. The binding
statistic over runs is gamespeed's own (mean + p80) / 2, imported, not re-derived.

SCENARIO FILE (what S4 writes): {"version": ..., "runs": [{"name": ..., "frames": [
    {"x": 16.16 int, "y": ..., "angle": BAM, "doors": [13 door states] (optional),
     "keys": {"forward": true, ...} (tic mode), "pre": [x, y, angle] (tic mode)} ...]}]}
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import probe as P                                                          # noqa: E402

ROOT = P.ROOT


# ------------------------------------------------------------------------------------------------
# poses
# ------------------------------------------------------------------------------------------------

def gamespeed_poses(run: int, n: int = 100) -> list:
    """every frame of gamespeed run `run` as the binary plays it: onewalk.DoorSim steps the oracle
    in m2_std_gate's order (doors tic, then the player), so doors a run opens are opened here too"""
    import gamespeed as GS
    import onewalk
    keys = GS.script(run, n)
    dsim = onewalk.DoorSim()
    st = dsim.reset()
    out = []
    for kd in keys:
        pre = (st.x, st.y, st.angle)
        st = dsim.step(st, kd)
        out.append({"x": st.x, "y": st.y, "angle": st.angle,
                    "doors": [dsim.ds[si][0] for si in dsim.order],
                    "keys": {k: True for k, v in kd.items() if v}, "pre": list(pre)})
    return out


# ------------------------------------------------------------------------------------------------
# the two drivers
# ------------------------------------------------------------------------------------------------

def startup_ops(gb) -> int:
    """EXACT ops from boot to frame 0's first input read (a zero-frame run)"""
    return gb.run(0).ops


def drive_view(gb, table, orc, poses, *, pixels=True, check_every=1, expect=None) -> dict:
    """VIEW mode: frame f draws poses[f] exactly (see the module docstring)"""
    cells = P.game_cells(orc.ndoors)
    p = P.Probe(cells, table, gb.width)
    readback = {}

    def start(pr, f):
        pose = poses[f]
        w = {"viewx": pose["x"], "viewy": pose["y"], "viewangle": pose["angle"], **P.KEYS_UP,
             **orc.door_pose(tuple(pose.get("doors") or ()))}
        if f == 0:
            w["mode"] = 0                  # the world, not the menu: every frame is a game frame
        pr.write_cells(w)

    def present(pr, f):
        readback[f] = pr.read_cells(["viewx", "viewy", "viewangle", "dstate", "mode"])
    p.on_frame_start(start)
    p.on_present(present)
    r = gb.run(len(poses), (), p, pre_run=lambda pr: pr.verify_known(orc.known_pristine()))
    return _collect(gb, orc, poses, r, p, readback, pixels, check_every, expect, mode="view")


def drive_tic(gb, table, orc, poses, *, pixels=True, check_every=1, pre_override=None) -> dict:
    """TIC mode: the menu, enter, then each game frame starts from the previous pose and plays its
    keys as events -- gamespeed's composition with the pose injected"""
    import gamespeed as GS
    import m2_std_gate as gate
    cells = P.game_cells(orc.ndoors)
    p = P.Probe(cells, table, gb.width)
    mf = gate.MENU_FRAMES
    per_frame = [{} for _ in range(mf)] + [dict(pz.get("keys") or {}) for pz in poses]
    events = GS.events_for(per_frame)
    readback = {}
    pres = pre_override or [pz["pre"] for pz in poses]

    def start(pr, f):
        if f >= mf:
            x, y, a = pres[f - mf]
            pr.write_cells({"viewx": x, "viewy": y, "viewangle": a})

    def present(pr, f):
        if f >= mf:
            readback[f - mf] = pr.read_cells(["viewx", "viewy", "viewangle", "dstate", "mode"])
    p.on_frame_start(start)
    p.on_present(present)
    r = gb.run(len(per_frame), events, p, pre_run=lambda pr: pr.verify_known(orc.known_pristine()))
    return _collect(gb, orc, poses, r, p, readback, pixels, check_every, None, mode="tic",
                    skip=mf)


def _collect(gb, orc, poses, r, p, readback, pixels, check_every, expect, mode, skip=0) -> dict:
    n = len(poses)
    ops_f = p.frame_ops()[skip:skip + n]
    state_ok, pix_ok, pix_diff = [], [], []
    for f, pose in enumerate(poses):
        got = readback.get(f)
        doors = tuple(pose.get("doors") or (0,) * orc.ndoors)
        want = (pose["x"], pose["y"], pose["angle"], doors)
        state_ok.append(got is not None and (got["viewx"], got["viewy"], got["viewangle"],
                                             got["dstate"]) == want and got["mode"] == 0)
        if pixels and f % check_every == 0:
            tgt = (expect or poses)[f]
            want_px = orc.render(tgt["x"], tgt["y"], tgt["angle"],
                                 tuple(tgt.get("doors") or ()))
            d = P.px_diff(r.frames[skip + f], want_px)
            pix_ok.append(d == 0)
            pix_diff.append(d)
    return {"mode": mode, "frames": n, "ops_total": r.ops, "frame_ops": ops_f,
            "state_ok": state_ok, "pix_ok": pix_ok, "pix_diff": pix_diff, "seconds": r.seconds,
            "presented": len(r.frames) - skip}


def summarize(res: dict, startup: int, menu_ops: int | None = None) -> dict:
    """the run's EXACT average (total - startup [- menu]) / frames, and its per-frame spread"""
    n = res["frames"]
    base = startup if menu_ops is None else menu_ops
    avg = (res["ops_total"] - base) / n
    fo = sorted(res["frame_ops"])
    pct = lambda q: fo[min(len(fo) - 1, math.ceil(q * len(fo)) - 1)] if fo else 0   # noqa: E731
    return {"avg_exact": avg, "p50": pct(0.5), "p80": pct(0.8), "max": fo[-1] if fo else 0,
            "min": fo[0] if fo else 0}


# ------------------------------------------------------------------------------------------------
# the report
# ------------------------------------------------------------------------------------------------

def report_runs(named_results, startup) -> dict:
    import gamespeed as GS
    avgs = []
    print("  %-14s %6s %13s %12s %12s %12s  %s" % ("run", "frames", "avg (exact)", "p50 +/-2^18",
                                                  "p80", "max", "pixels / state"))
    for name, res in named_results:
        s = summarize(res, startup)
        avgs.append(s["avg_exact"])
        print("  %-14s %6d %13s %12s %12s %12s  %d/%d byte-exact, %d/%d state-exact"
              % (name, res["frames"], format(int(round(s["avg_exact"])), ","),
                 format(s["p50"], ","), format(s["p80"], ","), format(s["max"], ","),
                 sum(res["pix_ok"]), len(res["pix_ok"]), sum(res["state_ok"]),
                 len(res["state_ok"])), flush=True)
    out = {"run_avgs": avgs}
    if len(avgs) > 1:
        out.update(mean=sum(avgs) / len(avgs), p80=GS.percentile_run(avgs),
                   binding=GS.binding_speed(avgs))
        print("  BINDING (mean + p80)/2 over %d runs: %s   (mean %s, p80 run %s)"
              % (len(avgs), format(int(out["binding"]), ","), format(int(out["mean"]), ","),
                 format(int(out["p80"]), ",")))
    return out


# ------------------------------------------------------------------------------------------------
# the controls (R9)
# ------------------------------------------------------------------------------------------------

# gamespeed run 0 as docs/ship-evidence/padB_gamespeed.log recorded it for these bytes: the run that
# opens door 0 at frame ~88, so tic mode is checked with a door moving under it
RECORDED_TIC_RUN, RECORDED_TIC_OPS = 0, 2_100_441_242


def selftest(fjm: Path, labels: Path, run: int, every: int, count: int, planned: dict) -> int:
    fails = []

    def check(name, cond, detail=""):
        print("  %-70s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    orc = P.Oracle()
    table = P.LabelTable.load(labels, {c.label for c in P.game_cells(orc.ndoors).values()})
    gb = P.GameBinary(fjm)
    print("b0 selftest -- %s sha256 %s (loaded %.1f s)" % (fjm.name, gb.sha[:16], gb.load_seconds),
          flush=True)
    poses = planned[run][::every][:count]
    print("  %d viewpoints = gamespeed run %d, frames 0, %d, ..., %d"
          % (len(poses), run, every, every * (len(poses) - 1)), flush=True)
    su = startup_ops(gb)
    print("  startup (boot -> frame 0's first input read): %s ops, EXACT" % format(su, ","))

    # B1 VIEW mode on the viewpoints: every frame draws its pose, byte-exact and state-exact
    rv = drive_view(gb, table, orc, poses)
    check("B1 view: all %d frames byte-exact vs the oracle's render of their pose" % len(poses),
          all(rv["pix_ok"]) and len(rv["pix_ok"]) == len(poses),
          "%d/%d" % (sum(rv["pix_ok"]), len(poses)))
    check("B1 view: the pose read back at every present = the pose injected (nothing moved)",
          all(rv["state_ok"]), "%d/%d" % (sum(rv["state_ok"]), len(poses)))
    check("B1 view: %d frames presented, none lost" % len(poses), rv["presented"] == len(poses))
    # each frame judged against the picture of its pose turned 90 degrees: never the same picture
    wrong = [dict(pz, angle=(pz["angle"] + 0x40000000) & 0xFFFFFFFF) for pz in poses]
    rn = drive_view(gb, table, orc, poses, expect=wrong)
    check("B1 negative: the same frames judged against a 90-degree-turned pose all FAIL",
          not any(rn["pix_ok"]), "%d/%d wrongly accepted" % (sum(rn["pix_ok"]), len(poses)))

    # B2 TIC mode on a whole recorded gamespeed run reproduces the recorded total TO THE OP:
    #    every injected pose is where blocked27 already stands, so every write is an identity
    if gb.sha.startswith(P.RECORDED_SHA16):
        pt = planned[RECORDED_TIC_RUN]
        rt = drive_tic(gb, table, orc, pt, pixels=True, check_every=10)
        check("B2 tic: gamespeed run %d through the injector = the recorded total, to the op"
              % RECORDED_TIC_RUN, rt["ops_total"] == RECORDED_TIC_OPS,
              "%s vs %s" % (format(rt["ops_total"], ","), format(RECORDED_TIC_OPS, ",")))
        check("B2 tic: its poses are state-exact at every present, pixels on every 10th",
              all(rt["state_ok"]) and all(rt["pix_ok"]),
              "state %d/%d, pixels %d/%d" % (sum(rt["state_ok"]), len(pt), sum(rt["pix_ok"]),
                                             len(rt["pix_ok"])))
        off = [pz["pre"] for pz in pt[1:]] + [pt[-1]["pre"]]   # every pre-pose one frame late
        rto = drive_tic(gb, table, orc, pt, pixels=False, pre_override=off)
        check("B2 negative: pre-poses one frame late change the total and fail the state check",
              rto["ops_total"] != RECORDED_TIC_OPS and not all(rto["state_ok"]),
              "%s, state %d/%d" % (format(rto["ops_total"], ","), sum(rto["state_ok"]), len(pt)))
    else:
        check("B2 needs the recorded binary (sha256 %s...)" % P.RECORDED_SHA16, False)

    # B3 EXACT per-viewpoint costs (a fresh image and ONE frame each) against the streaming
    #    readings; and whether a frame's cost depends on the frame before it
    exact = []
    for pose in poses:
        r1 = drive_view(gb, table, orc, [pose], pixels=False)
        exact.append(r1["ops_total"] - su)
    errs = [a - e for a, e in zip(rv["frame_ops"], exact)]
    check("B3 every streaming per-frame reading is within +/-2^18 of the exact one-frame cost",
          all(abs(e) < P.OPS_GRANULARITY for e in errs), "max |diff| %s" % format(
              max(abs(e) for e in errs), ","))
    stream_total = rv["ops_total"] - su
    check("B3 the streaming run's exact total vs the sum of exact one-frame costs",
          True, "streaming %s, sum %s, diff %s (history effects, MEASURED)"
          % (format(stream_total, ","), format(sum(exact), ","),
             format(stream_total - sum(exact), ",")))
    u, v = poses[0], poses[len(poses) // 2]
    c_first = exact[len(poses) // 2]
    c_after_u = drive_view(gb, table, orc, [u, v], pixels=False)["ops_total"] - (exact[0] + su)
    c_after_v = drive_view(gb, table, orc, [v, v], pixels=False)["ops_total"] - (c_first + su)
    print("  B3 cost of one pose: first frame %s, after another pose %s, after itself %s (MEASURED)"
          % (format(c_first, ","), format(c_after_u, ","), format(c_after_v, ",")))

    print("")
    print("  the %d viewpoints (view mode):" % len(poses))
    for i, (pose, fo, ex) in enumerate(zip(poses, rv["frame_ops"], exact)):
        print("   #%-2d frame %3d (%8.1f,%8.1f) %08x doors %s  stream %12s  exact %12s  %s"
              % (i, i * every, pose["x"] / 65536, pose["y"] / 65536, pose["angle"],
                 "".join("%x" % d for d in pose["doors"]), format(fo, ","), format(ex, ","),
                 "BYTE-EXACT" if rv["pix_ok"][i] else "!! %d px" % rv["pix_diff"][i]))
    s = summarize(rv, su)
    print("  view-mode average %s ops/frame EXACT over these %d frames (p80 %s, max %s, +/-2^18)"
          % (format(int(round(s["avg_exact"])), ","), len(poses), format(s["p80"], ","),
             format(s["max"], ",")))
    print("")
    print("B0 SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                                "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fjm", default=str(P.DEFAULT_FJM))
    ap.add_argument("--labels", default=str(P.DEFAULT_LABELS))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--from-gamespeed", type=int, nargs="*", default=None,
                    help="gamespeed run number(s) whose poses to drive")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--scenarios", default=None, help="a scenario JSON (see the docstring)")
    ap.add_argument("--mode", choices=("view", "tic"), default="view")
    ap.add_argument("--no-pixels", action="store_true")
    ap.add_argument("--json", default=None, help="write every per-frame number here")
    ap.add_argument("--stream", default="S2-b0")
    a = ap.parse_args()
    fjm, labels = Path(a.fjm), Path(a.labels)
    # everything that needs no binary happens BEFORE the lock (gamespeed's planner is ~75 s)
    t = time.time()
    if a.selftest:
        run = (a.from_gamespeed or [0])[0]
        planned = {k: gamespeed_poses(k) for k in sorted({run, RECORDED_TIC_RUN})}
        print("  (poses planned and stepped in %.1f s, outside the binary lock)" % (time.time() - t),
              flush=True)
        with P.binary_lock(a.stream):
            return selftest(fjm, labels, run, a.every if a.every > 1 else 5,
                            a.count if a.count != 100 else 20, planned)
    runs = []
    if a.scenarios:
        doc = json.loads(Path(a.scenarios).read_text(encoding="utf-8"))
        runs = [(r.get("name", "run%d" % i), r["frames"]) for i, r in enumerate(doc["runs"])]
    for k in (a.from_gamespeed or []):
        runs.append(("gamespeed%d" % k, gamespeed_poses(k)[::a.every][:a.count]))
    if not runs:
        ap.error("give --from-gamespeed N or --scenarios FILE")
    print("  (poses ready in %.1f s, outside the binary lock)" % (time.time() - t), flush=True)
    with P.binary_lock(a.stream):
        orc = P.Oracle()
        table = P.LabelTable.load(labels, {c.label for c in P.game_cells(orc.ndoors).values()})
        gb = P.GameBinary(fjm)
        su = startup_ops(gb)
        print("b0: %s sha256 %s, mode %s, startup %s ops (exact)"
              % (fjm.name, gb.sha[:16], a.mode, format(su, ",")), flush=True)
        results = []
        for name, poses in runs:
            drive = drive_view if a.mode == "view" else drive_tic
            res = drive(gb, table, orc, poses, pixels=not a.no_pixels)
            results.append((name, res))
        if a.mode == "tic":
            import m2_std_gate as gate
            menu = gb.run(gate.MENU_FRAMES).ops           # startup + menu, EXACT
            su = menu
        rep = report_runs(results, su)
        if a.json:
            Path(a.json).write_text(json.dumps({"fjm": str(fjm), "sha256": gb.sha, "mode": a.mode,
                                                "startup_ops": su, "summary": rep,
                                                "runs": [{"name": n, **r} for n, r in results]},
                                               indent=1), encoding="utf-8")
        bad = [n for n, r in results if not (all(r["pix_ok"]) and all(r["state_ok"]))]
        if bad:
            print("  !! pixel or state mismatches in %s -- the numbers above describe a wrong "
                  "program run" % bad)
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
