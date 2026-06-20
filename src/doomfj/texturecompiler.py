"""H4 — texture / colormap / palette compiler (M8). Composites DOOM textures from their patches and
bakes the per-pixel graphics data into the M5 dispatch tables, and completes F3's `sample_texture`.

- `composite_texture` assembles a texture's patches onto its canvas (column-major, transparency-aware)
  -> a width*height grid of palette indices.
- `compile_texture` / `compile_flat` emit a **dispatch table** (texel index -> palette byte, ~4@
  sample, D5) plus a `<label>.sample` idiom. Texels are **column-major** (index = col*height + row) so
  the renderer's per-column base + row add lands on a nibble boundary (U6); flats are 64x64 row-major.
- `compile_colormap` emits the light table as a dispatch table indexed by `(light<<8 | colour)` ->
  lit palette byte, plus `<label>.apply` (the per-pixel colormap apply, D11). Over-align candidate (#3).
- `compile_palette` emits the 256-colour RGB palette as **device data** (not a dispatch LUT, §1.3) —
  the present layer hands it to `set_palette`.

All values come from the WAD (the single source shared with the oracle, R6). flipjump parses `.fj` as
UTF-8; emitted text is ASCII.
"""
from __future__ import annotations

from typing import List, Optional

from doomfj.wad import WadFile, TextureDef, decode_picture
from doomfj.lut_generator import generate_dispatch_table_fj

FLAT_DIM = 64  # DOOM flats are 64x64


def composite_texture(wad: WadFile, tex: TextureDef) -> List[List[Optional[int]]]:
    """Assemble `tex`'s patches onto a height x width grid of palette indices (None = transparent).
    Patches are drawn at their origins; transparent patch pixels do not overwrite (DOOM compositing)."""
    canvas: List[List[Optional[int]]] = [[None] * tex.width for _ in range(tex.height)]
    for pr in tex.patches:
        pic = decode_picture(wad.get_data(pr.patch))
        for cx in range(pic.width):
            tx = pr.originx + cx
            if not 0 <= tx < tex.width:
                continue
            for (cy, value) in pic.columns[cx]:
                ty = pr.originy + cy
                if 0 <= ty < tex.height:
                    canvas[ty][tx] = value
    return canvas


def texture_texels(canvas: List[List[Optional[int]]], *, fill: int = 0) -> List[int]:
    """Flatten a composite to a column-major texel list (index = col*height + row). Transparent texels
    become `fill` (wall textures are fully opaque; the fill only matters for masked/see-through ones)."""
    height = len(canvas)
    width = len(canvas[0]) if height else 0
    return [canvas[row][col] if canvas[row][col] is not None else fill
            for col in range(width) for row in range(height)]


def _index_nibbles(count: int) -> int:
    n, c = 1, 16
    while c < count:
        c *= 16
        n += 1
    return n


def _texel_table(label: str, texels: List[int], mode: str, over_align: bool) -> str:
    idx_n = _index_nibbles(len(texels))
    table = generate_dispatch_table_fj(label, texels, index_nibbles=idx_n, result_nibbles=2,
                                       mode=mode, over_align=over_align)
    # F3 sample_texture: read a texel byte from the table at a precomputed texel index (col*h + row).
    idiom = "\n".join([
        f"// F3 sample_texture for \"{label}\" (texel index -> palette byte; ~4@, D5)",
        f"ns {label} {{",
        "    def sample dst, idx {",
        "        .lookup dst, idx",
        "    }",
        "}",
        "",
    ])
    return table + idiom


def compile_texture(label: str, wad: WadFile, texname: str, *, mode: str = "per_entry",
                    over_align: bool = False) -> str:
    """Composite `texname` and emit its texel dispatch table + `<label>.sample` (F3)."""
    defs = {d.name: d for d in wad.texture_defs()}
    texels = texture_texels(composite_texture(wad, defs[texname]))
    return _texel_table(label, texels, mode, over_align)


def compile_flat(label: str, wad: WadFile, flatname: str, *, mode: str = "per_entry",
                 over_align: bool = False) -> str:
    """Emit a flat (64x64 row-major palette indices) as a texel dispatch table + `<label>.sample`."""
    texels = list(wad.flat(flatname))
    return _texel_table(label, texels, mode, over_align)


def colormap_values(wad: WadFile, *, lights: int = 32) -> List[int]:
    """The light table flattened to index `light*256 + colour` -> lit palette index, for the first
    `lights` light levels (DOOM uses 32; COLORMAP also carries invuln + all-black past those)."""
    cm = wad.colormap()
    return [cm[light][colour] for light in range(lights) for colour in range(256)]


def compile_colormap(label: str, wad: WadFile, *, lights: int = 32, mode: str = "per_entry",
                     over_align: bool = True) -> str:
    """Emit the colormap as a dispatch table indexed by `(light<<8 | colour)` -> lit palette byte,
    plus `<label>.apply` (per-pixel colormap apply, D11). Over-aligned by default (#3, very hot)."""
    values = colormap_values(wad, lights=lights)
    idx_n = _index_nibbles(len(values))
    table = generate_dispatch_table_fj(label, values, index_nibbles=idx_n, result_nibbles=2,
                                       mode=mode, over_align=over_align)
    idiom = "\n".join([
        f"// F3 apply_colormap for \"{label}\" (index = light<<8 | colour -> lit byte; D11)",
        f"ns {label} {{",
        "    def apply dst, idx {",
        "        .lookup dst, idx",
        "    }",
        "}",
        "",
    ])
    return table + idiom


def compile_palette(label: str, wad: WadFile, *, index: int = 0) -> str:
    """Emit the 256-colour RGB palette as device data (R,G,B bytes per colour) — read by the present
    layer's set_palette, not a dispatch LUT (§1.3)."""
    pal = wad.playpal(index)
    lines = [f'// palette "{label}": 256 RGB colours, device data (doomfj.texturecompiler)',
             f"{label}:"]
    for (r, g, b) in pal:
        lines.append(f"    ;{hex(r)} * dw")
        lines.append(f"    ;{hex(g)} * dw")
        lines.append(f"    ;{hex(b)} * dw")
    return "\n".join(lines) + "\n"
