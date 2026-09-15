"""THE PREMISE Z1/Z2/Z3 RESTED ON, PINNED PER FILE: a narrowed clear and its mov are one statement.

`hex.mov n` is `zero n` + `xor n`, so a `hex.zero N, X` sitting in front of a `hex.mov M, X, Y`
clears the low M nibbles twice. Z1 (6c82984) and Z2+Z3 (c65da95) rewrote those across the SEVEN
`src/fj` files `git show --stat` lists for the two commits, into `hex.zero N-M, X + M*dw` +
`hex.mov M, X, Y`, worth -459,685 binding ops. How many survive today is not prose: `EXPECTED_SITES`
below is the per-file count and it is ASSERTED, because deleting a narrowed clear is exactly the
Z1 bug and a scan that only proved it still finds SOME of them would not notice.

The rewrite is only sound when the mov UNCONDITIONALLY follows the clear, and Z1 shipped a site
where it did not. In `proj.tex_col_wrap` the two were on DIFFERENT BRANCHES --

    rem_zero:
        hex.zero 8, dst      <- Z1 deleted this; on this branch it IS the result
        ;end
    rem_nz:
        hex.mov 8, dst, tw

-- so the "pair" was a `;end` and a label apart, and `m2_std_gate` still passed byte-exact because
the door-route trajectory never enters `rem_zero`. A gate proves one path; the premise is a
property of EVERY path, and only a structural check sees all of them.

So this file re-derives the premise from the real `src/fj/*.fj` text, one test per modified file
(R3). It runs THREE scans, because the transform can go wrong in more than one direction and a
deleted line leaves nothing behind to inspect:

* the SITE scan below, over every clear the transform left narrowed (`zero N, X + M*dw`);
* `repped_narrowed_clear_faults`, over the narrowed clears a `rep(...)` GUARDS. The site scan skips
  those, so without it a guarded site would be checked by nothing at all. It runs every check below
  except the coverage half, plus the one that matters most for a guarded pair: the mov carries the
  SAME guard text, so no build configuration can keep one half and drop the other. One site today,
  `frame_render.fj:2475`;
* `branch_split_clear_mov_pairs`, over every clear it has NOT touched yet -- the clear/mov pairs a
  Z-style matcher finds but control flow separates. That set is pinned, so deleting or narrowing
  one of those clears (exactly what Z1 did) fails here even though it leaves no narrowed site to
  scan. Three entries today: two `proj` branches whose `hex.zero 8, dst` IS the result, and
  `frame.clamp_row`'s negative branch, which is the same shape in a Z1-touched file.

The site scan asserts, for every narrowed clear:

* the very next STATEMENT is the mov -- nothing between them, in particular no label to jump into
  and no jump out (this is the check that fails on the Z1 bug shape);
* the mov carries no label of its own (a label ON the mov is a way into the gap just as much as a
  label before it);
* the mov is guarded by exactly what the clear is guarded by (by nothing, in the site scan), so
  neither can expand to nothing while the other stays;
* the mov writes the SAME register at offset 0, and the clear starts exactly where the mov stops
  (`clear offset == mov width`): contiguous, no hole between the two halves and no nibble done
  twice;
* `clear width + mov width` covers the full width the register is then USED at -- the widest
  `offset + width` of any later reference to it, up to the next full redefinition, falling back to
  its `hex.vec` declaration when no later reference carries a width. A narrowing that leaves the
  top nibbles dirty fails here. Clearing MORE than that is not a fault: it wastes calls but paints
  no wrong pixel, and five sites are in that shape (`frame_render.fj` L582, L1023, L1213, L2347 and
  L2417, each clearing 8 and reading 2). Clearing more than the register HOLDS is a fault -- that
  runs into its neighbour, which is how an out-of-bounds `mov 5` register read mis-rejected
  41-2,290 sprite pixels in 2026-09 (docs/handoff-fj-wide-pointers.md; the byte-exact gate caught
  that one before it could ship).

Widths stay SYMBOLIC (`w/4 - idx_n`, `w/4 - 2`): each identity is evaluated under several
assignments of the macro parameters, with `w` taken from `doomfj.harness` so it is the width this
build actually assembles at, and it must hold under all of them. Both of those are load-bearing and
both have a control below that goes red when they are sabotaged (the two tests marked SABOTAGE
CONTROL: cutting the sweep to one assignment, and evaluating the identities at any other `w`).

WHAT THIS DOES NOT COVER, and none of it is a substitute for the byte-exact gates:

* A width hidden in a macro NAME (`frame.add4_chain`) or in a macro whose first argument is not a
  width (`cm.apply`, `hex.ptr_index`, `frame.ptr_index`) is invisible to the coverage half. At a
  site whose only later references are of that shape the fallback is the `hex.vec` declaration,
  which bounds the register, not how wide the code reads it.
* Only clears written with an OFFSET (`X + M*dw`) are treated as narrowed by the site scan. A clear
  narrowed by shrinking its width alone (`hex.zero 2, X` where 8 were needed) still looks like an
  ordinary clear and is not a site there.
* A rep-guarded narrowed clear does not get the COVERAGE half: whether the register is later read
  wider than the pair clears is not asked, because the statements around it are guarded too and
  this scan does not evaluate guards. Everything else about the pair is checked.
* The coverage half stops collecting reads at the next clear of the same base -- including a
  NARROWED one at an offset, which redefines only part of the register. A read past that point is
  not counted, so `used` can be under-estimated and a genuinely short clear+mov pass. Three sites
  in the tree stop that way today (`frame_render.fj:718`, `projection.fj:1347` and `:1354`); at
  each of them what was collected before the stop, or the `hex.vec` fallback, still pins the total.
* The pair scan is a WINDOW scan like the one that produced the bug, not a dataflow analysis: it
  sees a clear whose mov is `_SCAN_WINDOW` statements away, and would not see one paired across a
  whole macro body. It says nothing about clears with no mov anywhere near them. A pinned pair that
  vanishes is therefore asked a second question -- is the CLEAR still in the file? -- so that a mov
  drifting out of the window is not reported as the Z1 bug.
* It is a text scan, not the assembler: `rep(0, k)` / `stl.comp_if` compile-time guards are not
  evaluated (guards are compared as TEXT), aliasing between neighbouring `hex.vec`s is not
  modelled, and nothing here says the VALUE the mov copies is the right one. That is what
  `tests/fj/test_table_reader_ptr_clear.py` and the byte-exact gates are for.
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from doomfj.harness import W

FJ = Path("src/fj")
# every src/fj file `git show --stat 6c82984 c65da95` lists -- the whole blast radius of the passes.
NARROWED_FILES = ("fixed_point.fj", "frame_render.fj", "plane_bands.fj", "plane_render.fj",
                  "projection.fj", "sim.fj", "stream_render.fj")
# the narrowed clears each file carries TODAY. Pinned, because prose cannot fail: with only "the
# scan still finds some" asserted, deleting one -- the Z1 bug's own shape -- left this file green.
EXPECTED_SITES = {"fixed_point.fj": 3, "frame_render.fj": 22, "plane_bands.fj": 4,
                  "plane_render.fj": 5, "projection.fj": 9, "sim.fj": 4, "stream_render.fj": 10}
# and the rep-guarded ones the site scan skips, pinned for the same reason and so that a NEW one
# cannot appear unnoticed -- being skipped there, it would otherwise be checked by nothing.
EXPECTED_REPPED = {"fixed_point.fj": 0, "frame_render.fj": 1, "plane_bands.fj": 0,
                   "plane_render.fj": 0, "projection.fj": 0, "sim.fj": 0, "stream_render.fj": 0}
# the emitter declares the hoisted scratch registers that the fj macros only name in a `<` list, so
# the `hex.vec` width of those lives here and in no .fj file (M1-HOIST).
HOIST_PY = Path("src/doomfj/wall_renderer.py")

_LABEL = re.compile(r"^([A-Za-z_]\w*)\s*:\s*")
_REP = re.compile(r"^rep\s*\([^)]*\)\s*")
_CALL = re.compile(r"^((?:[A-Za-z_]\w*)?\.)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+(.*)$")
_OFFSET = re.compile(r"^([A-Za-z_]\w*)\s*\+\s*(.+?)\s*\*\s*dw$")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_DECL = re.compile(r'(?m)^\s*"?([A-Za-z_]\w*):\s*(?:hex\.|\.)?vec\s+([^,"\n]+)')
# a width is a literal or an expression over `w` -- `8`, `w/4`, `w/4 - idx_n`. A bare identifier
# (`lit`, `srw_yabs`, `HOTTER_PAD`) is a register or a pad, and a `dw` makes it an ADDRESS rather
# than a width, which is what keeps `.read_byte_and_inc dst + 2*k*dw, ptr` out of the width scan.
_WIDTH = re.compile(r"^(?:\d+|[^/]*\bw\b.*)$")
_SAFE_EXPR = re.compile(r"^[0-9A-Za-z_ +\-*/()%]+$")
_CLEARS = ("zero", "sparse_zero")
_MOVS = ("mov", "sparse_mov")
# each identity must hold for every assignment of the macro parameters it is written over, so
# `w/4 - idx_n` + `idx_n` proves equal to `w/4` and not to one lucky number. `w` is not free: it is
# the width this build assembles at (R6 -- one source with the harness).
_ENVS = tuple(range(4))


def _ev(expr, env):
    """the value of an fj width/offset expression under one assignment of its free names."""
    names = {n: (W if n == "w" else 2 + (env * 3 + sum(map(ord, n))) % 5)
             for n in set(_IDENT.findall(expr))}
    return eval(expr.replace("/", "//"), {"__builtins__": {}}, names)


def _this_module():
    """this module object -- what the sabotage controls below monkeypatch. Looked up lazily, so a
    script that imports this file outside pytest does not have to register it in `sys.modules`."""
    return sys.modules[__name__]


def _is_width(arg):
    a = arg.strip()
    return bool(_WIDTH.match(a)) and "dw" not in a and bool(_SAFE_EXPR.match(a))


def _statements(text):
    """the file as LOGICAL statements: comments stripped, `\\` continuations joined, leading labels
    split off (a label is a jump target, so `mid: hex.mov ...` is a gap and not an adjacency), and
    the brace depth each one sits at so a scan can stop at the end of its macro body."""
    out, lines, i, depth = [], text.split("\n"), 0, 0
    while i < len(lines):
        start, buf = i + 1, lines[i]
        while buf.rstrip().endswith("\\") and i + 1 < len(lines):
            buf = buf.rstrip()[:-1]
            i += 1
            buf += lines[i]
        i += 1
        s = buf.split("//")[0].strip()
        if not s:
            continue
        labels = []
        while True:
            m = _LABEL.match(s)
            if not m:
                break
            labels.append(m.group(1))
            s = s[m.end():].strip()
        before = depth
        depth += s.count("{") - s.count("}")
        out.append(dict(line=start, text=s, labels=labels, depth=min(before, depth),
                        repped=bool(_REP.match(s))))
    return out


def _parse(text):
    """a macro call as (prefix, name, pad, width, dst, other args), or None.

    `hex.sparse_*` takes its pad first, so the width is one further along; every other hex macro in
    these files puts the width first."""
    m = _CALL.match(_REP.sub("", text))
    if not m:
        return None
    args = [a.strip() for a in m.group(3).split(",")]
    name = m.group(2)
    if name.startswith("sparse_"):
        if len(args) < 2:
            return None
        return m.group(1) or "", name, args[0], args[1], (args[2] if len(args) > 2 else ""), args[3:]
    return m.group(1) or "", name, None, args[0], (args[1] if len(args) > 1 else ""), args[2:]


def _split(dst):
    """`X + K*dw` -> (X, K); a plain `X` -> (X, None)."""
    m = _OFFSET.match(dst)
    return (m.group(1), m.group(2)) if m else (dst.strip(), None)


def _guard(text):
    """the `rep(...)` a statement is guarded by, or "". Compared as TEXT: this is not the
    assembler, and two guards that merely look alike are not proved to expand alike."""
    m = _REP.match(text)
    return m.group(0).strip() if m else ""


def _labels_at(st, j):
    """the labels a statement can be REACHED by: its own, plus the label-only lines above it. A
    label on its own line is a statement with no text (`rem_zero:` is written that way in every
    real file), so a clear's own `labels` list is usually empty and says nothing about the branch
    it sits on."""
    labels, k = list(st[j]["labels"]), j - 1
    while k >= 0 and not st[k]["text"]:
        labels = list(st[k]["labels"]) + labels
        k -= 1
    return tuple(labels)


@lru_cache(maxsize=1)
def _hoisted_scratch_text():
    return HOIST_PY.read_text(encoding="utf-8")


def _declared(statements, j, base):
    """the `hex.vec` width of `base`, from its own macro body first and the emitter's hoisted
    scratch second. Two different widths under one name means we cannot tell which one applies."""
    depth = statements[j]["depth"]
    lo, hi = j, j
    while lo > 0 and statements[lo - 1]["depth"] >= depth:
        lo -= 1
    while hi + 1 < len(statements) and statements[hi + 1]["depth"] >= depth:
        hi += 1
    body = "\n".join("".join(la + ": " for la in s["labels"]) + s["text"]
                     for s in statements[lo:hi + 1])
    for text in (body, _hoisted_scratch_text()):
        found = {m.group(2).split("//")[0].strip()
                 for m in _DECL.finditer(text) if m.group(1) == base}
        if len(found) == 1:
            return found.pop()
    return None


def _coverage_faults(st, j, base, wid, nwid, tag):
    """clear + mov must cover every nibble the register is then read at, and no nibble past it."""
    reads, k, depth = [], j + 2, st[j]["depth"]
    while k < len(st) and st[k]["depth"] >= depth:
        r = _parse(st[k]["text"])
        if r is not None:
            _, nm, _, rwid, rdst, rest = r
            rb, ro = _split(rdst)
            if rb == base and (nm in _CLEARS or (nm in _MOVS + ("set",) and ro is None)):
                break            # base is redefined from scratch; its old width stops mattering
            if _is_width(rwid):  # anything else that names `base` READS it at its width
                for arg in ([rdst] + rest if rdst else rest):
                    ab, ao = _split(arg)
                    if ab == base and (ao is None or _SAFE_EXPR.match(ao)):
                        reads.append((rwid, ao, st[k]["line"], st[k]["text"]))
        k += 1
    declared = _declared(st, j, base)
    if not reads and declared is None:
        return [f"{tag}\n    nothing later reads {base} at a visible width and it has no hex.vec "
                f"declaration, so its total width is unpinned -- no teeth at this site"]
    for env in _ENVS:
        total = _ev(wid, env) + _ev(nwid, env)
        used = max((_ev(r[0], env) + (_ev(r[1], env) if r[1] else 0) for r in reads), default=None)
        if used is None:
            used = _ev(declared, env)
        if total < used:
            where = ", ".join(f"{r[3]!r} (line {r[2]})" for r in reads) or f"hex.vec {declared}"
            return [f"{tag}\n    clears {wid} + moves {nwid} = {total} nibbles, but {base} is read "
                    f"at {used}: the top {used - total} are left dirty by {where}"]
        if declared is not None and total > _ev(declared, env):
            return [f"{tag}\n    clears {total} nibbles of {base}, declared hex.vec {declared} -- "
                    f"the clear runs past the register into its neighbour"]
    return []


def _completion_faults(st, j, p, tag, guard):
    """the ways the statement after a narrowed clear fails to complete it. `guard` is the `rep(...)`
    the clear itself carries, which the mov must carry too (both "" in the unguarded scan)."""
    pre, nm, pad, wid, dst, _ = p
    base, off = _split(dst)
    if j + 1 >= len(st):
        return [f"{tag}\n    the clear is the last statement in the file"]
    nxt = st[j + 1]
    if nxt["labels"]:
        return [f"{tag}\n    label(s) {nxt['labels']} land between the clear and "
                f"{nxt['text']!r} -- a path can reach the mov without the clear"]
    nguard = _guard(nxt["text"])
    if nguard != guard:
        if not guard:
            return [f"{tag}\n    the mov is rep-guarded ({nxt['text']!r}): it can expand to "
                    f"nothing while the narrowed clear stays"]
        return [f"{tag}\n    the clear is guarded by {guard!r} and the mov by "
                f"{nguard or 'nothing'}: one half can expand without the other"]
    q = _parse(nxt["text"])
    if q is None or q[1] not in _MOVS:
        return [f"{tag}\n    the next statement is {nxt['text']!r}, not the mov that is "
                f"supposed to clear the low {off} nibbles"]
    npre, nnm, npad, nwid, ndst, _ = q
    if npre != pre or (nnm == "sparse_mov") != (nm == "sparse_zero"):
        return [f"{tag}\n    the next statement is {nxt['text']!r}: a different macro "
                f"family or namespace from the clear, so it clears something else"]
    if pad != npad:
        return [f"{tag}\n    sparse pad {npad} on the mov, {pad} on the clear"]
    nbase, noff = _split(ndst)
    if nbase != base or noff is not None:
        return [f"{tag}\n    the mov writes {ndst!r}, not {base!r} at offset 0"]
    if not _SAFE_EXPR.match(nwid) or any(_ev(off, e) != _ev(nwid, e) for e in _ENVS):
        return [f"{tag}\n    the clear starts at +{off} but the mov covers {nwid}: "
                f"the two halves do not meet"]
    if guard:     # the coverage half reads the statements around the pair, and those are guarded
        return []   # too -- what width the register is later read at is the assembler's to say
    return _coverage_faults(st, j, base, wid, nwid, tag)


def _scan(text, name, repped):
    """-> (sites, faults) over the narrowed clears that are rep-guarded (`repped`) or not. A site is
    a clear written at an offset into its register -- the shape Z1/Z2/Z3 leave behind. A fault is a
    way that site breaks the premise."""
    st = _statements(text)
    sites, faults = [], []
    for j, s in enumerate(st):
        p = _parse(s["text"])
        if p is None or s["repped"] != repped:
            continue
        nm, wid, dst = p[1], p[3], p[4]
        if nm not in _CLEARS:
            continue
        off = _split(dst)[1]
        # the clear's own width and offset are widths BY POSITION, so a bare macro parameter
        # (`idx_n`) counts here even though `_is_width` -- which has to tell a width from a
        # register in an argument list it does not know the shape of -- would reject it.
        if off is None or not _SAFE_EXPR.match(wid) or not _SAFE_EXPR.match(off):
            continue
        tag = f"{name}:{s['line']}  {s['text']}"
        sites.append(tag)
        faults += _completion_faults(st, j, p, tag, _guard(s["text"]))
    return sites, faults


def narrowed_clear_faults(text, name="<fixture>"):
    """the unguarded narrowed clears, with every check this file has."""
    return _scan(text, name, repped=False)


def repped_narrowed_clear_faults(text, name="<fixture>"):
    """the narrowed clears a `rep(...)` guards, which the site scan skips.

    Everything the site scan asserts holds here except the coverage half, which is dropped because
    the reads around a guarded pair are guarded too and this scan does not evaluate guards. What is
    added is the property that makes such a pair safe under EVERY configuration: the mov carries the
    same guard as the clear, so the two expand together or not at all."""
    return _scan(text, name, repped=True)


# Z1's own matcher paired a clear with a mov "within 6 lines". A statement window twice that finds
# every pair it could have found, so nothing it would rewrite escapes the table below.
_SCAN_WINDOW = 12


def branch_split_clear_mov_pairs(text):
    """the clear/mov pairs a Z-style matcher finds and control flow separates.

    -> a sorted tuple of ((clear labels, clear), mov, labels reached in between). This is the OTHER
    half of the premise: the site scan can only look at clears the transform left behind, and Z1's
    mistake was to DELETE one (`N == M`, so nothing remained to scan). Here the clear is still full
    width, and what is pinned is that it is still there. The clear carries its own labels into the
    key so that `labelled_full_clears` can be asked about it by name when a pair goes missing."""
    st = _statements(text)
    out = []
    for j, s in enumerate(st):
        p = _parse(s["text"])
        if p is None or s["repped"]:
            continue
        _, nm, _, _, dst, _ = p
        base, off = _split(dst)
        if nm not in _CLEARS or off is not None:
            continue
        labels, jumped = [], False
        for k in range(j + 1, min(j + 1 + _SCAN_WINDOW, len(st))):
            if st[k]["depth"] < s["depth"]:
                break
            labels += st[k]["labels"]
            q = _parse(st[k]["text"])
            if q is not None and q[1] in _MOVS and _split(q[4]) == (base, None):
                if labels or jumped:
                    out.append(((_labels_at(st, j), s["text"]), st[k]["text"], tuple(labels)))
                break
            if ";" in st[k]["text"]:
                jumped = True
    return tuple(sorted(out))


def labelled_full_clears(text):
    """every full-width clear in the file, keyed the way the pair table keys them: (the labels it
    can be reached by, its text). A narrowed clear is not in here, because narrowing one IS the bug.
    A clear that no label reaches is keyed by its text alone, which is weaker -- none of the three
    pinned ones is in that shape."""
    st = _statements(text)
    out = set()
    for j, s in enumerate(st):
        p = _parse(s["text"])
        if p is None or s["repped"] or p[1] not in _CLEARS:
            continue
        if _split(p[4])[1] is None:
            out.add((_labels_at(st, j), s["text"]))
    return out


def _pin_state(text, pinned):
    """what the pin table has to say about `text` -> (deleted, drifted, new).

    A pinned pair that is no longer found is only the Z1 bug if the CLEAR is gone. If the clear is
    still there, the mov moved more than `_SCAN_WINDOW` statements away (or changed shape), which is
    not a bug but does mean the pin has stopped proving anything. The two have to be told apart: the
    window is 12 statements and the `scalestep` pin's mov sits at the far end of it -- TWO unrelated
    statements inserted in that branch lose the pair with the clear untouched (measured)."""
    found = branch_split_clear_mov_pairs(text)
    still = labelled_full_clears(text)
    gone = [p for p in pinned if p not in found]
    return ([p for p in gone if p[0] not in still], [p for p in gone if p[0] in still],
            [p for p in found if p not in pinned])


# EVERY CLEAR HERE IS LIVE ON ITS OWN BRANCH. A Z-style scan pairs it with the mov beside it and
# wants to narrow or delete it; doing so paints the wrong pixels on a path no single gate walks --
# `m2_std_gate` passed byte-exact over the deleted `tex_col_wrap` one. The two `proj` ones are
# results: an x2<=x1 span and a texture column that divides exactly both mean dst = 0; the
# `frame.clamp_row` one is the negative end of a clamp, where 0 IS the clamped value. Adding a row
# here is a claim that the new pair was checked and must stay whole, so do it deliberately, not to
# go green.
LIVE_CLEARS_ACROSS_A_BRANCH = {
    "fixed_point.fj": (),
    "frame_render.fj": (((("neg",), "hex.zero 8, dst"), "hex.mov 8, dst, bound",
                         ("hi_ck", "clamp_hi")),),
    "plane_bands.fj": (),
    "plane_render.fj": (),
    "projection.fj": (((("no_span",), "hex.zero 8, dst"), "hex.mov 8, dst, sst_quot",
                       ("have_span", "diff_neg")),
                      ((("rem_zero",), "hex.zero 8, dst"), "hex.mov 8, dst, tw", ("rem_nz",))),
    "sim.fj": (),
    "stream_render.fj": (),
}


def _real(name):
    return (FJ / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def scanned():
    return {n: narrowed_clear_faults(_real(n), n) for n in NARROWED_FILES}


@pytest.fixture(scope="module")
def repped_scanned():
    return {n: repped_narrowed_clear_faults(_real(n), n) for n in NARROWED_FILES}


@pytest.mark.parametrize("name", NARROWED_FILES)
def test_every_narrowed_clear_is_completed_by_the_next_statement(name, scanned):
    sites, faults = scanned[name]
    assert not faults, (f"{len(faults)} of {len(sites)} narrowed clear(s) in {name} break the "
                        f"zero-before-mov premise:\n\n" + "\n\n".join(faults))


@pytest.mark.parametrize("name", NARROWED_FILES)
def test_the_scan_finds_every_narrowed_clear_the_file_carries(name, scanned):
    """NON-VACUITY, AND DELETION. The count is the premise's population: a scan that stopped
    matching would pass the test above forever, and a narrowed clear deleted outright -- the Z1 bug
    in the direction that leaves nothing to inspect -- takes the count down with it."""
    sites, _ = scanned[name]
    assert len(sites) == EXPECTED_SITES[name], (
        f"{name} holds {len(sites)} narrowed clear(s), the table says {EXPECTED_SITES[name]}. If "
        f"one was deliberately removed or added, re-run the scan and update EXPECTED_SITES; if not, "
        f"this is a narrowed clear deleted or a scanner that stopped seeing `zero N, X + K*dw`:\n"
        + "\n".join(sites))


@pytest.mark.parametrize("name", NARROWED_FILES)
def test_every_rep_guarded_narrowed_clear_keeps_its_mov_under_the_same_guard(name, repped_scanned):
    sites, faults = repped_scanned[name]
    assert not faults, (f"{len(faults)} of {len(sites)} rep-guarded narrowed clear(s) in {name} can "
                        f"expand without their mov:\n\n" + "\n\n".join(faults))


@pytest.mark.parametrize("name", NARROWED_FILES)
def test_the_rep_guarded_sites_are_the_ones_the_table_names(name, repped_scanned):
    """the site scan SKIPS these, so an unpinned count is the one way a narrowed clear could sit in
    the tree checked by nothing at all."""
    sites, _ = repped_scanned[name]
    assert len(sites) == EXPECTED_REPPED[name], (
        f"{name} holds {len(sites)} rep-guarded narrowed clear(s), the table says "
        f"{EXPECTED_REPPED[name]}. A new one is only safe if its mov carries the same guard -- "
        f"check it, then update EXPECTED_REPPED:\n" + "\n".join(sites))


@pytest.mark.parametrize("name", NARROWED_FILES)
def test_the_clears_that_are_live_on_their_own_branch_are_all_still_whole(name):
    deleted, drifted, new = _pin_state(_real(name), LIVE_CLEARS_ACROSS_A_BRANCH[name])
    assert not deleted, (f"{name}: a clear that is LIVE ON ITS OWN BRANCH is gone from the file -- "
                         f"deleted or narrowed. This is the Z1 bug:\n"
                         + "\n".join(map(str, deleted)))
    assert not drifted, (f"{name}: the clear is STILL IN THE FILE, so this is not the Z1 bug: its "
                         f"mov is no longer within _SCAN_WINDOW={_SCAN_WINDOW} statements of it, or "
                         f"changed shape. The pin has stopped proving anything -- re-read the "
                         f"branch and update the table:\n" + "\n".join(map(str, drifted)))
    assert not new, (f"{name}: a new clear/mov pair separated by control flow. A Z-style rewrite "
                     f"MUST NOT touch it; check it, then add it to LIVE_CLEARS_ACROSS_A_BRANCH:\n"
                     + "\n".join(map(str, new)))


# -- the negative control (R9): FIXTURE text mutated into each shape that defeats a naive scan --
# Every mutant must be REJECTED and every GOOD fixture accepted, because a scanner that silently
# matched nothing would look exactly like a clean tree. The fixtures come in a NUMERIC and a
# SYMBOLIC form: symbolic widths swept over `_ENVS` are the checker's headline feature, so a control
# built on literals alone would leave it untested. Real files are mutated further down.
GOOD = """
ns demo {
    def narrow dst, src, other @ end {
        hex.zero 6, dst + 2*dw
        hex.mov 2, dst, src
        hex.mul_const 8, dst, dst, 3
        hex.add 8, other, dst
        ;end
      end:
    }
}
"""

GOOD_SPARSE = """
ns demo {
    def narrow_sparse dst, src, other @ end {
        hex.sparse_zero PAD, 3, dst + 5*dw
        hex.sparse_mov PAD, 5, dst, src
        hex.mul_lo 8, other, dst, src
        ;end
      end:
    }
}
"""

# the shape the three `fixed_point.fj` table readers are in: both halves written over a macro
# PARAMETER, and a register declared at a literal width the symbolic clear has to land on exactly.
GOOD_SYMBOLIC = """
ns demo {
    def narrow_symbolic src, idx_n @ dst, end {
        hex.zero w/4 - idx_n, dst + idx_n*dw
        hex.mov idx_n, dst, src
        hex.add 8, dst, src
        ;end
      dst: hex.vec 8
      end:
    }
}
"""

# and the shape `frame_render.fj:2475` is in: both halves under the SAME compile-time guard.
GOOD_REPPED = """
ns demo {
    def narrow_repped src, flag @ dst, end {
        rep(flag, k) hex.zero 6, dst + 2*dw
        rep(flag, k) hex.mov 2, dst, src
        hex.add 8, dst, src
        ;end
      dst: hex.vec 8
      end:
    }
}
"""

MUTANTS = {
    # the Z1 bug itself: the clear is the whole result on its own branch, the mov is on the other
    "the_z1_shape_a_jump_and_a_label_between_them":
        GOOD.replace("        hex.mov 2, dst, src\n",
                     "        ;end\n      other:\n        hex.mov 2, dst, src\n"),
    "a_jump_between_the_clear_and_the_mov":
        GOOD.replace("        hex.mov 2, dst, src\n", "        ;end\n        hex.mov 2, dst, src\n"),
    "a_label_on_the_mov_itself":
        GOOD.replace("        hex.mov 2, dst, src", "      mid: hex.mov 2, dst, src"),
    "another_statement_between_them":
        GOOD.replace("        hex.mov 2, dst, src\n",
                     "        hex.inc 8, other\n        hex.mov 2, dst, src\n"),
    "a_clear_too_narrow_for_the_width_the_register_is_read_at":
        GOOD.replace("hex.zero 6, dst + 2*dw", "hex.zero 4, dst + 2*dw"),
    "a_mov_to_a_different_destination":
        GOOD.replace("hex.mov 2, dst, src", "hex.mov 2, other, src"),
    "a_mov_that_leaves_a_hole_under_the_clear":
        GOOD.replace("hex.mov 2, dst, src", "hex.mov 1, dst, src"),
    "a_mov_that_is_itself_offset":
        GOOD.replace("hex.mov 2, dst, src", "hex.mov 2, dst + 2*dw, src"),
    "a_rep_guarded_mov_that_can_expand_to_nothing":
        GOOD.replace("hex.mov 2, dst, src", "rep(1-flag, k) hex.mov 2, dst, src"),
    "no_mov_at_all":
        GOOD.replace("        hex.mov 2, dst, src\n", ""),
    "a_sparse_pair_whose_pads_disagree":
        GOOD_SPARSE.replace("hex.sparse_mov PAD, 5", "hex.sparse_mov OTHER_PAD, 5"),
    "a_sparse_clear_too_narrow_for_its_read":
        GOOD_SPARSE.replace("hex.sparse_zero PAD, 3", "hex.sparse_zero PAD, 1"),
    # the same failures written over a macro PARAMETER instead of a literal: the widths the shipped
    # readers are actually written in, and the half of the checker the literal fixtures never reach.
    "a_symbolic_clear_that_starts_one_nibble_above_the_mov":
        GOOD_SYMBOLIC.replace("hex.zero w/4 - idx_n, dst + idx_n*dw",
                              "hex.zero w/4 - idx_n - 1, dst + (idx_n+1)*dw"),
    "a_symbolic_mov_narrower_than_the_clears_offset":
        GOOD_SYMBOLIC.replace("hex.mov idx_n, dst, src", "hex.mov idx_n - 1, dst, src"),
    "a_symbolic_clear_too_narrow_for_the_width_the_register_is_read_at":
        GOOD_SYMBOLIC.replace("hex.zero w/4 - idx_n,", "hex.zero w/4 - idx_n - 2,"),
    "a_symbolic_clear_that_runs_past_the_register":
        GOOD_SYMBOLIC.replace("hex.zero w/4 - idx_n,", "hex.zero w/4 - idx_n + 2,"),
}

REPPED_MUTANTS = {
    "the_two_halves_carry_different_guards":
        GOOD_REPPED.replace("rep(flag, k) hex.mov", "rep(1-flag, k) hex.mov"),
    "the_mov_lost_the_guard_the_clear_still_has":
        GOOD_REPPED.replace("rep(flag, k) hex.mov 2, dst, src", "hex.mov 2, dst, src"),
    "a_guarded_clear_with_no_mov_under_it":
        GOOD_REPPED.replace("        rep(flag, k) hex.mov 2, dst, src\n", ""),
}


@pytest.mark.parametrize("good", [GOOD, GOOD_SPARSE, GOOD_SYMBOLIC],
                         ids=["plain", "sparse", "symbolic"])
def test_the_control_fixture_is_accepted(good):
    sites, faults = narrowed_clear_faults(good)
    assert len(sites) == 1, f"the fixture should hold exactly one narrowed clear, found {sites}"
    assert not faults, "\n\n".join(faults)


@pytest.mark.parametrize("shape", sorted(MUTANTS))
def test_the_checker_rejects(shape):
    sites, faults = narrowed_clear_faults(MUTANTS[shape], shape)
    assert faults, f"MUTANT ACCEPTED: {shape}\nsites={sites}\n\n{MUTANTS[shape]}"


def test_the_guarded_fixture_is_accepted_by_the_guarded_scan_and_invisible_to_the_other():
    sites, faults = repped_narrowed_clear_faults(GOOD_REPPED)
    assert len(sites) == 1, f"the fixture should hold exactly one guarded clear, found {sites}"
    assert not faults, "\n\n".join(faults)
    assert narrowed_clear_faults(GOOD_REPPED)[0] == [], (
        "the site scan must SKIP a guarded clear -- that it does is why the guarded scan exists")


@pytest.mark.parametrize("shape", sorted(REPPED_MUTANTS))
def test_the_guarded_scan_rejects(shape):
    sites, faults = repped_narrowed_clear_faults(REPPED_MUTANTS[shape], shape)
    assert faults, f"MUTANT ACCEPTED: {shape}\nsites={sites}\n\n{REPPED_MUTANTS[shape]}"


# -- controls on the checker's OWN MACHINERY: sabotage either of the two things the docstring says
# the widths are checked with, and a test here has to go red. Both sabotages were silent before.

# `w/4 - 6` is 2 at the FIRST assignment `_ev` makes, which is what `idx_n` is there too -- so this
# mutant's two halves meet under that one assignment and part under the others.
ENV_MUTANT = GOOD_SYMBOLIC.replace("hex.mov idx_n, dst, src", "hex.mov w/4 - 6, dst, src")


def test_the_widths_are_swept_over_more_than_one_assignment(monkeypatch):
    """_ENVS SABOTAGE CONTROL. Cut the sweep to its first assignment and this mutant is accepted;
    that is the whole value of the sweep, so it has to be the difference between the two runs."""
    assert narrowed_clear_faults(ENV_MUTANT, "env")[1], (
        "the swept checker must reject a pair whose halves meet under one assignment only")
    monkeypatch.setattr(_this_module(), "_ENVS", _ENVS[:1])
    assert not narrowed_clear_faults(ENV_MUTANT, "env")[1], (
        "this mutant no longer separates one assignment from the sweep -- `_ev` changed, so "
        "re-tune ENV_MUTANT until a single assignment accepts it and the sweep does not")


def test_the_widths_are_evaluated_at_the_builds_w(monkeypatch):
    """W SABOTAGE CONTROL. GOOD_SYMBOLIC clears `w/4` nibbles of a register declared `hex.vec 8`, so
    it balances at the width this build assembles at and at no other: a stale or wrong `W` cannot
    sit in this module unnoticed."""
    assert not narrowed_clear_faults(GOOD_SYMBOLIC)[1]
    for bogus in (16, 64, 999):
        monkeypatch.setattr(_this_module(), "W", bogus)
        assert narrowed_clear_faults(GOOD_SYMBOLIC, f"w={bogus}")[1], (
            f"the symbolic fixture is accepted at w={bogus} as well as at the real {W}, so `w` is "
            f"not load-bearing here any more")


def test_the_hoisted_scratch_declarations_are_load_bearing(monkeypatch):
    """HOIST SABOTAGE CONTROL. Four real sites are pinned by a `hex.vec` the EMITTER writes and no
    .fj file does; drop that fallback and they have no teeth, which must be a fault, not silence."""
    monkeypatch.setattr(_this_module(), "_hoisted_scratch_text", lambda: "")
    for name in ("frame_render.fj", "stream_render.fj"):
        assert narrowed_clear_faults(_real(name), name)[1], (
            f"{name} is unaffected by losing the hoisted declarations, so the fallback the "
            f"docstring leans on is not pinning anything")


# -- and the same teeth on REAL code (R9, the way scratchpad/cr/alpha_check.py's selftest does it):
# every mutation below is applied to the shipped `src/fj` text IN MEMORY, and the file on disk is
# never touched. A fixture proves the checker reads its own grammar; only a real file proves it
# reads THIS tree.
REAL_MUTANTS = (
    # Z2's own clear, narrowed by a nibble -- the failure tests/fj/test_table_reader_ptr_clear.py
    # sees from the other side, as a read of the wrong table entry
    ("fixed_point.fj", ".zero w/4 - idx_n, ptr + idx_n*dw",
     ".zero w/4 - idx_n - 1, ptr + (idx_n+1)*dw", "do not meet"),
    ("stream_render.fj", "hex.zero w/4 - 4, srw_sidx + 4*dw",
     "hex.zero w/4 - 5, srw_sidx + 5*dw", "do not meet"),
    ("frame_render.fj", "hex.sparse_zero HOTTER_PAD, 6, x + 2*dw",
     "hex.sparse_zero HOTTER_PAD, 5, x + 3*dw", "do not meet"),
    ("plane_bands.fj", "hex.mov 2, lvl, bb_light", "hex.mov 1, lvl, bb_light", "do not meet"),
    # a way INTO the gap between the two halves: the Z1 bug's shape with nothing deleted
    ("plane_render.fj", "hex.mov 2, pixofs, y", "pix_gap: hex.mov 2, pixofs, y",
     "land between the clear"),
    # and the coverage half: a clear that no longer reaches the width the register is read at
    ("plane_render.fj", "hex.zero 6, pixofs + 2*dw", "hex.zero 3, pixofs + 2*dw", "left dirty"),
    ("sim.fj", "        hex.mov 4, dst, src\n", "", "not the mov that is supposed to clear"),
)


@pytest.mark.parametrize("name,old,new,expected", REAL_MUTANTS,
                         ids=[f"{m[0].split('.')[0]}{i}" for i, m in enumerate(REAL_MUTANTS)])
def test_the_checker_rejects_the_real_file_mutated(name, old, new, expected):
    text = _real(name)
    assert old in text, f"{old!r} is not in {name} any more -- re-point this mutant"
    mutated = text.replace(old, new, 1)
    assert mutated != text
    _, faults = narrowed_clear_faults(mutated, name)
    assert any(expected in f for f in faults), (
        f"MUTATED {name} ACCEPTED, or rejected for another reason than {expected!r}:\n"
        + "\n\n".join(faults))


def _drop_the_clear_under(text, label, clear):
    """delete the first `clear` line after `label:` -- Z1's edit, on real code, in memory."""
    lines = text.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.split("//")[0].strip() == label + ":"]
    assert at, f"{label}: is no longer a label in this file"
    k = [i for i in range(at[0] + 1, len(lines)) if lines[i].split("//")[0].strip() == clear]
    assert k, f"no {clear!r} under {label}: any more"
    return "\n".join(lines[:k[0]] + lines[k[0] + 1:])


