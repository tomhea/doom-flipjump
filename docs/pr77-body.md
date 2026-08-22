# M1 - the self-resetting program

The fj program self-modifies, so the host restored a pristine 85M-word image before every frame.
That is both the fps ceiling and the reason a standalone `.fjm` cannot exist. This makes the program
restore **itself**: a reset appended as a final part (`<map>_07_reset.fj`), plus a size-neutral
patch turning the frame's trailing `stl.loop` into `;m1_reset`, which ends by re-entering the frame
at `__hot_end`. **One execution now renders as many frames as the wire feeds.**

Base is `m1-base` (= `16ee4fd`), so this diff is M1 only — 13 files outside `scratchpad/`, not the 310-commit branch.

## TDD evidence (R1)

Every block below is generated, not retyped. `scratchpad/m1_mutations.py` edits **real shipped
files** (`src/doomfj/selfreset.py`, `src/fj/m1_reset.fj`) and restores them in a `finally`.

**FAIL** — every mutation that can coexist, applied at once (`scratchpad/_m1_mutations_all.log`, verbatim and complete):

```
=== 14 OF 15 MUTATIONS APPLIED TO REAL SHIPPED CODE ===
    selfreset.py: the two-sided guard deleted
    selfreset.py: main-part recognition assert gone
    selfreset.py: provenance refusal gone
    selfreset.py: containment check gone
    selfreset.py: byte counts hardcoded again
    m1_reset.fj: high-nibble exact_xor deleted
    m1_reset.fj: shared pointer never restored
    selfreset.py: layout fingerprint check gone
    selfreset.py: missing-label refusal gone
    selfreset.py: label+offset format refusal gone
    selfreset.py: containment unbounded at the top
    selfreset.py: verify back to the membership test
    selfreset.py: pristine-value check gone
    selfreset.py: limit back to a truthiness test

    NOT APPLIED (conflicts with a mutation above -- covered individually by
    the per-mutation run in scratchpad/_m1_mutations.log):
      m1_reset.fj: one write past the cell

.FF........FFFFFFFFFFFF.F.F.FFFF.FF.F.F                                  [100%]
=========================== short test summary info ===========================
FAILED tests/host/test_selfreset.py::test_refuses_a_set_naming_a_label_this_build_does_not_have
FAILED tests/host/test_selfreset.py::test_refuses_an_absolute_address_set - K...
FAILED tests/host/test_selfreset.py::test_restore_set_without_provenance_is_refused
FAILED tests/host/test_selfreset.py::test_offset_running_past_its_label_is_refused
FAILED tests/host/test_selfreset.py::test_emit_splits_byte_arrays_from_nibble_cells
FAILED tests/host/test_selfreset.py::test_emit_coalesces_zero_runs_and_keeps_non_zero_singles
FAILED tests/host/test_selfreset.py::test_emit_drops_a_read_only_extent - Ass...
FAILED tests/host/test_selfreset.py::test_emit_ignores_words_below_code_start
FAILED tests/host/test_selfreset.py::test_emit_refuses_set_words_in_the_unreachable_tail_of_a_byte_array
FAILED tests/host/test_selfreset.py::test_emit_patches_the_frame_tail_size_neutrally
FAILED tests/host/test_selfreset.py::test_emit_refuses_a_main_part_it_does_not_recognise[stl.output_char 0xFF\nstl.loop\nstl.loop\nbad: stl.loop\n-exactly 1 bare stl.loop]
FAILED tests/host/test_selfreset.py::test_emit_refuses_a_main_part_it_does_not_recognise[stl.output_char 0xFF\nstl.loop\n-junk-input halt]
FAILED tests/host/test_selfreset.py::test_emit_refuses_a_main_part_it_does_not_recognise[nop\nstl.loop\nbad: stl.loop\n-0xFF end-of-frame marker]
FAILED tests/host/test_selfreset.py::test_no_byte_array_word_is_ever_nibble_cleared
FAILED tests/host/test_selfreset.py::test_layout_fingerprint_rejects_a_differently_laid_out_build
FAILED tests/host/test_selfreset.py::test_containment_is_bounded_at_the_top_of_the_address_space
FAILED tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance[2]
FAILED tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance[10]
FAILED tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance[-10]
FAILED tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance[5000]
FAILED tests/host/test_selfreset.py::test_verify_values_catches_a_changed_pristine_value
FAILED tests/host/test_selfreset.py::test_verify_values_reports_clean_when_it_read_nothing
FAILED tests/fj/test_m1_reset.py::test_clears_every_value_0_to_255 - Assertio...
FAILED tests/fj/test_m1_reset.py::test_second_call_on_the_same_cell_still_works
24 failed, 15 passed in 1.72s

=== RESTORED ===
.......................................                                  [100%]
39 passed in 1.79s
```

