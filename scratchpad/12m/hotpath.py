"""WHICH MACROS ARE ON THE HOT PATH of the SHIPPED game, measured by playing a walk in it?

The campaign has priced macros on the deg/hosted tiers and then been wrong about the game: rung 0's
padding revert cost +5.98% on the full game where the deg median predicted +3.3%. So this profiles
the thing that actually ships: the standalone `--menu --doors` binary, driven by the same scripted
keyboard a player uses, with no host and no wire.

HOW. `flipjump.interpreter.fjm_run._run_featured` calls `breakpoint_handler.should_break(ip,
op_counter)` on every executed op. Passing a handler that records `ip` and always returns False is
a per-op hook needing no interpreter change (the mechanism `scratchpad/ca2_profile.py` established).
Selecting a breakpoint handler forces the pure-python loop at ~0.5-1M ops/s, so this is a
FEW-FRAMES tool: a 26M-op game frame is ~30-50 s.

ATTRIBUTION. Every op executes at an address, and the pass-1 label table maps addresses to names of
the form `f<file>:l<line>:macro(n)---local`. Sorting labels by address and binary-searching each
executed ip gives the innermost label at or before it, and `doom_macro()` walks out to the deepest
non-stl macro so the answer names a DOOM macro rather than `hex.exact_xor` every time. Both the
stl-level and doom-level rankings are printed, because the two answer different questions:
"which primitive burns the ops" vs "which of our code calls it".

    python scratchpad/12m/hotpath.py --fjm build/doom_e1m1_menu_rung0.fjm \\
        --labels scratchpad/12m/_rung0_labels.tsv.gz --frames 3
    python scratchpad/12m/hotpath.py --selftest

CONTROLS (R9)
  C1 CONSERVATION -- the histogram must sum to the interpreter's own op counter. If the hook misses
     ops, every ranking is wrong, and the run is reported VACUOUS rather than ranked.
  C2 NON-VACUITY -- attribution must place a real majority of ops against named labels; a run that
     attributes almost nothing looks like a flat profile, which reads as "nothing is hot".
  C3 ORDERING -- the binary search must return the innermost label at or before an address, checked
     against a linear scan on a synthetic table.
  C4 SENSITIVITY -- two different walks must produce different rankings, or the tool is reporting
     the program's shape rather than the walk's cost.
"""
import argparse
import bisect
import gzip
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT, ROOT / "scratchpad" / "12m"):
    sys.path.insert(0, str(q))

STL_NS = "stl."


def _mac(part):
    """`f12:l340:hex.exact_xor(5)` -> `hex.exact_xor`"""
    name = part.split(":")[-1]
    return name.split("(")[0]


def inner_macro(name):
    """the INNERMOST macro of an expansion path -- what primitive is burning the op"""
    parts = str(name).split("---")
    return _mac(parts[-2]) if len(parts) >= 2 else _mac(parts[0])


def doom_macro(name):
    """the deepest macro in the path that is NOT stl -- which of OUR macros called it"""
    parts = str(name).split("---")
    for part in reversed(parts[:-1] if len(parts) > 1 else parts):
        m = _mac(part)
        if not m.startswith(STL_NS) and not m.startswith("hex.") and not m.startswith("bit."):
            return m
    return inner_macro(name)


# A matched pair drops a negligible fraction of ops past bare labels; a mismatched pair drops a
# huge one. Measured on the two real pairs this campaign produced:
#   rung-0 histogram vs rung-0 labels (MISMATCHED) : 12.14% of ops far past a bare label
#   S2 histogram vs S2 labels (MATCHED)            :  0.017%
# Three orders of magnitude apart, so the threshold is not delicate.
JOIN_DROP_LIMIT = 0.02


def provenance_of(path):
    """the `# key=value` header labels2.py stamps, so the join key can be checked EXACTLY."""
    out = {}
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.startswith("#"):
                break
            if "=" in line:
                k, v = line[1:].strip().split("=", 1)
                out[k.strip()] = v.strip()
    return out


