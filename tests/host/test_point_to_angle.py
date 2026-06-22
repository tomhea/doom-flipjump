"""M12b (F5) — projection angle primitive: the shared `tantoangle` kernel + `R_PointToAngle2` oracle.
`point_to_angle` returns the BAM angle of a map vector via DOOM's octant-fold + SlopeDiv + tantoangle
(no runtime atan) — the angle the wall projection (M12c) and the fj renderer build on. tantoangle is the
shared value kernel both the oracle and the fj angle LUT read (R6/D12).
"""
import math

from doomfj.reference_model import ANG90, ANG180, ANG270, FULL_CIRCLE, SLOPERANGE, ReferenceModel
from doomfj.tables import tantoangle_table


# ── the tantoangle value kernel ──────────────────────────────────────────────

def test_tantoangle_anchors_and_shape():
    t = tantoangle_table(SLOPERANGE)
    assert len(t) == SLOPERANGE + 1
    assert t[0] == 0
    assert t[SLOPERANGE] == 0x20000000             # atan(1) = 45deg = ANG45
    assert t[1024] == 316933406                     # atan(0.5) in BAM (hand-computed)
    assert all(t[i] < t[i + 1] for i in range(SLOPERANGE))   # strictly increasing


# ── point_to_angle: DOOM-exact cardinals (incl. the ±1 octant-boundary quirks) ──

def test_cardinal_angles_doom_exact():
    rm = ReferenceModel()
    u = 1 << 16
    assert rm.point_to_angle(0, 0,  u,  0) == 0               # East
    assert rm.point_to_angle(0, 0,  0,  u) == ANG90 - 1       # North (DOOM returns ANG90-1)
    assert rm.point_to_angle(0, 0, -u,  0) == ANG180 - 1      # West
    assert rm.point_to_angle(0, 0,  0, -u) == ANG270          # South
    assert rm.point_to_angle(5, 5, 5, 5) == 0                 # degenerate (no vector)


# ── point_to_angle ≈ atan2 (it approximates atan2 by tantoangle quantization) ──

def _bam_diff(a, b):
    d = (a - b) & (FULL_CIRCLE - 1)
    return min(d, FULL_CIRCLE - d)


def test_point_to_angle_matches_atan2_within_quantization():
    rm = ReferenceModel()
    tol = 1 << 20                                   # ~4 tantoangle steps (~0.09deg)
    for k in range(64):
        theta = 2 * math.pi * k / 64
        dx = round(math.cos(theta) * 1_000_000)     # 16.16-scale magnitude (avoids SlopeDiv clamp)
        dy = round(math.sin(theta) * 1_000_000)
        got = rm.point_to_angle(0, 0, dx, dy)
        ideal = round(theta / (2 * math.pi) * FULL_CIRCLE) & (FULL_CIRCLE - 1)
        assert _bam_diff(got, ideal) <= tol, (k, hex(got), hex(ideal))


def test_point_to_angle_is_origin_invariant():
    """The angle depends only on the vector, not the absolute viewpoint."""
    rm = ReferenceModel()
    for (ox, oy) in [(0, 0), (1000 << 16, -500 << 16), (-7 << 16, 7 << 16)]:
        a = rm.point_to_angle(ox, oy, ox + (3 << 16), oy + (1 << 16))
        b = rm.point_to_angle(0, 0, 3 << 16, 1 << 16)
        assert a == b
