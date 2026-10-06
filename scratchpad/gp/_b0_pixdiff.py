"""_b0_pixdiff.py -- where a b0_scenarios run's picture parts from the oracle, and whose pixels they are.

    python scratchpad/gp/_b0_pixdiff.py --run R0-northwest [--run ...] [--frames N] [--first K] [--probe]

Drives the run through b0_scenarios.drive EXACTLY (the gate's own oracle call, GameOracle = GAME_RENDER_KW), with
orc.render and gb.run wrapped: every render is compared with the binary's frame of the same index as drive makes it.
For the first K mismatching frames: the differing pixels (count, view rows 0..83 vs bar 84..99, bounding box,
(binary, oracle) palette pairs). `--probe`: on the first mismatching frame, re-render the oracle with one drawable /
mobile / keyword removed at a time and report which variant changes the oracle's pixels in the differing set, and
which variant MATCHES the binary there (the thing the binary drew differently).
"""
from __future__ import annotations

import argparse
import collections
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import b0_scenarios as B                                                     # noqa: E402
import probe as P                                                            # noqa: E402
import scenarios_v2 as S                                                     # noqa: E402

W = 160
REAL = P.Oracle.render
READ, PH, TRUNC = {}, {}, {}


def diffinfo(a: bytes, b: bytes):
    idx = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    if not idx:
        return None
    rows = [i // W for i in idx]
    cols = [i % W for i in idx]
    pairs = collections.Counter((a[i], b[i]) for i in idx)
    return {"n": len(idx), "view": sum(r < 84 for r in rows), "bar": sum(r >= 84 for r in rows),
            "bbox": (min(cols), min(rows), max(cols), max(rows)), "pairs": pairs.most_common(8), "idx": idx}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="scratchpad/gp/scenarios/combat_scenarios_v6.json")
    ap.add_argument("--fjm", default="build/doom_e1m1_blocked50.fjm")
    ap.add_argument("--labels", default="scratchpad/12m/atlas/blocked50.labels.tsv.gz")
    ap.add_argument("--run", action="append", required=True)
    ap.add_argument("--frames", type=int, default=100)
    ap.add_argument("--first", type=int, default=3)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--mobfix", action="store_true")
    ap.add_argument("--barfix", action="store_true")
    ap.add_argument("--trunc", action="store_true")
    ap.add_argument("--probe-at", type=int, nargs="*", default=[])
    ap.add_argument("--showbv", type=int, nargs="*", default=None)
    ap.add_argument("--proxydiff", action="store_true", help="diff the binary's pictures, normal vs --proxy run")
    ap.add_argument("--cells", type=int, nargs="*", default=[])
    ap.add_argument("--save", default=None, help="dump the first mismatching frame pair + diff as json")
    a = ap.parse_args()
    doc = json.loads(Path(a.file).read_text(encoding="ascii"))
    S.use_sight_rule(doc)
    runs = {r["name"]: r for r in doc["runs"]}
    orc = B.GameOracle()
    full = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis)
    table = P.LabelTable.load(Path(a.labels), {c.label for c in full.values()})
    if a.cells:
        real_gc = P.game_cells
        P.game_cells = lambda *x, **k: real_gc(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis)
        real_probe_init = P.Probe.__init__

        def pinit(self, *x, **k):
            real_probe_init(self, *x, **k)
            self.on_present(lambda pr, f: READ.__setitem__(f - 2, pr.read_cells()) if f - 2 in a.cells else None)
        P.Probe.__init__ = pinit
        real_mr = P.Oracle.monster_removed

        def mr(self, phase):
            PH["ph"] = phase
            return real_mr(self, phase)
        P.Oracle.monster_removed = mr
    gb = P.GameBinary(Path(a.fjm))
    import m2_std_gate as gate
    mf = gate.MENU_FRAMES
    if a.proxydiff:
        for name in a.run:
            fr = B.model_frames(runs[name])[:a.frames]
            pf = B.model_frames(runs[name], proxy=True)[:a.frames]
            r0 = B.drive(gb, table, orc, fr, pixel_every=1)
            r1 = B.drive(gb, table, orc, pf, pixel_every=1)
            print("%s: normal state %d/%d pixels %d/%d cam %d dr %d | proxy state %d/%d pixels %d/%d cam %d dr %d"
                  % (name, sum(r0["state_ok"]), len(r0["state_ok"]), sum(r0["pix_ok"]), len(r0["pix_ok"]),
                     r0["cam_parts"], r0["door_parts"],
                     sum(r1["state_ok"]), len(r1["state_ok"]), sum(r1["pix_ok"]), len(r1["pix_ok"]),
                     r1["cam_parts"], r1["door_parts"]))
            for f in range(min(3, len(fr))):
                print("   f%d normal inj %s exp %s | proxy inj %s exp %s | model post %s keys %s / %s"
                      % (f, fr[f]["inj"], fr[f]["exp"][0], pf[f]["inj"], pf[f]["exp"][0], fr[f]["post"],
                         sorted(k for k, v in fr[f]["keys"].items() if v), sorted(k for k, v in pf[f]["keys"].items() if v)))
            dif = [f for f in range(len(fr)) if r0["frames"][f] != r1["frames"][f]]
            so = [f for f in range(len(fr)) if fr[f]["strafe_only"]]
            print("  binary pictures differ normal vs proxy on %d frames: %s" % (len(dif), dif[:30]))
            print("  strafe-only frames: %s" % so[:60])
            for f in dif[:a.first]:
                d = diffinfo(r0["frames"][f], r1["frames"][f])
                print("   f%d strafe_only %s: %d px (view %d bar %d) bbox %s pairs %s; post_loot normal==proxy model: %s"
                      % (f, fr[f]["strafe_only"], d["n"], d["view"], d["bar"], d["bbox"], d["pairs"][:4],
                         fr[f]["post_loot"] == pf[f]["post_loot"]))
        return
    if a.trunc:
        # EXPERIMENT: the oracle with the pre-fix emitter's truncation -- a baked barrel's explosion lump's (light,
        # height) class past 255 drawn with class & 0xFF's shade rows (sprlight row[h] = wall_light_row(ln, h, units))
        sys.path.insert(0, str(HERE.parents[1] / "tests" / "fj"))
        import test_baked_barrel_light_fj as TB
        spr_cls, cls_list = TB.barrel_light_setup()
        from doomfj.reference_model import ReferenceModel as RMC
        inv = {c: k for k, c in spr_cls.items()}
        real_wlr = RMC.wall_light_row
        big = {k: inv[c & 0xFF] for k, c in spr_cls.items() if c > 0xFF and k[1] in (31, 40, 50, 53)}
        print("  trunc: pairs remapped %s" % sorted(big.items()), flush=True)

        def wlr(self, ln, h, units):
            k = big.get((ln, units))
            if k:                                    # only a BAKED barrel's sprite (the caller's thing, its view)
                fl = sys._getframe(1).f_locals
                t, tv, di = fl.get("t"), fl.get("tview"), fl.get("t_di")
                bk = fl.get("_baked")
                if not (t is not None and getattr(t, "type", None) == 2035 and tv and str(tv[0]).startswith("BEXP")
                        and bk is not None and di < len(bk) and bk[di]):
                    k = None
            return real_wlr(self, k[0], h, k[1]) if k else real_wlr(self, ln, h, units)
        TRUNC.update(big=big, real=real_wlr)
        RMC.wall_light_row = wlr
    for name in a.run:
        frames = B.model_frames(runs[name])[:a.frames]
        box = {}
        real_run = gb.run

        def run_wrap(*args, **kw):
            r = real_run(*args, **kw)
            box["r"] = r
            return r
        gb.run = run_wrap
        calls = []
        real_render = P.Oracle.render

        def render_wrap(self, *args, **kw):
            out = real_render(self, *args, **kw)
            f = len(calls)
            calls.append(out)
            binf = box["r"].frames[mf + f] if mf + f < len(box["r"].frames) else b""
            if a.showbv is not None:
                print("  f%d barrels %s views %s ok %s" % (f, a.showbv, [(kw.get("barrel_views") or {}).get(q) for q in a.showbv],
                                                       binf == out), flush=True)
            if a.cells and f in a.cells:
                ex = self.monster_rt(PH["ph"])
                got = READ.get(f, {})
                print("  CELLS f%d binary mdrop %s dr_live %s" % (f, got.get("mdrop"), got.get("dr_live")))
                for key in ("thpos_rt", "thss_rt", "thvis"):
                    e, g = ex.get(key), got.get(key)
                    if e is None or g is None:
                        print("    %s: model %s binary %s" % (key, e is not None, g is not None))
                        continue
                    dif = [(i, hex(e[i]) if key == 'thpos_rt' else e[i], hex(g[i]) if key == 'thpos_rt' else g[i])
                           for i in range(min(len(e), len(g))) if e[i] != g[i]]
                    print("    %s: %d rows (model %d, binary %d) differ: %s" % (key, len(dif), len(e), len(g), dif[:12]))
                st = PH["ph"].state()
                for key in sorted(st):
                    if key not in got:
                        continue
                    e, g = st[key], got[key]
                    if isinstance(e, (list, tuple)):
                        dif = [(i, e[i], g[i]) for i in range(min(len(e), len(g))) if e[i] != g[i]]
                        if dif or len(e) != len(g):
                            print("    STATE %s differs (model, binary): %s" % (key, dif[:10]))
                    elif e != g:
                        print("    STATE %s differs: model %s binary %s" % (key, e, g))
                print("    (compared %d state keys)" % sum(1 for k in st if k in got))
            if binf != out:
                bad.append(f)
                d = diffinfo(binf, out)
                if len(bad) <= a.first or f in a.probe_at:
                    print("  %s frame %d: %d px differ (view %d, bar %d) bbox(x0,y0,x1,y1)=%s (bin,orc) pairs %s"
                          % (name, f, d["n"], d["view"], d["bar"], d["bbox"], d["pairs"]), flush=True)
                    mph_info(kw)
                if a.save and len(bad) == 1:
                    Path(a.save).write_text(json.dumps({"run": name, "frame": f, "bin": list(binf),
                                                        "orc": list(out), "args": [repr(x) for x in args],
                                                        "kw": {k: repr(v) for k, v in kw.items()}}))
                if (a.probe and len(bad) == 1) or f in a.probe_at:
                    probe_variants(self, args, kw, binf, out, d)
                if a.barfix and len(bad) <= a.first:
                    bv = dict(kw.get("barrel_views") or {})
                    res_ = []
                    for di in sorted(bv):
                        k2 = dict(kw, seen_out=set(), aim_out=[0] * 17,
                                  removed=sorted(set(kw.get("removed") or []) | {di}),
                                  barrel_views={k: v for k, v in bv.items() if k != di})
                        o = REAL(self, *args, **k2)
                        nd = sum(1 for i in range(len(o)) if o[i] != binf[i])
                        ch = sum(1 for i in range(len(o)) if o[i] != out[i])
                        if ch:
                            res_.append((di, bv[di], "left", nd, "changed", ch))
                        for alt in ("BAR1A0", "BAR1B0", "BEXPA0", "BEXPB0", "BEXPC0", "BEXPD0", "BEXPE0"):
                            if alt == bv[di] or not ch:
                                continue
                            k3 = dict(kw, seen_out=set(), aim_out=[0] * 17, barrel_views={**bv, di: alt})
                            o = REAL(self, *args, **k3)
                            nd3 = sum(1 for i in range(len(o)) if o[i] != binf[i])
                            res_.append((di, "as", alt, nd3))
                    print("     f%d barrels: %s" % (f, res_), flush=True)
                if a.mobfix:
                    mob = kw.get("mobiles") or []
                    fixes = []
                    for j in range(len(mob)):
                        k2 = dict(kw, seen_out=set(), aim_out=[0] * 17,
                                  mobiles=[m for i, m in enumerate(mob) if i != j])
                        o = REAL(self, *args, **k2)
                        nd = sum(1 for i in range(len(o)) if o[i] != binf[i])
                        if nd < d["n"]:
                            fixes.append((mob[j], nd))
                    print("     f%d: %d px (view %d bar %d) bbox %s; removing mobile -> px left: %s; mobiles %s"
                          % (f, d["n"], d["view"], d["bar"], d["bbox"], fixes, mob), flush=True)
            return out

        def mph_info(kw):
            mob = kw.get("mobiles")
            print("     mobiles: %s" % (mob,))
            print("     barrel_views: %s" % (kw.get("barrel_views"),))
            print("     removed: %s" % (sorted(kw.get("removed") or []),))
        bad = []
        P.Oracle.render = render_wrap
        try:
            res = B.drive(gb, table, orc, frames, pixel_every=1)
        finally:
            P.Oracle.render = real_render
            gb.run = real_run
        print("%s: %d frames, state %d/%d, pixels %d/%d, mismatching frames %s"
              % (name, len(frames), sum(res["state_ok"]), len(res["state_ok"]), sum(res["pix_ok"]),
                 len(res["pix_ok"]), bad[:40]), flush=True)


