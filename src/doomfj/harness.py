"""Probe harness: assemble + run a FlipJump program, report op_counter / storage_mode / .fjm size.
Verified against flipjump 1.5.0 (native engine, storage_mode == 'flat')."""
from __future__ import annotations
import tempfile
import time
from pathlib import Path
import flipjump as fj

W = 32  # memory_width; 16.16 fits one word (DESIGN §1.2). Single source: config.py once M1 lands.

# ⚠ BUILD TIME vs ARTIFACT SIZE -- ONE KNOB, AND THIS IS ITS ONLY DEFINITION.
# MEASURED 2026-08-20 on the shipped 314,505,544-byte program image: the .fjm's LZMA compression is
# 99.9% of the assembler's `create binary` phase, and the match finder is the whole cost.
#     False (flipjump's default, BT4/nice_len 64) .... 100.8 s to write, 21.8 MB
#     True  (MODE_FAST / MF_HC4) .................... . 7.5 s to write, 29.0 MB
# It is ENCODER-only: dict_size is untouched, the reader passes no dict size, so every existing
# .fjm still loads and a fast-written one is read by the unmodified reader.
# Default True because the thing being optimised is the ~13-minute edit-build-look loop. FLIP IT TO
# FALSE when cutting the distributable standalone .fjm, where 7 MB matters and 93 s does not.
FJM_LZMA_FAST = True

def assemble_fjm(fj_paths: list[str | Path], out_fjm: str | Path, *, flat_max_words: int | None = None) -> dict:
    """Assemble at w=32 with --werror (assemble default). Returns assemble time + .fjm size."""
    paths = [Path(p).resolve() for p in fj_paths]
    out = Path(out_fjm); out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble(paths, out, memory_width=W, print_time=False,      # warning_as_errors=True is the default
                lzma_fast=FJM_LZMA_FAST)
    return {"assemble_seconds": round(time.perf_counter() - t, 4), "fjm_bytes": out.stat().st_size}

def run_fjm(fjm_path: str | Path, *, flat_max_words: int | None = None):
    return fj.run(Path(fjm_path), print_time=False, print_termination=False, flat_max_words=flat_max_words)

def probe(fj_paths: list[str | Path], *, flat_max_words: int | None = None):
    """One-shot assemble+run; returns the TerminationStatistics (term.op_counter, term.storage_mode, ...).
    Assembles to a temp .fjm then runs, because flat_max_words is a *run* param (fj.assemble_and_run
    does not accept it)."""
    paths = [Path(p).resolve() for p in fj_paths]
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "probe.fjm"
        fj.assemble(paths, out, memory_width=W, print_time=False)
        return fj.run(out, print_time=False, print_termination=False, flat_max_words=flat_max_words)

def op_delta_vs_empty(fj_paths, empty_paths, **kw) -> int:
    """ops attributable to the program, minus an empty-loop baseline (DESIGN §11 / handoff §4)."""
    return probe(fj_paths, **kw).op_counter - probe(empty_paths, **kw).op_counter
