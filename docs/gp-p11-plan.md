# M7 P11 -- the EXIT sign, the shared third-slot painter, and one ledge rule for slots, sight and aim

The owner's third play-test answers (2026-10-12/13, the chat after blocked55):

| item | the owner | what P11 does |
|---|---|---|
| (a) the exit switch "super clear that it's exit" | option (a): a floating "EXIT" sign sprite, DOOM's red | a virtual decoration over the exit alcove (section 1) |
| (b) share the third slot's drawing copies | "0.1% is alright, try not to get more than that" | one region painter the C path fcalls (section 2) |
| (c) a sprite fully hidden behind a ledge takes no slot | "i agree with you" -- measure on the model first | measured: 0 of 16 blinks removed; kept, free with (d) (section 3) |
| (d) aim and sight follow the ledge rule | (my recommendation) "Great" | the same test in the seen rule and the aim window (section 3) |

P11 is a separate rung from P10 (the owner, after asking whether merging would save time: "Ok i agree with you" -- it
would not). Its combat set is re-planned as v10 and shown to the owner before it is frozen.

## 1. (a) The EXIT sign -- doomfj/exitsign.py

- **A virtual thing**, type 9800 (`gamedata.EXIT_SIGN_TYPE`): `WadFile.things` appends it AFTER the THINGS lump's own,
  so no wad index moves, and only where the map's exit line is the one it was placed against (E1M1's line 407:
  special 11, (-400, 1280) -> (-400, 1312)). Every consumer that draws things sees it through that one list (the oracle,
  the emitter's sprite bank, leaf lists and runtime rows, the node builder's thing boxes); the WORLD drops it
  (`gamedata.NOT_THINGS`; a `ThingType` with no flags so a drawable list's lookups answer "not solid, not special").
- **The picture is built**, not read: Freedoom's EXITSIGN texture is a running man beside 5-row letters, which the
  bank's 2:1 column sampling (and the low tiers' rows) erase at 160x84. A 5x7 font drawn at 3x (the X's diagonals
  bold), PLAYPAL red 176 on a dark plate 108 in a rim 100: 69 x 27 map units.
- **Where**: the switch is the back wall of a 32x16 alcove (sector 67) that opens east into the exit room (sector
  66) at x = -384. The sign hangs in the room 4 units before the opening, centred, its lower edge 2 above the alcove's
  ceiling -- an EXIT sign over a door, DOOM's convention. Inside the alcove it would draw over the alcove's side walls
  seen at an angle (a thing beats the walls of its own leaf).
- **Drawn in the ACTOR class** (`reference_model.DRAW_ACTOR_TYPES`: the oracle's `act` and both of the emitter's row
  builders): measured in the model, as scenery the room's monster B-gated 'EX' out of the picture (slot B is refused
  to a short scenery fragment). Sight and aim still ask MONSTER_TYPES: never seen, never aimed.
- Its leaf (the exit room) has monsters at spawn, so it takes the RUNTIME path: the runtime tables grow by one row.
  The game tier's reset is by label (one pass) -- extents from the declarations, nothing to re-key.

## 2. (b) The shared third-slot painter

`stream.emit_region_c`'s two background windows (around the third fragment, slot C) each held an inline copy of the
region painter at each of `emit_col_lines`' four call sites; now they set `erc_lo` / `erc_hi` and fcall ONE shared
leaf (`erc_leaf`, beside `band_walk`). The common path (no slot C) stays inline. Price: an fcall in the rare columns
with a third fragment; size: the copies' words back. Gate: the edge gate's G3 views (byte-exact) and the build's size.

## 3. (c) + (d) -- one rule

`reference_model.ledge_hidden(ups_x, los_x, yb, hb)`: a thing's bucket box [yb, yb + hb) is FULLY HIDDEN in a
column when the nearer boundary pieces stored there when its leaf is reached leave none of its rows open -- above
the last upper piece's end, from the last lower piece's start down (DOOM's running ceilingclip / floorclip: P10 G1's
clip window), or both when they meet. A side with no piece bounds nothing: the view's edges are not a ledge, so a
monster above or below the view keeps today's sight. Three users in `render_wall_frame` (`stack_steps` only):

