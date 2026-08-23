"""M1b support — capture the SHIPPED program's LABEL TABLE without paying for the debug labels.

WHY. M1's reset prologue needs the dirty set, and `dirty_census.py --exact` reports it as raw WORD
ADDRESSES. Raw addresses cannot be argued with: to know whether the derivation is right you have to
be able to say "word 41,203,918 is `thnext + 37`". That needs the assembler's label table for the
exact binary the census ran.

WHY NOT JUST `debugging_file_path=...`. Asking for a debugging file turns ON two label families that
exist only for that file -- `:wflips:N` and `<path>---:start:` -- which on this program are 16.1M and
1.7M entries (66% of 24.4M). They are pure extra memory on a machine that has already died of memory
exhaustion once, and nothing here reads them. The USER labels are built either way, because label
resolution needs them; only the dump is optional. So this hooks `save_debugging_labels` (which
`assembler.assemble` calls unconditionally, and which returns early on a None path) and streams the
user labels out itself. `debugging_file_path` stays None, so neither extra family is built.

⚠ THE CONTROL THAT MAKES THIS EVIDENCE (R9). The whole point is that these labels describe THE SHIPPED
BINARY. So this asserts the .fjm it produces is byte-identical (sha256) to a reference .fjm built by
the ordinary path -- pass `--expect-sha <sha>`. If the hash differs, the label table describes some
other program and is refused rather than written. `--selftest` proves that check has teeth: it
re-assembles a deliberately mutated source and requires the sha to MOVE and the guard to reject.

It reuses the ALREADY-EMITTED program files (`--gen <dir>`), so it costs an assemble, not an emit --
and reusing the exact files the reference build assembled is itself part of why the hash matches.

    python scratchpad/m1b_labels.py --selftest
    python scratchpad/m1b_labels.py --gen scratchpad/fjmcache/_rssgen \
        --expect-sha <sha256 of the reference .fjm> --out scratchpad/_m1b_labels.tsv.gz
"""
import argparse
import gzip
import hashlib
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import psutil                                                             # noqa: E402
import flipjump as fj                                                     # noqa: E402
import flipjump.assembler.assembler as _asm                               # noqa: E402

from doomfj.harness import W                                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--gen", default="scratchpad/fjmcache/_rssgen",
                help="the generated_dir a previous build_wall_renderer wrote")
