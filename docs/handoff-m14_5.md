# HANDOFF: M14.5 — BAKE WHAT DOESN'T MOVE, POINT AT WHAT DOES

Owner directive (2026-08-14), after the 27M sprite package shipped:

> a hybrid combination of [baked + is_visible (only for those that need it)] and [runtime sprites
> which based on baked whenever they can] can be the optimal solution. also — make the runtime
> memory access and the is_visible mem access a fixed-address register access — as those get
> accessed many times … I want you to also look at all the other pointer access stuff, and see if
> something is read-many write-some or the other way around … Also — the table of sprites … I'd
> like you to think of the simplest ways to show these sprites — but in a zero-costing way of
> drawing … also — you stated a linked list — is it the best optimized data structure?

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

## 4. THE ZERO-COST GLYPHS

⚠ **FIRST, THE CORRECTION.** A simpler picture does **not**, by itself, make a hidden sprite cheap.
MEASURED: 94.1% of loaded things are rejected before anything is drawn (22,146 loaded, 1,314 drawn
over 260 frames). The cost is *deciding not to draw*, not drawing. **Baking is what makes them
cheap; the glyph is what keeps them cheap once they are visible.**

DERIVED floor per visible baked thing: the projection still runs. From the spawn profile
`frame.thing_record_body` is 3,127,430 over 183 loads ≈ 17,090 per thing, against ~69,130 per
runtime load. So a baked glyph thing should land near a quarter of today's cost — **DERIVED from
two measurements, and the M14.5 build must confirm it.** Not zero. Nothing here is zero.

### ⚠ 4-0. WHAT A GLYPH ACTUALLY BUYS IN fj — the correction (owner, 2026-08-14)

> *are they really easy to draw in fj, or is it just simple-to-draw in normal-graphics machinery*

**The latter, mostly. "Few colours" is a normal-graphics intuition and it optimises the wrong axis
here.** Read the real path before designing any more glyphs:

