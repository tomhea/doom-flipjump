"""M7 P1.6 -- `doomfj.spritebank`, the native-list sprite bank's ONE generator (docs/gp-sprite-bank.md).

The bank stores a column once per tier at its native scale, with row boundaries NORMALIZED to 0..255,
and `rowmap` draws it at a height bucket. These pin the arithmetic both mirrors share: the list is
`sprite_strip`'s run rules at native scale, the rowmap is ceil(n * hb / 255), a column draws iff its
bucket is at least its `min_b` (a DEFINITION, because rounding makes a thin column's extent
non-monotone in the height), and a drawn strip is never empty.
"""
import random

import pytest

from doomfj.config import Config
from doomfj.reference_model import (ReferenceModel, SPRITE_HEIGHT_BUCKETS, sprite_bucket_height)
from doomfj.spritebank import (NORM, bank_list, bank_list_of, min_bucket, native_list, norm_row,
                               rowmap_row, rowmap_table, strip_at, strip_from_list)

H = Config().VIEW_H
HEIGHTS = tuple(sprite_bucket_height(b, H) for b in range(SPRITE_HEIGHT_BUCKETS))


def _col(rng, dh, p_hole=0.2, colours=6):
    """a random column: transparent margins, opaque interior with holes, a few colours"""
    top, bot = rng.randrange(0, dh // 3 + 1), rng.randrange(0, dh // 3 + 1)
    out = []
    for v in range(dh):
        if v < top or v >= dh - bot or rng.random() < p_hole:
            out.append(-1)
        else:
            out.append(rng.randrange(colours))
    return out


def _paint(st):
    if st is None:
        return {}
    r0, runs = st
    out, prev = {}, 0
    for e, t in runs:
        for r in range(prev, e):
            out[r0 + r] = t
        prev = e
    return out


def test_normalization_spans_0_to_255_and_is_strictly_increasing():
    for dh in (1, 7, 32, 55, 128, 255):
        ns = [norm_row(v, dh) for v in range(dh + 1)]
        assert ns[0] == 0 and ns[-1] == NORM
        assert all(a < b for a, b in zip(ns, ns[1:])), dh
    with pytest.raises(AssertionError):
        norm_row(0, 256)                             # a byte cannot hold a taller column


def _rowmap_faults(fn):
    """every (n, hb) where `fn` is not ceil(n * hb / 255) -- the independent statement of the rule"""
    return [(n, hb) for hb in range(1, H + 1) for n in range(NORM + 1)
            if fn(n, hb) != -(-n * hb // NORM)]


def _identity_faults(nl_fn, trials=300, seed=1):
    """columns where `nl_fn`'s list, drawn at identity scale, paints differently from sprite_strip"""
    rng = random.Random(seed)
    out = []
    for _ in range(trials):
        col = _col(rng, NORM)
        cap = rng.choice((4, 12, 24))
        if _paint(ReferenceModel.sprite_strip(col, NORM, NORM, cap=cap)) != _paint(
                strip_from_list(nl_fn(col, NORM, cap), NORM)):
            out.append((cap, col))
    return out


def test_the_rowmap_is_ceil_and_its_table_is_32_by_256():
    assert _rowmap_faults(rowmap_row) == []
    t = rowmap_table(HEIGHTS)
    assert len(t) == SPRITE_HEIGHT_BUCKETS and all(len(r) == NORM + 1 for r in t)
    assert all(r[-1] == hb for r, hb in zip(t, HEIGHTS))
    assert all(all(a <= b for a, b in zip(r, r[1:])) for r in t)


def test_at_identity_scale_the_native_list_draws_what_sprite_strip_draws():
    """dh == 255 makes normalization the identity, and hb == dh makes the rowmap one: then the list
    drawn at that height is `sprite_strip`'s own column, pixel for pixel -- the run rules are the
    same rules, applied once"""
    assert _identity_faults(native_list) == []


def test_min_b_is_the_rule_and_a_drawn_strip_is_never_empty():
    rng = random.Random(2)
    nonmonotone = 0
    for _ in range(2000):
        dh = rng.choice((7, 16, 33, 55, 62, 110))
        col = _col(rng, dh, p_hole=0.6)
        bl = bank_list(col, dh, rng.choice((4, 12, 24)), HEIGHTS)
        if bl is None:
            assert all(v < 0 for v in col)
            continue
        lst = (bl[0], bl[2], bl[3])
        raw = [strip_from_list(lst, hb) is not None for hb in HEIGHTS]
        nonmonotone += any(raw[b] and not all(raw[b:]) for b in range(len(raw)))
        for b, hb in enumerate(HEIGHTS):
            st = strip_at(bl, b, hb)
            assert (st is not None) == (b >= bl[1]), (b, bl[1])
            if st is not None:
                assert st[1] and all(a[0] < b_[0] for a, b_ in zip(st[1], st[1][1:]))
        assert bl[1] == min_bucket(lst, HEIGHTS)
    # the rule is not vacuous: rounding really does make some thin columns non-monotone
    assert nonmonotone > 0


def test_a_transparent_column_has_no_list_and_never_draws():
    assert native_list([-1] * 9, 9, 12) is None
    assert bank_list([-1] * 9, 9, 12, HEIGHTS) is None
    assert strip_at(None, 31, HEIGHTS[31]) is None


def test_the_cap_binds_at_native_scale_first_shortest_first():
    """sprite_strip's reduction, at native scale: the FIRST shortest run goes -- into the run above
    it, or, being the first run, into the one below -- and equal neighbours are not re-merged"""
    col = [1, 2, 1, 2, 1, 2, 1, 2]                 # eight 1-row runs
    n_first, n_last, pairs = native_list(col, 8, 4)
    assert len(pairs) == 4 and n_first == 0 and n_last == NORM
    # run 0 (no run above) goes into run 1 (colour 2, now 2 rows); then the first 1-row run is
    # always index 1, absorbed upward into the colour-2 run: 2, 2, 1, 2
    assert [t for _, t in pairs] == [2, 2, 1, 2]
    assert [e for e, _ in pairs] == [norm_row(v, 8) for v in (5, 6, 7, 8)]


def test_bank_list_of_is_the_same_answer_memoized():
    rng = random.Random(3)
    col = _col(rng, 55)
    assert bank_list_of(tuple(col), 55, 12, HEIGHTS) == bank_list(col, 55, 12, HEIGHTS)
    assert bank_list_of(tuple(col), 55, 12, HEIGHTS) is bank_list_of(tuple(col), 55, 12, HEIGHTS)


def test_a_mutated_rowmap_or_list_is_caught():
    """R9: the two equivalence checks above must reject a rowmap that floors instead of ceiling, and
    a list whose cap absorbs the shortest run DOWNWARD instead of into the run above"""
    assert _rowmap_faults(lambda n, hb: (n * hb) // NORM)

    def absorb_down(col, dh, cap):
        idx = [v for v, t in enumerate(col) if t >= 0]
        if not idx:
            return None
        v0, v1 = idx[0], idx[-1]
        runs, last = [], col[v0]
        for v in range(v0, v1 + 1):
            if col[v] >= 0:
                last = col[v]
            if runs and runs[-1][1] == last:
                runs[-1][0] = v + 1
            else:
                runs.append([v + 1, last])
        while len(runs) > cap:
            starts = [v0] + [r[0] for r in runs[:-1]]
            lens = [r[0] - s_ for r, s_ in zip(runs, starts)]
            i = lens.index(min(lens))
            if i + 1 < len(runs):
                runs.pop(i)                          # the run BELOW takes its rows
            else:
                runs[i - 1][0] = runs[i][0]
                runs.pop(i)
        return norm_row(v0, dh), norm_row(v1 + 1, dh), [(norm_row(e, dh), t) for e, t in runs]
    assert _identity_faults(absorb_down)
