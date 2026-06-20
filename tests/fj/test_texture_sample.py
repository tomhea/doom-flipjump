"""M8 (H4) — sample_texture / apply_colormap read the compiled graphics dispatch tables byte-exact on
the real engine. Texels/colormap values come from the trimmed-Freedoom fixture (R6 SSOT). The dispatch
mechanism itself is proven every-entry+call-twice in M5; here we prove the compiled VALUES are right."""
from pathlib import Path

import flipjump as fj

from doomfj.harness import W
from doomfj.wad import WadFile
from doomfj.texturecompiler import (
    colormap_values,
    compile_colormap,
    compile_flat,
    compile_texture,
    composite_texture,
    texture_texels,
)

FIXTURE = Path("tests/fixtures/freedoom_assets.wad")


def _run(tmp_path, name, body, tables, expected: bytes):
    prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(tables) + "\n")
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output([p.resolve()], b"", expected, memory_width=W,
                                         warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj output != expected"


def _walk_reads(call, values, *, twice):
    """Body that sets idx=0 then, for each value, reads `call r, idx` (twice if asked) and idx+=1.
    Reads therefore see indices 0,1,2,... in order — expected[i] = values[i]."""
    body = ["hex.set 2, idx, 0"]
    expected = b""
    for v in values:
        for _ in range(2 if twice else 1):
            body += [f"{call} r, idx", "hex.print_as_digit 2, r, 0", "stl.output 10"]
            expected += f"{v:02x}\n".encode()
        body += ["hex.add_constant 2, idx, 1"]
    return body, expected


def test_sample_texture_byte_exact(tmp_path):
    # A-YELLOW (16x8 = 128 texels): sample EVERY texel TWICE (#8), byte-exact vs the composite
    wad = WadFile.from_path(FIXTURE)
    texels = texture_texels(composite_texture(wad, {d.name: d for d in wad.texture_defs()}["A-YELLOW"]))
    body, expected = _walk_reads("tex.sample", texels, twice=True)
    _run(tmp_path, "sample_texture", body,
         [compile_texture("tex", wad, "A-YELLOW"), "idx: hex.vec 2", "r: hex.vec 2"], expected)


def test_sample_flat_byte_exact(tmp_path):
    # CEIL1_2 (64x64 = 4096 texels): sample a spread of texels byte-exact (every-entry is proven in M5)
    wad = WadFile.from_path(FIXTURE)
    flat = list(wad.flat("CEIL1_2"))
    picks = [0, 1, 63, 64, 100, 1000, 2048, 4095]
    body, data = [], []
    for k, i in enumerate(picks):
        for _ in range(2):
            body += [f"flt.sample r, a{k}", "hex.print_as_digit 2, r, 0", "stl.output 10"]
        data.append(f"a{k}: hex.vec 3, {i}")
    data.append("r: hex.vec 2")
    expected = "".join(f"{flat[i]:02x}\n{flat[i]:02x}\n" for i in picks).encode()
    _run(tmp_path, "sample_flat", body, [compile_flat("flt", wad, "CEIL1_2")] + data, expected)


def test_apply_colormap_byte_exact(tmp_path):
    # colormap (lights=2 for a fast assemble): apply (light<<8 | colour) -> lit byte, byte-exact
    wad = WadFile.from_path(FIXTURE)
    values = colormap_values(wad, lights=2)
    picks = [(0, 0), (0, 1), (0, 255), (1, 0), (1, 7), (1, 100), (1, 255), (0, 128)]
    body, data = [], []
    for k, (light, colour) in enumerate(picks):
        idx = (light << 8) | colour
        for _ in range(2):
            body += [f"cm.apply r, a{k}", "hex.print_as_digit 2, r, 0", "stl.output 10"]
        data.append(f"a{k}: hex.vec 3, {idx}")
    data.append("r: hex.vec 2")
    expected = "".join(f"{values[(l << 8 | c)]:02x}\n{values[(l << 8 | c)]:02x}\n"
                       for (l, c) in picks).encode()
    _run(tmp_path, "apply_colormap", body,
         [compile_colormap("cm", wad, lights=2, over_align=False)] + data, expected)