def _insert_after_label(text, label, statement, times):
    lines = text.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.split("//")[0].strip() == label + ":"]
    assert at, f"{label}: is no longer a label in this file"
    return "\n".join(lines[:at[0] + 1] + [f"        {statement}"] * times + lines[at[0] + 1:])


@pytest.mark.parametrize("name,label", [("projection.fj", "rem_zero"),
                                        ("projection.fj", "no_span"),
                                        ("frame_render.fj", "neg")])
def test_deleting_a_live_clear_from_the_real_file_is_caught(name, label):
    """the Z1 bug re-committed in memory against the shipped text: the clear that IS the result on
    its branch is gone, the mov on the other branch stays, and every trajectory that never enters
    the branch is still byte-exact."""
    mutated = _drop_the_clear_under(_real(name), label, "hex.zero 8, dst")
    deleted, drifted, _ = _pin_state(mutated, LIVE_CLEARS_ACROSS_A_BRANCH[name])
    assert any(p[0][0] == (label,) for p in deleted), (
        f"deleting the {label}: clear from {name} is not reported as deleted: {deleted} {drifted}")
    assert not drifted, f"it must not be reported as a mov that drifted instead: {drifted}"


def test_a_mov_that_drifts_out_of_the_window_is_not_reported_as_the_z1_bug():
    """THE HONESTY CONTROL for the pin. `scalestep`'s mov sits inside a 12-statement window -- two
    inserted statements are enough to push it out -- and the pair then vanishes with the clear
    untouched. A whole window of them is inserted here so the control cannot go vacuous if the
    branch is rewritten. That has to read as a pin that stopped proving anything, not as the Z1
    bug."""
    mutated = _insert_after_label(_real("projection.fj"), "have_span", "hex.inc 8, sst_span",
                                  _SCAN_WINDOW)
    deleted, drifted, _ = _pin_state(mutated, LIVE_CLEARS_ACROSS_A_BRANCH["projection.fj"])
    assert not deleted, f"the clear is still in the file, so nothing may read as deleted: {deleted}"
    assert [p[0] for p in drifted] == [(("no_span",), "hex.zero 8, dst")], (
        f"the scalestep pin is the one that should have lost its mov, got {drifted}")


