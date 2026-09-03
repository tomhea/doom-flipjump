"""The popcount census predictor: price a label/address change WITHOUT a build-and-sweep.

THE COST MODEL (the campaign's hardest-won fact): a `wflip addr, value` site executes
max(1, popcount(value)) ops per visit -- one op per set bit of the resolved value, walked as a
chain. Chain DEDUP is space-only; execution walks every link. So for a change that alters only
resolved VALUES (an array moved to a denser address, a constant folded, a label placement), the
whole-program op delta is exactly

    sum over wflip sites:  visits(site) * (popcount_B(site) - popcount_A(site))

and every term is computable from two label-resolves (minutes, no .fjm needed) plus ONE per-op
IP histogram of the baseline (scratchpad/ca2_profile.py --bucket-bits 6). This is the tool that
un-blinds the sub-100k ideas the campaign's measurement floor killed.

MODES
  selftest              end-to-end on a small synthetic program: capture A and B, profile A,
                        predict B-A, then RUN B and require predicted == measured EXACTLY.
                        Includes the vacuity control predict(A,A) == 0 and refuses to pass if
                        the synthetic delta happens to be zero (a vacuous ground truth).
  capture --fjm X.fj... --out census.json.gz [-w 32]
                        assemble the given .fj files, recording every wflip site in insertion
                        order: (ordinal, base bit-address, popcount, cost).
  capture-doom --out census.json.gz [--stl-dual|--worktree] [--ptr-cell-bits N]
                        the deg-tier doom build with the same spy. HEAVY (a full assembly);
                        rule 1 applies -- one at a time.
  predict --a A.json.gz --b B.json.gz --hist hist.json
                        the join. hist must be a ca2_profile --out file with bucket_bits 6.

JOIN CONTRACT (v1): the two censuses must have the SAME op-stream shape -- equal length, joined
by ordinal. That is exactly the value-only change class this predicts; a change that adds or
removes ops fails the length assert and needs the sweep, as before.
"""
import argparse
import gzip
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------- census capture


def _spy_on_wflips(assembler_module):
    """Wrap BinaryData.insert_wflip_ops to record (base bit-address, popcount) per site, in
    insertion order. Returns (records, unhook). The base address is where the site's first op
    lands: segment first_address plus the words already emitted."""
    records = []
    binary_data_cls = assembler_module.BinaryData
    orig = binary_data_cls.insert_wflip_ops

    def spy(self, word_address, flip_value, return_address):
        base = self.first_address + len(self.fj_words) * self.memory_width
        pc = bin(flip_value).count("1")
        records.append((base, pc))
        return orig(self, word_address, flip_value, return_address)

    binary_data_cls.insert_wflip_ops = spy

    def unhook():
        binary_data_cls.insert_wflip_ops = orig

    return records, unhook


def capture_fj(fj_paths, out_path, memory_width=32, defines_file=None):
    """assemble the given program with the spy on; write the census. Returns the records."""
    import flipjump
    import flipjump.assembler.assembler as asm

    records, unhook = _spy_on_wflips(asm)
    try:
        with tempfile.TemporaryDirectory() as td:
            flipjump.assemble([Path(p) for p in fj_paths], Path(td) / "census.fjm",
                              memory_width=memory_width, print_time=False,
                              defines_file=defines_file)
    finally:
        unhook()
    if out_path:
        _write_census(out_path, fj_paths, records)
    return records


def _write_census(out_path, source_desc, records):
    payload = {
        "source": [str(p) for p in source_desc],
        "n_sites": len(records),
        "sites": [[base, pc] for base, pc in records],
    }
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    print(f"census -> {out_path}  ({len(records):,} wflip sites)")


