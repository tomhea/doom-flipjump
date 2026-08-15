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

Glyph design rule: cost is **colour RUNS per column**, because that is what `sprite_strip` bakes.
1 run/column is the floor for a visible sprite.

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

⚠ **A glyph is a PICTURE CHANGE and must move in BOTH MIRRORS in one commit** — the oracle's sprite
art and the emitter's bank come from `sprite_art`, so the cleanest implementation is a glyph table
consulted *there*, which makes both sides read it by construction (the same SSOT trick that made
`THING_SPRITE` safe for the sprite cut).

---

## 5. IS A LINKED LIST THE RIGHT STRUCTURE?

**For static things: no — and the right answer is no structure at all.** A baked call site inside
the leaf *is* the index. Every byte of `sshead`/`thnext` and every op of `bind_things` spent on a
static thing is pure overhead.

**For dynamic things: the traversal is fine; the REBUILD is the cost.** `bind_things` is MEASURED at
3,294,888 per frame for 251 things and it is **bit-identical at both profiled viewpoints** — a pure
frame-constant, because it re-links every thing every frame whether or not anything moved. It is
per-thing, so with only monsters dynamic it scales down with the count.

Two real weaknesses to fix in M14.5 or M16:

1. ⚠ **The list is SINGLY linked, so unlinking requires finding the predecessor — O(list length).**
   Today that never happens because the whole structure is rebuilt from scratch. The moment M16 does
   incremental re-binding (`P_UnsetThingPosition`/`P_SetThingPosition`, §5b of the perf handoff), a
   singly-linked list is the wrong structure. **DOOM uses a doubly-linked list for exactly this
   reason.**
2. **Rebuilding at all is optional.** The lists are world state and fj has none between frames —
   which is the same argument that made positions and bindings round-trip. Round-tripping the lists
   (§5b) means fj never rebuilds; it reads a head at a fixed address (§3.2) and walks.

⚠ **§5b's ceiling is 3,294,888 but its collectable fraction is unknown**, and the one experiment
that tried to collect part of it by re-addressing collected nothing (§0). Price it with a build.

**Candidate ranking for the dynamic set** (all DERIVED from structure, none measured):
baked CSR for statics (zero per-frame) > doubly-linked list rebuilt only for movers > today's
singly-linked full rebuild.

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
