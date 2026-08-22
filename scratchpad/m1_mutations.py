"""R1 evidence for M1, as a re-runnable script instead of a hand-composed table.

Each entry MUTATES REAL SHIPPED CODE -- not a copy, not a fixture -- runs the M1 tests, and records
which tests failed. A test that passes under the mutation it is supposed to catch is not evidence.

CR round 4: the PR body's mutation table was hand-composed and nothing on disk backed it. This
writes scratchpad/_m1_mutations.log, which the body can cite.

⚠ It edits files in src/ and restores them from an in-memory copy in a finally block. If it is
killed mid-run, `git checkout src/` restores the tree.

    python scratchpad/m1_mutations.py
"""
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SR = ROOT / "src/doomfj/selfreset.py"
FJ = ROOT / "src/fj/m1_reset.fj"
TESTS = ["tests/host/test_selfreset.py", "tests/fj/test_m1_reset.py"]

# ⚠ CR round 7: this script writes ROOT/src/doomfj/selfreset.py, but the tests import whatever
# `doomfj` resolves to. If those differ it mutates a file nobody imports. It fails LOUD when that
# happens (every mutation reports "!! NOTHING CAUGHT IT"), but a one-line check says so directly.
sys.path.insert(0, str(ROOT / "src"))
import doomfj.selfreset as _sr                                             # noqa: E402
assert Path(_sr.__file__).resolve() == SR.resolve(), (
    "this script would mutate %s but the tests import %s" % (SR, _sr.__file__))


def rd(p):
    return io.open(p, encoding="utf-8").read()


def wr(p, s):
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)


def drop_two_sided(s):
    i = s.index("    stray = sorted((wset & declared_words) - byte_words)")
    j = s.index("    nib = sorted(wset - byte_words)", i)
    return s[:i] + s[j:]


def drop_main_check(s):
    a = ('    assert len(hits) == 1, ("self-reset: expected exactly 1 bare stl.loop (the frame '
         'tail), "\n                            "found %d" % len(hits))')
    assert a in s
    return s.replace(a, "    hits = hits[:1] or [0]")


def drop_provenance(s):
    a = '    for k in ("source_sha256", "labels_sha256", "generated_by"):'
    assert a in s, "drop_provenance no longer matches -- update it, do not leave it stale"
    return s.replace(a, "    for k in ():")


def drop_containment(s):
    a = "            if off >= span:"
    assert a in s, "drop_containment no longer matches -- update it, do not leave it stale"
    return s.replace(a, "            if False:")


def hardcode_counts(s):
    a = "    for name, n in byte_arrays(bits, words_sorted, view_w, nss):"
    assert a in s, "hardcode_counts no longer matches -- update it, do not leave it stale"
    return s.replace(a, "    for name, n in [('sshead', 682), ('pclm', 160), ('sfflag', 160)]:")


def drop_high_nibble(s):
    out = [l for l in s.splitlines(True) if "c+dbit+7, c+dbit+6" not in l]
    assert len(out) == len(s.splitlines(True)) - 1
    return "".join(out)


def drop_pointer_restore(s):
    a = "      back:\n        wflip hex.pointers.ret_after_read_byte+w, back\n"
    assert a in s
    return s.replace(a, "      back:\n")


def spill_past_the_cell(s):
    t = "hex.exact_xor c+dbit+7, c+dbit+6, c+dbit+5, c+dbit+4, hex.pointers.read_byte+dw"
    assert t in s, "spill_past_the_cell no longer matches -- update it, do not leave it stale"
    return s.replace(t, t + "\n        wflip c+dw+w, 1*dw")


MUTATIONS = [
    ("selfreset.py: the two-sided guard deleted",        SR, drop_two_sided),
    ("selfreset.py: main-part recognition assert gone",  SR, drop_main_check),
    ("selfreset.py: provenance refusal gone",            SR, drop_provenance),
    ("selfreset.py: containment check gone",             SR, drop_containment),
    ("selfreset.py: byte counts hardcoded again",        SR, hardcode_counts),
    ("m1_reset.fj: high-nibble exact_xor deleted",       FJ, drop_high_nibble),
    ("m1_reset.fj: shared pointer never restored",       FJ, drop_pointer_restore),
    ("m1_reset.fj: one write past the cell",             FJ, spill_past_the_cell),
]



