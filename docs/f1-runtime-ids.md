# F1 item 12 -- runtime thing ids past 254 (design note, M8, 2026-10-17)

Read-only design (nothing run). Per-map numbers are the survey's (`docs/levels/*.md`); stl costs are from
`docs/handoff-fj-wide-pointers.md` 13 and `src/fj/m1_reset.fj`. **Every op / word / day figure is UNVERIFIED.**

## 0. Findings

1. **"254" is six fj limits, not one** -- each assumes a runtime id < 256: the 8-bit list cells (`sshead`, `thnext`);
   the two-level `thsel_leaf` select; `TD_KEY_ROWS = 256`; the 2-nibble rank compare in `sim.rank_key` (`td_rk`); the
   2-nibble `dr_t` in barrelcode's drop link (`assert d < 256`); the `ll_*` 2-nibble registers in `sim.leaf_link` /
   `leaf_unlink`. Widening only the cells would leave E1M5's drops (ids 249..369) mis-ranked and mis-selected.
2. **The model's lists bind on no surveyed map**: `World`'s `leaf_head` / `mob_next` use the MOBILE index (`nmobile =
   nmon + 10`, 199 on E1M5); only the fj id space (WAD runtime things, then the pools, then the drops) passes 254. The
   oracle's mirrors are width-free Python.
3. **The sums:** E1M5 370 (239 + 10 + 121 droppers); E1M9 244 (10 under); E1M2 228; E1M8 10; E1M3 / E1M4 refused by
   their unknown thing types (nt 240 / 216; sums UNVERIFIED, ~337 for E1M3).
4. **Baking more things cannot reach 254 on E1M5**: its floor with no non-monster runtime thing is 189 + 10 + 121 = 320.
5. **flipjump 1.5.1 already has the tool**: the dual decoder table (`hex.pointers.PTR_WIDE_BITS`, `runlib.fj`) and
   `hex.read_cell` / `hex.write_cell`. A 12-bit list entry stays ONE cell at the same stride (bits dbit..dbit+11 of the
   jump word, as `byte_array_decl`'s `;v * dw` already writes); only the accessor widens (the wide read flips dbit+12
   into a 4,096-entry table at op 4,096); narrow reads keep their cost; a program without `-D` lays no table (E1M1's
   stl untouched). The 2026-09-03 16-bit pack died only because its 65,536-entry table landed in the hot block; a
   12-bit table ends at op 8,192, below the hot block's `pad 16384` anchor.

## 1. The inventory (every reader / writer of a runtime id or a list cell)

- **`src/fj/sim.fj`:** `thing_pos_read` / `thing_int_read` / `thing_pos_first` (w/4, no limit); `thing_load`
  (`sp_ti`, w/4); `leaf_link` / `leaf_unlink` (2-nibble `ll_enc` / `ll_v` / `ll_nxt`, `read_byte` / `write_byte` on
  `sshead` / `thnext`); `bind_things` (hosted; `hv` / `tv` 2 nibbles, bytes); `thing_pass` (`read_byte`);
  `thing_pass_depth` (7 / 9 params; `read_byte` `td_head` / `td_e`, `td_keys` rows `t << 4`); `rank_key` (`hex.cmp 2`).
- **`src/fj/m1_reset.fj`:** `m1.zerobyte` (8 bits). `frame_render.fj`'s `thing_load_cold` works on the ROW (already
  derived).
- **Emitters:** `monstercode.p31_parts` (`ntm` assert, the two-level `thsel_leaf`), `TD_KEY_ROWS` / `P33_DECLS`,
  `D3_DECLS` / `rank_threshold` (`td_rk` 2 nibbles); `things.LIST_MAX_THINGS`, `spawn_leaf_lists`, `byte_array_decl`
  (`v < 256`), `LEAF_LINK_DECLS`, `skill_level_start`; `wall_renderer.restart_lines` (`m1.zerobyte`, per-skill raw flips
  of 8 bits), `_moving_thing_tables`' asserts, the `thnext` extent (`2*nt`), `byte_array_decl` of `sshead` / `thnext`;
  `barrelcode` `dr_t` (2 nibbles, `d < 256`). w/4 or constant-offset users need nothing (projcode `pw_t`, knockcode /
  monstercode `mm_tw`, lootcode `rtu_t`, the `thpos_rt + 16*t` constants); `hurtcode.turn_lines`' `dt_t` is a monster
  slot's row (< nt <= 255 on every surveyed map: keep its assert).
