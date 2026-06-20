"""M6 integration evidence (R2/R-1): probe the per-lookup op cost of the F3 trig idioms on the
M5-generated dispatch tables. Measures ops for K lookups vs 0 lookups (same table) -> ops/lookup, and
the implied @ (per-op cost) at this small-program scale. Writes build/m6-metrics.json.

Reproducible: `python scripts/m6_evidence.py`. read_cos = read_sin + one hex.add_constant (the #9
shared-table quarter-turn). All flat (R4)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.lut_generator import generate_trig_idioms_fj

N = 4096          # the real game trig size (16^3)
FRAC = 16
K = 256           # lookups to amortise


def _ops(idiom: str, nlookups: int) -> dict:
    body = [f"fs.{idiom} r, a" for _ in range(nlookups)] + ["r: hex.vec 8", "a: hex.vec 3, 0x123"]
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
            + generate_trig_idioms_fj("fs", N, FRAC) + "\n")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "p.fj"
        src.write_text(prog, encoding="utf-8")
        out = Path(d) / "p.fjm"
        fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
        term = fj.run(out, print_time=False, print_termination=False)
    return {"op_counter": term.op_counter, "storage_mode": str(term.storage_mode)}


def main() -> dict:
    # a 32-bit (8-nibble) per-result-nibble read = 8 dispatches; read_cos adds the +N/4 hex add.
    dispatches = {"read_sin": 8, "read_cos": 8}
    metrics = {"table_entries": N, "result_nibbles": 8, "lookups": K, "mode": "per_result_nibble"}
    for idiom in ("read_sin", "read_cos"):
        hi, lo = _ops(idiom, K), _ops(idiom, 0)
        per = (hi["op_counter"] - lo["op_counter"]) / K
        per_dispatch = per / dispatches[idiom]
        metrics[idiom] = {
            "ops_per_lookup": round(per, 1),
            "dispatches_per_lookup": dispatches[idiom],
            "ops_per_dispatch": round(per_dispatch, 1),
            "implied_at": round(per_dispatch / 4, 1),  # dispatch core ~= 4@ ⇒ @ ~= ops_per_dispatch/4
            "storage_mode": hi["storage_mode"],
        }
        assert hi["storage_mode"] == "flat", f"R4: {idiom} not flat"
    out = Path("build/m6-metrics.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
