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
from doomfj.harness import W, assemble_fjm, run_fjm
from doomfj.lut_generator import (
    generate_dispatch_table_fj, generate_offset_deposit_table_fj, generate_trig_idioms_fj,
)
from doomfj.mapcompiler import compile_geometry_streams
from doomfj.tables import reciprocal_table
from doomfj.texturecompiler import compile_colormap, compile_flat, compile_palette, compile_texture
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer

_SRC_FJ = Path("src/fj")
# the fixed include set the runtime wall renderer assembles against (before the emitted main)
_RENDERER_INCLUDES = ["fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj"]


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
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False)
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


def build_wall_renderer(wad_path, mapname="E1M1", *, cfg=None, out_fjm, generated_dir,
                        flat_max_words=None) -> dict:
    """M12rr — wire the OPTIMIZED runtime wall renderer into a shipped `.fjm` (replacing the M10 halt-only
    `build_doom` mainline for the renderer path). Emits the renderer via the SHARED
    `doomfj.wall_renderer.emit_wall_renderer` — the SAME emitter the byte-exact golden test renders through
    (R6 single source) — so every space optimization (M12oo pass-2 trampoline, M12pp/qq xor_by + xor-involution
    walk) ships here for free. Assembles against the fixed renderer include set, then R0-gates: assert
    `storage_mode == flat` and `span < limit`. The renderer's fully-unrolled pass-2 + BSP walk push the span
    past the 2**23 default, so pass a RAISED `flat_max_words` (2**26) per DESIGN §1.2 (RAM-only cost). The
    viewpoint `(vx,vy,va)` is read from stdin at runtime; the gate run feeds an invalid byte so the input
    parser jumps to `bad:` and halts immediately (the span/storage_mode are load-time, so no full render is
    needed for the gate — the golden test does the byte-exact render)."""
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    cfg = cfg or Config()
    wad = WadFile.from_path(wad_path)
    limit = flat_max_words or FLAT_MAX_WORDS
    gen = Path(generated_dir); gen.mkdir(parents=True, exist_ok=True)

    main = emit_wall_renderer(wad, mapname, cfg, over_align=False)
    consts = cfg.emit_fj_consts(gen / "fj_consts.fj")
    main_p = gen / "renderer_main.fj"
    main_p.write_text(main, encoding="utf-8")
    paths = [consts] + [_SRC_FJ / f for f in _RENDERER_INCLUDES] + [main_p]

    out = Path(out_fjm); out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False)
    assemble_seconds = round(time.perf_counter() - t, 3)
    term = fj.run(out, io_device=FixedIO(b"q\n"), print_time=False, print_termination=False,
                  flat_max_words=limit)                    # 'q' is not a digit -> input parser -> bad: -> halt
    span = _span_words(out)
    metrics = {
        "map": mapname, "downscale": cfg.TEXTURE_DOWNSCALE,
        "storage_mode": str(term.storage_mode), "span_words": span, "flat_limit": limit,
        "headroom": round(limit / span, 3) if span else None,
        "fjm_bytes": out.stat().st_size, "assemble_seconds": assemble_seconds,
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
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False)

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
                memory_width=W, print_time=False)
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
    fj.assemble([p.resolve() for p in paths], out, memory_width=W, print_time=False)
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
