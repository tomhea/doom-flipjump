# HANDOFF: M14.5 — BAKE WHAT DOESN'T MOVE, POINT AT WHAT DOES

Owner directive (2026-08-14), after the 27M sprite package shipped:

> a hybrid combination of [baked + is_visible (only for those that need it)] and [runtime sprites
> which based on baked whenever they can] can be the optimal solution. also — make the runtime
> memory access and the is_visible mem access a fixed-address register access — as those get
> accessed many times … I want you to also look at all the other pointer access stuff, and see if
> something is read-many write-some or the other way around … Also — the table of sprites … I'd
> like you to think of the simplest ways to show these sprites — but in a zero-costing way of
> drawing … also — you stated a linked list — is it the best optimized data structure?

⚠ **The glyph half of that directive was WITHDRAWN by the owner on the same day**, once the draw
path was measured and showed no speed difference: *"alright, drop the glyphs programme from the
plan."* §4 records why, so the idea is not re-invented. **The rest of the directive stands.**

Everything here inherits `docs/handoff-perf.md`'s evidence rule: **no figure without a measurement
and a command**, every number tagged MEASURED or DERIVED, and a difference is only a measurement if
both sides are controlled to be comparable (§0 of that document, sixth clause).

---

## 0. ⚠ THE CORRECTION THAT MOTIVATES THIS MILESTONE

The perf campaign recorded "unrolling to remove pointer math loses at this scale, +1,929,402"
(`handoff-perf.md` §10.12). **That experiment was mislabelled and the conclusion does not
generalise to baking.**

`sim.bind_one` kept every part of the runtime machinery — the binding read, the dirty compare, the
point location, the linked-list insert — and replaced only the *address arithmetic* with baked
addresses, then paid for 251 inlined copies of that unchanged work. It measured the cost of
**unrolling a loop**, not the cost of **baking a thing**.

Baking a thing is a different thing entirely, and it is already measured, twice:

| | median | source |
|---|---|---|
| base renderer, no things | 20,941,091 | MEASURED, `sweep_base_nothings.csv`, gated byte-exact ×4 |
| + 251 sprites **BAKED** (pre-M14 path) | 28,193,396 | MEASURED, `sweep_base_today.csv`, gated byte-exact ×4 |
| + 251 sprites **RUNTIME** (M14 table) | 35,293,677 | MEASURED, `sweep_m14_rowrule.csv`, gated |

**Baked sprites cost 7,252,305; the same sprites through the runtime table cost 14,352,586 —
roughly half.** ⚠ The runtime figure is measured against the *dec-wire* floor, so it also carries
the state wire and `player_sim`; those are near-zero at zero things but not exactly zero, so the
claim is "roughly half", not a ratio to three digits.

Binary size agrees, and the owner's intuition was right: the baked build carries all 251 things in
**14,360,731 − 11,938,275 = 2,422,456 bytes**. ⚠ There is no M14-with-zero-things build, so the
runtime side of that particular comparison is not clean — **build one before quoting a size ratio.**

---

## 1. WHY BAKED IS CHEAPER — the mechanism, not the vibe

**Baked = per-thing CODE. Runtime = shared CODE + per-thing DATA.**

`subsector_action`'s baked branch emits a call site *for each thing, physically inside its leaf*,
with an `xor_by` block holding all thirteen sprite registers as compile-time constants. Which leaf
a thing belongs to is compile-time too, because the code lives there.

The runtime branch emits ONE shared `thing_pass` per leaf. Shared code cannot inline anything, so
every per-thing datum becomes an indexed read — and in FlipJump an indexed read is not an addressing
mode, it is **self-modifying code**: `hex.pointers.set_flip_and_jump_pointers` writes the target
address into a flip/jump pair and jumps through it.

MEASURED (`opprof.py --m14`, spawn frame, the binary sha256-identical to the swept one):

```
hex.pointers.set_flip_and_jump_pointers  ->  4,763,368 + 2,315,106 = 7,078,474 ops = 12.7% of frame
hex.xor_by (the baked-constant path)     ->                            138,254 ops
```

That ratio is the whole argument. A baked constant is an immediate XOR; a runtime read builds an
instruction and executes it.

---

## 2. THE POINTER AUDIT — read-many vs write-many, and which are fixable

⚠ **"Fixable" means the INDEX is compile-time somewhere.** A pointer whose index is genuinely
runtime (a screen column from the projection) cannot become a fixed address, and no amount of
cleverness changes that.

