"""M0 build: assemble the hello-world, run it, assert flat, emit build/metrics.json.
Grows into H6 (the full generators -> ordered assemble-list -> doom.fjm) in later milestones."""
from __future__ import annotations
import json
from pathlib import Path
from doomfj.harness import assemble_fjm, run_fjm

def build(fj_src="src/fj/hello.fj", out_fjm="build/hello.fjm", metrics="build/metrics.json") -> dict:
    m = assemble_fjm([fj_src], out_fjm)
    term = run_fjm(out_fjm)
    m["op_counter"] = term.op_counter
    m["storage_mode"] = str(term.storage_mode)
    # R4 guard: the program MUST run on the flat path.
    assert m["storage_mode"] == "flat", f"R4: storage_mode is {m['storage_mode']!r}, not flat"
    Path(metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(metrics).write_text(json.dumps(m, indent=2))
    return m

if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
