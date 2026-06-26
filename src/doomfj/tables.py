"""G-a — pure LUT VALUE functions (sine, reciprocal, ...).

These return the raw encoded entry values (the LUT *contents*), and are the single source shared by
the emitter (H2/H4, M5/M8) and the reference oracle (H5, M9) so the two cannot drift (D12/R6). The
fj-text emission (`hex.vec` entries / packed-byte ops) is a separate concern — `lut_generator.py`
(M5, §3.4 fallback) and the dispatch-code emitter. (Value kernel lifted from PR #1, D15 keep — M4.)
"""
from __future__ import annotations
import math

from doomfj.fixedpoint import encode_fixed_point, fixed_div, _signed


# ── DOOM floor/ceiling (visplane) light constants (R_InitLightTables / R_MapPlane, M13) ──
LIGHTLEVELS = 16        # zlight light buckets (sector light >> LIGHTSEGSHIFT)
LIGHTSEGSHIFT = 4       # sector light (0..255) -> zlight light bucket (0..15)
MAXLIGHTZ = 128         # zlight distance buckets (distance >> LIGHTZSHIFT)
LIGHTZSHIFT = 20        # distance (16.16) -> zlight distance bucket
LIGHTSCALESHIFT = 12    # DOOM R_InitLightTables intermediate shift
DISTMAP = 2             # DOOM distance-darkening rate divisor


def yslope_table(view_w: int, view_h: int) -> list[int]:
    """DOOM's `yslope[]` (R_ExecuteSetViewSize): per screen-row y, `FixedDiv(centerx*FRACUNIT, |dy|)`
    where `dy = ((y - view_h//2) << 16) + FRACUNIT/2` (the +0.5 keeps the horizon row non-zero, so no
    div0). 16.16. `distance = FixedMul(planeheight, yslope[y])` is the world distance to the floor/ceiling
    pixel in row y (planeheight = |plane_z - viewz|). centerx = view_w//2 (PROJECTION, FOV=90°). Shared
    kernel (R6): the oracle and the fj LUT both read it."""
    centerx = view_w // 2
    centery = view_h // 2
    out = []
    for y in range(view_h):
        dy = abs(((y - centery) << 16) + (1 << 15))
        out.append(fixed_div(centerx << 16, dy, 8, 4))    # FixedDiv(centerx<<16, dy) -> 16.16
    return out


def zlight_table(view_w: int, num_colormaps: int) -> list[list[int]]:
    """DOOM's `zlight[]` (R_InitLightTables): the distance-based floor/ceiling light map. Returns a
    `LIGHTLEVELS × MAXLIGHTZ` grid of COLORMAP row indices (0..num_colormaps-1). Index it as
    `zlight[light >> LIGHTSEGSHIFT][min(MAXLIGHTZ-1, distance >> LIGHTZSHIFT)]` (R_MapPlane). Farther
    spans (larger distance bucket j) get a darker row. centerx = view_w//2 (our PROJECTION analog of
    DOOM's SCREENWIDTH/2). Shared kernel (R6): the oracle and the fj LUT both read it."""
    centerx = view_w // 2
    grid = []
    for i in range(LIGHTLEVELS):
        startmap = ((LIGHTLEVELS - 1 - i) * 2) * num_colormaps // LIGHTLEVELS
        row = []
        for j in range(MAXLIGHTZ):
            scale = fixed_div(centerx << 16, (j + 1) << LIGHTZSHIFT, 8, 4)   # FixedDiv(centerx<<16, ...)
            scale >>= LIGHTSCALESHIFT
            level = startmap - scale // DISTMAP
            level = max(0, min(num_colormaps - 1, level))
            row.append(level)
        grid.append(row)
    return grid


def sine_table(count: int, fraction_bits: int, total_bits: int) -> list[int]:
    """sin(2*pi*k/count) for k in [0, count), as signed fixed-point words (two's-complement).
    count=4096 (16**3) is the design's trig table size (§1.2/§2.1)."""
    return [encode_fixed_point(math.sin(2 * math.pi * k / count), fraction_bits, total_bits)
            for k in range(count)]


def reciprocal_table(count: int, fraction_bits: int, total_bits: int) -> list[int]:
    """round(2^fraction_bits / i) for i in [0, count); entry 0 is clamped to the max entry value
    (DOOM convention), and every entry is clamped to the entry width. Replaces runtime divides."""
    max_value = (1 << total_bits) - 1
    table = [max_value]
    table += [min(round((1 << fraction_bits) / i), max_value) for i in range(1, count)]
    return table


