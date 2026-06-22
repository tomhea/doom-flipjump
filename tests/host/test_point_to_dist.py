"""M12d (F5) — projection distance primitive: `R_PointToDist` (view→point distance). Computes
sqrt(dx²+dy²) without a sqrt — fold to the major octant, index `tantoangle` by the FixedDiv slope,
divide dx by cos(angle) (= finesine[angle+90°]). The wall's perpendicular distance `rw_distance`
(M12e, feeding R_ScaleFromGlobalAngle) is built on this; the fj renderer matches it (R6/D12).
"""
import math

from doomfj.reference_model import ReferenceModel

U = 1 << 16   # 16.16 unit


def _d(rm, vx, vy, x, y):
    return rm.point_to_dist(vx * U, vy * U, x * U, y * U)


def test_axis_aligned_exact():
    """dy=0 (or dx=0 after the octant fold) ⇒ dist = dx exactly (cos 0 = 1, no quantization)."""
    rm = ReferenceModel()
    assert _d(rm, 0, 0, 100, 0) == 100 * U
    assert _d(rm, 0, 0, 0, 100) == 100 * U
    assert _d(rm, 128, 128, 128, 400) == 272 * U
    assert _d(rm, 50, 50, 7, 50) == 43 * U


def test_45_degrees_near_exact():
    rm = ReferenceModel()
    got, ideal = _d(rm, 0, 0, 100, 100), round(100 * math.sqrt(2) * U)
    assert abs(got - ideal) <= 64                                    # sqrt(2)*100, within finesine quantization


def test_offaxis_matches_euclidean_within_quantization():
    rm = ReferenceModel()
    for (vx, vy, x, y) in [(0, 0, 300, 40), (50, 50, 200, 90), (10, 90, 240, 17), (-30, 12, 88, -200)]:
        got = _d(rm, vx, vy, x, y) / U
        want = math.hypot(x - vx, y - vy)
        assert abs(got - want) / want <= 0.002, (vx, vy, x, y, got, want)   # <=0.2% (LUT quantization)


def test_distance_is_symmetric():
    rm = ReferenceModel()
    for (vx, vy, x, y) in [(0, 0, 300, 40), (50, 50, 200, 90), (-30, 12, 88, -200)]:
        assert _d(rm, vx, vy, x, y) == _d(rm, x, y, vx, vy)


def test_degenerate_point_is_zero():
    rm = ReferenceModel()
    assert _d(rm, 5, 5, 5, 5) == 0
