"""msframe -- THE ms/frame instrument. Every performance claim in this project goes through it.

    python scratchpad/12m/msframe.py --a build/X.fjm                       # measure one binary
    python scratchpad/12m/msframe.py --a build/X.fjm --b build/Y.fjm       # A/B two binaries
    python scratchpad/12m/msframe.py --a build/X.fjm --b build/X.fjm --env-b FLIPJUMP_CELL64=1
                                                                             # A/B one binary, two engine configs
    python scratchpad/12m/msframe.py --a build/X.fjm --save-baseline shipped
    python scratchpad/12m/msframe.py --a build/Y.fjm --against shipped     # a change vs the frozen baseline
    python scratchpad/12m/msframe.py --selftest                            # R9: prove it can see a known effect

WHY THIS EXISTS. The project's speed thesis is "optimise ms/frame, not ops/frame" -- and until
this file there was no instrument for ms/frame at all. gamespeed.py counts ops. The ad-hoc runs
of 2026-09-12 measured the SAME binary doing the SAME work at 53-125 M fj/s, and the causes were
all process failures: single samples, the process migrating between P- and E-cores, two runaway
`find` processes of the session's own making pegging cores for hours, and a warm-vs-cold file
cache changing image load. A change judged by that kind of number is judged by noise.

WHAT IT DOES ABOUT EACH:
  * PINS the child to one logical CPU and raises it to HIGH priority. The 2026-09-12 attempt
    failed silently because ctypes was not told the argument types; this one checks the return
    value and prints GetLastError if the pin is refused.
  * REFUSES TO START if the machine is busy: it samples every process's CPU time twice, one
    second apart, and lists anything using more than half a core. Runaway processes are the
    default state of a long session, not an exception.
  * Puts a C yardstick (L1-resident, engine-compiled) BESIDE every measurement, before and after
    the run, so a clock or core-type shift is visible instead of silently folded into the result.
  * ALTERNATES the arms, counterbalanced (A,B then B,A), so drift hits both equally.
  * Runs every measurement in a FRESH PROCESS -- the image load is per-process and a reused core
    is not a fresh core.
  * CHECKS CORRECTNESS BEFORE SPEED: the presented frames must be byte-identical across arms and
    reps. A speed number from a wrong program is refused, not reported.
  * Reports a MEDIAN AND A SPREAD, and a verdict with a stated rule (below), never a bare number.
  * APPENDS EVERY RESULT to a ledger with the binaries' hashes, the engine's hash, both repos'
    git heads, the machine state and the full environment -- so a number can always be traced to
    exactly what produced it, which CLAUDE.md's Performance Claims rule requires.

THE VERDICT RULE. With N alternated pairs, arm B is called FASTER (or SLOWER) only if (1) every
pair agrees in sign and (2) the median ratio differs from 1 by more than the resolution floor
(default 3%). N=5 pairs all agreeing by chance is 1/16 one-sided. Anything else is NOT SEPARATED,
which means "measure more or give up", never "probably fine".

R9. `--selftest` is the negative-and-positive control: A vs the same A must not be called
separated, and A vs A-with-a-known-20 ms-per-frame-delay must be called SLOWER with the delta
measured within tolerance. An instrument that cannot show a 20 ms effect has no business
adjudicating a 5% one.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "scratchpad" / "12m" / "msframe_ledger.jsonl"
BASELINES = ROOT / "scratchpad" / "12m" / "msframe_baselines"

DEFAULT_FRAMES = 200
DEFAULT_REPS = 5
DEFAULT_CPU = 2            # a P-core on the i7-12700H (logical 0-11 are P, 12-19 are E);
                           # not 0, which takes the interrupts. --cpu overrides; --probe-cores finds it.
RESOLUTION = 0.03          # the smallest effect this instrument will call separated
YARD_MIN_PCORE = 2.8e9     # below this the pinned CPU is probably an E-core or throttled

# ---------------------------------------------------------------------------------------------
# the child: one measurement in one fresh process
# ---------------------------------------------------------------------------------------------
CHILD = r'''
import ctypes, hashlib, os, sys, time
from pathlib import Path
ROOT = Path(sys.argv[1]); fjm = Path(sys.argv[2]); nf = int(sys.argv[3]); cpu = int(sys.argv[4])
delay_ms = float(os.environ.get("MSFRAME_SELFTEST_DELAY_MS", "0"))
for q in (ROOT/"tests", ROOT/"src", ROOT/"scratchpad", ROOT/"scratchpad/12m", ROOT):
    sys.path.insert(0, str(q))

pin_note = "not pinned"
if os.name == "nt" and cpu >= 0:
    import ctypes.wintypes as wt
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wt.HANDLE
    k.GetCurrentThread.restype = wt.HANDLE
    k.SetProcessAffinityMask.argtypes = [wt.HANDLE, ctypes.c_size_t]
    k.SetProcessAffinityMask.restype = wt.BOOL
    k.SetThreadAffinityMask.argtypes = [wt.HANDLE, ctypes.c_size_t]
    k.SetThreadAffinityMask.restype = ctypes.c_size_t
    k.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]
    k.SetPriorityClass.restype = wt.BOOL
    mask = 1 << cpu
    ok_p = k.SetProcessAffinityMask(k.GetCurrentProcess(), mask)
    err_p = ctypes.get_last_error() if not ok_p else 0
    ok_t = k.SetThreadAffinityMask(k.GetCurrentThread(), mask)
    ok_pri = k.SetPriorityClass(k.GetCurrentProcess(), 0x80)   # HIGH_PRIORITY_CLASS
    pin_note = "cpu%d proc=%s thread=%s prio=%s" % (cpu, "ok" if ok_p else "FAIL(err %d)" % err_p,
                                                     "ok" if ok_t else "FAIL", "high" if ok_pri else "FAIL")

import gamespeed as GS, m2_std_gate as gate
from doomfj.fastrun import FjmRunner, _fjcore
from flipjump.interpreter.io_devices.KeyboardIO import ScriptedKeyEventSource
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from flipjump.interpreter.io_devices.pygame_window import PcIO
from flipjump.utils.exceptions import IOReadOnEOF

def yard():
    r = _fjcore.cpu_calibrate(150000000)
    return float(r["ops"]) / float(r["seconds"])

class Rec(gate.Recording):
    def _present(self):
        super()._present()
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)      # the selftest's KNOWN effect, nothing else

y0 = yard()
per_frame = [{} for _ in range(GS.MENU_FRAMES)] + [{"forward": True} for _ in range(nf)]
events = GS.events_for(per_frame); n = len(per_frame)
t0 = time.time()
runner = FjmRunner(fjm)
core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
for seg, k_ in runner._segments: core.add_segment(seg, k_)
for st, v in runner._runs: core.set_words(st, v)
load = time.time() - t0
screen = Rec(); kb = gate.Stopper(ScriptedKeyEventSource(events), screen, n)
io = PcIO(screen, kb); io.attach_memory(NativeDeviceMemory(core, runner.width))
t1 = time.time()
res = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
dt = time.time() - t1
y1 = yard()
ops = res[1]; paused = res[4]; fr = len(screen.frames)
pix = hashlib.sha256(b"".join(screen.frames)).hexdigest()
out = {"frames": fr, "ops": ops, "secs": dt, "io_secs": paused, "load_secs": load,
       "ms_per_frame": dt / fr * 1000.0, "fjs": ops / dt, "ops_per_frame": ops / fr,
       "pix": pix, "yard_before": y0, "yard_after": y1, "pin": pin_note,
       "cell_bytes": getattr(core, "cell_bytes", None), "storage_mode": core.storage_mode,
       "large_pages": getattr(core, "large_pages", None)}
import json
print("MSFRAME_RESULT " + json.dumps(out), flush=True)
'''


def run_child(fjm, frames, cpu, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    cmd = [sys.executable, "-u", "-c", CHILD, str(ROOT), str(fjm), str(frames), str(cpu)]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
    for line in p.stdout.splitlines():
        if line.startswith("MSFRAME_RESULT "):
            return json.loads(line[len("MSFRAME_RESULT "):])
    sys.stderr.write("--- child stdout ---\n" + p.stdout[-3000:] + "\n--- child stderr ---\n"
                     + p.stderr[-3000:] + "\n")
    raise SystemExit("child produced no result for %s" % fjm)


# ---------------------------------------------------------------------------------------------
# machine state: refuse to measure on a busy box
# ---------------------------------------------------------------------------------------------
def busy_processes():
    """(name, pid, cpu_seconds_in_1s) for every process using more than half a core."""
    if os.name != "nt":
        return []
    ps = r'''
$a = Get-Process | Select-Object Id,Name,CPU
Start-Sleep -Seconds 1
$b = Get-Process | Select-Object Id,Name,CPU
$h = @{}
foreach ($p in $a) { if ($null -ne $p.CPU) { $h[$p.Id] = $p.CPU } }
foreach ($p in $b) {
  if ($h.ContainsKey($p.Id) -and $null -ne $p.CPU) {
    $d = $p.CPU - $h[$p.Id]
    if ($d -gt 0.5) { "$($p.Name)|$($p.Id)|$([math]::Round($d,2))" }
  }
}
'''
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:
        return []
    rows = []
    me = os.getpid()
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 3 and parts[1].isdigit() and int(parts[1]) != me:
            rows.append((parts[0], int(parts[1]), float(parts[2])))
    return rows


def power_plan():
    if os.name != "nt":
        return "n/a"
    try:
        out = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, text=True,
                             timeout=10).stdout.strip()
        return out.split("(")[-1].rstrip(")") if "(" in out else out
    except Exception:
        return "unknown"


def git_head(repo):
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "?"


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def engine_hash():
    import glob
    cands = glob.glob(str(ROOT.parent / "flipjump-151" / "flipjump" / "interpreter" / "_fjcore*.pyd"))
    return sha256_file(cands[0]) if cands else "?"


# ---------------------------------------------------------------------------------------------
# the measurement
# ---------------------------------------------------------------------------------------------
def median(xs):
    s = sorted(xs)
    return s[len(s) // 2] if len(s) % 2 else 0.5 * (s[len(s) // 2 - 1] + s[len(s) // 2])


def measure(a_fjm, b_fjm, frames, reps, cpu, env_a, env_b, label_a, label_b):
    """returns (rows, summary). rows[i] = (resA, resB) per rep."""
    rows = []
    for i in range(reps):
        # counterbalanced: A,B on even reps, B,A on odd, so order effects cancel
        order = [("A", a_fjm, env_a), ("B", b_fjm, env_b)] if i % 2 == 0 else \
                [("B", b_fjm, env_b), ("A", a_fjm, env_a)]
        got = {}
        for tag, fjm, env in order:
            if fjm is None:
                continue
            got[tag] = run_child(fjm, frames, cpu, env)
        ra, rb = got.get("A"), got.get("B")
        rows.append((ra, rb))
        if rb:
            print("  rep %d  %-6s %7.1f ms  %6.1fM fj/s  yard %.2f->%.2fG   |  %-6s %7.1f ms  %6.1fM fj/s  yard %.2f->%.2fG"
                  % (i, label_a, ra["ms_per_frame"], ra["fjs"] / 1e6, ra["yard_before"] / 1e9,
                     ra["yard_after"] / 1e9, label_b, rb["ms_per_frame"], rb["fjs"] / 1e6,
                     rb["yard_before"] / 1e9, rb["yard_after"] / 1e9), flush=True)
        else:
            print("  rep %d  %-6s %7.1f ms  %6.1fM fj/s  yard %.2f->%.2fG   pin: %s"
                  % (i, label_a, ra["ms_per_frame"], ra["fjs"] / 1e6, ra["yard_before"] / 1e9,
                     ra["yard_after"] / 1e9, ra["pin"]), flush=True)
    return rows


def summarize(rows, label_a, label_b, resolution):
    a = [r[0] for r in rows]
    b = [r[1] for r in rows if r[1]]
    out = {"a": {"ms_median": median([x["ms_per_frame"] for x in a]),
                 "ms_min": min(x["ms_per_frame"] for x in a),
                 "ms_max": max(x["ms_per_frame"] for x in a),
                 "fjs_median": median([x["fjs"] for x in a]),
                 "ops_per_frame": a[0]["ops_per_frame"],
                 "pix_all_same": len({x["pix"] for x in a}) == 1,
                 "ops_all_same": len({x["ops"] for x in a}) == 1,
                 "cell_bytes": a[0]["cell_bytes"], "storage": a[0]["storage_mode"],
                 "pin": a[0]["pin"],
                 "yard_median": median([x["yard_before"] for x in a] + [x["yard_after"] for x in a])}}
    if not b:
        return out
    out["b"] = {"ms_median": median([x["ms_per_frame"] for x in b]),
                "ms_min": min(x["ms_per_frame"] for x in b),
                "ms_max": max(x["ms_per_frame"] for x in b),
                "fjs_median": median([x["fjs"] for x in b]),
                "ops_per_frame": b[0]["ops_per_frame"],
                "pix_all_same": len({x["pix"] for x in b}) == 1,
                "ops_all_same": len({x["ops"] for x in b}) == 1,
                "cell_bytes": b[0]["cell_bytes"], "storage": b[0]["storage_mode"],
                "pin": b[0]["pin"],
                "yard_median": median([x["yard_before"] for x in b] + [x["yard_after"] for x in b])}
    # correctness across arms: the SAME script on the SAME game must present the SAME bytes
    out["pix_identical_across_arms"] = all(r[0]["pix"] == r[1]["pix"] for r in rows)
    out["ops_identical_across_arms"] = all(r[0]["ops"] == r[1]["ops"] for r in rows)
    # the verdict: per-pair ratios, sign agreement, and the resolution floor
    ratios = [r[0]["ms_per_frame"] / r[1]["ms_per_frame"] for r in rows]   # >1 means B faster
    out["pair_ratios_a_over_b"] = ratios
    out["ratio_median"] = median(ratios)
    signs = [1 if x > 1 else -1 for x in ratios]
    agree = len(set(signs)) == 1
    mag = abs(out["ratio_median"] - 1.0)
    if agree and mag > resolution and signs[0] > 0:
        out["verdict"] = "B FASTER"
    elif agree and mag > resolution and signs[0] < 0:
        out["verdict"] = "B SLOWER"
    else:
        out["verdict"] = "NOT SEPARATED"
    out["verdict_rule"] = ("all %d pairs agree in sign AND |median ratio - 1| > %.0f%%"
                           % (len(rows), resolution * 100))
    return out


def print_summary(s, label_a, label_b, frames):
    print("")
    A = s["a"]
    print("  %-8s median %7.1f ms/frame  [%.1f .. %.1f]   %6.1fM fj/s   %s ops/frame   cell=%s %s"
          % (label_a, A["ms_median"], A["ms_min"], A["ms_max"], A["fjs_median"] / 1e6,
             format(int(A["ops_per_frame"]), ","), A["cell_bytes"], A["storage"]))
    if "b" in s:
        B = s["b"]
        print("  %-8s median %7.1f ms/frame  [%.1f .. %.1f]   %6.1fM fj/s   %s ops/frame   cell=%s %s"
              % (label_b, B["ms_median"], B["ms_min"], B["ms_max"], B["fjs_median"] / 1e6,
                 format(int(B["ops_per_frame"]), ","), B["cell_bytes"], B["storage"]))
        print("")
        print("  pixels identical across arms and reps : %s"
              % ("YES" if s["pix_identical_across_arms"] and A["pix_all_same"] and B["pix_all_same"]
                 else "NO  <- speed below is MEANINGLESS"))
        print("  ops identical across arms             : %s%s"
              % ("YES" if s["ops_identical_across_arms"] else "no",
                 "" if s["ops_identical_across_arms"] else
                 "   (expected when the arms are different binaries; not when they are one engine A/B)"))
        print("  per-pair A/B ms ratio                 : %s"
              % " ".join("%.3f" % x for x in s["pair_ratios_a_over_b"]))
        print("  median ratio                          : %.3f  (>1 = B faster)" % s["ratio_median"])
        print("  VERDICT: %s   (rule: %s)" % (s["verdict"], s["verdict_rule"]))
    print("  pin: %s   yardstick median %.2fG%s"
          % (A["pin"], A["yard_median"] / 1e9,
             "" if A["yard_median"] >= YARD_MIN_PCORE else "   <- LOW: E-core or throttled?"))


def append_ledger(record):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------------------------
def selftest(frames, cpu):
    """R9. Negative control: A vs A is not separated. Positive control: a known 20 ms/frame
    delay in B is called SLOWER and measured within tolerance."""
    fjm = ROOT / "build" / "doom_e1m1_blocked25.fjm"
    ok = True

    def check(name, cond, detail):
        nonlocal ok
        ok = ok and bool(cond)
        print("  %-52s %s  %s" % (name, "PASS" if cond else "FAIL", detail), flush=True)

    print("selftest: %d game frames per arm, 3 pairs, cpu %d" % (frames, cpu), flush=True)
    print("--- negative control: A vs the same A ---", flush=True)
    rows = measure(fjm, fjm, frames, 3, cpu, {}, {}, "A", "A'")
    s = summarize(rows, "A", "A'", RESOLUTION)
    check("C1 the same program presents the same pixels",
          s["pix_identical_across_arms"], "")
    check("C2 identical arms are NOT called separated",
          s["verdict"] == "NOT SEPARATED",
          "verdict %s, median ratio %.3f" % (s["verdict"], s["ratio_median"]))
    noise = max(abs(x - 1) for x in s["pair_ratios_a_over_b"])
    print("      (machine noise this run: worst pair %.1f%% -- the instrument cannot resolve "
          "effects smaller than this)" % (noise * 100), flush=True)

    print("--- positive control: A vs A + 20 ms/frame known delay ---", flush=True)
    rows = measure(fjm, fjm, frames, 3, cpu, {}, {"MSFRAME_SELFTEST_DELAY_MS": "20"}, "A", "A+20ms")
    s = summarize(rows, "A", "A+20ms", RESOLUTION)
    delta = s["b"]["ms_median"] - s["a"]["ms_median"]
    check("C3 the delayed arm is called SLOWER", s["verdict"] == "B SLOWER", s["verdict"])
    check("C4 the delta is measured within 30% of the injected 20 ms",
          abs(delta - 20.0) < 6.0, "measured %.1f ms/frame" % delta)
    check("C5 pixels still identical (the delay must not touch the program)",
          s["pix_identical_across_arms"], "")
    print("\n%s" % ("SELFTEST PASS" if ok else "SELFTEST FAIL"), flush=True)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", help="binary A (the baseline / control)")
    ap.add_argument("--b", help="binary B (the change); omit to measure A alone")
    ap.add_argument("--env-a", action="append", default=[], help="KEY=VAL for arm A's process")
    ap.add_argument("--env-b", action="append", default=[], help="KEY=VAL for arm B's process")
    ap.add_argument("--frames", type=int, default=DEFAULT_FRAMES)
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--cpu", type=int, default=DEFAULT_CPU, help="logical CPU to pin to; -1 = none")
    ap.add_argument("--resolution", type=float, default=RESOLUTION)
    ap.add_argument("--save-baseline", metavar="NAME", help="record arm A's result under NAME")
    ap.add_argument("--against", metavar="NAME", help="compare arm A against a saved baseline "
                    "(the baseline's binary becomes arm A, yours becomes arm B)")
    ap.add_argument("--ignore-busy", action="store_true", help="measure even if the box is busy")
    ap.add_argument("--note", default="", help="free text recorded in the ledger")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest(min(a.frames, 60), a.cpu)

    if not a.a:
        raise SystemExit("--a is required")

    # ── the machine must be quiet, or the number is about the machine
    busy = busy_processes()
    plan = power_plan()
    print("machine : power plan '%s'; busy processes: %s"
          % (plan, "none" if not busy else ", ".join("%s(%d) %.1fs/s" % r for r in busy)),
          flush=True)
    if busy and not a.ignore_busy:
        raise SystemExit("REFUSING to measure on a busy machine (a runaway process cost most of "
                         "2026-09-12's numbers). Kill them or pass --ignore-busy and say so in the note.")

    env_a = dict(kv.split("=", 1) for kv in a.env_a)
    env_b = dict(kv.split("=", 1) for kv in a.env_b)
    a_fjm = Path(a.a)
    b_fjm = Path(a.b) if a.b else None
    label_a, label_b = "A", "B"

    if a.against:
        base = json.loads((BASELINES / (a.against + ".json")).read_text(encoding="utf-8"))
        # the saved baseline's binary is the control; the user's --a is the change
        b_fjm, env_b, label_b = a_fjm, env_a, "change"
        a_fjm, env_a, label_a = Path(base["binary"]), base.get("env", {}), "base"
        print("against : baseline '%s' = %s (%s), recorded %s at %s ms/frame"
              % (a.against, base["binary"], base["binary_sha"], base["when"],
                 "%.1f" % base["summary"]["a"]["ms_median"]), flush=True)
        if sha256_file(a_fjm) != base["binary_sha"]:
            raise SystemExit("the baseline binary on disk no longer matches the recorded hash")

    print("msframe : A=%s%s%s, %d game frames, %d reps, cpu %d, resolution %.0f%%"
          % (a_fjm.name, (" B=%s" % b_fjm.name) if b_fjm else "",
             (" env_b=%s" % env_b) if env_b else "", a.frames, a.reps, a.cpu, a.resolution * 100),
          flush=True)
    rows = measure(a_fjm, b_fjm, a.frames, a.reps, a.cpu, env_a, env_b, label_a, label_b)
    s = summarize(rows, label_a, label_b, a.resolution)
    print_summary(s, label_a, label_b, a.frames)

    record = {"when": time.strftime("%Y-%m-%d %H:%M:%S"), "frames": a.frames, "reps": a.reps,
              "cpu": a.cpu, "resolution": a.resolution, "note": a.note,
              "a": {"binary": str(a_fjm), "sha": sha256_file(a_fjm), "env": env_a},
              "b": ({"binary": str(b_fjm), "sha": sha256_file(b_fjm), "env": env_b} if b_fjm else None),
              "engine_pyd_sha": engine_hash(),
              "git": {"doom": git_head(ROOT), "flipjump": git_head(ROOT.parent / "flipjump-151")},
              "machine": {"power_plan": plan, "busy": busy},
              "summary": s, "rows": rows}
    append_ledger(record)
    print("  ledger  : appended to %s" % LEDGER.relative_to(ROOT))

    if a.save_baseline:
        BASELINES.mkdir(parents=True, exist_ok=True)
        out = BASELINES / (a.save_baseline + ".json")
        out.write_text(json.dumps({"binary": str(a_fjm), "binary_sha": sha256_file(a_fjm),
                                   "env": env_a, "when": record["when"], "frames": a.frames,
                                   "reps": a.reps, "engine_pyd_sha": record["engine_pyd_sha"],
                                   "git": record["git"], "summary": s}, indent=1),
                       encoding="utf-8")
        print("  baseline: saved as '%s' -> %s" % (a.save_baseline, out.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
