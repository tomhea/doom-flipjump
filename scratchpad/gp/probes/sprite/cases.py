"""Synthetic sprite columns picked with the E1M1 ORACLE (no fj, no build).

For fight-like frames (runtime monsters moved in front of the camera through the oracle's own
`thing_positions` override) and for the sprite-heavy static viewpoints, every column that carries a
slot-A sprite fragment becomes a CASE: the column's clip rows (ctake/fstart), its ceiling and floor
plane keys (-> the real vpb band lists via the emitter's own `_band_pair_lists`), the fragment
(y_base, runs, light row) exactly as the oracle stores it, the W1R wall inputs, and the V5 piece
counts. `python cases.py` writes cases.json next to this file and prints the population summary.
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config                                            # noqa: E402
from doomfj.fixedpoint import _signed                                       # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState, build_scene, MONSTER_TYPES,  # noqa: E402
                                    GAME_RENDER_KW)
from doomfj.things import drawable_things, baked_thing_mask                 # noqa: E402
from doomfj.wad import WadFile                                              # noqa: E402

HERE = Path(__file__).resolve().parent
cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
drawable, _ = drawable_things(rm, mw.things("E1M1"), art, {})
baked = baked_thing_mask(rm, scene.cmap, drawable, MONSTER_TYPES)
SPAWN = [(t.x, t.y) for t in drawable]
MONS = {k: [i for i, t in enumerate(drawable) if not baked[i] and t.type == k]
        for k in (3001, 3004, 9, 3002)}

# viewpoints: the deg_gate sprite frames and the atlas profile points (docs: ATLAS.md)
VPS = [("gate664", 664, 291, 0x18000000), ("gate1869", 1869, 479, 0x80000000),
       ("h57", 2893, 2015, 0x80000000), ("h71", 2637, 991, 0x0), ("h100", 2637, 991, 0x40000000),
       ("h28", 2893, 1503, 0x0), ("h42", 2381, -289, 0xC0000000), ("h85", 333, -33, 0x40000000)]
FIGHTS = {
    "static": [],
    "heavy": [(3001, 200, -60), (3001, 230, 40), (3001, 260, 110), (3004, 320, -140),
              (3004, 300, 150), (9, 380, 0)],
    "melee": [(3002, 70, 0), (3001, 160, -80), (3001, 180, 70), (3004, 260, 0)],
}


def positions(vx, vy, va, placements):
    pos = list(SPAWN)
    used = {k: 0 for k in MONS}
    a = (va & 0xFFFFFFFF) / 2 ** 32 * 2 * math.pi
    for typ, d, lat in placements:
        i = MONS[typ][used[typ]]
        used[typ] += 1
        pos[i] = (int(round(vx + d * math.cos(a) - lat * math.sin(a))),
                  int(round(vy + d * math.sin(a) + lat * math.cos(a))))
    return pos


def viewz_of(vx, vy):
    lds, sds = mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    from doomfj.reference_model import scene_sectors
    secs = scene_sectors(scene)
    ss = scene.cmap.subsectors[rm.point_in_subsector(scene.cmap, vx, vy)]
    return rm.view_z(rm._seg_sector(lds, sds, secs, scene.cmap.segs[ss.firstseg]).floor_h)


def piece(pc):
    """one V5 stacked piece as the fj stores it: rows clamped to the screen (ts_piece_store),
    the face's (sector light, wall units) shading class, and the BACK sector's plane keys (the
    region behind the boundary walks the back pid's lists)."""
    y1, y2, fsc, units, bsec = pc
    return [max(y1, 0), min(y2, cfg.VIEW_H - 1), fsc.light, max(1, units),
            bsec.ceil_h, bsec.floor_h, bsec.light, bsec.ceil_tex, bsec.floor_tex]


def collect():
    cases = []
    for fname, pl in FIGHTS.items():
        for name, vx, vy, va in VPS:
            planes, things, steps = [], [], []
            rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene,
                                 sprite_wad=art, **GAME_RENDER_KW,
                                 planes_out=planes, things_out=things,
                                 steps_out=steps,
                                 thing_positions=positions(vx, vy, va, pl) if pl else None)
            ceil_hi, floor_lo, col_ch, col_fh, col_lt, col_cf, col_ff = planes[0]
            sfrag = things[0]
            ups, los = steps[0]
            vz = viewz_of(vx, vy)
            wnoff = ((va & 0xFFFFFFFF) * 5) >> 25
            for x in range(cfg.VIEW_W):
                f = sfrag[x]
                if f is None:
                    continue
                y_base, runs, lr = f
                cases.append(dict(
                    scen=fname, vp=name, x=x, cexcl=ceil_hi[x] + 1, fstart=floor_lo[x],
                    ch=col_ch[x], fh=col_fh[x], lt=col_lt[x], cf=col_cf[x], ff=col_ff[x], vz=vz,
                    y_base=y_base, runs=[list(r) for r in runs], lr=lr,
                    nup=len(ups[x]), nlo=len(los[x]),
                    ups=[piece(pc) for pc in ups[x]], los=[piece(pc) for pc in los[x]],
                    gnrow=rm.wall_noise(x + wnoff), gnrow2=rm.wall_noise2(x + wnoff),
                    gnrow3=rm.wall_noise3(x + wnoff)))
    return cases


def main():
    cases = collect()
    H = cfg.VIEW_H
    print("sprite columns (slot A) collected: %d" % len(cases))
    for scen in FIGHTS:
        cs = [c for c in cases if c["scen"] == scen]
        if not cs:
            continue
        nr = sum(len(c["runs"]) for c in cs) / len(cs)
        print("  %-6s %4d cols  mean runs %.1f  pieces-in-col %.0f%%" %
              (scen, len(cs), nr, 100.0 * sum(1 for c in cs if c["nup"] or c["nlo"]) / len(cs)))
    # geometry classes: where the fragment sits against the column's wall window [ctake, fstart)
    def cls(c):
        ctake = min(c["cexcl"], c["fstart"])
        sy1 = max(0, min(H, c["y_base"]))
        sy2 = max(0, min(H, c["y_base"] + c["runs"][-1][0]))
        if sy1 <= ctake and sy2 >= c["fstart"]:
            return "covers-wall"
        if sy1 > ctake and sy2 < c["fstart"]:
            return "inside-wall"
        if sy1 >= c["fstart"]:
            return "inside-floor"
        if sy2 <= ctake:
            return "inside-ceil"
        return "straddles"
    from collections import Counter
    print("  geometry classes:", dict(Counter(cls(c) for c in cases)))
    random.seed(1)
    # the measured MIX: every heavy/melee column plus a sample of the static ones (a fight frame is
    # what the plan prices)
    mix = [c for c in cases if c["scen"] != "static"]
    stat = [c for c in cases if c["scen"] == "static"]
    mix += random.sample(stat, min(len(stat), 60))
    for c in mix:
        c["cls"] = cls(c)
    (HERE / "cases.json").write_text(json.dumps(mix), encoding="utf-8")
    print("wrote %d cases -> cases.json; classes %s" % (len(mix), dict(Counter(c["cls"] for c in mix))))


if __name__ == "__main__":
    main()
