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

(filled after the build: the binary, the gates, the ledger row, size, the pin report.)
