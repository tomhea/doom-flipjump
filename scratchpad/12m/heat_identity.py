"""heat_identity.py -- a BlockPool with no heat list must build the SAME .fjm as flipjump 1.5.1.

    python scratchpad/12m/heat_identity.py --base C:/Users/tomhe/Documents/flipjump-73e09c0 \
        --new C:/Users/tomhe/Documents/flipjump-151

tomhea/flipjump#363 adds `BlockPool(heat=)` (pin protection, M7 P1.1). This builds
`tablepool_gate.py`'s programs, two-pass (count, then place), at six knob sets -- uniform, spread,
width buckets + pin_broken, a span tight enough to break groups, and eviction by value at an aligned and
an unaligned pool base -- with the checkout given by --base (1.5.1 BEFORE #363: 73e09c0) and with the
checkout given by --new under `heat=None` and `heat={}`, and compares every .fjm's sha256.

WHICH CODE RAN, recorded and required (R9): both sides are named checkouts, each imported through its
own PYTHONPATH in its own subprocess. The run prints each side's git revision, whether its tree is
clean, the path its `flipjump` was imported from and the sha256 of its `preprocessor.py`, and FAILS
when a side imported a flipjump from anywhere else, when the two sides' preprocessors are the same
file (then "identical" compares a program with itself -- what this tool did once the installed
flipjump became 1.5.1 WITH #363), or when the baseline's BlockPool already accepts `heat`.

CONTROL (R9): the --new side also builds each program with a heat list naming its busiest group's
last table; those builds must DIFFER from the baseline (or raise, when the hot group cannot get a
block), else "identical" would mean nothing. Each side runs in its own subprocess, so the two
flipjumps never share an interpreter.
"""
import argparse
import hashlib
import inspect
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
    # a pool base NOT aligned to the biggest block: eviction's plain sum and the real layout differ
    "evict, unaligned base": {"evict_by_value": True, "span_bits": 1 << 15, "pool_base": POOL_BASE + 16 * 64},
}


def side(modes):
    sys.path.insert(0, str(HERE))
    import flipjump as fj
    from flipjump.assembler.preprocessor import BlockPool
    from tablepool_gate import PROGRAMS
    pre = Path(fj.__file__).resolve().parent / "assembler" / "preprocessor.py"
    out = {"flipjump": os.path.dirname(os.path.realpath(fj.__file__)),
           "preprocessor_sha256": hashlib.sha256(pre.read_bytes()).hexdigest(),
           "accepts_heat": "heat" in inspect.signature(BlockPool.__init__).parameters}
    if modes == ["probe"]:                   # which code this side runs, before anything is built
        print(json.dumps(out))
        return
    for pname, source in PROGRAMS.items():
        for kname, knobs in KNOBS.items():
            for mode in modes:
                key = "%s | %s | heat %s" % (pname, kname, mode)
                with tempfile.TemporaryDirectory() as td:
                    t = Path(td)
                    (t / "s.fj").write_text(source, encoding="utf-8")
                    span = knobs.get("span_bits")
                    base = knobs.get("pool_base", POOL_BASE)
                    sites = []

                    class Recorder(BlockPool):
                        def reserve(self, *args, **kwargs):          # the --new side passes the path
                            if len(args) >= 5 and args[2] is not None:
                                sites.append((args[2], args[4]))
                            return super().reserve(*args, **kwargs)

                    counting = Recorder(W, base, span_bits=span)
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
                    kw = {k: v for k, v in knobs.items() if k not in ("span_bits", "pool_base")}
                    width_hist = counting.width_hist if kw.get("width_buckets") else None
                    try:
                        placing = BlockPool(W, base, counts=counting.counts, widths=counting.widths,
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


def git(checkout, *args):
    r = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "(not a git checkout: %s)" % r.stderr.strip()[:60]


def provenance(label, checkout, got):
    """print which code a side ran; return the reasons it cannot serve as that side"""
    where = Path(got.pop("flipjump")).resolve()
    sha, heat = got.pop("preprocessor_sha256"), got.pop("accepts_heat")
    dirty = git(checkout, "status", "--porcelain", "--untracked-files=no", "--", "flipjump")
    print("%-8s %s: rev %s, %s; flipjump imported from %s; preprocessor.py sha256 %s; "
          "BlockPool(heat=) %s" % (label, checkout, git(checkout, "rev-parse", "--short", "HEAD"),
                                    "DIRTY" if dirty else "clean", where, sha[:16],
                                    "accepted" if heat else "absent"))
    bad = []
    if Path(checkout).resolve() not in where.parents:
        bad.append("%s imported flipjump from %s, not from %s" % (label, where, checkout))
    return bad, sha, heat


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="a flipjump checkout WITHOUT pin protection: 1.5.1 before #363 (73e09c0)")
    ap.add_argument("--new", help="the flipjump checkout with BlockPool(heat=)")
    ap.add_argument("--side", default=None, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.side:
        return side(a.side.split(","))
    if not (a.base and a.new):
        ap.error("--base and --new are both required: this compares two named checkouts")
    env_old, env_new = dict(os.environ, PYTHONPATH=a.base), dict(os.environ, PYTHONPATH=a.new)
    probe_old, probe_new = run_side(["probe"], env_old), run_side(["probe"], env_new)
    bad_old, sha_old, heat_old = provenance("BASELINE", a.base, dict(probe_old))
    bad_new, sha_new, heat_new = provenance("NEW", a.new, dict(probe_new))
    bad = bad_old + bad_new
    if sha_old == sha_new:
        bad.append("both sides run the same preprocessor.py -- identity would compare a program with itself")
    if heat_old:
        bad.append("the baseline's BlockPool already accepts heat -- it is not flipjump before #363")
    if not heat_new:
        bad.append("the new side's BlockPool does not accept heat -- the control cannot run")
    for reason in bad:
        print("PROVENANCE FAIL: " + reason)
    if bad:
        return 1
    print("PROVENANCE PASS: two different preprocessors, the baseline without heat, the new side with it")
    old = run_side(["absent"], env_old)
    new = run_side(["None", "{}", "hot"], env_new)
    for label, got, probe in (("BASELINE", old, probe_old), ("NEW", new, probe_new)):
        ran = {k: got.pop(k) for k in probe}
        if ran != probe:                     # the builds ran the code the probe named, or nothing counts
            print("PROVENANCE FAIL: the %s builds ran %s, the probe named %s" % (label, ran, probe))
            return 1
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
