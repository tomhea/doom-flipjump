"""Run one assembled .fjm MANY times without re-paying the per-run load.

`flipjump.run(path, ...)` is a one-shot API: every call re-parses the .fjm from disk and rebuilds
the native engine's memory image. That is exactly right for a test, and exactly wrong for the
walker, which renders the SAME program once per frame — measured on E1M1 (6.36M words), the parse
costs 1.63s and the run-list prep 0.87s, against a 0.105s actual run. So ~96% of `flipjump.run`'s
wall time was setup the walker was paying over and over.

`FjmRunner` hoists everything that does not depend on the frame — the parse, the segment list and
the contiguous word runs — into the constructor, leaving per frame only (a) a fresh
`_fjcore.Memory` + bulk `set_words`, and (b) the C run loop itself:

    E1M1 spawn frame, WPX+FT1        flipjump.run    FjmRunner
      per-frame wall time              2.56 s         0.187 s      (13.6x)
      of which the C run loop          0.105 s        0.105 s      (220M ops/s)

⚠ The memory image MUST be rebuilt per run — it cannot be reused. FlipJump programs self-modify
(every `wflip`, and this renderer's whole `xor_by` per-seg constant machinery), so a second run on
a dirty image is not the same program: measured, run 2 on a reused core halts after 9 ops. The
`set_words` restore is therefore load-bearing, not an optimisation to be tidied away later.

Output is byte-identical to `flipjump.run` — the engine and the IO device are the same ones
`flipjump.run` would have picked; only the redundant reload is gone.
"""
from pathlib import Path
from typing import List, Optional, Tuple

import flipjump as fj
from flipjump.fjm import fjm_reader
from flipjump.fjm.fjm_reader import GarbageHandling
from flipjump.interpreter.fjm_run import IOReadOnEOF, is_native_engine_active
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory

from doomfj.config import RENDER_FLAT_MAX_WORDS   # R6: ONE flat limit, not twelve literals

try:                                          # the native engine is optional (a source install
    from flipjump.interpreter import _fjcore  # without the built C extension still works)
except ImportError:                           # pragma: no cover
    _fjcore = None


class FjmRunner:
    """An assembled .fjm loaded ONCE and runnable many times. `run(io_device)` returns the op count.

    Falls back to `flipjump.run` (same results, ~14x slower) whenever the native engine is absent
    or cannot take this program — so callers never need to branch on it; check `.native` only to
    report which path is live."""

    def __init__(self, fjm_path: Path,
                 flat_max_words: int = RENDER_FLAT_MAX_WORDS) -> None:
        self.fjm_path = Path(fjm_path)
        self.flat_max_words = flat_max_words
        self._mem = fjm_reader.Reader(self.fjm_path)
        self._mem.assert_runnable()
        self.native = (_fjcore is not None and is_native_engine_active()
                       and self._mem.garbage_handling == GarbageHandling.Stop)
        self.width = self._mem.memory_width
        self._segments: List[Tuple[int, int]] = []
        self._runs: List[Tuple[int, List[int]]] = []
        if self.native:
            self._segments = [(s.segment_start, s.segment_length)
                              for s in self._mem.memory_segments]
            # the loaded words as CONTIGUOUS runs, built once -- per frame this is just one
            # bulk set_words per run, with no dict walk and no re-sort
            start: Optional[int] = None
            nxt, vals = 0, []
            for addr in sorted(self._mem.memory):
                if start is None or addr != nxt:
                    if start is not None:
                        self._runs.append((start, vals))
                    start, vals = addr, []
                vals.append(self._mem.memory[addr])
                nxt = addr + 1
            if start is not None:
                self._runs.append((start, vals))
        # the parsed dict is redundant either way and would sit on ~350MB for E1M1 (6.36M
        # int->int entries) for the whole session: the native path keeps only `_runs`, and the
        # fallback path re-reads the .fjm from disk inside `fj.run` (CR-2026-08: this release
        # used to live inside the `if self.native:` block, leaking the dict on the fallback).
        self._mem.memory = {}

    def run(self, io_device) -> int:
        """Run the program once against `io_device`; returns the op count."""
        if not self.native:
            return fj.run(self.fjm_path, io_device=io_device, print_time=False,
                          print_termination=False,
                          flat_max_words=self.flat_max_words).op_counter
        # WALKER-PERF: one long-lived core, restored per frame by the C-side freeze()/reset()
        # snapshot (a single 8B-per-word memcpy) instead of rebuilding a fresh core and pushing
        # every word back through set_words -- the Python-list reload measured ~0.5s/frame at
        # the 37M-word image (10x the run loop itself). Older engines without freeze() fall
        # back to the rebuild path, so this stays correct on a stock flipjump install.
        core = getattr(self, "_core", None)
        if core is not None:
            core.reset()
        else:
            core = _fjcore.Memory(self.width, flat_max_words=self.flat_max_words)
            for seg_start, seg_len in self._segments:
                core.add_segment(seg_start, seg_len)
            for start, vals in self._runs:
                core.set_words(start, vals)
            if hasattr(core, "freeze"):
                try:
                    core.freeze()             # pure-flat programs only; paged falls back below
                    self._core = core
                    self._runs = []           # the frozen image supersedes the Python-int runs
                except RuntimeError:
                    pass
        io_device.attach_memory(NativeDeviceMemory(core, self.width))
        _cause, op_count, _err, _last, _paused = core.run(
            io_device.read_bit, io_device.write_bit, IOReadOnEOF, last_ops_length=0)
        return op_count
