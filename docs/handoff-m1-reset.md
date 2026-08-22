# M1 — the self-resetting program: what is now MEASURED

**Written 2026-08-20.** Companion to `docs/handoff-complete-game.md`, which sets out why M1 gates
everything. This file holds what M1a and the first half of M1b produced. Every number was measured
in this session on the binary named below; nothing is quoted from an older doc.

---

## 0. The artifact everything below is about

```
scratchpad/fjmcache/_rssprobe.fjm     the SHIPPED config (build.build_wall_renderer defaults)
  sha256   3c13ec21424f7f5434bd2070d9a34796ab2f92de9657dc16e2894f4c63e4acee
  fjm      31,122,687 bytes
  span     84,823,030 words, storage flat, headroom 1.582
```

`scratchpad/_m1b_labels.tsv.gz` is that program's label table — **6,806,757 labels**, produced by
re-assembling **the same emitted files** and refusing to write unless the `.fjm` sha256 matched the
line above. So every name used below describes the binary that was censused, not a lookalike.

---

## 1. M1a — the `sshead`/`thnext` stride. ANSWERED, three ways.

**The stride is ONE hex cell, and in the array a byte lives entirely inside that one cell.**

For an array declared `A: hex.vec N` addressed the way `sim.bind_things` / `sim.thing_pass` address
it (`hex.set w/4, base, A` → `hex.ptr_index p, base, i` → `hex.write_byte p, v`):

| | |
|---|---|
| entry `i` starts at | `A + i*dw` — **one** hex cell per index (`dw` = 2w = 64 bits = 2 words at W=32) |
| its 8 bits occupy | bits `dbit..dbit+7` of that **one** cell (`dbit = w + #w = 38`), i.e. bits 6..13 of the cell's **second (jump)** word |
| writing entry `i` dirties | **at most one 32-bit word: `base_word + 2i + 1`** |
| do entries overlap? | **no** |

"At most", not "exactly": `write_byte` XORs the *delta*, so writing a byte that already equals the
target dirties nothing. §2.4 shows that is not academic.

**Scope.** Valid for `w ∈ {16, 32, 64}`. At `w = 8` — which is in `SUPPORTED_MEMORY_WIDTHS` —
`dbit+7 = 19 ≥ dw = 16` and the byte would spill into the next cell. `ptr_index` also truncates:
only index bits `0..(w-#w-1)` survive, i.e. `0..25` at w=32. Safe for 682 and 75; not unconditional.

### 1.1 The asymmetry that blocked this for two milestones

> **In the ARRAY a byte is ONE cell. In a REGISTER it is TWO cells, a nibble each.**

`hex.read_byte dst, ptr` declares `dst` as `hex[:2]` — that is why `sim.thing_pass` zeroes `h`
before reading into it. Both "one cell" and "two cells" are true, **about different things**. Every
apparent contradiction in this repo's `sshead` history is that one sentence.

### 1.2 How it was measured, and why this probe can be believed

`scratchpad/m1a_stride.py` assembles small programs at the project's real `W=32` **with a debugging
file**, reads the array label's address from the assembler's own label table, runs them in the
native core, and diffs **every raw word** of the array region, reporting the XOR delta per word.
There is no fj-side printing anywhere in it — which is the whole difference. All three earlier
probes reported through `hex.if0 1, arr + k*dw`, a construct that (see §1.5) cannot legally test one
of these cells at all.

Observed for writes `[(0,0xA5), (1,0x07), (2,0x10), (5,0xFB), (9,0x01)]`:

```
word +1   cell 0   delta 0x2940  = 0xa5      word +11  cell 5   delta 0x3ec0  = 0xfb
word +3   cell 1   delta 0x01c0  = 0x07      word +19  cell 9   delta 0x0040  = 0x01
word +5   cell 2   delta 0x0400  = 0x10
EXACTLY ONE LAYOUT FITS: stride 1 cell(s), byte in ONE cell
read_byte round-trip at indices 5 / 2 / 0 -> 0xfb / 0x10 / 0xa5   ok
```

**R9 controls, all of which run and must pass BEFORE the answer prints:**

- **A — calibration.** The estimator is first pointed at arrays written with
  `hex.set 2, A + i*K*dw, v` — a stride the source states literally — for K = 1, 2, 3, and must
  return exactly K. It does. An estimator answering "1" three times would be reporting its own
  assumption.
- **B — discrimination.** 7 of 8 candidate layouts are *rejected* on the K=2 observation.
- **C — poison.** One bit of a real observation is flipped; **every** model must then fail.
- **D — vacuity.** A program that writes nothing dirties nothing.

### 1.3 Confirmed independently on the shipped 84.8M-word binary

```
sshead: label word 36,604,810   declared hex.vec 1364 cells = 2728 words
  next label is exactly 2728 words away -> attribution here is exact, not a guess
  35 dirty words, offsets 1..1359,  offset mod 2: {1: 35}   offset mod 4: {1: 18, 3: 17}
  -> 35 distinct CELLS, indices 0..679, all < nss=682

thnext: label word 36,607,538   declared hex.vec 150 cells = 300 words
  next label is exactly 300 words away  -> exact
  40 dirty words, offsets 1..147,   offset mod 2: {1: 40}   offset mod 4: {1: 18, 3: 22}
  -> 40 distinct CELLS, indices 0..73, all < nt=75
```

Every dirty word is at an **odd** offset — a cell's value word — and the mod-4 split is ~50/50,
which is exactly what a **1-cell** stride produces and what a 2-cell stride cannot (that would put
every dirty word at `offset % 4 == 1`).

The discriminator demonstrably has teeth on real data: `thvis`, which the emitter really does
declare at a **2-cell** stride (`hex.input 1, thvis + i*2*dw`), shows up as a single **step-4**
progression of exactly **123** entries — the only step-4 run longer than 20 in the image. Two
different strides, in one binary, each read correctly.

### 1.4 …and by independent source derivation

