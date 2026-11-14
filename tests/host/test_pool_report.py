"""doomfj.pool_report: every number it reads off a flipjump BlockPool, on pools small enough to work out by hand.

Two kinds of pool: one whose census is only LAID OUT (`pool_report.lay_out`, no assembly), for the block queries;
and one that ASSEMBLED the small program XOR, for what became of the tables and for the heat list.

NOT COVERED here: `ungrouped` above 0 (a table dispatched through no word the pool can name) and an ambiguous
heat-list group; XOR has neither.
"""
import flipjump as fj
from flipjump.assembler.inner_classes.table_pool import BlockPool, HotSite

from doomfj import pool_report

W = 32
OP_BITS = 2 * W                      # an fj op is two words
BASE = 1 << 26                       # above everything XOR reaches

XOR = """
stl.startup_and_init_all
    hex.set 4, a, 0x1234
    hex.set 4, b, 0x5678
    rep(24, i) hex.xor 4, a, b
    hex.print_uint 4, a, 1, 1
    stl.loop
a: hex.vec 4
b: hex.vec 4
"""
# XOR's tables are all 16 ops wide, one group per hex digit's jump word. `hex.set` zeroes a digit by xoring it
# with itself (one table through each of a's and b's 4 words), and each of the 24 `hex.xor 4, a, b` dispatches
# through b's 4 words: 1 table in each of a's groups, 1 + 24 in each of b's.
A_GROUPS = ["((a + %d) + 32)" % (64 * digit) for digit in range(4)]
B_GROUPS = ["((b + %d) + 32)" % (64 * digit) for digit in range(4)]
TABLES = 4 * 1 + 4 * 25
A_BLOCK_BITS = 1 * 16 * OP_BITS      # 1 table: 1 slot of 16 ops
B_BLOCK_BITS = 32 * 16 * OP_BITS     # 25 tables: 32 slots (the next power of two) of 16 ops


def _assembled(tmp_path, **pool_options):
    src = tmp_path / "xor.fj"
    src.write_text(XOR)
    pool = BlockPool(W, BASE, **pool_options)
    fj.assemble([src], tmp_path / "xor.fjm", memory_width=W, show_progress=False, table_pool=pool)
    return pool


def _laid_out():
    """g: three tables of 3-4 ops and one of 16; h: three tables of 8 ops; five of g's and all of `wide`'s tables are
    40 ops, wider than the 16-op slot limit"""
    pool = BlockPool(W, BASE, max_slot_ops=16)
    pool_report.lay_out(pool, {"g": {3: 2, 4: 1, 16: 1, 40: 5}, "h": {8: 3}, "wide": {40: 2}})
    return pool


# ---- the blocks (a census laid out, nothing assembled) ----

def test_a_block_is_its_sub_blocks_the_biggest_first():
    pool = _laid_out()
    # g: the one 16-op slot (1024 bits) first, then 4 slots of 4 ops (3 tables round up to 4) at bit 1024
    assert pool_report.sub_blocks(pool, "g") == {16: (0, 1), 4: (16 * OP_BITS, 4)}
    assert pool_report.block_bits(pool, "g") == (16 + 4 * 4) * OP_BITS == 2048
    assert pool_report.sub_blocks(pool, "h") == {8: (0, 4)}
    assert pool_report.block_bits(pool, "h") == 4 * 8 * OP_BITS == 2048
    # no table of `wide` fits a slot: an empty block
    assert pool_report.sub_blocks(pool, "wide") == {} and pool_report.block_bits(pool, "wide") == 0


def test_a_table_takes_the_slot_of_the_next_power_of_two_and_a_too_wide_one_takes_none():
    assert pool_report.slot_counts(_laid_out(), {3: 2, 4: 1, 16: 1, 40: 5}) == {4: 3, 16: 1}


def test_the_blocks_follow_each_other_from_the_pools_base():
    pool = _laid_out()
    bases = pool_report.bases(pool)
    assert (bases["g"], bases["h"]) == (BASE, BASE + 2048)
    assert pool_report.demand_bits(pool) == 2048 + 2048 + 0
    assert pool_report.extent_bits(pool) == 4096              # no hole between the two blocks
    assert pool_report.broken_groups(pool) == set()           # nothing was assembled, so no table missed a slot


# ---- the tables (XOR assembled) ----

