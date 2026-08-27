# `src/fj/` — the hand-written FlipJump

Read this before opening anything else. **7 of these 11 files are the program.**

Everything else in the shipped image is machine-written into `build/generated_loop/` — see
[the generated side](#the-generated-side) at the bottom.

## The program

Listed in include order (`build.py:_RENDERER_INCLUDES` + `_LINES_INCLUDES` + `_SIM_INCLUDES`).
fj top-level labels are global, so **the order is the contract** — never reorder.

| file | macros | called from `MAIN` | what it is |
|---|---:|---|---|
| `fixed_point.fj` | 10 | `hex.fixed_mul_lo`, `hex.mul_lo` | 16.16 fixed-point + the packed-table reads. Extends the stl's `hex` namespace, so everything uses it. |
| `present.fj` | 14 | `init_screen_stream`, `set_palette`, `begin_frame_collines` | drives the screen device: command bytes on the output stream. |
| `projection.fj` | 32 | `point_on_side_leaf`, `wedge_setup`, `wedge_bbox` | the projection math — angles, scales, column ranges. 12 more macros are called by `frame_render.fj`. |
| `frame_render.fj` | 82 | `seg_pass1_leaf_body_lines`, `seg_pass1_leaf_body_ts`, `seg_pass2_leaf_body_lines`, `thing_record_body` | the frame. **Only 7 of its 82 macros are called from outside**; the rest are its internals. |
| `stream_render.fj` | 41 | `emit_bytes4` | the per-column run emitter — pushes runs to the device. |
| `sim.fj` | 10 | `check_position`, `try_move`, `bind_things`, `thing_pass` | the player sim: collision against real linedefs. |
| `m1_reset.fj` | 4 | `m1.zerobyte` | M1's self-reset primitives (constant-address byte clear). |

**Where the time goes.** Per frame the four `MAIN` entry points in `frame_render.fj` dominate;
`projection.fj` is the arithmetic under them. Start there.

## Not instantiated by the SHIPPED tier

`plane_render.fj` and `plane_bands.fj` implement OTHER build tiers the emitter still offers.
The emitter branches on five `raster_mode`s (`lines` — shipped — plus `proj`, `raster`, `spans`,
`stream`) and two `floor_mode`s (`FT1` — shipped — and `textured`), and the non-shipped ones
instantiate these files. `emit_wall_renderer` emits `recip32_leaf: plane.recip32` and
`build_bands_leaf: plane.build_bands` under `if stream:`.

Nothing here runs in `doom_e1m1_loop.fjm`, and they cost no span (fj only emits macros that are
actually expanded). But they are not deletable without dropping the tiers they implement.

| file | instantiated by | tests |
|---|---|---|
| `plane_render.fj` | `floor_mode="textured"` and the non-`lines` rasters | `test_plane_kernel`, `test_floor_planes_fj`, `test_plane_span_pass` |
| `plane_bands.fj` | `raster_mode="stream"` (in `emit_wall_renderer`) | `test_plane_bands_fj`, `test_stream_pass1_wiring` |
| `memory_map.fj` | nothing at runtime; it consumes `fj_consts.fj`, so it checks the constants file is usable | `test_build` |
| `hello.fj` | nothing — the toolchain canary: proves the assembler runs at all | `test_toolchain` |

⚠ Two of `m1_reset.fj`'s four macros — `m1.readbyte` and `m1.writebyte` — are also uncalled by the
program. They were built for the C1 constant-address dispatch, which does not work (see
`docs/handoff-constaddr.md` §9); their tests are real and they are cheap to keep.

## Conventions

- **`@` is control-flow labels, `<` is named state.** A macro's `@` list should contain jump
  targets, not `hex.vec` declarations — a vec inside a `rep`-expanded macro is emitted once per
  expansion, which is how the M1 restore set ended up naming registers by expansion path
  (`f9:l208:rep0:sim.check_block(14)---...---p1`). `sim.check_block` / `check_line` were fixed;
  the pattern to copy is `cb_*` / `cl_*` in `collision.py::CHECK_SCRATCH_DECLS`.
- **The emitter ABI is frozen.** fj *global* labels, *macro names* and *positional parameter lists*
  appear inside Python f-strings, so they are not safely renameable in isolation — that is a
  fan-out edit into `src/doomfj/*.py`. `@`-locals, macro-local labels and comments are free.
  `scratchpad/cr/alpha_check.py` enforces exactly this.
- **Heavy code goes in a shared `stl.fcall` leaf**, not inlined per pixel/column — inlining it is
  what made assembly super-linear.

## The generated side

`build/generated_loop/`, written by `doomfj.wall_renderer.emit_wall_renderer` +
`write_program_files`. **Order is load-bearing**: every baked address constant depends on the
layout, so never sort, glob, or reorder these.

| file | what |
|---|---|
| `e1m1_00_entry.fj` | jumps to `main` |
| `e1m1_01_tables.fj` | trig/reciprocal LUTs + the dispatch tables |
| **`e1m1_02_main.fj`** | **the actual program** — this is the one to read |
| `e1m1_03_segconsts.fj` | per-seg baked constants |
| `e1m1_04_walk.fj` | the BSP walk, as code |
| `e1m1_05_state.fj` | the runtime state registers |
| `e1m1_06_banks.fj` | baked sprite / step / sky / band banks |
| `e1m1_07_reset.fj` | M1's self-reset part |

The compiled image is `build/doom_e1m1_loop.fjm`.
