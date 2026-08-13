# HANDOFF: M14 — input + simulation (with MOVING things)

Owner directive (2026-08-12): M14 delivers the **full** milestone — runtime input, the player
simulation with line collision, **and** moving things. Written for a session with no prior
context: everything you need is here or pointed at from here. Read it all before starting.

---

## 0. Repo state you are inheriting

- Branch `m13opt3-early-out`, tip = `a11b9cb`. Working tree clean apart from ~400 untracked
  `scratchpad/` experiment files (leave them; **never `git add -A scratchpad/`**).
- Read `CLAUDE.md` first — it is short and it is the operating manual (one heavy build at a
  time; byte-exactness; trust the gate, distrust the pre-gate; the frozen emitter ABI).
- The renderer is DONE and certified. `deg_gate` targets, to the digit:
  `45,208,629 / 35,486,777 / 42,824,933 / 33,547,652`.
- The emitted program is **7 ordered files** (`e1m1_02_main.fj` is ~55 lines). Order is the
  contract — see `write_program_files`.
- ⚠ **Read `docs/handoff-session-visuals.md` §5b before writing any code.** It is the previous
  session's M14 prep and it already did the hard analysis of what moving things break.

## 1. What is already done for you

From §5b, confirmed against the code:

**Position-agnostic already.** `proj.project_thing` and `frame.thing_record_body` read a thing's
position out of REGISTERS (`sp_x`/`sp_y`/`sp_z`). Projection, height bucket, column DDA and
run-list emit do not know where the thing is. **Move it and the same kernel projects it
correctly.** The expensive, intricate half of moving things is already finished.

**The oracle already simulates.** `reference_model.py` has `FORWARD_MOVE = 50<<16`,
`ANGLE_TURN = 640<<16`, and the turn/move step (~line 561). `docs/m9-oracle.txt` pins one
hand-checked tic. Collision was explicitly deferred *to this milestone*.

**The host already loops.** `scripts/walk_e1m1.py` reads keys, runs the sim **host-side**, and
feeds the result to the binary as three decimals on stdin (`f"{px}\n{py}\n{ang}\n"`).

## 2. THE ARCHITECTURE DECISION — settle this in writing before rung 1

The program is a **pure function of stdin that renders one frame and halts** (there is no loop
inside it; the loop is host-side because fj self-modifies — a second run on a dirty image dies
after 9 ops). M14 does not change that. What changes is the function's signature:

```
today:   (vx, vy, viewangle)                  -> frame
M14:     (world state, input) -> frame,        world state'
```

So **simulation state must ROUND-TRIP through stdin/stdout every frame.** The host becomes a
relay that holds the previous state and feeds it back; it stops being the thing that computes
movement. That preserves the existing architecture exactly — still stateless, still one run =
one frame — and it is the honest reading of "the sim runs in fj".

### 2.1 M14-0 RESULT — the wire format is BINARY. Measured, not estimated.

Two probes, both in `scratchpad/`, both shipping the negative control R9 demands:

* `m14_0_insitu_digits.py` — the **in-situ** cost of one decimal input digit, measured inside a real
  12.5MB E1M1 binary (`b_272d37507ca58434.fjm`) by the leading-zeros trick: `"0000001869"` and
  `"1869"` are the same value, six digits apart. *Control:* the frame bytes must be identical across
  every padded run, or the probe is measuring a moved value, not a digit. They were.
* `m14_0_wire_cost.py` — a k = 1/17/33 sweep over each candidate primitive in a small program.
  *Controls:* marginal cost linear in k, all input drained, output byte-exact.

| primitive | ops per unit | one 32-bit value |
|---|---|---|
| `hex.input_dec_int 10` | **2,135 / digit** (in-situ **2,079–2,395**) | ~21,400 (10 digits) |
| `hex.input_dec_uint 8` | 1,747 / digit (in-situ 1,969) | ~17,500 |
| `hex.print_dec_uint 8` | **12,927 / number** | 12,927 |
| `hex.input n` (raw) | **73.6 / byte** | **295** |
| `byte.emit` (raw, runtime) | **54 / byte** | **216** |
| `stl.output_char` (const) | 8 / byte | — |

**The small program does not lie about this one.** In-situ / small = **×0.97 … ×1.12** on the digit
row, so `@` barely moves between a 100KB and a 12.5MB program here and the small-program rows
transfer directly.

**Round-tripping one 32-bit value costs 511 ops binary against ~34,300 decimal — 67× cheaper.**
Scaled to the thing table (212 things × 5 values):