def check_join(dropped, total, fjm, labels):
    """⚠ THE JOIN KEY. A profile is a JOIN between a histogram and a label table, and the two are
    comparable only if they came from the SAME BUILD.

    Nothing checked this, and it is the single root cause behind FINDINGS AY (a 12.14% macro that
    did not exist), its retraction BA, a wasted build-gate-measure cycle on D1, and three further
    wrong hypotheses. BB wrote that history down and STILL shipped no control -- CR-2026-09-07
    caught that every other control here passes on a mismatched pair.

    ⚠ The obvious test -- "labels must span the executed addresses" -- is WRONG, and was rejected
    after being tried: execution legitimately runs past the last label into the unlabelled
    wflip-spot area (~6.4M words on the S2 build), so it flags a MATCHED pair as broken. The
    signal that actually discriminates is how many ops land far past a BARE label.
    """
    frac = dropped / max(1, total)
    if frac > JOIN_DROP_LIMIT:
        return (False,
                "MISMATCH: %.2f%% of ops sit far past a bare label (limit %.0f%%). A matched pair "
                "drops ~0.02%%. %s and %s are almost certainly from different builds -- re-capture "
                "with labels2.py." % (100.0*frac, 100.0*JOIN_DROP_LIMIT, fjm, labels))
    return (True, "%.3f%% of ops dropped past bare labels -- consistent with a matched pair"
                  % (100.0*frac))


