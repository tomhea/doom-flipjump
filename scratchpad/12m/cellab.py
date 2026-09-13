"""A/B the 4-byte cell against the 8-byte cell on the REAL binary: pixels, ops, and speed.

The engine now stores a w<=32 program's words in 4 bytes instead of 8, which halves the touched
cache footprint -- the cost this whole investigation identified as binding. FLIPJUMP_CELL64=1
forces the old width, so both run from ONE build of ONE binary and the only difference is the
cell.

WHAT IT CHECKS, in this order, because a speed number from a wrong program is worthless:
  * ops must be IDENTICAL -- the cell width changes storage, never semantics.
  * every presented frame's bytes must be IDENTICAL.
  * only then, the time, ALTERNATED across reps, with the C yardstick beside each measurement
    so a clock or load shift is visible rather than silently folded into the result.

Alternation is not ceremony here: the same binary and the same work measured 53-125 M fj/s
earlier today, and the cause turned out to be two runaway `find` processes of this session's own
making. Single samples do not survive that.

    python scratchpad/12m/cellab.py [frames] [reps]
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CHILD = r'''
import hashlib, os, sys, time
from pathlib import Path
ROOT = Path(r"%s")
for q in (ROOT/"tests", ROOT/"src", ROOT/"scratchpad", ROOT/"scratchpad/12m", ROOT):
    sys.path.insert(0, str(q))
import gamespeed as GS, m2_std_gate as gate
from doomfj.fastrun import FjmRunner, _fjcore
from flipjump.interpreter.io_devices.KeyboardIO import ScriptedKeyEventSource
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from flipjump.interpreter.io_devices.pygame_window import PcIO
from flipjump.utils.exceptions import IOReadOnEOF

nf = int(sys.argv[1]); fjm = ROOT/"build"/sys.argv[2]
y = _fjcore.cpu_calibrate(200000000); yard = float(y["ops"])/float(y["seconds"])
per_frame = [{} for _ in range(GS.MENU_FRAMES)] + [{"forward": True} for _ in range(nf)]
events = GS.events_for(per_frame); n = len(per_frame)
runner = FjmRunner(fjm)
core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
for seg, k in runner._segments: core.add_segment(seg, k)
for st, v in runner._runs: core.set_words(st, v)
screen = gate.Recording(); kb = gate.Stopper(ScriptedKeyEventSource(events), screen, n)
io = PcIO(screen, kb); io.attach_memory(NativeDeviceMemory(core, runner.width))
t = time.time()
res = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
dt = time.time()-t
ops = res[1]
h = hashlib.sha256(b"".join(screen.frames)).hexdigest()[:24]
print("RESULT cell=%%s ops=%%d frames=%%d secs=%%.3f fjs=%%.1f yard=%%.2f mem=%%s pix=%%s"
      %% (core.cell_bytes if hasattr(core, "cell_bytes") else "?",
         ops, len(screen.frames), dt, ops/dt/1e6, yard/1e9,
         core.storage_mode, h), flush=True)
''' % (str(ROOT).replace("\\", "/"),)


def run(force64, frames, fjm):
    env = dict(os.environ)
    if force64:
        env["FLIPJUMP_CELL64"] = "1"
    else:
        env.pop("FLIPJUMP_CELL64", None)
    out = subprocess.run([sys.executable, "-u", "-c", CHILD, str(frames), fjm],
                         capture_output=True, text=True, env=env, cwd=str(ROOT))
    for line in out.stdout.splitlines():
        if line.startswith("RESULT"):
            return dict(kv.split("=", 1) for kv in line.split()[1:])
    sys.stderr.write(out.stdout[-2000:] + out.stderr[-2000:])
    raise SystemExit("child produced no RESULT")


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    fjm = sys.argv[3] if len(sys.argv) > 3 else "doom_e1m1_b26.fjm"
    print("A/B on %s, %d game frames, %d alternating reps" % (fjm, frames, reps), flush=True)

    rows = []
    for i in range(reps):
        a = run(False, frames, fjm)      # 4-byte cells (the change)
        b = run(True, frames, fjm)       # 8-byte cells (the control)
        rows.append((a, b))
        print("  rep %d  4B: %8s fj/s  yard %s   |  8B: %8s fj/s  yard %s"
              % (i, a["fjs"], a["yard"], b["fjs"], b["yard"]), flush=True)

    print("")
    ok = True
    for i, (a, b) in enumerate(rows):
        if a["ops"] != b["ops"]:
            print("  !! rep %d OPS DIFFER: 4B=%s 8B=%s" % (i, a["ops"], b["ops"])); ok = False
        if a["pix"] != b["pix"]:
            print("  !! rep %d PIXELS DIFFER: 4B=%s 8B=%s" % (i, a["pix"], b["pix"])); ok = False
    print("ops identical across every rep   : %s" % ("YES" if ok else "NO"))
    print("pixels identical across every rep: %s" % ("YES" if ok else "NO"))
    if not ok:
        raise SystemExit("CORRECTNESS FAILED -- the speed numbers below are meaningless")

    fa = [float(a["fjs"]) for a, _b in rows]
    fb = [float(b["fjs"]) for _a, b in rows]
    print("")
    print("  4-byte cells : %s   median %.1f M fj/s"
          % (" / ".join("%.1f" % x for x in fa), sorted(fa)[len(fa) // 2]))
    print("  8-byte cells : %s   median %.1f M fj/s"
          % (" / ".join("%.1f" % x for x in fb), sorted(fb)[len(fb) // 2]))
    print("  speedup (median): %.2fx" % (sorted(fa)[len(fa) // 2] / sorted(fb)[len(fb) // 2]))
    print("  cell_bytes reported: 4B run -> %s, 8B run -> %s"
          % (rows[0][0].get("cell"), rows[0][1].get("cell")))


if __name__ == "__main__":
    raise SystemExit(main())