| structure | read | write | index | verdict |
|---|---|---|---|---|
| `sshead[ss]` | 1× per visited leaf | 1× per thing | **read: COMPILE-TIME** (the leaf knows its own `s`); write: runtime (`ptss`) | **FIX THE READ** — §3.2 |
| `thnext[t]` | 1× per thing walked | 1× per thing (bind) | runtime both | only removable by removing the list — §5 |
| `thpos[t]` | 1× per load | wire, **already fixed-address** (`hex.input 8, thpos_rt + i*16*dw`) | read runtime | baked things do not read it at all |
| `throw` / `throwc` | 1× per load | **never** (static data) | runtime | **read-many / write-NEVER — the worst case, and baking removes it entirely** |
| `sprlt` | 1× per drawn thing | never | runtime | baked: becomes a constant |
| **`is_visible` (new)** | 1× per thing per frame | rare (host → wire) | **COMPILE-TIME at a baked call site** | **fixed-address by construction** — §3.3 |
| `drawn[x]`, `sprflag[x]`, `spslot[x]` | many per frame | ~once per column | runtime `x` (projection output) | **NOT fixable** |
| `colst[x]` fields | many | many | runtime `x` | **NOT fixable** |
| column run-streams (`stream_render`) | sequential `_and_inc` | sequential | inherently sequential | **NOT fixable**; a stream's length is runtime |

**Two conclusions.**

1. The single most wasteful pattern in the program is **`throw`/`throwc`: read every frame, written
   never.** A barrel's sprite width has not changed since the WAD was authored, yet the runtime path
   fetches it through a constructed pointer on every frame it is reached. Baking is not an
   optimisation here, it is the removal of a mistake.
2. `stream_render`'s 59 `_and_inc` accesses are the other large family and they are **not** a defect
   — a run-list walk is the right structure and its length is genuinely runtime. Do not "fix" them.

⚠ **Do not attempt to make `drawn[x]` fixed-address by unrolling the column loop.** That is
precisely the shape that measured +1,929,402 in §0, and the repo has a second instance
(`inline_side=True`, +0.42M). The layout tax beats the pointer saving at this scale.

---

## 3. THE ARCHITECTURE

### 3.1 Three classes of thing, not two

| class | examples | position | leaf | mechanism |
|---|---|---|---|---|
| **STATIC** | trees, columns, rubble, stalagmites | never changes | never changes | fully baked, no wire, no list |
| **STATIC + VANISHABLE** | pickups, barrels (until destroyed) | never changes | never changes | baked + a 1-nibble `is_visible` at a **fixed address** |
| **DYNAMIC** | monsters (M16 AI) | changes | **changes** | the runtime path as it exists today |

The middle row is the owner's insight and it is the one the current code cannot express: today a
medikit that must disappear when picked up is forced onto the full runtime path, paying a table
read, a position read, a binding and a list insert every frame — to express one bit.

**Only a thing that changes LEAF needs `bind_things`.** That is the dividing line.

### 3.2 `sshead` read at a baked address

`thing_pass` currently opens with `hex.set w/4, hq, sshead` + `hex.ptr_index hp, hq, cur_ss` +
`read_byte`. But `subsector_action(s)` knows `s` at emit time, so the leaf's list head is at the
compile-time address `sshead + s*2*dw`.

```
hex.if0 2, sshead + {s}*2*dw, ss{cid}_nothings   // 0 = empty (the zero-init sentinel)
```

⚠ **This was priced ONCE and rejected** (`handoff-perf.md` §5a): `sim.thing_pass`'s own cost is
2,092,711 at spawn and the leaf-proportional part could not be separated from the per-thing part
(adding `leaves` to the 260-frame regression moved neither R² nor the residual). **Re-price it under
the hybrid**, where the dynamic set is ~53 things and the per-thing part shrinks, so the per-leaf
part is a much larger share of a much smaller number.

### 3.3 `is_visible` — read-many, write-once, fixed address

```
thvis: hex.vec {n_vanishable}          // one nibble each, zero-init
// at the baked call site, index i is a compile-time constant:
hex.if0 1, thvis + {i}*dw, ss{cid}_thing{ti}_skip
```

One 1-nibble test at a compile-time address — the same shape as the `tstop` guard already emitted
there, so the marginal cost is ~one existing guard. The host writes it via the wire at fixed
addresses exactly as the position array is already filled (`hex.input`, `+ i*16*dw`), which is
**precedent that already ships and is gated**.

