"""M7 P1.6 -- the native-list sprite bank: ONE generator for both mirrors (docs/gp-sprite-bank.md).

A sprite column is stored ONCE per resolution tier, at the patch's own scale, and drawn at any height
bucket through ONE table, `rowmap`: its row boundaries are NORMALIZED to 0..255 of the column's
native height, so the same table serves every patch. `native_list` builds a column's list,
`strip_from_list` draws it at a bucket -- the oracle calls it where it called `sprite_strip`, and
the emitter bakes the same lists and the same table, so the two cannot draw different pictures.

What moves against the per-bucket bank it replaces (class F, plan D6): a boundary lands at
`rowmap[b][round(v*255/dh)]` instead of `ceil(v*hb/dh)`, and the run cap binds once, at native scale,
instead of per bucket. What does not: which things are drawn, their bucket and height, their feet,
their tier, their light.
"""
from __future__ import annotations

from functools import lru_cache

NORM = 255                        # a boundary's normalized range: row v of dh -> round(v*NORM/dh)


def norm_row(v: int, dh: int) -> int:
    """native boundary `v` (0..dh) of a `dh`-row column, normalized to 0..NORM (round half up)"""
    assert 0 <= v <= dh and 0 < dh <= NORM, (v, dh)
    return (v * NORM + dh // 2) // dh


def rowmap_row(n: int, hb: int) -> int:
    """the screen row, below the sprite's bucket top, of normalized boundary `n` at height `hb`"""
    return (n * hb + NORM - 1) // NORM


def rowmap_table(bucket_heights) -> list:
    """`rowmap[b][n]` for every bucket: the table fj dispatches through, 32 x 256"""
    return [[rowmap_row(n, hb) for n in range(NORM + 1)] for hb in bucket_heights]


def native_list(col, dh: int, cap: int):
    """One column's list at native scale -> `(n_first, n_last, [(n_end, texel), ...])`, or None for a
    fully transparent column. The run rules are `ReferenceModel.sprite_strip`'s, applied to native
    rows: only the OPAQUE EXTENT is kept, interior holes take the nearest opaque texel ABOVE, equal
    neighbours merge, and while there are more runs than `cap` the first shortest (by native length)
    is absorbed into the run above it (the first run into the one below)."""
    assert len(col) == dh, (len(col), dh)
    idx = [v for v, t in enumerate(col) if t >= 0]
    if not idx:
        return None
    v0, v1 = idx[0], idx[-1]
    runs: list[list[int]] = []                   # [end_exclusive (native row), texel]
    last = col[v0]
    for v in range(v0, v1 + 1):
        if col[v] >= 0:
            last = col[v]
        if runs and runs[-1][1] == last:
            runs[-1][0] = v + 1
        else:
            runs.append([v + 1, last])
    while len(runs) > cap:
        starts = [v0] + [r[0] for r in runs[:-1]]
        lens = [r[0] - s for r, s in zip(runs, starts)]
        i = lens.index(min(lens))
        if i:
            runs[i - 1][0] = runs[i][0]
        runs.pop(i)
    return norm_row(v0, dh), norm_row(v1 + 1, dh), [(norm_row(e, dh), t) for e, t in runs]


def strip_from_list(lst, hb: int):
    """A native list drawn `hb` rows tall -> `(r0, runs)` in `sprite_strip`'s format (`r0` the first
    painted row below the sprite's top, `runs` `[rel_end_exclusive from r0, texel]`), or None when
    the column maps to no row at this height. A run that maps to no row is dropped."""
    if lst is None:
        return None
    n_first, n_last, pairs = lst
    r0 = rowmap_row(n_first, hb)
    if rowmap_row(n_last, hb) <= r0:
        return None
    runs, prev = [], 0
    for n_end, t in pairs:
        e = rowmap_row(n_end, hb) - r0
        if e > prev:
            runs.append([e, t])
            prev = e
    return r0, runs


def min_bucket(lst, bucket_heights):
    """The bucket from which the column draws at EVERY taller bucket -- the record's one test per
    column (`b >= min_b`). Rounding makes a thin column's extent non-monotone in the height (it can
    map to a row at one bucket and to none at the next), so this is a DEFINITION both mirrors share,
    not a property of the list: below `min_b` the column is not drawn, even at a bucket where its
    extent would map to a row. `len(bucket_heights)` = never drawn."""
    n = len(bucket_heights)
    if lst is None:
        return n
    b = n
    while b > 0 and strip_from_list(lst, bucket_heights[b - 1]) is not None:
        b -= 1
    return b


def bank_list(col, dh: int, cap: int, bucket_heights):
    """The bank's content for one column and tier -> `(n_first, min_b, n_last, pairs)` (the block's
    ops 0, 1, 2 and the pairs from op 3), or None for a fully transparent column."""
    lst = native_list(col, dh, cap)
    if lst is None:
        return None
    n_first, n_last, pairs = lst
    return n_first, min_bucket(lst, bucket_heights), n_last, pairs


def strip_at(bl, b: int, hb: int):
    """`bank_list`'s column drawn at bucket `b` (height `hb`): `strip_from_list`, or None below the
    column's `min_b` -- what the oracle draws and fj emits"""
    if bl is None or b < bl[1]:
        return None
    st = strip_from_list((bl[0], bl[2], bl[3]), hb)
    assert st is not None, "min_b promised a row at every bucket from it"
    return st


@lru_cache(maxsize=None)
def bank_list_of(col: tuple, dh: int, cap: int, bucket_heights: tuple):
    """`bank_list`, memoized by the column's CONTENT -- the oracle asks for the same columns every
    frame, and a column's list depends on nothing else"""
    return bank_list(list(col), dh, cap, bucket_heights)
