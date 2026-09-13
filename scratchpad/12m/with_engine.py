"""with_engine -- run a gate, a script or pytest with a CANDIDATE _fjcore.pyd injected in place of
the installed engine, in-process, so the existing gates need no engine parameter of their own.

    python scratchpad/12m/with_engine.py <pyd> scratchpad/m2_std_gate.py --fjm build/X.fjm
    python scratchpad/12m/with_engine.py <pyd> --pytest tests/unit/test_native_memory.py -q

The candidate is placed in sys.modules as flipjump.interpreter._fjcore BEFORE flipjump is
imported, so every in-process importer sees it. It prints the engine's path and sha256 first, and
REFUSES to run if the injected engine is not the one flipjump ends up importing -- a gate that
silently tested the installed engine would be the worst kind of pass. (Subprocesses spawned by
a test still use the installed engine; the fj unit tests here are in-process.)"""
import hashlib
import importlib.util
import runpy
import sys
from pathlib import Path


def inject(pyd):
    pyd = Path(pyd).resolve()
    spec = importlib.util.spec_from_file_location("flipjump.interpreter._fjcore", str(pyd))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["flipjump.interpreter._fjcore"] = mod
    from flipjump.interpreter import _fjcore  # noqa: E402
    if Path(_fjcore.__file__).resolve() != pyd:
        raise SystemExit("with_engine: injection failed, flipjump imported %s" % _fjcore.__file__)
    sha = hashlib.sha256(pyd.read_bytes()).hexdigest()[:16]
    print("with_engine: %s sha256 %s" % (pyd, sha), flush=True)
    return sha


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    inject(sys.argv[1])
    if sys.argv[2] == "--pytest":
        import pytest
        raise SystemExit(pytest.main(sys.argv[3:]))
    script = sys.argv[2]
    sys.argv = [script] + sys.argv[3:]
    sys.path.insert(0, str(Path(script).resolve().parent))
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
