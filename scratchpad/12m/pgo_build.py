"""pgo_build -- build flipjump-151's _fjcore.pyd with MSVC profile-guided optimisation, trained on
the game, WITHOUT touching the installed engine. An experiment tool: it measures what the compiler's
block layout is worth (the shipped loop runs its common path as a chain of TAKEN jumps, see
handoff-throughput-plan section 12), it is not the shipping build.

    python scratchpad/12m/pgo_build.py <outdir> [--frames 100] [--fjm build/doom_e1m1_blocked25.fjm]

Steps (the same cl/link flags setup.py's build_ext uses, plus the PGO switches):
  1. cl  /c /O2 /W3 /GL /DNDEBUG /MD  _fjcore.c                     -> obj
  2. link /LTCG:PGINSTRUMENT /PGD:<pgd>                              -> <outdir>/instr/_fjcore.pyd
  3. train: run the game for --frames frames on the instrumented engine (a fresh process; the
     profile .pgc is written when it exits) -- pgort140.dll is copied beside the .pyd
  4. pgomgr /merge, then link /LTCG:PGOPTIMIZE /PGD:<pgd>            -> <outdir>/pgo/_fjcore.pyd
The result's hash is printed; measure it with msframe --env-b MSFRAME_FJCORE_PYD=<outdir>/pgo/...
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT.parent / "flipjump-151"
SRC = FJ / "flipjump" / "interpreter" / "_fjcore.c"
VCVARS = r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
PY = Path(sys.executable).parent
CL_FLAGS = ["/c", "/nologo", "/O2", "/W3", "/GL", "/DNDEBUG", "/MD", "-I%s" % (PY / "include")]
LINK_FLAGS = ["/nologo", "/INCREMENTAL:NO", "/DLL", "/MANIFEST:EMBED,ID=2", "/MANIFESTUAC:NO",
              "/LIBPATH:%s" % (PY / "libs"), "/EXPORT:PyInit__fjcore"]

TRAIN = r'''
import os, sys, importlib.util, hashlib
from pathlib import Path
ROOT = Path(sys.argv[1]); fjm = Path(sys.argv[2]); nf = int(sys.argv[3]); pyd = sys.argv[4]
for q in (ROOT/"tests", ROOT/"src", ROOT/"scratchpad", ROOT/"scratchpad/12m", ROOT):
    sys.path.insert(0, str(q))
spec = importlib.util.spec_from_file_location("flipjump.interpreter._fjcore", pyd)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
sys.modules["flipjump.interpreter._fjcore"] = mod
import gamespeed as GS, m2_std_gate as gate
from doomfj.fastrun import FjmRunner, _fjcore
assert Path(_fjcore.__file__).resolve() == Path(pyd).resolve(), _fjcore.__file__
from flipjump.interpreter.io_devices.KeyboardIO import ScriptedKeyEventSource
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from flipjump.interpreter.io_devices.pygame_window import PcIO
from flipjump.utils.exceptions import IOReadOnEOF
per_frame = [{} for _ in range(GS.MENU_FRAMES)] + [{"forward": True} for _ in range(nf)]
events = GS.events_for(per_frame); n = len(per_frame)
runner = FjmRunner(fjm)
core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
for seg, k_ in runner._segments: core.add_segment(seg, k_)
for st, v in runner._runs: core.set_words(st, v)
screen = gate.Recording(); kb = gate.Stopper(ScriptedKeyEventSource(events), screen, n)
io = PcIO(screen, kb); io.attach_memory(NativeDeviceMemory(core, runner.width))
res = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
print("TRAIN frames=%d ops=%d pix=%s" % (len(screen.frames), res[1],
      hashlib.sha256(b"".join(screen.frames)).hexdigest()[:16]), flush=True)
'''


def run(args, cwd=None):
    cmd = 'cmd /c ""%s" >nul 2>&1 && %s"' % (VCVARS, " ".join('"%s"' % a if " " in a else a for a in args))
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    sys.stdout.write(p.stdout[-4000:])
    if p.returncode:
        sys.stderr.write(p.stderr[-4000:])
        raise SystemExit("failed: %s" % args[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--frames", type=int, default=100)
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked25.fjm")
    a = ap.parse_args()
    out = Path(a.outdir).resolve()
    for sub in ("obj", "instr", "pgo"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    obj = out / "obj" / "_fjcore.obj"
    pgd = out / "instr" / "_fjcore.pgd"
    instr = out / "instr" / "_fjcore.pyd"
    final = out / "pgo" / "_fjcore.pyd"

    print("1. compile"); run(["cl"] + CL_FLAGS + ["/Tc%s" % SRC, "/Fo%s" % obj])
    print("2. instrumented link")
    run(["link"] + LINK_FLAGS + ["/LTCG:PGINSTRUMENT", "/PGD:%s" % pgd, str(obj), "/OUT:%s" % instr])
    # the instrumented DLL needs the PGO runtime beside it
    vc_bin = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools\VC\Tools\MSVC")
    rt = sorted(vc_bin.glob("*/bin/HostX64/x64/pgort140.dll"))[-1]
    shutil.copy(rt, instr.parent / "pgort140.dll")
    print("3. train on %s for %d frames" % (a.fjm, a.frames))
    p = subprocess.run([sys.executable, "-u", "-c", TRAIN, str(ROOT), str(ROOT / a.fjm), str(a.frames), str(instr)],
                       capture_output=True, text=True, cwd=str(ROOT), env=dict(os.environ, PATH=str(instr.parent) + os.pathsep + os.environ["PATH"]))
    print(p.stdout[-2000:]); sys.stderr.write(p.stderr[-2000:])
    pgcs = list(instr.parent.glob("*.pgc"))
    if not pgcs:
        raise SystemExit("no .pgc profile was written - the instrumented engine did not run/exit cleanly")
    print("   profiles: %s" % ", ".join(x.name for x in pgcs))
    print("4. merge + optimised link")
    run(["pgomgr", "/merge", str(pgd)], cwd=str(instr.parent))
    run(["link"] + LINK_FLAGS + ["/LTCG:PGOPTIMIZE", "/PGD:%s" % pgd, str(obj), "/OUT:%s" % final])
    print("PGO engine: %s sha256 %s" % (final, hashlib.sha256(final.read_bytes()).hexdigest()[:16]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
