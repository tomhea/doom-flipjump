"""W1R-2C draft: finer runs + an ALT-COLOUR bit per run, ready to paste into reference_model
once V5's certification is committed (keeping the certified sources clean until then).

Pattern entries become (run_len, colormap_row, alt) -- alt=1 draws the run over the texture's
SECOND representative texel (wlit2) instead of the first. Lens shrunk ~30-40% vs the shipped
tables (finer texture, ~+30-50% wall pairs -- the wall emit is ~0.5M of the frame, so this is
a ~+0.2M-class change). Alt runs are scattered (~30%) so they read as embedded stones/panels.
"""

W1R_TIER_BOUNDS_2C = (6, 16, 40)

W1R_PATTERNS_2C = (
    (   # tier 0, wlen < 6
        ((5, 14, 0),), ((5, 17, 1),), ((5, 15, 0),), ((5, 16, 1),),
    ),
    (   # tier 1, 6 <= wlen < 16: 2-3 px runs
        ((2, 9, 0), (2, 15, 1), (3, 11, 0), (2, 17, 0)),
        ((2, 13, 1), (3, 9, 0), (2, 17, 0), (2, 12, 0)),
        ((3, 11, 0), (2, 17, 0), (2, 9, 1), (2, 14, 0)),
        ((2, 15, 0), (2, 10, 0), (2, 17, 1), (3, 12, 0)),
    ),
    (   # tier 2, 16 <= wlen < 40: 2-4 px runs
        ((3, 4, 0), (2, 12, 1), (3, 8, 0), (4, 14, 0), (2, 5, 0), (3, 10, 1)),
        ((3, 10, 0), (4, 4, 0), (2, 14, 1), (3, 6, 0), (2, 12, 0), (3, 8, 0)),
        ((4, 6, 0), (2, 13, 0), (3, 4, 1), (2, 10, 0), (3, 14, 0), (2, 7, 1)),
        ((2, 12, 0), (3, 5, 1), (4, 10, 0), (2, 4, 0), (3, 14, 0), (2, 8, 0)),
    ),
    (   # tier 3, wlen >= 40 (near): 3-6 px runs
        ((5, 0, 0), (3, 7, 1), (5, 3, 0), (4, 8, 0), (4, 1, 0), (3, 5, 1), (4, 2, 0)),
        ((4, 4, 0), (5, 0, 0), (3, 8, 1), (5, 2, 0), (4, 6, 0), (4, 0, 1), (3, 3, 0)),
        ((5, 1, 0), (4, 5, 1), (4, 0, 0), (3, 8, 0), (5, 4, 0), (4, 7, 1), (3, 2, 0)),
        ((4, 2, 0), (5, 7, 0), (3, 0, 1), (5, 4, 0), (3, 8, 0), (4, 1, 0), (4, 6, 1)),
    ),
)


def w1r_texel2(texels, pal, texel1):
    """The SECOND representative texel: the most common texel among those RGB-distant from
    texel1 (so the accent reads as a different material, not a shade of the same one), searched
    in the brighter half like texel1. Falls back to texel1 (single-colour textures stay
    single-colour -- the alt bit then changes nothing)."""
    from collections import Counter
    lum = {t: sum(pal[t]) for t in set(texels)}
    med = sorted(lum[t] for t in texels)[len(texels) // 2]
    bright = [t for t in texels if lum[t] >= med]
    r1, g1, b1 = pal[texel1]

    def dist(t):
        r, g, b = pal[t]
        return abs(r - r1) + abs(g - g1) + abs(b - b1)

    far = [t for t in bright if dist(t) >= 60]
    if not far:
        return texel1
    return Counter(far).most_common(1)[0][0]
