"""b0_scenarios.py -- B0 of the combat scenario set: blocked27 in TIC mode from each checkpoint.

    python scratchpad/gp/b0_scenarios.py [--file scratchpad/gp/scenarios/combat_scenarios_v1.json]
    python scratchpad/gp/b0_scenarios.py --selftest

WHAT IT RUNS. For each run of the set: the menu's 2 frames and enter, exactly as gamespeed composes
them, then the run's 100 game frames. At every game frame's start the probe (scratchpad/gp/
probe.py) writes the MODEL's pre-tic pose -- the checkpoint for the first frame, the model's
previous post-tic pose after that -- and the frame's movement and use keys arrive as real key
events. Fire and the weapon keys are not delivered: blocked27 has no weapons. So every frame runs
blocked27's own door tic, player tic and collision FROM WHERE THE MODEL STOOD, and draws the result.

WHAT IT CHECKS, every frame. The expectation is `scenarios.BinaryMirror`: the static oracle stepping
the same pre-pose and keys (doors without key checks, no things -- blocked27's rules). The binary's
post-tic pose must equal it at every present (state-exact) and its picture must equal the oracle's
render of it (byte-exact on every --pixel-every'th frame and on every frame where the mirror parts
from the model). A frame where the mirror parts from the model's pose (a solid thing refused the
model's step, a monster opened a door in the model) is COUNTED, not failed: B0 measures what
blocked27 does from that pose.

WHAT B0 THEN MEASURES: blocked27's cost of playing the set's frames from the set's poses with the
set's keys -- its real player tic and collision, and the render of the pose it reaches, in ITS world:
monsters at their spawns in their spawn frames, every pickup present, no fireballs, corpses or
effects, doors as its own door machine leaves them. Per run, (total - startup - menu) / 100 exactly;
the binding statistic is gamespeed's (mean + p80) / 2 over the runs; the per-frame maximum is the
largest probe reading (+/- 2^18, probe.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import probe as P                                                            # noqa: E402
import scenarios as S                                                        # noqa: E402

ROOT = P.ROOT


class GameOracle(P.Oracle):
    """probe.Oracle with the GAME tier's picture features: the sky (V2) and the bbox wedge cull are
    retired into the default build (wall_renderer), so the oracle must draw them too -- deg_gate's
    keyword set. MEASURED 2026-09-26: probe.Oracle's m2_std_gate/m3_gate keywords (no `sky`, no
    `bbox_cull`) differ from blocked27 by 1,000-2,600 px on every frame that shows sky (the
    courtyard, the east yard) and by 0 px indoors; with these two keywords, 0 px everywhere."""
    RENDER_KW = dict(P.Oracle.RENDER_KW, sky=True, bbox_cull=True)


def run_inputs(run: dict):
    """(pre-poses, key dicts, model post-poses) of one scenario run"""
    cp = run["checkpoint"]
    keys = [S.str_to_keys(k) for k in run["keys"]]
    posts = [tuple(p) for p in run["poses"]]
    pres = [(cp["x16"], cp["y16"], cp["angle"])] + posts[:-1]
    return pres, keys, posts


def expectations(w, pres, keys):
    """the mirror's post-tic pose and door states per frame (blocked27's rules)"""
    mirror = S.BinaryMirror(w)
    return [mirror.step(pre, kd) for pre, kd in zip(pres, keys)]


def drive(gb, table, orc, w, pres, keys, posts, *, pixel_every=5, exp_override=None):
    """one run through the binary; returns the per-frame record and the exact total"""
    import gamespeed as GS
    import m2_std_gate as gate
    mf = gate.MENU_FRAMES
    cells = P.game_cells(orc.ndoors)
    p = P.Probe(cells, table, gb.width)
    per_frame = [{} for _ in range(mf)] + [{k: v for k, v in kd.items()
                                             if k in ("forward", "back", "turn_left",
                                                      "turn_right", "use")} for kd in keys]
    events = GS.events_for(per_frame)
    readback = {}

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
    exp = exp_override or expectations(w, pres, keys)
    ops_f = p.frame_ops()[mf:mf + len(keys)]
    state_ok, pix_ok, parts = [], [], []
    for f, ((epose, edoors), post) in enumerate(zip(exp, posts)):
        got = readback.get(f)
        ok = got is not None and got["mode"] == 0 and (
            got["viewx"], got["viewy"], got["viewangle"], got["dstate"]) == (
            P_signed(epose[0]), P_signed(epose[1]), epose[2], tuple(edoors))
        state_ok.append(ok)
        part = epose != post
        parts.append(part)
        if f % pixel_every == 0 or part:
            want = orc.render(P_signed(epose[0]), P_signed(epose[1]), epose[2], tuple(edoors))
            pix_ok.append(r.frames[mf + f] == want)
    return {"ops_total": r.ops, "frame_ops": ops_f, "state_ok": state_ok, "pix_ok": pix_ok,
            "parts": sum(parts), "presented": len(r.frames), "seconds": r.seconds}


def P_signed(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def summarize(res, base_ops, n):
    fo = sorted(res["frame_ops"])
    pct = lambda q: fo[min(len(fo) - 1, -(-int(q * 100) * len(fo) // 100) - 1)]   # noqa: E731
    return {"avg_exact": (res["ops_total"] - base_ops) / n, "p50": pct(0.5), "p80": pct(0.8),
            "max": fo[-1]}


def b0(doc_path: Path, fjm: Path, labels: Path, pixel_every: int, out_json: Path | None) -> int:
    import gamespeed as GS
    import m2_std_gate as gate
    doc = json.loads(Path(doc_path).read_text(encoding="ascii"))
    w = S.new_world()                      # static data for the mirror (door boxes, lines)
    runs = [(run["name"],) + run_inputs(run) for run in doc["runs"]]
    with P.binary_lock("S4-b0"):
        orc = GameOracle()
        table = P.LabelTable.load(labels, {c.label for c in P.game_cells(orc.ndoors).values()})
        gb = P.GameBinary(fjm)
        base = gb.run(gate.MENU_FRAMES).ops           # startup + the menu frames, EXACT
        print("b0_scenarios: %s sha256 %s | set %s (%d runs) | startup+menu %s ops (exact)"
              % (fjm.name, gb.sha[:16], Path(doc_path).name, len(runs), format(base, ",")),
              flush=True)
        results = []
        for name, pres, keys, posts in runs:
            res = drive(gb, table, orc, w, pres, keys, posts, pixel_every=pixel_every)
            res["name"] = name
            results.append(res)
    print("  %-22s %13s %12s %12s %12s  %-11s %-11s %s"
          % ("run", "avg (exact)", "p50 +/-2^18", "p80", "max", "state", "pixels", "parted"))
    avgs, allf = [], []
    for res in results:
        s = summarize(res, base, len(res["frame_ops"]))
        avgs.append(s["avg_exact"])
        allf += res["frame_ops"]
        print("  %-22s %13s %12s %12s %12s  %4d/%-6d %4d/%-6d %d"
              % (res["name"], format(int(round(s["avg_exact"])), ","), format(s["p50"], ","),
                 format(s["p80"], ","), format(s["max"], ","), sum(res["state_ok"]),
                 len(res["state_ok"]), sum(res["pix_ok"]), len(res["pix_ok"]), res["parts"]))
    mean, p80 = sum(avgs) / len(avgs), GS.percentile_run(avgs)
    binding = GS.binding_speed(avgs)
    print("  B0 BINDING (mean + p80)/2 over %d runs: %s ops/frame   (mean %s, p80 run %s)"
          % (len(avgs), format(int(round(binding)), ","), format(int(round(mean)), ","),
             format(int(round(p80)), ",")))
    print("  per-frame maximum over the set: %s ops (+/- 2^18); spread of run averages %s .. %s"
          % (format(max(allf), ","), format(int(min(avgs)), ","), format(int(max(avgs)), ",")))
    print("  headroom to the 22,000,000 cap on this binding: %s ops/frame"
          % format(int(round(22_000_000 - binding)), ","))
    bad = [r["name"] for r in results if not (all(r["state_ok"]) and all(r["pix_ok"])
                                                 and r["presented"] == len(r["state_ok"]) + 2)]
    if out_json:
        Path(out_json).write_text(json.dumps({
            "fjm": str(fjm), "sha256": gb.sha, "set": str(doc_path), "base_ops": base,
            "binding": binding, "mean": mean, "p80_run": p80, "frame_max": max(allf),
            "runs": [{**{k: v for k, v in r.items() if k != "frame_ops"},
                      "avg_exact": (r["ops_total"] - base) / len(r["frame_ops"]),
                      "frame_ops": r["frame_ops"]} for r in results]}, indent=1), encoding="ascii")
    if bad:
        print("  !! state or pixel mismatches in %s -- these numbers describe a wrong run" % bad)
    print("B0 %s" % ("OK" if not bad else "FAIL"))
    return 1 if bad else 0


def selftest(fjm: Path, labels: Path) -> int:
    """R9: the driver's composition IS gamespeed's (a recorded run reproduces to the op), and its
    state check has teeth (an expectation off by one turn fails every frame)."""
    import m2_std_gate as gate
    import b0 as B
    fails = []

    def check(name, cond, detail=""):
        print("  %-72s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    w = S.new_world()
    # a gamespeed run as a scenario: the spawn as the checkpoint, DoorSim's poses as the "model"
    gpose = B.gamespeed_poses(B.RECORDED_TIC_RUN)
    cp = (w.ws.px, w.ws.py, w.ws.pangle)
    keys = [dict(pz["keys"]) for pz in gpose]
    posts = [(pz["x"], pz["y"], pz["angle"]) for pz in gpose]
    pres = [cp] + posts[:-1]
    with P.binary_lock("S4-b0-selftest"):
        orc = GameOracle()
        table = P.LabelTable.load(labels, {c.label for c in P.game_cells(orc.ndoors).values()})
        gb = P.GameBinary(fjm)
        r1 = drive(gb, table, orc, w, pres, keys, posts, pixel_every=10)
        check("T1 gamespeed run %d as a scenario reproduces the recorded total, to the op"
              % B.RECORDED_TIC_RUN, r1["ops_total"] == B.RECORDED_TIC_OPS,
              "%s vs %s" % (format(r1["ops_total"], ","), format(B.RECORDED_TIC_OPS, ",")))
        check("T1 ... state-exact and byte-exact against the mirror at every checked frame",
              all(r1["state_ok"]) and all(r1["pix_ok"]),
              "state %d/%d pixels %d/%d" % (sum(r1["state_ok"]), len(r1["state_ok"]),
                                            sum(r1["pix_ok"]), len(r1["pix_ok"])))
        check("T1 ... and the mirror never parts from DoorSim's poses (the same rules)",
              r1["parts"] == 0, "%d" % r1["parts"])
        exp = expectations(w, pres, keys)
        bent = [(((p[0], p[1], (p[2] + (640 << 16)) & 0xFFFFFFFF)), d) for p, d in exp]
        r2 = drive(gb, table, orc, w, pres, keys, posts, pixel_every=50, exp_override=bent)
        check("T2 an expectation one turn off FAILS the state check on every frame",
              not any(r2["state_ok"]), "%d/%d accepted" % (sum(r2["state_ok"]), len(r2["state_ok"])))
        menu = gb.run(gate.MENU_FRAMES).ops
        check("T3 startup + menu measured through this driver = the recorded calibration",
              menu == P.RECORDED_CALIBRATION, "%s" % format(menu, ","))
        # T4 the PIXEL check has teeth: the courtyard run's first frames show sky; the oracle
        # without the game tier's sky/bbox keywords must be rejected there, the game oracle not
        doc = json.loads(S.SCEN_FILE.read_text(encoding="ascii"))
        run = next(r for r in doc["runs"] if r["name"] == "R0-courtyard")
        pres4, keys4, posts4 = run_inputs(run)
        pres4, keys4, posts4 = pres4[:6], keys4[:6], posts4[:6]
        good = drive(gb, table, orc, w, pres4, keys4, posts4, pixel_every=1)
        plain = drive(gb, table, P.Oracle(), w, pres4, keys4, posts4, pixel_every=1)
        check("T4 the game oracle passes the courtyard's sky frames, pixel for pixel",
              all(good["pix_ok"]) and all(good["state_ok"]), "%d/%d" % (sum(good["pix_ok"]),
                                                                      len(good["pix_ok"])))
        check("T4 negative: the oracle WITHOUT sky/bbox_cull is rejected on the same frames",
              not any(plain["pix_ok"]), "%d/%d accepted" % (sum(plain["pix_ok"]),
                                                            len(plain["pix_ok"])))
    print("")
    print("B0_SCENARIOS SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                                          "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", default=str(S.SCEN_FILE))
    ap.add_argument("--fjm", default=str(P.DEFAULT_FJM))
    ap.add_argument("--labels", default=str(P.DEFAULT_LABELS))
    ap.add_argument("--pixel-every", type=int, default=5)
    ap.add_argument("--json", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        import gamespeed as GS
        t = time.time()
        GS.script(0)                                     # plan gamespeed's routes outside the lock
        print("  (gamespeed routes planned in %.0f s, outside the lock)" % (time.time() - t))
        return selftest(Path(a.fjm), Path(a.labels))
    return b0(Path(a.file), Path(a.fjm), Path(a.labels), a.pixel_every,
              Path(a.json) if a.json else None)


if __name__ == "__main__":
    sys.exit(main())