* binary: **~542k ops/frame**, i.e. 1.2–1.6% of the certified 33.5–45.2M frame — affordable;
* decimal: **~36M ops/frame**, i.e. *more than the entire frame* — exactly the doubling §2 feared.

**DECISION: the wire is raw little-endian binary** (`hex.input n, cell` in, `byte.emit` out), for
player state and for the thing table alike. No dirty-list complexity is needed and no thing sim has
to stay host-side: at 511 ops a value, all 212 things can round-trip every frame. The three player
decimals stay affordable either way (~60k ops) but move to binary too, so there is one format.

## 3. ⚠ THE TRAP THAT WILL BITE FIRST — the prune, and it fails SILENTLY

A leaf with no one-sided seg is dropped **twice**:
- `wall_renderer.py::_lines_prune` (compile time) — drops the leaf's walk block entirely;
- `wall_renderer.py::_lines_plane_gate` (runtime `tsstop` node gate) — skips the subtree.

Both were taught that a **thing-carrying leaf is live** (`if _si0 in things_by_ss: return False`).
That works only because with STATIC things the emitter knows which leaves carry things.
**With moving things it does not.** A monster walks into a leaf pruned as empty and **vanishes
with no error, no warning, no assertion.**

§5b is emphatic and it is right: **settle this BEFORE writing the runtime thing list, not
after.** This is the bug class that already cost this repo two builds. Options, cheapest first:

1. **Widen the predicate** to "any leaf a thing could ever enter" — in practice any leaf reachable
   by walking, i.e. keep every leaf with a floor. Costs walk time on leaves that are usually
   empty; measure it against the current prune win before choosing.
2. **Move the prune to runtime** — gate on "this leaf's thing count > 0" read from the runtime
   table rather than baked at emit.
3. **Constrain the sim** so a thing cannot leave its emit-time leaf. Rejected: that is not moving
   things, it is sliding them.

Whichever you pick, add an **assertion or a gate that fails loudly** when a thing's runtime leaf
was pruned. A silent vanish is unacceptable; a hard failure is fine.

## 4. What else is compile-time and must become runtime

- **`things_by_ss`** (`wall_renderer.py:440-445`) is built at emit by `point_in_subsector`, and
  the per-thing call sites are emitted INSIDE that leaf's code. Needs a runtime thing table plus
  either a runtime `point_in_subsector` per moved thing, or DOOM's own
  `P_UnsetThingPosition`/`P_SetThingPosition` per-leaf list. Sizing is friendly: mean ~1.9 things
  per occupied leaf, max 13, so the per-leaf loop is short and a BSP descent is cheap against a
  ~47k projection.
- **The per-thing constants** — x, y, z, sprite base, light class, min-size depth bound, monster
  flag — are baked as one xor-involution block per (subsector, thing). Moving things means those
  come from the table, not from a baked block.
- **The art is ONE still frame.** `sprite_art` resolves `A0/A1/A2A8/A1D1` — frame A, rotation 0.
  No walk cycle, no 8-way facing: a moving monster slides, facing one way. **Decide explicitly**
  whether M14 ships that (honest, and fine for a first cut) or adds rotations (a bank-size
  question — 8 rotations multiplies the sprite bank).

## 4b. ✅ FIXED — the renderer used to be byte-exact at INTEGER positions only

**Root cause: `proj.wall_x_range_m` read the view position's INTEGER MAP SLICE.** The lines-tier
leaf calls `wall_x_range_m`, not the `wall_x_range` the projection-kernel tests cover, and the
M13-mapmul optimisation inside it passed `viewx + 4*dw` / `viewy + 4*dw` — the top four nibbles —
to `point_to_angle_m`, and multiplied the affine cull by the map slice of `viewxa`/`viewya`. That is
exactly bit-identical **while `viewx = m<<16`**, which was true of every gate, test and golden this
repo has ever had. M14-c's sim breaks the premise from the player's second step: the low nibbles
carry a real fraction, the slice floors it, and the renderer draws the frame for the integer
position. The macro's own comment stated the premise; nothing had ever violated it.

**The fix** (`src/fj/projection.fj`): both halves of `wall_x_range_m` go back to full 16.16 width —
`hex.fixed_mul_lo 8, 4` for the affine cull and `.point_to_angle` for the two vertex atans, i.e. the
same arithmetic its non-`_m` twin has always used. The signature is untouched (the frozen ABI holds);
`dsl`/`dtb` survive as coarser measurement-only knobs, documented in place.

