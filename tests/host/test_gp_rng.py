"""S3a: DOOM's rndtable and the RNG interface (`doomfj.rng`).

The table was fetched twice from two independent sources (Chocolate Doom and id's linuxdoom-1.10)
and diffed; these tests pin what was accepted and prove each check can fail (R9)."""
from doomfj import rng as R


def test_the_table_is_dooms_by_checksum():
    assert R.verify_rndtable() == []
    assert len(R.RNDTABLE) == R.TABLE_SIZE == 256
    assert R.RNDTABLE[:8] == (0, 8, 109, 220, 222, 241, 149, 107)     # m_random.c, first values
    assert R.RNDTABLE[-4:] == (120, 163, 236, 249)                     # ... and last
    assert R.table_sha256(R.RNDTABLE) == R.RNDTABLE_SHA256


def test_the_checksum_rejects_any_single_change():
    """R9: one value off, a short table, or two values swapped (same sum!) must all fail."""
    for i in (0, 1, 83, 128, 255):
        bad = list(R.RNDTABLE)
        bad[i] = (bad[i] + 1) % 256
        assert R.verify_rndtable(bad), "a change at %d went unnoticed" % i
    assert R.verify_rndtable(R.RNDTABLE[:-1])
    swapped = list(R.RNDTABLE)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    assert sum(swapped) == R.RNDTABLE_SUM and R.verify_rndtable(swapped)


def test_p_random_pre_increments_like_doom():
    assert R.p_random(0) == (8, 1)            # P_Random from a cleared index returns rndtable[1]
    assert R.p_random(255) == (0, 0)          # and wraps at 256
    s, seq = 0, []
    for _ in range(256):
        v, s = R.p_random(s)
        seq.append(v)
    assert s == 0 and seq == list(R.RNDTABLE[1:]) + [R.RNDTABLE[0]]


def test_p_subrandom_is_first_minus_second():
    for s in range(256):
        a, s1 = R.p_random(s)
        b, s2 = R.p_random(s1)
        assert R.p_subrandom(s) == (a - b, s2)


def test_outcome_tables_compose_with_the_post_increment_state():
    """D10's emit-time fold: one increment plus one table read equals P_Random then f, at every
    state -- here with A_PosAttack's damage, ((P_Random() % 5) + 1) * 3."""
    f = lambda v: ((v % 5) + 1) * 3        # noqa: E731
    t = R.outcome_table(f)
    assert len(t) == 256
    for s in range(256):
        v, n = R.p_random(s)
        assert R.p_random_outcome(s, t) == (f(v), n)


def test_indexing_an_outcome_table_by_the_pre_increment_state_is_wrong():
    """The negative control for the composition: reading slot `state` instead of `state + 1`
    disagrees with P_Random somewhere, so the test above can fail."""
    t = R.outcome_table(lambda v: v)
    assert any(t[s] != R.p_random(s)[0] for s in range(256))


def test_stream_seeds_are_distinct_and_stream_zero_starts_like_doom():
    seeds = [R.stream_seed(k) for k in range(256)]
    assert len(set(seeds)) == 256
    assert R.stream_seed(R.STREAM_WORLD) == 0
    assert all(0 <= s <= R.STATE_MASK for s in seeds)