* **Record time, per COLUMN** (`thing_record_body`'s `col_loop`): `read_byte drawn_v`,
  `read_byte sprflag_v`, slot select, `mul_const` + `rep(blkshift) shl_bit`, `ptr_index` into
  `sprbank`, `read_byte run_r0`, `read_byte run_last`, the y clamps, the slot store. **Three pointer
  reads and a shift loop, and NONE of it depends on the run count** — only the block HEADER is read.
* **Emit time, per RUN** (`stream.sprite_runs`): `read_byte_and_inc rel`, `read_byte_and_inc tex`,
  ~8 ops, `byte.emit` + `cm.emit`. This is the only run-proportional part.

MEASURED at spawn (`opprof.py --m14`):

```
stream.sprite_runs      48,014 direct + 236,702 wflip = 284,716   0.5% of a 55.8M frame
frame.thing_record_body                                3,127,430   5.6%
```

**The run-walk is an order of magnitude smaller than the per-column record work it hangs off.** So
runs are SECOND-ORDER. The first-order driver is **how many COLUMNS the sprite covers on screen**,
which is set by the projection, not by the art — a 5-wide glyph and a 5-wide sampled sprite cost
about the same to record.

⚠ **One fj-specific freebie with no normal-graphics analogue:** `hex.if0 2, run_last, col_next`
short-circuits a **fully transparent column** before the rest of the header work. Empty columns are
nearly free, so a SPARSE glyph beats a solid one of the same width. Design for empty columns, not
for few colours.

**So the honest division of labour, and it is not what §4 originally implied:**

| tool | fixes | evidence |
|---|---|---|
| **BAKING** | **ops** — removes the load, the table reads, the binding | 7,252,305 baked vs 14,352,586 runtime |
| **GLYPHS** | **the BUILD** — bank size, binary size, assemble time | bank is 5,694,869 chars for 12 images; 399s vs 1583s assemble |

Glyphs are what make it *affordable to bake 176 statics* without the bank exploding. They are not
an ops optimisation and must not be sold as one.

Secondary design rule (real, but second-order): cost per run is ~2 pointer reads at emit, and bank
size is ~`columns × 32 buckets × (2 + 2×runs)` bytes — so runs drive the BUILD more than the frame.

Proposals rendered at `scratchpad/glyph_sheet.png` (`scratchpad/glyph_sheet.py`), each drawn in that
class's own dominant palette colours sampled from its real sprite, so it still reads as itself:

| sprite | n | glyph | runs/col |
|---|---|---|---|
| BON1 health bonus | 30 | 2×4 dot | 1 |
| BON2 armour bonus | 22 | 2×4 dot | 1 |
| BAR1 **barrel** | 22 | 3×6, banded top+bottom | 3 |
| SMIT stalagmite | 18 | 5×5 triangle | 1 |
| SHEL shells | 18 | 3×3 box | 3 |
| TRE2 large tree | 15 | 5×6 canopy + trunk | 2 |
| TRE1 small tree | 12 | 3×5 canopy + trunk | 2 |
| ROCK rubble | 8 | 4×3 | 1 |
| COLU column | 7 | 3×6 + base | 2 |
| STIM stimpack | 6 | **5×5 PLUS** (the owner's example) | 1 |
| SBOX shell box | 5 | 4×3 banded | 3 |
| AMMO clip box | 4 | 4×3 banded | 3 |
| ELEC tech pillar | 4 | 3×6 + cap | 2 |
| CLIP ammo clip | 3 | 2×2 | 1 |
| ARM1 green armour | 2 | 5×5 shield | 1 |
| ARM2 blue armour | 1 | 5×5 shield | 1 |
| MGUN chaingun | 2 | 5×3 bar | 2 |
| LAUN rocket launcher | 2 | 5×3 bar + tip | 2 |
| BROK rocket box | 2 | 3×3 striped | 1 |

⚠ **AWAITING PER-ROW APPROVAL.** The 3-run rows (BAR1, SHEL, SBOX, AMMO) are the expensive ones;
if the owner wants them cheaper, drop the band and they become 1 run.

### 4a. ⚠ A GLYPH MUST BE A PROCEDURAL SHAPE, NOT A BITMAP (owner, 2026-08-14)

> they are about 10px total — what if they are close by, how would they look? the same?

**No, and the sheet above is misleading on exactly this point.** The grids are bitmaps at one size.
The sprite bank bakes a run-list PER HEIGHT BUCKET (`SPRITE_HEIGHT_BUCKETS = 32`), so a 5-row glyph
on a barrel two units away is stretched across ~70 screen rows — **14-pixel blocks**. That is the
"closer sprites seem very pixelated" complaint that caused `SPRITE_RUN_CAP_HD = 24` and the
full-res HD bake to exist; shipping a bitmap glyph would walk straight back into it.

**Define each glyph by PROPORTION and let every bucket bake it at that bucket's own resolution:**
a plus whose arm is ⅕ of the height, a barrel whose bands are the top and bottom ⅙, a tree whose
trunk is the lower ⅓ and ⅕ of the width. Then:

* the run count stays **1–3 per column at every size** — a procedural shape has the same number of
  colour transitions whether it is 4 rows tall or 80;
* it gets **crisper** as it grows, where sampled art gets blockier — the opposite of the current
  failure mode;
* the HD bake and `DEG_SPR_LOWRES_*` tiers become irrelevant for glyph classes, since there is no
  source art to lose detail from.

⚠ **KEEP THE ORIGINAL WORLD FOOTPRINT.** `sp_w` / `sp_hh` / `sp_left` come from the real picture's
dimensions. If a glyph changes them, things change size and horizontal position on screen and the
picture moves far more than intended. **Bake the glyph into the same world box the real sprite had.**

⚠ **A LIKELY WIN I UNDER-SOLD.** Glyphs replace sampled art in the bank, and the bank is the build's
dominant cost — MEASURED, the sprite bank is 5,694,869 chars for 12 images, and the same config
assembled in **399s with no sprites vs 1583s with all of them**. A procedural glyph's run-list is a
fraction of a sampled image's, so glyph classes should shrink the bank and the assemble time
markedly. That may matter more than their ops saving. **Measure it: emit with glyphs and diff the
`banks` part size.**

⚠ **A glyph is a PICTURE CHANGE and must move in BOTH MIRRORS in one commit** — the oracle's sprite
art and the emitter's bank come from `sprite_art`, so the cleanest implementation is a glyph table
consulted *there*, which makes both sides read it by construction (the same SSOT trick that made
`THING_SPRITE` safe for the sprite cut).

---

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
4. **Glyphs** (§4), after per-row approval, both mirrors in one commit, with a before/after sheet.
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