| | before | after |
|---|---|---|
| integer positions (10 random walkable × random angles) | 10/10 byte-exact | **10/10** |
| the same + half a map unit | 2/10 | **10/10** |
| `m14_gate` phase 2, 8 relayed tics from spawn | diverged at tic 2 | **8/8 byte-exact** |

**Cost: +3.3M–4.0M ops/frame (~+9–10%)** at the four gate viewpoints — the price the M13-mapmul
narrowing was buying, now paid back because the premise it rested on is gone. Correctness over op
budget, per §7. If it needs winning back, the lever is a *conditional*: the map-slice path is still
valid whenever the position's low nibbles are zero, so a per-frame test could pick the narrow path
for integer positions — but that is an optimisation to price separately, not a correctness matter.

<details><summary>The original blocker write-up, kept for the record</summary>

### ⚠ THE BLOCKER M14-c FOUND — the renderer is byte-exact at INTEGER positions only

**Read this before touching M14-c or M14-d.** The player sim is the first thing in this project
ever to produce a **fractional** player position. Every gate, every test and every golden in the
repo feeds `SimState(vx << 16, ...)` — a whole number of map units. In that regime the renderer is
in excellent shape; outside it, it is not.

Measured with `scratchpad/m14_vp_sweep.py` against the certified tier (one build, keys=0, so the
sim is not in the picture at all):

| player position | byte-exact frames |
|---|---|
| integer map units (10 random walkable points, random angles) | **10 / 10** |
| the same points + **half a map unit** (`--frac 0x8000`) | **2 / 10** (diffs 7–574 px of 16,000) |

That integer row is itself new: before this, "byte-exact" meant *four fixed viewpoints*.
`lite_sweep.py` visits many viewpoints but only counts ops — it never compared a pixel.

**Minimal repro** (no sim, no fractional y, one column, four pixels):

```bash
python scratchpad/m14_gate.py --probe -416 256 0x0 0     # BYTE-EXACT
```

then the same point with `x = (-416 << 16) + 0x8000`: 4 pixels differ, all in column 133, rows
68–72. Bisecting the fraction, `+0x1000` (1/16 unit) is still byte-exact and `+0x8000` is not.

**Diagnosis: the two mirrors propagate the sub-unit position through DIFFERENT parts of the
pipeline.** Measured at `(-267, 1458, 0xe8af30f7)`, comparing each side against ITSELF at the
integer and the half-unit position:

```
oracle(int) vs oracle(half): 494 px    the oracle moves this much for half a unit
fj(int)     vs fj(half)    : 105 px    fj moves, but only a fifth as much
fj(int)     vs oracle(int) :   0 px    the integer regime is exact
fj(half)    vs oracle(half): 574 px    ... and the two drift apart on the way
```

So it is **not** that fj discards the fraction (it moves 105 px) and **not** a single threshold
flipping — fj carries the fraction into part of the pipeline and drops it in the rest. `viewx`/
`viewy` (16.16, fraction intact) reach `proj.wall_x_range` and `proj.wall_offset`; other consumers
work from `vx`/`vy`, the 10-nibble integer map coordinate. On the oracle side `state.x` is used at
full precision in more places. **Find the consumers that differ — that is the whole bug.**

⚠ **RULED OUT, do not re-test it:** the `DEG_STACK_SCALE` far gate. The first hypothesis was that
the V5 stacked piece at the repro column flips on its scale threshold. It does not: binary-searching
`deg_stack_scale` shows the oracle still places that piece at a threshold of 2²², i.e. the column's
scale is ≥ 4,194,304 against a gate of 32,768 — a margin of +4,161,536. The gate is nowhere near
binding.

This is a **pre-existing renderer/oracle divergence, not something M14 introduced** — it reproduces
with `keys=0`, i.e. with the program behaving exactly as it did before this milestone. Nothing had
ever asked the renderer for a fractional viewpoint. But it *blocks* M14-c's byte-exactness claim,
because a walking player is fractional from its second step.

**Shape of the divergence** at that point (574 px, `fj(half)` vs `oracle(half)`): 53 of 160 columns
are touched, **median 6 pixels per column**, and **no column is wholly changed** — but three
(81, 87, 92) are 62–70 pixels of 100. So it is two effects at once: mostly ROW boundaries off by a
row or two across many columns, plus a few columns where a whole surface changed (a seg's claimed
x-range, or which seg won the column). Feature toggles on the oracle attribute those pixels to
`near_steps` / `stack_steps` / `plane_near` in roughly equal thirds and to `things` / `wall_noise`
not at all — i.e. it is the geometry, not the decoration.

