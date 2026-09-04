"""THE RITUAL -- one command per idea, for the 12M campaign (docs/handoff-12m-campaign.md).

At a strict per-idea cadence the ritual IS the wall clock, so it is one script and it prints the
ledger row at the end. Four steps, in the order the doctrine requires:

    build   the deg-tier binary, under three spies: the wflip census (optional, --census),
            the resolved label table (always), and a capture of the assembled .fjm itself.
            deg_gate runs inside this, so its 4 byte-exact viewpoints come free with the build.
    freeze  the LABEL DIFF against the base build. Section 1 of the plan: never trust the
            op-by-op estimate of a filler; 3 of 5 ts builds drifted. This is that check.
    sweep   ca2_sweep base.fjm vs new.fjm -- 260 frames, byte-exact + the MEDIAN, the only
            ship criterion.
    row     the LEDGER.md line, printed ready to paste.

Artifacts land in scratchpad/12m/atlas/<id>.*  and are never read whole into the main thread.

    python scratchpad/12m/ritual.py build  --id BASE --census
    python scratchpad/12m/ritual.py freeze --id P1-1 --base BASE
    python scratchpad/12m/ritual.py sweep  --id P1-1 --base BASE
    python scratchpad/12m/ritual.py all    --id P1-1 --base BASE --pool P1 --what "..."

CONTROLS (R9)
  * build REFUSES to start while another fat python process is alive (rule 1 is about peak RSS,
    and "the log looks done" has twice not meant "the process is gone").
  * build REFUSES to write artifacts if deg_gate did not report PASS -- a binary that fails its
    own four viewpoints must never become a sweep operand.
  * freeze has a self-test (--selftest) that perturbs a label table and requires a report of
    exactly that perturbation; a freeze check that cannot fail is not evidence.
  * sweep is ca2_sweep unchanged, with its own picture and vacuity controls; this script only
    parses the numbers it printed and refuses a non-zero exit.
"""
import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ATLAS = HERE / "atlas"
sys.path.insert(0, str(ROOT / "scratchpad"))


def _p(*a):
    print(*a, flush=True)


def art(idx, suffix):
    return ATLAS / (idx + suffix)


# ------------------------------------------------------------------------------------ rule 1


def _fat_pythons():
    """Live python.exe processes over 1 GB RSS, excluding this one. Rule 1's actual test."""
    me = str(__import__("os").getpid())
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process python -ErrorAction SilentlyContinue | "
             "Select-Object Id,WorkingSet64 | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:
        return []
    if not out:
        return []
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [(r["Id"], r["WorkingSet64"]) for r in rows
            if str(r["Id"]) != me and r["WorkingSet64"] > 1_000_000_000]


# ------------------------------------------------------------------------------------- build


class _Tee:
    def __init__(self, stream, sink):
        self.stream, self.sink = stream, sink

    def write(self, s):
        self.sink.append(s)
        return self.stream.write(s)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, k):
        return getattr(self.stream, k)


DEG_LINE = re.compile(r"^\((-?\d+),(-?\d+),(0x[0-9a-f]+)\): ([\d,]+) ops\s+(.*)$")


