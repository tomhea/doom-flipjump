"""M8 integration evidence (R2) + E1M1 texture-span measurement (OQ8/R-3 → §1.2).

Runs on the dev Freedoom WAD (gitignored), so the numbers are recorded into the committed artifact /
integration doc, not a CI test. Measures the texel footprint of the textures + flats E1M1 actually
references (the dispatch-table span is ~1 entry/texel, the §1.3 "textures ≈ 93% of LUT span" line).
Plus a small assemble check that a compiled texture/colormap runs flat (R4).

Usage: `bash scripts/fetch_freedoom.sh && python scripts/m8_evidence.py`.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.wad import WadFile
from doomfj.texturecompiler import compile_texture, composite_texture, texture_texels

FREEDOOM = Path("assets/freedoom1.wad")
LEVEL = "E1M1"


def main() -> dict:
    wad = WadFile.from_path(FREEDOOM)
    defs = {d.name: d for d in wad.texture_defs()}

    # wall textures referenced by E1M1's sidedefs
    used_tex = set()
    for s in wad.sidedefs(LEVEL):
        for t in (s.upper, s.lower, s.middle):
            if t and t != "-" and t in defs:
                used_tex.add(t)
    # flats referenced by E1M1's sectors
    flat_names = {f.name for f in wad.lumps_between("F_START", "F_END")}
    used_flat = set()
    for sec in wad.sectors(LEVEL):
        for f in (sec.floor_tex, sec.ceil_tex):
            if f in flat_names:
                used_flat.add(f)

    tex_texels = sum(defs[t].width * defs[t].height for t in used_tex)
    flat_texels = len(used_flat) * 64 * 64
    total = tex_texels + flat_texels

    # one compiled texture runs flat (R4)
    src = compile_texture("t", wad, sorted(used_tex)[0]) if used_tex else compile_texture("t", wad, "STEP4")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.fj"
        p.write_text("stl.startup_and_init_all\nstl.loop\n" + src + "\n", encoding="utf-8")
        out = Path(d) / "t.fjm"
        fj.assemble([p.resolve()], out, memory_width=W, print_time=False)
        term = fj.run(out, print_time=False, print_termination=False)

    metrics = {
        "level": LEVEL,
        "wall_textures_used": len(used_tex),
        "flats_used": len(used_flat),
        "wall_texel_count": tex_texels,
        "flat_texel_count": flat_texels,
        "total_texture_texels": total,
        "note": "1 dispatch entry per texel (byte result); the §1.3 textures-dominate-LUT-span line. "
                "Compare against the ~300K design estimate; downscale is the span lever if over budget.",
        "compiled_texture_storage_mode": str(term.storage_mode),
    }
    Path("build").mkdir(exist_ok=True)
    Path("build/m8-metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
