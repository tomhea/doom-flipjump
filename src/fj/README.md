# `src/fj/` — the hand-written FlipJump

Read this before opening anything else. **7 of these 13 files are the program; 6 are not called by
anything** and exist only for their own tests.

Everything else in the shipped image is machine-written into `build/generated_loop/` — see
[the generated side](#the-generated-side) at the bottom.

## The program

Listed in include order (`build.py:_RENDERER_INCLUDES` + `_LINES_INCLUDES` + `_SIM_INCLUDES`).
fj top-level labels are global, so **the order is the contract** — never reorder.

| file | lines | macros | called from `MAIN` | what it is |
|---|---:|---:|---|---|
| `fixed_point.fj` | 243 | 10 | `hex.fixed_mul_lo`, `hex.mul_lo` | 16.16 fixed-point + the packed-table reads. Extends the stl's `hex` namespace, so everything uses it. |
| `present.fj` | 230 | 14 | `init_screen_stream`, `set_palette`, `begin_frame_collines` | drives the screen device: command bytes on the output stream. |
| `projection.fj` | 2,122 | 32 | `point_on_side_leaf`, `wedge_setup`, `wedge_bbox` | the projection math — angles, scales, column ranges. 12 more macros are called by `frame_render.fj`. |
| `frame_render.fj` | 3,402 | 82 | `seg_pass1_leaf_body_lines`, `seg_pass1_leaf_body_ts`, `seg_pass2_leaf_body_lines`, `thing_record_body` | the frame. **Only 7 of its 82 macros are called from outside**; the rest are its internals. |
| `stream_render.fj` | 1,542 | 41 | `emit_bytes4` | the per-column run emitter — pushes runs to the device. |
| `sim.fj` | 607 | 10 | `check_position`, `try_move`, `bind_things`, `thing_pass` | the player sim: collision against real linedefs. |
| `m1_reset.fj` | 85 | 4 | `m1.zerobyte` | M1's self-reset primitives (constant-address byte clear). |

**Where the time goes.** Per frame the four `MAIN` entry points in `frame_render.fj` dominate;
`projection.fj` is the arithmetic under them. Start there.

## NOT called by anything

Assembled into every build, never instantiated. fj only emits macros that are actually expanded, so
these cost **no span** — but they cost reading time, and two of them sit in the *shipping tier*
include list, which is misleading.

| file | lines | why it is still here |
|---|---:|---|
| `plane_render.fj` | 340 | the pre-"lines" framebuffer floor/ceiling raster. In `_RENDERER_INCLUDES`. Live only in `test_plane_kernel.py`, `test_floor_planes_fj.py`, `test_plane_span_pass.py`. |
| `plane_bands.fj` | 298 | the per-column band-list builder it replaced; the shipped path uses the GENERATED `vpb_walk` instead (`stream_render.fj:811`). In `_LINES_INCLUDES`. |
| `wall_render.fj` | 33 | an early wall demo. `test_render_macros.py`. |
| `framebuffer.fj` | 28 | framebuffer pixel demo. `test_framebuffer.py`. |
| `memory_map.fj` | 19 | a layout probe. `test_build.py`. |
| `hello.fj` | 3 | the toolchain smoke test. `test_toolchain.py`. |

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

| file | lines | what |
|---|---:|---|
| `e1m1_00_entry.fj` | 32 | jumps to `main` |
| `e1m1_01_tables.fj` | 334,667 | trig/reciprocal LUTs + the dispatch tables |
| **`e1m1_02_main.fj`** | **202** | **the actual program** — this is the one to read |
| `e1m1_03_segconsts.fj` | 43,294 | per-seg baked constants |
| `e1m1_04_walk.fj` | 92,154 | the BSP walk, as code |
| `e1m1_05_state.fj` | 129 | the runtime state registers |
| `e1m1_06_banks.fj` | 5,407,895 | baked sprite / step / sky / band banks |
| `e1m1_07_reset.fj` | 638 | M1's self-reset part |

The compiled image is `build/doom_e1m1_loop.fjm`.
