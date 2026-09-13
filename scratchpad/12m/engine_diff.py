"""engine_diff -- differential test of two _fjcore.pyd builds on the run loop's EDGE CASES.

    python scratchpad/12m/engine_diff.py <pyd A> <pyd B>      # every case must agree, to the digit
    python scratchpad/12m/engine_diff.py --selftest <pyd A>   # R9: A vs a MUTATED A must be rejected

The game gates prove the common path (hundreds of millions of ops, pixels and op counts identical).
What they cannot reach is the rare per-op work the engine folds are rearranging: unaligned ips, the
op in the last word of the address space, jumps and flips into the garbage tail past the last
segment, in-segment words that happen to hold the garbage magic, IO ordering, the not-looping
self-flip, a start_ip past 2^32. Each case here runs a tiny hand-built w=32 program (flat limit 2^27,
which is the game's) in a FRESH PROCESS per engine and records the termination cause, the op count,
the error address, the IO transcript, the storage flags and a memory fingerprint. Two engines are
equivalent on a case only if every field matches.

The negative control mutates one field of arm B's report (ENGINE_DIFF_MUTATE=1 adds one to a case's
op count) and requires the tool to call the engines DIFFERENT."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

FULL = 1 << 27           # words in the 32-bit address space
MAGIC32 = 0xBB67AE85     # FLAT_GARBAGE_MAGIC32 (the 4-byte-cell garbage fill)


def build_cases():
    """each case: (name, width, flat_max_words, segments [(start, n)], words {addr: [values]},
    start_ip, input_bits, fingerprint word addresses)"""
    tail_word = FULL - 1000
    cases = []
    cases.append(("loop", 32, FULL, [(0, 8)], {0: [128, 0]}, 0, [], list(range(8))))
    cases.append(("self_mod", 32, FULL, [(0, 18)],
                  {0: [512, 128], 4: [513, 256], 8: [166, 128], 10: [514, 320]}, 0, [], list(range(18))))
    # op0 jumps to the UNALIGNED ip 129: the decode of words 4|5 at offset 1 is f=601, j=256
    cases.append(("unaligned_jump", 32, FULL, [(0, 24)],
                  {0: [600, 129], 4: [1202, 512, 0], 8: [602, 256]}, 0, [], list(range(24))))
    # a jump into the garbage tail past the last segment
    cases.append(("tail_jump", 32, FULL, [(0, 24)], {0: [600, tail_word * 32]}, 0, [], list(range(24))))
    # a flip into the garbage tail
    cases.append(("tail_flip", 32, FULL, [(0, 24)], {0: [tail_word * 32 + 3, 0]}, 0, [], list(range(24))))
    # the op in the LAST word of the address space: its jump word lies past the end
    cases.append(("last_word_op", 32, FULL, [(0, 32), (FULL - 1, 1)],
                  {0: [601, (FULL - 1) * 32], FULL - 1: [600]}, 0, [], list(range(32)) + [FULL - 1]))
    # an in-segment data word holding the garbage magic is real data
    cases.append(("magic_data", 32, FULL, [(0, 16)], {0: [8 * 32, 0], 8: [MAGIC32]}, 0, [], list(range(16))))
    # the op's OWN flip word is the magic (flips bit 5 of word MAGIC32>>5, made a real segment)
    cases.append(("magic_flip_word", 32, FULL, [(0, 8), (MAGIC32 >> 5, 1)],
                  {0: [MAGIC32, 0]}, 0, [], list(range(8)) + [MAGIC32 >> 5]))
    # the op's JUMP word is the magic: an unaligned ip whose decode is f=603, j=256 (a looping op)
    a = MAGIC32 >> 5
    cases.append(("magic_jump_word", 32, FULL, [(0, 24), (a, 3)],
                  {0: [600, MAGIC32], 8: [604, 256], a: [603 << 5, 256 << 5, 0]}, 0, [],
                  list(range(24)) + [a, a + 1, a + 2]))
    # IO: output 1 (ip 0), output 0 (ip 128), then the input op at ip 64 (range (38,102]) whose jump
    # word (word 3, base 128) receives the input bit at bit 6: 1 -> 192 (an op that returns to 64),
    # 0 -> 128 (output 0 again, back to 64, where the input is exhausted -> EOF). ops 0,128,64,192,
    # 64,192,64,128 = 8 counted; outputs [1,0,0]; consumed [1,1,0].
    cases.append(("io", 32, FULL, [(0, 24)], {0: [65, 128], 2: [0, 128], 4: [64, 64], 6: [604, 64]}, 0,
                  [1, 1, 0], list(range(24))))
    # a null-ip halt (j < 2w) that is NOT a self-loop
    cases.append(("null_ip", 32, FULL, [(0, 24)], {0: [601, 128], 4: [600, 0]}, 0, [], list(range(24))))
    # j == ip but f inside the op's own words: not a halt; the flip rewrites the jump word to an
    # unaligned ip whose decode flips into the tail -> a memory error, same address both engines
    cases.append(("self_flip_not_looping", 32, FULL, [(0, 24)], {0: [601, 128], 4: [161, 128]}, 0, [],
                  list(range(24))))
    # a start ip at 2^32: outside the 32-bit space
    cases.append(("start_ip_high", 32, FULL, [(0, 8)], {0: [128, 0]}, 1 << 32, [], list(range(8))))
    # the general (non-full-span) instantiations: the same limit at w=16, and w=32 under a small limit
    cases.append(("w16_loop", 16, FULL, [(0, 8)], {0: [64, 0]}, 0, [], list(range(8))))
    cases.append(("w32_small_limit", 32, 1 << 20, [(0, 18)],
                  {0: [512, 128], 4: [513, 256], 8: [166, 128], 10: [514, 320]}, 0, [], list(range(18))))
    return cases


def run_case(fjcore, case):
    name, w, limit, segs, words, start_ip, input_bits, fp_addrs = case
    from flipjump.utils.exceptions import IOReadOnEOF
    m = fjcore.Memory(w, flat_max_words=limit)
    for s, n in segs:
        m.add_segment(s, n)
    for addr, vals in words.items():
        m.set_words(addr, vals)
    out = []
    inp = list(input_bits)
    consumed = []

    def write_bit(b):
        out.append(1 if b else 0)

    def read_bit():
        if not inp:
            raise IOReadOnEOF("eof")
        b = inp.pop(0)
        consumed.append(b)
        return bool(b)

    cause, ops, err, last, paused = m.run(read_bit, write_bit, IOReadOnEOF, last_ops_length=0, start_ip=start_ip)
    if os.environ.get("ENGINE_DIFF_MUTATE") == "1" and name == "unaligned_jump":
        ops += 1
    fp = hashlib.sha256(",".join(str(m.get_word(a)) for a in fp_addrs).encode()).hexdigest()[:16]
    return {"cause": int(cause), "ops": int(ops), "error_address": (int(err) if err is not None else None),
            "output": out, "consumed": consumed, "storage": m.storage_mode, "cell_bytes": m.cell_bytes,
            "full_span": getattr(m, "flat_full_span", None), "fingerprint": fp,
            "words": {str(a): m.get_word(a) for a in fp_addrs[:8]}}


def child(pyd):
    spec = importlib.util.spec_from_file_location("flipjump.interpreter._fjcore", pyd)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["flipjump.interpreter._fjcore"] = mod
    from flipjump.interpreter import _fjcore
    assert Path(_fjcore.__file__).resolve() == Path(pyd).resolve(), _fjcore.__file__
    report = {"engine": str(Path(pyd).resolve()),
              "engine_sha": hashlib.sha256(Path(pyd).read_bytes()).hexdigest()[:16], "cases": {}}
    for case in build_cases():
        report["cases"][case[0]] = run_case(_fjcore, case)
    print("ENGINE_DIFF_REPORT " + json.dumps(report), flush=True)


def report_for(pyd, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, "-u", __file__, "--child", str(pyd)], capture_output=True,
                       text=True, env=env)
    for line in p.stdout.splitlines():
        if line.startswith("ENGINE_DIFF_REPORT "):
            return json.loads(line[len("ENGINE_DIFF_REPORT "):])
    sys.stderr.write(p.stdout[-2000:] + "\n" + p.stderr[-3000:] + "\n")
    raise SystemExit("no report from %s" % pyd)


def compare(ra, rb, quiet=False):
    """returns the list of (case, field, a, b) differences"""
    diffs = []
    for name, a in ra["cases"].items():
        b = rb["cases"][name]
        for k in a:
            if k == "full_span":
                continue  # the flag is the CHANGE under test, not a behaviour; reported, not compared
            if a[k] != b[k]:
                diffs.append((name, k, a[k], b[k]))
        if not quiet:
            print("  %-24s cause=%d ops=%-4d err=%-12s out=%s in=%s %s full_span A=%s B=%s  %s"
                  % (name, a["cause"], a["ops"], a["error_address"], a["output"], a["consumed"],
                     a["storage"], a["full_span"], b["full_span"],
                     "SAME" if not [d for d in diffs if d[0] == name] else "DIFFERENT"))
    return diffs


def main():
    if sys.argv[1] == "--child":
        return child(sys.argv[2])
    if sys.argv[1] == "--selftest":
        pyd = sys.argv[2]
        ra = report_for(pyd)
        rb = report_for(pyd, {"ENGINE_DIFF_MUTATE": "1"})
        diffs = compare(ra, rb, quiet=True)
        ok = any(d[0] == "unaligned_jump" and d[1] == "ops" for d in diffs)
        print("selftest: a mutated op count on one case is %s (%d differences)"
              % ("REJECTED" if ok else "NOT DETECTED -- the tool is blind", len(diffs)))
        rc = report_for(pyd)
        same = not compare(ra, rc, quiet=True)
        print("selftest: the same engine twice is %s" % ("IDENTICAL" if same else "NOT IDENTICAL -- nondeterministic?"))
        print("SELFTEST %s" % ("PASS" if ok and same else "FAIL"))
        return 0 if ok and same else 1
    a, b = sys.argv[1], sys.argv[2]
    ra, rb = report_for(a), report_for(b)
    print("A %s %s" % (ra["engine_sha"], ra["engine"]))
    print("B %s %s" % (rb["engine_sha"], rb["engine"]))
    diffs = compare(ra, rb)
    for d in diffs:
        print("  DIFF %s.%s: A=%r B=%r" % d)
    print("ENGINE_DIFF %s: %d cases, %d differences" % ("PASS" if not diffs else "FAIL", len(ra["cases"]), len(diffs)))
    return 0 if not diffs else 1


if __name__ == "__main__":
    raise SystemExit(main())