**Each mutation individually**, so no mutation hides behind another
(`scratchpad/_m1_mutations.log`, verbatim and complete):

```
BASELINE (no mutation)
  39 passed in 1.76s

MUTATION: selfreset.py: the two-sided guard deleted
  1 failed, 38 passed in 1.77s   ok
    caught by tests/host/test_selfreset.py::test_emit_refuses_set_words_in_the_unreachable_tail_of_a_byte_array

MUTATION: selfreset.py: main-part recognition assert gone
  1 failed, 38 passed in 1.78s   ok
    caught by tests/host/test_selfreset.py::test_emit_refuses_a_main_part_it_does_not_recognise

MUTATION: selfreset.py: provenance refusal gone
  1 failed, 38 passed in 1.78s   ok
    caught by tests/host/test_selfreset.py::test_restore_set_without_provenance_is_refused

MUTATION: selfreset.py: containment check gone
  2 failed, 37 passed in 1.77s   ok
    caught by tests/host/test_selfreset.py::test_containment_is_bounded_at_the_top_of_the_address_space
    caught by tests/host/test_selfreset.py::test_offset_running_past_its_label_is_refused

MUTATION: selfreset.py: byte counts hardcoded again
  10 failed, 29 passed in 1.78s   ok
    caught by tests/host/test_selfreset.py::test_emit_coalesces_zero_runs_and_keeps_non_zero_singles
    caught by tests/host/test_selfreset.py::test_emit_drops_a_read_only_extent
    caught by tests/host/test_selfreset.py::test_emit_ignores_words_below_code_start
    caught by tests/host/test_selfreset.py::test_emit_patches_the_frame_tail_size_neutrally
    caught by tests/host/test_selfreset.py::test_emit_refuses_a_main_part_it_does_not_recognise
    caught by tests/host/test_selfreset.py::test_emit_refuses_a_main_part_it_does_not_recognise
    caught by tests/host/test_selfreset.py::test_emit_refuses_a_main_part_it_does_not_recognise
    caught by tests/host/test_selfreset.py::test_emit_refuses_set_words_in_the_unreachable_tail_of_a_byte_array
    caught by tests/host/test_selfreset.py::test_emit_splits_byte_arrays_from_nibble_cells
    caught by tests/host/test_selfreset.py::test_no_byte_array_word_is_ever_nibble_cleared

MUTATION: m1_reset.fj: high-nibble exact_xor deleted
  2 failed, 37 passed in 1.68s   ok
    caught by tests/fj/test_m1_reset.py::test_clears_every_value_0_to_255
    caught by tests/fj/test_m1_reset.py::test_second_call_on_the_same_cell_still_works

MUTATION: m1_reset.fj: shared pointer never restored
  2 failed, 37 passed in 1.78s   ok
    caught by tests/fj/test_m1_reset.py::test_clears_every_value_0_to_255
    caught by tests/fj/test_m1_reset.py::test_second_call_on_the_same_cell_still_works

MUTATION: m1_reset.fj: one write past the cell
  2 failed, 37 passed in 1.79s   ok
    caught by tests/fj/test_m1_reset.py::test_neighbours_untouched
    caught by tests/fj/test_m1_reset.py::test_second_call_on_the_same_cell_still_works

MUTATION: selfreset.py: layout fingerprint check gone
  1 failed, 38 passed in 1.78s   ok
    caught by tests/host/test_selfreset.py::test_layout_fingerprint_rejects_a_differently_laid_out_build

MUTATION: selfreset.py: missing-label refusal gone
  1 failed, 38 passed in 1.78s   ok
    caught by tests/host/test_selfreset.py::test_refuses_a_set_naming_a_label_this_build_does_not_have

MUTATION: selfreset.py: label+offset format refusal gone
  1 failed, 38 passed in 1.81s   ok
    caught by tests/host/test_selfreset.py::test_refuses_an_absolute_address_set

MUTATION: selfreset.py: containment unbounded at the top
  1 failed, 38 passed in 1.80s   ok
    caught by tests/host/test_selfreset.py::test_containment_is_bounded_at_the_top_of_the_address_space

MUTATION: selfreset.py: verify back to the membership test
  4 failed, 35 passed in 1.82s   ok
    caught by tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance
    caught by tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance
    caught by tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance
    caught by tests/host/test_selfreset.py::test_verify_catches_a_moved_label_at_every_distance

MUTATION: selfreset.py: pristine-value check gone
  2 failed, 37 passed in 1.78s   ok
    caught by tests/host/test_selfreset.py::test_verify_values_catches_a_changed_pristine_value
    caught by tests/host/test_selfreset.py::test_verify_values_reports_clean_when_it_read_nothing

MUTATION: selfreset.py: limit back to a truthiness test
  1 failed, 38 passed in 1.78s   ok
    caught by tests/host/test_selfreset.py::test_verify_values_reports_clean_when_it_read_nothing

RESTORED: 39 passed in 1.76s  ok

M1 MUTATION EVIDENCE: PASS -- every mutation is caught
```

