"""M7 P6+P7 item 12 (the owner, 2026-10-05: "It's kind of hard to kill from afar, maybe too hard. try to measure
it yourself as well") -- the player's odds of hitting ONE monster at range, the window vs DOOM.

    python scratchpad/gp/aim_range.py [--views 32] [--dstep 4] [--selftest]

THE QUESTION has two halves, and the table keeps them apart:
  (a) THE RULE. Our shot hits what the 17-column aim window names in the shot's COLUMN -- the nearest box
      +-r_eff (DOOM's diagonal half-width, `CombatMixin.aim_radius`) projected like a sprite. DOOM traces a RAY
      by angle and crosses the thing's corner-to-corner diagonal (PIT_AddThingIntercepts). At range a box is
      1-2 columns wide, so the question is whether the column test is harder than the ray.
  (b) THE TURN. The player cannot point anywhere: his view angle moves in steps of the turn per frame. After
      the best turn, the target's bearing is off the view by a residual delta, uniform over one step
      (the target's bearing is uniform against the angle lattice). DOOM's keyboard tap is the SLOW turn,
      angleturn[2] = 320 << 16 for the first SLOWTURNTICS = 6 tics a key is held (then 640, or 1280 running).

THE MEASURE. A target of radius r at distance D (integer map units, as monsters stand), seen from a player at
the origin; `--views` bearings around the circle (r_eff and the diagonal depend on the absolute angle); for
each, the view angle = the true bearing - delta, delta on a grid of `--dstep` x 2^16 BAM over the widest step.
For each step size S, the samples with |delta| <= S/2 are averaged. Per sample:
  ours   the MODEL'S OWN aim, `CombatMixin.aim_geometric` (the window's box formula; the window agrees with it
         on 99.94% of fight frames, docs/gp-aim-window.md), called on a one-target world, per column
         - pistol (accurate first shot): column `aim_centre` (80)
         - a refire bullet / one pellet: the column `Sites.gunshot` names, averaged over the 256 stream states
         - a shotgun blast: 7 pellets from stream state n (pellet k reads state n + 1 + 3k), averaged over n:
           P(>= 1 pellet hits) and the mean pellets that hit
  doom   DOOM's 2D trace at view + (P_SubRandom() << 18), the SAME (b - c) draws from the same table states,
         against the diagonal chosen by the sign of dx ^ dy; a hit needs the crossing within 2048 along the ray.
No walls (one target in the open), no heights (autoaim is vertical only, so it changes nothing here).

CENTRING. The player aims by the PICTURE: he turns until the target looks centred. The drawn sprite and the
window share DOOM's R_ProjectSprite column convention (column c is drawn/tested when the box covers screen
position c + 1), so a picture-centred target is centred on the window's own hit interval, which sits ~1 column
off the true bearing (section C prints it). So A and B centre the residual on each rule's own accurate-shot
interval; C also gives the bearing-centred number, for the record.

--selftest (R9): the measure must SEE a rule change -- with the window's radius halved, ours/doom of the
pistol (r 20 at 1024, r 30 at 1920) must fall below 0.75; with DOOM's diagonal replaced by a plain +-r box across the ray,
box/doom must fall below 0.90 (a measure that cannot tell r from r/2, or r from DOOM's r(|sin|+|cos|),
proves nothing about either).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from doomfj import combat as C                                    # noqa: E402
from doomfj.combat import CombatMixin, outcome_table_k            # noqa: E402
from doomfj.reference_model import ANGLE_TURN, ANGLE_TURN_HELD, ANGLE_TURN_TAP, ReferenceModel   # noqa: E402

M32 = 0xFFFFFFFF
TWO32 = 1 << 32
RANGE = 2048.0
DISTANCES = (128, 256, 512, 768, 1024, 1536, 1920)
RADII = {20: "zombieman / imp / sergeant", 30: "demon"}
STEPS = {                                   # name -> BAM per step
    "ours_640": 640 << 16,                  # blocked48's turn (one rate; before 2026-10-05)
    "ours_960": ANGLE_TURN_HELD,            # the owner's x1.5: a hold's later frames (and the only rate without taps)
    "ours_tap_320": ANGLE_TURN_TAP,         # SHIPPED on p67-f: a hold's FIRST frame (DOOM's slow turn) -- a tap
    "doom_tap_320": 320 << 16,              # DOOM's slow turn: a keyboard tap
    "doom_walk_640": 640 << 16,             # DOOM's held walk turn (same as ours_640: the rule alone)
}
PELLETS = 7
PAD = 200                                   # delta grid margin (2^16 BAM) past the widest half-step


def deg(bam: int) -> float:
    return bam * 360.0 / TWO32


class OneTarget:
    """the duck-typed world `aim_geometric` reads: ws (pose), rm, shootable_targets, los_points (open floor)"""

    def __init__(self, rm, x: int, y: int, r: int):
        self.rm = rm
        self.ws = SimpleNamespace(px=0, py=0, pangle=0)
        self._t = [("mon", 0, x, y, r)]

    def shootable_targets(self):
        return self._t

    @staticmethod
    def los_points(_a, _b):
        return True


def doom_hit(x: int, y: int, r: float, angle_bam: int) -> bool:
    """DOOM's P_LineAttack in 2D from the origin: PIT_AddThingIntercepts' diagonal, the crossing within RANGE"""
    a = (angle_bam & M32) * 2 * math.pi / TWO32
    dx, dy = math.cos(a), math.sin(a)
    pos = (dx > 0) == (dy > 0)                     # tracepositive = (dx ^ dy) > 0
    p1, p2 = ((x - r, y + r), (x + r, y - r)) if pos else ((x - r, y - r), (x + r, y + r))
    s1 = dx * p1[1] - dy * p1[0]
    s2 = dx * p2[1] - dy * p2[0]
    if (s1 > 0) == (s2 > 0):
        return False
    f = s1 / (s1 - s2)
    ix, iy = p1[0] + f * (p2[0] - p1[0]), p1[1] + f * (p2[1] - p1[1])
    dist = ix * dx + iy * dy
    return 0 < dist <= RANGE


def measure(views: int, dstep: int, ours_radius_scale: float = 1.0, doom_box: bool = False):
    rm = ReferenceModel()
    sites = C.Sites(rm)
    centre = rm.angle_to_x(0)
    gun_col = [col for _dmg, col in sites.gunshot[1]]                   # by post-state of the first draw
    spread = outcome_table_k(lambda a, b, c: b - c, 3)                   # the same states, DOOM's angle
    smax = max(STEPS.values()) // 2 + (PAD << 16)
    grid = list(range(-smax, smax + 1, dstep << 16))
    res = {}
    aim = CombatMixin.aim_geometric
    keys = ("pis", "bul", "sg1", "sgm")
    for r in RADII:
        r_ours = max(1, int(round(r * ours_radius_scale)))
        for D in DISTANCES:
            acc = {name: {"n": 0, **{p + k: 0.0 for p in ("o_", "d_", "ob_", "db_") for k in keys}}
                   for name in STEPS}
            off = []
            for k in range(views):
                b0 = (k + 0.37) * 2 * math.pi / views                    # never exactly on an axis
                x, y = int(round(D * math.cos(b0))), int(round(D * math.sin(b0)))
                bear = int(round(math.atan2(y, x) * TWO32 / (2 * math.pi))) & M32
                w = OneTarget(rm, x, y, r_ours)
                rows = {"o": [], "d": []}
                for d in grid:
                    view = (bear - d) & M32
                    w.ws.pangle = view
                    cover = [aim(w, c) is not None for c in range(72, 89)]
                    if doom_box:
                        d_tab = [_box_hit(x, y, r, (view + (s << 18)) & M32) for s in spread]
                        d_p = _box_hit(x, y, r, view)
                    else:
                        d_tab = [doom_hit(x, y, r, view + (s << 18)) for s in spread]
                        d_p = doom_hit(x, y, r, view)
                    o_tab = [cover[gun_col[n] - 72] for n in range(256)]
                    for tag, p, tab in (("o", cover[centre - 72], o_tab), ("d", d_p, d_tab)):
                        s1 = sm = 0
                        for n in range(256):
                            hh = sum(tab[(n + 1 + 3 * j) & 255] for j in range(PELLETS))
                            s1 += hh > 0
                            sm += hh
                        rows[tag].append((d, {"pis": float(p), "bul": sum(tab) / 256.0, "sg1": s1 / 256.0,
                                              "sgm": sm / 256.0}))
                # the player centres what he SEES: the middle of each rule's own accurate-shot interval
                # ("o_"/"d_"); "ob_"/"db_" centre on the TRUE bearing instead (the rule's bias shows there)
                for tag in ("o", "d"):
                    hit = [d for d, v in rows[tag] if v["pis"]]
                    assert hit, (r, D, k, tag)
                    if hit[0] > grid[0] and hit[-1] < grid[-1]:
                        c = (hit[0] + hit[-1]) / 2.0
                        if tag == "o":
                            off.append(c / 65536.0)
                    else:                       # wider than the grid (near): the bearing, and every step hits
                        c = 0.0
                    for name, S in STEPS.items():
                        for pre, cc in ((tag + "_", c), (tag + "b_", 0.0)):
                            sel = [v for d, v in rows[tag] if abs(d - cc) * 2 <= S]
                            for kk in keys:
                                acc[name][pre + kk] += sum(v[kk] for v in sel) / len(sel)
                for name in STEPS:
                    acc[name]["n"] += 1
            res[(r, D)] = {name: {kk: (v / a["n"] if kk != "n" else v) for kk, v in a.items()}
                           for name, a in acc.items()}
            res[(r, D)]["bias_deg"] = (sum(off) / len(off) * 65536 * 360.0 / TWO32) if off else None
    return res


def _box_hit(x, y, r, angle_bam):
    """the R9 control's DOOM: the +-r box ACROSS the ray (perpendicular distance), not the diagonal"""
    a = angle_bam * 2 * math.pi / TWO32
    dx, dy = math.cos(a), math.sin(a)
    along = x * dx + y * dy
    across = abs(-x * dy + y * dx)
    return 0 < along <= RANGE and across <= r


