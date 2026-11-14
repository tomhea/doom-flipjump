"""What a flipjump BlockPool did, read off what it keeps.

flipjump's pool (flipjump/assembler/inner_classes/table_pool.py) keeps its census (`census`, `alias`), each group's
block (`blocks`), every table's site and address (`table_sites`), the final pin map (`pinned`) and what it left as it
was (`kept_inline`, `unpins`, `heat_unmatched`). It has no counters and no layout queries of its own. The blocked
build's driver, the gates and the pool tools (scratchpad/12m) read every number they print from here, so one module
follows the pool's fields.

`lay_out` sizes and places the blocks of a census with no assembly (the pool's `lay_out_blocks`, what its
`place_deferred` does once the expansion is done). That is how the tools re-derive a build's layout from its
counts cache.
"""
from flipjump.assembler.inner_classes.table_pool import KEPT_NO_JUMP_WORD, heat_key


# ---- the census ----

def counts_blob(pool):
    """the counts cache's four fields (build_blocked.py --counts-cache), from the pool's census"""
    hist = pool.merged_census()
    return {"counts": {group: sum(widths.values()) for group, widths in hist.items()},
            "widths": {group: max(widths) for group, widths in hist.items()},
            "width_hist": hist,
            "alias": dict(pool.alias)}


# ---- the blocks ----

def lay_out(pool, width_hist):
    """Give every group of `width_hist` (a counts cache's: {group: {table width in ops: how many}}) its block, as an
    assembly of that census does. Nothing is assembled; the pool then answers the block queries below."""
    pool.lay_out_blocks({group: dict(hist) for group, hist in width_hist.items()})


def bases(pool):
    """{group: its block's base}, for the groups that got a block, in layout order"""
    return {group: block.base for group, block in pool.blocks.items() if block.base is not None}


def block_bits(pool, group):
    """the size of the group's block, in bits (placed or not)"""
    return pool.blocks[group].bits


def demand_bits(pool):
    """the bits every group's block takes, placed or not"""
    return sum(block.bits for block in pool.blocks.values())


def extent_bits(pool):
    """the bits from the pool's base to the end of its last placed block"""
    ends = [block.base + block.bits for block in pool.blocks.values() if block.base is not None]
    return max(ends, default=pool.pool_base) - pool.pool_base


def sub_blocks(pool, group):
    """{slot width in ops: (the sub-block's bit offset in the block, its slots)} of the group's block"""
    return dict(pool.blocks[group].sub_blocks)


def slot_counts(pool, widths):
    """{slot width in ops: tables}, for one group's {table width in ops: how many}: the slot each table takes"""
    counts = {}
    for width, count in widths.items():
        if width > pool.max_slot_ops:
            continue                          # too wide to move: it takes no slot
        slot_ops = pool.slot_ops(width)
        counts[slot_ops] = counts.get(slot_ops, 0) + count
    return counts


def broken_groups(pool):
    """the groups with a table that got no slot in their block (a broken group's word is normally left unpinned)"""
    return {group for group, block in pool.blocks.items() if block.broken}


def blocked_words(pool):
    """{group: its jump word's Expr}, for the groups with a table in their block (the words the pool asks to pin)"""
    return {group: pool.census[group].word for group, block in pool.blocks.items()
            if block.base is not None and block.taken}


# ---- the tables ----

def stats(pool):
    """What became of the tables the pool met:
      moved       left the program's code (in_blocks + overflowed)
      in_blocks   took a slot of their group's block
      overflowed  placed in no block: their group got none, or the program's words cannot be pinned at all
      declined    too wide for any slot, in a group that has a block: stayed inline (and broke the group)
      ungrouped   dispatched through no word the pool can name: stayed inline
    """
    placed = bases(pool)
    moved = sum(1 for site in pool.table_sites if site.address)
    in_blocks = sum(sum(block.taken.values()) for block in pool.blocks.values())
    return {"moved": moved,
            "in_blocks": in_blocks,
            "overflowed": moved - in_blocks,
            "declined": sum(1 for site in pool.table_sites if not site.address and site.group in placed),
            "ungrouped": pool.kept_inline.get(KEPT_NO_JUMP_WORD, 0)}


# ---- the heat list ----

def hot_groups(pool):
    """{group: {(site, occurrence): (slot width, rank)}}: the heat list's groups this program has, in the list's
    order"""
    return {group: block.hot.ranks for group, block in pool.blocks.items() if block.hot is not None}


def heat_report(pool):
    """what the heat list found in this program. A listed group is missing if the program has none of its key, and
    ambiguous if it has several; a listed site is matched if its table still has the listed width."""
    hot = hot_groups(pool)
    group_keys = {heat_key(group) for group in pool.blocks}
    matched = width_changed = 0
    for site in pool.table_sites:
        listed = hot[site.group].get((site.site, site.occurrence)) if site.address and site.group in hot else None
        if listed is not None:
            matched += listed[0] == site.slot_ops
            width_changed += listed[0] != site.slot_ops
    return {"hot_groups": len(hot),
            "hot_groups_missing": sum(key not in group_keys for key in pool.heat_unmatched),
            "hot_groups_ambiguous": sum(key in group_keys for key in pool.heat_unmatched),
            "hot_sites_listed": sum(len(ranks) for ranks in hot.values()),
            "hot_sites_matched": matched,
            "hot_sites_width_changed": width_changed}
