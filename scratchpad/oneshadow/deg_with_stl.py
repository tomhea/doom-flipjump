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

DEG = Path(__file__).resolve().parents[1] / "deg_gate.py"
sys.argv = [str(DEG)]
runpy.run_path(str(DEG), run_name="__main__")