def _read_census(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    return [(base, pc) for base, pc in payload["sites"]]


# ---------------------------------------------------------------------------- prediction


def predict(census_a, census_b, hist, hist_shift):
    """the join: ordinal-by-ordinal, visits from the baseline histogram at A's base address.

    Returns (predicted_delta, diagnostics). Asserts the v1 contract: equal site counts.
    A site whose baseline base-address has no histogram entry executed 0 times -- that is a
    real value (cold code), not a join failure."""
    if len(census_a) != len(census_b):
        raise SystemExit(
            f"JOIN REFUSED: {len(census_a):,} sites in A vs {len(census_b):,} in B. "
            "This predictor prices value-only changes; an op-stream shape change needs the sweep."
        )
    delta = 0
    contributors = []
    n_changed = n_moved = 0
    for ordinal, ((base_a, pc_a), (base_b, pc_b)) in enumerate(zip(census_a, census_b)):
        if base_a != base_b:
            n_moved += 1
        if pc_a == pc_b:
            continue
        n_changed += 1
        visits = hist.get(base_a >> hist_shift, 0)
        cost_a, cost_b = max(1, pc_a), max(1, pc_b)
        term = visits * (cost_b - cost_a)
        delta += term
        if term:
            contributors.append((abs(term), ordinal, base_a, cost_a, cost_b, visits, term))
    contributors.sort(reverse=True)
    diags = {"n_sites": len(census_a), "n_popcount_changed": n_changed,
             "n_base_moved": n_moved, "top": contributors[:20]}
    return delta, diags


def _report(delta, diags):
    print(f"sites            : {diags['n_sites']:,}")
    print(f"popcount changed : {diags['n_popcount_changed']:,}")
    print(f"base moved       : {diags['n_base_moved']:,}"
          + ("   (all visits keyed on A's addresses)" if diags["n_base_moved"] else ""))
    print(f"PREDICTED DELTA  : {delta:+,} ops for the profiled frame")
    if diags["top"]:
        print("top contributors (site ordinal, A-address, costA->costB, visits, ops):")
        for _absterm, ordinal, base_a, ca, cb, visits, term in diags["top"]:
            print(f"  #{ordinal:<9,} {hex(base_a):>14} {ca:>2}->{cb:<2} x {visits:>11,} = {term:+,}")


# ---------------------------------------------------------------------------- selftest

SELFTEST_PROG = """stl.startup
    hex.set 2, cnt, {iters:#x}
  loop_start:
    wflip flag+w, probe_target
    wflip flag+w, probe_target
    hex.dec 2, cnt
    hex.if0 2, cnt, done
    ;loop_start
  done:
    stl.loop

  flag: ;0
  cnt:  hex.vec 2, 0
    rep({shim_ops}, i) stl.fj 0, 0
  probe_target: ;0
"""


def _run_ops(fjm_path):
    """run to the stl.loop and return the interpreter's own op count."""
    from flipjump import run, FixedIO

    stats = run(Path(fjm_path), io_device=FixedIO(b""), print_time=False, print_termination=False)
    return stats.op_counter


def _profile_per_op(fjm_path, shift):
    """the ca2_profile hook at per-op resolution: ip is a bit-address, one op is dw bits."""
    from collections import Counter

    from flipjump import FixedIO
    from flipjump.interpreter.fjm_run import run as fjm_run_run

    class IPHistogram:
        def __init__(self):
            self.hist = Counter()

        def should_break(self, ip, op_counter):
            self.hist[ip >> shift] += 1
            return False

    h = IPHistogram()
    term = fjm_run_run(Path(fjm_path), io_device=FixedIO(b""), breakpoint_handler=h,
                       print_time=False)
    assert sum(h.hist.values()) == term.op_counter, "the hook missed ops -- histogram VACUOUS"
    return h.hist, term.op_counter


def selftest():
    """predicted == measured, to the op, on a program whose ground truth is two real runs."""
    import flipjump
    import flipjump.assembler.assembler as asm

    memory_width = 32
    shift = 6  # dw = 2*w = 64 bits per op
    iters = 20

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        def build(name, shim_ops):
            src = td / f"{name}.fj"
            src.write_text(SELFTEST_PROG.format(iters=iters, shim_ops=shim_ops), encoding="utf-8")
            records, unhook = _spy_on_wflips(asm)
            try:
                flipjump.assemble([src], td / f"{name}.fjm", memory_width=memory_width,
                                  print_time=False)
            finally:
                unhook()
            return records, td / f"{name}.fjm"

        census_a, fjm_a = build("a", 0)
        # find a shim that actually changes the probe address's popcount; a delta of zero would
        # make the ground-truth comparison vacuously pass, which this test refuses to do.
        for shim in (7, 5, 3, 9, 15, 1):
            census_b, fjm_b = build("b", shim)
            if len(census_b) == len(census_a) and any(
                pa != pb for (_, pa), (_, pb) in zip(census_a, census_b)
            ):
                break
        else:
            raise SystemExit("SELFTEST BROKEN: no shim changed any popcount -- ground truth vacuous")

        hist, ops_profiled = _profile_per_op(fjm_a, shift)
        ops_a = _run_ops(fjm_a)
        ops_b = _run_ops(fjm_b)
        assert ops_a == ops_profiled, "profiled run diverged from plain run of the same binary"
        measured = ops_b - ops_a
        if measured == 0:
            raise SystemExit("SELFTEST BROKEN: the variant measured identical -- ground truth vacuous")

        predicted, diags = predict(census_a, census_b, hist, shift)
        zero, _ = predict(census_a, census_a, hist, shift)

        # the join-refusal control: a shape-changed op stream must be REFUSED, never mispriced.
        try:
            predict(census_a[:-1], census_b, hist, shift)
        except SystemExit:
            refused = True
        else:
            refused = False

        print(f"sites: {len(census_a)}   changed: {diags['n_popcount_changed']}   "
              f"A ops: {ops_a:,}   B ops: {ops_b:,}")
        print(f"measured delta : {measured:+,}")
        print(f"predicted delta: {predicted:+,}")
        print(f"vacuity control: predict(A,A) = {zero:+,}")
        print("join-refusal   : " + ("refused, as it must" if refused else "ACCEPTED A BROKEN JOIN"))
        ok = predicted == measured and zero == 0 and refused
        print("SELFTEST " + ("PASSED -- prediction exact to the op" if ok else "FAILED"))
        return 0 if ok else 1


# ---------------------------------------------------------------------------- doom capture


def capture_doom(out_path, stl_choice, ptr_cell_bits):
    """the deg-tier build with the spy on. HEAVY: a full assembly, rule 1 applies."""
    argv = ["deg_with_stl.py"]
    if stl_choice:
        argv.append(stl_choice)
    if ptr_cell_bits:
        argv += ["--ptr-cell-bits", str(ptr_cell_bits)]
    saved_argv, sys.argv = sys.argv, argv

    import runpy

    import flipjump.assembler.assembler as asm

    records, unhook = _spy_on_wflips(asm)
    try:
        # deg_with_stl handles the stl selection and the defines file, then runs deg_gate,
        # which assembles (census recorded here) and gates 4 viewpoints (a free byte-exactness
        # check on the very build the census describes).
        runpy.run_path(str(ROOT / "scratchpad" / "oneshadow" / "deg_with_stl.py"),
                       run_name="__main__")
    finally:
        unhook()
        sys.argv = saved_argv
    _write_census(out_path, argv, records)


# ---------------------------------------------------------------------------- cli


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("selftest")
    cap = sub.add_parser("capture")
    cap.add_argument("--fjm", nargs="+", required=True, help=".fj source files, in order")
    cap.add_argument("--out", required=True)
    cap.add_argument("-w", type=int, default=32)
    capd = sub.add_parser("capture-doom")
    capd.add_argument("--out", required=True)
    capd.add_argument("--stl", choices=["stock", "worktree", "stl-dual"], default="stl-dual")
    capd.add_argument("--ptr-cell-bits", type=int, default=16)
    pred = sub.add_parser("predict")
    pred.add_argument("--a", required=True)
    pred.add_argument("--b", required=True)
    pred.add_argument("--hist", required=True, help="ca2_profile --out json, bucket_bits must be 6")
    args = ap.parse_args()

    if args.mode == "selftest":
        sys.exit(selftest())
    if args.mode == "capture":
        capture_fj(args.fjm, args.out, memory_width=args.w)
        return
    if args.mode == "capture-doom":
        choice = {"stock": None, "worktree": "--worktree", "stl-dual": "--stl-dual"}[args.stl]
        capture_doom(args.out, choice, args.ptr_cell_bits)
        return
    if args.mode == "predict":
        hist_payload = json.loads(Path(args.hist).read_text(encoding="utf-8"))
        if hist_payload.get("bucket_bits") != 6:
            raise SystemExit(f"hist bucket_bits is {hist_payload.get('bucket_bits')}, need 6 "
                             "(per-op resolution): re-run ca2_profile with --bucket-bits 6")
        hist = {int(k): v for k, v in hist_payload["hist"].items()}
        delta, diags = predict(_read_census(args.a), _read_census(args.b), hist, 6)
        _report(delta, diags)


if __name__ == "__main__":
    main()