def viewangletox_table(view_w: int, trig_n: int) -> list[int]:
    """DOOM's `viewangletox[]`: maps a view-relative fine angle to a screen column. Front-FOV table of
    `trig_n//2` entries (§1.3). Entry j holds the column for view-relative angle `(j<<angle_shift) - ANG90`
    (j=0 → -90°, j=trig_n//4 → straight ahead → CENTERX, j=trig_n//2 → +90°): `col = CENTERX - tan(angle)
    * PROJECTION`, where FOV=90° ⇒ PROJECTION=CENTERX=view_w//2 (screen edges at ±45°). Clamped to
    [-1, view_w+1] (DOOM's off-screen sentinels). Monotonic non-increasing. Shared kernel (R6): the oracle
    `angle_to_x` and the fj LUT both read it. (The wall *scale* uses finesine, not finetangent, so no
    runtime tangent LUT is needed — tan is folded into this build-time table.)"""
    centerx = view_w // 2
    projection = centerx
    angle_shift = 32 - (trig_n.bit_length() - 1)      # config-derived (same as the finesine shift)
    ang90 = 1 << 30
    table = []
    for j in range(trig_n // 2):
        angle = (j << angle_shift) - ang90            # signed BAM in [-ANG90, +ANG90)
        col = round(centerx - math.tan(angle / (1 << 32) * 2 * math.pi) * projection)
        table.append(max(-1, min(view_w + 1, col)))
    return table


def xtoviewangle_table(view_w: int, trig_n: int) -> list[int]:
    """DOOM's `xtoviewangle[]` (the inverse of `viewangletox`): maps a screen column to the view-relative
    BAM angle at that column's left edge. `view_w + 1` entries (a column can be the right edge of the last
    wall). Built exactly as DOOM's R_InitTextureMapping: for column x, find the first fine index i with
    `viewangletox[i] <= x`, then `xtoviewangle[x] = (i << angle_shift) - ANG90` (masked to 32-bit BAM).
    Result: x=0 → ≈+ANG45 (leftmost = most-positive/CCW angle), centre → 0, x=view_w → ≈-ANG45. The
    per-column wall scale (M12h) reads `viewangle + xtoviewangle[x]` at the seg's two endpoint columns to
    seed DOOM's scale interpolation. Shared kernel (R6/D12): the oracle and the fj LUT both read it."""
    vtox = viewangletox_table(view_w, trig_n)
    angle_shift = 32 - (trig_n.bit_length() - 1)
    ang90 = 1 << 30
    table = []
    for x in range(view_w + 1):
        i = 0
        while i < len(vtox) and vtox[i] > x:
            i += 1
        table.append(((i << angle_shift) - ang90) & 0xFFFFFFFF)
    return table


def finetangent_table(trig_n: int) -> list[int]:
    """DOOM's `finetangent[]`: `tan(angle - 90°)` as signed 16.16, indexed by the same fine index as
    finesine (`angle >> angle_shift`). The −90° offset is DOOM's (R_RenderSegLoop indexes it with
    `rw_centerangle + xtoviewangle[x]`, which sits around ANG90 for a head-on wall) ⇒ `finetangent[ANG90]
    = tan(0) = 0` (the wall's centre texel), rising to ±1.0 at ±45° from centre. Poles at angle 0°/180°
    (tan(∓90°) = ∓∞) are clamped to the signed 32-bit range. The per-column texture u-coordinate is
    `rw_offset − FixedMul(finetangent[angle], rw_distance)` (M12-textures). Shared kernel (R6/D12)."""
    lo, hi = -(1 << 31), (1 << 31) - 1
    out = []
    for i in range(trig_n):
        t = math.tan(2 * math.pi * i / trig_n - math.pi / 2)
        out.append(max(lo, min(hi, round(t * (1 << 16)))) & 0xFFFFFFFF)
    return out


def distscale_table(view_w: int, trig_n: int) -> list[int]:
    """DOOM's `distscale[]` (R_ExecuteSetViewSize): the per-column fisheye correction `1/|cos(view-relative
    angle at column x)|` = `FixedDiv(FRACUNIT, |finecosine[xtoviewangle[x] >> angle_shift]|)`, 16.16. Used
    by R_MapPlane to turn a row's perpendicular `distance` into the slant `length` to the span's left edge
    (`length = FixedMul(distance, distscale[x1])`). `view_w` entries. The view-relative angles span only the
    ±FOV/2 frustum, so `cos` never reaches 0 (no div0). Shared kernel (R6): the oracle and the fj LUT both
    read it."""
    vtoa = xtoviewangle_table(view_w, trig_n)
    sine = sine_table(trig_n, 16, 32)
    angle_shift = 32 - (trig_n.bit_length() - 1)
    out = []
    for x in range(view_w):
        idx = (vtoa[x] & 0xFFFFFFFF) >> angle_shift
        cos = sine[(idx + trig_n // 4) & (trig_n - 1)]          # finecosine = finesine shifted +N/4
        cosadj = max(1, abs(_signed(cos, 32)))                  # |cos|; clamp away from 0 (no div0)
        out.append(fixed_div(1 << 16, cosadj, 8, 4))            # FixedDiv(FRACUNIT, |cos|)
    return out


def tantoangle_table(slope_range: int = 2048) -> list[int]:
    """DOOM's `tantoangle[]`: the BAM angle whose tangent is `i/slope_range`, for i in [0, slope_range].
    `tantoangle[i] = atan(i/slope_range)` as a 32-bit BAM (full turn = 2^32) — so [0] = 0 and
    [slope_range] = atan(1) = 45deg = ANG45 = 0x20000000. Indexed by R_PointToAngle's slope quotient
    (a computed value in [0, SLOPERANGE], §1.3 — not a shift-extracted index). slope_range+1 entries.
    Shared kernel: the oracle's `point_to_angle` and the fj angle LUT both read these (R6/D12)."""
    return [round(math.atan(i / slope_range) / (2 * math.pi) * (1 << 32)) for i in range(slope_range + 1)]
