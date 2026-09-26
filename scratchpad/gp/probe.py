"""probe.py -- S2 of docs/plan-gameplay.md: the STATE PROBE / INJECTOR for a RUNNING game binary.

    python scratchpad/gp/probe.py --selftest            # R9: controls C0..C4 (takes the binary lock)
    python scratchpad/gp/probe.py --demo                # read a walk, inject a viewpoint (blocked27)

WHAT IT IS. The screen device holds `device_memory` (NativeDeviceMemory: read_word/write_word) for
the whole run, and the frame loop calls back into Python on every input bit and every present. So a
gate can READ any cell of the running program by LABEL, and WRITE one, at a known point of the frame
-- with no change to the program at all. That is what makes gates state-exact (plan section 9) and
what drives B0 (scratchpad/gp/b0.py) and, later, fuzzing.

API (see the class docstrings):
    table = LabelTable.load(labels_tsv_gz, names)            # label -> bit address
    probe = Probe(cells, table)                               # cells: {key: Cell(...)}
    probe.on_frame_start(fn) / on_present(fn) / on_end(fn)    # fn(probe, frame_index)
    probe.read_cells([keys]) -> {key: value}   probe.write_cells({key: value})
    probe.read_word(w) / write_word(w, v)                     # raw memory words
    probe.verify_known({key: value})                          # raises LabelTableRejected
    probe.frame_ops()                                         # per-frame ops, +/- 2^18 (below)
    GameBinary(fjm).run(frames, events, probe, pre_run=fn) -> RunResult(frames, ops EXACT, ...)

WHEN THE HOOKS FIRE (the game frame is: 8 polls -> menu branch -> doors -> player -> render ->
present -> M1 reset -> loop):
  on_frame_start  the FIRST INPUT READ of frame f, before its polls. The previous frame's M1 reset
                  has finished: every restored cell is pristine and every persisted cell (view,
                  key flags, mode, doors) holds what frame f's tic will read. A write here is what
                  frame f simulates and draws.
  on_present      frame f's picture is out; the reset has NOT run. Persisted cells hold the
                  post-tic state the frame was drawn from.
  on_end          the first input read after the LAST requested frame (after its reset); the run
                  then stops with IOReadOnEOF, exactly like the gates' Stopper.

OPS PER FRAME, AND ITS GRANULARITY. The only live op counter is `_fjcore.Memory.last_run_op_count`.
The engine refreshes it once per strip of SIGNAL_CHECK_MASK + 1 = 2^18 = 262,144 ops
(flipjump-151 _fjcore.c: `#define SIGNAL_CHECK_MASK 0x3FFFFull`, stored at the top of each strip),
not per op and not at IO. A frame-start reading is the count at the start of the current strip: it
LAGS the truth by 0..262,143 ops, so a per-frame difference is within +/-262,143 of the true count.
The run TOTAL (core.run's return value) is exact. Control C4 measures EXACT per-frame counts by
prefix runs and checks the readings against them, so the bound is tested, not assumed.

THE CELL LAYOUT (w=32, dw=2w=64 bits; docs/handoff-m1-reset.md section 1, measured by
scratchpad/m1a_stride.py). A cell at bit address A is two words: the FLIP word A//w and the JUMP
word A//w+1. A hex (nibble) cell holds its nibble as `v << 6` in the jump word (v * dw); a BYTE cell
(the write_byte arrays -- sshead, pclm, ...) holds its byte the same way, `b << 6`, one cell per
index. A data cell's flip word is 0.
  In a BLOCKED build the jump word also carries a per-cell BASE: `base | (v << 6)` (MEASURED on
blocked27: viewx's cells read 0xaa700000 .. 0xaaf103c0; see Probe._field). The probe records every
cell's base when it attaches to the pristine image, writes only the value field, and is STRICT on
reads: a non-zero flip word, or a base that differs from the recorded one, is an error -- which is
what makes a label table that is off by one WORD fail loudly instead of reading garbage.
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import os
import sys
import time
from array import array
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", ROOT):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

DEFAULT_FJM = ROOT / "build" / "doom_e1m1_blocked27.fjm"
DEFAULT_LABELS = ROOT / "scratchpad" / "12m" / "atlas" / "blocked27.labels.tsv.gz"
DEFAULT_WAD = "tests/fixtures/freedoom_e1m1.wad"
DEFAULT_ASSET = "assets/freedoom1.wad"
DEFAULT_MAP = "E1M1"

OPS_GRANULARITY = 1 << 18     # _fjcore.c SIGNAL_CHECK_MASK + 1: how often last_run_op_count moves
# what docs/ship-evidence/padB_gamespeed.log recorded for these bytes (padB.fjm == blocked27):
# control C5 replays them to prove the lean loader loads the shipped program
RECORDED_SHA16 = "38b09a7331f4f52b"
RECORDED_CALIBRATION = 518_147          # startup + 2 menu frames
RECORDED_RUN, RECORDED_RUN_OPS = 1, 1_001_952_090
LOCK_PATH = Path(r"C:\Users\tomhe\AppData\Local\Temp\claude\C--Users-tomhe-Documents-doom-flipjump"
                 r"\29ddbecf-cbb7-4734-805a-36c0e391327d\scratchpad\gp_binary.lock")


# ================================================================================================
# the binary lock (one agent runs the game binary at a time)
# ================================================================================================

class LockTimeout(RuntimeError):
    pass


@contextmanager
def binary_lock(stream: str, lock_path: Path = LOCK_PATH, poll_s: float = 30.0,
                max_wait_s: float = 40 * 60, quiet: bool = False):
    """O_CREAT|O_EXCL the lock file with our stream name in it; while someone else holds it, poll
    every `poll_s` for up to `max_wait_s`; on exit delete it -- but only if it is still OURS."""
    t0 = time.time()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            tag = "%s pid %d since %s" % (stream, os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S"))
            break
        except FileExistsError:
            waited = time.time() - t0
            if waited >= max_wait_s:
                raise LockTimeout("lock %s still held after %.0f s (holder: %r)"
                                  % (lock_path, waited, _read_quiet(lock_path)))
            if not quiet:
                print("  lock held by %r -- waited %.0f s, polling every %.0f s"
                      % (_read_quiet(lock_path), waited, poll_s), flush=True)
            time.sleep(min(poll_s, max(0.01, max_wait_s - waited)))
    os.write(fd, tag.encode("ascii"))
    os.close(fd)
    try:
        yield tag
    finally:
        if _read_quiet(lock_path) == tag:
            os.remove(str(lock_path))


def _read_quiet(p: Path) -> str:
    try:
        return Path(p).read_text(encoding="ascii", errors="replace")
    except OSError:
        return "<gone>"


# ================================================================================================
# the label table
# ================================================================================================

class LabelTable:
    """`name -> bit address` for the names asked for, plus every label ADDRESS in the table (sorted),
    so a cell spec can be checked against its label's declared extent (the next label up)."""

    def __init__(self, addrs: dict, all_addrs: array, source: str):
        self.addrs = dict(addrs)
        self.all_addrs = all_addrs
        self.source = source

    @classmethod
    def load(cls, path, names) -> "LabelTable":
        want = set(names)
        got, every = {}, array("Q")
        with gzip.open(str(path), "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                name, _t, addr = line.rstrip("\n").rpartition("\t")
                a = int(addr)
                every.append(a)
                if name in want:
                    got[name] = a
        missing = sorted(want - set(got))
        if missing:
            raise KeyError("label table %s has no %s" % (path, missing[:8]))
        return cls(got, array("Q", sorted(set(every))), str(path))

    def shifted(self, delta_bits: int) -> "LabelTable":
        """THE NEGATIVE CONTROL'S INPUT: the same table with every address moved by `delta_bits`."""
        return LabelTable({k: v + delta_bits for k, v in self.addrs.items()},
                          array("Q", (a + delta_bits for a in self.all_addrs)),
                          "%s (shifted %+d bits)" % (self.source, delta_bits))

    def __getitem__(self, name):
        return self.addrs[name]

    def extent_bits(self, name) -> int:
        """bits from `name` to the next DISTINCT label address: the most its declaration spans"""
        a = self.addrs[name]
        i = bisect.bisect_right(self.all_addrs, a)
        return (self.all_addrs[i] - a) if i < len(self.all_addrs) else (1 << 62)


# ================================================================================================
# cells
# ================================================================================================

class CellLayoutError(ValueError):
    """a word that is not laid out the way the cell kind says (see the module docstring)"""


class LabelTableRejected(RuntimeError):
    """the known-value check failed: this label table does not describe this binary"""


@dataclass(frozen=True)
class Cell:
    """One probed quantity.
      kind 'hex'  : `count` numbers of `n` nibbles each in consecutive hex cells (hex.vec); nibble i
                    of a number sits in its i-th cell (little-endian).
                    viewx = Cell('viewx', 'hex', 8, signed=True); dstate = Cell('dstate', 'hex', 1,
                    count=13); dwait = Cell('dwait', 'hex', 2, count=13).
      kind 'byte' : `count` BYTE cells at a one-cell stride (the write_byte arrays).
      kind 'raw'  : `count` raw memory words from word (label // w) + index.
    `index` offsets the first element: in CELLS for hex (nibble cells) and byte, in WORDS for raw.
    A count of 1 reads as an int; more reads as a tuple."""
    label: str
    kind: str = "hex"
    n: int = 1
    count: int = 1
    signed: bool = False
    index: int = 0

    def span_cells(self) -> int:
        if self.kind == "hex":
            return self.index + self.n * self.count
        if self.kind == "byte":
            return self.index + self.count
        return 0


class Probe:
    """Reads and writes named cells of a running program; carries the per-frame hooks and the op
    readings. `GameBinary.run` attaches it (attach(device_memory, core))."""

    def __init__(self, cells: dict, labels: LabelTable, width: int = 32, strict: bool = True):
        self.cells = dict(cells)
        self.labels = labels
        self.w = width
        self.dw = 2 * width
        self.dshift = self.dw.bit_length() - 1          # 6 at w=32: a cell's value sits at v * dw
        self.strict = strict
        self.dm = None
        self.core = None
        self._hooks = {"frame_start": [], "present": [], "end": []}
        self.readings = []            # last_run_op_count at each frame start (+ one at the end)
        self.frame = -1
        self.bases = {}               # jump-word address -> the cell's base (see _field)
        for key, c in self.cells.items():
            if c.kind not in ("hex", "byte", "raw"):
                raise ValueError("cell %s: unknown kind %r" % (key, c.kind))
            if c.kind != "raw":
                need, have = c.span_cells() * self.dw, labels.extent_bits(c.label)
                if need > have:
                    raise ValueError("cell %s spans %d bits but label %s extends %d bits -- the spec "
                                     "is wider than the declaration" % (key, need, c.label, have))

    # ---- attach / raw access -------------------------------------------------------------------
    def attach(self, device_memory, core=None):
        """Attach to a memory -- normally the PRISTINE image, before the run (GameBinary.run does
        that). Every probed cell's BASE (its jump word outside the value field) is recorded here;
        see _field for why a cell has one and what reading it later checks."""
        self.dm = device_memory
        self.core = core if core is not None else getattr(device_memory, "_core_memory", None)
        self.readings = []
        self.frame = -1
        self.bases = {}
        for key, c in self.cells.items():
            if c.kind == "raw":
                continue
            fbits = 4 if c.kind == "hex" else 8
            mask = ((1 << fbits) - 1) << self.dshift
            for e in range(c.count):
                for i in range(c.n if c.kind == "hex" else 1):
                    jwa = self.cell_bits(key, e, i) // self.w + 1
                    self.bases[jwa] = self.read_word(jwa) & ~mask

    def read_word(self, word_address: int) -> int:
        return self.dm.read_word(word_address)

    def write_word(self, word_address: int, value: int) -> None:
        self.dm.write_word(word_address, value)

    def ops_now(self) -> int:
        """the engine's live counter (refreshed every OPS_GRANULARITY ops -- see the docstring)"""
        return int(self.core.last_run_op_count)

    # ---- addresses -------------------------------------------------------------------------------
    def cell_bits(self, key: str, element: int = 0, nib: int = 0) -> int:
        c = self.cells[key]
        base = self.labels[c.label]
        if c.kind == "hex":
            return base + (c.index + element * c.n + nib) * self.dw
        if c.kind == "byte":
            return base + (c.index + element) * self.dw
        raise ValueError("raw cells have word addresses: use word_of")

    def word_of(self, key: str, element: int = 0) -> int:
        c = self.cells[key]
        return self.labels[c.label] // self.w + c.index + element

    def jump_word(self, key: str, element: int = 0, nib: int = 0) -> int:
        return self.cell_bits(key, element, nib) // self.w + 1

    # ---- one cell's field ----------------------------------------------------------------------
    def _field(self, cell_bits: int, width_bits: int) -> int:
        """The value field of one cell: bits dshift .. dshift+width-1 of its JUMP word.

        ⚠ A CELL HAS A BASE (MEASURED on blocked27, 2026-09-26). In a blocked build the jump word
        of a state cell is `base | (v << 6)`: viewx's eight cells read 0xaa700000 .. 0xaaf103c0,
        i.e. a per-cell base with bits 0..15 clear plus the nibble at bit 6 (0xaaf20180 = base
        0xaaf20000 + 6<<6). The base is the pinned table the cell dispatches into (build_blocked's
        --pin-state-cells); in an unblocked build it is 0, which is the layout the M1 handoff
        measured. So the strict check is not "no other bits" but: the flip word is 0, and the base
        is the one recorded at attach -- a read that finds a different base has lost track of the
        cell (a wrong table, a wrong kind, or the program rewrote a base mid-frame)."""
        jwa = cell_bits // self.w + 1
        jw = self.read_word(jwa)
        mask = ((1 << width_bits) - 1) << self.dshift
        if self.strict:
            fw = self.read_word(jwa - 1)
            base = self.bases.get(jwa)
            if fw != 0 or (base is not None and (jw & ~mask) != base):
                raise CellLayoutError("cell at bit %d: flip word %#x, jump word %#x, recorded base %s"
                                      " -- not this %d-bit data cell"
                                      % (cell_bits, fw, jw, "none" if base is None else hex(base),
                                         width_bits))
        return (jw & mask) >> self.dshift

    def _set_field(self, cell_bits: int, width_bits: int, v: int) -> None:
        jw_addr = cell_bits // self.w + 1
        mask = ((1 << width_bits) - 1) << self.dshift
        jw = self.read_word(jw_addr)
        self.write_word(jw_addr, (jw & ~mask) | ((v << self.dshift) & mask))

    # ---- the API ----------------------------------------------------------------------------------
    def read_cells(self, names=None) -> dict:
        out = {}
        for key in (self.cells if names is None else names):
            c = self.cells[key]
            vals = []
            for e in range(c.count):
                if c.kind == "hex":
                    v = 0
                    for i in range(c.n):
                        v |= self._field(self.cell_bits(key, e, i), 4) << (4 * i)
                    if c.signed and v >> (4 * c.n - 1):
                        v -= 1 << (4 * c.n)
                elif c.kind == "byte":
                    v = self._field(self.cell_bits(key, e), 8)
                else:
                    v = self.read_word(self.word_of(key, e))
                vals.append(v)
            out[key] = vals[0] if c.count == 1 else tuple(vals)
        return out

    def write_cells(self, values: dict) -> None:
        for key, val in values.items():
            c = self.cells[key]
            vals = [val] if c.count == 1 else list(val)
            if len(vals) != c.count:
                raise ValueError("cell %s takes %d values, got %d" % (key, c.count, len(vals)))
            for e, v in enumerate(vals):
                if c.kind == "hex":
                    v &= (1 << (4 * c.n)) - 1
                    for i in range(c.n):
                        self._set_field(self.cell_bits(key, e, i), 4, (v >> (4 * i)) & 0xF)
                elif c.kind == "byte":
                    self._set_field(self.cell_bits(key, e), 8, v & 0xFF)
                else:
                    self.write_word(self.word_of(key, e), v & ((1 << self.w) - 1))

    # ---- the known-value check (control C3) ---------------------------------------------------------
    def check_known(self, expected: dict) -> list:
        """[(cell, want, got_or_layout_error)] for every cell that does not hold its known value"""
        bad = []
        for key, want in expected.items():
            try:
                got = self.read_cells([key])[key]
            except CellLayoutError as e:
                bad.append((key, want, "LAYOUT %s" % e))
                continue
            if got != want:
                bad.append((key, want, got))
        return bad

    def verify_known(self, expected: dict) -> None:
        bad = self.check_known(expected)
        if bad:
            raise LabelTableRejected("%d of %d known cells disagree (table %s), e.g. %s"
                                     % (len(bad), len(expected), self.labels.source, bad[:3]))

    # ---- hooks ----------------------------------------------------------------------------------
    def on_frame_start(self, fn):
        self._hooks["frame_start"].append(fn)
        return fn

    def on_present(self, fn):
        self._hooks["present"].append(fn)
        return fn

    def on_end(self, fn):
        self._hooks["end"].append(fn)
        return fn

    def _fire(self, kind, frame):
        for fn in self._hooks[kind]:
            fn(self, frame)

    def _frame_start(self, frame):                   # called by ProbeKeyboard
        self.frame = frame
        self.readings.append(self.ops_now())
        self._fire("frame_start", frame)

    def _end(self, frame):                           # called by ProbeKeyboard, then EOF
        self.readings.append(self.ops_now())
        self._fire("end", frame)

    def _present(self, frame):                       # called by ProbeScreen
        self._fire("present", frame)

    def frame_ops(self) -> list:
        """per-frame op counts from the frame-start readings; element f is frame f, each within
        +/-(2^18 - 1) of the true count (see the module docstring and control C4)"""
        r = self.readings
        return [r[i + 1] - r[i] for i in range(len(r) - 1)]


# ================================================================================================
# running the binary with the probe attached
# ================================================================================================

def _devices():
    from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO
    from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
    from flipjump.utils.exceptions import IOReadOnEOF

    class ProbeScreen(InMemoryScreen):
        """the stock headless screen + a snapshot of every presented frame + the present hook"""

        def __init__(self, probe=None, **kw):
            super().__init__(**kw)
            self.frames, self.palettes, self._probe = [], [], probe

        def _present(self):
            super()._present()
            self.frames.append(bytes(self.pixel_indices))
            self.palettes.append(hashlib.sha1(bytes(b for rgb in self.palette for b in rgb))
                                 .hexdigest()[:12])
            if self._probe is not None:
                self._probe._present(len(self.frames) - 1)

    class ProbeKeyboard(KeyboardIO):
        """the scripted keyboard; its first read after each present IS the frame-start hook, and it
        EOFs once the screen has presented `limit` frames (the standalone program has no end)"""

        def __init__(self, source, screen, limit, probe=None):
            super().__init__(source)
            self._screen, self._limit, self._probe, self._started = screen, limit, probe, -1

        def read_bit(self):
            n = len(self._screen.frames)
            if n != self._started:
                self._started = n
                if n >= self._limit:
                    if self._probe is not None:
                        self._probe._end(n)
                    raise IOReadOnEOF("the probe has the %d frames it asked for" % self._limit)
                if self._probe is not None:
                    self._probe._frame_start(n)
            return super().read_bit()

    return ProbeScreen, ProbeKeyboard, IOReadOnEOF


@dataclass
class RunResult:
    frames: list                # presented pixel indices, one bytes object per frame
    palettes: list              # sha1[:12] of the palette at each present
    ops: int                    # EXACT: core.run's own count, startup included
    readings: list              # the probe's frame-start readings (+/- OPS_GRANULARITY each)
    seconds: float


def _lean_fjm(path):
    """(width, [(segment_start, segment_length, array('I') of the data words)]) -- flipjump's
    fjm_reader._init_memory, vectorised: jump words of a RelativeJump/Compressed image are stored
    relative to their own bit address and are rebuilt here the same way."""
    import lzma
    import struct
    import numpy as np
    from flipjump.fjm import fjm_reader as R
    from flipjump.fjm.fjm_consts import FJMVersion
    with open(path, "rb") as fh:
        _magic, width, version, segnum = struct.unpack(R._header_base_format,
                                                       fh.read(R._header_base_size))
        version = FJMVersion(version)
        if version != FJMVersion.BaseVersion:
            struct.unpack(R._header_extension_format, fh.read(R._header_extension_size))
        segs = [struct.unpack(R._segment_format, fh.read(R._segment_size)) for _ in range(segnum)]
        data = fh.read()
    if version == FJMVersion.CompressedVersion:
        data = lzma.decompress(data, format=R._LZMA_FORMAT, filters=R._LZMA_DECOMPRESSION_FILTERS)
    if width != 32:
        raise ValueError("the lean loader is written for w=32; use loader='fjmrunner'")
    words = np.frombuffer(data, dtype="<u4")
    assert array("I").itemsize == 4
    out = []
    for seg_start, seg_len, data_start, data_len in segs:
        chunk = words[data_start:data_start + data_len].astype(np.uint64)
        if version in (FJMVersion.RelativeJumpVersion, FJMVersion.CompressedVersion):
            pos = np.arange(1, data_len, 2, dtype=np.uint64) + np.uint64(seg_start)
            chunk[1::2] = (chunk[1::2] + pos * np.uint64(width)) & np.uint64((1 << width) - 1)
        a = array("I")
        a.frombytes(chunk.astype("<u4").tobytes())
        out.append((seg_start, seg_len, a))
    return width, out


class GameBinary:
    """A game .fjm loaded ONCE and run many times from its pristine image (the engine's
    freeze()/reset() snapshot, one memcpy per run -- the FjmRunner idiom).

    loader="lean" (default) decodes the .fjm with numpy straight into the engine: ~0.4 GB of
    Python-side memory instead of FjmRunner's dict of every word (several GB for this 43M-word
    image). It mirrors flipjump's fjm_reader (header, segments, LZMA, relative jump words) and is
    checked by selftest control C5, which replays gamespeed runs and requires the op totals the
    ship-gate evidence recorded for these bytes, to the op. loader="fjmrunner" is the stock path."""

    def __init__(self, fjm=DEFAULT_FJM, flat_max_words: int | None = None, loader: str = "lean"):
        from doomfj.config import RENDER_FLAT_MAX_WORDS
        from doomfj.fastrun import _fjcore
        t = time.time()
        self.fjm = Path(fjm)
        self.sha = hashlib.sha256(self.fjm.read_bytes()).hexdigest()
        self.flat_max_words = flat_max_words or RENDER_FLAT_MAX_WORDS
        self.loader = loader
        if loader == "lean":
            self.width, segments = _lean_fjm(self.fjm)
            core = _fjcore.Memory(self.width, flat_max_words=self.flat_max_words)
            for seg_start, seg_len, words in segments:
                core.add_segment(seg_start, seg_len)
            for seg_start, seg_len, words in segments:
                core.set_words(seg_start, words)
            del segments
        else:
            from doomfj.fastrun import FjmRunner
            r = FjmRunner(self.fjm, flat_max_words=self.flat_max_words)
            assert r.native, "the probe needs the native engine"
            self.width = r.width
            core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
            for seg, n in r._segments:
                core.add_segment(seg, n)
            for start, vals in r._runs:
                core.set_words(start, vals)
            r._runs = []
            del r
        core.freeze()                    # the pristine snapshot; every run starts with reset()
        self.core = core
        self.load_seconds = time.time() - t

    def memory(self):
        """a device-memory view of the core, for reading the image outside a run"""
        from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
        return NativeDeviceMemory(self.core, self.width)

    def run(self, frames: int, events=(), probe: Probe | None = None, pre_run=None) -> RunResult:
        from flipjump.interpreter.io_devices.KeyboardIO import ScriptedKeyEventSource
        from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
        from flipjump.interpreter.io_devices.pygame_window import PcIO
        ProbeScreen, ProbeKeyboard, IOReadOnEOF = _devices()
        self.core.reset()
        screen = ProbeScreen(probe)
        kb = ProbeKeyboard(ScriptedKeyEventSource(list(events)), screen, frames, probe)
        io = PcIO(screen, kb)
        io.attach_memory(NativeDeviceMemory(self.core, self.width))
        if probe is not None:
            probe.attach(screen.device_memory, self.core)
        if pre_run is not None:
            pre_run(probe)                       # e.g. the known-value check on the pristine image
        t = time.time()
        _c, ops, _e, _l, _p = self.core.run(io.read_bit, io.write_bit, IOReadOnEOF,
                                            last_ops_length=0)
        return RunResult(list(screen.frames), list(screen.palettes), int(ops),
                         list(probe.readings) if probe is not None else [], time.time() - t)


# ================================================================================================
# the game tier's cells and known values, and the oracle side
# ================================================================================================

def game_cells(ndoors: int) -> dict:
    """the persisted world state of the standalone game tier (build.STANDALONE_PERSIST +
    DOOR_PERSIST) as probe cells"""
    from doomfj.doorcode import WAIT_NIBBLES
    cells = {"viewx": Cell("viewx", "hex", 8, signed=True),
             "viewy": Cell("viewy", "hex", 8, signed=True),
             "viewangle": Cell("viewangle", "hex", 8),
             "mode": Cell("mode", "hex", 1)}
    for k in ("kb_f", "kb_b", "kb_l", "kb_r", "kb_u"):
        cells[k] = Cell(k, "hex", 1)
    cells["dstate"] = Cell("dstate", "hex", 1, count=ndoors)
    cells["ddir"] = Cell("ddir", "hex", 1, count=ndoors)
    cells["dsub"] = Cell("dsub", "hex", 1, count=ndoors)
    cells["dwait"] = Cell("dwait", "hex", WAIT_NIBBLES, count=ndoors)
    return cells


KEYS_UP = {"kb_f": 0, "kb_b": 0, "kb_l": 0, "kb_r": 0, "kb_u": 0}


class Oracle:
    """the reference model as the gates use it: the static world, the render keywords of
    m2_std_gate/m3_gate, door POSES, and the door-aware stepper (onewalk.DoorSim = the M2 order)"""

    RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                     near_steps=True, stack_steps=True, things=True, degrade=True)

    def __init__(self, wad=DEFAULT_WAD, asset=DEFAULT_ASSET, mapname=DEFAULT_MAP):
        from doomfj.config import Config
        from doomfj.doors import door_states
        from doomfj.reference_model import ReferenceModel, build_scene, spawn_state
        from doomfj.wad import WadFile
        self.mw = WadFile.from_path(str(ROOT / wad))
        self.art = WadFile.from_path(str(ROOT / asset))
        self.mapname = mapname
        self.rm = ReferenceModel(Config())
        self.secs = self.mw.sectors(mapname)
        self.lds, self.sds = self.mw.linedefs(mapname), self.mw.sidedefs(mapname)
        self.door_order = sorted(door_states(self.secs, self.lds, self.sds))
        self.spawn = spawn_state(self.mw, mapname)
        self._scenes = {(): build_scene(self.mw, self.mw, mapname)}

    @property
    def ndoors(self):
        return len(self.door_order)

    def known_pristine(self) -> dict:
        """what the game tier BAKES, from sources independent of the binary: the WAD's player
        start, the menu mode, every key up, every door shut and idle (doors.initial_states)"""
        from doomfj.doors import IDLE
        nd = self.ndoors
        return {"viewx": self.spawn.x, "viewy": self.spawn.y, "viewangle": self.spawn.angle,
                "mode": 1, **KEYS_UP,
                "dstate": (0,) * nd, "ddir": (IDLE,) * nd, "dsub": (0,) * nd, "dwait": (0,) * nd}

    def door_pose(self, dstate: tuple) -> dict:
        """cells that hold every door STILL at `dstate` for a frame: idle, no timer -- door_tic
        leaves (k, IDLE, 0, 0) unchanged when use is not pressed"""
        from doomfj.doors import IDLE
        nd = self.ndoors
        return {"dstate": tuple(dstate) if dstate else (0,) * nd, "ddir": (IDLE,) * nd,
                "dsub": (0,) * nd, "dwait": (0,) * nd}

    def scene_for(self, dstate: tuple = ()):
        """the RENDER scene with the doors at `dstate` (a tuple in door_order); shut if empty"""
        from doomfj.doors import heights_for_states
        from doomfj.reference_model import build_scene
        key = tuple(dstate) if dstate and any(dstate) else ()
        if key not in self._scenes:
            self._scenes[key] = build_scene(
                self.mw, self.mw, self.mapname,
                heights_for_states(self.secs, self.lds, self.sds,
                                   {si: k for si, k in zip(self.door_order, key)}))
        return self._scenes[key]

    def render(self, x, y, angle, dstate: tuple = ()) -> bytes:
        from doomfj.reference_model import SimState
        return bytes(self.rm.render_wall_frame(SimState(x, y, angle, self.mapname),
                                               self.scene_for(dstate), sprite_wad=self.art,
                                               **self.RENDER_KW))

    def menu_frame(self) -> bytes:
        """m3_gate's menu picture"""
        from doomfj.menu import palette_colours, pixels
        from doomfj.wall_renderer import DEFAULT_MENU
        cfg = self.rm.cfg
        colours = palette_colours(bytes(b for rgb in self.mw.playpal(0) for b in rgb))
        return bytes(pixels(cfg.VIEW_W, cfg.VIEW_H, DEFAULT_MENU, 2, colours))

    def door_states_tuple(self, ds: dict) -> tuple:
        return tuple(ds[si][0] for si in self.door_order)