⚠ Read both blocks. The all-at-once block says **nothing** about
`test_neighbours_untouched`: the mutation that catches it (`one write past the cell`) is the one it
lists as NOT APPLIED, because an earlier mutation deletes the line that one anchors on. The
per-mutation run is where that test is shown to have teeth.

⚠⚠ An earlier revision of this paragraph said the test was among the passes "because a mutation that
breaks the clear earlier masks a write past the end". That asserted the mutation RAN and the test
survived — a coverage claim about the FAIL block that was false. Worse, it was never true: before
round 10 that mutation was a bare `str.replace` whose anchor had already been deleted, so it was a
**silent no-op**, which is precisely the failure this harness exists to detect. It took the uniform
anchor assert to surface it.

Full host suite, with the marker filter's bound visible:

```
$ timeout 900 python -m pytest tests/host tests/fj/test_m1_reset.py -q   # _m1_pytest_full.log
284 passed, 1 deselected in 43.01s
```

## Integration evidence (R2)

The shipped artifact, from `scratchpad/_m1_wired3.log` — the build that EXERCISES the
pristine-value check, which is why this is the run quoted and not the earlier
`_m1_wired2.log`:

```json
  "storage_mode": "flat",
  "span_words": 85468976,
  "flat_limit": 134217728,
  "headroom": 1.57,
  "fjm_bytes": 31347735,
  "assemble_seconds": 2918.415,
  "tier": "lines/W1R/FT1+plane_near",
  "features": {
    "wall_noise": true,
    "sky": true,
    "steps": true,
    "things": true,
    "stack_steps": true,
    "bbox_cull": true,
    "deg": true,
    "player_sim": true,
    "collide": true,
    "moving_things": true,
    "state_wire": "bin",
    "self_reset": true
  },
  "self_reset": {
    "nibble_cells": 4349,
    "byte_cells": 1002,
    "restore_set": "C:\\Users\\tomhe\\Documents\\doom-flipjump\\src\\doomfj\\data\\m1_restore_set.json.gz",
    "labels_moved_in_set": 0,
    "values_changed_in_set": 0,
    "baked_cells_value_checked": 10702,
    "view_w": 160,
    "subsectors": 682
  }
}
total 4039s
```

⚠ **TWO ASSEMBLE TIMES FOR ONE BYTE-IDENTICAL BINARY**, and the drift is the machine, not the
program: `_m1_wired2.log` 3,193 s / 4,724 s total, `_m1_wired3.log` 2,918 s / 4,039 s total, same
inputs, same output sha256 `75794727dce656be…`. That is a 15% wall-clock spread on identical work,
which is why CLAUDE.md says to compare on process CPU time and treat this machine's wall clock as
unreliable. Quoting the slower of the two below, since it is the less flattering.

**ASSEMBLE TIME REGRESSED, AND THAT IS THE HONEST NUMBER: 3,193 s assemble / 4,724 s total, against
559 s for the single-pass build.** M1 is inherently two-pass - pass 1 exists only to learn where
every cell landed, because most of the dirty set is macro-local scratch that fj cannot name from
outside its macro - so ~2x is structural and the rest is the larger span. It buys back the host's
whole-image restore on *every frame*, but the build-time goal the memory index calls met is met for
the non-reset tier only.

Gate on the wired binary (`scratchpad/_m1_gate8.log`; the tool names and hashes both
images, and no longer prints a percentage against its own worst-case chain mean):

