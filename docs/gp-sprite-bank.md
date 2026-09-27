# M7 P1.6 -- the native-list sprite bank (design, before the build)

The handoff's rung P1.6 (`docs/handoff-gameplay.md` section 10; plan section 6.6; decision D6): **the
sprite bank stores each patch column ONCE per resolution tier, at native resolution, and a `rowmap`
scales it at draw time -- so the image holds every monster frame and rotation.** Class F: the scaling
rounds differently from today's per-bucket lists, so sprite pixels move (plan D6: "every sprite pixel
changes"). Kill criteria: `docs/gp-ledger.md`. The survey this starts from is
`scratchpad/gp/probes/bank/survey.md` (today's format, the oracle's rule, the v2 column's reads).

## 1. What it replaces, and why

Every downscaled patch column `u` carried **41 pre-scaled blocks** of 64 ops: 32 main blocks, one per
height bucket (buckets 12-31 full-res rows capped at 24 runs, 0-11 half-res at 12), and 9 coarse
blocks (buckets 0-8, half-res, cap 4) -- 5,248 words a column, **2,923,136 words** for E1M1's 32 kinds
and 557 columns, holding ONE patch per thing type (monsters: walk frame A, rotation 1). Every monster
frame in that format would take the image to 51.7% of 2^27 (plan 6.6).

## 2. The format (`doomfj.spritebank`, one generator for both mirrors)

**A list per (patch column, tier), in NORMALIZED rows.** For each column and each tier -- HD (the
patch's rows, cap 24), MID (every other row, cap 12), LD (every other row, cap 4) -- ONE run list,
built by `sprite_strip`'s rules at the patch's own scale (only the opaque extent; holes take the
texel above; equal neighbours merge; the first shortest run absorbed while over the cap), with every
row boundary NORMALIZED: `n = round(v * 255 / dh)`, 0..255 of the column's native height. A block:

    op 0  n_first        -- the first opaque row
    op 1  min_b          -- the column draws at bucket b iff b >= min_b (section 4)
    op 2  n_last         -- the end of the last run
    op 3.. (n_end, texel) x runs, then 0   (a real n_end is >= 1)

The v2 column's constraints hold as they are: 64-op blocks, a 16-bit index at nibble 3
(`frame.blk_addr` unchanged), the record's `[slot][list lo][list hi]` unchanged, the fields at fixed
offsets, texels RAW, and no list straddles a 4096-bit window because every list IS a window.

**Layout, tier-major.** A kind's HD lists sit in `dw` consecutive blocks, then its MID lists, then its
LD lists, so a column's block is `u + region` -- an ADD where the per-bucket bank multiplied `u` by 32
(or by the LD bucket count). The thing rows keep their schema: `sp_base` is the HD region, `sp_base2`
the LD region, MID is `sp_base + sp_dw`. After the kinds come the ANIMATION's regions (section 5).

## 3. The rowmap

`rowmap[b][n] = ceil(n * hb_b / 255)`: the screen row, below the sprite's bucket top, of normalized
boundary `n` at bucket `b` (today's 32 buckets and heights). ONE table for every patch, because the
rows are normalized: 32 x 256 = 8,192 entries, a D4 per-entry DISPATCH table
(`wall_renderer.sprite_rowmap_fj`, `rowmap.lookup dst, idx` with idx = b*256 + n) -- never a
`hex.pointers` read, which would arm another cluster and cost the next list read its narrow arm
(`docs/gp-sprite-column.md` 5.5).

- **the record** (`frame.thing_record_body`): the tier's region as the per-thing constant (HD when
  the bucket is at least `hdb`, the first bucket as tall as SPRITE_HD_H -- the parameter that was
  `buckets`; LD for a far short thing; MID otherwise), then per column `blk = u + region`, `min_b`
  read at op 1 (the full arm, where `last_rel` was), and the column taken iff bucket >= min_b. The
  bucket goes into the thing's slot (`gpslot` byte 3). The multiply and its `nld` parameter are gone
  (24 parameters: the heat list is re-keyed for it, `thing_record_body:25:24`).
- **the derive** (`stream.frag_derive`): the slot cache also fetches the bucket (`gps_b`); the
  fragment's rowmap index `ridx` = [row lo][row hi][bucket] (`gps_ridx` for A, `gpsb_ridx` for B,
  which is walked after A's derive); `n_first` (the block's first read, the full arm) and `n_last`
  (the narrow arm) each go through the rowmap; `ybase` is the BUCKET TOP; sy1 / sy2 clamp the first
  and last mapped rows.
- **each run** (`frag_runs`, `frag_runs_win`): `n_end` read straight into `ridx`'s low byte, the
  terminator tested, one `rowmap.lookup`, then the run's end is `ybase + row` as before. A run that
  maps to no row emits its end at the cursor, which the device accepts (it refuses only a run end
  behind the cursor, and mapped ends never go back).

## 4. What moves, and what does not

- **Moves** (MEASURED, `scratchpad/gp/probes/bank/compare.py`, `docs/ship-evidence/p16_compare.log`:
  every column, tier and bucket of E1M1's 32 kinds): **14.14%** of painted rows (181,406 of
  1,283,191), and **78** of 40,128 column-bucket pairs flip between drawn and not. The worst columns
  are heavily capped HD ones: the cap picks its "first shortest" run at native scale instead of on
  screen.
- **`min_b` is a DEFINITION** both mirrors share (`spritebank.min_bucket`): the first bucket from
  which the column draws at every taller one. Rounding makes a thin column's extent non-monotone in
  the height -- and today's own rule is non-monotone too (527 of 18,744 column-tiers on E1M1's
  sprites) -- so no single threshold reproduces either; this one makes the record's one compare exact.