⚠ The oracle needs the same bit or the mirrors diverge — one shared list of "hidden thing indices"
threaded into `render_wall_frame`, in the same commit.

### 3.4 Runtime things reuse baked data where they can

A monster's *art metrics* (`sp_left`, `sp_w`, `sp_hh`, `sp_tzmax`, `sp_tzmax2`, `sp_base`, `sp_dw`)
are properties of its TYPE, not its identity, and they never change. Only position, leaf and
`sp_lt` are dynamic.

So `throw`/`throwc` need not be indexed by THING at all — index them by **TYPE** (5 monster types
today against 251 things), or dispatch on type to a baked constant block. ⚠ This is a
`read_table_packed` whose stride is its row width (§10.10 of the perf handoff) — a type-indexed
table is a smaller table, not a cheaper read, so **measure whether the win is real** before assuming
it.

---

## 4. ~~THE ZERO-COST GLYPHS~~ — RETIRED (owner, 2026-08-14)

**Dropped from the plan. Restore the hidden things with their REAL ART instead.**

The programme rested on a normal-graphics intuition — simpler art draws faster — and the code says
otherwise. Three rounds of glyph design were spent before the draw path was actually read; this
section is kept, short, so nobody re-derives it.

**WHY IT DIED.** MEASURED (`opprof.py --m14`, spawn):

```
stream.sprite_runs -- the ONLY run-proportional work   284,716 ops = 0.5% of the frame
per SCREEN column, in thing_record_body's col_loop:    u DDA, read_byte drawn, read_byte sprflag,
  slot select, mul_const, rep(blkshift) shl_bit, ptr_index into sprbank, TWO header reads
  -> THREE POINTER READS, and NONE of it looks at the art
```

A textured sprite and a 3-band glyph cost the **same** per screen column. Runs differ, and runs are
half a percent of the frame. **There is no meaningful speed difference.**

**AND THE ALTERNATIVE IS CHEAP.** MEASURED, emitting with `THING_SPRITE_ALL`:

```
wall bank only                 95,671,818
shipped 13 classes            101,366,687   (sprites  5,694,869)
ALL 56 classes, REAL ART      109,214,892   (sprites 13,543,074)
=> every hidden thing back with its own sprite: +7,848,205 chars, +6.9% of the program
```

**TWO FACTS WORTH KEEPING**, because they will come up again:

1. **Vertical scaling is free; horizontal is fixed.** The bank bakes per HEIGHT BUCKET, so a
   procedural shape is crisp at any height — nothing is stretched vertically. But
   `u = min(dw-1, frac>>16)` and **`sp_dw` is a per-TYPE constant, not per-bucket**, so an N-column
   sprite always renders as N vertical bands however close the player stands. Exact for
   rectangle-based shapes, crude for organic ones.
2. **Screen columns come from the WORLD footprint (`sp_left`/`sp_w`), not from the art's column
   count (`sp_dw`).** Shrinking the art shrinks the BANK; only shrinking the world footprint
   shrinks the per-frame work — and that visibly narrows the object.

**THE ONE THING THAT WOULD REVIVE THIS: ASSEMBLE TIME.** It is the real constraint and it is
unpriced for the M14 config. The dec baseline went **399s with no sprites to 1583s with all of
them**, and `--things` builds are already ~20-25 min. If restoring all 56 classes pushes a build
past an hour, glyphs become worth it **for the build, not for the frame**. ⚠ Measure that with ONE
build before writing another glyph.

Artefacts, kept for reference only: `scratchpad/glyph_sheet.py`, `scratchpad/glyph_fast.py`,
and their PNGs.

## 4b. ⚠ THE GAP THAT WOULD HAVE SHIPPED A BUG: MERGED ITERATION ORDER

**A leaf that holds BOTH baked statics and dynamic monsters must visit them in an order both
mirrors agree on, and today's order cannot be preserved.**

Within a leaf the oracle iterates `things_by_ss[ss]`, built by appending in WAD order, so statics
and monsters are interleaved. fj cannot interleave them: the baked things are *code* emitted at the
call site and the dynamic ones are a *runtime list*, so the only orders fj can produce are
"all baked, then all dynamic" or the reverse.

This is not cosmetic. Arrival order decides:
* **which sprite claims slot A** (the write-once near fragment) and which gets slot B — a monster
  behind a barrel swaps depth with it if the order flips;
