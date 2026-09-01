"""Assemble+run one .fj program against the ISOLATED stl copy, and print what it output.

The guard at the top is the point of this file: `flipjump` is installed editable and points
at C:/Users/tomhe/Documents/flipjump-151, which doom, bf2fj and c2fj all build against. This
runner refuses to start unless the imported package is the WORKTREE copy instead, so no
experiment here can reach the shared install.

usage:  python fjrun.py <prog.fj> [more.fj ...] [--width N] [--input BYTES]
"""

import sys
from pathlib import Path

WORKTREE = Path(r"C:\Users\tomhe\Documents\flipjump-wide")

sys.path.insert(0, str(WORKTREE))
import flipjump  # noqa: E402

_got = Path(flipjump.__file__).resolve()
if WORKTREE.resolve() not in _got.parents:
    raise SystemExit(f"REFUSING: flipjump resolved to {_got}, not the worktree copy under {WORKTREE}")

from flipjump import assemble, run_test_output  # noqa: E402
from flipjump.utils.classes import TerminationCause  # noqa: E402


def run(fj_files, width=64, fixed_input=b"", quiet=True):
    """assemble the files and run them; return (ok, output_bytes). Never raises on a bad run."""
    import io, contextlib, tempfile, os

    out = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        fjm = Path(td) / "a.fjm"
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                assemble([Path(f) for f in fj_files], fjm, memory_width=width, print_time=False)
        except Exception as e:                       # a compile error is a legitimate result here
            return False, f"ASSEMBLE-ERROR: {type(e).__name__}: {e}".encode()

        from flipjump.interpreter.fjm_run import run as fj_run
        from flipjump.interpreter.io_devices.FixedIO import FixedIO

        io_dev = FixedIO(fixed_input)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                term = fj_run(fjm, io_device=io_dev)
        except Exception as e:
            return False, f"RUN-ERROR: {type(e).__name__}: {e}".encode()

        got = io_dev.get_output(allow_incomplete_output=True)
        ok = term.termination_cause == TerminationCause.Looping
        return ok, got


if __name__ == "__main__":
    # --raw is how mutctl calls this file: as a SUBPROCESS, so that a mutated setter which
    # jumps into a loop instead of crashing can be killed on a timeout rather than hanging
    # the harness (that is exactly what happened on the first run, for 25 minutes).
    args = list(sys.argv[1:])
    raw = "--raw" in args
    if raw:
        args.remove("--raw")
    width = 64
    if "--width" in args:
        i = args.index("--width")
        width = int(args[i + 1])
        del args[i:i + 2]
    ok, got = run(args, width=width)
    if raw:
        sys.stdout.buffer.write((b"OK:" if ok else b"NO:") + got)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write("ok=%s" % ok + chr(10))
        sys.stdout.write("---8<--- output ---8<---" + chr(10))
        sys.stdout.write(got.decode("utf-8", errors="replace"))
        sys.stdout.write(chr(10) + "---8<--- end ---8<---" + chr(10))
