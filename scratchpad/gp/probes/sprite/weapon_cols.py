"""The weapon sprite's screen columns at 160 wide, from freedoom1.wad (cheap Python, no fj).

For every weapon frame: which columns it covers, its top row per column (wtop), how many colour
runs (pairs) the baked overlay would emit, how many columns have a transparent gap below their
first opaque row, and how many columns could use a PARTIAL DITTO for their world part (the column
to the left is no weapon column, or its weapon starts at or below this column's wtop, so its rows
[0, wtop) are world rows). DOOM's R_DrawPSprite at 320x(view), then 2x nearest sampling.
    python weapon_cols.py            # view 100 rows (no status bar) and 84 rows (bar)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.wad import WadFile, decode_picture                              # noqa: E402

FW = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
FRAMES = {"fist": ["PUNGA0", "PUNGB0", "PUNGC0", "PUNGD0"],
          "pistol": ["PISGA0", "PISGB0", "PISGC0", "PISGD0", "PISGE0"],
          "pistol flash": ["PISFA0"],
          "shotgun": ["SHTGA0", "SHTGB0", "SHTGC0", "SHTGD0"],
          "shotgun flash": ["SHTFA0", "SHTFB0"],
          "chainsaw": ["SAWGA0", "SAWGB0", "SAWGC0", "SAWGD0"]}


def columns(lump, view_rows, sy=32, sx=1):
    pic = decode_picture(FW.get_data(lump))
    dense = []
    for x in range(pic.width):
        d = [-1] * pic.height
        for (v, t) in pic.columns[x]:
            d[v] = t
        dense.append(d)
    x1 = 160 + (sx - 160) - pic.leftoffset                     # at 320 wide
    top = (view_rows * 2) // 2 - (100.5 - (sy - pic.topoffset))  # centery(320) - texturemid
    out = {}
    for X in range(160):
        u = 2 * X - x1
        if not 0 <= u < pic.width:
            continue
        rows = []
        for Y in range(view_rows):
            v = int(2 * Y + 0.5 - top)
            rows.append(dense[u][v] if 0 <= v < pic.height else -1)
        op = [i for i, t in enumerate(rows) if t >= 0]
        if not op:
            continue
        first, last = op[0], op[-1]
        runs, prev = 0, None
        for i in range(first, last + 1):
            t = rows[i]
            if t < 0:
                t = prev                                     # interior gap: nearest opaque above
            if t != prev:
                runs += 1
                prev = t
        out[X] = dict(wtop=first, bottom=last + 1, runs=runs,
                      gap=any(rows[i] < 0 for i in range(first, last + 1)))
    return out


def summary(view_rows):
    res = {}
    for weapon, lumps in FRAMES.items():
        for lump in lumps:
            cols = columns(lump, view_rows)
            xs = sorted(cols)
            pdit = sum(1 for x in xs if (x - 1) not in cols or cols[x - 1]["wtop"] >= cols[x]["wtop"])
            res[lump] = dict(weapon=weapon, ncols=len(xs), x=(xs[0], xs[-1]) if xs else None,
                             pairs=sum(c["runs"] for c in cols.values()),
                             reach_bottom=sum(1 for c in cols.values() if c["bottom"] == view_rows),
                             gap_cols=sum(1 for c in cols.values() if c["gap"]),
                             pdit_ok=pdit, min_top=min((c["wtop"] for c in cols.values()), default=None))
    return res


if __name__ == "__main__":
    allres = {}
    for vr in (100, 84):
        r = summary(vr)
        allres[vr] = r
        print("view %d rows:" % vr)
        for lump, d in r.items():
            print("  %-7s %-14s cols %3d  x %-10s pairs %4d  to-bottom %3d  gap-cols %2d  "
                  "partial-ditto-ok %3d  top row %s" % (lump, d["weapon"], d["ncols"], d["x"], d["pairs"],
                                                        d["reach_bottom"], d["gap_cols"], d["pdit_ok"],
                                                        d["min_top"]))
    (Path(__file__).resolve().parent / "weapon_cols.json").write_text(json.dumps(allres, indent=1),
                                                                      encoding="utf-8")
