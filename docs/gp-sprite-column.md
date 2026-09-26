# The cheaper sprite column: prototype and design

**Status: PHASE 0 PROTOTYPE (stream S6, plan-gameplay section 14 #1). No tracked file was changed.**
The prototype is a set of standalone fj programs in `scratchpad/gp/probes/sprite/`. Nothing here
builds the renderer or runs the game. Every number is MEASURED with the command given, or
UNVERIFIED.

---

## 0. The answer

- **The proposal changes no pixel.** It was run on 1,648 sprite columns from 16 oracle fight
  frames. The proposed column equals today's on every one, and today's equals the plain column
  with the oracle's fragment pasted in. Both negative controls fail as they must (section 4.4).
- **End to end, v2 cuts a sprite column by ~40%** (39-43% on three frames), and v1 by 16-36%.
  "End to end" is record + load + the sprite's share of the emission, standalone (section 4.1).
  Against the small-shift layout noise, the end-to-end delta is ~25x and the emission delta
  5-8x (section 4.5).

  | frame | TODAY | v1 | v2 |
  |---|---|---|---|
  | heavy:gate664 | 70,796 | 48,313 (-31.8%) | 41,320 (-41.6%) |
  | heavy:h100 | 74,584 | 62,654 (-16.0%) | 45,370 (-39.2%) |
  | melee:h57 | 91,644 | 58,246 (-36.4%) | 52,083 (-43.2%) |

- **The emission alone drops only 18% (v2).** `stream.emit_col_lines`' sprite path goes
  from 61,262 to 50,097 ops per column (section 4.2).
  - v1 alone moves work out of the record and into the emission. Its emission-only price is
    therefore within a few percent of today's: -6% overall, from +8% to -20% by frame.
  - About 60% of a sprite column's emission is the ceiling, wall and floor around the sprite.
    That part costs what a plain column costs, and none of the listed items touch it.
- **The plan's target, <= 15K per column on blocked27, cannot be met from the sprite side.** A
  plain column is 15.9K, and a sprite column still emits its ceiling and floor. Restated as the
  sprite's own cost (record + load + runs + split), v2 removes ~40% of it: short of -50%.
  - Divided by the median standalone/blocked27 factor, v2's end-to-end saving is
    ~19.3K ops per sprite column on blocked27. A 103-column fight frame (the mean of the
    16 frames) would save ~1.98M ops (UNVERIFIED, section 6).
  - The plan's ~30K per column is the emission alone. The record and load come on top of it
    (section 6). The fight line of plan section 7, a phase-0 output, should be priced on the
    end-to-end number.
- **Recommendation: build v2 in P1 as one rung, and gate it through `docs/ship-gate.md`.** The
  pixel gates come first, then `msframe`. This rung changes table sizes, so it re-rolls the
  blocking pass's pins (plan 13 #1). Its real price is known only after that build.

## 1. What was compared, and how faithfully

**The programs.** Each probe assembles `fj_consts` + the seven `src/fj` files + one generated main.
So the macros under test are the REAL ones:
- `stream.emit_col_lines`, `emit_region`, `sprite_runs`, `steps_splice_c/f` and `steps_face`;
- `half_walk_code` over the frame's own bands-as-code lists (`wall_renderer._band_pair_lists`);
- the W1R walker (`generate_w1r_walls_fj`) and the `byte`/`cm` emit tables;
- `frame.lines_spr_load`, `lines_spr_seed` and `step_shade`.

Two parts of today's code are **transplanted from the source text at run time**, so they cannot
drift from it:
- `frame.thing_record_body`'s per-column loop (`col_loop:` .. `set_tstop:`);
- the ditto ladder's sprite rungs.

**The cases** come from `cases.py`. The oracle (`ReferenceModel.render_wall_frame`, shipped
feature set) is run on:
- three scenarios: `static` (spawn positions); `heavy` and `melee` (runtime monsters moved in
  front of the camera through the oracle's `thing_positions`);
- eight viewpoints: the deg_gate sprite frames `gate664` and `gate1869`, and six atlas points.

Every column holding a slot-A fragment becomes a case. A case records:
- the clip rows, the ceiling/floor keys and the V5 pieces;
- the W1R inputs;
- the fragment, exactly as the oracle stores it: `y_base`, runs, light row.

The fight frames hold 1,648 sprite columns (103 per frame), at 12.6 runs per column.

**What is NOT like blocked27:**
1. **No blocking pass.** Addresses are wherever the standalone layout puts them, and an fj op's
   cost follows the popcount of the addresses it flips. Standalone prices run
   1.7-2.0x blocked27's:
   - plain column 26,847 vs 15.9K (x1.69);
   - today's sprite-column emission 61,262 vs 30.2K (x2.03);
   - `hex.ptr_index` 1,403 vs 846; `read_byte` 445 vs 260 (`t4_prims.py`; plan section 3).
2. **Slot A only.** The A+B path (`sprfl = 2`, a second fragment behind the first) was not
   prototyped.
3. **The bank holds only the frame's blocks**, in the shipped block format.
4. **Harness costs are removed by measurement.** `BASE` and `HARN` runs price the per-case
   register setup, which is then subtracted.
   - Emission prices are slopes: 2 passes minus 1.
   - Record and load prices are slopes over K columns: K = 10 minus K = 2.
   - The end-to-end price is one pass minus the `HARN` program.
   - Every run must end in the program's own `stl.loop`. A run that crashed ends early, and
     would read as a saving (`plib.assemble_run` asserts this).

## 2. Where a sprite column's ops go today (MEASURED standalone, heavy:gate664)

| part | where | ops | command |
|---|---|---|---|
| record, per recorded column | `thing_record_body` col_loop | 19,743 (low addresses) | `python t5_recload.py` |
| load, per sprite column | `lines_spr_load` | 5,110 | `python t5_recload.py` |
| ditto ladder, sprite rungs | `seg_pass2_leaf_body_lines` | 134 .. 1,279 per column reaching it, + 770 in shadow saves per emitted column | `python t6_ladder.py` |
| emission: the regions around the sprite | 2 x `emit_region` | 30,340 | `python t3_breakdown.py` |
| emission: the runs | `sprite_runs` | 22,218 (13.1 runs/col) | same |
| the same column with no sprite | `emit_col_lines`, plain path | 25,096 | `python t2_emit.py` |

(All commands run from `scratchpad/gp/probes/sprite/`.)

Two things in this table decide the design:
- **The record half is as heavy as the runs.** It writes 7 bytes per column. Five of them come
  from two per-THING constants (the top row `trb_y0` and the light row) plus the block header,
  which the emitter reads anyway:
  - `y_base = trb_y0 + r0` (2 bytes);
  - `sy1` / `sy2`, its clamps (2 bytes);
  - the light row (1 byte).

  To compute them per column, it pays a header read, two `clamp_row`s and 8-nibble adds.
- **The regions cost more than the plain column** (30.3K against 25.1K). They are the same
  ceiling/floor/wall walks, cut in two windows. Nothing sprite-specific can take them below a
  plain column.

## 3. The proposal, item by item (plan section 14 #1)

| plan item | prototype | status |
|---|---|---|
| a 3-byte fragment record; per-thing constants written once per thing | `gpspr.rec_thing` + `rec_cols` + `load` + the (slot, blk) ladder | built, measured, pixel-identical |
| one region walk instead of two | window-first `steps_face` / `steps_splice_c/f` / `emit_region`: each list is walked once, and a face or region outside its window costs one compare | built, measured, pixel-identical |
| skip the wall split when the sprite covers the whole open window | the covered path: ceiling splice to `sy1`, runs, floor splice from `sy2` | built, pixel-identical; applies to only 6% of fight columns (100/1,648) |
| run-lists precomputed per scale bucket, "one lookup" per run | the bank already IS per bucket. v2 makes each run cheaper instead: fast unclipped path (65% of columns), narrow 3-nibble reads inside a 4096-bit block, a nibble-placed block address, 2-nibble row math | v2 built, measured, pixel-identical. "One read per run" is impossible (rel and texel are two bytes); a code-per-run bank is section 7's open lever |
| `DEG_HD_BUDGET` 2 | not prototyped: it changes pixels (owner call) | upper bound from the cases: 3.4 runs/column above cap 12, ~3K/column standalone |

**v1** is the first three rows. **v2** is v1 plus the addressing row. Both live in
`scratchpad/gp/probes/sprite/gp_sprite_col.fj` (`ns gpspr`).

**How the record splits.** The renderer already stores a fragment as two parts. The thing's
bucket top `trb_y0` is per thing, and the block header's `r0` is per column (`y_base = trb_y0 + r0`).
The oracle does the same (`ytop_b + st[0]`). The proposal stores that split and nothing else:
- **per thing, in its slot** `gpslot[s]`: `[y0 + 32768 lo][hi][light row][0]`;
- **per column, in `spslot[x]`**: `[s][blk lo][blk hi]`.

The emitter re-reads `r0` and `last_rel` from the block, which it reads anyway.
- The slot is fetched once per THING. `gps_cur_s` caches it, and a thing's columns are adjacent.
- The ditto ladder compares (slot, blk). Equal slot and block imply an equal fragment, so it is
  never looser than today's four fields.

## 4. Results

### 4.1 End to end: record -> load -> emit, per sprite column (`t8_pipeline.py`)

Each variant is one fj program:
- pass 1 records every column of the frame;
- pass 2 seeds, loads and emits each column.

Price = (variant - HARN) / columns. HARN is the same program with the record, load and sprite
removed. The ditto ladder is not included (4.3).

| frame | cols | TODAY | v1 | v2 | pixel checks |
|---|---|---|---|---|---|
| heavy:gate664 | 106 | 70,796 | 48,313 (-31.8%) | 41,320 (-41.6%) | 106/106/106 of 106 equal |
| heavy:h100 | 126 | 74,584 | 62,654 (-16.0%) | 45,370 (-39.2%) | 126/126/126 of 126 equal |
| melee:h57 | 89 | 91,644 | 58,246 (-36.4%) | 52,083 (-43.2%) | 89/89/89 of 89 equal |

Command: `python t8_pipeline.py heavy:gate664` (and `melee:h57`, `heavy:h100`).

Its output line reads `TODAY pipeline == plain + oracle fragment on N; PROP ... on N; PROP2 ...
on N`.

**How much layout alone moves these numbers.** The transplanted record loop carries the
renderer's unreachable layout freeze (`rep(703) stl.fj 0, 0`). The renderer has one copy of it.
This harness expands the record once per case, so the table above strips it: it would otherwise
be ~100 dead copies shifting every later address in TODAY's program only. Left in
(`--keepfill`), TODAY reads: heavy:gate664 TODAY 63,727 (-10.0%); heavy:h100 TODAY 77,559 (+4.0%); melee:h57 TODAY 87,831 (-4.2%). v1 and v2 carry no such filler and are unchanged.

That spread is the scale of the placement noise any real build will show (risk 1).

### 4.2 Emission only, all 16 fight frames (`t2_emit.py`)

The register state is set per case, and `emit_col_lines` (or the proposed `emit_col`) runs alone.

| frame | cols | runs/col | PLAIN | TODAY | v1 | v2 |
|---|---|---|---|---|---|---|
| heavy:gate664 | 106 | 13.1 | 25,096 | 50,793 | 52,319 (+3%) | 45,685 (-10%) |
| heavy:gate1869 | 90 | 14.7 | 17,635 | 54,134 | 56,123 (+4%) | 44,458 (-18%) |
| heavy:h57 | 73 | 7.2 | 29,278 | 64,197 | 51,623 (-20%) | 48,797 (-24%) |
| heavy:h71 | 111 | 8.6 | 28,857 | 57,808 | 61,459 (+6%) | 52,037 (-10%) |
| heavy:h100 | 126 | 18.8 | 26,253 | 59,223 | 58,901 (-1%) | 50,748 (-14%) |
| heavy:h28 | 83 | 8.4 | 24,217 | 64,955 | 55,642 (-14%) | 46,946 (-28%) |
| heavy:h42 | 83 | 6.5 | 31,332 | 70,427 | 57,974 (-18%) | 50,930 (-28%) |
| heavy:h85 | 74 | 7.5 | 29,450 | 65,808 | 52,973 (-20%) | 47,849 (-27%) |
| melee:gate664 | 122 | 14.8 | 23,375 | 52,844 | 49,268 (-7%) | 43,623 (-17%) |
| melee:gate1869 | 103 | 15.5 | 18,714 | 57,375 | 61,900 (+8%) | 51,088 (-11%) |
| melee:h57 | 89 | 13.4 | 29,453 | 66,620 | 67,822 (+2%) | 55,257 (-17%) |
| melee:h71 | 133 | 11.0 | 29,650 | 61,049 | 59,052 (-3%) | 53,010 (-13%) |
| melee:h100 | 132 | 18.2 | 27,406 | 58,450 | 56,478 (-3%) | 49,789 (-15%) |
| melee:h28 | 112 | 12.6 | 26,100 | 65,773 | 61,257 (-7%) | 55,009 (-16%) |
| melee:h42 | 117 | 10.8 | 34,089 | 73,228 | 59,003 (-19%) | 52,949 (-28%) |
| melee:h85 | 94 | 12.9 | 28,565 | 63,590 | 62,555 (-2%) | 51,476 (-19%) |
| **all, column-weighted** | 1648 | 12.6 | 26,847 | 61,262 | 57,849 (-6%) | 50,097 (-18%) |

Command: `python t2_emit.py`. It writes `t2_out.txt` and `t2_emit_results.json`.

v1's emission-only price is close to today's, sometimes above it. It now derives `sy1`, `sy2` and
`y_base` from the block header: 7.7K per column, work that today's record half did (4.3). The
end-to-end table is the one that decides.

### 4.3 Components (heavy:gate664)

| component | TODAY | v1 | v2 | command |
|---|---|---|---|---|
| record, per recorded column (lite layout) | 19,743 | 12,043 | 10,292 | `python t5_recload.py` |
| record, per THING | ~0 | 3,835 | 3,835 | same (K=0 intercept) |
| load, per sprite column | 5,110 | 2,764 | 2,764 | same |
| ladder: first sprite field differs | 134 | 94 | 94 | `python t6_ladder.py` |
| ladder: same thing, next block | 600 | 251 | 251 | same |
| ladder: all equal (a ditto) | 1,279 | 614 | 614 | same |
| shadow saves, EVERY emitted column, sprite or not | 770 | 367 | 367 | same |
| emission: regions around the sprite (prologue + 2 regions) | 30,340 | 36,037 (v1 regions + derive) | -- | `python t3_breakdown.py heavy:gate664` |
| emission: the runs (TODAY `sprite_runs`; PROP derive + runs) | 22,218 | 24,693 | 18,551 | same |
| of which the fragment derive (moved here from the record) | -- | 7,717 | 5,505 | same |
| block address: 6 `shl_bit` + `ptr_index` vs nibble placement | 3,228 | 3,228 | 1,280 | same |

The ladder and saves rows apply to every drawn column, not only sprite columns. A frame emits
~103.5 columns (160 minus 56.5 dittos, plan 14), so the saves alone are ~42K a frame standalone
(derived).

### 4.4 Controls (R9)

- **The emission check can fail.** `python t2_emit.py --negative heavy:gate664` shifts the
  proposal's y0 unbias by one row (`sub_constant 32768 -> 32767`). Result: `NEGATIVE CONTROL: the one-row-shifted PROP differs on 101 columns, PROP2 on 101 -> control PASSES (the check can fail)`
- **The pipeline check can fail.** `python t8_pipeline.py --negative heavy:gate664` shifts
  `rec_thing`'s bias by one row, in the RECORD half. Result: `NEGATIVE CONTROL ('heavy', 'gate664'): with rec_thing's bias off by one, the PROP pipeline differs from TODAY on 101/106 columns, PROP2 on 101/106 -> control PASSES (the check can fail)`
- **The harness is wired right.** On every column, today's pipeline equals the plain column with
  the oracle's fragment pasted in.
- **A caught bug.** The first v2 read the first run with the narrow arm. Region 1's step faces
  had armed `stepcol` in between, so the arm was stale.
  - `t2_emit.py` caught it: v2 differed from today on 75 of 106 columns of heavy:gate664.
  - It also "cost" 35.8K instead of 45.7K, because its runs read the wrong memory. A wrong
    column can look like a saving.
  - The fix is in `runs2`'s comment.
- **A caught harness bug.** The first pipeline harness crashed (`ip<2w`). The loaders' narrow arm
  needs a hot-block predecessor, and the harness gave it a bank read. Fixed in the harness, the
  same for every variant.

### 4.5 Layout noise: the floor a delta must clear (`t9_layout.py`)

An fj op's price follows the popcount of the addresses it flips. So two standalone programs
differ in layout as well as in logic. `t9_layout.py` re-prices the same TODAY and v2 logic with
dead ops inserted in front of it: the leaf, for the emission; the record pre-loop, for the
pipeline.

- Emission, leaf shifted by 0 / 1,500 / 4,000 / 9,000 ops (`python t9_layout.py emit
  heavy:gate664`): `emit ('heavy', 'gate664') over 4 shifts: TODAY 50793 .. 51405 (1.2% of the mean); PROP2 45685 .. 46598 (2.0% of the mean); PROP2-TODAY -5310 .. -4755 (-10.4% .. -9.3%)`
- End to end, pre-loop shifted by 0 / 1,500 / 4,000 ops (`python t9_layout.py e2e
  heavy:gate664`): `e2e ('heavy', 'gate664') over 3 shifts: TODAY 70796 .. 71692 (1.3% of the mean); PROP2 41320 .. 41964 (1.5% of the mean); PROP2-TODAY -29757 .. -29422 (-41.6% .. -41.2%)`
- The `--keepfill` runs of 4.1 are the same experiment by accident: ~74K dead ops moved TODAY
  alone.

**Verdict.**
- Shifts of up to 9,000 ops move either program by 1-2%.
- The deltas sit far outside that: emission -9.3% to -10.4%, end to end -41.2% to -41.6%.
- One large shift moved more: the ~74K dead ops of `--keepfill` moved TODAY's end-to-end price
  by 10% on heavy:gate664 (63.7K with the filler, 70.8K without).
- At that scale, layout is as large as v1's entire emission change. That is why the ratios here
  motivate a build, and `msframe` decides it.

## 5. Exact changes

### 5.1 `src/fj/frame_render.fj`

1. **`frame.thing_record_body`, per thing.** Add this after the shade row
   (`hex.read_byte trb_shade_row, trb_tbl_p`):
   - `hex.inc 2, gps_nslot` and `hex.mov 2, gps_s_rec, gps_nslot`;
   - write `[trb_y0 + 32768 lo][hi][trb_shade_row]` at `gpslot + 4 * gps_s_rec`
     (`gpspr.rec_thing`: `ptr_index` + three full-arm writes).
   - Slot ids are 1..255 and 0 means "no fragment". This is exact only while a frame accepts at
     most 255 things, which the budgets do not guarantee: `n_thing` and `n_mon` are separate
     255-budgets. The real bound is the map's drawable things: 251 on E1M1 (MEASURED,
     `things.drawable_things` over `freedoom_e1m1.wad` + `freedoom1.wad`).
   - The emitter must assert `drawable + runtime pools <= 255` (risk 5).
2. **`thing_record_body`, `col_loop`.**
   - KEEP: the u DDA, the `drawn` / `sprflag` tests, the slot A/B choice, the block index, the
     fully-transparent test (`trb_run_last == 0`), and the `sprflag` write.
   - DELETE:
     - the `trb_run_r0` read and its `ptr_add` / `ptr_sub`; read only `last_rel`, at block + 1;
     - the row math: `trb_run_w8`, `trb_y_base`, both `.clamp_row`s;
     - the per-column bias: `trb_y0_biased`.
   - The seven slot writes become three: `[gps_s_rec][blk lo][blk hi]`. The first keeps its
     full arm, the rest use `write_byte*5` (`gpspr.rec_cols`).
   - **v2:** the block address is `blk_addr`, not `mov w/4` + six `shl_bit w/4` + `ptr_index`.
     `blk_addr` writes the four nibbles of blk at nibble 3 and adds the base, which is
     `sprbank + dw` because the record reads op 1 (`gpspr.rec_cols2`).
   - Remove the dead registers from the extern list and the emitter: `trb_run_r0`, `trb_run_w8`,
     `trb_y_base`, `trb_sy1`, `trb_sy2`, `trb_y0_biased`. `trb_cbound` stays, for the x2 clamp.
3. **`frame.lines_spr_load`** becomes `lines_spr_load sprfl, s, sblk, sb, sblkb`.
   - It reads three `read0_byte_and_inc` for slot A, then `ptr_add 5` and three more for B.
   - Its zeroing is `s` / `sblk` / `sb` / `sblkb`, not twelve fields.
   - The `rep(980)` layout filler is re-sized or dropped. That is a re-roll either way (section 7).
4. **The ditto ladder**, in `frame.seg_pass2_leaf_body_lines`.
   - `ck_spr_sy1 .. ck_sprb_blk` (eight compares) become four: `p2_s`/`p2_ds` (2 nibbles),
     `p2_sblk`/`p2_dsblk` (4), and B's pair.
   - The eight `hex.sparse_mov HOT_PAD` shadow saves become four.
   - New shadows: `p2_ds`, `p2_dsb`. Gone: `p2_dssy1`, `p2_dssy2`, `p2_dsy0b` and their B twins.
     These are global labels, so the emitter's declarations change with them (rule 4).
5. **The pass-2 emit call** passes `p2_sprfl, p2_s, p2_sblk, p2_sb, p2_sblkb` in place of the
   eleven sprite registers.
6. **Per-frame state.** `gps_nslot` and `gps_cur_s` must be 0 at every frame start: put them in
   the M1/M5 restore sets.
   - **If `gps_cur_s` survives a frame, the picture is wrong and nothing crashes.** The next
     frame's first sprite column is slot 1 again. It would skip the fetch and draw with the last
     frame's thing-1 top row and light.

### 5.2 `src/fj/stream_render.fj`

1. **`steps_face`**: compute the draw window first, and exit on
   `hex.cmp 2, draw_lo, draw_hi, win_ok, end, end` before `frame.step_shade`. The walker's own
   guard already emitted nothing for an empty window, so this is pixel-neutral.
2. **`steps_splice_c` / `steps_splice_f`**: move `frame.lines_pid_ids_c/f` into the branch that
   walks the region behind the boundary.
3. **`emit_region`**:
   - the wall piece tests `wlo < whi` before its `w1rslv` / `seg_w1rf` flag tests;
   - at `stack = 1`, the `qlo`/`qbound` set-up feeds only the rep-gated `half_walk*` arms, so gate
     it with them. Mind werror on unused locals.
4. **`emit_col_lines`, `sprite_one`** (`gpspr.emit_col`):
   - `frag_derive`: fetch the slot (cached), then read the block header, then compute `y_base`
     and `sy1`/`sy2` clamped to `viewh`;
   - then the covered test, `sy1 <= ctake && sy2 >= fstart`:
     - covered: `steps_splice_c` over `[0, sy1)`, the runs, `steps_splice_f` over `[sy2, H)`;
     - otherwise: the two window-first `emit_region`s around the runs.
5. **The runs** replace `stream.sprite_runs` (`gpspr.runs` / `runs2`):
   - fast path when `0 <= y_base` and `y_base + last_rel <= viewh`: no per-run sign/zero/limit
     tests, and the texel is read straight into the cm index's low byte;
   - otherwise today's clipped loop, run for run.
   - **v2:**
     - `arm3` reads (`read3_and_inc`: zero 2, arm the low 3 nibbles, read, `add_constant 3`);
     - 2-nibble row math on the fast path;
     - the block's first read and the column's first run read keep the full arm;
     - exactness rests on `sprbank` being 4096-bit aligned: 64 ops x 64 bits = 16^3, so a block
       never changes nibbles >= 3.
6. **The A+B path** (`sprfl = 2`) runs the same derive for slot B. `sprite_runs_win` gets the same
   treatment. NOT prototyped.
7. **Dead after the change:** `stream.sprite_runs` and its `srn_*` registers.

### 5.3 The emitter (`src/doomfj/wall_renderer.py`)

1. **Declare `gpslot`**: 4 bytes x (THING_BUDGET + 1) = 1,024 ops.
   - Put it in the hot block after `spslot` if the 16^5 window still has room.
     - In blocked27 that window is `[0x200000, 0x300000)`. Its last label, `tantoangle`, sits
       7,731 ops below the window's end (MEASURED from
       `scratchpad/12m/atlas/blocked27.labels.tsv.gz`).
     - `tantoangle`'s own length comes off that, so 1,024 ops likely fit (UNVERIFIED).
   - Otherwise put it in the tail. Its reads and writes are full arms, so both are correct.
2. **Hoisted declarations.**
   - Add the `gps_*` registers and `p2_s`, `p2_sb`, `p2_ds`, `p2_dsb`.
   - Delete the dead registers of 5.1 and 5.2.
3. **v2 only:** `pad 64` before `sprbank:` in `_lines_sprite_bank`.
   - In blocked27 the bank is already 4096-bit aligned: `sprbank` = bit 263,987,200 =
     64,450 x 4096 (MEASURED, same label table).
   - Whether the placement pass guarantees that, or it is luck, is UNVERIFIED. So the build must
     check it, as `scratchpad/12m/ritual.py` checks the arm5 window, and refuse otherwise.
   - If the alignment cannot be guaranteed, v2's addressing is off and v1 stands.
4. **Unchanged:** `SPR_SLOT_STRIDE` (16), the bank's block format, and the
   `frame.thing_record_body` call.
5. **Restore sets:** add `gps_nslot` and `gps_cur_s`, drop the deleted labels, and re-run the
   label-coverage check.

### 5.4 The oracle

No change: the proposal draws the same pixels. The oracle already splits a fragment into the
thing's top (`ytop_b`) and the column's first opaque row (`st[0]`), which is exactly what the
record now stores.

### 5.5 With D6's native-list sprite bank

D6 replaces the per-bucket baked lists with native run-lists, scaled at draw time through an
8,192-entry `rowmap` (plan 6.6). The prototype runs on TODAY's bank. The design carries over as
follows:
- **The record keeps its shape**, `[slot][list lo][list hi]`. The thing's slot also carries its
  bucket, which is the `rowmap` row.
- **The derive grows**: `sy1`/`sy2` need two `rowmap` lookups a column (first and last row).
- **Each run grows by one `rowmap` lookup.** It must be a D4/dispatch lookup, NOT a
  `hex.pointers` read. A pointer read arms another cluster, so the next list read could no
  longer use the narrow arm (risk 2). A dispatch is also the cheaper lookup.
- **The narrow arm needs lists that never straddle a 4096-bit boundary.** Packed variable-length
  lists must be padded at the boundary: a few words per 4096-bit window.
- The plan already says the per-run `rowmap` lookup must be priced against the column target. It
  is the first probe for the next S6 round.

### 5.6 Fan-out (rule 5)

- `grep` finds the changed macros in `src/fj/frame_render.fj`, `src/fj/stream_render.fj` and
  `src/doomfj/wall_renderer.py` only.
- `tests/` calls none of `emit_col_lines`, `sprite_runs`, `lines_spr_load` or
  `thing_record_body` directly.
- Scratchpad tools that text-patch them (`scratchpad/12m/p2_3_run_arm.py`,
  `p1_1_clip_rows.py`, `p1_3_shift_adjacency.py`, `deg_gate_placed.py`, `profx/analyze.py`) need
  a look before reuse.

## 6. Which pixels change, and what it should cost on blocked27

**Pixels: none.** Section 4 shows the proposed column byte-equal to today's on every case, and
today's equal to the oracle's fragment over the plain column.

One latent difference goes the right way:
- Today's ladder compares `(sy1, sy2, y0b, blk)`, but not the light row `slr`.
- Suppose two different things of the same sprite, bucket and top row meet at adjacent columns
  with the same texture column, under different light. Today they ditto, and the second is drawn
  in the first's light.
- The (slot, blk) signature cannot ditto across things.
- The 24 oracle frames never hit it. They hold 556 adjacent column pairs with an identical
  fragment, and none differs in light row (MEASURED by a scan of `cases.json`). Beyond those
  frames it is UNVERIFIED. Where it does occur, the proposal moves those pixels TO the oracle.

**The plan's ~30K per sprite column is the emission alone.**
- It is plan section 3's "sprite_runs 10.9K + split wall emission 19.3K".
- The record and the load of a VISIBLE sprite column come on top:
  - 24.9K standalone at low addresses (`t5_recload.py`: 19,743 + 5,110);
  - 42-54K standalone inside the full pipelines (`t8_pipeline.py` minus `t2_emit.py`'s sprite
    share, by frame).
- On blocked27 this is UNVERIFIED, but it is the same order as the emission's own sprite share.
  Fight budgets should use the end-to-end number.

**Expected ops (UNVERIFIED projection).**
- Emission: today's sprite column is 30.2K on blocked27 (MEASURED, plan section 3). v2's
  standalone ratio (0.818) puts it at ~24.7K.
- End to end: blocked27's record + load per column is not in plan section 3. Scale the
  standalone end-to-end saving (32,751 per column) by 1/1.70, the median of the four
  ratios in section 1. That gives ~19.3K per sprite column.
- At the fight frames' 103 sprite columns, that is ~1.98M a frame.
- The ladder saves on all columns come on top: ~25K a frame.
- **The ship gate decides.** A placement re-roll can move a frame by millions either way
  (plan 13 #1).

## 7. Risks and open points

1. **Placement re-roll (the big one).**
   - This rung changes table counts and sizes: `gpslot`, a smaller `spslot` use, deleted
     registers, and the `pad 64`.
   - The blocking pass will re-pick its pins, and one deletion has cost ~6.8M before.
   - Land it after P0's pin protection (plan 13 #1). Price it by `msframe` against shipped. A B
     SLOWER verdict does not ship.
2. **The arm3 invariant is silent when broken.**
   - A narrow read is exact only if the previous arm was in the same 4096-bit block.
   - Anything that arms a pointer between two run reads breaks it: a future per-run table read,
     for example.
   - Only the pixel gate sees it; this session's first v2 is the proof (4.4).
   - `runs2`'s comment states the rule; a reviewer must re-check it on every edit there.
3. **The 4096-bit alignment of `sprbank` under the placement pass.**
   - It holds in blocked27 (5.3). That it survives a re-roll is UNVERIFIED, hence the
     build-time check.
   - v1 needs no alignment.
4. **The B path is unprototyped.**
   - A+B columns fetch two slots. The single-entry cache then thrashes, and it costs one fetch
     per fragment.
   - Pixel identity for B is argued, not measured.
5. **1-byte slot ids hold only while a frame can accept <= 255 things.**
   - E1M1's drawable things are 251 today.
   - The plan's R4 skill filter removes 33 of them (218 left).
   - The pools add ~12 (plan section 7). That leaves ~230, which fits.
   - The plan's own size note says E1M3 (248) and E1M5 (250) would not fit. The same pressure
     hits the byte-wide thing lists (the parked M4 wide-list branch).
   - The emitter asserts the bound, or the record takes a 2-byte id (4 bytes, one more
     write/read and a 4-nibble ladder compare).
   - If the id wraps, the cache hands the wrong thing's top row to a column: wrong pixels,
     no crash.
6. **`rec_thing` costs 3.8K standalone per thing**, even for a thing that ends up recording no
   column. Two fixes, neither prototyped (UNVERIFIED savings of ~1.2-2.5K a thing):
   - allocate the slot lazily at the first `do_store`;
   - or walk a running slot pointer (`ptr_add 4`) instead of `ptr_index`.
7. **Standalone is not blocked27.** The v2 savings are exactly the pointer-arm costs that
   placement changes most. The 1.70x factor is a median, not a law.
8. **What would go further** (not prototyped; UNVERIFIED):
   - **the bank as code**: a block becomes a list of calls into shared (rel, texel) pair
     blocks, as bands-as-code S2 did. That removes both pointer reads per run, at an image-size
     cost that must be measured against the 35% budget;
   - **`DEG_HD_BUDGET` 2**: changes pixels;
   - **lazy slots** (point 6).

## 8. Files (all new, `scratchpad/gp/probes/sprite/`)

| file | what |
|---|---|
| `gp_sprite_col.fj` | the PROPOSED macros, `ns gpspr`: v1 (`emit_col`, `emit_region`, `steps_*`, `frag_derive`, `runs`, `rec_thing`, `rec_cols`, `load`) and v2 (`arm3`, `read3_and_inc`, `blk_addr`, `frag_derive2`, `runs2`, `emit_col2`, `rec_cols2`) |
| `plib.py` | the harness: cases to program (real band lists, W1R walker, V5 pieces, bank, slots), assemble, run, decode |
| `cases.py` -> `cases.json` | the oracle cases (3 scenarios x 8 viewpoints); NOT tracked (827 KB, regenerable: `cases.py` uses a fixed seed), sha256 `c3f09c0cd8a87099` -- regenerate with `python cases.py` and check the hash |
| `t2_emit.py` | emission TODAY / v1 / v2 on all fight frames, pixel checks, `--negative` |
| `t8_pipeline.py` | end-to-end record -> load -> emit, pixel checks, `--negative` |
| `t3_breakdown.py`, `t4_prims.py`, `t5_recload.py`, `t6_ladder.py` | components and primitives |
| `t9_layout.py` | the layout-noise control (section 4.5) |
| `t1_today.py`, `feas0.py` | the first feasibility steps |
| `t7_weapon.py`, `weapon_cols.py` | the weapon overlay, for `docs/gp-partial-ditto.md` |
| `*_out.txt`, `*.json` | the outputs quoted here |
