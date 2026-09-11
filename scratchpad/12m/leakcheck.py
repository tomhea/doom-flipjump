"""Does a SHUT door actually occlude? Measured objectively, not by eye.

A shut door was "glass": the room beyond painted straight through it. Judging that by eye, or by
counting shut-vs-open pixels, is what made an earlier fix look proven when it was not -- that fix
put a grey slab over the top of the doorway while the far room's floor still showed underneath and
every sprite behind the door still painted ON TOP of the slab.

THE METRIC HERE CANNOT BE FOOLED THAT WAY. Perturb ONLY the room on the FAR SIDE of the shut door
(move its floor and ceiling). If the door occludes, the frame is bit-identical: nothing beyond it
can reach the screen. Every pixel that changes is a pixel that leaked through a closed door.

    python scratchpad/12m/leakcheck.py --selftest
    python scratchpad/12m/leakcheck.py                 # full sweep, current oracle

⚠ THIS FILE'S FIRST VERSION MEASURED THE WRONG SECTOR AND ITS "0 px LEAK" WAS VACUOUS.
It perturbed `sds[lds[li].back].sector` on the belief that that is "the sector behind the door".
On E1M1 it is not: all 25 door linedefs have their BACK side on the DOOR SECTOR ITSELF (front =
the room, back = the moving sector). So the perturbation moved the shut door's own ceiling from
one shut position to another shut position, both frames drew an occluding door, and the tool
reported a confident zero for a door that could have been made of glass. The far room is reached
through the door sector's OTHER linedef -- see `doomfj.doorcode.door_rooms`.

CONTROLS (R9)
  C1 THE PROBE MUST BE VISIBLE AT ALL -- the same perturbation with the door OPEN must change many
     pixels. This is simultaneously the GLASS-DOOR control: it is the measurement this file would
     report if the door stopped occluding, so a large C1 beside a zero leak is the proof.
  C2 THE VIEWER MUST BE ON THE NEAR SIDE -- the linedef side test decides the side and BSP point
     location then REJECTS any viewpoint standing in the door sector or in a room being perturbed.
     (The first version computed a point location and then ignored the answer.) The drop count is
     reported: a filter that never fires is not a filter.
  C3 NON-VACUITY -- a viewpoint from which the door occupies no columns is dropped, not scored 0.
  C4 EVERY DOOR IS ACCOUNTED FOR -- a door with no far room to perturb (E1M1 sector 84 is a closet
     with a single two-sided line) is REPORTED as unmeasurable, never counted as clean.
"""
import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scratchpad"))

from doomfj.reference_model import ReferenceModel, SimState, Scene            # noqa: E402
from doomfj.config import Config                                              # noqa: E402
from doomfj.wad import WadFile                                                # noqa: E402
from doomfj.mapcompiler import bake_bsp, _point_side                          # noqa: E402
from doomfj import build as buildmod                                          # noqa: E402
from doomfj.doorcode import door_rooms                                        # noqa: E402
import m2_std_gate as G                                                       # noqa: E402

KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
          near_steps=True, stack_steps=True, things=True, degrade=True)
STANDOFFS = (64, 96, 128, 160, 192, 240)


def setup():
    mw = WadFile.from_path(str(buildmod.DEFAULT_WAD))
    spr = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    cmap = bake_bsp(mw, "E1M1")
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    tbl = G.door_states(secs, lds, sds)
    return (ReferenceModel(Config()), mw, spr, cmap, secs, lds, sds, tbl,
            G.door_line_ids(secs, lds, sds, tbl))


def _sector_of_point(rm, cmap, lds, sds, x, y):
    """Which SECTOR index does map point (x, y) stand in? BSP leaf -> its first seg -> that seg's
    front sector, which is mapcompiler.seg_sector's rule applied to an index instead of an object."""
    ssi = rm.point_in_subsector(cmap, x, y)
    ss = cmap.subsectors[ssi]
    if ss.numsegs <= 0:
        return None
    seg = cmap.segs[ss.firstseg]
    ld = lds[seg.linedef]
    side = ld.front if seg.side == 0 else ld.back
    return None if side == -1 else sds[side].sector