# -- and the same for the pair scan: the fixture is the shape of the three real branched sites --
BRANCHED = """
ns demo {
    def branched dst, src, a, b @ zero_path, mov_path, end {
        hex.cmp 8, a, b, mov_path, zero_path, mov_path
      zero_path:
        hex.zero 8, dst
        ;end
      mov_path:
        hex.mov 8, dst, src
        ;end
      end:
    }
}
"""

ADJACENT = """
ns demo {
    def adjacent dst, src @ end {
        hex.zero 8, dst
        hex.mov 8, dst, src
        ;end
      end:
    }
}
"""

BRANCH_MUTANTS = {
    # Z1's mistake, byte for byte: N == M, so the "redundant" clear was removed outright
    "z1_deletes_the_live_clear": BRANCHED.replace("        hex.zero 8, dst\n", ""),
    # and the other way it can go: the same clear narrowed instead of deleted
    "z1_narrows_the_live_clear": BRANCHED.replace("hex.zero 8, dst", "hex.zero 4, dst + 4*dw"),
}


def test_the_pair_scan_sees_a_clear_that_is_live_on_its_own_branch():
    assert branch_split_clear_mov_pairs(BRANCHED) == \
        (((("zero_path",), "hex.zero 8, dst"), "hex.mov 8, dst, src", ("mov_path",)),)


