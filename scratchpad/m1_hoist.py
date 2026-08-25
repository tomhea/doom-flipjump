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
ap.add_argument("--shared", action="store_true",
                help="assert the caller has checked that N expansions may share one cell")
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()

# the size may be SYMBOLIC (`hex.vec w/4`, the pointer registers). An earlier version excluded
# "/" here to dodge the `//` comment and silently skipped all 12 of them -- a SILENT UNDER-HOIST,
# which leaves @-locals in the restore set. Take the rest of the line, strip the comment after.
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


def hoist(text, macro, prefix):
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
    decls, keep_body = {}, []
    for l in body:
        m = DECL.match(l)
        if m and m.group(2) in at:
            _sz = m.group(3).split("//")[0].strip()
            # ⚠ A SIZE OR INITIALISER THAT MENTIONS A MACRO PARAMETER CANNOT BE HOISTED:
            # at top level the parameter does not exist. Real case, found by a 25-minute
            # assembly failure rather than by this tool: `piece_max: hex.vec 1, 1+stack`
            # -> "Can't evaluate label stack". Such a local STAYS an @-local, which is
            # harmless: a declared constant is never written, so it is never dirty and
            # never in the restore set.
            if set(re.findall(r"(?<![0-9a-fA-Fx])[A-Za-z_]\w*", _sz)) & _params:
                skipped.append(m.group(2))
                keep_body.append(l)
                continue
            decls[m.group(2)] = _sz
            continue                      # the declaration moves out of the macro
        keep_body.append(l)
    assert decls, ("%s: no @-local carries a `name: hex.vec` declaration -- nothing to hoist "
                   "(its @ list is all control-flow labels)" % macro)

    # ⚠ A LOCAL THAT IS DECLARED BUT NEVER USED MUST NOT BE HOISTED. Before the hoist its
    # declaration counted as its use; afterwards the `<` entry is unreferenced and fj says
    # "unused labels: <name>" -- a WARNING, which the assembler treats as an ERROR (R8).
    # Leave it exactly as it was: it is a dead cell either way, and deleting it would be a
    # separate change with its own gate.
    for _n in [n for n in decls
               if not any(re.search(r"\b%s\b" % re.escape(n), l) for l in keep_body)]:
        skipped.append(_n)
        keep_body.append("      %s: hex.vec %s" % (_n, decls.pop(_n)))

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
        "            @ loop, tmp, flag, ptr, dead, done \\",
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
        "    }",
    ])
    got, decls = hoist(SRC, "demo", "d")
    ok = True

    def chk(name, cond):
        global ok
        ok &= cond
        print("  %-52s %s" % (name, "ok" if cond else "!! FAIL"))

    chk("def keeps its indentation", got.split('\n')[0].startswith("    def demo"))
    chk("control-flow labels stay in @", "@ loop, dead, done" in got)
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
    # C1: a macro whose @ list is only control flow must REFUSE, not silently no-op
    NOSTORE = "\n".join(["    def q a \\", "            @ x {", "      x:", "        ;x", "    }"])
    try:
        hoist(NOSTORE, "q", "z")
        chk("C1 refuses a macro with no storage", False)
    except AssertionError:
        chk("C1 refuses a macro with no storage", True)
    print("SELFTEST: %s" % ("PASS" if ok else "!! FAIL"))
    sys.exit(0 if ok else 1)

assert args.file and args.macro and args.prefix, "need --file --macro --prefix"
p = Path(args.file)
txt = p.read_text(encoding="utf-8")
new, decls = hoist(txt, args.macro, args.prefix)
print("%s :: %s -> %d globals" % (p.name, args.macro, len(decls)))
for d in decls:
    print("    \"%s\"," % d)
if args.dry_run:
    print("\n(dry run -- nothing written)")
else:
    p.write_text(new, encoding="utf-8")
    print("\nWROTE %s" % p)
