"""Run B0 of a combat scenario set on the FJPROFX engine -- the runs b0_scenarios.py runs, profiled.

    python drive_b0.py run <prefix> [--file SET] [--fjm PATH] [--labels TSV] [--pixel-every N] [--lock PATH]
    python drive_b0.py check <prefix> --b0-json RECORD

`run` IS b0_scenarios.b0(): the set's runs replayed on the model (`model_frames`), their setups and pokes
(`drive`, `setup_poke`), the oracle and every frame's state / pixel check, the startup + menu calibration -- all of it
b0_scenarios' own code, called unchanged. The only substitution is probe.GameBinary -> `ProfBinary`, which loads the
FJPROFX engine (the instrumented _fjcore, by path, before any doomfj import) and, around every binary run:
  prof_reset() -> the run -> prof_dump(<prefix>.<tag>)          (tag: "calibration", then the set's run names)
and calls prof_mark() at every present (drive.py's MarkRec). So each run has its own dumps -- .log.bin (per present:
ops at the last IO + the object counters), .marks.bin, .self.bin, .incl.bin -- and <prefix>.runs.json lists them in
drive.py's shape (name, ops, frames, marks, sha). <prefix> is also written COMBINED (logs and marks concatenated,
histograms summed, calibration first) so analyze.py / phases.py read it as one run set. --proxy is not run: B0's
binding statistic is the normal runs' (`b0()` prints it); the proxy pass only prices the strafe undercount.
b0()'s own record goes to <prefix>.b0.json (NOT docs/ship-evidence).

`check` is the R9-style control that the profiled workload IS B0's: every run's (ops - startup+menu) must equal
the record's avg_exact x frames TO THE OP, and the startup + menu ops its base_ops. Exit 1 on any difference.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import (ROOT, BinaryLock, engine_env, engine_pyd, load_sparse,  # noqa: E402
                    work_dir)

FRAMES = 100


def out_prefix(p):
    p = Path(p)
    return p if p.is_absolute() else work_dir() / p


def opts(argv):
    pos, o = [], {"file": "scratchpad/gp/scenarios/combat_scenarios_v7.json", "fjm": None, "labels": None,
                  "pixel_every": "1", "lock": None, "b0_json": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and a[2:].replace("-", "_") in o:
            o[a[2:].replace("-", "_")] = argv[i + 1]
            i += 2
            continue
        pos.append(a)
        i += 1
    return pos, o


def load_engine():
    pyd = engine_pyd()
    spec = importlib.util.spec_from_file_location("flipjump.interpreter._fjcore", str(pyd))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["flipjump.interpreter._fjcore"] = mod
    assert hasattr(mod, "prof_mark") and hasattr(mod, "prof_reset"), "not the FJPROFX engine"
    return mod


def run(prefix, o):
    fj = load_engine()
    for q in (ROOT / "scratchpad" / "gp", ROOT / "tests", ROOT / "src", ROOT / "scratchpad",
              ROOT / "scratchpad" / "12m", ROOT):
        sys.path.insert(0, str(q))
    import probe as P                                                         # noqa: E402
    import b0_scenarios as B                                                  # noqa: E402
    from doomfj.fastrun import _fjcore                                       # noqa: E402
    assert _fjcore is fj and Path(_fjcore.__file__).resolve() == engine_pyd().resolve(), _fjcore.__file__
    print("engine: %s" % _fjcore.__file__, flush=True)

    doc = json.loads((ROOT / o["file"]).read_text(encoding="ascii"))
    tags = ["calibration"] + [r["name"] for r in doc["runs"]]
    records = []

    real_devices = P._devices
    current = {"marks": None}

    def devices():                                  # the stock ProbeScreen + prof_mark at every present
        Screen, Kb, Eof = real_devices()

        class MarkScreen(Screen):
            def _present(self):
                super()._present()
                current["marks"].append(_fjcore.prof_mark())
        return MarkScreen, Kb, Eof
    P._devices = devices

    class ProfBinary(P.GameBinary):
        def run(self, frames, events=(), probe=None, pre_run=None):
            k = len(records)
            assert k < len(tags), "b0 ran more binary runs than calibration + the set's runs"
            marks = current["marks"] = []
            _fjcore.prof_reset()
            r = super().run(frames, events, probe, pre_run)
            current["marks"] = None
            pre = "%s.%s" % (prefix, tags[k])
            n = _fjcore.prof_dump(pre)
            assert n == len(r.frames) == len(marks), (n, len(r.frames), len(marks))
            records.append({"name": tags[k], "ops": r.ops, "frames": len(r.frames), "want": frames,
                            "secs": round(r.seconds, 2), "marks": marks, "dump": Path(pre).name,
                            "sha": [hashlib.sha256(f).hexdigest()[:16] for f in r.frames]})
            print("  [profx] %-20s %s ops, %d frames, %.1fs -> %s.*" % (tags[k], format(r.ops, ","), len(r.frames),
                                                                       r.seconds, Path(pre).name), flush=True)
            return r
    P.GameBinary = ProfBinary

    fjm = Path(o["fjm"]) if o["fjm"] else ROOT / "build" / "doom_e1m1_blocked53.fjm"
    labels = Path(o["labels"]) if o["labels"] else ROOT / "scratchpad" / "12m" / "atlas" / "blocked53.labels.tsv.gz"
    t0 = time.time()
    rc = B.b0(ROOT / o["file"], fjm, labels, int(o["pixel_every"]), Path(str(prefix) + ".b0.json"), False)
    assert [r["name"] for r in records] == tags, [r["name"] for r in records]
    Path(str(prefix) + ".runs.json").write_text(json.dumps({
        "mode": "b0", "set": o["file"], "fjm": str(fjm), "labels": str(labels), "stock": False, "poke": False,
        "trace": None, "b0_rc": rc, "runs": records}), encoding="ascii")
    combine(prefix, records)
    print("drive_b0: b0 rc %d, %d binary runs profiled, total %.1fs" % (rc, len(records), time.time() - t0),
          flush=True)
    return rc


def combine(prefix, records):
    """<prefix>.{log,marks,self,incl}.bin = the per-run dumps, calibration first, as one run set"""
    logs, marks, hs = [], [], {}
    hdr_out = hdr_outside = hdr_rej = 0
    for r in records:
        pre = str(prefix.parent / r["dump"])
        raw = Path(pre + ".log.bin").read_bytes()
        n, rec, outside, out, rej = np.frombuffer(raw[:40], dtype="<u8").tolist()
        logs.append(np.frombuffer(raw, dtype="<u8", offset=40, count=n * rec).reshape(n, rec))
        hdr_outside += outside
        hdr_out += out
        hdr_rej += rej
        mraw = Path(pre + ".marks.bin").read_bytes()
        mn, mrec = np.frombuffer(mraw[:16], dtype="<u8").tolist()
        marks.append(np.frombuffer(mraw, dtype="<u8", offset=16, count=mn * mrec).reshape(mn, mrec))
        for kind in ("self", "incl"):
            w, c = load_sparse(pre + ".%s.bin" % kind)
            hs.setdefault(kind, []).append((w, c))
    L = np.concatenate(logs)
    with open(str(prefix) + ".log.bin", "wb") as f:
        np.array([L.shape[0], L.shape[1], hdr_outside, hdr_out, hdr_rej], dtype="<u8").tofile(f)
        L.astype("<u8").tofile(f)
    M = np.concatenate(marks)
    with open(str(prefix) + ".marks.bin", "wb") as f:
        np.array([M.shape[0], M.shape[1]], dtype="<u8").tofile(f)
        M.astype("<u8").tofile(f)
    dt = np.dtype([("w", "<u4"), ("c", "<u8")])
    for kind, parts in hs.items():
        w = np.concatenate([p[0] for p in parts])
        c = np.concatenate([p[1] for p in parts])
        uw, inv = np.unique(w, return_inverse=True)
        uc = np.zeros(len(uw), dtype=np.int64)
        np.add.at(uc, inv, c)
        arr = np.zeros(len(uw), dtype=dt)
        arr["w"], arr["c"] = uw.astype("<u4"), uc.astype("<u8")
        with open(str(prefix) + ".%s.bin" % kind, "wb") as f:
            np.array([len(uw)], dtype="<u8").tofile(f)
            arr.tofile(f)


def check(prefix, o):
    """the profiled workload is B0's: per run, (ops - startup+menu) == the record's avg_exact x 100, to the op"""
    runs = json.loads(Path(str(prefix) + ".runs.json").read_text())["runs"]
    rec = json.loads((ROOT / o["b0_json"]).read_text())
    cal = runs[0]
    assert cal["name"] == "calibration"
    bad = []
    print("startup + menu: profiled %s, record base_ops %s  %s" % (
        format(cal["ops"], ","), format(rec["base_ops"], ","), "EQUAL" if cal["ops"] == rec["base_ops"] else "DIFFER"))
    if cal["ops"] != rec["base_ops"]:
        bad.append("calibration")
    byname = {r["name"]: r for r in rec["runs"]}
    print("%-20s %16s %16s %16s  %s" % ("run", "profiled ops", "-base", "record avg x100", "verdict"))
    for r in runs[1:]:
        want = int(round(byname[r["name"]]["avg_exact"] * FRAMES))
        got = r["ops"] - rec["base_ops"]
        ok = got == want and r["frames"] == FRAMES + 2
        print("%-20s %16s %16s %16s  %s" % (r["name"], format(r["ops"], ","), format(got, ","), format(want, ","),
                                            "EQUAL" if ok else "DIFFER"))
        if not ok:
            bad.append(r["name"])
        # the per-run dump must conserve ops (the histograms sum to the run's op total)
        w, c = load_sparse(str(prefix.parent / r["dump"]) + ".incl.bin")
        if int(c.sum()) != r["ops"]:
            bad.append(r["name"] + "(incl sum %d)" % int(c.sum()))
    missing = sorted(set(byname) - {r["name"] for r in runs[1:]})
    if missing:
        bad.append("missing runs %s" % missing)
    print("EXACT-TOTAL CHECK: %d/%d runs equal%s" % (len(runs) - 1 - len([b for b in bad if b != "calibration"]),
                                                     len(byname), "" if not bad else "; DIFFER: %s" % bad))
    return 1 if bad else 0


def main(argv):
    pos, o = opts(argv)
    if not pos or pos[0] not in ("run", "check"):
        raise SystemExit(__doc__)
    prefix = out_prefix(pos[1])
    if pos[0] == "check":
        return check(prefix, o)
    if os.environ.get("FJPROFX_MAP") is None:
        # the engine reads its inputs from the environment at the first flat allocation (drive.py's rule)
        return subprocess.run([sys.executable, "-u", str(Path(__file__).resolve())] + argv,
                              env=engine_env()).returncode
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with BinaryLock(o["lock"], "profx v7 attribution"):
        return run(prefix, o)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
