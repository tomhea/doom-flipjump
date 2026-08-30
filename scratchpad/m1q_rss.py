"""Q1 (docs/handoff-complete-game.md §6) — PEAK RSS of the CURRENT shipped E1M1 build.

WHY: `CLAUDE.md` rule 1 ("one heavy build at a time") exists because two concurrent builds died
silently -- exit 255, empty output. The 2026-08-20 assembler work established the cause was MEMORY
EXHAUSTION (129.4 MB of fj source became ~13.6 GB live on a 16.8 GB machine), not an assembler bug,
and cut the live set hard. The rule stands until someone MEASURES the peak of the current build.
This measures it. If 2 x peak + the OS fits comfortably in RAM, the rule can be relaxed to two
concurrent builds and every gate day gets twice as fast.

WHAT IT REPORTS, and why each number is separate:
  * peak RSS during EMISSION (python builds ~129 MB of fj text + the tables), and
  * peak RSS during ASSEMBLE (the phase that used to page), and
  * the overall peak -- which is what two concurrent processes would each hold.
Emission and assembly are separate processes' worth of memory only if you run them separately; the
shipped path runs them in ONE process, so the OVERALL peak is the number that decides the rule.

⚠ WALL CLOCK IS NOT TRUSTED HERE. This machine runs two vmware-vmx VMs and the same code has
measured 758 s and 802 s in consecutive runs. Both wall and process CPU time are printed; compare
runs on CPU.

⚠ NEGATIVE CONTROL (R9). The sampler is the load-bearing tool, so it ships one: `--selftest`
allocates a known ballast (a bytearray of a stated size), touches every page, and requires the
sampler to observe a rise of at least 90% of it. A sampler that reports a flat line because it
samples the wrong process, or too slowly, or reads a field that does not move, would otherwise
produce a reassuring "peak 0.4 GB" and get rule 1 relaxed on a lie. The control also asserts the
sampler REJECTS a too-large claim (it must NOT report a rise big enough for a ballast twice the
size), so it is two-sided.

    python scratchpad/m1q_rss.py --selftest
    python scratchpad/m1q_rss.py
"""
import argparse
import hashlib
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import psutil                                                             # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--selftest", action="store_true")
ap.add_argument("--interval", type=float, default=0.10, help="sampler period, seconds")
ap.add_argument("--ballast-mb", type=int, default=800, help="--selftest ballast size")
args = ap.parse_args()


class Sampler:
    """Peak-RSS sampler for THIS process, with a marked phase boundary.

    `peak` is monotone over the whole life; `mark(name)` snapshots the running peak so a phase's
    contribution can be read off afterwards.
    """

    def __init__(self, interval):
        self.interval = interval
        self.proc = psutil.Process()
        self.peak = 0
        self.marks = []
        self._stop = threading.Event()
        self._th = None
        self.samples = 0

    def _loop(self):
        while not self._stop.is_set():
            rss = self.proc.memory_info().rss
            if rss > self.peak:
                self.peak = rss
            self.samples += 1
            self._stop.wait(self.interval)

    def start(self):
        self.peak = self.proc.memory_info().rss
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()
        return self

    def mark(self, name):
        self.marks.append((name, self.peak, self.proc.memory_info().rss,
                           time.perf_counter(), time.process_time()))

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=2)
        return self.peak


def selftest():
    """R9: the sampler must SEE a known allocation, and must not see one that is not there."""
    ok = True
    n = args.ballast_mb * 1_000_000
    s = Sampler(0.02).start()
    base = s.peak
    time.sleep(0.3)
    ballast = bytearray(n)
    for i in range(0, n, 4096):        # touch every page: bytearray(n) is already zero-filled and
        ballast[i] = 1                 # committed on CPython, but touching makes the RSS explicit
    time.sleep(0.3)
    peak = s.stop()
    rise = peak - base
    del ballast
    print(f"CONTROL 1 (positive): ballast {n/1e9:.3f} GB -> sampler saw a rise of {rise/1e9:.3f} GB "
          f"in {s.samples} samples")
    got = rise >= 0.90 * n
    print(f"  rise >= 90% of the ballast ......... {'ok' if got else 'FAIL -- the sampler is blind'}")
    ok &= got
    # Two-sided: the same observation must NOT support a claim of twice the ballast.
    over = rise >= 0.90 * 2 * n
    print(f"CONTROL 2 (negative): the same rise must NOT support a 2x claim "
          f"({rise/1e9:.3f} GB vs {2*n/1e9:.3f} GB)")
    print(f"  rejects the inflated claim ........ {'ok' if not over else 'FAIL -- it accepts anything'}")
    ok &= not over
    # Third: a sampler that never ran must report no rise (catches a start()/stop() mix-up).
    s2 = Sampler(0.02)
    flat = s2.peak == 0
    print(f"CONTROL 3: an unstarted sampler reports 0 ... {'ok' if flat else 'FAIL'}")
    ok &= flat
    print(f"\n{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if args.selftest:
    sys.exit(selftest())


from doomfj.build import build_wall_renderer                              # noqa: E402

vm = psutil.virtual_memory()
print(f"machine: {vm.total/1e9:.1f} GB RAM, {vm.available/1e9:.1f} GB available at start",
      flush=True)

OUT = ROOT / "scratchpad/fjmcache/_rssprobe.fjm"
GEN = ROOT / "scratchpad/fjmcache/_rssgen"
from doomfj.config import RENDER_FLAT_MAX_WORDS                           # noqa: E402

s = Sampler(args.interval).start()
t0w, t0c = time.perf_counter(), time.process_time()
s.mark("start")
m = build_wall_renderer(ROOT / "tests/fixtures/freedoom_e1m1.wad", "E1M1",
                        out_fjm=OUT, tier="render")
s.mark("done")
peak = s.stop()
dtw, dtc = time.perf_counter() - t0w, time.process_time() - t0c

sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
print(f"\nBUILD: wall {dtw:,.1f}s  CPU {dtc:,.1f}s   (assemble alone, as build.py timed it: "
      f"{m['assemble_seconds']:,.1f}s wall)")
print(f"  fjm {m['fjm_bytes']:,} bytes   sha256 {sha}")
print(f"  span {m['span_words']:,} words   storage {m['storage_mode']}   "
      f"headroom {m['headroom']}")
print(f"\nPEAK RSS: {peak/1e9:.2f} GB  ({s.samples:,} samples @ {args.interval}s)")
print(f"  of {vm.total/1e9:.1f} GB RAM = {100*peak/vm.total:.1f}%")
two = 2 * peak
print(f"  TWO concurrent builds would need ~{two/1e9:.2f} GB = {100*two/vm.total:.1f}% of RAM")
verdict = ("SAFE-LOOKING: two concurrent builds fit with margin" if two < 0.70 * vm.total else
           "MARGINAL: two concurrent builds are over 70% of RAM -- keep rule 1"
           if two < 0.95 * vm.total else
           "UNSAFE: two concurrent builds exceed RAM -- rule 1 STANDS")
print(f"  => {verdict}")
print("\n!! This measures ONE build's peak. It is evidence FOR relaxing rule 1, not a relaxation:\n"
      "   the actual test is two concurrent builds that both produce the right sha256.")
