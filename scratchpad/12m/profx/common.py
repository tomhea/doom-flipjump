"""profx shared pieces: paths, the WORK directory, loaders for the engine's dumps, the binary lock.

WORK holds everything big or derived (the instrumented engine, maps, dumps, traces). It is OUTSIDE
the repo tree: $PROFX_WORK, else <system temp>/profx. Only sources, the README and small reference
outputs live in scratchpad/12m/profx/.
"""
import gzip
import json
import os
import struct
import tempfile
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
W = 32                                   # memory width of the game binaries
POOL_BASE_WORD = 0x60000000 // W         # ship-gate 1b's --pool-base, as a word address


def work_dir():
    d = Path(os.environ.get("PROFX_WORK") or (Path(tempfile.gettempdir()) / "profx"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_fjm():
    return Path(os.environ.get("PROFX_FJM") or (ROOT / "build" / "doom_e1m1_blocked27.fjm"))


def default_labels():
    return Path(os.environ.get("PROFX_LABELS_TSV")
                or (ROOT / "scratchpad" / "12m" / "atlas" / "blocked27.labels.tsv.gz"))


# ------------------------------------------------------------------------------------ label table

_LAB = {}


def labels(path=None):
    """(sorted int64 word addresses, names) -- every label, macro-internal ones included"""
    path = Path(path or default_labels())
    key = str(path)
    if key not in _LAB:
        rows = []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                name, _, addr = line.rstrip("\n").rpartition("\t")
                if addr:
                    rows.append((int(addr) // W, name))
        rows.sort()
        _LAB[key] = (np.array([r[0] for r in rows], dtype=np.int64), [r[1] for r in rows])
    return _LAB[key]


def label_dict(path=None):
    """{name: BIT address}"""
    out = {}
    with gzip.open(Path(path or default_labels()), "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if addr:
                out.setdefault(name, int(addr))
    return out


# ------------------------------------------------------------------------------------ engine dumps

def load_sparse(path):
    """a histogram dump: (word addresses, counts), both int64"""
    raw = Path(path).read_bytes()
    nz = struct.unpack_from("<Q", raw, 0)[0]
    dt = np.dtype([("w", "<u4"), ("c", "<u8")])
    arr = np.frombuffer(raw, dtype=dt, offset=8, count=nz)
    return arr["w"].astype(np.int64), arr["c"].astype(np.int64)


def load_log(path):
    """the per-present log: array [n, 258] = ops at the last IO, output-bit ops, obj[0..255]"""
    raw = Path(path).read_bytes()
    n, rec, outside, out, rej = struct.unpack_from("<QQQQQ", raw, 0)
    log = np.frombuffer(raw, dtype=np.uint64, offset=40, count=n * rec).reshape(n, rec).astype(np.int64)
    return log, outside, out, rej


def load_marks(path):
    """the marker log: array [n, 34] = marker id, ops before the marker op, obj[0..31]"""
    raw = Path(path).read_bytes()
    n, rec = struct.unpack_from("<QQ", raw, 0)
    return np.frombuffer(raw, dtype=np.uint64, offset=16, count=n * rec).reshape(n, rec).astype(np.int64)


def load_trace(path):
    """(first traced op index, word address of every traced op)"""
    raw = Path(path).read_bytes()
    lo, n = struct.unpack_from("<QQ", raw, 0)
    return int(lo), np.frombuffer(raw, dtype=np.uint32, offset=16, count=n).astype(np.int64)


def objects():
    d = json.loads((work_dir() / "objects.json").read_text())
    return {int(k): v for k, v in d.items()}


def marks_meta():
    d = json.loads((work_dir() / "marks.json").read_text())
    return {int(k): v for k, v in d.items()}


def engine_env(env=None):
    """the environment the FJPROFX engine reads at its first flat allocation"""
    e = dict(os.environ if env is None else env)
    wd = work_dir()
    e["FJPROFX_MAP"] = str(wd / "map.txt")
    e["FJPROFX_LABELS"] = str(wd / "labels.u32")
    e["FJPROFX_MARKS"] = str(wd / "marks.txt")
    return e


def engine_pyd():
    return work_dir() / "engX" / "_fjcore.pyd"


# ------------------------------------------------------------------------------------ binary lock

class BinaryLock:
    """One stream runs the game binary at a time. O_CREAT|O_EXCL, our name inside, poll every 30 s
    for up to 40 minutes, delete on exit. `path=None` is a no-op (single-user use)."""

    def __init__(self, path, name, poll=30.0, timeout=2400.0):
        self.path = Path(path) if path else None
        self.name, self.poll, self.timeout = name, poll, timeout
        self.held = False

    def __enter__(self):
        if self.path is None:
            return self
        t0 = time.time()
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.time() - t0 > self.timeout:
                    raise SystemExit("binary lock %s still held after %.0f s -- giving up"
                                     % (self.path, self.timeout))
                try:
                    who = self.path.read_text(errors="replace").strip()
                except OSError:
                    who = "?"
                print("  lock held by %r -- waiting %.0f s" % (who, self.poll), flush=True)
                time.sleep(self.poll)
                continue
            with os.fdopen(fd, "w") as fh:
                fh.write(self.name + "\n")
            self.held = True
            print("  binary lock taken: %s (%s)" % (self.path, self.name), flush=True)
            return self

    def __exit__(self, *exc):
        if self.held:
            try:
                self.path.unlink()
                print("  binary lock released", flush=True)
            except OSError as e:
                print("  !! could not delete the lock %s: %s" % (self.path, e), flush=True)
            self.held = False
        return False