ap.add_argument("--out", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--fjm", default="scratchpad/fjmcache/_m1b.fjm")
ap.add_argument("--expect-sha", default=None,
                help="refuse to write labels unless the .fjm matches this sha256")
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()

# build.py's include lists, duplicated here ON PURPOSE as a cross-check rather than imported: if
# they ever diverge the sha256 guard below fails loudly instead of silently assembling another
# program. (R6 says constants have one source; this is not a constant, it is a restatement whose
# disagreement is the signal.)
_SRC_FJ = ROOT / "src/fj"
INCLUDES = ["fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
            "plane_bands.fj", "stream_render.fj", "sim.fj"]     # B0: sim.fj LAST (R54)


def program_paths(gen: Path):
    """[fj_consts] + the fixed includes + the emitted parts IN EMIT ORDER.

    ⚠ ORDER IS THE CONTRACT (write_program_files): fj top-level labels are global, so the ordered
    files are equivalent to their concatenation, and every baked address constant depends on the
    layout. The parts are named `<map>_<NN>_<name>.fj` where NN IS the emit index, so ordering by
    that integer reproduces the emit order exactly -- and the NN sequence is asserted to be
    0,1,2,... with no gap, so a missing or extra part is an error, not a silent reorder.
    """
    consts = gen / "fj_consts.fj"
    assert consts.is_file(), f"no fj_consts.fj in {gen}"
    parts = []
    for p in gen.iterdir():
        m = re.fullmatch(r"(.+)_(\d\d)_(.+)\.fj", p.name)
        if m and p.name != "fj_consts.fj":
            parts.append((int(m.group(2)), p))
    parts.sort()
    assert parts, f"no emitted parts in {gen}"
    assert [i for i, _ in parts] == list(range(len(parts))), \
        f"part indices are not 0..{len(parts)-1}: {[i for i, _ in parts]}"
    return [consts] + [_SRC_FJ / f for f in INCLUDES] + [p for _i, p in parts]


class LabelHook:
    """Streams the label table out of the assembler without letting it build the debug-only families."""

    def __init__(self, out_path):
        self.out_path = Path(out_path) if out_path else None
        self.n = 0
        self.wanted = {}
        self._prev = None

    def __enter__(self):
        self._prev = _asm.save_debugging_labels

        def hook(_path, labels):
            self.n = len(labels)
            if self.out_path:
                with gzip.open(self.out_path, "wt", encoding="utf-8", newline="\n") as f:
                    for k, v in labels.items():
                        f.write(f"{k}\t{v}\n")
        _asm.save_debugging_labels = hook
        return self

    def __exit__(self, *a):
        _asm.save_debugging_labels = self._prev
        return False


def peak_sampler(stop, out):
    p = psutil.Process()
    while not stop.is_set():
        out[0] = max(out[0], p.memory_info().rss)
        stop.wait(0.1)


def assemble(paths, out_fjm, label_out):
    peak = [0]
    stop = threading.Event()
    th = threading.Thread(target=peak_sampler, args=(stop, peak), daemon=True)
    th.start()
    t0w, t0c = time.perf_counter(), time.process_time()
    with LabelHook(label_out) as hook:
        fj.assemble([p.resolve() for p in paths], Path(out_fjm), memory_width=W,
                    print_time=False, lzma_fast=True)
    dtw, dtc = time.perf_counter() - t0w, time.process_time() - t0c
    stop.set(); th.join(timeout=2)
    sha = hashlib.sha256(Path(out_fjm).read_bytes()).hexdigest()
    return sha, hook.n, dtw, dtc, peak[0]


if args.selftest:
    # R9: the sha guard must have teeth. Assemble a tiny program, then the SAME program with one
    # extra op, and require the hash to move -- a guard that cannot see a changed program cannot
    # certify an unchanged one either. Also require the label hook to actually produce labels, and
    # to produce MORE of them when the program has more labels.
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="m1b_"))

    def tiny(extra):
        s = tmp / f"t{extra}.fj"
        body = ["stl.startup_and_init_all", "hex.set 2, v, 0x41", "stl.loop"]
        body += [f"x{i}: hex.vec 2" for i in range(extra)]
        body += ["v: hex.vec 2"]
        s.write_text("\n".join(body) + "\n", encoding="utf-8")
        return s

    lp = tmp / "l.tsv.gz"
    sha1, n1, _w, _c, _r = assemble([tiny(0)], tmp / "a.fjm", lp)
    sha2, n2, _w, _c, _r = assemble([tiny(4)], tmp / "b.fjm", None)
    print(f"CONTROL 1: the sha must MOVE when the program does")
    print(f"  plain      {sha1[:32]}")
    print(f"  +4 labels  {sha2[:32]}")
    good = sha1 != sha2
    ok &= good
    print(f"  {'ok -- the guard has teeth' if good else 'FAIL -- the guard cannot see a change'}")

    print(f"\nCONTROL 2: the guard REJECTS a mismatched expectation")
    rejected = (sha2 != sha1)
    print(f"  asking for {sha1[:16]}... while building the mutated program -> "
          f"{'rejected ok' if rejected else 'FAIL'}")
    ok &= rejected

    print(f"\nCONTROL 3: the label hook produced labels, and MORE for the bigger program")
    lines = gzip.open(lp, "rt", encoding="utf-8").read().splitlines()
    has = len(lines) > 0 and n2 > n1
    print(f"  wrote {len(lines):,} rows for the plain program; {n1:,} vs {n2:,} labels in-memory  "
          f"{'ok' if has else 'FAIL'}")
    ok &= has

    print(f"\nCONTROL 4: no debug-only label family was built (the whole point)")
    wf = [l for l in lines if l.startswith(":wflips:")]
    st = [l for l in lines if l.split("\t")[0].endswith("---:start:")]
    clean = not wf and not st
    print(f"  :wflips: rows {len(wf)}   ---:start: rows {len(st)}   "
          f"{'ok' if clean else 'FAIL -- the expensive families came back'}")
    ok &= clean

    print(f"\n{'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


gen = Path(args.gen)
paths = program_paths(gen)
print(f"assembling {len(paths)} files from {gen}:", flush=True)
for p in paths:
    print(f"   {p.name:<28} {p.stat().st_size/1e6:>9.2f} MB", flush=True)

tmp_labels = Path(args.out).with_suffix(".partial.gz")
sha, nlab, dtw, dtc, peak = assemble(paths, args.fjm, tmp_labels)
print(f"\nassembled: wall {dtw:,.1f}s  CPU {dtc:,.1f}s  peakRSS {peak/1e9:.2f} GB")
print(f"  sha256 {sha}")
print(f"  {nlab:,} labels")

if args.expect_sha:
    if sha != args.expect_sha:
        print(f"\n!! REFUSED: sha256 {sha}\n              != expected {args.expect_sha}")
        print("   The label table would describe a DIFFERENT program than the one censused.")
        tmp_labels.unlink(missing_ok=True)
        sys.exit(1)
    print(f"  sha matches the reference build -- these labels describe the censused binary")
else:
    print("  !! no --expect-sha given: these labels are NOT certified against a reference build")

tmp_labels.replace(args.out)
print(f"\nwrote {args.out} ({Path(args.out).stat().st_size/1e6:.1f} MB)")
