"""heat_identity.py -- a BlockPool with no heat list must build the SAME .fjm as flipjump 1.5.1.

    python scratchpad/12m/heat_identity.py --new C:/Users/tomhe/Documents/flipjump-pr

tomhea/flipjump#363 adds `BlockPool(heat=)` (pin protection, M7 P1.1). This builds
`tablepool_gate.py`'s programs, two-pass (count, then place), at five knob sets -- uniform, spread,
width buckets + pin_broken, a span tight enough to break groups, and eviction by value -- with the
INSTALLED flipjump (the baseline, 1.5.1) and with the checkout given by --new under `heat=None` and
`heat={}`, and compares every .fjm's sha256.

CONTROL (R9): the --new side also builds each program with a heat list naming its busiest group's
last table; those builds must DIFFER from the baseline (or raise, when the hot group cannot get a
block), else "identical" would mean nothing. Each side runs in its own subprocess, so the two
flipjumps never share an interpreter.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = 32
POOL_BASE = 1 << 26
KNOBS = {
    "plain": {},
    "spread2": {"spread": 2, "spread_min_count": 4},
    "buckets+pin_broken": {"width_buckets": True, "max_slot_ops": 512, "pin_broken": True},
    "tight span": {"span_bits": 1 << 16},
    "evict by value": {"evict_by_value": True, "span_bits": 1 << 15},
}


def side(modes):
    sys.path.insert(0, str(HERE))
    import flipjump as fj
    from flipjump.assembler.preprocessor import BlockPool
    from tablepool_gate import PROGRAMS
    out = {"flipjump": os.path.dirname(fj.__file__)}
    for pname, source in PROGRAMS.items():
        for kname, knobs in KNOBS.items():
            for mode in modes:
                key = "%s | %s | heat %s" % (pname, kname, mode)
                with tempfile.TemporaryDirectory() as td:
                    t = Path(td)
                    (t / "s.fj").write_text(source, encoding="utf-8")
                    span = knobs.get("span_bits")
                    sites = []

                    class Recorder(BlockPool):
                        def reserve(self, *args, **kwargs):          # the --new side passes the path
                            if len(args) >= 5 and args[2] is not None:
                                sites.append((args[2], args[4]))
                            return super().reserve(*args, **kwargs)

                    counting = Recorder(W, POOL_BASE, span_bits=span)
                    fj.assemble([(t / "s.fj").resolve()], t / "c.fjm", memory_width=W, print_time=False,
                                table_pool=counting)
                    if mode == "hot":
                        from flipjump.assembler.preprocessor import heat_key
                        if not counting.counts:
                            continue
                        g = max(counting.counts, key=lambda k: (counting.counts[k], k))
                        last = heat_key([p for gg, p in sites if gg == g][-1])
                        occ = sum(1 for gg, p in sites if gg == g and heat_key(p) == last) - 1
                        extra = {"heat": {heat_key(g): [(last, occ, 16)]}}
                    else:
                        extra = {} if mode == "absent" else {"heat": None if mode == "None" else {}}
                    kw = {k: v for k, v in knobs.items() if k != "span_bits"}
                    width_hist = counting.width_hist if kw.get("width_buckets") else None
                    try:
                        placing = BlockPool(W, POOL_BASE, counts=counting.counts, widths=counting.widths,
                                            span_bits=span, width_hist=width_hist, **kw, **extra)
                    except Exception as e:                   # a hot group that cannot be placed raises
                        out[key] = "raised: %s" % str(e)[:60]
                        continue
                    fj.assemble([(t / "s.fj").resolve()], t / "o.fjm", memory_width=W, print_time=False,
                                table_pool=placing)
                    out[key] = "%s evicted %d" % (hashlib.sha256((t / "o.fjm").read_bytes()).hexdigest()[:16],
                                                  getattr(placing, "evicted_low_value", 0))
    print(json.dumps(out))


def run_side(modes, env):
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, __file__, "--side", ",".join(modes)], cwd=td, env=env,
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(r.stdout + r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--new", default=r"C:\Users\tomhe\Documents\flipjump-pr",
                    help="the flipjump checkout to compare against the installed one")
    ap.add_argument("--side", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.side:
        return side(a.side.split(","))
    old = run_side(["absent"], dict(os.environ))
    new = run_side(["None", "{}", "hot"], dict(os.environ, PYTHONPATH=a.new))
    print("BASELINE flipjump: %s" % old.pop("flipjump"))
    print("NEW flipjump:      %s" % new.pop("flipjump"))
    same = 0
    for key, got_old in old.items():
        base = key.rsplit(" | heat", 1)[0]
        for mode in ("None", "{}"):
            got = new["%s | heat %s" % (base, mode)]
            same += got == got_old
            print("  %-58s heat=%-4s baseline %s  new %s  %s"
                  % (base, mode, got_old, got, "SAME" if got == got_old else "DIFFERS"))
    total = 2 * len(old)
    print("IDENTITY %s: %d/%d builds byte-identical to the baseline"
          % ("PASS" if same == total else "FAIL", same, total))
    moved = sorted(k.rsplit(" | heat", 1)[0] for k, v in old.items()
                   if new.get("%s | heat hot" % k.rsplit(" | heat", 1)[0], v) != v)
    print("CONTROL %s: with a heat list naming each program's busiest group's last table, %d builds differ "
          "from the baseline or raise: %s" % ("PASS" if moved else "FAIL", len(moved), moved))
    return 0 if same == total and moved else 1


if __name__ == "__main__":
    sys.exit(main())
