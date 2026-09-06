"""Run ca2_profile once per population pick, so the atlas is built on frames that span the sweep.

frames.py wrote <id>.frames.json with picks evenly spaced in RANK; this runs the per-op profiler
on each of them and leaves <id>.h<pct>.json for atlas.py to join against the label table.

    python scratchpad/12m/profile_picks.py --id BASE

Each profile carries ca2_profile's own three controls (the hook saw every op; the op count matches
the fast engine; the picture is byte-identical under instrumentation). This wrapper REFUSES to
keep a profile whose run did not print PASS -- a histogram from a run that changed the frame is
not a measurement of the frame.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATLAS = Path(__file__).resolve().parent / "atlas"

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True)
ap.add_argument("--bucket-bits", type=int, default=6)
ap.add_argument("--only", type=int, default=0, help="profile only the first N picks")
a = ap.parse_args()

picks = json.load(open(ATLAS / (a.id + ".frames.json")))["picks"]
if a.only:
    picks = picks[:a.only]
fjm = ATLAS / (a.id + ".fjm")
print("%d picks of %s" % (len(picks), fjm), flush=True)

kept, t0 = [], time.perf_counter()
for p in picks:
    tag = ("%.1f" % p["pct"]).replace(".", "_")
    out = ATLAS / ("%s.h%s.json" % (a.id, tag))
    cmd = [sys.executable, str(ROOT / "scratchpad" / "ca2_profile.py"), "--fjm", str(fjm),
           "--vx", str(p["vx"]), "--vy", str(p["vy"]), "--va", str(p["va"]),
           "--bucket-bits", str(a.bucket_bits), "--out", str(out), "--top", "5"]
    print("", flush=True)
    print("p%s rank %d  (%d,%d,%#x)  expect %s ops"
          % (p["pct"], p["rank"], p["vx"], p["vy"], p["va"], format(p["ops"], ",")), flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    tail = [ln for ln in r.stdout.splitlines() if ln.startswith(("CONTROL", "profiled", "ca2_profile"))]
    for ln in tail:
        print("   " + ln, flush=True)
    if r.returncode != 0 or "ca2_profile: PASS" not in r.stdout:
        print("   !! a control failed -- discarding this profile", flush=True)
        print(r.stdout[-1500:], flush=True)
        print(r.stderr[-800:], flush=True)
        out.unlink(missing_ok=True)
        continue
    kept.append(str(out))

print("")
print("kept %d/%d profiles in %.0fs" % (len(kept), len(picks), time.perf_counter() - t0))
for k in kept:
    print("   " + k)
sys.exit(0 if len(kept) == len(picks) else 1)
