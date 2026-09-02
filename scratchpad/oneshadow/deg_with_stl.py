"""Run scratchpad/deg_gate.py, printing WHICH stl it is about to build against.

    python deg_with_stl.py              -> the stock editable install (flipjump-151)
    python deg_with_stl.py --worktree   -> the one-shadow stl (flipjump-wide)

PYTHONPATH is NOT the way to do this, and finding that out cost a run. The flipjump worktree has
its own `tests/` package and it is a REGULAR package (it has an __init__.py), while
doom-flipjump/tests is a NAMESPACE one. A regular package wins over a namespace portion no matter
where the two sit on sys.path, so putting the worktree on PYTHONPATH silently rebinds `tests` and
deg_gate dies on `from tests.fj.stream_screen import StreamScreen`.

So: put the worktree on sys.path only long enough to bind `flipjump`, then take it straight back
off. Submodules imported later still resolve through the already-bound parent package, so the
whole stl comes from the worktree while every other name comes from doom.
"""
import runpy
import sys
from pathlib import Path

WORKTREE = Path("C:/Users/tomhe/Documents/flipjump-wide")

want_worktree = "--worktree" in sys.argv
if want_worktree:
    sys.path.insert(0, str(WORKTREE))
import flipjump  # noqa: E402
if want_worktree:
    sys.path.remove(str(WORKTREE))

stl = Path(flipjump.__file__).resolve().parent / "stl"
if want_worktree and WORKTREE.resolve() not in stl.parents:
    raise SystemExit("REFUSING: asked for the worktree stl but got " + str(stl))
if not want_worktree and WORKTREE.resolve() in stl.parents:
    raise SystemExit("REFUSING: asked for the stock stl but got the worktree at " + str(stl))
print("STL: " + str(stl), flush=True)

# --ptr-cell-bits N: assemble doom's program with a wider pointer cell. deg_gate calls
# fj.assemble() directly, so the CLI -D path is not involved -- the override is injected the same
# way the CLI does it, as a defines file placed BEFORE the stl.
bits = None
if "--ptr-cell-bits" in sys.argv:
    bits = int(sys.argv[sys.argv.index("--ptr-cell-bits") + 1])
    import tempfile
    from flipjump.utils import functions as _fjfuncs
    _d = Path(tempfile.mkdtemp()) / "_defines.fj"
    _d.write_text("ns hex {" + chr(10) + "ns pointers {" + chr(10)
                  + "PTR_CELL_BITS = %d" % bits + chr(10) + "}" + chr(10) + "}" + chr(10))
    _orig_get_file_tuples = _fjfuncs.get_file_tuples

    def _with_defines(files, *, no_stl=False):
        tuples = _orig_get_file_tuples(files, no_stl=no_stl)
        return [("d1", _d)] + tuples

    _fjfuncs.get_file_tuples = _with_defines
    import flipjump.flipjump_quickstart as _qs
    _qs.get_file_tuples = _with_defines

    import flipjump.assembler.assembler as _asm
    _orig_assemble = _asm.assemble

    def _assemble(input_files, memory_width, fjm_writer, **kw):
        kw["defines_file"] = _d
        return _orig_assemble(input_files, memory_width, fjm_writer, **kw)

    _asm.assemble = _assemble
    print("PTR_CELL_BITS: %d (defines file before the stl)" % bits, flush=True)

DEG = Path(__file__).resolve().parents[1] / "deg_gate.py"
sys.argv = [str(DEG)]
runpy.run_path(str(DEG), run_name="__main__")