### What the bisection has already ruled out — `scratchpad/m14_frac_bisect.py`, ~1 minute, no build

That script drives the projection kernels the way `tests/fj/test_projection_kernels.py` does (whose
every case feeds a whole number of map units) but with the low nibbles populated. Results:

| stage | fractional viewpoints | verdict |
|---|---|---|
| `proj.wall_setup` (→ rw_distance) | 4 points × {0, 1 ulp, ¼, ½, 0.99 unit} | **exact** |
| `proj.wall_x_range` (→ x1, x2, rw_angle1) | same | **exact** |
| `proj.wall_x_range` on the REAL E1M1 segs at the repro | 8 segs × {integer, ½} | **exact**, including the 133→134 shift |
| the emitter's OWN pass-1 head → the kernel | fed through the real wire | **exact** (`viewx=fe608000`, `viewxa=019f8000`, x1=134) |

That last row matters most: the wire loads the fraction, the M13-absmul derivation keeps it
(`viewxa` is the abs of the FULL 16.16, not of the integer part), and `wall_x_range` answers the
oracle's value. **So the fraction reaches the kernels intact and the kernels are right.** The
M13-absmul suspicion is dead, and so is the `DEG_STACK_SCALE` one.

And yet the shipped frame barely moves. At (-416, 256, 0) for a half unit:

```
x + 0.5 : fj moved   0 px, oracle moved   4
y + 0.5 : fj moved   2 px, oracle moved 216
both    : fj moved   0 px, oracle moved 214
x + 0.99: fj moved   0 px, oracle moved   8
```

**So the divergence is DOWNSTREAM of the kernels, inside the lines-tier leaf's own per-column and
piece machinery** — the part that turns an exact `(x1, x2, scale, rw_distance)` into claimed
columns, wall runs, V3/V5 pieces and plane regions. That is where to look next, and it is a much
smaller haystack than the whole renderer.

### Narrowed further: it is WHICH BOUNDARY WINS A COLUMN'S PIECE SLOT

The oracle's own `steps_out` for the repro column, at both positions:

```
-416.0   los[133] = [(63, 72, front floor 0, step 16, back floor 16)]   a RISER, rows 63..72
-416.5   los[133] = [(70, 70, front floor 0, step  0, back floor  0)]   a 1-row LIP (AQF054->AQF018)
```

So half a unit changes which boundary owns column 133's piece slot — riser to flat-change lip — and
fj keeps painting the riser. The colours line up exactly: the 104/105s fj shows at rows 68–72 are
the riser face, and the oracle's 75s are what shows once the riser stops covering the column.

Both degradation gates that could plausibly flip this are RULED OUT by binary-searching the
threshold at that column (do not re-test them):

| gate | value | the column's actual scale | margin |
|---|---|---|---|
| `DEG_STACK_SCALE` | 32,768 | ≥ 4,194,304 | +4,161,536 |
| `DEG_LIP_SCALE` | 16,384 | 32,875 | +16,491 |

Neither is anywhere near binding, so this is not a threshold landing on a knife edge — it is the
**piece-slot assignment itself**: which marking seg reaches the column first, and with what
`rng2`. That is `subsector_action`'s attribution path and the V5 slot machinery in
`stream_render.fj`, not the projection.

Options, in the order I would take them:
1. compare at the RECORD level, not the pixel level: the oracle already exposes `steps_out` /
   `planes_out` / `things_out`, and the fj frame is a 0x0B fillCol run-list before `StreamScreen`
   composites it. Diffing those two for the 4-pixel repro column names the disagreeing record
   directly, instead of inferring it from colours;
2. once found, feed the 16.16 position to whichever consumer is truncating (or truncate on the
   oracle side, if the integer really is the intended input) so the mirrors agree by construction;