def px_diff(a: bytes, b: bytes) -> int:
    return sum(1 for p, q in zip(a, b) if p != q) + abs(len(a) - len(b))


# ================================================================================================
# the controls (R9)
# ================================================================================================

class _FakeMemory:
    """a word dict with the device-memory interface, for the codec's offline control"""

    def __init__(self, words=None):
        self.words = dict(words or {})

    def read_word(self, a):
        return self.words.get(a, 0)

    def write_word(self, a, v):
        self.words[a] = v & 0xFFFFFFFF


def codec_selftest(check) -> None:
    """C-1, no binary: the codec against a hand-built image whose layout is stated independently
    (a nibble v at jump word `v << 6`, a byte b at `b << 6`, flip words 0)"""
    dw = 64
    img = _FakeMemory()
    base = {"num": 100 * dw, "one": 108 * dw, "arr": 109 * dw, "byt": 112 * dw, "end": 116 * dw}
    val = 0xFE600000

    def pin(i):                                           # a blocked cell's BASE (bits 16+)
        return (0xAA70 + 3 * i) << 16
    for i in range(8):                                    # num: hex.vec 8 = 0xFE600000, pinned
        img.words[(base["num"] + i * dw) // 32 + 1] = pin(i) | ((val >> (4 * i)) & 0xF) << 6
    img.words[base["one"] // 32 + 1] = 1 << 6             # one: hex.vec 1 = 1, base 0
    for i, v in enumerate((3, 0, 9)):                     # arr: three 1-nibble entries
        img.words[(base["arr"] + i * dw) // 32 + 1] = v << 6
    for i, v in enumerate((0xA5, 0x00, 0xFF, 0x3C)):      # byt: four byte cells
        img.words[(base["byt"] + i * dw) // 32 + 1] = v << 6
    table = LabelTable(base, array("Q", sorted(base.values())), "<synthetic>")
    cells = {"num": Cell("num", "hex", 8, signed=True), "one": Cell("one", "hex", 1),
             "arr": Cell("arr", "hex", 1, count=3), "byt": Cell("byt", "byte", count=4),
             "raw": Cell("one", "raw", index=1)}
    p = Probe(cells, table)
    p.attach(img, core=None)
    want = {"num": val - (1 << 32), "one": 1, "arr": (3, 0, 9), "byt": (0xA5, 0, 0xFF, 0x3C),
            "raw": 1 << 6}
    check("C-1 codec: a hand-laid image decodes to its stated values", p.read_cells() == want,
          str(p.read_cells()))
    p.write_cells({"num": -2, "arr": (15, 1, 0), "byt": (1, 2, 3, 4), "one": 0})
    check("C-1 codec: written values read back",
          p.read_cells(["num", "arr", "byt", "one"]) == {"num": -2, "arr": (15, 1, 0),
                                                         "byt": (1, 2, 3, 4), "one": 0})
    check("C-1 codec: ... and land at value << 6 in the jump words, bases and flip words kept",
          img.words[(base["num"] + 0 * dw) // 32 + 1] == pin(0) | 0xE << 6
          and img.words[(base["num"] + 7 * dw) // 32 + 1] == pin(7) | 0xF << 6
          and img.words[(base["byt"] + 3 * dw) // 32 + 1] == 4 << 6
          and all(img.words.get((base[k]) // 32, 0) == 0 for k in ("num", "arr", "byt")))
    img.words[(base["num"] + 2 * dw) // 32 + 1] ^= 1 << 20    # the program "moved" a base
    try:
        p.read_cells(["num"])
        check("C-1 codec negative: a base that drifted from the recorded one is a layout ERROR",
              False)
    except CellLayoutError:
        check("C-1 codec negative: a base that drifted from the recorded one is a layout ERROR",
              True)
    img.words[(base["num"] + 2 * dw) // 32 + 1] ^= 1 << 20
    img.words[base["one"] // 32] = 1                      # a non-zero FLIP word
    try:
        p.read_cells(["one"])
        check("C-1 codec negative: a non-zero flip word is a layout ERROR", False)
    except CellLayoutError:
        check("C-1 codec negative: a non-zero flip word is a layout ERROR", True)
    img.words[base["one"] // 32] = 0
    img.words[base["one"] // 32 + 1] = (1 << 6) | 1       # a stray bit outside the nibble field
    try:
        p.read_cells(["one"])
        check("C-1 codec negative: a stray jump-word bit (base 0 recorded) is a layout ERROR",
              False)
    except CellLayoutError:
        check("C-1 codec negative: a stray jump-word bit (base 0 recorded) is a layout ERROR",
              True)
    try:
        Probe({"num": Cell("num", "hex", 9)}, table)
        check("C-1 spec negative: a cell wider than its label's extent is refused", False)
    except ValueError:
        check("C-1 spec negative: a cell wider than its label's extent is refused", True)


def selftest(fjm: Path, labels_path: Path) -> int:
    import gamespeed as GS
    import m2_std_gate as gate
    import onewalk
    from doomfj.reference_model import ANGLE_TURN
    from doomfj.wall_renderer import STANDALONE_POLLS
    fails = []

    def check(name, cond, detail=""):
        print("  %-68s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("probe selftest -- %s" % fjm, flush=True)
    codec_selftest(check)

    # ---- C0 the lock (no binary): a HELD lock times a second taker out; release deletes it ----
    tmp_lock = LOCK_PATH.with_name("gp_selftest.lock")
    if tmp_lock.exists():
        tmp_lock.unlink()
    with binary_lock("selftest-A", tmp_lock, poll_s=0.2, max_wait_s=1.0, quiet=True):
        try:
            with binary_lock("selftest-B", tmp_lock, poll_s=0.2, max_wait_s=0.6, quiet=True):
                timed_out = False
        except LockTimeout:
            timed_out = True
        check("C0 a HELD lock makes a second taker time out", timed_out)
    check("C0 the lock file is gone after release", not tmp_lock.exists())

    orc = Oracle()
    cells = game_cells(orc.ndoors)
    cells["pclm"] = Cell("pclm", "byte", count=4, index=40)        # 4 byte cells of a byte array
    cells["kb_f_jw"] = Cell("kb_f", "raw", count=1, index=1)        # kb_f's raw JUMP word
    t = time.time()
    table = LabelTable.load(labels_path, {c.label for c in cells.values()})
    print("  label table: %d distinct addresses, %d probed labels, %.1f s"
          % (len(table.all_addrs), len(table.addrs), time.time() - t), flush=True)
    gb = GameBinary(fjm)
    print("  binary: %s sha256 %s, loaded in %.1f s" % (fjm.name, gb.sha[:16], gb.load_seconds),
          flush=True)
    known = orc.known_pristine()

    # ---- C3 the known-value check passes on the true table; a table shifted by one cell or one
    #      word is REJECTED ------------------------------------------------------------------------
    dm = gb.memory()
    for label, delta in (("the true table", 0), ("+1 cell", 2 * gb.width), ("-1 cell", -2 * gb.width),
                         ("+1 word", gb.width), ("-1 word", -gb.width)):
        gb.core.reset()
        p = Probe(cells, table.shifted(delta) if delta else table, gb.width)
        p.attach(dm, gb.core)
        bad = p.check_known(known)
        if delta == 0:
            check("C3 the TRUE table passes the known-value check", not bad,
                  "%d of %d known cells agree" % (len(known) - len(bad), len(known)))
        else:
            check("C3 a table shifted %s is REJECTED" % label, bool(bad),
                  "%d of %d known cells disagree, e.g. %s"
                  % (len(bad), len(known), (str(bad[0])[:60] if bad else "-")))

    # the scripted walk C1 runs: menu, enter, walk + turn, stop (m2_std_gate's events)
    walk = ([{"forward": True}] * 6 + [{"forward": True, "turn_left": True}] * 4
            + [{"turn_right": True}] * 3 + [{}] * 3)
    per_frame = [{} for _ in range(gate.MENU_FRAMES)] + walk
    events = GS.events_for(per_frame)
    nfr = len(per_frame)
    k_mut = gate.MENU_FRAMES + 5

    # ---- C1 IDENTITY WRITE-BACK changes nothing (ops AND pixels); a CHANGED write does ----------
    base = gb.run(nfr, events, Probe(cells, table, gb.width),
                  pre_run=lambda pr: pr.verify_known(known))

    def identity(pr, f):
        pr.write_cells(pr.read_cells())                # every cell, the raw word included
    p1 = Probe(cells, table, gb.width)
    p1.on_frame_start(identity)
    p1.on_present(identity)
    same = gb.run(nfr, events, p1)
    check("C1 identity write-back at every frame start AND present: ops identical",
          same.ops == base.ops, "%s vs %s" % (format(same.ops, ","), format(base.ops, ",")))
    check("C1 ... and all %d presented frames byte-identical" % nfr, same.frames == base.frames)

    def mutate(pr, f):
        if f == k_mut:
            v = pr.read_cells(["viewangle"])["viewangle"]
            pr.write_cells({"viewangle": (v + ANGLE_TURN) & 0xFFFFFFFF})
    pm = Probe(cells, table, gb.width)
    pm.on_frame_start(mutate)
    mut = gb.run(nfr, events, pm)
    first = next((i for i, (a, b) in enumerate(zip(mut.frames, base.frames)) if a != b), None)
    check("C1 negative: a CHANGED write (viewangle + one turn) is caught at its frame",
          first == k_mut and mut.ops != base.ops, "first differing frame %s (written at %d)"
          % (first, k_mut))

    # ---- C2 PLANTED VALUES read back, sit where the layout says, and do what the program says ----
    # C2a WORD kind (an 8-nibble 16.16 number): plant a far, fractional viewpoint.
    tx, ty, ta = (1272 << 16) + 0x8000, (-724 << 16) + 0x4000, 0x2E000000   # inside E1M1
    got = {}

    def plant_view(pr, f):
        if f == k_mut:
            pr.write_cells({"viewx": tx, "viewy": ty, "viewangle": ta, **KEYS_UP})
            got["read"] = pr.read_cells(["viewx", "viewy", "viewangle"])
            got["jw"] = [pr.read_word(pr.jump_word("viewx", 0, i)) for i in range(8)]
            got["fw"] = [pr.read_word(pr.jump_word("viewx", 0, i) - 1) for i in range(8)]
            got["base"] = [pr.bases[pr.jump_word("viewx", 0, i)] for i in range(8)]
    p2 = Probe(cells, table, gb.width)
    p2.on_frame_start(plant_view)
    r2 = gb.run(k_mut + 1, [e for e in events if e.tic < k_mut * STANDALONE_POLLS], p2)
    check("C2a word: planted viewx/viewy/viewangle read back",
          got.get("read") == {"viewx": tx, "viewy": ty, "viewangle": ta}, str(got.get("read")))
    want_jw = [b | ((((tx & 0xFFFFFFFF) >> (4 * i)) & 0xF) << 6)
               for i, b in enumerate(got.get("base") or [0] * 8)]
    check("C2a word: viewx's 8 jump words are base | nibble<<6, flip words 0, bases kept",
          got.get("jw") == want_jw and got.get("fw") == [0] * 8,
          "jw %s" % [hex(v) for v in (got.get("jw") or [])][:3])
    d = px_diff(r2.frames[k_mut], orc.render(tx, ty, ta))
    check("C2a word: that frame IS the oracle's render of the planted viewpoint", d == 0,
          "%d px differ" % d)

    # C2b NIBBLE kind: mode=0 at frame 0 (the world, not the menu), kb_f=1 over frames 1..3.
    def plant_nib(pr, f):
        if f == 0:
            pr.write_cells({"mode": 0})
        elif f == 1:
            pr.write_cells({"kb_f": 1})
        elif f == 4:
            pr.write_cells({"kb_f": 0})
    p3 = Probe(cells, table, gb.width)
    p3.on_frame_start(plant_nib)
    views = []
    p3.on_present(lambda pr, f: views.append(pr.read_cells(["viewx", "viewy", "viewangle", "mode"])))
    r3 = gb.run(6, [], p3)
    dsim = onewalk.DoorSim()
    st = dsim.reset()
    ok_pix = ok_state = True
    for f in range(6):
        if 1 <= f < 4:
            st = dsim.step(st, {"forward": True})
        ok_state &= (views[f]["viewx"], views[f]["viewy"], views[f]["viewangle"],
                     views[f]["mode"]) == (st.x, st.y, st.angle, 0)
        ok_pix &= r3.frames[f] == orc.render(st.x, st.y, st.angle)
    check("C2b nibble: mode=0 planted at frame 0 -> a WORLD frame, byte-exact vs the oracle",
          r3.frames[0] == orc.render(orc.spawn.x, orc.spawn.y, orc.spawn.angle))
    check("C2b nibble: kb_f=1 planted -> 3 steps, state AND pixels = the oracle's, 6 frames",
          ok_pix and ok_state, "ends (%.1f, %.1f)" % (views[-1]["viewx"] / 65536,
                                                       views[-1]["viewy"] / 65536))

    # C2c RAW kind: kb_f's JUMP WORD written raw -- the whole word the nibble plant produces,
    #     base | 1 << 6 (a blocked build's cell has a base: see Probe._field) -- must be the same
    #     program run. MEASURED once (2026-09-26): writing the unblocked M1 layout instead, a bare
    #     1 << 6, into this pinned cell ended the run after ~1 frame (19,840,405 ops against
    #     125,870,339) -- the base is load-bearing, which is why the codec keeps it.
    def plant_raw(pr, f):
        w = pr.word_of("kb_f_jw")
        if f == 0:
            pr.write_cells({"mode": 0})
        elif f == 1:
            pr.write_word(w, pr.bases[w] | (1 << pr.dshift))
        elif f == 4:
            pr.write_cells({"kb_f_jw": pr.bases[w]})
    p4 = Probe(cells, table, gb.width)
    p4.on_frame_start(plant_raw)
    r4 = gb.run(6, [], p4)
    check("C2c raw: kb_f's jump word written raw = the nibble plant, pixels and ops",
          r4.frames == r3.frames and r4.ops == r3.ops,
          "ops %s vs %s" % (format(r4.ops, ","), format(r3.ops, ",")))

    # C2d BYTE kind: plant bytes into pclm at PRESENT (after the picture, before the M1 reset).
    # They must read back, sit at byte<<6, then be CLEARED BY THE PROGRAM'S OWN byte clear
    # (m1.zerobyte jumps through the stl byte table on the cell's value -- a byte in the wrong bits
    # would not come back as zero), and the frames after must equal an unplanted run's.
    blog = {}
    planted = (0xA5, 0x5A, 0xFF, 0x01)

    def zero_mode(pr, f):
        if f == 0:
            pr.write_cells({"mode": 0})

    def plant_byte(pr, f):
        if f == 1:
            pr.write_cells({"pclm": planted})
            blog["read"] = pr.read_cells(["pclm"])["pclm"]
            blog["jw"] = [pr.read_word(pr.jump_word("pclm", e)) for e in range(4)]
            blog["base"] = [pr.bases[pr.jump_word("pclm", e)] for e in range(4)]

    def after_reset(pr, f):
        if f == 2:
            blog["after"] = pr.read_cells(["pclm"])["pclm"]
    p5 = Probe(cells, table, gb.width)
    p5.on_frame_start(zero_mode)
    p5.on_present(plant_byte)
    p5.on_frame_start(after_reset)
    r5 = gb.run(4, [], p5)
    p6 = Probe(cells, table, gb.width)
    p6.on_frame_start(zero_mode)
    r6 = gb.run(4, [], p6)
    check("C2d byte: planted pclm bytes read back", blog.get("read") == planted, str(blog.get("read")))
    check("C2d byte: each byte sits at <<6 in its cell's jump word, the base kept",
          blog.get("jw") == [bb | (b << 6) for b, bb in zip(planted, blog.get("base") or [0] * 4)],
          "%s, bases %s" % ([hex(v) for v in blog.get("jw", [])],
                            [hex(v) for v in blog.get("base", [])]))
    check("C2d byte: the program's own M1 byte clear zeroed all four by the next frame",
          blog.get("after") == (0, 0, 0, 0), str(blog.get("after")))
    check("C2d byte: ... and every frame equals an unplanted run's", r5.frames == r6.frames)

    # ---- C4 THE OPS-PER-FRAME API: readings against EXACT per-frame counts by prefix runs ------
    def one(n):
        pz = Probe(cells, table, gb.width)
        pz.on_frame_start(zero_mode)
        return gb.run(n, [], pz), pz
    totals = [one(n)[0].ops for n in range(1, 5)]              # exact, through frames 0..n-1
    r7, p7 = one(4)
    exact = [totals[i + 1] - totals[i] for i in range(3)]      # frames 1..3, EXACT
    errs = [a - e for a, e in zip(p7.frame_ops()[1:4], exact)]
    check("C4 a run's total equals the same-length prefix run's (determinism)",
          r7.ops == totals[3], "%s vs %s" % (format(r7.ops, ","), format(totals[3], ",")))
    check("C4 every per-frame reading is within +/-2^18 of the EXACT count", all(
        abs(e) < OPS_GRANULARITY for e in errs),
        "exact %s, errors %s" % ([format(x, ",") for x in exact], errs))
    check("C4 negative: the same check at a claimed 2^10 granularity FAILS",
          not all(abs(e) < (1 << 10) for e in errs), "max |error| %s" % max(abs(e) for e in errs))

    # ---- C5 THE LEAN LOADER IS THE SHIPPED PROGRAM: replay what the ship-gate evidence recorded
    #      for these bytes (docs/ship-evidence/padB_gamespeed.log; padB.fjm == blocked27, sha256
    #      38b09a7331f4f52b), with NO probe writes, and require the totals to the op ---------------
    if gb.sha.startswith(RECORDED_SHA16):
        menu_only = [{} for _ in range(gate.MENU_FRAMES)]
        rc = gb.run(len(menu_only), GS.events_for(menu_only))
        check("C5 startup + 2 menu frames = the recorded calibration, to the op",
              rc.ops == RECORDED_CALIBRATION, "%s vs %s" % (format(rc.ops, ","),
                                                           format(RECORDED_CALIBRATION, ",")))
        per_run = GS.full_script(RECORDED_RUN, 100)
        rr = gb.run(len(per_run), GS.events_for(per_run))
        check("C5 gamespeed run %d replayed = the recorded total, to the op" % RECORDED_RUN,
              rr.ops == RECORDED_RUN_OPS and len(rr.frames) == len(per_run),
              "%s vs %s (%d frames, %.1f s)" % (format(rr.ops, ","), format(RECORDED_RUN_OPS, ","),
                                                len(rr.frames), rr.seconds))
        rr2 = gb.run(len(per_run), GS.events_for(GS.full_script(RECORDED_RUN + 1, 100)))
        check("C5 negative: a DIFFERENT run's script does not reproduce it",
              rr2.ops != RECORDED_RUN_OPS, format(rr2.ops, ","))
    else:
        check("C5 recorded totals exist only for sha256 %s..." % RECORDED_SHA16, False,
              "this binary is %s" % gb.sha[:16])

    print("")
    print("PROBE SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                                   "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


# ================================================================================================
# the demonstration (deliverable 2)
# ================================================================================================

def demo(fjm: Path, labels_path: Path) -> int:
    import gamespeed as GS
    import m2_std_gate as gate
    import onewalk
    orc = Oracle()
    cells = game_cells(orc.ndoors)
    table = LabelTable.load(labels_path, {c.label for c in cells.values()})
    gb = GameBinary(fjm)
    print("demo: %s (sha256 %s), labels %s" % (fjm.name, gb.sha[:16], Path(labels_path).name),
          flush=True)
    known = orc.known_pristine()
    menu = orc.menu_frame()
    ok = True

    # (a) READ the view state at every present of a scripted walk: gamespeed run 0's first 30
    #     frames, delivered as key events after the menu, exactly as m2_std_gate/gamespeed do
    n_walk = 30
    per_frame = [{} for _ in range(gate.MENU_FRAMES)] + GS.script(0)[:n_walk]
    events = GS.events_for(per_frame)
    keys_by_frame, enters = gate.held_per_frame(events, len(per_frame))
    p = Probe(cells, table, gb.width)
    seen = []
    p.on_present(lambda pr, f: seen.append(pr.read_cells()))       # EVERY game-tier cell
    r = gb.run(len(per_frame), events, p, pre_run=lambda pr: pr.verify_known(known))
    print("(a) %d frames, %s ops (exact); the probe's persisted state at each present (view, mode, "
          "5 key flags, 13 doors x 4 cells) vs the oracle (onewalk.DoorSim, m2_std_gate's order):"
          % (len(r.frames), format(r.ops, ",")))
    dsim = onewalk.DoorSim()
    st, mode, n_state, n_pix = dsim.reset(), 1, 0, 0
    for f in range(len(per_frame)):
        if enters[f]:
            mode ^= 1
        if mode == 0:
            st = dsim.step(st, keys_by_frame[f])
        g = seen[f]
        kd = keys_by_frame[f]
        want_s = {"viewx": st.x, "viewy": st.y, "viewangle": st.angle, "mode": mode,
                  "kb_f": int(bool(kd.get("forward"))), "kb_b": int(bool(kd.get("back"))),
                  "kb_l": int(bool(kd.get("turn_left"))), "kb_r": int(bool(kd.get("turn_right"))),
                  "kb_u": int(bool(kd.get("use"))),
                  "dstate": tuple(dsim.ds[si][0] for si in orc.door_order),
                  "ddir": tuple(dsim.ds[si][1] for si in orc.door_order),
                  "dsub": tuple(dsim.ds[si][2] for si in orc.door_order),
                  "dwait": tuple(dsim.ds[si][3] for si in orc.door_order)}
        diff = [k for k in want_s if g[k] != want_s[k]]
        s_ok = not diff
        pix = r.frames[f] == (orc.render(st.x, st.y, st.angle, orc.door_states_tuple(dsim.ds))
                              if mode == 0 else menu)
        n_state += s_ok
        n_pix += pix
        if f < 4 or f % 5 == 0 or f == len(per_frame) - 1 or not (s_ok and pix):
            print("   f%-3d %-5s %-4s probe (%9.3f,%9.3f,%08x)  oracle (%9.3f,%9.3f,%08x)  %s  %s"
                  % (f, "menu" if mode else "world",
                     "".join(k[0] for k in sorted(keys_by_frame[f]) if keys_by_frame[f][k]) or "-",
                     g["viewx"] / 65536, g["viewy"] / 65536, g["viewangle"],
                     st.x / 65536, st.y / 65536, st.angle,
                     "STATE-EXACT" if s_ok else "!! STATE DIFFERS in %s" % diff,
                     "BYTE-EXACT" if pix else "!! PIXELS DIFFER"), flush=True)
    print("   => state-exact %d/%d frames, pixels byte-exact %d/%d (menu frames vs m3_gate's menu)"
          % (n_state, len(per_frame), n_pix, len(per_frame)))
    ok &= n_state == len(per_frame) and n_pix == len(per_frame)

    # (b) INJECT a viewpoint at frame k: where gamespeed run 3 stands at its frame 70, keys up
    far = onewalk.DoorSim()
    s3 = far.reset()
    for kd in GS.script(3)[:70]:
        s3 = far.step(s3, kd)
    inj = (s3.x, s3.y, s3.angle)
    ds3 = orc.door_states_tuple(far.ds)
    kf = gate.MENU_FRAMES + 12
    per_frame_b = [{} for _ in range(gate.MENU_FRAMES)] + GS.script(0)[:12] + [{}] * 4
    ev_b = GS.events_for(per_frame_b)
    pb = Probe(cells, table, gb.width)
    pb.on_frame_start(lambda pr, f: pr.write_cells(
        {"viewx": inj[0], "viewy": inj[1], "viewangle": inj[2], **orc.door_pose(ds3)})
        if f == kf else None)
    after = []
    pb.on_present(lambda pr, f: after.append(pr.read_cells(["viewx", "viewy", "viewangle"])))
    rb = gb.run(len(per_frame_b), ev_b, pb)
    want = orc.render(*inj, dstate=ds3)
    d = px_diff(rb.frames[kf], want)
    later = all(rb.frames[f] == want and (after[f]["viewx"], after[f]["viewy"],
                                          after[f]["viewangle"]) == inj
                for f in range(kf, len(per_frame_b)))
    before = rb.frames[kf - 1] == r.frames[kf - 1]
    print("(b) injected run 3's frame-70 pose (%.3f, %.3f, %08x, doors %s) at frame %d, keys "
          "released:" % (inj[0] / 65536, inj[1] / 65536, inj[2], "".join("%x" % v for v in ds3), kf))
    print("   frame %d: %s; frames %d..%d stay on it, state-exact and byte-exact: %s; frame %d "
          "(before the write) equals run (a)'s: %s"
          % (kf, "BYTE-EXACT vs the oracle's render of that pose" if d == 0 else
             "!! %d px differ" % d, kf, len(per_frame_b) - 1, "yes" if later else "!! NO",
             kf - 1, "yes" if before else "!! NO"))
    ok &= d == 0 and later and before
    print("DEMO %s" % ("PASS" if ok else "FAIL"), flush=True)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fjm", default=str(DEFAULT_FJM))
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--stream", default="S2-probe")
    ap.add_argument("--selftest-offline", action="store_true",
                    help="only the controls that need no binary (the codec, C-1)")
    a = ap.parse_args()
    if a.selftest_offline:
        fails = []

        def check(name, cond, detail=""):
            print("  %-68s %s%s" % (name, "ok" if cond else "FAIL",
                                    ("  " + detail) if detail else ""), flush=True)
            if not cond:
                fails.append(name)
        codec_selftest(check)
        print("OFFLINE SELFTEST %s" % ("PASS" if not fails else "FAIL: " + ", ".join(fails)))
        return 1 if fails else 0
    if not (a.selftest or a.demo):
        ap.print_help()
        return 2
    # plan gamespeed's ten routes BEFORE taking the lock: ~75 s of oracle BFS that needs no binary
    import gamespeed as GS
    t = time.time()
    GS.script(0)
    print("  (gamespeed's routes planned in %.1f s, outside the binary lock)" % (time.time() - t),
          flush=True)
    with binary_lock(a.stream):
        rc = 0
        if a.selftest:
            rc |= selftest(Path(a.fjm), Path(a.labels))
        if a.demo:
            rc |= demo(Path(a.fjm), Path(a.labels))
        return rc


if __name__ == "__main__":
    sys.exit(main())
