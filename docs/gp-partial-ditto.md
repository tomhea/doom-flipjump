# Partial ditto: a 0x0B column that copies its top rows from the column to its left

**Status: DESIGN (phase 0, stream S6 / plan section 14 #5). No flipjump edit has been made.**
Per the owner's D9, the change would go on a branch off flipjump `1.5.1`, as a PR into `1.5.1`
only, never `main`, and unpublished. Numbers are MEASURED with the command given, or UNVERIFIED.

---

## 1. Why the device needs it

The shipped renderer streams each frame as 0x0B column run-lists (`present.begin_frame_collines`).
Today's full DITTO record, `[x][0xFE]`, copies the whole column x-1 into column x. Two planned
features break it.

- **The weapon sprite (plan 6.6).** A weapon column differs from its left neighbour, so it can no
  longer be a ditto. Plan sections 6.6 and 14 (MEASURED, blocked27): 56.5 of 160 columns are
  dittoed, and a re-emitted column costs ~15.9K. The plan prices the loss at **+0.2 to 0.5M ops
  on every frame**, and sets the target at <= 0.1M.
- **The bottom HUD bar (decided, D6).** The screen stays 160x100: the bar takes the bottom 16
  rows and the view is 84. The bar rows `[VIEW_H, H)` are never mentioned by the view, so the
  device keeps them. But a full DITTO copies all H rows, including the left column's bar.

## 2. Where the device code is

| what | file | name |
|---|---|---|
| the device (fj `--io pc`, every gate that uses `PcIO`) | flipjump-151 `flipjump/interpreter/io_devices/ScreenIO.py` | `InMemoryScreen._begin_frame_collines`, `InMemoryScreen._handle_collines_byte`, the constants `COLLINES_END = 0xFF` and `COLLINES_DITTO = 0xFE`, and the module docstring's grammar |
| the window | same package, `pygame_window.py` | `InteractiveScreen(InMemoryScreen)` inherits the decoder; `PcIO` composes it. No change needed there |
| doom's test decoder (deg_gate and the `tests/fj` gates) | doom-flipjump `tests/fj/stream_screen.py` | `StreamScreen._handle_collines_byte`, its own copy of the 0x0B grammar. It must change in the same step |
| the grammar's fj-side statement | doom-flipjump `src/fj/present.fj` | the comment on `present.begin_frame_collines` |

There is **no 0x0B unit test in flipjump-151 today** (branch `1.5.1`, 73e09c0). A search of
`tests/` for `collines` or `0x0B` finds one docstring mention, in `tests/unit/test_pygame_ce.py`.
doom's `tests/fj/test_stream_screen.py` has no 0x0B test either.

## 3. The stream-format change (additive)

Inside a column list, at the position where a pair's `y2` byte is expected:

| bytes | meaning today | meaning after |
|---|---|---|
| `y2 <= H`, then `colour` | fill rows `[cursor, y2)`; `cursor = y2` | unchanged |
| `0xFF` | end of column | unchanged |
| `0xFE` | DITTO: copy the whole column x-1, and end the column | unchanged |
| **`0xFD y`** | error (`y2` past the screen) | **PARTIAL DITTO**: copy rows `[cursor, y)` of column x-1 into column x; `cursor = y`; the list continues |
| **`0xFC y`** | error | **KEEP** (the sibling, recommended): leave rows `[cursor, y)` as they are; `cursor = y`; the list continues |

Rules:
- `cursor <= y <= H`, else error.
- `0xFD` in column 0 is an error, as the full DITTO is today.
- After the new token, the list goes on with pairs, another token, or `0xFF`. A column may
  therefore be `[x][0xFD][wtop][pairs...][0xFF]`, or `[x][0xFC][VIEW_H][pairs...][0xFF]`.

**Backward compatibility.**
- The two tokens are recognised only when `H <= 0xFB`. On such a screen neither byte can be a
  valid `y2`: today both raise "run ends at row ..., past the ...-row screen". So no stream that
  decodes today changes meaning. Doom's screen is 100 rows, with or without the bar (D6).
- On a taller screen the bytes keep their old meaning.
- Old binaries never emit them, so the shipped binary decodes identically.
- A NEW binary needs the new device: it is forward-incompatible by design.

**Why the full `0xFE` DITTO is not given a row count instead.** `[x][0xFE]` is followed by the
next record's tag. A trailing count would change how every existing stream parses.

## 4. Device implementation (sketch, ~20 lines per decoder)

```python
COLLINES_PARTIAL_DITTO = 0xFD   # [0xFD][y]: rows [cursor, y) copied from column x-1
COLLINES_KEEP = 0xFC            # [0xFC][y]: rows [cursor, y) left as they are
# __init__ / _begin_frame_collines / on opening a column:  self._collines_op = None

def _handle_collines_byte(self, byte):
    if self._collines_op is not None:                 # the row byte of a 0xFD / 0xFC
        op, self._collines_op = self._collines_op, None
        if not self._collines_row <= byte <= self.height:
            raise IODeviceException(f'collines {op:#x} to row {byte}: cursor {self._collines_row}, '
                                    f'screen {self.height}')
        if op == COLLINES_PARTIAL_DITTO:
            x, w = self._collines_column, self.width
            for row in range(self._collines_row, byte):
                self.pixel_indices[row * w + x] = self.pixel_indices[row * w + x - 1]
        self._collines_row = byte
        return
    ...                                               # (tag position: unchanged)
    if self._collines_y2 is None:                     # a y2, 0xFF, 0xFE -- or now 0xFD / 0xFC
        if self.height <= 0xFB and byte in (COLLINES_PARTIAL_DITTO, COLLINES_KEEP):
            if byte == COLLINES_PARTIAL_DITTO and self._collines_column == 0:
                raise IODeviceException('collines PARTIAL DITTO for column 0 (no left neighbour)')
            self._collines_op = byte
            return
        ...                                           # (unchanged)
```

- `StreamScreen._handle_collines_byte` in doom gets the same ~20 lines.
- The docstring grammar and `present.fj`'s comment get the two new rows.
- For the emitter, a capability constant (`ScreenIO.COLLINES_PARTIAL_DITTO`) lets the build
  REFUSE to emit the tokens against a device that lacks them. That makes the failure loud and
  early, instead of an exception on the first frame.

## 5. How the renderer would use it

**(a) HUD bar** (`VIEW_H < H`; the plan's 160x16 bar makes `VIEW_H = 84`):
- The view's column lists already end at `viewh`, so the bar rows are never touched by a column
  record.
- The one place that would touch them is the pass-2 leaf's `emit_ditto:` in
  `frame.seg_pass2_leaf_body_lines`. There, `byte.emit x; stl.output_char 0xFE` becomes
  `byte.emit x; stl.output_char 0xFD; stl.output_char VIEW_H; stl.output_char 0xFF`. Three
  constant bytes replace one, at 8 ops a byte: +16 ops per ditto, ~0.9K a frame at 56.5 dittos
  (UNVERIFIED, the plan's count).
- Bar changes are separate records after the view: `[x][0xFC][VIEW_H][bar pairs][0xFF]`, baked per
  glyph column, only for the columns whose digit changed.
- After the menu frame (which covers every row), the whole bar is redrawn once.

**(b) Weapon: KEEP overlay (recommended).**
- The world is emitted exactly as today, so every ditto survives and the world emitter is
  untouched.
- After the view, and before the frame's closing `0xFF`, each weapon column is one record:
  `[x][0xFC][wtop[x]][pairs...][0xFF]`.
- The pairs are baked per (weapon frame, column): a constant `y2`, and the texel through `cm.emit`
  with the frame's light row set once. Flash pixels are full-bright, so they are pre-mapped
  constant bytes.
- Order matters: the overlay must come after the world, because a later ditto of column x+1
  copies column x.

**(c) Weapon: in-record partial ditto (the item as the plan phrased it).**
- A weapon column whose world matches its left neighbour's (today's ditto signature) emits
  `[x][0xFD][wtop[x]][pairs...][0xFF]`.
- This is only valid when rows `[0, wtop[x])` of column x-1 are still world. That holds when x-1
  is not a weapon column, or when its weapon starts at or below `wtop[x]` (the rising side of the
  silhouette).
- Every other dittoable weapon column must still emit its world down to `wtop[x]`.
- It needs `wtop[x]` inside the world emitter (a runtime bottom instead of the constant `viewh`)
  and a new ditto-ladder rung.

Eligible columns, MEASURED from the WAD by `python scratchpad/gp/probes/sprite/weapon_cols.py`:

| frame | columns | eligible |
|---|---|---|
| PISGA0 | 28 | 15 |
| SHTGA0 | 33 | 20 |
| PUNGA0 | 47 | 37 |
| SAWGA0 | 41 | 17 |
| SHTGC0 | 46 | 34 |

## 6. Expected savings, per frame

The overlay pairs are MEASURED on a standalone fj program:
`python scratchpad/gp/probes/sprite/t7_weapon.py`. It generates the baked overlay, decodes the
output, checks it against the WAD geometry with 0 pixel mismatches, and prices it by the slope
over repetitions. That program is not a blocking-pass build, so the absolute numbers are
UNVERIFIED on blocked27.

The lost-ditto columns use the plan's MEASURED 15.9K per re-emitted column and 56.5/160 = 35.3%
ditto rate. The rate inside the weapon's columns is UNVERIFIED.

| weapon frame (view 100 rows) | cols | pairs | today's protocol: lost dittos | (c) partial ditto: residual lost dittos | (b) KEEP overlay: all it costs |
|---|---|---|---|---|---|
| pistol idle PISGA0 | 28 | 516 | ~157K + pairs | ~73K + pairs | **83,664** |
| shotgun idle SHTGA0 | 33 | 398 | ~186K + pairs | ~73K + pairs | **64,106** |
| fist idle PUNGA0 | 47 | 483 | ~264K + pairs | ~56K + pairs | **78,027** |
| chainsaw idle SAWGA0 | 41 | 736 | ~231K + pairs | ~135K + pairs | **122,623** |
| shotgun firing SHTGC0 | 46 | 1,032 | ~259K + pairs | ~68K + pairs | **172,951** |
| pistol flash PISFA0 (bright) | 16 | 130 | -- | -- | 2,507 |

- "Pairs" in columns (c) and today's protocol cost the same as the overlay's own pairs.
- **So KEEP removes the whole lost-ditto term, ~0.16 to 0.26M/frame at idle** -- in line with the
  plan's +0.2 to 0.5M.
- What remains is the overlay itself: 64K to 123K at idle, and 173K for the firing shotgun.
  Divided by the 1.70x median standalone/blocked27 factor of `docs/gp-sprite-column.md`, that is
  ~38-72K idle and ~102K firing (UNVERIFIED). So the plan's <= 0.1M target is met at idle and
  roughly met on firing frames.
- The partial ditto (c) removes 40 to 80% of the lost-ditto term, and costs a ditto rung and a
  runtime world bottom.
- At the bar's 84-row view the overlay shrinks: pistol 56,832, shotgun 39,034, fist 38,345
  (same command).
- The only term the overlay does not recover is the world rows under the weapon, which an
  in-record stop would skip. The plan puts that at ~0.02 to 0.05M, UNVERIFIED.

**Recommendation.** Add both tokens in one flipjump change; they share one parser branch.
- Use KEEP for the weapon and for bar updates.
- Use PARTIAL DITTO for the view's dittos above the bar.

D6 chose the bottom bar together with this device option. The 24-column side panel is the
fallback only if the device change were refused, and then the weapon keeps today's lost-ditto
cost.

Plan 6.6 sketches the weapon with the world stopped at the weapon's top. That is (c)'s shape. KEEP
gives that up, which costs ~0.02-0.05M of world rows under the weapon. In return it keeps every
ditto and leaves the world emitter unchanged.

## 7. The unit tests

**flipjump-151, a new `tests/unit/test_screen_collines.py`** (none exists):

1. Today's grammar as a baseline:
   - pairs fill `[cursor, y2)`;
   - `0xFF` ends the column, and the tail keeps last frame's pixels;
   - `0xFE` copies all rows;
   - `0xFF` at tag position presents;
   - the errors: `y2 < cursor`, `y2 > H`, a DITTO at column 0, `x >= W`.
2. PARTIAL DITTO:
   - `[x][0xFD][y][pairs][0xFF]` equals rows `[0, y)` from column x-1, the pairs below, and the
     tail kept;
   - a mid-list `0xFD` copies only `[cursor, y)`;
   - `y == cursor` is a no-op;
   - errors: column 0, `y < cursor`, `y > H`.
3. KEEP: `[x][0xFC][y]...` leaves rows `[cursor, y)` with the previous frame's pixels. Test it
   across two frames.
4. Compatibility:
   - on an `H = 252` screen, `0xFC`/`0xFD` still decode as plain `y2` values;
   - a recorded 0x0B frame from the shipped renderer decodes to the same pixel hash before and
     after the change.
5. **Negative controls (R9):** two deliberately wrong decoders must fail tests 2 and 4 --
   - one that copies `[cursor, y]` (one row too many);
   - one that recognises the tokens on a 252-row screen.

**doom-flipjump, `tests/fj/test_stream_screen.py`:**
- the same cases against `StreamScreen`;
- plus a cross-decoder test: 1,000 random well-formed 0x0B frames, new tokens included, fed to
  `StreamScreen` and to `InMemoryScreen` must leave identical `pixel_indices`. The two decoders
  are separate copies, and this test keeps them from drifting.

## 8. Risks and open points

- **Two decoders, one grammar.** Without the cross-decoder test, a gate (StreamScreen) and the
  player (`--io pc`) could disagree on a frame with no pixel gate noticing.
- **Order-dependence.**
  - KEEP overlays must follow the world. A ditto that comes after an overlaid column copies the
    weapon.
  - The bar pass must follow any record that could touch the bar. In the shipped order (view,
    then overlays, then the frame's `0xFF`) this holds by construction.
- **The bar needs `VIEW_H < H` in the renderer.** No build has ever had `VIEW_H != H` (plan 6.6),
  and that change is independent of this device option.
- **The weapon's pair cost (~160 ops/pair standalone) is the overlay's whole price.**
  - ~84 of those ops are `cm.emit` (MEASURED, `python scratchpad/gp/probes/sprite/t4_prims.py`)
    and 8 the constant `y2` byte, so ~70 are the `hex.set 2` that loads the texel (derived).
  - Pre-mapping the colours per light level cuts a pair to ~19 ops (the flash row above), but
    multiplies the baked code by the number of light rows. The size budget decides.
