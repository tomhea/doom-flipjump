"""conftest.py puts THIS checkout's src first: a worktree's tests must test the worktree's code, not the installed
(main repo's) doomfj -- in this process and in the subprocesses tests start (M8 lesson, the C3 agent, 2026-10-19)."""
import os
import subprocess
import sys
from pathlib import Path

import doomfj

SRC = Path(__file__).resolve().parents[2] / "src"


def child_doomfj(env):
    r = subprocess.run([sys.executable, "-c", "import doomfj; print(doomfj.__file__)"], cwd=os.sep, env=env,
                       capture_output=True, text=True)
    return Path(r.stdout.strip()).resolve().parent.parent if r.returncode == 0 else None


def test_doomfj_is_this_checkouts():
    assert Path(doomfj.__file__).resolve().parent.parent == SRC


def test_a_subprocess_imports_this_checkouts_doomfj():
    assert child_doomfj(os.environ.copy()) == SRC


def test_control_the_path_is_what_decides(tmp_path):
    """the control: a child given ANOTHER directory first on PYTHONPATH imports that one's doomfj -- so the check above
    reads where doomfj came from, and would see a wrong path (in tmp_path: the child's import leaves a __pycache__)"""
    pkg = tmp_path / "doomfj"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    env = dict(os.environ, PYTHONPATH=str(tmp_path))
    assert child_doomfj(env) == tmp_path.resolve()
