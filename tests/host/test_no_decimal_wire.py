"""A screen's `stdin=` must come from the wire encoder. CLOSED-WORLD: anything else is a failure.

WHY THIS EXISTS. `state_wire="dec"` retired; the program is binary-only. A decimal feed does not
error -- the magic byte fails, the program halts at `bad:` after ~200 ops, and the screen shows a
blank frame. That reads as a catastrophic render bug, and CLAUDE.md records two debugging cycles
lost to exactly it. Worse, a gate fed that way still PASSES its own byte-exactness control, because
two blank frames compare equal. `scratchpad/ca2_sweep.py` -- the governing 260-frame metric -- was
in precisely that state.

⚠ WHY THIS IS A WHITELIST AND NOT A PATTERN MATCHER, which is the second thing that went wrong.
The first version detected the BAD shape: f-strings, `%d` formats, bytes literals of digits. That
is OPEN-WORLD -- an unrecognised shape passes -- and review found eleven escapes, among them
`b'%d' % (...)` (bytes, not str), a positional `StreamScreen(feed)`, `"<lf>".join(...)`, `.format`,
and, most damningly, `feed = f"..."` on one line and `StreamScreen(stdin=feed)` on the next, which
is the very file the round was written to catch. Trading two fixable false positives for eleven
false negatives is the "control that cannot fail" this whole review round was about.

So: the value must be traceable to `encode_feed*`. Names are resolved, concatenation is walked
(`encode_feed(...) + blob_tail` is how the hosted gates send things), and ONE level of local helper
is followed, because `scripts/walk_e1m1.py` legitimately wraps the encoder in a `wire()` closure.
Anything the rule cannot trace is a FAILURE, not a pass -- and the one real exception is named
below with its reason rather than left to a pattern.
"""
import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCREENS = ("StreamScreen", "CountScreen", "DumpScreen", "Recording", "InMemoryScreen")
ENCODER = "encode_feed"

# EXEMPTIONS, each named with its reason and each traced BY HAND on 2026-08-29. This list is the
# honest end of a closed-world rule: full inter-procedural resolution is a research problem, and an
# ever-cleverer resolver that quietly gives up is exactly the open-world failure this file exists
# to avoid. A visible list can be re-checked; a silent fallthrough cannot. The length is asserted
# below rather than written in prose, because this comment has now been wrong at six and at seven.
#
# Every entry below reaches its screen through a helper that returns `encode_feed(...)` -- across
# a module boundary, a tuple unpack, or a scope the resolver does not follow. Each was verified by
# reading it, and each is re-checked every run by the rot test below.
EXEMPT = {
    # the SCREEN'S OWN unit test: two raw bytes to prove `read_bit` drains an independent buffer,
    # with no program on the other end to care what wire it is
    "tests/fj/test_stream_screen.py",
    # `run_one(r, core, feed)` -- fed from `m14_feed()`, which builds the binary wire
    "scratchpad/dirty_census.py",
    # `run_one(r, core, blob)` -- fed from `feed()`, `encode_feed(...) + THINGS`
    "scratchpad/dirty_restore.py",
    # `G.feed(...)` across a module boundary: G is m14_gate, whose `feed` is binary
    "scratchpad/m145_diag.py",
    # `run(fjm, feed)` -- fed from the local `feed()` helper
    "scratchpad/m14_gate.py",
    # `m14_feed()` returns (bytes, n_things); its docstring says "the binary wire, exactly as
    # m14_sweep / dirty_census build it"
    "scratchpad/m1_dirtymap.py",
    # `f = feed(...)`, the local helper at :213
    "scratchpad/m1d_loop.py",
    # `run(core, f)` where `f = feed(...)` -- `feed` returns encode_feed(...) + things + bindings.
    # The resolver is SCOPE-BLIND, and this file binds `f` in four different scopes (two file
    # handles, a comprehension, the feed), so it cannot tell which one reaches the screen. Exempt
    # for that reason -- and the file already protects itself better than this guard could:
    # `assert ops1 > 1_000_000, "CONTROL 3 (vacuity): ... wrong wire"` fires at the ~209 ops a
    # `bad:` halt produces.
    "scratchpad/m1c_restore_set.py",
}


def _returns_of(fn):
    return [n.value for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]


