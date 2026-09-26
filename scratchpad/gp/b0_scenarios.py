"""b0_scenarios.py -- B0 of the combat scenario set (v2): blocked27 in TIC mode from each checkpoint.

    python scratchpad/gp/b0_scenarios.py [--file scratchpad/gp/scenarios/combat_scenarios_v2.json]
                                         [--pixel-every N] [--json OUT] [--proxy]
    python scratchpad/gp/b0_scenarios.py --selftest

WHAT IT RUNS. For each run of the set: the menu's 2 frames and enter, exactly as gamespeed composes
them, then the run's 100 game frames. The run is first REPLAYED on the model (scenarios_v2), which
must reproduce the file's frozen poses; that gives every frame's model pose before and after the
tic and the model's doors before it. At every game frame's start the probe (probe.py) writes:
  * THE POSE FROM WHICH blocked27's OWN TIC LANDS WHERE THE MODEL DID (`scenarios_v2.b0_injection`):
    the pre-tic angle, and the model's landing minus blocked27's forward/back step (the landing
    itself when the frame has no forward/back key). With no strafe and nothing in the way this is
    the model's pre-tic pose (v1's injection); it also absorbs strafe (blocked27 has none) and a
    step a solid thing refused (blocked27 walks through things);
  * THE MODEL'S DOORS before the tic, all four cells per door (state, dir, sub, wait): a door a
    monster opened in the model opens in blocked27 one frame later instead of never.
The frame's forward/back/turn/use keys arrive as real key events. Strafe, fire and the weapon keys
are not delivered: blocked27 reads none of them (its input discards other keycodes).

WHAT IT CHECKS, every frame. The expectation is `scenarios_v2.BinaryMirror` stepping the injected
pose and doors with the delivered keys (blocked27's rules: no strafe, no things, no key checks).
The binary's pose and door states at every present must equal it (state-exact) and its picture
must equal the game oracle's render of it (byte-exact on every --pixel-every'th frame and on every
frame the expectation parts from the model). A frame whose expectation parts from the model
(camera: the model's pose; doors: the model's door states) is COUNTED.

STRAFE. On a STRAFE-ONLY frame (strafe, no forward/back) blocked27 runs no collision tic: it does
not move. The frame is drawn from the model's landing, but the collision the gameplay binary will
run there is missing -- B0 UNDERCOUNTS those frames. `--proxy` measures the size: a second pass
gives every strafe-only frame a FORWARD step into the same landing (so blocked27 runs its collision
tic and lands on the same pose, drawing the same picture) and reports the exact difference.

WHAT B0 MEASURES: blocked27's cost of drawing the set's camera path frame by frame, with its own
door tic, player tic and collision (not on strafe-only frames), in ITS world: monsters at their
spawns in their spawn frames, every pickup present, no fireballs, corpses or effects. Per run,
(total - startup - menu) / 100 exactly; the binding statistic is gamespeed's (mean + p80) / 2 over
the runs; the per-frame maximum is the largest probe reading (+/- 2^18, probe.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import probe as P                                                            # noqa: E402
import scenarios_v2 as S                                                     # noqa: E402

ROOT = P.ROOT
M32 = 0xFFFFFFFF
DRIVER = "scratchpad/gp/b0_scenarios.py"


class GameOracle(P.Oracle):
    """probe.Oracle with the GAME tier's picture keywords: `sky` (V2) and the `bbox_cull` wedge cull
    are retired into the default build, so the oracle draws them too -- deg_gate's set. MEASURED
    2026-09-26 (S4 v1): without `sky` the oracle differs from blocked27 on every frame that shows
    sky; probe.Oracle has had `sky` since a07e8b9, and `bbox_cull` moves no pixel."""
    RENDER_KW = dict(P.Oracle.RENDER_KW)       # = reference_model.GAME_RENDER_KW (PR #87)


def P_signed(v: int) -> int:
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def sha16(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def model_frames(run: dict, proxy: bool = False) -> list:
    """replay one run on the model; per frame: the injection, the delivered keys, the doors written,
    the expectation (the mirror), and the model's own landing and doors. The replay must reproduce
    the file's poses (the set's freeze)."""
    w = S.start_world(run["setup"])
    mirror = S.BinaryMirror(w)
    out = []
    for i, s in enumerate(run["keys"]):
        kd = S.str_to_keys(s)
        ws = w.ws
        pre = (ws.px, ws.py, ws.pangle)
        pre_doors = S.door_tuples(w)
        w.tic(kd)
        post = (ws.px, ws.py, ws.pangle)
        if list(post) != list(run["poses"][i]):
            raise AssertionError("%s frame %d: the model no longer reproduces the set's pose (%s vs "
                                 "%s) -- the model or the file changed" % (run["name"], i, post,
                                                                           run["poses"][i]))
        inj, bkeys = S.b0_injection(w.rm, pre, post, kd, proxy=proxy)
        out.append({"inj": inj, "keys": bkeys, "doors": pre_doors,
                    "exp": mirror.step(inj, bkeys, pre_doors), "post": post,
                    "post_doors": tuple(ws.d_state),
                    "strafe_only": S.has_strafe(kd) and not (kd.get("forward") or kd.get("back"))})
    return out


def drive(gb, table, orc, frames: list, *, pixel_every: int = 5, override=None) -> dict:
    """one run through the binary: inject and deliver per `frames`; check against the expectation
    (`override`: a list of (pose, doors) to check against instead)"""
    import gamespeed as GS
    import m2_std_gate as gate
    mf = gate.MENU_FRAMES
    cells = P.game_cells(orc.ndoors)
    p = P.Probe(cells, table, gb.width)
    per_frame = [{} for _ in range(mf)] + [fr["keys"] for fr in frames]
    events = GS.events_for(per_frame)
    readback = {}

    def start(pr, f):
        if f < mf:
            return
        fr = frames[f - mf]
        vals = {"viewx": fr["inj"][0], "viewy": fr["inj"][1], "viewangle": fr["inj"][2]}
        if fr["doors"] is not None:
            d = fr["doors"]
            vals.update({"dstate": tuple(t[0] for t in d), "ddir": tuple(t[1] for t in d),
                         "dsub": tuple(t[2] for t in d), "dwait": tuple(t[3] for t in d)})
        pr.write_cells(vals)

    def present(pr, f):
        if f >= mf:
            readback[f - mf] = pr.read_cells(["viewx", "viewy", "viewangle", "dstate", "mode"])
    p.on_frame_start(start)
    p.on_present(present)
    r = gb.run(len(per_frame), events, p, pre_run=lambda pr: pr.verify_known(orc.known_pristine()))
    ops_f = p.frame_ops()[mf:mf + len(frames)]
    state_ok, pix_ok, pix_frames = [], [], []
    cam = door = 0
    for f, fr in enumerate(frames):
        epose, edoors = override[f] if override is not None else fr["exp"]
        got = readback.get(f)
        state_ok.append(got is not None and got["mode"] == 0 and (
            got["viewx"], got["viewy"], got["viewangle"], got["dstate"]) == (
            P_signed(epose[0]), P_signed(epose[1]), epose[2] & M32, tuple(edoors)))
        c_part = (P_signed(epose[0]), P_signed(epose[1]), epose[2] & M32) != (
            P_signed(fr["post"][0]), P_signed(fr["post"][1]), fr["post"][2] & M32)
        d_part = fr.get("post_doors") is not None and tuple(edoors) != tuple(fr["post_doors"])
        cam += c_part
        door += d_part
        if f % pixel_every == 0 or c_part or d_part:
            want = orc.render(P_signed(epose[0]), P_signed(epose[1]), epose[2], tuple(edoors))
            pix_ok.append(r.frames[mf + f] == want)
            pix_frames.append(f)
    return {"ops_total": r.ops, "frame_ops": ops_f, "state_ok": state_ok, "pix_ok": pix_ok,
            "pix_frames": pix_frames, "cam_parts": cam, "door_parts": door,
            "presented": len(r.frames), "seconds": r.seconds, "frames": r.frames[mf:]}


def summarize(res, base_ops, n):
    fo = sorted(res["frame_ops"])
    pct = lambda q: fo[min(len(fo) - 1, -(-int(q * 100) * len(fo) // 100) - 1)]   # noqa: E731
    return {"avg_exact": (res["ops_total"] - base_ops) / n, "p50": pct(0.5), "p80": pct(0.8),
            "max": fo[-1]}


def b0(doc_path: Path, fjm: Path, labels: Path, pixel_every: int, out_json, proxy: bool) -> int:
    import gamespeed as GS
    import m2_std_gate as gate
    doc = json.loads(Path(doc_path).read_text(encoding="ascii"))
    t0 = time.time()
    runs = [(run["name"], model_frames(run), model_frames(run, proxy=True) if proxy else None)
            for run in doc["runs"]]
    print("  model replays: %d runs reproduce the set's poses (%.0f s, outside the lock)"
          % (len(runs), time.time() - t0), flush=True)
    orc = GameOracle()
    assert list(orc.door_order) == list(S.new_world().door_order), "door order differs"
    with P.binary_lock("S4v2-b0"):
        table = P.LabelTable.load(labels, {c.label for c in P.game_cells(orc.ndoors).values()})
        gb = P.GameBinary(fjm)
        base = gb.run(gate.MENU_FRAMES).ops           # startup + the menu frames, EXACT
        print("b0_scenarios: %s sha256 %s | set %s (%d runs, keys %s) | startup+menu %s ops (exact)"
              % (fjm.name, gb.sha[:16], Path(doc_path).name, len(runs), S.keys_sha(doc),
                 format(base, ",")), flush=True)
        results = []
        for name, frames, pframes in runs:
            res = drive(gb, table, orc, frames, pixel_every=pixel_every)
            res["name"] = name
            res["strafe_only"] = sum(fr["strafe_only"] for fr in frames)
            if pframes is not None:
                rp = drive(gb, table, orc, pframes, pixel_every=pixel_every)
                res["proxy"] = rp
                res["proxy_same_picture"] = rp["frames"] == res["frames"]
            results.append(res)
    print("  %-20s %12s %11s %11s %11s  %-9s %-9s %3s %3s %4s"
          % ("run", "avg (exact)", "p50 +-2^18", "p80", "max", "state", "pixels", "cam", "dr",
             "sonl"))
    avgs, allf, rows = [], [], []
    for res in results:
        s = summarize(res, base, len(res["frame_ops"]))
        avgs.append(s["avg_exact"])
        allf += [(v, res["name"]) for v in res["frame_ops"]]
        rows.append({"name": res["name"], **s, "state_ok": sum(res["state_ok"]),
                     "state_n": len(res["state_ok"]), "pix_ok": sum(res["pix_ok"]),
                     "pix_n": len(res["pix_ok"]), "cam_parts": res["cam_parts"],
                     "door_parts": res["door_parts"], "strafe_only_frames": res["strafe_only"],
                     "seconds": res["seconds"], "frame_ops": res["frame_ops"]})
        print("  %-20s %12s %11s %11s %11s  %3d/%-5d %3d/%-5d %3d %3d %4d"
              % (res["name"], format(int(round(s["avg_exact"])), ","), format(s["p50"], ","),
                 format(s["p80"], ","), format(s["max"], ","), sum(res["state_ok"]),
                 len(res["state_ok"]), sum(res["pix_ok"]), len(res["pix_ok"]), res["cam_parts"],
                 res["door_parts"], res["strafe_only"]))
    mean, p80 = sum(avgs) / len(avgs), GS.percentile_run(avgs)
    binding = GS.binding_speed(avgs)
    p80_name = next(r["name"] for r in rows if r["avg_exact"] == p80)
    fmax = max(allf)
    print("  B0 BINDING (mean + p80)/2 over %d runs: %s ops/frame   (mean %s, p80 run %s = %s)"
          % (len(avgs), format(int(round(binding)), ","), format(int(round(mean)), ","),
             p80_name, format(int(round(p80)), ",")))
    print("  per-frame maximum: %s ops (+/- 2^18) in %s; run averages %s .. %s; headroom to 22M: %s"
          % (format(fmax[0], ","), fmax[1], format(int(min(avgs)), ","), format(int(max(avgs)), ","),
             format(int(round(22_000_000 - binding)), ",")))
    under = None
    if proxy:
        pavgs, per = [], {}
        print("  STRAFE UNDERCOUNT (--proxy: each strafe-only frame given a forward step into the "
              "same landing):")
        for res in results:
            rp = res["proxy"]
            d = rp["ops_total"] - res["ops_total"]
            pavgs.append((rp["ops_total"] - base) / len(rp["frame_ops"]))
            per[res["name"]] = {"delta_total": d, "strafe_only_frames": res["strafe_only"],
                                "per_strafe_only_frame": d / res["strafe_only"] if res["strafe_only"] else None,
                                "state_ok": sum(rp["state_ok"]), "same_picture": res["proxy_same_picture"],
                                "avg_exact_proxy": pavgs[-1]}
            print("    %-20s +%s ops over %d strafe-only frames = %s per frame; state %d/%d; "
                  "picture identical: %s"
                  % (res["name"], format(d, ","), res["strafe_only"],
                     format(int(round(d / res["strafe_only"])), ",") if res["strafe_only"] else "-",
                     sum(rp["state_ok"]), len(rp["state_ok"]), res["proxy_same_picture"]))
        pb = GS.binding_speed(pavgs)
        tot_d = sum(v["delta_total"] for v in per.values())
        tot_n = sum(v["strafe_only_frames"] for v in per.values())
        print("    binding with the collision tic on strafe-only frames: %s (B0 + %s); %s ops per "
              "strafe-only frame over %d frames"
              % (format(int(round(pb)), ","), format(int(round(pb - binding)), ","),
                 format(int(round(tot_d / tot_n)), ",") if tot_n else "-", tot_n))
        under = {"binding_proxy": pb, "mean_proxy": sum(pavgs) / len(pavgs),
                 "p80_proxy": GS.percentile_run(pavgs), "delta_binding": pb - binding,
                 "strafe_only_frames": tot_n, "delta_total": tot_d,
                 "per_strafe_only_frame": tot_d / tot_n if tot_n else None, "per_run": per,
                 "method": "each strafe-only frame injected one FORWARD step behind the model's "
                           "landing with forward delivered: blocked27 runs its collision tic into "
                           "the same pose (same picture); the difference is exact"}
    bad = [r["name"] for r in results
           if not (all(r["state_ok"]) and all(r["pix_ok"]) and r["presented"] == len(r["state_ok"]) + 2)]
    if proxy:
        bad += [r["name"] + "(proxy)" for r in results
                if not (all(r["proxy"]["state_ok"]) and r["proxy_same_picture"])]
    if out_json:
        cmd = "python scratchpad/gp/b0_scenarios.py --file %s --pixel-every %d%s --json %s" % (
            Path(doc_path).as_posix(), pixel_every, " --proxy" if proxy else "", Path(out_json).as_posix())
        Path(out_json).write_text(json.dumps({
            "fjm": str(fjm), "sha256": gb.sha, "labels": str(labels),
            "labels_sha256": hashlib.sha256(Path(labels).read_bytes()).hexdigest(),
            "set": str(doc_path), "keys_sha": S.keys_sha(doc), "driver_sha16": sha16(HERE / "b0_scenarios.py"),
            "command": cmd, "base_ops": base, "binding": binding, "mean": mean, "p80_run": p80,
            "p80_run_name": p80_name, "frame_max": fmax[0], "frame_max_run": fmax[1],
            "runs": rows, "strafe_undercount": under}, indent=1), encoding="ascii")
    if bad:
        print("  !! state or pixel mismatches in %s -- these numbers describe a wrong run" % bad)
    print("B0 %s" % ("OK" if not bad else "FAIL"))
    return 1 if bad else 0


def selftest(fjm: Path, labels: Path, doc_path: Path) -> int:
    """R9 for the driver: its composition IS gamespeed's (a recorded run reproduces to the op, with
    every door written each frame), its state and pixel checks have teeth, a door write takes
    effect, and the strafe proxy changes the ops and not the picture."""
    import m2_std_gate as gate
    import onewalk
    import b0 as B
    fails = []

    def check(name, cond, detail=""):
        print("  %-78s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    w = S.new_world()
    mirror = S.BinaryMirror(w)
    # T1: gamespeed run 0 as frames: DoorSim's pre-tic pose and doors injected, its keys delivered
    import gamespeed as GS
    keys = GS.script(B.RECORDED_TIC_RUN)
    dsim = onewalk.DoorSim()
    st = dsim.reset()
    frames = []
    for kd in keys:
        pre = (st.x, st.y, st.angle)
        pre_doors = [tuple(dsim.ds[si]) for si in dsim.order]
        st = dsim.step(st, kd)
        bk = S.b0_keys(kd)
        frames.append({"inj": pre, "keys": bk, "doors": pre_doors,
                       "exp": mirror.step(pre, bk, pre_doors), "post": (st.x, st.y, st.angle),
                       "post_doors": tuple(dsim.ds[si][0] for si in dsim.order)})
    doc = json.loads(Path(doc_path).read_text(encoding="ascii"))
    runs = {r["name"]: r for r in doc["runs"]}
    court = model_frames(runs["R0-courtyard"])[:6]
    nw, nwp = model_frames(runs["R0-northwest"])[:30], model_frames(runs["R0-northwest"], proxy=True)[:30]
    orc = GameOracle()
    # T5's window: the first frame of the aftermath run (then the west hall's) from which opening a
    # still-shut door changes the picture, and the door
    from doomfj.doors import IDLE, WAIT

    def open_state(ed, only=None):
        return tuple(w.door_nstates[si] - 1 if (only is None or d == only) else ed[d]
                     for d, si in enumerate(w.door_order))
    found = None
    for rname in ("R0-aftermath", "R0-west-hall", "R0-imp-court"):
        frs = model_frames(runs[rname])
        for k in range(2, len(frs) - 6):
            (ex, ey, ea), ed = frs[k]["exp"]
            shut = orc.render(P_signed(ex), P_signed(ey), ea, tuple(ed))
            if orc.render(P_signed(ex), P_signed(ey), ea, open_state(ed)) == shut:
                continue
            door = next((d for d in range(len(ed)) if not ed[d] and orc.render(
                P_signed(ex), P_signed(ey), ea, open_state(ed, d)) != shut), None)
            if door is not None:
                found = (rname, k, door, frs[k - 2:k + 6])
                break
        if found:
            break
    rname, k0, door, aft = found
    si = w.door_order[door]
    opened = []
    for k, fr in enumerate(aft):
        fr2 = dict(fr)
        if k >= 2:
            ds = [tuple(t) for t in fr["doors"]]
            ds[door] = (w.door_nstates[si] - 1, IDLE, 0, WAIT)
            fr2["doors"] = ds
            fr2["exp"] = mirror.step(fr["inj"], fr["keys"], ds)
            fr2["post_doors"] = None
        opened.append(fr2)
    with P.binary_lock("S4v2-b0-selftest"):
        table = P.LabelTable.load(labels, {c.label for c in P.game_cells(orc.ndoors).values()})
        gb = P.GameBinary(fjm)
        r1 = drive(gb, table, orc, frames, pixel_every=10)
        check("T1 gamespeed run %d, every door written each frame, reproduces the recorded total"
              % B.RECORDED_TIC_RUN, r1["ops_total"] == B.RECORDED_TIC_OPS,
              "%s vs %s" % (format(r1["ops_total"], ","), format(B.RECORDED_TIC_OPS, ",")))
        check("T1 ... state-exact and byte-exact against the mirror, which never parts from DoorSim",
              all(r1["state_ok"]) and all(r1["pix_ok"]) and r1["cam_parts"] == 0 and r1["door_parts"] == 0,
              "state %d/%d pixels %d/%d parts %d/%d" % (sum(r1["state_ok"]), len(r1["state_ok"]),
                                                        sum(r1["pix_ok"]), len(r1["pix_ok"]),
                                                        r1["cam_parts"], r1["door_parts"]))
        bent = [((p[0], p[1], (p[2] + (640 << 16)) & M32), d) for p, d in (fr["exp"] for fr in frames)]
        r2 = drive(gb, table, orc, frames, pixel_every=50, override=bent)
        check("T2 an expectation one turn off FAILS the state check on every frame",
              not any(r2["state_ok"]), "%d/%d accepted" % (sum(r2["state_ok"]), len(r2["state_ok"])))
        menu = gb.run(gate.MENU_FRAMES).ops
        check("T3 startup + menu measured through this driver = the recorded calibration",
              menu == P.RECORDED_CALIBRATION, "%s" % format(menu, ","))
        good = drive(gb, table, orc, court, pixel_every=1)
        plain = drive(gb, table, P.Oracle(), court, pixel_every=1)
        check("T4 the game oracle passes the courtyard's sky frames, state- and pixel-exact",
              all(good["pix_ok"]) and all(good["state_ok"]), "%d/%d" % (sum(good["pix_ok"]),
                                                                      len(good["pix_ok"])))
        nosky = type("NoSky", (GameOracle,), {"RENDER_KW": dict(GameOracle.RENDER_KW, sky=False)})()
        bad = drive(gb, table, nosky, court, pixel_every=1)
        check("T4 negative: an oracle WITHOUT sky is rejected on the same frames",
              not any(bad["pix_ok"]), "%d/%d accepted (probe.Oracle today: %d/%d)" % (
                  sum(bad["pix_ok"]), len(bad["pix_ok"]), sum(plain["pix_ok"]), len(plain["pix_ok"])))
        base_a = drive(gb, table, orc, aft, pixel_every=1)
        door_a = drive(gb, table, orc, opened, pixel_every=1)
        check("T5 a door written open takes effect: state- and pixel-exact against the mirror",
              all(door_a["state_ok"]) and all(door_a["pix_ok"]),
              "%s frames %d..%d, door %d (sector %d) from frame %d: state %d/%d pixels %d/%d" % (
                  rname, k0 - 2, k0 + 5, door, si, k0, sum(door_a["state_ok"]), len(door_a["state_ok"]), sum(door_a["pix_ok"]),
                  len(door_a["pix_ok"])))
        check("T5 ... the write frame's picture differs from the unwritten run's, the two before it"
              " do not", door_a["frames"][2] != base_a["frames"][2]
              and door_a["frames"][:2] == base_a["frames"][:2] and all(base_a["state_ok"]),
              "%d/%d frames differ" % (sum(door_a["frames"][k] != base_a["frames"][k]
                                          for k in range(len(aft))), len(aft)))
        a = drive(gb, table, orc, nw, pixel_every=1)
        b = drive(gb, table, orc, nwp, pixel_every=1)
        so = sum(fr["strafe_only"] for fr in nw)
        check("T6 the strafe proxy draws the same pictures, state-exact",
              a["frames"] == b["frames"] and all(b["state_ok"]) and all(a["state_ok"]),
              "%d strafe-only frames of %d" % (so, len(nw)))
        check("T6 ... and costs more ops (the collision tic it adds)",
              so > 0 and b["ops_total"] > a["ops_total"],
              "+%s ops" % format(b["ops_total"] - a["ops_total"], ","))
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
    ap.add_argument("--proxy", action="store_true", help="also measure the strafe undercount")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        import gamespeed as GS
        t = time.time()
        GS.script(0)                                     # plan gamespeed's routes outside the lock
        print("  (gamespeed routes planned in %.0f s, outside the lock)" % (time.time() - t))
        return selftest(Path(a.fjm), Path(a.labels), Path(a.file))
    return b0(Path(a.file), Path(a.fjm), Path(a.labels), a.pixel_every,
              Path(a.json) if a.json else None, a.proxy)


if __name__ == "__main__":
    sys.exit(main())
