"""Build the FJPROFX instrumented engine: flipjump-151's _fjcore.c at 73e09c0, patched, compiled.

The installed engine is never touched: the patched source is written to <WORK>/engX and loaded by
path. The patch is ANCHORED -- each insertion point must occur exactly once in the source, or the
build stops -- and the source must be byte-identical (LF text) to _fjcore.c at 73e09c0, checked by
sha256, so the patch never lands on a source it was not written for.

What the patch adds, per op, in the FLAT loop only (at `jump_word_ready`, before `ops++`):
  * marker check: if the op's word is a phase marker, log (marker id, op index, obj[0..31]);
  * trace: if the op index is inside [FJPROFX_TRACE_LO, +FJPROFX_TRACE_N), record its word;
  * self[word] += 1                                  exact execution count per word;
  * OWNER attribution (see profx_state.inc.c): an op in OPAQUE code (map id != 0) that is
    LABELLED or within 16 words of the last accepted op is accepted as program flow; if it flips
    (f != 0) it becomes the owner. Everything else -- wflip chains, the block pool, the stl
    runtime, data reads, far unlabelled ops living in pad holes -- is charged to the owner;
  * incl[owner] += 1, obj[map(owner)] += 1           inclusive attribution;
  * output-bit ops are counted.
The IO callbacks remember the op count so `prof_mark()` (called at each present) can log it.

    python engine.py                       # -> <WORK>/engX/_fjcore.pyd
    python engine.py --write-patch fjcore_profx.patch --no-compile
"""
import argparse
import difflib
import hashlib
import re
import subprocess
import sys
from pathlib import Path

from common import HERE, ROOT, work_dir

FJ_COMMIT = "73e09c0"
SRC_REL = "flipjump/interpreter/_fjcore.c"
SRC_SHA256 = "51b5561674cfa53c93c82d7541a3efef5a525609d4843e3115b4d0c39e7a7a70"   # LF text at 73e09c0
VCVARS = r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
PY = Path(sys.executable).parent
CL_FLAGS = ["/c", "/nologo", "/O2", "/W3", "/GL", "/DNDEBUG", "/MD", "-I%s" % (PY / "include")]
LINK_FLAGS = ["/nologo", "/INCREMENTAL:NO", "/DLL", "/MANIFEST:EMBED,ID=2", "/MANIFESTUAC:NO", "/LTCG",
              "/LIBPATH:%s" % (PY / "libs"), "/EXPORT:PyInit__fjcore"]
ANCHOR = "/* force-inline so run_flat_loop's literal width/ww arguments constant-fold per width */"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source(fjdir):
    """_fjcore.c at 73e09c0 as LF text: the working copy if it matches, else `git show` (read-only)"""
    wc = Path(fjdir) / SRC_REL
    if wc.exists():
        text = wc.read_text(encoding="utf-8")        # universal newlines: CRLF checkouts normalise
        if sha(text) == SRC_SHA256:
            return text, "working copy %s" % wc
    p = subprocess.run(["git", "-C", str(fjdir), "show", "%s:%s" % (FJ_COMMIT, SRC_REL)],
                       capture_output=True)
    if p.returncode == 0:
        text = p.stdout.decode("utf-8").replace("\r\n", "\n")
        if sha(text) == SRC_SHA256:
            return text, "git show %s:%s" % (FJ_COMMIT, SRC_REL)
    raise SystemExit("the engine source is not _fjcore.c at %s (sha256 %s...) -- the patch is anchored "
                     "to that exact file" % (FJ_COMMIT, SRC_SHA256[:16]))