def from_encoder(node, tree, depth=0):
    """Is this value traceable to `encode_feed*`? Unknown means NO."""
    if node is None or depth > 3:
        return False
    if isinstance(node, ast.Call):
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
        if name.startswith(ENCODER):
            return True
        for fn in ast.walk(tree):                       # one level of local helper
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                rets = _returns_of(fn)
                return bool(rets) and all(from_encoder(r, tree, depth + 1) for r in rets)
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return from_encoder(node.left, tree, depth) or from_encoder(node.right, tree, depth)
    if isinstance(node, ast.IfExp):
        return (from_encoder(node.body, tree, depth) and from_encoder(node.orelse, tree, depth))
    if isinstance(node, ast.Name):
        assigns, seen = [], 0
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == node.id:
                        assigns.append(n.value)
                    elif isinstance(t, ast.Tuple):
                        # `feed, nth = m14_feed(...)` -- most real call sites look like this
                        names = [e.id for e in t.elts if isinstance(e, ast.Name)]
                        if node.id in names:
                            assigns.append(_tuple_element(n.value, names.index(node.id), tree))
            elif (isinstance(n, ast.Name) and n.id == node.id
                  and isinstance(n.ctx, (ast.Store, ast.Del))):
                seen += 1                      # a WRITE we have not read; a read is harmless
        # ⚠ ANY BINDING WE DID NOT READ makes this unknowable. Walking `ast.Assign` alone let an
        # `AnnAssign`, a for-target, a `with ... as` or an `AugAssign` rebind the name after a
        # traceable assignment, and a fully decimal feed then passed. Counting every Name
        # occurrence was the over-correction: a READ is harmless, and it flagged six constants
        # that are simply used twice. Stores and deletes only.
        if seen > len(assigns):
            return False
        if assigns:
            return all(from_encoder(v, tree, depth + 1) for v in assigns)
        # a PARAMETER: the value arrives from the caller, so trace it there. Without this the rule
        # flagged five helpers of the shape `def run_one(r, core, feed): StreamScreen(stdin=feed)`,
        # which are perfectly fine and are handed encoder output at every call site.
        return _param_always_encoded(node.id, tree, depth)
    return False


def _tuple_element(value, index, tree):
    """the `index`-th element of a tuple-valued expression, or None if it cannot be known"""
    if isinstance(value, ast.Tuple) and index < len(value.elts):
        return value.elts[index]
    if isinstance(value, ast.Call):                     # a helper returning a tuple
        name = getattr(value.func, "id", None) or getattr(value.func, "attr", None) or ""
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                rets = _returns_of(fn)
                elts = [r.elts[index] for r in rets
                        if isinstance(r, ast.Tuple) and index < len(r.elts)]
                if elts and len(elts) == len(rets):
                    return elts[0] if len(elts) == 1 else None
    return None


def _param_always_encoded(pname, tree, depth):
    """`pname` is a parameter somewhere; are ALL in-file calls passing an encoded value for it?

    A function nobody calls in this file is unknowable, so it fails -- closed-world."""
    owners = [fn for fn in ast.walk(tree)
              if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
              and any(a.arg == pname for a in fn.args.args)]
    if not owners:
        return False
    for fn in owners:
        idx = [a.arg for a in fn.args.args].index(pname)
        calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
                 and (getattr(c.func, "id", None) or getattr(c.func, "attr", None)) == fn.name]
        if not calls:
            return False
        for c in calls:
            if len(c.args) > idx:
                value = c.args[idx]
            else:
                value = next((kw.value for kw in c.keywords if kw.arg == pname), None)
            if not from_encoder(value, tree, depth + 1):
                return False
    return True


def _is_newline_expr(node):
    """`chr(10)` and the `.join`/`.format` that carry it -- the repo's own newline idiom, which a
    Constant test cannot see because `chr(10)` is a Call.
    ⚠ ONLY EVER CALLED ON AN `.encode()` RECEIVER. A newline is not a wire: `chr(10)` is this
    repo's newline idiom and appears in prints throughout the diagnostics, and `"<lf>".join([...])`
    is how fj SOURCE is assembled -- flagging either on its own made this fire on
    `print(chr(10) + "PHASE 1b ...")` and on a test building a two-line fj program. Under an
    `.encode()`, the same shapes are a feed.
    """
    if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "chr"
            and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 10):
        return True                                # chr(10) inside an encoded expression
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)             and node.func.attr in ("join", "format"):
        recv = node.func.value
        if isinstance(recv, ast.Constant) and isinstance(recv.value, str) and chr(10) in recv.value:
            return True
        if _is_newline_expr(recv):
            return True
    return False