```
loop : build/doom_e1m1_loop.fjm  sha256 75794727dce656be18140f10c88cff5b647660c713bcea4c8d1e34a918c5689a
old  : scratchpad/fjmcache/_rssprobe.fjm  sha256 3c13ec21424f7f5434bd2070d9a34796ab2f92de9657dc16e2894f4c63e4acee
  ONE run: 206,293,420 ops -> 4 frames presented
  CONTROL 1 (frame count): 4 == 4?  ok
  frame 0 (664,291,0x18000000): loop vs old BYTE-EXACT; vs oracle loop=0 old=0 (equal -- M1 changed nothing)  ok
  frame 1 (1272,-724,0x40000000): loop vs old BYTE-EXACT; vs oracle loop=0 old=0 (equal -- M1 changed nothing)  ok
  frame 2 (1869,479,0x80000000): loop vs old BYTE-EXACT; vs oracle loop=378 old=378 (equal -- M1 changed nothing)  ok
  frame 3 (-416,256,0x0): loop vs old BYTE-EXACT; vs oracle loop=0 old=0 (equal -- M1 changed nothing)  ok
CONTROL 2 (non-looping): the SAME wire on the OLD binary must present exactly 1 frame
  old binary: 57,364,424 ops -> 1 frame(s)  ok -- so N frames IS the loop
  ONE run: 381,820,821 ops -> 8 frames  ok
  frame 0 (664,291,0x18000000,k=0): BYTE-EXACT
  frame 1 (700,300,0x20000000,k=1): BYTE-EXACT
  frame 2 (1272,-724,0x40000000,k=5): BYTE-EXACT
  frame 3 (1869,479,0x80000000,k=0): BYTE-EXACT
PHASE 1 (oracle, 4 frames one run) : PASS
CONTROL 2 (old binary = 1 frame)   : PASS
PHASE 2 (8-frame chain vs pristine): PASS
M1 GATE: PASS
```

The gate's own negative control, added in round 2 -- the same gate, run twice:

```
$ python scratchpad/m1_gate.py --selftest --loop-fjm build/doom_e1m1_loop.fjm
# scratchpad/_m1_gate8_self.log, produced by the SHIPPED tool (the earlier
# _m1_gate6_self.log predated a print-only edit to m1_gate.py)
SELFTEST 2/2: one byte of presented frame 0 flipped -- must FAIL
  frame 0 (664,291,0x18000000): loop vs old !! DIFFER; vs oracle loop=1 old=0 !! M1 MOVED PIXELS  FAIL
  frame 1 (1272,-724,0x40000000): loop vs old BYTE-EXACT; vs oracle loop=0 old=0 (equal -- M1 changed nothing)  ok
  frame 2 (1869,479,0x80000000): loop vs old BYTE-EXACT; vs oracle loop=378 old=378 (equal -- M1 changed nothing)  ok
  frame 3 (-416,256,0x0): loop vs old BYTE-EXACT; vs oracle loop=0 old=0 (equal -- M1 changed nothing)  ok
  frame 0 (664,291,0x18000000,k=0): !! 1 px DIFFER
  clean run  exit 0 (want 0)
  mutated    exit 1 (want non-zero)
M1 GATE SELFTEST: PASS
```

The per-frame lines are quoted rather than the summary because the summary is what hid a broken
version of this control for a whole round. CR round 3 found the guard testing `keep is None`, which
no caller ever sets, so the flip landed on the old-binary REFERENCE runs too. That version also
printed `M1 GATE SELFTEST: PASS` -- but its frame 0 read `loop vs old BYTE-EXACT` (both corrupted
identically) and its FAIL came from a corrupted reference at frame 1. It proved the gate notices a
broken reference and said nothing about the property the gate exists to certify. The signature
above -- frame 0 DIFFER, frames 1-3 exact -- is what a working control looks like.

Playability, 100 frames walking and turning through E1M1 (`scratchpad/_m1_play3.log`):

```
loop : build/doom_e1m1_loop.fjm  sha256 75794727dce656be18140f10c88cff5b647660c713bcea4c8d1e34a918c5689a
old  : scratchpad/fjmcache/_rssprobe.fjm  sha256 3c13ec21424f7f5434bd2070d9a34796ab2f92de9657dc16e2894f4c63e4acee
  CONTROL (the player really moved): 1735 map units travelled, 50 distinct positions, 15 distinct angles
  CONTROL (vacuity): 72 distinct pictures of 100
  start (-416.0, 256.0)   end (799.7, 477.3)
  BYTE-EXACT vs the old binary: 100/100 frames  ok
M1 PLAYABILITY: PASS
```

Cost, against the **sweep median over 260 frames** - the repo's metric, not the gate
viewpoints (`scratchpad/_m1_sweep6.log`):

```
loop : build/doom_e1m1_loop.fjm  sha256 75794727dce656be18140f10c88cff5b647660c713bcea4c8d1e34a918c5689a
old  : scratchpad/fjmcache/_rssprobe.fjm  sha256 3c13ec21424f7f5434bd2070d9a34796ab2f92de9657dc16e2894f4c63e4acee
  median 30,191,585   mean 30,929,878   min 7,675,375   max 61,405,073
  CONTROL (same pictures): 260/260 byte-exact  ok
  sweep MEDIAN frame          : 30,191,585 ops
  in-program reset, per frame : 250,789 ops
  => the reset is 0.8% OF THE MEDIAN FRAME
```

