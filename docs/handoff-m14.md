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

⚠ **MEASURE BEFORE YOU COMMIT TO IT.** E1M1-lite has **212 things**. If each round-trips
(x, y, z, angle, state) as decimals, that is ~1000 `hex.input_dec_int` calls per frame and the
per-call cost is **unmeasured**. At ~23M ops/frame today, an input path costing even 20k
ops/number would double the frame. **Rung 0 is a spike that measures `hex.input_dec_int` and
`stl.output_char` per number**, and the answer decides the wire format:
- cheap → decimals, simplest;
- expensive → a packed binary form, or only round-trip things that MOVED (a dirty list), or keep
  thing sim host-side for M14 and move it in M15.
Do not design the wire format before that number exists. Write the number into this file.

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

## 5. Suggested rungs (each its own commit + gate)

- **M14-0 spike** — measure `hex.input_dec_int` / output cost per number. Decide the wire format.
  No behaviour change. *(Write the measured number into §2 of this file.)*
- **M14-a** — the prune decision from §3, with the loud-failure guard. Renderer output must stay
  **byte-exact** (nothing moves yet), so `deg_gate` op counts may change but pixels must not.
- **M14-b** — state round-trip: the program reads player state + input, re-emits it unchanged.
  Byte-exact vs today when the input is the current viewpoint.
- **M14-c** — the player sim in fj (turn/move), byte-exact vs the oracle's existing step.
- **M14-d** — line collision, against a new oracle mirror. This is the substantial new algorithm.
- **M14-e** — the runtime thing table + moving things, with per-frame re-binding to leaves.

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

## 7. Standing preferences (owner)

Correctness and detail over op budget; fix-it-everywhere over spot fixes; CR loops until clean;
report with evidence (hashes, op counts, before/after), never adjectives. A budget that binds
paints wrong pixels — bound cost with provably write-neutral stops instead.
