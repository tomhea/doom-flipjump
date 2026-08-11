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


def main():
    if len(sys.argv) < 5:
        raise SystemExit(__doc__.strip().split("\n\n")[-2])
    ref, fname, outer, sub_name = sys.argv[1:5]
    new = (ROOT / "src" / "fj" / fname).read_text(encoding="utf-8")
    r = subprocess.run(["git", "show", "%s:src/fj/%s" % (ref, fname)],
                       cwd=str(ROOT), capture_output=True)
    if r.returncode != 0:
        raise SystemExit("git show failed: " + r.stderr.decode(errors="replace"))
    old = r.stdout.decode("utf-8")

    params = [p.strip() for p in
              re.search(r"def %s ([^@{]+)[@{]" % sub_name, new).group(1).replace("\\", "").split(",")
              if p.strip()]
    sub_body = ops(body(new, sub_name))
    mloc = re.search(r"def %s [^@{]*@([^{<]*)" % sub_name, new)
    locals_ = [x.strip() for x in mloc.group(1).replace("\\", "").split(",") if x.strip()] if mloc else []

    # The per-copy label prefixes the ORIGINAL inline blocks used (the sub-macro's own locals are
    # bare). Erased on BOTH sides: each expansion legitimately gets fresh label names.
    prefixes = [""]
    for a in sys.argv[5:]:
        if a.startswith("--prefixes="):
            prefixes += a.split("=", 1)[1].split(",")
        elif a == "--prefixes":
            prefixes += sys.argv[sys.argv.index(a) + 1].split(",")
    names = sorted({pre + l for l in locals_ for pre in prefixes}, key=len, reverse=True)

    calls = re.findall(r"\.%s ([^\n]+)" % sub_name, new)
    if not calls:
        raise SystemExit("no call sites for .%s found" % sub_name)

    def norm(seq):
        if not names:
            return list(seq)
        pat = r"\b(%s)\b" % "|".join(map(re.escape, names))
        return [re.sub(pat, "LBL", l) for l in seq]

    old_body = ops(body(old, outer))
    bad = 0
    for n, call in enumerate(calls):
        args = [a.strip() for a in call.split(",")]
        m = dict(zip(params, args))
        exp = [re.sub(r"\b(%s)\b" % "|".join(map(re.escape, params)),
                      lambda x: m[x.group(1)], l) for l in sub_body]
        first = norm([exp[0]])[0]
        try:
            i = next(k for k, l in enumerate(old_body) if norm([l])[0] == first)
        except StopIteration:
            print("call %d: FAIL  first expanded op not found in %s@%s:\n    %s"
                  % (n, outer, ref, first))
            bad += 1
            continue
        A, B = norm(old_body[i:i + len(exp)]), norm(exp)
        if A == B:
            print("call %d: IDENTICAL (%d ops, from %s line ~%d)" % (n, len(B), outer, i))
        else:
            bad += 1
            print("call %d: DIFFERS" % n)
            for k in range(max(len(A), len(B))):
                x = A[k] if k < len(A) else "<none>"
                y = B[k] if k < len(B) else "<none>"
                if x != y:
                    print("    op %d\n      %s: %s\n      new : %s" % (k, ref, x, y))
    print("\n%s" % ("EXPANSION-IDENTICAL — extraction is emission-neutral" if not bad
                    else "!! %d call site(s) DIFFER" % bad))
    return 1 if bad else 0


sys.exit(main())
