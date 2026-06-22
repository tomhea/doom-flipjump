"""M12g (F5) — wall height projection (R_RenderSegLoop top/bottom). Given the front sector's ceiling/floor
heights, the eye `viewz` (= floor + VIEWHEIGHT), and a column's `scale`, the wall occupies screen rows
[top, bottom) with top = CENTERY - worldtop·scale, bottom = CENTERY - worldbottom·scale (worldX = height -
viewz). Validated on the square room sector (floor 0, ceiling 128): a far wall sits small around the
horizon (CENTERY=50); a near wall overfills the viewport. The render loop (M12h) clips off-screen rows.
"""
from doomfj.reference_model import ReferenceModel, VIEWHEIGHT


def test_view_z_is_floor_plus_eye_height():
    rm = ReferenceModel()
    assert rm.view_z(0) == (0 + VIEWHEIGHT) << 16
    assert rm.view_z(64) == (64 + 41) << 16


def test_wall_screen_span_exact():
    """Square-room sector (ceil 128, floor 0, viewz 41) at three scales — deterministic rows."""
    rm = ReferenceModel()
    vz = rm.view_z(0)
    assert rm.wall_screen_span(128, 0, vz, 40960) == (-5, 75)    # scale 0.625 (perp wall at dist 128)
    assert rm.wall_screen_span(128, 0, vz, 16384) == (28, 60)    # scale 0.25 (far): small, near horizon
    assert rm.wall_screen_span(128, 0, vz, 93952) == (-75, 108)  # scale ~1.43 (close): overfills view


def test_top_above_bottom_and_brackets_horizon():
    """top < bottom always; a distant wall straddles the horizon (CENTERY)."""
    rm = ReferenceModel()
    vz = rm.view_z(0)
    cy = rm.cfg.CENTERY
    for scale in (8192, 16384, 32768, 65536):
        top, bottom = rm.wall_screen_span(128, 0, vz, scale)
        assert top < bottom
    top, bottom = rm.wall_screen_span(128, 0, vz, 16384)          # far wall
    assert top < cy < bottom


def test_closer_wall_is_taller():
    """Bigger scale (nearer) ⇒ the wall's top rises and its bottom drops (taller on screen)."""
    rm = ReferenceModel()
    vz = rm.view_z(0)
    near_top, near_bottom = rm.wall_screen_span(128, 0, vz, 65536)   # scale 1.0
    far_top, far_bottom = rm.wall_screen_span(128, 0, vz, 16384)     # scale 0.25
    assert near_top < far_top and near_bottom > far_bottom