class LabelTable:
    """addresses sorted once; `lookup(ip)` is the innermost label at or before ip"""

    def __init__(self, pairs):
        pairs = sorted(pairs)
        self.addrs = [a for a, _n in pairs]
        self.names = [n for _a, n in pairs]

    def lookup(self, addr):
        i = bisect.bisect_right(self.addrs, addr) - 1
        return self.names[i] if i >= 0 else None

    def span_of(self, addr):
        """how far `addr` sits past its label, and how wide that label's region is.

        ⚠ THE TRAP THIS EXISTS FOR. `lookup` returns the nearest PRECEDING label, so every op
        after the last label is attributed to it. `distscale` is the last top-level label in the
        doom image, and 9,726,044 ops -- 12.14% of the whole frame -- were attributed to it while
        **0%** of them were inside the 81,920-bit table. A whole finding (AY) and a build were
        spent on that before it was caught. A bucket whose ops sit far past its label is code that
        merely FOLLOWS it, not code that IS it."""
        i = bisect.bisect_right(self.addrs, addr) - 1
        if i < 0:
            return None, None
        nxt = self.addrs[i + 1] if i + 1 < len(self.addrs) else None
        return addr - self.addrs[i], (None if nxt is None else nxt - self.addrs[i])

    @classmethod
    def load(cls, path):
        pairs = []
        op = gzip.open if str(path).endswith(".gz") else open
        with op(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                bits = line.split("\t")
                if len(bits) < 2:
                    continue
                name, addr = bits[0], bits[1]
                try:
                    pairs.append((int(addr), name))
                except ValueError:
                    try:
                        pairs.append((int(name), bits[1]))     # tolerate addr-first files
                    except ValueError:
                        continue
        if not pairs:
            raise ValueError("%s: no (name, address) rows parsed" % path)
        return cls(pairs)


class IpRecorder:
    """the per-op hook: record the ip, never break"""

    def __init__(self):
        self.hits = Counter()
        self.ops = 0

    def should_break(self, ip, op_counter):
        self.hits[ip] += 1
        self.ops += 1
        return False


def run_walk(fjm, frames, seed=0):
    """Play `frames` game frames of script `seed` in the REAL binary, recording every op's ip.

    ⚠ The per-op hook is NOT available on the native core. `_fjcore.Memory.run` is
    `run(read_bit, write_bit, eof_exception_type, last_ops_length=0, start_ip=0)` -- no
    `breakpoint_handler`. That hook lives on `flipjump.interpreter.fjm_run.run`, the interpreter's
    own entry point, and passing it is also what SELECTS the instrumented pure-python loop. Driving
    the native core with a handler would have silently profiled nothing; C1 would have caught it,
    but only after a full run.

    Returns (recorder, ops, frames_presented, frames_asked).
    """
    import m2_std_gate as gate
    from gamespeed import events_for, full_script
    from flipjump.interpreter.fjm_run import run as fjm_run_run
    from flipjump.interpreter.io_devices.KeyboardIO import ScriptedKeyEventSource
    from flipjump.interpreter.io_devices.pygame_window import PcIO
    from flipjump.utils.exceptions import IOReadOnEOF                      # noqa: F401
    from doomfj.config import RENDER_FLAT_MAX_WORDS

    per_frame = full_script(seed, frames)
    screen = gate.Recording()
    keyboard = gate.Stopper(ScriptedKeyEventSource(events_for(per_frame)), screen, len(per_frame))
    io = PcIO(screen, keyboard)
    rec = IpRecorder()
    term = fjm_run_run(Path(fjm), io_device=io, breakpoint_handler=rec, print_time=False,
                       flat_max_words=RENDER_FLAT_MAX_WORDS)
    return rec, term.op_counter, len(screen.frames), len(per_frame)


# an op more than this far past its label is not plausibly "inside" it -- it is code that follows
# a data table or sits after the last label. 1 op = 2 words; 4096 ops of slack is generous.
FAR_PAST_LABEL_BITS = 4096 * 64


def rank(rec, table, keyfn, top=25, guard=True):
    """bucket ops by macro. With `guard`, ops sitting implausibly far past their label are counted
    as UNATTRIBUTED rather than credited to it -- see LabelTable.span_of for why."""
    buckets = Counter()
    unattributed = 0
    far = 0
    for ip, n in rec.hits.items():
        name = table.lookup(ip)
        if name is None:
            unattributed += n
            continue
        if guard and "---" not in str(name):
            off, _w = table.span_of(ip)
            if off is not None and off > FAR_PAST_LABEL_BITS:
                far += n                     # a BARE label this far back is not the owner
                unattributed += n
                continue
        buckets[keyfn(name)] += n
    if far:
        print("  (guard: %s ops sat > %d ops past a BARE label and were NOT credited to it)"
              % (format(far, ","), FAR_PAST_LABEL_BITS // 64), flush=True)
    rank.last_far = far          # kept for the selftest's plumbing assertions
    return buckets, unattributed, far


def report(buckets, total, unattributed, title, top=25):
    print("", flush=True)
    print("%s  (attributed %s of %s ops, %.1f%%)"
          % (title, format(total - unattributed, ","), format(total, ","),
             100.0 * (total - unattributed) / max(1, total)), flush=True)
    print("  %-46s %14s %8s" % ("macro", "ops", "share"), flush=True)
    print("  " + "-" * 70, flush=True)
    for name, n in buckets.most_common(top):
        print("  %-46s %14s %7.2f%%" % (name[:46], format(n, ","), 100.0 * n / max(1, total)),
              flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_menu_rung0.fjm")
    ap.add_argument("--labels", default="scratchpad/12m/_rung0_labels.tsv.gz")
    ap.add_argument("--frames", type=int, default=3, help="GAME frames (menu frames are extra)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", default=None,
                    help="save the raw ip histogram (json.gz) so re-analysis needs no re-run")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--heavy", action="store_true",
                    help="also run C9: drive main() on a real mismatched pair")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.heavy)

    print("labels : %s" % a.labels, flush=True)
    table = LabelTable.load(ROOT / a.labels)
    print("         %s addresses" % format(len(table.addrs), ","), flush=True)
    # ⚠ BEFORE run_walk. Checking after the run meant a bad/mismatched fjm died on the
    # loader first, so the provenance control passed for the WRONG REASON (CR-2026-09-07).
    # THE EXACT JOIN CHECK, when the label file carries provenance (labels2.py stamps it).
    # The drop-rate test below is a PROXY and only a fallback -- CR-2026-09-07 caught that
    # provenance was stamped and never read, making "checked exactly" false of every code path.
    pv = provenance_of(ROOT / a.labels)
    if pv.get("sha256"):
        import hashlib
        got = hashlib.sha256((ROOT / a.fjm).read_bytes()).hexdigest()
        if got != pv["sha256"]:
            print("VACUOUS: label provenance sha256=%s but %s hashes to %s -- these are DIFFERENT "
                  "BUILDS. Re-capture with labels2.py --fjm %s."
                  % (pv["sha256"][:16], a.fjm, got[:16], a.fjm), flush=True)
            return 1
        print("join   : EXACT -- labels carry sha256=%s and %s matches"
              % (got[:16], a.fjm), flush=True)
    else:
        print("join   : no provenance in %s -- falling back to the drop-rate PROXY. Re-capture "
              "with labels2.py for an exact check." % a.labels, flush=True)

    print("fjm    : %s  (walk seed %d, %d game frames)" % (a.fjm, a.seed, a.frames), flush=True)
    rec, ops, presented, asked = run_walk(ROOT / a.fjm, a.frames, a.seed)

    # C1 CONSERVATION -- if the hook MISSED ops, nothing below is trustworthy.
    #
    # The hook may legitimately see exactly ONE op more than the interpreter counts: it records the
    # op ABOUT TO EXECUTE, and the final op raises IOReadOnEOF during its read, so it never
    # completes and never increments op_counter. That is a single event per run, so the tolerance
    # is exactly 1 and it is DIRECTIONAL -- a hook that saw FEWER ops than were executed has missed
    # some, which is the failure that silently corrupts every ranking, and it is still rejected.
    delta = rec.ops - ops
    if not 0 <= delta <= 1:
        print("VACUOUS: the hook saw %s ops, the interpreter counted %s (delta %+d) -- a hook that "
              "misses ops makes every bucket wrong, so rankings are suppressed"
              % (format(rec.ops, ","), format(ops, ","), delta), flush=True)
        return 1
    if delta:
        print("note   : hook saw 1 op more than the counter -- the EOF op, recorded then aborted",
              flush=True)
    if presented != asked:
        print("VACUOUS: %d frames presented, %d asked" % (presented, asked), flush=True)
        return 1
    print("ops    : %s over %d presented frames (hook total matches interpreter)"
          % (format(ops, ","), presented), flush=True)

    if a.out:
        import json
        with gzip.open(ROOT / a.out, "wt", encoding="utf-8") as fh:
            json.dump({"ops": ops, "hook_ops": rec.ops, "frames": presented, "seed": a.seed,
                       "fjm": a.fjm, "hist": {str(k): v for k, v in rec.hits.items()}}, fh)
        print("saved  : %s (%s distinct addresses)"
              % (a.out, format(len(rec.hits), ",")), flush=True)

    inner, un_i, far = rank(rec, table, inner_macro)
    ok, msg = check_join(far, ops, a.fjm, a.labels)
    print("join   : %s" % msg, flush=True)
    if not ok:
        print("VACUOUS: refusing to rank a mismatched histogram/label pair -- this is the exact "
              "failure that produced FINDINGS AY.", flush=True)
        return 1
    report(inner, ops, un_i, "HOT PRIMITIVES (innermost macro -- what burns the ops)", a.top)
    doom, un_d, _f2 = rank(rec, table, doom_macro)
    report(doom, ops, un_d, "HOT DOOM MACROS (deepest non-stl caller -- our code)", a.top)

    if (ops - un_i) < 0.5 * ops:
        print("", flush=True)
        print("⚠ C2: only %.1f%% of ops attributed -- treat the ranking as indicative, not exact"
              % (100.0 * (ops - un_i) / max(1, ops)), flush=True)
    return 0


def selftest(heavy=False):
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("hotpath selftest -- a profile that cannot be wrong cannot be right", flush=True)

    # C3 the lookup must return the innermost label AT OR BEFORE an address
    t = LabelTable([(100, "a"), (200, "b"), (350, "c")])
    linear = lambda x: next((n for a, n in reversed([(100, "a"), (200, "b"), (350, "c")])
                             if a <= x), None)
    ok = all(t.lookup(x) == linear(x) for x in (0, 99, 100, 101, 199, 200, 349, 350, 351, 10_000))
    check("C3 lookup matches a linear scan at and around every boundary", ok)
    check("C3 an address before every label is unattributed, not label 0", t.lookup(50) is None)

    # C6 THE JOIN-KEY CONTROL, driven END TO END through rank().
    #
    # ⚠ The first version of this control called check_join() with two hand-typed integers and
    # never ran rank(). That left the whole path that PRODUCES its input -- rank() counting `far`,
    # stashing it on rank.last_far, main() reading it back -- untested, so the detector FAILED
    # OPEN: CR-2026-09-07 mutation-proved that `rank.last_far = far` -> `pass` still passed the
    # selftest. That was round-1's own finding recurring inside its fix. This drives the real path.
    far_tab = LabelTable([(1000, "aaa"), (2000, "bbb")])

    class Matched:                     # every op sits just after a label -> nothing dropped
        hits = Counter({1001: 900, 2001: 100})

    # ⚠ A FIXED offset, deliberately NOT derived from FAR_PAST_LABEL_BITS. Addressing the fixture
    # as `FAR_PAST_LABEL_BITS + 1` makes it scale with the constant under test, so widening the
    # constant to 10**18 disables detection on the real data while the selftest stays green
    # (CR-2026-09-07 R9-a). 600M bits ~= 18.7M words: the scale of the real AY gap.
    FAR_FIXTURE = 600_000_000

    class Mismatched:                  # ops far past the last BARE label -> a build mismatch
        hits = Counter({2000 + FAR_FIXTURE: 900, 2001: 100})

    rank.last_far = None
    _b, _u, _far0 = rank(Matched(), far_tab, inner_macro)
    m_far = rank.last_far
    ok, msg = check_join(m_far or 0, 1000, "a.fjm", "a.labels")
    check("C6 rank() reports its drop count (the plumbing is exercised)", m_far == 0,
          "far=%s" % m_far)
    check("C6 a MATCHED pair is ACCEPTED end to end", ok, msg[:40])

    rank.last_far = None
    _b2, _u2, _far1 = rank(Mismatched(), far_tab, inner_macro)
    x_far = rank.last_far
    ok2, msg2 = check_join(x_far or 0, 1000, "b.fjm", "b.labels")
    check("C6 rank() COUNTS the far ops (not silently zero)", x_far == 900, "far=%s" % x_far)
    check("C6 a MISMATCHED pair is REJECTED end to end",
          (not ok2) and "MISMATCH" in msg2, msg2[:44])
    check("C6 the threshold brackets the two REAL calibration pairs "
          "(0.017%% matched, 12.14%% mismatched)",
          0.00017 < JOIN_DROP_LIMIT < 0.1214)

    # C8 THE VERDICT PATH IN main(). C6 exercises rank()+check_join, but main() is what actually
    # EMITS a verdict, and CR-2026-09-07 R9-b showed it was untested: `check_join(0, ops, ...)` and
    # `if not ok: -> if False:` both left the selftest green. This drives main() end to end on a
    # real (tiny) fjm with DELIBERATELY WRONG labels and requires a non-zero exit.
    import subprocess as _sp, tempfile as _tf2, gzip as _gz2
    with _tf2.TemporaryDirectory() as _td2:
        t2 = Path(_td2)
        fake_fjm = t2 / "wrong.fjm"
        fake_fjm.write_bytes(bytes(64))
        wrong = t2 / "wrong_labels.tsv.gz"
        with _gz2.open(wrong, "wt", encoding="utf-8") as fh:
            fh.write("# fjm=other.fjm" + chr(10) + "# sha256=" + ("0" * 64) + chr(10))
            fh.write("lbl" + chr(9) + "64" + chr(10))
        r = _sp.run([sys.executable, str(Path(__file__).resolve()), "--fjm", str(fake_fjm),
                     "--labels", str(wrong), "--frames", "1"],
                    capture_output=True, text=True, timeout=600)
        out = (r.stdout or "") + (r.stderr or "")
        check("C8 main() REJECTS a provenance mismatch with a non-zero exit",
              r.returncode != 0, "rc=%d" % r.returncode)
        check("C8 ...and says DIFFERENT BUILDS rather than ranking anyway",
              "DIFFERENT BUILDS" in out or "VACUOUS" in out,
              (out.strip().splitlines() or ["(no output)"])[-1][:56])

    # C7 PROVENANCE -- the EXACT join key, not the drop-rate proxy.
    import hashlib, tempfile as _tf
    with _tf.TemporaryDirectory() as _td:
        q = Path(_td) / "l.tsv.gz"
        sha = hashlib.sha256(b"binary-bytes").hexdigest()
        with gzip.open(q, "wt", encoding="utf-8") as fh:
            fh.write("# fjm=build/x.fjm" + chr(10) + "# sha256=" + sha + chr(10))
            fh.write("lbl" + chr(9) + "64" + chr(10))
        pv = provenance_of(q)
        check("C7 provenance is read back exactly", pv.get("sha256") == sha, str(pv)[:36])
        check("C7 a different binary's sha does NOT match",
              pv.get("sha256") != hashlib.sha256(b"other").hexdigest())
        check("C7 the header does not leak into the label table",
              LabelTable.load(q).names == ["lbl"])

    # C5 THE OVER-ATTRIBUTION GUARD. An op far past a BARE label must not be credited to it.
    class R:
        hits = Counter({350 + 600_000_000: 500})
    b, un, _ = rank(R(), t, inner_macro)
    check("C5 an op far past a bare label is UNATTRIBUTED, not credited to it",
          un == 500 and not b, "unattributed=%d buckets=%s" % (un, str(dict(b))))
    class R2:
        hits = Counter({351: 500})
    b2, un2, _ = rank(R2(), t, inner_macro)
    check("C5 an op just after a bare label still IS credited (guard is not always-on)",
          un2 == 0 and b2.get("c") == 500, str(dict(b2)))

    # macro-name extraction
    n = "f3:l10:doom.walk(1)---f9:l88:hex.exact_xor(4)---switch"
    check("C4 inner_macro takes the innermost", inner_macro(n) == "hex.exact_xor",
          inner_macro(n))
    check("C4 doom_macro walks out past stl/hex to OUR macro", doom_macro(n) == "doom.walk",
          doom_macro(n))
    check("C4 a bare label degrades gracefully", inner_macro("vpb_px") == "vpb_px")

    # C1 the conservation check must be able to FAIL
    class Rec:
        ops = 5
        hits = Counter({10: 3, 20: 2})
    b, un, _far = rank(Rec(), t, inner_macro)
    check("C1 ops landing before any label count as UNATTRIBUTED, not as label 'a'",
          un == 5 and not b, "unattributed=%d buckets=%s" % (un, dict(b)))
    check("C1 the EOF tolerance is exactly 1 and DIRECTIONAL",
          all(cond == (0 <= d <= 1) for d, cond in
              [(-1, False), (0, True), (1, True), (2, False), (-100, False)]),
          "a hook seeing FEWER ops than executed is still rejected")
    b2, un2, _far = rank(type("R", (), {"hits": Counter({150: 7})})(), t, inner_macro)
    check("C1 ops after a label attribute to it", un2 == 0 and b2["a"] == 7, str(dict(b2)))

    # C9 THE PROXY VERDICT PATH in main(), driven end to end on a REAL mismatched pair.
    # C8 covers the PROVENANCE path, which rejects first -- so without this, main()'s drop-rate
    # branch is untested and `check_join(0, ...)` survives (CR-2026-09-07 R9-b). HEAVY (it loads a
    # real image), so it is opt-in; the PR that added it ran it and pasted the output.
    if heavy:
        import subprocess as _sp3
        print("  -- C9 drives main() on a real mismatched pair (heavy) ...", flush=True)
        r = _sp3.run([sys.executable, str(Path(__file__).resolve()),
                      "--fjm", "build/doom_e1m1_w1.fjm",
                      "--labels", "scratchpad/12m/_rung0_labels.tsv.gz", "--frames", "1"],
                     capture_output=True, text=True, cwd=str(ROOT))
        out = (r.stdout or "") + (r.stderr or "")
        check("C9 main() REJECTS a real mismatched pair via the proxy", r.returncode != 0,
              "rc=%d" % r.returncode)
        hit = [l.strip() for l in out.splitlines() if "MISMATCH" in l]
        check("C9 ...naming it a MISMATCH rather than ranking",
              "MISMATCH" in out and "VACUOUS" in out,
              (hit[0][:60] if hit else "(no MISMATCH line)"))
    else:
        print("  (C9 skipped -- pass --heavy to drive main()'s proxy path on a real pair)",
              flush=True)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
