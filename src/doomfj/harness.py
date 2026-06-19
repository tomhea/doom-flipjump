"""Probe harness: assemble + run a FlipJump program, report op_counter / storage_mode / .fjm size.
Verified against flipjump 1.5.0 (native engine, storage_mode == 'flat')."""
from __future__ import annotations
import time
from pathlib import Path
import flipjump as fj

W = 32  # memory_width; 16.16 fits one word (DESIGN §1.2). Single source: config.py once M1 lands.

def assemble_fjm(fj_paths: list[str | Path], out_fjm: str | Path, *, flat_max_words: int | None = None) -> dict:
    """Assemble at w=32 with --werror (assemble default). Returns assemble time + .fjm size."""
    paths = [Path(p).resolve() for p in fj_paths]
    out = Path(out_fjm); out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble(paths, out, memory_width=W, print_time=False)      # warning_as_errors=True is the default
    return {"assemble_seconds": round(time.perf_counter() - t, 4), "fjm_bytes": out.stat().st_size}

def run_fjm(fjm_path: str | Path, *, flat_max_words: int | None = None):
    return fj.run(Path(fjm_path), print_time=False, print_termination=False, flat_max_words=flat_max_words)

def probe(fj_paths: list[str | Path], *, flat_max_words: int | None = None):
    """One-shot assemble+run; returns the TerminationStatistics (term.op_counter, term.storage_mode, ...)."""
    paths = [Path(p).resolve() for p in fj_paths]
    return fj.assemble_and_run(paths, memory_width=W, print_time=False, print_termination=False,
                               flat_max_words=flat_max_words)

def op_delta_vs_empty(fj_paths, empty_paths, **kw) -> int:
    """ops attributable to the program, minus an empty-loop baseline (DESIGN §11 / handoff §4)."""
    return probe(fj_paths, **kw).op_counter - probe(empty_paths, **kw).op_counter
