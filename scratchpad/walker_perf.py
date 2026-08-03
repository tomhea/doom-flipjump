"""Where does the walker's frame wall-time go? restore (set_words) vs the C run loop."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner, _fjcore
from flipjump.interpreter.fjm_run import IOReadOnEOF
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from tests.fj.stream_screen import StreamScreen

print("_fjcore API:", [n for n in dir(_fjcore) if not n.startswith("__")])
print("Memory API:", [n for n in dir(_fjcore.Memory) if not n.startswith("__")])

r = FjmRunner(ROOT / "scratchpad/fjmcache/b_b604d01771039f04.fjm")
print(f"native={r.native}  runs={len(r._runs)}  words={sum(len(v) for _, v in r._runs):,}")

for i in range(3):
    t0 = time.perf_counter()
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for seg_start, seg_len in r._segments:
        core.add_segment(seg_start, seg_len)
    t1 = time.perf_counter()
    for start, vals in r._runs:
        core.set_words(start, vals)
    t2 = time.perf_counter()
    scr = StreamScreen(stdin=b"-435\n223\n0\n")
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    t3 = time.perf_counter()
    print(f"alloc {t1-t0:.3f}s  restore {t2-t1:.3f}s  run {t3-t2:.3f}s  "
          f"ops {ops:,}  fj/s incl. restore {ops/(t3-t0)/1e6:.0f}M  run-only {ops/(t3-t2)/1e6:.0f}M")