An earlier revision of this claimed 7.47% against a 47.5M mean of **gate** viewpoints. That was the
wrong denominator and is retracted in the log above.

## The two things that are load-bearing and easy to break

**`m1_reset.fj` goes LAST, after the emitted parts - not into `includes`.** A macro-expansion label
is named `f<file>:l<line>:...`, so inserting a file anywhere earlier renumbers every label in every
file after it. Measured: putting it in the includes renamed 200 of the set's labels and the loader
refused, exactly as it should.

**The restore set is label+offset, never absolute.** Absolute addresses are valid only for the one
assembly they came from, and as a build input that is a landmine - the pass1-vs-pass2 check compares
the two passes *to each other*, never the set to the program, so it cannot catch it.

## Answers to CR round 1 (7 findings)

R6's hardcoded `BYTE_ARRAYS` was a real silent-corruption path - the coverage assert is one-sided,
so a wider `VIEW_W` drops byte cells into the nibble set, where the clear **corrupts** rather than
fails, byte-exact on E1M1. Counts are now derived from each array's label extent and cross-checked
against `cfg.VIEW_W` and `len(cmap.subsectors)`.

R9's round-trip control computed `base + (x - base) == x`, an algebraic identity, and it was the
only provenance the shipped data file had. Replaced by a round-trip through the production loader
plus three mutations that must each be caught (shift a label / delete a label / make an offset
escape its span), and `load_restore_set` now enforces containment and refuses an unprovenanced set.
`CODE_START_WORD` is derived from word 1. Details in `ef8dad9`.

**One finding was wrong:** hatchling already ships `src/doomfj/data/` - verified by building a
wheel, where an explicit `force-include` is *rejected as a duplicate*. The default-path half of that
finding was right and is fixed.

**No rebuild was needed for the round-1 fixes, and that was proven rather than argued:** at that
point re-emitting the reset part gave `sha256 b8edfe38836e5884...`, identical to the then-shipped
part, 5,031/1,002 cells either way. ⚠ That hash is HISTORICAL. Round 2 changed what the emitter
produces, so the file at that path is now `63a80ad69cdda5e0f3d3126b...` at 4,349/1,002 cells --
see the rebuild section.


## Answers to CR round 2 (7 findings)

The big one: **the guard was still one-sided.** `emit_reset_part` asserted every byte cell must be
IN the set and nothing in the other direction, so a set word inside a byte array's DECLARED extent
but outside its REACHABLE part fell through to the nibble clear. It was doing exactly that -- 682
cells of `sshead`, declared `hex.vec 2*nss` but reached at a ONE-cell stride.

Padding, or live byte cells being corrupted? The code could not tell, which is the finding.
MEASURED: 0 dirty words across all five `scratchpad/_m1_dirty*.json.gz` maps. Dead work. Trimmed
(5,031 -> 4,349 nibble cells), the guard made two-sided, and REBUILT -- worth -19,110 ops/frame and
-57,950 span-words.

Byte-array MEMBERSHIP cannot be settled statically (`src/fj/` writes bytes through pointer
registers), so `scratchpad/m1_bytecheck.py` settles it by running frames and checking that no
nibble-cleared cell ever holds a value > 15, with the three known arrays as the vacuity control:

`scratchpad/_m1_bytecheck.log`, verbatim:

```
checking 4,349 nibble-cleared cells across 3 known byte arrays as the control
image  : scratchpad/fjmcache/_rssprobe.fjm
sha256 : 3c13ec21424f7f5434bd2070d9a34796ab2f92de9657dc16e2894f4c63e4acee
labels : scratchpad/_m1b_labels.tsv.gz
set    : src/doomfj/data/m1_restore_set.json.gz
labels sha256 matches the set's provenance  ok
  (-416,256,0x0,k=0)        46,927,659 ops    0.5s  cells>15 so far: 0
  (664,291,0x18000000,k=1)    61,519,657 ops    0.5s  cells>15 so far: 0
  (1272,-724,0x40000000,k=5)    54,804,140 ops    0.7s  cells>15 so far: 0
  (1869,479,0x80000000,k=0)    51,929,636 ops    0.5s  cells>15 so far: 0

CONTROL 1 (vacuity) -- the KNOWN byte arrays must themselves show values > 15:
  sshead      24 of 682 cells held a value > 15   ok
  pclm       160 of 160 cells held a value > 15   ok
  sfflag     160 of 160 cells held a value > 15   ok

RESULT: over 4 viewpoints, no nibble-cleared cell held a value > 15.
        SCOPE: that is evidence about THESE viewpoints, not a proof over all frames.
        It is what licenses BYTE_ARRAY_NAMES holding only sshead/pclm/sfflag.

m1_bytecheck: PASS
```