def drop_layout_fingerprint(s):
    a = "    got = layout_fingerprint(doc, labels)"
    assert a in s, "drop_layout_fingerprint no longer matches -- update it, do not leave it stale"
    return s.replace(a, "    return out  #")


def drop_missing_label_refusal(s):
    i = s.index("    assert not missing, (")
    j = s.index("\n", s.index("derived from a different program", i))
    return s[:i] + "    missing = []" + s[j:]


def drop_format_refusal(s):
    i = s.index('    assert doc.get("format")')
    j = s.index("\n", s.index("regenerate with scratchpad/m1_setfile.py", i))
    return s[:i] + "    pass" + s[j:]


def unbound_top_containment(s):
    a = "        span = (addrs[i] - b) if i < len(addrs) else 2"
    assert a in s, "unbound_top_containment no longer matches -- update it"
    return s.replace(a, "        span = (addrs[i] - b) if i < len(addrs) else 1 << 60")


MUTATIONS += [
    ("selfreset.py: layout fingerprint check gone",     SR, drop_layout_fingerprint),
    ("selfreset.py: missing-label refusal gone",        SR, drop_missing_label_refusal),
    ("selfreset.py: label+offset format refusal gone",  SR, drop_format_refusal),
    ("selfreset.py: containment unbounded at the top",  SR, unbound_top_containment),
]



def restore_membership_verify(s):
    """Put back the pre-round-7 verify_labels_unchanged: resolve against the NEW table and test
    PASS-1 addresses for membership. Catches 1-word moves and silently passes everything bigger."""
    i = s.index("    doc = json.load(gzip.open(restore_set_path, \"rt\", encoding=\"utf-8\"))\n    named =")
    j = s.index("    return moved\n", i) + len("    return moved\n")
    body = (
        "    s = load_restore_set(restore_set_path, new, check_layout=False)\n"
        "    out = []\n"
        "    for k in set(old) & set(new):\n"
        "        if old[k] != new[k] and ((old[k] // W) in s or (old[k] // W + 1) in s):\n"
        "            out.append(k)\n"
        "    return out\n")
    return s[:i] + body + s[j:]


MUTATIONS += [
    ("selfreset.py: verify back to the membership test", SR, restore_membership_verify),
]



def drop_value_check(s):
    a = "        if get_word_1(x) != get_word_2(x):"
    assert a in s, "drop_value_check no longer matches -- update it"
    return s.replace(a, "        if False:")


MUTATIONS += [
    ("selfreset.py: pristine-value check gone", SR, drop_value_check),
]



def restore_truthy_limit(s):
    a = "    if limit is not None:"
    assert a in s, "restore_truthy_limit no longer matches -- update it"
    return s.replace(a, "    if limit:")


MUTATIONS += [
    ("selfreset.py: limit back to a truthiness test", SR, restore_truthy_limit),
]


# ⚠ The subprocess must import the SAME doomfj this script mutates. The guard above only checks
# THIS process's import, which the sys.path.insert forces to ROOT/src; pytest resolves it
# independently (pyproject sets pythonpath = ["."], not src). CR round 11 showed a checkout where
# the harness mutated one file and tested another and still printed "14 OF 15 APPLIED", exit 0.
ENV = dict(__import__("os").environ, PYTHONPATH=str(ROOT / "src"))


def run():
    out = subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q", "--no-header", "--tb=no"],
                         cwd=ROOT, capture_output=True, text=True, env=ENV)
    failed = sorted(l.split(" ")[1].split("[")[0] for l in out.stdout.splitlines()
                    if l.startswith("FAILED"))
    tail = [l for l in out.stdout.splitlines() if " passed" in l or " failed" in l]
    return failed, (tail[-1] if tail else "?")


ap = __import__("argparse").ArgumentParser()
ap.add_argument("--all-at-once", action="store_true",
                help="apply EVERY mutation together and print the raw pytest output -- the R1 "
                     "FAIL block, generated rather than retyped")
cli = ap.parse_args()

