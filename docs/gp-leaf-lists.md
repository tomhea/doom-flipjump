# M7 P1.3 -- persistent leaf lists

The handoff's rung P1.3 (`docs/handoff-gameplay.md` section 10, plan section 6.3): the game tier's
per-leaf thing lists stop being rebuilt every frame. Class S -- the same pixels, cheaper. Kill
criteria: `docs/gp-ledger.md`.

## What it removes

Each runtime thing (the ones the renderer draws from a list, not from a baked leaf) is linked into
its leaf's list: `sshead[leaf]` is the first thing, `thnext[t]` the next, both BYTE arrays storing
`t + 1` so that 0 ends a list. The renderer walks a leaf's list in ascending index order, which is
what keeps each sprite's front-to-back slot the same as a from-scratch build.

`sim.bind_things` rebuilt all of them EVERY frame -- 438,808 ops/frame on gamespeed (MEASURED,
plan section 3) -- from the bindings `thss_rt` (thing -> leaf). The game tier has no host, and
nothing moves a thing yet, so every frame rebuilt the SPAWN lists. The M1 reset also restored
`sshead` (and the bindings and positions) to pristine every frame, which cost its own ops.

## The design

- **Bake.** `things.spawn_leaf_lists(binds, nleaves)` is bind_things' loop in Python (prepend in
  descending index order, so every list comes out ascending); the emitter bakes its result into the
  standalone image with `things.byte_array_decl` -- one cell an entry, the byte in the jump word
  (`b * dw`, the layout `read_byte` reads) -- padded with zero cells to the extent the old
  `hex.vec` had, so no label after it moves (the hot block is anchored) and the M1 restore set's
  span for `sshead` holds.
- **Persist.** `build.THING_PERSIST = ("sshead", "thss_rt", "thpos_rt")` joins STANDALONE_PERSIST in
  the game tier (`moving_things`): the lists' heads, each thing's leaf and each thing's position are
  world state now, changed only by a thing's MOVE. `thnext` is not in the tuple because the restore
  set never carried it -- bind_things rewrote every link every frame, so it never needed restoring,
  and it persists by not being restored (a name the set lacks would make the build refuse).
- **No per-frame rebuild.** The standalone frame no longer calls `sim.bind_things`; the hosted tiers
  keep the wire protocol (the host sends positions and cached bindings, bind_things relinks).
- **The per-move relink** -- `sim.leaf_unlink t, leaf` / `sim.leaf_link t, leaf` (src/fj/sim.fj):
  DOOM's P_UnsetThingPosition / P_SetThingPosition on these lists, ascending insert and unlink, the
  step-for-step mirror of `world.py`'s `_list_remove` / `_list_insert`. Monsters are still inert,
  so nothing in the binary calls them; P3 does, on the ~7% of monster steps that change leaf. Their
  scratch is named globals (`things.LEAF_LINK_DECLS`), no @-local data.

## Tests

| claim | test | control |
|---|---|---|
| the baked lists are bind_things' lists | `tests/host/test_leaf_lists.py`: E1M1's things' spawn leaves, against an independent construction (group, sort, chain) | a descending build is refused |
| the declaration spells them at the old extent | `test_the_declaration_spells_the_bytes_at_the_old_extent` | an extent the values do not fit, or a byte over 255, is refused |
| the persisted names are in the set | `tests/host/test_restore_set_shipped.py::test_the_thing_cells_are_in_the_standalone_set_too` | `thnext` must stay out of the set, or join the tuple |
| the relink is world.py's | `tests/fj/test_leaf_lists_fj.py`: 8 moves (16 ops) in ONE image, the arrays compared with world.py's own code after every op; the sequence is classified from the model's state and must cover link into empty/head/middle/tail and unlink of the only element/head/middle/tail | a link that always prepends, and an unlink that leaves the moved thing's link, are both caught |

## As built

`build/doom_e1m1_blocked30.fjm`, sha256 `0dd3806016af68cd`, from the ship-gate 1b line unchanged (blocked27's heat
list); the source changed, so the counts cache recounted (17,496 groups after alias merging, 336,374
tables) and the build took 7,234 s. Rebuilt from the same line at the branch head, HITting the cache
that count wrote: the same sha256 and the same label table (`blocked30r_build.log`, 4,769 s) --
VERIFIED byte-identical. The row and the verdict are in `docs/gp-ledger.md`.

- **The first build was stopped.** Persisting `sshead` -- a byte array -- made
  `selfreset.emit_reset_part` refuse its own set after pass 1: the persisted words left the set,
  then the byte-array pass asserted they were still in it (without that assert the reset would
  have zeroed the persisted lists every frame). The P1.5 pre-build review found it while the first
  build was in pass 1; the byte-array pass now skips persisted names (87c2c75, with
  `test_persist_keeps_a_byte_array_out_of_the_reset`: it fails on the parent with the build's own
  assertion), and the second build passed.
- **Gates**: m2_std_gate PASS, m3_gate PASS (`blocked30_gates.log`); gamespeed's trail PASS with
  both controls rejected (`blocked30_gamespeed_trail.log`) -- the same trajectories; B0 on set v2
  state- and pixel-exact on every frame (`blocked30_b0_v2.log`).
- **Ops**: `sim.bind_things` fell from 401,796 ops a frame to 0 and the M1 reset from 226,935 to
  94,229 on gamespeed's ten games (profx, `blocked30_phases.log`) -- the reset no longer restores
  the lists' heads, the bindings and the positions. The binding fell 462,400 (-3.1%); the render
  walk rose 68,316 and collision 2,818: placement (the changed table counts re-rolled the pins),
  not work.
- **Speed**: msframe NOT SEPARATED from blocked29 -- 62.8 against 64.2 ms/frame, faster in all 5
  pairs, median x1.021, under the 3% rule. It ships under the ship gate's "foundation for P3"
  clause: the per-move relink is what P3's monsters call.
- **Size**: 36,208,972 words, 26.98% of 2^27 (was 27.35%, -497,816 words; `blocked30_poolmap.log`).
- **Pins**: 20 of 20 hot words pinned (`blocked30_pinreport.log`), 4 re-keyed by their heat key as
  in P1.2; 14,083 of the list's 35,894 hot sites matched.
