# P1.6 survey (Explore agent, 2026-09-27 ~08:40, read-only on doom-m7e 890a0c2)

## 1. Today's bank
- SPR_BLOCK_STRIDE = 64 ops, asserted (wall_renderer.py:3157-3165). reference_model: 32 buckets (:151), HD from bucket h 40 cap 24 (:158-159), mid cap 12 (:167), coarse below 32 px cap 4 (:173-174), DEG_SPR_NEAR_TZ=384 (:162), DEG_HD_BUDGET=0 (off, :335). View 160x100, TEXTURE_DOWNSCALE=2.
- `pad 64` then `sprbank:` (wall_renderer.py:3184-3190); build.py:77-94 checks alignment (called :403).
- Block = 64 cells, one op each: [r0][last_rel][n][(rel_end, RAW texel) x n], zero padding; len(body) < 64 strict -> a 0 terminator (:3234-3239). r0 from the bucket top; rel_end exclusive from r0. Empty column [0,0,0]. Largest body 51.
- Per downscaled column u (dw = width//2, u samples patch column 2u): 32 main blocks (buckets 12-31 = heights 42..100 HD full-res rows cap 24; buckets 0-11 = heights 4..38 MID half-res cap 12) + a coarse (LD) region of 9 blocks (buckets 0-8, heights 4..29, cap 4) (:3221-3261).
- Index: main sp_base + u*32 + b; LD sp_base2 + u*9 + b; kind-major, then u, then bucket; blk < 0x10000 asserted (:3262).
- bucket = min(31, ((h-1)*32)//101); bucket height = the largest h mapping to it (reference_model.py:349-362): [4,7,10,13,16,19,23,26,29,32,35,38,42,...,98,100].
- blk_addr: base + blk x 4096 bits (frame_render.fj:1962-1971).
- Size: 41 blocks x 128 words = 5,248 words a column; E1M1 32 kinds, 557 columns -> 22,837 blocks = 2,923,136 words (art_budget_out.txt:34-35).
- The `n` byte is written, never read (frag_derive skips it, stream_render.fj:858).

## 2. The oracle's sprite column (reference_model.py)
- per thing (:2003-2034): hb from th_px; too-near clamped to 100 px, top moved down (:1584-1591); feet planted ytop_b = ytop + th_px - hb (:2017); lr = wall_light_row(lightnum, hb, wph) (:2018).
- tier: HD if hb >= 40 (strip(fcols[u], pic.height, hb, cap 24)); else coarse if hb < 32 and tz > 384<<16; else mid (strip(cols[u], pic.height//2, hb, cap 12)). mid/coarse row v = patch row 2v (:1475-1494).
- u = min(dw-1, max(0, frac>>16)), frac += istep (:1595, :2019-2022).
- sprite_strip (:1498-1539): v0/v1 first/last opaque native rows; interior holes take the nearest opaque texel above; screen row r (0..hb-1) shows native row floor(r*dh/hb), painted iff in [v0, v1]; runs merged; while runs > cap the first shortest (by SCREEN length) run is absorbed into the run above; no row -> None (no fragment, slot free, :2035-2036).
- paint (:2478-2489): slot B first, then A; rows [y0+prev, y0+rel) clipped; colormap[lr][texel]; y0 = ytop_b + r0.
- exactness: a native boundary b lands on screen row ceil(b*hb/dh): depends on hb AND dh (each patch's own height per tier) -> a 32x256 rowmap cannot be exact; the cap binds per bucket after scaling -> class F (plan D6 "every sprite pixel changes", plan-gameplay.md:575).

## 3. v2 reads -- constraints on a new layout
- record: blk_addr(trb_blk, sprbank+dw) then full-arm read of last_rel at op 1; last_rel == 0 -> skip (frame_render.fj:712-714).
- frag_derive (stream_render.fj:836-888): gpslot fetch full (:840-852); blk_addr (:855); r0 full arm (:856); last_rel read3_and_inc (:857); skip n (:858).
- frag_runs (:898-944) / frag_runs_win (:951-984): first rel full arm; later rel/texel 3-nibble reads; loop holds only byte.emit/cm.emit dispatch tables; ends on rel == 0; frag_runs_win copies, runs twice per A+B column.
- arm3/read3_and_inc (frame_render.fj:1940-1961): re-arm nibbles 0-2 relative to the last armed pointer; no carry out of nibble 2.
- KEEP: (a) sprbank 4096-bit aligned; (b) each list header..0 terminator inside one 64-op window (gp-sprite-column.md:377-378); (c) no pointer read between reads of one walk -> the per-run rowmap is a DISPATCH lookup (gp-sprite-column.md:374-376; handoff:290); (d) r0 at op 0, last_rel at op 1 (record hard-codes sprbank+dw), pairs from op 3; (e) rel >= 1, one byte; 2-nibble row math (view h <= 255); texels RAW; (f) list address = 16-bit index at 64-op granularity; spslot [s][lo][hi]; ditto compares (slot, blk).
- sub-slots of 32/16 ops do not fit blk_addr's nibble-3 placement (need an index scale or sub-offset); the record's last_rel==0 test becomes "empty at this scale".
- doc 5.5 (:366-380): the slot carries its bucket (the rowmap row); derive 2 lookups, each run 1. gpslot byte 3 unused (wall_renderer.py:3170; frame_render.fj:618-631).

## 4. Prototype scratchpad/gp/render/art_budget.py (imports the MAIN checkout's src and WADs)
- words = 2 x ops. F0 today padded; F1 today packed; F2 native lists packed (per u three lists at identity scale: full cap 24, half cap 12, half cap 4); F3 the same at padded strides 64/32/16 ops (the handoff's figures).
- sets: FULL8 every frame, 8 rotations, WAD mirror pairs (A2A8) counted once; DOOM5 rotations 6-8 as mirrors; monsters POSS, SPOS, TROO, SARG (walk, attack, pain, death, gib); effects BAL1, PUFF, BLUD rot 0; static today's 32 kinds.
- monsters FULL8 218 patches 4,755 columns F3 1,065,120; DOOM5 197 / 4,303 / 963,872; effects 16,576 + 5,152 + 3,584 = 25,312; static 32 / 557 / 124,768 (F2 65,054). Mean runs a column: full 12.8-18.5, half 6.7-9.5, coarse 3.3-3.8.
- NOT BUILT: no rowmap, no draw-time scaling, no pixel comparison. UNVERIFIED: the ~1.96M total (only 1,215,200 printed); rowmap/patch tables ~0.15M, weapons ~0.4M, HUD ~0.19M are transcript-only estimates.
- the static F3 includes the 5 monster kinds' A1 patches (SARG twice: 3002 and 58), which FULL8 also counts.

## 5. Today vs P1.6
- today: one patch per thing TYPE (first of A0/A1/A2A8/A1D1, reference_model.py:1463-1471, table :136-150); monsters always walk frame A rotation 1; no rotation/mirroring anywhere; fj clamps u only from above (frame_render.fj:663-669).
- thing -> block: _lines_sprite_bank returns base_of/dw_of/ld_base_of per kind (wall_renderer.py:1173, 3213-3263); baked things in their constant block (:1717-1721, schema :168-170); runtime via thing_rows cold row (things.py:27-57, 153-184) into throwc (wall_renderer.py:607-610), thing_load_cold (frame_render.fj:491-509); per frame sprbkt gives the bucket (wall_renderer.py:1179-1182; frame_render.fj:564), per-thing constant (:566, :588-603), column index u*32 + const (:696-703), stored in spslot (:715-729), read by frag_derive.
- per-type values to become per-patch: left/w/hh/top and sp_tzmax (things.py:175-177; wall_renderer.py:1700-1722); light class key (lightnum, wph) (wall_renderer.py:3372).
- P1.6 adds: 218 FULL8 monster patches + effects; a (sprite, frame, rotation) -> list/mirror/geometry table; mirroring by negating the step (plan-gameplay.md:365-368) -- needs a lower clamp on u. state -> frame data exists (gamedata.py:178+); world.octant_of (world.py:144).
- open: the -0.97M assumes weapons + HUD (P4); static + monsters + effects + tables alone ~ -1.56M. Rowmap key/values undefined anywhere.
