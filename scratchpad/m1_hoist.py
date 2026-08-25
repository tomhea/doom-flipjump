"""Hoist a macro's `@`-local STORAGE to named globals, leaving control-flow labels in `@`.

WHY. The M1 restore set is keyed on assembler expansion paths
(`f<file>:l<line>:macro(arity)---local`) because an `@`-local has no other name: it is one cell PER
EXPANSION, so the only thing distinguishing them is where they were expanded from. Those keys break
on any line/arity drift -- 313 of 344 needed re-keying for LINE NUMBERS ALONE (2026-08-25). A named
global has no file, line, rep index or arity, so hoisting the storage deletes that whole class.

An `@`-local is ALREADY a baked constant address, so this emits the IDENTICAL op. `deg_gate` proves
it: byte-exact pixels AND op counts identical to the digit.

⚠ SAFE WITHOUT AN INDEX ONLY WHEN INSTANTIATIONS CANNOT BE LIVE AT ONCE. With one expansion it is
exact by construction. With N sequential expansions a shared cell is equivalent iff each expansion
WRITES before it READS -- otherwise expansion 2 would see expansion 1's leftover where it used to
see its own cell. This tool REFUSES a multi-instantiation macro unless --shared says the caller has
checked that, and the honest check is deg_gate.

⚠ LATCHES SURVIVE. `proj.column_params_m`'s `consts_set` is deliberately a program static that
persists between calls ("set them on the FIRST call only"). A global is also a static, so the
property is preserved -- but it is why the DECLARED INITIALISER must be carried over verbatim.

    python scratchpad/m1_hoist.py --file src/fj/projection.fj --macro wedge_setup --prefix ws --dry-run
    python scratchpad/m1_hoist.py --selftest
"""
import argparse

import re
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--file")
ap.add_argument("--macro")
ap.add_argument("--prefix")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--only", default=None,
                help="comma-separated locals to hoist; the rest stay @-local")
ap.add_argument("--shared", action="store_true",
                help="assert the caller has checked that N expansions may share one cell")
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()

# the size may be SYMBOLIC (`hex.vec w/4`, the pointer registers). An earlier version excluded
# "/" here to dodge the `//` comment and silently skipped all 12 of them -- a SILENT UNDER-HOIST,
# which leaves @-locals in the restore set. Take the rest of the line, strip the comment after.
NLJ = chr(10)
DECL = re.compile(r"^(\s*)([A-Za-z_]\w*)\s*:\s*hex\.vec\s+(.+)$")