def probe_variants(orc, args, kw, binf, out, d):
    idx = d["idx"]

    def rr(**over):
        k = dict(kw)
        k["seen_out"] = set()
        k["aim_out"] = [0] * 17
        k.update(over)
        return REAL(orc, *args, **k)

    def score(o):
        changed = sum(o[i] != out[i] for i in idx)
        match = sum(o[i] == binf[i] for i in idx)
        elsewhere = sum(1 for i in range(len(o)) if o[i] != binf[i])
        return changed, match, elsewhere
    print("     PROBE (variant: oracle px changed in the diff set / matching the binary there / total px != binary)")
    variants = [("mobiles=None", dict(mobiles=None)), ("barrel_views=None", dict(barrel_views=None)),
                ("removed=None", dict(removed=None)), ("views=None", dict(views=None))]
    for nm, ov in variants:
        print("       %-28s %s" % (nm, score(rr(**ov))), flush=True)
    mob = kw.get("mobiles") or []
    for j in range(len(mob)):
        print("       %-28s %s" % ("drop mobile %d %s" % (j, str(mob[j])[:60]),
                                   score(rr(mobiles=[m for i, m in enumerate(mob) if i != j]))), flush=True)
    # each drawable hidden in turn
    n = 200
    hits = []
    for t in range(n):
        try:
            o = rr(hidden_extra=tuple(set(kw.get("hidden_extra", ())) | {t}))
        except Exception as e:                       # noqa: BLE001
            continue
        s = score(o)
        if s[0]:
            hits.append((t, s))
    for t, s in hits:
        print("       hide drawable %-3d -> %s" % (t, s), flush=True)


if __name__ == "__main__":
    main()
