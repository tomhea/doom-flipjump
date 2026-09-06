"""Capture the FULL label table, including everything emitted in PASS 2.

`scratchpad/ca_labels.py` hooks `labels_resolve` and aborts at `emit_reset_part`, so it returns
PASS-1 labels only. That is cheap and it is what the restore-set tooling needs -- but it leaves the
whole pass-2 region unlabelled, and `hotpath` then has nothing to attribute those ops to.

That hole is not small. On the rung-0 binary, **9,726,044 ops of an 80,111,139-op two-frame walk
(12.14%) execute ABOVE the highest pass-1 label** -- in words 42,036,802..51,377,722, where the M1
self-reset part is emitted. Before the over-attribution guard those ops were silently credited to
`distscale`, the last top-level label, which is how FINDINGS AY came to claim a 12.14% macro that
did not exist (see BA).

This lets the build run to completion and captures labels from the LAST `labels_resolve` call, so
the reset part is included.

    python scratchpad/12m/labels2.py --out scratchpad/12m/_full_labels.tsv.gz
"""
import argparse
import gzip
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scratchpad/12m/_full_labels.tsv.gz")
    ap.add_argument("--fjm", default="build/labels2_scratch.fjm")
    a = ap.parse_args()

    import flipjump.assembler.assembler as asm
    from doomfj.build import build_wall_renderer

    grabbed = {}
    real = asm.labels_resolve

    def hook(ops, labels, memory_width, fjm_writer, **k):
        # keep the LAST call's labels -- pass 2 includes the reset part
        grabbed["labels"] = labels
        grabbed["mw"] = memory_width
        grabbed["n"] = grabbed.get("n", 0) + 1
        return real(ops, labels, memory_width, fjm_writer, **k)

    asm.labels_resolve = hook
    t0 = time.time()
    print("building the game tier to completion (both passes) ...", flush=True)
    try:
        build_wall_renderer(ROOT / a.fjm, tier="game")
    finally:
        asm.labels_resolve = real

    labels = grabbed.get("labels")
    if not labels:
        print("NO LABELS CAPTURED -- labels_resolve never ran", flush=True)
        return 1
    print("labels_resolve ran %d time(s); kept the last" % grabbed["n"], flush=True)

    out = ROOT / a.out
    n = 0
    with gzip.open(out, "wt", encoding="utf-8", newline="\n") as fh:
        for name, v in labels.items():
            try:
                addr = int(v)
            except (TypeError, ValueError):
                try:
                    addr = int(v.value)
                except (AttributeError, TypeError, ValueError):
                    continue
            fh.write("%s\t%d\n" % (name, addr))
            n += 1
    print("pass 2 in %ds: %s labels -> %s (%.1f MB)"
          % (int(time.time() - t0), format(n, ","), a.out, out.stat().st_size / 1e6), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