3. (last resort, and against the owner's stated preferences) quantise the sim's position to whole
   map units, which hides a real bug rather than fixing it.

*(Option 2 is what shipped: the truncating consumer was `wall_x_range_m`'s map slice, and it now
takes the full 16.16. Option 1's record-level diff was never needed — the kernel-level bisect in
`m14_frac_bisect.py` reached the macro first.)*

</details>

## 5. Suggested rungs (each its own commit + gate)

- **M14-0 spike** ✅ **DONE** (`81c3796`) — measured; §2.1 has the numbers and the decision (binary).
- **M14-a** ✅ **DONE** (`fda6de4`) — the prune settled on `thing_live_subsectors`, both guards in,
  `deg_gate` byte-exact ×4 at +1.4% ops, 217 host tests incl. the shipped build.
- **M14-b** ✅ **DONE** — the binary wire round-trips; `m14_gate.py` phase 1 is byte-exact at all
  four viewpoints with the state echoed back unchanged, and the bin wire is 336k–603k ops
  *cheaper* than the decimals it replaces.
- **M14-c** ✅ **DONE.** The fj tic matches `step_sim` exactly — all 16 key combinations, a 200-tic
  relayed trajectory and the angle wrap (`tests/fj/test_state_wire.py`, 36 tests) — and the
  renderer-level gate passes too: `m14_gate` phase 1 byte-exact ×4, phase 2 **8/8 tics byte-exact
  with the state relayed**, once §4b's `wall_x_range_m` precision bug was fixed (+9–10% ops).
- **M14-d** ✅ **DONE and gated.** Oracle mirror (`check_position`/`try_move`/`move_with_collision`
  = P_CheckPosition / PIT_CheckLine / P_BoxOnLineSide + the subsector seed, 20 host tests);
  `mapcompiler.build_blockmap` (256-unit cells) narrowing ~1.5k linedefs to ~35, PROVEN equivalent
  to the exhaustive sweep; `src/fj/sim.fj`'s `check_line` / `check_block` / `check_position` /
  `try_move`, each oracle-exact; wired into `player_sim` with a second, tagged BSP descent for the
  candidate's seed. **Gate: phase 1 byte-exact ×4, phase 2 26/26 relayed tics byte-exact, with
  collision changing the outcome on 5 of them.** Cost ~+1–2M ops/tic on top of §4b's fix.
  Departures from vanilla, mirrored on both sides: no dropoff test, axis retry not `P_SlideMove`.
  ⚠ Two dead ends are recorded so they are not re-walked: bake-as-code for the per-block line
  tests (~57k macro lines, **did not assemble in 50 minutes**), and a gate whose script never
  touches a wall (vacuous — `phase2` now counts blocked tics and fails at zero, which is what
  caught `cprad` being left at zero and collapsing the collision box to a point).
- **M14-e** ❌ **NOT STARTED — the last rung, and the biggest.** §3's trap is already disarmed
  (M14-a), so what remains is the sprite pipeline itself. The analysis, so the next session starts
  from a design rather than a blank page:

  **What is baked per (subsector, thing) today** (`subsector_action`): one xor-involution block
  holding `sp_x/sp_y/sp_z`, `sp_left/sp_w/sp_hh`, `sp_tzmax(+2)`, `sp_mon`, `sp_base(+2)`,
  `sp_dw`, `sp_lt` — then `stl.fcall thing_leaf`. Three groups, and they do NOT move together:
   1. **position** (`sp_x/sp_y`) — pure runtime, straight from the table;
   2. **per TYPE** (`sp_left/sp_w/sp_hh/sp_tzmax/sp_mon/sp_base/sp_dw`) — bake ONE table indexed
      by a type index carried in the thing's row; nothing here depends on where the thing is;
   3. ⚠ **per SECTOR** (`sp_z` = the thing's floor + the art's z-offset, and `sp_lt` = the light
      class from `wall_lightnum(sector.light)` × art height) — these change WHEN THE THING MOVES
      BETWEEN SECTORS, which is exactly what M14-e is for. Either recompute them from the leaf the
      per-thing descent lands in, or carry them in the wire row as part of the thing's state (the
      §2 architecture says state round-trips, and z is state).

  **Re-binding.** The per-thing BSP descent is now cheap and proven — M14-d added `tag` to
  `_bsp_descend_code` precisely so a second descent could exist, and a third is the same move.
  Its leaf action appends the thing to that leaf's runtime list.
  **The free win:** that descent visits exactly the ancestors of the thing's leaf, so setting a
  "thing below" flag on the way down costs nothing and restores the `tsstop` node gate at runtime —
  buying back M14-a's +1.4%.

  **Cost budget, already measured (§2.1):** 212 things × 5 values round-trip for ~542k ops, 1.2–1.6%
  of the frame. The wire is not the problem; the per-leaf lists and the leaf loop are the work.

  **Gate it the way M14-d was gated:** `m14_gate --collide` plus a thing that actually CHANGES LEAF
  during the run, with the gate failing if none does. Every vacuity trap in this milestone has been
  a script that never exercised the thing being tested.
