# Pin protection for the blocking pass (design; phase 0, S8, 2026-09-26)

This is a design only. No flipjump code is edited in phase 0. The change goes on a branch off
flipjump-151 `1.5.1` and is PR'd into `1.5.1`. Plan `docs/plan-gameplay.md` section 13.1 asks for it.

## 1. What BlockPool does today (flipjump-151 at `73e09c0`)

**Tables and groups.** `flipjump/assembler/preprocessor.py`, `relocatable_table_end`, finds a
dispatch table: a `pad`, then plain `a;b` entries, disarmed by `wflip src+w, switch`. In
`resolve_macro_aux` (the `Pad` branch), the table's **group** becomes the source word's expression,
`str(src + w)`. `PreprocessorData.begin_relocation` asks `TablePool.wants`, which applies
`build_blocked.py`'s `SAFE_TABLE_MACROS`, and skips the runtime's words (below `RESERVED_BELOW`).

**Two passes.**
- The counting pass, `BlockPool(counts=None)`, uses `reserve` to count tables, widths and
  width histograms per group. Doom freezes the result in `scratchpad/12m/_counts_game.json.gz`.
- The placing pass runs `BlockPool._preallocate`:
  - Each block is sized by `_block_bits`: a power of two, via `_uniform_shape` or `_bucket_layout`.
    `spread` multiplies the slots of big groups.
  - Blocks are placed **biggest first** from `pool_base`, each aligned to its own size.
  - A block that does not fit under `pool_base + span_bits` joins `broken_groups`.
- `reserve` then gives each table the next of its group's `_cheap_indices`, in **encounter order**.
- `_decline` breaks a group on `too_wide` or `overflow`.

**Pinning.**
- `BlockPool.pinned_words` goes to `assembler.resolve_pinned`, which drops aliased expressions,
  runtime words and the caller's `pin_exclude` (for doom, `build_blocked.py`'s `_reset_owned`).
- `BinaryData.insert_fj_op` bakes the base into the variable.
- `BinaryData.insert_wflip_ops` rebases every address-sized writer: `flip ^= base` above `pinned_floor`.
- So a dispatch through a pinned word costs `2 x popcount(offset in block)`: arm plus disarm.

## 2. What goes wrong (MEASURED with `scratchpad/12m/pinreport.py` and `profx/hotwords.py`)

**The hot list.** The 20 hottest shared words of blocked27 carry 534,540 table ops/frame; the pool
as a whole runs 1,733,624/frame. `hex.tables.res + 32` alone takes 139,824 dispatches/frame into
81,461 tables. (`python profx/hotwords.py games`, 1,000 gamespeed frames.)

**What the pin report finds on three binaries:**

| binary | hot words pinned | notes |
|---|---|---|
| blocked27 | 20/20, bases as profiled | build log: 27,030 groups placed, 52.9% of the pool, 2 broken but pinned by `--pin-broken` |
| blocked25 | 20/20 | 5 bases moved: the small groups (`thing_pass hp`, `tsf_sfslot_p`, a `seg_pass2` stream cell) |
| b26 | 2/20 (18 LOST) | built without `--pin-broken` / `--width-buckets`: 10,052 too-wide declines broke 1,333 groups |

For b26, the pin report's ESTIMATE of what the lost pins cost is ~843K ops/frame.

**The two mechanisms that re-roll.**
- (a) **Whole groups.**
  - A group is lost when the pool runs out, since biggest-first drops the *smallest* blocks last in line.
  - It is also lost when a knob changes, or on a decline without `--pin-broken`.
  - Hot groups can be small: the three `thing_pass hp` groups have 14 tables each.
- (b) **Indices inside a pinned group.** Indices follow encounter order. The main part's collision
  code, 1.5M words of it, is reached before the render leaves, so it takes the cheapest indices of
  the shared words. A label census of `hex.tables.res`'s block measures this: collision's tables
  sit at a mean offset popcount of 5.7, the seg/thing leaves' at 6.9. Any table added upstream
  shifts every later index.

**The cost of (b), as an ESTIMATE.** `profx/heatindex.py` is arithmetic on the measured profile.
- The top 20 groups pay ~2.54M ops/frame in arm/disarm today.
- Giving their hottest tables the cheapest offsets would cut that to ~1.27M.
- `hex.tables.res`'s mean flip falls from 6.3 to 3.0 bits.
- So protection is also a reclaim of order 1M ops/frame. This is unverified until a build measures it.

## 3. The change

**1. `BlockPool(..., heat=...)`.** `heat` is an ordered list of hot groups. For each group it holds:
- a normalized key: `fN:lNNN:` / `sN:lNNN:` coordinates are stripped, so a line move keeps the match,
  and a collision is reported;
- the group's reserved block size;
- its hot table sites, as labels prefixes normalized the same way, hottest first.

`reserve()` gains `labels_prefix`, which `begin_relocation` already has.

**2. `_preallocate` places hot groups FIRST, from `pool_base`, in heat order.**
- Each gets the block its counts imply, and at least the reserved size.
- Everything else follows biggest first, as today.
- New groups can no longer move or evict a hot block.
- A hot group that does not fit **raises**; it never breaks silently.
- A hot group that outgrows its power of two is logged as a re-roll.

**3. Heat-ordered indices.** In a hot group, the k-th hot site gets the k-th cheapest index, reserved
up front. All other tables take the remaining indices in encounter order.

**4. Hot groups always pin.** An overflow in a hot group declines inline and keeps the pin, which is
`pin_broken` per group. A caller's `pin_exclude` veto of a hot word is counted and printed.

**5. `heat=None` is byte-identical to today.**

**How the list reaches the assembler.** `profx/hotwords.py` writes `hotwords_<ref>.json`; the per-site
list is a small extension. `build_blocked.py --pin-heat <file>` passes it to the placing pools and
`_preflight`. The counting pass, the counts cache and its signature are unchanged. The build prints
the heat file's sha256 and a line per hot group.

**Gate.** `pinreport.py` on the new binary must exit 0 (every hot word pinned). This joins
`docs/ship-gate.md` step 1.

## 4. How to test

**flipjump unit tests** (synthetic counts, no doom):
- the hot block lands at `pool_base` and keeps its base when N bigger groups are added;
- in a pool too small for everything, the hot group keeps its block and pin while `heat=None`
  loses it (the negative control);
- hot sites get the cheapest indices whatever the encounter order;
- an overflow keeps the pin;
- `heat=None` produces sha256-identical `.fjm` files (`scratchpad/12m/tablepool_gate.py`).

**Doom:**
1. Rebuild blocked27 with `--pin-heat`, then run `m2_std_gate` and `m3_gate`.
2. `pinreport` must show 20/20 at the reserved bases.
3. `msframe --against shipped` must not be SLOWER; then `gamespeed`.
4. Plan 13.1's placement-tax build (new tables emitted, none called) must show 0 lost and 0 moved in
   `pinreport`. Its gamespeed delta is the tax that remains.

**The first measurement to take** is the (b) estimate above: a heat-ordered rebuild against blocked27.