* **`n_thing` / `n_mon`**, and therefore `degfl`'s graduated acceptance, which raises the min-size
  bar after the first SOFT accepted things — a different order changes *which* far things are
  dropped;
* **`n_hd`** (the HD bake budget), spent in visit order.

⚠ **So the oracle must adopt the same split, in the same commit.** `render_wall_frame`'s per-leaf
loop becomes "statics of this leaf, then dynamics of this leaf", matching the emitter. That is a
BOTH-MIRRORS change of the kind §7.1 of `handoff-perf.md` describes, and **it will move pixels**
wherever a static and a dynamic thing overlap in the same leaf — a deliberate, ownable picture
change, not a regression.

⚠ **The gate will catch it either way** — that is what phase 1 is for — but it will catch it as a
mysterious multi-hundred-pixel diff late in a 25-minute build. Decide the order FIRST, write it in
both mirrors, and record it here.

### ✅ RESOLVED — bake only HOMOGENEOUS leaves, and the picture stays byte-identical

MEASURED, no build (`scratchpad/m145_order_check.py`, and the split count beside it):

```
leaves holding things                : 132
leaves holding BOTH kinds            :  15
static/monster pairs that would SWAP :  14
statics total                        : 198
  ... in MIXED leaves                :  22  (11%)
  ... in HOMOGENEOUS leaves          : 176  (89%)
```

**So bake a static thing only when NO monster shares its leaf.** The other 22 stay on the runtime
path. Then **every leaf is either all-baked or all-runtime**, the per-leaf order is WAD order in
both cases exactly as today, and **the frame is byte-identical** — for 89% of the baking win. The
picture change in §4b simply does not have to be taken.

⚠ **THE ORACLE'S RULE MUST BE "BAKED FIRST, THEN RUNTIME" — NOT "STATIC FIRST, THEN DYNAMIC".**
Those coincide today only because of the split above. Keying the oracle on *static-ness* would
reorder the 15 mixed leaves and diverge immediately; keying it on *baked-ness* is order-preserving
by construction. **The baked/runtime classification is therefore an SSOT both mirrors read**, in the
same way `THING_SPRITE` is the SSOT for drawability.

⚠ **THIS CLASSIFICATION IS NOT STABLE UNDER M16.** Monsters move, so a leaf that is homogeneous at
level load stops being so the moment a monster walks into it — and then a baked static and a runtime
monster DO share a leaf, and the order becomes baked-then-runtime rather than WAD order. That is
fine and needs no fix, because both mirrors follow the same rule and the oracle IS the reference —
but it means **the byte-identical guarantee holds for the spawn configuration, not for all of M16's
play**. Do not carry "byte-identical" forward as a property of the design; it is a property of the
starting positions.

## 5. IS A LINKED LIST THE RIGHT STRUCTURE?

**For static things: no — and the right answer is no structure at all.** A baked call site inside
the leaf *is* the index. Every byte of `sshead`/`thnext` and every op of `bind_things` spent on a
static thing is pure overhead.

**For dynamic things: the traversal is fine; the REBUILD is the cost.** `bind_things` is MEASURED at
3,294,888 per frame for 251 things and it is **bit-identical at both profiled viewpoints** — a pure
frame-constant, because it re-links every thing every frame whether or not anything moved. It is
per-thing, so with only monsters dynamic it scales down with the count.

⚠ **THERE IS NO UNLINK, AND THERE SHOULD NOT BE ONE.** An earlier draft of this section recommended
a doubly-linked list so a moved thing could be unlinked in O(1). That was wrong, and the owner
caught it: `bind_things` **rebuilds from scratch every frame** — `sshead` is zero-init so there is
nothing to unlink from, and every thing is simply re-inserted. Unlink only exists in the design
where the lists round-trip and are maintained INCREMENTALLY (§5b of the perf handoff), and that
design does not pay once the statics are baked:

* the rebuild is **per-thing** and shrinks with the dynamic set — DERIVED, 3,294,888 × 53/251 ≈
  **~0.7M** for a monsters-only dynamic set (confirm by measuring, it is not a measurement yet);
* but `sshead` is **682 entries no matter how few things there are**, so round-tripping the lists
  costs ~735 entries in and out *regardless*. **The wire cost does not scale down with the dynamic
  set; the rebuild cost does.** §5b gets less attractive as M14.5 succeeds, not more.

**So: keep the singly-linked list, keep the full rebuild, and let baking shrink it.** A forward pass
over ~53 things with no search beats any incremental scheme here, and it needs no new data
structure, no wire format change and no host state.

