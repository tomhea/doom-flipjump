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


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