def _views(rm, cmap, lds, sds, li, door_sec, far):
    """Viewpoints on the door line's NEAR side -- the side its front sidedef faces (C2).

    Two independent conditions, because each catches what the other misses:
      * `mapcompiler._point_side` decides the SIDE. DOOM's rule is right = front, and this file
        borrows the shared primitive rather than re-deriving a winding rule it does not own.
      * BSP point location then REJECTS any point that lands in the door sector or in a far room.
        The side test alone would accept a point that is geometrically in front but has wandered
        through a corner into the very room being perturbed.

    ⚠ An earlier attempt required the located sector to EQUAL the linedef's front sector. That
    dropped all 24 of door 10's viewpoints: an E1M1 door's front sector is a one-subsector alcove
    in the door frame, so anyone standing back far enough to see the door is never in it.

    Returns (kept, dropped); `dropped` is reported so a filter that never fires is visible."""
    ld = lds[li]
    v1, v2 = cmap.vertexes[ld.v1], cmap.vertexes[ld.v2]
    dx, dy = v2[0] - v1[0], v2[1] - v1[1]
    mx, my = (v1[0] + v2[0]) / 2.0, (v1[1] + v2[1]) / 2.0
    nl = (dx * dx + dy * dy) ** 0.5 or 1.0
    nx, ny = -dy / nl, dx / nl
    banned = set(far) | {door_sec}
    kept, dropped = [], 0
    for sgn in (1.0, -1.0):
        for d in STANDOFFS:
            px, py = int(mx + sgn * nx * d), int(my + sgn * ny * d)
            if _point_side(v1[0], v1[1], dx, dy, px, py) >= 0:
                dropped += 1          # back side of the line -- the far side by definition
                continue
            if _sector_of_point(rm, cmap, lds, sds, px, py) in banned:
                dropped += 1          # in the door, or already in the room we perturb
                continue
            ang = int(math.atan2(my - py, mx - px) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
            kept.append((px, py, ang, d))
    return kept, dropped


def _perturb(secs, base, far):
    """Move the far rooms' floor and ceiling, keeping each room OPEN (a perturbation that shuts the
    far room would hide itself and read as 'no leak')."""
    out = dict(base)
    for fs in far:
        fh, ch = out.get(fs, (secs[fs].floor_h, secs[fs].ceil_h))
        room = ch - fh
        out[fs] = (fh + min(8, max(0, room // 4)), ch - min(40, max(0, room // 2)))
    return out


def sweep(limit_doors=None, verbose=True):
    rm, mw, spr, cmap, secs, lds, sds, tbl, lines_of = setup()
    kw = dict(KW, sprite_wad=spr)
    topo = door_rooms(lds, sds, tbl, lines_of)
    order = sorted(tbl)
    if limit_doors:
        order = [s for s in order if s in limit_doors]
    shut = {si: (secs[si].floor_h, tbl[si][0]) for si in sorted(tbl)}
    total_leak = total_probe = views = dropped = 0
    rows, unmeasurable = [], []
    for si in order:
        for li, near, far in topo[si]:
            if not far:
                unmeasurable.append((si, li))      # C4
                continue
            kept, drop = _views(rm, cmap, lds, sds, li, si, far)
            dropped += drop
            for (px, py, ang, d) in kept:
                st = SimState(x=px << 16, y=py << 16, angle=ang, level="E1M1")
                pert = _perturb(secs, shut, far)
                base = rm.render_wall_frame(
                    st, Scene(mw, mw, "E1M1", cmap, shut, frozenset()), **kw)
                pf = rm.render_wall_frame(
                    st, Scene(mw, mw, "E1M1", cmap, pert, frozenset()), **kw)
                leak = sum(1 for a, b in zip(base, pf) if a != b)
                # C1 / glass-door control: THIS door open, every other door left shut
                opn = dict(shut)
                opn[si] = (secs[si].floor_h, tbl[si][-1])
                ob = rm.render_wall_frame(
                    st, Scene(mw, mw, "E1M1", cmap, opn, frozenset()), **kw)
                op = rm.render_wall_frame(
                    st, Scene(mw, mw, "E1M1", cmap, _perturb(secs, opn, far), frozenset()), **kw)
                probe = sum(1 for a, b in zip(ob, op) if a != b)
                if probe == 0:
                    continue                       # C3: door invisible from here -- not scored
                views += 1
                total_leak += leak
                total_probe += probe
                rows.append((si, li, near, far, d, leak, probe))
    if verbose:
        print("%-6s %-6s %-6s %-8s %-6s %-10s %s"
              % ("door", "line", "near", "far", "dist", "LEAK", "probe(open)"))
        for si, li, near, far, d, leak, probe in sorted(rows, key=lambda r: -r[5])[:14]:
            print("%-6d %-6d %-6d %-8s %-6d %-10d %d"
                  % (si, li, near, ",".join(map(str, far)), d, leak, probe))
        print("")
        print("C2 viewpoints DROPPED (not in the near room) : %d" % dropped)
        print("C4 door lines with no far room to perturb    : %s"
              % (", ".join("sec %d line %d" % t for t in unmeasurable) or "none"))
    print("VIEWPOINTS SCORED : %d" % views)
    print("LEAK through shut doors : %s px   (0 = every shut door fully occludes)"
          % format(total_leak, ","))
    print("probe visibility (open) : %s px   (C1: must be large, or the probe proves nothing)"
          % format(total_probe, ","))
    return total_leak, total_probe, views, dropped, unmeasurable


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("leakcheck selftest -- a probe nothing can see reports 0 leak for a GLASS door too")
    rm, mw, spr, cmap, secs, lds, sds, tbl, lines_of = setup()
    topo = door_rooms(lds, sds, tbl, lines_of)
    # the defect this file shipped with: `back` is the DOOR, never the room beyond it
    backs = {sds[lds[li].back].sector for si in topo for li, _n, _f in topo[si]}
    check("C0 the old 'back sector' target was the DOOR itself", backs <= set(tbl),
          "%d sectors, all doors" % len(backs))
    check("C4 the far room is a DIFFERENT sector from the door",
          all(si not in f for si in topo for _l, _n, f in topo[si]))

    leak, probe, views, dropped, unmeas = sweep(limit_doors={10}, verbose=False)
    check("C3 at least one viewpoint was scored", views > 0, "%d views" % views)
    check("C2 the near-side filter actually fires", dropped > 0, "%d dropped" % dropped)
    check("C1 the probe IS visible with the door open", probe > 0, "%s px" % format(probe, ","))
    check("C1 ...and substantially so", probe > 200, "%s px" % format(probe, ","))
    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else (sweep() and 0))
