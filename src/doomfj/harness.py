"""Probe harness: assemble + run a FlipJump program, report op_counter / storage_mode / .fjm size.
Verified against flipjump 1.5.0 (native engine, storage_mode == 'flat')."""
from __future__ import annotations
import tempfile
import time
from pathlib import Path
import flipjump as fj

W = 32  # memory_width; 16.16 fits one word (DESIGN §1.2). Single source: config.py once M1 lands.

# ⚠ BUILD TIME vs ARTIFACT SIZE -- THE .fjm's LZMA PRESET, AND THIS IS ITS ONLY DEFINITION.
# flipjump 1.6.0 dropped the fast-mode flag (MODE_FAST / MF_HC4, 2026-08-20) for `lzma_preset` (0-9, faster->smaller;
# CLI --lzma-preset). The owner's decision A10 (the flipjump 1.6.0 plan, section 4), measured on blocked64:
#   * preset 1 for DAY-TO-DAY builds: 13.4 s to write against the fast mode's 17.8 s, the same size;
#   * preset 6 for SHIP builds: -10.8% file size against the fast mode. Presets 7, 8 and 9 measured -11.1%, -10.9% and -10.9%, no real
#     gain, and they need the fixed reader; preset 6 is readable by every reader.
# It is ENCODER-only: every preset is read by the same reader, so the program image does not change with it.
# The ship builds are scratchpad/12m/build_blocked.py's (docs/ship-gate.md 1b, through build_labeled.py): it writes
# SHIP_LZMA_PRESET unless told otherwise (--lzma-preset). Everything else writes FJM_LZMA_PRESET.
FJM_LZMA_PRESET = 1
SHIP_LZMA_PRESET = 6

def assemble_fjm(fj_paths: list[str | Path], out_fjm: str | Path, *, flat_max_words: int | None = None) -> dict:
    """Assemble at w=32 with --werror (assemble default). Returns assemble time + .fjm size."""
    paths = [Path(p).resolve() for p in fj_paths]
    out = Path(out_fjm); out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble(paths, out, memory_width=W, print_time=False,      # warning_as_errors=True is the default
                lzma_preset=FJM_LZMA_PRESET)
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