if cli.all_at_once:
    # R1 wants a FAIL block and a PASS block. CR round 5 was right that the body's FAIL block was
    # hand-composed with nothing on disk behind it, so this produces it: every mutation applied at
    # once, the REAL pytest output printed, then the tree restored and run again.
    originals = {p: rd(p) for p in (SR, FJ)}
    try:
        applied, skipped = [], []
        for _name, _path, _fn in MUTATIONS:
            _before = rd(_path)
            try:
                _after = _fn(_before)
            except (AssertionError, ValueError):
                # A mutation can fail to apply for TWO REASONS and they mean opposite things:
                #   CONFLICT -- an earlier mutation removed the text this one anchors on. Benign;
                #               the per-mutation run covers it.
                #   DRIFT    -- the anchor no longer matches the SHIPPED code at all. That is a
                #               broken control and must fail the run.
                # Distinguish them by re-applying to the PRISTINE file. CR round 11 demonstrated
                # the previous version filing a drifted anchor under "conflict" and exiting 0 --
                # laundering a broken control into a benign note, in the tool whose entire job is
                # to prove controls are not broken.
                try:
                    _probe = _fn(originals[_path])
                    assert _probe != originals[_path], "no-op on pristine"
                except (AssertionError, ValueError):
                    raise AssertionError(
                        "mutation %r does not match the shipped code -- its anchor has DRIFTED "
                        "(it also fails against the pristine file, so this is not a conflict)"
                        % _name)
                skipped.append(_name)
                continue
            assert _after != _before, (
                "mutation %r changed nothing -- its anchor has drifted from the code" % _name)
            wr(_path, _after)
            applied.append(_name)
        print("=== %d OF %d MUTATIONS APPLIED TO REAL SHIPPED CODE ==="
              % (len(applied), len(MUTATIONS)))
        for _name in applied:
            print("    %s" % _name)
        if skipped:
            print("")
            print("    NOT APPLIED (conflicts with a mutation above -- covered individually by")
            print("    the per-mutation run in scratchpad/_m1_mutations.log):")
            for _name in skipped:
                print("      %s" % _name)
        print("")
        r = subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q", "--no-header",
                            "--tb=no"], cwd=ROOT, capture_output=True, text=True, env=ENV)
        print(r.stdout.rstrip())
    finally:
        for _p, _s in originals.items():
            wr(_p, _s)
    print("")
    print("=== RESTORED ===")
    r = subprocess.run([sys.executable, "-m", "pytest", *TESTS, "-q", "--no-header", "--tb=no"],
                       cwd=ROOT, capture_output=True, text=True, env=ENV)
    print(r.stdout.rstrip())
    sys.exit(0 if " failed" not in r.stdout else 1)

ok = True
print("BASELINE (no mutation)")
base_failed, base_line = run()
print("  %s" % base_line)
if base_failed:
    print("  !! the tree is not clean -- %s" % base_failed)
    ok = False

originals = {p: rd(p) for p in (SR, FJ)}
try:
    for name, path, fn in MUTATIONS:
        mutated = fn(originals[path])
        # ⚠ THE UNIFORM ANCHOR CHECK, and it is one line rather than fourteen. A mutation whose
        # anchor has drifted silently becomes a no-op, and a no-op mutation "passes" every test --
        # which reads as coverage. Individual functions assert their own anchors too (and two have
        # fired for real), but only this catches ALL of them, including any added later. CR round 10
        # found 3 of 14 relying solely on the loud-failure backstop; the body had claimed all 14
        # asserted, which was a completeness claim about the R1 evidence tool itself.
        assert mutated != originals[path], (
            "mutation %r changed nothing -- its anchor has drifted from the code" % name)
        wr(path, mutated)
        failed, line = run()
        wr(path, originals[path])
        caught = bool(failed)
        ok &= caught
        print("")
        print("MUTATION: %s" % name)
        print("  %s   %s" % (line, "ok" if caught else "!! NOTHING CAUGHT IT"))
        for f in failed:
            print("    caught by %s" % f)
finally:
    for p, s in originals.items():
        wr(p, s)

print("")
after_failed, after_line = run()
print("RESTORED: %s  %s" % (after_line, "ok" if not after_failed else "!! TREE LEFT DIRTY"))
ok &= not after_failed
print("")
print("M1 MUTATION EVIDENCE: %s" % ("PASS -- every mutation is caught" if ok else "FAIL"))
sys.exit(0 if ok else 1)
