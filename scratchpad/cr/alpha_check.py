"""ALPHA-EQUIVALENCE pre-gate for the fj clarity pass.

Stronger than "erase all identifiers": that only proves no op/number moved, and would
happily accept a REWIRED JUMP TARGET (`;fnext` silently becoming `;floop`) or a local
renamed onto a global it also references (two distinct cells collapsing into one).

Here each macro body is alpha-renamed IN ITS OWN SCOPE: every identifier is replaced by the
index of its FIRST occurrence within that macro (signature included, so the params/@locals/
<globals lists are covered too). Two versions are equivalent iff the token streams match.
That makes the check a bijection test:
  - a pure rename (old -> new, one-to-one)      -> identical streams        PASS
  - two names collapsing into one (shadowing)   -> index stream differs     FAIL
  - one name splitting into two                 -> index stream differs     FAIL
  - a jump target rewired to a different label  -> index stream differs     FAIL
  - any op/rep/number/arity change              -> token stream differs     FAIL

Usage:  python alpha_check.py [<git-ref>]      (default HEAD)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
FILES = ["fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj",
         "plane_render.fj", "plane_bands.fj", "stream_render.fj"]

TOKEN = re.compile(r"0x[0-9a-fA-F]+|\d+|\.{0,2}[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*|\S")
IDENT = re.compile(r"^\.{0,2}[A-Za-z_]")


def macro_streams(text):
    """-> dict {macro_name: [alpha-renamed tokens]}, plus '<toplevel>'."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"\\\s*\n", " ", text)
    toks = TOKEN.findall(text)

    out = {}
    order = []
    stack = []          # [(name, depth_at_open)]
    depth = 0
    pending = None      # macro name awaiting its '{'
    sigbuf = []         # signature tokens, attributed to the macro not to <toplevel>
    i = 0

    def sink():
        return stack[-1][0] if stack else "<toplevel>"

    while i < len(toks):
        t = toks[i]
        if t == "def" and i + 1 < len(toks) and pending is None:
            pending = toks[i + 1]
            sigbuf = []
        if t == "{":
            depth += 1
            if pending is not None:
                name = pending
                n, k = name, 2
                while n in out:          # same macro name in two namespaces
                    n, k = "%s#%d" % (name, k), k + 1
                out[n] = list(sigbuf)    # signature belongs to the macro's scope
                order.append(n)
                stack.append((n, depth))
                pending, sigbuf = None, []
                i += 1
                continue
        elif t == "}":
            if stack and stack[-1][1] == depth:
                stack.pop()
            depth -= 1
            i += 1
            continue
        if pending is not None:
            sigbuf.append(t)
        else:
            out.setdefault(sink(), [])
            out[sink()].append(t)
        i += 1

    # alpha-rename per scope
    alpha = {}
    for name, ts in out.items():
        seen = {}
        res = []
        for t in ts:
            if IDENT.match(t):
                if t not in seen:
                    seen[t] = len(seen)
                res.append("#%d" % seen[t])
            else:
                res.append(t)
        alpha[name] = res
    return alpha


def show(a, b):
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            lo = max(0, i - 10)
            print("      ref : %s" % " ".join(a[lo:i + 10]))
            print("      wt  : %s" % " ".join(b[lo:i + 10]))
            return
    print("      length differs: ref %d vs wt %d tokens" % (len(a), len(b)))


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    bad = 0
    for f in FILES:
        old = subprocess.run(["git", "show", "%s:src/fj/%s" % (ref, f)],
                             cwd=ROOT, capture_output=True).stdout.decode("utf-8")
        new = open(Path(ROOT) / "src" / "fj" / f, encoding="utf-8").read()
        A, B = macro_streams(old), macro_streams(new)
        if set(A) != set(B):
            print("%-20s FAIL  macro set changed: %s" % (f, set(A) ^ set(B)))
            bad += 1
            continue
        diffs = [n for n in A if A[n] != B[n]]
        ntok = sum(len(v) for v in A.values())
        if diffs:
            print("%-20s FAIL  %d/%d scopes differ (%d tokens)" % (f, len(diffs), len(A), ntok))
            for n in diffs:
                print("    scope %s:" % n)
                show(A[n], B[n])
            bad += 1
        else:
            print("%-20s OK    %d scopes, %d tokens alpha-identical" % (f, len(A), ntok))
    print("\n%s" % ("ALPHA-EQUIVALENT (rename/comment-only)" if not bad
                    else "!! %d file(s) NOT alpha-equivalent" % bad))
    return 1 if bad else 0


sys.exit(main())
