"""The owner's question (2026-10-13): gamespeed read a mean of 11.6M ops/frame at P9 (blocked54) and 18.2M at P10
(onepass56) -- P10 re-planned the tours, so the two numbers are on DIFFERENT frames. This measures DIFFERENT binaries
on the SAME frames: gamespeed's tours as blocked57 walked them (its own poses, dumped per present by
p11_trail_seen_dump.py), replayed into each binary -- the menu skipped by poke (B0's POKE_LEAD / POKE_ENTER), the
view pose written at every frame start with no key held (so the binary renders exactly that pose), the doors held at
the tour's states, and the player's health held at 100 (no death, no restart). Per run: the EXACT average ops per
game frame ((total - startup) / frames, as b0_scenarios), and p50 / p80 / max of the per-frame readings (+/- 2^18).
--control: the same replay with every frame's pose replaced by the tour's FIRST pose (a frozen camera) -- it must
measure different ops, or the harness is not measuring the poses.
Run in a doom-flipjump checkout (the route dumps: docs/ship-evidence/p11_ops_matrix_routes.json.gz, one JSON each):
PYTHONPATH="src;scratchpad/12m;scratchpad/gp;scratchpad" python scratchpad/gp/p11_pose_replay.py FJM LABELS DUMP.json [...] [--control]"""
import json
import sys
from pathlib import Path

sys.path[:0] = ["scratchpad/12m", "scratchpad/gp", "scratchpad", "src"]
import b0_scenarios as B  # noqa: E402
import m2_std_gate as gate  # noqa: E402
import probe as P  # noqa: E402

args = [a for a in sys.argv[1:] if a != "--control"]
CONTROL = "--control" in sys.argv[1:]
fjm, labels, dumps = args[0], args[1], args[2:]


def pct(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


with P.binary_lock("pose-replay"):
    orc = P.Oracle()
    # only the cells the replay writes: an older binary declares some cells narrower than today's specs (P9's wp_own:
    # 5 weapons, P10's 6), and the probe refuses a spec wider than its label -- these are the same in every binary
    WRITES = {"viewx", "viewy", "viewangle", "p_hp", "ddir", "dreq", "dstate", "dsub", "dwait"} | set(gate.POKE_ENTER)
    specs = {k: c for k, c in B.setup_cell_specs(orc).items() if k in WRITES}
    table = P.LabelTable.load(Path(labels), {c.label for c in specs.values()})
    gb = P.GameBinary(Path(fjm))
    mf = gate.POKE_LEAD
    base = gb.run(mf).ops                         # startup + the lead frames, EXACT
    print("%s: startup + %d lead frames %s ops (exact); %s" % (Path(fjm).name, mf, format(base, ","),
                                                              "CONTROL: a frozen camera" if CONTROL else "the tours' poses"))
    avgs = []
    for dpath in dumps:
        d = json.loads(Path(dpath).read_text(encoding="ascii"))
        frames = [d["per_frame"][str(g)] for g in range(d["frames"])]
        if CONTROL:
            frames = [dict(frames[g], viewx=frames[0]["viewx"], viewy=frames[0]["viewy"],
                           viewangle=frames[0]["viewangle"]) for g in range(len(frames))]
        p = P.Probe(specs, table, gb.width)
        skipped = set()

        def start(pr, f, frames=frames):
            g = f - mf
            if g < 0 or g >= len(frames):
                return
            fr = frames[g]
            vals = {"viewx": fr["viewx"], "viewy": fr["viewy"], "viewangle": fr["viewangle"], "p_hp": 100}
            if f == mf:
                vals.update(gate.POKE_ENTER)
            vals.update(orc.door_pose(tuple(fr["dstate"])))
            skipped.update(k for k in vals if k not in pr.cells)
            pr.write_cells({k: v for k, v in vals.items() if k in pr.cells})
        p.on_frame_start(start)
        per = [{} for _ in range(mf + len(frames))]
        try:
            r = gb.run(len(per), gate.to_events(per), p)
        except Exception as e:                    # e.g. P10's pre-fix window walker: the screen refuses a run
            done = max(0, len(p.frame_ops()) - mf)
            print("  run %s: CRASHED after %d of %d frames -- %s: %s (left out of the averages)"
                  % (d["run"], done, len(frames), type(e).__name__, str(e).splitlines()[0][:120]), flush=True)
            continue
        fo = p.frame_ops()[mf:mf + len(frames)]
        avg = (r.ops - base) / len(frames)
        avgs.append(avg)
        print("  run %s: %d frames, avg %s ops/frame (exact); p50 %s p80 %s max %s; cells not in this binary: %s"
              % (d["run"], len(frames), format(round(avg), ","), format(pct(fo, 0.5), ","), format(pct(fo, 0.8), ","),
                 format(max(fo), ","), sorted(skipped) or "none"), flush=True)
    if not avgs:
        sys.exit("no run completed")
    mean = sum(avgs) / len(avgs)
    p80 = pct(avgs, 0.8)
    print("%s over %d runs: mean of run averages %s, 80th pct %s, (mean+p80)/2 %s ops/frame"
          % (Path(fjm).name, len(avgs), format(round(mean), ","), format(round(p80), ","), format(round((mean + p80) / 2), ",")))