- **Unchanged**: which things are drawn, where their feet stand, their bucket and height, their tier,
  their light, the slots, the ditto signature, the compositor.
- **The frozen combat set moves** (MEASURED, `docs/ship-evidence/p16_census_f4.log`): under this
  oracle the census's drawn population (F4) differs on 5 of the 11 runs, while every criterion still
  passes; under P1.5's oracle it reproduces 11/11. A picture rule is a BEHAVIOUR change
  (`docs/handoff-gameplay.md` section 1): P1.6 ships with a v3 of the set, planned on the frozen
  keys, B0 re-measured, frozen by the OWNER.
- **Both mirrors in one commit**: the oracle's column loop calls `strip_at(bank_list_of(...))`, the
  emitter bakes `sprite_tier_lists` -> the same `bank_list_of`.

## 5. All frames and rotations

`wall_renderer.anim_frames` walks gamedata's state chains from every entry state of the map's monster
types and of `ANIM_ACTORS` (the barrel, the imp's fireball, the puff, the blood); `anim_patches` reads
the views off the wad's own lump names (`TROOA2A8` is rotation 2 and, mirrored, 8; `...A0` every
rotation). E1M1: POSS, SPOS and TROO A-U, SARG A-N, BAR1 A-B, BEXP A-E, BAL1 A-E, PUFF A-D, BLUD A-C
-- **306 views, 237 distinct lumps** (69 views mirrored), each lump's three regions once;
`_lines_sprite_bank` returns `{(sprite, frame, rotation): (region, dw, mirrored)}`. Nothing draws them
before P3 (moving monsters); `tests/host/test_sprite_bank.py` decodes every one from the emitted text.

## 6. Budget

- **Size (MEASURED at emit)**: 16,635 blocks = 2,129,280 words, against 22,837 blocks = 2,923,136
  words today -- **-793,856 words** (-0.59% of 2^27) while holding every frame and rotation.
- **Ops (ESTIMATE)**: +2 rowmap lookups a sprite column and +1 a run (a D4 dispatch, ~60-80 ops)
  against the record's multiply saved per column -- on combat set v2, +0.05 .. +0.15M ops/frame.
- **Freeze**: a v3 of the combat set (section 4).
