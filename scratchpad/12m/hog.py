# an L3-thrashing neighbour: stream 96 MB back and forth on one pinned core until killed
import ctypes, ctypes.wintypes as wt, os, sys, time
cpu = int(sys.argv[1]) if len(sys.argv) > 1 else 6
k = ctypes.windll.kernel32
k.GetCurrentProcess.restype = wt.HANDLE; k.GetCurrentThread.restype = wt.HANDLE
k.SetProcessAffinityMask.argtypes = [wt.HANDLE, ctypes.c_size_t]; k.SetThreadAffinityMask.argtypes = [wt.HANDLE, ctypes.c_size_t]
k.SetProcessAffinityMask(k.GetCurrentProcess(), 1 << cpu); k.SetThreadAffinityMask(k.GetCurrentThread(), 1 << cpu)
a = bytearray(96 << 20); b = bytearray(96 << 20)
t_end = time.time() + float(sys.argv[2]) if len(sys.argv) > 2 else 1e18
while time.time() < t_end:
    a[:] = b; b[:] = a
