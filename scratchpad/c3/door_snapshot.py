"""C3 (M8 episode): a snapshot of every door-related model table and emitted fj text for E1M1 and E1M2, so a door change
can be proved to leave both maps' doors IDENTICAL (light: no full emission). Run before and after; `--check FILE`
compares. R9: `--selftest` mutates a door constant and requires a difference."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import doors as D, doorcode as DC, switches as SW, switchcode as SC   # noqa: E402
from doomfj.mapcompiler import bake_bsp   # noqa: E402
from doomfj.wad import WadFile   # noqa: E402


def h(x):
    return hashlib.sha256(repr(x).encode()).hexdigest()[:16]


def snap(path, m):
    mw = WadFile.from_path(str(path))
    secs, lds, sds, verts = mw.sectors(m), mw.linedefs(m), mw.sidedefs(m), mw.vertexes(m)
    cv = bake_bsp(mw, m).vertexes
    out = {}
    tbl = D.door_states(secs, lds, sds)
    out["door_sectors"] = h(list(D.door_sectors(secs, lds, sds).items()))
    out["door_states"] = h(sorted(tbl.items()))
    out["kinds"] = h(sorted(D.door_kinds(secs, lds, sds).items()))
    boxes = D.use_boxes_xy(secs, lds, sds, cv)
    out["use_boxes"] = h(sorted(boxes.items()))
    out["switch_trig"] = h(D.switch_door_triggers(secs, lds, sds, cv))
    out["walk_trig"] = h(D.walkover_triggers(secs, lds, sds, verts))
    geo = D.door_contact_geo(secs, lds, sds, cv)
    out["contact"] = h(sorted(geo.items()))
    out["stamp"] = h(D.geometry_stamp(secs, lds, sds))
    passes = {si: D.pass_state(secs, lds, sds, si) for si in tbl}
    trig = D.walkover_triggers(secs, lds, sds, verts)
    for dead in (None, "p_dd0"):
        for con in (None, geo):
            t = DC.door_tic_lines(sorted(tbl), {si: len(v) for si, v in tbl.items()}, boxes,
                                  D.door_kinds(secs, lds, sds), contact=con, passes=passes, dead=dead,
                                  switches=D.switch_boxes(secs, lds, sds, cv), walked={x[0] for x in trig},
                                  mon_press=frozenset(sorted(tbl)[:2]), mon_contact=[("mx", "my", 20, "ma")])
            out["tic_%s_%s" % (dead, con is not None)] = h(t)
    out["walk_lines"] = h(DC.walkover_lines(trig, sorted(tbl), 16))
    out["decls"] = h(DC.door_decls(len(tbl), len(trig)))
    sw = SW.map_switches(secs, lds, sds, cv)
    out["switches"] = h(sw)
    slot = {si: d for d, si in enumerate(sorted(tbl))}
    out["switch_door_phase"] = h(SC.door_phase_lines(sw, slot, dead="p_dd0"))
    return out


def main():
    a = sys.argv[1:]
    fx = ROOT / "tests" / "fixtures"
    full = ROOT / "assets" / "freedoom1.wad"
    res = {"E1M1": snap(full, "E1M1"), "E1M2": snap(full, "E1M2"),
           "E1M1_fix": snap(fx / "freedoom_e1m1.wad", "E1M1"), "E1M2_fix": snap(fx / "freedoom_e1m2.wad", "E1M2")}
    if a and a[0] == "--selftest":
        old = D.WAIT
        D.WAIT = old + 1
        import doomfj.doorcode as dcm
        dcm.WAIT = old + 1
        try:
            mut = snap(full, "E1M1")
        finally:
            D.WAIT = dcm.WAIT = old
        diff = [k for k in mut if mut[k] != res["E1M1"][k]]
        assert diff, "selftest: a WAIT change moved nothing"
        print("selftest OK: the mutation moved", diff)
        return
    if a and a[0] == "--check":
        base = json.loads(Path(a[1]).read_text())
        n, bad = 0, []
        for m in base:
            for k in base[m]:
                n += 1
                if base[m][k] != res[m][k]:
                    bad.append((m, k))
        print("compared %d entries over %d maps: %s" % (n, len(base), "IDENTICAL" if not bad else "DIFFER %s" % bad))
        sys.exit(1 if bad else 0)
    Path(a[0]).write_text(json.dumps(res, indent=1))
    print("wrote", a[0], sum(len(v) for v in res.values()), "entries")


if __name__ == "__main__":
    main()