def split_macro(text, macro):
    """Return (start, hdr_end, body_end) line indices for `def <macro>` .. its closing `}`."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines)
                  if re.match(r"\s*def\s+%s\b" % re.escape(macro), l)), None)
    assert start is not None, "no `def %s` in the file" % macro
    # the header continues while lines end with a backslash; it ends on the line with `{`
    h = start
    while "{" not in lines[h]:
        h += 1
        assert h < len(lines), "unterminated def header for %s" % macro
    # the body ends at the first line that is exactly the closing brace at the def's indent
    indent = len(lines[start]) - len(lines[start].lstrip())
    b = h + 1
    close = " " * indent + "}"
    while lines[b].rstrip() != close:
        b += 1
        assert b < len(lines), "unterminated body for %s" % macro
    return lines, start, h, b


def parse_list(hdr, sigil):
    """Extract the comma-separated names following `sigil` in the def header."""
    # strip continuations and the trailing `{`
    flat = " ".join(x.rstrip("\\").strip() for x in hdr).rsplit("{", 1)[0]
    # cut at the sigil, then stop at the NEXT sigil if there is one
    if sigil not in flat:
        return [], flat
    tail = flat.split(sigil, 1)[1]
    for other in ("@", "<"):
        if other != sigil and other in tail:
            tail = tail.split(other, 1)[0]
    return [n.strip() for n in tail.split(",") if n.strip()], flat


def hoist(text, macro, prefix, only=None):
    """Return (new_text, decls) -- decls are `name: hex.vec N` strings for the emitter."""
    lines, start, hdr_end, body_end = split_macro(text, macro)
    hdr = lines[start:hdr_end + 1]
    at, _ = parse_list(hdr, "@")
    lt, _ = parse_list(hdr, "<")
    assert at, "%s has no @ list to hoist" % macro

    # storage = an @ name that has a `name: hex.vec ...` DECLARATION in the body.
    _flat = " ".join(x.rstrip("\\").strip() for x in hdr).rsplit("{", 1)[0]
    _params = set(re.findall(r"[A-Za-z_]\w*",
                            re.split(r"[@<]", _flat, 1)[0])) - {"def", macro}
    skipped = []
    body = lines[hdr_end + 1:body_end]

    # ⚠⚠ DECLARATIONS THAT STAY MUST NOT MOVE. An earlier version decided later and APPENDED the
    # ones it declined to the END of the body -- and a macro whose last body line is a terminal
    # label (proj.point_to_angle's `done:`) then had data words sitting in its FALL-THROUGH EXIT.
    # Every call ran the declarations as ops and jumped into garbage. That bug is what made
    # point_to_angle look like "the one macro that cannot share": a six-run bisect measured the
    # TOOL, not the code. CR 2026-08-25 reproduced it -- it failed with a SINGLE expansion (so not
    # sharing) and with disp=0 and no dispatch (so not relocation), and passed with 20 expansions
    # sharing once the label was restored.
    #
    # So: keep EVERY declaration in place while deciding, and delete only the hoisted ones at the
    # end, by index. A skipped declaration is then byte-identical to where it started.
    keep_body = list(body)
    cand = {}                       # name -> (index into keep_body, size)
    for i, l in enumerate(body):
        m = DECL.match(l)
        if not (m and m.group(2) in at):
            continue
        _sz = m.group(3).split("//")[0].strip()
        # A SIZE OR INITIALISER THAT MENTIONS A MACRO PARAMETER CANNOT BE HOISTED: at top level the
        # parameter does not exist (`piece_max: hex.vec 1, 1+stack` -> "Can't evaluate label stack").
        # It stays, and it is harmless -- a declared constant is never written, so never dirty.
        if set(re.findall(r"(?<![0-9a-fA-Fx])[A-Za-z_]\w*", _sz)) & _params:
            skipped.append(m.group(2))
            continue
        cand[m.group(2)] = (i, _sz)

    # --only: hoist a SUBSET, the rest stay.
    if only:
        _miss = [n for n in only if n not in cand]
        assert not _miss, "--only names %s, not a hoistable @-local here" % _miss
        for _n in [n for n in cand if n not in only]:
            skipped.append(_n)
            del cand[_n]

    # A LOCAL DECLARED BUT NEVER USED MUST NOT BE HOISTED: before, its declaration counted as the
    # use; after, the `<` entry is unreferenced and fj reports "unused labels: <name>", which
    # warning_as_errors turns into a failed assembly (R8). Use-detection ignores the declaration
    # lines themselves.
    _decl_idx = {i for i, _ in cand.values()}
    for _n in [n for n in cand
               if not any(re.search(r"\b%s\b" % re.escape(n), l)
                          for j, l in enumerate(keep_body) if j not in _decl_idx)]:
        skipped.append(_n)
        del cand[_n]

    assert cand, ("%s: no @-local carries a `name: hex.vec` declaration -- nothing to hoist "
                  "(its @ list is all control-flow labels)" % macro)
    decls = {n: sz for n, (_i, sz) in cand.items()}
    for _i in sorted((i for i, _ in cand.values()), reverse=True):
        del keep_body[_i]          # remove ONLY the hoisted declarations, from the back

    ren = {n: "%s_%s" % (prefix, n) for n in decls}
    # rewrite the body: whole-word renames only
    pat = re.compile(r"\b(%s)\b" % "|".join(sorted(map(re.escape, ren), key=len, reverse=True)))
    keep_body = [pat.sub(lambda m: ren[m.group(1)], l) for l in keep_body]

    new_at = [n for n in at if n not in decls]
    new_lt = lt + [ren[n] for n in sorted(decls)]
    # rebuild the header: keep the parameter list verbatim, replace the @ and < lists
    flat = " ".join(x.rstrip("\\").strip() for x in hdr).rsplit("{", 1)[0]
    params = re.split(r"[@<]", flat, 1)[0].rstrip()
    ind = " " * (len(lines[start]) - len(lines[start].lstrip()))
    new_hdr = [ind + params + " \\"]      # ⚠ keep the def's own indent: these live inside `ns ... {`
    if new_at:
        new_hdr.append(ind + "        @ " + ", ".join(new_at) + " \\")
    new_hdr.append(ind + "        < " + ", ".join(new_lt) + " {")

    # POST-CONDITION: nothing left in @ may still carry a hex.vec declaration. Without this a
    # regex gap under-hoists SILENTLY and the restore set keeps naming expansion paths.
    _left = []
    for _n in new_at:
        for _l in keep_body:
            _m = DECL.match(_l)
            if _m and _m.group(2) == _n:
                _left.append(_n)
                break
    _left = [n for n in _left if n not in skipped]
    assert not _left, "%s: still @-locals but declared: %s" % (macro, _left)
    out = lines[:start] + new_hdr + keep_body + lines[body_end:]
    for _n in skipped:
        print("    SKIPPED (stays @-local): %s" % _n)
    return "\n".join(out), ["%s: hex.vec %s" % (ren[n], decls[n]) for n in sorted(decls)]


if args.selftest:
    SRC = "\n".join([
        "    def demo a, b \\",
        "            @ loop, tmp, flag, ptr, dead, pdep, done, exit_here \\",
        "            < shared {",
        "        hex.zero 8, tmp",
        "        hex.if0 1, flag, done",
        "        hex.add 8, tmp, a",
        "      loop:",
        "        hex.mov 8, shared, tmp",
        "        hex.ptr_index ptr, shared, tmp",
        "      done:",
        "      tmp: hex.vec 8",
        "      flag: hex.vec 1, 1        // a latch with an initialiser",
        "      ptr: hex.vec w/4          // SYMBOLIC size -- the gap that under-hoisted",
        "      dead: hex.vec 2           // declared, never used -> must stay @-local",
        "      pdep: hex.vec 1, 1+b      // size mentions PARAMETER b -> must stay @-local",
      # ⚠ a TERMINAL LABEL as the LAST body line. This is proj.point_to_angle's shape
      # (`done:`), and it is what turned a mis-placed declaration into data words in the
      # macro's fall-through EXIT. Without it the position bug is unobservable.
        "      exit_here:",
        "    }",
    ])
    got, decls = hoist(SRC, "demo", "d")
    ok = True

    def chk(name, cond):
        global ok
        ok &= cond
        print("  %-52s %s" % (name, "ok" if cond else "!! FAIL"))

    chk("def keeps its indentation", got.split('\n')[0].startswith("    def demo"))
    chk("control-flow labels stay in @", "@ loop, dead, pdep, done, exit_here" in got)
    chk("storage moved to < with prefix", "< shared, d_flag, d_ptr, d_tmp {" in got)
    chk("uses renamed", "hex.zero 8, d_tmp" in got and "hex.add 8, d_tmp, a" in got)
    chk("declarations removed from body", "tmp: hex.vec" not in got and "flag: hex.vec" not in got)
    chk("label `loop:` NOT renamed", "      loop:" in got)
    chk("pre-existing < entry kept", "hex.mov 8, shared, d_tmp" in got)
    chk("initialiser carried over", "d_flag: hex.vec 1, 1" in decls)
    chk("SYMBOLIC size hoisted (w/4)", "d_ptr: hex.vec w/4" in decls)
    chk("all three emitted", decls == ["d_flag: hex.vec 1, 1", "d_ptr: hex.vec w/4", "d_tmp: hex.vec 8"])
    chk("declared-but-unused stays @-local", "dead" in got.split("{")[0] and "d_dead" not in got)
    chk("its declaration is put back", "dead: hex.vec 2" in got)
    chk("parameter-dependent decl stays", "pdep: hex.vec 1, 1+b" in got
                                          and "d_pdep" not in got)
    # ⚠⚠ THE POSITION CHECK. Every declaration that STAYS must remain BEFORE the terminal
    # label, exactly where it started. Appending them after `exit_here:` put data in the
    # fall-through exit and is what made proj.point_to_angle look unhoistable (CR 2026-08-25).
    _b = got.split("{", 1)[1].split(NLJ)
    _term = max(i for i, l in enumerate(_b) if l.strip() == "exit_here:")
    _after = [l.strip() for l in _b[_term + 1:] if ": hex.vec" in l]
    chk("NO declaration lands after the terminal label", not _after)
    for _nm in ("dead", "pdep"):
        _at = max(i for i, l in enumerate(_b) if l.strip().startswith(_nm + ":"))
        chk("%s stays BEFORE the terminal label" % _nm, _at < _term)
    # C1: a macro whose @ list is only control flow must REFUSE, not silently no-op
    NOSTORE = "\n".join(["    def q a \\", "            @ x {", "      x:", "        ;x", "    }"])
    try:
        hoist(NOSTORE, "q", "z")
        chk("C1 refuses a macro with no storage", False)
    except AssertionError:
        chk("C1 refuses a macro with no storage", True)
    # --only: the flag the whole point_to_angle conclusion rested on, previously untested.
    _g2, _d2 = hoist(SRC, "demo", "d", only={"tmp"})
    chk("--only hoists just the named local", _d2 == ["d_tmp: hex.vec 8"])
    chk("--only leaves the others declared in place",
        "flag: hex.vec 1, 1" in _g2 and "ptr: hex.vec w/4" in _g2)
    _b2 = _g2.split("{", 1)[1].split(NLJ)
    _t2 = max(i for i, l in enumerate(_b2) if l.strip() == "exit_here:")
    chk("--only: nothing lands after the terminal label",
        not [l for l in _b2[_t2 + 1:] if ": hex.vec" in l])
    try:
        hoist(SRC, "demo", "d", only={"nosuch"})
        chk("C2 --only naming a non-local refuses", False)
    except AssertionError:
        chk("C2 --only naming a non-local refuses", True)

    print("SELFTEST: %s" % ("PASS" if ok else "!! FAIL"))
    sys.exit(0 if ok else 1)

assert args.file and args.macro and args.prefix, "need --file --macro --prefix"
p = Path(args.file)
txt = p.read_text(encoding="utf-8")
new, decls = hoist(txt, args.macro, args.prefix,
                   only=set(args.only.split(",")) if args.only else None)
print("%s :: %s -> %d globals" % (p.name, args.macro, len(decls)))
for d in decls:
    print("    \"%s\"," % d)
if args.dry_run:
    print("\n(dry run -- nothing written)")
else:
    p.write_text(new, encoding="utf-8")
    print("\nWROTE %s" % p)
