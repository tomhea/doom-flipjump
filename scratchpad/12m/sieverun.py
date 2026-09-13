# the engine FLOOR: run the prime sieve (small, L1/L2-resident instruction stream) pinned, on the
# shipped engine (PROF3_PYD unset) or on an instrumented one (PROF3_PYD=path). SIEVE_N = the input.
import ctypes, importlib.util, os, sys, time
from pathlib import Path
ROOT = Path(r'C:/Users/tomhe/Documents/doom-flipjump')
for q in (ROOT/'src', ROOT):
    sys.path.insert(0, str(q))
cpu = int(os.environ.get("PROF3_CPU", "2"))
if os.name == "nt" and cpu >= 0:
    import ctypes.wintypes as wt
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = wt.HANDLE; k.GetCurrentThread.restype = wt.HANDLE
    k.SetProcessAffinityMask.argtypes = [wt.HANDLE, ctypes.c_size_t]; k.SetProcessAffinityMask.restype = wt.BOOL
    k.SetThreadAffinityMask.argtypes = [wt.HANDLE, ctypes.c_size_t]; k.SetThreadAffinityMask.restype = ctypes.c_size_t
    k.SetPriorityClass.argtypes = [wt.HANDLE, wt.DWORD]; k.SetPriorityClass.restype = wt.BOOL
    k.SetProcessAffinityMask(k.GetCurrentProcess(), 1 << cpu); k.SetThreadAffinityMask(k.GetCurrentThread(), 1 << cpu)
    k.SetPriorityClass(k.GetCurrentProcess(), 0x80)
pyd = os.environ.get("PROF3_PYD", "")
if pyd:
    spec = importlib.util.spec_from_file_location("_fjcore", pyd)
    pc = importlib.util.module_from_spec(spec); spec.loader.exec_module(pc)
else:
    from doomfj.fastrun import _fjcore as pc
from doomfj.fastrun import FjmRunner
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.utils.exceptions import IOReadOnEOF
fjm = Path(os.environ["SIEVE_FJM"])
n_in = os.environ.get("SIEVE_N", "300000")
runner = FjmRunner(fjm, flat_max_words=1 << 27)
core = pc.Memory(runner.width, flat_max_words=runner.flat_max_words)
for seg, k_ in runner._segments: core.add_segment(seg, k_)
for start, vals in runner._runs: core.set_words(start, vals)
io = FixedIO((n_in + "\n").encode())
t = time.time()
res = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
dt = time.time() - t
ops = res[1]; paused = res[4]
out = io.get_output(allow_incomplete_output=True)
tail = out[-60:].decode("ascii", "replace").replace("\n", "|")
print("SIEVERUN engine=%s w=%d cell_bytes=%s N=%s ops=%s secs=%.3f io=%.3f fjs=%.1fM out_tail=%r"
      % ("instrumented" if pyd else "shipped", runner.width, getattr(core, "cell_bytes", None), n_in,
         format(ops, ","), dt, paused, ops / (dt - paused) / 1e6, tail), flush=True)