def patch(s):
    state = (HERE / "profx_state.inc.c").read_text(encoding="utf-8")
    funcs = (HERE / "profx_funcs.inc.c").read_text(encoding="utf-8")

    def sub1(text, old, new, what):
        n = text.count(old)
        if n != 1:
            raise SystemExit("anchor %r occurs %d times (want 1)" % (what, n))
        return text.replace(old, new, 1)

    s = sub1(s, ANCHOR, state + "\n" + ANCHOR, "state")
    s = sub1(s, "    m->flat_count = low_max_end;\n    m->flat_covers_all = (max_end <= low_max_end);",
             "    m->flat_count = low_max_end;\n    m->flat_covers_all = (max_end <= low_max_end);\n"
             "    gx_alloc(low_max_end);", "alloc")
    # the per-op hook: the FIRST `jump_word_ready:` + `ops++;` is the flat loop's (the paged loop
    # comes later in the file and is not instrumented: the game runs flat)
    s, n = re.subn(r"(jump_word_ready:\s*\n\s*)ops\+\+;", r"\1GX_OP(word_address, f, dw);\n            ops++;",
                   s, count=1)
    if n != 1:
        raise SystemExit("op anchor not found")
    old_out = ("        double io_start = monotonic_seconds();\n"
               "        PyObject* result = PyObject_CallFunctionObjArgs(write_bit, (f == dw + 1) ? Py_True : Py_False, NULL);")
    if s.count(old_out) < 1:
        raise SystemExit("output anchor not found")
    s = s.replace(old_out, "        double io_start = monotonic_seconds();\n        PyObject* result;\n"
                  "        gx_ops_io = ops;\n"
                  "        result = PyObject_CallFunctionObjArgs(write_bit, (f == dw + 1) ? Py_True : Py_False, NULL);", 1)
    old_in = "        double io_start = monotonic_seconds();\n        result = PyObject_CallNoArgs(read_bit);"
    if s.count(old_in) < 1:
        raise SystemExit("input anchor not found")
    s = s.replace(old_in, "        double io_start = monotonic_seconds();\n        gx_ops_io = ops;\n"
                  "        result = PyObject_CallNoArgs(read_bit);", 1)
    s = sub1(s, "static PyMethodDef module_methods[] = {", funcs, "module methods")
    return s


def _run(args, cwd):
    cmd = 'cmd /c ""%s" >nul 2>&1 && %s"' % (VCVARS, " ".join('"%s"' % a if " " in a else a for a in args))
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(cwd))
    if p.returncode:
        sys.stdout.write(p.stdout[-3000:])
        sys.stderr.write(p.stderr[-3000:])
        raise SystemExit("failed: %s" % args[0])


def build(out_dir=None, fjdir=None, write_patch=None, compile_=True):
    fjdir = Path(fjdir or (ROOT.parent / "flipjump-151"))
    out = Path(out_dir or (work_dir() / "engX"))
    out.mkdir(parents=True, exist_ok=True)
    src, where = source(fjdir)
    patched = patch(src)
    print("engine source: %s (sha256 %s..., flipjump %s)" % (where, SRC_SHA256[:16], FJ_COMMIT), flush=True)
    if write_patch:
        diff = difflib.unified_diff(src.splitlines(True), patched.splitlines(True),
                                    "a/" + SRC_REL, "b/" + SRC_REL)
        Path(write_patch).write_text("".join(diff), encoding="utf-8", newline="\n")
        print("patch written: %s" % write_patch, flush=True)
    (out / "_fjcore.c").write_text(patched, encoding="utf-8")
    if compile_:
        _run(["cl"] + CL_FLAGS + ["/Tc%s" % (out / "_fjcore.c"), "/Fo%s" % (out / "_fjcore.obj")], out)
        _run(["link"] + LINK_FLAGS + [str(out / "_fjcore.obj"), "/OUT:%s" % (out / "_fjcore.pyd")], out)
        pyd = out / "_fjcore.pyd"
        print("built %s (sha256 %s...)" % (pyd, hashlib.sha256(pyd.read_bytes()).hexdigest()[:16]), flush=True)
        return pyd
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fj", default=None, help="the flipjump-151 checkout (default: next to the repo)")
    ap.add_argument("--out", default=None, help="engine directory (default <WORK>/engX)")
    ap.add_argument("--write-patch", default=None, help="also write the unified diff here")
    ap.add_argument("--no-compile", action="store_true")
    a = ap.parse_args()
    build(a.out, a.fj, a.write_patch, not a.no_compile)


if __name__ == "__main__":
    main()