**Ranking for the dynamic set** (DERIVED from structure, not measured): baked call sites for statics
(no structure at all) > today's singly-linked full rebuild over a small set > incremental
maintenance with round-tripped lists. Revisit only if M16 makes the dynamic set large.

---

## 6. THE WORK ORDER

Each rung is one self-contained commit: build → `m14_gate.py 10 --things` → sweep → record.

1. **Split the thing set into STATIC / VANISHABLE / DYNAMIC** in one SSOT (as `THING_SPRITE` is the
   SSOT for drawability), and route static things back to the baked branch. **This is the whole
   milestone's value; do it first and measure it alone.**
   ⚠ Both `subsector_action` branches must be able to run **in the same leaf** — baked call sites
   for its statics *and* `thing_pass` for its dynamics. Today they are `if/elif`.
   ⚠ `_lines_prune` and `thing_live_subsectors` (M14-a) widened liveness because a thing could walk
   into any leaf. A STATIC thing cannot, so the prune may narrow again for statics — **but only for
   statics**, and a mistake here makes sprites vanish silently, which is what M14-a exists to
   prevent. Keep its `assert_thing_live_survives_prune` guard and its R9 negative control.
2. **`is_visible`** (§3.3), for the vanishable set only.
3. **`sshead` at a baked address** (§3.2) — re-price under the hybrid before building.
4. **RESTORE THE HIDDEN THINGS WITH THEIR REAL ART** — no glyphs (§4 is retired). Their *art* is
   nearly free: **+7,848,205 chars of bank (+6.9% of the program) and nothing per frame**. Restore
   in the cost order `m14_class_cost.py` ranks, sweep after each batch.
   ⚠ **Time the build** as the set grows — assemble time, not ops, is what limits this (§4).

   ⚠ **ALL 198 DOES NOT FIT AT 27M, AND THE PLAN SHOULD NOT PRETEND IT DOES.** The arithmetic,
   from this session's measurements:

   | | ops | source |
   |---|---|---|
   | base renderer, no things | 20,941,091 | MEASURED |
   | 53 monsters, runtime | +4,912,083 | MEASURED (25,853,174) |
   | 198 non-monsters, RUNTIME | +9,440,503 | DERIVED; cross-checks the 9,439,503 sprite-cut delta |
   | **198 non-monsters, BAKED** | **?** | the whole question |

   To fit 27M the 198 baked must cost **≤ 1,146,826 — 0.12× their runtime cost.** The measured
   baked/runtime ratio over all 251 sprites is **0.505**; the optimistic bound for a reject-heavy
   set is ~0.25 (a rejected thing's runtime cost is mostly `thing_load` ≈ 52,755 of ≈ 69,130, and
   baking removes exactly that, leaving the ≈ 17,090 projection). So:

   ```
   198 baked at 0.505  ~4.77M  ->  ~30.6M   |  198 baked at 0.25  ~2.36M  ->  ~28.2M
   ```

   **Both clear the ceiling.** What fits at 27M is roughly **50–100 of the 198** — still far better
   than today's 15. ⚠ These are DERIVED from a ratio measured on the FULL set, not on the
   non-monster subset, so the error bars are wide: **step 1's build measures the real ratio, and
   the restore list must be re-cut from that number, not from these.**

   **The owner's options once step 1 has measured it:** raise the ceiling to ~28–31M and take
   everything; keep 27M and restore the cheapest ~50–100; or spend the difference on the base
   renderer instead (§8 — it is 20.94M with no things at all).
5. **The list decision** (§5) — only once M16's re-binding shape is known.

**Acceptance:** `m14_gate.py 10 --things` PASS (byte-exact ×4, cold-vs-warm identical pixels, N
relayed tics, both vacuity controls non-zero); `m14_basegate.py --rebuild` PASS **and op-identical
to the digit** if the static path is touched (it is shared with the shipped renderer — this caught
nothing last time only because the change was inert); `pytest tests/host -q --deselect …e1m1_flat` →
242; the sweep median reported against the owner's 27M ceiling with min/mean/p90/worst.

---

## 7. ⚠ TRAPS THIS SESSION PAID FOR

1. **A pixel COUNT does not indicate which subsystem moved.** 1766/17/8 px looked "too small for a
   list-order bug" and pointed at the multiplies; `scratchpad/_mulcomm.py` disproved that in seconds
   by TESTING commutativity (8/8 identical). Test, don't reason.