def encodes_newline_decimals(source: str):
    """`[lineno]` for every `<something with a newline>.encode()` -- the ROT CHECK for exemptions.

    This is the pattern matcher that was wrong as the primary rule, doing the job it is actually
    good at: not "is this feed safe" (open-world, and it missed eleven shapes) but "did an exempted
    file grow something that LOOKS like the retired wire". A false positive here costs one re-trace;
    the primary rule stays closed-world. It looks only at `.encode()` receivers, so the `print(f"a
    newline")` that is all over these diagnostics does not trip it."""
    LF = chr(10)
    out = []
    tree = ast.parse(source)
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "encode"):
            continue
        for sub in ast.walk(n.func.value):
            if isinstance(sub, ast.JoinedStr) and any(
                isinstance(v, ast.Constant) and isinstance(v.value, str) and LF in v.value
                for v in sub.values
            ):
                out.append(n.lineno)
            elif (isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Mod)
                  and isinstance(sub.left, ast.Constant)
                  and isinstance(sub.left.value, (str, bytes))
                  and ("%d" in sub.left.value if isinstance(sub.left.value, str)
                       else b"%d" in sub.left.value)):
                out.append(n.lineno)
            elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and LF in sub.value:
                out.append(n.lineno)                # "<lf>".join(...), "{}<lf>".format(...)
            elif _is_newline_expr(sub):
                out.append(n.lineno)                # chr(10).join(...), str(a)+chr(10)+str(b)
    # ⚠ SHAPES THAT NEVER REACH `.encode()` NEED THEIR OWN PASS. The bytes `%` arm used to sit in
    # the loop above, where `bytes` has no `.encode()` -- a dead branch that fired only on
    # `(b"%d" % x).encode()`, which raises at runtime. So `b"%d<lf>%d" % (a, b)`, escape #4 in this
    # file's own control, went unseen. `chr(10)` is this repo's newline idiom and was invisible too.
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, bytes) and LF.encode() in n.value:
            text = n.value.decode("latin-1")
            if any(part.strip().lstrip("-").isdigit() for part in text.split(LF) if part.strip()):
                out.append(n.lineno)                # b"-435<lf>223"
        elif (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod)
              and isinstance(n.left, ast.Constant) and isinstance(n.left.value, bytes)
              and b"%d" in n.left.value):
            out.append(n.lineno)                    # b"%d<lf>%d" % (a, b)
    return sorted(set(out))


def bad_feeds(source: str):
    """`[(lineno, screen)]` for every screen whose stdin is not traceable to the wire encoder.
    Positional first arguments are checked too -- `StreamScreen(feed)` was one of the escapes."""
    tree = ast.parse(source)
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
        if name not in SCREENS:
            continue
        value = next((kw.value for kw in n.keywords if kw.arg == "stdin"), None)
        if value is None and n.args:
            value = n.args[0]
        if value is None:
            continue                                    # no feed at all: nothing to get wrong
        if not from_encoder(value, tree):
            out.append((n.lineno, name))
    return out


