"""RENAME-PASS EQUIVALENCE GATE for the hand-written fj library (`src/fj/*.fj`).

Cheap (~1s, NO build) pre-gate for a pass that is supposed to change only `@`-locals, labels
and comments. Run it BEFORE spending 20 minutes on scratchpad/deg_gate.py.

    python scratchpad/cr/alpha_check.py [<git-ref>]   # default HEAD
    python scratchpad/cr/alpha_check.py --selftest    # prove the gate still has teeth

WHAT IT COMPARES. Each macro is reduced to a token stream in its own scope. Exactly ONE class
of name is alpha-renamed (replaced by the index of its first occurrence): the macro's own
`@` list, which in this dialect holds both its compile-time locals and its body labels.
EVERYTHING ELSE COMPARES VERBATIM -- op names (`hex.mov`), macro calls, `ns` names, positional
parameters, the `<`-list globals, and every numeric literal, width and arity. Scope keys are
namespace-qualified.

So the gate accepts a consistent renaming of `@`-locals/labels and NOTHING ELSE. It rejects:
  - any op / rep / arity / width / constant change;
  - a jump target rewired to a different label, INCLUDING a "consistent" rewire that also
    edits the `<` list (both sides are literal here, so the substitution shows up);
  - a global swapped for another global (`slopediv_recip` -> `yslope_packed`);
  - an op swapped for a same-arity op (`hex.read_table_packed` -> `hex.read_table_by`);
  - a renamed namespace, or a renamed positional parameter (both forbidden by the pass's
    contract -- emitters bind them by name and position);
  - two locals collapsing onto one name, or one splitting into two.
It accepts a pure permutation of `@`-locals, which is genuinely equivalence-preserving.

⚠ HISTORY / CORRECTION. The first version of this tool alpha-renamed EVERY identifier and was
described in commit faa9ffc as a "bijection test" catching rewired jump targets. That was
WRONG: with ops and globals renameable too, a consistent rewire passed clean. A code review
(2026-08-11) demonstrated four such false PASSes on real files. The clarity pass's conclusion
survived re-checking under the corrected rule below (and was independently proven by the
byte-exact deg_gate), but the evidence as originally stated was insufficient. `--selftest`
exists so this class of overclaim is caught mechanically next time.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"

TOKEN = re.compile(r"0x[0-9a-fA-F]+|\d+|\.{0,2}[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*|\S")
IDENT = re.compile(r"^\.{0,2}[A-Za-z_]")


def _strip(text):
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"\\\s*\n", " ", text)


def macro_streams(text):
    """-> {namespace-qualified scope name: [tokens]}, with only @-locals alpha-renamed."""
    toks = TOKEN.findall(_strip(text))
    out, ns_stack, stack = {}, [], []
    depth, i = 0, 0
    pending = None          # macro name awaiting its '{'
    sig = []                # its signature tokens
    ns_pending = None

    def sink():
        return stack[-1][0] if stack else "<toplevel>"

    while i < len(toks):
        t = toks[i]
        if t == "ns" and i + 1 < len(toks) and pending is None:
            ns_pending = toks[i + 1]
        if t == "def" and i + 1 < len(toks) and pending is None:
            pending, sig = toks[i + 1], []
        if t == "{":
            depth += 1
            if pending is not None:
                name = ".".join(ns_stack + [pending])
                k, n = 2, name
                while n in out:
                    n, k = "%s#%d" % (name, k), k + 1
                out[n] = list(sig)
                stack.append((n, depth))
                pending, sig = None, []
                i += 1
                continue
            if ns_pending is not None:
                ns_stack.append(ns_pending)
                ns_pending = None
                stack.append((None, depth))     # namespace frame, not a scope
                i += 1
                continue
            stack.append((None, depth))
            i += 1
            continue
        if t == "}":
            if stack and stack[-1][1] == depth:
                if stack[-1][0] is None and ns_stack:
                    ns_stack.pop()
                stack.pop()
            depth -= 1
            i += 1
            continue
        if pending is not None:
            sig.append(t)
        else:
            s = sink()
            out.setdefault(s, []).append(t)
        i += 1

    # per scope: alpha-rename ONLY the @-list names; everything else stays literal.
    alpha = {}
    for name, ts in out.items():
        renameable = set()
        if "@" in ts:
            j = ts.index("@") + 1
            while j < len(ts) and ts[j] != "<":
                if IDENT.match(ts[j]):
                    renameable.add(ts[j])
                j += 1
        seen, res = {}, []
        for t in ts:
            if t in renameable:
                if t not in seen:
                    seen[t] = len(seen)
                res.append("@%d" % seen[t])
            else:
                res.append(t)
        alpha[name] = res
    return alpha


def _read(ref, name):
    r = subprocess.run(["git", "show", "%s:src/fj/%s" % (ref, name)],
                       cwd=str(ROOT), capture_output=True)
    if r.returncode != 0:
        raise SystemExit("git show %s:src/fj/%s failed: %s"
                         % (ref, name, r.stderr.decode(errors="replace").strip()))
    return r.stdout.decode("utf-8")


def compare(ref, verbose=True):
    files = sorted(p.name for p in FJ.glob("*.fj"))
    listed = subprocess.run(["git", "ls-tree", "--name-only", "%s:src/fj" % ref],
                            cwd=str(ROOT), capture_output=True)
    old_files = sorted(f for f in listed.stdout.decode().split() if f.endswith(".fj"))
    bad = 0
    if set(files) != set(old_files):
        print("FAIL  file set changed: %s" % (set(files) ^ set(old_files)))
        bad += 1
    for f in sorted(set(files) & set(old_files)):
        A, B = macro_streams(_read(ref, f)), macro_streams((FJ / f).read_text(encoding="utf-8"))
        ntok = sum(len(v) for v in A.values())
        if not A or not ntok:                       # non-vacuity: an empty parse is not a pass
            print("%-20s FAIL  parsed to nothing (%d scopes, %d tokens)" % (f, len(A), ntok))
            bad += 1
            continue
        if set(A) != set(B):
            print("%-20s FAIL  macro set changed: %s" % (f, sorted(set(A) ^ set(B))[:6]))
            bad += 1
            continue
        diffs = [n for n in A if A[n] != B[n]]
        if diffs:
            print("%-20s FAIL  %d/%d scopes differ (%d tokens)" % (f, len(diffs), len(A), ntok))
            for n in diffs[:4]:
                a, b = A[n], B[n]
                k = next((j for j in range(min(len(a), len(b))) if a[j] != b[j]), min(len(a), len(b)))
                lo = max(0, k - 8)
                print("    scope %s" % n)
                print("      ref : %s" % " ".join(a[lo:k + 8]))
                print("      wt  : %s" % " ".join(b[lo:k + 8]))
            bad += 1
        elif verbose:
            print("%-20s OK    %d scopes, %d tokens" % (f, len(A), ntok))
    return bad


MUTATIONS = [
    ("global swapped for another global", "hex.mov 8, denom, bb_recip_ph",
                                          "hex.mov 8, denom, yslope_packed"),
    ("op swapped for a same-arity op",    "hex.read_table_packed 3, recipv",
                                          "hex.read_table_by 3, recipv"),
    ("namespace renamed",                 "ns plane {", "ns wall {"),
    ("constant changed",                  "hex.set 8, cfff, 0xFFF", "hex.set 8, cfff, 0xFFE"),
    ("jump target rewired (local -> local)",
     "hex.cmp 2, rshift, czero2, unshift_done, unshift_done, unshift_step",
     "hex.cmp 2, rshift, czero2, norm_done, unshift_done, unshift_step"),
    ("positional parameter renamed",      "def build_bands basewidth", "def build_bands bw"),
]


def selftest():
    """Apply known-bad mutations to a real file and require the gate to REJECT each one."""
    target = FJ / "plane_bands.fj"
    original = target.read_text(encoding="utf-8")
    head_clean = compare("HEAD", verbose=False) == 0
    print("baseline (working tree vs HEAD): %s" % ("clean" if head_clean else "DIRTY -- commit first"))
    if not head_clean:
        return 1
    failures = 0
    try:
        for label, old, new in MUTATIONS:
            if old not in original:
                print("  SKIP  %-36s (anchor not found)" % label)
                continue
            target.write_text(original.replace(old, new, 1), encoding="utf-8")
            caught = compare("HEAD", verbose=False) != 0
            print("  %-4s  %s" % ("ok" if caught else "MISS", label))
            failures += (0 if caught else 1)
    finally:
        target.write_text(original, encoding="utf-8")
    print("selftest: %s" % ("all mutations rejected" if not failures
                            else "!! %d MUTATION(S) PASSED THE GATE" % failures))
    return 1 if failures else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    ref = next((a for a in sys.argv[1:] if not a.startswith("-")), "HEAD")
    bad = compare(ref)
    print("\n%s" % ("EQUIVALENT — @-local/label renames and comments only" if not bad
                    else "!! %d file(s) NOT equivalent" % bad))
    return 1 if bad else 0


sys.exit(main())