def test_every_table_of_xor_moves_into_its_groups_block(tmp_path):
    pool = _assembled(tmp_path)
    assert pool_report.stats(pool) == {"moved": TABLES, "in_blocks": TABLES, "overflowed": 0, "declined": 0,
                                       "ungrouped": 0}
    assert set(pool_report.blocked_words(pool)) == set(A_GROUPS + B_GROUPS)
    assert pool_report.broken_groups(pool) == set()
    assert {pool_report.block_bits(pool, group) for group in A_GROUPS} == {A_BLOCK_BITS}
    assert {pool_report.block_bits(pool, group) for group in B_GROUPS} == {B_BLOCK_BITS}


def test_the_counts_blob_is_the_pools_census(tmp_path):
    pool = _assembled(tmp_path)
    blob = pool_report.counts_blob(pool)
    assert blob["counts"] == {**{group: 1 for group in A_GROUPS}, **{group: 25 for group in B_GROUPS}}
    assert blob["widths"] == {group: 16 for group in A_GROUPS + B_GROUPS}
    assert blob["width_hist"] == pool.merged_census() == {group: {16: count} for group, count in blob["counts"].items()}
    assert blob["alias"] == {}


def test_a_table_wider_than_any_slot_stays_inline_and_breaks_its_group(tmp_path):
    pool = _assembled(tmp_path, max_slot_ops=8)
    assert pool_report.stats(pool) == {"moved": 0, "in_blocks": 0, "overflowed": 0, "declined": TABLES,
                                       "ungrouped": 0}
    assert pool_report.broken_groups(pool) == set(A_GROUPS + B_GROUPS)
    assert pool_report.blocked_words(pool) == {}              # no word to pin: no group has a table in its block


def test_a_pool_too_short_for_every_block_overflows_the_groups_that_got_none(tmp_path):
    # room for four of b's blocks, but not for a's four small ones too: three of b's blocks are placed, and the
    # tables of the five other groups (25 + 4) go after them, in no block
    pool = _assembled(tmp_path, pool_end=BASE + 4 * B_BLOCK_BITS)
    stats = pool_report.stats(pool)
    assert stats == {"moved": TABLES, "in_blocks": 75, "overflowed": 29, "declined": 0, "ungrouped": 0}
    assert len(pool_report.bases(pool)) == 3
    assert pool_report.extent_bits(pool) == 3 * B_BLOCK_BITS
    assert pool_report.demand_bits(pool) == 4 * B_BLOCK_BITS + 4 * A_BLOCK_BITS   # placed or not


# ---- the heat list ----

def _b0_sites(pool):
    return [site for site in pool.table_sites if site.group == B_GROUPS[0]]


def test_the_heat_report_counts_what_the_list_matched(tmp_path):
    plain_sites = _b0_sites(_assembled(tmp_path))
    listed = [plain_sites[5], plain_sites[0]]                 # the hottest first
    heat = {B_GROUPS[0]: [HotSite(site.site, site.occurrence, 16) for site in listed]}
    pool = _assembled(tmp_path, heat=heat)

    assert list(pool_report.hot_groups(pool)) == [B_GROUPS[0]]
    assert sorted(pool_report.hot_groups(pool)[B_GROUPS[0]].values()) == [(16, 0), (16, 1)]   # (slot width, rank)
    assert pool_report.heat_report(pool) == {"hot_groups": 1, "hot_groups_missing": 0, "hot_groups_ambiguous": 0,
                                             "hot_sites_listed": 2, "hot_sites_matched": 2,
                                             "hot_sites_width_changed": 0}
    # the hot group's block is the pool's first, and the listed tables take its first slots, in the list's order
    base = pool_report.bases(pool)[B_GROUPS[0]]
    sites = _b0_sites(pool)
    assert base == BASE and [sites[5].address, sites[0].address] == [base, base + 16 * OP_BITS]


def test_the_heat_report_says_what_the_list_did_not_match(tmp_path):
    site = _b0_sites(_assembled(tmp_path))[5]
    good = [HotSite(site.site, site.occurrence, 16)]
    stale_group = pool_report.heat_report(_assembled(tmp_path, heat={B_GROUPS[0]: good, "no.such.group": good}))
    assert (stale_group["hot_groups"], stale_group["hot_groups_missing"]) == (1, 1)
    # a listed site whose table is 16 ops wide here, listed as 8
    wrong_width = pool_report.heat_report(_assembled(tmp_path, heat={B_GROUPS[0]: [HotSite(site.site, 0, 8)]}))
    assert (wrong_width["hot_sites_listed"], wrong_width["hot_sites_matched"],
            wrong_width["hot_sites_width_changed"]) == (1, 0, 1)
