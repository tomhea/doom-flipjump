"""Rule 1 for every agent and chain: run ONE heavy command at a time on this box.

    python scripts/heavy.py NAME [--prio N] [--build] [--log FILE] -- cmd arg ...
    python scripts/heavy.py NAME --light [--log FILE] -- cmd arg ...

HEAVY (the default): waits until C:/Users/tomhe/Documents/HEAVY.lock does not exist, no LIVE waiter with a HIGHER
--prio is queued (Documents/HEAVY.queue/<prio>_<name>_<pid>; default prio 5; the critical path gets more), and
available RAM >= 6 GB (the box idles at ~7.5 of 15.6); then creates the lock EXCLUSIVELY (O_EXCL: two waiters cannot
both win), runs the command, removes the lock and exits with the command's return code. `--build` marks the lock as a
BUILD (an assembly peaks at ~17 GB here: even light work then risks a silent death of the build).
LIGHT (`--light`): does not take the lock; waits only while a BUILD holds it, then runs. Use it for a host test file
or any python that may take over ~0.5 GB.
Heavy = any build / assembly, any full-map emission or emit_check, emit_baseline, deg_gate, any gate script, msframe,
a tests/fj FILE that runs over ~1 min, any whole test directory. Never delete a lock or queue entry you did not
create; never kill a python process you did not start."""
import ctypes
import os
import subprocess
import sys
import time

DOCS = r"C:\Users\tomhe\Documents"
LOCK = os.path.join(DOCS, "HEAVY.lock")
QUEUE = os.path.join(DOCS, "HEAVY.queue")
MIN_AVAIL_GB = 4.5
POLL = 30


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


def pid_alive(pid):
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259                                           # STILL_ACTIVE


def clear_stale_lock():
    """a lock whose holder died (a session ended mid-job, 2026-10-20: the queue sat blocked for a day) is removed --
    the holder's pid is in the lock text; a live holder, or a lock with no pid, is left alone"""
    import re
    m = re.search(r"\bpid (\d+)\b", lock_text())
    if m and not pid_alive(int(m.group(1))):
        try:
            os.remove(LOCK)
            print("heavy.py: removed a stale lock (pid %s is gone)" % m.group(1), flush=True)
        except OSError:
            pass


def lock_text():
    try:
        return open(LOCK).read().strip()
    except OSError:
        return ""


def higher_waiter(prio):
    """a LIVE waiter queued with a higher priority (entries of dead waiters are ignored, not deleted)"""
    try:
        names = os.listdir(QUEUE)
    except OSError:
        return None
    for n in names:
        try:
            p, _, rest = n.partition("_")
            pid = int(rest.rsplit("_", 1)[1])
            if int(p) > prio and pid_alive(pid):
                return n
        except (ValueError, IndexError):
            continue
    return None


GIT_BASH = "C:/Program Files/Git/bin/bash.exe"      # CreateProcess searches System32 (WSL bash) before PATH


def run(cmd, log):
    # `bash` alone resolves to WSL's bash (System32) from a Windows python: it has no /c/... paths and no python, so
    # every agent chain died at once and "passed" through the queue overnight (2026-10-19) -- use Git Bash
    if cmd and cmd[0] in ("bash", "bash.exe", "sh") and os.path.exists(GIT_BASH):
        cmd = [GIT_BASH] + cmd[1:]
    if log:
        with open(log, "w") as f:
            return subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT)
    return subprocess.call(cmd)


def main():
    a = sys.argv[1:]
    name = a.pop(0)
    prio, build, light, log = 5, False, False, None
    while a and a[0] != "--":
        o = a.pop(0)
        if o == "--prio":
            prio = int(a.pop(0))
        elif o == "--build":
            build = True
        elif o == "--light":
            light = True
        elif o == "--log":
            log = a.pop(0)
        else:
            raise SystemExit("heavy.py: unknown option %s" % o)
    assert a and a[0] == "--", "usage: heavy.py NAME [--prio N] [--build | --light] [--log FILE] -- cmd ..."
    cmd = a[1:]
    if light and any("tests/fj" in c.replace("\\", "/") for c in cmd):
        # an fj harness is HEAVY (one sat at 12 GB under --light, 2026-10-19): it takes the lock like one
        print("heavy.py: --light refused for a tests/fj command -- running it as HEAVY", flush=True)
        light = False
    if light:
        said = False
        while "BUILD" in lock_text():
            if not said:
                print("heavy.py --light: waiting for the build -- %s" % lock_text(), flush=True)
                said = True
            time.sleep(POLL)
        return run(cmd, log)
    os.makedirs(QUEUE, exist_ok=True)
    me = os.path.join(QUEUE, "%d_%s_%d" % (prio, name.replace("_", "-"), os.getpid()))
    open(me, "w").write(" ".join(cmd)[:300] + "\n")
    said = False
    try:
        while True:
            clear_stale_lock()
            if not os.path.exists(LOCK) and not higher_waiter(prio) and avail_gb() >= MIN_AVAIL_GB:
                try:
                    fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    continue
                os.write(fd, ("%s%s prio %d pid %d since %s: %s\n" % ("BUILD " if build else "", name, prio,
                              os.getpid(), time.ctime(), " ".join(cmd)[:300])).encode())
                os.close(fd)
                break
            if not said:
                print("heavy.py: waiting -- %s" % (lock_text() or higher_waiter(prio)
                                                    or "(RAM %.1f GB)" % avail_gb()), flush=True)
                said = True
            time.sleep(POLL)
    finally:
        os.remove(me)
    try:
        return run(cmd, log)
    finally:
        os.remove(LOCK)


if __name__ == "__main__":
    raise SystemExit(main())