The image is named and hashed in the tool's own output because CR round 4 was right that this
verdict -- the one licensing `BYTE_ARRAY_NAMES` in shipped code -- previously named no artifact.
The default is the NON-looping binary on purpose: the loop's own reset would overwrite the cells
under test.

Also: `emit_reset_part` gained 9 tests (it had none); `test_byte_arrays_covers_only_...` was
correctly called vacuous and is replaced by a property test; `m1_setfile.py --selftest` builds its
own synthetic inputs so it runs on a clean checkout; `m1_gate.py` and `m1_reemit.py` gained
`--selftest`; and the re-emission evidence that used to live in `/tmp` is now committed as
`scratchpad/m1_reemit.py`.

## Known gaps

- `tests/host` still has no test that BUILDS the loop end-to-end; the gate, sweep, playability,
  byte-check and re-emit runs are scripts under `scratchpad/`.
- **Negative-control coverage is now GENERATED into `docs/handoff-m1-reset.md` §9.7** by
  `scratchpad/m1_inventory.py` (`--check` fails if the doc disagrees with the filesystem), because
  the prose version of it in this body was wrong three revisions running -- first overclaiming that
  all five tools carried `--selftest` (false, and the exact failure CLAUDE.md records: a false
  R9-compliance statement inside the R9 evidence), then undercounting. The real remaining gaps:
  **`m1_sweep.py` and `m1_play.py` have NO negative control** beyond their in-run vacuity and
  byte-exact comparisons, and their verdicts are quoted above; and **`m1_dirtymap.py`** -- whose
  0-dirty-words result is what licenses the 682-cell trim -- has a genuine mutation control
  (CONTROL 3 shifts the label table and requires the per-label counts to change) but no flag to
  invoke it standalone; and **`m1c_restore_set.py`**, the uncontrolled first stage of the chain
  that produced the restore set now shipping in `src/`.
- **The M1 reset part's own span is 645,946 words** (`85,468,976 - 84,823,030`, the same config with
  and without the flag). ⚠ Do NOT derive it from the M14 ledger row: that is an older, smaller
  configuration and the subtraction gives 17,255,518, which is 26x wrong. An earlier revision of
  DESIGN.md invited exactly that.
- `m1_bytecheck.py --selftest` needs a BUILT binary (it reads what a real program leaves in real
  memory), so unlike the other three it cannot run on a bare checkout.
- 9 of the restore set's 308 labels were found by observation rather than derived, and the file does
  not mark which 9.
- The only caller of `build_wall_renderer(self_reset=True)` is `scratchpad/m1_wired_build.py`;
  `scripts/walk_e1m1.py` consumes a prebuilt loop `.fjm` via `--fjm/--loop` but cannot produce one.

## Answers to CR round 6 (4 blocking + 4 non-blocking)

**R4 — the corroboration arithmetic was wrong, again in the shape round 5 flagged.** DESIGN.md said
the part is "~85 words per restored cell"; 645,946 / 5,351 = **120.7**. 85.0 is the *nibble-run*
rate the trim measured. There are two rates and they are now both stated, with the byte-cell rate
(~276) derived rather than implied. The 645,946 figure itself was verified sound by the reviewer.

**R4 — "both sha-named in the handoff" was false.** Only the without-flag binary was. Both are now
named and hashed in DESIGN.md and in handoff §9.5:
`self_reset=False` `_rssprobe.fjm` `3c13ec21424f7f54…` (84,823,030 words);
`self_reset=True` `build/doom_e1m1_loop.fjm` `75794727dce656be…` (85,468,976).

**R9 — three tools I filed as "not cited as evidence" are cited**, one of them in shipped source
(`src/fj/m1_reset.fj` lines 14 and 21 cite `m1_zbyte.py`). Corrected, and the count was 22 not 21.
⚠ **This inventory has now been wrong in five successive revisions.** That is recorded in §9.7 as
the lesson, because it is not about M1: a hand-maintained inventory of one's own evidence is itself
evidence, and it decays exactly as fast as everything else.

**R1 — the blocks were still edited inside their fences** despite the body claiming otherwise. All
of them are now pasted whole from their logs, including the `short test summary info` section the
FAIL block had been dropping — the section a reader needs to audit the masking disclosure.

Non-blocking, taken: `m1_gate.py`, `m1_sweep.py` and `m1_play.py` now print both images with
sha256 (they named no artifact), and were re-run — `_m1_gate7.log`, `_m1_play3.log`,
`_m1_sweep6.log`. `handoff-complete-game.md`'s "do not write the reset prologue until M1a and M1b
agree" is struck. The fps table's own section now carries the UNVERIFIED retraction, not just the
pointer to it.

