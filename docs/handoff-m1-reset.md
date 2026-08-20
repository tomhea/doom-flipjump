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
6,821 labels -> 363,832 words (0.429% of the image, ~2.9 MB) in 3,766 runs
  81,573 of them NON-ZERO in the pristine image (22.4%)
  231,418 of them read-only LUTs -- safe but pure cost, droppable -> ~132k essential
```

**Result: 11 of 11 frames restore to a 0-differ exact walk over all 84,823,030 words, and the
re-run reproduces the op count and the pixels byte for byte.**

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
- **The read-only LUTs are untested as droppable.** 231,418 of the 363,832 words are baked LUTs
  (`stepcol`, `lnrow`, `finetangent`, `slopediv_recip`, `tantoangle`, `viewangletox`, `bklin`);
  restoring them is safe but pure cost, and nothing here has yet re-run the validation **without**
  them. Do that before sizing the fj prologue — it is one no-build run and it decides whether the
  prologue is ~132k words or ~364k.

---

## 5. What this changes about M1c

1. The prologue restores **cell VALUES**, not code. Across twelve frames the only code-side words
   in evidence are three: word 0 (op 0 flip), word 1 (op 0 jump — the 9-op death), word 2
   (`stl.IO`), plus `hex.pointers.to_flip`'s first word at 1030.
2. **Word 1 must be restored unconditionally**, even though it is clean on one gate viewpoint.
3. Cost looks small — ~10k cells at ~20 ops each is ~0.2M ops against a ~47M-op frame (~0.4 %) —
   but that is arithmetic from a cell count, **not a measurement**. Measure it.
4. Restoring `sfslot`/`spslot` and the ~900 `@`-scratch registers is the bulk; `sshead`/`thnext`
   are noise.
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