A four-lens adversarial pass over the stl (`stl/hex/pointers/*`, `stl/hex/memory.fj`,
`stl/runlib.fj`, the assembler's `#` operator) reached the same layout on **two paths that share no
assumption**:

- **write side** — `xor_byte_to_flip_ptr hex { rep(2, i) .xor_hex_to_flip_ptr hex+i*dw, 4*i }`
  (`xor_to_pointer.fj:106-108`): both nibbles go to the **same** pointed address, at `bit_shift`
  0 and 4.
- **read side** — `read_byte_from_inners_ptrs` flips bit `dbit+8` of the pointed cell and jumps into
  it, landing in the **256-entry** `read_ptr_byte_table` pinned at op 256
  (`xor_from_pointer.fj:36`, `basic_pointers.fj:19-27`). A 256-entry table indexed by the cell's own
  jump word can only mean an 8-bit field in that one cell.

### 1.5 The three earlier probes were never in conflict

| probe | what it saw | verdict |
|---|---|---|
| `_ssheadaddr.py` | wrote 9 at index 5, nibble 5 lit | stride 1 cell — **true** |
| `_ssheadoverlap.py` | wrote 0x10 at 3, read 4 as zero | no overlap — **true** |
| `_ssheadlayout.py` | a 2-nibble value lit only one cell | byte in one cell — **true** |

All three were right. What they lacked was a negative control, which is why none of them could
settle it. `src/fj/sim.fj`'s comment saying they are "MUTUALLY INCONSISTENT" has been corrected
(comment-only edit; the non-comment text of the file is byte-identical to HEAD, verified by hash).

### 1.6 Two corollaries that will bite the next person

1. **`hex.if0` cannot test one of these cells AT ALL — at either width.** This is stronger than
   "it's too narrow", which is what I first wrote and what the adversarial pass refuted.
   `hex.if0 1, A + s*dw` reaches `hex.if_flags`, which does `wflip hex+w, switch, hex` and then
   **executes the cell**, landing at `(value*dw) ^ switch` (`cond_jumps.fj:12-26`). `pad 16` aligns
   `switch` to 16 ops, so the target is inside the 16-entry table **only when the value's high
   nibble is 0** — and the escaping path skips `clean:`, leaving the array cell **permanently
   corrupted**. `if_flags` is documented for `0..15`; these entries hold `t+1 ∈ 1..251`.
   `hex.if0 2` additionally straddles entry `s+1`. A baked empty-list test must `read_byte` and test
   the register. This is a sharper statement of why M14.5 §3.2 is blocked, not a new blocker.
2. **`sshead` and `thnext` are declared twice the size they can reach.** `hex.vec 2*nss` = 1,364
   cells and `hex.vec 2*nt` = 150 cells against a 1-cell stride; cells `nss..` and `nt..` are
   unreachable padding. Not a correctness bug, but it is the strongest live artifact of the
   stride-2 assumption, and it means "restore the whole array" would do twice the needed work.
   Also: `hex.set 2, x, v` sets the **low nibbles of cells x and x+dw** — it is not an entry write,
   so the sketch it appears in was doubly wrong.

---

## 2. The dirty set, MEASURED and NAMED — and the roadmap's 74% is wrong

`scratchpad/m1_dirtymap.py` on the shipped binary, four `deg_gate` viewpoints × three key states:

| key state | per-frame dirty words | union of 4 |
|---|---|---:|
| `keys=0` (stationary) | 3,905 – 5,371 | **6,706** |
| `keys=1` (forward) | 4,967 – 7,130 | **9,214** |
| `keys=5` (forward + turn) | 5,447 – 7,245 | **9,544** |
| **grand union, 12 frames** | | **10,230** of 84,823,030 = **0.0121 %** |

### 2.1 The shape is far simpler than expected

```
grand union: 10,230 dirty words
  10,227 are ODD  addresses -> a data cell's VALUE word
       3 are EVEN addresses -> a code op's FLIP word: words 0, 2, 1030 -- and only those three,
                               in all twelve frames across all three key states
```

**The frame's residue is almost entirely DATA-CELL VALUES, not self-modified code.** Every `xor_by`
involution, every wflip chain, every `*_consts` SET/CLEAR pair puts itself back. The entire stl
truth-table span — **words 1,060 … 17,322, 16,263 consecutive words covering all six dispatch
tables** — comes back **completely clean**. What survives is registers and arrays. That makes M1c a
sequence of cell writes rather than anything resembling a memcpy of code, and it is the most
encouraging structural fact in this file.

### 2.2 Where the words are (keys=0 union, attributed)

| owner | words | what it is |
|---|---:|---|
| `sfslot` | 1,413 | V3 step-face per-column slots, 160 cols × 16-cell stride |
| `spslot` | 948 | V4 sprite-fragment per-column slots, 160 × 16 |
| `thss_rt` | 166 | runtime thing→subsector cache (16-cell stride) |
| `drawn` / `pclm` / `sfflag` | 160 each | one packed byte per column |
| `sprflag` | 131 | one packed byte per column |
| `thvis` | 123 | per-thing visibility, 2-cell stride |
| **`thnext`** | **40** | |
| **`sshead`** | **35** | |
| `thpos_rt` | **0** | see §2.4 |
| 898 macro-local `@` scratch registers | 3,176 | `fixed_mul_lo`'s `wide_a/wide_b/res`, `hex.scmp`'s `ba/bb`, `point_to_angle`'s `tan_base`, … |
| 89 top-level named cells | 3,528 | |

`drawn + pclm + sfflag + sprflag` = 4 × 160 = **the "640 latch-array bytes" commit `3046a40` named**,
now located.

> **⚠ CORRECTION TO `docs/handoff-complete-game.md` §1 AND TO COMMIT `3046a40`.**
> "`sshead`/`thnext` … are **74 %** of the ~2,500 cells" is **wrong for the shipped config**. They
> are **75 of 6,706 words = 1.1 %**. The 74 % is what the *declared spans* `2*nss + 2*nt` give with
> **nt = 251**; the shipped binary bakes 176 of the 251 things statically and carries only
> **nt = 75** at runtime, and a 1-cell stride means only `nss + nt` cells are reachable at all.
> **M1a was on the critical path for CORRECTNESS. It was never on the critical path for COST.**
> The cost is `sfslot`/`spslot` and ~900 macro-local scratch registers.

### 2.3 The source-derived set agrees with the measured set

A six-region source enumeration (run with no build, from `src/fj/`, `src/doomfj/wall_renderer.py`
and the stl) produced an upper bound of **≈14,918 words at keys=0** against the measured 6,706 —
larger, which is the safe direction, with both gaps explained (keys=0 removes collision scratch;
delta-writes remove `thpos_rt`). Four of its falsifiable predictions were then tested against the
attribution and **all four held**:

- **P1 parity** — every dirty word odd except `{0, 2, 1030}`. Holds, 10,227 of 10,230.
- **P2 the stl block is 14 words** — the derivation predicted, *before the label table existed*,
  exactly `{0, 1, 2, 1025, 1030, 1033, 1037, 1039, 1041, 1043, 1053, 1055, 1057, 1059}` below
  `code_start` (word 17,308). **The measurement returns exactly that set.**
- **P7 keys≠0 is a step change** — it adds 3,524 words, and they attribute where predicted:
  `sim.point_side` 820, `sim.check_line` 800, `sim.check_block` 344, `sim.try_move` 16.
- **P8 the 167-long run splits** — it is `sfflag` 160 + `cpid` 2 + `pmin` 2 + `pmax` 2 + `sfslot` 1.

**So M1a and M1b agree on the classes.** M1b still owes the *complete* emitter-side derivation
(§4), but its skeleton is now cross-checked in both directions.

### 2.4 A SAMPLED restore set is unsound, and here are two receipts

**Receipt 1 — the low words are frame-dependent.** `delta = pristine ^ after`, words 0..2:

```
viewpoint                 ops          parity  word0   word1   word2
(664,291,0x18000000)      57,364,424      0     0x1     0x0     0x3
(1272,-724,0x40000000)    49,068,962      0     0x1     0x200   0x0
(1869,479,0x80000000)     51,929,636      0     0x1     0x200   0x3
spawn (-416,256,0x0)      46,927,659      1     0x0     0x200   0x3
```

- **Word 1 — op 0's jump word, the single word that causes the 9-op death — is CLEAN on the
  (664,291) viewpoint.** A census taken on that frame alone would have missed the most important
  word in the program.
- **Word 2** (`stl.IO`, xor 3) is clean on (1272,-724).
- **Word 0** is op 0's *flip* field. `;X` parses as flip-address 0, so every jump-only op toggles
  bit 0 of word 0: its final state is the **parity of the op count** — `0x1` on the three even-op
  frames, `0x0` on the odd-op spawn frame. That is why commit `3046a40`, which measured the spawn
  frame, listed words 1 and 2 but not word 0.

**Receipt 2 — a write of the value that is already there is invisible to every measurement.**
`thpos_rt`'s 1,200 cells are **entirely absent** from every census, because the wire feeds the
baked spawn positions, so every `hex.input` write is zero-delta. **Measured two-sided**, same
harness, same frame, only the fed positions differ:

```
UNMOVED (the control):   46,927,659 ops, 3,905 dirty words ->    0 inside thpos_rt
MOVED by +64 map units:  47,043,633 ops, 3,994 dirty words ->   92 inside thpos_rt
                                                (offsets 11..2379, every one odd)
```

92 words that **no census in this repo's history has ever seen**, produced by moving things 64
units — and they appear in one step, from a region a learned range-set would have marked clean.
(92 rather than 1,200 because +64 changes only some nibbles of each 16-nibble position and leaves
`y` alone; a real move changes more.) The same mechanism suppresses most of `thnext` — there is no
75-long stride-2 progression anywhere in the image, because `thnext[t] = sshead[ptss]` is 0 for the
first thing in each leaf.

And **150 words are dirty at keys=0 but not at keys≠0** — no single configuration is a superset of
the others. Only the union is meaningful.

### 2.5 `--keys 3` is a VACUOUS move — do not use it

The key bits are `bit0 = forward, bit1 = back, bit2 = turn left, bit3 = turn right`
(`hex.if_flags pkeys, 0xaaaa/0xcccc/0xf0f0/0xff00`). `keys=3` presses **forward and back**, whose
impulses cancel to `pmove = 0`, and `hex.if0 8, pmove, simmv_done` then skips the entire collision
path. Measured: keys=3 adds **661 ops and 1 word** over keys=0. Use `keys=1` or `keys=5`.

---

## 3. Q1 — peak RSS. `CLAUDE.md` rule 1 STANDS.

`scratchpad/m1q_rss.py`. Its sampler carries an R9 control: it must see a known ballast, must
*reject* an inflated claim of twice that ballast, and must report zero when unstarted.

| run | conditions | peak RSS | wall | CPU |
|---|---|---:|---:|---:|
| emit + assemble | 2.1 GB free at start (paged) | **9.46 GB** | 1,452.5 s | 981.9 s |
| assemble only, same emitted files | 7.5 GB free at start | **9.66 GB** | 639.9 s | 396.5 s |

Two runs, one under memory pressure and one with headroom, agree at **~9.5–9.7 GB**. Two concurrent
builds need ~19 GB against 16.8 GB of RAM — **112 % of the machine**.

> **Rule 1 is not relaxable on this machine. Keep it.**

The second run also puts a clean number on the assemble phase alone: **396.5 s CPU / 639.9 s wall**,
against the campaign's 342 s CPU / 559 s wall. Same order; the wall gap is this machine's VM drift,
which is why the campaign said to compare on CPU.

---

## 4. What M1b still owes

The measured set is a union of twelve frames and is a **lower bound by construction** (§2.4). What
is still owed is the derivation from the emitter, and specifically these classes:

1. **Macro-local scratch vectors created BY stl macros** — `hex.scmp`'s `ba`/`bb`
   (`cond_jumps.fj:215-218`), `hex.mul`'s `dst/src/a_1bits/b_1bits` (`mul.fj:82-85`), `hex.div`'s
   `_b/_a/_r/i` (`div.fj:61-65`). Per-**instantiation**, so the emitter can count them. The
   measurement confirms the class is the single largest: 898 such labels, 3,176 words, 47 %.
2. **Non-zero pristine values — a `memset(0)` prologue is WRONG.** Known so far: `pmax = 159`,
   `col_top = 1`, `piece_max = 1+stack`, `cw16 = 16`, `thpos_rt` = baked spawn positions. `pmax` is
   live and *is* in the measured dirty set: zero it and every seg finds an empty window, killing
   plane attribution for the whole frame, silently. **This list is not known to be complete.**
3. **Two latches that no code clears**, neither nameable from outside its macro:
   `proj.project_thing::trig_cached` (`projection.fj:1567`) — leave it set and frame N+1 projects
   every sprite with frame N's sin/cos; and the triple `{consts_set, c_centeryfix, c_viewh1}`
   (`projection.fj:1644-1647`) — clear all three or none.
4. **`stl.fcall` return registers under an early-out.** `wflip ret_reg+w, ret, label … ret: wflip
   ret_reg+w, ret` (`ptrlib.fj:93-98`) is an involution *only if control reaches `ret:`*. This
   branch is named `m13opt3-early-out`. A stale `ret_reg` is byte-exact until the next `fcall`
   through it — **invisible to `deg_gate`**.
5. **Config sensitivity.** The set is valid for `build_wall_renderer`'s defaults and no other tier.
   `two_sided=True` revives the whole `colbuf` runtime-write path; `raster_mode="framebuffer"`
   revives 17,920 declared-but-currently-clean `col_*` cells.
6. **The host writes nothing.** `ScreenIO.py` only ever calls `read_data_byte`;
   `NativeDeviceMemory.write_word` has no caller in `src/`. Grep-derived, not observed.

Everything here assumes `W = 32` (`harness.py:9`) and that the emitted program begins with exactly
`stl.startup_and_init_all`. Both hold for the shipped entry; either changing moves every address.

---

## 4b. THE RESTORE SET IS DERIVED, AND IT SURVIVES EVERY HOLDOUT

`scratchpad/m1c_restore_set.py` builds the set from the program rather than from observations, and
then runs the real M1 gate on it in Python — **before any fj exists**. The set is the union of the
full `[label, next label)` extent of:

| source | labels contributed | where it comes from |
|---|---:|---|
| **declared** | 265 | every top-level label of `e1m1_05_state.fj`, `e1m1_01_tables.fj`, and the state prefix of `e1m1_06_banks.fj` (which ends at `thvis`; after it the file is baked banks) |
| **macro-local vectors** | 6,546 | every label in the table mangled `…---<local>` whose `<local>` is declared `hex.vec`/`bit.vec` somewhere |
| **observed** | 1,438 | anything a censused frame dirtied — kept as belt-and-braces |

Those three overlap; deduplicated the tool reports **6,821 labels** (`{macrovec: 5,225, both:
1,429, declared: 158, observed-only: 9}`). **Only 9 labels come from observation alone** — the
derivation now covers essentially everything the census found, which is the point.

```
with the read-only LUTs   6,821 labels -> 363,832 words (0.429%),  81,573 non-zero (22.4%)
--drop-luts   (SHIP THIS) 6,813 labels -> 132,414 words (0.156%),   7,330 non-zero ( 5.5%)
                                       = 66,207 hex cells in 3,768 runs
```

**Result: 11 of 11 frames restore to a 0-differ exact walk over all 84,823,030 words, and the
re-run reproduces the op count and the pixels byte for byte — with OR without the LUTs.**
The eight read-only LUTs (`stepcol`, `lnrow`, `finetangent`, `slopediv_recip`, `slopediv_recip8`,
`tantoangle`, `viewangletox`, `bklin`) really are never written: dropping their 231,418 words
changes no verdict, and cuts the non-zero cells — the ones that need a `hex.set` rather than a
`hex.zero` — from 81,573 to 7,330.

**So the fj prologue is ~66,207 cells, of which ~94.5 % are a clear-to-zero.**

```
VALIDATION A (4 frames the set was built from)   all 0 differ, ops ==, pixels match
VALIDATION B (7 HOLDOUT frames it never saw)     all 0 differ, ops ==, pixels match
   including 3 never-censused viewpoints, a MOVED-things wire, and turn-only key states
```

### Why "macro-local vectors" is the whole trick

Restoring *all* macro-locals is impossible: there are 5,128,268 of them and their label-to-label
extents sweep up every jump target and the code between, totalling **47,145,920 words — 55 % of the
image**. Filtering to those whose local name is *declared as a vector* collapses that to **6,546
labels / 66,128 words**. It is small only because this repo puts every heavy body in a **shared leaf
instantiated once** — the architecture that exists for assemble time turns out to be what makes a
self-reset affordable.

### Three parser shapes, each of which cost a holdout failure

The derivation was wrong four times, and each time a holdout said so. Words still leaking after the
restore, per run (`—` = the run stopped at an earlier failure and never reached that frame):

| set | words | things moved | (1000,100) | (1500,-200) | (2100,800) |
|---|---:|---:|---:|---:|---:|
| observed labels only | 37,116 | **92** | — | — | — |
| + declared state | 315,796 | 0 | 29 | 19 | 725 |
| + macro-local vecs, same-line decls only | 340,358 | 0 | 2 | 14 | 169 |
| + next-line decls (`ba:` / `.vec n`) | 363,094 | 0 | 2 | **0** | **0** |
| + generated-macro and `rep(...)` decls | 363,832 | **0** | **0** | **0** | **0** |

- **next-line declarations.** The stl writes `ba:` on one line and `.vec n` on the next
  (`cond_jumps.fj:209-218`). A same-line-only regex misses `ba`/`bb` and every other stl scratch
  vector — 185 words leaking out of `sim.check_line` alone.
- **generated macros.** `w1rpat.walk_win` is written into the program by `lut_generator.py:878`, so
  its `wl2: hex.vec 2` exists in **no hand-written `.fj` file**. A parser reading only `src/fj` +
  the stl cannot see it. Two words, one viewpoint.
- **`rep(...)` declarations.** `col_top: rep(160, i) hex.vec 8, 1`.

Each of these is now a **named assertion** in the parser: it refuses to run if it stops seeing
`ba`, `bb`, `wl2`, `wide_a` or `col_top`. A parser that quietly stops recognising a shape would
otherwise just silently shrink the restore set, and the only symptom would be a different program
next frame.

⚠ **And every one of those failures was PIXEL-IDENTICAL.** In all nine leaking runs above the
frame-2 pixels matched and only the op count moved. `deg_gate` compares pixels. **It cannot see any
of this** — which is exactly why the gate for M1c has to be the exact 84.8M-word walk plus the op
count, not a picture.

### A hole in a linked-list head does not diverge — it does not TERMINATE

`scratchpad/m1c_hole.py` punches one label out of the set and runs the next frame, under an
external timeout because `_fjcore.Memory.run` takes no op cap:

```
--drop none    (the CONTROL)  frame 2  57,364,424 ops in 0.22s   ops ==, pixels match   exit 0
--drop spslot  (5,120 words)  frame 2  57,362,405 ops in 0.19s   -2,019 ops             exit 0
--drop sshead  (2,728 words)  frame 2  DID NOT TERMINATE -- killed at 180 s             exit 124
```

`sshead` is the **head array of a linked list**. Leave it stale and `bind_things` prepends onto a
list that is already non-empty, so `thing_pass` walks a chain that can close on itself. That is
almost certainly what commit `3046a40` hit when it restored the two low words and reported "STILL
RUNNING AFTER 560s": **not a slow frame — a cycle.** It also means the ablation loop must judge on
the walk alone and never re-run, or the control hangs (it did, for 35 minutes, before this was
understood).

### What this does NOT prove

- **Eleven frames, one map, one build config.** It shows the *construction rule* generalises to
  frames it was not built from — which a learned range set demonstrably does not — but "declared
  state ∪ macro-local vectors" is still a rule about this emitter's output, re-checkable only by
  running the holdout. Config sensitivity from §4.5 applies unchanged.
- **The ablation control is narrower than it looks.** It drops one label and requires failure, but
  only for the probe frames it runs — so it demonstrates teeth for a label those frames actually
  dirty and proves nothing about a label they do not. All 8 labels tried failed as required
  (`spslot`/`sfslot` 500 words each, `thss_rt` 166, `sfflag` 127, `thvis` 123, `sprflag` 106,
  `sshead` 35, `stl.IO` **1**), so the validation detects holes down to a single word — but that is
  a demonstration that it *can* detect a hole, not a per-label necessity proof.
- **The LUT drop is validated on the same 11 frames, no more.** `--drop-luts` passes all 11, which
  is evidence those eight labels are never written — not a proof that no code path writes them.

---

## 5. What this changes about M1c

1. The prologue restores **cell VALUES**, not code. Across twelve frames the only code-side words
   in evidence are three: word 0 (op 0 flip), word 1 (op 0 jump — the 9-op death), word 2
   (`stl.IO`), plus `hex.pointers.to_flip`'s first word at 1030.
2. **Word 1 must be restored unconditionally**, even though it is clean on one gate viewpoint.
3. **The set is settled: 132,414 words = 66,207 hex cells in 3,768 runs, only 7,330 of them
   non-zero.** So ~94.5 % of the prologue is "clear this cell", and the pristine values it does
   need are read straight out of the assembled image — they never have to be re-derived.
4. Cost is **not yet measured**. Naive arithmetic (66k cells × 5–20 ops) puts it at 0.3M–1.3M ops
   against a ~47M-op frame, i.e. **0.7 %–2.8 %** — but that is a guess from a cell count, and this
   repo's rule is that a number is not a number until the harness prints it. Measure it, and note
   that a contiguous run can be cleared with one `hex.zero n, addr` rather than n separate ones.
5. Restoring `sfslot`/`spslot` and the ~900 `@`-scratch registers is the bulk; `sshead`/`thnext`
   are noise **in size** — but `sshead` is the one whose omission hangs the program, so "small" and
   "unimportant" are not the same thing here.
5. `stl.startup_and_init_all` executes exactly one op and jumps over all six truth tables, and the
   tables measure clean — so an in-program loop does not have to re-run it. That is a source claim
   about a macro that has only ever run once, and it becomes load-bearing the moment the program
   stops reloading a pristine image.
6. The gate is the one `handoff-complete-game.md` specifies: run the same frame twice, require
   identical op counts **and** identical pixels, plus an exact 84.8M-word walk against the pristine
   image — per frame, not once.

---

## 6. Tools added this session

| tool | cost | proves |
|---|---|---|
| `scratchpad/m1a_stride.py [--selftest]` | ~30 s, no build | the `ptr_index`/`write_byte` layout, calibrated against strides the stl states literally |
| `scratchpad/m1b_labels.py [--selftest]` | one assemble | the shipped program's label table; refuses to write unless the `.fjm` sha matches a reference build |
| `scratchpad/m1_dirtymap.py` | ~50 s + attribution | the exact dirty set, its structure, and every word's owning label |
| `scratchpad/m1q_rss.py [--selftest]` | one build | peak RSS of the current build |

`m1a_stride.py`, `m1b_labels.py` and `m1q_rss.py` carry `--selftest` negative controls.
`m1_dirtymap.py` runs its four controls (walker, vacuity, label-shift, declared-size) inline on
every invocation — there is no way to get a number out of it without them.


---

## 7. M1c + M1d — DONE. The program self-resets and loops.

**Built:** `scratchpad/fjmcache/_m1loop.fjm`, 89,446,230 span-words,
sha256 `ebeac2361b72ddf82be6c1c31f7c77be2697552a31e4a9ec6d78ea7abf91f287`.

### 7.1 The insight that made it small

**In an internal loop, op 0 never re-executes** — so the 9-op death (word 1, op 0's jump field)
stops mattering entirely. The loop re-enters at `__hot_end`. And `stl.startup_and_init_all` has
nothing to re-run: it emits the six truth tables as *data* and jumps over them, which is exactly why
the whole table span measures clean after a frame. So M1c and M1d are not two milestones stacked —
doing them together is what makes M1c easy.

### 7.2 The shape of the change

| | |
|---|---|
| `e1m1_02_main.fj` | the frame's trailing `stl.loop` becomes `;m1_reset` — **1 op → 1 op** |
| `e1m1_07_reset.fj` | a new, last part: `m1_reset:` … `;__hot_end` |

Size-neutral plus appended means no existing label moves, which is what lets the reset bake
**numeric addresses** taken from a first assembly. That is necessary, not a shortcut: most of the
set is macro-`@`-local scratch, which fj cannot name from outside its macro, and restoring only the
fj-addressable declared state leaves **up to 4,495 pixels wrong**.

### 7.3 The final set — 113,058 words = 56,529 cells

Three reductions, each proven by the 12-frame chain rather than argued:

- **`sfslot`/`spslot`/`thnext` need no restore** (−10,540 words): the slot arrays are write-once and
  gated by their flag byte, and `bind_things` fully overwrites `thnext` every frame.
- **the stl region below `code_start` must NOT be restored** (−552 words): `to_flip` and
  `to_flip_var` are a **consistent pair** that `set_flip_pointer` xors against, so restoring one
  without the other is worse than restoring neither.
- **seven read-only regions auto-excluded** (−8,264 words): `throw`, `sprlt`, `throwc`, `bkoff`,
  `xtoviewangle`, plus `__hot_end` (code) and a `thvis` extent overrun. Derived, not listed: a cell
  only nibble ops ever write cannot hold a pristine value above 15, so anything that does is a
  packed LUT or code.

### 7.4 Two primitives, and the choice is correctness (M1a / R57)

Measured per cell: **`hex.zero` 19.5 ops, `hex.set` 21.5, `hex.zero_ptr` 943.**

A nibble op on a BYTE cell does not merely fail — it **corrupts**: 0xA5 → 0x22A5, because
`hex.xor`'s dispatch jumps out of its own 16-entry table. So `sshead`/`pclm`/`sfflag`/`drawn`/
`sprflag` get pointer loops and everything else is unrolled. And `hex.xor_by` **clamps to a
nibble** (`stl/hex/memory.fj:74`), which is why the pointer path is the only value-independent way
to clear a full byte.

### 7.5 The gate — PASS

```
PHASE 1  four certified viewpoints, ALL IN ONE RUN
         loop vs old binary: BYTE-EXACT x4
         vs oracle: loop delta == old delta on every frame -> M1 moved no pixel
CONTROL  the same wire on the OLD binary presents exactly 1 frame
PHASE 2  8-frame chain, every frame BYTE-EXACT vs that frame on a PRISTINE image
PHASE 3  the reset costs 270,811 ops/frame  [PRE-TRIM -- superseded by 251,701, see 9.5] = 0.9% of the 30,191,585-op MEDIAN
```

⚠ The 378-px delta at (1869,479) in phase 1 is **pre-existing**: the oracle call is `deg_gate`'s,
which certifies the non-sim tier, and the OLD certified binary has exactly the same 378. The test
that means something for M1 is that the two deltas are *equal*.

### 7.6 fps

⚠⚠ **EVERY NUMBER IN THIS SECTION IS UNVERIFIED FOR THE SHIPPED BINARY, INCLUDING THE 3.85×.**
It was measured on 2026-08-21 against the pre-CR, pre-trim, pre-rebuild program and has not been
re-run since; `scratchpad/m1_fps.py` also carries no negative control (§9.7). CLAUDE.md's
Performance Claims rule says re-measure before acting on it — so do that, do not cite this table.
Kept because the METHOD (alternating A/B on one harness, best of 3, ratio not absolutes) is the
right one and the successor measurement should use it.

Alternating A/B ×3 on one harness, best of 3, `scratchpad/m1_fps.py`:

| | cpu/frame | fps (cpu) |
|---|---:|---:|
| host restores the image | 1918.0 ms | 0.52 |
| **M1 internal loop** | **498.0 ms** | **2.01** |
| | | **3.85×** |

⚠ **The absolute numbers are harness-bound and must not be quoted as the game's fps.** The "host
restore" side is `FjmRunner`'s per-frame core rebuild in Python, which is what the walker does but
is not a 52 ms memcpy. What the measurement supports is the **ratio**, measured in-session on both
sides. ⚠ Rep 2 came back 299 s against 18 s for identical work — this machine's VM drift, which is
why the runs alternate and report best-of-N on CPU time.

### 7.7 What was NOT done at the time — ALL OF IT NOW IS (2026-08-22)

[SUPERSEDED. `build_wall_renderer(self_reset=True)` does both passes and refuses the binary if a
baked address moved; `scripts/walk_e1m1.py --fjm PATH --loop` runs it. See §9.5. The original text
follows because the distinction it draws is the one CLAUDE.md's wiring checklist exists to enforce,
and it is worth keeping visible that M1 spent a while *built and gated* rather than *shipped*.]

~~**The reset is not wired into `build.py`.** It is produced by `scratchpad/m1_emit_reset.py` and
assembled by `scratchpad/m1_build.py`; `build_wall_renderer` still emits the single-pass,
host-reset program. Wiring the two-pass into the emitter is the remaining integration step, and
`walk_e1m1.py` has not been pointed at the looping binary.~~

⚠ The one part of this that is STILL TRUE: the only caller of `build_wall_renderer(self_reset=True)`
is `scratchpad/m1_wired_build.py`. `walk_e1m1.py` consumes a prebuilt loop `.fjm`; it cannot
produce one.

Also open: 9 of the set's labels still come from observation alone rather than derivation, and the
whole set is validated on 12 frames of one map in one build config.

### 7.8 Four controls that earned their keep

- the **byte-preload control** caught a vacuous cost measurement: `hex.xor_by` had clamped 0xA5 to
  0xF, so "hex.zero clears a byte" had been measured on a byte that was never there;
- the **label-stability control** caught 32 moved labels — `hex.exact_xor`'s `end`/`switch`, which
  sit at wflip-chain spots whose recycled `pad` slots shift when the program gains thousands of
  wflips. None was a restored cell, but the control was a coarse min..max range and is now a
  membership test;
- the **no-restore control hung** instead of failing — the `sshead` cycle again;
- the **first build died with an empty log** at 6.19 GB with 4.72 GB free: the silent OOM of
  CLAUDE.md rule 1, reproduced exactly.


---

## 8. The reset came down 13x, and the frame cost was measured against the wrong thing

Two corrections and one idea, all after §7 was written.

### 8.1 The denominator was wrong

§7 reported "7.47% of a 47.5M-op frame". **47.5M was the mean of eight hand-picked GATE viewpoints.**
The metric is the sweep median, and `handoff-complete-game.md` §4 says gate viewpoints overstate the
typical frame by 1.5-1.9x. Re-measured in-session over the sweep's own 260-frame walkable grid, one
frame per run on the old binary:

```
median 30,191,585   mean 30,929,878   min 7,675,375   max 61,405,073
```

which reproduces commit `d125a18`'s 29,792,277 to within 1.3%.

### 8.2 The set was 9.4x bigger than it needed to be

The predicate was wrong too. A cell needs restoring iff the next frame **reads it before it writes
it** -- not merely if the frame dirties it. Per cell that is hopeless; per **(macro, local)** it is
easy, because it is a property of the macro body and identical in every instantiation. The 1,321
scratch labels collapse to 349 distinct pairs (`scratchpad/m1_rbw.py`); walk each macro body and
classify the FIRST statement that mentions the local, defaulting to READ so a gap in the table can
only make the set bigger.

| set | words | |
|---|---:|---|
| A shipped first | 113,058 | every dirty label's full extent |
| B never-dirty dropped | 27,930 | 77% of A is never dirty at all (`col_*` alone is 35,840 words of framebuffer-tier state the `lines` tier never touches) |
| **D read-before-write** | **12,066** | 220 of 349 pairs are write-first |

Set D: 12-frame chain PASS, **260/260 sweep frames byte-exact**.

### 8.3 The byte clear needed no pointer at all

`hex.zero_ptr` costs 943 ops/cell and almost all of it is `set_flip_and_jump_pointers`, copying an
8-nibble address so the machine can reach a cell it only knows at RUNTIME. **The reset knows every
address at emit time.** So drive the stl's own 256-entry byte table directly:

```
hex.zero 2, read_byte
wflip ret_after_read_byte+w, back
C+dbit+8 ; C          # set the marker bit, JUMP INTO THE CELL: its jump word is now
                      # (v+256)*dw, which IS read_ptr_byte_table + v (pinned at op 256)
back:
wflip ret_after_read_byte+w, back
C+dbit+8 ;
hex.exact_xor C+dbit+3..0, read_byte       # C ^= v -> low nibble cleared
hex.exact_xor C+dbit+7..4, read_byte+dw    # C ^= v -> high nibble cleared
```

`hex.exact_xor`'s four flip targets are **arbitrary bit addresses**, so the HIGH nibble of a byte
cell is reachable by name -- the thing `hex.zero` cannot do, and the reason a nibble op corrupts a
byte cell (R57).

```
hex.zero_ptr (pointer path)      943.0 ops/cell
m1.zerobyte  (constant address)   91.1 ops/cell    10.3x
```

Verified on **all 256 byte values**, planted with a RAW `wflip` -- `hex.xor_by` clamps to a nibble
and would have made that check vacuous, which it already had once (`scratchpad/m1_zbyte.py`).

### 8.4 The result

`scratchpad/fjmcache/_m1loop4.fjm`, sha256 `40b0ace20430ed6f1f6e3c18e4d0b9cfba8451c163349fbd4352bb3049370eee`

| build | reset/frame | % of the 30,191,585 median |
|---|---:|---:|
| set B + `hex.zero_ptr` loop | 2,161,364 | 7.2% |
| set D + `m1.zerobyte`, unrolled | 270,811 | 0.9% |
| **the same, after the CR round-2 `sshead` trim** | **250,789** | **0.8%** |

M1 gate PASS; **260/260 sweep frames byte-exact**.

Also folded in: `drawn` and `sprflag` moved to the nibble path, justified statically --
`frame.mark_drawn` writes 1 (`frame_render.fj:340`) and `sprflag` writes 1 or 2
(`frame_render.fj:1538`). `pclm` (a plane-pair id, 152 of 255 used) and `sfflag` (measured 33)
genuinely exceed a nibble and keep the byte clear.

### 8.5 What is left

[SUPERSEDED -- see 9.5. The nibble half is **4,349** cells after the CR round-2 `sshead` trim, not
5,031, and M1 **is** wired into `build.py` (`self_reset=True`, 2026-08-22).]

The floor is ~91 ops/cell x 1,002 byte cells (91k) + the nibble cells. The one remaining lever is
that **`sshead` is 682 of those 1,002 cells but only <=75 heads are ever non-zero**, and
`thss_rt[t]` names exactly which -- a change to what the reset iterates, not to the primitive.
⚠ MEASURED AND REJECTED: at a constant address the byte clear is ~91 ops/cell, so 682 x 91 = 62,130
beats 75 x 943 = 70,725 for a selective clear at a RUNTIME address, and that 943 is a lower bound.
The lever is only worth taking if the selective clear can keep constant addresses.

---

## 9. CR rounds 1 and 2 — what review found that the gates could not

Two rounds against `docs/cr-rules.md`. Every finding that mattered was in the class this repo is
worst at: **things that stay byte-exact, so no rendering gate can see them.**

### 9.1 The one-sided guard, and 682 cells of dead work (R6, round 2)

`emit_reset_part` asserted `byte_words - wset` — every byte cell must be IN the set — and nothing
in the other direction. So a set word lying inside a byte array's declared extent but outside its
**reachable** part fell straight through to the nibble clear.

It was doing exactly that. `sshead` is declared `hex.vec 2*nss` (1,364 cells) but the stride is ONE
cell, so only `nss` = 682 are addressable; the set carried the whole extent, so 682 unreachable
cells were being nibble-cleared every frame.

The question that mattered was whether those cells are padding (dead work) or live byte cells
(silent corruption), and the code could not tell the two apart. **Measured, not argued:** across
all five `scratchpad/_m1_dirty*.json.gz` maps, the padding half is dirty in **0 words**. Dead work.

| | |
|---|---:|
| nibble cells before | 5,031 |
| nibble cells after the trim | **4,349** |
| removed | 682 (the whole `sshead` padding half) |

The guard is now two-sided: a set word in a byte array's declared-but-unreachable range is
**refused**, and `scratchpad/m1_setfile.py` trims that tail when it writes the set (derived from the
label extents, not hardcoded).

### 9.2 Is any OTHER array a byte array? (R6, round 2)

The counts were derived but the **membership** of the byte-array list was still hand-written, and
`src/fj/` has a dozen other `hex.write_byte` sites — all through pointer registers, so no static
rule can name the arrays they reach.

`scratchpad/m1_bytecheck.py` settles it empirically instead: run real frames, and for every cell the
reset nibble-clears, read the value it is left holding. A byte cell gives itself away by holding a
value > 15.

```
  4 viewpoints, 46.9M-61.5M ops each
  CONTROL 1 (vacuity) -- the KNOWN byte arrays must show values > 15:
    sshead      24 of 682 cells held a value > 15   ok
    pclm       160 of 160 cells   ok
    sfflag     160 of 160 cells   ok
  RESULT: no nibble-cleared cell ever held a value > 15.
```

The vacuity control is the point: without it, a clean result would be indistinguishable from a probe
that was reading the wrong memory.

⚠ **CR round 3 found three defects in this probe, and one of them had already reached the docs.**
The counts were summed OVER THE FOUR RUNS, so a 160-cell array reported "640" — a number that
cannot exist. `ok` did not depend on there being anything to check, so an empty set would have
printed the clean RESULT line. And the FAIL branch had never executed (its `%d` had no argument).
It now reports DISTINCT cells, asserts it has >1,000 cells to check, and carries a `--selftest`
that plants `0xA5` in one nibble-cleared cell and requires the verdict to flip:

```
  SELFTEST 1/2 as shipped                      -> m1_bytecheck: PASS
  SELFTEST 2/2 one cell planted with 0xA5      -> m1_bytecheck: FAIL
     !! 1 NIBBLE-CLEARED CELL HELD A VALUE > 15   word 17321
  M1 BYTECHECK SELFTEST: PASS
```

### 9.3 A control that computed `x == x` (R9, round 1)

`m1_setfile.py`'s "CONTROL: round-trip" rebuilt the absolute set from the same arrays that produced
the offsets — `base + (x - base) == x`, an identity, true for every input, and the **only**
provenance the shipped data file had. It is now a round-trip through the production loader with
three mutations that must each be caught (shift a label / delete a label / make an offset escape its
span), and `--selftest` builds its own synthetic inputs so it runs on a clean checkout.

The escape case is the one a round-trip is structurally blind to: attribution is
nearest-preceding-label with **no containment check**, so `load_restore_set` now enforces one.

### 9.4 The rest

- **Hardcoded byte counts** (R6): a wider `VIEW_W` would have dropped byte cells into the nibble set
  — corruption, byte-exact on E1M1. Counts are derived and cross-checked against two sources.
- **`CODE_START_WORD = 17308`** (R6): derived from word 1, which is op0's jump field and *is*
  `code_start`. Verified against the shipped binary: `553856 // 32 = 17308`.
- **`emit_reset_part` had no test** (R3): it is pure and injectable, so a fake label table covers
  the split, the read-only drop, the run coalescing and the main-part surgery in milliseconds.
- **`m1_gate.py` had no `--selftest`** (R9): it now re-runs itself with one byte of a presented
  frame flipped and requires the verdict to flip too.
- **Assemble time regressed** (R2): 3,498 s / 4,560 s total against 559 s single-pass (the
  rebuild in 9.5 measures 3,193 s / 4,724 s). Two passes
  are structural to M1; the number was omitted from the first PR body and should not have been.
- **One finding was wrong**: hatchling already ships `src/doomfj/data/`, verified by building a
  wheel where an explicit `force-include` is rejected as a duplicate.

### 9.5 The rebuild — every number re-measured on the shipped bytes

```
binary  build/doom_e1m1_loop.fjm   31,347,735 bytes
        sha256 75794727dce656be18140f10c88cff5b647660c713bcea4c8d1e34a918c5689a
        (the without-flag twin is scratchpad/fjmcache/_rssprobe.fjm,
         sha256 3c13ec21424f7f5434bd2070d9a34796ab2f92de9657dc16e2894f4c63e4acee,
         84,823,030 words -- so the reset part's own span is 645,946 words)

build   span 85,468,976 words (was 85,526,926), storage flat, headroom 1.57
        assemble 3,193 s of a 4,724 s two-pass build
        nibble_cells 4349, byte_cells 1002, labels_moved_in_set 0
        view_w 160, subsectors 682          <- derived geometry, now recorded in metrics

part    m1_reemit.py: the built e1m1_07_reset.fj == what this code emits, 63a80ad69cdd...

gate    PHASE 1 (oracle, 4 frames one run) : PASS
        CONTROL 2 (old binary = 1 frame)   : PASS
        PHASE 2 (8-frame chain vs pristine): PASS      8/8 BYTE-EXACT
        M1 GATE: PASS
        reset = 251,701 ops/frame on the 8-frame chain

gate    --selftest: clean exit 0, one presented-frame byte flipped exit 1
        M1 GATE SELFTEST: PASS

play    100 frames from ONE run, 72 distinct pictures
        (-416.0, 256.0) -> (799.7, 477.3)
        BYTE-EXACT vs the old binary: 100/100        M1 PLAYABILITY: PASS

sweep   260 frames, median 30,191,585 ops
        reset = 250,789 ops/frame = 0.8% OF THE MEDIAN
        CONTROL (same pictures): 260/260 byte-exact  ok
```

The two reset figures (251,701 and 250,789) are the same quantity over different frame sets, not one
number rounded twice. The trim is worth **-19,110 ops/frame** against the pre-trim build measured on
the identical 8-frame chain, and **-57,950 span-words**.

### 9.6 The control that certified the wrong property (CR round 3)

`m1_gate.py --selftest`, added in round 2, guarded its frame flip with `keep is None` -- and no
caller ever passes `keep`. So `--corrupt-frame 0` flipped a byte in **every** run, the old-binary
reference runs included. It still printed `M1 GATE SELFTEST: PASS`.

What it was actually doing, from `_m1_gate5_self.log`:

```
frame 0: loop vs old BYTE-EXACT      <- BOTH corrupted identically
frame 1: loop vs old !! DIFFER       <- the FAIL came from a corrupted REFERENCE
```

After the fix (`_m1_gate6_self.log`):

```
frame 0: loop vs old !! DIFFER; vs oracle loop=1 old=0 !! M1 MOVED PIXELS  FAIL
frame 1..3: BYTE-EXACT
```

**The lesson, and it is the sharpest one in this file: a negative control can pass while testing
the wrong property, and its summary line looks identical either way.** Both versions printed
`PASS`; only the per-frame signature distinguishes them. Quote the signature, not the verdict --
and when a control is the evidence, the thing to review is *which* mutation it rejects, not
*whether* it rejects one.

### 9.7 Which M1 tools carry a negative control (CR rounds 4 and 5)

⚠ **The previous three versions of this list were all wrong** — first overclaiming that every tool
had `--selftest`, then undercounting, then calling an 11-row table "the exhaustive list" when the
PR adds **21 `m1*.py` scripts**. So the scope is stated first and the claim is bounded to it.

**SCOPE: every tool whose verdict this PR or `DESIGN.md` quotes as proof.** That is the set R9
governs. Other `m1*` scripts are exploratory probes whose output is not cited as evidence anywhere,
and they are listed separately rather than silently omitted.

| tool | `--selftest` | the mutation it rejects |
|---|---|---|
| `m1_mutations.py` | it *is* the control | 8 mutations of shipped `src/` files; every one must be caught |
| `m1_gate.py` | yes | flips a byte of the **loop** binary's presented frame; requires FAIL |
| `m1_bytecheck.py` | yes (needs a built image) | plants `0xA5` in a nibble-cleared cell |
| `m1_reemit.py` | yes (synthetic) | drops a label; the emission must differ |
| `m1_setfile.py` | yes (synthetic) | C1 shift / C2 delete / C3 escape, plus a positive |
| `m1a_stride.py` | yes | mutates a known-good stride; must be rejected |
| `m1b_labels.py` | yes | — |
| `m1q_rss.py` | yes | — |
| **`m1_dirtymap.py`** | **no flag** | has one: CONTROL 3 shifts the label table, per-label counts must change. Its 0-dirty-words result licenses the 682-cell trim. |
| **`m1_sweep.py`** | **none** | in-run only: byte-exact vs the old binary over 260 frames |
| **`m1_play.py`** | **none** | in-run only: distinct-picture vacuity + byte-exact over 100 frames |
| **`m1c_restore_set.py`** | **none** | the first stage of the chain that produced the SHIPPED `m1_restore_set.json.gz`. Uncontrolled. |
| **`m1_fps.py`** | **none** | produced the 3.85x figure, which is why that figure is now labelled UNVERIFIED rather than quoted (see below) |

⚠ **CR round 6 found this partition wrong too** — three of the tools I had filed as uncited are
cited, one of them *in shipped source*. They belong in the table:

| tool | `--selftest` | where its verdict is cited |
|---|---|---|
| **`m1_zbyte.py`** | **none** | §8 (943.0 → 91.1 ops/cell) **and `src/fj/m1_reset.fj` lines 14 and 21** |
| **`m1c_hole.py`** | **none** | §6 — the "DID NOT TERMINATE, killed at 180 s" hang evidence |
| **`m1_rbw.py`** | **none** | §8 — the read-before-write derivation of the SHIPPED set |

**Genuinely uncited, listed for completeness:** `m1_build.py`, `m1_emit_reset.py`,
`m1_minimize.py`, `m1_wired_build.py`, `m1c_cost.py`, `m1d_loop.py`.

That is 22 `m1*.py` scripts in total, not 21. **This list has now been wrong in five successive
revisions** — overclaiming, undercounting, miscounting, and mis-partitioning. The lesson is not
about M1: a hand-maintained inventory of one's own evidence is itself evidence, and it decays
exactly as fast as everything else.

⚠ **`m1_fps.py` and `DESIGN.md`.** CR round 5 caught `DESIGN.md` pointing readers at "the fps line
in the handoff" while `docs/handoff-complete-game.md` marks that same figure UNVERIFIED for the
shipped binary. A pointer to a retracted number is a citation of it, so the pointer is gone.

**The real remaining gaps are the four bold rows with no control at all.** `m1c_restore_set.py` is
the most load-bearing of them: it produced a file that ships in `src/`.