**On provenance (the reviewer's ruling, and I took the stronger option).** Presence-only hashes were
judged acceptable-if-documented, with a cheap alternative offered. The alternative is implemented: a
`layout_fingerprint` — sha256 over the sorted `(label, span_words)` pairs of the set's *own* labels,
invariant to the line-number churn that makes a whole-table hash useless here. It catches precisely
what resolution + containment + count miss. `load_restore_set` now refuses a set without one, and
`m1_setfile.py` gained C4:

```
  C4 layout changed, fingerprint stale -> refused ok
```

C4 is deliberately NOT refingerprinted while C1-C3 deliberately ARE — otherwise the fingerprint
would catch everything and C1-C3 would stop testing resolution, containment and the missing-label
refusal at all. Passing for the wrong reason is the failure this file already had once.

The containment check's one-sided top-of-address-space case is also closed: the highest-addressed
label had unbounded offsets, which is the same shape as the round-2 bug.

**Mutations: 8 → 12**, covering the guards the reviewer noted no mutation exercised. All 12 caught.
⚠ When I changed the containment code, `drop_containment` silently stopped matching and the harness
reported `!! NOTHING CAUGHT IT` rather than a green tick — the non-vacuity property working. Every
mutation whose anchor drifts silently becomes a no-op, and a no-op mutation passes every
test -- which reads as coverage. The harness now asserts, for EVERY mutation and any added later,
that applying it actually changed the file; breaking one anchor gives
`mutation '...' changed nothing -- its anchor has drifted from the code`.

⚠ An earlier revision of this line claimed all 14 functions asserted their own anchors. Three did
not -- they relied on the loud-failure backstop. That was a completeness claim about the R1 evidence
tool itself, which is the class CLAUDE.md records.

⚠ Two mutations **cannot both be applied in this order**: `drop_high_nibble` deletes the line
`spill_past_the_cell` anchors on. (Reversing them would apply both — it is an ordering artifact, not
a true incompatibility, and CR round 11 was right to say so. The order is kept deliberately, because
it is what keeps the conflict path exercised rather than dormant.) The all-at-once block names what
it could not apply; the per-mutation run covers it.

⚠⚠ **And the skip mechanism itself had the defect it was built to prevent.** It filed every failed
application under "conflict" and exited 0 — so a mutation whose anchor had DRIFTED from the shipped
code was laundered into a benign note, in the tool whose whole job is proving controls are not
broken. It now distinguishes them by re-applying to the pristine file: fails there too → DRIFT,
raise; succeeds → conflict, report. Proven both ways.

## Answers to CR round 7 (5 blocking)

**The first real code defect since round 2, and my own comment was defending it.**
`verify_labels_unchanged` is the build's ONLY check that the addresses baked from pass 1 survived
pass 2. It resolved the set against the PASS-2 table and asked whether each PASS-1 address was a
member — so a 1-word move was caught and anything larger passed silently:

```
alpha 100 -> 101   ['alpha']   caught
alpha 100 -> 102   []          REPORTED CLEAN
alpha 100 -> 110   []          REPORTED CLEAN
alpha 100 ->  90   []          REPORTED CLEAN
```

`build.py` asserts on that and records `labels_moved_in_set: 0` — a field that could not tell
"nothing moved" from "something moved two words". The layout fingerprint catches all four, and
round 6 switched it off *in this function* with `check_layout=False`, justified by a comment of
mine claiming the opt-out cost only a nicer diagnostic. It cost the detection. Now total, with a
test parametrised over +1/+2/+10/-10/+5000 (a single delta=1 case is what let it survive) and a
13th mutation restoring the old membership test.

**Control C4 was vacuous** — containment refused it, not the fingerprint, because the set carries
whole extents (307 of 308 labels have `maxoff+1 == span`) so shifting a label UP makes its own
offsets escape. C4 moves the label DOWN now and asserts the two-sided half: with the fingerprint
off, the same input must be ACCEPTED.

**The build-path fingerprint assert had never run.** `scratchpad/m1_fpcheck.py` drives the REAL
`build_wall_renderer` to pass 1 and fires it against the build's own table
(`scratchpad/_m1_fpcheck.log`, verbatim):

```
running build_wall_renderer(self_reset=True) as far as pass 1 ...
pass 1 reached in 1271s, 6,806,757 labels

set's layout_fingerprint : 46422330e2a2aa53aca2233c682ae757ae39c3d1a5405473dea4511764765c99  (generated from scratchpad/_m1b_labels.tsv.gz)
this build's pass-1 table: 46422330e2a2aa53aca2233c682ae757ae39c3d1a5405473dea4511764765c99

load_restore_set against the REAL pass-1 table: ACCEPTED, 10,702 words

m1_fpcheck: PASS -- the build-path assert is exercised and passes
```

⚠ My first version of that script re-listed `emit_wall_renderer`'s arguments by hand and died on
`floor_mode="ft1"` vs `"FT1"` — a twin of `build.py` that drifted within a single edit. It
intercepts the real call now instead of reconstructing it.

**The rate table was mislabeled**: 4,008 cells are in coalesced `hex.zero` runs, not 4,349 — 341 are
`hex.set` singles, a different primitive at a different price. And 85.0 is a MARGINAL rate used as
an average with the third row derived from the residue. DESIGN.md now gives the measured
composition and the one measured rate (120.7 words/cell) and refuses the split. Rounds 5, 6 and 7
were all this same shape.

**§9.7 was wrong in its sixth revision**, in the two rows the previous revision edited. It now says
plainly that if the table matters it should be GENERATED from the filesystem, and that it is not.

## New this round, and OPEN

`docs/handoff-m1-reset.md` §9.8 records a gap nothing in the repo reconciled: §7.4's per-primitive
prices predict **176,769** ops for the shipped composition; the measured cost is **250,789**. A
**42%** gap. The tidy explanation (74,019 / 265 `hex.zero` runs = 279 ops per run) is an arithmetic
coincidence, not a measurement. The measured number stands on its own; the model under it does not,
and the handoff now says not to use those prices to predict a reset cost.

## Answers to CR round 8 (3 blocking)

**Two of the three describe a body that is not the one on the PR.** Counting every string the review
quotes, against the live body fetched from GitHub: `"270,811 ops"` 0, `"_m1_gate4"` 0,
`"_m1_wired.log"` 0, `"7 failed, 11 passed"` 0, `"5,271,539,564"` 0, `"0.9% OF THE MEDIAN"` 0. Those
blocks were repointed in round 6 and regenerated in round 7. The likely cause is structural: the
body was drafted in an **untracked** scratchpad file, so a reviewer exporting the tree at a commit
sees no body at all. Fixed — it lives at `docs/pr77-body.md` now, in the tree, at the same commit as
the code it describes.

**The third is mine and is the seventh occurrence of the same class.** The round-7 SCOPE comment on
the fingerprint — added specifically to be honest about scope — stated the span distribution with
its keys and values transposed: *"2400 of them share span 2, 320 share span 4"*. There are 308
labels, so that is not merely wrong but impossible. Measured:
`{2:29, 4:77, 6:6, 8:19, 12:8, 16:158, 20:4, 320:4, 2400:2, 2728:1}`. The conclusion inverted with
it: 301 of 308 labels have span ≤ 20 and any one of them flips the hash, so the power is **not**
confined to the few wide rows. Corrected with the real distribution inline.

**A non-blocking item that deserved better: addresses and values are two claims.**
`verify_labels_unchanged` proves the reset writes to the right ADDRESSES. `emit_reset_part` bakes
`hex.set 1, addr, v` with `v` from **pass 1's** image, and nothing compared pass 2's value there — a
drift would restore the wrong value silently and pixel-identically. `verify_values_unchanged` now
compares both images and the build refuses on any difference.

That is new code on the shipped build path, which is exactly what round 7 caught me shipping
unexercised — so the build was **re-run** rather than reasoned about:

```
  "self_reset": {
    "nibble_cells": 4349, "byte_cells": 1002,
    "labels_moved_in_set": 0,
    "values_changed_in_set": 0,
    "baked_cells_value_checked": 10702,
    "view_w": 160, "subsectors": 682
  }
  span 85,468,976 words, flat, assemble 2,918 s, total 4,039 s
```

`baked_cells_value_checked: 10702` is every word the set resolves to, not a sample. **And the binary
came out BYTE-IDENTICAL** (`75794727dce656be…`, 31,347,735 bytes) — the same file the sweep and
playability logs certify. "No rebuild needed" was checked by rebuilding.

Also taken: `scratchpad/_m1_scratchtest.py` deleted (tracked by accident, uncontrolled, superseded,
unrunnable on a clean checkout — and §9.7's glob is `m1*.py` while that file starts with an
underscore, which is why the inventory could never have found it); the `check_layout=False` opt-out
justified at the call site for the right reason; `handoff-complete-game.md`'s next-steps block
rewritten as a banner after its strike-through was found closing at the end of its own first line —
twice, because round 7's fix added a note instead of moving the marker.
