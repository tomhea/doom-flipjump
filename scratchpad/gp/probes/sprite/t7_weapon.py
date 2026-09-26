"""Step 7: what a WEAPON OVERLAY costs when it is baked as code and emitted as separate column
records after the world (the device's proposed KEEP token, docs/gp-partial-ditto.md): per weapon
column [x][0xFC][wtop] then the weapon's pairs -- a constant y2 byte and the texel through cm.emit
with the frame's light row -- then [0xFF]. Emitted by a standalone fj program, decoded and checked
against the psprite geometry computed in Python (weapon_cols.py). ops per frame by the slope."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402
import weapon_cols as wc                                                     # noqa: E402

KEEP = 0xFC
fr = plib.Frame(plib.by_frame(plib.load_cases())[("heavy", "gate664")][:2])


def pairs_of(lump, view_rows):
    """the baked overlay: per column (x, wtop, [(y2, texel)...]) with interior gaps filled from
    the texel above (the sprite rule), rows clipped to the view."""
    from doomfj.wad import decode_picture
    pic = decode_picture(wc.FW.get_data(lump))
    dense = []
    for x in range(pic.width):
        d = [-1] * pic.height
        for (v, t) in pic.columns[x]:
            d[v] = t
        dense.append(d)
    x1 = 160 + (1 - 160) - pic.leftoffset
    top = view_rows - (100.5 - (32 - pic.topoffset))
    out = []
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
        runs, prev = [], None
        for i in range(first, last + 1):
            t = rows[i] if rows[i] >= 0 else prev
            if runs and runs[-1][1] == t:
                runs[-1][0] = i + 1
            else:
                runs.append([i + 1, t])
            prev = t
        out.append((X, first, runs))
    return out


def code(cols, bright=False):
    lines = []
    for (x, wtop, runs) in cols:
        lines += ["stl.output_char %d" % x, "stl.output_char %d" % KEEP, "stl.output_char %d" % wtop]
        for (y2, tex) in runs:
            lines.append("stl.output_char %d" % y2)
            if bright:
                lines.append("stl.output_char %d" % plib.COLORMAP[0][tex])
            else:
                lines += ["hex.set 2, wpn_cm, %d" % tex, "cm.emit wpn_cm"]
        lines.append("stl.output_char 0xFF")
    return lines


def decode_keep(stream):
    cols, i = {}, 0
    while i < len(stream):
        x = stream[i]
        i += 1
        assert stream[i] == KEEP
        cur = stream[i + 1]
        i += 2
        px = {}
        while stream[i] != 0xFF:
            y2, c = stream[i], stream[i + 1]
            i += 2
            for y in range(cur, y2):
                px[y] = c
            cur = y2
        i += 1
        cols[x] = px
    return cols


if __name__ == "__main__":
    LR = 3
    for view in (100, 84):
        for lump, bright in (("PISGA0", False), ("PISGB0", False), ("PISFA0", True), ("SHTGA0", False),
                             ("SHTGC0", False), ("PUNGA0", False), ("SAWGA0", False)):
            cols = pairs_of(lump, view)
            npairs = sum(len(r) for _, _, r in cols)
            ops = []
            for reps in (1, 3):
                body = ["hex.set 4, wpn_cm, %d" % (LR << 8)] + code(cols, bright) * reps
                text = plib.program(fr, [], 1, pre_loop=body, lite="emit", extra_text="wpn_cm: hex.vec 4")
                o, out = plib.assemble_run(text, "wpn", want_output=True)
                ops.append(o)
                if reps == 1:
                    got = decode_keep(out)
            per = (ops[1] - ops[0]) / 2.0
            # check: the decoded overlay equals the Python columns, coloured through the colormap
            bad = 0
            for (x, wtop, runs) in cols:
                prev = wtop
                for (y2, tex) in runs:
                    want = plib.COLORMAP[0 if bright else LR][tex]
                    bad += sum(1 for y in range(prev, y2) if got[x].get(y) != want)
                    prev = y2
            print("  view %3d  %-7s cols %3d  pairs %4d  overlay %7.0f ops/frame  (%.0f per pair incl. framing)"
                  "  pixel mismatches %d" % (view, lump, len(cols), npairs, per, per / max(1, npairs), bad),
                  flush=True)
