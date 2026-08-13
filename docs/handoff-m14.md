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

## 4b. ⚠ THE BLOCKER M14-c FOUND — the renderer is byte-exact at INTEGER positions only

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

**Diagnosis so far.** Re-rendering the oracle with features toggled at that exact point:

```
oracle all on       col133 rows 66..74: [1, 2, 75, 75, 104, 6, 6, 6, 6]
oracle stack=False  col133 rows 66..74: [1, 2,  8,  8, 104, 6, 6, 6, 6]
fj                  col133 rows 66..74: [., .,104,104,   .,104,105, ., .]
```

The 75s are a **V5 stacked boundary piece** the oracle places and fj does not; fj paints wall
colour through those rows instead. V5 pieces sit behind a *scale threshold* gate
(`DEG_STACK_SCALE`, 16384). A threshold is exactly what a sub-unit position change perturbs: at
integer positions the per-column scale lands far from 16384, at fractional ones it lands on it, and
a one-ulp difference between the two mirrors' scale then decides the piece differently. **That is
the hypothesis to test first — instrument the per-column scale on both sides at (-416.5, 256).**

This is a **pre-existing renderer/oracle divergence, not something M14 introduced** — it reproduces
with `keys=0`, i.e. with the program behaving exactly as it did before this milestone. But it
*blocks* M14-c's byte-exactness claim, because a walking player is fractional from its second step.

Options, in the order I would take them:
1. find the one-ulp difference and fix it (the mirrors then agree everywhere);
2. if the scale genuinely cannot be made bit-identical, move the V5 gate off a raw scale compare
   onto a quantity both sides compute identically;
3. (last resort, and against the owner's stated preferences) quantise the sim's position to whole
   map units, which hides a real bug.

## 5. Suggested rungs (each its own commit + gate)

- **M14-0 spike** ✅ **DONE** (`81c3796`) — measured; §2.1 has the numbers and the decision (binary).
- **M14-a** ✅ **DONE** (`fda6de4`) — the prune settled on `thing_live_subsectors`, both guards in,
  `deg_gate` byte-exact ×4 at +1.4% ops, 217 host tests incl. the shipped build.
- **M14-b** ✅ **DONE** — the binary wire round-trips; `m14_gate.py` phase 1 is byte-exact at all
  four viewpoints with the state echoed back unchanged, and the bin wire is 336k–603k ops
  *cheaper* than the decimals it replaces.
- **M14-c** ⚠ **BUILT AND PROVEN AS A SIM, NOT CERTIFIED AS A FRAME.** The fj tic matches
  `step_sim` exactly: all 16 key combinations, a 200-tic relayed trajectory, and the angle wrap
  (`tests/fj/test_state_wire.py`, 36 tests). The renderer-level gate then walks into §4b — the
  first fractional position diverges. **§4b is the next piece of work, and it is not M14's fault.**
- **M14-d** ⚠ **ORACLE DONE, fj NOT STARTED.** `check_position` / `try_move` /
  `move_with_collision` mirror P_CheckPosition / PIT_CheckLine / P_BoxOnLineSide (no blockmap: the
  per-line bbox reject does that job, ~1.5k lines against a ~34M-op frame). 16 tests in
  `tests/host/test_collision.py`, including the control that collision actually blocks something.
  Two departures from vanilla are documented in the docstrings and must be mirrored in fj:
  no dropoff test, and axis-separated retry instead of `P_SlideMove`. The fj half wants a baked
  packed linedef table + a runtime loop; `hex.read_table_packed` is the primitive.
- **M14-e** ❌ **NOT STARTED** — the runtime thing table + moving things. §3 is settled, so the
  trap is disarmed; what remains is real work: per-thing constants out of the baked per-leaf
  xor-involution blocks and into a runtime table, a runtime `point_in_subsector` per moved thing,
  and per-leaf lists. Note the free win waiting there: the per-thing BSP descent visits exactly
  the ancestors of the thing's leaf, so setting a "thing below" flag on each costs nothing and
  buys back M14-a's 1.4% by restoring the `tsstop` node gate at runtime.

## 6. Verification (see `CLAUDE.md` for the full ladder)

Every rung: `alpha_check`/`expand_check` if you touched fj macros, `tests/host`, then
`scratchpad/deg_gate.py` (~20 min, SOLO). A rung that changes what is drawn needs a new oracle
mirror and a byte-exact test **before** the fj side (R1: failing test first).

⚠ After touching `build.py`, run `test_build_wall_renderer_e1m1_flat` — it is deselected from the
normal run and it is the SHIPPED path (~70 min).

⚠ New for M14: the sim is stateful across frames, which the current gates are not built for. You
will need a **multi-frame** gate — run N tics from a fixed start with a scripted input sequence
and compare the whole sequence against the oracle. One frame proving byte-exact says nothing
about state drift on frame 200.

**That gate now exists, at two levels:**
- `tests/fj/test_state_wire.py::test_sim_matches_the_oracle_over_N_tics` — 200 tics of the sim
  alone, each tic's echoed state relayed into the next, ~20 s and no renderer build. This is where
  a sim bug should be caught.
- `scratchpad/m14_gate.py` — phase 1 (four still viewpoints) + phase 2 (N tics, frame *and* state
  compared every tic). It **caches its binary** at `scratchpad/fjmcache/m14_bin.fjm` and takes
  `--probe vx vy va keys` for a single frame, so a divergence can be chased without a 25-minute
  rebuild. `--rebuild` forces a fresh one.
- `scratchpad/m14_vp_sweep.py` — byte-exactness over MANY viewpoints (the repo had none: every
  gate certified the same four, and `lite_sweep.py` counts ops without comparing a pixel). It is
  what turned §4b from "one bad frame" into a measured boundary.

⚠ And the trap the multi-frame gate found on its first run, now fixed and regression-tested:
`SimState` normalises x/y to signed on construction. `spawn_state` built them SIGNED, `step_sim`
returned them MASKED, and the projection reads `state.x` **raw** while everything else goes through
`_signed` — so feeding a simulated state back into the renderer rendered a different frame from the
identical hand-built one (14,845 of 16,000 pixels). Nothing had ever composed those two functions.

## 7. Standing preferences (owner)

Correctness and detail over op budget; fix-it-everywhere over spot fixes; CR loops until clean;
report with evidence (hashes, op counts, before/after), never adjectives. A budget that binds
paints wrong pixels — bound cost with provably write-neutral stops instead.