def do_build(idx, stl, want_census, force):
    fat = _fat_pythons()
    if fat and not force:
        raise SystemExit("REFUSING (rule 1): fat python still alive: "
                         + ", ".join("pid %d @ %.1f GB" % (i, b / 1e9) for i, b in fat))
    ATLAS.mkdir(parents=True, exist_ok=True)
    import runpy

    import flipjump
    import flipjump.assembler.assembler as asm
    import popcount_census as pc

    fjm_dest = art(idx, ".fjm")
    seen = []
    files_seen = []

    orig_assemble = flipjump.assemble

    def assemble_spy(input_files, output_file, *a, **kw):
        r = orig_assemble(input_files, output_file, *a, **kw)
        seen.append(Path(output_file))
        # the f<i> tags in every label path are this list's 1-based indices, so the atlas
        # can name a call site's FILE instead of guessing it.
        files_seen.append([str(Path(x)) for x in input_files])
        return r

    flipjump.assemble = assemble_spy
    unhook_labels = pc._spy_on_labels(asm, str(art(idx, ".labels.tsv.gz")))
    records = unhook_census = None
    if want_census:
        records, unhook_census = pc._spy_on_wflips(asm, record_values=True)

    sink = []
    saved_out, saved_argv = sys.stdout, sys.argv
    sys.stdout = _Tee(saved_out, sink)
    sys.argv = ["deg_with_stl.py"] + ([] if stl == "stock" else ["--" + stl])
    t0 = time.perf_counter()
    try:
        try:
            runpy.run_path(str(ROOT / "scratchpad" / "oneshadow" / "deg_with_stl.py"),
                           run_name="__main__")
        except SystemExit as e:
            if e.code not in (0, None):
                raise SystemExit("deg_gate exited %r -- NOT writing artifacts" % (e.code,))
    finally:
        sys.stdout, sys.argv = saved_out, saved_argv
        flipjump.assemble = orig_assemble
        unhook_labels()
        if unhook_census:
            unhook_census()
    wall = time.perf_counter() - t0

    # CHECK THE WINDOW FIRST. It is decided at assembly, and a violation makes frame.arm5
    # produce wild pointers -- which shows up as a pixel diff whose cause is invisible.
    # P7-2 cost a 15-minute build learning that: -221 ops of headroom, 15,975 px wrong.
    lab = art(idx, ".labels.tsv.gz")
    if lab.exists():
        ok, msg = narrow_arm_window(str(lab))
        _p("narrow-arm window: %s  %s" % (msg, "ok" if ok else "!! VIOLATED"))
        if not ok:
            raise SystemExit("the narrow pointer arm (frame.arm5) is NOT exact in this "
                             "layout: " + msg + " -- the frame would be wrong. "
                             "NOT writing artifacts.")
    text = "".join(sink)
    if "\nPASS" not in text and not text.rstrip().endswith("PASS"):
        raise SystemExit("deg_gate did not print PASS -- NOT writing artifacts")
    vps = []
    for line in text.splitlines():
        m = DEG_LINE.match(line.strip())
        if m:
            vps.append({"vx": int(m.group(1)), "vy": int(m.group(2)), "va": m.group(3),
                        "ops": int(m.group(4).replace(",", "")), "verdict": m.group(5).strip()})
    if len(vps) != 4:
        raise SystemExit("parsed %d deg viewpoints, expected 4 -- NOT writing artifacts" % len(vps))
    if any(v["verdict"] != "BYTE-EXACT" for v in vps):
        raise SystemExit("a viewpoint is not BYTE-EXACT -- NOT writing artifacts")
    if not seen:
        raise SystemExit("the assemble spy never fired -- no binary to keep")
    shutil.copy2(seen[-1], fjm_dest)
    json.dump({"id": idx, "stl": stl, "wall_s": round(wall, 1), "viewpoints": vps,
               "input_files": files_seen[-1] if files_seen else [],
               "fjm": str(fjm_dest), "fjm_bytes": fjm_dest.stat().st_size},
              open(art(idx, ".deg.json"), "w"), indent=1)
    if want_census:
        pc._write_census(str(art(idx, ".census.json.gz")), sys.argv, records)
    _p("")
    _p("build %s: PASS in %.0f s -> %s (%.1f MB)" % (idx, wall, fjm_dest,
                                                     fjm_dest.stat().st_size / 1e6))
    for v in vps:
        _p("   (%d,%d,%s) %s ops" % (v["vx"], v["vy"], v["va"], format(v["ops"], ",")))
    return vps


# ------------------------------------------------------------------------------------ freeze


# P2-3's narrow pointer arm (frame.arm5) rewrites only the low FIVE hexes of the three address
# fields. That is exact only while every narrow-armed table lies inside ONE 16^5 window, so that
# nibbles 5..7 are equal on both sides of every consecutive pair of arms. fj has no assert
# directive and rep() cannot take a label-dependent count, so the check has to live here -- and
# it is not hypothetical: config.py sets SLOT_SHIFT = 2 as soon as PID_BYTES becomes 2, which
# makes sfslot alone 2,621,440 bits and would break every narrow arm SILENTLY.
NARROW_ARM_LO = "pclm"     # the lowest table in the hot-data block
NARROW_ARM_HI = "wrej"     # the first label after `drawn`, the highest


