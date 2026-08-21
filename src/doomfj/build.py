"""H6 build system. `build` is the M0 hello-world smoke build; `build_doom` (M10/R0) integrates the
full E1M1 table set into one flat `.fjm` and measures the real address-span vs the flat limit.

`build_doom` generates every currently-buildable table — finesine trig (M6), reciprocal (M4/M5),
colormap + per-texture/per-flat texel tables + palette (M8, textures downscaled by the shared D5 lever),
the +4-offset deposit table (M5), the framebuffer, and the map geometry streams (M7; BSP-as-code
deferred to M12) — assembles them with a minimal mainline, and asserts `storage_mode == flat` with
`span_words < flat_limit` (R4). The full-E1M1 span feeds the DESIGN §1.2/§1.3 ledgers (R0)."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

import flipjump as fj
from flipjump.fjm.fjm_reader import Reader

from doomfj.config import Config, FLAT_MAX_WORDS
from doomfj.harness import W, FJM_LZMA_FAST, assemble_fjm, run_fjm
from doomfj.lut_generator import (
    generate_dispatch_table_fj, generate_offset_deposit_table_fj, generate_trig_idioms_fj,
)
from doomfj.mapcompiler import bake_bsp, compile_geometry_streams
from doomfj.tables import reciprocal_table
from doomfj.texturecompiler import compile_colormap, compile_flat, compile_palette, compile_texture
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer, write_program_files

_SRC_FJ = Path("src/fj")
# the fixed include set the runtime wall renderer assembles against (before the emitted main)
_RENDERER_INCLUDES = ["fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj"]
# ... plus these two for raster_mode="lines" (the shipping tier): the packed-byte ceiling/floor BAND
# lists pass-1 builds, and the 0x0B column-stream present that replaces the framebuffer raster.
_LINES_INCLUDES = ["plane_bands.fj", "stream_render.fj"]
# B0 (2026-08-18): the player sim. ⚠ LAST in the list -- fj top-level labels are global, so the
# ordered file list is equivalent to its concatenation and the order is the contract (R54). This is
# the same position m14_gate.py and scripts/walk_e1m1.py put it in.
_SIM_INCLUDES = ["sim.fj"]
# V4 needs sprite lumps and a cut-down map wad has none, so sprite art comes from a full wad.
DEFAULT_SPRITE_WAD = "assets/freedoom1.wad"


def _resolve_sprite_wad(map_wad, sprite_wad):
    """The wad V4 takes SPRITE art from: an already-loaded `WadFile`, a path, or the default —
    falling back to the map wad, and RAISING if nothing in reach carries an S_START..S_END block.
    Explicit failure, not a silent `things=False`: a feature that quietly does not run is the bug
    class this renderer has paid for twice (the V4 courtyard, both BSP prunes)."""
    def _has_sprites(w):
        return "S_START" in w.names() and "S_END" in w.names()

    if isinstance(sprite_wad, WadFile):
        if not _has_sprites(sprite_wad):
            raise ValueError("things=True: the given sprite_wad has no S_START..S_END lumps")
        return sprite_wad
    if sprite_wad is not None and Path(sprite_wad).exists():
        w = WadFile.from_path(str(sprite_wad))
        if not _has_sprites(w):
            # CR-2026-08: an existing-but-spriteless path raises exactly like a loaded WadFile
            # does -- silently substituting the map wad here was the one hole in the
            # "explicit failure" rule this docstring itself states.
            raise ValueError(
                f"things=True: {sprite_wad!r} exists but has no S_START..S_END lumps")
        return w
    if _has_sprites(map_wad):
        return map_wad
    raise ValueError(
        f"things=True needs sprite art: {sprite_wad!r} is absent or carries no sprite lumps, and "
        f"the map wad has none either. Pass sprite_wad=<a full wad> or build with things=False.")


def build(fj_src="src/fj/hello.fj", out_fjm="build/hello.fjm", metrics="build/metrics.json") -> dict:
    m = assemble_fjm([fj_src], out_fjm)
    term = run_fjm(out_fjm)
    m["op_counter"] = term.op_counter
    m["storage_mode"] = str(term.storage_mode)
    # R4 guard: the program MUST run on the flat path.
    assert m["storage_mode"] == "flat", f"R4: storage_mode is {m['storage_mode']!r}, not flat"
    Path(metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(metrics).write_text(json.dumps(m, indent=2))
    return m


def _safe(prefix: str, name: str) -> str:
    """A flipjump-legal label from a WAD lump name (e.g. 'A-YELLOW' -> 'tex_A_YELLOW')."""
    return f"{prefix}_" + re.sub(r"[^0-9A-Za-z_]", "_", name)


def _span_words(fjm_path: Path) -> int:
    """The assembled program's flat address-span in words = max(segment_start + segment_length).
    Compared against flat_max_words: storage_mode flips flat->hybrid when the limit drops below it."""
    return max(s.segment_start + s.segment_length for s in Reader(fjm_path).memory_segments)


def build_doom(wad_path, mapname="E1M1", *, cfg=None, out_fjm, generated_dir,
               texture_subset=None, flat_subset=None, lights=32, flat_max_words=None) -> dict:
    """Generate + assemble the E1M1 table set into one `.fjm`; return metrics incl. storage_mode,
    span_words, headroom, and per-category entry counts. Asserts flat + span < limit (R4).

    `texture_subset`/`flat_subset` (names) keep the committed test fast; pass None to integrate the
    whole level (the R0 measurement). `lights` is the colormap light-row count (32 = full)."""
    cfg = cfg or Config()
    wad = WadFile.from_path(wad_path)
    factor = cfg.TEXTURE_DOWNSCALE
    limit = flat_max_words or FLAT_MAX_WORDS
    gen = Path(generated_dir)
    gen.mkdir(parents=True, exist_ok=True)

    tex_names = texture_subset if texture_subset is not None else [d.name for d in wad.texture_defs()]
    flat_names = (flat_subset if flat_subset is not None
                  else [l.name for l in wad.lumps_between("F_START", "F_END")])

    entry_counts: dict[str, int] = {}

    # ── the mainline: hex/ptr/stack init + halt. Tables occupy span whether or not they're executed. ──
    main = "stl.startup_and_init_all\nstl.loop\n"

    # finesine (M6): the per-result-nibble trig table + read_sin/read_cos
    trig = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    entry_counts["finesine"] = cfg.TRIG_N

    # reciprocal / scale (M4 value kernel -> M5 dispatch): 16^3 distance buckets (kills the wall divide)
    recip_vals = reciprocal_table(cfg.TRIG_N, 16, 32)
    recip = generate_dispatch_table_fj("reciprocal", recip_vals, index_nibbles=3, result_nibbles=8)
    entry_counts["reciprocal"] = cfg.TRIG_N

    # colormap (M8): (light<<8 | colour) -> lit byte
    colormap = compile_colormap("colormap", wad, lights=lights, over_align=False)
    entry_counts["colormap"] = lights * 256

    # +4-offset deposit table (M5, D3)
    deposit = generate_offset_deposit_table_fj("deposit")
    entry_counts["deposit"] = 256

    # textures + flats (M8), downscaled by the shared D5 lever (factor)
    tex_parts, total_texels = [], 0
    defs = {d.name: d for d in wad.texture_defs()}
    for name in tex_names:
        tex_parts.append(compile_texture(_safe("tex", name), wad, name, downscale=factor))
        d = defs[name]
        total_texels += (d.width // factor) * (d.height // factor)
    for name in flat_names:
        tex_parts.append(compile_flat(_safe("flat", name), wad, name, downscale=factor))
        total_texels += (64 // factor) * (64 // factor)
    entry_counts["textures"] = total_texels
    entry_counts["texture_count"], entry_counts["flat_count"] = len(tex_names), len(flat_names)

    # palette device data (M8) + framebuffer (packed bytes) + map geometry streams (M7)
    palette = compile_palette("palette", wad)
    entry_counts["palette"] = cfg.NCOLORS
    framebuffer = f"framebuffer: hex.vec {2 * cfg.FB_SIZE}\n"   # FB_SIZE packed bytes (2 nibbles each)
    geometry = compile_geometry_streams(wad, mapname)

    # ── write the assemble list (mainline first = entry at addr 0) ──
    files = {
        "fj_consts.fj": cfg.emit_fj_consts(gen / "fj_consts.fj").read_text(encoding="utf-8"),
        "main.fj": main,
        "tables.fj": "\n".join([trig, recip, colormap, deposit]),
        "graphics.fj": "\n".join(tex_parts + [palette, framebuffer]),
        "map.fj": geometry,
    }
    paths = []
    for fname, text in files.items():
        p = gen / fname
        if fname != "fj_consts.fj":   # already written by emit_fj_consts
            p.write_text(text, encoding="utf-8")
        paths.append(p)

    out = Path(out_fjm)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False,
                lzma_fast=FJM_LZMA_FAST)
    assemble_seconds = round(time.perf_counter() - t, 3)
    term = fj.run(out, print_time=False, print_termination=False, flat_max_words=limit)

    span = _span_words(out)
    metrics = {
        "map": mapname,
        "downscale": factor,
        "storage_mode": str(term.storage_mode),
        "span_words": span,
        "flat_limit": limit,
        "headroom": round(limit / span, 3) if span else None,
        "fjm_bytes": out.stat().st_size,
        "assemble_seconds": assemble_seconds,
        "entry_counts": entry_counts,
    }
    # R4: no silent paged-mode fallback; the program must fit flat under the limit.
    assert metrics["storage_mode"] == "flat", f"R4: storage_mode {metrics['storage_mode']!r} != flat"
    assert span < limit, f"R4: span {span} >= flat limit {limit}"
    return metrics


# The M1 restore set SHIPS WITH THE PACKAGE. It is the default so the path is not re-typed at
# every call site (and so an installed copy uses the same one the tests do).
DEFAULT_RESTORE_SET = Path(__file__).resolve().parent / "data" / "m1_restore_set.json.gz"


def build_wall_renderer(wad_path, mapname="E1M1", *, cfg=None, out_fjm, generated_dir,
                        flat_max_words=None, floor_mode="FT1", wall_mode="W1R",
                        raster_mode="lines", plane_near=True, wall_noise=True, sky=True,
                        steps=True, things=True, sprite_wad=DEFAULT_SPRITE_WAD,
                        stack_steps=True, bbox_cull=True, deg=True,
                        state_wire="bin", player_sim=True, collide=True,
                        moving_things=True, self_reset=False, restore_set=DEFAULT_RESTORE_SET) -> dict:
    """M12rr — wire the OPTIMIZED runtime wall renderer into a shipped `.fjm` (replacing the M10 halt-only
    `build_doom` mainline for the renderer path). Emits the renderer via the SHARED
    `doomfj.wall_renderer.emit_wall_renderer` — the SAME emitter the byte-exact golden test renders through
    (R6 single source) — so every space optimization (M12oo pass-2 trampoline, M12pp/qq xor_by + xor-involution
    walk) ships here for free. Assembles against the renderer include set, then R0-gates: assert
    `storage_mode == flat` and `span < limit`. The renderer's fully-unrolled pass-2 + BSP walk push the span
    past the 2**23 default, so pass a RAISED `flat_max_words` (`config.RENDER_FLAT_MAX_WORDS`, 2**27
    since 2026-08-18 -- the M14 tier is 1.6% over 2**26) per DESIGN §1.2 (RAM-only cost). The
    viewpoint `(vx,vy,va)` is read from stdin at runtime; the gate run feeds an invalid byte so the input
    parser jumps to `bad:` and halts immediately (the span/storage_mode are load-time, so no full render is
    needed for the gate — the golden test does the byte-exact render).

    **The defaults are the SHIPPING tier**, i.e. what `scripts/walk_e1m1.py` puts on screen: the lines
    raster with W1R walls + FT1 floors + rung-3a `plane_near`, all four VISUAL FEATURES
    (V1 `wall_noise` grain, V2 `sky`, V3 `steps` faces, V4 `things` sprites) ON, and V5 `stack_steps`
    + the `bbox_cull` wedge subtree cull + the `deg` degradation package ON.

    ⚠ B0 (2026-08-18) — AND THE SHIPPED ARTIFACT NOW RUNS THE SIM. `state_wire="bin"`,
    `player_sim`, `collide` and `moving_things` default ON here because `scripts/walk_e1m1.py`
    turns them on, and A0.1's whole point is that the artifact shipped, the artifact certified and
    the artifact a human looks at are ONE program. Shipping a renderer while the walker ships a
    game would have re-created the divergence A0.1 just closed. The binary reads a BINARY wire
    (a decimal feed halts it after ~200 ops) and it is the M14 tier, ~68.2M span-words — which is
    why `config.RENDER_FLAT_MAX_WORDS` had to go to 2**27 (DESIGN §1.2).

    ⚠ CR-2026-08 (IN-3, A0.1) — THIS SENTENCE USED TO BE FALSE, which is why it is now spelled out
    flag by flag. `stack_steps`, `bbox_cull` and `deg` were never passed here at all and defaulted
    OFF in the emitter, and `wall_mode` was WPX where the walker uses W1R — so THREE entry points
    built THREE different renderers: the artifact shipped, the artifact certified by
    `scratchpad/deg_gate.py`, and the artifact a human actually looked at. Optimizing or certifying
    any one of them said little about the others. If you add an emit-shaping keyword, add it HERE
    and to the walker in the same commit, or the divergence comes straight back. Every one is byte-exact
    against the oracle (`tests/fj/test_visual_features.py`); before this they were emitter keywords that
    only the walker and that test ever passed, so the shipped binary rendered a strictly older picture
    than the project's own screenshots. The older tiers stay reachable by keyword
    (`raster_mode="framebuffer", floor_mode="textured", wall_mode="textured"` is the pre-lines build).

    ⚠ V4 needs SPRITE ART, and a cut-down map wad has no sprite lumps at all — hence `sprite_wad`,
    which defaults to `assets/freedoom1.wad` and falls back to the map wad when that file is absent.
    If neither carries sprites this RAISES rather than quietly dropping the feature: a silently
    not-running feature is exactly the class of bug that cost this repo the most (docs/opt-experiments.md).
    """
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    cfg = cfg or Config()
    wad = WadFile.from_path(wad_path)
    limit = flat_max_words or FLAT_MAX_WORDS
    gen = Path(generated_dir); gen.mkdir(parents=True, exist_ok=True)
    spr = _resolve_sprite_wad(wad, sprite_wad) if things else None

    parts = emit_wall_renderer(wad, mapname, cfg, over_align=False, floor_mode=floor_mode,
                               wall_mode=wall_mode, raster_mode=raster_mode, plane_near=plane_near,
                               wall_noise=wall_noise, sky=sky, steps=steps, things=things,
                               sprite_wad=spr, stack_steps=stack_steps, bbox_cull=bbox_cull,
                               deg=deg, state_wire=state_wire, player_sim=player_sim,
                               collide=collide, moving_things=moving_things, return_parts=True)
    consts = cfg.emit_fj_consts(gen / "fj_consts.fj")
    # The emitted program goes out as SEPARATE files: the huge machine-written regions (LUT and
    # dispatch tables, per-seg constant blocks, the BSP walk, the baked banks) no longer share a
    # file with the ~50-line program. ⚠ Order is load-bearing -- see write_program_files.
    prog = write_program_files(parts, gen, mapname)
    includes = (_RENDERER_INCLUDES + (_LINES_INCLUDES if raster_mode == "lines" else [])
                + (_SIM_INCLUDES if player_sim else []))   # B0: sim.fj LAST (R54)
    paths = [consts] + [_SRC_FJ / f for f in includes] + prog

    out = Path(out_fjm); out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    reset_info = None
    if self_reset:
        # M1 -- the program restores itself and LOOPS, so the host never reloads the image.
        # TWO PASSES, and the second is not a re-run: pass 1 exists only to learn where every cell
        # landed. The reset bakes those addresses (it must -- most of the dirty set is macro-local
        # scratch, which fj cannot name from outside its macro), is APPENDED as a new last part,
        # and patches the frame tail size-neutrally, so pass 2 has to place every restored cell at
        # the same address. That is ASSERTED below, not assumed: a reset writing shifted addresses
        # does not produce a wrong pixel, it produces a different program.
        assert restore_set, "self_reset=True requires restore_set (see docs/handoff-m1-reset.md)"
        from doomfj import selfreset
        from doomfj.fastrun import FjmRunner, _fjcore
        # ⚠ m1_reset.fj goes LAST, AFTER the emitted parts -- not into `includes`. A macro-expansion
        # label is named `f<file>:l<line>:...`, so inserting a file anywhere earlier renumbers every
        # label in every file after it, and the restore set (which names labels) stops resolving.
        # Measured: adding it to the includes renamed 200 of the set's labels and the loader
        # refused, exactly as it should. A file that only holds a `def` emits no ops, so appending
        # it moves no address.
        paths = paths + [_SRC_FJ / "m1_reset.fj"]
        labels1 = selfreset.capture_labels(paths, out, lzma_fast=FJM_LZMA_FAST)
        r1 = FjmRunner(out, flat_max_words=limit)
        core1 = _fjcore.Memory(r1.width, flat_max_words=r1.flat_max_words)
        for _s, _n in r1._segments:
            core1.add_segment(_s, _n)
        for _st, _v in r1._runs:
            core1.set_words(_st, _v)
        # view_w/nss are the SECOND source the byte-array cell counts are checked against; the
        # first is each array's label extent in this build's own table. Both must agree, so a
        # resolution or map change cannot silently nibble-clear a byte cell (see selfreset.py).
        nss = len(bake_bsp(wad, mapname).subsectors)
        part, n_nib, n_byte = selfreset.emit_reset_part(gen, labels1, core1.get_word,
                                                        restore_set, cfg.VIEW_W, nss, mapname)
        del core1, r1
        paths = paths + [part]
        labels2 = selfreset.capture_labels(paths, out, lzma_fast=FJM_LZMA_FAST)
        moved = selfreset.verify_labels_unchanged(labels1, labels2, restore_set)
        assert not moved, ("M1 self-reset REFUSED: %d baked addresses moved between passes, e.g. %s"
                           % (len(moved), sorted(moved)[:3]))
        reset_info = {"nibble_cells": n_nib, "byte_cells": n_byte,
                      "restore_set": str(restore_set), "labels_moved_in_set": 0,
                      "view_w": cfg.VIEW_W, "subsectors": nss}
    else:
        fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False,
                    lzma_fast=FJM_LZMA_FAST)
    assemble_seconds = round(time.perf_counter() - t, 3)
    term = fj.run(out, io_device=FixedIO(b"q\n"), print_time=False, print_termination=False,
                  flat_max_words=limit)                    # 'q' is not a digit -> input parser -> bad: -> halt
    span = _span_words(out)
    metrics = {
        "map": mapname, "downscale": cfg.TEXTURE_DOWNSCALE,
        "storage_mode": str(term.storage_mode), "span_words": span, "flat_limit": limit,
        "headroom": round(limit / span, 3) if span else None,
        "fjm_bytes": out.stat().st_size, "assemble_seconds": assemble_seconds,
        "tier": f"{raster_mode}/{wall_mode}/{floor_mode}" + ("+plane_near" if plane_near else ""),
        # CR-2026-08 (IN-3, A0.1): the metrics used to describe only FOUR of the emit-shaping flags,
        # so the three that had silently diverged (stack_steps/bbox_cull/deg) were invisible to every
        # consumer of metrics.json AND to the R4 gate below. A flag that shapes the picture is now
        # reported; add new ones here in the same commit that adds them to the signature.
        "features": {"wall_noise": wall_noise, "sky": sky, "steps": steps, "things": things,
                     "stack_steps": stack_steps, "bbox_cull": bbox_cull, "deg": deg,
                     # B0: the sim half. Reported for the same reason as the rest -- a flag that
                     # shapes the artifact must be visible in metrics.json, or the next divergence
                     # is invisible again.
                     "player_sim": player_sim, "collide": collide,
                     "moving_things": moving_things, "state_wire": state_wire,
                     # M1: the program self-resets and loops -- one run renders many frames.
                     "self_reset": self_reset},
        "self_reset": reset_info,
    }
    assert metrics["storage_mode"] == "flat", f"R4: storage_mode {metrics['storage_mode']!r} != flat"
    assert span < limit, f"R4: span {span} >= flat limit {limit}"
    return metrics


def build_present_slice(wad_path, *, cfg=None, col_x, color, out_fjm, generated_dir):
    """M11a (F4+F7): assemble the present slice — a packed-byte framebuffer with column `col_x` filled
    `color` (F4 fixed stores), the real E1M1 palette, and the F7 0x03 present — then run it headless
    through the screen device and capture the frame. Returns the device pixel_indices + per-frame
    sha256 + op_counter + storage_mode + span_words."""
    from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

    cfg = cfg or Config()
    wad = WadFile.from_path(wad_path)
    gen = Path(generated_dir)
    gen.mkdir(parents=True, exist_ok=True)

    consts = cfg.emit_fj_consts(gen / "fj_consts.fj")
    palette = compile_palette("palette", wad)
    main = "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        f"fb.fill_column framebuffer, {col_x}, {color}",
        "present.set_palette palette",
        "present.update_screen framebuffer",
        "stl.loop",
        f"framebuffer: hex.vec {cfg.FB_SIZE}",   # W*H packed-byte ops (one op/pixel)
        palette,
    ])
    (gen / "main.fj").write_text(main, encoding="utf-8")

    paths = [consts, Path("src/fj/present.fj"), Path("src/fj/framebuffer.fj"), gen / "main.fj"]
    out = Path(out_fjm)
    out.parent.mkdir(parents=True, exist_ok=True)
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False,
                lzma_fast=FJM_LZMA_FAST)

    screen = InMemoryScreen()
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False)
    return {
        "storage_mode": str(term.storage_mode),
        "span_words": _span_words(out),
        "op_counter": term.op_counter,
        "frame_count": screen.frame_count,
        "pixel_indices": screen.pixel_indices,
        "frame_hash": screen.frame_hashes[-1][1] if screen.frame_hashes else None,
        "fjm_bytes": out.stat().st_size,
    }


def build_textured_column(wad_path, texname, *, cfg=None, texcol, light, count, step, frac0=0,
                          downscale=None, out_fjm, generated_dir):
    """M11b (F5): assemble + run one textured wall column — the texture-v DDA (src/fj/wall_render.fj)
    over the M8 texel + colormap dispatch tables — and capture its per-row lit bytes (emitted as text,
    the proof path). Returns the captured output + op_counter + per-pixel op cost + storage_mode/span.
    `texcol`/`light` are the column constants; `step` is the 8.8 DDA step; the texture is downscaled by
    the shared D5 factor (matching the oracle)."""
    from flipjump.interpreter.io_devices.FixedIO import FixedIO

    cfg = cfg or Config()
    factor = downscale if downscale is not None else cfg.TEXTURE_DOWNSCALE
    wad = WadFile.from_path(wad_path)
    defs = {d.name: d for d in wad.texture_defs()}
    texheight = defs[texname].height // factor
    base = texcol * texheight
    gen = Path(generated_dir)
    gen.mkdir(parents=True, exist_ok=True)

    tex = compile_texture("tex", wad, texname, downscale=factor)
    cm = compile_colormap("cm", wad, lights=max(32, light + 1), over_align=False)
    main = "\n".join([
        "stl.startup_and_init_all",
        f"hex.set 4, frac, {frac0}",
        f"rep({count}, r) wall.column_step {base}, {light}",
        "stl.loop",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "pal: hex.vec 2",
        "cmidx: hex.vec 4", "lit: hex.vec 2", f"step: hex.vec 4, {step}",
        f"heightmask: hex.vec 3, {texheight - 1}",
        tex, cm,
    ])
    (gen / "main.fj").write_text(main, encoding="utf-8")

    out = Path(out_fjm)
    out.parent.mkdir(parents=True, exist_ok=True)
    fj.assemble([Path("src/fj/wall_render.fj").resolve(), (gen / "main.fj").resolve()], out,
                memory_width=W, print_time=False, lzma_fast=FJM_LZMA_FAST)
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    return {
        "storage_mode": str(term.storage_mode),
        "span_words": _span_words(out),
        "op_counter": term.op_counter,
        "per_pixel_ops": term.op_counter // count,
        "output": io.get_output(allow_incomplete_output=True),
    }


def build_unroll_frame(wad_path, texname, *, cfg=None, light, width=None, count=None, step, frac0=0,
                       downscale=None, lights=None, out_fjm, generated_dir, run=True):
    """M11c (F5 / D2b — the D2 bake-off): assemble (+ optionally run) the FULL-UNROLL renderer —
    `rep(width, x) frame.column ... rep(count, row) frame.pixel ...` writing each pixel DIRECTLY into its
    hex.vec2 framebuffer cell (no deposit, §2.1). With `run=True` it also presents over the 0x06 register
    device and captures the frame headless (pixel_indices + per-frame sha256 + op_counter/per_pixel_ops).

    `run=False` assembles ONLY — returns assemble_seconds + fjm_bytes + span_words (the R-2/R-4 gate
    numbers) without executing. Executing a full 160x100 frame is ~24M ops through the headless
    interpreter (minutes); the gate needs only the ASSEMBLE time + span, and ops/frame is extrapolated
    from a small run's per_pixel_ops — so the full-scale measurement uses run=False.

    `width`/`count` default to the full viewport (VIEW_W x VIEW_H = the bake-off scale); pass smaller for
    the fast committed golden. The synthetic frame splats texcol = x % texwidth across the screen at a
    constant `light`/`step` (matching the oracle). The two per-pixel tables are over-aligned (§2.1)."""
    cfg = cfg or Config()
    factor = downscale if downscale is not None else cfg.TEXTURE_DOWNSCALE
    width = width if width is not None else cfg.VIEW_W
    count = count if count is not None else cfg.VIEW_H
    wad = WadFile.from_path(wad_path)
    defs = {d.name: d for d in wad.texture_defs()}
    texheight = defs[texname].height // factor
    texwidth = defs[texname].width // factor
    lights = lights if lights is not None else max(32, light + 1)
    gen = Path(generated_dir)
    gen.mkdir(parents=True, exist_ok=True)

    consts = cfg.emit_fj_consts(gen / "fj_consts.fj")
    # §2.1: over-align both very-hot per-pixel dispatch tables (texture + colormap).
    tex = compile_texture("tex", wad, texname, over_align=True, downscale=factor)
    cm = compile_colormap("cm", wad, lights=lights, over_align=True)
    palette = compile_palette("palette", wad)

    stride = cfg.W
    render = []
    for x in range(width):
        render.append(f"frame.setup_col {(x % texwidth) * texheight}, {light}, {step}, {frac0}")
        for row in range(count):
            render.append(f"frame.pixel framebuffer + {2 * (row * stride + x)}*dw")
    main = "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        *render,
        "present.set_palette palette",
        "present.update_screen_reg framebuffer",
        "stl.loop",
        "pixel_leaf:",                                # the shared per-pixel leaf (emitted ONCE)
        "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",   # register form: 2 ops/pixel (low, high nibble)
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {texheight - 1}",
        "pixel_ret: ;0",                             # the stl.fcall return-register (one op)
        tex, cm, palette,
    ])
    (gen / "main.fj").write_text(main, encoding="utf-8")

    paths = [consts, Path("src/fj/present.fj"), Path("src/fj/frame_render.fj"), gen / "main.fj"]
    out = Path(out_fjm)
    out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False,
                lzma_fast=FJM_LZMA_FAST)
    assemble_seconds = round(time.perf_counter() - t, 3)

    pixels = width * count
    m = {
        "span_words": _span_words(out),
        "assemble_seconds": assemble_seconds,
        "fjm_bytes": out.stat().st_size,
        "width": width,
        "count": count,
        "pixels": pixels,
    }
    if not run:
        return m

    from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
    screen = InMemoryScreen()
    term = fj.run(out, io_device=screen, print_time=False, print_termination=False)
    m.update({
        "storage_mode": str(term.storage_mode),
        "op_counter": term.op_counter,
        "per_pixel_ops": term.op_counter // pixels if pixels else 0,
        "pixel_indices": screen.pixel_indices,
        "frame_hash": screen.frame_hashes[-1][1] if screen.frame_hashes else None,
    })
    return m


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
