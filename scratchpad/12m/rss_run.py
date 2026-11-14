"""Run a command and record its wall time and PEAK memory (the README's "the build" row quotes them).

usage: python scratchpad/12m/rss_run.py <json out> -- cmd arg ...

Samples the command's whole process tree every 0.5 s with psutil: the sum of the tree's resident set (RSS, what
the box must hold) and of its private bytes (commit), and keeps each peak. On Windows it also reads the root
process's own kernel-kept PeakWorkingSet / PeakPagefileUsage at exit, which no sampling interval can miss -- the
JSON carries both, so a sampled peak far below the kernel's says the interval missed a spike. Exit code = the
command's.
"""
from __future__ import annotations

import json
import sys
import time

import psutil


def tree(p: psutil.Process):
    try:
        return [p] + p.children(recursive=True)
    except psutil.NoSuchProcess:
        return []


def main() -> int:
    if "--" not in sys.argv or sys.argv.index("--") != 2:
        raise SystemExit(__doc__)
    out, cmd = sys.argv[1], sys.argv[3:]
    t0 = time.time()
    root = psutil.Popen(cmd)
    peak_rss = peak_priv = 0
    samples = 0
    kernel = {}
    while root.poll() is None:
        rss = priv = 0
        for q in tree(root):
            try:
                mi = q.memory_info()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            rss += mi.rss
            priv += getattr(mi, "private", getattr(mi, "vms", 0))
        peak_rss, peak_priv = max(peak_rss, rss), max(peak_priv, priv)
        samples += 1
        try:                                   # the root's kernel peaks, read while it is alive (gone after exit)
            mi = root.memory_info()
            kernel = {"peak_wset": getattr(mi, "peak_wset", None), "peak_pagefile": getattr(mi, "peak_pagefile", None)}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        time.sleep(0.5)
    rc = root.returncode
    rec = {"cmd": cmd, "rc": rc, "seconds": round(time.time() - t0, 1), "samples": samples,
           "peak_tree_rss_gb": round(peak_rss / 2 ** 30, 2), "peak_tree_private_gb": round(peak_priv / 2 ** 30, 2),
           "root_kernel_peak_wset_gb": round(kernel["peak_wset"] / 2 ** 30, 2) if kernel.get("peak_wset") else None,
           "root_kernel_peak_pagefile_gb": (round(kernel["peak_pagefile"] / 2 ** 30, 2)
                                            if kernel.get("peak_pagefile") else None),
           "box_total_gb": round(psutil.virtual_memory().total / 2 ** 30, 1)}
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(rec, fh, indent=1)
    print("RSS_RUN", json.dumps(rec))
    return rc


if __name__ == "__main__":
    sys.exit(main())