def narrow_arm_window(labels_path):
    """-> (ok, message). The hot-data block must not straddle a 16^5 (2^20 bit) boundary."""
    want = {NARROW_ARM_LO, NARROW_ARM_HI}
    got = {}
    with gzip.open(labels_path, "rt", encoding="utf-8") as f:
        for line in f:
            name, _, addr = line.rstrip(chr(10)).rpartition(chr(9))
            if name in want:
                got[name] = int(addr)
                if len(got) == len(want):
                    break
    if len(got) != len(want):
        return False, "could not find %s in the label table" % (want - set(got))
    lo, hi = got[NARROW_ARM_LO], got[NARROW_ARM_HI]
    ok = (lo >> 20) == ((hi - 1) >> 20)
    head = ((lo >> 20) + 1 << 20) - hi
    return ok, ("hot-data block %s(0x%X) .. %s(0x%X), %s ops of headroom to the 16^5 boundary"
                % (NARROW_ARM_LO, lo, NARROW_ARM_HI, hi, format(head // 64, ",")))


def _globals_only(path):
    """The BAKED labels: top-level names, the ones an address constant can depend on. Macro
    expansion paths (f<file>:l<line>:... ---) are excluded -- there are millions of them and
    they move whenever anything above them moves, which says nothing extra."""
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if ":" in name or "---" in name:
                continue
            out[name] = int(addr)
    return out


def freeze_report(base_labels, new_labels, top=25):
    a, b = _globals_only(base_labels), _globals_only(new_labels)
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    both = set(a) & set(b)
    moved = {n: b[n] - a[n] for n in both if b[n] != a[n]}
    return {"base_n": len(a), "new_n": len(b), "common": len(both), "moved": len(moved),
            "gone": only_a, "added": only_b, "deltas": moved, "top": top}


def print_freeze(rep):
    _p("=" * 92)
    _p("FREEZE (label diff over top-level labels only)")
    _p("  base %s labels, new %s labels, %s common"
       % (format(rep["base_n"], ","), format(rep["new_n"], ","), format(rep["common"], ",")))
    if rep["gone"]:
        _p("  LABELS REMOVED (%d): %s" % (len(rep["gone"]), ", ".join(rep["gone"][:12])))
    if rep["added"]:
        _p("  LABELS ADDED   (%d): %s" % (len(rep["added"]), ", ".join(rep["added"][:12])))
    d = rep["deltas"]
    if not d:
        _p("  MOVED: none -- the layout is FROZEN (0 of %s labels shifted)"
           % format(rep["common"], ","))
    else:
        from collections import Counter
        hist = Counter(d.values())
        _p("  MOVED: %d of %s labels" % (len(d), format(rep["common"], ",")))
        _p("  delta histogram (bit-address; one op is 2w = 64 bits at w=32):")
        for delta, n in sorted(hist.items(), key=lambda kv: -kv[1])[:10]:
            _p("     %+12d bits (%+9.1f ops) x %d labels" % (delta, delta / 64.0, n))
        first = sorted(d.items(), key=lambda kv: abs(kv[1]), reverse=True)[:rep["top"]]
        _p("  largest shifts:")
        for name, delta in first:
            _p("     %-46s %+12d bits (%+9.1f ops)" % (name[:46], delta, delta / 64.0))
    _p("=" * 92)
    return not (rep["gone"] or rep["added"] or rep["deltas"])


def selftest_freeze():
    """R9 negative control: a freeze check that cannot fail is not evidence."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    rows = [("alpha", 64), ("beta", 128), ("f1:l2:mac---x", 192), ("gamma", 256)]
    A = tmp / "a.tsv.gz"
    B = tmp / "b.tsv.gz"
    with gzip.open(A, "wt", encoding="utf-8") as f:
        for n, v in rows:
            f.write("%s\t%d\n" % (n, v))
    with gzip.open(B, "wt", encoding="utf-8") as f:
        for n, v in rows:
            f.write("%s\t%d\n" % (n, v + (64 if n == "gamma" else 0)))
        f.write("delta\t999\n")
    rep = freeze_report(str(A), str(B))
    ok = rep["moved"] == 1 and rep["deltas"].get("gamma") == 64
    ok &= rep["added"] == ["delta"] and rep["gone"] == []
    ok &= rep["common"] == 3          # the macro-path row must be excluded
    _p("control 1 (a moved label + an added label are reported): %s" % ("ok" if ok else "FAIL"))
    same = freeze_report(str(A), str(A))
    ok2 = not (same["moved"] or same["added"] or same["gone"])
    _p("control 2 (a table against itself reports FROZEN):        %s" % ("ok" if ok2 else "FAIL"))
    _p("freeze selftest: %s" % ("PASS" if (ok and ok2) else "FAIL"))
    return 0 if (ok and ok2) else 1


# ------------------------------------------------------------------------------------- sweep


SWEEP_ROW = re.compile(r"^(A base|B new|delta)\s+([\d,-]+)\s+([\d,-]+)\s+([\d,-]+)\s+([\d,-]+)")


def do_sweep(idx, base, angles, step, limit):
    a, b = art(base, ".fjm"), art(idx, ".fjm")
    for p in (a, b):
        if not p.exists():
            raise SystemExit("missing %s -- build it first" % p)
    cmd = [sys.executable, str(ROOT / "scratchpad" / "ca2_sweep.py"), "--a", str(a), "--b", str(b),
           "--angles", str(angles), "--step", str(step)]
    if limit:
        cmd += ["--limit", str(limit)]
    _p("$ " + " ".join(cmd))
    log = art(idx, ".sweep.log")
    t0 = time.perf_counter()
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        rows = {}
        for line in proc.stdout:
            fh.write(line)
            m = SWEEP_ROW.match(line.strip())
            if m:
                rows[m.group(1)] = [int(x.replace(",", "")) for x in m.groups()[1:]]
            if line.startswith(("=", "PICTURE", "VACUITY", "ca2_sweep", "A (", "B (")) or "!!" in line:
                _p("   " + line.rstrip())
        rc = proc.wait()
    _p("sweep wall %.0f s, log -> %s" % (time.perf_counter() - t0, log))
    if rc != 0:
        raise SystemExit("ca2_sweep FAILED (exit %d) -- see %s" % (rc, log))
    if "delta" not in rows:
        raise SystemExit("could not parse the sweep table -- see %s" % log)
    res = {"base_median": rows["A base"][0], "new_median": rows["B new"][0],
           "delta_median": rows["delta"][0], "base_min": rows["A base"][2],
           "new_min": rows["B new"][2], "delta_min": rows["delta"][2],
           "delta_max": rows["delta"][3], "log": str(log)}
    res["pct"] = 100.0 * res["delta_median"] / res["base_median"]
    json.dump(res, open(art(idx, ".sweep.json"), "w"), indent=1)
    return res


# --------------------------------------------------------------------------------- ledger row


def ledger_row(idx, pool, what, base, res, degs, base_degs):
    dd = "/".join("%+d" % (n["ops"] - o["ops"]) for n, o in zip(degs, base_degs)) if base_degs else "n/a"
    verdict = "SHIP" if res["delta_median"] < 0 else "KILL"
    return ("| %s | %s | %s | %s | %s (%+.2f%%) | %s | (commit) |"
            % (idx, pool, what, dd, format(res["new_median"], ","), res["pct"], verdict))


# ---------------------------------------------------------------------------------------- cli


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("build", "freeze", "sweep", "all"):
        s = sub.add_parser(name)
        s.add_argument("--id", required=True)
        if name in ("build", "all"):
            s.add_argument("--stl", default="stock", choices=["stock", "worktree", "stl-dual"])
            s.add_argument("--census", action="store_true")
            s.add_argument("--force", action="store_true", help="override the rule-1 guard")
        if name in ("freeze", "sweep", "all"):
            s.add_argument("--base", required=True)
        if name in ("sweep", "all"):
            s.add_argument("--angles", type=int, default=4)
            s.add_argument("--step", type=int, default=256)
            s.add_argument("--limit", type=int, default=0)
        if name == "all":
            s.add_argument("--pool", default="?")
            s.add_argument("--what", default="")
    sub.add_parser("selftest")
    a = ap.parse_args()

    if a.mode == "selftest":
        raise SystemExit(selftest_freeze())
    if a.mode == "build":
        do_build(a.id, a.stl, a.census, a.force)
        return
    if a.mode == "freeze":
        ok = print_freeze(freeze_report(str(art(a.base, ".labels.tsv.gz")),
                                        str(art(a.id, ".labels.tsv.gz"))))
        raise SystemExit(0 if ok else 3)
    if a.mode == "sweep":
        res = do_sweep(a.id, a.base, a.angles, a.step, a.limit)
        _p("MEDIAN %s -> %s  (%+d, %+.2f%%)   MIN %+d   MAX %+d"
           % (format(res["base_median"], ","), format(res["new_median"], ","),
              res["delta_median"], res["pct"], res["delta_min"], res["delta_max"]))
        return
    # all
    degs = do_build(a.id, a.stl, a.census, a.force)
    print_freeze(freeze_report(str(art(a.base, ".labels.tsv.gz")),
                               str(art(a.id, ".labels.tsv.gz"))))
    base_degs = None
    bp = art(a.base, ".deg.json")
    if bp.exists():
        base_degs = json.load(open(bp))["viewpoints"]
        _p("DEG vs %s:" % a.base)
        for n, o in zip(degs, base_degs):
            _p("   (%d,%d,%s) %s -> %s  (%+d, %+.2f%%)"
               % (n["vx"], n["vy"], n["va"], format(o["ops"], ","), format(n["ops"], ","),
                  n["ops"] - o["ops"], 100.0 * (n["ops"] - o["ops"]) / o["ops"]))
    res = do_sweep(a.id, a.base, a.angles, a.step, a.limit)
    _p("")
    _p("MEDIAN %s -> %s  (%+d, %+.2f%%)   MIN %+d   MAX %+d"
       % (format(res["base_median"], ","), format(res["new_median"], ","),
          res["delta_median"], res["pct"], res["delta_min"], res["delta_max"]))
    _p("")
    _p("LEDGER ROW:")
    _p(ledger_row(a.id, a.pool, a.what, a.base, res, degs, base_degs))


if __name__ == "__main__":
    main()