def test_an_adjacent_clear_and_mov_is_not_a_split_pair():
    """the pair table has to stay the list of clears a rewrite must not touch. A scan that reported
    every clear/mov pair would fill it with the ordinary ones and make a deletion invisible again."""
    assert branch_split_clear_mov_pairs(ADJACENT) == ()


@pytest.mark.parametrize("shape", sorted(BRANCH_MUTANTS))
def test_the_pair_scan_loses_the_pair_when_the_live_clear_goes(shape):
    """what the pinned table then reports as `deleted` -- this is the Z1 bug's own shape."""
    assert branch_split_clear_mov_pairs(BRANCH_MUTANTS[shape]) == (), \
        f"MUTANT ACCEPTED: {shape}\n{BRANCH_MUTANTS[shape]}"
    pinned = ((("zero_path",), "hex.zero 8, dst"), "hex.mov 8, dst, src", ("mov_path",))
    deleted, drifted, _ = _pin_state(BRANCH_MUTANTS[shape], (pinned,))
    assert deleted and not drifted, f"{shape} must read as deleted, not drifted: {deleted} {drifted}"


def test_narrowing_a_live_clear_also_fails_the_site_scan():
    _, faults = narrowed_clear_faults(BRANCH_MUTANTS["z1_narrows_the_live_clear"], "branched")
    assert faults, "a clear narrowed across a branch must fail the site scan too"