- (c) the record loop: a hidden column takes no slot;
- (d) the seen rule: a monster is seen only through an open column where its box is not hidden;
- (d) the aim window: a hidden column is skipped as a wall-drawn one is (`ReferenceModel.thing_rows`, project_thing's
  rows, gives the aimed thing's box).

The fj: `frame.ledge_box` clamps the box once per thing (ylo1 = clamp(y0, -1, H) + 1, yhi1 = clamp(y0 + hb, 0, H + 1)
+ 1 -- two nibbles, and every compare with a piece row comes out as unclamped); `frame.ledge_test` reads the column's
sfflag counts and, only when a side has a piece, its last piece's row from sfslot; the record reads the counts at
`slot_check` (rec_clip_read moved there) and tests before the seen mark; the seen probe tests each open column;
aimcode's leaf takes the rows (`proj.thing_rows`, project_thing's own code as a macro) once the box meets the window.

**Measured on the model first** (v8's 1,100 frames; session scratchpad `p11/p11cd_px.py --rule old|new`):

| | P10 (old) | P11 (new) |
|---|---|---|
| live-monster-frames that would paint and got NO slot (true blinks) | 16 | 16 |
| columns that would paint and got no slot | 207 | 196 |
| hidden fragments (no pixel) per frame | -- | ~10 |
| record-loop open columns per frame / with nearer pieces | ~107 / 31.7% | same |
| sight lost (old-rule seen, new-rule not), monster-frames | -- | 322 behind pieces + 143 off-view and covered |

So (c) does NOT reduce the blinks: they are columns where three VISIBLE fragments are already in front. It stays
because (d) needs the same per-column test where the record marks seen, so skipping the slot is free.

## 4. Tests and gates

- tests/fj/test_sprite_bank_fj.py: the record's LEDGE cases (no slot behind the pieces; no seen mark for a thing
  hidden in every column; decoys at the offsets the test must not read; the three boundaries forced onto columns
  that take a slot) and five mutants (the call gone, u1 / l1 read instead of the last piece, an end not + 1, the
  clamp short) -- 46 passed with the walkers and the screen tests.
- tests/fj/test_aim_record_fj.py: the leaf's box rule with rows + ledges (321 of 400 records decided by the pieces)
  and three mutants (the test gone in the window's middle column, the bucket's index as its height, the sprite's top
  for the bucket's).
- tests/host/test_exit_sign.py: the picture spells the word (decoded from its pixels), the thing is appended last and
  bound to the line, the world ignores it, the model draws it past the room's monster (341 px, 93 red) and, R9, as
  scenery the monster cuts it (154 px).
- scratchpad/gp/edge_gate.py: two EXIT-sign views (R9: the sign moves 430 / 762 px), the G1 / G3 views now with (c).
- The restore sets: `scratchpad/add_hoisted_decls.py` adds the 12 new scratch globals at their declared extent to
  both (test_restore_set_shipped: 22 passed). The hosted tiers' explicit-offset sets do not grow with the runtime
  tables: moving those tiers to the one-pass reset too is the next one-pass step.

## 5. The rest of the rung

1. The host suite on the P11 tree; the v10 plan (`scenarios_v2.py --plan --sight seen`, ~28 min of model time) and
   its comparison with v9 -- shown to the owner before freezing.
2. The edge gate (heavy, after blocked56's chain releases the box).
3. The build: ONE PASS (`--counts-trust` with blocked56's counts), then the full chain (gates, B0 v10, the fight /
   hurt / die / p2a gates, stress, gamespeed, msframe vs blocked56 -- class F, the D8 tripwire ~90 ms/frame -- size).

**Kill criteria** (declared before the build): (K1) any gate not byte- and state-exact; (K2) the size over 42% of
2^27 (43% since 88c1ac1: the owner raised the cap on P10's onepass56, 2026-10-13); (K3) CAP-22 binding; (K4) msframe over ~90 ms/frame unexplained (D8); (K5) (b) costing more than 0.1% of
msframe's time against a build without it (the owner's bound) -- measured, not estimated.
