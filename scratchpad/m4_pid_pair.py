"""M4 -- THE PID PAIR GATE: narrow must be INERT, wide must be EFFECTIVE, and the picture must
hold over 260 frames rather than 4.

deg_gate's four viewpoints passed a width-4 build that ca2_sweep then failed on three frames
(2 / 292 / 940 px). The failure is intermittent BY CONSTRUCTION -- a too-narrow source register is
read for PID_NIBBLES nibbles and the neighbour is usually zero -- so four viewpoints cannot see it.
**A pid change is proved by the sweep.** This runs both halves against the SAME tree and hands the
two binaries to ca2_sweep, so the pair can never be mismatched by hand.

    python scratchpad/m4_pid_pair.py            # both halves, then the 260-frame sweep
"""
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# ⚠ NOT "/tmp". Python on Windows resolves that to a nonexistent C:\tmp, so `newest_deg` found
# nothing and the run stopped after the narrow half with "binary: None" -- having already spent 25
# minutes. tempfile.gettempdir() is what deg_gate's own mkdtemp uses.
TMP = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir())


def newest_deg(after):
    """deg_gate leaves its .fjm in a fresh mkdtemp; take the one written after `after`."""
    best, bt = None, after
    for p in TMP.glob("*/deg.fjm"):
        t = p.stat().st_mtime
        if t > bt:
            best, bt = p, t
    return best


def run(script, label):
    t0 = time.time()
    print("=== %s: %s" % (label, script), flush=True)
    r = subprocess.run([sys.executable, str(ROOT / "scratchpad" / script)],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "ops" in line or line.startswith(("PASS", "FAIL", "program parts")):
            print("   " + line, flush=True)
    if r.returncode != 0:
        print("   !! %s FAILED (exit %d)" % (label, r.returncode), flush=True)
        print(r.stdout[-2000:]); print(r.stderr[-2000:])
        return None
    b = newest_deg(t0)
    print("   binary: %s" % b, flush=True)
    return b


def main():
    narrow = run("deg_gate.py", "NARROW (PID_NIBBLES=2) -- must be OP-IDENTICAL to the shipped run")
    if narrow is None:
        return 1
    wide = run("m4_pid4_gate.py", "WIDE (PID_NIBBLES=4) -- must be byte-exact with HIGHER ops")
    if wide is None:
        return 1
    print("=== 260-frame sweep on the matched pair ===", flush=True)
    r = subprocess.run([sys.executable, str(ROOT / "scratchpad" / "ca2_sweep.py"),
                        "--a", str(narrow), "--b", str(wide)], capture_output=True, text=True)
    print(r.stdout[-2500:])
    if r.stderr.strip():
        print(r.stderr[-1000:])
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
