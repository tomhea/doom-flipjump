"""M12c (F5) — horizontal projection: the shared `viewangletox` kernel + `angle_to_x` oracle + the
projection constants (CENTERX/CENTERY/PROJECTION). Maps a view-relative BAM angle to a screen column via
the FOV-90 perspective (focal = CENTERX = VIEW_W//2, screen edges at ±45°). The wall's [x1, x2] column
span (M12d) is two angle_to_x lookups; the fj renderer reads the same emitted table (R6/D12).
"""
from doomfj.config import Config
from doomfj.reference_model import ANG90, ReferenceModel
from doomfj.tables import viewangletox_table

ANG45 = ANG90 // 2


# ── projection constants (config-derived SSOT) ──────────────────────────────

def test_projection_constants_config_derived():
    c = Config()
    assert (c.CENTERX, c.CENTERY, c.PROJECTION) == (80, 50, 80)          # W=160,H=100; FOV90 focal=centerx
    assert Config(W=320, H=200).CENTERX == 160                            # follows resolution (no literal)
    assert "CENTERX" in c.constants() and c.constants()["PROJECTION"] == 80


# ── viewangletox value kernel ───────────────────────────────────────────────

def test_viewangletox_anchors_and_shape():
    t = viewangletox_table(160, 4096)
    assert len(t) == 4096 // 2                                            # front-FOV half-table (§1.3)
    assert t[1024] == 80                                                  # straight ahead -> CENTERX
    assert t[1536] == 0                                                   # +45deg -> left edge (col 0)
    assert t[512] == 160                                                  # -45deg -> right edge
    assert all(t[i] >= t[i + 1] for i in range(len(t) - 1))               # monotonic non-increasing
    assert min(t) == -1 and max(t) == 161                                 # clamped to [-1, VIEW_W+1]


# ── angle_to_x (the lookup the wall projection uses) ────────────────────────

def test_angle_to_x_anchors():
    rm = ReferenceModel()
    assert rm.angle_to_x(0) == 80                                         # straight ahead -> centre
    assert rm.angle_to_x(ANG45) == 0                                      # +45deg (left) -> col 0
    assert rm.angle_to_x((-ANG45) & 0xFFFFFFFF) == 160                    # -45deg (right) -> col 160


def test_angle_to_x_matches_table():
    rm = ReferenceModel()
    t = viewangletox_table(rm.cfg.VIEW_W, rm.cfg.TRIG_N)
    # angle 0 -> index 1024; sweep a few view-relative angles and confirm the lookup matches the table
    for a in [0, ANG45 // 2, ANG45, -(ANG45 // 2) & 0xFFFFFFFF, (-ANG45) & 0xFFFFFFFF]:
        idx = ((a + ANG90) & 0xFFFFFFFF) >> rm.angle_shift
        idx = max(0, min(len(t) - 1, idx))
        assert rm.angle_to_x(a) == t[idx]


def test_angle_to_x_monotonic_across_fov():
    """Sweeping the view-relative angle left→right gives non-increasing columns (left = col 0)."""
    rm = ReferenceModel()
    cols = [rm.angle_to_x((a) & 0xFFFFFFFF) for a in range(ANG45, -ANG45, -(ANG45 // 20))]
    assert all(cols[i] <= cols[i + 1] for i in range(len(cols) - 1))