def test_every_screen_is_fed_the_binary_wire():
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    assert len(files) > 50, "the listing looks wrong (%d) -- vacuous run" % len(files)
    bad = []
    for rel in files:
        if rel in EXEMPT:
            continue
        try:
            found = bad_feeds((ROOT / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        bad += [(rel, line, screen) for line, screen in found]
    assert not bad, ("screens fed something not traceable to encode_feed*:" + chr(10)
                     + chr(10).join("  %s:%d %s(...)" % t for t in bad))


def test_the_rot_check_sees_every_way_this_repo_writes_a_newline():
    """R9 for the ROT CHECK itself, which review measured at 7 of 12 shapes: its bytes-`%` arm sat
    inside the `.encode()` walk, and `bytes` has no `.encode()`, so it fired only on code that
    raises at runtime. The three GOOD cases are the false positives that shaped it -- a print, and
    the `"<lf>".join([...])` that assembles fj SOURCE."""
    BS = chr(92)
    for src in ('x = f"{a}' + BS + 'n{b}".encode()',
                'x = ("%d' + BS + 'n%d" % (a, b)).encode()',
                'x = b"-435' + BS + 'n223"',
                'x = b"%d' + BS + 'n%d" % (a, b)',
                'x = chr(10).join(p).encode()',
                'x = "' + BS + 'n".join(p).encode()',
                'x = "{}' + BS + 'n".format(a).encode()',
                'x = (str(a) + chr(10) + str(b)).encode()'):
        assert encodes_newline_decimals(src), src
    for src in ('print(chr(10) + "hi")',
                'main = "' + BS + 'n".join(["stl.startup", "a;b"])',
                'x = encode_feed_mapunits(a, b, c)'):
        assert not encodes_newline_decimals(src), src


def test_it_rejects_every_shape_that_escaped_the_pattern_matcher():
    """R9, and the reason this file was rewritten. Each of these passed the bad-shape detector."""
    LF = chr(10)
    BS = chr(92)
    for src in ('StreamScreen(stdin=f"{x}' + BS + 'n{y}".encode())',
                'StreamScreen(stdin=("%d%s" % (vx, chr(10))).encode())',
                'StreamScreen(stdin=b"-435' + BS + 'n223")',
                'StreamScreen(stdin=b"%d' + BS + 'n%d" % (x, y))',
                'feed = f"{x}' + BS + 'n{y}".encode()' + LF + 'StreamScreen(stdin=feed)',
                'StreamScreen(f"{x}' + BS + 'n{y}".encode())',
                'StreamScreen(stdin="' + BS + 'n".join(parts).encode())',
                'StreamScreen(stdin="{}' + BS + 'n".format(x).encode())'):
        assert bad_feeds(src), src


def test_it_accepts_the_binary_wire_and_its_one_legitimate_wrapper():
    """... and the other half. Without this, a rule that rejects everything would pass above."""
    LF = chr(10)
    assert bad_feeds("StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))") == []
    assert bad_feeds("StreamScreen(stdin=encode_feed(x, y, a, 0) + blob_tail)") == []
    assert bad_feeds("f = encode_feed_mapunits(x, y, a)" + LF + "StreamScreen(stdin=f)") == []
    assert bad_feeds("def wire(k):" + LF + "    return encode_feed(x, y, a, k)" + LF
                     + "StreamScreen(stdin=wire(0))") == []
    # a parameter, traced to its in-file call sites
    assert bad_feeds("def run(feed):" + LF + "    StreamScreen(stdin=feed)" + LF
                     + "run(encode_feed_mapunits(x, y, a))") == []


def test_every_exemption_still_exists_and_still_has_no_decimal_shape():
    assert len(EXEMPT) == 8, ("EXEMPT changed size -- update this number deliberately, and the "
                              "reason for each entry. The prose describing it has been wrong "
                              "twice, which is why the count is asserted and not written out.")
    """An exemption list rots. Each entry must still be a tracked file, and must still contain no
    decimal-wire construction -- checked crudely on purpose, because the point is to notice when
    one of these files changes under the exemption, not to re-derive the trace."""
    tracked = set(subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split())
    for rel in sorted(EXEMPT):
        assert rel in tracked, f"{rel} is exempted but no longer tracked -- drop it from EXEMPT"
        found = encodes_newline_decimals((ROOT / rel).read_text(encoding="utf-8"))
        assert not found, (f"{rel} grew a decimal-wire construction while exempted, at line(s) "
                           f"{found} -- re-trace it or drop the exemption")


def test_a_rebind_the_resolver_cannot_read_makes_the_feed_unknown():
    """R9: the four rebinding forms that are not `ast.Assign`. Each must FAIL even though a
    traceable assignment comes first -- and a plain second READ of the name must not."""
    LF = chr(10)
    for src in ("f = encode_feed_mapunits(x, y, a)" + LF + "f: bytes = other" + LF
                + "StreamScreen(stdin=f)",
                "f = encode_feed_mapunits(x, y, a)" + LF + "for f in items: pass" + LF
                + "StreamScreen(stdin=f)",
                "f = encode_feed_mapunits(x, y, a)" + LF + "with open(p) as f: pass" + LF
                + "StreamScreen(stdin=f)",
                "f = encode_feed_mapunits(x, y, a)" + LF + "f += tail" + LF
                + "StreamScreen(stdin=f)"):
        assert bad_feeds(src), src
    # ... and a second READ is not a rebind: this is the shape of six real constants
    assert bad_feeds("W = encode_feed_mapunits(x, y, a)" + LF + "print(len(W))" + LF
                     + "StreamScreen(stdin=W)") == []


def test_a_parameter_fed_a_decimal_value_at_one_call_site_is_caught():
    """the parameter path must not become a hole: ONE bad call site is enough"""
    LF = chr(10)
    BS = chr(92)
    src = ("def run(feed):" + LF + "    StreamScreen(stdin=feed)" + LF
           + "run(encode_feed_mapunits(x, y, a))" + LF
           + 'run(f"{x}' + BS + 'n{y}".encode())')
    assert bad_feeds(src)
