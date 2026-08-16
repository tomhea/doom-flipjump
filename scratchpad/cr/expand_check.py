"""SUB-MACRO EXTRACTION GATE (the A4 pre-check).

When a duplicated block inside a big fj macro is pulled out into an inline sub-macro, the claim
is "textual expansion, so the emitted op stream is unchanged". That claim is easy to get WRONG
and expensive to disprove: the 4-viewpoint deg_gate takes ~20 minutes.

This expands the sub-macro at each call site with its REAL arguments and diffs the result,
token for token, against the inline block it replaced in a git ref. Label names are normalized
away (each expansion gets fresh ones); operands, widths, arity and order are compared exactly.

    python scratchpad/cr/expand_check.py <ref> <file.fj> <outer_macro> <sub_macro>

⚠ WHY THIS EXISTS. Extracting ts_step_faces' shared store tail, one parameter was threaded for
two different roles: `sfflag_v` is a 2-nibble register (nibble 0 = upper piece count, nibble 1 =
lower), and while the INCREMENT targets the side's own nibble, the byte written back to the
column is always the whole pair. Passing the side-offset register to `hex.write_byte` stored the
lower side's nibbles at the wrong offset. deg_gate caught it -- 4.5M ops lost, 7,570 px wrong at
(664,291) -- after 20 minutes. This check shows it in about a second.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def body(txt, name):
    i = txt.index("def %s " % name)
    i = txt.index("{", i) + 1
    d, j = 1, i
    while d:
        if txt[j] == "{":
            d += 1
        elif txt[j] == "}":
            d -= 1
        j += 1
    return txt[i:j - 1]


def ops(s):
    out = []
    for ln in s.split("\n"):
        ln = re.sub(r"//.*$", "", ln).strip()
        if ln:
            out.append(re.sub(r"\s+", " ", ln))
    return out


def check(old, new, outer, sub_name, prefixes=(""), extra=(), ref="ref", quiet=False):
    """The comparison itself, over TEXTS rather than git refs -- so `--selftest` can drive it with
    fixtures it mutates. Returns the number of call sites that differ (0 = emission-neutral)."""
    prefixes, extra = list(prefixes), list(extra)
    _p = print if not quiet else (lambda *a, **k: None)

    params = [p.strip() for p in
              re.search(r"def %s ([^@{]+)[@{]" % sub_name, new).group(1).replace("\\", "").split(",")
              if p.strip()]
    sub_body = ops(body(new, sub_name))
    mloc = re.search(r"def %s [^@{]*@([^{<]*)" % sub_name, new)
    locals_ = [x.strip() for x in mloc.group(1).replace("\\", "").split(",") if x.strip()] if mloc else []

    # The per-copy label prefixes the ORIGINAL inline blocks used (the sub-macro's own locals are
    # bare). Erased on BOTH sides: each expansion legitimately gets fresh label names.
    # `--erase` names additional OLD-side labels that play a sub-macro local's role but do not
    # share its prefix -- e.g. an inline block whose fall-through exit was the NEXT section's
    # label, which the sub-macro replaces with an internal `done:` in the same position.
    names = sorted({pre + l for l in locals_ for pre in prefixes} | set(extra),
                   key=len, reverse=True)

    calls = re.findall(r"\.%s ([^\n]+)" % sub_name, new)
    if not calls:
        raise SystemExit("no call sites for .%s found" % sub_name)

    def norm(seq):
        """Alpha-rename the per-copy label names: L0, L1, ... by first occurrence.

        ⚠ An earlier version mapped them ALL to one literal "LBL", which erased the control-flow
        graph -- swapping two branch targets, or inverting a compare's lt/gt arms, compared as
        IDENTICAL. That is the exact class of bug this tool exists to catch. Indexing by first
        occurrence keeps the equality-partition of targets, so a rewire changes the stream while
        a legitimate fresh naming does not."""
        if not names:
            return list(seq)
        pat = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, names)))
        seen, out = {}, []

        def rep(m):
            k = m.group(1)
            if k not in seen:
                seen[k] = len(seen)
            return "L%d" % seen[k]

        for l in seq:
            out.append(pat.sub(rep, l))
        return out

    old_body = ops(body(old, outer))
    new_body = ops(body(new, outer))
    cursor = 0                      # regions must be found in order and must not overlap
    ncur = 0                        # ... and each call site anchored to its own tail
    bad = 0
    for n, call in enumerate(calls):
        args = [a.strip() for a in call.split(",")]
        m = dict(zip(params, args))
        exp = [re.sub(r"\b(%s)\b" % "|".join(map(re.escape, params)),
                      lambda x: m[x.group(1)], l) for l in sub_body]
        first = norm([exp[0]])[0]
        try:
            i = next(k for k in range(cursor, len(old_body))
                     if norm([old_body[k]])[0] == first)      # in order, never re-matching a region
        except StopIteration:
            _p("call %d: FAIL  first expanded op not found in %s@%s:\n    %s"
                  % (n, outer, ref, first))
            bad += 1
            continue
        A, B = norm(old_body[i:i + len(exp)]), norm(exp)
        # END ANCHOR: the window is sized by the EXPANSION, so without this an op dropped from the
        # END of the original inline block would fall outside the window and never be compared.
        # The op after the call site in the new body must equal the op after the region in the old.
        nxt_old = old_body[i + len(exp)] if i + len(exp) < len(old_body) else None
        c = next((k for k in range(ncur, len(new_body))
                  if new_body[k].startswith("." + sub_name)), None)
        nxt_new = new_body[c + 1] if (c is not None and c + 1 < len(new_body)) else None
        ncur = (c + 1) if c is not None else ncur
        tail_ok = (nxt_old is None or nxt_new is None or nxt_old == nxt_new)
        cursor = i + len(exp)
        if A == B and tail_ok:
            _p("call %d: IDENTICAL (%d ops, from %s line ~%d)" % (n, len(B), outer, i))
        elif A == B:
            bad += 1
            _p("call %d: the block matches but the region does NOT end where the call does" % n)
            _p("    after the block  %s: %r" % (ref, nxt_old))
            _p("    after the call   new : %r" % (nxt_new,))
        else:
            bad += 1
            _p("call %d: DIFFERS" % n)
            for k in range(max(len(A), len(B))):
                x = A[k] if k < len(A) else "<none>"
                y = B[k] if k < len(B) else "<none>"
                if x != y:
                    _p("    op %d\n      %s: %s\n      new : %s" % (k, ref, x, y))
    _p("\n%s" % ("EXPANSION-IDENTICAL — extraction is emission-neutral" if not bad
                    else "!! %d call site(s) DIFFER" % bad))
    return bad


# ── THE NEGATIVE CONTROL (R9) ─────────────────────────────────────────────────────────────────
# A tool whose output is quoted as proof must ship a self-test that MUTATES real code and requires
# the tool to REJECT each mutation. Without one, "EXPANSION-IDENTICAL" is an unfalsified claim --
# and this repo has already shipped two verification tools whose controls exercised only the easy
# case (docs/cr-rules.md R9). The fixtures below are the shape the tool is actually used on: an
# outer macro holding two copies of a block, per-copy label prefixes, and the block extracted into
# an inline sub-macro. Each mutation is a real defect class this tool exists to catch.
_OLD = """
ns t {
    def outer a, b {
        hex.mov 8, a, b
        hex.add 8, a, b
        hex.cmp 2, a, b, lhit, lhit, ldone
      lhit:
        hex.zero 8, a
      ldone:
        hex.inc 8, a
        hex.mov 8, b, a
        hex.add 8, b, a
        hex.cmp 2, b, a, mhit, mhit, mdone
      mhit:
        hex.zero 8, b
      mdone:
        hex.dec 8, b
    }
}
"""
_NEW = """
ns t {
    def store_tail x, y @ done, hit {
        hex.mov 8, x, y
        hex.add 8, x, y
        hex.cmp 2, x, y, hit, hit, done
      hit:
        hex.zero 8, x
      done:
    }
    def outer a, b {
        .store_tail a, b
        hex.inc 8, a
        .store_tail b, a
        hex.dec 8, b
    }
}
"""
_MUTANTS = [
    ('an op DROPPED from the sub body',
     ('        hex.add 8, x, y\n', '')),
    ('a WIDTH changed (8 -> 4)',
     ('        hex.zero 8, x\n', '        hex.zero 4, x\n')),
    ('BRANCH TARGETS swapped (the rewire the old one-label norm could not see)',
     ('hex.cmp 2, x, y, hit, hit, done', 'hex.cmp 2, x, y, done, hit, hit')),
    ('ONE PARAM, TWO ROLES -- the operand swapped for the other register (R52)',
     ('        hex.zero 8, x\n', '        hex.zero 8, y\n')),
    ('an op APPENDED at the END of the sub body (only the tail anchor catches this)',
     ('      done:\n    }', '      done:\n        hex.inc 8, y\n    }')),
    ('an op inserted in the MIDDLE',
     ('        hex.add 8, x, y\n', '        hex.add 8, x, y\n        hex.inc 8, y\n')),
]

def selftest():
    args = dict(prefixes=["", "l", "m"], ref="fixture", quiet=True)
    base = check(_OLD, _NEW, "outer", "store_tail", **args)
    print("unmutated fixture: %s" % ("PASS (expansion-identical)" if base == 0
                                     else "!! FAIL (%d differ) -- the fixture itself is wrong" % base))
    failures = 0 if base == 0 else 1
    for name, (frm, to) in _MUTANTS:
        assert frm in _NEW, "mutation site moved: %r" % frm
        try:
            bad = check(_OLD, _NEW.replace(frm, to, 1), "outer", "store_tail", **args)
        except SystemExit:                 # a mutation that removes every call site still counts
            bad = 1
        ok = bad > 0
        failures += 0 if ok else 1
        print("  %-4s %s" % ("ok" if ok else "MISS", name))
    print("selftest: %s" % ("all mutations rejected" if not failures
                            else "!! %d CHECK(S) HAVE NO TEETH" % failures))
    return 1 if failures else 0


def main():
    if len(sys.argv) < 5:
        raise SystemExit(__doc__.strip().split(chr(10) + chr(10))[-2])
    ref, fname, outer, sub_name = sys.argv[1:5]
    new = (ROOT / "src" / "fj" / fname).read_text(encoding="utf-8")
    r = subprocess.run(["git", "show", "%s:src/fj/%s" % (ref, fname)],
                       cwd=str(ROOT), capture_output=True)
    if r.returncode != 0:
        raise SystemExit("git show failed: " + r.stderr.decode(errors="replace"))
    prefixes, extra = [""], []
    for a in sys.argv[5:]:
        for flag, dst in (("--prefixes", "p"), ("--erase", "e")):
            if a.startswith(flag + "="):
                v = a.split("=", 1)[1].split(",")
            elif a == flag:
                v = sys.argv[sys.argv.index(a) + 1].split(",")
            else:
                continue
            (prefixes if dst == "p" else extra).extend(v)
    return 1 if check(r.stdout.decode("utf-8"), new, outer, sub_name,
                      prefixes, extra, ref) else 0


sys.exit(selftest() if "--selftest" in sys.argv else main())
