"""Assemble a synthetic program and report TIME, PEAK RSS and the OUTPUT HASH.

The hash is the point. Every assembler change proposed here is meant to be EMISSION-NEUTRAL -- the
same .fjm, produced with less memory -- so the acceptance test is sha256 equality, not "it looked
fine". A change that speeds assembly and moves the hash is a change that broke the program.

⚠ AND IT SHIPS NEGATIVE CONTROLS (R9). --selftest asserts:
  1. the hash CHANGES when the program does (one extra `pad`) -- a hash check that cannot fail
     proves nothing;
  2. the DEBUG-LABEL skip is conditional, not a deletion. The assembler no longer builds the
     `:wflips:N` and `<path>---:start:` labels unless a debugging file was asked for, on the
     argument that nothing else can read them (both contain ':', which the lexer's identifier rule
     `[a-zA-Z_][a-zA-Z_0-9]*` can never produce). So: asking for a debugging file must still yield
     BOTH families, and the .fjm must be byte-identical either way.

    python scratchpad/asm_bench.py [--n 60000] [--tag baseline]
    python scratchpad/asm_bench.py --selftest
"""
import argparse
import hashlib
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import flipjump as fj                                                     # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from flipjump.utils.functions import load_debugging_labels                # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=60000)
ap.add_argument("--tag", default="run")
ap.add_argument("--selftest", action="store_true")
ap.add_argument("--phases", action="store_true", help="print the assembler per-phase timer")
ap.add_argument("--extra-pad", action="store_true", help="mutate the program (the negative control)")
args = ap.parse_args()


def program(n, extra_pad=False):
    """Shaped like the real emitted program's census: mostly raw ops and labels, a band-handler-like
    bit.if/output_bit mix, plus baked data -- so memory behaviour resembles the real thing."""
    body = ["stl.startup_and_init_all", ";p_end"]
    for i in range(n):
        body += [f"h{i}:",
                 f"    bit.if flag, h{i}_a, h{i}_b",
                 f"h{i}_a:", "    stl.output_bit 1", f"    ;h{i}_c",
                 f"h{i}_b:", "    stl.output_bit 0",
                 f"h{i}_c:"]
        if i % 8 == 0:
            body.append(f"    hex.xor_by 8, acc, {i & 0xFFFF}")
    body += ["p_end:", "stl.loop"]
    if extra_pad:
        body.append("pad 32768")
    body += ["flag: bit.vec 1, 0", "acc: hex.vec 8"]
    body += [f"d{i}: hex.vec 8, {(i * 2654435761) & 0xFFFFFFFF}" for i in range(n // 4)]
    return chr(10).join(body) + chr(10)


def peak_rss_sampler(stop, out):
    try:
        import psutil
    except ImportError:
        return
    p = psutil.Process()
    while not stop.is_set():
        out[0] = max(out[0], p.memory_info().rss)
        time.sleep(0.05)


def run(n, extra_pad=False, debug_path=None):
    tmp = Path(tempfile.mkdtemp(prefix="asmbench_"))
    src = tmp / "p.fj"
    src.write_text(program(n, extra_pad), encoding="utf-8")
    out = tmp / "p.fjm"
    peak = [0]
    stop = threading.Event()
    th = threading.Thread(target=peak_rss_sampler, args=(stop, peak), daemon=True)
    th.start()
    t0 = time.perf_counter()
    fj.assemble([src.resolve()], out, memory_width=W, print_time=args.phases,
                debugging_file_path=(tmp / debug_path) if debug_path else None)
    dt = time.perf_counter() - t0
    stop.set()
    th.join(timeout=1)
    h = hashlib.sha256(out.read_bytes()).hexdigest()[:16]
    if debug_path:
        return h, load_debugging_labels(tmp / debug_path)
    return dt, peak[0], h, out.stat().st_size, src.stat().st_size


if args.selftest:
    print("CONTROL 1: the hash must CHANGE when the program changes")
    _d, _r, h1, _s, _c = run(4000, False)
    _d, _r, h2, _s, _c = run(4000, True)
    print(f"  plain          {h1}")
    print(f"  +pad 32768     {h2}")
    ok = h1 != h2
    print(f"  {'ok -- the hash has teeth' if ok else 'FAIL -- the hash cannot detect a real change'}")

    print("\nCONTROL 2: the debug-label skip is CONDITIONAL, and cannot move the .fjm")
    h_dbg, labels = run(4000, False, debug_path="p.fj_debug")
    n_wflip = sum(1 for k in labels if k.startswith(":wflips:"))
    n_start = sum(1 for k in labels if k.endswith("---:start:"))
    same_fjm = h_dbg == h1
    print(f"  no debug file      .fjm {h1}")
    print(f"  with debug file    .fjm {h_dbg}   {len(labels):,} labels "
          f"({n_wflip:,} :wflips:, {n_start:,} ---:start:)")
    have_both = n_wflip > 0 and n_start > 0
    print(f"  labels still built when asked for ... "
          f"{'ok' if have_both else 'FAIL -- the skip DELETED them instead of skipping them'}")
    print(f"  .fjm identical either way ........... "
          f"{'ok' if same_fjm else 'FAIL -- the debug labels are reaching emission'}")
    ok = ok and have_both and same_fjm
    print(f"\n{'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)

dt, rss, h, fjm, srcb = run(args.n, args.extra_pad)
print(f"{args.tag:<14} n={args.n:<8} src={srcb/1e6:>6.1f}MB  {dt:>8.2f}s  "
      f"peakRSS={rss/1e9:>6.2f}GB  fjm={fjm:>10,}  sha={h}")