- **Model / reset / build / probe:** `world.build_schema` (`nmobile <= LIST_MAX_THINGS`; 8-bit `leaf_head` / `mob_next`
  in the mobile space); `selfreset.byte_arrays` (`m1.zerobyte` over `sshead` unless persisted -- the game tier persists
  it); the build's assemble sites (no `defines_file` today); `probe.Cell` kind `'byte'`; `hurt_gate.leaf_list_cells`,
  `b0_scenarios`; the survey's row.

## 2. Options

| option | ops/frame (big map) | words | E1M1 identity | faithful | effort |
|---|---|---|---|---|---|
| **A1. 12-bit list cells through the dual table** (`PTR_WIDE_BITS=12`), behind `Config.LIST_ID_BITS` (8 on E1M1) | list reads 9@ -> 11@ (~+90 a head read + next reads), writes ~+270 at relinks, a third select level ~+15 a thing load: est. +40..70k (~0.3%) | table 4,096 + pad <= 3,584 ops + wider accessors: est. +60..80k | `fj_consts` LIST_WIDE 0 / LIST_NIB 2, no `-D`; select and TD rows derived | exact | 2-3 days |
| A2. two byte cells an entry (or a hi-nibble array) | +1 dereference a read: est. +130..210k | more | more text sites | exact | 3-4 days |
| B. bake more things | a little lower | -- | a per-map mask rule | only where a leaf stays homogeneous | **insufficient** (E1M5's floor 320) |
| C. a drop pool smaller than the droppers | neutral | smaller | a rule E1M1 never meets | **no** (DOOM has no drop limit; E1M5 would get ~4-5 slots) | 1.5 days + an owner decision |
| D. two list families split by depth rank | a second head read a leaf: est. +130k | two walks | new macros | exact | 4-5 days, and family 1 still caps nt + 5 at 254 (fragile) |

`PTR_CELL_BITS=12` globally is rejected (it taxes every dereference: the wide-pointers doc's 13.4 lesson).
**Recommendation: A1** -- the cheapest faithful option, no layout or stride change (no `cur_ssp`, restore-span or
`thss_rt` change), a limit of 4,094 ids; its risks are the defines plumbing and the table placement (5).

## 3. The change list (A1)

- **`config.py`:** `LIST_ID_BITS: int = 8`; `LIST_NIB`, `LIST_WIDE` (asserted in {8, 12}) into `constants()`;
  `emit_fj_defines(path)` writes `hex.pointers.PTR_WIDE_BITS = 12` when wide; `MAP_CONFIG["E1M5"]["LIST_ID_BITS"] = 12`
  (E1M3 / E1M4 once measured). **Build:** `build.py` (3 assemble sites), `harness.assemble_fjm`, `build_labeled.py` /
  `build_blocked.py` pass `defines_file=` (fan-out, rule 5; check `assemble_blocked` forwards it).
- **`things.py`:** `list_max(bits)`, `list_bits(n)`; `spawn_leaf_lists(max_things=)`, `byte_array_decl(bits=)`,
  `leaf_link_decls(nib=)` (the old names kept as their 8-bit values).
- **`world.py`:** `leaf_head` / `mob_next` at `list_bits(lay.nmobile)` (8 on every surveyed map: schema unchanged).
- **`monstercode.py`:** `p31_parts(list_bits=)`, `ntm <= list_max(...)`; a THIRD select level only when `ntm > 256`
  (`thsel_leaf: sim.jump16 sp_ti + 2*dw, thsel_g<g>...`; the h-level text as today); `td_key_rows(n)`, `p33_decls`,
  `d3_decls(nib)`.
- **`barrelcode.py`:** `dr_t` at `nib`, `d < 16**nib`, `ndrop < 256` (`dr_live` 2 nibbles).
- **`wall_renderer.py`:** `restart_lines` with `m1.zerocell12` and `range(LIST_ID_BITS)` flips when wide; the asserts by
  width; `byte_array_decl(bits=)`; `p31_parts(list_bits=)`.
- **`selfreset.py`:** assert a wide `sshead` is persisted (only the game tier has wide lists).
- **`src/fj/sim.fj`:** NEW `sim.lread dst, ptr` / `sim.lwrite ptr, src` (`rep(1-LIST_WIDE) hex.read_byte` +
  `rep(LIST_WIDE) hex.read_cell`); every list access in `leaf_link`, `leaf_unlink`, `bind_things`, `thing_pass`,
  `thing_pass_depth` through them and every 2-nibble id width -> `LIST_NIB` (at LIST_WIDE 0 the exact ops of today).
- **`src/fj/m1_reset.fj`:** NEW `m1.zerocell12 c`.
- **Probe / gates:** `probe.Cell` kind `'cell'` (n nibbles); `hurt_gate` / `b0_scenarios` at `cfg.LIST_NIB`; the probe's
  selftest plants 0xABC (read through `'cell'` n=3; as `'byte'` it must differ -- control).
- Nothing in projcode, knockcode, lootcode, damagecode, monsterdecide, monstermove, frame_render.fj, reference_model,
  monsters, combat.

## 4. Proof

**`tests/fj/test_wide_ids_fj.py`** (RUN the fj at `LIST_ID_BITS=12`, the emitters' own functions, one image a case):
(1) relink with NT = 300, ids {0, 1, 254, 255, 256, 257, 299}, all link / unlink cases straddling 255/256, fj's lists
against `World._list_insert` / `_list_remove` after every op (+ coverage of ids >= 256); (2) the depth walk with ids
250..262 and rk0 at 0xFE / 0x102 against `rank_depth_key`; (3) the select at ntm = 300 (0, 15, 16, 255, 256, 271, 299
print themselves; 300 reaches `thsel_none`); (4) restart's list fragment on cells planted with 0xFFF / 0x100 / 0x0FF /
0x123 against `skill_level_start`; (5) `drop_link<k>` with `d >= 256`.
**R9 controls**, each with its named symptom: `nib2` (leaf_link's width back to 2), `narrow` (lread's wide arm a
read_byte), `rank2`, `select2` (the third level dropped: 256 prints 0), `zero8` (zerocell12's third xor dropped),
`drt2`. Parameterize `test_leaf_lists_fj` / `test_thing_pass_depth_fj` over {8, 12}.
**E1M1 identity:** `emit_baseline --check` (+ `--selftest`; it does not hash `fj_consts.fj`); NEW
`scratchpad/cr/fj_lib_identity.py --ref HEAD [--selftest]` (one probe program instantiating every touched macro at 8
bits, against the ref's and the tree's `src/fj`: equal .fjm sha256; R9 a one-op mutation differs and the 12-bit config
differs); one game build at the rung's end equal to the previous binary; recommended (heavy, solo): E1M1 built with
`LIST_ID_BITS = 12` forced, state- and pixel-exact on `fight_gate` / `die_gate` (class S, ops rise).

## 5. Survey, docs, risks

- **Survey:** the row becomes "runtime ids (list cells, Config.LIST_ID_BITS)" against `list_max(map_cfg(..).LIST_ID_BITS)`,
  an INFO row "list id bits needed" = `list_bits(n)` (mismatch with MAP_CONFIG reported), the ids guard on the
  unknown-type-filtered World (E1M3 / E1M4 print a number). Expected: E1M5 OK at 12; E1M9 OK at 8 (244: INFO, 10 under).
- **`docs/f1-big-map-widths.md`:** 0.3 and 13 point here; 12 gains **F1.5 runtime ids** (item 12; gates
  `test_wide_ids_fj` + controls, `fj_lib_identity`, `emit_baseline`, the E1M1-at-12 class S run; ~2-3 days): F1 ~8-11 days.
- **Risks:** the table placement (init + the 4,096-op table + pad may pass op 16,384 -- then the hot block anchors at
  32,768, a placement change on big maps only; the 8,655-op init figure is 2026-09-03's); flipjump's tests name the
  (8, 16) and (12, 16) configs, not (8, 12) -- the new harness is its first run; `build_blocked` must forward the
  defines; `thnext`'s `2*nt` extent fits E1M5 (370 <= 478), but a map with small nt and many drops needs
  `max(2*nt, nt + nmob)` (identical on E1M1).
