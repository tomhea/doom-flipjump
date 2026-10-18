"""Rule 1 for every agent and chain: run ONE heavy command at a time on this box.
    python heavy.py NAME [--log FILE] -- cmd arg ...
Waits (polling 60 s) until C:/Users/tomhe/Documents/HEAVY.lock does not exist AND available RAM >= 6 GB (the box idles at ~7.5 of 15.6), then creates
it EXCLUSIVELY (O_EXCL: two waiters cannot both win), runs the command (cwd = the current directory), removes the lock
and exits with the command's return code. The lock file says who holds it and since when; never delete a lock you did
not create. Heavy = any build / assembly, any E1M1-or-bigger emission, emit_baseline, deg_gate, any gate script,
msframe, a tests/fj FILE that takes over ~1 min or a whole tests/fj run."""
import ctypes
import os
import subprocess
import sys
import time

LOCK = r"C:\Users\tomhe\Documents\HEAVY.lock"
MIN_AVAIL_GB = 6.0


class MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def avail_gb():
    m = MEMSTAT()
    m.dwLength = ctypes.sizeof(MEMSTAT)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2 ** 30


def main():
    a = sys.argv[1:]
    name = a.pop(0)
    log = None
    if a and a[0] == "--log":
        a.pop(0)
        log = a.pop(0)
    assert a and a[0] == "--", "usage: heavy.py NAME [--log FILE] -- cmd ..."
    cmd = a[1:]
    said = False
    while True:
        if not os.path.exists(LOCK) and avail_gb() >= MIN_AVAIL_GB:
            try:
                fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            os.write(fd, ("%s pid %d since %s: %s\n" % (name, os.getpid(), time.ctime(), " ".join(cmd)[:300])).encode())
            os.close(fd)
            break
        if not said:
            held = open(LOCK).read().strip() if os.path.exists(LOCK) else "(free, RAM %.1f GB)" % avail_gb()
            print("heavy.py: waiting -- %s" % held, flush=True)
            said = True
        time.sleep(60)
    try:
        if log:
            with open(log, "w") as f:
                rc = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT)
        else:
            rc = subprocess.call(cmd)
    finally:
        os.remove(LOCK)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
