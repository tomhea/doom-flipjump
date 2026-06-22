"""M12c (F5) — horizontal projection: the shared `viewangletox` kernel + `angle_to_x` oracle + the
projection constants (CENTERX/CENTERY/PROJECTION). Maps a view-relative BAM angle to a screen column via
the FOV-90 perspective (focal = CENTERX = VIEW_W//2, screen edges at ±45°). The wall's [x1, x2] column
span (M12d) is two angle_to_x lookups; the fj renderer reads the same emitted table (R6/D12).
"""
from doomfj.config import Config
from doomfj.reference_model import ANG90, ReferenceModel
from doomfj.tables import viewangletox_table, xtoviewangle_table

ANG45 = ANG90 // 2
FINE_STEP = 1 << (32 - (4096).bit_length() + 1)   # one fine-angle BAM step at TRIG_N=4096 (= 1<<20)


def _signed(v):
    return v - (1 << 32) if v >= (1 << 31) else v


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


# ── xtoviewangle (the inverse: column -> view-relative angle, M12h) ─────────

def test_xtoviewangle_shape_and_anchors():
    # anchors land within ~one column's angular width (a fine-index plateau maps to one column);
    # at ~0.56°/column that is ≈6.4 fine steps, so allow 8 (centre sits on the widest plateau).
    t = xtoviewangle_table(160, 4096)
    assert len(t) == 160 + 1                                              # one entry per column edge
    assert abs(_signed(t[0]) - ANG45) <= 8 * FINE_STEP                    # leftmost col ≈ +45deg
    assert abs(_signed(t[80])) <= 8 * FINE_STEP                           # centre ≈ straight ahead (0)
    assert abs(_signed(t[160]) + ANG45) <= 8 * FINE_STEP                  # rightmost col ≈ -45deg


def test_xtoviewangle_monotonic_non_increasing():
    """Left→right columns give decreasing (signed) view angles (left = most-positive/CCW)."""
    sv = [_signed(v) for v in xtoviewangle_table(160, 4096)]
    assert all(sv[i] >= sv[i + 1] for i in range(len(sv) - 1))


def test_xtoviewangle_inverts_angle_to_x():
    """Round-trip: feeding each column's angle back through angle_to_x lands on (about) that column —
    the two tables are inverses (within the half-table's ±1-column quantization)."""
    rm = ReferenceModel()
    t = xtoviewangle_table(rm.cfg.VIEW_W, rm.cfg.TRIG_N)
    for x in range(0, rm.cfg.VIEW_W + 1, 8):
        assert abs(rm.angle_to_x(t[x]) - x) <= 1
