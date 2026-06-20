"""M5 integration evidence (R2): assemble representative generated dispatch tables + the D3 deposit,
measure assemble time / .fjm size / storage_mode / per-lookup op cost. Writes build/m5-metrics.json
(archived to versions/). Reproducible: `python scripts/m5_evidence.py`.

Numbers feed the §1.2 span ledger (per-entry vs per-result-nibble span tradeoff, D4/R-3) and confirm
the dispatch core runs on the flat path (R4). All values come from tables.py (R6 SSOT)."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.tables import sine_table
from doomfj.lut_generator import (
    generate_dispatch_table_fj,
    generate_offset_deposit_table_fj,
)

N = 4096          # the design's trig table size (16^3, §2.1)
NLOOKUPS = 64     # lookups to amortise the per-lookup op cost


def _assemble_run(name: str, table_fj: str, body: list[str]) -> dict:
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + table_fj + "\n")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"{name}.fj"
        src.write_text(prog, encoding="utf-8")
        out = Path(d) / f"{name}.fjm"
        t = time.perf_counter()
        fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
        asm = time.perf_counter() - t
        size = out.stat().st_size
        term = fj.run(out, print_time=False, print_termination=False)
    return {"assemble_seconds": round(asm, 3), "fjm_bytes": size,
            "op_counter": term.op_counter, "storage_mode": str(term.storage_mode)}


def _lookup_body(label: str, result_nibbles: int) -> list[str]:
    body = []
    for k in range(NLOOKUPS):
        body += [f"{label}.lookup r, idx{k % 8}"]
    body += [f"r: hex.vec {result_nibbles}"]
    body += [f"idx{j}: hex.vec 3, {j * 509}" for j in range(8)]  # spread indices across the table
    return body


def main() -> dict:
    finesine = sine_table(N, 16, 32)  # 4096 x 32-bit, the SSOT trig kernel
    metrics = {"table_entries": N, "result_nibbles": 8, "nlookups": NLOOKUPS}

    per_entry = generate_dispatch_table_fj("fs_pe", finesine, index_nibbles=3, result_nibbles=8,
                                           mode="per_entry")
    metrics["per_entry"] = _assemble_run("fs_pe", per_entry, _lookup_body("fs_pe", 8))

    per_nibble = generate_dispatch_table_fj("fs_pn", finesine, index_nibbles=3, result_nibbles=8,
                                            mode="per_result_nibble")
    metrics["per_result_nibble"] = _assemble_run("fs_pn", per_nibble, _lookup_body("fs_pn", 8))

    dep = generate_offset_deposit_table_fj("dep")
    dep_body = []
    for k in range(NLOOKUPS):
        dep_body += [f"hex.set 2, dv, {hex(k % 256)}", "dep.deposit dv", "dep.readback rb"]
    dep_body += ["dv: hex.vec 2", "rb: hex.vec 2"]
    metrics["deposit"] = _assemble_run("dep", dep, dep_body)

    for k in ("per_entry", "per_result_nibble", "deposit"):
        assert metrics[k]["storage_mode"] == "flat", f"R4: {k} not flat"

    out = Path("build/m5-metrics.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
