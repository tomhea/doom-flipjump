"""Measure fj engine throughput on the DOOM binary under Linux, where huge pages are FREE.

WHY THIS EXISTS. The binding cost is TLB translation: the game's 26.67 MB of touched data is
scattered over 23,397 4 KB pages against a ~2,048-entry L2 TLB, and a footprint-controlled A/B
measured 113.6 M ops/s at that page count against 448.8 M ops/s at 2,048 pages. Collapsing the
page count needs 2 MB pages -- and on Windows that needs SeLockMemoryPrivilege, which the owner
cannot be granted.

Linux does not need any privilege: Transparent Huge Pages via madvise(MADV_HUGEPAGE) are
available to every user whenever /sys/kernel/mm/transparent_hugepage/enabled is `always` or
`madvise`. The same touch map says the whole working set spans only 174 distinct 2 MB regions,
so under THP the entire thing becomes TLB-resident.

SELF-CONTAINED ON PURPOSE. It imports nothing from doomfj -- only flipjump -- so it runs in a
bare WSL/Linux checkout with no game dependencies installed. The key-event composition is
copied from `scratchpad/m2_std_gate.py` (to_events / events_for) and the two device subclasses
from the same file; they are duplicated rather than imported precisely so this file has no
dependency on the Windows-side package layout. The frame script must match the Windows run
EXACTLY or the comparison is meaningless, so the constants are pinned here and asserted against
the numbers the Windows side produced.

    python3 scratchpad/12m/wsl_speed.py <path-to.fjm> [game_frames]
"""
import sys
import time
from pathlib import Path

from flipjump.fjm import fjm_reader
from flipjump.fjm.fjm_reader import GarbageHandling
from flipjump.interpreter import _fjcore
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from flipjump.interpreter.io_devices.pygame_window import PcIO
from flipjump.utils.exceptions import IOReadOnEOF

# pinned to match the Windows-side harness exactly (src/doomfj/wall_renderer.py STANDALONE_POLLS,
# scratchpad/m2_std_gate.py MENU_FRAMES / ENTER / CODE)
STANDALONE_POLLS = 8
MENU_FRAMES = 2
ENTER = 0x0D
CODE = {"forward": 0x77, "back": 0x73, "turn_left": 0x61, "turn_right": 0x64, "use": 0x20}
KEY_NAMES = tuple(CODE)


class Recording(InMemoryScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


class Stopper(KeyboardIO):
    def __init__(self, event_source, screen, limit):
        super().__init__(event_source)
        self._screen, self._limit = screen, limit

    def read_bit(self):
        if len(self._screen.frames) >= self._limit:
            raise IOReadOnEOF("got the %d frames asked for" % self._limit)
        return super().read_bit()


def to_events(per_frame):
    out, held = [], {k: False for k in KEY_NAMES}
    for f, keys in enumerate(per_frame):
        for name in KEY_NAMES:
            want = bool(keys.get(name))
            if want != held[name]:
                out.append(KeyEvent(f * STANDALONE_POLLS, want, CODE[name]))
                held[name] = want
    return out


def events_for(per_frame):
    return to_events(per_frame) + [KeyEvent(MENU_FRAMES * STANDALONE_POLLS, True, ENTER),
                                   KeyEvent(MENU_FRAMES * STANDALONE_POLLS + 1, False, ENTER)]


def thp_state():
    try:
        return Path("/sys/kernel/mm/transparent_hugepage/enabled").read_text().strip()
    except OSError:
        return "unavailable"


def anon_huge_kb():
    """How many KB of this process are ACTUALLY backed by huge pages, per the kernel.

    This is the control that turns "we asked for THP" into "we got THP": MADV_HUGEPAGE is
    advisory and the kernel can decline (THP off, memory too fragmented to compact). Without
    reading it back, a speed number could be credited to huge pages that were never granted."""
    total = 0
    try:
        for line in Path("/proc/self/smaps").read_text().splitlines():
            if line.startswith("AnonHugePages:"):
                total += int(line.split()[1])
    except OSError:
        return -1
    return total


def main():
    fjm = Path(sys.argv[1])
    nframes = int(sys.argv[2]) if len(sys.argv) > 2 else 14

    print("THP policy      : %s" % thp_state(), flush=True)
    per_frame = [{} for _ in range(MENU_FRAMES)] + [{"forward": True} for _ in range(nframes)]
    events = events_for(per_frame)
    n = len(per_frame)

    t0 = time.time()
    mem = fjm_reader.Reader(fjm)
    mem.assert_runnable()
    assert mem.garbage_handling == GarbageHandling.Stop, "need garbage-stop for the flat path"

    # ⚠ MEMORY, not style. The reader materialises one dict entry per loaded word -- 43.7M of
    # them for this image, ~4.4 GB -- and WSL2 here has ~7 GB total. Building a separate list of
    # contiguous runs on TOP of that dict (which is what the Windows-side FjmRunner does, where
    # RAM is plentiful) peaks high enough to OOM. So: create the core FIRST, then push each run
    # into it as soon as the run ends and drop the reference immediately.
    core = _fjcore.Memory(mem.memory_width, flat_max_words=134217728)
    for s in mem.memory_segments:
        core.add_segment(s.segment_start, s.segment_length)

    start, nxt, vals, nruns = None, 0, [], 0
    for addr in sorted(mem.memory):
        if start is None or addr != nxt:
            if start is not None:
                core.set_words(start, vals)
                nruns += 1
            start, vals = addr, []
        vals.append(mem.memory[addr])
        nxt = addr + 1
    if start is not None:
        core.set_words(start, vals)
        nruns += 1
    del vals
    mem.memory = {}
    print("load            : %.1fs  (%s contiguous runs)" % (time.time() - t0,
                                                             format(nruns, ",")), flush=True)

    screen = Recording()
    kb = Stopper(ScriptedKeyEventSource(events), screen, n)
    io = PcIO(screen, kb)
    io.attach_memory(NativeDeviceMemory(core, mem.memory_width))

    t1 = time.time()
    res = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
    dt = time.time() - t1
    ops, paused = res[1], res[4]
    fr = len(screen.frames)
    lp = getattr(core, "large_pages", "n/a")
    cb = getattr(core, "cell_bytes", "n/a")
    huge = anon_huge_kb()

    print("storage_mode    : %s" % core.storage_mode)
    print("cell_bytes      : %s   (4 = the 4-byte-cell path is LIVE; 8 = forced or w>32)" % cb)
    print("large_pages flag: %s   (the allocator's own report)" % lp)
    print("AnonHugePages   : %s KB = %.1f MB   <- what the KERNEL actually granted"
          % (format(huge, ","), huge / 1024.0) if huge >= 0 else "AnonHugePages   : unreadable")
    print("frames          : %d" % fr)
    print("ops             : %s" % format(ops, ","))
    print("wall            : %.2fs   (IO %.3fs = %.1f%%)" % (dt, paused, 100.0 * paused / dt))
    print("")
    print("  fj/s          : %.1fM" % (ops / dt / 1e6))
    print("  ops/frame     : %s" % format(int(ops / max(1, fr)), ","))
    print("  ms/frame      : %.1f" % (dt / max(1, fr) * 1000))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
