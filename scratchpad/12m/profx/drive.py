"""Run the game binary on the FJPROFX engine (or the installed one) and record everything.

    python drive.py games <prefix>              calibration + gamespeed's 10 games (the binding workload)
    python drive.py walk N <prefix>             menu + N forward frames (msframe's script)
    python drive.py still N <prefix> [--poke]   menu + N idle frames; --poke marks runtime thing
                                                (g mod 75) DIRTY at the first poll of game frame g,
                                                so bind_things runs its dirty path -> ptloc_walk
  options: --stock (installed engine: a control, no dumps)  --trace LO N (record ops [LO, LO+N))
           --fjm PATH  --lock PATH (take the binary lock)  --lock-name NAME

<prefix> is relative to <WORK> unless absolute. Writes <prefix>.runs.json (per run: ops, presented
frames, the op count at each present, frame sha256s, things poked) and, on the FJPROFX engine,
<prefix>.log.bin / .marks.bin / .self.bin / .incl.bin (+ .trace.bin).

Composition is m2_std_gate.run_fj's (FjmRunner, Recording, Stopper, PcIO, NativeDeviceMemory) --
the object `fj --run build/<x>.fjm --io pc` builds -- with two subclasses that only OBSERVE (the
present hook) or, under --poke, write thss_rt cells the M1 reset restores at frame end.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import (ROOT, BinaryLock, default_fjm, engine_env, engine_pyd, label_dict,  # noqa: E402
                    work_dir)

DW = 64


def parse(argv):
    pos, opt = [], {"stock": False, "poke": False, "trace": None, "fjm": None, "lock": None,
                    "lock_name": "profx drive"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--stock":
            opt["stock"] = True
        elif a == "--poke":
            opt["poke"] = True
        elif a == "--trace":
            opt["trace"] = (int(argv[i + 1]), int(argv[i + 2]))
            i += 2
        elif a in ("--fjm", "--lock", "--lock-name"):
            opt[a[2:].replace("-", "_")] = argv[i + 1]
            i += 1
        else:
            pos.append(a)
        i += 1
    return pos, opt


def out_prefix(p):
    p = Path(p)
    return p if p.is_absolute() else work_dir() / p


def main(argv):
    pos, opt = parse(argv)
    need_env = os.environ.get("FJPROFX_MAP") is None or (
        opt["trace"] is not None and os.environ.get("FJPROFX_TRACE_LO") is None)
    if not opt["stock"] and need_env:
        # the engine reads its inputs from the environment at the first flat allocation: re-run
        # this script with them set, rather than trust that os.environ reaches the C runtime
        env = engine_env()
        if opt["trace"]:
            env["FJPROFX_TRACE_LO"], env["FJPROFX_TRACE_N"] = str(opt["trace"][0]), str(opt["trace"][1])
        return subprocess.run([sys.executable, "-u", str(Path(__file__).resolve())] + argv, env=env).returncode
    with BinaryLock(opt["lock"], opt["lock_name"]):
        return run(pos, opt)


def run(pos, opt):
    if not opt["stock"]:
        pyd = engine_pyd()
        spec = importlib.util.spec_from_file_location("flipjump.interpreter._fjcore", str(pyd))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        sys.modules["flipjump.interpreter._fjcore"] = mod
    for q in (ROOT / "tests", ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", ROOT):
        sys.path.insert(0, str(q))
    import gamespeed as GS                                                    # noqa: E402
    import m2_std_gate as gate                                                # noqa: E402
    from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
    from flipjump.interpreter.io_devices.KeyboardIO import ScriptedKeyEventSource  # noqa: E402
    from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
    from flipjump.interpreter.io_devices.pygame_window import PcIO           # noqa: E402
    from flipjump.utils.exceptions import IOReadOnEOF                         # noqa: E402

    if not opt["stock"]:
        assert Path(_fjcore.__file__).resolve() == engine_pyd().resolve(), _fjcore.__file__
        assert hasattr(_fjcore, "prof_mark"), "not the FJPROFX engine"
    print("engine: %s" % _fjcore.__file__, flush=True)
    fjm = Path(opt["fjm"]) if opt["fjm"] else default_fjm()
    thss = None
    if opt["poke"]:
        thss = label_dict()["thss_rt"] // 32

    class MarkRec(gate.Recording):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.marks = []

        def _present(self):
            super()._present()
            if not opt["stock"]:
                self.marks.append(_fjcore.prof_mark())

    class PokeStopper(gate.Stopper):
        def __init__(self, src, screen, limit, core):
            super().__init__(src, screen, limit)
            self.core, self.last, self.poked = core, -1, []

        def read_bit(self):
            nf = len(self._screen.frames)
            if nf != self.last:
                self.last = nf
                if opt["poke"] and nf >= gate.MENU_FRAMES:
                    t = (nf - gate.MENU_FRAMES) % 75
                    for k in range(4):              # thss_rt[t] = 0xFFFF: "the host moved this one"
                        self.core.set_word(thss + (t * 16 + k) * 2 + 1, 0xF * DW)
                    self.poked.append(t)
            return super().read_bit()

    def run_once(per_frame, name):
        events = GS.events_for(per_frame)
        n = len(per_frame)
        runner = FjmRunner(fjm)
        assert runner.native
        core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
        for seg, k in runner._segments:
            core.add_segment(seg, k)
        for st, vals in runner._runs:
            core.set_words(st, vals)
        screen = MarkRec()
        kb = PokeStopper(ScriptedKeyEventSource(events), screen, n, core)
        io = PcIO(screen, kb)
        io.attach_memory(NativeDeviceMemory(core, runner.width))
        t0 = time.time()
        _c, ops, _e, _l, _p = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
        rec = {"name": name, "ops": ops, "frames": len(screen.frames), "want": n,
               "secs": round(time.time() - t0, 2), "marks": screen.marks,
               "sha": [hashlib.sha256(f).hexdigest()[:16] for f in screen.frames], "poked": kb.poked}
        print("%s: %s ops, %d/%d frames, %.1fs%s" % (name, format(ops, ","), rec["frames"], n, rec["secs"],
                                                     (", poked %d" % len(kb.poked)) if opt["poke"] else ""),
              flush=True)
        del core, screen, io, runner
        return rec

    mode = pos[0]
    runs = []
    t0 = time.time()
    if mode == "games":
        prefix = out_prefix(pos[1])
        runs.append(run_once([{} for _ in range(gate.MENU_FRAMES)], "calibration"))
        for seed in range(10):
            runs.append(run_once(GS.full_script(seed, 100), "game%d" % seed))
    elif mode in ("walk", "still"):
        nf, prefix = int(pos[1]), out_prefix(pos[2])
        key = {"forward": True} if mode == "walk" else {}
        runs.append(run_once([{} for _ in range(gate.MENU_FRAMES)] + [dict(key) for _ in range(nf)], mode))
    else:
        raise SystemExit("mode must be games | walk N | still N")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    Path(str(prefix) + ".runs.json").write_text(
        json.dumps({"mode": mode, "fjm": str(fjm), "stock": opt["stock"], "poke": opt["poke"],
                    "trace": opt["trace"], "runs": runs}), encoding="ascii")
    if not opt["stock"]:
        n = _fjcore.prof_dump(str(prefix))
        print("prof_dump: %d present records -> %s.*" % (n, prefix), flush=True)
    print("total %.1fs" % (time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
