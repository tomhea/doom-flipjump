"""Runner for the mkprof3 instrumented engines (the game binary; b26 by default). Pins the process
to one logical CPU at HIGH priority, runs the yardstick before and after, drives the scripted
walk (menu frames + PROF3_FRAMES forward frames) and prints ops, net seconds and fj/s.

    PROF3_PYD=<instrumented _fjcore.pyd>  PROF3_CPU=2  PROF3_FRAMES=12  WSBIN=doom_e1m1_b26.fjm
    FJPROF_DUMP_TIME=<out.bin>  python scratchpad/12m/prof3run.py
"""
# runner for the mkprof3 instrumented engines: PROF3_PYD = path to the .pyd, WSBIN = binary name,
# PROF3_FRAMES = forward frames (default 12), PROF3_CPU = logical cpu to pin (default 2; -1 = no pin)
import ctypes, importlib.util, os, sys, time
from pathlib import Path
ROOT = Path(r'C:/Users/tomhe/Documents/doom-flipjump')
for q in (ROOT/'tests', ROOT/'src', ROOT/'scratchpad', ROOT/'scratchpad/12m', ROOT):
    sys.path.insert(0, str(q))
cpu = int(os.environ.get("PROF3_CPU", "2"))
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
    ok_t = k.SetThreadAffinityMask(k.GetCurrentThread(), mask)
    ok_pri = k.SetPriorityClass(k.GetCurrentProcess(), 0x80)
    pin_note = "cpu%d proc=%s thread=%s prio=%s" % (cpu, "ok" if ok_p else "FAIL", "ok" if ok_t else "FAIL", "high" if ok_pri else "FAIL")
PROF = Path(os.environ["PROF3_PYD"])
spec = importlib.util.spec_from_file_location("_fjcore", str(PROF))
pc = importlib.util.module_from_spec(spec); spec.loader.exec_module(pc)
import gamespeed as GS, m2_std_gate as gate
from doomfj.fastrun import FjmRunner
from flipjump.interpreter.io_devices.KeyboardIO import ScriptedKeyEventSource
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from flipjump.interpreter.io_devices.pygame_window import PcIO
from flipjump.utils.exceptions import IOReadOnEOF
def yard():
    r = pc.cpu_calibrate(150000000)
    return float(r["ops"]) / float(r["seconds"])
FJM = ROOT/'build'/os.environ.get('WSBIN','doom_e1m1_b26.fjm')
nf = int(os.environ.get("PROF3_FRAMES", "12"))
per_frame = [{} for _ in range(GS.MENU_FRAMES)] + [{'forward': True} for _ in range(nf)]
events = GS.events_for(per_frame); n = len(per_frame)
y0 = yard()
runner = FjmRunner(FJM)
core = pc.Memory(runner.width, flat_max_words=runner.flat_max_words)
for seg, k_ in runner._segments: core.add_segment(seg, k_)
for start, vals in runner._runs: core.set_words(start, vals)
screen = gate.Recording(); kb = gate.Stopper(ScriptedKeyEventSource(events), screen, n)
io = PcIO(screen, kb); io.attach_memory(NativeDeviceMemory(core, runner.width))
t = time.time()
_c, ops, _e, _l, _p = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
dt = time.time() - t
y1 = yard()
print("PROF3RUN pin=%s cell_bytes=%s frames=%d ops=%s secs=%.2f io_secs=%.2f fjs=%.1fM yard_before=%.2fG yard_after=%.2fG"
      % (pin_note, getattr(core, "cell_bytes", None), len(screen.frames), format(ops, ','), dt, _p,
         ops / (dt - _p) / 1e6, y0 / 1e9, y1 / 1e9), flush=True)