def report(res) -> str:
    L = []
    L.append("A. THE RULE ALONE -- both rules at the SAME step (640<<16 = 3.516 deg), each player centring what he")
    L.append("   sees (the middle of the rule's own accurate-shot interval). P = probability of a hit.")
    L.append("  r    D | ang.width | pistol 1st ours/doom | refire bullet ours/doom | shotgun P>=1 ours/doom "
             "| pellets of 7 ours/doom")
    for (r, D), by in sorted(res.items()):
        o, d = by["ours_640"], by["doom_walk_640"]
        w = 2 * math.degrees(math.atan(r / D))
        L.append("  %2d %4d | %5.2f deg | %5.3f / %5.3f        | %5.3f / %5.3f           | %5.3f / %5.3f          "
                 "| %4.2f / %4.2f" % (r, D, w, o["o_pis"], d["d_pis"], o["o_bul"], d["d_bul"], o["o_sg1"],
                                      d["d_sg1"], o["o_sgm"], d["d_sgm"]))
    L.append("")
    L.append("A2. THE SHIPPED RULE -- a tap turns ANGLE_TURN_TAP (the first frame of a hold; DOOM's slow turn), so the")
    L.append("   residual after the best taps is uniform over 320<<16; DOOM's keyboard tap is the same step. ours / doom:")
    L.append("  r    D | pistol 1st ours/doom | refire bullet ours/doom | shotgun P>=1 ours/doom | pellets of 7 ours/doom")
    for (r, D), by in sorted(res.items()):
        o, d = by["ours_tap_320"], by["doom_tap_320"]
        L.append("  %2d %4d | %5.3f / %5.3f        | %5.3f / %5.3f           | %5.3f / %5.3f          "
                 "| %4.2f / %4.2f" % (r, D, o["o_pis"], d["d_pis"], o["o_bul"], d["d_bul"], o["o_sg1"],
                                      d["d_sg1"], o["o_sgm"], d["d_sgm"]))
    L.append("")
    L.append("B. WITH THE TURN -- ours at blocked48's 640, the owner's x1.5 held rate 960 alone, and the SHIPPED tap")
    L.append("   (320, then 960 while held) vs DOOM's keyboard TAP (the slow turn, 320<<16 = 1.758 deg); the residual")
    L.append("   uniform over one step, centred as in A.")
    L.append("  r    D | pistol 1st: ours 640 | ours 960 | SHIPPED tap | DOOM tap 320 || shotgun P>=1: ours 640 "
             "| ours 960 | SHIPPED tap | DOOM tap 320")
    for (r, D), by in sorted(res.items()):
        L.append("  %2d %4d |  %5.3f               |  %5.3f   |  %5.3f       |  %5.3f       ||  %5.3f              "
                 "|  %5.3f   |  %5.3f       |  %5.3f" % (
                     r, D, by["ours_640"]["o_pis"], by["ours_960"]["o_pis"], by["ours_tap_320"]["o_pis"],
                     by["doom_tap_320"]["d_pis"], by["ours_640"]["o_sg1"], by["ours_960"]["o_sg1"],
                     by["ours_tap_320"]["o_sg1"], by["doom_tap_320"]["d_sg1"]))
    L.append("")
    L.append("C. THE WINDOW'S BIAS -- where our accurate-shot interval is centred, off the true bearing (- = the view")
    L.append("   turned LEFT of the target: column 80 is tested at its right edge, screen x 81, one column right of the")
    L.append("   view's centre -- R_ProjectSprite's x1/x2 convention, which the drawn sprite shares, so a player who")
    L.append("   centres the PICTURE never sees it), and the pistol's P at 640 if the player centred the TRUE bearing")
    L.append("   instead of the picture (ours / doom):")
    for (r, D), by in sorted(res.items()):
        b = by["bias_deg"]
        L.append("  %2d %4d | bias %s | pistol 1st, bearing-centred: %5.3f / %5.3f" % (
            r, D, "  (wider than the grid)" if b is None else "%+.3f deg" % b,
            by["ours_640"]["ob_pis"], by["doom_walk_640"]["db_pis"]))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", type=int, default=32)
    ap.add_argument("--dstep", type=int, default=4, help="delta grid, in units of 2^16 BAM")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    print("ANGLE_TURN_TAP %d << 16, ANGLE_TURN_HELD (= ANGLE_TURN) %d << 16 = %.3f deg; steps: %s" % (ANGLE_TURN_TAP >> 16,
        ANGLE_TURN >> 16, deg(ANGLE_TURN), ", ".join("%s %.3f deg" % (k, deg(v)) for k, v in STEPS.items())))
    if a.selftest:
        base = measure(8, 8)
        half = measure(8, 8, ours_radius_scale=0.5)
        box = measure(8, 8, doom_box=True)
        ok = True
        for r, D in ((20, 1024), (30, 1920)):         # where neither rule saturates at P = 1
            o, d = base[(r, D)]["ours_640"]["o_pis"], base[(r, D)]["doom_walk_640"]["d_pis"]
            oh = half[(r, D)]["ours_640"]["o_pis"]
            db = box[(r, D)]["doom_walk_640"]["d_pis"]
            print("selftest r=%d D=%d: ours %.3f doom %.3f | ours with r/2 %.3f (/doom %.2f, must be < 0.75) | "
                  "doom as a +-r box %.3f (/doom %.2f, must be < 0.90)" % (r, D, o, d, oh, oh / d, db, db / d))
            ok &= oh / d < 0.75                 # the measure sees the window's radius
            ok &= db / d < 0.90                 # ... and DOOM's diagonal against a plain box
        print("SELFTEST", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    res = measure(a.views, a.dstep)
    print("views %d, delta grid %d << 16 BAM; samples per (r, D, step): %s" % (
        a.views, a.dstep, {k: v["n"] for k, v in res[(20, 1024)].items() if k != "bias_deg"}))
    print(report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