2. **Bake an address only where shipped code already bakes it.** `thnext + i*2*dw` was an assumed
   stride and failed the gate; `thss`/`thpos` were safe because the emitter's own gated wire loops
   already use `+ i*16*dw`.
3. **`hex.read_table_packed nb` takes its STRIDE from `nb`** — it cannot read a prefix of a wider
   row. A lazy tail is a second TABLE. Its cost is linear in the row width.
4. **The assembler treats an unused macro parameter as an error**, so a signature cannot be padded
   to keep call sites stable — dropping a parameter's last use is automatically a fan-out edit.
5. **A proxy that ignores drawn area understates big sprites by ~1.67×** (`m14_class_cost.py`
   predicted 932,100, measured 1,558,963). Calibrate per class shape, not globally.
6. **ONE HEAVY BUILD AT A TIME** (CLAUDE.md rule 1). The `--things` build is ~25 min; `opprof.py`
   with `debugging_file_path` is **4073s and ~8GB RSS** — run it alone and kill the process after,
   or the next tool OOMs (it did).

## 7b. ⚠ THE GUARDS — because "just another if/else" is where these bugs live

Owner: *"that's a good code change maybe its just another if/else. yes, you should take a good
notice and make sure bugs as these won't happen."* The structural change IS small. Each hazard below
gets a control that FAILS LOUDLY, in the spirit of R9 — a check that never fires proves nothing.

1. **`if/elif` → both branches in one leaf.** The two thing branches in `subsector_action` are
   mutually exclusive today. Making them independent is the change. **Control:** an emit-time
   assertion that the union of (baked things emitted) ∪ (things in the runtime table) is EXACTLY the
   drawable set, per leaf and overall — no thing in both, none in neither. A thing silently in
   neither is invisible with no other symptom, which is the M14-a failure mode all over again.
2. **Iteration order (§4b).** **Control:** the M5 pre-count of leaves holding both kinds; then the
   gate. Do not rely on the gate alone to discover the order is wrong.
3. **The prune.** ⚠ **DO NOT narrow `thing_live_subsectors` for statics in M14.5.** It is tempting
   (a static thing cannot walk into a new leaf) and it is a separate, riskier optimisation whose
   failure mode is silent vanishing. M14-a exists because of exactly this. Keep
   `assert_thing_live_survives_prune` and its R9 negative control running unchanged.
4. **`is_visible` vacuity.** ⚠ **M14.5 HAS NO PICKUP LOGIC**, so nothing will ever clear a visibility
   bit and the gate would pass a build whose flag is never read. **Control, and it must be
   TWO-SIDED** (`handoff-perf.md` §11.2): the gate must hide a set of things that are ON SCREEN,
   assert the frame CHANGED, and assert it changed back when they are restored. Counting flag writes
   alone passed a mover set that was entirely off-screen once already.
5. **The shipped/static path.** Any change to `subsector_action` or the shared decls touches the
   renderer `build.py` ships. **Control:** `m14_basegate.py --rebuild` must come back byte-exact AND
   **op-identical to the digit** (51,688,913 / 41,978,565 / 48,915,900 / 39,594,303). It passed last
   time only because the change was inert; it will not be inert here.

## 8. OPEN, AND HONEST ABOUT IT

* **The floor.** The base renderer with zero sprites is 20,941,091 (MEASURED). Everything in this
  milestone is sprite work; none of it touches that floor, and a 12–25M *full game* target must
  eventually attack it. `handoff-perf.md` §1.2c is its decomposition, but it is ONE HEAVY FRAME —
  a median-frame profile does not exist.
* **M16's cost is entirely unmeasured**: per-tic re-binding for ~53 movers, AI thinkers, sight
  checks, and animation frames × rotations. The bank arithmetic that exists: monster sprites are
  **2,498,023 chars for 4 images (~624,505 each)**; ×8 rotations would be ~+17.5M chars, ~+15% of
  the emitted program — but DOOM mirrors rotations (≈5 distinct, not 8) and animation frames
  multiply on top. **Assemble time cannot be extrapolated**: the one clean data point is 399s with
  no sprites vs 1583s with all of them, and the assembler is ~cubic in unrolled ops. Bake ONE
  monster's rotations and time it before committing.
* **The metric.** The sweep feeds integer view positions and M14 made the program fractional — no
  frame the player sees is at a swept position (`handoff-perf.md` §12.10). fps has never been
  measured (§12.7).
