"""M13-raster coarse cull: the BAKED coarse-angle bounds shared (R6 SSOT) by the fj macro's data table
and the host reference / prototype.

The division-free coarse cull pins a vertex's absolute BAM angle to a conservative interval [lo,hi]
using ONLY sign-folds + integer magnitude compares (NO slope_div): the octant idx
(sign(dx)*4 + sign(dy)*2 + (|dx|>|dy|), matching proj.point_to_angle) plus a WEDGE idx that subdivides
the octant by comparing the ratio min(|dx|,|dy|)/max(...) against NW-1 fixed thresholds
(smaller*NW vs larger*k -- integer, no division). Each (octant, wedge) maps to a compile-time-constant
[lo,hi] BAM interval: within a wedge the true `base` = tantoangle[slope] lies in
[tantoangle[w*(SLOPERANGE/NW)], tantoangle[(w+1)*(SLOPERANGE/NW)]] (tantoangle is monotone), and the
octant's point_to_angle output formula maps that base-range to an angle-range, widened by a small
guard for the tantoangle quantization. Because the interval is a guaranteed SUPERSET of the true
angle, a seg both of whose vertices' intervals miss the frustum (or whose conservative column span is
fully drawn) is provably invisible -> cullable WITHOUT the division. Pure optimization: identical
pixels, no oracle change, no re-bless.
"""
from __future__ import annotations

from doomfj.tables import tantoangle_table
from doomfj.reference_model import SLOPERANGE

ANGMASK = (1 << 32) - 1
NW_DEFAULT = 8                 # wedges per octant (73% cull @ E1M1 spawn; diminishing returns above)
GUARD_DEFAULT = 1 << 22        # widen each interval for tantoangle quantization (keeps culls conservative)


def _octant_map(oct_: int, base: int) -> int:
    """proj.point_to_angle's per-octant output formula (projection.fj oct0..oct7), base in [0,ANG45]."""
    if oct_ == 0: return (0x3FFFFFFF - base) & ANGMASK
    if oct_ == 1: return base & ANGMASK
    if oct_ == 2: return (0xC0000000 + base) & ANGMASK
    if oct_ == 3: return (-base) & ANGMASK
    if oct_ == 4: return (0x40000000 + base) & ANGMASK
    if oct_ == 5: return (0x7FFFFFFF - base) & ANGMASK
    if oct_ == 6: return (0xBFFFFFFF - base) & ANGMASK
    return (0x80000000 + base) & ANGMASK   # oct 7


def coarse_angle_bounds(nw: int = NW_DEFAULT, guard: int = GUARD_DEFAULT):
    """Return a list of (lo, hi) BAM intervals, indexed by (octant*nw + wedge), 8*nw entries.
    Each interval is a conservative superset of the true absolute angle for any vertex whose octant
    and ratio-wedge match. lo/hi are unsigned 32-bit (may wrap; the consumer does modular arc tests)."""
    tta = tantoangle_table(SLOPERANGE)
    assert SLOPERANGE % nw == 0, f"SLOPERANGE={SLOPERANGE} not divisible by nw={nw}"
    step = SLOPERANGE // nw
    out = []
    for oct_ in range(8):
        for w in range(nw):
            blo = tta[w * step]
            bhi = tta[(w + 1) * step]
            a = _octant_map(oct_, blo)
            b = _octant_map(oct_, bhi)
            # the two endpoints may be in either order (formula can flip); pick the short arc
            lo, hi = (a, b) if ((b - a) & ANGMASK) < (1 << 31) else (b, a)
            out.append(((lo - guard) & ANGMASK, (hi + guard) & ANGMASK))
    return out


def octant_wedge_idx(dx: int, dy: int, nw: int = NW_DEFAULT):
    """The (octant, wedge, combined) indices for a delta, using ONLY sign-folds + integer compares
    (the exact computation the fj macro performs; no division). Returns None for the (0,0) degenerate."""
    if dx == 0 and dy == 0:
        return None
    sx = dx < 0
    sy = dy < 0
    adx, ady = abs(dx), abs(dy)
    gt = adx > ady
    oct_ = (4 if sx else 0) + (2 if sy else 0) + (1 if gt else 0)
    smaller, larger = (ady, adx) if gt else (adx, ady)
    w = 0
    for k in range(1, nw):
        if smaller * nw >= larger * k:     # smaller/larger >= k/nw  (integer, no division)
            w = k
    return oct_, w, oct_ * nw + w


def generate_coarse_bounds_fj(label: str, nw: int = NW_DEFAULT, guard: int = GUARD_DEFAULT) -> str:
    """Emit the coarse-bounds data table as fj: 8*nw entries, each two 8-nibble values [lo, hi]
    laid out contiguously (entry k's lo at label + k*16*dw, hi at label + (k*16+8)*dw). Read with
    hex.read_table 8 / hex.read_table_packed on the combined index (octant*nw + wedge)."""
    bounds = coarse_angle_bounds(nw, guard)
    lines = [f"// coarse-angle bounds ({8*nw} entries, nw={nw}, guard={guard:#x}) - doomfj.coarse_cull",
             f"{label}:"]
    for lo, hi in bounds:
        lines.append(f"    hex.vec 8, {lo:#x}")
        lines.append(f"    hex.vec 8, {hi:#x}")
    return "\n".join(lines) + "\n"
